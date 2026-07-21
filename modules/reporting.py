"""
reporting.py
------------
Builds the downloadable PDF "Executive Report" as a fixed-layout document
(CR-09):

    Page 1            Executive Overview + KPI Summary
    Page 2            Case Duration Distribution
    Page 3            Heuristics Miner
    Page 4            Lead Time: Rework vs Non-Rework
    Page 5            Bubble Chart: Duration vs Rework + Main Bottleneck
    Page 6 (cond.)    Role Analysis          -- only if the source log had a 'Role' column
    Page 7 (cond.)    Regional Analysis      -- only if the source log had a 'Region' column
    Final Page        Executive Summary + Recommendations

Reusing figures (CR-01)
-------------------------
Every chart embedded below is pulled from `result.figures` -- the SAME
Plotly/Matplotlib/Graphviz objects already built once by `app.py`'s
render_* functions to draw the Streamlit UI. The PDF never calls
`visualizations.py` a second time to reconstruct a chart it can already
reuse; it only falls back to rebuilding from `result.statistics` /
`result.case_times` in the (should-be-rare) case a figure is missing from
`result.figures`, so the report can still degrade gracefully instead of
silently omitting a whole page.

Kaleido / Graphviz fixes (CR-01.1/1.2/1.3)
---------------------------------------------
The previous "chart unavailable" placeholders had two root causes, both
fixed at the dependency level rather than papered over here:
    1. `kaleido` was unpinned in requirements.txt. kaleido>=1.0 changed its
       Plotly integration to require a separate Chrome download step that
       is never triggered automatically, so `fig.to_image(...)` silently
       fails. Pinned to `kaleido==0.2.1`, which bundles its own static
       binary and works synchronously out of the box.
    2. The system `dot` executable (needed by `Digraph.pipe(...)`, NOT by
       Streamlit's `st.graphviz_chart` which renders client-side) usually
       isn't present on a fresh Streamlit Cloud image. Added `packages.txt`
       with `graphviz` so it gets apt-installed at deploy time.
Both `_plotly_to_png` and `_graphviz_to_png` also now log the underlying
exception (via `logging`) instead of swallowing it silently, so a genuine
remaining failure is visible in the Streamlit Cloud logs instead of just
showing up as an empty page.

Font fix (Sec. 2.5 of the original refactor requirements)
-----------------------------------------------------------
Cyrillic text can't use ReportLab's built-in Helvetica/Times base fonts.
matplotlib already ships a full copy of DejaVu Sans (regular + bold) inside
its own installed package data, and matplotlib is already a hard dependency
of this app, so that bundled font is resolved via `matplotlib.get_data_path()`
at runtime -- no extra font file needs to live in the repo.
"""

import logging
import os
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional

import matplotlib
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from modules.config import AUTHOR_LINKEDIN, AUTHOR_NAME, PDF_FONT_NAME

logger = logging.getLogger(__name__)

FONT_REGULAR = PDF_FONT_NAME
FONT_BOLD = f"{PDF_FONT_NAME}-Bold"


# ---------------------------------------------------------------------------
# Font registration (no local TTF file required -- see module docstring)
# ---------------------------------------------------------------------------
def _register_fonts() -> None:
    if FONT_REGULAR in pdfmetrics.getRegisteredFontNames():
        return  # already registered in this process

    mpl_font_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    regular_path = os.path.join(mpl_font_dir, "DejaVuSans.ttf")
    bold_path = os.path.join(mpl_font_dir, "DejaVuSans-Bold.ttf")

    pdfmetrics.registerFont(TTFont(FONT_REGULAR, regular_path))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path))
    pdfmetrics.registerFontFamily(
        FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD, italic=FONT_REGULAR, boldItalic=FONT_BOLD
    )


# ---------------------------------------------------------------------------
# Figure -> PNG bytes helpers
# ---------------------------------------------------------------------------
def _plotly_to_png(fig) -> Optional[bytes]:
    if fig is None:
        return None
    try:
        return fig.to_image(format="png", scale=2)
    except Exception as e:
        logger.warning("Plotly -> PNG export failed (check kaleido install): %s", e)
        return None


def _matplotlib_to_png(fig) -> Optional[bytes]:
    if fig is None:
        return None
    try:
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning("Matplotlib -> PNG export failed: %s", e)
        return None


def _graphviz_to_png(dot) -> Optional[bytes]:
    if dot is None:
        return None
    try:
        return dot.pipe(format="png")
    except Exception as e:
        logger.warning(
            "Graphviz -> PNG export failed (is the system 'dot' binary installed? "
            "see packages.txt): %s", e,
        )
        return None


def _image_flowable(png_bytes: Optional[bytes], max_width_cm: float = 16) -> Optional[Image]:
    if not png_bytes:
        return None
    from PIL import Image as PILImage

    pil_img = PILImage.open(BytesIO(png_bytes))
    width_px, height_px = pil_img.size
    aspect = height_px / width_px if width_px else 1
    width = max_width_cm * cm
    height = width * aspect
    return Image(BytesIO(png_bytes), width=width, height=height)


def _figure_from_result(result, section_key: str, sub_key: Optional[str] = None):
    """
    CR-01: pull an already-built figure object out of `result.figures`
    (populated once by app.py's render_* functions) instead of asking
    `visualizations.py` to rebuild it for the PDF.
    """
    section = (result.figures or {}).get(section_key)
    if not section:
        return None
    if sub_key:
        return (section.get("figures") or {}).get(sub_key)
    return section.get("figure")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _build_styles() -> Dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "Title", fontName=FONT_BOLD, fontSize=24, leading=30,
            textColor=colors.HexColor("#1F2937"), alignment=TA_CENTER, spaceAfter=10,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub", fontName=FONT_REGULAR, fontSize=13, leading=18,
            textColor=colors.HexColor("#4B5563"), alignment=TA_CENTER, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", fontName=FONT_BOLD, fontSize=15, leading=19,
            textColor=colors.HexColor("#111827"), spaceBefore=14, spaceAfter=8,
        ),
        "chart_caption": ParagraphStyle(
            "ChartCaption", fontName=FONT_BOLD, fontSize=11, leading=14,
            textColor=colors.HexColor("#111827"), spaceBefore=10, spaceAfter=6,
        ),
        "base": ParagraphStyle(
            "Base", fontName=FONT_REGULAR, fontSize=10.5, leading=15,
            textColor=colors.black, spaceAfter=8,
        ),
        "bottleneck_box": ParagraphStyle(
            "BottleneckBox", fontName=FONT_REGULAR, fontSize=10.5, leading=15,
            textColor=colors.HexColor("#7F1D1D"), spaceAfter=8, backColor=colors.HexColor("#FEF2F2"),
            borderPadding=8,
        ),
        "insight": ParagraphStyle(
            "Insight", fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=colors.HexColor("#1F2937"), spaceAfter=4, leftIndent=10,
        ),
    }


def _unavailable(elements: list, styles: dict, label: str = "Графік недоступний для відображення.") -> None:
    elements.append(Paragraph(label, styles["base"]))


# ---------------------------------------------------------------------------
# Page 1: Executive Overview + KPI Summary (CR-09, CR-05 FTE row)
# ---------------------------------------------------------------------------
def _build_cover_page(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    elements.append(Spacer(1, 1.5 * cm))
    elements.append(Paragraph("Process Mining", styles["title"]))
    elements.append(Paragraph("Executive Report", styles["title"]))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(
        Paragraph(f"Дата формування: {datetime.now().strftime('%d.%m.%Y')}", styles["cover_sub"])
    )
    elements.append(Spacer(1, 0.8 * cm))
    elements.append(Paragraph(AUTHOR_NAME, styles["cover_sub"]))
    elements.append(
        Paragraph(f'<link href="{AUTHOR_LINKEDIN}">{AUTHOR_LINKEDIN}</link>', styles["cover_sub"])
    )
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Executive Overview", styles["subtitle"]))
    start = kpis.get("start_period")
    end = kpis.get("end_period")
    period_str = f"{start.date()} → {end.date()}" if pd.notna(start) and pd.notna(end) else "—"
    elements.append(
        Paragraph(
            f"Цей звіт узагальнює результати аналізу процесу за {kpis.get('num_cases', 0)} "
            f"кейсами в період {period_str}. Нижче наведено ключові показники, "
            "візуалізації та автоматично згенеровані рекомендації.",
            styles["base"],
        )
    )
    elements.append(Spacer(1, 8))


def _build_kpi_summary(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    """
    KPI Summary: Number of Cases, Analysis Period, Average Case Duration,
    Median Case Duration, and (CR-05, when a 'Role' column was present)
    Average FTE per Case.
    """
    elements.append(Paragraph("KPI Summary", styles["subtitle"]))

    start = kpis.get("start_period")
    end = kpis.get("end_period")
    period_str = (
        f"{start.date()} → {end.date()}" if pd.notna(start) and pd.notna(end) else "—"
    )

    rows = [
        ["Показник", "Значення"],
        ["Кількість кейсів (Number of Cases)", f"{kpis.get('num_cases', 0)}"],
        ["Період аналізу (Analysis Period)", period_str],
        ["Середня тривалість кейсу (Average Case Duration)", f"{kpis.get('avg_case_duration', 0):.2f} год"],
        ["Медіанна тривалість кейсу (Median Case Duration)", f"{kpis.get('median_case_duration', 0):.2f} год"],
    ]

    avg_fte = kpis.get("avg_fte_per_case")
    if avg_fte is not None:
        rows.append(["Середня к-сть ролей на кейс (Average FTE per Case)", f"{avg_fte:.2f}"])

    table = Table(rows, colWidths=[10.5 * cm, 5.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 12))


# ---------------------------------------------------------------------------
# Page 2: Case Duration Distribution (CR-01.1)
# ---------------------------------------------------------------------------
def _build_case_duration_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Case Duration Distribution (Histogram)", styles["subtitle"]))

    fig = _figure_from_result(result, "general_statistics")
    if fig is None:
        try:
            fig = visualizations.case_duration_histogram(result.case_times)
        except Exception as e:
            logger.warning("Histogram rebuild failed: %s", e)

    img = _image_flowable(_plotly_to_png(fig))
    if img is not None:
        elements.append(img)
    else:
        _unavailable(elements, styles)


# ---------------------------------------------------------------------------
# Page 3: Heuristics Miner (CR-01.2)
# ---------------------------------------------------------------------------
def _build_heuristics_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Heuristics Miner (Custom Graphviz)", styles["subtitle"]))

    dot = _figure_from_result(result, "heuristics")
    if dot is None:
        transitions = result.transitions or {}
        try:
            dot = visualizations.heuristics_graph(transitions["edges"], transitions["bottleneck_text"])
        except Exception as e:
            logger.warning("Heuristics graph rebuild failed: %s", e)
            dot = None

    img = _image_flowable(_graphviz_to_png(dot))
    if img is not None:
        elements.append(img)
    else:
        _unavailable(elements, styles, "Граф переходів недоступний для відображення.")


# ---------------------------------------------------------------------------
# Page 4: Lead Time vs Rework (CR-01.1 -- reuses the matplotlib figure)
# ---------------------------------------------------------------------------
def _build_lead_time_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Lead Time: Rework vs Non-Rework", styles["subtitle"]))

    lead_time = result.statistics.get("lead_time", {})
    rework = result.statistics.get("rework", {})

    fig = _figure_from_result(result, "lead_time")
    if fig is None:
        try:
            fig = visualizations.lead_time_boxplot(lead_time["lead_time_per_case"])
        except Exception as e:
            logger.warning("Lead time boxplot rebuild failed: %s", e)
            fig = None

    img = _image_flowable(_matplotlib_to_png(fig), max_width_cm=13)
    if img is not None:
        elements.append(img)
    else:
        _unavailable(elements, styles)

    elements.append(Spacer(1, 10))

    total_rework_cases = rework.get("total_rework_cases", 0)
    percent_rework = rework.get("percent_rework", 0)
    mean_lead_rework = lead_time.get("mean_lead_rework", 0) or 0
    mean_lead_no_rework = lead_time.get("mean_lead_no_rework", 0) or 0
    lead_diff = mean_lead_rework - mean_lead_no_rework

    explanation = (
        f"<b>Кейсів з повторюваними кроками (rework):</b> {total_rework_cases} "
        f"({percent_rework}% від загальної кількості кейсів).<br/><br/>"
        f"Середній Lead Time для кейсів з rework становить {mean_lead_rework:.2f} год, "
        f"проти {mean_lead_no_rework:.2f} год для кейсів без повторень — "
        f"різниця {lead_diff:+.2f} год.<br/><br/>"
    )
    if lead_diff > 0:
        explanation += (
            "Це підтверджує, що повторювані кроки (rework) суттєво подовжують "
            "виконання кейсу: чим більше повторів активностей, тим довше кейс "
            "залишається у процесі."
        )
    else:
        explanation += (
            "У цій вибірці rework не призводить до помітного збільшення Lead Time, "
            "однак варто продовжити моніторинг цього показника."
        )

    elements.append(Paragraph(explanation, styles["base"]))


# ---------------------------------------------------------------------------
# Page 5: Bubble Chart + bottleneck conclusion (CR-01.3)
# ---------------------------------------------------------------------------
def _build_bubble_chart_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(
        Paragraph("Bubble Chart: Duration per Step vs Rework Count", styles["subtitle"])
    )

    step_analysis = result.statistics.get("step_analysis", {})

    fig = _figure_from_result(result, "step_analysis")
    if fig is None:
        try:
            fig = visualizations.step_bubble_chart(
                step_analysis["analysis_df"], step_analysis["x_mean"], step_analysis["y_mean"]
            )
        except Exception as e:
            logger.warning("Bubble chart rebuild failed: %s", e)
            fig = None

    img = _image_flowable(_plotly_to_png(fig))
    if img is not None:
        elements.append(img)
    else:
        _unavailable(elements, styles)

    elements.append(Spacer(1, 10))

    top_step = step_analysis.get("top_step")
    if top_step is not None:
        bottleneck_text = (
            "<b>🔴 Main Potential Bottleneck</b><br/><br/>"
            f"<b>Activity:</b> {top_step['Activity Name']}<br/>"
            f"<b>Average Duration:</b> {top_step['avg_duration']:.2f} год<br/>"
            f"<b>Rework Count (середня к-сть повторів):</b> {top_step['avg_count']:.2f}<br/><br/>"
            f"<b>Recommendation:</b> крок «{top_step['Activity Name']}» перевищує середні "
            "значення і за тривалістю, і за кількістю повторів — розгляньте його "
            "автоматизацію, спрощення процедури або усунення зайвих погоджень."
        )
    else:
        bottleneck_text = (
            "<b>🔴 Main Potential Bottleneck</b><br/><br/>"
            "Явно виражених bottleneck'ів (кроків, що перевищують середні значення "
            "одночасно за тривалістю і кількістю повторів) не виявлено."
        )

    elements.append(Paragraph(bottleneck_text, styles["bottleneck_box"]))


# ---------------------------------------------------------------------------
# Page 6 (conditional): Role Analysis (CR-05)
# ---------------------------------------------------------------------------
def _build_role_analysis_page(elements: list, styles: dict, result) -> None:
    role = result.role_analysis
    if role is None:
        return

    elements.append(Paragraph("Role Analysis", styles["subtitle"]))
    elements.append(
        Paragraph(
            f"Середня кількість ролей на кейс (Average FTE per Case): "
            f"<b>{role['avg_roles_per_case']:.2f}</b>",
            styles["base"],
        )
    )

    for caption, sub_key in [
        ("Role vs Activity Matrix", "matrix"),
        ("Role Workload Distribution", "workload"),
        ("Role Bottleneck Ranking", "bottleneck"),
    ]:
        fig = _figure_from_result(result, "role_analysis", sub_key)
        img = _image_flowable(_plotly_to_png(fig), max_width_cm=15)
        if img is not None:
            elements.append(Paragraph(caption, styles["chart_caption"]))
            elements.append(img)
            elements.append(Spacer(1, 8))

    if role.get("top_bottleneck_role"):
        elements.append(
            Paragraph(
                f"🚧 Роль з найбільшою участю у bottleneck-активностях: "
                f"<b>{role['top_bottleneck_role']}</b>",
                styles["insight"],
            )
        )
    if role.get("top_rework_role"):
        elements.append(
            Paragraph(
                f"🔁 Роль з найвищою частотою rework: <b>{role['top_rework_role']}</b>",
                styles["insight"],
            )
        )


# ---------------------------------------------------------------------------
# Page 7 (conditional): Regional Analysis (CR-06)
# ---------------------------------------------------------------------------
def _build_region_analysis_page(elements: list, styles: dict, result) -> None:
    region = result.region_analysis
    if region is None:
        return

    elements.append(Paragraph("Regional Analysis", styles["subtitle"]))

    for caption, sub_key in [
        ("Lead Time by Region", "lead_time"),
        ("Rework by Region", "rework"),
        ("Regional Performance Matrix", "matrix"),
    ]:
        fig = _figure_from_result(result, "region_analysis", sub_key)
        img = _image_flowable(_plotly_to_png(fig), max_width_cm=15)
        if img is not None:
            elements.append(Paragraph(caption, styles["chart_caption"]))
            elements.append(img)
            elements.append(Spacer(1, 8))

    if region.get("leader") is not None:
        elements.append(
            Paragraph(
                f"🏆 Найкращий регіон: <b>{region['leader']['Region']}</b> "
                f"(Lead Time = {region['leader']['avg_lead_time']:.2f} год)",
                styles["insight"],
            )
        )
    if region.get("outsider") is not None:
        elements.append(
            Paragraph(
                f"⚠️ Регіон, що потребує уваги: <b>{region['outsider']['Region']}</b> "
                f"(Lead Time = {region['outsider']['avg_lead_time']:.2f} год)",
                styles["insight"],
            )
        )

    if region.get("insights"):
        elements.append(Paragraph("Automated Insights", styles["chart_caption"]))
        for insight in region["insights"]:
            elements.append(Paragraph(f"• {insight}", styles["insight"]))

    if region.get("recommendations"):
        elements.append(Paragraph("Recommendations", styles["chart_caption"]))
        for rec in region["recommendations"]:
            elements.append(Paragraph(f"• {rec}", styles["insight"]))


# ---------------------------------------------------------------------------
# Final page: Executive Summary (unchanged content/order of sections)
# ---------------------------------------------------------------------------
def _build_executive_summary_section(
    elements: list, styles: dict, summary_text: str, recommendations: str, maturity_score: int
) -> None:
    elements.append(Paragraph("Executive Summary", styles["subtitle"]))
    elements.append(Paragraph(summary_text.replace("\n", "<br/>"), styles["base"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Рекомендації", styles["subtitle"]))
    elements.append(Paragraph(recommendations.replace("\n", "<br/>"), styles["base"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Process Maturity Score", styles["subtitle"]))
    maturity_text = (
        "Process Maturity Score — це інтегральний показник зрілості процесу (шкала 0–100). "
        "Він враховує рівень повторних кроків (rework), варіативність сценаріїв, "
        "наявність bottleneck'ів та стабільність виконання процесу.<br/><br/>"
        f"<b>Поточне значення індексу: {maturity_score}/100.</b>"
    )
    elements.append(Paragraph(maturity_text, styles["base"]))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_pdf_report(result) -> BytesIO:
    """
    Build and return an in-memory PDF buffer for the executive report
    (CR-09 layout):

        Page 1            Executive Overview + KPI Summary
        Page 2            Case Duration Distribution
        Page 3            Heuristics Miner
        Page 4            Lead Time: Rework vs Non-Rework
        Page 5            Bubble Chart + Main Bottleneck Conclusion
        Page 6 (cond.)    Role Analysis      -- only if 'Role' column existed
        Page 7 (cond.)    Regional Analysis  -- only if 'Region' column existed
        Final Page        Executive Summary + Recommendations

    `result` is an `AnalysisResult` (modules.models.AnalysisResult) -- the
    same object used to render the Streamlit UI. Every chart embedded here
    is pulled from `result.figures` (built once by app.py) rather than
    rebuilt, per CR-01's "ensure figure object is passed into
    AnalysisResult.figures" requirement.
    """
    from modules import visualizations  # local import avoids a hard dependency

    _register_fonts()
    styles = _build_styles()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=50, bottomMargin=40,
    )
    elements: list = []

    kpis = result.kpis()

    # ---- Page 1: Executive Overview + KPI Summary ----
    _build_cover_page(elements, styles, kpis)
    _build_kpi_summary(elements, styles, kpis)
    elements.append(PageBreak())

    # ---- Page 2: Case Duration Distribution ----
    _build_case_duration_page(elements, styles, visualizations, result)
    elements.append(PageBreak())

    # ---- Page 3: Heuristics Miner ----
    _build_heuristics_page(elements, styles, visualizations, result)
    elements.append(PageBreak())

    # ---- Page 4: Lead Time vs Rework ----
    _build_lead_time_page(elements, styles, visualizations, result)
    elements.append(PageBreak())

    # ---- Page 5: Bubble Chart + bottleneck conclusion ----
    _build_bubble_chart_page(elements, styles, visualizations, result)

    # ---- Page 6 (conditional): Role Analysis ----
    if result.role_analysis is not None:
        elements.append(PageBreak())
        _build_role_analysis_page(elements, styles, result)

    # ---- Page 7 (conditional): Regional Analysis ----
    if result.region_analysis is not None:
        elements.append(PageBreak())
        _build_region_analysis_page(elements, styles, result)

    # ---- Final Page: Executive Summary ----
    elements.append(PageBreak())
    exec_summary = result.executive_summary or {}
    _build_executive_summary_section(
        elements,
        styles,
        exec_summary.get("summary_text", ""),
        exec_summary.get("recommendations", ""),
        result.maturity_score,
    )

    doc.build(elements)
    buffer.seek(0)
    return buffer

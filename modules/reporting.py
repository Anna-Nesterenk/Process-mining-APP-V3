"""
reporting.py
------------
Builds the downloadable PDF "Executive Report" as a fixed 6-page document
(per the Executive Report & Visualization Improvements spec, CR-01..CR-08):

    Page 1: Cover + KPI Summary
    Page 2: Case Duration Distribution (Histogram)
    Page 3: Heuristics Miner (Custom Graphviz)
    Page 4: Lead Time: Rework vs Non-Rework (chart + explanation)
    Page 5: Bubble Chart: Duration per Step vs Rework Count (+ bottleneck conclusion)
    Page 6: Executive Summary (unchanged content: summary, recommendations, maturity score)

Risk Heatmap is intentionally NOT built or embedded here (CR-06) -- it stays
a Streamlit-only visualization.

Every chart on every page is built by calling the SAME `visualizations.py`
functions used to render the Streamlit UI (reusing `result.case_times`,
`result.statistics`, `result.transitions`), so nothing is recalculated for
the PDF -- it always matches what the user saw on screen.

Font fix (Sec. 2.5 of the original refactor requirements)
-----------------------------------------------------------
Cyrillic text can't use ReportLab's built-in Helvetica/Times base fonts, and
bundling a TTF file with the repo previously went wrong (file never
committed -> crash on Streamlit Cloud). matplotlib already ships a full copy
of DejaVu Sans (regular + bold) inside its own installed package data, and
matplotlib is already a hard dependency of this app, so that bundled font is
resolved via `matplotlib.get_data_path()` at runtime instead -- no extra
font file needs to live in the repo.

Chart embedding
-----------------
Plotly figures are rasterized to PNG via `fig.to_image(...)` (kaleido
backend -- see requirements.txt). Matplotlib figures are rasterized via
`fig.savefig(...)`. Graphviz Digraphs are rendered via `dot.pipe(...)`; if
the `dot` binary isn't available in a given environment, that one chart is
skipped rather than failing the whole report.
"""

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
    try:
        return fig.to_image(format="png", scale=2)
    except Exception:
        return None


def _matplotlib_to_png(fig) -> Optional[bytes]:
    try:
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _graphviz_to_png(dot) -> Optional[bytes]:
    try:
        return dot.pipe(format="png")
    except Exception:
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
    }


# ---------------------------------------------------------------------------
# Page 1: Cover + KPI Summary (CR-02)
# ---------------------------------------------------------------------------
def _build_cover_page(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    elements.append(Spacer(1, 2 * cm))
    elements.append(Paragraph("Process Mining", styles["title"]))
    elements.append(Paragraph("Executive Report", styles["title"]))
    elements.append(Spacer(1, 0.6 * cm))
    elements.append(
        Paragraph(f"Дата формування: {datetime.now().strftime('%d.%m.%Y')}", styles["cover_sub"])
    )
    elements.append(Spacer(1, 1 * cm))
    elements.append(Paragraph(AUTHOR_NAME, styles["cover_sub"]))
    elements.append(
        Paragraph(f'<link href="{AUTHOR_LINKEDIN}">{AUTHOR_LINKEDIN}</link>', styles["cover_sub"])
    )
    elements.append(Spacer(1, 1.2 * cm))


def _build_kpi_summary(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    """
    CR-02: KPI Summary now contains ONLY:
        Number of Cases, Analysis Period, Average Case Duration, Median Case Duration
    (Average Lead Time and Number of Activities have been removed.)
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
# Page 2: Case Duration Distribution (CR-03)
# ---------------------------------------------------------------------------
def _build_case_duration_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Case Duration Distribution (Histogram)", styles["subtitle"]))
    try:
        fig = visualizations.case_duration_histogram(result.case_times)
        img = _image_flowable(_plotly_to_png(fig))
        if img is not None:
            elements.append(img)
        else:
            elements.append(Paragraph("Графік недоступний для відображення.", styles["base"]))
    except Exception:
        elements.append(Paragraph("Графік недоступний для відображення.", styles["base"]))


# ---------------------------------------------------------------------------
# Page 3: Heuristics Miner (CR-04)
# ---------------------------------------------------------------------------
def _build_heuristics_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Heuristics Miner (Custom Graphviz)", styles["subtitle"]))
    transitions = result.transitions or {}
    try:
        dot = visualizations.heuristics_graph(transitions["edges"], transitions["bottleneck_text"])
        img = _image_flowable(_graphviz_to_png(dot))
        if img is not None:
            elements.append(img)
        else:
            elements.append(Paragraph("Граф переходів недоступний для відображення.", styles["base"]))
    except Exception:
        elements.append(Paragraph("Граф переходів недоступний для відображення.", styles["base"]))


# ---------------------------------------------------------------------------
# Page 4: Lead Time vs Rework (CR-05)
# ---------------------------------------------------------------------------
def _build_lead_time_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(Paragraph("Lead Time: Rework vs Non-Rework", styles["subtitle"]))

    lead_time = result.statistics.get("lead_time", {})
    rework = result.statistics.get("rework", {})

    try:
        fig = visualizations.lead_time_boxplot(lead_time["lead_time_per_case"])
        img = _image_flowable(_matplotlib_to_png(fig), max_width_cm=13)
        if img is not None:
            elements.append(img)
    except Exception:
        elements.append(Paragraph("Графік недоступний для відображення.", styles["base"]))

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
# Page 5: Bubble Chart + bottleneck conclusion (CR-07)
# ---------------------------------------------------------------------------
def _build_bubble_chart_page(elements: list, styles: dict, visualizations, result) -> None:
    elements.append(
        Paragraph("Bubble Chart: Duration per Step vs Rework Count", styles["subtitle"])
    )

    step_analysis = result.statistics.get("step_analysis", {})

    try:
        fig = visualizations.step_bubble_chart(
            step_analysis["analysis_df"], step_analysis["x_mean"], step_analysis["y_mean"]
        )
        img = _image_flowable(_plotly_to_png(fig))
        if img is not None:
            elements.append(img)
    except Exception:
        elements.append(Paragraph("Графік недоступний для відображення.", styles["base"]))

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
# Page 6: Executive Summary (CR-08 -- unchanged content, just re-numbered)
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
    Build and return an in-memory PDF buffer for the 6-page executive report:

        Page 1: Cover + KPI Summary
        Page 2: Case Duration Distribution (Histogram)
        Page 3: Heuristics Miner (Custom Graphviz)
        Page 4: Lead Time: Rework vs Non-Rework
        Page 5: Bubble Chart: Duration per Step vs Rework Count
        Page 6: Executive Summary

    `result` is an `AnalysisResult` (modules.models.AnalysisResult) -- the
    same object used to render the Streamlit UI -- so every chart embedded
    here is built by calling the exact same `visualizations.py` functions
    the UI uses, from the exact same centralized data. No calculation is
    ever repeated for the sake of the PDF.
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

    # ---- Page 1: Cover + KPI Summary ----
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
    elements.append(PageBreak())

    # ---- Page 6: Executive Summary (unchanged content) ----
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

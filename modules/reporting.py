"""
reporting.py
------------
Builds the downloadable PDF "Executive Report".

Layout (Req 1, this round)
-----------------------------
Content flows sequentially -- Case Duration Distribution, Lead Time, Bubble
Chart, and the conditional Role/Region Analysis sections are placed one
after another without being forced onto separate pages, so the report uses
page space efficiently instead of leaving large empty areas (Rule 1/2).
Section headings are kept together with their first chart/table via
ReportLab's `KeepTogether` so a heading is never left orphaned alone at the
bottom of a page (Rule 3/4). The one exception is Heuristics Miner, which
gets a dedicated LANDSCAPE page (`NextPageTemplate` switch between the
'Portrait'/'Landscape' page templates registered on the `BaseDocTemplate`)
so the process graph can use the maximum available page area regardless of
how many nodes/edges it has. See `generate_pdf_report`'s docstring for the
full page sequence.

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

Quantified Expected Impact (Req 2, this round)
--------------------------------------------------
Every Improvement Roadmap initiative's `expected_impact` field is a
structured dict (metric/current/target/improvement/unit/confidence/
calculation_method) computed once in `analytics.build_improvement_roadmap`
-- this module only renders it, never recalculates it (Sec 19/20 SSOT).
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
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from modules.config import AUTHOR_LINKEDIN, AUTHOR_NAME, PDF_FONT_NAME, TIME_METHODOLOGY_TEXT, TIME_METHODOLOGY_TITLE

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


def _image_flowable_fit(png_bytes: Optional[bytes], max_width: float, max_height: float) -> Optional[Image]:
    """
    Req 1.2: fit an image into a `max_width` x `max_height` box (points),
    scaling proportionally so the aspect ratio is always preserved -- fill
    whichever dimension is the binding constraint, never stretch/distort.
    Used for the full-page landscape Heuristics Miner graph.
    """
    if not png_bytes:
        return None
    from PIL import Image as PILImage

    pil_img = PILImage.open(BytesIO(png_bytes))
    width_px, height_px = pil_img.size
    if not width_px or not height_px:
        return None
    aspect = height_px / width_px

    width = max_width
    height = width * aspect
    if height > max_height:
        height = max_height
        width = height / aspect
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
        "table_cell": ParagraphStyle(
            "TableCell", fontName=FONT_REGULAR, fontSize=9, leading=12,
            textColor=colors.black,
        ),
        "table_cell_bold": ParagraphStyle(
            "TableCellBold", fontName=FONT_BOLD, fontSize=9, leading=12,
            textColor=colors.black,
        ),
        "table_header": ParagraphStyle(
            "TableHeader", fontName=FONT_BOLD, fontSize=9.5, leading=12,
            textColor=colors.white,
        ),
        "roadmap_critical": ParagraphStyle(
            "RoadmapCritical", fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=colors.HexColor("#7F1D1D"), spaceAfter=8, backColor=colors.HexColor("#FEF2F2"),
            borderPadding=8,
        ),
        "roadmap_high": ParagraphStyle(
            "RoadmapHigh", fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=colors.HexColor("#9A3412"), spaceAfter=8, backColor=colors.HexColor("#FFF7ED"),
            borderPadding=8,
        ),
        "roadmap_medium": ParagraphStyle(
            "RoadmapMedium", fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=colors.HexColor("#854D0E"), spaceAfter=8, backColor=colors.HexColor("#FEFCE8"),
            borderPadding=8,
        ),
        "roadmap_low": ParagraphStyle(
            "RoadmapLow", fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=colors.HexColor("#14532D"), spaceAfter=8, backColor=colors.HexColor("#F0FDF4"),
            borderPadding=8,
        ),
    }


def _unavailable(elements: list, styles: dict, label: str = "Графік недоступний для відображення.") -> None:
    elements.append(Paragraph(label, styles["base"]))


def _paragraph_row(cells, styles: dict, header: bool = False) -> list:
    """
    Req 3/4: convert a row of plain strings into wrapping Paragraph
    flowables. ReportLab's Table does NOT auto-wrap plain string cells --
    it draws them as a single line that can overflow the column -- only
    Paragraph flowables wrap to the actual column width and let the row
    grow to fit, which is what both the Regional Analysis table and the
    Process Maturity Score breakdown table need for their longer text
    columns (region names + descriptive labels, and penalty explanations).
    """
    style = styles["table_header"] if header else styles["table_cell"]
    return [Paragraph(str(cell), style) for cell in cells]


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
        rows.append(["Average FTE per Case", f"{avg_fte:.2f}"])

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
    title = Paragraph("Case Duration Distribution (Histogram)", styles["subtitle"])

    fig = _figure_from_result(result, "general_statistics")
    if fig is None:
        try:
            fig = visualizations.case_duration_histogram(result.case_times)
        except Exception as e:
            logger.warning("Histogram rebuild failed: %s", e)

    img = _image_flowable(_plotly_to_png(fig))
    if img is not None:
        elements.append(KeepTogether([title, img]))
    else:
        elements.append(title)
        _unavailable(elements, styles)


# ---------------------------------------------------------------------------
# Page 3: Heuristics Miner (CR-01.2) -- full-page LANDSCAPE (Req 1.1/1.2)
# ---------------------------------------------------------------------------
LANDSCAPE_MARGIN = 30  # points; kept tight per Req 1.1 "avoid unnecessary white margins"
HEURISTICS_TITLE_GAP = 10  # points; small breathing room between title and graph
HEURISTICS_GRAPH_DPI = 350  # rendering resolution for the PDF (independent of PDF display size); bumped from 300 to keep ppi comfortably high now that graphs render taller (Req 2.5)
HEURISTICS_SAFETY_MARGIN = 15  # points; empirically verified via binary search (threshold ~8pt) to reliably avoid the spurious-blank-page issue across different graph shapes, at negligible cost to graph size


def _build_heuristics_page(elements: list, styles: dict, visualizations, result) -> None:
    title = Paragraph("Heuristics Miner (Custom Graphviz)", styles["subtitle"])
    elements.append(title)

    dot = _figure_from_result(result, "heuristics")
    if dot is None:
        transitions = result.transitions or {}
        try:
            dot = visualizations.heuristics_graph(transitions["edges"], transitions["bottleneck_text"])
        except Exception as e:
            logger.warning("Heuristics graph rebuild failed: %s", e)
            dot = None

    landscape_size = landscape(A4)
    available_width = landscape_size[0] - 2 * LANDSCAPE_MARGIN
    frame_height = landscape_size[1] - 2 * LANDSCAPE_MARGIN

    # Measure the title's ACTUAL rendered height (not a fixed guess) so the
    # graph gets the true maximum remaining vertical space below it, and the
    # centering calculation below is based on real numbers.
    _, title_height = title.wrap(available_width, frame_height)
    # HEURISTICS_SAFETY_MARGIN: fitting the content to EXACTLY frame_height
    # (zero slack) caused ReportLab to spill onto a spurious blank second
    # page -- floating-point/rendering rounding across title+spacers+image
    # can tip the cumulative height a hair over the frame boundary. A few
    # points of slack guarantees the content always fits on the one
    # intended page.
    available_height = frame_height - title_height - HEURISTICS_TITLE_GAP - HEURISTICS_SAFETY_MARGIN

    # Render at a much higher DPI than the default (~96) specifically for
    # this full-page use -- generation resolution is deliberately decoupled
    # from PDF display size (Sec 8): render once at a resolution with
    # comfortable headroom for the largest this graph will ever be shown
    # (a full landscape page), THEN scale that high-res PNG down/up
    # proportionally to fit -- rather than enlarging an already-low-res
    # image, which is what caused visible blur before. Uses a copy so the
    # shared Digraph object (also reused for the Streamlit UI's
    # st.graphviz_chart and SVG zoom viewer) is never mutated.
    hires_dot = None
    if dot is not None:
        try:
            hires_dot = dot.copy()
            hires_dot.attr(dpi=str(HEURISTICS_GRAPH_DPI))
        except Exception as e:
            logger.warning("Could not prepare hi-res Graphviz copy, falling back to default DPI: %s", e)
            hires_dot = dot

    # Priority order (Sec 12): maximize size within (available_width,
    # available_height) first -- _image_flowable_fit already picks whichever
    # of width/height binds first and preserves aspect ratio -- THEN center
    # the resulting (already-maximized) image in the leftover space. Vertical
    # centering never shrinks the graph below its maximum fit.
    img = _image_flowable_fit(_graphviz_to_png(hires_dot), available_width, available_height)
    if img is not None:
        leftover = max(0.0, available_height - img.drawHeight)
        top_spacer = leftover / 2
        bottom_spacer = leftover - top_spacer
        elements.append(Spacer(1, HEURISTICS_TITLE_GAP + top_spacer))
        elements.append(img)
        if bottom_spacer > 0:
            elements.append(Spacer(1, bottom_spacer))
    else:
        _unavailable(elements, styles, "Граф переходів недоступний для відображення.")


# ---------------------------------------------------------------------------
# Page 4: Lead Time vs Rework (CR-01.1 -- reuses the matplotlib figure)
# ---------------------------------------------------------------------------
def _build_lead_time_page(elements: list, styles: dict, visualizations, result) -> None:
    title = Paragraph("Lead Time: Rework vs Non-Rework", styles["subtitle"])

    lead_time = result.statistics.get("lead_time", {})
    rework = result.statistics.get("rework", {})

    fig = _figure_from_result(result, "lead_time")
    if fig is None:
        try:
            fig = visualizations.lead_time_boxplot(lead_time["lead_time_per_case"])
        except Exception as e:
            logger.warning("Lead time boxplot rebuild failed: %s", e)
            fig = None

    img = _image_flowable(_plotly_to_png(fig), max_width_cm=13)
    if img is not None:
        elements.append(KeepTogether([title, img]))
    else:
        elements.append(title)
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
    title = Paragraph("Bubble Chart: Duration per Step vs Rework Count", styles["subtitle"])

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
        elements.append(KeepTogether([title, img]))
    else:
        elements.append(title)
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

    title = Paragraph("Role Analysis", styles["subtitle"])
    intro = Paragraph(
        f"Середня кількість FTE на кейс (Average FTE per Case): "
        f"<b>{role['avg_fte_per_case']:.2f}</b> "
        "(оцінка потрібного FTE-ресурсу на один кейс, а не кількість фізичних "
        "співробітників).",
        styles["base"],
    )
    elements.append(KeepTogether([title, intro]))

    # CR-02 4.4: Role / Cases / Average Hours per Case / FTE table.
    fte_df = role["role_workload"][["Role", "cases_handled", "avg_hours_per_case", "fte"]].sort_values(
        "fte", ascending=False
    )
    fte_rows = [["Role", "Cases", "Average Hours per Case", "FTE"]] + [
        [
            str(r["Role"]),
            f"{int(r['cases_handled'])}",
            f"{r['avg_hours_per_case']:.2f}",
            f"{r['fte']:.2f}",
        ]
        for _, r in fte_df.iterrows()
    ]
    fte_table = Table(fte_rows, colWidths=[5.5 * cm, 3 * cm, 5 * cm, 2.5 * cm])
    fte_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(Spacer(1, 6))
    elements.append(fte_table)
    elements.append(Spacer(1, 10))

    for caption, sub_key in [
        ("Role vs Activity Matrix", "matrix"),
        ("Role Workload Distribution", "workload"),
        ("Role Bottleneck Ranking", "bottleneck"),
    ]:
        fig = _figure_from_result(result, "role_analysis", sub_key)
        img = _image_flowable(_plotly_to_png(fig), max_width_cm=15)
        if img is not None:
            elements.append(KeepTogether([Paragraph(caption, styles["chart_caption"]), img]))
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
    if role.get("top_fte_role"):
        elements.append(
            Paragraph(
                f"🏋️ Роль з найвищим FTE: <b>{role['top_fte_role']}</b>",
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

    title = Paragraph("Regional Analysis", styles["subtitle"])

    # Sec. 14.1: Regional KPI Summary table (same kpi_summary dict the UI uses).
    kpi = region["kpi_summary"]
    kpi_rows_raw = [
        ["Показник", "Значення"],
        ["Кількість регіонів (Number of Regions)", f"{kpi['num_regions']}"],
        ["Найкращий регіон (Best Performing Region)", kpi["best_region"] or "—"],
        ["Регіон, що потребує уваги (Region Requiring Attention)", kpi["worst_region"] or "—"],
        ["Середній Lead Time по процесу (Overall Average Lead Time)", f"{kpi['overall_avg_lead_time']:.2f} год"],
        ["Найвищий Rework Rate (Highest Rework Rate Region)", kpi["highest_rework_region"] or "—"],
        ["Найвища концентрація bottleneck (Highest Bottleneck Concentration)", kpi["highest_bottleneck_region"] or "—"],
    ]
    # Req 3: wrapping Paragraph cells instead of plain strings -- several of
    # these labels are long enough to overflow a plain-string cell.
    kpi_rows = [_paragraph_row(kpi_rows_raw[0], styles, header=True)] + [
        _paragraph_row(row, styles) for row in kpi_rows_raw[1:]
    ]
    kpi_table = Table(kpi_rows, colWidths=[10.5 * cm, 5.5 * cm])
    kpi_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(KeepTogether([title, Spacer(1, 4), kpi_table]))
    elements.append(Spacer(1, 10))

    for caption, sub_key in [
        ("Lead Time by Region", "lead_time"),
        ("Rework by Region", "rework"),
        ("Regional Performance Matrix", "matrix"),
        ("Bottleneck Distribution by Region", "bottleneck"),
    ]:
        fig = _figure_from_result(result, "region_analysis", sub_key)
        img = _image_flowable(_plotly_to_png(fig), max_width_cm=15)
        if img is not None:
            elements.append(KeepTogether([Paragraph(caption, styles["chart_caption"]), img]))
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
    elements: list, styles: dict, summary_text: str, recommendations: str,
    maturity_score: int, maturity_score_breakdown: list, maturity_focus_areas: list,
) -> None:
    elements.append(Paragraph("Executive Summary", styles["subtitle"]))
    elements.append(Paragraph(summary_text.replace("\n", "<br/>"), styles["base"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Рекомендації", styles["subtitle"]))
    elements.append(Paragraph(recommendations.replace("\n", "<br/>"), styles["base"]))
    elements.append(Spacer(1, 8))

    # CR-04: full, explainable breakdown instead of a single opaque number.
    elements.append(Paragraph("Process Maturity Score", styles["subtitle"]))
    elements.append(
        Paragraph(f"<b>Score = {maturity_score} / 100</b>", styles["base"])
    )

    if maturity_score_breakdown:
        rows_raw = [["Component", "Points", "Applied", "Reason"]]
        rows_raw.append(["Base Score", "100", "—", "Starting score before penalties."])
        for c in maturity_score_breakdown:
            rows_raw.append([
                c["name"],
                f"{c['points']:+d}",
                "Yes" if c["applied"] else "No",
                c["reason"],
            ])
        # Req 4: wrapping Paragraph cells instead of plain strings -- the
        # "Reason" column holds full explanatory sentences that would
        # otherwise overflow a plain-string cell.
        rows = [_paragraph_row(rows_raw[0], styles, header=True)] + [
            _paragraph_row(row, styles) for row in rows_raw[1:]
        ]
        table = Table(rows, colWidths=[3.7 * cm, 1.8 * cm, 2.3 * cm, 8.5 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                    ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(Spacer(1, 6))
        elements.append(table)
        elements.append(Spacer(1, 10))

    # Req 5: the separate "Key Areas to Focus On" block has been removed
    # from the report (Process Maturity Score + breakdown above are
    # unchanged). Priority areas now live exclusively in the Improvement
    # Roadmap section below.

    # CR-03 / item 10: Time Calculation Methodology disclosure.
    elements.append(Paragraph(TIME_METHODOLOGY_TITLE, styles["subtitle"]))
    elements.append(
        Paragraph(TIME_METHODOLOGY_TEXT.replace("\n", "<br/>"), styles["base"])
    )


def _build_improvement_roadmap_section(
    elements: list, styles: dict, roadmap: list, quantified_impact_summary: dict = None,
) -> None:
    """
    Req 7 / Sec 18: the final actionable section of the report. Consumes
    the exact same `result.roadmap` list (built once in
    analytics.build_improvement_roadmap) that the Streamlit UI renders --
    no roadmap logic is duplicated here (Sec 20 SSOT).
    """
    elements.append(PageBreak())
    elements.append(Paragraph("Improvement Roadmap", styles["subtitle"]))

    # Req 1.10: aggregated Total Quantified Expected Impact, same
    # `quantified_impact_summary` dict the UI reads (Sec 20 SSOT).
    if quantified_impact_summary and quantified_impact_summary.get("initiatives_count"):
        s = quantified_impact_summary
        time_str = (
            f"{s['time_hours_per_case']:.2f} год/кейс" if s["time_initiatives_count"] else "—"
        )
        fte_str = f"{s['fte']:.2f} FTE" if s["fte_initiatives_count"] else "—"
        summary_text = (
            "<b>TOTAL QUANTIFIED EXPECTED IMPACT (Potential Gross Impact)</b><br/><br/>"
            f"<b>Potential Time Impact:</b> {time_str}<br/>"
            f"<b>Potential FTE Capacity Released:</b> {fte_str}<br/><br/>"
            f"<font size=8>{s['note']}</font>"
        )
        elements.append(Paragraph(summary_text, styles["roadmap_medium"]))
        elements.append(Spacer(1, 10))

    if not roadmap:
        elements.append(
            Paragraph(
                "Недостатньо аналітичних підстав для формування roadmap на цьому наборі даних.",
                styles["base"],
            )
        )
        return

    phases_present = list(dict.fromkeys(item["phase"] for item in roadmap))
    style_by_priority = {
        "Critical": "roadmap_critical", "High": "roadmap_high",
        "Medium": "roadmap_medium", "Low": "roadmap_low",
    }
    for phase in phases_present:
        elements.append(Paragraph(phase, styles["chart_caption"]))
        for item in roadmap:
            if item["phase"] != phase:
                continue
            quantified_line = ""
            ei = item.get("expected_impact")
            if ei:
                quantified_line = (
                    f"<b>Quantified Expected Impact:</b> Current: {ei['current_value']} {ei['unit']} → "
                    f"Target: {ei['target_value']} {ei['unit']} "
                    f"(Δ {ei['improvement_value']:+.2f} {ei['unit']}, {ei['improvement_percent']:+.1f}%)<br/>"
                    f"<font size=8 color='#6B7280'>{ei['calculation_method']} — "
                    f"Confidence: {ei['confidence']} (potential, not guaranteed)</font><br/>"
                )
            card_text = (
                f"<b>{item['icon']} {item['priority']} — {item['area']}</b><br/><br/>"
                f"<b>Problem:</b> {item['problem']}<br/>"
                f"<b>Evidence:</b> {item['evidence']}<br/>"
                f"<b>Recommended Action:</b> {item['action']}<br/>"
                f"<b>Expected Impact:</b> {item['impact']}<br/>"
                f"{quantified_line}"
                f"<font size=8 color='#6B7280'>Source: {item['source']}</font>"
            )
            card_style = styles[style_by_priority.get(item["priority"], "roadmap_medium")]
            elements.append(Paragraph(card_text, card_style))
            elements.append(Spacer(1, 8))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_pdf_report(result) -> BytesIO:
    """
    Build and return an in-memory PDF buffer for the executive report.

    Layout (Req 1): content flows sequentially and continuously -- Case
    Duration Distribution, Lead Time, Bubble Chart, and the conditional
    Role/Region Analysis sections are NOT each forced onto their own page
    (Rule 1/2 of the layout spec); ReportLab's normal frame-flow pagination
    only starts a new page when the current one is actually full. Section
    headings are kept together with their first chart/table via
    `KeepTogether` so a heading is never orphaned alone at the bottom of a
    page (Rule 3/4).

    The ONE exception is Heuristics Miner (Req 1.1): it gets its own
    dedicated LANDSCAPE page so the process graph can use the maximum
    available page area, via a `NextPageTemplate` switch between the
    'Portrait' and 'Landscape' page templates registered on the doc. The
    report also breaks to a fresh page before the Executive Summary /
    Improvement Roadmap, since those represent a distinct final "chapter"
    of the report rather than another analysis chart.

        Portrait   Executive Overview + KPI Summary
                   Case Duration Distribution
        Landscape  Heuristics Miner (full page)
        Portrait   Lead Time -> Bubble Chart -> Role -> Region (flowing)
                   Executive Summary + Recommendations + Maturity Score
                   Improvement Roadmap (with quantified Expected Impact, Req 2)

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
    portrait_size = A4
    landscape_size = landscape(A4)
    margin = 40

    doc = BaseDocTemplate(
        buffer, pagesize=portrait_size,
        rightMargin=margin, leftMargin=margin, topMargin=50, bottomMargin=margin,
    )
    portrait_frame = Frame(
        margin, margin, portrait_size[0] - 2 * margin, portrait_size[1] - 2 * margin, id="portrait",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    landscape_frame = Frame(
        LANDSCAPE_MARGIN, LANDSCAPE_MARGIN,
        landscape_size[0] - 2 * LANDSCAPE_MARGIN, landscape_size[1] - 2 * LANDSCAPE_MARGIN,
        id="landscape",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="Portrait", frames=[portrait_frame], pagesize=portrait_size),
        PageTemplate(id="Landscape", frames=[landscape_frame], pagesize=landscape_size),
    ])

    elements: list = []

    kpis = result.kpis()

    # ---- Executive Overview + KPI Summary (portrait, default template) ----
    _build_cover_page(elements, styles, kpis)
    _build_kpi_summary(elements, styles, kpis)

    # ---- Case Duration Distribution (flows right after KPI Summary; no
    #      forced page break -- Rule 1) ----
    _build_case_duration_page(elements, styles, visualizations, result)

    # ---- Heuristics Miner: dedicated LANDSCAPE page (Req 1.1) ----
    elements.append(NextPageTemplate("Landscape"))
    elements.append(PageBreak())
    _build_heuristics_page(elements, styles, visualizations, result)

    # ---- Back to portrait for everything else; Lead Time -> Bubble Chart
    #      -> Role -> Region all flow sequentially with no forced breaks
    #      between them (Rule 1/2) ----
    elements.append(NextPageTemplate("Portrait"))
    elements.append(PageBreak())
    _build_lead_time_page(elements, styles, visualizations, result)
    _build_bubble_chart_page(elements, styles, visualizations, result)

    if result.role_analysis is not None:
        _build_role_analysis_page(elements, styles, result)

    if result.region_analysis is not None:
        _build_region_analysis_page(elements, styles, result)

    # ---- Executive Summary + Improvement Roadmap: a distinct final
    #      "chapter" of the report, so a fresh page here is a deliberate
    #      logical section boundary rather than a Rule-1 violation. ----
    elements.append(PageBreak())
    exec_summary = result.executive_summary or {}
    _build_executive_summary_section(
        elements,
        styles,
        exec_summary.get("summary_text", ""),
        exec_summary.get("recommendations", ""),
        result.maturity_score,
        result.maturity_score_breakdown,
        result.maturity_focus_areas,
    )

    # ---- Improvement Roadmap: the final actionable section (Sec 18) ----
    _build_improvement_roadmap_section(elements, styles, result.roadmap, result.quantified_impact_summary)

    doc.build(elements)
    buffer.seek(0)
    return buffer

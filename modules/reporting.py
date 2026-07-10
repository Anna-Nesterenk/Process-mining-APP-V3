"""
reporting.py
------------
Builds the downloadable PDF "Executive Report".

Redesigned per Sec. 4 of the requirements:
    - Cover page (title, generation date, analysis period, case count)
    - KPI summary (cases, activities, avg lead time, median/avg duration)
    - Visualizations (every relevant chart embedded as PNG)
    - Executive summary, recommendations, maturity score

Font fix (Sec. 2.5)
--------------------
The previous implementation looked for a `DejaVuSans.ttf` file that was
never actually committed to the repo, so `generate_pdf_report` crashed with
a `FileNotFoundError` as soon as it was called on Streamlit Cloud (and on
any machine that didn't happen to have that file lying around). Cyrillic
text also can't use ReportLab's built-in Helvetica/Times base fonts, so
simply falling back to those isn't an option either.

Fix: matplotlib already ships a full copy of DejaVu Sans (regular + bold)
inside its own installed package data, and matplotlib is already a hard
dependency of this app. We resolve that bundled font via
`matplotlib.get_data_path()` at runtime and register it with ReportLab --
no extra font file needs to be committed to the repo, and the exact same
font is available locally and on Streamlit Cloud since both environments
install matplotlib from the same wheel.

Chart embedding
-----------------
Plotly figures are rasterized to PNG via `fig.to_image(...)` (kaleido
backend -- added to requirements.txt). Matplotlib figures are rasterized
via `fig.savefig(...)`. Graphviz Digraphs are rendered via `dot.pipe(...)`;
if the `dot` binary isn't available in a given environment, that one chart
is skipped rather than failing the whole report.
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


def _image_flowable(png_bytes: bytes, max_width_cm: float = 16) -> Optional[Image]:
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
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def _build_cover_page(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    elements.append(Spacer(1, 4 * cm))
    elements.append(Paragraph("Process Mining", styles["title"]))
    elements.append(Paragraph("Executive Report", styles["title"]))
    elements.append(Spacer(1, 1 * cm))
    elements.append(
        Paragraph(f"Дата формування: {datetime.now().strftime('%d.%m.%Y')}", styles["cover_sub"])
    )

    start = kpis.get("start_period")
    end = kpis.get("end_period")
    if pd.notna(start) and pd.notna(end):
        elements.append(
            Paragraph(
                f"Період аналізу: {start.date()} → {end.date()}", styles["cover_sub"]
            )
        )
    elements.append(
        Paragraph(f"Кількість проаналізованих кейсів: {kpis.get('num_cases', 0)}", styles["cover_sub"])
    )
    elements.append(Spacer(1, 2 * cm))
    elements.append(Paragraph(AUTHOR_NAME, styles["cover_sub"]))
    elements.append(
        Paragraph(f'<link href="{AUTHOR_LINKEDIN}">{AUTHOR_LINKEDIN}</link>', styles["cover_sub"])
    )
    elements.append(PageBreak())


def _build_kpi_summary(elements: list, styles: dict, kpis: Dict[str, Any]) -> None:
    elements.append(Paragraph("KPI Summary", styles["subtitle"]))

    rows = [
        ["Показник", "Значення"],
        ["Кількість кейсів (Number of Cases)", f"{kpis.get('num_cases', 0)}"],
        ["Кількість активностей (Number of Activities)", f"{kpis.get('num_activities', 0)}"],
        ["Середній Lead Time (Average Lead Time)", f"{kpis.get('avg_lead_time', 0):.2f} год"],
        ["Медіанна тривалість кейсу (Median Case Duration)", f"{kpis.get('median_case_duration', 0):.2f} год"],
        ["Середня тривалість кейсу (Average Case Duration)", f"{kpis.get('avg_case_duration', 0):.2f} год"],
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


def _build_visualizations_section(elements: list, styles: dict, charts: Dict[str, bytes]) -> None:
    if not any(charts.values()):
        return
    elements.append(PageBreak())
    elements.append(Paragraph("Visualizations", styles["subtitle"]))

    for caption, png_bytes in charts.items():
        img = _image_flowable(png_bytes)
        if img is None:
            continue
        elements.append(Paragraph(caption, styles["chart_caption"]))
        elements.append(img)
        elements.append(Spacer(1, 10))


def _build_executive_summary_section(
    elements: list, styles: dict, summary_text: str, recommendations: str, maturity_score: int
) -> None:
    elements.append(PageBreak())
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
    Build and return an in-memory PDF buffer for the executive report.

    `result` is an `AnalysisResult` (modules.models.AnalysisResult), which
    is the same object used to render the Streamlit UI -- so the PDF always
    shows the same numbers and charts the user just saw on screen.
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
    _build_cover_page(elements, styles, kpis)
    _build_kpi_summary(elements, styles, kpis)

    # ---- Build every chart from the centralized analysis data ----
    stats = result.statistics
    charts: Dict[str, bytes] = {}

    try:
        fig = visualizations.case_duration_histogram(result.case_times)
        charts["Тривалість кейсів"] = _plotly_to_png(fig)
    except Exception:
        pass

    step_analysis = stats.get("step_analysis", {})
    if step_analysis.get("analysis_df") is not None and not step_analysis["analysis_df"].empty:
        try:
            fig = visualizations.step_bubble_chart(
                step_analysis["analysis_df"], step_analysis["x_mean"], step_analysis["y_mean"]
            )
            charts["Бульбашкова діаграма кроків"] = _plotly_to_png(fig)
        except Exception:
            pass
        try:
            fig = visualizations.risk_heatmap(
                step_analysis["analysis_df"], step_analysis["x_mean"], step_analysis["y_mean"]
            )
            charts["Risk Heatmap"] = _matplotlib_to_png(fig)
        except Exception:
            pass

    lead_time = stats.get("lead_time", {})
    if lead_time.get("lead_time_per_case") is not None:
        try:
            fig = visualizations.lead_time_boxplot(lead_time["lead_time_per_case"])
            charts["Lead Time: rework vs без rework"] = _matplotlib_to_png(fig)
        except Exception:
            pass

    transitions = stats.get("transitions", {})
    if transitions.get("edges") is not None:
        try:
            dot = visualizations.heuristics_graph(transitions["edges"], transitions["bottleneck_text"])
            png = _graphviz_to_png(dot)
            if png:
                charts["Heuristics Miner (переходи процесу)"] = png
        except Exception:
            pass

    _build_visualizations_section(elements, styles, charts)

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

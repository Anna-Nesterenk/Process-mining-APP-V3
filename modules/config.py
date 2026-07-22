"""
config.py
---------
Central place for application-wide constants and settings.
Keeping these values in one module makes future changes (e.g. adding a new
mandatory column, renaming a metric, or changing the analytics tracking id)
a one-line edit instead of a search-and-replace across the whole codebase.
"""

# ---------------------------------------------------------------------------
# Google Analytics
# ---------------------------------------------------------------------------
GA_ID = "G-ZY97CXY9MR"

# ---------------------------------------------------------------------------
# Streamlit page settings
# ---------------------------------------------------------------------------
PAGE_TITLE = "Process Mining (Excel)"
APP_TITLE = "🧩 Process Mining App"
LAYOUT = "wide"

AUTHOR_NAME = "Hanna Nesterenko"
AUTHOR_LINKEDIN = "https://www.linkedin.com/in/anna-nesterenko-bi/"

# ---------------------------------------------------------------------------
# Event log schema
# ---------------------------------------------------------------------------
# Columns that MUST be present and fully populated for the analysis to run.
MANDATORY_COLUMNS = [
    "Case ID",
    "Activity Name",
    "Start Timestamp",
    "Finish Timestamp",
]

# Columns that enrich the analysis but are not required for Stage 1.
OPTIONAL_COLUMNS = [
    "Role",
    "Region",
]

ALL_TEMPLATE_COLUMNS = MANDATORY_COLUMNS + OPTIONAL_COLUMNS

# ---------------------------------------------------------------------------
# Usage metrics persisted to disk
# ---------------------------------------------------------------------------
METRICS_FILE = "metrics.json"
DEFAULT_METRICS = {
    "app_visits": 0,
    "datasets_uploaded": 0,
    "analyses_run": 0,
    "pdf_generated": 0,
}

# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------
# The font itself is resolved at runtime from matplotlib's bundled DejaVu
# Sans (see modules/reporting.py::_register_fonts) so no TTF file needs to
# be committed to / found in the repo. This name is just the ReportLab
# registration key.
PDF_FONT_NAME = "DejaVuSans"

# ---------------------------------------------------------------------------
# CR-03: Time Calculation Methodology
# ---------------------------------------------------------------------------
# Single source of truth for this disclosure text -- quoted verbatim in the
# UI (General Statistics section), the PDF Executive Report, and README.md,
# so the three can never drift out of sync.
TIME_METHODOLOGY_TITLE = "Методологія розрахунку часу (Time Calculation Methodology)"
TIME_METHODOLOGY_TEXT = (
    "Усі розрахунки, пов'язані з часом і тривалістю процесу, виконуються на основі "
    "календарних днів і годин за моделлю 24/7.\n\n"
    "При розрахунку Lead Time, тривалості кейсу, Waiting Time та тривалості окремих "
    "активностей неробочий час не виключається.\n\n"
    "Поточна версія застосунку не розрізняє:\n"
    "- робочі та неробочі години;\n"
    "- робочі дні та вихідні;\n"
    "- державні свята;\n"
    "- індивідуальні графіки роботи співробітників;\n"
    "- часові пояси.\n\n"
    "Тому всі часові показники відображають фактичний календарний час між "
    "відповідними мітками часу (timestamps)."
)

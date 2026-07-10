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

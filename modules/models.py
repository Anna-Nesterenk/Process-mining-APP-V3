"""
models.py
---------
FR-9: A single, typed container (`AnalysisResult`) that bundles every piece
of analysis produced for one uploaded event log -- case metrics, statistics,
figures, transition/variant analysis and the executive summary.

Building one `AnalysisResult` per run gives `app.py` and `reporting.py` a
single object to pass around instead of a growing list of loose dicts, and
is what `reporting.generate_pdf_report` now consumes: the PDF is guaranteed
to show exactly the same numbers and charts as the Streamlit UI because both
are rendered from this one object (Sec. 5, "reporting uses the same data and
visualizations displayed in the UI").
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class AnalysisResult:
    """Unified analysis object produced by `analytics.build_full_analysis`."""

    # Centralized data (Single Source of Truth)
    case_times: pd.DataFrame
    activity_statistics: pd.DataFrame

    # Grouped analytical results, keyed the same way as the section they
    # power (general statistics, rework, lead time, step/bottleneck
    # analysis, transitions, variants).
    statistics: Dict[str, Any] = field(default_factory=dict)

    # Rendering-layer output: {name: {"figure": ..., "statistics": ...}}
    # populated by app.py's render_* functions (FR-8) as sections are drawn.
    figures: Dict[str, Any] = field(default_factory=dict)

    transitions: Dict[str, Any] = field(default_factory=dict)
    variants: Dict[str, Any] = field(default_factory=dict)

    executive_summary: Dict[str, Any] = field(default_factory=dict)
    maturity_score: int = 0
    maturity_score_breakdown: list = field(default_factory=list)
    maturity_focus_areas: list = field(default_factory=list)
    ai_narrative: str = ""
    roadmap: list = field(default_factory=list)
    quantified_impact_summary: Dict[str, Any] = field(default_factory=dict)

    # CR-08: Optional -- None whenever the source event log doesn't contain
    # a 'Role' / 'Region' column (CR-05 / CR-06 visibility conditions).
    role_analysis: Optional[Dict[str, Any]] = None
    region_analysis: Optional[Dict[str, Any]] = None
    avg_fte_per_case: Optional[float] = None

    def kpis(self) -> Dict[str, Any]:
        """Convenience accessor for the handful of top-line KPIs the PDF
        cover/summary page needs, all derived from `case_times` -- the
        single centralized table -- so they can never drift from what the
        Streamlit UI shows."""
        ct = self.case_times
        return {
            "num_cases": len(ct),
            "num_activities": int(ct["Number of Activities"].sum()),
            "avg_lead_time": ct["Lead Time"].mean(),
            "median_case_duration": ct["Duration (hours)"].median(),
            "avg_case_duration": ct["Duration (hours)"].mean(),
            "start_period": ct["Start Timestamp"].min(),
            "end_period": ct["Finish Timestamp"].max(),
            "avg_fte_per_case": self.avg_fte_per_case,
        }

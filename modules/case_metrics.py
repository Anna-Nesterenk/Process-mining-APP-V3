"""
case_metrics.py
----------------
Single Source of Truth for every case-level and activity-level analytical
aggregation in the app (FR-1, FR-2, FR-9, Sec. 5/6).

Historically `analytics.py`, `visualizations.py` and `reporting.py` each ran
their own `groupby("Case ID")` to (re-)derive case duration, lead time and
waiting time. That both wasted CPU on large event logs (Sec. 2.3/2.6) and
created a risk of the three modules silently disagreeing (Sec. 2.2).

This module is now the *only* place that aggregates the raw event-level
DataFrame into case-level (`calculate_case_times`) and activity-level
(`calculate_activity_statistics`) tables. Every other module must consume
those tables instead of recomputing them.

Waiting Time definition (FR-5, fixes Sec. 2.4)
-----------------------------------------------
Waiting Time for a case = sum over consecutive activities of
    Start Timestamp(activity i+1) - Finish Timestamp(activity i)

The per-event component of that sum (`waiting_hours`: the wait *before* the
current event) is computed once in `data_processing.prepare_dataframe` and
simply summed per case here -- no re-derivation from timestamps happens in
this module.

Lead Time definition (FR-6)
----------------------------
Lead Time for a case = max(Finish Timestamp) - min(Start Timestamp)
This is numerically identical to case duration, so `calculate_case_times`
exposes both `Duration (hours)` and `Lead Time` (same value, two names) to
match the vocabulary used across the rest of the app / requirements doc.
"""

from typing import Dict

import pandas as pd

CASE_ID_COL = "Case ID"
ACTIVITY_COL = "Activity Name"
START_COL = "Start Timestamp"
FINISH_COL = "Finish Timestamp"
WAITING_COL = "waiting_hours"
STEP_DURATION_COL = "step_duration_hours"


def calculate_case_times(df: pd.DataFrame) -> pd.DataFrame:
    """
    FR-1: Centralized per-case metrics table.

    Requires `df` to already have gone through
    `data_processing.prepare_dataframe` (needs the `waiting_hours` column).

    Returns one row per Case ID with:
        Case ID, Start Timestamp, Finish Timestamp,
        Duration (hours), Lead Time, Waiting Time, Number of Activities
    """
    if CASE_ID_COL not in df.columns:
        raise ValueError(f"DataFrame is missing required column '{CASE_ID_COL}'")

    grouped = df.groupby(CASE_ID_COL)

    case_times = grouped.agg(**{
        START_COL: (START_COL, "min"),
        FINISH_COL: (FINISH_COL, "max"),
        "Number of Activities": (ACTIVITY_COL, "count"),
    }).reset_index()

    case_times["Duration (hours)"] = (
        case_times[FINISH_COL] - case_times[START_COL]
    ).dt.total_seconds() / 3600

    # FR-6: Lead Time = max(Finish Timestamp) - min(Start Timestamp)
    case_times["Lead Time"] = case_times["Duration (hours)"]

    # FR-5: Waiting Time = sum of per-event waiting_hours within each case.
    if WAITING_COL in df.columns:
        waiting_per_case = (
            grouped[WAITING_COL]
            .sum(min_count=1)
            .rename("Waiting Time")
            .reset_index()
        )
    else:
        waiting_per_case = pd.DataFrame({
            CASE_ID_COL: case_times[CASE_ID_COL],
            "Waiting Time": 0.0,
        })

    case_times = case_times.merge(waiting_per_case, on=CASE_ID_COL, how="left")
    case_times["Waiting Time"] = case_times["Waiting Time"].fillna(0.0)

    return case_times


def calculate_activity_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Case + Activity level aggregation used by the bubble chart / risk
    heatmap / step-duration analysis.

    This is a fundamentally different grain than `calculate_case_times`
    (per-activity rather than per-case), so per Sec. 6 it is legitimate to
    aggregate it separately -- but it must still only be computed ONCE and
    reused by every consumer (bubble chart, heatmap, executive summary),
    instead of each one re-running its own groupby.
    """
    if STEP_DURATION_COL not in df.columns:
        raise ValueError(
            f"DataFrame is missing '{STEP_DURATION_COL}'. "
            "Call data_processing.compute_step_durations(df) first."
        )

    step_stats = (
        df.groupby([CASE_ID_COL, ACTIVITY_COL])
        .agg(
            duration_hours=(STEP_DURATION_COL, "sum"),
            count=(ACTIVITY_COL, "count"),
        )
        .reset_index()
    )
    return step_stats


def prepare_analysis_data(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Single entry point that performs the case-level and activity-level
    aggregations exactly once for the whole application (Sec. 5/6).

    All downstream analytics / visualization / reporting code must consume
    this result rather than issuing its own `groupby("Case ID")` calls.
    """
    return {
        "df": df,
        "case_times": calculate_case_times(df),
        "activity_statistics": calculate_activity_statistics(df),
    }

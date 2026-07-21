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

from typing import Dict, Optional

import pandas as pd

CASE_ID_COL = "Case ID"
ACTIVITY_COL = "Activity Name"
START_COL = "Start Timestamp"
FINISH_COL = "Finish Timestamp"
WAITING_COL = "waiting_hours"
STEP_DURATION_COL = "step_duration_hours"
ROLE_COL = "Role"
REGION_COL = "Region"


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


def calculate_role_statistics(df: pd.DataFrame) -> Optional[Dict[str, object]]:
    """
    CR-05: pure aggregation of role participation/workload -- the SSOT table
    that `analytics.role_analysis` builds bottleneck/rework rankings from.

    Returns None when the event log has no 'Role' column (CR-05 visibility
    condition: the whole Role Analysis section is skipped in that case).

    FTE approximation (no real FTE data is available in this event log):
        - "cases_handled" per role is used as a workload proxy for FTE
          count per role (a role that touches more distinct cases has a
          proportionally higher effective workload).
        - "avg_roles_per_case" (avg number of distinct roles touching a
          case) is used as the "Average FTE per Case" KPI.
    """
    if ROLE_COL not in df.columns:
        return None

    role_activity = (
        df.groupby([ROLE_COL, ACTIVITY_COL])
        .agg(
            occurrences=(ACTIVITY_COL, "count"),
            avg_duration_hours=(STEP_DURATION_COL, "mean"),
        )
        .reset_index()
    )

    role_workload = (
        df.groupby(ROLE_COL)
        .agg(
            cases_handled=(CASE_ID_COL, "nunique"),
            activities_performed=(ACTIVITY_COL, "count"),
            avg_step_duration_hours=(STEP_DURATION_COL, "mean"),
        )
        .reset_index()
        .sort_values("cases_handled", ascending=False)
    )

    avg_roles_per_case = df.groupby(CASE_ID_COL)[ROLE_COL].nunique().mean()

    return {
        "role_activity": role_activity,
        "role_workload": role_workload,
        "avg_roles_per_case": avg_roles_per_case,
    }


def calculate_region_statistics(
    df: pd.DataFrame, case_times: pd.DataFrame
) -> Optional[Dict[str, object]]:
    """
    CR-06: pure aggregation of region-level lead time / activity data -- the
    SSOT table that `analytics.region_analysis` builds insights/
    recommendations from.

    Returns None when the event log has no 'Region' column (CR-06
    visibility condition).
    """
    if REGION_COL not in df.columns:
        return None

    # One Region per case (assumed constant within a case; first non-null wins).
    case_region = df.groupby(CASE_ID_COL)[REGION_COL].first().reset_index()

    region_case_times = case_times.merge(case_region, on=CASE_ID_COL, how="left")
    region_lead_time = (
        region_case_times.groupby(REGION_COL)
        .agg(
            avg_lead_time=("Lead Time", "mean"),
            median_lead_time=("Lead Time", "median"),
            num_cases=(CASE_ID_COL, "count"),
        )
        .reset_index()
        .sort_values("avg_lead_time", ascending=False)
    )

    region_activity = (
        df.groupby([REGION_COL, ACTIVITY_COL])
        .agg(
            occurrences=(ACTIVITY_COL, "count"),
            avg_duration_hours=(STEP_DURATION_COL, "mean"),
        )
        .reset_index()
    )

    region_waiting = (
        df.groupby(REGION_COL)[WAITING_COL].mean().reset_index(name="avg_waiting_hours")
        if WAITING_COL in df.columns
        else pd.DataFrame({REGION_COL: region_lead_time[REGION_COL], "avg_waiting_hours": 0.0})
    )

    return {
        "case_region": case_region,
        "region_lead_time": region_lead_time,
        "region_activity": region_activity,
        "region_waiting": region_waiting,
    }


def prepare_analysis_data(df: pd.DataFrame) -> Dict[str, object]:
    """
    Single entry point that performs the case-level and activity-level
    aggregations exactly once for the whole application (Sec. 5/6).

    All downstream analytics / visualization / reporting code must consume
    this result rather than issuing its own `groupby("Case ID")` calls.

    CR-08: also computes role/region statistics once (None when the
    respective column is absent from the source event log).
    """
    case_times = calculate_case_times(df)
    return {
        "df": df,
        "case_times": case_times,
        "activity_statistics": calculate_activity_statistics(df),
        "role_statistics": calculate_role_statistics(df),
        "region_statistics": calculate_region_statistics(df, case_times),
    }

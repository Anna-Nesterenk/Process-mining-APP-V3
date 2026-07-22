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


FTE_HOURS_PER_DAY = 7.5
FTE_WORKING_DAYS_PER_MONTH = 21
FTE_ABSENCE_FACTOR = 1.15


def calculate_role_statistics(df: pd.DataFrame) -> Optional[Dict[str, object]]:
    """
    CR-02: pure aggregation of role participation/workload, including the
    per-role FTE calculation -- the SSOT table that `analytics.role_analysis`
    builds bottleneck/rework rankings and the Role Analysis table from.

    Returns None when the event log has no 'Role' column (CR-05 visibility
    condition: the whole Role Analysis section is skipped in that case).

    FTE formula (CR-02, replaces the previous `avg_roles_per_case` proxy,
    which measured something different -- the average number of distinct
    roles touching a case -- and was never a real FTE estimate):

        FTE_role = x_role / 7.5 / 21 * 1.15

    where `x_role` ("Average Hours per Case" for the role) is:

        x_role = average, over every case the role participated in, of the
                 SUM of that role's activity durations within that case.

    i.e. first sum step_duration_hours per (Case ID, Role) -- how much
    active time this role spent on this specific case -- then average that
    per-case total across all cases the role touched. This is an estimate
    of the FTE headcount required to sustain the role's average workload
    per case, NOT a count of distinct people or distinct roles.
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

    # x_role: total active hours per (Case ID, Role), then averaged across
    # the cases that role participated in.
    case_role_duration = (
        df.groupby([CASE_ID_COL, ROLE_COL])[STEP_DURATION_COL]
        .sum()
        .reset_index(name="total_duration_hours")
    )
    role_avg_hours_per_case = (
        case_role_duration.groupby(ROLE_COL)["total_duration_hours"]
        .mean()
        .reset_index(name="avg_hours_per_case")
    )

    role_cases = (
        df.groupby(ROLE_COL)[CASE_ID_COL].nunique().reset_index(name="cases_handled")
    )
    role_activities_performed = (
        df.groupby(ROLE_COL)[ACTIVITY_COL].count().reset_index(name="activities_performed")
    )
    # Per-event average duration (different grain than x_role above -- this
    # is "how long is a typical single step for this role", used to rank
    # roles by step-level slowness; x_role is "how much total time does
    # this role spend per case", used for the FTE calculation).
    role_avg_event_duration = (
        df.groupby(ROLE_COL)[STEP_DURATION_COL].mean().reset_index(name="avg_step_duration_hours")
    )

    role_workload = (
        role_cases
        .merge(role_avg_hours_per_case, on=ROLE_COL, how="left")
        .merge(role_activities_performed, on=ROLE_COL, how="left")
        .merge(role_avg_event_duration, on=ROLE_COL, how="left")
    )
    role_workload["avg_hours_per_case"] = role_workload["avg_hours_per_case"].fillna(0.0)

    # CR-02 FTE formula.
    role_workload["fte"] = (
        role_workload["avg_hours_per_case"]
        / FTE_HOURS_PER_DAY
        / FTE_WORKING_DAYS_PER_MONTH
        * FTE_ABSENCE_FACTOR
    )
    role_workload = role_workload.sort_values("cases_handled", ascending=False)

    # CR-02 4.5: Average FTE per Case = sum of FTE_role across all roles
    # involved in the process (an estimate of the total FTE resource needed
    # to handle one average case, NOT a headcount of distinct people/roles).
    avg_fte_per_case = float(role_workload["fte"].sum())

    return {
        "role_activity": role_activity,
        "role_workload": role_workload,
        "avg_fte_per_case": avg_fte_per_case,
    }


def calculate_region_statistics(
    df: pd.DataFrame, case_times: pd.DataFrame
) -> Optional[Dict[str, object]]:
    """
    CR-01: pure aggregation of region-level Lead Time / Waiting Time /
    Workload / Activity data -- the SSOT tables that `analytics.
    region_analysis` builds Rework/Bottleneck attribution, Leader/Outsider
    ranking, pattern detection and recommendations from.

    Returns None when the event log has no 'Region' column (CR-01 3.2
    visibility condition).

    Missing/empty Region values are treated as a normal region named
    "Unknown" (CR-01 3.2) rather than dropped from the analysis.

    Sec. 4 data-quality rule: a case is expected to have exactly one Region
    across all its events. If a Case ID has more than one distinct Region
    value, that is a data-quality issue, not something to resolve silently
    by picking whichever value happens to come first -- the whole case is
    reassigned to "Unknown" instead, and the number of affected cases is
    reported back via `inconsistent_region_cases_count` so it's visible to
    whoever reviews the analysis rather than hidden inside an arbitrary
    per-case choice.
    """
    if REGION_COL not in df.columns:
        return None

    df = df.copy()
    df[REGION_COL] = df[REGION_COL].fillna("Unknown")
    df.loc[df[REGION_COL].astype(str).str.strip() == "", REGION_COL] = "Unknown"

    # Sec. 4: a case is assumed to have a single Region. Detect violations of
    # that assumption instead of silently picking an arbitrary value with
    # .first(). Documented deterministic rule: any Case ID that has more
    # than one distinct Region value across its events is reassigned to
    # "Unknown" in full (not just the conflicting rows), since we cannot
    # know which of the conflicting values is authoritative for that case.
    region_counts_per_case = df.groupby(CASE_ID_COL)[REGION_COL].nunique()
    inconsistent_case_ids = region_counts_per_case[region_counts_per_case > 1].index
    inconsistent_region_cases_count = len(inconsistent_case_ids)

    case_region = df.groupby(CASE_ID_COL)[REGION_COL].first().reset_index()
    if inconsistent_region_cases_count:
        case_region.loc[
            case_region[CASE_ID_COL].isin(inconsistent_case_ids), REGION_COL
        ] = "Unknown"

    region_case_times = case_times.merge(case_region, on=CASE_ID_COL, how="left")
    region_case_times[REGION_COL] = region_case_times[REGION_COL].fillna("Unknown")

    # --- Lead Time (CR-01 3.3): num cases, avg/median/min/max ---
    region_lead_time = (
        region_case_times.groupby(REGION_COL)
        .agg(
            num_cases=(CASE_ID_COL, "count"),
            avg_lead_time=("Lead Time", "mean"),
            median_lead_time=("Lead Time", "median"),
            min_lead_time=("Lead Time", "min"),
            max_lead_time=("Lead Time", "max"),
        )
        .reset_index()
        .sort_values("avg_lead_time", ascending=False)
    )

    # --- Region + Activity grain (bottleneck attribution / most-critical
    # steps) -- single aggregation pass, reused by analytics.region_analysis
    # rather than recomputed there. ---
    region_activity = (
        df.groupby([REGION_COL, ACTIVITY_COL])
        .agg(
            occurrences=(ACTIVITY_COL, "count"),
            avg_duration_hours=(STEP_DURATION_COL, "mean"),
            total_duration_hours=(STEP_DURATION_COL, "sum"),
        )
        .reset_index()
    )

    # --- Waiting Time (CR-01 3.3): avg + median ---
    if WAITING_COL in df.columns:
        region_waiting = (
            df.groupby(REGION_COL)[WAITING_COL]
            .agg(["mean", "median"])
            .rename(columns={"mean": "avg_waiting_hours", "median": "median_waiting_hours"})
            .reset_index()
        )
    else:
        region_waiting = pd.DataFrame(
            {REGION_COL: region_lead_time[REGION_COL], "avg_waiting_hours": 0.0, "median_waiting_hours": 0.0}
        )

    # --- Workload (CR-01 3.3): total activities, avg per case, share of
    # total case/activity volume across the whole dataset. ---
    total_activities_all = len(df)
    total_cases_all = len(case_times)

    region_workload = df.groupby(REGION_COL)[ACTIVITY_COL].count().reset_index(name="total_activities")
    region_num_cases = region_case_times.groupby(REGION_COL)[CASE_ID_COL].nunique().reset_index(name="num_cases")
    region_workload = region_workload.merge(region_num_cases, on=REGION_COL, how="left")
    region_workload["avg_activities_per_case"] = (
        region_workload["total_activities"] / region_workload["num_cases"].replace(0, pd.NA)
    )
    region_workload["share_of_total_activities_pct"] = (
        (region_workload["total_activities"] / total_activities_all * 100).round(1)
        if total_activities_all else 0.0
    )
    region_workload["share_of_total_cases_pct"] = (
        (region_workload["num_cases"] / total_cases_all * 100).round(1)
        if total_cases_all else 0.0
    )

    return {
        "case_region": case_region,
        "region_case_times": region_case_times,
        "region_lead_time": region_lead_time,
        "region_activity": region_activity,
        "region_waiting": region_waiting,
        "region_workload": region_workload,
        "inconsistent_region_cases_count": inconsistent_region_cases_count,
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

"""
analytics.py
------------
Pure computation functions for the Process Mining app. No Streamlit calls
live here -- every function takes plain pandas objects (mostly the
centralized `case_times` / `activity_statistics` tables produced by
`case_metrics.py`) and returns plain Python / pandas objects.

FR-2/FR-3/FR-4: every function below that used to run its own
`groupby("Case ID")` to re-derive case duration / lead time / waiting time
now takes the already-computed `case_times` table instead. The only
`groupby` calls left in this module are for aggregations that are
genuinely different from case-level metrics (rework counts per
Case+Activity, transition/edge statistics, variant path strings) -- see
Sec. 6 of the requirements ("repeated groupby() operations are acceptable
only when implementing fundamentally different analytical logic").
"""

from typing import Any, Dict, List, Optional

import pandas as pd

CASE_ID_COL = "Case ID"
ACTIVITY_COL = "Activity Name"
START_COL = "Start Timestamp"
FINISH_COL = "Finish Timestamp"
ROLE_COL = "Role"
REGION_COL = "Region"


# ---------------------------------------------------------------------------
# General statistics (FR-4: reuses case_times, does not recompute it)
# ---------------------------------------------------------------------------
def general_statistics(case_times: pd.DataFrame) -> Dict[str, Any]:
    """High-level KPIs shown at the top of the report.

    FR-4: `general_statistics` no longer calculates `case_times` itself --
    it receives the already-prepared table from `case_metrics.py`.
    """
    return {
        "num_cases": len(case_times),
        "start_period": case_times[START_COL].min(),
        "end_period": case_times[FINISH_COL].max(),
        "case_times": case_times,
        "avg_duration": case_times["Duration (hours)"].mean(),
        "median_duration": case_times["Duration (hours)"].median(),
        "avg_activities": case_times["Number of Activities"].mean(),
    }


def start_end_activities(df: pd.DataFrame) -> Dict[str, Any]:
    """Most common start/end activities. Operates on individual events
    (first/last event per case), which is a different grain than
    `case_times` and cannot be derived from it, so it keeps its own
    lightweight groupby."""
    df_sorted = df.sort_values(START_COL).groupby(CASE_ID_COL)

    most_common_start = df_sorted.head(1)[ACTIVITY_COL].value_counts().idxmax()
    last_activities = df_sorted.tail(1)[ACTIVITY_COL].value_counts()
    most_common_end = last_activities.idxmax()
    top_end_activities = last_activities.head(10)

    return {
        "most_common_start": most_common_start,
        "most_common_end": most_common_end,
        "top_end_activities": top_end_activities,
    }


# ---------------------------------------------------------------------------
# Rework analysis
# ---------------------------------------------------------------------------
def rework_analysis(df: pd.DataFrame, case_times: pd.DataFrame) -> Dict[str, Any]:
    """Repeated-activity ("rework") analysis. This aggregates at the
    Case+Activity grain (activity occurrence counts within a case), which is
    fundamentally different from case-level metrics, so it is not derivable
    from `case_times` and keeps its own groupby."""
    activity_counts = (
        df.groupby([CASE_ID_COL, ACTIVITY_COL]).size().reset_index(name="occurrences")
    )

    rework_only = activity_counts[activity_counts["occurrences"] > 1].copy()
    rework_only["rework_times"] = rework_only["occurrences"] - 1

    top_rework = (
        rework_only.groupby(ACTIVITY_COL)["rework_times"].mean().reset_index()
    )
    top_rework = (
        top_rework[top_rework["rework_times"] > 1]
        .sort_values(by="rework_times", ascending=False)
        .assign(rework_times=lambda x: x["rework_times"].round(1))
        .rename(columns={"rework_times": "середня кількість повторів на кейс"})
    )

    cases_with_rework_list = rework_only[CASE_ID_COL].unique()
    total_rework_cases = len(cases_with_rework_list)
    total_cases = len(case_times)  # FR-2: reuse case_times instead of df.nunique()
    percent_rework = round((total_rework_cases / total_cases) * 100, 2) if total_cases else 0.0

    return {
        "activity_counts": activity_counts,
        "rework_only": rework_only,
        "top_rework": top_rework,
        "cases_with_rework_list": cases_with_rework_list,
        "total_rework_cases": total_rework_cases,
        "total_cases": total_cases,
        "percent_rework": percent_rework,
    }


# ---------------------------------------------------------------------------
# Lead time / waiting time vs. rework comparison
# ---------------------------------------------------------------------------
def lead_time_rework_comparison(
    case_times: pd.DataFrame, cases_with_rework_list
) -> Dict[str, Any]:
    """FR-3: Lead Time and Waiting Time per case are derived directly from
    `case_times` -- no independent recomputation from raw timestamps."""
    lead_time_per_case = case_times[[CASE_ID_COL, "Lead Time"]].rename(
        columns={"Lead Time": "lead_time"}
    )
    lead_time_per_case["rework"] = lead_time_per_case[CASE_ID_COL].isin(cases_with_rework_list)
    lead_time_per_case["rework_label"] = lead_time_per_case["rework"].map(
        {True: "З повтореннями", False: "Без повторень"}
    )

    waiting_time_per_case = case_times[[CASE_ID_COL, "Waiting Time"]].rename(
        columns={"Waiting Time": "waiting_time_hrs"}
    )

    is_rework = lead_time_per_case["rework"]
    mean_lead_rework = lead_time_per_case.loc[is_rework, "lead_time"].mean()
    mean_lead_no_rework = lead_time_per_case.loc[~is_rework, "lead_time"].mean()

    mean_wait_rework = waiting_time_per_case.loc[is_rework, "waiting_time_hrs"].mean()
    mean_wait_no_rework = waiting_time_per_case.loc[~is_rework, "waiting_time_hrs"].mean()

    return {
        "lead_time_per_case": lead_time_per_case,
        "waiting_time_per_case": waiting_time_per_case,
        "mean_lead_rework": mean_lead_rework,
        "mean_lead_no_rework": mean_lead_no_rework,
        "mean_wait_rework": mean_wait_rework,
        "mean_wait_no_rework": mean_wait_no_rework,
    }


# ---------------------------------------------------------------------------
# Step duration / bottleneck (bubble chart) analysis
# ---------------------------------------------------------------------------
def step_duration_analysis(activity_statistics: pd.DataFrame) -> Dict[str, Any]:
    """FR-7: consumes the pre-aggregated `activity_statistics` table
    (case_metrics.calculate_activity_statistics) instead of re-running the
    Case+Activity groupby itself."""
    analysis_df = (
        activity_statistics.groupby(ACTIVITY_COL)
        .agg(
            avg_duration=("duration_hours", "mean"),
            avg_count=("count", "mean"),
            impact=("duration_hours", "sum"),
        )
        .reset_index()
    )

    # CR-02: criticality score for bubble-label thresholding (Pareto 80/20).
    # Kept as its own column rather than overwriting `impact` (which drives
    # bubble size/color and bottleneck ranking elsewhere) to avoid changing
    # any existing KPI/bottleneck-selection behavior.
    analysis_df["criticality_score"] = analysis_df["avg_duration"] * analysis_df["avg_count"]

    x_mean = analysis_df["avg_duration"].mean()
    y_mean = analysis_df["avg_count"].mean()

    bottlenecks = analysis_df[
        (analysis_df["avg_duration"] > x_mean) & (analysis_df["avg_count"] > y_mean)
    ].sort_values("impact", ascending=False)

    top_step = bottlenecks.iloc[0] if not bottlenecks.empty else None

    return {
        "analysis_df": analysis_df,
        "x_mean": x_mean,
        "y_mean": y_mean,
        "bottlenecks": bottlenecks,
        "top_step": top_step,
    }


# ---------------------------------------------------------------------------
# Transition / waiting-time (Heuristics Miner edge) analysis
# ---------------------------------------------------------------------------
def transitions_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Builds Activity -> next Activity edge statistics.

    FR-2: the per-edge waiting time reuses the centrally computed
    `waiting_hours` column (Start(i) - Finish(i-1), from
    data_processing.prepare_dataframe) instead of re-subtracting
    timestamps. `waiting_hours` is defined as the wait *before* an event, so
    shifting it back by one position within each case gives exactly the
    wait *between* an event and the next one -- i.e. the edge weight -- with
    no second timestamp subtraction needed.
    """
    df_sorted = df.sort_values([CASE_ID_COL, START_COL]).copy()

    df_sorted["next_activity"] = df_sorted.groupby(CASE_ID_COL)[ACTIVITY_COL].shift(-1)
    df_sorted["waiting_time_hours"] = df_sorted.groupby(CASE_ID_COL)["waiting_hours"].shift(-1)

    transitions = df_sorted.dropna(subset=["next_activity"])

    edges = (
        transitions.groupby([ACTIVITY_COL, "next_activity"])
        .agg(frequency=(CASE_ID_COL, "count"), avg_waiting=("waiting_time_hours", "mean"))
        .reset_index()
    )

    if edges.empty:
        # No case has more than one activity, so there are no transitions to
        # analyze (e.g. a degenerate/tiny event log). Return an empty-but-
        # well-formed result instead of crashing on idxmax() of an empty
        # series -- every downstream consumer (heuristics graph, executive
        # summary, PDF) only needs these keys to exist with sane defaults.
        empty_bottleneck_row = pd.Series(
            {ACTIVITY_COL: "—", "next_activity": "—", "avg_waiting": 0.0, "frequency": 0}
        )
        edges = edges.assign(penwidth=[], cumsum_waiting=[], cumsum_ratio=[], color=[])
        return {
            "edges": edges,
            "bottleneck_row": empty_bottleneck_row,
            "bottleneck_text": (
                "Недостатньо даних для аналізу переходів: жоден кейс не містить "
                "більше однієї активності."
            ),
        }

    bottleneck_row = edges.loc[edges["avg_waiting"].idxmax()]

    edges["penwidth"] = (edges["frequency"] / edges["frequency"].max() * 5).clip(lower=1)

    total_waiting = edges["avg_waiting"].sum()
    edges = edges.sort_values("avg_waiting", ascending=False).reset_index(drop=True)
    edges["cumsum_waiting"] = edges["avg_waiting"].cumsum()
    edges["cumsum_ratio"] = edges["cumsum_waiting"] / total_waiting if total_waiting else 0

    def pareto_color(cumsum_ratio: float) -> str:
        if cumsum_ratio <= 0.8:
            return "red"
        elif cumsum_ratio <= 0.95:
            return "orange"
        return "green"

    edges["color"] = edges["cumsum_ratio"].apply(pareto_color)

    bottleneck_text = (
        f"Найбільший bottleneck: "
        f"{bottleneck_row[ACTIVITY_COL]} → {bottleneck_row['next_activity']} "
        f"(середній час: {bottleneck_row['avg_waiting']:.2f} год, "
        f"частота: {bottleneck_row['frequency']})"
    )

    return {
        "edges": edges,
        "bottleneck_row": bottleneck_row,
        "bottleneck_text": bottleneck_text,
    }


# ---------------------------------------------------------------------------
# Variant analysis
# ---------------------------------------------------------------------------
def variant_analysis(df: pd.DataFrame, case_times: pd.DataFrame) -> Dict[str, Any]:
    """Builds the sequence-of-activities "variant" per case. This requires
    the ordered event sequence itself, which is not present in `case_times`,
    so it keeps its own groupby -- but reuses `case_times` for the case
    count instead of a second `nunique()` pass."""
    variants = (
        df.sort_values(START_COL)
        .groupby(CASE_ID_COL)[ACTIVITY_COL]
        .apply(lambda x: " → ".join(x))
    )

    total_cases = len(case_times)
    unique_variants = variants.nunique()

    variant_counts_full = variants.value_counts()
    variant_counts_top5 = variant_counts_full.head(5)

    variant_counts = variant_counts_top5.reset_index()
    variant_counts.columns = ["Сценарій процесу", "Кількість кейсів"]

    top1_share = variant_counts_full.iloc[0] / total_cases * 100
    top5_share = variant_counts_top5.sum() / total_cases * 100

    if unique_variants == 1:
        conclusion = "Процес повністю стандартизований. Всі кейси проходять однаковий сценарій."
    elif top1_share > 70:
        conclusion = (
            "Процес переважно стандартизований. "
            "Більшість кейсів слідують одному основному сценарію."
        )
    elif top5_share > 70:
        conclusion = (
            "Процес має помірну варіабельність. "
            "Існує кілька домінуючих сценаріїв."
        )
    else:
        conclusion = (
            "Процес характеризується високою варіабельністю. "
            "Велика кількість альтернативних сценаріїв може свідчити "
            "про нестандартизовані процедури або виняткові кейси."
        )

    # Req 2 / Sec 10.3: per-Top-5-variant average Lead Time, computed once
    # here (both `variants` and `case_times` are already available in this
    # function) so the Improvement Roadmap can quantify "benchmark variant
    # vs inefficient variant" impact from a real in-dataset comparison
    # instead of an assumption.
    case_lead_time = case_times.set_index(CASE_ID_COL)["Lead Time"]
    variant_lead_time_top5 = (
        case_lead_time.reindex(variants.index)
        .groupby(variants.values)
        .mean()
        .reindex(variant_counts_top5.index)
    )

    return {
        "variants": variants,
        "total_cases": total_cases,
        "unique_variants": unique_variants,
        "variant_counts": variant_counts,
        "variant_counts_full": variant_counts_full,
        "variant_lead_time_top5": variant_lead_time_top5,
        "top1_share": top1_share,
        "top5_share": top5_share,
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# CR-05: Role analysis (only meaningful when the event log has a 'Role'
# column -- role_statistics is None otherwise, and this function mirrors
# that by returning None so the section is skipped end-to-end).
# ---------------------------------------------------------------------------
def role_analysis(
    df: pd.DataFrame,
    role_statistics: Optional[Dict[str, Any]],
    rework: Dict[str, Any],
    step_analysis: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if role_statistics is None:
        return None

    role_activity = role_statistics["role_activity"]
    role_workload = role_statistics["role_workload"]
    # CR-02: this is now the real FTE-based estimate (sum of FTE_role across
    # roles), not the previous avg-distinct-roles-per-case proxy.
    avg_fte_per_case = role_statistics["avg_fte_per_case"]

    # Bottleneck Analysis: which roles perform the bottleneck activities
    # identified by step_duration_analysis (reused, not recomputed).
    bottleneck_activities = (
        set(step_analysis["bottlenecks"][ACTIVITY_COL])
        if not step_analysis["bottlenecks"].empty
        else set()
    )
    role_bottleneck = role_activity[role_activity[ACTIVITY_COL].isin(bottleneck_activities)]
    role_bottleneck_ranking = (
        role_bottleneck.groupby(ROLE_COL)["occurrences"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        if not role_bottleneck.empty
        else pd.DataFrame(columns=[ROLE_COL, "occurrences"])
    )

    longest_duration_roles = role_workload.sort_values(
        "avg_step_duration_hours", ascending=False
    )

    # Rework Analysis: attribute repeated (Case ID, Activity Name) pairs
    # (already computed in rework_analysis, not recomputed here) to whichever
    # Role performed them.
    rework_only = rework["rework_only"]
    if not rework_only.empty and ROLE_COL in df.columns:
        role_lookup = df[[CASE_ID_COL, ACTIVITY_COL, ROLE_COL]].drop_duplicates(
            subset=[CASE_ID_COL, ACTIVITY_COL]
        )
        rework_with_role = rework_only.merge(
            role_lookup, on=[CASE_ID_COL, ACTIVITY_COL], how="left"
        )
        role_rework_ranking = (
            rework_with_role.groupby(ROLE_COL)["rework_times"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
    else:
        role_rework_ranking = pd.DataFrame(columns=[ROLE_COL, "rework_times"])

    top_bottleneck_role = (
        role_bottleneck_ranking.iloc[0][ROLE_COL] if not role_bottleneck_ranking.empty else None
    )
    top_rework_role = (
        role_rework_ranking.iloc[0][ROLE_COL] if not role_rework_ranking.empty else None
    )
    top_fte_role = (
        role_workload.sort_values("fte", ascending=False).iloc[0][ROLE_COL]
        if not role_workload.empty else None
    )

    return {
        "role_activity": role_activity,
        "role_workload": role_workload,
        "avg_fte_per_case": avg_fte_per_case,
        "role_bottleneck_ranking": role_bottleneck_ranking,
        "longest_duration_roles": longest_duration_roles,
        "role_rework_ranking": role_rework_ranking,
        "top_bottleneck_role": top_bottleneck_role,
        "top_rework_role": top_rework_role,
        "top_fte_role": top_fte_role,
    }


# ---------------------------------------------------------------------------
# CR-01: Regional analysis (only meaningful when the event log has a
# 'Region' column -- region_statistics is None otherwise). Missing/empty
# Region values are folded into an "Unknown" region by case_metrics rather
# than dropped (CR-01 3.2).
# ---------------------------------------------------------------------------
def region_analysis(
    region_statistics: Optional[Dict[str, Any]],
    rework: Dict[str, Any],
    step_analysis: Dict[str, Any],
    case_times: Optional[pd.DataFrame] = None,
) -> Optional[Dict[str, Any]]:
    if region_statistics is None:
        return None

    case_region = region_statistics["case_region"]
    region_lead_time = region_statistics["region_lead_time"]
    region_activity = region_statistics["region_activity"]
    region_waiting = region_statistics["region_waiting"]
    region_workload = region_statistics["region_workload"]

    # --- Rework (CR-01 3.3): reuse the case-level rework flag from
    # rework_analysis instead of recomputing which cases had rework. ---
    cases_with_rework_list = rework["cases_with_rework_list"]
    case_region_rework = case_region.copy()
    case_region_rework["has_rework"] = case_region_rework[CASE_ID_COL].isin(
        cases_with_rework_list
    )
    region_rework = (
        case_region_rework.groupby(REGION_COL)
        .agg(rework_cases=("has_rework", "sum"), total_cases=(CASE_ID_COL, "count"))
        .reset_index()
    )
    region_rework["rework_rate_pct"] = (
        region_rework["rework_cases"] / region_rework["total_cases"] * 100
    ).round(2)

    # --- Bottlenecks (CR-01 3.3): reuse the bottleneck activity list from
    # step_duration_analysis instead of recomputing it. For each region:
    # number of distinct bottleneck activities, total occurrences, the most
    # critical bottleneck step, and the region's share of all bottleneck
    # occurrences dataset-wide. ---
    bottleneck_activities = (
        set(step_analysis["bottlenecks"][ACTIVITY_COL])
        if not step_analysis["bottlenecks"].empty
        else set()
    )
    region_bottleneck = region_activity[region_activity[ACTIVITY_COL].isin(bottleneck_activities)]
    if not region_bottleneck.empty:
        region_bottleneck_ranking = (
            region_bottleneck.groupby(REGION_COL)
            .agg(
                occurrences=("occurrences", "sum"),
                num_bottleneck_activities=(ACTIVITY_COL, "nunique"),
            )
            .reset_index()
            .sort_values("occurrences", ascending=False)
        )
        # Most critical bottleneck step per region = highest total time
        # impact (occurrences * avg_duration_hours) within that region.
        region_bottleneck = region_bottleneck.copy()
        region_bottleneck["impact_hours"] = (
            region_bottleneck["occurrences"] * region_bottleneck["avg_duration_hours"]
        )
        top_step_idx = region_bottleneck.groupby(REGION_COL)["impact_hours"].idxmax()
        most_critical_by_region = region_bottleneck.loc[
            top_step_idx, [REGION_COL, ACTIVITY_COL, "avg_duration_hours"]
        ].rename(columns={ACTIVITY_COL: "top_bottleneck_activity"})
        region_bottleneck_ranking = region_bottleneck_ranking.merge(
            most_critical_by_region, on=REGION_COL, how="left"
        )
    else:
        region_bottleneck_ranking = pd.DataFrame(
            columns=[REGION_COL, "occurrences", "num_bottleneck_activities",
                     "top_bottleneck_activity", "avg_duration_hours"]
        )

    total_bottleneck_occurrences = (
        region_bottleneck_ranking["occurrences"].sum()
        if not region_bottleneck_ranking.empty
        else 0
    )
    region_bottleneck_ranking["share_pct"] = (
        (region_bottleneck_ranking["occurrences"] / total_bottleneck_occurrences * 100).round(1)
        if total_bottleneck_occurrences
        else 0
    )

    # --- Baseline for regional comparison (CR-01 3.5): overall average /
    # median across the WHOLE dataset, reusing case_times / rework /
    # step_analysis rather than recomputing anything. ---
    if case_times is not None and not case_times.empty:
        overall_avg_lead_time = case_times["Lead Time"].mean()
        overall_median_lead_time = case_times["Lead Time"].median()
        overall_avg_waiting = case_times["Waiting Time"].mean()
    else:
        overall_avg_lead_time = region_lead_time["avg_lead_time"].mean()
        overall_median_lead_time = region_lead_time["median_lead_time"].mean()
        overall_avg_waiting = region_waiting["avg_waiting_hours"].mean()
    overall_rework_rate = rework["percent_rework"]

    baseline = {
        "avg_lead_time": overall_avg_lead_time,
        "median_lead_time": overall_median_lead_time,
        "rework_rate_pct": overall_rework_rate,
        "avg_waiting_hours": overall_avg_waiting,
    }

    # --- Combined per-region table used for composite ranking + comparison
    # flags (CR-01 3.4/3.5): join every metric table on Region exactly once. ---
    combined = (
        region_lead_time
        .merge(region_rework[[REGION_COL, "rework_rate_pct", "rework_cases", "total_cases"]],
               on=REGION_COL, how="left")
        .merge(region_waiting, on=REGION_COL, how="left")
        .merge(region_workload, on=REGION_COL, how="left", suffixes=("", "_wl"))
    )
    if not region_bottleneck_ranking.empty:
        combined = combined.merge(
            region_bottleneck_ranking[[REGION_COL, "share_pct"]].rename(
                columns={"share_pct": "bottleneck_share_pct"}
            ),
            on=REGION_COL, how="left",
        )
    else:
        combined["bottleneck_share_pct"] = 0.0
    combined["bottleneck_share_pct"] = combined["bottleneck_share_pct"].fillna(0.0)

    # CR-01 3.5: flag regions materially (>20%) above the dataset-wide
    # average/median on each metric.
    def _flag_high(series: pd.Series, baseline_value: float, margin: float = 0.20) -> pd.Series:
        if not baseline_value:
            return pd.Series(False, index=series.index)
        return series > baseline_value * (1 + margin)

    combined["high_lead_time_flag"] = _flag_high(combined["avg_lead_time"], overall_avg_lead_time)
    combined["high_rework_flag"] = _flag_high(combined["rework_rate_pct"], overall_rework_rate)
    combined["high_waiting_flag"] = _flag_high(combined["avg_waiting_hours"], overall_avg_waiting)
    combined["high_bottleneck_flag"] = combined["bottleneck_share_pct"] > (
        100 / max(len(combined), 1) * 1.5
    )
    combined["high_workload_flag"] = _flag_high(
        combined["total_activities"], combined["total_activities"].mean()
    )

    # --- Leaders / Outsiders (Sec. 7): primarily Average Lead Time, but
    # adjusted by Rework Rate, Waiting Time, and Bottleneck concentration via
    # a composite rank (lower composite = better). Lead Time is weighted x2
    # since it's the default/primary criterion; Rework, Waiting Time, and
    # Bottleneck share all factor in as required by the spec so a region
    # can't be crowned "best" purely for having the lowest Lead Time while
    # being terrible on every other metric. ---
    if not combined.empty:
        combined["lead_time_rank"] = combined["avg_lead_time"].rank(method="min")
        combined["rework_rank"] = combined["rework_rate_pct"].rank(method="min")
        combined["waiting_rank"] = combined["avg_waiting_hours"].rank(method="min")
        combined["bottleneck_rank"] = combined["bottleneck_share_pct"].rank(method="min")
        combined["composite_score"] = (
            combined["lead_time_rank"] * 2
            + combined["rework_rank"]
            + combined["waiting_rank"]
            + combined["bottleneck_rank"]
        )
        leader = combined.sort_values("composite_score", ascending=True).iloc[0]
        outsider = combined.sort_values("composite_score", ascending=False).iloc[0]
        if leader[REGION_COL] == outsider[REGION_COL] and len(combined) > 1:
            outsider = combined.sort_values("composite_score", ascending=False).iloc[1]
    else:
        leader = None
        outsider = None

    # --- Pattern Detection / Automated Insights (CR-01 3.6): dynamic,
    # numbers-driven sentences, not hardcoded examples. ---
    insights: List[str] = []
    recommendations: List[str] = []

    if leader is not None:
        pct_below = (
            (overall_avg_lead_time - leader["avg_lead_time"]) / overall_avg_lead_time * 100
            if overall_avg_lead_time else 0
        )
        if pct_below > 1:
            insights.append(
                f"Регіон {leader[REGION_COL]} має Lead Time на {pct_below:.0f}% нижчий "
                f"за середній показник по процесу ({leader['avg_lead_time']:.2f} год "
                f"проти {overall_avg_lead_time:.2f} год)."
            )
        else:
            insights.append(
                f"Регіон {leader[REGION_COL]} демонструє найкращі показники Lead Time "
                f"({leader['avg_lead_time']:.2f} год)."
            )
        recommendations.append(
            f"Порівняти практики відстаючого регіону з регіоном {leader[REGION_COL]} "
            "та тиражувати найкращі підходи."
        )

    if outsider is not None and (leader is None or outsider[REGION_COL] != leader[REGION_COL]):
        pct_above = (
            (outsider["avg_lead_time"] - overall_avg_lead_time) / overall_avg_lead_time * 100
            if overall_avg_lead_time else 0
        )
        if pct_above > 1:
            insights.append(
                f"Регіон {outsider[REGION_COL]} має Lead Time на {pct_above:.0f}% вищий "
                f"за середній показник по процесу ({outsider['avg_lead_time']:.2f} год "
                f"проти {overall_avg_lead_time:.2f} год)."
            )
        else:
            insights.append(
                f"Регіон {outsider[REGION_COL]} демонструє найгірші показники Lead Time "
                f"({outsider['avg_lead_time']:.2f} год)."
            )
        recommendations.append(
            f"Дослідити причини високого Lead Time в регіоні {outsider[REGION_COL]}."
        )

    if not region_rework.empty:
        worst_rework = region_rework.sort_values("rework_rate_pct", ascending=False).iloc[0]
        pct_points_above = worst_rework["rework_rate_pct"] - overall_rework_rate
        if pct_points_above > 1:
            insights.append(
                f"Регіон {worst_rework[REGION_COL]} має найвищу частку rework "
                f"({worst_rework['rework_rate_pct']}%), що на {pct_points_above:.0f} "
                "в.п. вище за середній показник по процесу."
            )
        else:
            insights.append(
                f"Регіон {worst_rework[REGION_COL]} має найвищу частку rework "
                f"({worst_rework['rework_rate_pct']}%)."
            )
        if worst_rework["rework_rate_pct"] > overall_rework_rate * 1.2:
            recommendations.append(
                f"Провести Root Cause Analysis повторюваних кроків у регіоні "
                f"{worst_rework[REGION_COL]}."
            )

    if not region_bottleneck_ranking.empty:
        top_bn = region_bottleneck_ranking.sort_values("share_pct", ascending=False).iloc[0]
        insights.append(
            f"{top_bn['share_pct']}% усіх виявлених bottleneck-активностей "
            f"зосереджено в регіоні {top_bn[REGION_COL]}"
            + (
                f" (найкритичніший крок: {top_bn['top_bottleneck_activity']})."
                if pd.notna(top_bn.get("top_bottleneck_activity"))
                else "."
            )
        )
        recommendations.append(
            f"Дослідити bottleneck-активності в регіоні {top_bn[REGION_COL]}"
            + (
                f", зокрема крок «{top_bn['top_bottleneck_activity']}»."
                if pd.notna(top_bn.get("top_bottleneck_activity"))
                else "."
            )
        )

    if not region_waiting.empty:
        worst_waiting = region_waiting.sort_values("avg_waiting_hours", ascending=False).iloc[0]
        insights.append(
            f"Регіон {worst_waiting[REGION_COL]} має найвищий Waiting Time "
            f"({worst_waiting['avg_waiting_hours']:.2f} год очікування на крок), "
            "що може свідчити про проблеми передачі роботи між ролями (handoffs)."
        )
        if worst_waiting["avg_waiting_hours"] > overall_avg_waiting * 1.2:
            recommendations.append(
                f"Проаналізувати передачу завдань між ролями (handoffs) у регіоні "
                f"{worst_waiting[REGION_COL]}."
            )

    if not region_workload.empty:
        busiest = region_workload.sort_values("total_activities", ascending=False).iloc[0]
        insights.append(
            f"Найбільша концентрація робочого навантаження — у регіоні {busiest[REGION_COL]} "
            f"({busiest['share_of_total_activities_pct']}% усіх активностей, "
            f"{busiest['share_of_total_cases_pct']}% усіх кейсів)."
        )

    # Pattern 6 (Sec. 9): Best Practice Region -- consistently strong across
    # ALL FOUR metrics simultaneously (not just the single-metric "leader"),
    # so it's meaningfully different from just having the lowest Lead Time.
    best_practice_region = None
    if not combined.empty:
        below_avg_all = combined[
            ~combined["high_lead_time_flag"]
            & ~combined["high_rework_flag"]
            & ~combined["high_waiting_flag"]
            & ~combined["high_bottleneck_flag"]
        ]
        if not below_avg_all.empty:
            best_practice_region = below_avg_all.sort_values("composite_score", ascending=True).iloc[0]
            insights.append(
                f"Регіон {best_practice_region[REGION_COL]} демонструє стабільно високі "
                "показники одразу за кількома метриками (Lead Time, Rework Rate, Waiting "
                "Time, Bottleneck concentration — усі нижче середнього по процесу) і може "
                "слугувати еталоном (best practice)."
            )
            recommendations.append(
                f"Проаналізувати та задокументувати практики регіону "
                f"{best_practice_region[REGION_COL]} для тиражування в інших регіонах."
            )

    if not insights:
        insights.append("Недостатньо даних для формування регіональних висновків.")
    if not recommendations:
        recommendations.append("Недостатньо даних для формування регіональних рекомендацій.")

    # --- Regional KPI Summary (Sec. 13.1 / 14.1): a single small dict with
    # exactly the six headline numbers the UI and PDF both need, computed
    # once here so neither layer has to re-derive "highest rework region" /
    # "highest bottleneck region" etc. on its own. ---
    highest_rework_region = (
        region_rework.sort_values("rework_rate_pct", ascending=False).iloc[0][REGION_COL]
        if not region_rework.empty else None
    )
    highest_bottleneck_region = (
        region_bottleneck_ranking.sort_values("share_pct", ascending=False).iloc[0][REGION_COL]
        if not region_bottleneck_ranking.empty else None
    )
    kpi_summary = {
        "num_regions": len(region_lead_time),
        "best_region": leader[REGION_COL] if leader is not None else None,
        "worst_region": outsider[REGION_COL] if outsider is not None else None,
        "overall_avg_lead_time": overall_avg_lead_time,
        "highest_rework_region": highest_rework_region,
        "highest_bottleneck_region": highest_bottleneck_region,
        "best_practice_region": (
            best_practice_region[REGION_COL] if best_practice_region is not None else None
        ),
    }

    return {
        "region_lead_time": region_lead_time,
        "region_activity": region_activity,
        "region_rework": region_rework,
        "region_bottleneck_ranking": region_bottleneck_ranking,
        "region_waiting": region_waiting,
        "region_workload": region_workload,
        "combined": combined,
        "baseline": baseline,
        "leader": leader,
        "outsider": outsider,
        "best_practice_region": best_practice_region,
        "kpi_summary": kpi_summary,
        "insights": insights,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Executive summary, recommendations, maturity score
# ---------------------------------------------------------------------------
def build_executive_summary(
    percent_rework: float,
    mean_lead_rework: float,
    mean_lead_no_rework: float,
    bottlenecks: pd.DataFrame,
    top_step: Optional[pd.Series],
    bottleneck_row: pd.Series,
    unique_variants: int,
    total_cases: int,
    top1_share: float,
    maturity_score: int,
    role_analysis_result: Optional[Dict[str, Any]] = None,
    region_analysis_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    lead_diff = mean_lead_rework - mean_lead_no_rework

    # Req 6: the standalone "AI Process Narrative" block is removed; the one
    # piece of it not already covered elsewhere in this summary -- the
    # overall maturity-level framing sentence -- is folded in here instead
    # of being silently dropped.
    if maturity_score > 80:
        maturity_level = "високим рівнем операційної стабільності"
    elif maturity_score > 50:
        maturity_level = "помірною структурною зрілістю"
    else:
        maturity_level = "операційною нестабільністю"
    summary_text = (
        f"Процес характеризується {maturity_level} "
        f"(Process Maturity Score: {maturity_score}/100).\n\n"
    )

    if percent_rework > 30:
        summary_text += (
            f"🔁 Значна частка кейсів ({percent_rework}%) містить повторювані кроки. "
            f"Rework збільшує середній Lead Time на {lead_diff:.2f} год.\n\n"
        )
    else:
        summary_text += (
            f"🔁 Частка rework становить {percent_rework}%, що не є критичною, "
            "але потребує моніторингу.\n\n"
        )

    if not bottlenecks.empty:
        summary_text += (
            f"🚧 Основний bottleneck на рівні активності: "
            f"{top_step[ACTIVITY_COL]} "
            f"(середня тривалість {top_step['avg_duration']:.2f} год).\n\n"
        )

    summary_text += (
        f"⏳ Найбільша затримка між кроками: "
        f"{bottleneck_row[ACTIVITY_COL]} → "
        f"{bottleneck_row['next_activity']} "
        f"({bottleneck_row['avg_waiting']:.2f} год очікування).\n\n"
    )

    if unique_variants > total_cases * 0.5:
        summary_text += (
            "🔀 Процес має високу варіативність, що може свідчити "
            "про нестандартизовані процедури або винятки.\n\n"
        )
    elif top1_share > 70:
        summary_text += "📏 Процес добре стандартизований з домінуючим основним сценарієм.\n\n"

    # CR-07: Organizational Findings (only when Role column was present).
    if role_analysis_result is not None:
        summary_text += "\n**👥 Organizational Findings**\n\n"
        if role_analysis_result.get("top_bottleneck_role"):
            summary_text += (
                f"🚧 Роль, найбільше пов'язана з bottleneck-активностями: "
                f"**{role_analysis_result['top_bottleneck_role']}**.\n\n"
            )
        if role_analysis_result.get("top_rework_role"):
            summary_text += (
                f"🔁 Роль з найвищою частотою rework: "
                f"**{role_analysis_result['top_rework_role']}**.\n\n"
            )
        avg_fte = role_analysis_result.get("avg_fte_per_case")
        if avg_fte is not None:
            summary_text += (
                f"👤 Average FTE per Case (оцінка потрібного FTE-ресурсу на один кейс): "
                f"{avg_fte:.2f}.\n\n"
            )

    # CR-07: Regional Findings (only when Region column was present).
    if region_analysis_result is not None:
        summary_text += "\n**🌍 Regional Findings**\n\n"
        for insight in region_analysis_result.get("insights", []):
            summary_text += f"📍 {insight}\n\n"

    recommendations = "### 📌 Рекомендації:\n\n"
    if percent_rework > 30:
        recommendations += "- Зменшити причини повторних кроків (аналіз root cause rework).\n"
    if not bottlenecks.empty:
        recommendations += f"- Оптимізувати або автоматизувати крок **{top_step[ACTIVITY_COL]}**.\n"
    recommendations += (
        "- Проаналізувати переходи з найбільшим waiting time.\n"
        "- Стандартизувати варіативні сценарії або формалізувати винятки.\n"
        "- Впровадити SLA для критичних переходів.\n"
    )

    # CR-07: Recommended Actions from role/region analysis.
    if role_analysis_result is not None and role_analysis_result.get("top_bottleneck_role"):
        recommendations += (
            f"- Переглянути навантаження та процедури ролі "
            f"**{role_analysis_result['top_bottleneck_role']}**.\n"
        )
    if region_analysis_result is not None:
        for rec in region_analysis_result.get("recommendations", []):
            recommendations += f"- {rec}\n"

    return {"summary_text": summary_text, "recommendations": recommendations}


def compute_maturity_score(
    percent_rework: float, unique_variants: int, total_cases: int, bottlenecks: pd.DataFrame
) -> Dict[str, Any]:
    """
    CR-04: same scoring logic as before (start at 100, -20 per triggered
    penalty, floored at 0) but now returns a full breakdown so the score is
    explainable in the UI and PDF instead of being a single opaque number:

        {
            "score": int,               # final score, 0-100
            "base_score": 100,
            "components": [
                {
                    "name": str,             # e.g. "Rework penalty"
                    "applied": bool,
                    "points": int,           # e.g. -20 or 0
                    "metric_value": float,
                    "threshold": float,
                    "reason": str,           # human-readable explanation
                },
                ...
            ],
            "focus_areas": [str, ...],  # only for triggered penalties
        }
    """
    components: List[Dict[str, Any]] = []
    variability_threshold = total_cases * 0.5

    rework_triggered = percent_rework > 30
    components.append({
        "name": "Rework penalty",
        "applied": rework_triggered,
        "points": -20 if rework_triggered else 0,
        "metric_value": percent_rework,
        "threshold": 30,
        "reason": (
            f"Rework Rate = {percent_rework}%. Штраф застосовано, оскільки Rework Rate "
            "перевищує поріг 30%."
            if rework_triggered else
            f"Rework Rate = {percent_rework}%. Штраф не застосовано: значення в межах "
            "порогу 30%."
        ),
    })

    variability_triggered = unique_variants > variability_threshold
    components.append({
        "name": "Process variability penalty",
        "applied": variability_triggered,
        "points": -20 if variability_triggered else 0,
        "metric_value": unique_variants,
        "threshold": variability_threshold,
        "reason": (
            f"Кількість унікальних варіантів процесу = {unique_variants} "
            f"(поріг: {variability_threshold:.0f}, тобто 50% від {total_cases} кейсів). "
            + (
                "Штраф застосовано через високу варіативність процесу."
                if variability_triggered else
                "Штраф не застосовано: варіативність у межах норми."
            )
        ),
    })

    bottleneck_triggered = not bottlenecks.empty
    components.append({
        "name": "Bottleneck penalty",
        "applied": bottleneck_triggered,
        "points": -20 if bottleneck_triggered else 0,
        "metric_value": len(bottlenecks),
        "threshold": 0,
        "reason": (
            f"Виявлено {len(bottlenecks)} bottleneck-активностей (кроків, що перевищують "
            "середні значення одночасно за тривалістю і кількістю повторів). "
            + (
                "Штраф застосовано через наявність bottleneck'ів."
                if bottleneck_triggered else
                "Штраф не застосовано: явних bottleneck'ів не виявлено."
            )
        ),
    })

    score = 100 + sum(c["points"] for c in components)
    score = max(score, 0)

    focus_area_map = {
        "Rework penalty": "Reduce Rework — зменшити частку повторних кроків (rework)",
        "Process variability penalty": "Standardize Process Variants — стандартизувати сценарії процесу",
        "Bottleneck penalty": "Eliminate Bottlenecks — усунути bottleneck-активності",
    }
    focus_areas = [
        focus_area_map[c["name"]] for c in components if c["applied"]
    ]

    return {
        "score": score,
        "base_score": 100,
        "components": components,
        "focus_areas": focus_areas,
    }


def build_ai_narrative(
    maturity_score: int, avg_duration: float, percent_rework: float, unique_variants: int
) -> str:
    if maturity_score > 80:
        maturity_level = "високим рівнем операційної стабільності"
    elif maturity_score > 50:
        maturity_level = "помірною структурною зрілістю"
    else:
        maturity_level = "операційною нестабільністю"

    return f"""
    Процес характеризується {maturity_level}.

    Середній Lead Time становить {avg_duration:.2f} годин.
    Частка rework складає {percent_rework}%.
    Кількість унікальних варіантів процесу — {unique_variants}.

    Основні втрати часу пов'язані з кроками високої тривалості
    та переходами з великим waiting time.

    Поточна структура процесу свідчить про необхідність
    структурної оптимізації критичних активностей та стандартизації сценаріїв.
    """


def _build_expected_impact(
    metric: str,
    current_value: float,
    target_value: float,
    unit: str,
    calculation_method: str,
    confidence: str,
    affected_cases: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Req 2 / Sec 8: structured Expected Impact data model, computed once here
    so app.py/reporting.py only ever display it -- never recalculate it
    (Sec 19/20 SSOT). `confidence` follows Sec 13's own taxonomy:
        High   = directly observed (no target/assumption involved)
        Medium = target is an in-dataset benchmark (another region/role/variant)
        Low    = target is based on an assumed improvement percentage
    """
    improvement_value = current_value - target_value
    improvement_percent = (improvement_value / current_value * 100) if current_value else 0.0
    impact: Dict[str, Any] = {
        "metric": metric,
        "current_value": round(current_value, 2),
        "target_value": round(target_value, 2),
        "improvement_value": round(improvement_value, 2),
        "improvement_percent": round(improvement_percent, 1),
        "unit": unit,
        "calculation_method": calculation_method,
        "confidence": confidence,
    }
    if affected_cases is not None:
        impact["affected_cases"] = int(affected_cases)
        impact["total_impact"] = round(improvement_value * affected_cases, 2)
    impact["display_text"] = _format_impact_text(impact)
    return impact


def _format_impact_text(impact: Dict[str, Any]) -> str:
    """Req 14: one-line, human-readable rendering of a quantified Expected
    Impact dict, built once here and reused as-is by both the UI and PDF."""
    line = (
        f"Potential {impact['metric']} improvement: {impact['improvement_value']:+.2f} "
        f"{impact['unit']} ({impact['improvement_percent']:+.1f}%)"
    )
    if "total_impact" in impact:
        line += f", total potential impact ≈ {impact['total_impact']:+.1f} {impact['unit'].split('/')[0]}"
    line += f". Confidence: {impact['confidence']}."
    return line


def build_improvement_roadmap(
    rework: Dict[str, Any],
    lead_time: Dict[str, Any],
    step_analysis: Dict[str, Any],
    variants: Dict[str, Any],
    role_analysis_result: Optional[Dict[str, Any]] = None,
    region_analysis_result: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Req 7 / Sec 9-15: dynamic, evidence-based Improvement Roadmap.

    Every initiative below is built purely from numbers already computed
    elsewhere (rework / bottleneck / lead-time / variant / role / region
    analysis) -- nothing here recalculates a metric, it only interprets
    already-centralized results into prioritized, structured initiatives
    (Sec 20: Single Source of Truth). Priority thresholds intentionally
    reuse the exact same cutoffs `compute_maturity_score` already uses
    (Rework Rate > 30%, unique variants > 50% of cases) so the roadmap can
    never contradict the Executive Summary / Maturity Score it's derived
    alongside (Sec 16).

    Req 2: each initiative also carries a structured `expected_impact` dict
    (Sec 8) alongside the original qualitative `impact` sentence (Sec 14
    requires both to be shown), quantifying Current Value / Target Value /
    Improvement Value / Improvement % / Confidence -- using an in-dataset
    benchmark wherever one genuinely exists (Medium confidence: non-rework
    cases' Lead Time, the leading region, the average role FTE, the best
    Top-5 variant), and an explicitly-labeled assumed percentage only when
    no such benchmark exists (Low confidence: bottleneck duration, rework
    rate target).

    Returns a list of dicts, each with:
        priority, icon, phase, area, problem, evidence, action, impact,
        expected_impact, source
    sorted Critical -> Low (then by evidence severity within a tier),
    capped at 7 initiatives (Sec 13). Only initiatives with real supporting
    evidence are included -- if fewer than 3 qualify, fewer than 3 are
    returned (Sec 13: "do not generate artificial recommendations").
    """
    PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    PRIORITY_ICON = {"Critical": "🚨", "High": "🔴", "Medium": "🟠", "Low": "🟢"}
    PHASE_BY_AREA = {
        "Bottleneck Elimination": "Phase 1 — Stabilize",
        "Rework Reduction": "Phase 1 — Stabilize",
        "Lead Time Reduction": "Phase 1 — Stabilize",
        "Process Standardization": "Phase 2 — Standardize",
        "Regional Performance Optimization": "Phase 2 — Standardize",
        "Resource Allocation": "Phase 2 — Standardize",
        "Best Practice Replication": "Phase 3 — Optimize",
    }

    candidates: List[Dict[str, Any]] = []

    # --- 12.2 / 10.1 Bottleneck Analysis ---
    bottlenecks = step_analysis["bottlenecks"]
    top_step = step_analysis["top_step"]
    if not bottlenecks.empty and top_step is not None:
        total_impact = bottlenecks["impact"].sum()
        impact_share = (top_step["impact"] / total_impact) if total_impact else 0
        priority = "Critical" if (impact_share > 0.3 or len(bottlenecks) == 1) else "High"
        # Sec 10.1: no in-dataset benchmark exists for "how much a specific
        # bottleneck activity could shrink" -- an assumed 30% reduction is
        # used, explicitly labeled Low confidence per Sec 13.
        current_duration = float(top_step["avg_duration"])
        candidates.append({
            "priority": priority,
            "area": "Bottleneck Elimination",
            "problem": (
                f"Процес містить суттєві затримки, зосереджені навколо кроку "
                f"«{top_step[ACTIVITY_COL]}»."
            ),
            "evidence": (
                f"Крок «{top_step[ACTIVITY_COL]}»: середня тривалість "
                f"{top_step['avg_duration']:.2f} год, середня кількість повторів "
                f"{top_step['avg_count']:.2f} — обидва показники перевищують середні "
                "значення по процесу."
            ),
            "action": (
                "Провести Root Cause Analysis кроку та переглянути/спростити процедуру "
                "або усунути зайві погодження."
            ),
            "impact": "Скорочення Lead Time та підвищення пропускної здатності процесу.",
            "expected_impact": _build_expected_impact(
                metric="Bottleneck step duration",
                current_value=current_duration,
                target_value=current_duration * 0.7,
                unit="год/кейс",
                calculation_method=(
                    "Assumed 30% reduction in step duration (no in-dataset benchmark "
                    "available for this specific activity)"
                ),
                confidence="Low",
            ),
            "source": "Bottleneck Analysis",
            "severity": float(top_step["impact"]),
        })

    # --- 12.1 / 10.2 Rework Analysis ---
    percent_rework = rework["percent_rework"]
    if percent_rework > 15:
        priority = "Critical" if percent_rework > 50 else ("High" if percent_rework > 30 else "Medium")
        top_rework_activities = (
            rework["top_rework"]["Activity Name"].tolist()[:2]
            if not rework["top_rework"].empty else []
        )
        activities_note = (
            f" Основні активності: {', '.join(top_rework_activities)}." if top_rework_activities else ""
        )
        total_cases_rw = rework.get("total_cases", 0)
        # Sec 9.2 / 10.2: target rate = 1/3 reduction of current, floored at
        # 15% (the same "healthy" threshold this roadmap itself uses above
        # to decide whether Rework is worth flagging at all). This target is
        # an assumption, not an in-dataset benchmark -> Low confidence.
        target_rework_rate = max(15.0, percent_rework * (2 / 3))
        avoided_cases = total_cases_rw * (percent_rework - target_rework_rate) / 100
        rework_impact = _build_expected_impact(
            metric="Rework Rate",
            current_value=percent_rework,
            target_value=target_rework_rate,
            unit="%",
            calculation_method=(
                "Assumed target: current rate reduced by one-third, floored at a 15% "
                "healthy-process threshold"
            ),
            confidence="Low",
        )
        rework_impact["avoided_rework_cases"] = round(avoided_cases, 0)
        candidates.append({
            "priority": priority,
            "area": "Rework Reduction",
            "problem": "Значна частка кейсів містить повторювані активності (rework).",
            "evidence": f"Rework Rate = {percent_rework}%.{activities_note}",
            "action": "Визначити першопричини повторень та усунути основні джерела rework.",
            "impact": (
                "Скорочення Lead Time, зменшення операційного навантаження, "
                "підвищення стабільності процесу."
            ),
            "expected_impact": rework_impact,
            "source": "Rework Analysis",
            "severity": percent_rework,
        })

    # --- 12.3 / 9.1 Lead Time Analysis ---
    mean_lead_rework = lead_time["mean_lead_rework"] or 0
    mean_lead_no_rework = lead_time["mean_lead_no_rework"] or 0
    lead_diff = mean_lead_rework - mean_lead_no_rework
    if mean_lead_no_rework and lead_diff > 0.3 * mean_lead_no_rework:
        candidates.append({
            "priority": "High",
            "area": "Lead Time Reduction",
            "problem": "Середній Lead Time суттєво зростає для кейсів з rework.",
            "evidence": (
                f"Середній Lead Time: {mean_lead_rework:.2f} год (з rework) проти "
                f"{mean_lead_no_rework:.2f} год (без rework) — різниця {lead_diff:+.2f} год."
            ),
            "action": (
                "Проаналізувати кроки та waiting time, що найбільше впливають на Lead "
                "Time, і пріоритизувати найдовші активності."
            ),
            "impact": "Скорочення наскрізної тривалості процесу.",
            # Sec 9.1: benchmark = non-rework cases' own observed Lead Time
            # in this same dataset -> Medium confidence.
            "expected_impact": _build_expected_impact(
                metric="Case Lead Time",
                current_value=mean_lead_rework,
                target_value=mean_lead_no_rework,
                unit="год/кейс",
                calculation_method="Benchmark: average Lead Time of cases without rework in this dataset",
                confidence="Medium",
                affected_cases=rework.get("total_rework_cases"),
            ),
            "source": "Lead Time Analysis",
            "severity": lead_diff,
        })

    # --- 12.4 / 10.3 Variant Analysis ---
    unique_variants = variants["unique_variants"]
    total_cases = variants["total_cases"]
    top1_share = variants["top1_share"]
    top5_share = variants["top5_share"]
    variant_lead_time_top5 = variants.get("variant_lead_time_top5")
    if unique_variants > total_cases * 0.5:
        expected_impact = None
        # Sec 10.3: use the best- vs worst-performing Top-5 variant's own
        # observed Lead Time as the benchmark, when at least 2 variants of
        # data are available for the comparison -> Medium confidence.
        if variant_lead_time_top5 is not None and variant_lead_time_top5.notna().sum() >= 2:
            valid = variant_lead_time_top5.dropna()
            best_variant_lt = float(valid.min())
            worst_variant_lt = float(valid.max())
            if worst_variant_lt > best_variant_lt:
                expected_impact = _build_expected_impact(
                    metric="Variant Lead Time",
                    current_value=worst_variant_lt,
                    target_value=best_variant_lt,
                    unit="год/кейс",
                    calculation_method=(
                        "Benchmark: best-performing vs least-efficient Top-5 process "
                        "variant, both observed in this dataset"
                    ),
                    confidence="Medium",
                )
        candidates.append({
            "priority": "High",
            "area": "Process Standardization",
            "problem": "Процес характеризується надмірною варіативністю виконання.",
            "evidence": (
                f"{unique_variants} унікальних варіантів на {total_cases} кейсів "
                f"(ТОП-5 сценаріїв охоплюють {top5_share:.1f}% кейсів)."
            ),
            "action": (
                "Визначити найчастіші варіанти, проаналізувати рідкісні/виняткові "
                "сценарії та закріпити пріоритетний шлях процесу."
            ),
            "impact": (
                "Зниження складності процесу, підвищення передбачуваності, менша "
                "операційна варіативність."
            ),
            "expected_impact": expected_impact,
            "source": "Variant Analysis",
            "severity": (unique_variants / total_cases * 100) if total_cases else 0,
        })
    elif top1_share < 50:
        candidates.append({
            "priority": "Medium",
            "area": "Process Standardization",
            "problem": "Процес не має домінуючого стандартного сценарію виконання.",
            "evidence": f"Найпоширеніший сценарій охоплює лише {top1_share:.1f}% кейсів.",
            "action": "Оцінити доцільність формалізації одного або кількох базових сценаріїв процесу.",
            "impact": "Покращена передбачуваність та легша подальша автоматизація.",
            "expected_impact": None,
            "source": "Variant Analysis",
            "severity": 100 - top1_share,
        })

    # --- 12.5 / 10.4 Role / FTE Analysis ---
    if role_analysis_result is not None:
        top_bn_role = role_analysis_result.get("top_bottleneck_role")
        top_fte_role = role_analysis_result.get("top_fte_role")
        focus_role = top_fte_role or top_bn_role
        if focus_role:
            expected_impact = None
            # Sec 10.4: benchmark = average FTE across all roles in this
            # process -> Medium confidence.
            role_workload = role_analysis_result.get("role_workload")
            if top_fte_role and role_workload is not None and not role_workload.empty:
                focus_row = role_workload[role_workload["Role"] == top_fte_role]
                if not focus_row.empty:
                    current_fte = float(focus_row.iloc[0]["fte"])
                    avg_fte = float(role_workload["fte"].mean())
                    if current_fte > avg_fte:
                        expected_impact = _build_expected_impact(
                            metric="Role FTE",
                            current_value=current_fte,
                            target_value=avg_fte,
                            unit="FTE",
                            calculation_method="Benchmark: average FTE across all roles in this process",
                            confidence="Medium",
                        )
            candidates.append({
                "priority": "Medium",
                "area": "Resource Allocation",
                "problem": f"Значна частка процесного навантаження зосереджена на ролі «{focus_role}».",
                "evidence": (
                    f"Роль «{focus_role}» має найвищий оцінений FTE серед усіх ролей процесу."
                    if top_fte_role else
                    f"Роль «{focus_role}» найбільше пов'язана з bottleneck-активностями."
                ),
                "action": (
                    "Проаналізувати розподіл навантаження та розглянути перерозподіл "
                    "завдань, автоматизацію або редизайн процесу."
                ),
                "impact": "Покращене використання ресурсів та зменшення залежності від окремих ролей.",
                "expected_impact": expected_impact,
                "source": "Role / FTE Analysis",
                "severity": 1.0,
            })

    # --- 12.6 / 10.5 Regional Analysis ---
    if region_analysis_result is not None:
        outsider = region_analysis_result.get("outsider")
        leader = region_analysis_result.get("leader")
        baseline = region_analysis_result.get("baseline", {})
        if outsider is not None and baseline.get("avg_lead_time"):
            lt_gap_pct = (
                (outsider["avg_lead_time"] - baseline["avg_lead_time"]) / baseline["avg_lead_time"] * 100
            )
            rw_gap_pts = outsider.get("rework_rate_pct", 0) - baseline.get("rework_rate_pct", 0)
            if lt_gap_pct > 15 or rw_gap_pts > 10:
                priority = "Critical" if (lt_gap_pct > 40 or rw_gap_pts > 20) else "High"
                evidence_parts = []
                if lt_gap_pct > 1:
                    evidence_parts.append(f"Lead Time на {lt_gap_pct:.0f}% вищий за середній по процесу")
                if rw_gap_pts > 1:
                    evidence_parts.append(f"Rework Rate на {rw_gap_pts:.0f} в.п. вищий за середній по процесу")
                action = f"Провести Root Cause Analysis у регіоні {outsider[REGION_COL]}"
                expected_impact = None
                # Sec 10.5: benchmark = the leading region's own observed
                # average Lead Time -> Medium confidence, explicitly labeled
                # as a benchmark-based (not guaranteed) potential impact.
                if leader is not None and leader[REGION_COL] != outsider[REGION_COL]:
                    action += f" та порівняти практики виконання з регіоном {leader[REGION_COL]}."
                    expected_impact = _build_expected_impact(
                        metric="Regional Lead Time",
                        current_value=float(outsider["avg_lead_time"]),
                        target_value=float(leader["avg_lead_time"]),
                        unit="год/кейс",
                        calculation_method=(
                            f"Benchmark-based potential impact: best-performing region "
                            f"({leader[REGION_COL]})'s own observed average Lead Time"
                        ),
                        confidence="Medium",
                        affected_cases=outsider.get("num_cases"),
                    )
                else:
                    action += "."
                candidates.append({
                    "priority": priority,
                    "area": "Regional Performance Optimization",
                    "problem": f"Регіон {outsider[REGION_COL]} суттєво відстає від загальних показників процесу.",
                    "evidence": "; ".join(evidence_parts) + ".",
                    "action": action,
                    "impact": "Зменшення розриву в показниках між регіонами та тиражування кращих практик.",
                    "expected_impact": expected_impact,
                    "source": "Regional Analysis",
                    "severity": max(lt_gap_pct, rw_gap_pts),
                })

        best_practice_region = region_analysis_result.get("best_practice_region")
        if best_practice_region is not None:
            expected_impact = None
            if baseline.get("avg_lead_time") and float(best_practice_region["avg_lead_time"]) < baseline["avg_lead_time"]:
                expected_impact = _build_expected_impact(
                    metric="Regional Lead Time",
                    current_value=float(baseline["avg_lead_time"]),
                    target_value=float(best_practice_region["avg_lead_time"]),
                    unit="год/кейс",
                    calculation_method=(
                        f"Aspirational benchmark: if every region matched "
                        f"{best_practice_region[REGION_COL]}'s observed average Lead Time "
                        "(replication feasibility not yet assessed)"
                    ),
                    confidence="Low",
                )
            candidates.append({
                "priority": "Low",
                "area": "Best Practice Replication",
                "problem": "Найкращі практики провідного регіону поки не задокументовані та не тиражуються.",
                "evidence": (
                    f"Регіон {best_practice_region[REGION_COL]} демонструє стабільно високі "
                    "показники одразу за кількома метриками процесу."
                ),
                "action": (
                    f"Задокументувати та оцінити практики регіону "
                    f"{best_practice_region[REGION_COL]} для тиражування на інші регіони."
                ),
                "impact": "Підвищення продуктивності процесу в регіонах, що відстають.",
                "expected_impact": expected_impact,
                "source": "Regional Analysis",
                "severity": 0.5,
            })

    # Sec 13: Critical -> Low, then by evidence severity within a tier; cap at 7.
    candidates.sort(key=lambda c: (PRIORITY_ORDER[c["priority"]], -c["severity"]))
    candidates = candidates[:7]

    roadmap = []
    for c in candidates:
        roadmap.append({
            "priority": c["priority"],
            "icon": PRIORITY_ICON[c["priority"]],
            "phase": PHASE_BY_AREA.get(c["area"], "Phase 2 — Standardize"),
            "area": c["area"],
            "problem": c["problem"],
            "evidence": c["evidence"],
            "action": c["action"],
            "impact": c["impact"],
            "expected_impact": c.get("expected_impact"),
            "source": c["source"],
        })
    return roadmap


# ---------------------------------------------------------------------------
# Orchestration (FR-9): run every analysis exactly once from the centralized
# case_times / activity_statistics tables and hand back one dict that
# app.py and reporting.py both consume.
# ---------------------------------------------------------------------------
def build_full_analysis(analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    analysis_data: the dict returned by case_metrics.prepare_analysis_data()
    (keys: "df", "case_times", "activity_statistics", "role_statistics",
    "region_statistics").
    """
    df = analysis_data["df"]
    case_times = analysis_data["case_times"]
    activity_statistics = analysis_data["activity_statistics"]

    general = general_statistics(case_times)
    start_end = start_end_activities(df)
    rework = rework_analysis(df, case_times)
    lead_time = lead_time_rework_comparison(case_times, rework["cases_with_rework_list"])
    step_analysis = step_duration_analysis(activity_statistics)
    transitions = transitions_analysis(df)
    variants = variant_analysis(df, case_times)

    # CR-01/CR-05/CR-06: only produced when the respective column exists.
    role_result = role_analysis(df, analysis_data.get("role_statistics"), rework, step_analysis)
    region_result = region_analysis(
        analysis_data.get("region_statistics"), rework, step_analysis, case_times=case_times
    )
    # CR-02: this is now the real FTE-based estimate (sum of FTE_role across
    # roles), not the previous avg-distinct-roles-per-case proxy.
    avg_fte_per_case = role_result["avg_fte_per_case"] if role_result is not None else None

    # CR-04: compute_maturity_score now returns a full breakdown dict. This
    # now has to run BEFORE build_executive_summary, since Req 6 folds the
    # maturity-level framing sentence (previously the standalone "AI
    # Process Narrative" block) into the top of the Executive Summary.
    maturity_score_result = compute_maturity_score(
        rework["percent_rework"],
        variants["unique_variants"],
        variants["total_cases"],
        step_analysis["bottlenecks"],
    )
    maturity_score = maturity_score_result["score"]

    executive_summary = build_executive_summary(
        percent_rework=rework["percent_rework"],
        mean_lead_rework=lead_time["mean_lead_rework"],
        mean_lead_no_rework=lead_time["mean_lead_no_rework"],
        bottlenecks=step_analysis["bottlenecks"],
        top_step=step_analysis["top_step"],
        bottleneck_row=transitions["bottleneck_row"],
        unique_variants=variants["unique_variants"],
        total_cases=variants["total_cases"],
        top1_share=variants["top1_share"],
        maturity_score=maturity_score,
        role_analysis_result=role_result,
        region_analysis_result=region_result,
    )

    # Req 7: dynamic, evidence-based roadmap (replaces the old static
    # 5-bullet list). Req 6: build_ai_narrative() is intentionally no
    # longer called here -- the function itself is left defined in case a
    # future feature wants it internally, but it's no longer part of the
    # displayed analysis result.
    roadmap = build_improvement_roadmap(
        rework=rework,
        lead_time=lead_time,
        step_analysis=step_analysis,
        variants=variants,
        role_analysis_result=role_result,
        region_analysis_result=region_result,
    )

    return {
        "general": general,
        "start_end": start_end,
        "rework": rework,
        "lead_time": lead_time,
        "step_analysis": step_analysis,
        "transitions": transitions,
        "variants": variants,
        "role_analysis": role_result,
        "region_analysis": region_result,
        "avg_fte_per_case": avg_fte_per_case,
        "executive_summary": executive_summary,
        "maturity_score": maturity_score,
        "maturity_score_breakdown": maturity_score_result["components"],
        "maturity_focus_areas": maturity_score_result["focus_areas"],
        "roadmap": roadmap,
    }

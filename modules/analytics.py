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

    return {
        "variants": variants,
        "total_cases": total_cases,
        "unique_variants": unique_variants,
        "variant_counts": variant_counts,
        "variant_counts_full": variant_counts_full,
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
    role_analysis_result: Optional[Dict[str, Any]] = None,
    region_analysis_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    lead_diff = mean_lead_rework - mean_lead_no_rework
    summary_text = ""

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


def build_improvement_roadmap(
    percent_rework: float, bottlenecks: pd.DataFrame, top_step: Optional[pd.Series]
) -> List[str]:
    roadmap = []
    if percent_rework > 30:
        roadmap.append("1️⃣ Провести root cause analysis повторюваних кроків")
    if not bottlenecks.empty:
        roadmap.append(f"2️⃣ Оптимізувати крок '{top_step[ACTIVITY_COL]}'")
    roadmap.append("3️⃣ Встановити SLA для критичних переходів")
    roadmap.append("4️⃣ Стандартизувати ТОП варіанти процесу")
    roadmap.append("5️⃣ Впровадити регулярний process monitoring dashboard")
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
        role_analysis_result=role_result,
        region_analysis_result=region_result,
    )

    # CR-04: compute_maturity_score now returns a full breakdown dict.
    maturity_score_result = compute_maturity_score(
        rework["percent_rework"],
        variants["unique_variants"],
        variants["total_cases"],
        step_analysis["bottlenecks"],
    )
    maturity_score = maturity_score_result["score"]

    ai_narrative = build_ai_narrative(
        maturity_score,
        lead_time["lead_time_per_case"]["lead_time"].mean(),
        rework["percent_rework"],
        variants["unique_variants"],
    )

    roadmap = build_improvement_roadmap(
        rework["percent_rework"], step_analysis["bottlenecks"], step_analysis["top_step"]
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
        "ai_narrative": ai_narrative,
        "roadmap": roadmap,
    }

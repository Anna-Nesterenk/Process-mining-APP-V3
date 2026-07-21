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
    avg_roles_per_case = role_statistics["avg_roles_per_case"]

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

    return {
        "role_activity": role_activity,
        "role_workload": role_workload,
        "avg_roles_per_case": avg_roles_per_case,
        "role_bottleneck_ranking": role_bottleneck_ranking,
        "longest_duration_roles": longest_duration_roles,
        "role_rework_ranking": role_rework_ranking,
        "top_bottleneck_role": top_bottleneck_role,
        "top_rework_role": top_rework_role,
    }


# ---------------------------------------------------------------------------
# CR-06: Regional analysis (only meaningful when the event log has a
# 'Region' column -- region_statistics is None otherwise).
# ---------------------------------------------------------------------------
def region_analysis(
    region_statistics: Optional[Dict[str, Any]],
    rework: Dict[str, Any],
    step_analysis: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if region_statistics is None:
        return None

    case_region = region_statistics["case_region"]
    region_lead_time = region_statistics["region_lead_time"]
    region_activity = region_statistics["region_activity"]
    region_waiting = region_statistics["region_waiting"]

    # Rework Distribution: reuse the case-level rework flag from
    # rework_analysis instead of recomputing which cases had rework.
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

    # Bottleneck Distribution: reuse the bottleneck activity list from
    # step_duration_analysis instead of recomputing it.
    bottleneck_activities = (
        set(step_analysis["bottlenecks"][ACTIVITY_COL])
        if not step_analysis["bottlenecks"].empty
        else set()
    )
    region_bottleneck = region_activity[region_activity[ACTIVITY_COL].isin(bottleneck_activities)]
    region_bottleneck_ranking = (
        region_bottleneck.groupby(REGION_COL)["occurrences"]
        .sum()
        .reset_index()
        .sort_values("occurrences", ascending=False)
        if not region_bottleneck.empty
        else pd.DataFrame(columns=[REGION_COL, "occurrences"])
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

    # Regional Leaders / Outsiders: lowest / highest average lead time.
    leader = (
        region_lead_time.sort_values("avg_lead_time").iloc[0]
        if not region_lead_time.empty
        else None
    )
    outsider = (
        region_lead_time.sort_values("avg_lead_time", ascending=False).iloc[0]
        if not region_lead_time.empty
        else None
    )

    # Pattern Detection / Automated Insights & Recommendations.
    insights: List[str] = []
    recommendations: List[str] = []

    if leader is not None:
        insights.append(
            f"Регіон {leader[REGION_COL]} демонструє найнижчий середній Lead Time "
            f"({leader['avg_lead_time']:.2f} год)."
        )
        recommendations.append(f"Тиражувати практики регіону {leader[REGION_COL]}.")

    if outsider is not None and (leader is None or outsider[REGION_COL] != leader[REGION_COL]):
        insights.append(
            f"Регіон {outsider[REGION_COL]} демонструє найвищий середній Lead Time "
            f"({outsider['avg_lead_time']:.2f} год)."
        )
        recommendations.append(f"Дослідити процес погодження в регіоні {outsider[REGION_COL]}.")

    if not region_rework.empty:
        worst_rework = region_rework.sort_values("rework_rate_pct", ascending=False).iloc[0]
        insights.append(
            f"Регіон {worst_rework[REGION_COL]} має найвищу частку rework "
            f"({worst_rework['rework_rate_pct']}%)."
        )

    if not region_bottleneck_ranking.empty:
        top_bn = region_bottleneck_ranking.iloc[0]
        insights.append(
            f"Регіон {top_bn[REGION_COL]} містить {top_bn['share_pct']}% "
            "усіх виявлених bottleneck-активностей."
        )

    if not region_waiting.empty:
        worst_waiting = region_waiting.sort_values("avg_waiting_hours", ascending=False).iloc[0]
        insights.append(
            f"Найбільша концентрація затримок (waiting time) спостерігається в регіоні "
            f"{worst_waiting[REGION_COL]} ({worst_waiting['avg_waiting_hours']:.2f} год очікування на крок)."
        )

    if not region_activity.empty:
        workload_by_region = region_activity.groupby(REGION_COL)["occurrences"].sum()
        if not workload_by_region.empty:
            busiest_region = workload_by_region.idxmax()
            insights.append(
                f"Найбільша концентрація робочого навантаження — у регіоні {busiest_region}."
            )

    return {
        "region_lead_time": region_lead_time,
        "region_activity": region_activity,
        "region_rework": region_rework,
        "region_bottleneck_ranking": region_bottleneck_ranking,
        "leader": leader,
        "outsider": outsider,
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
        avg_roles = role_analysis_result.get("avg_roles_per_case")
        if avg_roles is not None:
            summary_text += f"👤 Середня кількість ролей на кейс (Average FTE per Case): {avg_roles:.2f}.\n\n"

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
) -> int:
    score = 100
    if percent_rework > 30:
        score -= 20
    if unique_variants > total_cases * 0.5:
        score -= 20
    if not bottlenecks.empty:
        score -= 20
    return max(score, 0)


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

    # CR-05/CR-06: only produced when the respective column exists.
    role_result = role_analysis(df, analysis_data.get("role_statistics"), rework, step_analysis)
    region_result = region_analysis(analysis_data.get("region_statistics"), rework, step_analysis)
    avg_fte_per_case = role_result["avg_roles_per_case"] if role_result is not None else None

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

    maturity_score = compute_maturity_score(
        rework["percent_rework"],
        variants["unique_variants"],
        variants["total_cases"],
        step_analysis["bottlenecks"],
    )

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
        "ai_narrative": ai_narrative,
        "roadmap": roadmap,
    }

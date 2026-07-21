"""
visualizations.py
------------------
All chart/figure construction lives here. Functions return figure objects
(plotly Figure, matplotlib Figure, graphviz Digraph) so that app.py stays
focused on orchestration (`st.plotly_chart(...)`, `st.pyplot(...)`, etc.)
rather than mixing chart-building code with page layout code.

FR-7: every function here takes an already-aggregated DataFrame (produced by
case_metrics.py / analytics.py) and only reshapes/plots it -- no
`groupby("Case ID")` or other aggregation happens in this module.
"""

import math

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import seaborn as sns
from graphviz import Digraph


def case_duration_histogram(case_times: pd.DataFrame):
    fig = px.histogram(
        case_times,
        x="Duration (hours)",
        nbins=20,
        title="Розподіл тривалості кейсів (години)"
    )

    return fig


def lead_time_boxplot(lead_time_per_case: pd.DataFrame):
    fig = plt.figure(figsize=(3, 1))
    sns.boxplot(
        data=lead_time_per_case,
        x="lead_time",
        y="rework_label",
        palette={"З повтореннями": "red", "Без повторень": "green"},
        width=0.5,
        fliersize=1,
    )
    plt.xlabel("Lead Time (год)", fontsize=3)
    plt.ylabel("", fontsize=3)
    plt.title("Розподіл тривалості кейсів з Rework та без", fontsize=4)
    plt.xticks(fontsize=3)
    plt.yticks(fontsize=3)
    plt.tight_layout()
    return fig


def step_bubble_chart(analysis_df: pd.DataFrame, x_mean: float, y_mean: float):
    """
    CR-02: only the top 20% most critical activities (by criticality_score =
    avg_duration * avg_count, computed once in
    analytics.step_duration_analysis) get an on-chart text label. Every
    bubble still shows full detail on hover -- this only declutters large
    processes where labeling every activity makes the chart unreadable.
    """
    df = analysis_df.copy()
    if "criticality_score" not in df.columns:
        df["criticality_score"] = df["avg_duration"] * df["avg_count"]

    n_top = max(1, math.ceil(len(df) * 0.2))
    top_20_percent = set(
        df.sort_values("criticality_score", ascending=False).head(n_top)["Activity Name"]
    )
    df["label"] = df["Activity Name"].where(df["Activity Name"].isin(top_20_percent), "")

    fig = px.scatter(
        df,
        x="avg_duration",
        y="avg_count",
        size="impact",
        color="impact",
        text="label",
        hover_data=["Activity Name", "avg_duration", "avg_count", "impact"],
        size_max=40,
        color_continuous_scale="RdYlGn_r",
        title="Бульбашкова діаграма: тривалість кроку vs кількість повторів",
    )
    fig.update_traces(textposition="top center", textfont=dict(size=12, color="black"))

    fig.add_shape(
        type="line",
        x0=x_mean, x1=x_mean,
        y0=analysis_df["avg_count"].min(), y1=analysis_df["avg_count"].max(),
        line=dict(color="blue", width=2, dash="dash"),
        name="Середнє по X",
    )
    fig.add_shape(
        type="line",
        x0=analysis_df["avg_duration"].min(), x1=analysis_df["avg_duration"].max(),
        y0=y_mean, y1=y_mean,
        line=dict(color="blue", width=2, dash="dash"),
        name="Середнє по Y",
    )
    fig.update_layout(
        width=900,
        height=600,
        title_font=dict(size=20, color="black"),
        xaxis_title="Середня тривалість кроку (год)",
        yaxis_title="Середня кількість повторів на кейс",
        xaxis=dict(tickfont=dict(size=14, color="black")),
        yaxis=dict(tickfont=dict(size=14, color="black")),
        legend_title=dict(font=dict(size=14, color="black")),
    )
    return fig


def heuristics_graph(edges: pd.DataFrame, bottleneck_text: str) -> Digraph:
    dot = Digraph(
        engine="dot",
        graph_attr={"rankdir": "LR"},
        node_attr={"shape": "box", "style": "rounded,filled", "fillcolor": "#F9F9F9"},
    )

    edges_sorted = edges.sort_values("avg_waiting")
    total_waiting = edges_sorted["avg_waiting"].sum()
    edges_sorted["cumsum_waiting"] = edges_sorted["avg_waiting"].cumsum()
    edges_sorted["cumsum_ratio"] = (
        edges_sorted["cumsum_waiting"] / total_waiting if total_waiting else 0
    )

    red_threshold = edges_sorted.loc[edges_sorted["cumsum_ratio"] <= 0.8, "avg_waiting"].max()
    orange_threshold = edges_sorted.loc[
        (edges_sorted["cumsum_ratio"] > 0.8) & (edges_sorted["cumsum_ratio"] <= 0.95),
        "avg_waiting",
    ].max()
    green_threshold = edges_sorted.loc[edges_sorted["cumsum_ratio"] > 0.95, "avg_waiting"].max()

    with dot.subgraph(name="cluster_legend") as c:
        c.attr(label="Legend", fontsize="12")
        c.node("L1", f"🟢 ≤ {green_threshold:.1f} год", shape="box", style="filled", fillcolor="green")
        c.node("L2", f"🟠 {green_threshold:.1f}–{orange_threshold:.1f} год", shape="box", style="filled", fillcolor="orange")
        c.node("L3", f"🔴 > {orange_threshold:.1f} год", shape="box", style="filled", fillcolor="red")

    activities = set(edges["Activity Name"]).union(edges["next_activity"])
    for act in activities:
        dot.node(act)

    for _, row in edges.iterrows():
        dot.edge(
            row["Activity Name"],
            row["next_activity"],
            label=f'{row["frequency"]} | {row["avg_waiting"]:.1f}h',
            penwidth=str(row["penwidth"]),
            color=row["color"],
        )

    dot.node(
        "bottleneck_info",
        bottleneck_text,
        shape="note",
        style="filled",
        fillcolor="#FFE4E1",
    )

    return dot


def heuristics_graph_to_svg(dot: Digraph) -> str:
    """CR-04: render the same Digraph as SVG (vector, scales cleanly) for
    the zoomable viewer, instead of the raster PNG used elsewhere."""
    return dot.pipe(format="svg").decode("utf-8")


def zoomable_svg_component(svg_markup: str, height: int = 600) -> str:
    """
    CR-04: wraps an SVG string in a scrollable container with simple +/- /
    reset zoom controls (plain CSS transform + vanilla JS), so large process
    maps can be inspected without downloading the image.
    """
    return f"""
    <div style="border:1px solid #E5E7EB; border-radius:8px; overflow:auto;
                height:{height}px; background:#ffffff; padding:4px;">
      <div id="zoom-wrapper" style="transform-origin: 0 0; transform: scale(1);
                  display:inline-block; padding:10px;">
        {svg_markup}
      </div>
    </div>
    <div style="margin-top:8px;">
      <button onclick="zoomStep(0.15)">➕ Zoom In</button>
      <button onclick="zoomStep(-0.15)">➖ Zoom Out</button>
      <button onclick="zoomReset()">⟲ Reset</button>
    </div>
    <script>
      let scale = 1;
      function apply() {{
        document.getElementById('zoom-wrapper').style.transform = 'scale(' + scale + ')';
      }}
      function zoomStep(delta) {{
        scale = Math.max(0.2, Math.min(5, scale + delta));
        apply();
      }}
      function zoomReset() {{
        scale = 1;
        apply();
      }}
    </script>
    """


def case_timeline(case_df: pd.DataFrame, selected_case, bottleneck_activity: str = None):
    """
    Gantt-style timeline for a single case: each activity is drawn as a
    horizontal bar from Start Timestamp to Finish Timestamp (instead of a
    single point), colored green by default and red when the activity is
    either repeated within this case (rework) or matches the globally
    identified bottleneck activity (from the bubble-chart analysis).
    """
    df = case_df.sort_values("Start Timestamp").reset_index(drop=True).copy()

    occurrence_counts = df["Activity Name"].value_counts()
    is_rework = df["Activity Name"].map(occurrence_counts) > 1
    is_bottleneck = (
        df["Activity Name"] == bottleneck_activity if bottleneck_activity else False
    )
    df["highlight"] = is_rework | is_bottleneck
    df["Категорія"] = df["highlight"].map(
        {True: "Rework / Bottleneck", False: "Звичайний крок"}
    )

    # Distinguish repeated activities as separate bars on the y-axis.
    df["Крок"] = [f"{i + 1}. {act}" for i, act in enumerate(df["Activity Name"])]

    rename_map = {}
    if "step_duration_hours" in df.columns:
        rename_map["step_duration_hours"] = "Duration (год)"
    if "waiting_hours" in df.columns:
        rename_map["waiting_hours"] = "Waiting Time (год)"
    df = df.rename(columns=rename_map)

    hover_cols = [c for c in ["Case ID", "Activity Name", "Duration (год)", "Waiting Time (год)"] if c in df.columns]

    fig = px.timeline(
        df,
        x_start="Start Timestamp",
        x_end="Finish Timestamp",
        y="Крок",
        color="Категорія",
        color_discrete_map={"Звичайний крок": "#2ECC71", "Rework / Bottleneck": "#E74C3C"},
        hover_data=hover_cols,
        title=f"Timeline кейсу {selected_case}",
    )
    fig.update_yaxes(autorange="reversed", title="Крок процесу")
    fig.update_xaxes(title="Час")
    return fig


# ---------------------------------------------------------------------------
# CR-05: Role Analysis charts
# ---------------------------------------------------------------------------
def role_activity_matrix(role_activity: pd.DataFrame):
    pivot = role_activity.pivot_table(
        index="Role", columns="Activity Name", values="occurrences", fill_value=0
    )
    fig = px.imshow(
        pivot,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="Blues",
        title="Role vs Activity Matrix",
        labels=dict(color="К-сть виконань"),
    )
    return fig


def role_workload_chart(role_workload: pd.DataFrame):
    fig = px.bar(
        role_workload.sort_values("cases_handled", ascending=False),
        x="Role",
        y="cases_handled",
        text="cases_handled",
        title="Role Workload Distribution (кількість кейсів на роль)",
        labels={"cases_handled": "Кількість кейсів"},
    )
    return fig


def role_bottleneck_ranking_chart(role_bottleneck_ranking: pd.DataFrame):
    if role_bottleneck_ranking.empty:
        return None
    fig = px.bar(
        role_bottleneck_ranking.sort_values("occurrences", ascending=False),
        x="Role",
        y="occurrences",
        text="occurrences",
        title="Role Bottleneck Ranking",
        labels={"occurrences": "К-сть виконань bottleneck-активностей"},
    )
    return fig


# ---------------------------------------------------------------------------
# CR-06: Regional Analysis charts
# ---------------------------------------------------------------------------
def region_lead_time_bar(region_lead_time: pd.DataFrame):
    fig = px.bar(
        region_lead_time.sort_values("avg_lead_time"),
        x="Region",
        y="avg_lead_time",
        text_auto=".2f",
        title="Lead Time by Region",
        labels={"avg_lead_time": "Середній Lead Time (год)"},
    )
    return fig


def region_rework_bar(region_rework: pd.DataFrame):
    fig = px.bar(
        region_rework.sort_values("rework_rate_pct", ascending=False),
        x="Region",
        y="rework_rate_pct",
        text_auto=".1f",
        title="Rework by Region",
        labels={"rework_rate_pct": "Частка rework (%)"},
    )
    return fig


def region_performance_matrix(region_lead_time: pd.DataFrame, region_rework: pd.DataFrame):
    merged = region_lead_time.merge(region_rework, on="Region", how="left")
    fig = px.scatter(
        merged,
        x="avg_lead_time",
        y="rework_rate_pct",
        size="num_cases",
        text="Region",
        title="Regional Performance Matrix",
        labels={
            "avg_lead_time": "Середній Lead Time (год)",
            "rework_rate_pct": "Частка rework (%)",
        },
        size_max=40,
    )
    fig.update_traces(textposition="top center")
    return fig

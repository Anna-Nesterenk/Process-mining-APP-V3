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
        title="Тривалість кейсів (години)"
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
    fig = px.scatter(
        analysis_df,
        x="avg_duration",
        y="avg_count",
        size="impact",
        color="impact",
        text="Activity Name",
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


def risk_heatmap(analysis_df: pd.DataFrame, x_mean: float, y_mean: float):
    risk_matrix = analysis_df.copy()
    risk_matrix["risk_score"] = (
        (risk_matrix["avg_duration"] / x_mean) * (risk_matrix["avg_count"] / y_mean)
    )
    pivot = risk_matrix.pivot_table(values="risk_score", index="Activity Name")

    fig = plt.figure(figsize=(3, 4))
    sns.heatmap(pivot, annot=True, cmap="Reds", linewidths=0.5)
    plt.title("Risk Intensity per Activity")
    plt.xticks([])
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


def case_timeline(case_df: pd.DataFrame, selected_case):
    fig = px.scatter(
        case_df,
        x="Start Timestamp",
        y="Activity Name",
        title=f"Timeline кейсу {selected_case}",
    )
    return fig

"""
app.py
------
Main Streamlit entrypoint. Responsible only for page layout and orchestration:

    1. Render header / instructions.
    2. Upload Excel file.
    3. VALIDATE the file (modules.data_validation) -- stop here if invalid.
    4. Preprocess into an analysis-ready DataFrame (modules.data_processing).
    5. Aggregate ONCE into case_times / activity_statistics
       (modules.case_metrics) -- the Single Source of Truth for every
       metric used below.
    6. Run every analysis exactly once (modules.analytics.build_full_analysis)
       and render results with visualizations (modules.visualizations).
    7. Bundle everything into one AnalysisResult (modules.models) and offer
       the PDF executive report for download (modules.reporting), built
       from that same object so the PDF matches the UI exactly.

All business logic lives in the `modules/` package; this file should stay
thin and readable.
"""

import warnings

import streamlit as st
import streamlit.components.v1 as components

warnings.filterwarnings("ignore")

from modules import analytics, case_metrics, data_processing, data_validation, reporting, visualizations
from modules.config import (
    APP_TITLE,
    AUTHOR_LINKEDIN,
    AUTHOR_NAME,
    GA_ID,
    LAYOUT,
    MANDATORY_COLUMNS,
    PAGE_TITLE,
)
from modules.metrics_tracker import render_usage_sidebar, track_metric, track_once_per_session
from modules.models import AnalysisResult


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
def render_analytics_snippet():
    components.html(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
        <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
        <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());
        gtag('config', '{GA_ID}', {{
          'send_page_view': true
        }});
        </script>
        </head>
        <body></body>
        </html>
        """,
        height=0,
    )


def render_header():
    st.set_page_config(page_title=PAGE_TITLE, layout=LAYOUT)
    st.title(APP_TITLE)

    st.markdown("---")
    st.markdown(f"© 2026 {AUTHOR_NAME} | [LinkedIn]({AUTHOR_LINKEDIN})")
    st.markdown("---")
    st.markdown("Завантажте Excel-файл з подіями для аналізу процесів")
    st.markdown("Файл має міститі обов'язкові поля (кожен рядок = подія/крок (event)):")
    for col in MANDATORY_COLUMNS:
        st.markdown(f"- **{col}**")
    st.markdown("Необов'язкові, але корисні поля: **Role**, **Region**.")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def main():
    render_analytics_snippet()
    render_header()

    track_once_per_session("visit_tracked", "app_visits")

    uploaded_file = st.file_uploader("Завантажте Excel лог", type=["xlsx"])
    if uploaded_file is None:
        render_usage_sidebar()
        return

    track_once_per_session("upload_tracked", "datasets_uploaded")

    # ---------------- Stage 1: Upload & Validation ----------------
    raw_df, validation_result = data_validation.load_and_validate_excel(uploaded_file)

    if raw_df is None:
        render_usage_sidebar()
        st.stop()

    if not validation_result.is_valid:
        data_validation.render_validation_errors(validation_result)
        st.warning("Будь ласка, виправте файл і завантажте його ще раз.")
        render_usage_sidebar()
        st.stop()

    st.success("✅ Excel успішно завантажено та пройшов валідацію.")
    st.dataframe(raw_df.head(5))

    # ---------------- Preprocessing (event-level, once) ----------------
    df = data_processing.prepare_dataframe(raw_df)
    df = data_processing.compute_step_durations(df)

    track_metric("analyses_run")

    # ---------------- Aggregation (case/activity-level, once) ----------------
    analysis_data = case_metrics.prepare_analysis_data(df)
    analysis = analytics.build_full_analysis(analysis_data)

    # ---------------- Render sections, collecting figures for the PDF --------
    figures = {}
    figures["general_statistics"] = render_general_statistics(
        analysis_data["case_times"], analysis["general"], analysis["start_end"], analysis["rework"]
    )
    render_completion_steps(analysis["start_end"])
    figures["rework"] = render_rework_section(analysis["rework"])
    figures["lead_time"] = render_lead_time_section(analysis["lead_time"])
    figures["step_analysis"] = render_bubble_section(analysis["step_analysis"])
    figures["heuristics"] = render_heuristics_section(analysis["transitions"])
    figures["variants"] = render_variant_analysis_section(analysis["variants"])
    figures["timeline"] = render_case_timeline_section(df, analysis["step_analysis"])

    # ---------------- CR-05 / CR-06: conditional sections ----------------
    if analysis["role_analysis"] is not None:
        figures["role_analysis"] = render_role_analysis_section(analysis["role_analysis"])
    if analysis["region_analysis"] is not None:
        figures["region_analysis"] = render_region_analysis_section(analysis["region_analysis"])

    # ---------------- FR-9: bundle everything into one AnalysisResult --------
    result = AnalysisResult(
        case_times=analysis_data["case_times"],
        activity_statistics=analysis_data["activity_statistics"],
        statistics=analysis,
        figures=figures,
        transitions=analysis["transitions"],
        variants=analysis["variants"],
        executive_summary=analysis["executive_summary"],
        maturity_score=analysis["maturity_score"],
        ai_narrative=analysis["ai_narrative"],
        roadmap=analysis["roadmap"],
        role_analysis=analysis["role_analysis"],
        region_analysis=analysis["region_analysis"],
        avg_fte_per_case=analysis["avg_fte_per_case"],
    )

    render_executive_summary_section(result)

    render_usage_sidebar()


# ---------------------------------------------------------------------------
# Section renderers (Streamlit layout + calls into analytics/visualizations)
#
# FR-8: each render_* function renders its visualization(s) to the Streamlit
# interface AND returns {"figure": ..., "statistics": ...} (or "figures" for
# sections with more than one chart) so the same figures can be reused
# verbatim in the PDF report instead of being rebuilt from scratch there.
# ---------------------------------------------------------------------------
def render_general_statistics(case_times, general, start_end, rework):
    st.subheader("📊 Загальна статистика логів")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Період дослідження",
            f"{general['start_period'].date()} → {general['end_period'].date()}",
        )
        st.metric("Кількість кейсів", general["num_cases"])
    with col2:
        st.metric("Сер. тривалість кейсу (год)", round(general["avg_duration"], 2))
        st.metric("Медіанна тривалість кейсу (год)", round(general["median_duration"], 2))
    with col3:
        st.metric("Сер. кількість Activity Name на кейс", round(general["avg_activities"], 1))

    top_rework_preview = rework["top_rework"]

    description = f"""
    Процес зазвичай починається з кроку '{start_end['most_common_start']}'
    та найчастіше завершується на кроці '{start_end['most_common_end']}'.

    Середня тривалість кейсу становить {round(general['avg_duration'], 2)} годин,
    а середня кількість кроків на кейс — {round(general['avg_activities'], 1)}.

    Найбільша кількість повторів спостерігається на кроках:
    {", ".join(top_rework_preview["Activity Name"].tolist()[:3]) if not top_rework_preview.empty else "—"}.
    """
    st.info(description)

    fig = visualizations.case_duration_histogram(case_times)
    st.plotly_chart(fig, use_container_width=True)

    return {"figure": fig, "statistics": general}


def render_completion_steps(start_end):
    st.subheader("🔚 Кроки завершення процесу")
    st.write("ТОП кроків завершення:")
    st.dataframe(
        start_end["top_end_activities"]
        .reset_index()
        .rename(columns={"index": "Activity Name", "Activity Name": "кількість кейсів"})
    )
    return {"statistics": start_end}


def render_rework_section(rework):
    st.subheader("🔁 Повторювані кроки (rework)")
    st.write("ТОП кроків з середньою кількістю повторів > 1 на кейс:")
    st.dataframe(rework["top_rework"])

    st.markdown(
        f"В нашій вибірці {rework['total_rework_cases']} кейсів ({rework['percent_rework']}%) "
        "містять повторювані кроки. Це вказує на наявність rework у процесі, який уповільнює "
        "його виконання та підвищує варіабельність тривалості кейсів."
    )
    return {"statistics": rework}


def render_lead_time_section(lead_time):
    st.markdown("### 📈 Розподіл Lead Time: кейси з rework vs без")

    fig = visualizations.lead_time_boxplot(lead_time["lead_time_per_case"])
    st.pyplot(fig)

    st.markdown(
        f"**Середні показники по групах:**\n\n"
        f"- Кейси з повтореннями: Lead Time = {lead_time['mean_lead_rework']:.2f} год, "
        f"Waiting Time = {lead_time['mean_wait_rework']:.2f} год\n"
        f"- Кейси без повторень: Lead Time = {lead_time['mean_lead_no_rework']:.2f} год, "
        f"Waiting Time = {lead_time['mean_wait_no_rework']:.2f} год"
    )
    return {"figure": fig, "statistics": lead_time}


def render_bubble_section(step_analysis):
    fig_bubble = visualizations.step_bubble_chart(
        step_analysis["analysis_df"], step_analysis["x_mean"], step_analysis["y_mean"]
    )
    st.plotly_chart(fig_bubble, use_container_width=True)

    st.markdown(
        """
    #### 🔎 Як читати діаграму

    - **Вісь X** – середня тривалість кроку
    - **Вісь Y** – середня кількість повторів на кейс
    - **Розмір бульбашки** – сумарний вплив кроку на загальний час процесу
    - **Пунктирні лінії** – середні значення по вибірці
    - **Підписи** – показані лише для 20% найбільш критичних активностей
      (Impact = середня тривалість × середня к-сть повторів); решта доступні через hover

    📌 Інтерпретація:
    - Правий верхній квадрант → потенційні bottleneck'и
    - Правий нижній → довгі, але рідкі кроки
    - Лівий верхній → часті, але короткі
    - Лівий нижній → мінімальний вплив
    """
    )

    if step_analysis["top_step"] is not None:
        top_step = step_analysis["top_step"]
        st.success(
            f"""
        🔴 Основний потенційний bottleneck: **{top_step['Activity Name']}**

        - Середня тривалість: {round(top_step['avg_duration'], 2)} год
        - Середня кількість повторів: {round(top_step['avg_count'], 2)}
        - Сумарний імпакт: {round(top_step['impact'], 2)} год

        Крок перевищує середні значення за обома параметрами та має найбільший внесок у затримку процесу.
        """
        )
    else:
        st.info("Явно виражених bottleneck'ів (вище середнього по тривалості і повторюваності) не виявлено.")

    return {"figure": fig_bubble, "statistics": step_analysis}


def render_heuristics_section(transitions):
    st.subheader("Heuristics Miner")
    st.markdown("Heuristics Miner → Petri Net показує реальний, частотний процес")
    st.markdown("Це граф переходів, ближчий до «як реально відбувалося»")
    st.markdown("Основні елементи Petri Net:")
    st.markdown("- ◯ Кружки (places). Стани процесу «Тут ми зараз»")
    st.markdown("- ▭ Прямокутники (transitions). Активності, Реальні дії")
    st.markdown("- ➝ Стрілки. Потік виконання")
    st.markdown("Частоти / товщина стрілок")
    st.markdown("📌 Читається: товсті стрілки → часто, тонкі → рідко")
    st.markdown("Це дуже важливо для: bottleneck analysis, відхилень")
    st.markdown("🧠 Як читати Heuristics Miner практично")
    st.markdown("1. Знайди Start → End")
    st.markdown("2. Подивись: де найбільше гілок, де є зворотні стрілки")
    st.markdown("3. Шукай: loops (повернення назад), обходи основного маршруту")
    st.markdown("4. Задай питання: Чому тут так багато варіантів? Чому тут повертаються назад?")
    st.markdown("📌 Heuristics Miner = реальна поведінка, з шумом")

    st.subheader("🔥 Heuristics Miner (Custom Graphviz)")
    dot = visualizations.heuristics_graph(transitions["edges"], transitions["bottleneck_text"])
    st.graphviz_chart(dot)

    st.markdown("Як це читати (практично):")
    st.markdown("🔴 товста + червона → критичний bottleneck")
    st.markdown("🟢 товста + зелена → стабільний шлях")

    with st.expander("🔍 Збільшений вигляд (zoom & scroll) для великих процесів"):
        try:
            svg_markup = visualizations.heuristics_graph_to_svg(dot)
            components.html(
                visualizations.zoomable_svg_component(svg_markup, height=600),
                height=680,
                scrolling=True,
            )
        except Exception:
            st.info("Zoom-перегляд недоступний у цьому середовищі (відсутній graphviz 'dot').")

    return {"figure": dot, "statistics": transitions}


def render_variant_analysis_section(variants):
    st.subheader("⚡ Variant analysis (ТОП 5 сценаріїв)")

    st.dataframe(variants["variant_counts"])

    st.markdown("### 📊 Загальна структура варіантів")
    st.write(f"🔢 Загальна кількість кейсів: **{variants['total_cases']}**")
    st.write(f"🧭 Унікальних сценаріїв: **{variants['unique_variants']}**")
    st.write(f"🥇 Частка найпоширенішого сценарію: **{variants['top1_share']:.1f}%**")
    st.write(f"🏆 Частка ТОП-5 сценаріїв: **{variants['top5_share']:.1f}%**")

    st.info(variants["conclusion"])

    return {"statistics": variants}


def render_case_timeline_section(df, step_analysis=None):
    st.subheader("📅 Timeline кейсу")
    case_list = df["Case ID"].unique()
    selected_case = st.selectbox("Оберіть кейс", case_list)

    top_step = step_analysis.get("top_step") if step_analysis else None
    bottleneck_activity = top_step["Activity Name"] if top_step is not None else None

    case_df = df[df["Case ID"] == selected_case].sort_values("Start Timestamp")
    fig = visualizations.case_timeline(case_df, selected_case, bottleneck_activity)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "🟢 Звичайний крок · 🔴 Rework (повторюваний крок у цьому кейсі) "
        "або крок, визначений як основний bottleneck процесу."
    )

    return {"figure": fig}


def render_role_analysis_section(role_analysis):
    st.markdown("---")
    st.header("👥 Process Role Analysis")
    st.caption("Розділ показано, оскільки у файлі присутня колонка **Role**.")

    st.metric("Середня кількість ролей на кейс (Average FTE per Case)", f"{role_analysis['avg_roles_per_case']:.2f}")

    st.subheader("Role vs Activity Matrix")
    fig_matrix = visualizations.role_activity_matrix(role_analysis["role_activity"])
    st.plotly_chart(fig_matrix, use_container_width=True)

    st.subheader("Role Workload Distribution")
    fig_workload = visualizations.role_workload_chart(role_analysis["role_workload"])
    st.plotly_chart(fig_workload, use_container_width=True)

    fig_bottleneck = None
    st.subheader("Role Bottleneck Ranking")
    if not role_analysis["role_bottleneck_ranking"].empty:
        fig_bottleneck = visualizations.role_bottleneck_ranking_chart(
            role_analysis["role_bottleneck_ranking"]
        )
        st.plotly_chart(fig_bottleneck, use_container_width=True)
    else:
        st.info("Явно виражених bottleneck-активностей, пов'язаних з конкретною роллю, не виявлено.")

    col1, col2 = st.columns(2)
    with col1:
        if role_analysis["top_bottleneck_role"]:
            st.warning(f"🚧 Роль з найбільшою участю у bottleneck-активностях: **{role_analysis['top_bottleneck_role']}**")
    with col2:
        if role_analysis["top_rework_role"]:
            st.warning(f"🔁 Роль з найвищою частотою rework: **{role_analysis['top_rework_role']}**")

    with st.expander("Тривалість кроків за ролями (найдовші в середньому)"):
        st.dataframe(role_analysis["longest_duration_roles"])

    return {
        "figures": {"matrix": fig_matrix, "workload": fig_workload, "bottleneck": fig_bottleneck},
        "statistics": role_analysis,
    }


def render_region_analysis_section(region_analysis):
    st.markdown("---")
    st.header("🌍 Regional Analysis")
    st.caption("Розділ показано, оскільки у файлі присутня колонка **Region**.")

    st.subheader("Lead Time by Region")
    fig_lead_time = visualizations.region_lead_time_bar(region_analysis["region_lead_time"])
    st.plotly_chart(fig_lead_time, use_container_width=True)

    st.subheader("Rework by Region")
    fig_rework = visualizations.region_rework_bar(region_analysis["region_rework"])
    st.plotly_chart(fig_rework, use_container_width=True)

    st.subheader("Regional Performance Matrix")
    fig_matrix = visualizations.region_performance_matrix(
        region_analysis["region_lead_time"], region_analysis["region_rework"]
    )
    st.plotly_chart(fig_matrix, use_container_width=True)

    col1, col2 = st.columns(2)
    if region_analysis["leader"] is not None:
        col1.success(
            f"🏆 Найкращий регіон: **{region_analysis['leader']['Region']}** "
            f"(Lead Time = {region_analysis['leader']['avg_lead_time']:.2f} год)"
        )
    if region_analysis["outsider"] is not None:
        col2.error(
            f"⚠️ Регіон, що потребує уваги: **{region_analysis['outsider']['Region']}** "
            f"(Lead Time = {region_analysis['outsider']['avg_lead_time']:.2f} год)"
        )

    st.subheader("📌 Automated Insights")
    for insight in region_analysis["insights"]:
        st.write(f"- {insight}")

    st.subheader("💡 Recommendations")
    for rec in region_analysis["recommendations"]:
        st.write(f"- {rec}")

    return {
        "figures": {"lead_time": fig_lead_time, "rework": fig_rework, "matrix": fig_matrix},
        "statistics": region_analysis,
    }


def render_executive_summary_section(result: AnalysisResult):
    st.markdown("---")
    st.header("🧠 Executive Summary та рекомендації")

    summary = result.executive_summary
    st.markdown(summary["summary_text"])
    st.markdown(summary["recommendations"])

    st.subheader("📊 Process Maturity Score")
    st.metric("Індекс зрілості процесу (0–100)", result.maturity_score)
    if result.maturity_score > 80:
        st.success("Процес високозрілий та контрольований.")
    elif result.maturity_score > 50:
        st.warning("Процес середнього рівня зрілості. Є зони для оптимізації.")
    else:
        st.error("Процес має значні структурні проблеми та потребує оптимізації.")

    st.header("🧠 AI Process Narrative")
    st.info(result.ai_narrative)

    kpis = result.kpis()

    st.markdown("---")
    st.header("📊 KPI Scorecard")
    if kpis.get("avg_fte_per_case") is not None:
        col1, col2, col3, col4, col5 = st.columns(5)
    else:
        col1, col2, col3, col4 = st.columns(4)
        col5 = None
    col1.metric("Lead Time (avg)", f"{kpis['avg_lead_time']:.2f} h")
    col2.metric("Rework Rate", f"{result.statistics['rework']['percent_rework']}%")
    col3.metric("Variant Count", result.variants["unique_variants"])
    col4.metric("Main Variant Share", f"{result.variants['top1_share']:.1f}%")
    if col5 is not None:
        col5.metric("Average FTE per Case", f"{kpis['avg_fte_per_case']:.2f}")

    st.header("🚀 Improvement Roadmap")
    for item in result.roadmap:
        st.write(item)

    pdf_buffer = reporting.generate_pdf_report(result)
    track_metric("pdf_generated")
    st.download_button(
        label="📄 Завантажити Executive Report (PDF)",
        data=pdf_buffer,
        file_name="process_mining_executive_report.pdf",
        mime="application/pdf",
    )


if __name__ == "__main__":
    main()

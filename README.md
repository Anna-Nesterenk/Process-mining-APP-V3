# Process Mining App

## Опис проєкту

**Process Mining App** — це вебзастосунок, розроблений на базі **Streamlit**, який дозволяє виконувати аналіз бізнес-процесів за журналами подій (Event Logs), представленими у форматі Excel.

Застосунок автоматизує основні етапи Process Mining:

* завантаження та перевірку журналу подій;
* підготовку даних до аналізу;
* побудову Event Log;
* розрахунок ключових процесних метрик;
* візуалізацію процесу;
* формування звітів у форматі PDF.

---

# Методологія розрахунку часу (Time Calculation Methodology)

Усі розрахунки, пов'язані з часом і тривалістю процесу (Lead Time, тривалість
кейсу, Waiting Time, тривалість окремих активностей), виконуються на основі
**календарних днів і годин за моделлю 24/7**.

Поточна версія застосунку **не розрізняє**:

* робочі та неробочі години;
* робочі дні та вихідні;
* державні свята;
* індивідуальні графіки роботи співробітників;
* часові пояси.

Тому всі часові показники відображають фактичний календарний час між
відповідними мітками часу (timestamps), а не "робочий" час у прийнятому в
компанії розумінні. Це саме формулювання відображається користувачу в розділі
**Загальна статистика логів** (UI) та на завершальній сторінці PDF Executive
Report — єдине джерело цього тексту: `modules/config.py`
(`TIME_METHODOLOGY_TITLE` / `TIME_METHODOLOGY_TEXT`).

---

# Основні можливості

* 📂 Завантаження журналу подій з Excel
* ✅ Автоматична перевірка коректності даних
* 🔄 Формування Process Mining Event Log
* 📊 Розрахунок статистичних показників процесу
* ⏱ Аналіз тривалості кейсів та окремих етапів
* 🔁 Аналіз повторних виконань (Rework)
* 📈 Побудова інтерактивних графіків
* 📑 Генерація PDF-звіту
* 📌 Збір статистики використання застосунку

---

# Архітектура (V2)

Проєкт побудований за модульним принципом із єдиним джерелом істини
(Single Source of Truth) для всіх кейс-рівневих метрик: кожна агрегація
`groupby("Case ID")` виконується один раз, у `case_metrics.py`, і
переюзається аналітикою, візуалізаціями та PDF-звітом.

```text
                    Користувач
                         │
                         ▼
                  app.py (UI, orchestration)
                         │
 ┌───────────────────────┼─────────────────────────┐
 │                       │                         │
 ▼                       ▼                         ▼
Validation         Data Processing          Metrics
(data_validation) (data_processing)    (metrics_tracker)
                         │  (event-level: timestamps,
                         │   waiting_hours, step_duration_hours)
                         ▼
                  case_metrics.py
              prepare_analysis_data()
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
    case_times                activity_statistics
   (Single Source of Truth)   (Case+Activity grain)
         │                               │
         └───────────────┬───────────────┘
                          ▼
                   analytics.py
              build_full_analysis()
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
       visualizations.py         models.py
        (figure builders)      AnalysisResult
              │                        │
              └───────────┬────────────┘
                           ▼
                     reporting.py
                 generate_pdf_report()
                           │
                           ▼
                     Streamlit UI
              (charts + downloadable PDF,
               both built from the same
               AnalysisResult)
```

Такий підхід дозволяє легко підтримувати та розширювати функціональність
застосунку, і гарантує, що PDF-звіт завжди показує ті самі цифри й графіки,
що й інтерфейс Streamlit.

---

# Структура проєкту

```text
process_mining_app/
│
├── app.py
├── README.md
├── requirements.txt
├── packages.txt          # apt packages for Streamlit Cloud (graphviz 'dot' binary)
│
└── modules/
    ├── analytics.py
    ├── case_metrics.py
    ├── config.py
    ├── data_processing.py
    ├── data_validation.py
    ├── metrics_tracker.py
    ├── models.py
    ├── reporting.py
    └── visualizations.py
```

---

# Призначення модулів

## app.py

Головна точка входу в застосунок.

Відповідає за:

* створення інтерфейсу Streamlit;
* взаємодію з користувачем;
* виклик модулів аналізу;
* відображення результатів.

У цьому файлі бажано не розміщувати бізнес-логіку.

---

## modules/config.py

Централізоване сховище конфігурацій та констант.

Містить:

* назву застосунку;
* службові параметри;
* перелік обов'язкових колонок;
* налаштування PDF;
* інші константи проєкту.

---

## modules/data_validation.py

Виконує перевірку вхідних даних.

Перевіряє:

* наявність необхідних колонок;
* коректність типів даних;
* відсутність критичних помилок;
* готовність даних до аналізу.

---

## modules/data_processing.py

Підготовка **подієвого** (event-level) рівня даних до Process Mining.

Основні функції:

* конвертація дат;
* сортування журналу подій;
* обчислення `waiting_hours` (час очікування перед кожною подією) та
  `step_duration_hours`;
* створення Event Log для бібліотеки pm4py (готовий до використання, але
  наразі жоден renderer його не споживає — див. коментар у файлі).

Тут **не** виконується жодної агрегації по `Case ID` — це відповідальність
`case_metrics.py`.

---

## modules/case_metrics.py

**Single Source of Truth** для всіх кейс-рівневих, activity-рівневих,
role-рівневих та region-рівневих метрик.

* `calculate_case_times(df)` — одна агрегація `groupby("Case ID")` на весь
  застосунок: Case ID, Start/Finish Timestamp, Duration (hours), Lead Time,
  Waiting Time, Number of Activities.
* `calculate_activity_statistics(df)` — агрегація на рівні Case+Activity
  (для bubble chart / step duration analysis).
* `calculate_role_statistics(df)` — агрегація на рівні Role (лише якщо є
  колонка **Role**), включно з розрахунком FTE (CR-02):

  ```
  x_role  = середнє, по кейсах, у яких брала участь роль, від суми
            тривалості всіх активностей цієї ролі в межах кейсу
  FTE_role = x_role / 7.5 / 21 * 1.15
  Average FTE per Case = Σ FTE_role (по всіх ролях процесу)
  ```

  Це оцінка потрібного FTE-ресурсу на один кейс, а НЕ кількість фізичних
  співробітників і НЕ середня кількість різних ролей на кейс (це була
  попередня, помилкова, реалізація метрики).
* `calculate_region_statistics(df, case_times)` — агрегація на рівні Region
  (лише якщо є колонка **Region**): Lead Time (num/avg/median/min/max),
  Waiting Time (avg/median), Workload (total activities, avg per case,
  частка від загального обсягу). Порожні/відсутні значення Region
  замінюються на `"Unknown"` і аналізуються як звичайний регіон, а не
  відкидаються.
* `prepare_analysis_data(df)` — викликає всі функції вище один раз і
  повертає результат для подальшого використання в `analytics.py`,
  `visualizations.py` та `reporting.py`.

Жоден інший модуль не повинен самостійно виконувати `groupby("Case ID")` /
`groupby("Role")` / `groupby("Region")` — нові кейс-, role- чи
region-рівневі метрики додаються сюди.

---

## modules/analytics.py

Основний модуль бізнес-логіки. Споживає `case_times` /
`activity_statistics` / `role_statistics` / `region_statistics` з
`case_metrics.py` замість повторного розрахунку.

Реалізує:

* Lead Time / Waiting Time порівняння (rework vs без rework);
* Rework analysis;
* Step duration / bottleneck (bubble chart) analysis;
* Transition (Heuristics Miner edges) analysis;
* Variant analysis;
* `role_analysis()` — участь ролей у bottleneck-активностях, rework,
  ранжування за FTE (лише якщо є колонка **Role**);
* `region_analysis()` — Lead Time / Rework / Bottleneck / Waiting Time /
  Workload по регіонах, визначення лідера й аутсайдера (композитний
  рейтинг: Lead Time + Rework Rate + Bottleneck share), порівняння з
  середнім/медіанним по всьому датасету, автоматичні insights та
  рекомендації (лише якщо є колонка **Region**);
* `compute_maturity_score()` — Process Maturity Score з повною
  деталізацією (CR-04): базовий бал, кожен штраф з причиною/пороговим
  значенням/фактичним значенням метрики, і автоматично згенеровані Focus
  Areas — а не єдине непрозоре число;
* Executive Summary (включно з Organizational/Regional Findings, коли
  доступні), AI Narrative, Improvement Roadmap;
* `build_full_analysis()` — оркеструє всі перелічені вище розрахунки один
  раз і повертає єдиний словник результатів.

Нові KPI рекомендується додавати саме до цього модуля (розраховуючи їх з
`case_times` / `activity_statistics` / `role_statistics` /
`region_statistics`, а не з сирого DataFrame).

---

## modules/models.py

Містить `AnalysisResult` — типізований контейнер, що об'єднує `case_times`,
статистику, фігури, transition/variant аналіз та executive summary одного
запуску аналізу. Один і той самий `AnalysisResult` використовується і для
рендеру Streamlit UI, і для генерації PDF — це гарантує, що звіт завжди
відповідає тому, що бачить користувач на екрані.

---

## modules/visualizations.py

Відповідає за побудову графіків та візуалізацій.

Використовує:

* Plotly (гістограми, box plot, bubble chart, Gantt-timeline, bar/scatter
  для Role та Region Analysis);
* Matplotlib / Seaborn (частина внутрішніх допоміжних графіків);
* Graphviz (Heuristics Miner, включно з SVG-версією для zoom-перегляду,
  CR-04).

Модуль лише відображає вже агреговані дані (з `case_metrics.py` /
`analytics.py`), не виконує власних `groupby("Case ID")` /
`groupby("Role")` / `groupby("Region")`.

---

## modules/reporting.py

Формує PDF Executive Report:

1. Executive Overview + KPI Summary (кількість кейсів, період аналізу,
   середня та медіанна тривалість кейсу, і, якщо у файлі є колонка **Role**,
   Average FTE per Case);
2. Case Duration Distribution (Histogram);
3. Heuristics Miner (Custom Graphviz);
4. Lead Time: Rework vs Non-Rework (графік + пояснення: кількість і частка
   кейсів з rework, інтерпретація впливу на Lead Time);
5. Bubble Chart: Duration per Step vs Rework Count (+ автоматично
   згенерований висновок про основний bottleneck);
6. **[умовно]** Role Analysis — лише якщо у файлі є колонка **Role**;
7. **[умовно]** Regional Analysis — лише якщо у файлі є колонка **Region**;
8. Executive Summary, рекомендації (включно з organizational/regional
   findings, якщо доступні), **деталізований** Process Maturity Score
   (базовий бал, кожен штраф з причиною та пороговим значенням, Focus
   Areas — CR-04), і Time Calculation Methodology (CR-03).

Risk Heatmap повністю відсутній у застосунку (видалений з UI, візуалізацій
та звіту).

Кожен графік у звіті береться напряму з `AnalysisResult.figures` — тих самих
об'єктів Plotly/Matplotlib/Graphviz, які `app.py` вже один раз побудував для
відображення в Streamlit UI. PDF не перебудовує жоден графік, а лише
рендерить у PNG те, що вже існує (`visualizations.py` викликається лише як
резервний варіант, якщо фігура з якоїсь причини відсутня в `figures`).

**Export pipeline:** Plotly-графіки експортуються у PNG через `kaleido`
(версія закріплена як `kaleido==0.2.1` у `requirements.txt` — новіші версії
вимагають окремого завантаження Chrome і мовчки ламають `fig.to_image()`).
Graphviz-граф рендериться через системний бінарник `dot`, який
встановлюється на Streamlit Cloud через `packages.txt`. Обидва експортери
логують причину збою (`logging`), якщо PNG все ж не вдалося згенерувати,
замість того щоб мовчки показувати порожню сторінку.

Шрифт для кирилиці береться напряму з пакета matplotlib (`DejaVu Sans`),
тому PDF не залежить від локально встановлених TTF-файлів і однаково працює
локально та на Streamlit Cloud.

---

## modules/metrics_tracker.py

Збирає статистику використання застосунку.

Відстежує:

* кількість відкриттів застосунку;
* кількість завантажених файлів;
* кількість виконаних аналізів;
* кількість сформованих PDF-звітів.

Статистика зберігається локально у JSON-файлі.

---

# Потік виконання

Після запуску застосунку обробка виконується у такій послідовності:

```text
Запуск Streamlit
        │
        ▼
Завантаження Excel
        │
        ▼
Перевірка даних
        │
        ▼
Підготовка журналу подій
        │
        ▼
Створення Event Log
        │
        ▼
Розрахунок процесних метрик
        │
        ▼
Побудова графіків
        │
        ▼
Формування PDF-звіту
```

---

# Як додати нову аналітику

Рекомендується дотримуватися наступної схеми:

1. Реалізувати розрахунок у `analytics.py`.
2. За потреби створити новий графік у `visualizations.py`.
3. Викликати нову функцію в `app.py`.
4. Додати інформацію до PDF-звіту (за необхідності) у `reporting.py`.

Такий підхід дозволяє зберігати чітке розділення відповідальності між модулями.

---

# Встановлення

```bash
git clone <repository_url>

cd process_mining_app

pip install -r requirements.txt
```

---

# Запуск

```bash
streamlit run app.py
```

Після запуску відкрийте адресу, яку відобразить Streamlit (зазвичай `http://localhost:8501`).

---

# Використані технології

* Python
* Streamlit
* Pandas
* pm4py
* Plotly
* Matplotlib
* Seaborn
* ReportLab
* Graphviz

---

# Подальший розвиток

Поточна архітектура вже підтримує модульний підхід і є гарною основою для подальшого масштабування.

У перспективі планується:

* розширення набору Process Mining KPI;
* підтримка декількох форматів журналів подій;
* інтеграція з інформаційними системами;
* додавання нових візуалізацій;
* розвиток архітектури до рівня сервісно-орієнтованої структури.


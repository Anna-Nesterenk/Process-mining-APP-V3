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

**Single Source of Truth** для всіх кейс-рівневих та activity-рівневих
метрик.

* `calculate_case_times(df)` — одна агрегація `groupby("Case ID")` на весь
  застосунок: Case ID, Start/Finish Timestamp, Duration (hours), Lead Time,
  Waiting Time, Number of Activities.
* `calculate_activity_statistics(df)` — агрегація на рівні Case+Activity
  (для bubble chart / risk heatmap).
* `prepare_analysis_data(df)` — викликає обидві функції один раз і повертає
  результат для подальшого використання в `analytics.py`, `visualizations.py`
  та `reporting.py`.

Жоден інший модуль не повинен самостійно виконувати `groupby("Case ID")` —
нові кейс-рівневі метрики додаються сюди.

---

## modules/analytics.py

Основний модуль бізнес-логіки. Споживає `case_times` /
`activity_statistics` з `case_metrics.py` замість повторного розрахунку.

Реалізує:

* Lead Time / Waiting Time порівняння (rework vs без rework);
* Rework analysis;
* Step duration / bottleneck (bubble chart) analysis;
* Transition (Heuristics Miner edges) analysis;
* Variant analysis;
* Executive Summary, Maturity Score, AI Narrative, Improvement Roadmap;
* `build_full_analysis()` — оркеструє всі перелічені вище розрахунки один
  раз і повертає єдиний словник результатів.

Нові KPI рекомендується додавати саме до цього модуля (розраховуючи їх з
`case_times` / `activity_statistics`, а не з сирого DataFrame).

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

* Plotly;
* Matplotlib;
* Seaborn;
* Graphviz.

Модуль лише відображає вже агреговані дані (з `case_metrics.py` /
`analytics.py`), не виконує власних `groupby("Case ID")`.

---

## modules/reporting.py

Формує сучасний PDF Executive Report:

* Cover Page (заголовок, дата формування, період аналізу, кількість кейсів);
* KPI Summary (кейси, активності, Lead Time, тривалість кейсу);
* Visualizations (усі релевантні графіки, вбудовані як PNG);
* Executive Summary, рекомендації, Process Maturity Score.

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


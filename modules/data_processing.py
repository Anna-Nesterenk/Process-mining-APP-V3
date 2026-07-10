"""
data_processing.py
-------------------
Event-level preprocessing that runs AFTER validation succeeds and BEFORE any
case-level aggregation (case_metrics.py) or analytics takes place:

    - normalising timestamp columns,
    - sorting events within a case,
    - deriving the per-event waiting time (FR-5) and per-step duration,
    - building the pm4py EventLog object (kept for future pm4py-based
      mining, currently unused by any renderer -- see build_event_log()).

Everything here operates on individual events (rows). Case-level and
activity-level aggregation (the actual `groupby("Case ID")` work) lives
exclusively in `case_metrics.py` (Single Source of Truth, FR-1/FR-2).
"""

import pandas as pd
from pm4py.objects.log.obj import Event, EventLog, Trace
from pm4py.objects.log.util import dataframe_utils

CASE_ID_COL = "Case ID"
ACTIVITY_COL = "Activity Name"
START_COL = "Start Timestamp"
FINISH_COL = "Finish Timestamp"


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise timestamp columns, sort events chronologically within each
    case, and compute the per-event `waiting_hours` column used everywhere
    downstream as the FR-5 Waiting Time building block:

        waiting_hours(event i) = Start(i) - Finish(previous event in case)

    Returns a new, cleaned DataFrame ready for analysis.
    """
    df = df.copy()

    df[START_COL] = pd.to_datetime(df[START_COL])
    if FINISH_COL in df.columns:
        df[FINISH_COL] = pd.to_datetime(df[FINISH_COL])

    df = dataframe_utils.convert_timestamp_columns_in_df(df)
    df = df.sort_values([CASE_ID_COL, START_COL]).reset_index(drop=True)

    df["previous_finish"] = df.groupby(CASE_ID_COL)[FINISH_COL].shift(1)
    df["waiting_hours"] = (
        df[START_COL] - df["previous_finish"]
    ).dt.total_seconds() / 3600

    return df


def compute_step_durations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a `step_duration_hours` column.

    If a real `Finish Timestamp` is available (mandatory as of Stage 1), use
    it directly. Otherwise fall back to the previous heuristic of using the
    next event's start time within the same case.
    """
    df = df.copy()

    if FINISH_COL in df.columns and df[FINISH_COL].notna().any():
        df["step_duration_hours"] = (
            df[FINISH_COL] - df[START_COL]
        ).dt.total_seconds() / 3600
    else:
        df = df.sort_values([CASE_ID_COL, START_COL])
        df[FINISH_COL] = df.groupby(CASE_ID_COL)[START_COL].shift(-1)
        df[FINISH_COL] = df[FINISH_COL].fillna(df[START_COL] + pd.Timedelta(minutes=1))
        df["step_duration_hours"] = (
            df[FINISH_COL] - df[START_COL]
        ).dt.total_seconds() / 3600

    return df


def build_event_log(df: pd.DataFrame) -> EventLog:
    """
    Convert the (validated, prepared) DataFrame into a pm4py EventLog.

    NOTE: not currently called from app.py -- the "Heuristics Miner" section
    is a custom Graphviz edge diagram built directly from the DataFrame
    (see analytics.transitions_analysis / visualizations.heuristics_graph),
    not a pm4py Petri net. The builder is kept here, ready to use, for
    future pm4py-based mining without adding an unused aggregation pass to
    every run today (Sec. 6 performance requirement).
    """
    log = EventLog()

    for case_id, group in df.groupby(CASE_ID_COL):
        trace = Trace()
        trace.attributes["concept:name"] = str(case_id)

        for _, row in group.sort_values(START_COL).iterrows():
            event = Event()
            event["concept:name"] = row[ACTIVITY_COL]
            event["time:Start Timestamp"] = row[START_COL]
            if FINISH_COL in row and pd.notna(row[FINISH_COL]):
                event["time:Finish Timestamp"] = row[FINISH_COL]
            trace.append(event)

        log.append(trace)

    return log

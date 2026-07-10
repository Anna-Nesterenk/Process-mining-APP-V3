"""
metrics_tracker.py
-------------------
Lightweight, file-backed usage counter for the app (visits, uploads,
analyses run, PDF reports generated). Extracted verbatim in behaviour from
the original script, just organised as a small self-contained module.
"""

import json
import os

import streamlit as st

from modules.config import METRICS_FILE, DEFAULT_METRICS


def load_metrics() -> dict:
    """Load metrics from disk, falling back to defaults if the file is missing."""
    if os.path.exists(METRICS_FILE):
        with open(METRICS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_METRICS.copy()


def save_metrics(metrics: dict) -> None:
    """Persist metrics to disk."""
    with open(METRICS_FILE, "w") as f:
        json.dump(metrics, f)


def track_metric(metric_name: str) -> None:
    """Increment a single named metric and persist it."""
    metrics = load_metrics()
    metrics[metric_name] = metrics.get(metric_name, 0) + 1
    save_metrics(metrics)


def track_once_per_session(session_flag: str, metric_name: str) -> None:
    """
    Track a metric only once per Streamlit session, guarded by a session_state flag.
    Used for events that should be counted once per visit/upload (not once per rerun).
    """
    if session_flag not in st.session_state:
        track_metric(metric_name)
        st.session_state[session_flag] = True


def render_usage_sidebar() -> None:
    """Render the 'App usage' block in the sidebar."""
    metrics = load_metrics()

    st.sidebar.markdown("### 📊 App usage")
    st.sidebar.metric("Users", metrics.get("app_visits", 0))
    st.sidebar.metric("Datasets uploaded", metrics.get("datasets_uploaded", 0))
    st.sidebar.metric("Analyses run", metrics.get("analyses_run", 0))
    st.sidebar.metric("Reports generated", metrics.get("pdf_generated", 0))

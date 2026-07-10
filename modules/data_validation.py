"""
data_validation.py
-------------------
Stage 1 deliverable: Data Upload and Validation Module.

Responsible for reading the uploaded Excel event log and validating it
BEFORE any process-mining analysis is executed. Validation covers:

    1. Required (mandatory) columns are present.
    2. Mandatory columns contain no empty values.
    3. Mandatory columns have the expected data type/format
       (Case ID non-empty identifier, Activity Name text,
       Start/Finish Timestamp valid datetimes).

Only if every check passes does `validate_event_log()` report success,
allowing the calling code (app.py) to proceed to preprocessing/analysis.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd
import streamlit as st

from modules.config import MANDATORY_COLUMNS


@dataclass
class ValidationResult:
    """Container for the outcome of validating an uploaded event log."""

    is_valid: bool = True
    missing_columns: List[str] = field(default_factory=list)
    # column -> list of 1-based row numbers where the value is empty
    empty_value_rows: Dict[str, List[int]] = field(default_factory=dict)
    # human-readable messages describing data-type/format problems
    type_errors: List[str] = field(default_factory=list)

    def add_missing_columns(self, columns: List[str]) -> None:
        if columns:
            self.missing_columns = columns
            self.is_valid = False

    def add_empty_values(self, column: str, row_numbers: List[int]) -> None:
        if row_numbers:
            self.empty_value_rows[column] = row_numbers
            self.is_valid = False

    def add_type_error(self, message: str) -> None:
        self.type_errors.append(message)
        self.is_valid = False


# ---------------------------------------------------------------------------
# Individual validation rules
# ---------------------------------------------------------------------------
def check_required_columns(df: pd.DataFrame) -> List[str]:
    """Rule 1: return the list of mandatory columns that are missing from df."""
    return [col for col in MANDATORY_COLUMNS if col not in df.columns]


def check_empty_values(df: pd.DataFrame, columns: List[str]) -> Dict[str, List[int]]:
    """
    Rule 2: for each given column present in df, return the (1-based, matching
    the row's position in the Excel file counting the header as row 1) row
    numbers where the value is missing/blank.
    """
    issues: Dict[str, List[int]] = {}
    for col in columns:
        if col not in df.columns:
            continue  # already reported by check_required_columns
        is_blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if is_blank.any():
            # +2 => +1 for 0-index -> 1-index, +1 for the header row in Excel
            row_numbers = (df.index[is_blank] + 2).tolist()
            issues[col] = row_numbers
    return issues


def check_data_types(df: pd.DataFrame) -> List[str]:
    """
    Rule 3: validate the expected format of mandatory fields.

    - Case ID: must not be empty (string or numeric) -- emptiness already
      covered by check_empty_values, so here we only flag fully-null column.
    - Activity Name: must be interpretable as text.
    - Start Timestamp / Finish Timestamp: must be parseable as datetimes.
    """
    errors: List[str] = []

    if "Case ID" in df.columns and df["Case ID"].dropna().empty:
        errors.append("Колонка 'Case ID' не містить жодного коректного значення.")

    if "Activity Name" in df.columns:
        non_null = df["Activity Name"].dropna()
        if not non_null.empty and not non_null.apply(lambda x: isinstance(x, str) or str(x).strip() != "").all():
            errors.append("Колонка 'Activity Name' містить некоректні (нетекстові) значення.")

    for ts_col in ("Start Timestamp", "Finish Timestamp"):
        if ts_col not in df.columns:
            continue
        parsed = pd.to_datetime(df[ts_col], errors="coerce")
        # rows that had a non-empty original value but failed to parse as datetime
        original_non_empty = df[ts_col].notna() & (df[ts_col].astype(str).str.strip() != "")
        invalid_mask = original_non_empty & parsed.isna()
        if invalid_mask.any():
            bad_rows = (df.index[invalid_mask] + 2).tolist()
            errors.append(
                f"Колонка '{ts_col}' містить значення, які не вдається розпізнати як дату/час "
                f"(рядки: {', '.join(map(str, bad_rows[:20]))}"
                f"{'...' if len(bad_rows) > 20 else ''})."
            )

    # Finish Timestamp should not occur before Start Timestamp
    if {"Start Timestamp", "Finish Timestamp"}.issubset(df.columns):
        start = pd.to_datetime(df["Start Timestamp"], errors="coerce")
        finish = pd.to_datetime(df["Finish Timestamp"], errors="coerce")
        inconsistent = finish.notna() & start.notna() & (finish < start)
        if inconsistent.any():
            bad_rows = (df.index[inconsistent] + 2).tolist()
            errors.append(
                "Знайдено рядки, де 'Finish Timestamp' настає раніше за 'Start Timestamp' "
                f"(рядки: {', '.join(map(str, bad_rows[:20]))}"
                f"{'...' if len(bad_rows) > 20 else ''})."
            )

    return errors


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def validate_event_log(df: pd.DataFrame) -> ValidationResult:
    """Run all validation rules in order and return the aggregated result."""
    result = ValidationResult()

    # Rule 1: required columns
    missing = check_required_columns(df)
    result.add_missing_columns(missing)
    if missing:
        # Cannot meaningfully run further checks if columns are missing.
        return result

    # Rule 2: empty values in mandatory columns
    empty_values = check_empty_values(df, MANDATORY_COLUMNS)
    for col, rows in empty_values.items():
        result.add_empty_values(col, rows)

    # Rule 3: data types / formats
    for message in check_data_types(df):
        result.add_type_error(message)

    return result


def render_validation_errors(result: ValidationResult) -> None:
    """Display validation errors to the user in a clear, actionable way."""
    if result.missing_columns:
        st.error(
            "❌ Файл не містить обов'язкові колонки: "
            f"**{', '.join(result.missing_columns)}**.\n\n"
            f"Обов'язкові колонки: {', '.join(MANDATORY_COLUMNS)}."
        )
        return  # no point showing further checks; columns aren't even there

    if result.empty_value_rows:
        st.error("❌ Знайдено порожні значення в обов'язкових колонках:")
        for col, rows in result.empty_value_rows.items():
            preview = ", ".join(map(str, rows[:20]))
            more = "..." if len(rows) > 20 else ""
            st.markdown(f"- **{col}**: рядки {preview}{more} ({len(rows)} шт.)")

    if result.type_errors:
        st.error("❌ Виявлено помилки формату даних:")
        for message in result.type_errors:
            st.markdown(f"- {message}")


def load_and_validate_excel(uploaded_file):
    """
    Read the uploaded Excel file and run it through validation.

    Returns
    -------
    (df, result): tuple
        df      -> the parsed DataFrame (None if the file could not be read)
        result  -> ValidationResult (None if the file could not be read at all)
    """
    try:
        df = pd.read_excel(uploaded_file)
    except Exception as exc:
        st.error(f"❌ Не вдалося прочитати Excel-файл: {exc}")
        return None, None

    result = validate_event_log(df)
    return df, result

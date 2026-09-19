from __future__ import annotations

import os
from datetime import date, datetime, time, timezone

import pandas as pd
import psycopg

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS grip_measurements (
    measurement_id BIGSERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL,
    dominant_hand TEXT,
    left_1_kg DOUBLE PRECISION,
    left_2_kg DOUBLE PRECISION,
    left_3_kg DOUBLE PRECISION,
    right_1_kg DOUBLE PRECISION,
    right_2_kg DOUBLE PRECISION,
    right_3_kg DOUBLE PRECISION,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if st is not None:
        try:
            value = st.secrets.get(name)
            if value:
                return str(value)
        except Exception:
            pass
    return None


def _database_url() -> str:
    value = _secret("GRIP_DATABASE_URL") or _secret("WITHINGS_DATABASE_URL")
    if not value:
        raise RuntimeError(
            "Grip storage needs GRIP_DATABASE_URL or WITHINGS_DATABASE_URL."
        )
    return value


def _ensure_table(con: psycopg.Connection) -> None:
    con.execute(CREATE_SQL)
    con.commit()


def _clean_attempt(value: float | int | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if value > 0 else None


def insert_grip_measurement(
    measured_date: date,
    measured_time: time,
    dominant_hand: str | None,
    left_attempts: list[float | None],
    right_attempts: list[float | None],
    notes: str | None = None,
) -> None:
    left = (_clean_attempt(v) for v in (left_attempts + [None, None, None])[:3])
    right = (_clean_attempt(v) for v in (right_attempts + [None, None, None])[:3])
    l1, l2, l3 = left
    r1, r2, r3 = right
    if all(v is None for v in (l1, l2, l3, r1, r2, r3)):
        raise ValueError("Enter at least one grip-strength attempt.")

    measured_at = datetime.combine(measured_date, measured_time).replace(
        tzinfo=timezone.utc
    )
    with psycopg.connect(_database_url()) as con:
        _ensure_table(con)
        con.execute(
            """
            INSERT INTO grip_measurements (
                measured_at, dominant_hand,
                left_1_kg, left_2_kg, left_3_kg,
                right_1_kg, right_2_kg, right_3_kg,
                notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                measured_at,
                dominant_hand,
                l1,
                l2,
                l3,
                r1,
                r2,
                r3,
                notes.strip() if notes and notes.strip() else None,
            ),
        )
        con.commit()


def delete_grip_measurement(measurement_id: int) -> None:
    with psycopg.connect(_database_url()) as con:
        _ensure_table(con)
        con.execute(
            "DELETE FROM grip_measurements WHERE measurement_id = %s",
            (int(measurement_id),),
        )
        con.commit()


def load_grip_measurements() -> pd.DataFrame:
    columns = [
        "measurement_id",
        "measured_at",
        "dominant_hand",
        "left_1_kg",
        "left_2_kg",
        "left_3_kg",
        "right_1_kg",
        "right_2_kg",
        "right_3_kg",
        "notes",
    ]
    with psycopg.connect(_database_url()) as con:
        _ensure_table(con)
        rows = con.execute(
            """
            SELECT
                measurement_id, measured_at, dominant_hand,
                left_1_kg, left_2_kg, left_3_kg,
                right_1_kg, right_2_kg, right_3_kg,
                notes
            FROM grip_measurements
            ORDER BY measured_at
            """
        ).fetchall()

    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame

    frame["measured_at"] = pd.to_datetime(frame["measured_at"], errors="coerce")
    left_cols = ["left_1_kg", "left_2_kg", "left_3_kg"]
    right_cols = ["right_1_kg", "right_2_kg", "right_3_kg"]
    for column in left_cols + right_cols:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["best_left_kg"] = frame[left_cols].max(axis=1, skipna=True)
    frame["best_right_kg"] = frame[right_cols].max(axis=1, skipna=True)
    frame["avg_left_kg"] = frame[left_cols].mean(axis=1, skipna=True)
    frame["avg_right_kg"] = frame[right_cols].mean(axis=1, skipna=True)
    stronger = frame[["best_left_kg", "best_right_kg"]].max(axis=1, skipna=True)
    difference = (frame["best_left_kg"] - frame["best_right_kg"]).abs()
    frame["asymmetry_pct"] = (difference / stronger * 100.0).where(stronger > 0)
    frame["best_overall_kg"] = stronger
    return frame

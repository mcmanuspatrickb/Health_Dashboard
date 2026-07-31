from __future__ import annotations
import os
from datetime import datetime
from typing import Any
import pandas as pd

TABLE_NAME = "renpho_measurements"

def _secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value not in (None, ""):
            return str(value).strip()
    except Exception:
        pass
    return None

def database_url() -> str | None:
    return _secret("RENPHO_DATABASE_URL") or _secret("WITHINGS_DATABASE_URL")

def _connect():
    url = database_url()
    if not url:
        raise RuntimeError("Set RENPHO_DATABASE_URL or WITHINGS_DATABASE_URL.")
    import psycopg
    return psycopg.connect(url)

def ensure_schema() -> None:
    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS renpho_measurements (
            measurement_id BIGSERIAL PRIMARY KEY,
            measured_at TIMESTAMPTZ NOT NULL UNIQUE,
            body_score DOUBLE PRECISION,
            weight_kg DOUBLE PRECISION,
            body_fat_pct DOUBLE PRECISION,
            body_fat_mass_kg DOUBLE PRECISION,
            bone_mass_kg DOUBLE PRECISION,
            protein_mass_kg DOUBLE PRECISION,
            body_water_mass_kg DOUBLE PRECISION,
            muscle_mass_kg DOUBLE PRECISION,
            skeletal_muscle_mass_kg DOUBLE PRECISION,
            fat_free_mass_kg DOUBLE PRECISION,
            bmi DOUBLE PRECISION,
            obesity_assessment_pct DOUBLE PRECISION,
            visceral_fat_index DOUBLE PRECISION,
            subcutaneous_fat_pct DOUBLE PRECISION,
            bmr_kcal_day DOUBLE PRECISION,
            smi_kg_m2 DOUBLE PRECISION,
            metabolic_age_years DOUBLE PRECISION,
            waist_hip_ratio DOUBLE PRECISION,
            left_arm_fat_kg DOUBLE PRECISION,
            right_arm_fat_kg DOUBLE PRECISION,
            trunk_fat_kg DOUBLE PRECISION,
            left_leg_fat_kg DOUBLE PRECISION,
            right_leg_fat_kg DOUBLE PRECISION,
            left_arm_muscle_kg DOUBLE PRECISION,
            right_arm_muscle_kg DOUBLE PRECISION,
            trunk_muscle_kg DOUBLE PRECISION,
            left_leg_muscle_kg DOUBLE PRECISION,
            right_leg_muscle_kg DOUBLE PRECISION,
            z20_right_arm DOUBLE PRECISION,
            z20_left_arm DOUBLE PRECISION,
            z20_trunk DOUBLE PRECISION,
            z20_right_leg DOUBLE PRECISION,
            z20_left_leg DOUBLE PRECISION,
            z100_right_arm DOUBLE PRECISION,
            z100_left_arm DOUBLE PRECISION,
            z100_trunk DOUBLE PRECISION,
            z100_right_leg DOUBLE PRECISION,
            z100_left_leg DOUBLE PRECISION,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        conn.commit()

COLUMNS = [
    "measurement_id","measured_at","body_score","weight_kg","body_fat_pct",
    "body_fat_mass_kg","bone_mass_kg","protein_mass_kg","body_water_mass_kg",
    "muscle_mass_kg","skeletal_muscle_mass_kg","fat_free_mass_kg","bmi",
    "obesity_assessment_pct","visceral_fat_index","subcutaneous_fat_pct",
    "bmr_kcal_day","smi_kg_m2","metabolic_age_years","waist_hip_ratio",
    "left_arm_fat_kg","right_arm_fat_kg","trunk_fat_kg","left_leg_fat_kg",
    "right_leg_fat_kg","left_arm_muscle_kg","right_arm_muscle_kg",
    "trunk_muscle_kg","left_leg_muscle_kg","right_leg_muscle_kg",
    "z20_right_arm","z20_left_arm","z20_trunk","z20_right_leg","z20_left_leg",
    "z100_right_arm","z100_left_arm","z100_trunk","z100_right_leg","z100_left_leg",
    "notes","created_at"
]

def load_renpho_measurements() -> pd.DataFrame:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE_NAME} ORDER BY measured_at")
            rows = cur.fetchall()
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if not frame.empty:
        frame["measured_at"] = pd.to_datetime(frame["measured_at"], utc=True, errors="coerce")
        frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, errors="coerce")
    frame.attrs["source"] = "Renpho"
    return frame

def _clean(value: Any):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(value) else value

def insert_renpho_measurement(measured_at: datetime, values: dict[str, Any]) -> None:
    ensure_schema()
    writable = [c for c in COLUMNS if c not in {"measurement_id","measured_at","created_at"}]
    payload = {}
    for c in writable:
        if c == "notes":
            v = values.get(c)
            payload[c] = str(v).strip() if v not in (None, "") else None
        else:
            payload[c] = _clean(values.get(c))
    columns = ["measured_at"] + writable
    placeholders = ", ".join(["%s"] * len(columns))
    update_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in writable)
    params = [measured_at] + [payload[c] for c in writable]
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO {TABLE_NAME} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (measured_at) DO UPDATE SET {update_sql}",
            params,
        )
        conn.commit()

def delete_renpho_measurement(measurement_id: int) -> None:
    """Delete exactly one Renpho measurement by its primary key."""
    ensure_schema()
    with _connect() as conn:
        result = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE measurement_id = %s",
            (int(measurement_id),),
        )
        conn.commit()

        if result.rowcount == 0:
            raise RuntimeError(
                f"Renpho measurement_id {measurement_id} was not found."
            )


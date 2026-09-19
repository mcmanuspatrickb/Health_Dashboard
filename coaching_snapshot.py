from __future__ import annotations

import json
import os
from typing import Any

import psycopg

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


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
    value = _secret("WITHINGS_DATABASE_URL")
    if not value:
        raise RuntimeError("Canonical coaching snapshot needs WITHINGS_DATABASE_URL.")
    return value


def load_latest_coaching_snapshot() -> dict[str, Any]:
    """Load the latest authoritative coaching interpretation.

    The weekly fitness-dashboard pipeline writes this snapshot. Streamlit uses
    it for coaching state/decision displays while keeping its own charts as
    exploratory views of the underlying measurements.
    """
    with psycopg.connect(_database_url()) as con:
        exists = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name='coaching_snapshots'
            """
        ).fetchone()[0]
        if not exists:
            return {}
        row = con.execute(
            """
            SELECT snapshot_json
            FROM coaching_snapshots
            ORDER BY analysis_date DESC, generated_at DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    value = row[0]
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if value is not None else {}

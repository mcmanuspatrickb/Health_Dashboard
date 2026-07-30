from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


TOKEN_FILE = Path("private/withings_token.json")
OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"

MEASURE_TYPES = {
    1: ("Weight", "kg"),
    4: ("Height", "m"),
    5: ("Fat-free mass", "kg"),
    6: ("Body fat ratio", "%"),
    8: ("Fat mass", "kg"),
    9: ("Diastolic blood pressure", "mmHg"),
    10: ("Systolic blood pressure", "mmHg"),
    11: ("Heart rate / pulse", "bpm"),
    76: ("Muscle mass", "kg"),
    77: ("Water mass", "kg"),
    88: ("Bone mass", "kg"),
    91: ("Pulse wave velocity", "m/s"),
    155: ("Vascular age", "years"),
    158: ("Nerve Health Score — left foot", "score"),
    159: ("Nerve Health Score — right foot", "score"),
    167: ("Nerve Health Score — feet max", "score"),
    168: ("Extracellular water", "kg"),
    169: ("Intracellular water", "kg"),
    170: ("Visceral fat index", "index"),
    173: ("Fat-free mass segmental", "segmental"),
    174: ("Fat mass segmental", "segmental"),
    175: ("Muscle mass segmental", "segmental"),
    196: ("Nerve Response Score", "score"),
    226: ("Basal metabolic rate", "kcal/day"),
    227: ("Metabolic age", "years"),
    229: ("Electrochemical skin conductance", "µS"),
}


def _secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip()

    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value not in (None, ""):
            return str(value).strip()

        section = st.secrets.get("withings")
        if section:
            simple = name.removeprefix("WITHINGS_").lower()
            for key in (name, simple, simple.upper()):
                try:
                    value = section.get(key)
                except Exception:
                    value = None
                if value not in (None, ""):
                    return str(value).strip()
    except Exception:
        pass

    return None


def _read_token() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        return {}
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8-sig"))


def _write_token(payload: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _credential(
    token: dict[str, Any],
    env_name: str,
    token_names: tuple[str, ...],
) -> str | None:
    value = _secret(env_name)
    if value:
        return value
    for name in token_names:
        value = token.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _refresh_local_token(token: dict[str, Any]) -> dict[str, Any]:
    client_id = _credential(
        token, "WITHINGS_CLIENT_ID", ("client_id", "clientId")
    )
    client_secret = _credential(
        token, "WITHINGS_CLIENT_SECRET", ("client_secret", "clientSecret")
    )
    refresh_token = _credential(
        token, "WITHINGS_REFRESH_TOKEN", ("refresh_token", "refreshToken")
    )

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Withings local mode needs client_id, client_secret and refresh_token."
        )

    response = requests.post(
        OAUTH_URL,
        timeout=30,
        data={
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )
    response.raise_for_status()
    payload = response.json()

    if int(payload.get("status", -1)) != 0:
        raise RuntimeError(
            f"Withings token refresh failed: status={payload.get('status')}"
        )

    body = payload.get("body", {}) or {}
    if not body.get("access_token"):
        raise RuntimeError("Withings token refresh returned no access_token.")

    merged = dict(token)
    merged.update(body)
    merged["client_id"] = client_id
    merged["client_secret"] = client_secret
    merged["expires_at"] = (
        int(time.time()) + int(body.get("expires_in", 10800)) - 60
    )
    _write_token(merged)
    return merged


def _local_access_token() -> str:
    token = _read_token()

    access_token = _credential(
        token, "WITHINGS_ACCESS_TOKEN", ("access_token", "accessToken")
    )
    expires_at = token.get("expires_at")

    if access_token and expires_at:
        try:
            if int(expires_at) > int(time.time()) + 120:
                return access_token
        except Exception:
            pass

    # If expiry metadata is absent, try the stored token once. If the API later
    # rejects it, the caller will refresh and retry.
    if access_token and not expires_at:
        return access_token

    token = _refresh_local_token(token)
    return str(token["access_token"])


def _post_withings(
    access_token: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    response = requests.post(
        MEASURE_URL,
        timeout=60,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
    )

    if response.status_code == 401:
        raise PermissionError("Withings access token expired.")

    response.raise_for_status()
    payload = response.json()
    if int(payload.get("status", -1)) != 0:
        raise RuntimeError(
            f"Withings API returned status={payload.get('status')}"
        )
    return payload


def _fetch_direct(days: int) -> pd.DataFrame:
    access_token = _local_access_token()
    enddate = int(time.time())
    startdate = int(
        (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).timestamp()
    )

    groups: list[dict[str, Any]] = []
    offset = None
    seen_offsets: set[int] = set()

    for _ in range(100):
        params: dict[str, Any] = {
            "action": "getmeas",
            "category": 1,
            "startdate": startdate,
            "enddate": enddate,
        }
        if offset is not None:
            params["offset"] = offset

        try:
            payload = _post_withings(access_token, params)
        except PermissionError:
            token = _refresh_local_token(_read_token())
            access_token = str(token["access_token"])
            payload = _post_withings(access_token, params)

        body = payload.get("body", {}) or {}
        page_groups = body.get("measuregrps", []) or []
        groups.extend(
            group for group in page_groups if isinstance(group, dict)
        )

        if not body.get("more"):
            break

        next_offset = body.get("offset")
        if next_offset is None:
            break
        try:
            next_offset = int(next_offset)
        except Exception:
            break
        if next_offset in seen_offsets:
            break
        seen_offsets.add(next_offset)
        offset = next_offset

    rows = []
    for group in groups:
        grpid = group.get("grpid")
        measured = pd.to_datetime(
            group.get("date"), unit="s", utc=True, errors="coerce"
        )
        modified = pd.to_datetime(
            group.get("modified"), unit="s", utc=True, errors="coerce"
        )
        deviceid = group.get("deviceid")

        for measure in group.get("measures", []) or []:
            if not isinstance(measure, dict):
                continue
            try:
                type_id = int(measure.get("type"))
            except Exception:
                continue

            raw_value = measure.get("value")
            unit_exp = measure.get("unit", 0)
            scalar = None
            if isinstance(raw_value, (int, float)) and not isinstance(
                raw_value, bool
            ):
                try:
                    scalar = float(raw_value) * (
                        10 ** int(unit_exp or 0)
                    )
                except Exception:
                    scalar = None

            metric, unit_name = MEASURE_TYPES.get(
                type_id, (f"Unknown type {type_id}", "unknown")
            )

            rows.append(
                {
                    "grpid": grpid,
                    "measured_at": measured,
                    "modified_at": modified,
                    "deviceid": deviceid,
                    "type_id": type_id,
                    "metric": metric,
                    "unit": unit_name,
                    "value": scalar,
                    "unit_exponent": unit_exp,
                    "position": measure.get("position"),
                    "raw_measure_json": json.dumps(
                        measure,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["measured_at"] = pd.to_datetime(
            frame["measured_at"], utc=True, errors="coerce"
        )
        frame["modified_at"] = pd.to_datetime(
            frame["modified_at"], utc=True, errors="coerce"
        )
        frame = frame.sort_values("measured_at").reset_index(drop=True)
    frame.attrs["source_mode"] = "local-direct"
    return frame


def _fetch_database(days: int, database_url: str) -> pd.DataFrame:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "WITHINGS_DATABASE_URL is configured but psycopg is not installed."
        ) from exc

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sql = """
        SELECT
            grpid,
            measured_at,
            modified_at,
            deviceid,
            type_id,
            metric,
            expected_unit AS unit,
            scalar_value AS value,
            unit_exponent,
            position,
            raw_measure_json
        FROM withings_measurements
        WHERE measured_at >= %s
        ORDER BY measured_at
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (cutoff,))
            rows = cur.fetchall()
            columns = [desc.name for desc in cur.description]

    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame["measured_at"] = pd.to_datetime(
            frame["measured_at"], utc=True, errors="coerce"
        )
        frame["modified_at"] = pd.to_datetime(
            frame["modified_at"], utc=True, errors="coerce"
        )
    frame.attrs["source_mode"] = "persistent-database"
    return frame


def load_withings_dashboard_measurements(
    days: int = 730,
) -> pd.DataFrame:
    """
    Cloud mode: persistent Postgres database.
    Local mode: direct Withings API + private/withings_token.json.
    """
    database_url = _secret("WITHINGS_DATABASE_URL")
    if database_url:
        return _fetch_database(days, database_url)
    return _fetch_direct(days)


def _pivot_sessions(
    measures: pd.DataFrame,
    type_map: dict[int, str],
) -> pd.DataFrame:
    if measures.empty:
        return pd.DataFrame()

    subset = measures[
        measures["type_id"].isin(type_map)
    ].copy()
    if subset.empty:
        return pd.DataFrame()

    subset["column"] = subset["type_id"].map(type_map)
    pivot = (
        subset.pivot_table(
            index=["grpid", "measured_at", "deviceid"],
            columns="column",
            values="value",
            aggfunc="last",
        )
        .reset_index()
        .sort_values("measured_at")
    )
    pivot.columns.name = None
    pivot["date"] = pd.to_datetime(
        pivot["measured_at"], utc=True, errors="coerce"
    ).dt.tz_convert("Europe/Berlin").dt.tz_localize(None)

    return pivot.reset_index(drop=True)


def build_withings_scale_sessions(
    measures: pd.DataFrame,
) -> pd.DataFrame:
    type_map = {
        1: "weight_kg",
        5: "fat_free_mass_kg",
        6: "body_fat_pct",
        8: "fat_mass_kg",
        76: "muscle_mass_kg",
        77: "water_mass_kg",
        88: "bone_mass_kg",
        91: "pwv_m_s",
        155: "vascular_age_years",
        167: "nerve_health_score",
        170: "visceral_fat_index",
        226: "bmr_kcal_day",
        227: "metabolic_age_years",
        168: "extracellular_water_kg",
        169: "intracellular_water_kg",
    }
    frame = _pivot_sessions(measures, type_map)
    if frame.empty:
        return frame

    if {"muscle_mass_kg", "weight_kg"}.issubset(frame.columns):
        frame["muscle_mass_pct"] = (
            frame["muscle_mass_kg"] / frame["weight_kg"] * 100
        )
    else:
        frame["muscle_mass_pct"] = pd.NA

    if {"water_mass_kg", "weight_kg"}.issubset(frame.columns):
        frame["water_pct"] = (
            frame["water_mass_kg"] / frame["weight_kg"] * 100
        )
    else:
        frame["water_pct"] = pd.NA

    return frame


def build_withings_bp_sessions(
    measures: pd.DataFrame,
) -> pd.DataFrame:
    frame = _pivot_sessions(
        measures,
        {
            9: "diastolic_mm_hg",
            10: "systolic_mm_hg",
            11: "pulse_bpm",
        },
    )
    if frame.empty:
        return frame

    required = {"systolic_mm_hg", "diastolic_mm_hg"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()

    frame = frame.dropna(
        subset=["systolic_mm_hg", "diastolic_mm_hg"]
    ).copy()
    return frame.reset_index(drop=True)


def latest_non_null(
    frame: pd.DataFrame,
    column: str,
):
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])

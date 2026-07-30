from __future__ import annotations

import argparse
import json
import os
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import psycopg
except ImportError as exc:
    raise SystemExit(
        "Install sync-service requirements first: "
        "pip install -r withings_sync_service_requirements.txt"
    ) from exc


TOKEN_FILE = Path("private/withings_token.json")
SECRETS_FILE = Path(".streamlit/secrets.toml")

OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
NOTIFY_URL = "https://wbsapi.withings.net"

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


def _read_secrets() -> dict[str, Any]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        return tomllib.loads(
            SECRETS_FILE.read_text(encoding="utf-8-sig")
        )
    except Exception:
        return {}


def _secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip()

    payload = _read_secrets()
    value = payload.get(name)
    if value not in (None, ""):
        return str(value).strip()

    section = payload.get("withings")
    if isinstance(section, dict):
        simple = name.removeprefix("WITHINGS_").lower()
        for key in (name, simple, simple.upper()):
            value = section.get(key)
            if value not in (None, ""):
                return str(value).strip()

    return None


def _db_url() -> str:
    value = _secret("WITHINGS_DATABASE_URL")
    if not value:
        raise RuntimeError("WITHINGS_DATABASE_URL is required.")
    return value


def init_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withings_oauth_state (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            userid TEXT,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at BIGINT NOT NULL,
            client_id TEXT NOT NULL,
            client_secret TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withings_measurements (
            grpid BIGINT NOT NULL,
            type_id INTEGER NOT NULL,
            position_key INTEGER NOT NULL DEFAULT -1,
            measured_at TIMESTAMPTZ NOT NULL,
            modified_at TIMESTAMPTZ,
            deviceid TEXT,
            metric TEXT NOT NULL,
            expected_unit TEXT,
            scalar_value DOUBLE PRECISION,
            raw_value_json TEXT,
            unit_exponent INTEGER,
            position INTEGER,
            raw_measure_json TEXT NOT NULL,
            PRIMARY KEY (grpid, type_id, position_key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_withings_measurements_measured
        ON withings_measurements (measured_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_withings_measurements_modified
        ON withings_measurements (modified_at)
        """
    )


def _load_local_token() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        return {}
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8-sig"))


def bootstrap() -> None:
    token = _load_local_token()

    client_id = (
        _secret("WITHINGS_CLIENT_ID")
        or token.get("client_id")
        or token.get("clientId")
    )
    client_secret = (
        _secret("WITHINGS_CLIENT_SECRET")
        or token.get("client_secret")
        or token.get("clientSecret")
    )
    access_token = (
        _secret("WITHINGS_ACCESS_TOKEN")
        or token.get("access_token")
        or token.get("accessToken")
    )
    refresh_token = (
        _secret("WITHINGS_REFRESH_TOKEN")
        or token.get("refresh_token")
        or token.get("refreshToken")
    )
    userid = token.get("userid") or token.get("user_id")

    if not all(
        [client_id, client_secret, access_token, refresh_token]
    ):
        raise RuntimeError(
            "Bootstrap needs current Withings client/access/refresh credentials."
        )

    expires_at = token.get("expires_at")
    if not expires_at:
        expires_at = int(time.time()) + 300

    with psycopg.connect(_db_url()) as conn:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO withings_oauth_state (
                singleton_id, userid, access_token, refresh_token,
                expires_at, client_id, client_secret, updated_at
            )
            VALUES (1, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (singleton_id) DO UPDATE SET
                userid = EXCLUDED.userid,
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                client_id = EXCLUDED.client_id,
                client_secret = EXCLUDED.client_secret,
                updated_at = NOW()
            """,
            (
                str(userid) if userid is not None else None,
                str(access_token),
                str(refresh_token),
                int(expires_at),
                str(client_id),
                str(client_secret),
            ),
        )
        conn.commit()

    print("Withings OAuth state copied into persistent database.")


def _oauth_state(conn) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT userid, access_token, refresh_token, expires_at,
               client_id, client_secret
        FROM withings_oauth_state
        WHERE singleton_id = 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError(
            "No Withings OAuth state in database. Run bootstrap first."
        )

    return {
        "userid": row[0],
        "access_token": row[1],
        "refresh_token": row[2],
        "expires_at": int(row[3]),
        "client_id": row[4],
        "client_secret": row[5],
    }


def _refresh_if_needed(conn) -> str:
    state = _oauth_state(conn)
    if state["expires_at"] > int(time.time()) + 180:
        return state["access_token"]

    response = requests.post(
        OAUTH_URL,
        timeout=30,
        data={
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": state["client_id"],
            "client_secret": state["client_secret"],
            "refresh_token": state["refresh_token"],
        },
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("status", -1)) != 0:
        raise RuntimeError(
            f"Withings refresh failed: status={payload.get('status')}"
        )

    body = payload.get("body", {}) or {}
    new_access = body["access_token"]
    new_refresh = body["refresh_token"]
    expires_at = (
        int(time.time()) + int(body.get("expires_in", 10800)) - 60
    )

    conn.execute(
        """
        UPDATE withings_oauth_state
        SET userid = COALESCE(%s, userid),
            access_token = %s,
            refresh_token = %s,
            expires_at = %s,
            updated_at = NOW()
        WHERE singleton_id = 1
        """,
        (
            str(body.get("userid")) if body.get("userid") else None,
            new_access,
            new_refresh,
            expires_at,
        ),
    )
    conn.commit()
    return new_access


def _withings_post(access_token: str, data: dict[str, Any]):
    response = requests.post(
        MEASURE_URL,
        timeout=60,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data=data,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("status", -1)) != 0:
        raise RuntimeError(
            f"Withings getmeas failed: status={payload.get('status')}"
        )
    return payload


def _scalar(raw_value, unit_exp):
    if isinstance(raw_value, bool):
        return float(raw_value)
    if not isinstance(raw_value, (int, float)):
        return None
    try:
        return float(raw_value) * (10 ** int(unit_exp or 0))
    except Exception:
        return None


def _fetch_groups(access_token: str, lastupdate: int | None):
    groups = []
    offset = None
    seen = set()

    for _ in range(100):
        params: dict[str, Any] = {
            "action": "getmeas",
            "category": 1,
        }
        if lastupdate is not None:
            params["lastupdate"] = int(lastupdate)
        else:
            params["startdate"] = 1262304000
            params["enddate"] = int(time.time())
        if offset is not None:
            params["offset"] = offset

        payload = _withings_post(access_token, params)
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
        next_offset = int(next_offset)
        if next_offset in seen:
            break
        seen.add(next_offset)
        offset = next_offset

    return groups


def sync_once() -> int:
    with psycopg.connect(_db_url()) as conn:
        init_schema(conn)
        access_token = _refresh_if_needed(conn)

        last_modified = conn.execute(
            "SELECT MAX(modified_at) FROM withings_measurements"
        ).fetchone()[0]
        lastupdate = (
            int(last_modified.timestamp()) if last_modified else None
        )

        groups = _fetch_groups(access_token, lastupdate)
        inserted = 0

        for group in groups:
            grpid = group.get("grpid")
            if grpid is None:
                continue

            measured_at = datetime.fromtimestamp(
                int(group.get("date")),
                tz=timezone.utc,
            )
            modified_raw = group.get("modified") or group.get("date")
            modified_at = datetime.fromtimestamp(
                int(modified_raw),
                tz=timezone.utc,
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
                position = measure.get("position")
                try:
                    position_key = int(position)
                except Exception:
                    position_key = -1

                metric, expected_unit = MEASURE_TYPES.get(
                    type_id,
                    (f"Unknown type {type_id}", "unknown"),
                )

                conn.execute(
                    """
                    INSERT INTO withings_measurements (
                        grpid, type_id, position_key, measured_at,
                        modified_at, deviceid, metric, expected_unit,
                        scalar_value, raw_value_json, unit_exponent,
                        position, raw_measure_json
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (grpid, type_id, position_key)
                    DO UPDATE SET
                        measured_at = EXCLUDED.measured_at,
                        modified_at = EXCLUDED.modified_at,
                        deviceid = EXCLUDED.deviceid,
                        metric = EXCLUDED.metric,
                        expected_unit = EXCLUDED.expected_unit,
                        scalar_value = EXCLUDED.scalar_value,
                        raw_value_json = EXCLUDED.raw_value_json,
                        unit_exponent = EXCLUDED.unit_exponent,
                        position = EXCLUDED.position,
                        raw_measure_json = EXCLUDED.raw_measure_json
                    """,
                    (
                        int(grpid),
                        type_id,
                        position_key,
                        measured_at,
                        modified_at,
                        deviceid,
                        metric,
                        expected_unit,
                        _scalar(raw_value, unit_exp),
                        json.dumps(raw_value, ensure_ascii=False),
                        int(unit_exp or 0),
                        int(position) if position is not None else None,
                        json.dumps(
                            measure,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
                inserted += 1

        conn.commit()

    print(f"Withings sync complete: processed {inserted} measurement values.")
    return inserted


def subscribe(callback_url: str) -> None:
    with psycopg.connect(_db_url()) as conn:
        init_schema(conn)
        access_token = _refresh_if_needed(conn)

    for appli in (1, 4):
        response = requests.post(
            NOTIFY_URL,
            timeout=30,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "action": "subscribe",
                "callbackurl": callback_url,
                "appli": appli,
                "comment": "Training dashboard Withings sync",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("status", -1)) != 0:
            raise RuntimeError(
                f"Subscription failed for appli={appli}: {payload}"
            )
        print(f"Subscribed appli={appli} to {callback_url}")


def build_app():
    try:
        from fastapi import FastAPI, HTTPException, Request
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is required for webhook mode."
        ) from exc

    app = FastAPI(title="Withings Sync Service")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.head("/withings")
    async def withings_head():
        return {}

    @app.post("/withings")
    async def withings_webhook(request: Request, token: str | None = None):
        expected = _secret("WITHINGS_WEBHOOK_SECRET")
        if expected and token != expected:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

        # Parse the form so malformed callbacks fail early.
        await request.form()
        sync_once()
        return {"status": "ok"}

    return app


app = None
try:
    app = build_app()
except Exception:
    # CLI use does not require FastAPI.
    app = None


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap")
    sub.add_parser("sync")
    subscribe_parser = sub.add_parser("subscribe")
    subscribe_parser.add_argument("callback_url")

    args = parser.parse_args()

    if args.command == "bootstrap":
        bootstrap()
    elif args.command == "sync":
        sync_once()
    elif args.command == "subscribe":
        subscribe(args.callback_url)


if __name__ == "__main__":
    main()

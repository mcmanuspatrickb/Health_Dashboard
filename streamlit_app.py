import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google_health_client import GoogleHealthClient
from google_health_data import (
    load_body,
    load_nutrition,
    load_recovery,
    load_sleep,
    load_steps,
)
from google_health_training import analyze_workout_heart_rate
from hevy_training_load import (
    build_exercise_summary,
    build_rpe_set_table,
    build_session_summary,
    prepare_training_frame,
    select_session_rows,
)
from hevy_progress import (
    build_exercise_history,
    build_note_flags,
    build_previous_exercise_comparison,
    select_exercise_history,
)

st.set_page_config(
    page_title="Hevy Workout Review",
    page_icon="🏋️",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = BASE_DIR / "data" / "workouts.csv"
GOALS_PATH = BASE_DIR / "data" / "fitness_goals.json"
GOAL_ALIASES_PATH = BASE_DIR / "data" / "goal_exercise_aliases.csv"
HEVY_BASE_URL = "https://api.hevyapp.com/v1/workouts"


def get_secret(name: str, default=None):
    """Safely read Streamlit secrets both locally and in Streamlit Cloud."""
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


@st.cache_data(ttl=14400, show_spinner=False)
def fetch_hevy_workouts(api_key: str, page_size: int = 10, max_pages: int = 10):
    headers = {
        "accept": "application/json",
        "api-key": api_key
    }

    all_workouts = []

    for page in range(1, max_pages + 1):
        params = {"page": page, "pageSize": page_size}

        response = requests.get(
            HEVY_BASE_URL,
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()

        workouts = (
            data.get("workouts")
            or data.get("data")
            or data.get("items")
            or []
        )

        if not workouts:
            break

        all_workouts.extend(workouts)

        page_count = data.get("page_count") or data.get("pageCount") or data.get("totalPages")
        if page_count and page >= int(page_count):
            break

        has_next = data.get("has_next") or data.get("hasNext")
        if has_next is False:
            break

    return all_workouts


def first_existing(obj: dict, keys: list, default=None):
    for key in keys:
        if isinstance(obj, dict) and key in obj and obj[key] not in [None, ""]:
            return obj[key]
    return default


def flatten_hevy_workouts(workouts: list) -> pd.DataFrame:
    """Flatten complete Hevy workout details while preserving trainer fields."""
    rows = []

    for workout in workouts:
        workout_id = first_existing(workout, ["id", "workout_id"])
        routine_id = first_existing(workout, ["routine_id", "routineId"])
        title = first_existing(workout, ["title", "name"], "Workout")
        description = first_existing(workout, ["description", "notes", "note"], "")
        start_time = first_existing(
            workout,
            ["start_time", "startTime", "started_at", "created_at"],
        )
        end_time = first_existing(
            workout,
            ["end_time", "endTime", "ended_at", "updated_at"],
        )
        created_at = first_existing(workout, ["created_at", "createdAt"])
        updated_at = first_existing(workout, ["updated_at", "updatedAt"])

        exercises = (
            workout.get("exercises")
            or workout.get("exercise_templates")
            or workout.get("workout_exercises")
            or []
        )

        if not exercises:
            rows.append({
                "workout_id": workout_id,
                "routine_id": routine_id,
                "title": title,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "created_at": created_at,
                "updated_at": updated_at,
                "exercise_index": None,
                "exercise_title": None,
                "exercise_notes": None,
                "exercise_template_id": None,
                "superset_id": None,
                "set_index": None,
                "set_type": None,
                "weight_kg": None,
                "reps": None,
                "distance_meters": None,
                "distance_km": None,
                "duration_seconds": None,
                "rpe": None,
                "custom_metric": None,
            })
            continue

        for exercise_position, exercise in enumerate(exercises):
            exercise_index = first_existing(
                exercise, ["index", "exercise_index"], exercise_position
            )
            exercise_title = first_existing(
                exercise,
                ["title", "name", "exercise_title", "exerciseName"],
                "Exercise",
            )
            exercise_notes = first_existing(
                exercise,
                ["notes", "note", "exercise_notes"],
                "",
            )
            exercise_template_id = first_existing(
                exercise,
                ["exercise_template_id", "exerciseTemplateId", "template_id"],
            )
            superset_id = first_existing(exercise, ["superset_id", "supersetId"])

            sets = (
                exercise.get("sets")
                or exercise.get("workout_sets")
                or exercise.get("exercise_sets")
                or []
            )

            if not sets:
                rows.append({
                    "workout_id": workout_id,
                    "routine_id": routine_id,
                    "title": title,
                    "description": description,
                    "start_time": start_time,
                    "end_time": end_time,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "exercise_index": exercise_index,
                    "exercise_title": exercise_title,
                    "exercise_notes": exercise_notes,
                    "exercise_template_id": exercise_template_id,
                    "superset_id": superset_id,
                    "set_index": None,
                    "set_type": None,
                    "weight_kg": None,
                    "reps": None,
                    "distance_meters": None,
                    "distance_km": None,
                    "duration_seconds": None,
                    "rpe": None,
                    "custom_metric": None,
                })
                continue

            for set_position, set_item in enumerate(sets):
                distance_meters = first_existing(
                    set_item,
                    ["distance_meters", "distanceMeters"],
                )
                distance_km = first_existing(
                    set_item,
                    ["distance_km", "distanceKm"],
                )
                if distance_km is None and distance_meters is not None:
                    try:
                        distance_km = float(distance_meters) / 1000
                    except (TypeError, ValueError):
                        distance_km = None

                rows.append({
                    "workout_id": workout_id,
                    "routine_id": routine_id,
                    "title": title,
                    "description": description,
                    "start_time": start_time,
                    "end_time": end_time,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "exercise_index": exercise_index,
                    "exercise_title": exercise_title,
                    "exercise_notes": exercise_notes,
                    "exercise_template_id": exercise_template_id,
                    "superset_id": superset_id,
                    "set_index": first_existing(
                        set_item, ["index", "set_index"], set_position
                    ),
                    "set_type": first_existing(
                        set_item, ["type", "set_type"], "normal"
                    ),
                    "weight_kg": first_existing(
                        set_item, ["weight_kg", "weightKg", "weight"]
                    ),
                    "reps": first_existing(set_item, ["reps", "repetitions"]),
                    "distance_meters": distance_meters,
                    "distance_km": distance_km,
                    "duration_seconds": first_existing(
                        set_item,
                        ["duration_seconds", "durationSeconds", "duration"],
                    ),
                    "rpe": first_existing(set_item, ["rpe"]),
                    "custom_metric": first_existing(
                        set_item, ["custom_metric", "customMetric"]
                    ),
                })

    return pd.DataFrame(rows)

def normalize_hevy_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    rename_candidates = {
        "exercise": "exercise_title",
        "Exercise": "exercise_title",
        "workout_title": "title",
        "workout_name": "title",
        "notes": "exercise_notes",
        "weight": "weight_kg"
    }
    for old, new in rename_candidates.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    for col in ["start_time", "end_time", "created_at", "updated_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)

    for col in [
        "exercise_index", "set_index", "reps", "weight_kg", "rpe",
        "duration_seconds", "distance_meters", "distance_km"
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = pd.NA

    for col in [
        "workout_id", "routine_id", "title", "description",
        "exercise_title", "exercise_notes", "exercise_template_id",
        "superset_id", "set_type", "custom_metric"
    ]:
        if col not in df.columns:
            df[col] = ""

    if "end_time" not in df.columns and "start_time" in df.columns:
        df["end_time"] = df["start_time"]

    if "start_time" not in df.columns and "end_time" in df.columns:
        df["start_time"] = df["end_time"]

    df["workout_date"] = pd.to_datetime(df["end_time"], errors="coerce").dt.date
    df["set_volume_kg"] = df["weight_kg"].fillna(0) * df["reps"].fillna(0)

    df["duration_minutes"] = (
        pd.to_datetime(df["end_time"], errors="coerce")
        - pd.to_datetime(df["start_time"], errors="coerce")
    ).dt.total_seconds() / 60

    return df


@st.cache_data
def load_from_csv(uploaded_file=None):
    if uploaded_file is not None:
        return pd.read_csv(uploaded_file)
    if DEFAULT_CSV.exists():
        return pd.read_csv(DEFAULT_CSV)
    return pd.DataFrame()


def load_data(page_size: int = 10, max_pages: int = 30):
    """Load Hevy directly from the API.

    The dashboard no longer exposes CSV/upload source controls.
    """
    api_key = get_secret("HEVY_API_KEY")
    if not api_key:
        st.error(
            "No HEVY_API_KEY found in Streamlit secrets. "
            "Add the key in Streamlit Community Cloud → App settings → Secrets."
        )
        return pd.DataFrame(), "Hevy API — missing key"

    try:
        workouts = fetch_hevy_workouts(
            api_key,
            page_size=page_size,
            max_pages=max_pages,
        )
        raw = flatten_hevy_workouts(workouts)
        return normalize_hevy_table(raw), "Hevy API"
    except Exception as exc:
        st.error(f"Hevy API failed: {exc}")
        return pd.DataFrame(), "Hevy API — error"


def format_set_table(df):
    cols = ["end_time", "exercise_title", "set_index", "set_type", "reps", "weight_kg", "rpe", "exercise_notes"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy().sort_values(["end_time", "exercise_title", "set_index"], ascending=[False, True, True])

    if "end_time" in out.columns:
        out["end_time"] = pd.to_datetime(out["end_time"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")

    if "set_index" in out.columns:
        out["set_index"] = pd.to_numeric(out["set_index"], errors="coerce") + 1
        out = out.rename(columns={"set_index": "set"})

    out = out.rename(columns={
        "end_time": "workout",
        "exercise_title": "exercise",
        "weight_kg": "weight kg",
        "exercise_notes": "notes"
    })

    return out


def get_selected_exercise_from_chart(event):
    try:
        points = event.get("selection", {}).get("points", [])
        if points:
            return points[0].get("x")
    except Exception:
        return None
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_health_steps(days: int = 14) -> pd.DataFrame:
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    return load_steps(client, start_date, end_date)


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_health_recovery(days: int = 30) -> pd.DataFrame:
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    return load_recovery(client, today - timedelta(days=days), today)


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_health_body(days: int = 30) -> pd.DataFrame:
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    return load_body(client, today - timedelta(days=days), today)


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_health_sleep(days: int = 30) -> pd.DataFrame:
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    return load_sleep(client, today - timedelta(days=days), today)


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_health_nutrition(days: int = 30) -> pd.DataFrame:
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    end_date = today - timedelta(days=1)
    return load_nutrition(client, today - timedelta(days=days), end_date)


@st.cache_data(ttl=14400, show_spinner=False)
def load_workout_heart_rate_analysis(
    start_time_iso: str,
    end_time_iso: str,
) -> dict:
    client = GoogleHealthClient()
    return analyze_workout_heart_rate(
        client,
        pd.Timestamp(start_time_iso),
        pd.Timestamp(end_time_iso),
    )


def build_hevy_sessions(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "workout_id",
        "title",
        "start_time",
        "end_time",
        "workout_date",
        "duration_minutes",
    ]
    available = [column for column in columns if column in frame.columns]
    sessions = frame[available].copy()
    required = {"start_time", "end_time"}
    if not required.issubset(sessions.columns):
        return pd.DataFrame(columns=columns)

    sessions["start_time"] = pd.to_datetime(
        sessions["start_time"], errors="coerce"
    )
    sessions["end_time"] = pd.to_datetime(
        sessions["end_time"], errors="coerce"
    )
    sessions = sessions.dropna(subset=["start_time", "end_time"])

    dedupe_columns = [
        column
        for column in ["workout_id", "title", "start_time", "end_time"]
        if column in sessions.columns
    ]
    sessions = sessions.drop_duplicates(subset=dedupe_columns)
    if "title" not in sessions.columns:
        sessions["title"] = "Workout"
    if "workout_id" not in sessions.columns:
        sessions["workout_id"] = pd.NA
    if "workout_date" not in sessions.columns:
        sessions["workout_date"] = sessions["start_time"].dt.date
    if "duration_minutes" not in sessions.columns:
        sessions["duration_minutes"] = (
            sessions["end_time"] - sessions["start_time"]
        ).dt.total_seconds() / 60

    sessions = sessions.sort_values("start_time", ascending=False).reset_index(
        drop=True
    )
    sessions["session_label"] = sessions.apply(
        lambda row: (
            f"{row['start_time'].strftime('%d %b %Y %H:%M')} — "
            f"{row['title']} ({row['duration_minutes']:.0f} min)"
        ),
        axis=1,
    )
    return sessions


def metric_delta(current, earlier, suffix: str = "") -> str | None:
    if pd.isna(current) or pd.isna(earlier):
        return None
    change = float(current) - float(earlier)
    return f"{change:+.1f}{suffix}"


from fitness_goals import (
    build_exercise_performance_history,
    build_goal_progress,
    load_alias_rules,
    load_body_composition_proxy,
    load_goals,
)



def _duration_seconds(value) -> float:
    if value in (None, ""):
        return 0.0
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _local_timestamp(value):
    if value in (None, ""):
        return None
    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Europe/Berlin")
    return timestamp.tz_convert("Europe/Berlin")


@st.cache_data(ttl=21600, show_spinner=False)
def load_google_health_endurance_sessions(days: int = 730) -> pd.DataFrame:
    """Load run, swim and bike sessions for endurance-goal comparison."""
    client = GoogleHealthClient()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    start_date = today - timedelta(days=days)
    filter_expression = (
        f'exercise.interval.civil_start_time >= "{start_date.isoformat()}" '
        f'AND exercise.interval.civil_start_time < "{today.isoformat()}"'
    )

    points = []
    page_token = None
    while True:
        response = client.list_data_points(
            "exercise",
            filter_expression=filter_expression,
            page_size=1000,
            page_token=page_token,
        )
        points.extend(response.get("dataPoints", []) or [])
        page_token = response.get("nextPageToken") or None
        if not page_token:
            break

    rows = []
    for point in points:
        exercise = point.get("exercise", {}) or {}
        exercise_type = str(exercise.get("exerciseType", "")).upper()
        display_name = str(exercise.get("displayName", ""))
        search_text = f"{exercise_type} {display_name}".lower()

        if any(token in search_text for token in ("run", "jog", "treadmill")):
            goal_activity = "run"
        elif any(token in search_text for token in ("swim", "pool", "open water")):
            goal_activity = "swim"
        elif any(token in search_text for token in ("bike", "biking", "cycling", "cycle")):
            goal_activity = "bike"
        else:
            continue

        interval = exercise.get("interval", {}) or {}
        start_time = _local_timestamp(interval.get("startTime"))
        end_time = _local_timestamp(interval.get("endTime"))
        if start_time is None or end_time is None:
            continue

        metrics = exercise.get("metricsSummary", {}) or {}
        distance_mm = pd.to_numeric(
            metrics.get("distanceMillimeters"),
            errors="coerce",
        )
        duration_seconds = _duration_seconds(exercise.get("activeDuration"))
        if duration_seconds <= 0:
            duration_seconds = max(
                0.0,
                (end_time - start_time).total_seconds(),
            )

        source = point.get("dataSource", {}) or {}
        application = source.get("application", {}) or {}
        platform = str(source.get("platform", ""))
        package_name = str(application.get("packageName", ""))

        rows.append(
            {
                "date": start_time.date(),
                "start_time": start_time,
                "end_time": end_time,
                "goal_activity": goal_activity,
                "exercise_type": exercise_type,
                "display_name": display_name or exercise_type.title(),
                "distance_km": (
                    float(distance_mm) / 1_000_000
                    if pd.notna(distance_mm)
                    else 0.0
                ),
                "duration_hours": duration_seconds / 3600,
                "average_hr": pd.to_numeric(
                    metrics.get("averageHeartRateBeatsPerMinute"),
                    errors="coerce",
                ),
                "calories_kcal": pd.to_numeric(
                    metrics.get("caloriesKcal"),
                    errors="coerce",
                ),
                "source_platform": platform,
                "source_package": package_name,
                "source_priority": (
                    3 if platform == "FITBIT" else
                    2 if platform == "HEALTH_CONNECT" else 1
                ),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date", "start_time", "end_time", "goal_activity",
                "exercise_type", "display_name", "distance_km",
                "duration_hours", "average_hr", "calories_kcal",
                "source_platform", "source_package",
            ]
        )

    frame = pd.DataFrame(rows)
    # Collapse obvious source mirrors: same activity/date with similar distance
    # and duration. Prefer Fitbit, then Health Connect, then other sources.
    frame["distance_bucket"] = frame["distance_km"].round(1)
    frame["duration_bucket"] = (frame["duration_hours"] * 12).round() / 12
    frame = (
        frame.sort_values(
            ["source_priority", "start_time"],
            ascending=[False, False],
        )
        .drop_duplicates(
            subset=[
                "goal_activity", "date", "distance_bucket", "duration_bucket"
            ],
            keep="first",
        )
        .drop(columns=["distance_bucket", "duration_bucket", "source_priority"])
        .sort_values("start_time", ascending=False)
        .reset_index(drop=True)
    )
    return frame


def safe_frame(label: str, loader, errors: list[dict]) -> pd.DataFrame:
    try:
        frame = loader()
        errors.append(
            {
                "source": label,
                "status": "OK",
                "records": len(frame),
                "details": "",
            }
        )
        return frame
    except Exception as exc:
        errors.append(
            {
                "source": label,
                "status": "ERROR",
                "records": 0,
                "details": str(exc),
            }
        )
        return pd.DataFrame()


def latest_value(frame: pd.DataFrame, column: str):
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def date_only(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def rolling_baseline(frame, column: str, end_date, days: int = 28):
    if frame.empty or column not in frame.columns:
        return None
    local = frame.copy()
    local["date_only"] = pd.to_datetime(local["date"], errors="coerce").dt.date
    start_date = end_date - timedelta(days=days)
    values = pd.to_numeric(
        local.loc[
            (local["date_only"] >= start_date)
            & (local["date_only"] < end_date),
            column,
        ],
        errors="coerce",
    ).dropna()
    return float(values.mean()) if not values.empty else None


def recovery_context_row(
    session,
    sleep: pd.DataFrame,
    recovery: pd.DataFrame,
    steps: pd.DataFrame,
    nutrition: pd.DataFrame,
) -> dict:
    workout_day = date_only(session.get("start_time"))
    if workout_day is None:
        return {}

    def day_row(frame, day):
        if frame.empty or "date" not in frame.columns:
            return None
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.date
        rows = frame.loc[dates.eq(day)]
        return rows.iloc[-1] if not rows.empty else None

    sleep_row = day_row(sleep, workout_day)
    recovery_row = day_row(recovery, workout_day)
    prior_steps = day_row(steps, workout_day - timedelta(days=1))
    prior_food = day_row(nutrition, workout_day - timedelta(days=1))
    next_recovery = day_row(recovery, workout_day + timedelta(days=1))

    rhr_baseline = rolling_baseline(recovery, "resting_hr", workout_day)
    hrv_baseline = rolling_baseline(recovery, "hrv_ms", workout_day)
    sleep_baseline = rolling_baseline(sleep, "sleep_hours", workout_day)

    return {
        "Sleep before workout": (
            sleep_row.get("sleep_hours") if sleep_row is not None else pd.NA
        ),
        "28d sleep baseline": sleep_baseline,
        "Resting HR": (
            recovery_row.get("resting_hr") if recovery_row is not None else pd.NA
        ),
        "28d resting-HR baseline": rhr_baseline,
        "HRV": (
            recovery_row.get("hrv_ms") if recovery_row is not None else pd.NA
        ),
        "28d HRV baseline": hrv_baseline,
        "Previous-day steps": (
            prior_steps.get("steps") if prior_steps is not None else pd.NA
        ),
        "Previous-day calories": (
            prior_food.get("calories_kcal") if prior_food is not None else pd.NA
        ),
        "Previous-day protein": (
            prior_food.get("protein_g") if prior_food is not None else pd.NA
        ),
        "Next-day resting HR": (
            next_recovery.get("resting_hr") if next_recovery is not None else pd.NA
        ),
        "Next-day HRV": (
            next_recovery.get("hrv_ms") if next_recovery is not None else pd.NA
        ),
    }


def progression_label(row: pd.Series) -> str:
    max_delta = pd.to_numeric(row.get("Δ max kg"), errors="coerce")
    volume_delta = pd.to_numeric(row.get("Δ volume %"), errors="coerce")
    current_rpe = pd.to_numeric(row.get("avg set RPE"), errors="coerce")
    previous_rpe = pd.to_numeric(row.get("previous avg RPE"), errors="coerce")
    if pd.isna(max_delta) and pd.isna(volume_delta):
        return "Incomparable"
    rpe_ok = (
        pd.isna(current_rpe)
        or pd.isna(previous_rpe)
        or current_rpe <= previous_rpe + 0.5
    )
    if rpe_ok and (
        (pd.notna(max_delta) and max_delta >= 2.5)
        or (pd.notna(volume_delta) and volume_delta >= 5)
    ):
        return "Progressed"
    if (
        (pd.isna(max_delta) or abs(max_delta) < 2.5)
        and (pd.isna(volume_delta) or abs(volume_delta) < 10)
    ):
        return "Maintained"
    return "Changed / review"


def prepare_body_calculations(
    body: pd.DataFrame,
    proxy_config: dict,
) -> pd.DataFrame:
    if body.empty:
        return body.copy()

    bone_mass = float(proxy_config.get("bone_mass_baseline_kg", 3.87))
    output = body.copy().sort_values("date")
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    output["weight_kg"] = pd.to_numeric(
        output.get("weight_kg"), errors="coerce"
    )
    output["body_fat_pct"] = pd.to_numeric(
        output.get("body_fat_pct"), errors="coerce"
    )
    paired = output.dropna(
        subset=["date", "weight_kg", "body_fat_pct"]
    ).copy()
    paired["calculated_fat_mass_kg"] = (
        paired["weight_kg"] * paired["body_fat_pct"] / 100
    )
    paired["calculated_lean_mass_kg"] = (
        paired["weight_kg"] - paired["calculated_fat_mass_kg"]
    )
    paired["estimated_muscle_mass_kg"] = (
        paired["calculated_lean_mass_kg"] - bone_mass
    )
    paired["estimated_muscle_mass_pct"] = (
        paired["estimated_muscle_mass_kg"] / paired["weight_kg"] * 100
    )
    rolling = (
        paired.set_index("date")[
            [
                "weight_kg",
                "body_fat_pct",
                "calculated_fat_mass_kg",
                "estimated_muscle_mass_kg",
                "estimated_muscle_mass_pct",
            ]
        ]
        .rolling("7D", min_periods=1)
        .median()
        .add_suffix("_7d_median")
        .reset_index()
    )
    return paired.merge(rolling, on="date", how="left")


def value_28_days_earlier(
    frame: pd.DataFrame,
    column: str,
) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    data = frame[["date", column]].dropna().sort_values("date")
    if data.empty:
        return None
    cutoff = data["date"].iloc[-1] - pd.Timedelta(days=28)
    earlier = data[data["date"] <= cutoff]
    if earlier.empty:
        return None
    return float(earlier.iloc[-1][column])


def render_goal_table(goal_frame: pd.DataFrame, category: str | None = None):
    display = goal_frame.copy()
    if category is not None:
        display = display[display["category"] == category]
    if display.empty:
        st.info("No goals are available in this category.")
        return
    columns = [
        "category", "goal", "current_display", "target_display", "status",
        "source_detail",
    ]
    columns = [column for column in columns if column in display.columns]
    st.dataframe(
        display[columns].rename(
            columns={
                "category": "Category",
                "goal": "Goal",
                "current_display": "Current best",
                "target_display": "Target",
                "status": "Status",
                "source_detail": "Method / notes",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def source_quality_row(label, frame, date_column="date", expected_days=None):
    latest = "—"
    populated = 0
    missing = pd.NA
    if not frame.empty:
        populated = len(frame)
        if date_column in frame.columns:
            dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
            if not dates.empty:
                latest = dates.max().strftime("%d %b %Y")
                if expected_days is not None:
                    cutoff = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(
                        days=expected_days
                    )
                    recent_days = dates.dt.date[dates.dt.date >= cutoff].nunique()
                    missing = max(0, expected_days - recent_days)
    return {
        "Source": label,
        "Records": populated,
        "Latest": latest,
        "Missing recent days": missing,
    }


st.title("🏋️ Training, Recovery & Goal Dashboard")
st.caption(
    "Dashboard powered by Hevy, Fitbit/Google Health and Cronometer. "
    "Direct Withings has been removed; body composition uses the Google Health mirror."
)

local_google_token = (
    BASE_DIR / "private" / "google_health_token.json"
).exists()
hevy_ready = bool(get_secret("HEVY_API_KEY"))
google_secret_names = [
    "GOOGLE_HEALTH_CLIENT_ID",
    "GOOGLE_HEALTH_CLIENT_SECRET",
    "GOOGLE_HEALTH_REFRESH_TOKEN",
]
missing_google_secrets = [
    name for name in google_secret_names if not get_secret(name)
]
google_ready = local_google_token or not missing_google_secrets

if not hevy_ready or not google_ready:
    missing = []
    if not hevy_ready:
        missing.append("HEVY_API_KEY")
    if not google_ready:
        missing.extend(missing_google_secrets)
    st.warning(
        "Cloud setup is incomplete. Missing secret name(s): "
        + ", ".join(missing)
        + ". Add them in Streamlit Community Cloud → App settings → Secrets."
    )

with st.sidebar:
    st.header("Dashboard controls")
    page_size = st.number_input(
        "API page size",
        min_value=1,
        max_value=10,
        value=10,
        step=1,
        help="Hevy's workouts endpoint is used in pages of up to 10 workouts.",
    )
    max_pages = st.number_input(
        "Max Hevy API pages",
        min_value=1,
        max_value=100,
        value=30,
        step=1,
        help="Use a larger value when you want longer exercise histories.",
    )
    trend_days = st.selectbox(
        "Default trend period",
        [30, 60, 90, 180, 365],
        index=2,
    )
    if st.button("Refresh cached data"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption(
        "Goals are stored in data/fitness_goals.json. Exercise matching rules "
        "are stored in data/goal_exercise_aliases.csv."
    )
    st.caption(
        "V10: sections remain lazy-loaded; endurance now has its own progress view."
    )

source_status = []
df, loaded_from = load_data(
    page_size=int(page_size),
    max_pages=int(max_pages),
)
source_status.append(
    {
        "source": "Hevy",
        "status": "OK" if not df.empty else "EMPTY",
        "records": len(df),
        "details": loaded_from,
    }
)

if df.empty:
    st.error(
        "No Hevy data loaded. Check HEVY_API_KEY or increase Max Hevy API pages."
    )
    st.stop()

# Lightweight Hevy summaries are shared across views.
session_summary = build_session_summary(df)
goals = load_goals(GOALS_PATH)
body_proxy = load_body_composition_proxy(GOALS_PATH)
alias_rules = load_alias_rules(GOAL_ALIASES_PATH)

st.caption(f"Hevy loaded from **{loaded_from}** · Today is treated as a partial day.")

SECTION_OPTIONS = [
    "Overview & Goals",
    "Workout Review",
    "Strength Progress",
    "Endurance",
    "Body Composition & Nutrition",
    "Recovery & Data Quality",
]
selected_section = st.radio(
    "Dashboard section",
    SECTION_OPTIONS,
    horizontal=True,
    label_visibility="collapsed",
    key="dashboard_section",
)

# Empty defaults make section-specific code explicit and keep inactive
# sections from triggering network calls.
health_steps = pd.DataFrame()
recovery = pd.DataFrame()
sleep = pd.DataFrame()
body = pd.DataFrame()
nutrition = pd.DataFrame()
endurance = pd.DataFrame()
performance_history = pd.DataFrame()
goal_progress = pd.DataFrame()
body_calc = pd.DataFrame()

if selected_section == "Overview & Goals":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_google_health_steps(days=90),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_google_health_sleep(days=90),
        source_status,
    )
    body = safe_frame(
        "Google Health body composition",
        lambda: load_google_health_body(days=90),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_google_health_nutrition(days=90),
        source_status,
    )
    # Endurance history is intentionally deferred to the Endurance section.
    goal_progress = build_goal_progress(
        goals,
        body,
        df,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )
    body_calc = prepare_body_calculations(body, body_proxy)

elif selected_section == "Workout Review":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_google_health_steps(days=90),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_google_health_recovery(days=90),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_google_health_sleep(days=90),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_google_health_nutrition(days=90),
        source_status,
    )
    # Workout HR is loaded later only for the selected workout.

elif selected_section == "Strength Progress":
    performance_history = build_exercise_performance_history(df)
    goal_progress = build_goal_progress(
        goals,
        body,
        df,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Endurance":
    endurance = safe_frame(
        "Google Health endurance sessions",
        lambda: load_google_health_endurance_sessions(days=730),
        source_status,
    )
    goal_progress = build_goal_progress(
        goals,
        body,
        df,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Body Composition & Nutrition":
    body = safe_frame(
        "Google Health body composition",
        lambda: load_google_health_body(days=365),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_google_health_nutrition(days=90),
        source_status,
    )
    endurance = safe_frame(
        "Google Health endurance sessions",
        lambda: load_google_health_endurance_sessions(days=90),
        source_status,
    )
    goal_progress = build_goal_progress(
        goals,
        body,
        df,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )
    body_calc = prepare_body_calculations(body, body_proxy)

elif selected_section == "Recovery & Data Quality":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_google_health_steps(days=90),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_google_health_recovery(days=90),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_google_health_sleep(days=90),
        source_status,
    )


if selected_section == "Overview & Goals":
    st.header("Current overview")
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    week_start = today - timedelta(days=7)

    latest_weight = latest_value(body, "weight_kg")
    latest_fat = latest_value(body, "body_fat_pct")
    recent_sessions = session_summary.copy()
    if not recent_sessions.empty:
        recent_sessions["start_date"] = pd.to_datetime(
            recent_sessions["start_time"], errors="coerce"
        ).dt.date
        week_sessions = recent_sessions[recent_sessions["start_date"] >= week_start]
    else:
        week_sessions = pd.DataFrame()

    steps_7 = health_steps.tail(7) if not health_steps.empty else pd.DataFrame()
    sleep_7 = sleep.dropna(subset=["sleep_hours"]).tail(7) if not sleep.empty else pd.DataFrame()
    food_logged = (
        nutrition[pd.to_numeric(nutrition.get("calories_kcal"), errors="coerce") > 0]
        if not nutrition.empty else pd.DataFrame()
    )
    food_7 = food_logged.tail(7)

    row1 = st.columns(5)
    row1[0].metric(
        "Current weight",
        f"{latest_weight:.2f} kg" if latest_weight is not None else "—",
        f"{latest_weight - 90:+.1f} kg to <90" if latest_weight is not None else None,
        delta_color="inverse",
    )
    row1[1].metric(
        "Current body fat",
        f"{latest_fat:.2f}%" if latest_fat is not None else "—",
        f"{latest_fat - 15:+.1f} pp to <15%" if latest_fat is not None else None,
        delta_color="inverse",
    )
    latest_mm_pct = (
        float(body_calc.iloc[-1]["estimated_muscle_mass_pct_7d_median"])
        if not body_calc.empty
        and pd.notna(body_calc.iloc[-1]["estimated_muscle_mass_pct_7d_median"])
        else None
    )
    row1[2].metric(
        "Estimated MM — 7d median",
        f"{latest_mm_pct:.2f}%" if latest_mm_pct is not None else "—",
        f"{latest_mm_pct - 80:+.1f} pp vs >80%"
        if latest_mm_pct is not None
        else None,
    )
    row1[3].metric("Workouts — last 7 days", len(week_sessions))
    row1[4].metric(
        "Weekly session load",
        (
            f"{pd.to_numeric(week_sessions.get('session_load'), errors='coerce').sum():,.0f}"
            if not week_sessions.empty else "—"
        ),
    )

    row2 = st.columns(4)
    row2[0].metric(
        "7-day steps",
        f"{steps_7['steps'].mean():,.0f} / day" if not steps_7.empty else "—",
    )
    row2[1].metric(
        "7-day sleep",
        f"{sleep_7['sleep_hours'].mean():.2f} h" if not sleep_7.empty else "—",
    )
    row2[2].metric(
        "7-day calories",
        f"{food_7['calories_kcal'].mean():,.0f} kcal" if not food_7.empty else "—",
    )
    row2[3].metric(
        "7-day protein",
        f"{food_7['protein_g'].mean():.0f} g" if not food_7.empty else "—",
    )

    st.subheader("Attention flags")
    flags = []
    if not session_summary.empty:
        latest_sessions = session_summary.head(8)
        missing_session_rpe = int(latest_sessions["session_rpe"].isna().sum())
        if missing_session_rpe:
            flags.append(f"{missing_session_rpe} of the latest {len(latest_sessions)} workouts are missing session RPE.")
        set_eligible = pd.to_numeric(latest_sessions["set_rpe_eligible"], errors="coerce").sum()
        set_logged = pd.to_numeric(latest_sessions["set_rpe_logged"], errors="coerce").sum()
        if set_eligible and set_logged / set_eligible < 0.8:
            flags.append(f"Set-RPE coverage is {set_logged / set_eligible * 100:.0f}% across the latest workouts.")
    if len(food_7) < 6:
        flags.append(f"Only {len(food_7)} nutrition days are populated in the latest seven logged-day window.")
    if len(sleep_7) < 6:
        flags.append(f"Only {len(sleep_7)} sleep days are populated in the latest seven-day window.")
    if not flags:
        st.success("No major data-completeness flags in the current overview.")
    else:
        for flag in flags:
            st.warning(flag)

    st.subheader("Goal tracker")
    primary_goal_names = [
        "Back squat — 3RM reference",
        "Bench press — 3RM reference",
        "Deadlift — 3RM reference",
        "Pull-ups",
        "Push-ups in one minute",
        "Bar hang",
    ]
    primary_goals = (
        goal_progress[
            goal_progress["goal"].isin(primary_goal_names)
        ]
        .assign(
            _goal_order=lambda frame: frame["goal"].map(
                {name: index for index, name in enumerate(primary_goal_names)}
            )
        )
        .sort_values("_goal_order")
        .drop(columns="_goal_order")
    )

    if not primary_goals.empty:
        goal_rows = list(primary_goals.iterrows())
        for row_start in range(0, len(goal_rows), 3):
            cards = st.columns(3)
            for column_index, (_, goal) in enumerate(
                goal_rows[row_start : row_start + 3]
            ):
                with cards[column_index]:
                    st.metric(
                        goal["goal"],
                        goal["current_display"],
                        f"Target: {goal['target_display']}",
                    )
                    if pd.notna(goal.get("progress_pct")):
                        st.progress(
                            int(
                                max(
                                    0,
                                    min(100, goal["progress_pct"]),
                                )
                            )
                        )
                    st.caption(goal["status"])

    with st.expander("Body composition & strength goals", expanded=False):
        overview_goal_progress = goal_progress[
            goal_progress["category"].isin(["Body Composition", "Strength"])
        ]
        render_goal_table(overview_goal_progress)
        st.caption(
            "Run, swim and bike goal history loads only in Endurance "
            "to keep the Overview fast."
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Latest 30 days — activity")
        if health_steps.empty:
            st.info("No step data available.")
        else:
            fig = px.bar(
                health_steps.tail(30),
                x="date",
                y="steps",
                labels={"date": "Date", "steps": "Steps"},
            )
            fig.add_hline(y=8000, line_dash="dash", annotation_text="8,000")
            fig.update_layout(height=320, xaxis_tickformat="%d %b")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Latest 30 days — training load")
        if session_summary.empty:
            st.info("No session-load history available.")
        else:
            load_chart = session_summary.dropna(subset=["session_load"]).copy()
            load_chart = load_chart.sort_values("start_time").tail(30)
            if load_chart.empty:
                st.info("Add session RPE to workout descriptions to calculate session load.")
            else:
                fig = px.bar(
                    load_chart,
                    x="start_time",
                    y="session_load",
                    hover_data=["title", "session_rpe", "duration_minutes"],
                    labels={"start_time": "Workout", "session_load": "Session load"},
                )
                fig.update_layout(height=320, xaxis_tickformat="%d %b")
                st.plotly_chart(fig, use_container_width=True)

elif selected_section == "Workout Review":
    st.header("Workout review")
    if session_summary.empty:
        st.info("No workout sessions are available.")
    else:
        sessions = session_summary.copy()
        sessions["session_label"] = sessions.apply(
            lambda row: (
                f"{row['start_time'].strftime('%d %b %Y %H:%M')} — "
                f"{row['title']} ({row['duration_minutes']:.0f} min)"
            ),
            axis=1,
        )
        selected_label = st.selectbox(
            "Workout session",
            sessions.head(30)["session_label"].tolist(),
        )
        selected = sessions[sessions["session_label"] == selected_label].iloc[0]
        selected_rows = select_session_rows(df, selected)
        exercise_summary = build_exercise_summary(selected_rows)
        comparison = build_previous_exercise_comparison(df, selected)
        if not comparison.empty:
            comparison["Progress status"] = comparison.apply(progression_label, axis=1)

        hr_analysis = None
        try:
            hr_analysis = load_workout_heart_rate_analysis(
                selected["start_time"].isoformat(),
                selected["end_time"].isoformat(),
            )
        except Exception as exc:
            st.warning(f"Workout heart-rate analysis could not be loaded: {exc}")

        duration = pd.to_numeric(selected.get("duration_minutes"), errors="coerce")
        working_sets = pd.to_numeric(selected.get("working_sets"), errors="coerce")
        volume = pd.to_numeric(selected.get("recorded_working_volume_kg"), errors="coerce")
        set_density = (
            working_sets / duration * 60
            if pd.notna(duration) and duration > 0 and pd.notna(working_sets)
            else pd.NA
        )
        volume_density = (
            volume / duration
            if pd.notna(duration) and duration > 0 and pd.notna(volume)
            else pd.NA
        )

        hr_summary = hr_analysis.get("summary", {}) if hr_analysis else {}
        top = st.columns(5)
        top[0].metric("Duration", f"{duration:.0f} min" if pd.notna(duration) else "—")
        top[1].metric("Average HR", f"{hr_summary.get('average_hr', 0):.0f} bpm" if hr_summary.get("average_hr") else "—")
        top[2].metric("Maximum HR", f"{hr_summary.get('maximum_hr', 0):.0f} bpm" if hr_summary.get("maximum_hr") else "—")
        top[3].metric("Session RPE", f"{selected['session_rpe']:.1f}" if pd.notna(selected.get("session_rpe")) else "—")
        top[4].metric("Session load", f"{selected['session_load']:.0f}" if pd.notna(selected.get("session_load")) else "—")

        second = st.columns(5)
        second[0].metric("Working sets", f"{working_sets:.0f}" if pd.notna(working_sets) else "—")
        second[1].metric("Warm-up sets", f"{selected['warmup_sets']:.0f}" if pd.notna(selected.get("warmup_sets")) else "—")
        second[2].metric("Set density", f"{set_density:.1f} / h" if pd.notna(set_density) else "—")
        second[3].metric("Volume density", f"{volume_density:,.0f} kg/min" if pd.notna(volume_density) else "—")
        second[4].metric("Average set RPE", f"{selected['average_set_rpe']:.1f}" if pd.notna(selected.get("average_set_rpe")) else "—")

        if str(selected.get("description", "")).strip():
            st.info("Session note: " + str(selected["description"]))

        hr_left, hr_right = st.columns([2, 1])
        with hr_left:
            st.subheader("Workout heart rate")
            samples = hr_analysis.get("samples", pd.DataFrame()) if hr_analysis else pd.DataFrame()
            if samples.empty:
                st.info("No wearable heart-rate samples were returned for this interval.")
            else:
                chart = samples.copy()
                chart["minutes"] = (
                    pd.to_datetime(chart["timestamp"], errors="coerce")
                    - pd.Timestamp(selected["start_time"])
                ).dt.total_seconds() / 60
                fig = px.line(
                    chart,
                    x="minutes",
                    y="bpm",
                    labels={"minutes": "Minutes into workout", "bpm": "Heart rate (bpm)"},
                )
                fig.update_layout(height=360)
                st.plotly_chart(fig, use_container_width=True)
        with hr_right:
            st.subheader("HR zones")
            zone_summary = hr_analysis.get("zone_summary", pd.DataFrame()) if hr_analysis else pd.DataFrame()
            if zone_summary.empty:
                st.info("No zone summary available.")
            else:
                fig = px.bar(
                    zone_summary,
                    x="zone",
                    y="minutes",
                    labels={"zone": "Zone", "minutes": "Minutes"},
                )
                fig.update_layout(height=360)
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recovery and nutrition context")
        context = recovery_context_row(
            selected,
            sleep,
            recovery,
            health_steps,
            nutrition,
        )
        if not context:
            st.info("No context could be matched to this workout date.")
        else:
            c = st.columns(5)
            c[0].metric("Sleep before", f"{context['Sleep before workout']:.2f} h" if pd.notna(context['Sleep before workout']) else "—")
            c[1].metric("Resting HR", f"{context['Resting HR']:.0f} bpm" if pd.notna(context['Resting HR']) else "—")
            c[2].metric("HRV", f"{context['HRV']:.1f} ms" if pd.notna(context['HRV']) else "—")
            c[3].metric("Prior-day calories", f"{context['Previous-day calories']:,.0f}" if pd.notna(context['Previous-day calories']) else "—")
            c[4].metric("Prior-day protein", f"{context['Previous-day protein']:.0f} g" if pd.notna(context['Previous-day protein']) else "—")
            with st.expander("Baseline and next-day context"):
                context_table = pd.DataFrame(
                    [{"Metric": key, "Value": value} for key, value in context.items()]
                )
                st.dataframe(context_table, use_container_width=True, hide_index=True)

        compare_tab, exercises_tab, notes_tab, sets_tab = st.tabs(
            ["Previous comparison", "Exercise summary", "Notes", "Set detail"]
        )
        with compare_tab:
            if comparison.empty:
                st.info("No previous exercise occurrences were found.")
            else:
                st.dataframe(comparison, use_container_width=True, hide_index=True)
                st.caption(
                    "Progressed = higher load or ≥5% more volume without average set RPE rising by more than 0.5. "
                    "Maintained = small load/volume change. Other program changes are marked for review."
                )
        with exercises_tab:
            if exercise_summary.empty:
                st.info("No exercise summary available.")
            else:
                st.dataframe(exercise_summary, use_container_width=True, hide_index=True)
        with notes_tab:
            flags = build_note_flags(selected_rows)
            if flags.empty:
                st.info("No exercise notes were recorded.")
            else:
                st.dataframe(flags, use_container_width=True, hide_index=True)
        with sets_tab:
            st.dataframe(
                format_set_table(selected_rows),
                use_container_width=True,
                hide_index=True,
                height=520,
            )

elif selected_section == "Strength Progress":
    st.header("Strength progress")
    if performance_history.empty:
        st.info("No working-set performance history is available.")
    else:
        exercises = sorted(performance_history["exercise"].dropna().astype(str).unique())
        selected_exercise = st.selectbox("Exercise", exercises)
        history = performance_history[
            performance_history["exercise"] == selected_exercise
        ].sort_values("start_time").tail(20)

        latest = history.iloc[-1]
        e1rm_delta = (
            latest["best_e1rm_kg"] - history.iloc[-2]["best_e1rm_kg"]
            if len(history) > 1
            and pd.notna(latest["best_e1rm_kg"])
            and pd.notna(history.iloc[-2]["best_e1rm_kg"])
            else None
        )
        cards = st.columns(5)
        cards[0].metric("Best e1RM", f"{latest['best_e1rm_kg']:.1f} kg" if pd.notna(latest["best_e1rm_kg"]) else "—", f"{e1rm_delta:+.1f} kg vs prior" if e1rm_delta is not None else None)
        cards[1].metric("Max load", f"{latest['max_weight_kg']:.1f} kg" if pd.notna(latest["max_weight_kg"]) else "—")
        cards[2].metric("Working volume", f"{latest['working_volume_kg']:,.0f} kg")
        cards[3].metric("Working sets", f"{latest['working_sets']:.0f}")
        cards[4].metric("Average set RPE", f"{latest['average_set_rpe']:.1f}" if pd.notna(latest["average_set_rpe"]) else "—")

        metric_tab, volume_tab, rpe_tab = st.tabs(["Estimated strength", "Volume", "RPE"])
        with metric_tab:
            chart = history.melt(
                id_vars="start_time",
                value_vars=["best_e1rm_kg", "max_weight_kg"],
                var_name="metric",
                value_name="kg",
            )
            chart["metric"] = chart["metric"].map(
                {"best_e1rm_kg": "Estimated 1RM", "max_weight_kg": "Max working load"}
            )
            fig = px.line(chart, x="start_time", y="kg", color="metric", markers=True)
            fig.update_layout(height=390, xaxis_tickformat="%d %b %Y")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Estimated 1RM uses the Epley formula only for loaded working sets of 1–12 reps.")
        with volume_tab:
            fig = px.bar(
                history,
                x="start_time",
                y="working_volume_kg",
                labels={"start_time": "Workout", "working_volume_kg": "Working volume (kg)"},
            )
            fig.update_layout(height=390, xaxis_tickformat="%d %b %Y")
            st.plotly_chart(fig, use_container_width=True)
        with rpe_tab:
            fig = px.line(
                history,
                x="start_time",
                y="average_set_rpe",
                markers=True,
                labels={"start_time": "Workout", "average_set_rpe": "Average set RPE"},
            )
            fig.update_yaxes(range=[0, 10])
            fig.update_layout(height=390, xaxis_tickformat="%d %b %Y")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recent personal records")
        pr_rows = performance_history[
            performance_history[["weight_pr", "e1rm_pr", "volume_pr", "reps_pr"]].any(axis=1)
        ].head(30).copy()
        if pr_rows.empty:
            st.info("No PR rows were identified.")
        else:
            pr_rows["PR types"] = pr_rows.apply(
                lambda row: ", ".join(
                    label
                    for flag, label in [
                        ("weight_pr", "Weight"),
                        ("e1rm_pr", "e1RM"),
                        ("volume_pr", "Volume"),
                        ("reps_pr", "Reps"),
                    ]
                    if bool(row[flag])
                ),
                axis=1,
            )
            st.dataframe(
                pr_rows[
                    [
                        "workout_date", "exercise", "PR types", "max_weight_kg",
                        "best_e1rm_kg", "working_volume_kg", "reps", "average_set_rpe",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    st.subheader("Strength-goal comparisons")
    render_goal_table(goal_progress, "Strength")
    with st.expander("Exercise matching rules"):
        alias_frame = pd.DataFrame(alias_rules)
        st.dataframe(alias_frame, use_container_width=True, hide_index=True)
        st.caption(
            "Edit data/goal_exercise_aliases.csv when a Hevy exercise name is not mapped correctly."
        )


elif selected_section == "Endurance":
    st.header("Endurance progress")

    if endurance.empty:
        st.info("No reconciled run, swim or bike sessions are available.")
    else:
        activity_labels = {
            "run": "Run",
            "swim": "Swim",
            "bike": "Bike",
        }
        available_activities = [
            activity
            for activity in ("run", "swim", "bike")
            if activity in set(endurance["goal_activity"].astype(str))
        ]
        # Keep all three selectable even when one currently has no data.
        activity_options = ["run", "swim", "bike"]
        selected_activity = st.radio(
            "Endurance activity",
            activity_options,
            horizontal=True,
            format_func=lambda value: activity_labels[value],
            key="endurance_activity",
        )

        activity = endurance[
            endurance["goal_activity"].astype(str).eq(selected_activity)
        ].copy()
        activity["date"] = pd.to_datetime(activity["date"], errors="coerce")
        activity["distance_km"] = pd.to_numeric(
            activity["distance_km"], errors="coerce"
        )
        activity["duration_hours"] = pd.to_numeric(
            activity["duration_hours"], errors="coerce"
        )
        activity["average_hr"] = pd.to_numeric(
            activity["average_hr"], errors="coerce"
        )
        activity = activity.dropna(subset=["date"]).sort_values("date")

        st.subheader(f"{activity_labels[selected_activity]} summary")

        if activity.empty:
            st.info(
                f"No {activity_labels[selected_activity].lower()} sessions "
                "are available in the current history."
            )
        else:
            distance_valid = activity[
                pd.to_numeric(activity["distance_km"], errors="coerce") > 0
            ].copy()
            duration_valid = activity[
                pd.to_numeric(activity["duration_hours"], errors="coerce") > 0
            ].copy()
            performance_valid = activity[
                (pd.to_numeric(activity["distance_km"], errors="coerce") > 0)
                & (pd.to_numeric(activity["duration_hours"], errors="coerce") > 0)
            ].copy()

            if selected_activity == "run":
                performance_valid["performance_value"] = (
                    performance_valid["duration_hours"] * 60
                    / performance_valid["distance_km"]
                )
                performance_label = "Pace (min/km)"
                best_value = (
                    performance_valid["performance_value"].min()
                    if not performance_valid.empty
                    else None
                )
                best_label = "Fastest pace"

                def format_performance(value):
                    if value is None or pd.isna(value):
                        return "—"
                    whole = int(value)
                    seconds = int(round((float(value) - whole) * 60))
                    if seconds == 60:
                        whole += 1
                        seconds = 0
                    return f"{whole}:{seconds:02d} min/km"

            elif selected_activity == "swim":
                performance_valid["performance_value"] = (
                    performance_valid["duration_hours"] * 60
                    / (performance_valid["distance_km"] * 10)
                )
                performance_label = "Pace (min/100 m)"
                best_value = (
                    performance_valid["performance_value"].min()
                    if not performance_valid.empty
                    else None
                )
                best_label = "Fastest pace"

                def format_performance(value):
                    if value is None or pd.isna(value):
                        return "—"
                    whole = int(value)
                    seconds = int(round((float(value) - whole) * 60))
                    if seconds == 60:
                        whole += 1
                        seconds = 0
                    return f"{whole}:{seconds:02d} /100 m"

            else:
                performance_valid["performance_value"] = (
                    performance_valid["distance_km"]
                    / performance_valid["duration_hours"]
                )
                performance_label = "Average speed (km/h)"
                best_value = (
                    performance_valid["performance_value"].max()
                    if not performance_valid.empty
                    else None
                )
                best_label = "Best avg speed"

                def format_performance(value):
                    if value is None or pd.isna(value):
                        return "—"
                    return f"{float(value):.1f} km/h"

            longest_distance = (
                float(distance_valid["distance_km"].max())
                if not distance_valid.empty
                else None
            )
            longest_duration = (
                float(duration_valid["duration_hours"].max())
                if not duration_valid.empty
                else None
            )
            mean_hr = activity["average_hr"].dropna().mean()

            e = st.columns(5)
            e[0].metric("Sessions", len(activity))
            e[1].metric(
                "Longest distance",
                f"{longest_distance:.2f} km"
                if longest_distance is not None
                else "—",
            )
            e[2].metric(
                "Longest duration",
                f"{longest_duration:.2f} h"
                if longest_duration is not None
                else "—",
            )
            e[3].metric(best_label, format_performance(best_value))
            e[4].metric(
                "Mean session HR",
                f"{mean_hr:.0f} bpm" if pd.notna(mean_hr) else "—",
            )

            chart_left, chart_right = st.columns(2)

            with chart_left:
                st.markdown("**Distance progression**")
                if distance_valid.empty:
                    st.info("No valid distance values are available.")
                else:
                    distance_fig = px.line(
                        distance_valid,
                        x="date",
                        y="distance_km",
                        markers=True,
                        hover_data=["display_name", "duration_hours", "average_hr"],
                        labels={"date": "Date", "distance_km": "Distance (km)"},
                    )
                    distance_fig.update_layout(
                        height=320,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(distance_fig, use_container_width=True)

                st.markdown(f"**{performance_label}**")
                if performance_valid.empty:
                    st.info("Distance and duration are required for this metric.")
                else:
                    performance_fig = px.line(
                        performance_valid,
                        x="date",
                        y="performance_value",
                        markers=True,
                        hover_data=["distance_km", "duration_hours", "average_hr"],
                        labels={
                            "date": "Date",
                            "performance_value": performance_label,
                        },
                    )
                    performance_fig.update_layout(
                        height=320,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(performance_fig, use_container_width=True)

            with chart_right:
                st.markdown("**Session duration**")
                if duration_valid.empty:
                    st.info("No valid duration values are available.")
                else:
                    duration_fig = px.line(
                        duration_valid,
                        x="date",
                        y="duration_hours",
                        markers=True,
                        hover_data=["display_name", "distance_km", "average_hr"],
                        labels={"date": "Date", "duration_hours": "Hours"},
                    )
                    duration_fig.update_layout(
                        height=320,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(duration_fig, use_container_width=True)

                st.markdown("**Average heart rate**")
                hr_valid = activity.dropna(subset=["average_hr"])
                if hr_valid.empty:
                    st.info("No average-HR values are available.")
                else:
                    hr_fig = px.line(
                        hr_valid,
                        x="date",
                        y="average_hr",
                        markers=True,
                        hover_data=["display_name", "distance_km", "duration_hours"],
                        labels={"date": "Date", "average_hr": "Average HR (bpm)"},
                    )
                    hr_fig.update_layout(
                        height=320,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(hr_fig, use_container_width=True)

            st.subheader(f"{activity_labels[selected_activity]} goal progress")
            selected_goal_rows = goal_progress[
                (goal_progress["category"] == "Endurance")
                & goal_progress["goal"].astype(str).str.lower().str.startswith(
                    selected_activity
                )
            ]
            render_goal_table(selected_goal_rows)

            if not distance_valid.empty:
                longest_row = distance_valid.loc[
                    distance_valid["distance_km"].idxmax()
                ]
                st.caption(
                    "Longest recorded session: "
                    f"{longest_row['distance_km']:.2f} km on "
                    f"{pd.Timestamp(longest_row['date']).strftime('%d %b %Y')}."
                )

        st.subheader("All endurance-goal comparisons")
        render_goal_table(goal_progress, "Endurance")

        with st.expander("Reconciled run, swim and bike sessions"):
            display_columns = [
                column
                for column in [
                    "date",
                    "goal_activity",
                    "display_name",
                    "distance_km",
                    "duration_hours",
                    "average_hr",
                    "calories_kcal",
                    "source_platform",
                ]
                if column in endurance.columns
            ]
            st.dataframe(
                endurance[display_columns],
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Endurance source status"):
            st.dataframe(
                pd.DataFrame(source_status),
                use_container_width=True,
                hide_index=True,
            )

elif selected_section == "Body Composition & Nutrition":
    st.header("Body composition and nutrition")

    st.subheader("Google Health body composition")
    latest_weight = latest_value(body, "weight_kg")
    latest_fat = latest_value(body, "body_fat_pct")
    latest_paired = body_calc.iloc[-1] if not body_calc.empty else None
    bone_baseline = float(body_proxy["bone_mass_baseline_kg"])

    b = st.columns(5)
    b[0].metric(
        "Weight",
        f"{latest_weight:.2f} kg" if latest_weight is not None else "—",
        f"{latest_weight - 90:+.1f} kg to <90"
        if latest_weight is not None
        else None,
        delta_color="inverse",
    )
    b[1].metric(
        "Body fat",
        f"{latest_fat:.2f}%" if latest_fat is not None else "—",
        f"{latest_fat - 15:+.1f} pp to <15%"
        if latest_fat is not None
        else None,
        delta_color="inverse",
    )
    b[2].metric(
        "Calculated fat mass",
        f"{latest_paired['calculated_fat_mass_kg']:.2f} kg"
        if latest_paired is not None
        else "—",
    )
    b[3].metric(
        "Estimated muscle mass",
        f"{latest_paired['estimated_muscle_mass_kg']:.2f} kg"
        if latest_paired is not None
        else "—",
    )
    b[4].metric(
        "Estimated muscle mass %",
        f"{latest_paired['estimated_muscle_mass_pct_7d_median']:.2f}%"
        if latest_paired is not None
        else "—",
        f"{latest_paired['estimated_muscle_mass_pct_7d_median'] - 80:+.1f} pp vs >80%"
        if latest_paired is not None
        else None,
    )

    if body.empty:
        st.info("No body-composition data is available.")
    else:
        period_start = (
            datetime.now(ZoneInfo("Europe/Berlin")).date()
            - timedelta(days=trend_days)
        )
        body_dates = pd.to_datetime(body["date"], errors="coerce").dt.date
        trend = body[body_dates >= period_start].copy()

        calc_trend = body_calc.copy()
        if not calc_trend.empty:
            calc_dates = pd.to_datetime(
                calc_trend["date"], errors="coerce"
            ).dt.date
            calc_trend = calc_trend[calc_dates >= period_start].copy()

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("**Weight / body-fat trend**")
            trend_metric = st.radio(
                "Body trend",
                ["Weight", "Body fat"],
                horizontal=True,
                label_visibility="collapsed",
                key="body_trend_metric",
            )
            if trend_metric == "Weight":
                weight_trend = trend.dropna(subset=["weight_kg"])
                if weight_trend.empty:
                    st.info("No weight measurements in this period.")
                else:
                    fig = px.line(
                        weight_trend,
                        x="date",
                        y="weight_kg",
                        markers=True,
                        labels={
                            "date": "Date",
                            "weight_kg": "Weight (kg)",
                        },
                    )
                    fig.add_hline(
                        y=90,
                        line_dash="dash",
                        annotation_text="90 kg goal",
                    )
                    fig.update_layout(
                        height=340,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                fat_trend = trend.dropna(subset=["body_fat_pct"])
                if fat_trend.empty:
                    st.info("No body-fat measurements in this period.")
                else:
                    fig = px.line(
                        fat_trend,
                        x="date",
                        y="body_fat_pct",
                        markers=True,
                        labels={
                            "date": "Date",
                            "body_fat_pct": "Body fat (%)",
                        },
                    )
                    fig.add_hline(
                        y=15,
                        line_dash="dash",
                        annotation_text="15% goal",
                    )
                    fig.update_layout(
                        height=340,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("**Fat mass vs estimated muscle mass**")
            if calc_trend.empty:
                st.info("Paired weight/body-fat data is unavailable.")
            else:
                composition_long = calc_trend[
                    [
                        "date",
                        "calculated_fat_mass_kg_7d_median",
                        "estimated_muscle_mass_kg_7d_median",
                    ]
                ].melt(
                    id_vars="date",
                    var_name="metric",
                    value_name="kg",
                )
                composition_long["metric"] = composition_long["metric"].map(
                    {
                        "calculated_fat_mass_kg_7d_median": "Fat mass — 7d median",
                        "estimated_muscle_mass_kg_7d_median": "Estimated muscle mass — 7d median",
                    }
                )
                fig = px.line(
                    composition_long,
                    x="date",
                    y="kg",
                    color="metric",
                    labels={"date": "Date", "kg": "kg", "metric": "Metric"},
                )
                fig.update_layout(
                    height=340,
                    xaxis_tickformat="%d %b",
                    legend_title_text="",
                )
                st.plotly_chart(fig, use_container_width=True)

        with c3:
            st.markdown("**Estimated muscle-mass percentage**")
            if calc_trend.empty:
                st.info("Paired weight/body-fat data is unavailable.")
            else:
                mm_fig = px.line(
                    calc_trend,
                    x="date",
                    y="estimated_muscle_mass_pct_7d_median",
                    labels={
                        "date": "Date",
                        "estimated_muscle_mass_pct_7d_median": (
                            "Estimated muscle mass — 7d median (%)"
                        ),
                    },
                )
                mm_fig.add_hline(
                    y=80,
                    line_dash="dash",
                    annotation_text="MM >80% goal",
                )
                mm_fig.update_layout(
                    height=340,
                    xaxis_tickformat="%d %b",
                )
                st.plotly_chart(mm_fig, use_container_width=True)

        if not body_calc.empty:
            latest_mm = float(
                body_calc.iloc[-1]["estimated_muscle_mass_kg_7d_median"]
            )
            earlier_mm = value_28_days_earlier(
                body_calc,
                "estimated_muscle_mass_kg_7d_median",
            )
            if earlier_mm is not None:
                st.caption(
                    f"28-day estimated muscle-mass change: "
                    f"{latest_mm - earlier_mm:+.2f} kg."
                )

        st.caption(
            f"Estimated muscle mass = weight − calculated fat mass − "
            f"{bone_baseline:.2f} kg fixed bone-mass baseline. "
            "Trends use a 7-day rolling median. "
            "This is a Withings-compatible proxy, not a direct skeletal-muscle measurement."
        )

    st.subheader("Nutrition adherence")
    logged = (
        nutrition[
            pd.to_numeric(
                nutrition.get("calories_kcal"),
                errors="coerce",
            )
            > 0
        ].copy()
        if not nutrition.empty
        else pd.DataFrame()
    )

    if logged.empty:
        st.info("No nutrition data is available.")
    else:
        logged["date_only"] = pd.to_datetime(
            logged["date"], errors="coerce"
        ).dt.date

        strength_dates = (
            set(
                pd.to_datetime(
                    session_summary["start_time"],
                    errors="coerce",
                ).dt.date.dropna()
            )
            if not session_summary.empty
            else set()
        )
        endurance_dates = (
            set(
                pd.to_datetime(
                    endurance["date"],
                    errors="coerce",
                ).dt.date.dropna()
            )
            if not endurance.empty
            else set()
        )

        def nutrition_day_type(day):
            has_strength = day in strength_dates
            has_endurance = day in endurance_dates
            if has_strength and has_endurance:
                return "Strength + Endurance"
            if has_strength:
                return "Strength Training"
            if has_endurance:
                return "Endurance"
            return "Rest Day"

        day_order = [
            "Strength Training",
            "Endurance",
            "Strength + Endurance",
            "Rest Day",
        ]
        logged["day_type"] = logged["date_only"].map(nutrition_day_type)
        logged["day_type"] = pd.Categorical(
            logged["day_type"],
            categories=day_order,
            ordered=True,
        )

        recent = logged.sort_values("date_only").tail(30)
        seven = logged.sort_values("date_only").tail(7)

        n = st.columns(4)
        n[0].metric(
            "7-day calories",
            f"{seven['calories_kcal'].mean():,.0f}",
        )
        n[1].metric(
            "7-day protein",
            f"{seven['protein_g'].mean():.0f} g",
        )
        protein_per_kg = (
            seven["protein_g"].mean() / latest_weight
            if latest_weight
            else None
        )
        n[2].metric(
            "Protein / kg BW",
            f"{protein_per_kg:.2f} g/kg"
            if protein_per_kg
            else "—",
        )
        n[3].metric("Logged days — last 30", len(recent))

        nutrition_chart, nutrition_summary = st.columns([2, 1])

        with nutrition_chart:
            fig = px.bar(
                recent,
                x="date",
                y="calories_kcal",
                color="day_type",
                hover_data=["protein_g", "carbs_g", "fat_g"],
                category_orders={"day_type": day_order},
                labels={
                    "date": "Date",
                    "calories_kcal": "Calories",
                    "day_type": "Day type",
                },
            )
            fig.update_layout(
                height=380,
                xaxis_tickformat="%d %b",
            )
            st.plotly_chart(fig, use_container_width=True)

        with nutrition_summary:
            comparison = (
                recent.groupby(
                    "day_type",
                    observed=True,
                )[
                    [
                        "calories_kcal",
                        "protein_g",
                        "carbs_g",
                        "fat_g",
                    ]
                ]
                .mean()
                .round(1)
                .reindex(day_order)
                .dropna(how="all")
            )
            st.markdown("**Average intake by day type**")
            st.dataframe(
                comparison,
                use_container_width=True,
            )
            counts = (
                recent.groupby("day_type", observed=True)
                .size()
                .reindex(day_order)
                .fillna(0)
                .astype(int)
                .rename("days")
            )
            st.markdown("**Logged days by type**")
            st.dataframe(
                counts.to_frame(),
                use_container_width=True,
            )

        st.caption(
            "Day classification: Strength Training = Hevy workout; "
            "Endurance = reconciled run/swim/bike session; "
            "Strength + Endurance = both on the same calendar day; "
            "Rest Day = neither."
        )

        excluded = int(
            pd.to_numeric(
                recent.get("excluded_fitbit_summary_records"),
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )
        if excluded:
            st.caption(
                f"Excluded {excluded} overlapping Fitbit nutrition "
                "summary record(s) in this period."
            )

    st.subheader("Body-composition goals")
    render_goal_table(goal_progress, "Body Composition")

elif selected_section == "Recovery & Data Quality":
    st.header("Recovery and data quality")

    rec_left, sleep_right = st.columns(2)

    with rec_left:
        st.subheader("Recovery versus 28-day baseline")
        if recovery.empty:
            st.info("No recovery data available.")
        else:
            recent = recovery.tail(60).copy()
            recent["rhr_28d"] = pd.to_numeric(
                recent["resting_hr"],
                errors="coerce",
            ).rolling(28, min_periods=7).mean()
            recent["hrv_28d"] = pd.to_numeric(
                recent["hrv_ms"],
                errors="coerce",
            ).rolling(28, min_periods=7).mean()

            rhr_fig = px.line(
                recent,
                x="date",
                y=["resting_hr", "rhr_28d"],
                labels={
                    "date": "Date",
                    "value": "Resting HR",
                    "variable": "Series",
                },
            )
            rhr_fig.update_layout(
                height=300,
                xaxis_tickformat="%d %b",
            )
            st.plotly_chart(rhr_fig, use_container_width=True)

            hrv_fig = px.line(
                recent,
                x="date",
                y=["hrv_ms", "hrv_28d"],
                labels={
                    "date": "Date",
                    "value": "HRV (ms)",
                    "variable": "Series",
                },
            )
            hrv_fig.update_layout(
                height=300,
                xaxis_tickformat="%d %b",
            )
            st.plotly_chart(hrv_fig, use_container_width=True)

    with sleep_right:
        st.subheader("Sleep consistency")
        main_sleep = (
            sleep.dropna(subset=["sleep_hours"]).tail(60).copy()
            if not sleep.empty
            else pd.DataFrame()
        )
        if main_sleep.empty:
            st.info("No sleep data available.")
        else:
            main_sleep["sleep_28d"] = pd.to_numeric(
                main_sleep["sleep_hours"],
                errors="coerce",
            ).rolling(28, min_periods=7).mean()

            fig = px.line(
                main_sleep,
                x="date",
                y=["sleep_hours", "sleep_28d"],
                labels={
                    "date": "Wake date",
                    "value": "Hours",
                    "variable": "Series",
                },
            )
            fig.update_layout(
                height=300,
                xaxis_tickformat="%d %b",
            )
            st.plotly_chart(fig, use_container_width=True)

            stages = main_sleep.tail(30)[
                ["date", "deep_minutes", "rem_minutes", "light_minutes"]
            ].melt(
                id_vars="date",
                var_name="stage",
                value_name="minutes",
            )
            stages["stage"] = stages["stage"].map(
                {
                    "deep_minutes": "Deep",
                    "rem_minutes": "REM",
                    "light_minutes": "Light",
                }
            )
            fig = px.bar(
                stages,
                x="date",
                y="minutes",
                color="stage",
            )
            fig.update_layout(
                barmode="stack",
                height=300,
                xaxis_tickformat="%d %b",
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Data quality")
    quality_rows = [
        source_quality_row(
            "Steps",
            health_steps,
            expected_days=14,
        ),
        source_quality_row(
            "Recovery",
            recovery,
            expected_days=14,
        ),
        source_quality_row(
            "Sleep",
            sleep,
            expected_days=14,
        ),
        source_quality_row(
            "Hevy sessions",
            session_summary,
            date_column="start_time",
        ),
    ]
    st.dataframe(
        pd.DataFrame(quality_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Endurance source status now lives in the Endurance section. "
        "Body-composition and nutrition source status are loaded with their own section."
    )

    if not session_summary.empty:
        q = st.columns(4)
        session_rpe_pct = (
            session_summary["session_rpe"].notna().mean() * 100
        )
        eligible = pd.to_numeric(
            session_summary["set_rpe_eligible"],
            errors="coerce",
        ).sum()
        logged_sets = pd.to_numeric(
            session_summary["set_rpe_logged"],
            errors="coerce",
        ).sum()
        set_rpe_pct = (
            logged_sets / eligible * 100
            if eligible
            else 0
        )
        warmup_sessions = (
            pd.to_numeric(
                session_summary["warmup_sets"],
                errors="coerce",
            )
            > 0
        ).mean() * 100

        q[0].metric(
            "Session-RPE coverage",
            f"{session_rpe_pct:.0f}%",
        )
        q[1].metric(
            "Set-RPE coverage",
            f"{set_rpe_pct:.0f}%",
        )
        q[2].metric(
            "Sessions with warm-ups marked",
            f"{warmup_sessions:.0f}%",
        )
        q[3].metric(
            "Hevy sessions loaded",
            len(session_summary),
        )

    with st.expander("Source errors and diagnostics"):
        st.dataframe(
            pd.DataFrame(source_status),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "A missing day can reflect no measurement, an incomplete sync, "
            "or a legitimately unlogged day. Today is excluded from complete-day expectations."
        )

st.divider()
st.caption(
    "Goal comparisons are descriptive training tools. Estimated 1RM, calculated fat mass, the Withings-compatible muscle-mass proxy, and recovery associations are estimates, not medical assessments."
)

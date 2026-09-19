import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
from renpho_data import (
    delete_renpho_measurement,
    insert_renpho_measurement,
    load_renpho_measurements,
)
from recomposition import build_recomposition_summary
from coaching_snapshot import load_latest_coaching_snapshot
from grip_data import (
    delete_grip_measurement,
    insert_grip_measurement,
    load_grip_measurements,
)

from withings_bridge import (
    build_withings_bp_sessions,
    build_withings_scale_sessions,
    latest_non_null as latest_withings_value,
    load_withings_dashboard_measurements,
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
HEVY_BODY_MEASUREMENTS_URL = "https://api.hevyapp.com/v1/body_measurements"
USER_HEIGHT_CM = 186.0


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



@st.cache_data(ttl=14400, show_spinner=False)
def fetch_hevy_body_measurements(
    api_key: str,
    page_size: int = 10,
    max_pages: int = 30,
):
    """Fetch Hevy body measurements without modifying the Hevy account."""
    headers = {
        "accept": "application/json",
        "api-key": api_key,
    }

    all_measurements = []

    for page in range(1, max_pages + 1):
        response = requests.get(
            HEVY_BODY_MEASUREMENTS_URL,
            headers=headers,
            params={"page": page, "pageSize": page_size},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("measurements") or payload.get("data") or payload.get("items") or []
        if not rows:
            break
        all_measurements.extend(rows)
        page_count = payload.get("page_count") or payload.get("pageCount") or payload.get("totalPages")
        if page_count and page >= int(page_count):
            break
        if payload.get("has_next") is False or payload.get("hasNext") is False:
            break
    return all_measurements


def normalize_hevy_body_measurements(payload):
    """Return a one-row-per-date table from Hevy body measurements."""
    rows = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        value_type = item.get("type") or item.get("measurement_type") or item.get("name")
        value = item.get("value")
        if value is None:
            value = item.get("value_kg") or item.get("value_cm")
        timestamp = item.get("date") or item.get("timestamp") or item.get("created_at") or item.get("recorded_at")
        if value_type is None or value is None or timestamp is None:
            continue
        parsed = pd.to_datetime(timestamp, errors="coerce", utc=True)
        if pd.isna(parsed):
            continue
        rows.append({
            "date": parsed.tz_convert("Europe/Berlin").date(),
            str(value_type).strip().lower(): pd.to_numeric(value, errors="coerce"),
        })
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return frame.groupby("date", as_index=False).first()


@st.cache_data(ttl=14400, show_spinner=False)
def load_hevy_body_measurements(api_key: str):
    return normalize_hevy_body_measurements(fetch_hevy_body_measurements(api_key))


def flatten_workouts(workouts):
    rows = []

    for w in workouts:
        title = w.get("title", "Workout")
        start_time = w.get("start_time")
        end_time = w.get("end_time")
        description = w.get("description") or ""
        routine_id = w.get("routine_id") or ""

        for exercise_index, ex in enumerate(w.get("exercises", [])):
            exercise_title = ex.get("title", "Unknown exercise")
            exercise_template_id = (
                ex.get("exercise_template_id")
                or ex.get("exerciseTemplateId")
                or ex.get("template_id")
                or ""
            )
            exercise_notes = ex.get("notes") or ""

            for set_index, s in enumerate(ex.get("sets", [])):
                distance_meters = s.get("distance_meters")
                if distance_meters is None:
                    distance_meters = s.get("distanceMeters")
                duration_seconds = s.get("duration_seconds")
                if duration_seconds is None:
                    duration_seconds = s.get("durationSeconds")
                rows.append({
                    "workout_id": w.get("id", ""),
                    "title": title,
                    "description": description,
                    "routine_id": routine_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "exercise_index": exercise_index,
                    "exercise_title": exercise_title,
                    "exercise_template_id": exercise_template_id,
                    "exercise_notes": exercise_notes,
                    "set_index": set_index,
                    "set_type": s.get("type", "normal"),
                    "weight_kg": s.get("weight_kg"),
                    "reps": s.get("reps"),
                    "rpe": s.get("rpe"),
                    "duration_seconds": duration_seconds,
                    "distance_meters": distance_meters,
                })

    return pd.DataFrame(rows)


def normalize_dates(df):
    if df.empty:
        return df

    df = df.copy()
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["end_time"] = pd.to_datetime(df["end_time"], errors="coerce")

    if df["start_time"].dt.tz is not None:
        df["start_time"] = df["start_time"].dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    if df["end_time"].dt.tz is not None:
        df["end_time"] = df["end_time"].dt.tz_convert("Europe/Berlin").dt.tz_localize(None)

    df["date"] = df["start_time"].dt.date
    return df


def _first_existing_column(frame: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def normalize_persistent_workouts(frame: pd.DataFrame) -> pd.DataFrame:
    """Map historical API exports into the current Hevy working-set schema."""
    if frame.empty:
        return frame
    output = frame.copy()
    rename_map = {}
    candidates = {
        "workout_id": ["workout_id", "id"],
        "title": ["title", "workout_title", "workout_name"],
        "description": ["description", "workout_description"],
        "routine_id": ["routine_id"],
        "start_time": ["start_time", "startTime"],
        "end_time": ["end_time", "endTime"],
        "exercise_index": ["exercise_index", "exercise_order"],
        "exercise_title": ["exercise_title", "exercise_name"],
        "exercise_template_id": ["exercise_template_id", "exerciseTemplateId", "template_id"],
        "exercise_notes": ["exercise_notes", "exercise_note", "notes"],
        "set_index": ["set_index", "set_order"],
        "set_type": ["set_type", "type"],
        "weight_kg": ["weight_kg", "weight"],
        "reps": ["reps"],
        "rpe": ["rpe"],
        "duration_seconds": ["duration_seconds", "durationSeconds"],
        "distance_meters": ["distance_meters", "distanceMeters"],
    }
    for canonical, options in candidates.items():
        existing = _first_existing_column(output, options)
        if existing and existing != canonical:
            rename_map[existing] = canonical
    output = output.rename(columns=rename_map)
    defaults = {
        "workout_id": "", "title": "Workout", "description": "", "routine_id": "",
        "exercise_index": pd.NA, "exercise_title": pd.NA, "exercise_template_id": "",
        "exercise_notes": "", "set_index": pd.NA, "set_type": "normal",
        "weight_kg": pd.NA, "reps": pd.NA, "rpe": pd.NA,
        "duration_seconds": pd.NA, "distance_meters": pd.NA,
    }
    for column, default in defaults.items():
        if column not in output.columns:
            output[column] = default
    return output


def load_csv(csv_file):
    if csv_file.exists():
        return pd.read_csv(csv_file)
    return pd.DataFrame()


def merge_workout_frames(current: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    if current.empty:
        return historical.copy()
    if historical.empty:
        return current.copy()
    combined = pd.concat([historical, current], ignore_index=True, sort=False)
    subset = [column for column in ["workout_id", "exercise_index", "set_index"] if column in combined.columns]
    if subset:
        combined = combined.drop_duplicates(subset=subset, keep="last")
    return combined


def load_goal_definitions(path: Path):
    if not path.exists():
        return []
    return pd.read_json(path).to_dict("records")


def load_alias_rules(path: Path):
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict("records")


def contains_any(text, patterns):
    text = str(text).lower()
    return any(pattern.lower() in text for pattern in patterns)


def epley(weight_kg, reps):
    weight_kg = pd.to_numeric(weight_kg, errors="coerce")
    reps = pd.to_numeric(reps, errors="coerce")
    if pd.isna(weight_kg) or pd.isna(reps) or weight_kg <= 0 or reps <= 0 or reps > 12:
        return pd.NA
    return float(weight_kg) * (1 + float(reps) / 30)


def build_exercise_performance_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    prepared = prepare_training_frame(frame)
    prepared = prepared[prepared["exercise_title"].notna()].copy()
    if prepared.empty:
        return pd.DataFrame()
    prepared["start_time"] = pd.to_datetime(prepared["start_time"], errors="coerce")
    prepared["workout_date"] = prepared["start_time"].dt.date
    prepared["best_e1rm_kg"] = prepared.apply(
        lambda row: epley(row.get("weight_kg"), row.get("reps"))
        if not row.get("is_warmup", False) else pd.NA,
        axis=1,
    )
    prepared["working_volume_kg"] = prepared["working_set_volume_kg"]
    group_keys = ["workout_id", "start_time", "workout_date", "exercise_title"]
    output = (
        prepared.groupby(group_keys, dropna=False, as_index=False)
        .agg(
            best_e1rm_kg=("best_e1rm_kg", "max"),
            max_weight_kg=("weight_kg", "max"),
            working_volume_kg=("working_volume_kg", "sum"),
            working_sets=("is_warmup", lambda s: int((~s).sum())),
            reps=("reps", "sum"),
            average_set_rpe=("rpe", "mean"),
        )
        .rename(columns={"exercise_title": "exercise"})
        .sort_values("start_time", ascending=False)
        .reset_index(drop=True)
    )
    for metric, flag in [
        ("max_weight_kg", "weight_pr"),
        ("best_e1rm_kg", "e1rm_pr"),
        ("working_volume_kg", "volume_pr"),
        ("reps", "reps_pr"),
    ]:
        output[flag] = False
        for exercise, group in output.sort_values("start_time").groupby("exercise"):
            running_best = pd.to_numeric(group[metric], errors="coerce").cummax()
            previous_best = running_best.shift(1)
            is_pr = pd.to_numeric(group[metric], errors="coerce") > previous_best
            if not group.empty:
                is_pr.iloc[0] = True
            output.loc[group.index, flag] = is_pr.fillna(False)
    return output


def trend_window(frame: pd.DataFrame, date_column: str, days: int) -> pd.DataFrame:
    if frame.empty or date_column not in frame.columns:
        return frame.copy()
    output = frame.copy()
    output[date_column] = pd.to_datetime(output[date_column], errors="coerce")
    latest = output[date_column].max()
    if pd.isna(latest):
        return output
    return output[output[date_column] >= latest - pd.Timedelta(days=days - 1)].copy()


def progression_label(row):
    delta_weight = pd.to_numeric(row.get("Δ max kg"), errors="coerce")
    delta_volume = pd.to_numeric(row.get("Δ volume %"), errors="coerce")
    current_rpe = pd.to_numeric(row.get("avg set RPE"), errors="coerce")
    previous_rpe = pd.to_numeric(row.get("previous avg RPE"), errors="coerce")
    rpe_change = current_rpe - previous_rpe if pd.notna(current_rpe) and pd.notna(previous_rpe) else 0

    if (pd.notna(delta_weight) and delta_weight > 0) or (
        pd.notna(delta_volume) and delta_volume >= 5 and rpe_change <= 0.5
    ):
        return "Progressed"
    if (
        (pd.isna(delta_weight) or abs(delta_weight) <= 2.5)
        and (pd.isna(delta_volume) or abs(delta_volume) < 10)
    ):
        return "Maintained"
    return "Review"


def recovery_context_row(session, sleep, recovery, steps, nutrition):
    session_date = pd.Timestamp(session["start_time"]).date()
    previous_date = session_date - timedelta(days=1)
    next_date = session_date + timedelta(days=1)

    def value_on(frame, date_value, column):
        if frame.empty or "date" not in frame.columns or column not in frame.columns:
            return pd.NA
        local = frame.copy()
        local["_date"] = pd.to_datetime(local["date"], errors="coerce").dt.date
        values = pd.to_numeric(local.loc[local["_date"] == date_value, column], errors="coerce").dropna()
        return values.iloc[-1] if not values.empty else pd.NA

    sleep_col = "sleep_hours" if "sleep_hours" in sleep.columns else "duration_hours"
    calories_col = "calories_kcal" if "calories_kcal" in nutrition.columns else "calories"
    protein_col = "protein_g"
    rhr_col = "resting_hr"
    hrv_col = "hrv"

    recent_sleep = sleep.copy()
    if not recent_sleep.empty:
        recent_sleep["_date"] = pd.to_datetime(recent_sleep["date"], errors="coerce").dt.date
        recent_sleep = recent_sleep[recent_sleep["_date"] < session_date].sort_values("_date").tail(28)
    recent_recovery = recovery.copy()
    if not recent_recovery.empty:
        recent_recovery["_date"] = pd.to_datetime(recent_recovery["date"], errors="coerce").dt.date
        recent_recovery = recent_recovery[recent_recovery["_date"] < session_date].sort_values("_date").tail(28)
    recent_steps = steps.copy()
    if not recent_steps.empty:
        recent_steps["_date"] = pd.to_datetime(recent_steps["date"], errors="coerce").dt.date
        recent_steps = recent_steps[recent_steps["_date"] < session_date].sort_values("_date").tail(28)
    recent_nutrition = nutrition.copy()
    if not recent_nutrition.empty:
        recent_nutrition["_date"] = pd.to_datetime(recent_nutrition["date"], errors="coerce").dt.date
        recent_nutrition = recent_nutrition[recent_nutrition["_date"] < session_date].sort_values("_date").tail(28)

    result = {
        "Sleep before workout": value_on(sleep, session_date, sleep_col),
        "Sleep 28d baseline": pd.to_numeric(recent_sleep.get(sleep_col), errors="coerce").mean() if not recent_sleep.empty else pd.NA,
        "Resting HR": value_on(recovery, session_date, rhr_col),
        "RHR 28d baseline": pd.to_numeric(recent_recovery.get(rhr_col), errors="coerce").mean() if not recent_recovery.empty else pd.NA,
        "HRV": value_on(recovery, session_date, hrv_col),
        "HRV 28d baseline": pd.to_numeric(recent_recovery.get(hrv_col), errors="coerce").mean() if not recent_recovery.empty else pd.NA,
        "Previous-day calories": value_on(nutrition, previous_date, calories_col),
        "Calories 28d baseline": pd.to_numeric(recent_nutrition.get(calories_col), errors="coerce").mean() if not recent_nutrition.empty else pd.NA,
        "Previous-day protein": value_on(nutrition, previous_date, protein_col),
        "Protein 28d baseline": pd.to_numeric(recent_nutrition.get(protein_col), errors="coerce").mean() if not recent_nutrition.empty else pd.NA,
        "Previous-day steps": value_on(steps, previous_date, "steps"),
        "Steps 28d baseline": pd.to_numeric(recent_steps.get("steps"), errors="coerce").mean() if not recent_steps.empty else pd.NA,
        "Next-day resting HR": value_on(recovery, next_date, rhr_col),
        "Next-day HRV": value_on(recovery, next_date, hrv_col),
    }
    return result


def safe_frame(name, loader, source_status):
    try:
        frame = loader()
        source_status.append({"source": name, "status": "ok", "rows": len(frame)})
        return frame
    except Exception as exc:
        source_status.append({"source": name, "status": "error", "rows": 0, "detail": str(exc)})
        return pd.DataFrame()


def parse_health_date(frame, column="date"):
    if frame.empty or column not in frame.columns:
        return frame
    output = frame.copy()
    output[column] = pd.to_datetime(output[column], errors="coerce")
    return output


def latest_value(frame, column):
    if frame.empty or column not in frame.columns:
        return None
    values = frame.dropna(subset=[column]).sort_values("date")
    return values.iloc[-1][column] if not values.empty else None


def latest_body_metrics(body):
    if body.empty:
        return {}
    output = {}
    for column in ["weight_kg", "body_fat_pct", "fat_mass_kg", "fat_free_mass_kg"]:
        output[column] = latest_value(body, column)
    return output


def withings_body_source(withings_scale: pd.DataFrame) -> pd.DataFrame:
    """Canonical body-composition source for the dashboard.

    Direct Withings measurements are the source of truth for body metrics. Keep
    this transformation narrow so Google Health remains authoritative for
    activity, recovery, sleep, and nutrition without reintroducing duplicate
    body-weight records.
    """
    if withings_scale.empty:
        return pd.DataFrame(columns=["date", "weight_kg", "body_fat_pct", "fat_mass_kg", "fat_free_mass_kg"])

    body = withings_scale.copy()
    keep = [
        column
        for column in [
            "date",
            "weight_kg",
            "body_fat_pct",
            "fat_mass_kg",
            "fat_free_mass_kg",
        ]
        if column in body.columns
    ]
    body = body[keep].copy()
    body["date"] = pd.to_datetime(body["date"], errors="coerce")
    for column in ["weight_kg", "body_fat_pct", "fat_mass_kg", "fat_free_mass_kg"]:
        if column in body.columns:
            body[column] = pd.to_numeric(body[column], errors="coerce")
    return body.sort_values("date").dropna(subset=["date"])


def body_rolling_average(body, days=7):
    if body.empty:
        return body.copy()
    output = body.copy().sort_values("date").set_index("date")
    numeric = output.select_dtypes(include="number").columns
    output[numeric] = output[numeric].rolling(f"{days}D", min_periods=2).mean()
    return output.reset_index()


def display_weight_delta(latest, target=90):
    return f"{latest - target:+.1f} kg to <{target}" if latest is not None else None


def body_proxy_values(body):
    if body.empty:
        return {}
    latest = body.sort_values("date").iloc[-1]
    weight = pd.to_numeric(latest.get("weight_kg"), errors="coerce")
    body_fat = pd.to_numeric(latest.get("body_fat_pct"), errors="coerce")
    fat_mass = pd.to_numeric(latest.get("fat_mass_kg"), errors="coerce")
    ffm = pd.to_numeric(latest.get("fat_free_mass_kg"), errors="coerce")
    if pd.isna(fat_mass) and pd.notna(weight) and pd.notna(body_fat):
        fat_mass = weight * body_fat / 100
    if pd.isna(ffm) and pd.notna(weight) and pd.notna(fat_mass):
        ffm = weight - fat_mass
    return {
        "weight_kg": None if pd.isna(weight) else float(weight),
        "body_fat_pct": None if pd.isna(body_fat) else float(body_fat),
        "fat_mass_kg": None if pd.isna(fat_mass) else float(fat_mass),
        "fat_free_mass_kg": None if pd.isna(ffm) else float(ffm),
    }


def source_caption(source_status):
    if not source_status:
        return
    ok = [item["source"] for item in source_status if item.get("status") == "ok"]
    bad = [item["source"] for item in source_status if item.get("status") != "ok"]
    st.caption("Loaded: " + ", ".join(ok) if ok else "No external sources loaded.")
    if bad:
        st.warning("Unavailable sources: " + ", ".join(bad))


def render_goal_table(progress, category=None):
    view = progress.copy()
    if category:
        view = view[view["category"] == category]
    if view.empty:
        st.info("No configured goals are available for this section.")
        return
    st.dataframe(
        view[["goal", "current_display", "target_display", "status"]],
        use_container_width=True,
        hide_index=True,
    )


def load_goals_data(goal_defs, body, performance_history, endurance, alias_rules, proxy_config=None):
    rows = []
    proxy_config = proxy_config or {}
    body_values = body_proxy_values(body)

    exercise_lookup = {}
    if not performance_history.empty:
        for exercise, group in performance_history.groupby("exercise"):
            exercise_lookup[str(exercise)] = group.sort_values("start_time")

    for goal in goal_defs:
        name = goal.get("name") or goal.get("goal") or "Goal"
        category = goal.get("category", "Other")
        metric = goal.get("metric")
        target = goal.get("target")
        current = None
        status = "Data needed"

        if metric in body_values:
            current = body_values.get(metric)
        elif category == "Strength":
            patterns = [row.get("contains") for row in alias_rules if row.get("goal") == name and row.get("contains")]
            matches = []
            for exercise, group in exercise_lookup.items():
                if contains_any(exercise, patterns):
                    matches.append(group)
            if matches:
                combined = pd.concat(matches).sort_values("start_time")
                current = pd.to_numeric(combined[goal.get("source_column", "best_e1rm_kg")], errors="coerce").dropna().max()
        elif category == "Endurance" and not endurance.empty:
            activity = str(goal.get("activity", "")).lower()
            subset = endurance[endurance["goal_activity"] == activity]
            source_column = goal.get("source_column")
            if not subset.empty and source_column in subset.columns:
                values = pd.to_numeric(subset[source_column], errors="coerce").dropna()
                if not values.empty:
                    current = values.max() if goal.get("direction", "higher") == "higher" else values.min()

        if current is not None and target is not None:
            direction = goal.get("direction", "higher")
            reached = current >= target if direction == "higher" else current <= target
            status = "Goal reached" if reached else "In progress"
            progress_pct = (
                min(current / target * 100, 100)
                if direction == "higher" and target
                else min(target / current * 100, 100)
                if direction == "lower" and current
                else pd.NA
            )
        else:
            progress_pct = pd.NA

        fmt = goal.get("format", "{:.1f}")
        rows.append({
            "category": category,
            "goal": name,
            "current": current,
            "target": target,
            "current_display": fmt.format(current) if current is not None else "—",
            "target_display": fmt.format(target) if target is not None else "—",
            "status": status,
            "progress_pct": progress_pct,
        })

    return pd.DataFrame(rows)


def load_body_composition_proxy(path: Path):
    if not path.exists():
        return {}
    data = pd.read_json(path)
    if isinstance(data, pd.DataFrame):
        return data.to_dict()
    return {}


def renpho_category(body_fat):
    if body_fat is None or pd.isna(body_fat):
        return "—"
    return "Trend only"


def normalize_endurance(endurance):
    if endurance.empty:
        return endurance
    output = endurance.copy()
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    return output.sort_values("date")


def latest_withings_body(withings_scale):
    if withings_scale.empty:
        return {}
    latest = withings_scale.sort_values("date").iloc[-1]
    return latest.to_dict()


def safe_number(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def format_set_table(rows):
    if rows.empty:
        return rows
    display = rows.copy()
    columns = [
        column for column in [
            "exercise_title", "set_index", "set_type", "weight_kg", "reps", "rpe",
            "duration_seconds", "distance_meters",
        ] if column in display.columns
    ]
    display = display[columns]
    if "set_index" in display.columns:
        display["set_index"] = pd.to_numeric(display["set_index"], errors="coerce") + 1
    return display.rename(columns={
        "exercise_title": "Exercise", "set_index": "Set", "set_type": "Type",
        "weight_kg": "Weight kg", "reps": "Reps", "rpe": "RPE",
        "duration_seconds": "Duration sec", "distance_meters": "Distance m",
    })


def load_workout_heart_rate_analysis(start_time, end_time):
    client = GoogleHealthClient.from_streamlit()
    return analyze_workout_heart_rate(client, start_time, end_time)


api_key = get_secret("HEVY_API_KEY")
source_status = []

current_workouts = []
if api_key:
    try:
        current_workouts = fetch_hevy_workouts(api_key, page_size=10, max_pages=20)
        source_status.append({"source": "Hevy API", "status": "ok", "rows": len(current_workouts)})
    except Exception as exc:
        source_status.append({"source": "Hevy API", "status": "error", "rows": 0, "detail": str(exc)})

current_frame = flatten_workouts(current_workouts)
historical_frame = normalize_persistent_workouts(load_csv(DEFAULT_CSV))
df = merge_workout_frames(current_frame, historical_frame)
df = normalize_dates(df)

if not df.empty:
    loaded_from = "Hevy API + saved history" if not current_frame.empty and not historical_frame.empty else "Hevy API" if not current_frame.empty else "saved history"
else:
    loaded_from = "no workout data"

session_summary = build_session_summary(df)
performance_history_all = build_exercise_performance_history(df)
goal_defs = load_goal_definitions(GOALS_PATH)
body_proxy = load_body_composition_proxy(GOALS_PATH)
alias_rules = load_alias_rules(GOAL_ALIASES_PATH)

st.caption(f"Hevy loaded from **{loaded_from}** · Today is treated as a partial day.")

SECTION_OPTIONS = [
    "Overview & Goals",
    "Workout Review",
    "Strength Progress",
    "Fat Loss & Muscle Preservation",
    "Endurance",
    "Body Composition & Nutrition",
    "Recovery & Data Quality",
    "Renpho",
]
selected_section = st.radio(
    "Dashboard section",
    SECTION_OPTIONS,
    horizontal=True,
    label_visibility="collapsed",
    key="dashboard_section",
)

trend_days = st.selectbox("Trend period", [30, 60, 90, 180, 365], index=2)

health_steps = pd.DataFrame()
recovery = pd.DataFrame()
sleep = pd.DataFrame()
nutrition = pd.DataFrame()
body = pd.DataFrame()
endurance = pd.DataFrame()
hevy_measurements = pd.DataFrame()
withings_measurements = pd.DataFrame()
withings_scale = pd.DataFrame()
withings_bp = pd.DataFrame()
renpho_measurements = pd.DataFrame()
grip_measurements = pd.DataFrame()
performance_history = pd.DataFrame()
goal_progress = pd.DataFrame()
body_calc = pd.DataFrame()

if selected_section == "Overview & Goals":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_steps(days=trend_days),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_recovery(days=trend_days),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_sleep(days=trend_days),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_nutrition(days=trend_days),
        source_status,
    )
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=max(365, trend_days)),
        source_status,
    )
    withings_scale = build_withings_scale_sessions(withings_measurements)
    body = withings_body_source(withings_scale)
    performance_history = performance_history_all
    goal_progress = load_goals_data(
        goal_defs,
        body,
        performance_history,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Workout Review":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_steps(days=90),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_recovery(days=90),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_sleep(days=90),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_nutrition(days=90),
        source_status,
    )
    # Workout HR is loaded later only for the selected workout.

elif selected_section == "Strength Progress":
    performance_history = performance_history_all
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=365),
        source_status,
    )
    withings_scale = build_withings_scale_sessions(withings_measurements)
    body = withings_body_source(withings_scale)
    goal_progress = load_goals_data(
        goal_defs,
        body,
        performance_history,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Fat Loss & Muscle Preservation":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_steps(days=90),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_recovery(days=90),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_sleep(days=90),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_nutrition(days=90),
        source_status,
    )
    hevy_measurements = safe_frame(
        "Hevy body measurements",
        lambda: load_hevy_body_measurements(api_key) if api_key else pd.DataFrame(),
        source_status,
    )
    grip_measurements = safe_frame(
        "Grip measurements",
        load_grip_measurements,
        source_status,
    )
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=365),
        source_status,
    )
    withings_scale = build_withings_scale_sessions(withings_measurements)
    body = withings_body_source(withings_scale)
    performance_history = performance_history_all

elif selected_section == "Endurance":
    endurance = safe_frame(
        "Google Health endurance sessions",
        lambda: GoogleHealthClient.from_streamlit().get_endurance_sessions(days=730),
        source_status,
    )
    performance_history = performance_history_all
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=365),
        source_status,
    )
    withings_scale = build_withings_scale_sessions(withings_measurements)
    body = withings_body_source(withings_scale)
    goal_progress = load_goals_data(
        goal_defs,
        body,
        performance_history,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Body Composition & Nutrition":
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_nutrition(days=trend_days),
        source_status,
    )
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=max(365, trend_days)),
        source_status,
    )
    withings_scale = build_withings_scale_sessions(withings_measurements)
    body = withings_body_source(withings_scale)
    goal_progress = load_goals_data(
        goal_defs,
        body,
        performance_history,
        endurance,
        alias_rules,
        proxy_config=body_proxy,
    )

elif selected_section == "Recovery & Data Quality":
    health_steps = safe_frame(
        "Google Health steps",
        lambda: load_steps(days=max(14, trend_days)),
        source_status,
    )
    recovery = safe_frame(
        "Google Health recovery",
        lambda: load_recovery(days=max(14, trend_days)),
        source_status,
    )
    sleep = safe_frame(
        "Google Health sleep",
        lambda: load_sleep(days=max(14, trend_days)),
        source_status,
    )
    nutrition = safe_frame(
        "Cronometer nutrition",
        lambda: load_nutrition(days=max(14, trend_days)),
        source_status,
    )
    withings_measurements = safe_frame(
        "Withings health metrics",
        lambda: load_withings_dashboard_measurements(days=max(365, trend_days)),
        source_status,
    )
    withings_bp = build_withings_bp_sessions(withings_measurements)

elif selected_section == "Renpho":
    renpho_measurements = safe_frame(
        "Renpho monthly measurements",
        load_renpho_measurements,
        source_status,
    )


if selected_section == "Overview & Goals":
    st.header("Current overview")
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    week_start = today - timedelta(days=7)

    latest_weight = latest_value(body, "weight_kg")
    latest_fat = latest_value(body, "body_fat_pct")
    latest_bpm = latest_value(recovery, "resting_hr")
    latest_hrv = latest_value(recovery, "hrv")
    latest_sleep = latest_value(sleep, "sleep_hours")
    latest_steps = latest_value(health_steps, "steps")

    top = st.columns(6)
    top[0].metric("Weight", f"{latest_weight:.2f} kg" if latest_weight is not None else "—", display_weight_delta(latest_weight))
    top[1].metric("Body fat", f"{latest_fat:.1f}%" if latest_fat is not None else "—", f"{latest_fat - 15:+.1f} pp to <15%" if latest_fat is not None else None, delta_color="inverse")
    top[2].metric("Resting HR", f"{latest_bpm:.0f} bpm" if latest_bpm is not None else "—")
    top[3].metric("HRV", f"{latest_hrv:.1f} ms" if latest_hrv is not None else "—")
    top[4].metric("Sleep", f"{latest_sleep:.2f} h" if latest_sleep is not None else "—")
    top[5].metric("Steps", f"{latest_steps:,.0f}" if latest_steps is not None else "—")

    seven_start = today - timedelta(days=6)
    body_7 = body[pd.to_datetime(body["date"], errors="coerce").dt.date >= seven_start] if not body.empty else pd.DataFrame()
    steps_7 = health_steps[pd.to_datetime(health_steps["date"], errors="coerce").dt.date >= seven_start] if not health_steps.empty else pd.DataFrame()
    sleep_7 = sleep[pd.to_datetime(sleep["date"], errors="coerce").dt.date >= seven_start] if not sleep.empty else pd.DataFrame()
    food_7 = nutrition[pd.to_datetime(nutrition["date"], errors="coerce").dt.date >= seven_start] if not nutrition.empty else pd.DataFrame()

    row2 = st.columns(4)
    row2[0].metric(
        "7-day steps",
        f"{steps_7['steps'].mean():,.0f}" if not steps_7.empty else "—",
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
        st.subheader(f"Latest {trend_days} days — activity")
        if health_steps.empty:
            st.info("No step data available.")
        else:
            fig = px.bar(
                trend_window(health_steps, "date", trend_days),
                x="date",
                y="steps",
                labels={"date": "Date", "steps": "Steps"},
            )
            fig.add_hline(y=7000, line_dash="dash", annotation_text="7,000 floor")
            fig.add_hline(y=8000, line_dash="dot", annotation_text="8,000 preferred")
            fig.update_layout(height=320, xaxis_tickformat="%d %b")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader(f"Latest {trend_days} days — training load")
        if session_summary.empty:
            st.info("No session-load history available.")
        else:
            load_chart = session_summary.dropna(subset=["session_load"]).copy()
            load_chart = trend_window(load_chart.sort_values("start_time"), "start_time", trend_days)
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
    performance_history = trend_window(performance_history, "start_time", trend_days)
    if performance_history.empty:
        st.info("No working-set performance history is available.")
    else:
        exercises = sorted(performance_history["exercise"].dropna().astype(str).unique())
        selected_exercise = st.selectbox("Exercise", exercises)
        history = performance_history[
            performance_history["exercise"] == selected_exercise
        ].sort_values("start_time")

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
        cards[4].metric("Average set RPE", f"{latest['average_set_rpe']:.1f}" if pd.notna(latest['average_set_rpe']) else "—")

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
        activity = trend_window(activity, "date", trend_days)

        st.subheader(f"{activity_labels[selected_activity]} summary — last {trend_days} days")

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
                    else pd.NA
                )
            elif selected_activity == "swim":
                performance_valid["performance_value"] = (
                    performance_valid["duration_hours"] * 3600
                    / (performance_valid["distance_km"] * 10)
                )
                performance_label = "Pace (sec/100m)"
                best_value = (
                    performance_valid["performance_value"].min()
                    if not performance_valid.empty
                    else pd.NA
                )
            else:
                performance_valid["performance_value"] = (
                    performance_valid["distance_km"]
                    / performance_valid["duration_hours"]
                )
                performance_label = "Speed (km/h)"
                best_value = (
                    performance_valid["performance_value"].max()
                    if not performance_valid.empty
                    else pd.NA
                )

            cards = st.columns(5)
            cards[0].metric("Sessions", f"{len(activity)}")
            cards[1].metric(
                "Distance",
                f"{activity['distance_km'].sum():.1f} km"
                if not activity["distance_km"].dropna().empty
                else "—",
            )
            cards[2].metric(
                "Time",
                f"{activity['duration_hours'].sum():.1f} h"
                if not activity["duration_hours"].dropna().empty
                else "—",
            )
            cards[3].metric(
                "Longest",
                f"{distance_valid['distance_km'].max():.2f} km"
                if not distance_valid.empty
                else "—",
            )
            cards[4].metric(
                "Best " + performance_label,
                f"{best_value:.2f}" if pd.notna(best_value) else "—",
            )

            left, right = st.columns(2)
            with left:
                if performance_valid.empty:
                    st.info("No comparable distance/time performance data is available.")
                else:
                    perf_fig = px.line(
                        performance_valid,
                        x="date",
                        y="performance_value",
                        markers=True,
                        labels={"date": "Date", "performance_value": performance_label},
                    )
                    perf_fig.update_layout(
                        height=320,
                        xaxis_tickformat="%d %b",
                    )
                    st.plotly_chart(perf_fig, use_container_width=True)
            with right:
                hr_view = activity.dropna(subset=["average_hr"])
                if hr_view.empty:
                    st.info("No average-heart-rate history is available for these sessions.")
                else:
                    hr_fig = px.line(
                        hr_view,
                        x="date",
                        y="average_hr",
                        markers=True,
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

elif selected_section == "Fat Loss & Muscle Preservation":
    st.header("Fat Loss & Muscle Preservation")
    st.caption(
        "Goal: reduce fat mass while preserving useful lean tissue and strength. "
        "Direct Withings supplies body composition, Cronometer supplies intake, "
        "Google Health supplies recovery/activity, and Hevy supplies strength and waist data."
    )

    canonical_snapshot = {}
    try:
        canonical_snapshot = load_latest_coaching_snapshot() or {}
    except Exception as exc:
        st.caption(f"Canonical weekly coaching snapshot is temporarily unavailable: {exc}")

    recomp = build_recomposition_summary(
        withings_scale=withings_scale,
        nutrition=nutrition,
        sleep=sleep,
        steps=health_steps,
        hevy_measurements=hevy_measurements,
        performance_history=performance_history,
    )
    summary = recomp.get("summary", {})
    analysis_end = recomp.get("analysis_end_date")

    if analysis_end is None:
        st.info("Not enough overlapping body-composition and nutrition data is available yet.")
    else:
        st.caption(f"Latest complete analysis date: {analysis_end.strftime('%d %b %Y')}")

        if canonical_snapshot:
            st.subheader("Canonical coaching status")
            st.caption(
                "This is the authoritative weekly interpretation shared with the email system. "
                "The live charts below remain exploratory views of the underlying measurements."
            )
            cstates = canonical_snapshot.get("states", {})
            cdecision = canonical_snapshot.get("decision", {})
            cenergy = canonical_snapshot.get("energy", {})
            ccols = st.columns(6)
            ccols[0].metric("Fat loss", str(cstates.get("fat_loss", "—")).replace("_", " ").title())
            ccols[1].metric("Muscle preservation", str(cstates.get("muscle_preservation", "—")).replace("_", " ").title())
            ccols[2].metric("Recovery", str(cstates.get("recovery", "—")).replace("_", " ").title())
            ccols[3].metric("Training", str(cstates.get("training", "—")).replace("_", " ").title())
            ccols[4].metric(
                "Calorie action",
                f"{str(cdecision.get('action', 'HOLD')).title()} {float(cdecision.get('calorie_adjustment') or 0):+.0f}",
                f"Target {float(cdecision.get('target_intake')):.0f} kcal/day" if cdecision.get("target_intake") is not None else None,
            )
            ccols[5].metric(
                "Planning maintenance",
                f"{float(cenergy.get('planning_tdee')):,.0f} kcal/day" if cenergy.get("planning_tdee") is not None else "—",
                (f"{float(cenergy.get('planning_range_low')):,.0f}-{float(cenergy.get('planning_range_high')):,.0f}"
                 if cenergy.get("planning_range_low") is not None and cenergy.get("planning_range_high") is not None else None),
            )
            priorities = canonical_snapshot.get("priorities", []) or []
            if priorities:
                st.markdown("**Current priorities:** " + " · ".join(str(item) for item in priorities))
            training_groups = canonical_snapshot.get("training_dose", {}).get("groups", []) or []
            if training_groups:
                with st.expander("Canonical training dose by primary muscle group"):
                    dose = pd.DataFrame(training_groups)
                    dose = dose[dose["muscle_group"] != "Other / unmapped"] if "muscle_group" in dose.columns else dose
                    st.dataframe(dose, use_container_width=True, hide_index=True)
                    st.caption(canonical_snapshot.get("training_dose", {}).get("method", ""))

        cards = st.columns(6)
        cards[0].metric(
            "Weight change in 28d window",
            f"{summary.get('weight_change_28d'):+.2f} kg"
            if summary.get("weight_change_28d") is not None else "—",
        )
        cards[1].metric(
            "Fat-mass change in 28d window",
            f"{summary.get('fat_change_28d'):+.2f} kg"
            if summary.get("fat_change_28d") is not None else "—",
        )
        cards[2].metric(
            "FFM change in 28d window",
            f"{summary.get('ffm_change_28d'):+.2f} kg"
            if summary.get("ffm_change_28d") is not None else "—",
        )
        cards[3].metric(
            "Loss pace",
            f"{summary.get('weight_loss_pct_week'):.2f}% / week"
            if summary.get("weight_loss_pct_week") is not None else "—",
        )
        cards[4].metric(
            "7d protein",
            f"{summary.get('protein_7'):.0f} g/day"
            if summary.get("protein_7") is not None else "—",
        )
        cards[5].metric(
            "Rolling maintenance",
            f"{summary.get('estimated_tdee'):,.0f} kcal/day"
            if summary.get("estimated_tdee") is not None else "—",
        )

        second = st.columns(5)
        second[0].metric(
            "Estimated deficit",
            f"{summary.get('estimated_deficit'):,.0f} kcal/day"
            if summary.get("estimated_deficit") is not None else "—",
        )
        canonical_adherence = canonical_snapshot.get("adherence", {}) if canonical_snapshot else {}
        protein_logged = canonical_adherence.get("protein_days_logged", 0)
        protein_met = canonical_adherence.get("protein_days_met", 0)
        second[1].metric(
            "Protein target days",
            f"{protein_met}/{protein_logged}" if protein_logged else "—",
        )
        waist_span = summary.get("waist_span_days")
        second[2].metric(
            f"Waist change ({waist_span}d)" if waist_span is not None else "Waist change",
            f"{summary.get('waist_change_28d'):+.1f} cm"
            if summary.get("waist_change_28d") is not None else "—",
        )
        second[3].metric(
            "28d sleep",
            f"{summary.get('sleep_28'):.1f} h/night"
            if summary.get("sleep_28") is not None else "—",
        )
        second[4].metric(
            "28d steps",
            f"{summary.get('steps_28'):,.0f}/day"
            if summary.get("steps_28") is not None else "—",
        )

        if summary.get("fat_share_of_loss_pct") is not None:
            st.caption(
                f"Experimental BIA-derived fat share of scale loss: ~{summary.get('fat_share_of_loss_pct'):.0f}%. "
                "This is supporting context only because both fat and fat-free compartments are hydration-sensitive."
            )

        low = summary.get("protein_low")
        high = summary.get("protein_high")
        if low is not None and high is not None:
            st.caption(
                f"Current protein working range: about {low:.0f}-{high:.0f} g/day "
                "(1.8-2.2 g/kg of current estimated fat-free mass)."
            )

        st.subheader("What the combined signals say")
        interpretations = (canonical_snapshot.get("interpretation", []) if canonical_snapshot else []) or recomp.get("interpretation", [])
        if interpretations:
            for item in interpretations:
                st.markdown(f"- {item}")
        else:
            st.info("Not enough data is available for a combined interpretation yet.")

        body_trend = recomp.get("body_trend", pd.DataFrame()).copy()
        if not body_trend.empty:
            body_trend = trend_window(body_trend, "date", max(90, trend_days))
            chart_columns = [
                column
                for column in [
                    "weight_kg_7d_median",
                    "fat_mass_kg_7d_median",
                    "fat_free_mass_kg_7d_median",
                ]
                if column in body_trend.columns
            ]
            if chart_columns:
                st.subheader("Smoothed body-composition trends")
                chart = body_trend.melt(
                    id_vars="date",
                    value_vars=chart_columns,
                    var_name="metric",
                    value_name="kg",
                )
                chart["metric"] = chart["metric"].map(
                    {
                        "weight_kg_7d_median": "Weight — 7d median",
                        "fat_mass_kg_7d_median": "Fat mass — 7d median",
                        "fat_free_mass_kg_7d_median": "Fat-free mass — 7d median",
                    }
                )
                fig = px.line(chart, x="date", y="kg", color="metric", markers=True)
                fig.update_layout(height=420, xaxis_tickformat="%d %b %Y")
                st.plotly_chart(fig, use_container_width=True)

        canonical_lifts = canonical_snapshot.get("strength", {}).get("lifts", []) if canonical_snapshot else []
        if canonical_lifts:
            strength = pd.DataFrame(canonical_lifts).rename(columns={
                "label": "Lift",
                "current_best_e1rm": "Current 4w best e1RM",
                "prior_best_e1rm": "Prior 4w best e1RM",
                "change_e1rm": "Change kg",
                "direction": "Direction",
                "current_observations": "Current observations",
                "prior_observations": "Prior observations",
            })
            keep = [
                "Lift", "Current 4w best e1RM", "Prior 4w best e1RM", "Change kg",
                "Direction", "Current observations", "Prior observations",
            ]
            strength = strength[[c for c in keep if c in strength.columns]]
        else:
            strength = recomp.get("strength", pd.DataFrame()).copy()
        st.subheader("4-week strength cross-check")
        if strength.empty:
            st.info("Not enough like-for-like core-lift observations exist in both four-week windows yet.")
        else:
            strength_display = strength.copy()
            for column in ["Current 4w best e1RM", "Prior 4w best e1RM", "Change kg"]:
                strength_display[column] = pd.to_numeric(
                    strength_display[column], errors="coerce"
                ).round(1)
            st.dataframe(strength_display, use_container_width=True, hide_index=True)
            if canonical_lifts:
                canonical_strength = canonical_snapshot.get("strength", {})
                st.caption(
                    f"Comparable lifts: {canonical_strength.get('up', 0)} up, "
                    f"{canonical_strength.get('flat', 0)} flat, "
                    f"{canonical_strength.get('down', 0)} down."
                )
            else:
                st.caption(
                    f"Comparable lifts: {summary.get('strength_up', 0)} up, "
                    f"{summary.get('strength_flat', 0)} flat, "
                    f"{summary.get('strength_down', 0)} down."
                )

        waist = recomp.get("waist", pd.DataFrame()).copy()
        if not waist.empty:
            st.subheader("Waist trend")
            waist_view = trend_window(waist, "date", max(180, trend_days))
            fig = px.line(
                waist_view,
                x="date",
                y="waist_cm",
                markers=True,
                labels={"date": "Date", "waist_cm": "Waist (cm)"},
            )
            fig.update_layout(height=330, xaxis_tickformat="%d %b %Y")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Grip strength")
        st.caption(
            "Grip is an additional functional strength signal independent of Withings BIA. "
            "For comparability, use the same device/handle setting and similar posture each time; "
            "three maximal attempts per hand are stored and the best attempt is charted."
        )

        with st.expander("Add grip-strength measurement", expanded=grip_measurements.empty):
            grip_now = datetime.now(ZoneInfo("Europe/Berlin"))
            with st.form("grip_measurement_form", clear_on_submit=False):
                gdate, gtime, dominant = st.columns([1, 1, 1])
                measured_date = gdate.date_input("Measurement date", value=grip_now.date())
                measured_time = gtime.time_input(
                    "Measurement time",
                    value=grip_now.replace(second=0, microsecond=0).time(),
                )
                dominant_hand = dominant.selectbox(
                    "Dominant hand",
                    ["Right", "Left", "Ambidextrous / not specified"],
                )

                left_col, right_col = st.columns(2)
                with left_col:
                    st.markdown("**Left hand — kg**")
                    left_1 = st.number_input("Left attempt 1", min_value=0.0, value=0.0, step=0.1)
                    left_2 = st.number_input("Left attempt 2", min_value=0.0, value=0.0, step=0.1)
                    left_3 = st.number_input("Left attempt 3", min_value=0.0, value=0.0, step=0.1)
                with right_col:
                    st.markdown("**Right hand — kg**")
                    right_1 = st.number_input("Right attempt 1", min_value=0.0, value=0.0, step=0.1)
                    right_2 = st.number_input("Right attempt 2", min_value=0.0, value=0.0, step=0.1)
                    right_3 = st.number_input("Right attempt 3", min_value=0.0, value=0.0, step=0.1)
                grip_notes = st.text_input(
                    "Notes (optional)",
                    placeholder="e.g. before workout, same handle setting, rested",
                )
                grip_submit = st.form_submit_button("Save grip measurement", type="primary")

            if grip_submit:
                try:
                    insert_grip_measurement(
                        measured_date=measured_date,
                        measured_time=measured_time,
                        dominant_hand=dominant_hand,
                        left_attempts=[left_1, left_2, left_3],
                        right_attempts=[right_1, right_2, right_3],
                        notes=grip_notes,
                    )
                    st.success("Grip-strength measurement saved.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save grip-strength measurement: {exc}")

        if grip_measurements.empty:
            st.info("No grip-strength measurements have been saved yet.")
        else:
            grip_view = grip_measurements.sort_values("measured_at").copy()
            latest_grip = grip_view.iloc[-1]
            grip_cards = st.columns(4)
            grip_cards[0].metric(
                "Best left",
                f"{latest_grip['best_left_kg']:.1f} kg"
                if pd.notna(latest_grip.get("best_left_kg")) else "—",
            )
            grip_cards[1].metric(
                "Best right",
                f"{latest_grip['best_right_kg']:.1f} kg"
                if pd.notna(latest_grip.get("best_right_kg")) else "—",
            )
            grip_cards[2].metric(
                "Best overall",
                f"{latest_grip['best_overall_kg']:.1f} kg"
                if pd.notna(latest_grip.get("best_overall_kg")) else "—",
            )
            grip_cards[3].metric(
                "L/R asymmetry",
                f"{latest_grip['asymmetry_pct']:.1f}%"
                if pd.notna(latest_grip.get("asymmetry_pct")) else "—",
            )

            grip_chart = grip_view.melt(
                id_vars="measured_at",
                value_vars=["best_left_kg", "best_right_kg"],
                var_name="hand",
                value_name="kg",
            )
            grip_chart["hand"] = grip_chart["hand"].map(
                {"best_left_kg": "Left", "best_right_kg": "Right"}
            )
            fig = px.line(
                grip_chart,
                x="measured_at",
                y="kg",
                color="hand",
                markers=True,
                labels={"measured_at": "Date", "kg": "Grip strength (kg)", "hand": "Hand"},
            )
            fig.update_layout(height=330, xaxis_tickformat="%d %b %Y")
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Grip measurement history / corrections"):
                display_cols = [
                    "measurement_id", "measured_at", "best_left_kg", "best_right_kg",
                    "avg_left_kg", "avg_right_kg", "asymmetry_pct", "dominant_hand", "notes",
                ]
                st.dataframe(
                    grip_view[[c for c in display_cols if c in grip_view.columns]].sort_values(
                        "measured_at", ascending=False
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                delete_options = grip_view.sort_values("measured_at", ascending=False).copy()
                delete_options["label"] = delete_options.apply(
                    lambda row: (
                        f"#{int(row['measurement_id'])} · "
                        f"{pd.Timestamp(row['measured_at']).strftime('%d %b %Y %H:%M')} · "
                        f"L {row['best_left_kg']:.1f} / R {row['best_right_kg']:.1f} kg"
                    ),
                    axis=1,
                )
                delete_label = st.selectbox(
                    "Delete an incorrect grip record",
                    delete_options["label"].tolist(),
                    key="grip_delete_record",
                )
                if st.button("Delete selected grip record", key="grip_delete_button"):
                    measurement_id = int(
                        delete_options.loc[
                            delete_options["label"] == delete_label, "measurement_id"
                        ].iloc[0]
                    )
                    try:
                        delete_grip_measurement(measurement_id)
                        st.success("Grip-strength record deleted.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not delete grip-strength record: {exc}")

        with st.expander("Method and limitations"):
            st.markdown(
                "- **Fat-free mass is not the same as muscle.** Withings BIA can move with hydration and glycogen, so the dashboard cross-checks it against strength and waist.\n"
                "- **Rolling maintenance/TDEE is experimental.** It combines logged calorie intake with the 28-day scale-weight trend using 7,700 kcal/kg as an energy-balance approximation. Water shifts and food-logging error can materially move it.\n"
                "- **Protein range is a coaching target, not a medical prescription.** The current working range is 1.8-2.2 g/kg of estimated fat-free mass during the cut.\n"
                f"- Energy-balance coverage confidence: **{summary.get('coverage_confidence', 'LOW')}** "
                f"({summary.get('calorie_days', 0)} nutrition days; {summary.get('weight_days', 0)} weight days)."
            )

elif selected_section == "Body Composition & Nutrition":
    st.header("Body composition and nutrition")

    st.subheader("Overall Health Trends")
    st.caption(
        "Direct Withings is the source of truth for the body metrics shown here. "
        "Google Health remains the source for non-Withings health metrics elsewhere."
    )

    latest_weight = latest_value(body, "weight_kg")
    latest_fat = latest_value(body, "body_fat_pct")
    direct_muscle_pct = latest_withings_value(
        withings_scale, "muscle_mass_pct"
    )
    water_pct = latest_withings_value(
        withings_scale, "water_pct"
    )
    visceral = latest_withings_value(
        withings_scale, "visceral_fat_index"
    )
    metabolic_age = latest_withings_value(
        withings_scale, "metabolic_age_years"
    )

    health_cards = st.columns(6)
    health_cards[0].metric(
        "Weight",
        f"{latest_weight:.2f} kg" if latest_weight is not None else "—",
        f"{latest_weight - 90:+.1f} kg to <90"
        if latest_weight is not None else None,
        delta_color="inverse",
    )
    health_cards[1].metric(
        "Body fat %",
        f"{latest_fat:.2f}%" if latest_fat is not None else "—",
        f"{latest_fat - 15:+.1f} pp to <15%"
        if latest_fat is not None else None,
        delta_color="inverse",
    )
    health_cards[2].metric(
        "Muscle mass %",
        f"{direct_muscle_pct:.2f}%"
        if direct_muscle_pct is not None else "—",
    )
    health_cards[3].metric(
        "Water %",
        f"{water_pct:.1f}%" if water_pct is not None else "—",
    )
    health_cards[4].metric(
        "Visceral fat",
        f"{visceral:.1f}" if visceral is not None else "—",
    )
    health_cards[5].metric(
        "Metabolic age",
        f"{metabolic_age:.0f} years"
        if metabolic_age is not None else "—",
    )

    weight_view = trend_window(
        body.dropna(subset=["weight_kg"])[["date", "weight_kg"]],
        "date",
        trend_days,
    ) if not body.empty and "weight_kg" in body.columns else pd.DataFrame()
    fat_view = trend_window(
        body.dropna(subset=["body_fat_pct"])[["date", "body_fat_pct"]],
        "date",
        trend_days,
    ) if not body.empty and "body_fat_pct" in body.columns else pd.DataFrame()

    withings_views = {}
    for label, column, unit in [
        ("Water %", "water_pct", "%"),
    ]:
        if not withings_scale.empty and column in withings_scale.columns:
            frame = withings_scale[["date", column]].dropna(subset=[column]).copy()
            frame = trend_window(frame, "date", trend_days)
        else:
            frame = pd.DataFrame()
        withings_views[label] = (frame, column, unit)

    if (
        weight_view.empty
        and fat_view.empty
        and all(frame.empty for frame, _, _ in withings_views.values())
    ):
        st.info("No overall health trend data is available for the selected period.")
    else:
        overall_fig = make_subplots(
            specs=[[{"secondary_y": True}]]
        )

        if not fat_view.empty:
            overall_fig.add_trace(
                go.Scatter(
                    x=fat_view["date"],
                    y=fat_view["body_fat_pct"],
                    mode="lines+markers",
                    name="Body fat %",
                    line={"width": 2},
                    marker={"size": 4},
                    legendrank=2,
                ),
                secondary_y=True,
            )

        water_frame, water_column, _ = withings_views["Water %"]
        if not water_frame.empty:
            overall_fig.add_trace(
                go.Scatter(
                    x=water_frame["date"],
                    y=water_frame[water_column],
                    mode="lines+markers",
                    name="Water %",
                    line={"width": 2},
                    marker={"size": 4},
                    legendrank=3,
                ),
                secondary_y=True,
            )

        if not weight_view.empty:
            overall_fig.add_trace(
                go.Scatter(
                    x=weight_view["date"],
                    y=weight_view["weight_kg"],
                    mode="lines+markers",
                    name="Weight (kg)",
                    line={"width": 4},
                    marker={"size": 6},
                    legendrank=1,
                ),
                secondary_y=False,
            )

        overall_fig.add_hline(
            y=90,
            line_dash="dash",
            annotation_text="90 kg target",
            secondary_y=False,
        )
        overall_fig.add_hline(
            y=15,
            line_dash="dot",
            annotation_text="15% body-fat target",
            secondary_y=True,
        )

        weight_values = pd.to_numeric(weight_view["weight_kg"], errors="coerce").dropna()
        if not weight_values.empty:
            weight_low = float(weight_values.min())
            weight_high = float(weight_values.max())
            overall_fig.update_yaxes(
                title_text="Weight (kg)",
                range=[min(88.0, weight_low - 1.5), weight_high + 2.0],
                secondary_y=False,
            )
        else:
            overall_fig.update_yaxes(
                title_text="Weight (kg)",
                secondary_y=False,
            )
        overall_fig.update_yaxes(
            title_text="Body fat / Water (%)",
            range=[0, 90],
            secondary_y=True,
        )
        overall_fig.update_layout(
            height=440,
            xaxis_tickformat="%d %b %Y",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        )
        st.plotly_chart(overall_fig, use_container_width=True)

    st.subheader("Advanced Withings body composition")
    advanced_metrics = [
        ("Fat mass", "fat_mass_kg", "kg"),
        ("Muscle mass", "muscle_mass_kg", "kg"),
        ("Fat-free mass", "fat_free_mass_kg", "kg"),
        ("BMR", "bmr_kcal_day", "kcal/day"),
    ]
    advanced_cards = st.columns(len(advanced_metrics))
    for card, (label, column, unit) in zip(advanced_cards, advanced_metrics):
        value = latest_withings_value(withings_scale, column)
        card.metric(
            label,
            f"{value:.1f} {unit}" if value is not None else "—",
        )

    numeric_metric_columns = [
        column
        for column in withings_scale.columns
        if column != "date"
        and pd.api.types.is_numeric_dtype(withings_scale[column])
        and withings_scale[column].notna().any()
    ]
    if numeric_metric_columns:
        selected_metric = st.selectbox(
            "Explore any direct Withings metric",
            sorted(numeric_metric_columns),
            key="advanced_withings_metric",
        )
        metric_view = withings_scale[["date", selected_metric]].dropna()
        metric_view = trend_window(metric_view, "date", trend_days)
        if not metric_view.empty:
            fig = px.line(
                metric_view,
                x="date",
                y=selected_metric,
                markers=True,
                labels={"date": "Date", selected_metric: selected_metric.replace("_", " ").title()},
            )
            fig.update_layout(height=330, xaxis_tickformat="%d %b")
            st.plotly_chart(fig, use_container_width=True)

    if not nutrition.empty:
        nutrition_view = trend_window(nutrition, "date", trend_days)
        nutrition_cards = st.columns(4)
        nutrition_cards[0].metric("Avg calories", f"{nutrition_view['calories_kcal'].mean():,.0f} kcal")
        nutrition_cards[1].metric("Avg protein", f"{nutrition_view['protein_g'].mean():.0f} g")
        nutrition_cards[2].metric("Avg carbs", f"{nutrition_view['carbs_g'].mean():.0f} g" if "carbs_g" in nutrition_view.columns else "—")
        nutrition_cards[3].metric("Avg fat", f"{nutrition_view['fat_g'].mean():.0f} g" if "fat_g" in nutrition_view.columns else "—")

        macros = nutrition_view.melt(
            id_vars="date",
            value_vars=[column for column in ["protein_g", "carbs_g", "fat_g"] if column in nutrition_view.columns],
            var_name="Macro",
            value_name="grams",
        )
        if not macros.empty:
            fig = px.line(macros, x="date", y="grams", color="Macro", markers=True)
            fig.update_layout(height=350, xaxis_tickformat="%d %b")
            st.plotly_chart(fig, use_container_width=True)

elif selected_section == "Recovery & Data Quality":
    st.header("Recovery and data quality")

    st.subheader("Daily recovery")
    recovery_display = recovery.merge(sleep, on="date", how="outer") if not recovery.empty and not sleep.empty else recovery if not recovery.empty else sleep
    if recovery_display.empty:
        st.info("No recovery data available.")
    else:
        recovery_display = trend_window(recovery_display, "date", trend_days)
        recovery_columns = [column for column in ["resting_hr", "hrv", "sleep_hours"] if column in recovery_display.columns]
        if recovery_columns:
            recovery_long = recovery_display.melt(
                id_vars="date",
                value_vars=recovery_columns,
                var_name="metric",
                value_name="value",
            )
            fig = px.line(recovery_long, x="date", y="value", color="metric", markers=True)
            fig.update_layout(height=390, xaxis_tickformat="%d %b")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Blood pressure")
    if withings_bp.empty:
        st.info("No direct Withings blood-pressure history is available.")
    else:
        bp_view = trend_window(withings_bp, "date", trend_days)
        bp_chart = bp_view.melt(
            id_vars="date",
            value_vars=[column for column in ["systolic_bp", "diastolic_bp"] if column in bp_view.columns],
            var_name="metric",
            value_name="mmHg",
        )
        fig = px.line(bp_chart, x="date", y="mmHg", color="metric", markers=True)
        fig.update_layout(height=350, xaxis_tickformat="%d %b")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Data source status")
    st.dataframe(pd.DataFrame(source_status), use_container_width=True, hide_index=True)

elif selected_section == "Renpho":
    st.header("Renpho monthly check-in")
    st.caption("This tab is intentionally separate from your Withings source of truth. Use it for occasional friend-scale measurements without mixing them into your primary body-composition trend.")

    with st.expander("Add Renpho measurement", expanded=renpho_measurements.empty):
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        with st.form("renpho_form"):
            c1, c2 = st.columns(2)
            renpho_date = c1.date_input("Date", value=now.date())
            renpho_time = c2.time_input("Time", value=now.replace(second=0, microsecond=0).time())
            r1, r2, r3 = st.columns(3)
            renpho_weight = r1.number_input("Weight kg", min_value=0.0, value=0.0, step=0.1)
            renpho_fat = r2.number_input("Body fat %", min_value=0.0, value=0.0, step=0.1)
            renpho_muscle = r3.number_input("Muscle mass kg", min_value=0.0, value=0.0, step=0.1)
            renpho_notes = st.text_input("Notes")
            renpho_submit = st.form_submit_button("Save Renpho measurement", type="primary")
        if renpho_submit:
            try:
                insert_renpho_measurement(
                    measured_date=renpho_date,
                    measured_time=renpho_time,
                    weight_kg=renpho_weight or None,
                    body_fat_pct=renpho_fat or None,
                    muscle_mass_kg=renpho_muscle or None,
                    notes=renpho_notes,
                )
                st.success("Renpho measurement saved.")
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save Renpho measurement: {exc}")

    if renpho_measurements.empty:
        st.info("No Renpho measurements have been saved yet.")
    else:
        renpho = renpho_measurements.sort_values("measured_at").copy()
        latest = renpho.iloc[-1]
        cards = st.columns(3)
        cards[0].metric("Latest weight", f"{latest['weight_kg']:.2f} kg" if pd.notna(latest['weight_kg']) else "—")
        cards[1].metric("Latest body fat", f"{latest['body_fat_pct']:.1f}%" if pd.notna(latest['body_fat_pct']) else "—")
        cards[2].metric("Latest muscle mass", f"{latest['muscle_mass_kg']:.1f} kg" if pd.notna(latest['muscle_mass_kg']) else "—")

        st.dataframe(
            renpho.sort_values("measured_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        delete_options = renpho.sort_values("measured_at", ascending=False).copy()
        delete_options["label"] = delete_options.apply(
            lambda row: f"#{int(row['measurement_id'])} · {pd.Timestamp(row['measured_at']).strftime('%d %b %Y %H:%M')}",
            axis=1,
        )
        selected_delete = st.selectbox("Delete incorrect Renpho record", delete_options["label"].tolist())
        if st.button("Delete selected Renpho record"):
            measurement_id = int(delete_options.loc[delete_options["label"] == selected_delete, "measurement_id"].iloc[0])
            try:
                delete_renpho_measurement(measurement_id)
                st.success("Renpho record deleted.")
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete Renpho record: {exc}")

source_caption(source_status)

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from hevy_training_load import prepare_training_frame


NOTE_PATTERNS = {
    "Pain/discomfort": re.compile(
        r"(?i)\b(pain|painful|hurt|hurts|sore|ache|aching|tweak|twinge)\b"
    ),
    "Fatigue/environment": re.compile(
        r"(?i)\b(tired|fatigue|fatigued|hot|exhausted|rough|barely|pause|all i had|all i could)\b"
    ),
    "Technique/balance": re.compile(
        r"(?i)\b(stance|form|technique|balance|unbalanced|practice|range)\b"
    ),
    "Equipment/setup": re.compile(
        r"(?i)\b(belt|strap|straps|chalk|grip)\b"
    ),
    "Positive/readiness": re.compile(
        r"(?i)\b(more left|left in the tank|go up|easier|fine|good|no issue|just right)\b"
    ),
}


def _first_nonempty(series: pd.Series | list[Any], default: Any = "") -> Any:
    for value in series:
        if value is None or pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _session_key_frame(frame: pd.DataFrame) -> pd.Series:
    workout_id = frame.get("workout_id", pd.Series("", index=frame.index)).fillna("").astype(str)
    title = frame.get("title", pd.Series("Workout", index=frame.index)).fillna("Workout").astype(str)
    start = pd.to_datetime(
        frame.get("start_time", pd.Series(pd.NaT, index=frame.index)),
        errors="coerce",
    )
    fallback = title + "|" + start.astype(str)
    return workout_id.where(workout_id.str.strip().ne(""), fallback)


def _top_set_text(group: pd.DataFrame) -> str:
    candidates = group[
        group["weight_kg"].notna()
        & group["reps"].notna()
        & (group["weight_kg"] > 0)
        & (group["reps"] > 0)
    ].copy()
    if candidates.empty:
        return "—"

    candidates = candidates.sort_values(
        ["weight_kg", "reps"], ascending=[False, False]
    )
    top = candidates.iloc[0]
    weight = float(top["weight_kg"])
    reps = int(top["reps"])
    weight_text = f"{weight:g}"
    return f"{weight_text} kg × {reps}"


def build_exercise_history(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per exercise occurrence, excluding explicit warm-up sets."""
    if frame.empty:
        return pd.DataFrame()

    prepared = prepare_training_frame(frame)
    prepared = prepared[prepared["exercise_title"].notna()].copy()
    if prepared.empty:
        return pd.DataFrame()

    prepared["session_key"] = _session_key_frame(prepared)
    prepared["start_time"] = pd.to_datetime(prepared["start_time"], errors="coerce")
    prepared["end_time"] = pd.to_datetime(prepared["end_time"], errors="coerce")

    rows: list[dict[str, Any]] = []
    for (session_key, exercise_title), group in prepared.groupby(
        ["session_key", "exercise_title"], sort=False, dropna=False
    ):
        working = group[~group["is_warmup"]].copy()
        rpe = working["rpe"].dropna()
        positive_load = working[
            working["weight_kg"].notna()
            & working["reps"].notna()
            & (working["weight_kg"] > 0)
            & (working["reps"] > 0)
        ]
        max_weight = (
            float(positive_load["weight_kg"].max())
            if not positive_load.empty
            else pd.NA
        )
        start_time = pd.to_datetime(
            _first_nonempty(group["start_time"], pd.NaT), errors="coerce"
        )

        rows.append(
            {
                "session_key": session_key,
                "workout_id": str(_first_nonempty(group.get("workout_id", []), "")),
                "workout_title": str(_first_nonempty(group.get("title", []), "Workout")),
                "start_time": start_time,
                "workout_date": start_time.date() if pd.notna(start_time) else pd.NaT,
                "exercise_order": pd.to_numeric(
                    group.get("exercise_index", pd.Series(dtype=float)), errors="coerce"
                ).min(),
                "exercise": str(exercise_title),
                "warmup_sets": int(group["is_warmup"].sum()),
                "working_sets": int(len(working)),
                "failure_sets": int(working["is_failure"].sum()),
                "reps": int(working["reps"].fillna(0).sum()),
                "max_weight_kg": max_weight,
                "top_set": _top_set_text(working),
                "recorded_load_sets": int(len(positive_load)),
                "recorded_working_volume_kg": (
                    float(working["working_set_volume_kg"].sum())
                    if not positive_load.empty
                    else pd.NA
                ),
                "average_set_rpe": float(rpe.mean()) if not rpe.empty else pd.NA,
                "maximum_set_rpe": float(rpe.max()) if not rpe.empty else pd.NA,
                "rpe_sets": int(rpe.count()),
                "notes": str(_first_nonempty(group.get("exercise_notes", []), "")),
            }
        )

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    return output.sort_values(
        ["start_time", "exercise_order"], ascending=[False, True]
    ).reset_index(drop=True)


def _selected_session_key(session: pd.Series | dict[str, Any]) -> str:
    mapping = dict(session)
    workout_id = mapping.get("workout_id")
    if workout_id is not None and str(workout_id).strip() not in ("", "nan", "None"):
        return str(workout_id)
    title = str(mapping.get("title", "Workout"))
    start = pd.to_datetime(mapping.get("start_time"), errors="coerce")
    return f"{title}|{start}"


def _delta(current: Any, previous: Any) -> float | Any:
    if pd.isna(current) or pd.isna(previous):
        return pd.NA
    return float(current) - float(previous)


def _pct_delta(current: Any, previous: Any) -> float | Any:
    if pd.isna(current) or pd.isna(previous) or float(previous) == 0:
        return pd.NA
    return (float(current) - float(previous)) / float(previous) * 100


def build_previous_exercise_comparison(
    frame: pd.DataFrame,
    session: pd.Series | dict[str, Any],
) -> pd.DataFrame:
    """Compare every selected-session exercise with its previous occurrence."""
    history = build_exercise_history(frame)
    if history.empty:
        return pd.DataFrame()

    session_key = _selected_session_key(session)
    current_rows = history[history["session_key"].astype(str) == session_key].copy()
    if current_rows.empty:
        selected_start = pd.to_datetime(dict(session).get("start_time"), errors="coerce")
        current_rows = history[history["start_time"].eq(selected_start)].copy()
    if current_rows.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, current in current_rows.sort_values("exercise_order").iterrows():
        earlier = history[
            (history["exercise"] == current["exercise"])
            & (history["start_time"] < current["start_time"])
        ].sort_values("start_time", ascending=False)
        previous = earlier.iloc[0] if not earlier.empty else None

        previous_date = previous["workout_date"] if previous is not None else pd.NaT
        previous_max = previous["max_weight_kg"] if previous is not None else pd.NA
        previous_volume = (
            previous["recorded_working_volume_kg"] if previous is not None else pd.NA
        )
        previous_sets = previous["working_sets"] if previous is not None else pd.NA
        previous_reps = previous["reps"] if previous is not None else pd.NA
        previous_top_set = previous["top_set"] if previous is not None else "—"
        previous_rpe = previous["average_set_rpe"] if previous is not None else pd.NA

        rows.append(
            {
                "exercise_order": current["exercise_order"],
                "exercise": current["exercise"],
                "previous date": previous_date,
                "current top set": current["top_set"],
                "previous top set": previous_top_set,
                "max weight kg": current["max_weight_kg"],
                "Δ max kg": _delta(current["max_weight_kg"], previous_max),
                "working volume kg": current["recorded_working_volume_kg"],
                "Δ volume %": _pct_delta(
                    current["recorded_working_volume_kg"], previous_volume
                ),
                "working sets": current["working_sets"],
                "previous sets": previous_sets,
                "reps": current["reps"],
                "previous reps": previous_reps,
                "avg set RPE": current["average_set_rpe"],
                "previous avg RPE": previous_rpe,
                "notes": current["notes"],
            }
        )

    output = pd.DataFrame(rows)
    return output.sort_values("exercise_order").drop(columns="exercise_order").reset_index(drop=True)


def select_exercise_history(
    history: pd.DataFrame,
    exercise: str,
    max_sessions: int = 10,
) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    output = history[history["exercise"].astype(str) == str(exercise)].copy()
    return output.sort_values("start_time").tail(max_sessions).reset_index(drop=True)


def build_note_flags(session_rows: pd.DataFrame) -> pd.DataFrame:
    """Transparent keyword flags from exercise notes; not a clinical assessment."""
    if session_rows.empty:
        return pd.DataFrame()

    notes = session_rows[
        [column for column in ("exercise_index", "exercise_title", "exercise_notes") if column in session_rows.columns]
    ].drop_duplicates()
    if "exercise_notes" not in notes.columns:
        return pd.DataFrame()

    notes["exercise_notes"] = notes["exercise_notes"].fillna("").astype(str).str.strip()
    notes = notes[notes["exercise_notes"].ne("")].copy()
    rows: list[dict[str, Any]] = []

    for _, row in notes.iterrows():
        text = row["exercise_notes"]
        flags = [label for label, pattern in NOTE_PATTERNS.items() if pattern.search(text)]
        if not flags:
            flags = ["General note"]
        priority = (
            "Review"
            if "Pain/discomfort" in flags
            else "Context"
            if any(flag in flags for flag in ("Fatigue/environment", "Technique/balance"))
            else "Info"
        )
        rows.append(
            {
                "exercise_order": pd.to_numeric(row.get("exercise_index"), errors="coerce"),
                "priority": priority,
                "exercise": row.get("exercise_title", ""),
                "keyword flags": ", ".join(flags),
                "note": text,
            }
        )

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    priority_order = pd.Categorical(
        output["priority"], categories=["Review", "Context", "Info"], ordered=True
    )
    output = output.assign(_priority_order=priority_order)
    return output.sort_values(["_priority_order", "exercise_order"]).drop(
        columns=["_priority_order", "exercise_order"]
    ).reset_index(drop=True)

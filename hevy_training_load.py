from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd


SESSION_RPE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:session\s*)?rpe\s*[:=\-]?\s*(10(?:\.0)?|[0-9](?:\.[0-9])?)\b"
    ),
    re.compile(
        r"(?i)\bsrpe\s*[:=\-]?\s*(10(?:\.0)?|[0-9](?:\.[0-9])?)\b"
    ),
)

WARMUP_TYPES = {
    "warmup",
    "warm-up",
    "warm_up",
    "warm up",
}
FAILURE_TYPES = {
    "failure",
    "failed",
}


def parse_session_rpe(value: Any) -> float | None:
    """Extract a 0–10 session RPE from a Hevy workout description."""
    if not isinstance(value, str):
        return None

    for pattern in SESSION_RPE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        parsed = float(match.group(1))
        if 0 <= parsed <= 10:
            return parsed
    return None


def _first_nonempty(values: Iterable[Any], default: Any = "") -> Any:
    for value in values:
        if value is None or pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _normalize_set_type(value: Any) -> str:
    if value is None or pd.isna(value):
        return "normal"
    return str(value).strip().lower().replace("_", " ") or "normal"


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _session_group_columns(frame: pd.DataFrame) -> list[str]:
    if "workout_id" in frame.columns and frame["workout_id"].notna().any():
        return ["workout_id"]
    return [
        column
        for column in ("title", "start_time", "end_time")
        if column in frame.columns
    ]


def prepare_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Add explicit working/warm-up flags and calculation columns."""
    if frame.empty:
        return frame.copy()

    output = frame.copy()
    for column in ("start_time", "end_time"):
        if column in output.columns:
            output[column] = pd.to_datetime(output[column], errors="coerce")

    for column in (
        "weight_kg",
        "reps",
        "rpe",
        "duration_seconds",
        "distance_meters",
        "distance_km",
        "set_index",
        "exercise_index",
    ):
        output[column] = _numeric(output, column)

    if "set_type" not in output.columns:
        output["set_type"] = "normal"
    output["set_type_normalized"] = output["set_type"].map(_normalize_set_type)
    output["is_warmup"] = output["set_type_normalized"].isin(WARMUP_TYPES)
    output["is_failure"] = output["set_type_normalized"].isin(FAILURE_TYPES)

    output["has_set"] = output.get("exercise_title", pd.Series(index=output.index)).notna()
    output["has_load_and_reps"] = (
        output["weight_kg"].notna()
        & output["reps"].notna()
        & (output["weight_kg"] > 0)
        & (output["reps"] > 0)
    )
    output["recorded_set_volume_kg"] = (
        output["weight_kg"].fillna(0) * output["reps"].fillna(0)
    )
    output["working_set_volume_kg"] = output["recorded_set_volume_kg"].where(
        ~output["is_warmup"], 0
    )
    return output


def build_session_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one trainer-facing summary row per Hevy workout."""
    if frame.empty:
        return pd.DataFrame()

    prepared = prepare_training_frame(frame)
    group_columns = _session_group_columns(prepared)
    if not group_columns:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    grouped = prepared.groupby(group_columns, dropna=False, sort=False)
    for group_key, group in grouped:
        start_time = pd.to_datetime(
            _first_nonempty(group.get("start_time", []), pd.NaT),
            errors="coerce",
        )
        end_time = pd.to_datetime(
            _first_nonempty(group.get("end_time", []), pd.NaT),
            errors="coerce",
        )
        duration_minutes = (
            (end_time - start_time).total_seconds() / 60
            if pd.notna(start_time) and pd.notna(end_time) and end_time >= start_time
            else pd.NA
        )

        description = str(_first_nonempty(group.get("description", []), ""))
        session_rpe = parse_session_rpe(description)
        set_rows = group[group["has_set"]].copy()
        working_rows = set_rows[~set_rows["is_warmup"]]
        set_rpe = working_rows["rpe"].dropna()

        workout_id = (
            str(_first_nonempty(group.get("workout_id", []), ""))
            if "workout_id" in group.columns
            else ""
        )
        title = str(_first_nonempty(group.get("title", []), "Workout"))

        row = {
            "workout_id": workout_id,
            "title": title,
            "description": description,
            "routine_id": _first_nonempty(group.get("routine_id", []), ""),
            "start_time": start_time,
            "end_time": end_time,
            "workout_date": start_time.date() if pd.notna(start_time) else pd.NaT,
            "duration_minutes": duration_minutes,
            "session_rpe": session_rpe,
            "session_load": (
                float(duration_minutes) * float(session_rpe)
                if pd.notna(duration_minutes) and session_rpe is not None
                else pd.NA
            ),
            "exercise_count": int(set_rows["exercise_title"].nunique()),
            "total_sets": int(len(set_rows)),
            "warmup_sets": int(set_rows["is_warmup"].sum()),
            "working_sets": int((~set_rows["is_warmup"]).sum()),
            "failure_sets": int(set_rows["is_failure"].sum()),
            "total_reps": float(set_rows["reps"].fillna(0).sum()),
            "recorded_total_volume_kg": float(
                set_rows["recorded_set_volume_kg"].sum()
            ),
            "recorded_working_volume_kg": float(
                set_rows["working_set_volume_kg"].sum()
            ),
            "set_rpe_logged": int(set_rpe.count()),
            "set_rpe_eligible": int(len(working_rows)),
            "set_rpe_coverage_pct": (
                float(set_rpe.count() / len(working_rows) * 100)
                if len(working_rows)
                else 0.0
            ),
            "average_set_rpe": float(set_rpe.mean()) if not set_rpe.empty else pd.NA,
            "maximum_set_rpe": float(set_rpe.max()) if not set_rpe.empty else pd.NA,
            "high_rpe_sets": int((set_rpe >= 9).sum()) if not set_rpe.empty else 0,
            "zero_load_sets": int(
                ((working_rows["weight_kg"].fillna(-1) == 0) & working_rows["reps"].notna()).sum()
            ),
        }
        rows.append(row)

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    return output.sort_values("start_time", ascending=False).reset_index(drop=True)


def select_session_rows(
    frame: pd.DataFrame,
    session: pd.Series | dict[str, Any],
) -> pd.DataFrame:
    """Select the source rows for one session summary."""
    if frame.empty:
        return frame.copy()

    session_mapping = dict(session)
    workout_id = session_mapping.get("workout_id")
    if (
        workout_id not in (None, "")
        and "workout_id" in frame.columns
        and frame["workout_id"].notna().any()
    ):
        return frame[frame["workout_id"].astype(str) == str(workout_id)].copy()

    mask = pd.Series(True, index=frame.index)
    for column in ("title", "start_time", "end_time"):
        if column not in frame.columns or column not in session_mapping:
            continue
        if column in ("start_time", "end_time"):
            left = pd.to_datetime(frame[column], errors="coerce")
            right = pd.to_datetime(session_mapping[column], errors="coerce")
            mask &= left.eq(right)
        else:
            mask &= frame[column].astype(str).eq(str(session_mapping[column]))
    return frame[mask].copy()


def build_exercise_summary(session_rows: pd.DataFrame) -> pd.DataFrame:
    """Summarize exercises for one selected workout."""
    if session_rows.empty:
        return pd.DataFrame()

    prepared = prepare_training_frame(session_rows)
    prepared = prepared[prepared["exercise_title"].notna()].copy()
    if prepared.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for exercise_title, group in prepared.groupby("exercise_title", sort=False):
        working = group[~group["is_warmup"]]
        set_rpe = working["rpe"].dropna()
        exercise_index = pd.to_numeric(group["exercise_index"], errors="coerce").min()
        notes = str(_first_nonempty(group.get("exercise_notes", []), ""))

        rows.append(
            {
                "exercise_order": exercise_index,
                "exercise": exercise_title,
                "warm-up sets": int(group["is_warmup"].sum()),
                "working sets": int((~group["is_warmup"]).sum()),
                "reps": int(group["reps"].fillna(0).sum()),
                "max weight kg": (
                    float(group["weight_kg"].max())
                    if group["weight_kg"].notna().any()
                    else pd.NA
                ),
                "recorded working volume kg": float(
                    group["working_set_volume_kg"].sum()
                ),
                "avg set RPE": float(set_rpe.mean()) if not set_rpe.empty else pd.NA,
                "max set RPE": float(set_rpe.max()) if not set_rpe.empty else pd.NA,
                "RPE sets": int(set_rpe.count()),
                "notes": notes,
            }
        )

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    return output.sort_values(
        ["exercise_order", "exercise"], na_position="last"
    ).drop(columns=["exercise_order"]).reset_index(drop=True)


def build_rpe_set_table(session_rows: pd.DataFrame) -> pd.DataFrame:
    """Return only sets with native per-set RPE values."""
    if session_rows.empty:
        return pd.DataFrame()

    prepared = prepare_training_frame(session_rows)
    output = prepared[prepared["rpe"].notna()].copy()
    if output.empty:
        return pd.DataFrame()

    keep = [
        column
        for column in (
            "exercise_index",
            "exercise_title",
            "set_index",
            "set_type",
            "weight_kg",
            "reps",
            "rpe",
        )
        if column in output.columns
    ]
    output = output[keep].sort_values(
        [column for column in ("exercise_index", "set_index") if column in keep]
    )
    if "set_index" in output.columns:
        output["set_index"] = output["set_index"] + 1
    return output.rename(
        columns={
            "exercise_title": "exercise",
            "set_index": "set",
            "set_type": "type",
            "weight_kg": "weight kg",
        }
    ).reset_index(drop=True)

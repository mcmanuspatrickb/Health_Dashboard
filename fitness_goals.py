from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from hevy_training_load import prepare_training_frame


DEFAULT_ALIAS_RULES = [
    {
        "goal_id": "back_squat",
        "pattern": r"(?i)\b(back\s*squat|barbell\s*squat|squat\s*\(barbell\))\b",
        "exclude_pattern": r"(?i)\b(front|goblet|hack|split|bulgarian)\b",
        "notes": "Barbell back-squat variations only.",
    },
    {
        "goal_id": "bench_press",
        "pattern": r"(?i)\b(bench\s*press|barbell\s*bench|bench\s*\(barbell\))\b",
        "exclude_pattern": r"(?i)\b(dumbbell|incline|decline|machine|smith)\b",
        "notes": "Flat barbell bench preferred.",
    },
    {
        "goal_id": "deadlift",
        "pattern": r"(?i)\b(deadlift|conventional\s*deadlift|sumo\s*deadlift)\b",
        "exclude_pattern": r"(?i)\b(romanian|rdl|stiff|single.leg)\b",
        "notes": "Conventional or sumo deadlift; excludes RDL variants.",
    },
    {
        "goal_id": "pull_ups",
        "pattern": r"(?i)\b(pull[ -]?ups?|chin[ -]?ups?)\b",
        "exclude_pattern": "",
        "notes": "Bodyweight or weighted pull-up/chin-up sets.",
    },
    {
        "goal_id": "pushups",
        "pattern": r"(?i)\b(push[ -]?ups?)\b",
        "exclude_pattern": r"(?i)\b(clap|plyo|plyometric|weighted|incline|decline)\b",
        "notes": "Standard push-ups; each recorded standard push-up set is assumed to represent the one-minute test.",
    },
    {
        "goal_id": "bar_hang",
        "pattern": r"(?i)\b(dead\s*hang|bar\s*hang|hang\s*hold)\b",
        "exclude_pattern": "",
        "notes": "Uses recorded set duration.",
    },
    {
        "goal_id": "row",
        "pattern": r"(?i)\b(cable\s*seated\s*row|seated\s*cable\s*row|cable\s*row(?:\s*\(seated\))?|seated\s*row\s*\(cable\))\b",
        "exclude_pattern": r"(?i)\b(single[ -]?arm|one[ -]?arm|unilateral)\b",
        "notes": "Cable Seated Row / bilateral seated cable-row variations only; excludes unilateral/single-arm rows.",
    },
    {
        "goal_id": "overhead_press",
        "pattern": r"(?i)\b(overhead\s*press|military\s*press|shoulder\s*press\s*\(barbell\)|barbell\s*overhead)\b",
        "exclude_pattern": r"(?i)\b(dumbbell|machine|smith|seated)\b",
        "notes": "Standing barbell overhead press preferred.",
    },
    {
        "goal_id": "farmer_carry",
        "pattern": r"(?i)\b(farmer'?s?\s*(carry|walk)|farmers?\s*(carry|walk))\b",
        "exclude_pattern": "",
        "notes": "Recorded weight is assumed to be per hand; confirm your Hevy convention.",
    },
    {
        "goal_id": "plank",
        "pattern": r"(?i)\bplank\b",
        "exclude_pattern": r"(?i)\b(side|copenhagen|high|weighted|pull.through)\b",
        "notes": "Standard front plank; uses recorded set duration.",
    },
    {
        "goal_id": "get_up",
        "pattern": r"(?i)\b(turkish\s*get[ -]?up|get[ -]?up)\b",
        "exclude_pattern": "",
        "notes": "Uses the heaviest recorded loaded set.",
    },
]


def load_goal_payload(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fitness_goals.json must contain a JSON object.")
    return payload


def load_goals(path: str | Path) -> list[dict[str, Any]]:
    payload = load_goal_payload(path)
    goals = payload.get("goals", [])
    if not isinstance(goals, list):
        raise ValueError("fitness_goals.json must contain a goals list.")
    return goals


def load_body_composition_proxy(path: str | Path) -> dict[str, float | str | list]:
    payload = load_goal_payload(path)
    proxy = payload.get("body_composition_proxy", {})
    if not isinstance(proxy, dict):
        proxy = {}
    return {
        "method": str(proxy.get("method", "withings_compatible_fixed_bone_mass")),
        "bone_mass_baseline_kg": float(proxy.get("bone_mass_baseline_kg", 3.87)),
        "notes": proxy.get("notes", []),
    }


def load_alias_rules(path: str | Path | None = None) -> list[dict[str, str]]:
    if path is None or not Path(path).exists():
        return DEFAULT_ALIAS_RULES
    frame = pd.read_csv(path).fillna("")
    required = {"goal_id", "pattern", "exclude_pattern"}
    if not required.issubset(frame.columns):
        return DEFAULT_ALIAS_RULES
    return frame.to_dict("records")


def estimate_e1rm(weight_kg: Any, reps: Any) -> float | None:
    """Epley estimate for sensible loaded sets of 1–12 reps."""
    weight = pd.to_numeric(weight_kg, errors="coerce")
    repetitions = pd.to_numeric(reps, errors="coerce")
    if pd.isna(weight) or pd.isna(repetitions):
        return None
    weight = float(weight)
    repetitions = float(repetitions)
    if weight <= 0 or repetitions < 1 or repetitions > 12:
        return None
    if repetitions == 1:
        return weight
    return weight * (1 + repetitions / 30)


def _match_exercise_names(
    names: pd.Series,
    goal_id: str,
    alias_rules: list[dict[str, str]],
) -> pd.Series:
    mask = pd.Series(False, index=names.index)
    for rule in alias_rules:
        if str(rule.get("goal_id", "")) != goal_id:
            continue
        pattern = str(rule.get("pattern", "")).strip()
        if not pattern:
            continue
        pattern_re = re.compile(pattern)
        text = names.fillna("").astype(str)
        current = text.map(lambda value: bool(pattern_re.search(value)))
        exclude = str(rule.get("exclude_pattern", "")).strip()
        if exclude:
            exclude_re = re.compile(exclude)
            current &= ~text.map(lambda value: bool(exclude_re.search(value)))
        mask |= current
    return mask


def _body_snapshot(
    body: pd.DataFrame,
    proxy_config: dict[str, Any] | None = None,
) -> dict[str, float | None]:
    proxy_config = proxy_config or {}
    bone_mass = float(proxy_config.get("bone_mass_baseline_kg", 3.87))
    if body.empty:
        return {
            "weight_kg": None,
            "body_fat_pct": None,
            "fat_mass_kg": None,
            "lean_mass_kg": None,
            "estimated_muscle_mass_kg": None,
            "estimated_muscle_mass_pct": None,
        }

    frame = body.copy().sort_values("date")
    weight = pd.to_numeric(frame.get("weight_kg"), errors="coerce").dropna()
    body_fat = pd.to_numeric(frame.get("body_fat_pct"), errors="coerce").dropna()
    latest_weight = float(weight.iloc[-1]) if not weight.empty else None
    latest_fat = float(body_fat.iloc[-1]) if not body_fat.empty else None
    fat_mass = (
        latest_weight * latest_fat / 100
        if latest_weight is not None and latest_fat is not None
        else None
    )
    lean_mass = (
        latest_weight - fat_mass
        if latest_weight is not None and fat_mass is not None
        else None
    )
    estimated_muscle_mass = (
        lean_mass - bone_mass
        if lean_mass is not None
        else None
    )
    estimated_muscle_pct = (
        estimated_muscle_mass / latest_weight * 100
        if estimated_muscle_mass is not None and latest_weight not in (None, 0)
        else None
    )
    return {
        "weight_kg": latest_weight,
        "body_fat_pct": latest_fat,
        "fat_mass_kg": fat_mass,
        "lean_mass_kg": lean_mass,
        "estimated_muscle_mass_kg": estimated_muscle_mass,
        "estimated_muscle_mass_pct": estimated_muscle_pct,
    }


def build_lift_records(
    frame: pd.DataFrame,
    alias_rules: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    if frame.empty:
        return {}
    prepared = prepare_training_frame(frame)
    prepared = prepared[
        prepared["exercise_title"].notna() & ~prepared["is_warmup"]
    ].copy()
    if prepared.empty:
        return {}

    prepared["e1rm_kg"] = [
        estimate_e1rm(weight, reps)
        for weight, reps in zip(prepared["weight_kg"], prepared["reps"])
    ]
    prepared["e1rm_kg"] = pd.to_numeric(prepared["e1rm_kg"], errors="coerce")
    prepared["duration_seconds"] = pd.to_numeric(
        prepared.get("duration_seconds"), errors="coerce"
    )
    prepared["distance_meters"] = pd.to_numeric(
        prepared.get("distance_meters"), errors="coerce"
    )

    records: dict[str, dict[str, Any]] = {}
    for goal_id in {
        str(rule["goal_id"]) for rule in alias_rules if rule.get("goal_id")
    }:
        subset = prepared[
            _match_exercise_names(
                prepared["exercise_title"],
                goal_id,
                alias_rules,
            )
        ].copy()
        if subset.empty:
            continue

        loaded = subset[(subset["weight_kg"] > 0) & (subset["reps"] > 0)]
        three_to_five = loaded[subset.loc[loaded.index, "reps"].between(3, 5)]
        timed_pushups = subset[
            subset["duration_seconds"].between(45, 75, inclusive="both")
        ]
        records[goal_id] = {
            "matched_exercises": ", ".join(
                sorted(subset["exercise_title"].astype(str).unique())
            ),
            "best_e1rm_kg": (
                float(subset["e1rm_kg"].max())
                if subset["e1rm_kg"].notna().any()
                else None
            ),
            "best_3_to_5_weight_kg": (
                float(three_to_five["weight_kg"].max())
                if not three_to_five.empty
                else None
            ),
            "best_reps": (
                int(subset["reps"].max())
                if subset["reps"].notna().any()
                else None
            ),
            "best_one_minute_reps": (
                int(timed_pushups["reps"].max())
                if not timed_pushups.empty
                and timed_pushups["reps"].notna().any()
                else None
            ),
            "has_duration": bool(subset["duration_seconds"].notna().any()),
            "best_duration_seconds": (
                float(subset["duration_seconds"].max())
                if subset["duration_seconds"].notna().any()
                else None
            ),
            "best_weight_kg": (
                float(subset["weight_kg"].max())
                if subset["weight_kg"].notna().any()
                else None
            ),
            "best_distance_m": (
                float(subset["distance_meters"].max())
                if subset["distance_meters"].notna().any()
                else None
            ),
        }
    return records


def build_exercise_performance_history(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per exercise occurrence with e1RM and PR-friendly metrics."""
    if frame.empty:
        return pd.DataFrame()
    prepared = prepare_training_frame(frame)
    prepared = prepared[
        prepared["exercise_title"].notna() & ~prepared["is_warmup"]
    ].copy()
    if prepared.empty:
        return pd.DataFrame()

    prepared["start_time"] = pd.to_datetime(prepared["start_time"], errors="coerce")
    prepared["e1rm_kg"] = [
        estimate_e1rm(weight, reps)
        for weight, reps in zip(prepared["weight_kg"], prepared["reps"])
    ]
    prepared["e1rm_kg"] = pd.to_numeric(prepared["e1rm_kg"], errors="coerce")
    workout_id = prepared.get(
        "workout_id", pd.Series("", index=prepared.index)
    ).fillna("").astype(str)
    fallback = (
        prepared.get("title", pd.Series("Workout", index=prepared.index)).astype(str)
        + "|"
        + prepared["start_time"].astype(str)
    )
    prepared["session_key"] = workout_id.where(workout_id.str.strip().ne(""), fallback)

    rows: list[dict[str, Any]] = []
    for (session_key, exercise), group in prepared.groupby(
        ["session_key", "exercise_title"],
        sort=False,
    ):
        rpe = group["rpe"].dropna()
        loaded = group[(group["weight_kg"] > 0) & (group["reps"] > 0)]
        rows.append(
            {
                "session_key": session_key,
                "exercise": str(exercise),
                "workout_title": str(group.get("title", pd.Series(["Workout"])).iloc[0]),
                "start_time": group["start_time"].min(),
                "workout_date": group["start_time"].min().date()
                if pd.notna(group["start_time"].min())
                else pd.NaT,
                "working_sets": int(len(group)),
                "reps": float(group["reps"].fillna(0).sum()),
                "max_weight_kg": (
                    float(loaded["weight_kg"].max()) if not loaded.empty else pd.NA
                ),
                "best_e1rm_kg": (
                    float(group["e1rm_kg"].max())
                    if group["e1rm_kg"].notna().any()
                    else pd.NA
                ),
                "working_volume_kg": float(group["working_set_volume_kg"].sum()),
                "average_set_rpe": float(rpe.mean()) if not rpe.empty else pd.NA,
                "rpe_sets": int(rpe.count()),
            }
        )

    output = pd.DataFrame(rows).sort_values(["exercise", "start_time"])
    if output.empty:
        return output
    for metric, flag in (
        ("max_weight_kg", "weight_pr"),
        ("best_e1rm_kg", "e1rm_pr"),
        ("working_volume_kg", "volume_pr"),
        ("reps", "reps_pr"),
    ):
        current_values = pd.to_numeric(output[metric], errors="coerce")
        previous_best = current_values.groupby(output["exercise"]).transform(
            lambda values: values.cummax().shift(1)
        )
        output[metric] = current_values
        output[flag] = current_values.notna() & (
            previous_best.isna() | current_values.gt(previous_best)
        )
    return output.sort_values("start_time", ascending=False).reset_index(drop=True)


def _status_for_minimum(current: float | None, target: float) -> tuple[str, float | None, float | None]:
    if current is None or pd.isna(current):
        return "No data", None, None
    progress = max(0.0, min(float(current) / target * 100, 100.0))
    return (
        "Achieved" if float(current) >= target else "In progress",
        progress,
        target - float(current),
    )


def _status_for_maximum(current: float | None, target: float) -> tuple[str, float | None, float | None]:
    if current is None or pd.isna(current):
        return "No data", None, None
    progress = max(0.0, min(target / float(current) * 100, 100.0)) if float(current) > 0 else None
    return (
        "Achieved" if float(current) <= target else "In progress",
        progress,
        float(current) - target,
    )


def _duration_text(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    minutes, remaining = divmod(int(round(float(seconds))), 60)
    if minutes:
        return f"{minutes}:{remaining:02d}"
    return f"{remaining} sec"


def _endurance_record(
    endurance: pd.DataFrame,
    activity: str,
) -> dict[str, Any]:
    if endurance.empty or "goal_activity" not in endurance.columns:
        return {}
    subset = endurance[endurance["goal_activity"] == activity].copy()
    if subset.empty:
        return {}
    subset["distance_km"] = pd.to_numeric(subset["distance_km"], errors="coerce")
    subset["duration_hours"] = pd.to_numeric(subset["duration_hours"], errors="coerce")
    longest = subset.sort_values("distance_km", ascending=False).iloc[0]
    return {
        "distance_km": float(longest["distance_km"]),
        "duration_hours": (
            float(longest["duration_hours"])
            if pd.notna(longest["duration_hours"])
            else None
        ),
        "date": longest.get("date"),
    }


def build_goal_progress(
    goals: list[dict[str, Any]],
    body: pd.DataFrame,
    hevy: pd.DataFrame,
    endurance: pd.DataFrame,
    alias_rules: list[dict[str, str]],
    proxy_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    proxy_config = proxy_config or {}
    body_values = _body_snapshot(body, proxy_config)
    current_bw = body_values["weight_kg"]
    lifts = build_lift_records(hevy, alias_rules)
    endurance_records = {
        activity: _endurance_record(endurance, activity)
        for activity in ("run", "swim", "bike")
    }

    rows: list[dict[str, Any]] = []
    for goal in goals:
        goal_id = str(goal.get("id", ""))
        metric = str(goal.get("metric", ""))
        target = goal.get("target")
        target = float(target) if target not in (None, "") else None
        target_direction = str(goal.get("direction", "minimum"))
        unit = str(goal.get("unit", ""))
        current: float | None = None
        current_text = "—"
        note = str(goal.get("note", ""))

        if metric == "body_weight_kg":
            current = body_values["weight_kg"]
            current_text = f"{current:.2f} kg" if current is not None else "—"
        elif metric == "body_fat_pct":
            current = body_values["body_fat_pct"]
            current_text = f"{current:.2f}%" if current is not None else "—"
        elif metric == "estimated_muscle_mass_pct":
            current = body_values["estimated_muscle_mass_pct"]
            muscle_kg = body_values["estimated_muscle_mass_kg"]
            current_text = (
                f"{current:.2f}% ({muscle_kg:.2f} kg)"
                if current is not None and muscle_kg is not None
                else "—"
            )
            bone_mass = float(proxy_config.get("bone_mass_baseline_kg", 3.87))
            note = (
                note
                + f" Formula uses a fixed {bone_mass:.2f} kg bone-mass baseline."
            ).strip()
        elif metric in {"e1rm_bw_ratio", "best_3_to_5_weight_kg"}:
            record = lifts.get(goal_id, {})
            if metric == "e1rm_bw_ratio":
                e1rm = record.get("best_e1rm_kg")
                current = (
                    float(e1rm) / float(current_bw)
                    if e1rm is not None and current_bw not in (None, 0)
                    else None
                )
                current_text = (
                    f"{current:.2f}× BW ({e1rm:.1f} kg e1RM)"
                    if current is not None
                    else "—"
                )
            else:
                current = record.get("best_3_to_5_weight_kg")
                current_text = (
                    f"{current:.1f} kg for 3–5 reps"
                    if current is not None
                    else "—"
                )
            if record.get("matched_exercises"):
                note = (note + " Matched: " + record["matched_exercises"]).strip()
        elif metric in {"best_reps", "best_one_minute_reps", "best_duration_seconds", "best_weight_kg", "best_distance_m", "farmer_bw_ratio"}:
            record = lifts.get(goal_id, {})
            if metric == "best_reps":
                current = record.get("best_reps")
                current_text = f"{int(current)} reps" if current is not None else "—"
            elif metric == "best_one_minute_reps":
                current = record.get("best_one_minute_reps")
                if current is not None:
                    current_text = f"{int(current)} reps in ~1 min"
                elif record.get("best_reps") is not None:
                    current_text = f"{int(record['best_reps'])} reps; timing missing"
                    note = (note + " One-minute status cannot be verified without set duration.").strip()
                else:
                    current_text = "—"
            elif metric == "best_duration_seconds":
                current = record.get("best_duration_seconds")
                current_text = _duration_text(current)
            elif metric == "best_weight_kg":
                current = record.get("best_weight_kg")
                current_text = f"{current:.1f} kg" if current is not None else "—"
            elif metric == "best_distance_m":
                current = record.get("best_distance_m")
                current_text = f"{current:.0f} m" if current is not None else "—"
            elif metric == "farmer_bw_ratio":
                load = record.get("best_weight_kg")
                current = (
                    float(load) / float(current_bw)
                    if load is not None and current_bw not in (None, 0)
                    else None
                )
                current_text = (
                    f"{current:.2f}× BW/hand ({load:.1f} kg recorded)"
                    if current is not None
                    else "—"
                )
        elif metric in {"endurance_distance_km", "endurance_time_hours"}:
            record = endurance_records.get(goal_id, {})
            if metric == "endurance_distance_km":
                current = record.get("distance_km")
                current_text = f"{current:.2f} km" if current is not None else "—"
            else:
                current = record.get("duration_hours")
                current_text = f"{current:.2f} h" if current is not None else "—"

        endurance_time_unverified = False
        if metric == "endurance_time_hours":
            required_distance = {"run": 42.2, "swim": 3.8, "bike": 180}.get(goal_id)
            achieved_distance = endurance_records.get(goal_id, {}).get("distance_km")
            endurance_time_unverified = (
                required_distance is not None
                and (achieved_distance is None or float(achieved_distance) < required_distance)
            )

        if endurance_time_unverified:
            status, progress, gap = "Distance not achieved", None, None
        elif target is None:
            status, progress, gap = "Reference", None, None
        elif target_direction == "maximum":
            status, progress, gap = _status_for_maximum(current, target)
        else:
            status, progress, gap = _status_for_minimum(current, target)

        rows.append(
            {
                **goal,
                "current": current,
                "current_display": current_text,
                "status": status,
                "progress_pct": progress,
                "gap": gap,
                "source_detail": note,
            }
        )

    return pd.DataFrame(rows)

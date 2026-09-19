from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pandas as pd


PROTEIN_LOW_PER_KG_LEAN = 1.8
PROTEIN_HIGH_PER_KG_LEAN = 2.2
ENERGY_KCAL_PER_KG = 7700.0

CORE_LIFTS = {
    "Bench press": {
        "include": r"\b(bench\s*press|barbell\s*bench|bench\s*\(barbell\))\b",
        "exclude": r"\b(dumbbell|incline|decline|machine|smith)\b",
    },
    "Deadlift": {
        "include": r"\b(deadlift|conventional\s*deadlift|sumo\s*deadlift)\b",
        "exclude": r"\b(romanian|rdl|stiff|single[ -]?leg)\b",
    },
    "Squat": {
        "include": r"\b(back\s*squat|barbell\s*squat|squat\s*\(barbell\)|deep\s*squat)\b",
        "exclude": r"\b(front|goblet|hack|split|bulgarian)\b",
    },
    "Overhead press": {
        "include": r"\b(overhead\s*press|military\s*press|shoulder\s*press\s*\(barbell\)|barbell\s*overhead)\b",
        "exclude": r"\b(dumbbell|machine|smith|seated|upright)\b",
    },
    "Row": {
        "include": r"\b(cable\s*seated\s*row|seated\s*cable\s*row|cable\s*row(?:\s*\(seated\))?|seated\s*row\s*\(cable\))\b",
        "exclude": r"\b(single[ -]?arm|one[ -]?arm|unilateral)\b",
    },
    "Pull-up": {
        "include": r"\b(pull[ -]?ups?|chin[ -]?ups?)\b",
        "exclude": None,
    },
}


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    values = _numeric(frame, column).dropna()
    return None if values.empty else float(values.mean())


def _latest(frame: pd.DataFrame, column: str) -> float | None:
    values = _numeric(frame, column).dropna()
    return None if values.empty else float(values.iloc[-1])


def _date_frame(frame: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    if frame.empty or date_column not in frame.columns:
        return pd.DataFrame()
    output = frame.copy()
    output["_date"] = pd.to_datetime(output[date_column], errors="coerce").dt.date
    return output.dropna(subset=["_date"])


def _body_daily(withings_scale: pd.DataFrame) -> pd.DataFrame:
    if withings_scale.empty or "date" not in withings_scale.columns:
        return pd.DataFrame(
            columns=["date", "weight_kg", "fat_mass_kg", "fat_free_mass_kg"]
        )

    frame = withings_scale.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["weight_kg"] = pd.to_numeric(frame.get("weight_kg"), errors="coerce")
    frame["body_fat_pct"] = pd.to_numeric(frame.get("body_fat_pct"), errors="coerce")
    frame["fat_mass_kg"] = pd.to_numeric(frame.get("fat_mass_kg"), errors="coerce")
    frame["fat_free_mass_kg"] = pd.to_numeric(
        frame.get("fat_free_mass_kg"), errors="coerce"
    )

    missing_fat = frame["fat_mass_kg"].isna()
    frame.loc[missing_fat, "fat_mass_kg"] = (
        frame.loc[missing_fat, "weight_kg"]
        * frame.loc[missing_fat, "body_fat_pct"]
        / 100.0
    )
    missing_ffm = frame["fat_free_mass_kg"].isna()
    frame.loc[missing_ffm, "fat_free_mass_kg"] = (
        frame.loc[missing_ffm, "weight_kg"] - frame.loc[missing_ffm, "fat_mass_kg"]
    )

    frame = frame.dropna(subset=["date"]).sort_values("date")
    frame["date_only"] = frame["date"].dt.date
    daily = (
        frame.groupby("date_only", as_index=False)
        .agg(
            date=("date", "max"),
            weight_kg=("weight_kg", "mean"),
            fat_mass_kg=("fat_mass_kg", "mean"),
            fat_free_mass_kg=("fat_free_mass_kg", "mean"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    return daily[["date", "weight_kg", "fat_mass_kg", "fat_free_mass_kg"]]


def _rolling_body(body: pd.DataFrame) -> pd.DataFrame:
    if body.empty:
        return body.copy()
    frame = body.copy().set_index("date").sort_index()
    rolling = frame[["weight_kg", "fat_mass_kg", "fat_free_mass_kg"]].rolling(
        "7D", min_periods=2
    ).median()
    rolling = rolling.add_suffix("_7d_median").reset_index()
    return body.merge(rolling, on="date", how="left")


def _common_end_date(body: pd.DataFrame, nutrition: pd.DataFrame) -> date | None:
    body_dates = pd.to_datetime(body.get("date"), errors="coerce").dropna()
    nutrition_dates = pd.to_datetime(nutrition.get("date"), errors="coerce").dropna()
    if body_dates.empty or nutrition_dates.empty:
        return None
    return min(body_dates.max().date(), nutrition_dates.max().date())


def _window(frame: pd.DataFrame, end_date: date, start_offset: int, end_offset: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    local = _date_frame(frame)
    start = end_date - timedelta(days=start_offset)
    end = end_date - timedelta(days=end_offset)
    return local[local["_date"].between(start, end)].copy()


def rolling_energy_balance(
    body: pd.DataFrame,
    nutrition: pd.DataFrame,
    end_date: date,
    recent_weight: float | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "estimated_tdee": None,
        "estimated_deficit": None,
        "weight_slope_kg_day": None,
        "weight_loss_pct_week": None,
        "avg_calories": None,
        "calorie_days": 0,
        "weight_days": 0,
        "coverage_confidence": "LOW",
    }

    start_date = end_date - timedelta(days=27)
    b = _date_frame(body)
    b = b[b["_date"].between(start_date, end_date)].copy()
    n = _date_frame(nutrition)
    n = n[n["_date"].between(start_date, end_date)].copy()

    calories = pd.to_numeric(n.get("calories_kcal"), errors="coerce").dropna()
    weights = b[["_date", "weight_kg"]].copy()
    weights["weight_kg"] = pd.to_numeric(weights["weight_kg"], errors="coerce")
    weights = weights.dropna().sort_values("_date")

    result["calorie_days"] = int(calories.count())
    result["weight_days"] = int(len(weights))
    result["avg_calories"] = float(calories.mean()) if not calories.empty else None

    if result["calorie_days"] >= 25 and result["weight_days"] >= 20:
        result["coverage_confidence"] = "HIGH"
    elif result["calorie_days"] >= 21 and result["weight_days"] >= 12:
        result["coverage_confidence"] = "MEDIUM"

    if result["calorie_days"] < 21 or result["weight_days"] < 12:
        return result

    first_date = min(weights["_date"])
    x = weights["_date"].map(lambda value: (value - first_date).days).astype(float)
    y = weights["weight_kg"].astype(float)
    x_centered = x - x.mean()
    denominator = float((x_centered ** 2).sum())
    if denominator <= 0:
        return result

    slope = float((x_centered * (y - y.mean())).sum() / denominator)
    estimated_tdee = float(result["avg_calories"]) - slope * ENERGY_KCAL_PER_KG
    result["weight_slope_kg_day"] = slope

    if not 1200 <= estimated_tdee <= 5000:
        return result

    result["estimated_tdee"] = estimated_tdee
    result["estimated_deficit"] = estimated_tdee - float(result["avg_calories"])
    if recent_weight is not None and float(recent_weight) > 0:
        result["weight_loss_pct_week"] = -slope * 7.0 / float(recent_weight) * 100.0
    return result


def _matches_core_lift(exercise: str, spec: dict[str, str | None]) -> bool:
    text = str(exercise).lower()
    if not re.search(str(spec["include"]), text, flags=re.IGNORECASE):
        return False
    exclude = spec.get("exclude")
    return not (exclude and re.search(str(exclude), text, flags=re.IGNORECASE))


def strength_comparison(performance_history: pd.DataFrame, end_date: date) -> pd.DataFrame:
    columns = [
        "Lift",
        "Current 4w best e1RM",
        "Prior 4w best e1RM",
        "Change kg",
        "Direction",
        "Current observations",
        "Prior observations",
    ]
    if performance_history.empty:
        return pd.DataFrame(columns=columns)

    frame = performance_history.copy()
    frame["start_time"] = pd.to_datetime(frame.get("start_time"), errors="coerce")
    frame["best_e1rm_kg"] = pd.to_numeric(frame.get("best_e1rm_kg"), errors="coerce")
    frame = frame.dropna(subset=["start_time", "best_e1rm_kg", "exercise"])
    if frame.empty:
        return pd.DataFrame(columns=columns)

    current_start = end_date - timedelta(days=27)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=27)

    rows = []
    for label, spec in CORE_LIFTS.items():
        matched = frame[frame["exercise"].map(lambda value: _matches_core_lift(value, spec))].copy()
        if matched.empty:
            continue
        matched["date_only"] = matched["start_time"].dt.date
        current = matched[matched["date_only"].between(current_start, end_date)]
        prior = matched[matched["date_only"].between(prior_start, prior_end)]
        if current.empty or prior.empty:
            continue
        current_best = float(current["best_e1rm_kg"].max())
        prior_best = float(prior["best_e1rm_kg"].max())
        change = current_best - prior_best
        direction = "up" if change > 1.0 else "down" if change < -1.0 else "flat"
        rows.append(
            {
                "Lift": label,
                "Current 4w best e1RM": current_best,
                "Prior 4w best e1RM": prior_best,
                "Change kg": change,
                "Direction": direction,
                "Current observations": int(len(current)),
                "Prior observations": int(len(prior)),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def waist_history(hevy_measurements: pd.DataFrame) -> pd.DataFrame:
    if hevy_measurements.empty or "date" not in hevy_measurements.columns:
        return pd.DataFrame(columns=["date", "waist_cm"])
    frame = hevy_measurements.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    waist_source = None
    for candidate in ("waist", "waist_cm"):
        if candidate in frame.columns:
            waist_source = candidate
            break
    if waist_source is None:
        return pd.DataFrame(columns=["date", "waist_cm"])
    frame["waist_cm"] = pd.to_numeric(frame[waist_source], errors="coerce")
    return frame[["date", "waist_cm"]].dropna().sort_values("date").reset_index(drop=True)


def build_recomposition_summary(
    withings_scale: pd.DataFrame,
    nutrition: pd.DataFrame,
    sleep: pd.DataFrame,
    steps: pd.DataFrame,
    hevy_measurements: pd.DataFrame,
    performance_history: pd.DataFrame,
) -> dict[str, Any]:
    body = _body_daily(withings_scale)
    body_trend = _rolling_body(body)
    end_date = _common_end_date(body, nutrition)
    if end_date is None:
        return {
            "analysis_end_date": None,
            "summary": {},
            "interpretation": ["Body-composition and nutrition data do not yet overlap enough to build the recomposition analysis."],
            "body_trend": body_trend,
            "strength": pd.DataFrame(),
            "waist": waist_history(hevy_measurements),
        }

    recent = _window(body, end_date, 6, 0)
    first = _window(body, end_date, 27, 21)
    trailing = _window(body, end_date, 27, 0)
    nutrition_7 = _window(nutrition, end_date, 6, 0)
    nutrition_28 = _window(nutrition, end_date, 27, 0)
    sleep_28 = _window(sleep, end_date, 27, 0)
    steps_28 = _window(steps, end_date, 27, 0)

    recent_weight = _mean(recent, "weight_kg")
    recent_fat = _mean(recent, "fat_mass_kg")
    recent_ffm = _mean(recent, "fat_free_mass_kg")
    first_weight = _mean(first, "weight_kg")
    first_fat = _mean(first, "fat_mass_kg")
    first_ffm = _mean(first, "fat_free_mass_kg")

    weight_delta = None if recent_weight is None or first_weight is None else recent_weight - first_weight
    fat_delta = None if recent_fat is None or first_fat is None else recent_fat - first_fat
    ffm_delta = None if recent_ffm is None or first_ffm is None else recent_ffm - first_ffm

    protein_7 = _mean(nutrition_7, "protein_g")
    protein_28 = _mean(nutrition_28, "protein_g")
    calories_28 = _mean(nutrition_28, "calories_kcal")
    sleep_28_avg = _mean(sleep_28, "sleep_hours")
    steps_28_avg = _mean(steps_28, "steps")

    protein_low = recent_ffm * PROTEIN_LOW_PER_KG_LEAN if recent_ffm else None
    protein_high = recent_ffm * PROTEIN_HIGH_PER_KG_LEAN if recent_ffm else None
    protein_per_kg = protein_7 / recent_ffm if protein_7 and recent_ffm else None

    energy = rolling_energy_balance(body, nutrition, end_date, recent_weight)
    strength = strength_comparison(performance_history, end_date)
    strength_up = int((strength.get("Direction") == "up").sum()) if not strength.empty else 0
    strength_flat = int((strength.get("Direction") == "flat").sum()) if not strength.empty else 0
    strength_down = int((strength.get("Direction") == "down").sum()) if not strength.empty else 0

    fat_share = None
    if weight_delta is not None and fat_delta is not None and weight_delta < -0.2 and fat_delta < 0:
        fat_share = abs(fat_delta) / abs(weight_delta) * 100.0

    waist = waist_history(hevy_measurements)
    waist_delta = None
    if len(waist) >= 2:
        latest_waist = float(waist.iloc[-1]["waist_cm"])
        cutoff = pd.Timestamp(end_date) - pd.Timedelta(days=28)
        earlier = waist[waist["date"] <= cutoff]
        if not earlier.empty:
            waist_delta = latest_waist - float(earlier.iloc[-1]["waist_cm"])

    interpretation: list[str] = []
    if fat_delta is not None:
        interpretation.append(
            f"Smoothed fat-mass trend: {fat_delta:+.2f} kg comparing the latest 7-day average with the first 7-day average of the 28-day window."
        )
    if ffm_delta is not None:
        if ffm_delta < -0.5 and strength_down == 0 and (strength_up + strength_flat) > 0:
            interpretation.append(
                f"BIA fat-free mass is down {abs(ffm_delta):.2f} kg, but comparable strength has not declined. That makes hydration/glycogen a plausible contributor; keep watching the multi-week trend rather than treating the BIA change as confirmed muscle loss."
            )
        elif ffm_delta < -0.5 and strength_down > 0:
            interpretation.append(
                f"BIA fat-free mass is down {abs(ffm_delta):.2f} kg and {strength_down} comparable lift(s) are also down. That combination deserves attention to protein, recovery, training quality, and deficit size."
            )
        else:
            interpretation.append(
                f"BIA fat-free-mass change is {ffm_delta:+.2f} kg; use strength and waist alongside it because BIA is hydration-sensitive."
            )

    pace = energy.get("weight_loss_pct_week")
    if pace is not None:
        if pace > 0.75:
            interpretation.append(
                f"Scale-loss pace is about {pace:.2f}%/week, on the aggressive side for a muscle-preservation goal."
            )
        elif pace >= 0.25:
            interpretation.append(
                f"Scale-loss pace is about {pace:.2f}%/week, a moderate pace that does not need to be accelerated if strength and fat loss are progressing."
            )

    if protein_low is not None and protein_7 is not None:
        if protein_7 < protein_low:
            interpretation.append(
                f"Protein averages {protein_7:.0f} g/day versus a current working range of about {protein_low:.0f}-{protein_high:.0f} g/day. Protein consistency is the clearest nutrition lever for the muscle-preservation goal."
            )
        else:
            interpretation.append(
                f"Protein averages {protein_7:.0f} g/day and is within the current working range of about {protein_low:.0f}-{protein_high:.0f} g/day."
            )

    if sleep_28_avg is not None and sleep_28_avg < 7.0:
        interpretation.append(
            f"28-day sleep averages {sleep_28_avg:.1f} h/night; improving recovery toward 7+ hours where practical may help preserve training quality."
        )

    if energy.get("estimated_tdee") is not None:
        interpretation.append(
            f"Experimental 28-day energy-balance estimate: maintenance about {energy['estimated_tdee']:.0f} kcal/day and average deficit about {energy['estimated_deficit']:.0f} kcal/day ({energy['coverage_confidence']} coverage confidence)."
        )

    summary = {
        "weight_change_28d": weight_delta,
        "fat_change_28d": fat_delta,
        "ffm_change_28d": ffm_delta,
        "fat_share_of_loss_pct": fat_share,
        "recent_weight": recent_weight,
        "recent_fat_mass": recent_fat,
        "recent_ffm": recent_ffm,
        "protein_7": protein_7,
        "protein_28": protein_28,
        "protein_per_kg_ffm": protein_per_kg,
        "protein_low": protein_low,
        "protein_high": protein_high,
        "calories_28": calories_28,
        "sleep_28": sleep_28_avg,
        "steps_28": steps_28_avg,
        "waist_change_28d": waist_delta,
        "strength_up": strength_up,
        "strength_flat": strength_flat,
        "strength_down": strength_down,
        **energy,
    }

    return {
        "analysis_end_date": end_date,
        "summary": summary,
        "interpretation": interpretation,
        "body_trend": body_trend,
        "strength": strength,
        "waist": waist,
        "body_28": trailing,
    }

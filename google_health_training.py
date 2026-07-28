from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from google_health_client import GoogleHealthClient


LOCAL_TZ = ZoneInfo("Europe/Berlin")
ALL_SOURCES = "users/me/dataSourceFamilies/all-sources"
WEARABLES = "users/me/dataSourceFamilies/google-wearables"


def _duration_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return 0.0


def _local_timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(LOCAL_TZ)
    return timestamp.tz_convert(LOCAL_TZ)


def _utc_text(value: Any) -> str:
    timestamp = _local_timestamp(value)
    if timestamp is None:
        raise ValueError("A valid timestamp is required.")
    return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _date_dict(value: dict[str, Any] | None) -> date | None:
    value = value or {}
    try:
        return date(
            int(value["year"]),
            int(value["month"]),
            int(value["day"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _civil_timestamp(value: dict[str, Any] | None) -> pd.Timestamp | None:
    value = value or {}
    day = _date_dict(value.get("date"))
    if day is None:
        return None
    time_value = value.get("time", {})
    return pd.Timestamp(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=int(time_value.get("hours", 0) or 0),
        minute=int(time_value.get("minutes", 0) or 0),
        second=int(time_value.get("seconds", 0) or 0),
        tz=LOCAL_TZ,
    )


def _sample_timestamp(sample_time: dict[str, Any] | None) -> pd.Timestamp | None:
    sample_time = sample_time or {}
    physical = _local_timestamp(sample_time.get("physicalTime"))
    if physical is not None:
        return physical
    return _civil_timestamp(sample_time.get("civilTime"))


def _interval_times(
    interval: dict[str, Any] | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    interval = interval or {}
    start = _local_timestamp(interval.get("startTime"))
    end = _local_timestamp(interval.get("endTime"))
    if start is None:
        start = _civil_timestamp(interval.get("civilStartTime"))
    if end is None:
        end = _civil_timestamp(interval.get("civilEndTime"))
    return start, end


def _reconcile_all(
    client: GoogleHealthClient,
    data_type: str,
    filter_expression: str,
    *,
    family: str,
    page_size: int = 10000,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        response = client.reconcile_data_points(
            data_type,
            filter_expression=filter_expression,
            data_source_family=family,
            page_size=page_size,
            page_token=token,
        )
        records.extend(response.get("dataPoints", []))
        token = response.get("nextPageToken") or None
        if not token:
            return records


def load_daily_heart_rate_zones(
    client: GoogleHealthClient,
    workout_date: date,
) -> pd.DataFrame:
    next_day = workout_date + timedelta(days=1)
    filter_expression = (
        f'daily_heart_rate_zones.date >= "{workout_date.isoformat()}" '
        f'AND daily_heart_rate_zones.date < "{next_day.isoformat()}"'
    )
    points = _reconcile_all(
        client,
        "daily-heart-rate-zones",
        filter_expression,
        family=ALL_SOURCES,
    )

    rows: list[dict[str, Any]] = []
    for point in points:
        payload = point.get("dailyHeartRateZones", {})
        for zone in payload.get("heartRateZones", []):
            minimum = pd.to_numeric(
                zone.get("minBeatsPerMinute"), errors="coerce"
            )
            maximum = pd.to_numeric(
                zone.get("maxBeatsPerMinute"), errors="coerce"
            )
            if pd.isna(minimum) or pd.isna(maximum):
                continue
            rows.append(
                {
                    "zone": str(
                        zone.get("heartRateZoneType", "UNKNOWN")
                    ).replace("_", " ").title(),
                    "min_bpm": int(minimum),
                    "max_bpm": int(maximum),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["zone", "min_bpm", "max_bpm"])
    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["zone", "min_bpm", "max_bpm"])
        .sort_values("min_bpm")
        .reset_index(drop=True)
    )


def load_heart_rate_samples(
    client: GoogleHealthClient,
    start_time: Any,
    end_time: Any,
) -> pd.DataFrame:
    start = _local_timestamp(start_time)
    end = _local_timestamp(end_time)
    if start is None or end is None or end <= start:
        return pd.DataFrame(columns=["timestamp", "bpm"])

    filter_expression = (
        f'heart_rate.sample_time.physical_time >= "{_utc_text(start)}" '
        f'AND heart_rate.sample_time.physical_time < "{_utc_text(end)}"'
    )
    points = _reconcile_all(
        client,
        "heart-rate",
        filter_expression,
        family=WEARABLES,
    )

    rows: list[dict[str, Any]] = []
    for point in points:
        payload = point.get("heartRate", {})
        timestamp = _sample_timestamp(payload.get("sampleTime"))
        bpm = pd.to_numeric(payload.get("beatsPerMinute"), errors="coerce")
        if timestamp is None or pd.isna(bpm):
            continue
        rows.append({"timestamp": timestamp, "bpm": int(bpm)})

    if not rows:
        return pd.DataFrame(columns=["timestamp", "bpm"])

    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _assign_zone(bpm: int, zones: pd.DataFrame) -> str:
    for _, row in zones.iterrows():
        if int(row["min_bpm"]) <= bpm <= int(row["max_bpm"]):
            return str(row["zone"])
    return "Outside configured zones"


def add_zone_durations(
    heart_rate: pd.DataFrame,
    zones: pd.DataFrame,
    workout_end: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if heart_rate.empty:
        return heart_rate.copy(), pd.DataFrame(columns=["zone", "minutes"])

    output = heart_rate.copy()
    end = _local_timestamp(workout_end)

    timestamp_delta = (
        output["timestamp"].shift(-1) - output["timestamp"]
    ).dt.total_seconds()
    positive_delta = timestamp_delta[timestamp_delta > 0]
    typical_interval = (
        float(positive_delta.median()) if not positive_delta.empty else 2.0
    )
    typical_interval = min(max(typical_interval, 0.5), 10.0)

    if end is not None:
        last_delta = max(
            0.0,
            min((end - output.iloc[-1]["timestamp"]).total_seconds(), 10.0),
        )
    else:
        last_delta = typical_interval

    output["seconds_to_next"] = timestamp_delta.clip(lower=0, upper=10)
    output.loc[output.index[-1], "seconds_to_next"] = last_delta
    output["seconds_to_next"] = output["seconds_to_next"].fillna(
        typical_interval
    )

    if zones.empty:
        output["zone"] = "Heart rate"
    else:
        output["zone"] = output["bpm"].map(
            lambda value: _assign_zone(int(value), zones)
        )

    zone_summary = (
        output.groupby("zone", as_index=False)["seconds_to_next"]
        .sum()
        .rename(columns={"seconds_to_next": "seconds"})
    )
    zone_summary["minutes"] = zone_summary["seconds"] / 60
    zone_summary = zone_summary.sort_values("minutes", ascending=False)

    return output, zone_summary[["zone", "minutes"]]


def _exercise_score(
    payload: dict[str, Any],
    overlap_ratio: float,
) -> float:
    exercise_type = str(payload.get("exerciseType", ""))
    priority = {
        "WEIGHTLIFTING": 30,
        "STRENGTH_TRAINING": 20,
        "WORKOUT": 10,
    }.get(exercise_type, 0)
    metrics = payload.get("metricsSummary", {})
    completeness = sum(
        1
        for key in (
            "averageHeartRateBeatsPerMinute",
            "activeZoneMinutes",
            "caloriesKcal",
        )
        if metrics.get(key) not in (None, "", 0, 0.0)
    )
    return overlap_ratio * 100 + priority + completeness * 5


def find_best_matching_exercise(
    client: GoogleHealthClient,
    start_time: Any,
    end_time: Any,
) -> dict[str, Any] | None:
    start = _local_timestamp(start_time)
    end = _local_timestamp(end_time)
    if start is None or end is None or end <= start:
        return None

    query_start = start.date() - timedelta(days=1)
    query_end = end.date() + timedelta(days=2)
    filter_expression = (
        f'exercise.interval.civil_start_time >= "{query_start.isoformat()}" '
        f'AND exercise.interval.civil_start_time < "{query_end.isoformat()}"'
    )
    points = _reconcile_all(
        client,
        "exercise",
        filter_expression,
        family=ALL_SOURCES,
        page_size=25,
    )

    duration_seconds = (end - start).total_seconds()
    candidates: list[dict[str, Any]] = []
    for point in points:
        payload = point.get("exercise", {})
        exercise_start, exercise_end = _interval_times(payload.get("interval"))
        if exercise_start is None or exercise_end is None:
            continue
        overlap_start = max(start, exercise_start)
        overlap_end = min(end, exercise_end)
        overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
        overlap_ratio = overlap_seconds / duration_seconds if duration_seconds else 0.0
        if overlap_ratio < 0.50:
            continue
        candidates.append(
            {
                "payload": payload,
                "start": exercise_start,
                "end": exercise_end,
                "overlap_ratio": overlap_ratio,
                "score": _exercise_score(payload, overlap_ratio),
            }
        )

    if not candidates:
        return None

    best = max(candidates, key=lambda item: item["score"])
    payload = best["payload"]
    metrics = payload.get("metricsSummary", {})
    return {
        "title": payload.get("displayName") or payload.get("exerciseType") or "Exercise",
        "exercise_type": payload.get("exerciseType", ""),
        "start": best["start"],
        "end": best["end"],
        "overlap_ratio": float(best["overlap_ratio"]),
        "summary_avg_hr": pd.to_numeric(
            metrics.get("averageHeartRateBeatsPerMinute"), errors="coerce"
        ),
        "active_zone_minutes": pd.to_numeric(
            metrics.get("activeZoneMinutes"), errors="coerce"
        ),
        "calories_kcal": pd.to_numeric(
            metrics.get("caloriesKcal"), errors="coerce"
        ),
    }


def analyze_workout_heart_rate(
    client: GoogleHealthClient,
    start_time: Any,
    end_time: Any,
) -> dict[str, Any]:
    start = _local_timestamp(start_time)
    end = _local_timestamp(end_time)
    if start is None or end is None or end <= start:
        raise ValueError("Workout start/end timestamps are invalid.")

    samples = load_heart_rate_samples(client, start, end)
    zones = load_daily_heart_rate_zones(client, start.date())
    samples, zone_summary = add_zone_durations(samples, zones, end)
    matching_exercise = find_best_matching_exercise(client, start, end)

    duration_seconds = (end - start).total_seconds()
    covered_seconds = (
        float(samples["seconds_to_next"].sum()) if not samples.empty else 0.0
    )

    if samples.empty:
        summary = {
            "duration_minutes": duration_seconds / 60,
            "sample_count": 0,
            "average_hr": pd.NA,
            "minimum_hr": pd.NA,
            "maximum_hr": pd.NA,
            "coverage_pct": 0.0,
            "matching_exercise": matching_exercise,
        }
    else:
        summary = {
            "duration_minutes": duration_seconds / 60,
            "sample_count": int(len(samples)),
            "average_hr": float(samples["bpm"].mean()),
            "minimum_hr": int(samples["bpm"].min()),
            "maximum_hr": int(samples["bpm"].max()),
            "coverage_pct": min(100.0, covered_seconds / duration_seconds * 100),
            "matching_exercise": matching_exercise,
        }

    return {
        "start": start,
        "end": end,
        "summary": summary,
        "samples": samples,
        "zones": zones,
        "zone_summary": zone_summary,
    }

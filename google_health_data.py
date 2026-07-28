from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from google_health_client import GoogleHealthClient


ALL_SOURCES = "users/me/dataSourceFamilies/all-sources"
WEARABLES = "users/me/dataSourceFamilies/google-wearables"


def _date_dict_to_timestamp(value: dict[str, Any] | None) -> pd.Timestamp | None:
    value = value or {}
    try:
        return pd.Timestamp(
            year=int(value["year"]),
            month=int(value["month"]),
            day=int(value["day"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _duration_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    text = value[:-1] if value.endswith("s") else value
    try:
        return float(text)
    except ValueError:
        return 0.0


def _physical_to_local_timestamp(
    physical_time: str | None,
    utc_offset: str | None,
) -> pd.Timestamp | None:
    if not physical_time:
        return None
    try:
        timestamp = pd.Timestamp(physical_time)
        return timestamp + pd.Timedelta(seconds=_duration_seconds(utc_offset))
    except (TypeError, ValueError):
        return None


def _sample_timestamp(sample_time: dict[str, Any] | None) -> pd.Timestamp | None:
    sample_time = sample_time or {}
    civil = sample_time.get("civilTime", {})
    civil_date = _date_dict_to_timestamp(civil.get("date"))
    if civil_date is not None:
        time_value = civil.get("time", {})
        return civil_date + pd.Timedelta(
            hours=int(time_value.get("hours", 0) or 0),
            minutes=int(time_value.get("minutes", 0) or 0),
            seconds=int(time_value.get("seconds", 0) or 0),
        )
    return _physical_to_local_timestamp(
        sample_time.get("physicalTime"),
        sample_time.get("utcOffset"),
    )


def _interval_start_timestamp(interval: dict[str, Any] | None) -> pd.Timestamp | None:
    interval = interval or {}
    civil = interval.get("civilStartTime", {})
    civil_date = _date_dict_to_timestamp(civil.get("date"))
    if civil_date is not None:
        time_value = civil.get("time", {})
        return civil_date + pd.Timedelta(
            hours=int(time_value.get("hours", 0) or 0),
            minutes=int(time_value.get("minutes", 0) or 0),
            seconds=int(time_value.get("seconds", 0) or 0),
        )
    return _physical_to_local_timestamp(
        interval.get("startTime"),
        interval.get("startUtcOffset"),
    )


def _interval_end_timestamp(interval: dict[str, Any] | None) -> pd.Timestamp | None:
    interval = interval or {}
    civil = interval.get("civilEndTime", {})
    civil_date = _date_dict_to_timestamp(civil.get("date"))
    if civil_date is not None:
        time_value = civil.get("time", {})
        return civil_date + pd.Timedelta(
            hours=int(time_value.get("hours", 0) or 0),
            minutes=int(time_value.get("minutes", 0) or 0),
            seconds=int(time_value.get("seconds", 0) or 0),
        )
    return _physical_to_local_timestamp(
        interval.get("endTime"),
        interval.get("endUtcOffset"),
    )


def _list_all(
    client: GoogleHealthClient,
    data_type: str,
    filter_expression: str,
    *,
    reconciled: bool = False,
    data_source_family: str | None = None,
    page_size: int = 10000,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        if reconciled:
            response = client.reconcile_data_points(
                data_type,
                filter_expression=filter_expression,
                data_source_family=data_source_family,
                page_size=page_size,
                page_token=page_token,
            )
        else:
            response = client.list_data_points(
                data_type,
                filter_expression=filter_expression,
                page_size=page_size,
                page_token=page_token,
            )

        points.extend(response.get("dataPoints", []))
        page_token = response.get("nextPageToken") or None
        if not page_token:
            return points


def load_steps(
    client: GoogleHealthClient,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Daily wearable step totals. end_date is inclusive."""
    payload = client.daily_rollup(
        data_type="steps",
        start_date=start_date,
        end_date=end_date,
        data_source_family=WEARABLES,
    )

    rows: list[dict[str, Any]] = []
    for point in payload.get("rollupDataPoints", []):
        day = _date_dict_to_timestamp(
            point.get("civilStartTime", {}).get("date")
        )
        if day is None:
            continue
        rows.append(
            {
                "date": day,
                "steps": int(point.get("steps", {}).get("countSum", 0)),
            }
        )

    return pd.DataFrame(rows, columns=["date", "steps"]).sort_values("date")


def load_recovery(
    client: GoogleHealthClient,
    start_date: date,
    end_date_exclusive: date,
) -> pd.DataFrame:
    rhr_filter = (
        f'daily_resting_heart_rate.date >= "{start_date.isoformat()}" '
        f'AND daily_resting_heart_rate.date < "{end_date_exclusive.isoformat()}"'
    )
    hrv_filter = (
        f'daily_heart_rate_variability.date >= "{start_date.isoformat()}" '
        f'AND daily_heart_rate_variability.date < "{end_date_exclusive.isoformat()}"'
    )

    rhr_points = _list_all(
        client,
        "daily-resting-heart-rate",
        rhr_filter,
        reconciled=True,
        data_source_family=ALL_SOURCES,
    )
    hrv_points = _list_all(
        client,
        "daily-heart-rate-variability",
        hrv_filter,
        reconciled=True,
        data_source_family=ALL_SOURCES,
    )

    rows: dict[pd.Timestamp, dict[str, Any]] = defaultdict(dict)

    for point in rhr_points:
        value = point.get("dailyRestingHeartRate", {})
        day = _date_dict_to_timestamp(value.get("date"))
        if day is not None:
            rows[day]["resting_hr"] = pd.to_numeric(
                value.get("beatsPerMinute"), errors="coerce"
            )

    for point in hrv_points:
        value = point.get("dailyHeartRateVariability", {})
        day = _date_dict_to_timestamp(value.get("date"))
        if day is not None:
            rows[day]["hrv_ms"] = pd.to_numeric(
                value.get("averageHeartRateVariabilityMilliseconds"),
                errors="coerce",
            )
            rows[day]["deep_sleep_hrv_ms"] = pd.to_numeric(
                value.get(
                    "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"
                ),
                errors="coerce",
            )
            rows[day]["non_rem_hr"] = pd.to_numeric(
                value.get("nonRemHeartRateBeatsPerMinute"), errors="coerce"
            )

    output = [dict(date=day, **values) for day, values in rows.items()]
    return pd.DataFrame(
        output,
        columns=[
            "date",
            "resting_hr",
            "hrv_ms",
            "deep_sleep_hrv_ms",
            "non_rem_hr",
        ],
    ).sort_values("date")


def _load_sample_metric(
    client: GoogleHealthClient,
    *,
    data_type: str,
    filter_field: str,
    payload_field: str,
    value_field: str,
    output_field: str,
    start_date: date,
    end_date_exclusive: date,
    transform=lambda value: value,
) -> pd.DataFrame:
    filter_expression = (
        f'{filter_field}.sample_time.civil_time >= "{start_date.isoformat()}" '
        f'AND {filter_field}.sample_time.civil_time < '
        f'"{end_date_exclusive.isoformat()}"'
    )
    points = _list_all(
        client,
        data_type,
        filter_expression,
        reconciled=True,
        data_source_family=ALL_SOURCES,
    )

    rows: list[dict[str, Any]] = []
    for point in points:
        value = point.get(payload_field, {})
        measured_at = _sample_timestamp(value.get("sampleTime"))
        raw_value = value.get(value_field)
        if measured_at is None or raw_value is None:
            continue
        rows.append(
            {
                "measured_at": measured_at,
                "date": measured_at.normalize(),
                output_field: transform(float(raw_value)),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["date", "measured_at", output_field])

    frame = pd.DataFrame(rows).sort_values("measured_at")
    # Use the latest reconciled measurement on days with multiple weigh-ins.
    frame = frame.groupby("date", as_index=False).tail(1)
    return frame[["date", "measured_at", output_field]].sort_values("date")


def load_body(
    client: GoogleHealthClient,
    start_date: date,
    end_date_exclusive: date,
) -> pd.DataFrame:
    weight = _load_sample_metric(
        client,
        data_type="weight",
        filter_field="weight",
        payload_field="weight",
        value_field="weightGrams",
        output_field="weight_kg",
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
        transform=lambda grams: grams / 1000,
    )
    body_fat = _load_sample_metric(
        client,
        data_type="body-fat",
        filter_field="body_fat",
        payload_field="bodyFat",
        value_field="percentage",
        output_field="body_fat_pct",
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )

    if weight.empty and body_fat.empty:
        return pd.DataFrame(
            columns=["date", "weight_kg", "body_fat_pct"]
        )

    weight_daily = weight[["date", "weight_kg"]] if not weight.empty else None
    body_fat_daily = (
        body_fat[["date", "body_fat_pct"]] if not body_fat.empty else None
    )

    if weight_daily is None:
        return body_fat_daily.sort_values("date")
    if body_fat_daily is None:
        return weight_daily.sort_values("date")
    return pd.merge(weight_daily, body_fat_daily, on="date", how="outer").sort_values(
        "date"
    )


def load_sleep(
    client: GoogleHealthClient,
    start_date: date,
    end_date_exclusive: date,
) -> pd.DataFrame:
    filter_expression = (
        f'sleep.interval.civil_end_time >= "{start_date.isoformat()}" '
        f'AND sleep.interval.civil_end_time < "{end_date_exclusive.isoformat()}"'
    )
    points = _list_all(
        client,
        "sleep",
        filter_expression,
        reconciled=True,
        data_source_family=WEARABLES,
        page_size=25,
    )

    rows: list[dict[str, Any]] = []
    for point in points:
        value = point.get("sleep", {})
        wake_time = _interval_end_timestamp(value.get("interval"))
        if wake_time is None:
            continue

        summary = value.get("summary", {})
        metadata = value.get("metadata", {})
        stages = {
            stage.get("type", "UNKNOWN"): int(stage.get("minutes", 0))
            for stage in summary.get("stagesSummary", [])
        }
        rows.append(
            {
                "date": wake_time.normalize(),
                "wake_time": wake_time,
                "minutes_asleep": int(summary.get("minutesAsleep", 0)),
                "minutes_awake": int(summary.get("minutesAwake", 0)),
                "deep_minutes": stages.get("DEEP", 0),
                "rem_minutes": stages.get("REM", 0),
                "light_minutes": stages.get("LIGHT", 0),
                "is_nap": bool(metadata.get("nap", False)),
                "processed": bool(metadata.get("processed", False)),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "minutes_asleep",
                "minutes_awake",
                "deep_minutes",
                "rem_minutes",
                "light_minutes",
                "nap_minutes",
            ]
        )

    frame = pd.DataFrame(rows).sort_values("wake_time")
    main = frame[~frame["is_nap"]].copy()
    naps = frame[frame["is_nap"]].copy()

    # Keep the longest non-nap session for each wake date.
    if not main.empty:
        main = (
            main.sort_values(["date", "minutes_asleep"])
            .groupby("date", as_index=False)
            .tail(1)
        )

    nap_totals = (
        naps.groupby("date", as_index=False)["minutes_asleep"]
        .sum()
        .rename(columns={"minutes_asleep": "nap_minutes"})
        if not naps.empty
        else pd.DataFrame(columns=["date", "nap_minutes"])
    )

    if main.empty:
        result = nap_totals.copy()
        for column in [
            "minutes_asleep",
            "minutes_awake",
            "deep_minutes",
            "rem_minutes",
            "light_minutes",
        ]:
            result[column] = pd.NA
    else:
        result = main.merge(nap_totals, on="date", how="left")

    result["nap_minutes"] = pd.to_numeric(
        result.get("nap_minutes", 0), errors="coerce"
    ).fillna(0)
    result["sleep_hours"] = pd.to_numeric(
        result.get("minutes_asleep"), errors="coerce"
    ) / 60

    columns = [
        "date",
        "sleep_hours",
        "minutes_asleep",
        "minutes_awake",
        "deep_minutes",
        "rem_minutes",
        "light_minutes",
        "nap_minutes",
    ]
    return result[columns].sort_values("date")


def load_nutrition(
    client: GoogleHealthClient,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Daily nutrition totals using Cronometer as the preferred source.

    Cronometer can export individual foods through Health Connect and also
    export a daily nutrient total through the legacy Fitbit Web API. Whenever
    Cronometer Health Connect foods exist for a day, this loader keeps those
    detailed records and excludes Fitbit Web API nutrition summaries. Fitbit
    nutrition is retained only on days with no Cronometer food records.
    """
    end_date_exclusive = end_date + timedelta(days=1)
    filter_expression = (
        f'nutrition_log.interval.civil_start_time >= '
        f'"{start_date.isoformat()}" '
        f'AND nutrition_log.interval.civil_start_time < '
        f'"{end_date_exclusive.isoformat()}"'
    )
    points = _list_all(
        client,
        "nutrition-log",
        filter_expression,
        reconciled=False,
    )

    item_rows: list[dict[str, Any]] = []
    for point in points:
        value = point.get("nutritionLog", {})
        logged_at = _interval_start_timestamp(value.get("interval"))
        if logged_at is None:
            continue

        nutrients = {
            nutrient.get("nutrient"): float(
                nutrient.get("quantity", {}).get("grams", 0) or 0
            )
            for nutrient in value.get("nutrients", [])
        }
        source = point.get("dataSource", {})
        application = source.get("application", {})
        platform = source.get("platform", "")
        package_name = application.get("packageName", "")

        item_rows.append(
            {
                "date": logged_at.normalize(),
                "calories_kcal": float(
                    value.get("energy", {}).get("kcal", 0) or 0
                ),
                "protein_g": nutrients.get("PROTEIN", 0.0),
                "carbs_g": float(
                    value.get("totalCarbohydrate", {}).get("grams", 0) or 0
                ),
                "fat_g": float(
                    value.get("totalFat", {}).get("grams", 0) or 0
                ),
                "is_cronometer_health_connect": (
                    platform == "HEALTH_CONNECT"
                    and package_name == "com.cronometer.android.gold"
                ),
                "is_fitbit_web_summary": platform == "FITBIT_WEB_API",
            }
        )

    output_columns = [
        "date",
        "calories_kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        "excluded_fitbit_summary_records",
        "nutrition_dedup_applied",
        "nutrition_overlap_warning",
    ]
    if not item_rows:
        return pd.DataFrame(columns=output_columns)

    items = pd.DataFrame(item_rows)

    def totals(frame: pd.DataFrame) -> dict[str, float]:
        return {
            field: float(frame[field].sum())
            for field in (
                "calories_kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
            )
        }

    daily_rows: list[dict[str, Any]] = []
    for day, day_items in items.groupby("date", sort=True):
        cronometer_items = day_items[
            day_items["is_cronometer_health_connect"]
        ]
        fitbit_summaries = day_items[day_items["is_fitbit_web_summary"]]

        dedup_applied = False
        overlap_warning = False
        excluded_records = 0
        kept_items = day_items

        if not cronometer_items.empty and not fitbit_summaries.empty:
            # Cronometer Health Connect foods are the source of truth for this
            # dashboard. Fitbit Web API nutrition entries are daily summaries
            # of the same Cronometer data and may be stale or only partially
            # synchronized, so exclude them whenever detailed Cronometer foods
            # are available for that date.
            kept_items = day_items[
                ~day_items["is_fitbit_web_summary"]
            ]
            excluded_records = int(len(fitbit_summaries))
            dedup_applied = True

        kept_totals = totals(kept_items)
        daily_rows.append(
            {
                "date": day,
                **kept_totals,
                "excluded_fitbit_summary_records": excluded_records,
                "nutrition_dedup_applied": dedup_applied,
                "nutrition_overlap_warning": overlap_warning,
            }
        )

    return pd.DataFrame(daily_rows, columns=output_columns).sort_values("date")

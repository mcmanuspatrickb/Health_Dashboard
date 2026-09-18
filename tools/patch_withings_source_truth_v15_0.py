from pathlib import Path

path = Path("streamlit_app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match, found {count}: {old[:140]!r}")
    text = text.replace(old, new, 1)


# Add a small adapter so Withings direct scale data becomes the dashboard's
# canonical body-composition frame wherever weight/body-fat are needed.
replace_once(
    '''def trend_window(frame: pd.DataFrame, date_column: str = "date", days: int = 90) -> pd.DataFrame:\n    """Filter a time series to the selected dashboard trend period."""\n    if frame.empty or date_column not in frame.columns:\n        return frame.copy()\n    cutoff = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=int(days))\n    dates = pd.to_datetime(frame[date_column], errors="coerce")\n    return frame.loc[dates.notna() & dates.dt.date.ge(cutoff)].copy()\n\n\nst.title("🏋️ Training, Recovery & Goal Dashboard")\n''',
    '''def trend_window(frame: pd.DataFrame, date_column: str = "date", days: int = 90) -> pd.DataFrame:\n    """Filter a time series to the selected dashboard trend period."""\n    if frame.empty or date_column not in frame.columns:\n        return frame.copy()\n    cutoff = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=int(days))\n    dates = pd.to_datetime(frame[date_column], errors="coerce")\n    return frame.loc[dates.notna() & dates.dt.date.ge(cutoff)].copy()\n\n\ndef withings_body_source(scale: pd.DataFrame) -> pd.DataFrame:\n    """Canonical weight/body-fat frame from direct Withings measurements."""\n    columns = ["date", "weight_kg", "body_fat_pct"]\n    if scale.empty or "date" not in scale.columns:\n        return pd.DataFrame(columns=columns)\n\n    available = [column for column in columns if column in scale.columns]\n    frame = scale[available].copy()\n    for column in columns:\n        if column not in frame.columns:\n            frame[column] = pd.NA\n\n    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")\n    frame["weight_kg"] = pd.to_numeric(frame["weight_kg"], errors="coerce")\n    frame["body_fat_pct"] = pd.to_numeric(frame["body_fat_pct"], errors="coerce")\n    return (\n        frame[columns]\n        .dropna(subset=["date"])\n        .sort_values("date")\n        .reset_index(drop=True)\n    )\n\n\nst.title("🏋️ Training, Recovery & Goal Dashboard")\n'''
)

# Make source-of-truth behavior explicit in the dashboard description.
replace_once(
    '''st.caption(\n    "Dashboard powered by Hevy, Google Health/Cronometer, and direct Withings metrics."\n)\n''',
    '''st.caption(\n    "Source of truth: direct Withings for Withings-measured body metrics; "\n    "Google Health/Cronometer for other health data; Hevy for training."\n)\n'''
)

# Overview: direct Withings supplies canonical weight/body-fat instead of the
# Google Health mirror. Google Health remains responsible for steps/sleep/etc.
replace_once(
    '''    body = safe_frame(\n        "Google Health body composition",\n        lambda: load_google_health_body(days=trend_days),\n        source_status,\n    )\n''',
    '''    withings_measurements = safe_frame(\n        "Withings health metrics",\n        lambda: load_withings_metrics(days=max(365, trend_days)),\n        source_status,\n    )\n    withings_scale = build_withings_scale_sessions(\n        withings_measurements\n    )\n    body = withings_body_source(withings_scale)\n'''
)

# Strength goal calculations can use current body weight directly from Withings
# when any BW-relative goal is present.
replace_once(
    '''elif selected_section == "Strength Progress":\n    performance_history = build_exercise_performance_history(df)\n    goal_progress = build_goal_progress(\n''',
    '''elif selected_section == "Strength Progress":\n    performance_history = build_exercise_performance_history(df)\n    withings_measurements = safe_frame(\n        "Withings health metrics",\n        lambda: load_withings_metrics(days=365),\n        source_status,\n    )\n    withings_scale = build_withings_scale_sessions(\n        withings_measurements\n    )\n    body = withings_body_source(withings_scale)\n    goal_progress = build_goal_progress(\n'''
)

# Body Composition: remove the Google Health body mirror and use direct Withings
# as the authoritative weight/body-fat source.
replace_once(
    '''elif selected_section == "Body Composition & Nutrition":\n    body = safe_frame(\n        "Google Health body composition",\n        lambda: load_google_health_body(days=365),\n        source_status,\n    )\n    nutrition = safe_frame(\n''',
    '''elif selected_section == "Body Composition & Nutrition":\n    nutrition = safe_frame(\n'''
)

replace_once(
    '''    withings_scale = build_withings_scale_sessions(\n        withings_measurements\n    )\n    goal_progress = build_goal_progress(\n''',
    '''    withings_scale = build_withings_scale_sessions(\n        withings_measurements\n    )\n    body = withings_body_source(withings_scale)\n    goal_progress = build_goal_progress(\n'''
)

# Update the explanatory caption in Overall Health Trends.
replace_once(
    '''    st.caption(\n        "Weight and body-fat percentage use Google Health. Muscle mass %, water %, "\n        "visceral fat, and metabolic age use direct Withings measurements."\n    )\n''',
    '''    st.caption(\n        "Direct Withings is the source of truth for the body metrics shown here. "\n        "Google Health remains the source for non-Withings health metrics elsewhere."\n    )\n'''
)

# The Overall Health Trends weight/body-fat views now inherit direct Withings
# through the canonical `body` frame. Draw weight last and thicker so it remains
# visually on top of the percentage traces.
weight_block = '''        if not weight_view.empty:\n            overall_fig.add_trace(\n                go.Scatter(\n                    x=weight_view["date"],\n                    y=weight_view["weight_kg"],\n                    mode="lines+markers",\n                    name="Weight (kg)",\n                    hovertemplate=(\n                        "%{x|%d %b %Y}<br>Weight: %{y:.2f} kg<extra></extra>"\n                    ),\n                ),\n                secondary_y=False,\n            )\n\n'''
replace_once(weight_block, '')

insert_after = '''            overall_fig.add_trace(\n                go.Scatter(\n                    x=frame["date"],\n                    y=frame[column],\n                    mode="lines+markers",\n                    name=label,\n                    hovertemplate=(\n                        f"%{{x|%d %b %Y}}<br>{label}: {value_text}<extra></extra>"\n                    ),\n                ),\n                secondary_y=True,\n            )\n\n'''
replacement = insert_after + '''        if not weight_view.empty:\n            overall_fig.add_trace(\n                go.Scatter(\n                    x=weight_view["date"],\n                    y=weight_view["weight_kg"],\n                    mode="lines+markers",\n                    name="Weight (kg)",\n                    line={"width": 4},\n                    marker={"size": 6},\n                    legendrank=1,\n                    hovertemplate=(\n                        "%{x|%d %b %Y}<br>Weight: %{y:.2f} kg<extra></extra>"\n                    ),\n                ),\n                secondary_y=False,\n            )\n\n'''
replace_once(insert_after, replacement)

# Increase the visual separation: weight occupies a tighter upper band while
# body-fat/water use a broader 0-90% axis. Keep both goal lines visible.
replace_once(
    '''        weight_axis_range = None\n        if not weight_view.empty:\n            weight_values = pd.to_numeric(\n                weight_view["weight_kg"], errors="coerce"\n            ).dropna()\n            if not weight_values.empty:\n                weight_low = min(90.0, float(weight_values.min()))\n                weight_high = float(weight_values.max())\n                spread = max(5.0, weight_high - weight_low)\n                weight_axis_range = [\n                    max(0.0, weight_low - max(2.0, spread * 0.08)),\n                    weight_high + max(2.0, spread * 0.12),\n                ]\n\n        overall_fig.update_yaxes(\n            title_text="Weight (kg)",\n            range=weight_axis_range,\n            secondary_y=False,\n        )\n        overall_fig.update_yaxes(\n            title_text="Body fat / water (%)",\n            range=[0, 60],\n            secondary_y=True,\n        )\n''',
    '''        weight_axis_range = None\n        if not weight_view.empty:\n            weight_values = pd.to_numeric(\n                weight_view["weight_kg"], errors="coerce"\n            ).dropna()\n            if not weight_values.empty:\n                weight_low = float(weight_values.min())\n                weight_high = float(weight_values.max())\n                weight_axis_range = [\n                    min(88.0, weight_low - 1.5),\n                    weight_high + 2.0,\n                ]\n\n        overall_fig.update_yaxes(\n            title_text="Weight (kg)",\n            range=weight_axis_range,\n            secondary_y=False,\n        )\n        overall_fig.update_yaxes(\n            title_text="Body fat / water (%)",\n            range=[0, 90],\n            secondary_y=True,\n        )\n'''
)

path.write_text(text, encoding="utf-8")

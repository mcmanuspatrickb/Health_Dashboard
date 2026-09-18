from __future__ import annotations

import json
from pathlib import Path


APP_PATH = Path("streamlit_app.py")
GOALS_PATH = Path("data/fitness_goals.json")


app = APP_PATH.read_text(encoding="utf-8")

# Correct the dashboard-level source description now that direct Withings data
# is intentionally used for advanced body-composition metrics.
app = app.replace(
    'st.caption(\n    "Dashboard powered by Hevy, Fitbit/Google Health and Cronometer. "\n    "Direct Withings has been removed; body composition uses the Google Health mirror."\n)\n',
    'st.caption(\n    "Dashboard powered by Hevy, Google Health/Cronometer, and direct Withings metrics."\n)\n',
    1,
)

# Remove the estimated-muscle-mass card from Overview & Goals.
overview_start = app.index('    row1 = st.columns(5)\n')
overview_end = app.index('    row2 = st.columns(4)\n', overview_start)
overview_block = '''    row1 = st.columns(4)
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
    row1[2].metric("Workouts — last 7 days", len(week_sessions))
    row1[3].metric(
        "Weekly session load",
        (
            f"{pd.to_numeric(week_sessions.get('session_load'), errors='coerce').sum():,.0f}"
            if not week_sessions.empty else "—"
        ),
    )

'''
app = app[:overview_start] + overview_block + app[overview_end:]

# Replace the two separate Google Health / Withings body-composition panels with
# one concise Overall Health Trends panel containing only the requested metrics.
body_start_marker = '    st.subheader("Google Health body composition")\n'
body_end_marker = '    st.subheader("Body measurements")\n'
body_start = app.index(body_start_marker)
body_end = app.index(body_end_marker, body_start)

health_block = '''    st.subheader("Overall Health Trends")
    st.caption(
        "Weight and body-fat percentage use Google Health. Muscle mass %, water %, "
        "visceral fat, and metabolic age use direct Withings measurements."
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

    health_trend_defs = {
        "Weight": (body, "weight_kg", "kg"),
        "Body fat %": (body, "body_fat_pct", "%"),
        "Muscle mass %": (withings_scale, "muscle_mass_pct", "%"),
        "Water %": (withings_scale, "water_pct", "%"),
        "Visceral fat": (withings_scale, "visceral_fat_index", "index"),
        "Metabolic age": (withings_scale, "metabolic_age_years", "years"),
    }

    selected_health_metric = st.selectbox(
        "Health metric trend",
        list(health_trend_defs.keys()),
        index=0,
        key="overall_health_metric_trend",
    )
    metric_source, metric_column, metric_unit = health_trend_defs[
        selected_health_metric
    ]

    if metric_source.empty or metric_column not in metric_source.columns:
        st.info(
            f"No {selected_health_metric.lower()} data is available."
        )
    else:
        metric_trend = metric_source[
            ["date", metric_column]
        ].dropna(subset=[metric_column]).copy()
        metric_trend = trend_window(
            metric_trend,
            "date",
            trend_days,
        )

        if metric_trend.empty:
            st.info(
                f"No {selected_health_metric.lower()} data is available "
                f"in the selected {trend_days}-day period."
            )
        else:
            health_fig = px.line(
                metric_trend,
                x="date",
                y=metric_column,
                markers=True,
                labels={
                    "date": "Date",
                    metric_column: (
                        f"{selected_health_metric} ({metric_unit})"
                    ),
                },
            )
            if selected_health_metric == "Weight":
                health_fig.add_hline(
                    y=90,
                    line_dash="dash",
                    annotation_text="90 kg goal",
                )
            elif selected_health_metric == "Body fat %":
                health_fig.add_hline(
                    y=15,
                    line_dash="dash",
                    annotation_text="15% body-fat goal",
                )
            health_fig.update_layout(
                height=410,
                xaxis_tickformat="%d %b %Y",
            )
            st.plotly_chart(
                health_fig,
                use_container_width=True,
            )

    source_mode = withings_measurements.attrs.get(
        "source_mode", "unknown"
    )
    st.caption(
        f"Withings source mode: {source_mode}. "
        f"Trend chart window: {trend_days} days."
    )

'''
app = app[:body_start] + health_block + app[body_end:]

# The proxy calculations are no longer displayed. Stop building them in the two
# sections that previously used them, while leaving the helper available for
# backward compatibility with older code/data.
app = app.replace(
    '    body_calc = prepare_body_calculations(body, body_proxy)\n',
    '',
)

# Remove obsolete proxy wording from the footer.
app = app.replace(
    '    "Goal comparisons are descriptive training tools. Estimated 1RM, calculated fat mass, the Withings-compatible muscle-mass proxy, and recovery associations are estimates, not medical assessments."\n',
    '    "Goal comparisons are descriptive training tools. Estimated 1RM and recovery associations are estimates, not medical assessments."\n',
    1,
)

APP_PATH.write_text(app, encoding="utf-8")

# Remove the estimated-muscle-mass percentage goal so it no longer appears in
# Overview or Body Composition goal tables.
goals_payload = json.loads(GOALS_PATH.read_text(encoding="utf-8"))
goals_payload["goals"] = [
    goal
    for goal in goals_payload.get("goals", [])
    if goal.get("metric") != "estimated_muscle_mass_pct"
]
goals_payload["notes"] = [
    note
    for note in goals_payload.get("notes", [])
    if "estimated muscle mass" not in str(note).lower()
    and not str(note).lower().startswith("mm means")
]
GOALS_PATH.write_text(
    json.dumps(goals_payload, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

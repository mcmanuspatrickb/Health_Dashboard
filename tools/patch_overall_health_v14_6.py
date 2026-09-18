from pathlib import Path


path = Path("streamlit_app.py")
text = path.read_text(encoding="utf-8")

start_marker = '    st.subheader("Overall Health Trends")\n'
end_marker = '    st.subheader("Body measurements")\n'

start = text.index(start_marker)
end = text.index(end_marker, start)

replacement = '''    st.subheader("Overall Health Trends")
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
        ("Muscle mass %", "muscle_mass_pct", "%"),
        ("Water %", "water_pct", "%"),
        ("Visceral fat", "visceral_fat_index", "index"),
        ("Metabolic age", "metabolic_age_years", "years"),
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

        if not weight_view.empty:
            overall_fig.add_trace(
                go.Scatter(
                    x=weight_view["date"],
                    y=weight_view["weight_kg"],
                    mode="lines+markers",
                    name="Weight (kg)",
                    hovertemplate=(
                        "%{x|%d %b %Y}<br>Weight: %{y:.2f} kg<extra></extra>"
                    ),
                ),
                secondary_y=False,
            )

        if not fat_view.empty:
            overall_fig.add_trace(
                go.Scatter(
                    x=fat_view["date"],
                    y=fat_view["body_fat_pct"],
                    mode="lines+markers",
                    name="Body fat (%)",
                    hovertemplate=(
                        "%{x|%d %b %Y}<br>Body fat: %{y:.2f}%<extra></extra>"
                    ),
                ),
                secondary_y=True,
            )

        for label, (frame, column, unit) in withings_views.items():
            if frame.empty:
                continue
            if unit == "%":
                value_text = "%{y:.2f}%"
            elif unit == "years":
                value_text = "%{y:.0f} years"
            else:
                value_text = "%{y:.2f}"
            overall_fig.add_trace(
                go.Scatter(
                    x=frame["date"],
                    y=frame[column],
                    mode="lines+markers",
                    name=label,
                    hovertemplate=(
                        f"%{{x|%d %b %Y}}<br>{label}: {value_text}<extra></extra>"
                    ),
                ),
                secondary_y=True,
            )

        overall_fig.add_hline(
            y=90,
            line_dash="dash",
            annotation_text="90 kg goal",
            secondary_y=False,
        )
        overall_fig.add_hline(
            y=15,
            line_dash="dash",
            annotation_text="15% body-fat goal",
            secondary_y=True,
        )
        overall_fig.update_xaxes(
            title_text="Date",
            tickformat="%d %b",
        )
        overall_fig.update_yaxes(
            title_text="Weight (kg)",
            secondary_y=False,
        )
        overall_fig.update_yaxes(
            title_text="Body composition value",
            secondary_y=True,
        )
        overall_fig.update_layout(
            height=540,
            margin={"l": 55, "r": 65, "t": 70, "b": 55},
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "center",
                "x": 0.5,
            },
            hovermode="x unified",
        )
        st.plotly_chart(
            overall_fig,
            use_container_width=True,
        )

    st.subheader("Withings advanced body composition")
    st.caption(
        "Direct Withings measurements. The trend menu below is built from the "
        "numeric Withings metrics actually available in your stored data, plus "
        "derived muscle-mass % and water %."
    )

    if withings_measurements.empty:
        st.info("No direct Withings measurements are available.")
    else:
        direct_muscle = latest_withings_value(
            withings_scale, "muscle_mass_kg"
        )
        bmr = latest_withings_value(
            withings_scale, "bmr_kcal_day"
        )

        withings_cards = st.columns(5)
        withings_cards[0].metric(
            "Direct muscle mass",
            f"{direct_muscle:.2f} kg"
            if direct_muscle is not None else "—",
        )
        withings_cards[1].metric(
            "Direct muscle mass %",
            f"{direct_muscle_pct:.2f}%"
            if direct_muscle_pct is not None else "—",
        )
        withings_cards[2].metric(
            "Visceral fat index",
            f"{visceral:.1f}" if visceral is not None else "—",
        )
        withings_cards[3].metric(
            "Water %",
            f"{water_pct:.1f}%" if water_pct is not None else "—",
        )
        withings_cards[4].metric(
            "BMR",
            f"{bmr:,.0f} kcal/day" if bmr is not None else "—",
        )

        available_withings_metrics = {}

        preferred_raw_order = [
            "Weight",
            "Body fat ratio",
            "Fat-free mass",
            "Fat mass",
            "Muscle mass",
            "Water mass",
            "Bone mass",
            "Visceral fat index",
            "Basal metabolic rate",
            "Metabolic age",
            "Vascular age",
            "Pulse wave velocity",
            "Nerve Health Score — left foot",
            "Nerve Health Score — right foot",
            "Nerve Health Score — feet max",
            "Nerve Response Score",
            "Extracellular water",
            "Intracellular water",
            "Electrochemical skin conductance",
            "Systolic blood pressure",
            "Diastolic blood pressure",
            "Heart rate / pulse",
            "Height",
        ]

        raw_numeric = withings_measurements.copy()
        if "value" in raw_numeric.columns:
            raw_numeric["value"] = pd.to_numeric(
                raw_numeric["value"], errors="coerce"
            )
            raw_numeric = raw_numeric.dropna(subset=["value"])
        else:
            raw_numeric = pd.DataFrame()

        raw_metric_names = (
            set(raw_numeric["metric"].dropna().astype(str))
            if not raw_numeric.empty and "metric" in raw_numeric.columns
            else set()
        )

        ordered_raw = [
            name for name in preferred_raw_order
            if name in raw_metric_names
        ]
        ordered_raw.extend(
            sorted(raw_metric_names - set(ordered_raw))
        )

        for metric_name in ordered_raw:
            rows = raw_numeric[
                raw_numeric["metric"].astype(str).eq(metric_name)
            ]
            if rows.empty:
                continue
            units = rows.get("unit", pd.Series(dtype=object)).dropna().astype(str)
            unit = units.iloc[-1] if not units.empty else ""
            available_withings_metrics[metric_name] = (
                "raw", metric_name, unit
            )

        for label, column, unit in [
            ("Muscle mass %", "muscle_mass_pct", "%"),
            ("Water %", "water_pct", "%"),
        ]:
            if (
                not withings_scale.empty
                and column in withings_scale.columns
                and pd.to_numeric(
                    withings_scale[column], errors="coerce"
                ).notna().any()
            ):
                available_withings_metrics[label] = (
                    "derived", column, unit
                )

        if not available_withings_metrics:
            st.info("No numeric Withings metrics are available for charting.")
        else:
            selected_withings_metric = st.selectbox(
                "Withings metric trend",
                list(available_withings_metrics.keys()),
                index=0,
                key="withings_metric_trend",
            )
            metric_kind, metric_key, metric_unit = available_withings_metrics[
                selected_withings_metric
            ]

            if metric_kind == "raw":
                metric_trend = raw_numeric[
                    raw_numeric["metric"].astype(str).eq(metric_key)
                ][["measured_at", "value"]].copy()
                metric_trend = trend_window(
                    metric_trend,
                    "measured_at",
                    trend_days,
                )
                x_column = "measured_at"
                y_column = "value"
            else:
                metric_trend = withings_scale[
                    ["date", metric_key]
                ].dropna(subset=[metric_key]).copy()
                metric_trend = trend_window(
                    metric_trend,
                    "date",
                    trend_days,
                )
                x_column = "date"
                y_column = metric_key

            if metric_trend.empty:
                st.info(
                    f"No {selected_withings_metric.lower()} data is available "
                    f"in the selected {trend_days}-day period."
                )
            else:
                withings_fig = px.line(
                    metric_trend,
                    x=x_column,
                    y=y_column,
                    markers=True,
                    labels={
                        x_column: "Date",
                        y_column: (
                            f"{selected_withings_metric} ({metric_unit})"
                            if metric_unit else selected_withings_metric
                        ),
                    },
                )
                withings_fig.update_layout(
                    height=390,
                    xaxis_tickformat="%d %b %Y",
                )
                st.plotly_chart(
                    withings_fig,
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

text = text[:start] + replacement + text[end:]
path.write_text(text, encoding="utf-8")

from pathlib import Path

path = Path("streamlit_app.py")
text = path.read_text(encoding="utf-8")

import_anchor = "from recomposition import build_recomposition_summary\n"
import_replacement = import_anchor + '''from grip_data import (
    delete_grip_measurement,
    insert_grip_measurement,
    load_grip_measurements,
)
'''
if "from grip_data import (" not in text:
    if import_anchor not in text:
        raise SystemExit("Grip import anchor not found")
    text = text.replace(import_anchor, import_replacement, 1)

empty_anchor = "renpho_measurements = pd.DataFrame()\nperformance_history = pd.DataFrame()\n"
empty_replacement = "renpho_measurements = pd.DataFrame()\ngrip_measurements = pd.DataFrame()\nperformance_history = pd.DataFrame()\n"
if "grip_measurements = pd.DataFrame()" not in text:
    if empty_anchor not in text:
        raise SystemExit("Grip empty-frame anchor not found")
    text = text.replace(empty_anchor, empty_replacement, 1)

load_anchor = '''    hevy_measurements = safe_frame(
        "Hevy body measurements",
        load_hevy_body_measurements,
        source_status,
    )
    withings_measurements = safe_frame(
'''
load_replacement = '''    hevy_measurements = safe_frame(
        "Hevy body measurements",
        load_hevy_body_measurements,
        source_status,
    )
    grip_measurements = safe_frame(
        "Grip measurements",
        load_grip_measurements,
        source_status,
    )
    withings_measurements = safe_frame(
'''
# Replace only the occurrence in the recomposition loading branch.
section_start = text.find('elif selected_section == "Fat Loss & Muscle Preservation":')
section_end = text.find('elif selected_section == "Endurance":', section_start)
if section_start < 0 or section_end < 0:
    raise SystemExit("Recomposition load branch not found")
section = text[section_start:section_end]
if '"Grip measurements"' not in section:
    if load_anchor not in section:
        raise SystemExit("Grip load anchor not found")
    section = section.replace(load_anchor, load_replacement, 1)
    text = text[:section_start] + section + text[section_end:]

render_anchor = '''        with st.expander("Method and limitations"):
            st.markdown(
'''
grip_block = r'''        st.subheader("Grip strength")
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

'''
# Add just before the existing method expander in the recomposition render branch.
render_start = text.find('elif selected_section == "Fat Loss & Muscle Preservation":', section_end)
render_end = text.find('elif selected_section == "Body Composition & Nutrition":', render_start)
if render_start < 0 or render_end < 0:
    raise SystemExit("Recomposition render branch not found")
render_section = text[render_start:render_end]
if 'st.subheader("Grip strength")' not in render_section:
    if render_anchor not in render_section:
        raise SystemExit("Grip render anchor not found")
    render_section = render_section.replace(render_anchor, grip_block + render_anchor, 1)
    text = text[:render_start] + render_section + text[render_end:]

path.write_text(text, encoding="utf-8")
print("Patched grip tracking into streamlit_app.py")

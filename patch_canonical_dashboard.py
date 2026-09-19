from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parent

# Add true waist interval to the exploratory recomposition summary.
p = root / "recomposition.py"
text = p.read_text(encoding="utf-8")
old = '''    waist = waist_history(hevy_measurements)\n    waist_delta = None\n    if len(waist) >= 2:\n        latest_waist = float(waist.iloc[-1]["waist_cm"])\n        cutoff = pd.Timestamp(end_date) - pd.Timedelta(days=28)\n        earlier = waist[waist["date"] <= cutoff]\n        if not earlier.empty:\n            waist_delta = latest_waist - float(earlier.iloc[-1]["waist_cm"])\n'''
new = '''    waist = waist_history(hevy_measurements)\n    waist_delta = None\n    waist_span_days = None\n    if len(waist) >= 2:\n        latest_row = waist.iloc[-1]\n        latest_waist = float(latest_row["waist_cm"])\n        latest_waist_date = pd.Timestamp(latest_row["date"])\n        cutoff = pd.Timestamp(end_date) - pd.Timedelta(days=28)\n        earlier = waist[waist["date"] <= cutoff]\n        if not earlier.empty:\n            earlier_row = earlier.iloc[-1]\n            waist_delta = latest_waist - float(earlier_row["waist_cm"])\n            waist_span_days = int((latest_waist_date - pd.Timestamp(earlier_row["date"])).days)\n'''
text = replace_once(text, old, new, "recomposition waist interval")
text = replace_once(
    text,
    '        "waist_change_28d": waist_delta,\n',
    '        "waist_change_28d": waist_delta,\n        "waist_span_days": waist_span_days,\n',
    "recomposition waist span summary",
)
p.write_text(text, encoding="utf-8")

# Patch the Streamlit UI to consume the canonical weekly coaching snapshot.
p = root / "streamlit_app.py"
text = p.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from recomposition import build_recomposition_summary\n",
    "from recomposition import build_recomposition_summary\nfrom coaching_snapshot import load_latest_coaching_snapshot\n",
    "dashboard canonical import",
)
text = replace_once(
    text,
    '            fig.add_hline(y=8000, line_dash="dash", annotation_text="8,000")\n',
    '            fig.add_hline(y=7000, line_dash="dash", annotation_text="7,000 floor")\n            fig.add_hline(y=8000, line_dash="dot", annotation_text="8,000 preferred")\n',
    "step floor/preferred lines",
)
text = replace_once(
    text,
    '''    recomp = build_recomposition_summary(\n        withings_scale=withings_scale,\n''',
    '''    canonical_snapshot = {}\n    try:\n        canonical_snapshot = load_latest_coaching_snapshot() or {}\n    except Exception as exc:\n        st.caption(f"Canonical weekly coaching snapshot is temporarily unavailable: {exc}")\n\n    recomp = build_recomposition_summary(\n        withings_scale=withings_scale,\n''',
    "load canonical snapshot",
)

analysis_caption = '''        st.caption(f"Latest complete analysis date: {analysis_end.strftime('%d %b %Y')}")\n\n        cards = st.columns(6)\n'''
canonical_panel = '''        st.caption(f"Latest complete analysis date: {analysis_end.strftime('%d %b %Y')}")\n\n        if canonical_snapshot:\n            st.subheader("Canonical coaching status")\n            st.caption(\n                "This is the authoritative weekly interpretation shared with the email system. "\n                "The live charts below remain exploratory views of the underlying measurements."\n            )\n            cstates = canonical_snapshot.get("states", {})\n            cdecision = canonical_snapshot.get("decision", {})\n            cenergy = canonical_snapshot.get("energy", {})\n            ccols = st.columns(6)\n            ccols[0].metric("Fat loss", str(cstates.get("fat_loss", "—")).replace("_", " ").title())\n            ccols[1].metric("Muscle preservation", str(cstates.get("muscle_preservation", "—")).replace("_", " ").title())\n            ccols[2].metric("Recovery", str(cstates.get("recovery", "—")).replace("_", " ").title())\n            ccols[3].metric("Training", str(cstates.get("training", "—")).replace("_", " ").title())\n            ccols[4].metric(\n                "Calorie action",\n                f"{str(cdecision.get('action', 'HOLD')).title()} {float(cdecision.get('calorie_adjustment') or 0):+.0f}",\n                f"Target {float(cdecision.get('target_intake')):.0f} kcal/day" if cdecision.get("target_intake") is not None else None,\n            )\n            ccols[5].metric(\n                "Planning maintenance",\n                f"{float(cenergy.get('planning_tdee')):,.0f} kcal/day" if cenergy.get("planning_tdee") is not None else "—",\n                (f"{float(cenergy.get('planning_range_low')):,.0f}-{float(cenergy.get('planning_range_high')):,.0f}"\n                 if cenergy.get("planning_range_low") is not None and cenergy.get("planning_range_high") is not None else None),\n            )\n            priorities = canonical_snapshot.get("priorities", []) or []\n            if priorities:\n                st.markdown("**Current priorities:** " + " · ".join(str(item) for item in priorities))\n            training_groups = canonical_snapshot.get("training_dose", {}).get("groups", []) or []\n            if training_groups:\n                with st.expander("Canonical training dose by primary muscle group"):\n                    dose = pd.DataFrame(training_groups)\n                    dose = dose[dose["muscle_group"] != "Other / unmapped"] if "muscle_group" in dose.columns else dose\n                    st.dataframe(dose, use_container_width=True, hide_index=True)\n                    st.caption(canonical_snapshot.get("training_dose", {}).get("method", ""))\n\n        cards = st.columns(6)\n'''
text = replace_once(text, analysis_caption, canonical_panel, "canonical status panel")

text = text.replace('"28d weight trend"', '"Weight change in 28d window"', 1)
text = text.replace('"28d fat-mass trend"', '"Fat-mass change in 28d window"', 1)
text = text.replace('"28d fat-free-mass trend"', '"FFM change in 28d window"', 1)

old_second = '''        second[1].metric(\n            "BIA fat share of loss",\n            f"{summary.get('fat_share_of_loss_pct'):.0f}%"\n            if summary.get("fat_share_of_loss_pct") is not None else "—",\n        )\n        second[2].metric(\n            "Waist — ~28d change",\n            f"{summary.get('waist_change_28d'):+.1f} cm"\n            if summary.get("waist_change_28d") is not None else "—",\n        )\n'''
new_second = '''        canonical_adherence = canonical_snapshot.get("adherence", {}) if canonical_snapshot else {}\n        protein_logged = canonical_adherence.get("protein_days_logged", 0)\n        protein_met = canonical_adherence.get("protein_days_met", 0)\n        second[1].metric(\n            "Protein target days",\n            f"{protein_met}/{protein_logged}" if protein_logged else "—",\n        )\n        waist_span = summary.get("waist_span_days")\n        second[2].metric(\n            f"Waist change ({waist_span}d)" if waist_span is not None else "Waist change",\n            f"{summary.get('waist_change_28d'):+.1f} cm"\n            if summary.get("waist_change_28d") is not None else "—",\n        )\n'''
text = replace_once(text, old_second, new_second, "de-emphasize BIA fat share")

protein_caption_marker = '''        low = summary.get("protein_low")\n        high = summary.get("protein_high")\n'''
protein_caption_new = '''        if summary.get("fat_share_of_loss_pct") is not None:\n            st.caption(\n                f"Experimental BIA-derived fat share of scale loss: ~{summary.get('fat_share_of_loss_pct'):.0f}%. "\n                "This is supporting context only because both fat and fat-free compartments are hydration-sensitive."\n            )\n\n        low = summary.get("protein_low")\n        high = summary.get("protein_high")\n'''
text = replace_once(text, protein_caption_marker, protein_caption_new, "BIA fat share caption")

text = replace_once(
    text,
    '        interpretations = recomp.get("interpretation", [])\n',
    '        interpretations = (canonical_snapshot.get("interpretation", []) if canonical_snapshot else []) or recomp.get("interpretation", [])\n',
    "canonical combined interpretation",
)

text = replace_once(
    text,
    '        strength = recomp.get("strength", pd.DataFrame()).copy()\n        st.subheader("4-week strength cross-check")\n',
    '''        canonical_lifts = canonical_snapshot.get("strength", {}).get("lifts", []) if canonical_snapshot else []\n        if canonical_lifts:\n            strength = pd.DataFrame(canonical_lifts).rename(columns={\n                "label": "Lift",\n                "current_best_e1rm": "Current 4w best e1RM",\n                "prior_best_e1rm": "Prior 4w best e1RM",\n                "change_e1rm": "Change kg",\n                "direction": "Direction",\n                "current_observations": "Current observations",\n                "prior_observations": "Prior observations",\n            })\n            keep = [\n                "Lift", "Current 4w best e1RM", "Prior 4w best e1RM", "Change kg",\n                "Direction", "Current observations", "Prior observations",\n            ]\n            strength = strength[[c for c in keep if c in strength.columns]]\n        else:\n            strength = recomp.get("strength", pd.DataFrame()).copy()\n        st.subheader("4-week strength cross-check")\n''',
    "canonical exact-lift strength",
)

p.write_text(text, encoding="utf-8")
print("Patched Health Dashboard canonical coaching integration.")

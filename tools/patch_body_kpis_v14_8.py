from pathlib import Path

path = Path("streamlit_app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


# Overall Health Trends chart only: remove muscle mass %, leaving
# Weight, Body fat %, and Water %. KPI cards remain unchanged.
replace_once(
    '''    withings_views = {}\n    for label, column, unit in [\n        ("Muscle mass %", "muscle_mass_pct", "%"),\n        ("Water %", "water_pct", "%"),\n    ]:\n''',
    '''    withings_views = {}\n    for label, column, unit in [\n        ("Water %", "water_pct", "%"),\n    ]:\n''',
)

# Withings advanced body-composition KPI row only:
# Fat mass | Muscle mass | Fat-free mass | BMR.
# Leave the Withings trend dropdown/chart unchanged.
replace_once(
    '''        fat_mass = latest_withings_value(\n            withings_scale, "fat_mass_kg"\n        )\n        fat_free_mass = latest_withings_value(\n            withings_scale, "fat_free_mass_kg"\n        )\n        bmr = latest_withings_value(\n            withings_scale, "bmr_kcal_day"\n        )\n\n        withings_cards = st.columns(4)\n        withings_cards[0].metric(\n            "Fat mass",\n            f"{fat_mass:.2f} kg"\n            if fat_mass is not None else "—",\n        )\n        withings_cards[1].metric(\n            "Direct muscle mass %",\n            f"{direct_muscle_pct:.2f}%"\n            if direct_muscle_pct is not None else "—",\n        )\n        withings_cards[2].metric(\n            "Fat-free mass",\n            f"{fat_free_mass:.2f} kg"\n            if fat_free_mass is not None else "—",\n        )\n        withings_cards[3].metric(\n            "BMR",\n            f"{bmr:,.0f} kcal/day" if bmr is not None else "—",\n        )\n''',
    '''        fat_mass = latest_withings_value(\n            withings_scale, "fat_mass_kg"\n        )\n        muscle_mass = latest_withings_value(\n            withings_scale, "muscle_mass_kg"\n        )\n        fat_free_mass = latest_withings_value(\n            withings_scale, "fat_free_mass_kg"\n        )\n        bmr = latest_withings_value(\n            withings_scale, "bmr_kcal_day"\n        )\n\n        withings_cards = st.columns(4)\n        withings_cards[0].metric(\n            "Fat mass",\n            f"{fat_mass:.2f} kg"\n            if fat_mass is not None else "—",\n        )\n        withings_cards[1].metric(\n            "Muscle mass",\n            f"{muscle_mass:.2f} kg"\n            if muscle_mass is not None else "—",\n        )\n        withings_cards[2].metric(\n            "Fat-free mass",\n            f"{fat_free_mass:.2f} kg"\n            if fat_free_mass is not None else "—",\n        )\n        withings_cards[3].metric(\n            "BMR",\n            f"{bmr:,.0f} kcal/day" if bmr is not None else "—",\n        )\n''',
)

path.write_text(text, encoding="utf-8")

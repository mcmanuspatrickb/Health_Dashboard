from pathlib import Path

path = Path("streamlit_app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


# Google Health's body loader uses an exclusive end date. Include the current
# day so same-day weight/body-fat samples can appear when Google Health has
# already received them.
replace_once(
    '''@st.cache_data(ttl=3600, show_spinner=False)\ndef load_google_health_body(days: int = 30) -> pd.DataFrame:\n    client = GoogleHealthClient()\n    today = datetime.now(ZoneInfo("Europe/Berlin")).date()\n    return load_body(client, today - timedelta(days=days), today)\n''',
    '''@st.cache_data(ttl=3600, show_spinner=False)\ndef load_google_health_body(days: int = 30) -> pd.DataFrame:\n    client = GoogleHealthClient()\n    today = datetime.now(ZoneInfo("Europe/Berlin")).date()\n    return load_body(\n        client,\n        today - timedelta(days=days),\n        today + timedelta(days=1),\n    )\n''',
)

# Give weight its own tighter axis while keeping percentage metrics on a
# stable 0-60% scale. This visually separates weight from water % while still
# keeping the 90 kg and 15% goal lines visible.
replace_once(
    '''        overall_fig.update_yaxes(\n            title_text="Weight (kg)",\n            secondary_y=False,\n        )\n        overall_fig.update_yaxes(\n            title_text="Body composition value",\n            secondary_y=True,\n        )\n''',
    '''        weight_axis_range = None\n        if not weight_view.empty:\n            weight_values = pd.to_numeric(\n                weight_view["weight_kg"], errors="coerce"\n            ).dropna()\n            if not weight_values.empty:\n                weight_low = min(90.0, float(weight_values.min()))\n                weight_high = float(weight_values.max())\n                spread = max(5.0, weight_high - weight_low)\n                weight_axis_range = [\n                    max(0.0, weight_low - max(2.0, spread * 0.08)),\n                    weight_high + max(2.0, spread * 0.12),\n                ]\n\n        overall_fig.update_yaxes(\n            title_text="Weight (kg)",\n            range=weight_axis_range,\n            secondary_y=False,\n        )\n        overall_fig.update_yaxes(\n            title_text="Body fat / water (%)",\n            range=[0, 60],\n            secondary_y=True,\n        )\n''',
)

path.write_text(text, encoding="utf-8")

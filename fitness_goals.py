{
  "version": 2,
  "notes": [
    "Goals are preserved from the user's original table.",
    "Estimated 1RM uses the Epley formula for loaded working sets of 1–12 reps.",
    "Farmer-carry weight is assumed to be entered per hand in Hevy.",
    "MM means estimated muscle-mass percentage.",
    "Estimated muscle mass uses a fixed 3.87 kg bone-mass baseline from the latest direct Withings measurement."
  ],
  "goals": [
    {
      "id": "body_weight",
      "category": "Body Composition",
      "goal": "Body weight",
      "metric": "body_weight_kg",
      "target": 90,
      "direction": "maximum",
      "unit": "kg",
      "target_display": "<90 kg",
      "note": "Google Health weight."
    },
    {
      "id": "body_fat",
      "category": "Body Composition",
      "goal": "Body fat",
      "metric": "body_fat_pct",
      "target": 15,
      "direction": "maximum",
      "unit": "%",
      "target_display": "<15%",
      "note": "Google Health body-fat percentage."
    },
    {
      "id": "muscle_mass_percent",
      "category": "Body Composition",
      "goal": "Estimated muscle mass percentage",
      "metric": "estimated_muscle_mass_pct",
      "target": 80,
      "direction": "minimum",
      "unit": "%",
      "target_display": ">80%",
      "note": "Withings-compatible proxy using Google Health weight/body fat and fixed 3.87 kg bone mass."
    },
    {
      "id": "back_squat",
      "category": "Strength",
      "goal": "Back squat — estimated 1RM/BW",
      "metric": "e1rm_bw_ratio",
      "target": 1.5,
      "direction": "minimum",
      "unit": "× BW",
      "target_display": "1.5× BW",
      "note": "Estimated 1RM from working sets."
    },
    {
      "id": "back_squat",
      "category": "Strength",
      "goal": "Back squat — 3RM reference",
      "metric": "best_3_to_5_weight_kg",
      "target": 135,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "135 kg × 3",
      "note": "Dashboard uses the best load completed for 3–5 reps."
    },
    {
      "id": "bench_press",
      "category": "Strength",
      "goal": "Bench press — estimated 1RM/BW",
      "metric": "e1rm_bw_ratio",
      "target": 1.25,
      "direction": "minimum",
      "unit": "× BW",
      "target_display": "1.25× BW",
      "note": "Interim reference: 1× BW for 3–5 reps."
    },
    {
      "id": "bench_press",
      "category": "Strength",
      "goal": "Bench press — 3RM reference",
      "metric": "best_3_to_5_weight_kg",
      "target": 112.5,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "112.5 kg × 3",
      "note": "Dashboard uses the best load completed for 3–5 reps."
    },
    {
      "id": "deadlift",
      "category": "Strength",
      "goal": "Deadlift — estimated 1RM/BW",
      "metric": "e1rm_bw_ratio",
      "target": 2,
      "direction": "minimum",
      "unit": "× BW",
      "target_display": "2× BW",
      "note": "Estimated 1RM from conventional/sumo working sets."
    },
    {
      "id": "deadlift",
      "category": "Strength",
      "goal": "Deadlift — 3RM reference",
      "metric": "best_3_to_5_weight_kg",
      "target": 180,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "180 kg × 3",
      "note": "Dashboard uses the best load completed for 3–5 reps."
    },
    {
      "id": "pull_ups",
      "category": "Strength",
      "goal": "Pull-ups",
      "metric": "best_reps",
      "target": 10,
      "direction": "minimum",
      "unit": "reps",
      "target_display": "10+ reps",
      "note": "Best recorded working set."
    },
    {
      "id": "pushups",
      "category": "Strength",
      "goal": "Push-ups in one minute",
      "metric": "best_one_minute_reps",
      "target": 40,
      "direction": "minimum",
      "unit": "reps",
      "target_display": "40+ reps / 1 min",
      "note": "Requires Hevy set duration near one minute."
    },
    {
      "id": "bar_hang",
      "category": "Strength",
      "goal": "Bar hang",
      "metric": "best_duration_seconds",
      "target": 60,
      "direction": "minimum",
      "unit": "sec",
      "target_display": "1+ minute",
      "note": "Best recorded set duration."
    },
    {
      "id": "row",
      "category": "Strength",
      "goal": "Barbell row — estimated 1RM/BW",
      "metric": "e1rm_bw_ratio",
      "target": 1.25,
      "direction": "minimum",
      "unit": "× BW",
      "target_display": "1.25× BW",
      "note": "Interim reference: 1× BW for 3–5 reps."
    },
    {
      "id": "row",
      "category": "Strength",
      "goal": "Barbell row — 3RM reference",
      "metric": "best_3_to_5_weight_kg",
      "target": 112.5,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "112.5 kg × 3",
      "note": "Dashboard uses the best load completed for 3–5 reps."
    },
    {
      "id": "overhead_press",
      "category": "Strength",
      "goal": "Overhead press — estimated 1RM/BW",
      "metric": "e1rm_bw_ratio",
      "target": 1,
      "direction": "minimum",
      "unit": "× BW",
      "target_display": "1× BW",
      "note": "Standing barbell press preferred."
    },
    {
      "id": "overhead_press",
      "category": "Strength",
      "goal": "Overhead press — 3RM reference",
      "metric": "best_3_to_5_weight_kg",
      "target": 90,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "90 kg × 3",
      "note": "Dashboard uses the best load completed for 3–5 reps."
    },
    {
      "id": "farmer_carry",
      "category": "Strength",
      "goal": "Farmer carry — load/BW per hand",
      "metric": "farmer_bw_ratio",
      "target": 0.5,
      "direction": "minimum",
      "unit": "× BW/hand",
      "target_display": "0.5× BW per hand",
      "note": "Assumes Hevy weight is entered per hand."
    },
    {
      "id": "farmer_carry",
      "category": "Strength",
      "goal": "Farmer carry — minimum load",
      "metric": "best_weight_kg",
      "target": 45,
      "direction": "minimum",
      "unit": "kg/hand",
      "target_display": "45 kg per hand",
      "note": "Assumes Hevy weight is entered per hand."
    },
    {
      "id": "farmer_carry",
      "category": "Strength",
      "goal": "Farmer carry — distance",
      "metric": "best_distance_m",
      "target": 40,
      "direction": "minimum",
      "unit": "m",
      "target_display": "40–80 m (~30 sec)",
      "note": "The first target threshold is 40 m."
    },
    {
      "id": "plank",
      "category": "Strength",
      "goal": "Plank",
      "metric": "best_duration_seconds",
      "target": 180,
      "direction": "minimum",
      "unit": "sec",
      "target_display": "3+ minutes",
      "note": "Best recorded set duration."
    },
    {
      "id": "get_up",
      "category": "Strength",
      "goal": "Get-up",
      "metric": "best_weight_kg",
      "target": 40,
      "direction": "minimum",
      "unit": "kg",
      "target_display": "40+ kg",
      "note": "Turkish get-up or matching exercise alias."
    },
    {
      "id": "run",
      "category": "Endurance",
      "goal": "Run distance",
      "metric": "endurance_distance_km",
      "target": 42.2,
      "direction": "minimum",
      "unit": "km",
      "target_display": "42.2 km",
      "note": "Longest reconciled running session."
    },
    {
      "id": "run",
      "category": "Endurance",
      "goal": "Run time reference",
      "metric": "endurance_time_hours",
      "target": 7,
      "direction": "maximum",
      "unit": "hours",
      "target_display": "≤7 hours at 42.2 km",
      "note": "Time is meaningful only when the target distance is completed."
    },
    {
      "id": "swim",
      "category": "Endurance",
      "goal": "Swim distance",
      "metric": "endurance_distance_km",
      "target": 3.8,
      "direction": "minimum",
      "unit": "km",
      "target_display": "3.8 km",
      "note": "Longest reconciled swimming session."
    },
    {
      "id": "swim",
      "category": "Endurance",
      "goal": "Swim time reference",
      "metric": "endurance_time_hours",
      "target": 2,
      "direction": "maximum",
      "unit": "hours",
      "target_display": "≤2 hours at 3.8 km",
      "note": "Time is meaningful only when the target distance is completed."
    },
    {
      "id": "bike",
      "category": "Endurance",
      "goal": "Bike distance",
      "metric": "endurance_distance_km",
      "target": 180,
      "direction": "minimum",
      "unit": "km",
      "target_display": "180 km",
      "note": "Longest reconciled cycling session."
    },
    {
      "id": "bike",
      "category": "Endurance",
      "goal": "Bike time reference",
      "metric": "endurance_time_hours",
      "target": 8,
      "direction": "maximum",
      "unit": "hours",
      "target_display": "≤8 hours at 180 km",
      "note": "Time is meaningful only when the target distance is completed."
    }
  ],
  "body_composition_proxy": {
    "method": "withings_compatible_fixed_bone_mass",
    "bone_mass_baseline_kg": 3.87,
    "notes": [
      "Estimated muscle mass = weight - estimated fat mass - fixed bone-mass baseline.",
      "Estimated fat mass = weight x body-fat percentage.",
      "This is a Withings-compatible proxy, not a direct skeletal-muscle measurement.",
      "Use the 7-day rolling median for trend interpretation."
    ]
  }
}

"""Fictional-only tests for canonical coaching snapshot freshness metadata."""
from __future__ import annotations

import unittest
from datetime import date
from coaching_snapshot import snapshot_freshness


class CanonicalFreshnessTests(unittest.TestCase):
    def test_stale_snapshot_does_not_change_coaching_decision(self):
        synthetic = {
            "analysis_date": "2026-10-24",
            "decision": {"action": "HOLD", "target_intake": 1900},
        }
        result = snapshot_freshness(synthetic, date(2026, 11, 3))
        self.assertEqual(result["age_days"], 10)
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(synthetic["decision"]["action"], "HOLD")

    def test_missing_or_invalid_analysis_date(self):
        self.assertEqual(snapshot_freshness({}, date(2026, 11, 3))["status"], "UNKNOWN")
        self.assertEqual(snapshot_freshness(
            {"analysis_date": "2026-11-04"}, date(2026, 11, 3)
        )["status"], "FUTURE_DATED")

    def test_current_snapshot(self):
        self.assertEqual(snapshot_freshness(
            {"analysis_date": "2026-11-01"}, date(2026, 11, 3)
        )["status"], "CURRENT")


if __name__ == "__main__":
    unittest.main()

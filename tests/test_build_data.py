import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.build_data import build_dashboard
from tests.helpers import configs


MADRID = ZoneInfo("Europe/Madrid")


class BuildDataTests(unittest.TestCase):
    def setUp(self):
        self.values = configs()

    def build(self, ledger=None, current=None, now=None):
        return build_dashboard(
            self.values["challenge"], self.values["participants"], self.values["baseline"],
            current or self.values["current"], ledger or self.values["ledger"],
            now or datetime(2026, 8, 10, 12, tzinfo=MADRID),
        )

    def test_ranking_and_120_km_objective(self):
        data = self.build()
        self.assertEqual(data["challenge"]["objective_per_runner_km"], 120)
        self.assertEqual(data["challenge"]["objective_total_km"], 1440)
        self.assertEqual([runner["name"] for runner in data["runners"][:3]], ["Pablo Meijide", "Antonio Meijide", "Kike Rasilla"])
        self.assertAlmostEqual(data["summary"]["total_km"], 403.9)

    def test_projection_uses_data_coverage_day(self):
        data = self.build(now=datetime(2026, 8, 16, 12, tzinfo=MADRID))
        pablo = next(runner for runner in data["runners"] if runner["name"] == "Pablo Meijide")
        self.assertAlmostEqual(pablo["projection_km"], round(63.09 / 16 * 36, 1))
        self.assertAlmostEqual(pablo["pace_required_km_per_day"], round((120 - 63.09) / 14, 2))

    def test_baseline_plus_new_activity(self):
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "historical_exact", "bootstrap_complete": True})
        ledger["records"] = [{
            "fingerprint": "a" * 64, "participant": "Pablo Meijide", "activity_date": "2026-08-11",
            "date_accuracy": "exact", "distance_km": 5.25, "moving_time_s": 1800,
            "elevation_m": 40, "sport_type": "Run",
        }]
        data = self.build(ledger=ledger, now=datetime(2026, 8, 11, 12, tzinfo=MADRID))
        pablo = next(runner for runner in data["runners"] if runner["name"] == "Pablo Meijide")
        self.assertEqual(pablo["km"], 68.34)
        self.assertEqual(pablo["outings_tracked"], 1)
        self.assertEqual(pablo["elevation_tracked_m"], 40)

    def test_completed_challenge_has_no_projection(self):
        data = self.build(now=datetime(2026, 8, 31, 12, tzinfo=MADRID))
        self.assertTrue(data["challenge"]["finished"])
        self.assertTrue(all(runner["projection_km"] is None for runner in data["runners"]))

    def test_current_baseline_requires_all_numeric_totals(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16"})
        with self.assertRaisesRegex(ValueError, "one numeric total"):
            self.build(current=current)


if __name__ == "__main__":
    unittest.main()

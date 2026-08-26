import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.build_data import build_dashboard
from scripts.state import load_json
from tests.helpers import configs


MADRID = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parents[1]


class BuildDataTests(unittest.TestCase):
    def setUp(self):
        self.values = configs()

    def build(self, ledger=None, current=None, now=None, leaderboard_adjustments=None):
        return build_dashboard(
            self.values["challenge"], self.values["participants"], self.values["baseline"],
            current or self.values["current"], ledger or self.values["ledger"],
            now or datetime(2026, 8, 10, 12, tzinfo=MADRID),
            leaderboard_adjustments or self.values["leaderboard_adjustments"],
        )

    def test_ranking_and_125_km_objective(self):
        data = self.build()
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["challenge"]["objective_per_runner_km"], 125)
        self.assertEqual(data["challenge"]["objective_total_km"], 1500)
        self.assertEqual([runner["name"] for runner in data["runners"][:3]], ["Pablo Meijide", "Antonio Meijide", "Kike Rasilla"])
        self.assertAlmostEqual(data["summary"]["total_km"], 403.9)
        self.assertAlmostEqual(data["summary"]["projection_km"], round(403.9 / 16 * 36, 1))
        self.assertAlmostEqual(data["summary"]["projection_gap_km"], round(403.9 / 16 * 36 - 1500, 1))
        self.assertEqual(data["summary"]["on_track_runners"], 2)
        self.assertEqual(data["runners"][0]["slug"], "pablo-meijide")
        self.assertAlmostEqual(sum(runner["contribution_pct"] for runner in data["runners"]), 100, delta=0.2)

    def test_projection_uses_data_coverage_day(self):
        data = self.build(now=datetime(2026, 8, 16, 12, tzinfo=MADRID))
        pablo = next(runner for runner in data["runners"] if runner["name"] == "Pablo Meijide")
        self.assertAlmostEqual(pablo["projection_km"], round(63.09 / 16 * 36, 1))
        self.assertAlmostEqual(pablo["pace_required_km_per_day"], round((125 - 63.09) / 14, 2))

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

    def test_efficiency_metrics_are_post_checkpoint_only(self):
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "historical_exact", "bootstrap_complete": True})
        ledger["records"] = [
            {
                "fingerprint": "a" * 64, "participant": "Pablo Meijide", "activity_date": "2026-08-11",
                "date_accuracy": "exact", "detected_at": "2026-08-11T09:00:00+02:00",
                "distance_km": 5, "moving_time_s": 1800, "elevation_m": 40, "sport_type": "Run",
            },
            {
                "fingerprint": "b" * 64, "participant": "Pablo Meijide", "activity_date": "2026-08-12",
                "date_accuracy": "exact", "detected_at": "2026-08-12T10:00:00+02:00",
                "distance_km": 8, "moving_time_s": 3000, "elevation_m": 110, "sport_type": "TrailRun",
            },
        ]
        data = self.build(ledger=ledger, now=datetime(2026, 8, 12, 12, tzinfo=MADRID))
        pablo = next(runner for runner in data["runners"] if runner["name"] == "Pablo Meijide")
        tracking = pablo["tracking"]
        self.assertEqual(tracking["outings"], 2)
        self.assertEqual(tracking["distance_km"], 13)
        self.assertEqual(tracking["km_per_outing"], 6.5)
        self.assertEqual(tracking["longest_outing_km"], 8)
        self.assertEqual(tracking["weighted_pace_min_per_km"], round(4800 / 60 / 13, 2))
        self.assertEqual(tracking["elevation_m_per_km"], round(150 / 13, 1))
        self.assertEqual(tracking["distribution"]["medium_5_to_10k"], 2)
        self.assertNotIn("fingerprint", tracking["activities"][0])

    def test_milestones_distinguish_checkpoint_and_detected_dates(self):
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "historical_exact", "bootstrap_complete": True})
        ledger["records"] = [{
            "fingerprint": "c" * 64, "participant": "Kike Rasilla", "activity_date": "2026-08-11",
            "date_accuracy": "exact", "detected_at": "2026-08-11T08:00:00+02:00",
            "distance_km": 10, "moving_time_s": 3200, "elevation_m": 20, "sport_type": "Run",
        }]
        data = self.build(ledger=ledger, now=datetime(2026, 8, 11, 12, tzinfo=MADRID))
        kike = next(runner for runner in data["runners"] if runner["name"] == "Kike Rasilla")
        self.assertEqual(kike["milestones"][0]["status"], "before_tracking")
        self.assertEqual(kike["milestones"][1]["status"], "exact")
        self.assertEqual(kike["milestones"][1]["reached_on"], "2026-08-11")
        self.assertEqual(kike["milestones"][2]["status"], "pending")

    def test_quality_separates_feed_check_from_complete_observation(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16", "captured_at": "2026-08-16T19:00:00+02:00"})
        current["totals_km"] = {name: item["total"] for name, item in self.values["baseline"]["runners"].items()}
        ledger = deepcopy(self.values["ledger"])
        ledger.update({
            "strategy": "incremental_fingerprint", "bootstrap_complete": True,
            "incremental_checkpoint_date": "2026-08-16", "last_successful_update": "2026-08-16T20:00:00+02:00",
        })
        data = self.build(ledger=ledger, current=current, now=datetime(2026, 8, 16, 20, tzinfo=MADRID))
        self.assertEqual(data["data_through"], "2026-08-16")
        self.assertEqual(data["quality"]["last_feed_check"], "2026-08-16T20:00:00+02:00")
        self.assertEqual(data["quality"]["last_complete_observation"], "2026-08-16T20:00:00+02:00")
        self.assertTrue(data["quality"]["tracking_active"])
        self.assertFalse(data["quality"]["activity_metrics_available"])

    def test_real_august_16_checkpoint_joins_weekly_snapshot_without_day_10_overlap(self):
        current = load_json(ROOT / "bootstrap/current_baseline.json")
        data = self.build(current=current, now=datetime(2026, 8, 16, 21, 52, tzinfo=MADRID))
        self.assertEqual(data["data_through"], "2026-08-16")
        self.assertAlmostEqual(data["summary"]["total_km"], 674.65)
        self.assertEqual(data["runners"][0]["name"], "Borja Glez- Palenzuela Gracia")
        self.assertAlmostEqual(data["runners"][0]["km"], 101.97)
        self.assertEqual(data["summary"]["outings_total"], 80)
        self.assertEqual(data["summary"]["elevation_total_m"], 5839)
        self.assertFalse(data["summary"]["elevation_total_complete"])
        self.assertEqual(data["runners"][0]["outings_total"], 9)
        self.assertEqual(data["runners"][0]["elevation_total_m"], 779)
        self.assertAlmostEqual(
            sum(current["totals_km"].values()) - 403.9,
            current["weekly_snapshot"]["net_challenge_increment_km"],
        )

    def test_visibility_reconciliation_uses_api_records_for_borja_and_kept(self):
        current = load_json(ROOT / "bootstrap/current_baseline.json")
        adjustments = load_json(ROOT / "state/leaderboard_adjustments.json")
        ledger = load_json(ROOT / "state/activity_ledger.json")
        data = self.build(
            current=current,
            ledger=ledger,
            leaderboard_adjustments=adjustments,
            now=datetime(2026, 8, 25, 23, 30, tzinfo=MADRID),
        )
        kept = next(runner for runner in data["runners"] if runner["name"] == "Kept ES")
        borja = next(runner for runner in data["runners"] if runner["name"].startswith("Borja"))
        self.assertEqual((kept["km"], kept["outings_total"]), (130.74, 13))
        self.assertEqual((borja["km"], borja["outings_total"]), (164.02, 14))
        self.assertEqual(kept["tracking"]["outings"], 6)
        self.assertAlmostEqual(kept["tracking"]["distance_km"], 62.579)
        self.assertEqual(borja["tracking"]["outings"], 5)
        self.assertAlmostEqual(borja["tracking"]["distance_km"], 62.047)
        self.assertTrue(kept["elevation_total_complete"])
        self.assertTrue(borja["elevation_total_complete"])
        self.assertIsNone(kept["leaderboard_adjustment"])
        self.assertIsNone(borja["leaderboard_adjustment"])
        self.assertEqual(data["quality"]["leaderboard_reconciliation_km"], 0)
        self.assertEqual(data["coverage"]["leaderboard_adjustments"], 0)
        self.assertAlmostEqual(
            data["summary"]["total_km"],
            round(sum(runner["km"] for runner in data["runners"]), 2),
        )


if __name__ == "__main__":
    unittest.main()

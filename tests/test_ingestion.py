import unittest
from copy import deepcopy
from datetime import date

from scripts.update_strava import fingerprint, process_feed
from tests.helpers import configs


def activity(name="Pablo M.", sport="Run", distance=5000, activity_id=None, start_date=None):
    result = {
        "athlete": {"firstname": name.split()[0], "lastname": name.split()[-1]},
        "name": "Morning Run", "distance": distance, "moving_time": 1500, "elapsed_time": 1600,
        "total_elevation_gain": 25.5, "sport_type": sport,
    }
    if activity_id is not None:
        result["id"] = activity_id
    if start_date is not None:
        result["start_date"] = start_date
    return result


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.values = configs()

    def process(self, ledger, feed, current, day):
        return process_feed(
            ledger, feed, self.values["challenge"], self.values["participants"], current,
            self.values["baseline"]["checkpoint_date"], day,
        )

    def test_fingerprint_is_stable(self):
        first = activity()
        second = dict(reversed(list(first.items())))
        self.assertEqual(fingerprint(first), fingerprint(second))
        self.assertEqual(len(fingerprint(first)), 64)

    def test_filters_run_and_trailrun_and_is_idempotent(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16"})
        current["totals_km"] = {name: item["total"] for name, item in self.values["baseline"]["runners"].items()}
        feed = [activity(), activity("Sergio S.", "TrailRun", 3000), activity("Antonio M.", "Ride", 30000)]
        first = self.process(self.values["ledger"], feed, current, date(2026, 8, 16))
        self.assertEqual(first["strategy"], "incremental_fingerprint")
        self.assertEqual(first["records"], [])
        new_feed = feed + [activity("Antonio M.", "Run", 6000)]
        second = self.process(first, new_feed, current, date(2026, 8, 17))
        self.assertEqual(len(second["records"]), 1)
        self.assertEqual(second["records"][0]["participant"], "Antonio Meijide")
        third = self.process(second, new_feed, current, date(2026, 8, 17))
        self.assertEqual(third["records"], second["records"])

    def test_historical_exact_uses_only_post_baseline_dates(self):
        feed = [
            activity("Pablo M.", activity_id=1, start_date="2026-08-10T08:00:00Z"),
            activity("Pablo M.", activity_id=2, start_date="2026-08-11T08:00:00Z"),
        ]
        result = self.process(self.values["ledger"], feed, self.values["current"], date(2026, 8, 16))
        self.assertEqual(result["strategy"], "historical_exact")
        self.assertEqual([record["fingerprint"] for record in result["records"]], [fingerprint(feed[1])])

    def test_empty_response_is_valid_and_does_not_choose_strategy(self):
        result = self.process(self.values["ledger"], [], self.values["current"], date(2026, 8, 16))
        self.assertIsNone(result["strategy"])
        self.assertEqual(result["records"], [])

    def test_spike_records_sanitized_real_field_names(self):
        feed = [activity("Pablo M.", activity_id=7, start_date="2026-08-11T08:00:00Z")]
        result = self.process(self.values["ledger"], feed, self.values["current"], date(2026, 8, 16))
        probe = result["field_probe"]
        self.assertIn("id", probe["observed_top_level_fields"])
        self.assertIn("firstname", probe["observed_athlete_fields"])
        self.assertEqual(probe["id_present"], 1)


if __name__ == "__main__":
    unittest.main()

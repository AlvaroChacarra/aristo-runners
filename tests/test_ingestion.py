import unittest
from copy import deepcopy
from datetime import date

from scripts.update_strava import fingerprint, process_feed, resolve_participant
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


def displayed_activity(display, distance=5000):
    return {
        "athlete": {"name": display},
        "name": "New Run",
        "distance": distance,
        "moving_time": 1500,
        "elapsed_time": 1600,
        "total_elevation_gain": 25.5,
        "sport_type": "Run",
    }


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
        self.assertEqual(second["records"][0]["detected_at"], "2026-08-17")
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

    def test_every_configured_name_and_alias_resolves_to_exactly_one_runner(self):
        self.assertEqual(len(self.values["participants"]), 12)
        for participant in self.values["participants"]:
            for alias in [participant["name"], *participant.get("aliases", [])]:
                with self.subTest(participant=participant["name"], alias=alias):
                    self.assertEqual(
                        resolve_participant(displayed_activity(alias), self.values["participants"]),
                        participant["name"],
                    )

    def test_all_twelve_runners_accept_one_new_activity_and_replay_is_idempotent(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16"})
        current["totals_km"] = {
            name: item["total"] for name, item in self.values["baseline"]["runners"].items()
        }
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "incremental_fingerprint", "bootstrap_complete": True})
        feed = [
            displayed_activity(participant["name"], 5000 + index)
            for index, participant in enumerate(self.values["participants"])
        ]

        first = self.process(ledger, feed, current, date(2026, 8, 17))
        second = self.process(first, feed, current, date(2026, 8, 17))

        self.assertEqual(len(first["records"]), 12)
        self.assertEqual(
            {record["participant"] for record in first["records"]},
            {participant["name"] for participant in self.values["participants"]},
        )
        self.assertEqual(first["records"], second["records"])
        self.assertEqual(first["unmatched_activities"], 0)

    def test_unknown_runner_is_reported_and_never_assigned(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16"})
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "incremental_fingerprint", "bootstrap_complete": True})

        result = self.process(ledger, [displayed_activity("Unknown Runner")], current, date(2026, 8, 17))

        self.assertEqual(result["records"], [])
        self.assertEqual(result["unmatched_activities"], 1)
        self.assertEqual(result["unmatched_athletes"], ["unknown runner"])

    def test_incremental_feed_accepts_final_day_and_rejects_later_observations(self):
        current = deepcopy(self.values["current"])
        current.update({"complete": True, "checkpoint_date": "2026-08-16"})
        ledger = deepcopy(self.values["ledger"])
        ledger.update({"strategy": "incremental_fingerprint", "bootstrap_complete": True})

        final_day = self.process(
            ledger,
            [displayed_activity("Alvaro López-Chacarra", 7000)],
            current,
            date(2026, 8, 30),
        )
        after_end = self.process(
            final_day,
            [
                displayed_activity("Alvaro López-Chacarra", 7000),
                displayed_activity("Alvaro López-Chacarra", 8000),
            ],
            current,
            date(2026, 8, 31),
        )

        self.assertEqual(len(final_day["records"]), 1)
        self.assertEqual(final_day["records"][0]["activity_date"], "2026-08-30")
        self.assertEqual(after_end["records"], final_day["records"])


if __name__ == "__main__":
    unittest.main()

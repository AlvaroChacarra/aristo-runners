import unittest
from copy import deepcopy

from scripts.state import load_json
from scripts.validate_live_state import LiveStateValidationError, validate_live_state
from tests.helpers import ROOT


class LiveStateValidationTests(unittest.TestCase):
    def setUp(self):
        self.challenge = load_json(ROOT / "config/challenge.json")
        self.participants = load_json(ROOT / "config/participants.json")
        self.current = load_json(ROOT / "bootstrap/current_baseline.json")
        self.ledger = load_json(ROOT / "state/activity_ledger.json")
        self.dashboard = load_json(ROOT / "data.json")

    def validate(self, ledger=None, dashboard=None):
        return validate_live_state(
            self.challenge,
            self.participants,
            self.current,
            ledger or self.ledger,
            dashboard or self.dashboard,
        )

    def test_live_state_covers_every_configured_runner(self):
        report = self.validate()
        self.assertEqual(len(report), 12)
        self.assertEqual({item["participant"] for item in report}, {p["name"] for p in self.participants})
        self.assertTrue(
            {item["status"] for item in report} <= {"OBSERVED", "NO_POST_CHECKPOINT_RECORD"}
        )

    def test_duplicate_fingerprint_is_rejected(self):
        ledger = deepcopy(self.ledger)
        ledger["records"].append(deepcopy(ledger["records"][0]))
        with self.assertRaisesRegex(LiveStateValidationError, "duplicate activity fingerprints"):
            self.validate(ledger=ledger)

    def test_unmatched_activity_is_rejected(self):
        ledger = deepcopy(self.ledger)
        ledger["unmatched_activities"] = 1
        ledger["unmatched_athletes"] = ["unknown runner"]
        with self.assertRaisesRegex(LiveStateValidationError, "unmatched"):
            self.validate(ledger=ledger)


if __name__ == "__main__":
    unittest.main()

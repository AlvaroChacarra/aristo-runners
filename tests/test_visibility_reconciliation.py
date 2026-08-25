import unittest

from scripts.reconcile_visibility import apply_visibility_reconciliations


def record(fingerprint, participant, distance):
    return {
        "fingerprint": fingerprint,
        "participant": participant,
        "activity_date": "2026-08-25",
        "date_accuracy": "observed",
        "detected_at": "2026-08-25T23:27:20+02:00",
        "distance_km": distance,
        "moving_time_s": 1200,
        "elapsed_time_s": 1250,
        "elevation_m": 10.0,
        "sport_type": "Run",
    }


class VisibilityReconciliationTests(unittest.TestCase):
    def test_selective_reconciliation_is_idempotent_and_preserves_other_athletes(self):
        ledger = {
            "records": [record("keep", "Borja", 8.747), record("old", "Borja", 9.475), record("other", "Kept", 5.0)],
            "ignored_fingerprints": [],
        }
        adjustments = {
            "version": 1,
            "adjustments": [
                {"id": "borja-manual", "participant": "Borja"},
                {"id": "kept-manual", "participant": "Kept"},
            ],
        }
        manifest = {
            "version": 1,
            "reconciliations": [
                {
                    "id": "borja-visible",
                    "participant": "Borja",
                    "reconciled_at": "2026-08-25T23:27:20+02:00",
                    "source": "test",
                    "keep": [{"fingerprint": "keep", "activity_date": "2026-08-19"}],
                    "ignore_fingerprints": ["old"],
                    "remove_adjustment_ids": ["borja-manual"],
                }
            ],
        }

        first_ledger, first_adjustments = apply_visibility_reconciliations(ledger, adjustments, manifest)
        second_ledger, second_adjustments = apply_visibility_reconciliations(first_ledger, first_adjustments, manifest)

        self.assertEqual(first_ledger, second_ledger)
        self.assertEqual(first_adjustments, second_adjustments)
        self.assertEqual([item["fingerprint"] for item in first_ledger["records"]], ["keep", "other"])
        kept = next(item for item in first_ledger["records"] if item["fingerprint"] == "keep")
        self.assertEqual(kept["activity_date"], "2026-08-19")
        self.assertIn("old", first_ledger["ignored_fingerprints"])
        self.assertEqual([item["id"] for item in first_adjustments["adjustments"]], ["kept-manual"])


if __name__ == "__main__":
    unittest.main()

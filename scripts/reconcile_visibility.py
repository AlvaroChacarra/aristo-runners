from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.state import atomic_write_json, load_json


ROOT = Path(__file__).resolve().parents[1]


def apply_visibility_reconciliations(
    ledger: dict[str, Any],
    leaderboard_adjustments: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconcile activities that suddenly become visible without dates.

    ClubActivity omits IDs and dates. When a follow/privacy relationship changes,
    Strava can expose an athlete's historical feed all at once. The manifest keeps
    only explicitly matched post-checkpoint fingerprints and checkpoints every
    other newly visible fingerprint so repeated runs remain idempotent.
    """
    if manifest.get("version") != 1 or not isinstance(manifest.get("reconciliations"), list):
        raise ValueError("invalid visibility reconciliation manifest")

    updated = deepcopy(ledger)
    adjustments = deepcopy(leaderboard_adjustments)
    records = updated.setdefault("records", [])
    ignored = set(updated.setdefault("ignored_fingerprints", []))
    audit = {item["id"]: item for item in updated.get("visibility_reconciliations", [])}

    adjustment_items = adjustments.get("adjustments")
    if adjustments.get("version") != 1 or not isinstance(adjustment_items, list):
        raise ValueError("invalid leaderboard adjustments document")

    for item in manifest["reconciliations"]:
        reconciliation_id = item.get("id")
        participant = item.get("participant")
        keep = item.get("keep", [])
        ignore = set(item.get("ignore_fingerprints", []))
        remove_adjustments = set(item.get("remove_adjustment_ids", []))
        if not isinstance(reconciliation_id, str) or not reconciliation_id:
            raise ValueError("visibility reconciliation requires an id")
        if not isinstance(participant, str) or not participant:
            raise ValueError("visibility reconciliation requires a participant")
        if not isinstance(keep, list) or not all(isinstance(entry, dict) for entry in keep):
            raise ValueError("visibility reconciliation keep list is invalid")
        keep_by_fingerprint = {entry.get("fingerprint"): entry for entry in keep}
        if None in keep_by_fingerprint or len(keep_by_fingerprint) != len(keep):
            raise ValueError("kept fingerprints must be present and unique")
        if ignore & set(keep_by_fingerprint):
            raise ValueError("a fingerprint cannot be both kept and ignored")

        seen: set[str] = set()
        retained: list[dict[str, Any]] = []
        for record in records:
            fingerprint = record.get("fingerprint")
            if fingerprint not in ignore and fingerprint not in keep_by_fingerprint:
                retained.append(record)
                continue
            if record.get("participant") != participant:
                raise ValueError(f"fingerprint belongs to another participant: {fingerprint}")
            seen.add(fingerprint)
            if fingerprint in ignore:
                ignored.add(fingerprint)
                continue
            replacement = deepcopy(record)
            replacement["activity_date"] = keep_by_fingerprint[fingerprint]["activity_date"]
            replacement["date_accuracy"] = "observed"
            retained.append(replacement)

        missing_keep = set(keep_by_fingerprint) - seen
        if missing_keep:
            raise ValueError(f"kept fingerprints are absent from the ledger: {sorted(missing_keep)}")
        missing_ignore = ignore - seen - ignored
        if missing_ignore:
            raise ValueError(f"ignored fingerprints are absent from the ledger: {sorted(missing_ignore)}")
        records = retained

        existing_adjustment_ids = {entry.get("id") for entry in adjustment_items}
        missing_adjustments = remove_adjustments - existing_adjustment_ids
        already_removed = set(audit.get(reconciliation_id, {}).get("removed_adjustment_ids", []))
        if missing_adjustments - already_removed:
            raise ValueError(f"adjustments are absent: {sorted(missing_adjustments - already_removed)}")
        adjustment_items = [entry for entry in adjustment_items if entry.get("id") not in remove_adjustments]

        audit[reconciliation_id] = {
            "id": reconciliation_id,
            "participant": participant,
            "reconciled_at": item.get("reconciled_at"),
            "source": item.get("source"),
            "kept_fingerprints": sorted(keep_by_fingerprint),
            "ignored_fingerprint_count": len(ignore),
            "removed_adjustment_ids": sorted(remove_adjustments),
        }

    updated["records"] = sorted(
        records,
        key=lambda record: (record["activity_date"], record["participant"], record["fingerprint"]),
    )
    updated["ignored_fingerprints"] = sorted(ignored)
    updated["visibility_reconciliations"] = sorted(audit.values(), key=lambda item: item["id"])
    adjustments["adjustments"] = adjustment_items
    return updated, adjustments


def reconcile_from_files(root: Path = ROOT) -> None:
    ledger_path = root / "state/activity_ledger.json"
    adjustments_path = root / "state/leaderboard_adjustments.json"
    manifest_path = root / "state/visibility_reconciliations.json"
    ledger, adjustments = apply_visibility_reconciliations(
        load_json(ledger_path), load_json(adjustments_path), load_json(manifest_path)
    )
    atomic_write_json(ledger_path, ledger)
    atomic_write_json(adjustments_path, adjustments)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    reconcile_from_files(args.root)

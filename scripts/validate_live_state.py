from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from scripts.state import load_json
from scripts.update_strava import normalize, resolve_participant


ROOT = Path(__file__).resolve().parents[1]


class LiveStateValidationError(ValueError):
    pass


def validate_live_state(
    challenge: dict[str, Any],
    participants: list[dict[str, Any]],
    current: dict[str, Any],
    ledger: dict[str, Any],
    dashboard: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate dynamic production invariants without freezing live totals."""
    errors: list[str] = []
    names = [participant["name"] for participant in participants]
    name_set = set(names)
    if len(names) != len(name_set):
        errors.append("participant canonical names must be unique")

    alias_owners: dict[str, set[str]] = defaultdict(set)
    for participant in participants:
        for alias in [participant["name"], *participant.get("aliases", [])]:
            alias_owners[normalize(alias)].add(participant["name"])
            resolved = resolve_participant({"athlete": {"name": alias}}, participants)
            if resolved != participant["name"]:
                errors.append(f"alias does not resolve uniquely: {alias!r} -> {resolved!r}")
    ambiguous = sorted(alias for alias, owners in alias_owners.items() if len(owners) > 1)
    if ambiguous:
        errors.append(f"ambiguous configured aliases: {ambiguous}")

    records = ledger.get("records", [])
    fingerprints = [record.get("fingerprint") for record in records]
    if any(fingerprint is None for fingerprint in fingerprints):
        errors.append("every ledger record requires a fingerprint")
    duplicates = sorted(fp for fp, count in Counter(fingerprints).items() if fp is not None and count > 1)
    if duplicates:
        errors.append(f"duplicate activity fingerprints: {duplicates}")
    ignored = set(ledger.get("ignored_fingerprints", []))
    overlap = sorted(set(fingerprints) & ignored)
    if overlap:
        errors.append(f"fingerprints cannot be both recorded and ignored: {overlap}")
    unknown = {record.get("participant") for record in records} - name_set
    if unknown:
        errors.append(f"ledger references unknown participants: {sorted(map(str, unknown))}")
    if int(ledger.get("unmatched_activities", 0)) != 0:
        errors.append(f"feed contains {ledger['unmatched_activities']} unmatched activities")
    if ledger.get("unmatched_athletes"):
        errors.append(f"feed contains unmatched athletes: {ledger['unmatched_athletes']}")

    runners = dashboard.get("runners", [])
    runner_names = [runner.get("name") for runner in runners]
    if len(runner_names) != len(set(runner_names)):
        errors.append("dashboard runner names must be unique")
    if set(runner_names) != name_set:
        errors.append("dashboard participants differ from configured participants")
    if dashboard.get("summary", {}).get("participants") != len(names):
        errors.append("dashboard participant count differs from configuration")
    dashboard_total = round(sum(float(runner.get("km", 0)) for runner in runners), 2)
    if dashboard.get("summary", {}).get("total_km") != dashboard_total:
        errors.append("dashboard total does not equal the sum of runner totals")
    if dashboard.get("quality", {}).get("last_feed_check") != ledger.get("last_successful_update"):
        errors.append("dashboard and ledger do not represent the same feed check")

    start = date.fromisoformat(challenge["challenge_start"])
    end = date.fromisoformat(challenge["challenge_end"])
    records_by_runner: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for record in records:
        if record.get("participant") not in name_set:
            continue
        record_date = date.fromisoformat(record["activity_date"])
        if start <= record_date <= end:
            records_by_runner[record["participant"]].append(record)

    current_totals = current.get("totals_km", {}) if current.get("complete") else {}
    runner_by_name = {runner.get("name"): runner for runner in runners}
    report: list[dict[str, Any]] = []
    for name in names:
        runner = runner_by_name.get(name, {})
        runner_records = records_by_runner[name]
        tracked_km = round(sum(float(record["distance_km"]) for record in runner_records), 3)
        tracked_outings = len(runner_records)
        tracking = runner.get("tracking", {})
        if runner.get("outings_tracked") != tracked_outings or tracking.get("outings") != tracked_outings:
            errors.append(f"tracked outing count differs for {name}")
        if tracking.get("distance_km") != tracked_km:
            errors.append(f"tracked distance differs for {name}")
        baseline_km = current_totals.get(name)
        if baseline_km is not None and float(runner.get("km", 0)) + 1e-9 < float(baseline_km):
            errors.append(f"dashboard total is below the checkpoint for {name}")
        latest = max((record.get("detected_at") or record["activity_date"] for record in runner_records), default=None)
        report.append({
            "participant": name,
            "records": tracked_outings,
            "tracked_km": tracked_km,
            "dashboard_km": runner.get("km"),
            "latest_detection": latest,
            "status": "OBSERVED" if runner_records else "NO_POST_CHECKPOINT_RECORD",
        })

    if errors:
        raise LiveStateValidationError("; ".join(errors))
    return report


def validate_from_files(root: Path = ROOT) -> list[dict[str, Any]]:
    report = validate_live_state(
        load_json(root / "config/challenge.json"),
        load_json(root / "config/participants.json"),
        load_json(root / "bootstrap/current_baseline.json"),
        load_json(root / "state/activity_ledger.json"),
        load_json(root / "data.json"),
    )
    ledger = load_json(root / "state/activity_ledger.json")
    print(
        "All-runner live validation passed:",
        f"participants={len(report)} feed={ledger.get('last_feed_size', 0)} ",
        f"unmatched={ledger.get('unmatched_activities', 0)}",
    )
    for item in report:
        print(
            f"- {item['participant']}: {item['status']} records={item['records']} ",
            f"tracked_km={item['tracked_km']:.3f} total_km={item['dashboard_km']} ",
            f"latest={item['latest_detection'] or '-'}",
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    validate_from_files(args.root)

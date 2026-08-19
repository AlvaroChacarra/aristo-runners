from copy import deepcopy
from pathlib import Path

from scripts.state import load_json


ROOT = Path(__file__).resolve().parents[1]


def empty_ledger():
    """Return isolated ingestion state; tests must not depend on live persisted state."""
    return {
        "version": 1,
        "club_id": None,
        "strategy": None,
        "bootstrap_complete": False,
        "needs_current_baseline": False,
        "ignored_fingerprints": [],
        "records": [],
        "field_probe": None,
        "last_successful_update": None,
        "last_feed_size": 0,
        "unmatched_activities": 0,
        "unmatched_athletes": [],
    }


def configs():
    current = load_json(ROOT / "bootstrap/current_baseline.json")
    current.update({"complete": False, "checkpoint_date": None, "captured_at": None})
    current["totals_km"] = {name: None for name in current["totals_km"]}
    values = {
        "challenge": load_json(ROOT / "config/challenge.json"),
        "participants": load_json(ROOT / "config/participants.json"),
        "baseline": load_json(ROOT / "config/baseline.json"),
        "current": current,
        "ledger": empty_ledger(),
        "leaderboard_adjustments": {"version": 1, "adjustments": []},
    }
    return deepcopy(values)

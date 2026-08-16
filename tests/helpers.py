from copy import deepcopy
from pathlib import Path

from scripts.state import load_json


ROOT = Path(__file__).resolve().parents[1]


def configs():
    values = {
        "challenge": load_json(ROOT / "config/challenge.json"),
        "participants": load_json(ROOT / "config/participants.json"),
        "baseline": load_json(ROOT / "config/baseline.json"),
        "current": load_json(ROOT / "bootstrap/current_baseline.json"),
        "ledger": load_json(ROOT / "state/activity_ledger.json"),
    }
    return deepcopy(values)

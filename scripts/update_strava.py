from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.build_data import build_dashboard
from scripts.state import (
    atomic_write_bytes,
    atomic_write_json,
    decrypt_refresh_token,
    encrypt_refresh_token,
    load_json,
)
from scripts.strava_client import StravaClient, StravaError


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value).lower().split())


def athlete_parts(activity: dict[str, Any]) -> tuple[int | None, str]:
    athlete = activity.get("athlete") or {}
    athlete_id = athlete.get("id")
    display = athlete.get("name") or " ".join(filter(None, (athlete.get("firstname"), athlete.get("lastname"))))
    return (int(athlete_id) if athlete_id is not None else None, display.strip())


def resolve_participant(activity: dict[str, Any], participants: list[dict[str, Any]]) -> str | None:
    athlete_id, display = athlete_parts(activity)
    if athlete_id is not None:
        by_id = [p["name"] for p in participants if p.get("athlete_id") is not None and int(p["athlete_id"]) == athlete_id]
        if len(by_id) == 1:
            return by_id[0]
    observed = normalize(display)
    if not observed:
        return None
    matches: list[str] = []
    for participant in participants:
        aliases = [participant["name"], *participant.get("aliases", [])]
        normalized = {normalize(alias) for alias in aliases}
        canonical_tokens = normalize(participant["name"]).split()
        if len(canonical_tokens) > 1:
            normalized.add(f"{canonical_tokens[0]} {canonical_tokens[1][0]}")
            normalized.add(f"{canonical_tokens[0]} {canonical_tokens[-1][0]}")
        if observed in normalized:
            matches.append(participant["name"])
    return matches[0] if len(matches) == 1 else None


def activity_date(activity: dict[str, Any]) -> date | None:
    raw = activity.get("start_date_local") or activity.get("start_date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def fingerprint(activity: dict[str, Any]) -> str:
    if activity.get("id") is not None:
        payload: Any = {"id": str(activity["id"])}
    else:
        athlete_id, display = athlete_parts(activity)
        payload = {
            "athlete": str(athlete_id) if athlete_id is not None else normalize(display),
            "name": normalize(str(activity.get("name", ""))),
            "distance": round(float(activity.get("distance", 0)), 3),
            "moving_time": int(activity.get("moving_time", 0)),
            "elapsed_time": int(activity.get("elapsed_time", 0)),
            "elevation": round(float(activity.get("total_elevation_gain", 0)), 2),
            "sport_type": activity.get("sport_type") or activity.get("type"),
        }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def inspect_fields(activities: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(activities)
    present = lambda key: sum(item.get(key) is not None for item in activities)
    athlete_ids = sum((item.get("athlete") or {}).get("id") is not None for item in activities)
    date_count = sum(bool(item.get("start_date") or item.get("start_date_local")) for item in activities)
    top_level_fields = sorted({key for item in activities for key in item})
    athlete_fields = sorted({key for item in activities for key in (item.get("athlete") or {})})
    return {
        "sample_size": count,
        "observed_top_level_fields": top_level_fields,
        "observed_athlete_fields": athlete_fields,
        "id_present": present("id"),
        "start_date_present": present("start_date"),
        "start_date_local_present": present("start_date_local"),
        "athlete_id_present": athlete_ids,
        "historical_capable": count > 0 and present("id") == count and date_count == count,
    }


def detect_strategy(activities: list[dict[str, Any]]) -> str | None:
    if not activities:
        return None
    return "historical_exact" if inspect_fields(activities)["historical_capable"] else "incremental_fingerprint"


def process_feed(
    ledger: dict[str, Any],
    activities: list[dict[str, Any]],
    challenge: dict[str, Any],
    participants: list[dict[str, Any]],
    current_baseline: dict[str, Any],
    baseline_checkpoint: str,
    observed_on: date,
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    allowed = set(challenge["allowed_sport_types"])
    eligible = [item for item in activities if (item.get("sport_type") or item.get("type")) in allowed]
    updated["field_probe"] = inspect_fields(activities)
    updated["field_probe"]["eligible_sample_size"] = len(eligible)
    updated["field_probe"]["eligible_historical_capable"] = inspect_fields(eligible)["historical_capable"]
    updated["last_feed_size"] = len(activities)
    strategy = updated.get("strategy")
    if strategy is None:
        strategy = detect_strategy(eligible)
        if strategy is None:
            return updated
        updated["strategy"] = strategy

    existing = {record["fingerprint"] for record in updated.get("records", [])}
    ignored = set(updated.get("ignored_fingerprints", []))
    start = date.fromisoformat(challenge["challenge_start"])
    end = date.fromisoformat(challenge["challenge_end"])
    baseline_cutoff = date.fromisoformat(baseline_checkpoint)

    if strategy == "incremental_fingerprint" and not updated.get("bootstrap_complete"):
        ignored.update(fingerprint(item) for item in eligible)
        updated["ignored_fingerprints"] = sorted(ignored)
        if current_baseline.get("complete"):
            updated["bootstrap_complete"] = True
            updated["needs_current_baseline"] = False
            updated["incremental_checkpoint_date"] = current_baseline.get("checkpoint_date")
        else:
            updated["needs_current_baseline"] = True
        return updated

    unmatched = 0
    unmatched_athletes: set[str] = set()
    for item in eligible:
        fp = fingerprint(item)
        if fp in existing or fp in ignored:
            continue
        exact_date = activity_date(item)
        if strategy == "historical_exact":
            if exact_date is None:
                raise ValueError("Historical strategy encountered an activity without a reliable date")
            if not baseline_cutoff < exact_date <= end:
                continue
            record_date = exact_date
            accuracy = "exact"
        else:
            if observed_on < start or observed_on > end:
                continue
            record_date = observed_on
            accuracy = "observed"
        participant = resolve_participant(item, participants)
        if participant is None:
            unmatched += 1
            _, display = athlete_parts(item)
            unmatched_athletes.add(normalize(display) or "athlete_id_only")
            continue
        updated.setdefault("records", []).append(
            {
                "fingerprint": fp,
                "participant": participant,
                "activity_date": record_date.isoformat(),
                "date_accuracy": accuracy,
                "distance_km": round(float(item.get("distance", 0)) / 1000, 3),
                "moving_time_s": int(item.get("moving_time", 0)),
                "elapsed_time_s": int(item.get("elapsed_time", 0)),
                "elevation_m": round(float(item.get("total_elevation_gain", 0)), 1),
                "sport_type": item.get("sport_type") or item.get("type"),
            }
        )
        existing.add(fp)
    updated["unmatched_activities"] = unmatched
    updated["unmatched_athletes"] = sorted(unmatched_athletes)
    updated["records"].sort(key=lambda record: (record["activity_date"], record["participant"], record["fingerprint"]))
    return updated


def _required_env(environment: dict[str, str]) -> tuple[str, str, str]:
    names = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
    missing = [name for name in names if not environment.get(name)]
    if missing:
        raise RuntimeError(f"Missing required GitHub Secrets: {', '.join(missing)}")
    return tuple(environment[name] for name in names)  # type: ignore[return-value]


def run_update(
    root: Path = ROOT,
    environment: dict[str, str] | None = None,
    now: datetime | None = None,
    client_factory: Callable[..., StravaClient] = StravaClient,
) -> dict[str, Any] | None:
    challenge = load_json(root / "config/challenge.json")
    timezone = ZoneInfo(challenge["timezone"])
    now = now or datetime.now(timezone)
    if now.date() >= date.fromisoformat(challenge["club_endpoint_retirement"]):
        print("Strava club endpoint retirement guard active; no API request made.")
        return None
    environment = environment or dict(os.environ)
    client_id, client_secret, bootstrap_token = _required_env(environment)
    encrypted_path = root / "state/refresh_token.enc"
    refresh_token = (
        decrypt_refresh_token(encrypted_path.read_bytes(), client_secret)
        if encrypted_path.exists() and encrypted_path.stat().st_size
        else bootstrap_token
    )
    unauthenticated = client_factory()
    token_bundle = unauthenticated.refresh(client_id, client_secret, refresh_token)
    # Persist rotation before any subsequent API call can fail.
    atomic_write_bytes(encrypted_path, encrypt_refresh_token(token_bundle.refresh_token, client_secret))
    client = client_factory(access_token=token_bundle.access_token)

    participants = load_json(root / "config/participants.json")
    baseline = load_json(root / "config/baseline.json")
    current = load_json(root / "bootstrap/current_baseline.json")
    ledger = load_json(root / "state/activity_ledger.json")
    override = challenge.get("club_id")
    club_id = int(override or ledger.get("club_id") or client.discover_club(challenge["club_name"]))
    activities = client.list_club_activities(club_id)
    updated = process_feed(ledger, activities, challenge, participants, current, baseline["checkpoint_date"], now.date())
    updated["club_id"] = club_id
    updated["last_successful_update"] = now.isoformat(timespec="seconds")
    dashboard = build_dashboard(challenge, participants, baseline, current, updated, now)
    atomic_write_json(root / "state/activity_ledger.json", updated)
    atomic_write_json(root / "data.json", dashboard)
    probe = updated.get("field_probe") or {}
    print(
        "Strava update valid:",
        f"feed={len(activities)} strategy={updated.get('strategy')} ",
        f"id={probe.get('id_present', 0)}/{probe.get('sample_size', 0)} ",
        f"date={max(probe.get('start_date_present', 0), probe.get('start_date_local_present', 0))}/{probe.get('sample_size', 0)} ",
        f"new_records={len(updated.get('records', []))} unmatched={updated.get('unmatched_activities', 0)}",
    )
    return dashboard


if __name__ == "__main__":
    try:
        run_update()
    except StravaError as exc:
        raise SystemExit(f"Strava update failed safely: {exc}") from exc

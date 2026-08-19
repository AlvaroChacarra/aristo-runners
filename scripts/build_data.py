from __future__ import annotations

import argparse
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.state import atomic_write_json, load_json


ROOT = Path(__file__).resolve().parents[1]
MILESTONE_PCTS = (25, 50, 75, 100)


def challenge_day(day: date, start: date, days: int) -> int:
    return max(0, min(days, (day - start).days + 1))


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _baseline_series(item: dict[str, Any], days: int) -> tuple[list[float], set[int]]:
    values = [0.0] * days
    exact_days = set(range(1, 9)) | {16}
    for index, value in enumerate(item["d8"][:8]):
        values[index] = float(value)
    day8 = values[7]
    increment = float(item["d15total"]) / 7
    for day in range(9, 16):
        values[day - 1] = day8 + increment * (day - 8)
    values[15] = values[14] + float(item["d16add"])
    expected = float(item["total"])
    if not math.isclose(values[15], expected, abs_tol=0.011):
        raise ValueError(f"Baseline components do not equal total {expected}")
    for index in range(16, days):
        values[index] = expected
    return values, exact_days


def _validated_current_baseline(
    current: dict[str, Any], names: list[str], baseline_totals: dict[str, float], start: date, days: int
) -> tuple[date, dict[str, float]] | None:
    if not current.get("complete"):
        return None
    if not current.get("checkpoint_date"):
        raise ValueError("current_baseline.complete requires checkpoint_date")
    checkpoint = date.fromisoformat(current["checkpoint_date"])
    day = challenge_day(checkpoint, start, days)
    if day < 16 or checkpoint > start + timedelta(days=days - 1):
        raise ValueError("current baseline checkpoint is outside the supported challenge interval")
    totals = current.get("totals_km", {})
    if set(totals) != set(names) or any(not isinstance(totals[name], (int, float)) for name in names):
        raise ValueError("current baseline must contain one numeric total for every participant")
    parsed = {name: float(totals[name]) for name in names}
    for name in names:
        if parsed[name] + 0.01 < baseline_totals[name]:
            raise ValueError(f"current baseline for {name} is below the day-16 checkpoint")
    return checkpoint, parsed


def _validated_cumulative_stats(current: dict[str, Any], names: list[str]) -> dict[str, dict[str, Any]]:
    empty = {name: {"outings": 0, "elevation_m": 0.0, "elevation_complete": True} for name in names}
    raw = current.get("cumulative_stats")
    if not raw:
        return empty
    if set(raw) != set(names):
        raise ValueError("current baseline cumulative_stats must contain every participant")
    parsed: dict[str, dict[str, Any]] = {}
    for name in names:
        item = raw[name]
        outings = item.get("outings")
        elevation = item.get("elevation_m")
        complete = item.get("elevation_complete")
        if not isinstance(outings, int) or outings < 0:
            raise ValueError(f"invalid cumulative outings for {name}")
        if not isinstance(elevation, (int, float)) or elevation < 0:
            raise ValueError(f"invalid cumulative elevation for {name}")
        if not isinstance(complete, bool):
            raise ValueError(f"invalid elevation completeness for {name}")
        parsed[name] = {
            "outings": outings,
            "elevation_m": float(elevation),
            "elevation_complete": complete,
        }
    return parsed


def _validated_leaderboard_adjustments(
    raw: dict[str, Any] | None, names: list[str], start: date, end: date
) -> list[dict[str, Any]]:
    if not raw:
        return []
    if raw.get("version") != 1 or not isinstance(raw.get("adjustments"), list):
        raise ValueError("invalid leaderboard adjustments document")
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for item in raw["adjustments"]:
        adjustment_id = item.get("id")
        participant = item.get("participant")
        try:
            observed_on = date.fromisoformat(item.get("observed_on", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid leaderboard adjustment date") from exc
        if not isinstance(adjustment_id, str) or not adjustment_id or adjustment_id in seen:
            raise ValueError("leaderboard adjustment ids must be unique")
        if participant not in names:
            raise ValueError(f"leaderboard adjustment references unknown participant {participant}")
        if not start <= observed_on <= end:
            raise ValueError("leaderboard adjustment is outside the challenge")
        distance = item.get("distance_km")
        outings = item.get("outings")
        elevation = item.get("elevation_m")
        if not isinstance(distance, (int, float)) or distance <= 0:
            raise ValueError("leaderboard adjustment distance must be positive")
        if not isinstance(outings, int) or outings <= 0:
            raise ValueError("leaderboard adjustment outings must be positive")
        if elevation is not None and (not isinstance(elevation, (int, float)) or elevation < 0):
            raise ValueError("invalid leaderboard adjustment elevation")
        if not isinstance(item.get("source"), str) or not item["source"]:
            raise ValueError("leaderboard adjustment requires a source")
        seen.add(adjustment_id)
        parsed.append({**item, "observed_on_date": observed_on})
    return parsed


def _tracking_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    outings = len(records)
    distance = round(sum(float(record.get("distance_km", 0)) for record in records), 3)
    moving_time = sum(int(record.get("moving_time_s", 0)) for record in records)
    elevation = round(sum(float(record.get("elevation_m", 0)) for record in records), 1)
    distances = [float(record.get("distance_km", 0)) for record in records]
    distribution = {
        "short_under_5k": sum(value < 5 for value in distances),
        "medium_5_to_10k": sum(5 <= value < 10 for value in distances),
        "long_10k_plus": sum(value >= 10 for value in distances),
    }
    activities = [
        {
            "date": record["activity_date"],
            "date_basis": "exact" if record.get("date_accuracy") == "exact" else "detected",
            "detected_at": record.get("detected_at"),
            "distance_km": round(float(record.get("distance_km", 0)), 3),
            "moving_time_s": int(record.get("moving_time_s", 0)),
            "elevation_m": round(float(record.get("elevation_m", 0)), 1),
            "sport_type": record.get("sport_type"),
        }
        for record in sorted(records, key=lambda item: (item["activity_date"], item.get("detected_at") or ""), reverse=True)
    ]
    return {
        "available": outings > 0,
        "outings": outings,
        "distance_km": distance,
        "km_per_outing": round(distance / outings, 2) if outings else None,
        "longest_outing_km": round(max(distances), 2) if distances else None,
        "weighted_pace_min_per_km": round(moving_time / 60 / distance, 2) if moving_time and distance else None,
        "elevation_m": elevation,
        "elevation_m_per_km": round(elevation / distance, 1) if distance else None,
        "moving_time_s": moving_time,
        "distribution": distribution,
        "activities": activities,
    }


def _milestones(
    anchor_total: float,
    anchor_date: date,
    records: list[dict[str, Any]],
    objective: float,
) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: (item["activity_date"], item.get("detected_at") or ""))
    output: list[dict[str, Any]] = []
    for pct in MILESTONE_PCTS:
        target = objective * pct / 100
        if anchor_total + 0.001 >= target:
            output.append({
                "pct": pct,
                "target_km": round(target, 2),
                "status": "before_tracking",
                "reached_on": None,
                "checkpoint_date": anchor_date.isoformat(),
            })
            continue
        running = anchor_total
        reached: dict[str, Any] | None = None
        for record in ordered:
            running += float(record.get("distance_km", 0))
            if running + 0.001 >= target:
                exact = record.get("date_accuracy") == "exact"
                reached = {
                    "pct": pct,
                    "target_km": round(target, 2),
                    "status": "exact" if exact else "detected",
                    "reached_on": record["activity_date"],
                    "checkpoint_date": anchor_date.isoformat(),
                }
                break
        output.append(reached or {
            "pct": pct,
            "target_km": round(target, 2),
            "status": "pending",
            "reached_on": None,
            "checkpoint_date": anchor_date.isoformat(),
        })
    return output


def build_dashboard(
    challenge: dict[str, Any],
    participants: list[dict[str, Any]],
    baseline: dict[str, Any],
    current: dict[str, Any],
    ledger: dict[str, Any],
    now: datetime | None = None,
    leaderboard_adjustments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timezone = ZoneInfo(challenge["timezone"])
    now = now or datetime.now(timezone)
    start = date.fromisoformat(challenge["challenge_start"])
    end = date.fromisoformat(challenge["challenge_end"])
    days = int(challenge["challenge_days"])
    if (end - start).days + 1 != days:
        raise ValueError("challenge_days does not match inclusive start/end dates")
    objective = float(challenge["objective_per_runner_km"])
    names = [participant["name"] for participant in participants]
    if len({slugify(name) for name in names}) != len(names):
        raise ValueError("participant slugs must be unique")
    if set(names) != set(baseline["runners"]):
        raise ValueError("baseline participants do not match participants.json")
    adjustments = _validated_leaderboard_adjustments(leaderboard_adjustments, names, start, end)
    adjustments_by_runner: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for adjustment in adjustments:
        adjustments_by_runner[adjustment["participant"]].append(adjustment)

    series: dict[str, list[float]] = {}
    approximate_days: set[int] = set(range(9, 16))
    baseline_totals: dict[str, float] = {}
    for name in names:
        series[name], _ = _baseline_series(baseline["runners"][name], days)
        baseline_totals[name] = float(baseline["runners"][name]["total"])

    current_validated = _validated_current_baseline(current, names, baseline_totals, start, days)
    cumulative_stats = _validated_cumulative_stats(current, names) if current_validated else _validated_cumulative_stats({}, names)
    anchor_date = current_validated[0] if current_validated else date.fromisoformat(baseline["checkpoint_date"])
    anchor_totals = current_validated[1] if current_validated else baseline_totals
    data_through = anchor_date
    if current_validated:
        checkpoint, totals = current_validated
        checkpoint_day = challenge_day(checkpoint, start, days)
        span = checkpoint_day - 16
        if span:
            approximate_days.update(range(17, checkpoint_day + 1))
            for name in names:
                delta = totals[name] - baseline_totals[name]
                for day in range(17, checkpoint_day + 1):
                    series[name][day - 1] = baseline_totals[name] + delta * ((day - 16) / span)
                for day in range(checkpoint_day + 1, days + 1):
                    series[name][day - 1] = totals[name]

    records_by_runner: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    records_by_day: dict[tuple[str, int], float] = {}
    estimated_activity_dates = False
    for record in ledger.get("records", []):
        name = record["participant"]
        if name not in series:
            raise ValueError(f"ledger references unknown participant {name}")
        activity_date = date.fromisoformat(record["activity_date"])
        if not start <= activity_date <= end:
            continue
        day = challenge_day(activity_date, start, days)
        records_by_day[(name, day)] = records_by_day.get((name, day), 0.0) + float(record["distance_km"])
        records_by_runner[name].append(record)
        estimated_activity_dates |= record.get("date_accuracy") != "exact"

    for adjustment in adjustments:
        name = adjustment["participant"]
        day = challenge_day(adjustment["observed_on_date"], start, days)
        records_by_day[(name, day)] = records_by_day.get((name, day), 0.0) + float(adjustment["distance_km"])
        data_through = max(data_through, adjustment["observed_on_date"])

    tracking_active = bool(ledger.get("bootstrap_complete")) or ledger.get("strategy") == "historical_exact"
    last_feed_check_dt = _parse_datetime(ledger.get("last_successful_update"), timezone)
    if tracking_active and last_feed_check_dt:
        data_through = max(data_through, min(last_feed_check_dt.date(), end))
    elif records_by_day:
        latest_record_day = max(day for _, day in records_by_day)
        data_through = max(data_through, start + timedelta(days=latest_record_day - 1))

    anchor_day = challenge_day(anchor_date, start, days)
    for name in names:
        cumulative_add = 0.0
        for day in range(anchor_day, days + 1):
            cumulative_add += records_by_day.get((name, day), 0.0)
            series[name][day - 1] += cumulative_add

    today = now.date()
    current_day = challenge_day(today, start, days)
    display_day = current_day if current_day else (0 if today < start else days)
    data_day = challenge_day(data_through, start, days)
    value_day = min(max(data_day, 1), days)
    finished = today > end
    remaining_calendar_days = max(0, days - current_day)

    runners: list[dict[str, Any]] = []
    for order, name in enumerate(names):
        km = round(series[name][value_day - 1], 2)
        remaining = round(max(0.0, objective - km), 2)
        pace_required = None if finished or remaining_calendar_days == 0 else round(remaining / remaining_calendar_days, 2)
        projection = None if finished else round((km / max(data_day, 1)) * days, 1)
        tracked = _tracking_stats(records_by_runner[name])
        cumulative = cumulative_stats[name]
        reconciled = adjustments_by_runner[name]
        reconciled_km = round(sum(float(item["distance_km"]) for item in reconciled), 2)
        reconciled_outings = sum(item["outings"] for item in reconciled)
        reconciled_elevation = sum(float(item["elevation_m"] or 0) for item in reconciled)
        outings_total = cumulative["outings"] + tracked["outings"] + reconciled_outings
        elevation_total = round(cumulative["elevation_m"] + tracked["elevation_m"] + reconciled_elevation)
        milestone_records = records_by_runner[name] + [
            {
                "activity_date": item["observed_on"], "date_accuracy": "detected",
                "detected_at": item["captured_at"], "distance_km": item["distance_km"],
            }
            for item in reconciled
        ]
        runner_milestones = _milestones(anchor_totals[name], anchor_date, milestone_records, objective)
        runners.append({
            "slug": slugify(name),
            "name": name,
            "km": km,
            "progress_pct": round(km / objective * 100, 1),
            "remaining_km": remaining,
            "outings_tracked": tracked["outings"],
            "elevation_tracked_m": round(tracked["elevation_m"]),
            "outings_total": outings_total,
            "elevation_total_m": elevation_total,
            "elevation_total_complete": cumulative["elevation_complete"] and all(
                item["elevation_m"] is not None for item in reconciled
            ),
            "moving_time_tracked_s": tracked["moving_time_s"],
            "pace_required_km_per_day": pace_required,
            "projection_km": projection,
            "projection_gap_km": None if projection is None else round(projection - objective, 1),
            "on_track": km >= objective or (projection is not None and projection >= objective),
            "completed": km >= objective,
            "tracking": tracked,
            "leaderboard_adjustment": ({
                "distance_km": reconciled_km,
                "outings": reconciled_outings,
                "observed_through": max(item["observed_on"] for item in reconciled),
                "source": "Strava club leaderboard",
                "activity_details_available": False,
            } if reconciled else None),
            "milestones": runner_milestones,
            "_order": order,
        })
    runners.sort(key=lambda runner: (-runner["km"], runner["_order"]))
    total_km = round(sum(runner["km"] for runner in runners), 2)
    for rank, runner in enumerate(runners, 1):
        runner["rank"] = rank
        runner["contribution_pct"] = round(runner["km"] / total_km * 100, 1) if total_km else 0.0
        runner.pop("_order")

    total_objective = objective * len(names)
    group_projection = None if finished else round((total_km / max(data_day, 1)) * days, 1)
    group_projection_gap = round(total_km - total_objective, 1) if finished else round(group_projection - total_objective, 1)
    labels = [(start + timedelta(days=index)).isoformat() for index in range(days)]

    all_tracked = [(runner, activity) for runner in runners for activity in runner["tracking"]["activities"]]
    cards: list[dict[str, Any]] = []
    leader = runners[0]
    cards.append({
        "kind": "leader", "label": "Líder actual", "name": leader["name"],
        "runner_slug": leader["slug"], "value": f"{leader['km']:.1f} km", "scope": "total",
    })
    incomplete = [runner for runner in runners if not runner["completed"]]
    closest = min(incomplete, key=lambda runner: runner["remaining_km"], default=leader)
    cards.append({
        "kind": "closest", "label": f"Más cerca de {objective:g} km", "name": closest["name"],
        "runner_slug": closest["slug"], "value": f"le faltan {closest['remaining_km']:.1f} km", "scope": "total",
    })
    if all_tracked:
        longest_runner, longest = max(all_tracked, key=lambda item: item[1]["distance_km"])
        cards.append({
            "kind": "longest_tracked", "label": "Salida más larga registrada", "name": longest_runner["name"],
            "runner_slug": longest_runner["slug"], "value": f"{longest['distance_km']:.1f} km",
            "scope": "post_tracking_checkpoint",
        })
        average_candidates = [runner for runner in runners if runner["tracking"]["outings"]]
        best_average = max(average_candidates, key=lambda runner: runner["tracking"]["km_per_outing"])
        cards.append({
            "kind": "best_average_tracked", "label": "Mejor media por salida", "name": best_average["name"],
            "runner_slug": best_average["slug"], "value": f"{best_average['tracking']['km_per_outing']:.1f} km/salida",
            "scope": "post_tracking_checkpoint",
        })

    reached = [
        (runner, milestone) for runner in runners for milestone in runner["milestones"]
        if milestone["status"] in {"detected", "exact"}
    ]
    if reached:
        latest_runner, latest = max(reached, key=lambda item: (item[1]["reached_on"], item[1]["pct"]))
        cards.append({
            "kind": "latest_milestone", "label": "Último hito alcanzado", "name": latest_runner["name"],
            "runner_slug": latest_runner["slug"], "value": f"{latest['pct']}% del objetivo",
            "scope": "post_tracking_checkpoint",
        })

    detected_values = [
        record.get("detected_at") or record.get("activity_date")
        for records in records_by_runner.values() for record in records
    ]
    latest_activity_detected_at = max(detected_values) if detected_values else None
    if tracking_active and last_feed_check_dt:
        last_complete_observation = last_feed_check_dt.isoformat(timespec="seconds")
    elif current_validated:
        last_complete_observation = current.get("captured_at") or anchor_date.isoformat()
    else:
        last_complete_observation = anchor_date.isoformat()
    reconciliation_datetimes = [
        parsed for item in adjustments
        if (parsed := _parse_datetime(item.get("captured_at"), timezone)) is not None
    ]
    last_reconciliation_dt = max(reconciliation_datetimes, default=None)
    current_observation_dt = _parse_datetime(last_complete_observation, timezone)
    if last_reconciliation_dt and (current_observation_dt is None or last_reconciliation_dt > current_observation_dt):
        last_complete_observation = last_reconciliation_dt.isoformat(timespec="seconds")

    return {
        "schema_version": 2,
        "generated_at": now.isoformat(timespec="seconds"),
        "data_through": data_through.isoformat(),
        "challenge": {
            "club_name": challenge["club_name"], "start": start.isoformat(), "end": end.isoformat(),
            "days": days, "current_day": display_day, "finished": finished,
            "objective_per_runner_km": objective, "objective_total_km": total_objective,
            "timezone": challenge["timezone"],
        },
        "summary": {
            "total_km": total_km,
            "progress_pct": round(total_km / total_objective * 100, 1),
            "projection_km": group_projection,
            "projection_gap_km": group_projection_gap,
            "active_runners": sum(runner["km"] > 0 for runner in runners),
            "participants": len(runners),
            "completed_runners": sum(runner["completed"] for runner in runners),
            "on_track_runners": sum(runner["on_track"] for runner in runners),
            "outings_tracked": sum(runner["tracking"]["outings"] for runner in runners),
            "elevation_tracked_m": round(sum(runner["tracking"]["elevation_m"] for runner in runners)),
            "outings_total": sum(runner["outings_total"] for runner in runners),
            "elevation_total_m": round(sum(runner["elevation_total_m"] for runner in runners)),
            "elevation_total_complete": all(runner["elevation_total_complete"] for runner in runners),
        },
        "runners": runners,
        "series": {
            "labels": labels,
            "datasets": [
                {"name": name, "slug": slugify(name), "cumulative_km": [round(value, 2) for value in series[name]]}
                for name in names
            ],
        },
        "highlights": {
            "leader": {"name": leader["name"], "km": leader["km"]},
            "completed_objective": sum(runner["completed"] for runner in runners),
            "on_track": sum(runner["on_track"] for runner in runners),
            "cards": cards,
        },
        "quality": {
            "last_feed_check": ledger.get("last_successful_update"),
            "last_complete_observation": last_complete_observation,
            "latest_activity_detected_at": latest_activity_detected_at,
            "baseline_checkpoint": baseline["checkpoint_date"],
            "tracking_checkpoint": ledger.get("incremental_checkpoint_date") if tracking_active else None,
            "totals_basis": "checkpoint_plus_incremental" if tracking_active else "historical_checkpoint",
            "activity_metrics_basis": "post_tracking_checkpoint",
            "cumulative_activity_stats_basis": "golden_checkpoint_plus_incremental" if current.get("cumulative_stats") else "post_tracking_only",
            "tracking_active": tracking_active,
            "activity_metrics_available": bool(all_tracked),
            "leaderboard_reconciliation_count": len(adjustments),
            "leaderboard_reconciliation_km": round(sum(float(item["distance_km"]) for item in adjustments), 2),
            "last_leaderboard_reconciliation": (
                last_reconciliation_dt.isoformat(timespec="seconds") if last_reconciliation_dt else None
            ),
        },
        "coverage": {
            "baseline_checkpoint": baseline["checkpoint_date"],
            "strategy": ledger.get("strategy"),
            "bootstrap_complete": bool(ledger.get("bootstrap_complete")),
            "needs_current_baseline": bool(ledger.get("needs_current_baseline")),
            "approximate_chart_days": sorted(approximate_days),
            "estimated_activity_dates": estimated_activity_dates,
            "outings_and_elevation_are_post_checkpoint_only": True,
            "leaderboard_adjustments": len(adjustments),
        },
    }


def build_from_files(root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    dashboard = build_dashboard(
        load_json(root / "config/challenge.json"), load_json(root / "config/participants.json"),
        load_json(root / "config/baseline.json"), load_json(root / "bootstrap/current_baseline.json"),
        load_json(root / "state/activity_ledger.json"), now,
        load_json(root / "state/leaderboard_adjustments.json"),
    )
    atomic_write_json(root / "data.json", dashboard)
    return dashboard


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    build_from_files(args.root)

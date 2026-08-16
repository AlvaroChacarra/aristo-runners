from __future__ import annotations

import argparse
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.state import atomic_write_json, load_json


ROOT = Path(__file__).resolve().parents[1]


def challenge_day(day: date, start: date, days: int) -> int:
    return max(0, min(days, (day - start).days + 1))


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


def build_dashboard(
    challenge: dict[str, Any],
    participants: list[dict[str, Any]],
    baseline: dict[str, Any],
    current: dict[str, Any],
    ledger: dict[str, Any],
    now: datetime | None = None,
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
    if set(names) != set(baseline["runners"]):
        raise ValueError("baseline participants do not match participants.json")

    series: dict[str, list[float]] = {}
    approximate_days: set[int] = set(range(9, 16))
    baseline_totals: dict[str, float] = {}
    for name in names:
        series[name], _ = _baseline_series(baseline["runners"][name], days)
        baseline_totals[name] = float(baseline["runners"][name]["total"])

    current_validated = _validated_current_baseline(current, names, baseline_totals, start, days)
    data_through = date.fromisoformat(baseline["checkpoint_date"])
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
        data_through = max(data_through, checkpoint)

    record_counts = {name: 0 for name in names}
    record_elevation = {name: 0.0 for name in names}
    record_moving_time = {name: 0 for name in names}
    records_by_day: dict[tuple[str, int], float] = {}
    estimated_activity_dates = False
    for record in ledger.get("records", []):
        name = record["participant"]
        if name not in series:
            raise ValueError(f"ledger references unknown participant {name}")
        activity_date = date.fromisoformat(record["activity_date"])
        day = challenge_day(activity_date, start, days)
        if not start <= activity_date <= end:
            continue
        records_by_day[(name, day)] = records_by_day.get((name, day), 0.0) + float(record["distance_km"])
        record_counts[name] += 1
        record_elevation[name] += float(record.get("elevation_m", 0))
        record_moving_time[name] += int(record.get("moving_time_s", 0))
        estimated_activity_dates |= record.get("date_accuracy") != "exact"
        data_through = max(data_through, activity_date)

    anchor_day = challenge_day(current_validated[0], start, days) if current_validated else 16
    for name in names:
        cumulative_add = 0.0
        for day in range(anchor_day + 1, days + 1):
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
        remaining = max(0.0, objective - km)
        pace_required = None if finished or remaining_calendar_days == 0 else round(remaining / remaining_calendar_days, 2)
        projection = None if finished else round((km / max(data_day, 1)) * days, 1)
        runners.append(
            {
                "name": name,
                "km": km,
                "progress_pct": round(km / objective * 100, 1),
                "outings_tracked": record_counts[name],
                "elevation_tracked_m": round(record_elevation[name]),
                "moving_time_tracked_s": record_moving_time[name],
                "pace_required_km_per_day": pace_required,
                "projection_km": projection,
                "on_track": km >= objective or (projection is not None and projection >= objective),
                "_order": order,
            }
        )
    runners.sort(key=lambda runner: (-runner["km"], runner["_order"]))
    for rank, runner in enumerate(runners, 1):
        runner["rank"] = rank
        runner.pop("_order")

    total_km = round(sum(runner["km"] for runner in runners), 2)
    total_objective = objective * len(names)
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    top = runners[0]
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "data_through": data_through.isoformat(),
        "challenge": {
            "club_name": challenge["club_name"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "current_day": display_day,
            "finished": finished,
            "objective_per_runner_km": objective,
            "objective_total_km": total_objective,
            "timezone": challenge["timezone"],
        },
        "summary": {
            "total_km": total_km,
            "progress_pct": round(total_km / total_objective * 100, 1),
            "active_runners": sum(runner["km"] > 0 for runner in runners),
            "participants": len(runners),
            "outings_tracked": sum(record_counts.values()),
            "elevation_tracked_m": round(sum(record_elevation.values())),
        },
        "runners": runners,
        "series": {
            "labels": labels,
            "datasets": [{"name": name, "cumulative_km": [round(value, 2) for value in series[name]]} for name in names],
        },
        "highlights": {
            "leader": {"name": top["name"], "km": top["km"]},
            "completed_objective": sum(runner["km"] >= objective for runner in runners),
            "on_track": sum(runner["on_track"] for runner in runners),
        },
        "coverage": {
            "baseline_checkpoint": baseline["checkpoint_date"],
            "strategy": ledger.get("strategy"),
            "bootstrap_complete": bool(ledger.get("bootstrap_complete")),
            "needs_current_baseline": bool(ledger.get("needs_current_baseline")),
            "approximate_chart_days": sorted(approximate_days),
            "estimated_activity_dates": estimated_activity_dates,
            "outings_and_elevation_are_post_checkpoint_only": True,
        },
    }


def build_from_files(root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    dashboard = build_dashboard(
        load_json(root / "config/challenge.json"),
        load_json(root / "config/participants.json"),
        load_json(root / "config/baseline.json"),
        load_json(root / "bootstrap/current_baseline.json"),
        load_json(root / "state/activity_ledger.json"),
        now,
    )
    atomic_write_json(root / "data.json", dashboard)
    return dashboard


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    build_from_files(args.root)

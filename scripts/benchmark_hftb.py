"""Benchmark the published HFTB roster across fresh Python processes."""

import argparse
import csv
import json
import math
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

import ortools

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from softball_fielding import COED_RULES, Player, lineup_plan, optimize_game
from softball_fielding.models import INFIELD, INNINGS, OUTFIELD, POSITIONS
from softball_fielding.optimizer import POSITION_FALLBACKS, STINT_PROGRESS
from softball_fielding.quality import (
    continuity_vector,
    is_lexicographically_no_worse,
    schedule_quality_metrics,
)

ROSTER_CSV = ROOT / "roster_positions.csv"
QUALITY_TARGET = (5, 0, 9, 20, 21)
QUALITY_MINIMUM_PASS_RATE = 0.9
PREFIX = (4, 210, 0)


def _selected(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "x"}


def _gender(value: object) -> str:
    return (
        "Woman"
        if str(value).strip().lower() in {"f", "female", "w", "woman"}
        else "Man"
    )


def load_players() -> tuple[Player, ...]:
    """Load the exact checked-in public roster without importing the web app."""

    with ROSTER_CSV.open(encoding="utf-8-sig", newline="") as source:
        rows = tuple(csv.DictReader(source))
    return tuple(
        Player(
            row["Name"].strip(),
            _gender(row["Gender"]),
            frozenset(
                position for position in POSITIONS if _selected(row[position])
            ),
        )
        for row in rows
    )


def _eligible(player: Player, active_positions: tuple[str, ...]) -> set[str]:
    positions = {"C", *player.preferences}
    for preferred in player.preferences:
        positions.update(POSITION_FALLBACKS.get(preferred, ()))
    if "C" not in active_positions and "RF" not in active_positions:
        if "RF" in player.preferences:
            positions.add("RC")
    return positions.intersection(active_positions)


def assert_legal_and_consistent(result, players: tuple[Player, ...]) -> None:
    """Validate result contracts independently from optimizer variables."""

    expected_positions, minimum_women = lineup_plan(
        len(players), sum(player.is_woman for player in players), COED_RULES
    )
    by_name = {player.name: player for player in players}
    actual_innings = Counter()
    actual_positions = {player.name: set() for player in players}

    assert len(result.assignments) == INNINGS
    assert result.active_positions == expected_positions
    for inning in result.assignments:
        assert set(inning) == set(expected_positions)
        assert len(set(inning.values())) == result.lineup_size
        actual_innings.update(inning.values())
        for position, name in inning.items():
            assert name in by_name
            assert position in _eligible(by_name[name], expected_positions)
            actual_positions[name].add(position)
        assigned = [by_name[name] for name in inning.values()]
        assert sum(player.is_woman for player in assigned) >= minimum_women
        assert any(
            by_name[name].is_woman and position in INFIELD
            for position, name in inning.items()
        )
        assert any(
            by_name[name].is_woman and position in OUTFIELD
            for position, name in inning.items()
        )

    assert result.player_innings == {
        player.name: actual_innings[player.name] for player in players
    }
    assert result.player_positions == {
        player.name: tuple(
            position
            for position in POSITIONS
            if position in actual_positions[player.name]
        )
        for player in players
    }


def run_once(players: tuple[Player, ...], budget: float) -> dict[str, object]:
    started = perf_counter()
    events = []

    def record_progress(message: str) -> None:
        events.append(
            {"message": message, "elapsed_seconds": perf_counter() - started}
        )

    result = optimize_game(
        players,
        profile=COED_RULES,
        max_solve_seconds=budget,
        progress_callback=record_progress,
    )
    elapsed = perf_counter() - started
    assert_legal_and_consistent(result, players)
    metrics = schedule_quality_metrics(result)
    prefix = (
        metrics["playing_time_spread"],
        metrics["scaled_deviation"],
        metrics["fallback_innings"],
    )
    quality = continuity_vector(metrics)
    prefix_seconds = next(
        event["elapsed_seconds"]
        for event in events
        if event["message"] == STINT_PROGRESS
    )
    return {
        "elapsed_seconds": round(elapsed, 6),
        "fairness_fallback_seconds": round(prefix_seconds, 6),
        "solver_status": result.solver_status,
        "metrics": metrics,
        "continuity_vector": quality,
        "prefix_pass": prefix == PREFIX,
        "quality_pass": is_lexicographically_no_worse(quality, QUALITY_TARGET),
        "progress_events": events,
    }


def worker(process_index: int, runs: int, budget: float) -> None:
    players = load_players()
    run_once(players, budget)  # Excluded warm-up in every fresh process.
    records = []
    for run_index in range(1, runs + 1):
        record = run_once(players, budget)
        record.update({"process_index": process_index, "run_index": run_index})
        records.append(record)
    print(json.dumps(records, separators=(",", ":")), flush=True)


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def orchestrate(arguments: argparse.Namespace) -> int:
    records = []
    for process_index in range(1, arguments.processes + 1):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-process",
            str(process_index),
            "--worker-runs",
            str(arguments.runs_per_process),
            "--budget",
            str(arguments.budget),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        records.extend(json.loads(completed.stdout))

    elapsed = [record["elapsed_seconds"] for record in records]
    prefix_elapsed = [record["fairness_fallback_seconds"] for record in records]
    report = {
        "environment": {
            "commit": git_revision(),
            "os": platform.platform(),
            "cpu": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "ortools": ortools.__version__,
            "worker_count": 8,
            "nominal_budget_seconds": arguments.budget,
            "fresh_processes": arguments.processes,
            "warmups_excluded": arguments.processes,
            "qualifying_runs": len(records),
        },
        "targets": {
            "fairness_fallback_prefix": PREFIX,
            "continuity_target": QUALITY_TARGET,
            "continuity_minimum_pass_rate": QUALITY_MINIMUM_PASS_RATE,
            "solver_p95_seconds": 5.5,
            "solver_max_seconds": 6.0,
            "fairness_fallback_p95_seconds": 0.25,
            "fairness_fallback_max_seconds": 0.75,
        },
        "summary": {
            "solver_p95_seconds": percentile_95(elapsed),
            "solver_max_seconds": max(elapsed),
            "fairness_fallback_p95_seconds": percentile_95(prefix_elapsed),
            "fairness_fallback_max_seconds": max(prefix_elapsed),
            "status_distribution": dict(
                sorted(Counter(record["solver_status"] for record in records).items())
            ),
            "all_prefix_pass": all(record["prefix_pass"] for record in records),
            "quality_pass_count": sum(
                record["quality_pass"] for record in records
            ),
            "quality_pass_rate": sum(
                record["quality_pass"] for record in records
            )
            / len(records),
            "all_quality_pass": all(record["quality_pass"] for record in records),
        },
        "runs": records,
    }
    output = Path(arguments.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))

    summary = report["summary"]
    return int(
        not summary["all_prefix_pass"]
        or summary["quality_pass_rate"] < QUALITY_MINIMUM_PASS_RATE
        or summary["solver_p95_seconds"] > 5.5
        or summary["solver_max_seconds"] > 6.0
        or summary["fairness_fallback_p95_seconds"] > 0.25
        or summary["fairness_fallback_max_seconds"] > 0.75
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--runs-per-process", type=int, default=5)
    parser.add_argument(
        "--output", default="benchmarks/hftb-5s-reference.json"
    )
    parser.add_argument("--worker-process", type=int)
    parser.add_argument("--worker-runs", type=int)
    arguments = parser.parse_args()
    if arguments.worker_process is not None:
        worker(arguments.worker_process, arguments.worker_runs, arguments.budget)
        return 0
    if arguments.processes < 4 or arguments.processes * arguments.runs_per_process < 20:
        parser.error("reference runs require at least 20 solves across four processes")
    return orchestrate(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

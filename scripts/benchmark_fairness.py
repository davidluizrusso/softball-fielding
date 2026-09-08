"""Repeat optimizer stress cases at candidate fairness-phase time limits."""

import argparse
import json
from collections import Counter
from time import perf_counter

from softball_fielding import LineupError, OPEN_RULES, Player, optimize_game
from softball_fielding.models import INNINGS, POSITIONS


def flexible_roster(size: int):
    return [
        Player(f"Player {index + 1}", "Man", frozenset(POSITIONS))
        for index in range(size)
    ]


def fairness_metrics(result):
    counts = tuple(result.player_innings.values())
    player_count = len(counts)
    total_slots = INNINGS * result.lineup_size
    return {
        "counts": dict(sorted(Counter(counts).items())),
        "spread": max(counts) - min(counts),
        "scaled_deviation": sum(
            abs(player_count * count - total_slots) for count in counts
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budgets", nargs="+", type=float, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--sizes", nargs="+", type=int, default=(8, 10, 13, 15))
    arguments = parser.parse_args()

    for size in arguments.sizes:
        for budget in arguments.budgets:
            for repeat in range(1, arguments.repeats + 1):
                messages = []
                started_at = perf_counter()
                result = None
                error = None
                try:
                    result = optimize_game(
                        flexible_roster(size),
                        profile=OPEN_RULES,
                        max_solve_seconds=budget + 0.6,
                        fairness_solve_seconds=budget,
                        progress_callback=messages.append,
                    )
                except LineupError as caught:
                    error = str(caught)
                record = {
                    "size": size,
                    "fairness_budget_seconds": budget,
                    "repeat": repeat,
                    "elapsed_seconds": round(perf_counter() - started_at, 3),
                    "fairness_proven": any(
                        message.startswith("Fairest playing-time balance proven")
                        for message in messages
                    ),
                    "overall_status": (
                        result.solver_status if result is not None else "ERROR"
                    ),
                }
                if result is not None:
                    record.update(fairness_metrics(result))
                if error is not None:
                    record["later_stage_error"] = error
                print(
                    json.dumps(record, sort_keys=True),
                    flush=True,
                )


if __name__ == "__main__":
    main()

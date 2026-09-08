"""Independent schedule-quality reconstruction for tests and benchmarks."""

from itertools import groupby
from typing import Dict, Tuple

from .models import INNINGS, ScheduleResult


QualityMetrics = Dict[str, int]
ContinuityVector = Tuple[int, int, int, int, int]


def player_state_sequences(result: ScheduleResult) -> Dict[str, Tuple[str, ...]]:
    """Reconstruct each player's seven field-or-Bench states from assignments."""

    return {
        player_name: tuple(
            next(
                (
                    position
                    for position, assigned_name in inning.items()
                    if assigned_name == player_name
                ),
                "Bench",
            )
            for inning in result.assignments
        )
        for player_name in result.player_innings
    }


def schedule_quality_metrics(result: ScheduleResult) -> QualityMetrics:
    """Compute all eight optimization metrics without solver internals."""

    sequences = player_state_sequences(result)
    runs = {
        player_name: tuple(
            (state, len(tuple(group))) for state, group in groupby(sequence)
        )
        for player_name, sequence in sequences.items()
    }
    innings = tuple(result.player_innings.values())
    player_count = len(innings)
    total_slots = INNINGS * result.lineup_size

    return {
        "playing_time_spread": max(innings) - min(innings),
        "scaled_deviation": sum(
            abs(player_count * count - total_slots) for count in innings
        ),
        "fallback_innings": sum(map(len, result.fallback_assignments)),
        "one_inning_state_runs": sum(
            length == 1
            for player_runs in runs.values()
            for _state, length in player_runs
        ),
        "excess_field_positions": sum(
            max(0, len({state for state in sequence if state != "Bench"}) - 2)
            for sequence in sequences.values()
        ),
        "two_inning_state_runs": sum(
            length == 2
            for player_runs in runs.values()
            for _state, length in player_runs
        ),
        "distinct_field_positions": sum(
            len({state for state in sequence if state != "Bench"})
            for sequence in sequences.values()
        ),
        "transitions": sum(
            first != second
            for sequence in sequences.values()
            for first, second in zip(sequence, sequence[1:])
        ),
    }


def continuity_vector(metrics: QualityMetrics) -> ContinuityVector:
    """Return continuity metrics in their documented lexicographic order."""

    return (
        metrics["one_inning_state_runs"],
        metrics["excess_field_positions"],
        metrics["two_inning_state_runs"],
        metrics["distinct_field_positions"],
        metrics["transitions"],
    )


def is_lexicographically_no_worse(
    candidate: ContinuityVector, reference: ContinuityVector
) -> bool:
    """Return whether candidate is equal or better under objective priority."""

    return candidate <= reference

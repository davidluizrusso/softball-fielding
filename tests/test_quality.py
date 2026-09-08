import csv
from pathlib import Path

from ortools.sat.python import cp_model

from softball_fielding import (
    COED_RULES,
    OPEN_RULES,
    Player,
    ScheduleResult,
    optimize_game,
)
from softball_fielding.models import POSITIONS
from softball_fielding.optimizer import _candidate_is_no_worse
from softball_fielding.quality import (
    continuity_vector,
    is_lexicographically_no_worse,
    player_state_sequences,
    schedule_quality_metrics,
)


ROOT = Path(__file__).resolve().parents[1]


def published_hftb_players():
    with (ROOT / "roster_positions.csv").open(
        encoding="utf-8-sig", newline=""
    ) as source:
        rows = tuple(csv.DictReader(source))
    return tuple(
        Player(
            row["Name"].strip(),
            (
                "Woman"
                if row["Gender"].strip().lower() in {"f", "female", "w", "woman"}
                else "Man"
            ),
            frozenset(
                position
                for position in POSITIONS
                if row[position].strip().lower() in {"1", "true", "t", "yes", "y", "x"}
            ),
        )
        for row in rows
    )


def test_quality_metrics_reconstruct_field_and_bench_states():
    assignments = (
        {"P": "A"},
        {"P": "A"},
        {"P": "A"},
        {"P": "B"},
        {"P": "B"},
        {"P": "A"},
        {"P": "A"},
    )
    result = ScheduleResult(
        assignments=assignments,
        active_positions=("P",),
        player_innings={"A": 5, "B": 2},
        player_positions={"A": ("P",), "B": ("P",)},
        solver_status="FEASIBLE",
        fallback_assignments=({}, {}, {}, {"P": "B"}, {}, {}, {}),
    )

    assert player_state_sequences(result) == {
        "A": ("P", "P", "P", "Bench", "Bench", "P", "P"),
        "B": ("Bench", "Bench", "Bench", "P", "P", "Bench", "Bench"),
    }
    assert schedule_quality_metrics(result) == {
        "playing_time_spread": 3,
        "scaled_deviation": 6,
        "fallback_innings": 1,
        "one_inning_state_runs": 0,
        "excess_field_positions": 0,
        "two_inning_state_runs": 4,
        "distinct_field_positions": 2,
        "transitions": 4,
    }


def test_quality_comparison_is_lexicographic_not_component_wise():
    reference = (5, 0, 9, 20, 21)

    assert is_lexicographically_no_worse((5, 0, 9, 19, 99), reference)
    assert is_lexicographically_no_worse((4, 99, 99, 99, 99), reference)
    assert not is_lexicographically_no_worse((5, 1, 0, 0, 0), reference)
    assert not is_lexicographically_no_worse((6, 0, 0, 0, 0), reference)


def test_timed_candidate_requires_a_solved_no_worse_continuity_vector():
    incumbent = (5, 0, 9, 19, 20)

    assert _candidate_is_no_worse(cp_model.FEASIBLE, incumbent, incumbent)
    assert _candidate_is_no_worse(
        cp_model.OPTIMAL, (5, 0, 8, 99, 99), incumbent
    )
    assert not _candidate_is_no_worse(
        cp_model.FEASIBLE, (5, 0, 10, 0, 0), incumbent
    )
    assert not _candidate_is_no_worse(cp_model.UNKNOWN, incumbent, incumbent)


def test_published_hftb_default_preserves_fairness_and_quality_contract():
    result = optimize_game(published_hftb_players(), profile=COED_RULES)
    metrics = schedule_quality_metrics(result)

    assert (
        metrics["playing_time_spread"],
        metrics["scaled_deviation"],
        metrics["fallback_innings"],
    ) == (4, 210, 0)
    assert continuity_vector(metrics) <= (5, 0, 9, 20, 21)
    assert result.solver_status == "FEASIBLE"


def test_default_solve_budget_is_five_seconds_and_override_remains_supported(
    monkeypatch,
):
    captured_budgets = []
    real_solver = cp_model.CpSolver

    class BudgetCapturingSolver:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters

        def Solve(self, model):
            captured_budgets.append(self.parameters.max_time_in_seconds)
            return self.delegate.Solve(model)

        def Value(self, variable):
            return self.delegate.Value(variable)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    monkeypatch.setattr(
        "softball_fielding.optimizer.cp_model.CpSolver", BudgetCapturingSolver
    )
    players = tuple(
        Player(position, "Man", frozenset((position,))) for position in POSITIONS
    )
    optimize_game(
        players,
        profile=OPEN_RULES,
        max_solve_seconds=0.5,
    )

    assert captured_budgets
    assert max(captured_budgets) <= 0.5
    assert optimize_game.__kwdefaults__["max_solve_seconds"] == 5.0

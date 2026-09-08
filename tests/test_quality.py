import json
import math
from collections import Counter
from pathlib import Path

from ortools.sat.python import cp_model

from softball_fielding import (
    OPEN_RULES,
    Player,
    ScheduleResult,
    optimize_game,
)
from softball_fielding.models import POSITIONS
from softball_fielding.optimizer import (
    _bound_continuity_by_incumbent,
    _candidate_is_no_worse,
    _continuity_weights,
)
from softball_fielding.quality import (
    continuity_vector,
    is_lexicographically_no_worse,
    player_state_sequences,
    schedule_quality_metrics,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_actual_weighted_ceiling_allows_better_prefix_to_spend_lower_tiers():
    weights = _continuity_weights(player_count=15, position_count=10)
    incumbent = (5, 0, 9, 20, 21)
    better_prefix = (4, 1, 10, 30, 40)
    incumbent_penalty = sum(
        value * weight for value, weight in zip(incumbent, weights)
    )
    model = cp_model.CpModel()
    choose_better_prefix = model.NewBoolVar("choose_better_prefix")
    components = []
    for index, (old_value, new_value) in enumerate(
        zip(incumbent, better_prefix)
    ):
        component = model.NewIntVar(
            min(old_value, new_value),
            max(old_value, new_value),
            f"continuity_component_{index}",
        )
        model.Add(
            component
            == old_value
            + (new_value - old_value) * choose_better_prefix
        )
        components.append(component)
    penalty = sum(
        component * weight
        for component, weight in zip(components, weights)
    )

    class IncumbentSolver:
        def Value(self, _expression):
            return incumbent_penalty

    _bound_continuity_by_incumbent(model, penalty, IncumbentSolver())
    model.Minimize(penalty)
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    solved_vector = tuple(solver.Value(component) for component in components)

    assert better_prefix < incumbent
    assert better_prefix[1] > incumbent[1]
    assert better_prefix[2] > incumbent[2]
    assert status == cp_model.OPTIMAL
    assert solved_vector == better_prefix
    assert _candidate_is_no_worse(status, solved_vector, incumbent)


def test_hftb_reference_benchmark_artifact_preserves_quality_contract():
    report = json.loads(
        (ROOT / "benchmarks" / "hftb-5s-reference.json").read_text(
            encoding="utf-8"
        )
    )
    environment = report["environment"]
    targets = report["targets"]
    summary = report["summary"]
    runs = report["runs"]

    assert environment["fresh_processes"] >= 4
    assert environment["warmups_excluded"] == environment["fresh_processes"]
    assert environment["qualifying_runs"] == len(runs) >= 20
    assert environment["nominal_budget_seconds"] == 5.0
    assert environment["worker_count"] == 8
    assert len(environment["commit"]) == 40
    assert all(
        character in "0123456789abcdef"
        for character in environment["commit"]
    )

    prefix = tuple(targets["fairness_fallback_prefix"])
    floor = tuple(targets["continuity_floor"])
    assert prefix == (4, 210, 0)
    assert floor == (5, 0, 9, 20, 21)
    run_ids = {
        (run["process_index"], run["run_index"])
        for run in runs
    }
    assert len(run_ids) == len(runs)
    assert {process_index for process_index, _run_index in run_ids} == set(
        range(1, environment["fresh_processes"] + 1)
    )
    expected_runs_per_process = len(runs) // environment["fresh_processes"]
    assert Counter(run["process_index"] for run in runs) == {
        process_index: expected_runs_per_process
        for process_index in range(1, environment["fresh_processes"] + 1)
    }
    for run in runs:
        metrics = run["metrics"]
        assert (
            metrics["playing_time_spread"],
            metrics["scaled_deviation"],
            metrics["fallback_innings"],
        ) == prefix
        reconstructed_vector = continuity_vector(metrics)
        assert tuple(run["continuity_vector"]) == reconstructed_vector
        assert reconstructed_vector <= floor
        assert run["solver_status"] in {"FEASIBLE", "OPTIMAL"}
        assert run["prefix_pass"] is True
        assert run["quality_pass"] is True

    percentile_index = math.ceil(0.95 * len(runs)) - 1
    elapsed = sorted(run["elapsed_seconds"] for run in runs)
    prefix_elapsed = sorted(run["fairness_fallback_seconds"] for run in runs)
    assert summary["solver_p95_seconds"] == elapsed[percentile_index]
    assert summary["solver_max_seconds"] == max(elapsed)
    assert (
        summary["fairness_fallback_p95_seconds"]
        == prefix_elapsed[percentile_index]
    )
    assert summary["fairness_fallback_max_seconds"] == max(prefix_elapsed)
    assert summary["solver_p95_seconds"] <= targets["solver_p95_seconds"]
    assert summary["solver_max_seconds"] <= targets["solver_max_seconds"]
    assert (
        summary["fairness_fallback_p95_seconds"]
        <= targets["fairness_fallback_p95_seconds"]
    )
    assert (
        summary["fairness_fallback_max_seconds"]
        <= targets["fairness_fallback_max_seconds"]
    )
    assert summary["status_distribution"] == dict(
        sorted(Counter(run["solver_status"] for run in runs).items())
    )
    assert summary["all_prefix_pass"] is True
    assert summary["all_quality_pass"] is True


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

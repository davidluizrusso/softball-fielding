from collections import Counter
from itertools import groupby

import pytest
from ortools.sat.python import cp_model

import softball_fielding.optimizer as optimizer_module
from softball_fielding import (
    LineupError,
    OPEN_RULES,
    Player,
    lineup_plan,
    lineup_shortages,
    optimize_game,
)
from softball_fielding.models import INFIELD, INNINGS, OUTFIELD, POSITIONS
from softball_fielding.optimizer import _eligible_positions, _fallback_positions


def player(name, gender, *preferences):
    return Player(name, gender, frozenset(preferences))


def preference_continuity_trade_players(*, promote_third_fallback=False):
    players = [
        player("Middle Flex", "Man", "2B", "3B", "SS"),
        player("Short Specialist", "Man", "SS"),
        player("Third Specialist", "Man", "3B"),
        player("Second Specialist", "Man", "2B"),
        player("Battery Flex", "Man", "P", "1B"),
        player("Pitcher", "Man", "P"),
        player("Battery Utility", "Man", "P", "1B"),
        player("First Specialist", "Man", "1B"),
        player("Left", "Man", "LF"),
        player("Left Center", "Man", "LC"),
        player("Left Right Center Flex", "Man", "LF", "RC"),
        player("Left Center Right Flex", "Man", "LC", "RF"),
        player("Right Side Flex", "Man", "RC", "RF"),
    ]
    if promote_third_fallback:
        return [
            (
                player(candidate.name, candidate.gender, "2B", "3B")
                if candidate.name == "Third Specialist"
                else candidate
            )
            for candidate in players
        ]
    return players


def test_eligible_positions_follow_canonical_lineup_order():
    candidate = player("Order Guard", "Woman", "RF", "P", "SS")

    assert _eligible_positions(candidate, POSITIONS) == (
        "P",
        "C",
        "2B",
        "3B",
        "SS",
        "RF",
    )
    assert candidate.preferences == frozenset(("P", "SS", "RF"))
    assert _fallback_positions(candidate, POSITIONS) == ("C", "2B", "3B")


@pytest.mark.parametrize(
    ("preference", "expected"),
    [
        ("P", ("P", "C")),
        ("C", ("C",)),
        ("1B", ("C", "1B")),
        ("2B", ("C", "2B")),
        ("3B", ("C", "2B", "3B")),
        ("SS", ("C", "2B", "3B", "SS")),
        ("LF", ("C", "LF", "RC", "RF")),
        ("LC", ("C", "LF", "LC", "RC", "RF")),
        ("RC", ("C", "RC", "RF")),
        ("RF", ("C", "RF")),
    ],
)
def test_position_hierarchy_expands_only_in_the_approved_direction(
    preference, expected
):
    candidate = player("Hierarchy Guard", "Man", preference)

    assert _eligible_positions(candidate, POSITIONS) == expected
    assert candidate.preferences == frozenset((preference,))


def test_pitcher_and_first_base_are_never_inferred():
    candidate = player("No Specialist Guessing", "Woman", "SS", "LC")

    eligibility = _eligible_positions(candidate, POSITIONS)

    assert "P" not in eligibility
    assert "1B" not in eligibility
    assert "C" in eligibility


def test_explicit_preference_priority_preserves_zero_fallback_across_player_order():
    players = [
        player("Wide", "Man", "LF", "RC", "RF"),
        player("Left", "Man", "LF"),
        player("Pitcher", "Man", "P"),
        player("Catcher", "Man", "C"),
        player("First", "Man", "1B"),
        player("Second", "Man", "2B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left Center", "Man", "LC"),
        player("Right Center", "Man", "RC"),
    ]

    for ordered_players in (players, list(reversed(players))):
        result = optimize_game(ordered_players, profile=OPEN_RULES)

        assert sum(map(len, result.fallback_assignments)) == 0
        assert all(inning["LF"] == "Left" for inning in result.assignments)
        assert all(inning["RF"] == "Wide" for inning in result.assignments)


def test_unproven_fallback_incumbent_is_frozen_before_continuity(monkeypatch):
    real_solver = cp_model.CpSolver
    solve_count = 0
    fallback_incumbents = []
    frozen_fallback_domains = []
    players = preference_continuity_trade_players()
    fallback_variable_names = {
        f"inning_{inning}_player_{player_index}_{position}"
        for inning in range(INNINGS)
        for player_index, candidate in enumerate(players)
        for position in _fallback_positions(candidate, POSITIONS)
    }

    class DowngradedFallbackSolver:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters

        def Solve(self, model):
            nonlocal solve_count
            solve_count += 1
            if solve_count == 2:
                self.parameters.num_search_workers = 1
                self.parameters.stop_after_first_solution = True
            status = self.delegate.Solve(model)
            if solve_count == 2:
                assert status == cp_model.FEASIBLE
                solution = self.delegate.ResponseProto().solution
                fallback_incumbents.append(
                    sum(
                        solution[index]
                        for index, variable in enumerate(model.Proto().variables)
                        if variable.name in fallback_variable_names
                    )
                )
            elif solve_count == 3:
                model_proto = model.Proto()
                fallback_indexes = {
                    index
                    for index, variable in enumerate(model_proto.variables)
                    if variable.name in fallback_variable_names
                }
                frozen_fallback_domains.extend(
                    tuple(constraint.linear.domain)
                    for constraint in model_proto.constraints
                    if set(constraint.linear.vars) == fallback_indexes
                    and set(constraint.linear.coeffs) == {1}
                )
            return status

        def Value(self, variable):
            return self.delegate.Value(variable)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    monkeypatch.setattr(
        optimizer_module.cp_model,
        "CpSolver",
        DowngradedFallbackSolver,
    )
    result = optimize_game(
        players,
        profile=OPEN_RULES,
        max_solve_seconds=15.0,
    )

    assert fallback_incumbents
    assert fallback_incumbents[0] > INNINGS
    assert (
        fallback_incumbents[0],
        fallback_incumbents[0],
    ) in frozen_fallback_domains
    assert result.solver_status == "FEASIBLE"
    assert (
        sum(map(len, result.fallback_assignments))
        == fallback_incumbents[0]
    )


def test_short_stint_fallback_objective_looks_ahead_to_excess(monkeypatch):
    real_solver = cp_model.CpSolver
    skipped_ideal_stint_probe = False
    inspected_weighted_lookahead = False

    class LookaheadInspected(Exception):
        pass

    class InspectedLookaheadSolver:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters

        def Solve(self, model):
            nonlocal skipped_ideal_stint_probe
            nonlocal inspected_weighted_lookahead
            model_proto = model.Proto()
            objective_terms = {
                model_proto.variables[index].name: coefficient
                for index, coefficient in zip(
                    model_proto.objective.vars,
                    model_proto.objective.coeffs,
                )
            }
            objective_names = set(objective_terms)
            one_inning_names = {
                name for name in objective_names if "_one_inning_" in name
            }
            excess_names = {
                name
                for name in objective_names
                if name.startswith("excess_positions_")
            }
            if (
                not skipped_ideal_stint_probe
                and excess_names
                and not one_inning_names
            ):
                skipped_ideal_stint_probe = True
                return cp_model.UNKNOWN

            if one_inning_names and excess_names and not inspected_weighted_lookahead:
                inspected_weighted_lookahead = True
                maximum_excess = 11 * (len(POSITIONS) - 2)
                assert {objective_terms[name] for name in one_inning_names} == {
                    maximum_excess + 1
                }
                assert {objective_terms[name] for name in excess_names} == {1}
                raise LookaheadInspected

            return self.delegate.Solve(model)

        def Value(self, variable):
            return self.delegate.Value(variable)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    monkeypatch.setattr(
        optimizer_module.cp_model,
        "CpSolver",
        InspectedLookaheadSolver,
    )
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(7)]

    with pytest.raises(LookaheadInspected):
        optimize_game(players, max_solve_seconds=15.0)

    assert skipped_ideal_stint_probe
    assert inspected_weighted_lookahead


def test_proven_short_stint_optimum_does_not_reimpose_infeasible_ideal_groups():
    players = [
        player("A", "Man", "P"),
        player("B", "Man", "P", "C"),
        player("C", "Man", "C", "1B"),
        player("D", "Man", "1B", "2B"),
        player("E", "Man", "2B", "3B"),
        player("F", "Man", "3B", "SS"),
        player("G", "Man", "SS"),
        player("Left", "Man", "LF"),
        player("Left Center", "Man", "LC"),
        player("Right Center", "Man", "RC"),
        player("Right", "Man", "RF"),
    ]

    result = optimize_game(
        players,
        profile=OPEN_RULES,
        max_solve_seconds=10.0,
    )

    assert_schedule_invariants(result, players, OPEN_RULES)
    assert_equal_share(result)
    assert sum(map(len, result.fallback_assignments)) == 0


def test_optimizer_rejects_more_than_fifteen_available_players():
    players = [
        player(f"Player {index + 1}", "Man", *POSITIONS)
        for index in range(16)
    ]

    with pytest.raises(LineupError, match="At most 15 available players"):
        optimize_game(players, profile=OPEN_RULES)


def test_reduced_lineup_orders_rf_substitution_as_rc():
    candidate = player("Reduced Order Guard", "Woman", "RF", "P", "SS")
    reduced_positions = tuple(
        position for position in POSITIONS if position not in {"C", "RF"}
    )

    assert _eligible_positions(candidate, reduced_positions) == (
        "P",
        "2B",
        "3B",
        "SS",
        "RC",
    )


def test_nine_player_lineup_does_not_promote_rf_to_rc():
    candidate = player("Nine Player Guard", "Woman", "RF")
    nine_player_positions = tuple(
        position for position in POSITIONS if position != "RF"
    )

    assert _eligible_positions(candidate, nine_player_positions) == ("C",)


def state_sequence(result, player_name):
    return [
        next(
            (
                position
                for position, name in inning.items()
                if name == player_name
            ),
            "Bench",
        )
        for inning in result.assignments
    ]


def state_runs(sequence):
    return [
        (state, len(tuple(run)))
        for state, run in groupby(sequence)
    ]


def continuity_metrics(result):
    sequences = {
        name: state_sequence(result, name)
        for name in result.player_innings
    }
    runs = {
        name: state_runs(sequence)
        for name, sequence in sequences.items()
    }
    return {
        "bench_total": sum(
            state == "Bench"
            for sequence in sequences.values()
            for state in sequence
        ),
        "bench_runs": sum(
            state == "Bench"
            for player_runs in runs.values()
            for state, _length in player_runs
        ),
        "one_inning_state_runs": sum(
            length == 1
            for player_runs in runs.values()
            for _state, length in player_runs
        ),
        "two_inning_state_runs": sum(
            length == 2
            for player_runs in runs.values()
            for _state, length in player_runs
        ),
        "excess_field_positions": sum(
            max(
                0,
                len({state for state in sequence if state != "Bench"}) - 2,
            )
            for sequence in sequences.values()
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


def _assignments_from_solver_response(solver, players):
    """Reconstruct the fielding matrix from a captured CP-SAT incumbent."""

    solution = solver.delegate.ResponseProto().solution
    assignments = [dict() for _inning in range(INNINGS)]
    for index, variable in enumerate(solver.solved_model.Proto().variables):
        if not solution[index] or not variable.name.startswith("inning_"):
            continue
        parts = variable.name.split("_")
        if len(parts) != 5 or parts[4] == "bench":
            continue
        inning = int(parts[1])
        player_index = int(parts[3])
        position = parts[4]
        assignments[inning][position] = players[player_index].name
    return tuple(assignments)


@pytest.mark.parametrize(
    ("forced_final_status", "return_worse_vector"),
    [
        (cp_model.UNKNOWN, False),
        (cp_model.INFEASIBLE, False),
        (cp_model.FEASIBLE, True),
    ],
)
def test_final_timed_candidate_cannot_replace_the_best_legal_incumbent(
    monkeypatch, forced_final_status, return_worse_vector
):
    """Exercise the real final handoff for every rejected-candidate mode."""

    real_solver = cp_model.CpSolver
    real_vector = optimizer_module._continuity_vector_from_solver
    captured = {}

    class FinalCandidateMutatingSolver:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters
            self.is_final_solver = False
            self.solved_model = None

        def Solve(self, model):
            objective_names = {
                model.Proto().variables[index].name
                for index in model.Proto().objective.vars
            }
            self.is_final_solver = bool(objective_names) and all(
                name.startswith("distinct_positions_")
                or "_transition_" in name
                for name in objective_names
            )
            if self.is_final_solver:
                captured["final_calls"] = captured.get("final_calls", 0) + 1
                if forced_final_status in (cp_model.UNKNOWN, cp_model.INFEASIBLE):
                    return forced_final_status
            self.solved_model = model
            status = self.delegate.Solve(model)
            return cp_model.FEASIBLE if self.is_final_solver else status

        def Value(self, variable):
            return self.delegate.Value(variable)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    def tracking_vector(solver, *variable_groups):
        vector = real_vector(solver, *variable_groups)
        if getattr(solver, "is_final_solver", False) and return_worse_vector:
            incumbent = captured["incumbent_vector"]
            return (incumbent[0] + 1, *incumbent[1:])
        captured["incumbent_vector"] = vector
        captured["incumbent_solver"] = solver
        return vector

    monkeypatch.setattr(
        optimizer_module.cp_model, "CpSolver", FinalCandidateMutatingSolver
    )
    monkeypatch.setattr(
        optimizer_module, "_continuity_vector_from_solver", tracking_vector
    )
    players = tuple(
        player(position, "Man", position) for position in POSITIONS
    )

    result = optimize_game(
        players,
        profile=OPEN_RULES,
        max_solve_seconds=1.0,
    )

    assert captured["final_calls"] == 1
    assert result.assignments == _assignments_from_solver_response(
        captured["incumbent_solver"], players
    )
    metrics = continuity_metrics(result)
    assert (
        metrics["one_inning_state_runs"],
        metrics["excess_field_positions"],
        metrics["two_inning_state_runs"],
        metrics["distinct_field_positions"],
        metrics["transitions"],
    ) == captured["incumbent_vector"]
    assert_schedule_invariants(result, players, OPEN_RULES)
    assert_equal_share(result)
    assert result.solver_status == "FEASIBLE"


def test_two_inning_portfolio_uses_two_isolated_four_worker_searches(
    monkeypatch,
):
    real_solver = cp_model.CpSolver
    configurations = []

    class PortfolioInspectingSolver:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters

        def Solve(self, model):
            objective_names = {
                model.Proto().variables[index].name
                for index in model.Proto().objective.vars
            }
            if any("_two_inning_" in name for name in objective_names):
                configurations.append(
                    (
                        self.parameters.random_seed,
                        self.parameters.num_search_workers,
                        self.parameters.use_lns_only,
                        id(model),
                        id(self.delegate),
                    )
                )
            return self.delegate.Solve(model)

        def Value(self, variable):
            return self.delegate.Value(variable)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    monkeypatch.setattr(
        optimizer_module.cp_model, "CpSolver", PortfolioInspectingSolver
    )
    players = tuple(
        player(position, "Man", position) for position in POSITIONS
    )

    result = optimize_game(
        players,
        profile=OPEN_RULES,
        max_solve_seconds=1.0,
    )

    assert_schedule_invariants(result, players, OPEN_RULES)
    assert {
        (seed, workers, use_lns_only)
        for seed, workers, use_lns_only, _model_id, _solver_id in configurations
    } == {(42, 4, False), (43, 4, True)}
    assert len(
        {model_id for *_configuration, model_id, _solver_id in configurations}
    ) == 2
    assert len(
        {solver_id for *_configuration, _model_id, solver_id in configurations}
    ) == 2


def test_explicit_preferences_beat_a_strictly_smoother_fallback_schedule():
    original_players = preference_continuity_trade_players()
    promoted_players = preference_continuity_trade_players(
        promote_third_fallback=True
    )

    assert {
        candidate.name: _eligible_positions(candidate, POSITIONS)
        for candidate in original_players
    } == {
        candidate.name: _eligible_positions(candidate, POSITIONS)
        for candidate in promoted_players
    }

    preferred_result = optimize_game(
        original_players,
        profile=OPEN_RULES,
        max_solve_seconds=15.0,
    )
    smoother_result = optimize_game(
        promoted_players,
        profile=OPEN_RULES,
        max_solve_seconds=15.0,
    )

    assert_equal_share(preferred_result)
    assert_equal_share(smoother_result)
    assert preferred_result.solver_status == "OPTIMAL"
    assert smoother_result.solver_status == "OPTIMAL"
    assert sum(map(len, preferred_result.fallback_assignments)) == INNINGS
    assert sum(map(len, smoother_result.fallback_assignments)) == INNINGS

    original_preferences = {
        candidate.name: candidate.preferences for candidate in original_players
    }
    smoother_fallbacks_under_original_preferences = sum(
        position not in original_preferences[name]
        for inning in smoother_result.assignments
        for position, name in inning.items()
    )
    assert smoother_fallbacks_under_original_preferences == INNINGS + 2

    preferred_metrics = continuity_metrics(preferred_result)
    smoother_metrics = continuity_metrics(smoother_result)
    assert preferred_metrics == {
        "bench_total": 21,
        "bench_runs": 13,
        "one_inning_state_runs": 5,
        "two_inning_state_runs": 16,
        "excess_field_positions": 1,
        "distinct_field_positions": 20,
        "transitions": 21,
    }
    assert smoother_metrics == {
        "bench_total": 21,
        "bench_runs": 13,
        "one_inning_state_runs": 5,
        "two_inning_state_runs": 14,
        "excess_field_positions": 0,
        "distinct_field_positions": 20,
        "transitions": 20,
    }


def assert_equal_share(result):
    player_count = len(result.player_innings)
    total_slots = len(result.assignments) * result.lineup_size
    lower, higher_count = divmod(total_slots, player_count)
    expected = Counter({lower: player_count - higher_count})
    if higher_count:
        expected[lower + 1] = higher_count

    assert Counter(result.player_innings.values()) == expected


def assert_schedule_invariants(result, players, profile):
    expected_positions, minimum_women = lineup_plan(
        len(players),
        sum(candidate.is_woman for candidate in players),
        profile,
    )
    assert result.active_positions == expected_positions

    by_name = {candidate.name: candidate for candidate in players}
    actual_counts = Counter()
    actual_positions = {candidate.name: set() for candidate in players}
    assert len(result.assignments) == 7
    for inning in result.assignments:
        assert set(inning) == set(expected_positions)
        assert len(set(inning.values())) == result.lineup_size
        actual_counts.update(inning.values())

        for position, name in inning.items():
            actual_positions[name].add(position)
            assert position in _eligible_positions(
                by_name[name], expected_positions
            )

        assigned = [by_name[name] for name in inning.values()]
        assert sum(candidate.is_woman for candidate in assigned) >= minimum_women
        if profile.require_woman_infield_and_outfield:
            assert any(
                by_name[name].is_woman and position in INFIELD
                for position, name in inning.items()
            )
            assert any(
                by_name[name].is_woman and position in OUTFIELD
                for position, name in inning.items()
            )

    assert result.player_innings == {
        candidate.name: actual_counts[candidate.name]
        for candidate in players
    }
    assert result.player_positions == {
        candidate.name: tuple(
            position
            for position in POSITIONS
            if position in actual_positions[candidate.name]
        )
        for candidate in players
    }
    assert all(
        "Bench" not in positions
        for positions in result.player_positions.values()
    )


@pytest.mark.parametrize(
    ("player_count", "woman_count", "lineup_size"),
    [(10, 4, 10), (10, 3, 9), (9, 3, 9), (8, 3, 8)],
)
def test_lineup_plan_matches_count_boundaries(
    player_count, woman_count, lineup_size
):
    active_positions, minimum_women = lineup_plan(player_count, woman_count)

    assert len(active_positions) == lineup_size
    assert minimum_women == (4 if lineup_size == 10 else 3)


def test_lineup_shortages_reports_every_known_count_problem():
    shortages = lineup_shortages(7, 2)

    assert len(shortages) == 2
    assert "At least 8 available players" in shortages[0]
    assert "At least 3 available women" in shortages[1]


@pytest.mark.parametrize(
    ("player_count", "active_positions"),
    [
        (10, POSITIONS),
        (9, tuple(position for position in POSITIONS if position != "RF")),
        (
            8,
            tuple(position for position in POSITIONS if position not in {"C", "RF"}),
        ),
    ],
)
def test_open_lineup_plan_has_no_gender_minimum(player_count, active_positions):
    planned_positions, minimum_women = lineup_plan(
        player_count, 0, OPEN_RULES
    )

    assert planned_positions == active_positions
    assert minimum_women == 0


def test_open_shortages_only_require_eight_players():
    assert lineup_shortages(8, 0, OPEN_RULES) == ()

    shortages = lineup_shortages(7, 0, OPEN_RULES)
    assert len(shortages) == 1
    assert "At least 8 available players" in shortages[0]
    assert "women" not in shortages[0].lower()


def assert_legal(result, players, minimum_women):
    by_name = {candidate.name: candidate for candidate in players}
    assert len(result.assignments) == 7
    for inning in result.assignments:
        assert set(inning) == set(result.active_positions)
        assert len(set(inning.values())) == result.lineup_size

        for position, name in inning.items():
            assert position in _eligible_positions(
                by_name[name], result.active_positions
            )

        assigned = [by_name[name] for name in inning.values()]
        assert sum(candidate.is_woman for candidate in assigned) >= minimum_women
        assert any(
            by_name[name].is_woman and position in INFIELD
            for position, name in inning.items()
        )
        assert any(
            by_name[name].is_woman and position in OUTFIELD
            for position, name in inning.items()
        )


def position_stint_lengths(result, player_name):
    sequence = []
    for inning in result.assignments:
        sequence.append(
            next(
                (position for position, name in inning.items() if name == player_name),
                None,
            )
        )

    lengths = []
    current_position = None
    current_length = 0
    for position in [*sequence, None]:
        if position == current_position and position is not None:
            current_length += 1
            continue
        if current_position is not None:
            lengths.append(current_length)
        current_position = position
        current_length = 1 if position is not None else 0
    return lengths


def test_ten_player_lineup_is_legal_and_balanced():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(7)]

    result = optimize_game(players)

    assert result.active_positions == POSITIONS
    assert_legal(result, players, minimum_women=4)
    assert max(result.player_innings.values()) - min(result.player_innings.values()) <= 1
    assert all(len(positions) <= 2 for positions in result.player_positions.values())
    assert_equal_share(result)
    assert continuity_metrics(result)["bench_total"] == 7


def test_position_stints_are_at_least_two_innings_when_possible():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(8)]

    result = optimize_game(players)

    all_stints = [
        length
        for candidate in players
        for length in position_stint_lengths(result, candidate.name)
    ]
    assert all_stints
    assert min(all_stints) >= 2
    assert Counter(
        result.player_innings[candidate.name]
        for candidate in players
        if candidate.is_woman
    ) == Counter({7: 4})
    assert Counter(
        result.player_innings[candidate.name]
        for candidate in players
        if not candidate.is_woman
    ) == Counter({5: 6, 6: 2})
    assert continuity_metrics(result)["bench_total"] == 14

    for name, innings in result.player_innings.items():
        if innings == 5:
            bench_runs = [
                length
                for state, length in state_runs(state_sequence(result, name))
                if state == "Bench"
            ]
            assert bench_runs == [2]


def test_state_metrics_treat_bench_as_a_real_continuity_state():
    sequence = ["1B", "Bench", "1B", "1B", "Bench", "Bench", "LF"]
    runs = state_runs(sequence)

    assert runs == [
        ("1B", 1),
        ("Bench", 1),
        ("1B", 2),
        ("Bench", 2),
        ("LF", 1),
    ]
    assert sum(length == 1 for _state, length in runs) == 3
    assert sum(length == 2 for _state, length in runs) == 2
    assert sum(first != second for first, second in zip(sequence, sequence[1:])) == 4
    assert len({state for state in sequence if state != "Bench"}) == 2


def test_open_all_men_full_lineup_is_legal_and_has_no_bench():
    players = [
        player(f"M{index}", "Man", *POSITIONS) for index in range(10)
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert_schedule_invariants(result, players, OPEN_RULES)
    assert_equal_share(result)
    metrics = continuity_metrics(result)
    assert metrics["bench_total"] == 0
    assert metrics["bench_runs"] == 0


def test_open_eight_player_lineup_preserves_rf_to_rc_alias():
    players = [
        player("Pitcher", "Man", "P"),
        player("First", "Man", "1B"),
        player("Second", "Man", "2B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left", "Man", "LF"),
        player("Left Center", "Man", "LC"),
        player("Right Fielder", "Man", "RF"),
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert_schedule_invariants(result, players, OPEN_RULES)
    assert all(
        inning["RC"] == "Right Fielder"
        for inning in result.assignments
    )


def test_open_full_lineup_infers_rf_from_lc_eligibility():
    preferences = tuple(position for position in POSITIONS if position != "RF")
    players = [
        player(f"M{index}", "Man", *preferences) for index in range(10)
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert all(inning["RF"] in result.player_innings for inning in result.assignments)
    assert sum(map(len, result.fallback_assignments)) == INNINGS
    assert all(set(inning) == {"RF"} for inning in result.fallback_assignments)
    assert all(
        "RF" in _eligible_positions(candidate, POSITIONS)
        for candidate in players
    )


def test_nine_players_omit_rf_without_the_eight_player_rf_exception():
    players = [
        player("W Pitcher", "Woman", "P"),
        player("W Second", "Woman", "2B"),
        player("W Left", "Woman", "LF"),
        player("Catcher", "Man", "C"),
        player("First", "Man", "1B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left Center", "Man", "LC"),
        player("Right Center", "Man", "RC"),
    ]

    result = optimize_game(players)

    assert "RF" not in result.active_positions
    assert "C" in result.active_positions
    assert all(inning["RC"] == "Right Center" for inning in result.assignments)
    assert_legal(result, players, minimum_women=3)


def test_eight_players_omit_catcher_and_right_field():
    players = [
        player("W Pitcher", "Woman", "P"),
        player("W Second", "Woman", "2B"),
        player("W Left", "Woman", "LF"),
        player("First", "Man", "1B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left Center", "Man", "LC"),
        player("Right Fielder", "Man", "RF"),
    ]

    result = optimize_game(players)

    assert "RF" not in result.active_positions
    assert "C" not in result.active_positions
    assert all(inning["RC"] == "Right Fielder" for inning in result.assignments)
    assert_legal(result, players, minimum_women=3)


def test_three_women_caps_a_large_roster_at_nine_fielders():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(3)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(8)]

    result = optimize_game(players)

    assert result.lineup_size == 9
    assert "RF" not in result.active_positions
    assert_legal(result, players, minimum_women=3)


def test_pitcher_remains_an_explicit_only_hard_constraint():
    players = [
        player(f"W{index}", "Woman", "1B", "2B", "LF", "LC")
        for index in range(4)
    ] + [
        player(f"M{index}", "Man", "C", "1B", "2B", "3B", "SS", "LF", "LC", "RC", "RF")
        for index in range(6)
    ]

    with pytest.raises(LineupError, match="P"):
        optimize_game(players)


def test_duplicate_names_are_rejected():
    players = [
        player("Same Name", "Woman", *POSITIONS),
        player("Same Name", "Woman", *POSITIONS),
        player("W2", "Woman", *POSITIONS),
        player("W3", "Woman", *POSITIONS),
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(6)]

    with pytest.raises(LineupError, match="unique"):
        optimize_game(players)


def test_fewer_than_eight_players_are_rejected_before_solving():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(3)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(4)]

    with pytest.raises(LineupError, match="At least 8.*only 7"):
        optimize_game(players)


def test_fewer_than_three_women_are_rejected_before_solving():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(2)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(7)]

    with pytest.raises(LineupError, match="At least 3 available women.*only 2"):
        optimize_game(players)


@pytest.mark.parametrize(
    ("women_preferences", "missing_group"),
    [
        (("P", "1B", "2B"), "outfield"),
    ],
)
def test_women_must_cover_infield_and_outfield(women_preferences, missing_group):
    players = [
        player(f"W{index}", "Woman", *women_preferences) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(6)]

    with pytest.raises(LineupError, match=missing_group):
        optimize_game(players)


def test_playing_time_counts_match_assignments():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(8)]
    result = optimize_game(players)

    actual = Counter(name for inning in result.assignments for name in inning.values())
    assert result.player_innings == {
        candidate.name: actual[candidate.name] for candidate in players
    }

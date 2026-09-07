"""Constraint-programming model for seven-inning defensive schedules."""

from collections import Counter
from time import monotonic
from typing import Dict, Iterable, List, Sequence, Tuple

from ortools.sat.python import cp_model

from .models import (
    COED_RULES,
    INFIELD,
    INNINGS,
    OUTFIELD,
    POSITIONS,
    LeagueRules,
    Player,
    ScheduleResult,
    resolve_league_rules,
)

BENCH_STATE = "Bench"


class LineupError(ValueError):
    """Raised when the inputs cannot produce a legal schedule."""


def lineup_shortages(
    player_count: int,
    woman_count: int,
    profile: LeagueRules = COED_RULES,
) -> Tuple[str, ...]:
    """Return count-based reasons a profile cannot field a lineup."""

    rules = resolve_league_rules(profile)
    shortages = []
    if player_count < 8:
        shortages.append(
            f"At least 8 available players are required; only {player_count} "
            "are available."
        )
    if woman_count < rules.reduced_lineup_minimum_women:
        shortages.append(
            f"At least {rules.reduced_lineup_minimum_women} available women "
            f"are required; only {woman_count} "
            "are available."
        )
    return tuple(shortages)


def lineup_plan(
    player_count: int,
    woman_count: int,
    profile: LeagueRules = COED_RULES,
) -> Tuple[Tuple[str, ...], int]:
    """Return active positions and the minimum women for a league profile."""

    rules = resolve_league_rules(profile)
    shortages = lineup_shortages(player_count, woman_count, rules)
    if shortages:
        raise LineupError(" ".join(shortages))

    if (
        player_count >= 10
        and woman_count >= rules.full_lineup_minimum_women
    ):
        return POSITIONS, rules.full_lineup_minimum_women
    if player_count >= 9:
        return (
            tuple(position for position in POSITIONS if position != "RF"),
            rules.reduced_lineup_minimum_women,
        )
    return (
        tuple(position for position in POSITIONS if position not in {"C", "RF"}),
        rules.reduced_lineup_minimum_women,
    )


def _lineup_rules(
    players: Sequence[Player], profile: LeagueRules
) -> Tuple[Tuple[str, ...], int]:
    return lineup_plan(
        len(players),
        sum(player.is_woman for player in players),
        profile,
    )


def _eligible_positions(
    player: Player, active_positions: Sequence[str]
) -> frozenset[str]:
    preferences = set(player.preferences)
    if "RF" not in active_positions and "RF" in preferences:
        preferences.add("RC")
    return frozenset(preferences.intersection(active_positions))


def _validate_players(players: Sequence[Player]) -> None:
    duplicate_names = sorted(
        name for name, count in Counter(player.name for player in players).items()
        if count > 1
    )
    if duplicate_names:
        raise LineupError(
            "Player names must be unique. Duplicate name(s): "
            + ", ".join(duplicate_names)
            + "."
        )


def _preflight_preferences(
    players: Sequence[Player],
    active_positions: Sequence[str],
    eligibility: Dict[int, frozenset[str]],
    profile: LeagueRules,
) -> None:
    uncovered = [
        position
        for position in active_positions
        if not any(position in eligibility[index] for index in range(len(players)))
    ]
    if uncovered:
        raise LineupError(
            "No available player prefers the following required position(s): "
            + ", ".join(uncovered)
            + "."
        )

    if not profile.require_woman_infield_and_outfield:
        return

    women_infield = any(
        player.is_woman and eligibility[index].intersection(INFIELD)
        for index, player in enumerate(players)
    )
    women_outfield = any(
        player.is_woman and eligibility[index].intersection(OUTFIELD)
        for index, player in enumerate(players)
    )
    missing_groups = []
    if not women_infield:
        missing_groups.append("infield")
    if not women_outfield:
        missing_groups.append("outfield")
    if missing_groups:
        raise LineupError(
            "At least one available woman must prefer an active "
            + " and ".join(missing_groups)
            + " position."
        )


def optimize_game(
    players: Iterable[Player],
    *,
    profile: LeagueRules = COED_RULES,
    max_solve_seconds: float = 3.0,
) -> ScheduleResult:
    """Build the fairest legal seven-inning schedule for available players."""

    player_list = tuple(players)
    rules = resolve_league_rules(profile)
    _validate_players(player_list)
    active_positions, minimum_women = _lineup_rules(player_list, rules)
    eligibility = {
        index: _eligible_positions(player, active_positions)
        for index, player in enumerate(player_list)
    }
    _preflight_preferences(player_list, active_positions, eligibility, rules)

    model = cp_model.CpModel()
    assignments: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
    bench_assignments: Dict[Tuple[int, int], cp_model.IntVar] = {}

    for inning in range(INNINGS):
        for player_index, _player in enumerate(player_list):
            bench_assignments[(inning, player_index)] = model.NewBoolVar(
                f"inning_{inning}_player_{player_index}_bench"
            )
            for position in eligibility[player_index]:
                assignments[(inning, player_index, position)] = model.NewBoolVar(
                    f"inning_{inning}_player_{player_index}_{position}"
                )

    for inning in range(INNINGS):
        for position in active_positions:
            model.Add(
                sum(
                    assignments[(inning, player_index, position)]
                    for player_index in range(len(player_list))
                    if (inning, player_index, position) in assignments
                )
                == 1
            )

        for player_index in range(len(player_list)):
            model.Add(
                bench_assignments[(inning, player_index)]
                + sum(
                    assignments[(inning, player_index, position)]
                    for position in eligibility[player_index]
                )
                == 1
            )

        if minimum_women:
            woman_assignments = [
                assignments[(inning, player_index, position)]
                for player_index, player in enumerate(player_list)
                if player.is_woman
                for position in eligibility[player_index]
            ]
            model.Add(sum(woman_assignments) >= minimum_women)

        if rules.require_woman_infield_and_outfield:
            woman_infield_assignments = [
                assignments[(inning, player_index, position)]
                for player_index, player in enumerate(player_list)
                if player.is_woman
                for position in eligibility[player_index].intersection(INFIELD)
            ]
            woman_outfield_assignments = [
                assignments[(inning, player_index, position)]
                for player_index, player in enumerate(player_list)
                if player.is_woman
                for position in eligibility[player_index].intersection(OUTFIELD)
            ]
            model.Add(sum(woman_infield_assignments) >= 1)
            model.Add(sum(woman_outfield_assignments) >= 1)

    innings_played: List[cp_model.IntVar] = []
    for player_index, player in enumerate(player_list):
        count = model.NewIntVar(0, INNINGS, f"innings_{player_index}")
        model.Add(
            count
            == sum(
                assignments[(inning, player_index, position)]
                for inning in range(INNINGS)
                for position in eligibility[player_index]
            )
        )
        innings_played.append(count)

    maximum_innings = model.NewIntVar(0, INNINGS, "maximum_innings")
    minimum_innings = model.NewIntVar(0, INNINGS, "minimum_innings")
    model.AddMaxEquality(maximum_innings, innings_played)
    model.AddMinEquality(minimum_innings, innings_played)
    playing_time_spread = model.NewIntVar(0, INNINGS, "playing_time_spread")
    model.Add(playing_time_spread == maximum_innings - minimum_innings)

    total_slots = INNINGS * len(active_positions)
    player_count = len(player_list)
    maximum_scaled_deviation = max(total_slots, abs(INNINGS * player_count - total_slots))
    deviations: List[cp_model.IntVar] = []
    for player_index, count in enumerate(innings_played):
        deviation = model.NewIntVar(
            0, maximum_scaled_deviation, f"deviation_{player_index}"
        )
        model.AddAbsEquality(deviation, player_count * count - total_slots)
        deviations.append(deviation)

    excess_position_counts: List[cp_model.IntVar] = []
    distinct_position_counts: List[cp_model.IntVar] = []
    state_transitions: List[cp_model.IntVar] = []
    one_inning_stints: List[cp_model.IntVar] = []
    two_inning_stints: List[cp_model.IntVar] = []
    for player_index, _player in enumerate(player_list):
        position_used = []
        for position in eligibility[player_index]:
            used = model.NewBoolVar(f"player_{player_index}_uses_{position}")
            inning_variables = [
                assignments[(inning, player_index, position)]
                for inning in range(INNINGS)
            ]
            for assignment in inning_variables:
                model.Add(assignment <= used)
            model.Add(used <= sum(inning_variables))
            position_used.append(used)

        state_variables = {
            position: [
                assignments[(inning, player_index, position)]
                for inning in range(INNINGS)
            ]
            for position in eligibility[player_index]
        }
        state_variables[BENCH_STATE] = [
            bench_assignments[(inning, player_index)]
            for inning in range(INNINGS)
        ]

        for state, inning_variables in state_variables.items():
            for inning, assignment in enumerate(inning_variables):
                previous = inning_variables[inning - 1] if inning > 0 else None
                following = (
                    inning_variables[inning + 1] if inning + 1 < INNINGS else None
                )

                if previous is not None:
                    transition = model.NewBoolVar(
                        f"player_{player_index}_{state}_transition_{inning}"
                    )
                    model.Add(transition <= assignment)
                    model.Add(transition + previous <= 1)
                    model.Add(transition >= assignment - previous)
                    state_transitions.append(transition)

                one_inning = model.NewBoolVar(
                    f"player_{player_index}_{state}_one_inning_{inning}"
                )
                model.Add(one_inning <= assignment)
                lower_bound = assignment
                if previous is not None:
                    model.Add(one_inning + previous <= 1)
                    lower_bound -= previous
                if following is not None:
                    model.Add(one_inning + following <= 1)
                    lower_bound -= following
                model.Add(one_inning >= lower_bound)
                one_inning_stints.append(one_inning)

            for inning in range(INNINGS - 1):
                first = inning_variables[inning]
                second = inning_variables[inning + 1]
                previous = inning_variables[inning - 1] if inning > 0 else None
                following = (
                    inning_variables[inning + 2] if inning + 2 < INNINGS else None
                )
                two_inning = model.NewBoolVar(
                    f"player_{player_index}_{state}_two_inning_{inning}"
                )
                model.Add(two_inning <= first)
                model.Add(two_inning <= second)
                lower_bound = first + second - 1
                if previous is not None:
                    model.Add(two_inning + previous <= 1)
                    lower_bound -= previous
                if following is not None:
                    model.Add(two_inning + following <= 1)
                    lower_bound -= following
                model.Add(two_inning >= lower_bound)
                two_inning_stints.append(two_inning)

        distinct_positions = model.NewIntVar(
            0, len(active_positions), f"distinct_positions_{player_index}"
        )
        model.Add(distinct_positions == sum(position_used))
        distinct_position_counts.append(distinct_positions)
        excess_positions = model.NewIntVar(
            0, max(0, len(active_positions) - 2), f"excess_positions_{player_index}"
        )
        model.Add(excess_positions >= distinct_positions - 2)
        excess_position_counts.append(excess_positions)

    # Each coefficient is larger than the maximum possible contribution of
    # every lower-priority term. This encodes the documented lexicographic
    # order without requiring five additional solver passes.
    transition_cost = 1
    distinct_position_cost = (
        player_count * (INNINGS - 1) * transition_cost + 1
    )
    two_inning_cost = (
        player_count * len(active_positions) * distinct_position_cost
        + player_count * (INNINGS - 1) * transition_cost
        + 1
    )
    excess_position_cost = (
        player_count * (INNINGS - 1) * two_inning_cost
        + player_count * len(active_positions) * distinct_position_cost
        + player_count * (INNINGS - 1) * transition_cost
        + 1
    )
    one_inning_cost = (
        player_count
        * max(0, len(active_positions) - 2)
        * excess_position_cost
        + player_count * (INNINGS - 1) * two_inning_cost
        + player_count * len(active_positions) * distinct_position_cost
        + player_count * (INNINGS - 1) * transition_cost
        + 1
    )

    consistency_penalty = (
        sum(one_inning_stints) * one_inning_cost
        + sum(excess_position_counts) * excess_position_cost
        + sum(two_inning_stints) * two_inning_cost
        + sum(distinct_position_counts) * distinct_position_cost
        + sum(state_transitions) * transition_cost
    )
    max_deviation_total = player_count * maximum_scaled_deviation
    fairness_objective = (
        playing_time_spread * (max_deviation_total + 1) + sum(deviations)
    )
    model.Minimize(fairness_objective)

    started_at = monotonic()
    fairness_solver = cp_model.CpSolver()
    fairness_solver.parameters.max_time_in_seconds = min(
        1.0, max(0.1, max_solve_seconds * 0.25)
    )
    fairness_solver.parameters.num_search_workers = 8
    fairness_solver.parameters.random_seed = 42
    fairness_status = fairness_solver.Solve(model)

    if fairness_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if fairness_status == cp_model.INFEASIBLE:
            raise LineupError(
                "No legal schedule can satisfy all positional preferences and "
                "league rules. Try adding preferences or changing availability."
            )
        raise LineupError(
            "The optimizer could not find a schedule within the time limit. "
            "Please try again."
        )

    best_spread = fairness_solver.Value(playing_time_spread)
    best_deviation = sum(fairness_solver.Value(item) for item in deviations)
    model.Add(playing_time_spread == best_spread)
    model.Add(sum(deviations) == best_deviation)
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, fairness_solver.Value(variable))

    # Find the highest-priority continuity target on its own first. In broad,
    # interchangeable rosters this reaches the obvious lower bound (zero)
    # much more reliably than asking one weighted search to navigate every
    # lower-priority tie at once.
    model.Minimize(sum(one_inning_stints))
    one_inning_solver = cp_model.CpSolver()
    one_inning_solver.parameters.max_time_in_seconds = min(
        1.0,
        max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.45),
    )
    one_inning_solver.parameters.num_search_workers = 8
    one_inning_solver.parameters.random_seed = 42
    one_inning_status = one_inning_solver.Solve(model)
    if one_inning_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupError(
            "The optimizer could not improve lineup continuity within the "
            "time limit. Please try again."
        )

    best_one_inning = sum(
        one_inning_solver.Value(item) for item in one_inning_stints
    )
    if one_inning_status == cp_model.OPTIMAL or best_one_inning == 0:
        model.Add(sum(one_inning_stints) == best_one_inning)
    model.clear_hints()
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, one_inning_solver.Value(variable))

    model.Minimize(consistency_penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(
        0.1, max_solve_seconds - (monotonic() - started_at)
    )
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            raise LineupError(
                "No legal schedule can satisfy all positional preferences and "
                "league rules. Try adding preferences or changing availability."
            )
        raise LineupError(
            "The optimizer could not find a schedule within the time limit. "
            "Please try again."
        )

    solved_assignments = []
    positions_by_player: Dict[str, set[str]] = {
        player.name: set() for player in player_list
    }
    for inning in range(INNINGS):
        inning_assignment: Dict[str, str] = {}
        for position in active_positions:
            for player_index, player in enumerate(player_list):
                variable = assignments.get((inning, player_index, position))
                if variable is not None and solver.Value(variable):
                    inning_assignment[position] = player.name
                    positions_by_player[player.name].add(position)
                    break
        solved_assignments.append(inning_assignment)

    player_innings = {
        player.name: solver.Value(innings_played[index])
        for index, player in enumerate(player_list)
    }
    player_positions = {
        player.name: tuple(
            position for position in POSITIONS if position in positions_by_player[player.name]
        )
        for player in player_list
    }

    return ScheduleResult(
        assignments=tuple(solved_assignments),
        active_positions=active_positions,
        player_innings=player_innings,
        player_positions=player_positions,
        solver_status=solver.StatusName(status),
    )

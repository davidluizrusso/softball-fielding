"""Constraint-programming model for seven-inning defensive schedules."""

from collections import Counter
from time import monotonic
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from .models import (
    COED_RULES,
    INFIELD,
    INNINGS,
    MAX_AVAILABLE_PLAYERS,
    OUTFIELD,
    POSITIONS,
    LeagueRules,
    Player,
    ScheduleResult,
    resolve_league_rules,
)

BENCH_STATE = "Bench"

POSITION_FALLBACKS = {
    "SS": ("3B", "2B"),
    "3B": ("2B",),
    "LC": ("LF", "RC", "RF"),
    "LF": ("RC", "RF"),
    "RC": ("RF",),
}

FAIRNESS_PROGRESS = "Checking the fairest possible playing time…"
PREFERENCE_PROGRESS = "Preferring selected positions over fallback eligibility…"
STINT_PROGRESS = "Keeping field and Bench assignments in longer blocks…"
CONSISTENCY_PROGRESS = "Reducing position changes…"


def _report_progress(
    callback: Optional[Callable[[str], None]], message: str
) -> None:
    if callback is not None:
        callback(message)


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
    if player_count > MAX_AVAILABLE_PLAYERS:
        shortages.append(
            f"At most {MAX_AVAILABLE_PLAYERS} available players are supported; "
            f"{player_count} are available."
        )
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
) -> Tuple[str, ...]:
    eligibility = set(player.preferences)
    eligibility.add("C")
    for preferred_position in player.preferences:
        eligibility.update(POSITION_FALLBACKS.get(preferred_position, ()))
    is_eight_player_lineup = "C" not in active_positions and "RF" not in active_positions
    if is_eight_player_lineup and "RF" in player.preferences:
        eligibility.add("RC")
    return tuple(
        position for position in active_positions if position in eligibility
    )


def _fallback_positions(
    player: Player, active_positions: Sequence[str]
) -> Tuple[str, ...]:
    """Return eligible positions the player did not explicitly prefer."""

    return tuple(
        position
        for position in _eligible_positions(player, active_positions)
        if position not in player.preferences
    )


def _validate_players(players: Sequence[Player]) -> None:
    if len(players) > MAX_AVAILABLE_PLAYERS:
        raise LineupError(
            f"At most {MAX_AVAILABLE_PLAYERS} available players are supported; "
            f"{len(players)} were provided."
        )
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
    eligibility: Dict[int, Tuple[str, ...]],
    profile: LeagueRules,
) -> None:
    uncovered = [
        position
        for position in active_positions
        if not any(position in eligibility[index] for index in range(len(players)))
    ]
    if uncovered:
        raise LineupError(
            "No available player is eligible for the following required position(s): "
            + ", ".join(uncovered)
            + "."
        )

    if not profile.require_woman_infield_and_outfield:
        return

    women_infield = any(
        player.is_woman
        and any(position in INFIELD for position in eligibility[index])
        for index, player in enumerate(players)
    )
    women_outfield = any(
        player.is_woman
        and any(position in OUTFIELD for position in eligibility[index])
        for index, player in enumerate(players)
    )
    missing_groups = []
    if not women_infield:
        missing_groups.append("infield")
    if not women_outfield:
        missing_groups.append("outfield")
    if missing_groups:
        raise LineupError(
            "At least one available woman must be eligible for an active "
            + " and ".join(missing_groups)
            + " position."
        )


def optimize_game(
    players: Iterable[Player],
    *,
    profile: LeagueRules = COED_RULES,
    max_solve_seconds: float = 10.0,
    fairness_solve_seconds: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
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
    fallback_eligibility = {
        index: _fallback_positions(player, active_positions)
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
                for position in eligibility[player_index]
                if position in INFIELD
            ]
            woman_outfield_assignments = [
                assignments[(inning, player_index, position)]
                for player_index, player in enumerate(player_list)
                if player.is_woman
                for position in eligibility[player_index]
                if position in OUTFIELD
            ]
            model.Add(sum(woman_infield_assignments) >= 1)
            model.Add(sum(woman_outfield_assignments) >= 1)

    # Players with identical gender and eligibility are interchangeable in the
    # mathematical model. Canonically ordering their complete state sequences
    # removes name-permutation symmetry without excluding a distinct schedule.
    equivalent_players: Dict[
        Tuple[bool, Tuple[str, ...], Tuple[str, ...]], List[int]
    ] = {}
    for player_index, player in enumerate(player_list):
        equivalence_key = (
            player.is_woman,
            tuple(
                position
                for position in active_positions
                if position in eligibility[player_index]
            ),
            tuple(
                position
                for position in active_positions
                if position in player.preferences
            ),
        )
        equivalent_players.setdefault(equivalence_key, []).append(player_index)

    active_position_index = {
        position: index for index, position in enumerate(active_positions)
    }
    state_base = len(active_positions) + 1
    maximum_schedule_signature = state_base**INNINGS - 1
    for group_index, player_indexes in enumerate(equivalent_players.values()):
        if len(player_indexes) < 2:
            continue
        schedule_signatures = []
        for player_index in player_indexes:
            schedule_signature = model.NewIntVar(
                0,
                maximum_schedule_signature,
                f"equivalent_group_{group_index}_player_{player_index}_schedule",
            )
            model.Add(
                schedule_signature
                == sum(
                    state_base ** (INNINGS - 1 - inning)
                    * (
                        sum(
                            active_position_index[position]
                            * assignments[(inning, player_index, position)]
                            for position in eligibility[player_index]
                        )
                        + len(active_positions)
                        * bench_assignments[(inning, player_index)]
                    )
                    for inning in range(INNINGS)
                )
            )
            schedule_signatures.append(schedule_signature)
        for first, second in zip(
            schedule_signatures, schedule_signatures[1:]
        ):
            model.Add(first <= second)

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

    fallback_assignment_variables = [
        assignments[(inning, player_index, position)]
        for inning in range(INNINGS)
        for player_index in range(len(player_list))
        for position in fallback_eligibility[player_index]
    ]

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
    position_used_variables: List[cp_model.IntVar] = []
    field_one_inning_by_player: Dict[int, List[cp_model.IntVar]] = {}
    bench_one_inning_by_player: Dict[int, List[cp_model.IntVar]] = {}
    for player_index, _player in enumerate(player_list):
        field_one_inning_by_player[player_index] = []
        bench_one_inning_by_player[player_index] = []
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
            position_used_variables.append(used)

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
                if state == BENCH_STATE:
                    bench_one_inning_by_player[player_index].append(one_inning)
                else:
                    field_one_inning_by_player[player_index].append(one_inning)

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

    ideal_one_inning_groups = []
    for player_index, count in enumerate(innings_played):
        for state_name, target_innings, stint_variables in (
            ("field", 1, field_one_inning_by_player[player_index]),
            (
                "bench",
                INNINGS - 1,
                bench_one_inning_by_player[player_index],
            ),
        ):
            is_singleton = model.NewBoolVar(
                f"player_{player_index}_unavoidable_one_inning_{state_name}"
            )
            model.Add(count == target_innings).OnlyEnforceIf(is_singleton)
            model.Add(count != target_innings).OnlyEnforceIf(is_singleton.Not())
            ideal_one_inning_groups.append((stint_variables, is_singleton))

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
    _report_progress(progress_callback, FAIRNESS_PROGRESS)
    fairness_budget = min(
        max_solve_seconds,
        max(
            0.1,
            fairness_solve_seconds
            if fairness_solve_seconds is not None
            else min(2.0, max_solve_seconds * 0.4),
        ),
    )

    # First try the arithmetic lower bound: every player receives either the
    # floor or ceiling of an equal share. Any feasible schedule in this slice
    # certifies both the minimum spread and the minimum scaled L1 deviation.
    equal_share_floor, equal_share_remainder = divmod(total_slots, player_count)
    equal_share_ceiling = equal_share_floor + bool(equal_share_remainder)
    ideal_fairness_model = model.clone()
    for count in innings_played:
        ideal_fairness_model.Add(count >= equal_share_floor)
        ideal_fairness_model.Add(count <= equal_share_ceiling)
    ideal_fairness_model.Minimize(0)
    ideal_fairness_solver = cp_model.CpSolver()
    ideal_fairness_solver.parameters.max_time_in_seconds = min(
        0.75, max(0.1, fairness_budget * 0.35)
    )
    ideal_fairness_solver.parameters.num_search_workers = 8
    ideal_fairness_solver.parameters.random_seed = 42
    ideal_fairness_status = ideal_fairness_solver.Solve(ideal_fairness_model)

    if ideal_fairness_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        fairness_solver = ideal_fairness_solver
        fairness_status = ideal_fairness_status
        fairness_proven = True
    else:
        fairness_solver = cp_model.CpSolver()
        fairness_solver.parameters.max_time_in_seconds = max(
            0.1, fairness_budget - (monotonic() - started_at)
        )
        fairness_solver.parameters.num_search_workers = 8
        fairness_solver.parameters.random_seed = 42
        fairness_status = fairness_solver.Solve(model)
        fairness_proven = fairness_status == cp_model.OPTIMAL

    if fairness_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if fairness_status == cp_model.INFEASIBLE:
            raise LineupError(
                "No legal schedule can satisfy the derived position eligibility "
                "and league rules. Try adding preferences or changing availability."
            )
        raise LineupError(
            "The optimizer could not find a schedule within the time limit. "
            "Please try again."
        )

    _report_progress(
        progress_callback,
        (
            "Fairest playing-time balance proven. Checking preferred positions…"
            if fairness_proven
            else "Best playing-time balance found within the time limit. "
            "Checking preferred positions…"
        ),
    )

    best_spread = fairness_solver.Value(playing_time_spread)
    best_deviation = sum(fairness_solver.Value(item) for item in deviations)
    model.Add(playing_time_spread == best_spread)
    model.Add(sum(deviations) == best_deviation)
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, fairness_solver.Value(variable))

    # Explicit preferences outrank every continuity objective. Hierarchy-derived
    # positions are legal fallbacks, but all such fallbacks currently have the
    # same cost; the model does not invent a comfort ranking among them.
    fallback_objective = sum(fallback_assignment_variables)
    fairness_fallback_count = sum(
        fairness_solver.Value(variable)
        for variable in fallback_assignment_variables
    )
    if fairness_fallback_count == 0:
        fallback_solver = fairness_solver
        fallback_status = fairness_status
        best_fallback_count = 0
        fallback_proven = True
    else:
        _report_progress(progress_callback, PREFERENCE_PROGRESS)
        model.Minimize(fallback_objective)
        fallback_solver = cp_model.CpSolver()
        fallback_solver.parameters.max_time_in_seconds = min(
            1.0,
            max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.25),
        )
        fallback_solver.parameters.num_search_workers = 8
        fallback_solver.parameters.random_seed = 42
        fallback_status = fallback_solver.Solve(model)
        if fallback_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise LineupError(
                "The optimizer could not minimize fallback assignments within "
                "the time limit. Please try again."
            )
        best_fallback_count = sum(
            fallback_solver.Value(variable)
            for variable in fallback_assignment_variables
        )
        fallback_proven = (
            fallback_status == cp_model.OPTIMAL or best_fallback_count == 0
        )

    # Even when the phase times out without a proof, preserve the exact
    # incumbent count so lower-priority continuity terms cannot spend more
    # fallback innings. The overall result remains truthfully FEASIBLE.
    model.Add(fallback_objective == best_fallback_count)
    model.clear_hints()
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, fallback_solver.Value(variable))

    _report_progress(progress_callback, STINT_PROGRESS)
    # First ask a cloned model for the ideal lower bound: the only one-inning
    # states are those forced by a player receiving exactly one field or Bench
    # inning. Feasibility is substantially easier to establish than proving a
    # weighted optimum on broad, interchangeable rosters.
    ideal_stints_model = model.clone()
    for stint_variables, unavoidable_singleton in ideal_one_inning_groups:
        ideal_stints_model.Add(
            sum(stint_variables) == unavoidable_singleton
        )
    # Look ahead to the next lexicographic tier while proving the ideal
    # one-inning-stint slice. This does not change priority because the ideal
    # stint counts are hard constraints in this clone.
    ideal_stints_model.Minimize(sum(excess_position_counts))
    ideal_stints_solver = cp_model.CpSolver()
    ideal_stints_solver.parameters.max_time_in_seconds = min(
        2.0,
        max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.45),
    )
    ideal_stints_solver.parameters.num_search_workers = 8
    ideal_stints_solver.parameters.random_seed = 42
    ideal_stints_status = ideal_stints_solver.Solve(ideal_stints_model)

    if ideal_stints_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        one_inning_solver = ideal_stints_solver
        one_inning_status = ideal_stints_status
        best_one_inning = sum(
            ideal_stints_solver.Value(item) for item in one_inning_stints
        )
        best_excess_positions = sum(
            ideal_stints_solver.Value(item) for item in excess_position_counts
        )
        ideal_stints_feasible = True
        one_inning_proven = True
    else:
        ideal_stints_feasible = False
        maximum_excess_positions = len(player_list) * max(
            0, len(active_positions) - 2
        )
        model.Minimize(
            sum(one_inning_stints) * (maximum_excess_positions + 1)
            + sum(excess_position_counts)
        )
        one_inning_solver = cp_model.CpSolver()
        one_inning_solver.parameters.max_time_in_seconds = min(
            2.0,
            max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.45),
        )
        one_inning_solver.parameters.num_search_workers = 8
        one_inning_solver.parameters.random_seed = 42
        one_inning_status = one_inning_solver.Solve(model)
        best_one_inning = (
            sum(one_inning_solver.Value(item) for item in one_inning_stints)
            if one_inning_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else 0
        )
        best_excess_positions = (
            sum(
                one_inning_solver.Value(item)
                for item in excess_position_counts
            )
            if one_inning_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else 0
        )
        one_inning_proven = (
            one_inning_status == cp_model.OPTIMAL
            or (
                one_inning_status == cp_model.FEASIBLE
                and best_one_inning == 0
            )
        )

    if one_inning_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupError(
            "The optimizer could not improve lineup continuity within the "
            "time limit. Please try again."
        )

    if ideal_stints_feasible:
        for stint_variables, unavoidable_singleton in ideal_one_inning_groups:
            model.Add(sum(stint_variables) == unavoidable_singleton)
    elif one_inning_proven:
        model.Add(sum(one_inning_stints) == best_one_inning)
    else:
        # Freeze the achieved higher-priority incumbent. Allowing a smaller
        # count here would let the next excess-position phase select its own
        # lower-priority slice before the short-stint improvement is secured.
        # The overall result remains truthfully FEASIBLE because this count
        # has not been proven minimal.
        model.Add(sum(one_inning_stints) == best_one_inning)
    model.clear_hints()
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, one_inning_solver.Value(variable))

    solution_solver = one_inning_solver
    solution_status = one_inning_status
    # An optimal look-ahead solve proves the next tier too. A zero incumbent is
    # also a certificate because excess-position counts have lower bound zero,
    # even when CP-SAT has not proven the supplying objective optimal.
    excess_proven = (
        best_excess_positions == 0 or one_inning_status == cp_model.OPTIMAL
    )
    if excess_proven:
        if best_excess_positions == 0:
            for excess_positions in excess_position_counts:
                model.Add(excess_positions == 0)
        else:
            model.Add(sum(excess_position_counts) == best_excess_positions)
    else:
        # Secure the two-position target before spending time on lower-order
        # polish. Probe the known lower bound inside the existing excess-phase
        # budget, then use only the unspent remainder for ordinary minimization.
        model.AddDecisionStrategy(
            position_used_variables,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MIN_VALUE,
        )
        excess_phase_budget = min(
            2.5,
            max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.75),
        )
        excess_phase_started_at = monotonic()
        ideal_excess_model = model.clone()
        for excess_positions in excess_position_counts:
            ideal_excess_model.Add(excess_positions == 0)
        ideal_excess_model.Minimize(0)
        ideal_excess_solver = cp_model.CpSolver()
        ideal_excess_solver.parameters.max_time_in_seconds = max(
            0.05, excess_phase_budget * 0.6
        )
        ideal_excess_solver.parameters.num_search_workers = 8
        ideal_excess_solver.parameters.random_seed = 42
        ideal_excess_status = ideal_excess_solver.Solve(ideal_excess_model)

        if ideal_excess_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            excess_solver = ideal_excess_solver
            excess_status = ideal_excess_status
            best_excess_positions = 0
            excess_proven = True
        else:
            model.Minimize(sum(excess_position_counts))
            excess_solver = cp_model.CpSolver()
            excess_solver.parameters.max_time_in_seconds = max(
                0.05,
                excess_phase_budget - (monotonic() - excess_phase_started_at),
            )
            excess_solver.parameters.num_search_workers = 8
            excess_solver.parameters.random_seed = 42
            excess_solver.parameters.search_branching = (
                cp_model.PARTIAL_FIXED_SEARCH
            )
            excess_status = excess_solver.Solve(model)
            best_excess_positions = (
                sum(
                    excess_solver.Value(item)
                    for item in excess_position_counts
                )
                if excess_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                else best_excess_positions
            )
            excess_proven = (
                excess_status == cp_model.OPTIMAL
                or (
                    excess_status == cp_model.FEASIBLE
                    and best_excess_positions == 0
                )
            )

        if excess_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solution_solver = excess_solver
            solution_status = excess_status
            if excess_proven:
                if best_excess_positions == 0:
                    for excess_positions in excess_position_counts:
                        model.Add(excess_positions == 0)
                else:
                    model.Add(
                        sum(excess_position_counts) == best_excess_positions
                    )
            else:
                model.Add(sum(excess_position_counts) <= best_excess_positions)
            model.clear_hints()
            for variable in (*assignments.values(), *bench_assignments.values()):
                model.AddHint(variable, excess_solver.Value(variable))

    _report_progress(progress_callback, CONSISTENCY_PROGRESS)
    model.Minimize(consistency_penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(
        0.1, max_solve_seconds - (monotonic() - started_at)
    )
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    final_status = solver.Solve(model)

    if final_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution_solver = solver
        solution_status = final_status
    elif final_status == cp_model.INFEASIBLE:
        raise LineupError(
            "No legal schedule can satisfy the derived position eligibility "
            "and league rules. Try adding preferences or changing availability."
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
                if variable is not None and solution_solver.Value(variable):
                    inning_assignment[position] = player.name
                    positions_by_player[player.name].add(position)
                    break
        solved_assignments.append(inning_assignment)

    player_innings = {
        player.name: solution_solver.Value(innings_played[index])
        for index, player in enumerate(player_list)
    }
    player_positions = {
        player.name: tuple(
            position for position in POSITIONS if position in positions_by_player[player.name]
        )
        for player in player_list
    }
    solved_fallback_assignments = tuple(
        {
            position: player.name
            for position, player_name in inning_assignment.items()
            for player_index, player in enumerate(player_list)
            if player.name == player_name
            and position in fallback_eligibility[player_index]
        }
        for inning_assignment in solved_assignments
    )
    all_priorities_proven = (
        fairness_proven
        and fallback_proven
        and one_inning_proven
        and excess_proven
        and final_status == cp_model.OPTIMAL
    )

    return ScheduleResult(
        assignments=tuple(solved_assignments),
        active_positions=active_positions,
        player_innings=player_innings,
        player_positions=player_positions,
        solver_status="OPTIMAL" if all_priorities_proven else "FEASIBLE",
        fallback_assignments=solved_fallback_assignments,
    )

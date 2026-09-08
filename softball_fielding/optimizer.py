"""Constraint-programming model for seven-inning defensive schedules."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
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


def _continuity_vector_from_solver(
    solver: cp_model.CpSolver,
    one_inning_stints: Sequence[cp_model.IntVar],
    excess_position_counts: Sequence[cp_model.IntVar],
    two_inning_stints: Sequence[cp_model.IntVar],
    distinct_position_counts: Sequence[cp_model.IntVar],
    state_transitions: Sequence[cp_model.IntVar],
) -> Tuple[int, int, int, int, int]:
    """Return the documented lexicographic continuity vector."""

    return tuple(
        sum(solver.Value(variable) for variable in variables)
        for variables in (
            one_inning_stints,
            excess_position_counts,
            two_inning_stints,
            distinct_position_counts,
            state_transitions,
        )
    )


def _candidate_is_no_worse(
    status: cp_model.CpSolverStatus,
    candidate: Tuple[int, int, int, int, int],
    incumbent: Tuple[int, int, int, int, int],
) -> bool:
    """Accept only solved candidates that preserve lexicographic quality."""

    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and candidate <= incumbent


def _continuity_weights(
    player_count: int, position_count: int
) -> Tuple[int, int, int, int, int]:
    """Return coefficients that encode the continuity tuple lexicographically."""

    transition_cost = 1
    distinct_position_cost = player_count * (INNINGS - 1) + 1
    two_inning_cost = (
        player_count * position_count * distinct_position_cost
        + player_count * (INNINGS - 1)
        + 1
    )
    excess_position_cost = (
        player_count * (INNINGS - 1) * two_inning_cost
        + player_count * position_count * distinct_position_cost
        + player_count * (INNINGS - 1)
        + 1
    )
    one_inning_cost = (
        player_count
        * max(0, position_count - 2)
        * excess_position_cost
        + player_count * (INNINGS - 1) * two_inning_cost
        + player_count * position_count * distinct_position_cost
        + player_count * (INNINGS - 1)
        + 1
    )
    return (
        one_inning_cost,
        excess_position_cost,
        two_inning_cost,
        distinct_position_cost,
        transition_cost,
    )


def _bound_continuity_by_incumbent(
    model: cp_model.CpModel,
    consistency_penalty: cp_model.LinearExpr,
    incumbent_solver: cp_model.CpSolver,
) -> int:
    """Keep the full weighted incumbent while leaving better prefixes open."""

    incumbent_penalty = incumbent_solver.Value(consistency_penalty)
    model.Add(consistency_penalty <= incumbent_penalty)
    return incumbent_penalty


class LineupError(ValueError):
    """Raised when the inputs cannot produce a legal schedule."""


@dataclass(frozen=True)
class LineupPreflight:
    """Exact one-inning legality facts shared by callers and the optimizer."""

    active_positions: Tuple[str, ...]
    minimum_women: int
    eligibility: Tuple[Tuple[str, ...], ...]


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


def _one_inning_assignment_exists(
    players: Sequence[Player],
    active_positions: Sequence[str],
    eligibility: Sequence[Sequence[str]],
    *,
    minimum_women: int = 0,
    require_woman_infield_and_outfield: bool = False,
) -> bool:
    """Return whether distinct players can satisfy one complete inning."""

    eligible_players = {
        position: tuple(
            player_index
            for player_index in range(len(players))
            if position in eligibility[player_index]
        )
        for position in active_positions
    }
    position_order = tuple(
        sorted(
            active_positions,
            key=lambda position: (
                len(eligible_players[position]),
                active_positions.index(position),
            ),
        )
    )

    @lru_cache(maxsize=None)
    def search(
        position_offset: int,
        used_players: int,
        women_assigned: int,
        has_woman_infield: bool,
        has_woman_outfield: bool,
    ) -> bool:
        if position_offset == len(position_order):
            return (
                women_assigned >= minimum_women
                and (
                    not require_woman_infield_and_outfield
                    or (has_woman_infield and has_woman_outfield)
                )
            )

        remaining_positions = position_order[position_offset:]
        if women_assigned < minimum_women:
            unused_eligible_women = {
                player_index
                for position in remaining_positions
                for player_index in eligible_players[position]
                if not used_players & (1 << player_index)
                and players[player_index].is_woman
            }
            if women_assigned + min(
                len(remaining_positions), len(unused_eligible_women)
            ) < minimum_women:
                return False

        if require_woman_infield_and_outfield:
            for has_woman, position_group in (
                (has_woman_infield, INFIELD),
                (has_woman_outfield, OUTFIELD),
            ):
                if has_woman:
                    continue
                if not any(
                    position in position_group
                    and any(
                        not used_players & (1 << player_index)
                        and players[player_index].is_woman
                        for player_index in eligible_players[position]
                    )
                    for position in remaining_positions
                ):
                    return False

        position = position_order[position_offset]
        candidate_players = sorted(
            eligible_players[position],
            key=lambda player_index: not players[player_index].is_woman,
        )
        for player_index in candidate_players:
            player_bit = 1 << player_index
            if used_players & player_bit:
                continue
            is_woman = players[player_index].is_woman
            if search(
                position_offset + 1,
                used_players | player_bit,
                min(minimum_women, women_assigned + int(is_woman)),
                has_woman_infield
                or (is_woman and position in INFIELD),
                has_woman_outfield
                or (is_woman and position in OUTFIELD),
            ):
                return True
        return False

    return search(0, 0, 0, False, False)


def _hall_conflict(
    active_positions: Sequence[str],
    eligibility: Sequence[Sequence[str]],
) -> Optional[Tuple[Tuple[str, ...], int]]:
    """Return the canonical smallest Hall-deficient position subset."""

    eligible_by_position = {
        position: {
            player_index
            for player_index, player_positions in enumerate(eligibility)
            if position in player_positions
        }
        for position in active_positions
    }
    for subset_size in range(2, len(active_positions) + 1):
        for position_subset in combinations(active_positions, subset_size):
            eligible_players = set().union(
                *(eligible_by_position[position] for position in position_subset)
            )
            if len(eligible_players) < subset_size:
                return tuple(position_subset), len(eligible_players)
    return None


def lineup_preflight(
    players: Iterable[Player],
    *,
    profile: LeagueRules = COED_RULES,
) -> LineupPreflight:
    """Validate that the roster can field one exact legal inning."""

    player_list = tuple(players)
    rules = resolve_league_rules(profile)
    _validate_players(player_list)
    active_positions, minimum_women = _lineup_rules(player_list, rules)
    eligibility = tuple(
        _eligible_positions(player, active_positions) for player in player_list
    )
    uncovered = [
        position
        for position in active_positions
        if not any(position in player_positions for player_positions in eligibility)
    ]
    if uncovered:
        raise LineupError(
            "No available player is eligible for the following required position(s): "
            + ", ".join(uncovered)
            + "."
        )

    if not _one_inning_assignment_exists(
        player_list,
        active_positions,
        eligibility,
    ):
        conflict = _hall_conflict(active_positions, eligibility)
        if conflict is None:  # Hall's theorem guarantees a witness.
            raise LineupError(
                "No distinct-player assignment can fill every required position "
                "with the current eligibility."
            )
        conflict_positions, eligible_count = conflict
        position_noun = (
            "position" if len(conflict_positions) == 1 else "positions"
        )
        player_noun = "player" if eligible_count == 1 else "players"
        raise LineupError(
            "No legal schedule can fill one inning because position eligibility "
            "conflicts: "
            + ", ".join(conflict_positions)
            + f" require {len(conflict_positions)} distinct players but have "
            f"only {eligible_count} eligible {player_noun} between them "
            f"for those {position_noun}."
        )

    if not rules.require_woman_infield_and_outfield:
        return LineupPreflight(
            active_positions=tuple(active_positions),
            minimum_women=minimum_women,
            eligibility=eligibility,
        )

    women_infield = any(
        player.is_woman
        and any(position in INFIELD for position in eligibility[index])
        for index, player in enumerate(player_list)
    )
    women_outfield = any(
        player.is_woman
        and any(position in OUTFIELD for position in eligibility[index])
        for index, player in enumerate(player_list)
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

    if not _one_inning_assignment_exists(
        player_list,
        active_positions,
        eligibility,
        minimum_women=minimum_women,
        require_woman_infield_and_outfield=True,
    ):
        raise LineupError(
            "No distinct-player assignment can satisfy the Co-ed minimum-women "
            "and infield/outfield placement rules with the current position "
            "eligibility."
        )

    return LineupPreflight(
        active_positions=tuple(active_positions),
        minimum_women=minimum_women,
        eligibility=eligibility,
    )


def optimize_game(
    players: Iterable[Player],
    *,
    profile: LeagueRules = COED_RULES,
    max_solve_seconds: float = 5.0,
    fairness_solve_seconds: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ScheduleResult:
    """Build the fairest legal seven-inning schedule for available players."""

    player_list = tuple(players)
    rules = resolve_league_rules(profile)
    preflight = lineup_preflight(player_list, profile=rules)
    active_positions = preflight.active_positions
    minimum_women = preflight.minimum_women
    eligibility = {
        index: player_eligibility
        for index, player_eligibility in enumerate(preflight.eligibility)
    }
    fallback_eligibility = {
        index: _fallback_positions(player, active_positions)
        for index, player in enumerate(player_list)
    }
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
    (
        one_inning_cost,
        excess_position_cost,
        two_inning_cost,
        distinct_position_cost,
        transition_cost,
    ) = _continuity_weights(
        player_count, len(active_positions)
    )

    consistency_penalty = (
        sum(one_inning_stints) * one_inning_cost
        + sum(excess_position_counts) * excess_position_cost
        + sum(two_inning_stints) * two_inning_cost
        + sum(distinct_position_counts) * distinct_position_cost
        + sum(state_transitions) * transition_cost
    )
    continuity_tail_penalty = (
        sum(distinct_position_counts) * distinct_position_cost
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
        0.25,
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
            2.5,
            max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.55),
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
        # The exact fairness/preference incumbent is already a legal schedule.
        # A short continuity slice that finds no replacement must not turn that
        # incumbent into an application error. Keep it, mark this tier
        # unproven, and let the later full-objective searches continue.
        one_inning_solver = fallback_solver
        one_inning_status = fallback_status
        best_one_inning = sum(
            one_inning_solver.Value(item) for item in one_inning_stints
        )
        best_excess_positions = sum(
            one_inning_solver.Value(item) for item in excess_position_counts
        )
        ideal_stints_feasible = False
        one_inning_proven = False

    if ideal_stints_feasible:
        for stint_variables, unavoidable_singleton in ideal_one_inning_groups:
            model.Add(sum(stint_variables) == unavoidable_singleton)
    elif one_inning_proven:
        model.Add(sum(one_inning_stints) == best_one_inning)
    else:
        # Preserve the achieved ceiling without forbidding a later phase from
        # discovering a strictly better higher-priority value. The overall
        # result remains truthfully FEASIBLE because this count is unproven.
        model.Add(sum(one_inning_stints) <= best_one_inning)
    model.clear_hints()
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, one_inning_solver.Value(variable))

    solution_solver = one_inning_solver
    solution_status = one_inning_status
    # A lower-bound value for a tier is a proof only after every higher tier is
    # itself proven. Otherwise a better one-inning value may legitimately need
    # more excess positions, so component-wise fixing would violate lexicographic
    # priority.
    excess_proven = one_inning_proven and (
        best_excess_positions == 0
        or one_inning_status == cp_model.OPTIMAL
    )
    if excess_proven:
        if best_excess_positions == 0:
            for excess_positions in excess_position_counts:
                model.Add(excess_positions == 0)
        else:
            model.Add(sum(excess_position_counts) == best_excess_positions)
    elif best_excess_positions == 0:
        # Zero is already the lowest possible value, but it is not a proof of
        # this tier while one-inning continuity remains unproven: a better
        # one-inning schedule may require nonzero excess. Preserve the full
        # incumbent and spend no separate phase budget pretending otherwise.
        _bound_continuity_by_incumbent(
            model, consistency_penalty, solution_solver
        )
    else:
        # Preserve the entire incumbent vector while allowing a higher-priority
        # improvement to spend lower-priority quality. The coefficient hierarchy
        # makes this one linear ceiling exactly lexicographic over all feasible
        # continuity vectors.
        _bound_continuity_by_incumbent(
            model, consistency_penalty, solution_solver
        )
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
        ideal_excess_model.Minimize(
            0 if one_inning_proven else consistency_penalty
        )
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
        else:
            model.Minimize(
                sum(excess_position_counts)
                if one_inning_proven
                else consistency_penalty
            )
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

        if excess_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            incumbent_vector = _continuity_vector_from_solver(
                solution_solver,
                one_inning_stints,
                excess_position_counts,
                two_inning_stints,
                distinct_position_counts,
                state_transitions,
            )
            candidate_vector = _continuity_vector_from_solver(
                excess_solver,
                one_inning_stints,
                excess_position_counts,
                two_inning_stints,
                distinct_position_counts,
                state_transitions,
            )
            if _candidate_is_no_worse(
                excess_status, candidate_vector, incumbent_vector
            ):
                solution_solver = excess_solver
                solution_status = excess_status
                incumbent_vector = candidate_vector

        incumbent_vector = _continuity_vector_from_solver(
            solution_solver,
            one_inning_stints,
            excess_position_counts,
            two_inning_stints,
            distinct_position_counts,
            state_transitions,
        )
        best_one_inning = incumbent_vector[0]
        best_excess_positions = incumbent_vector[1]
        excess_proven = one_inning_proven and (
            best_excess_positions == 0
            or excess_status == cp_model.OPTIMAL
        )
        if excess_proven:
            model.Add(sum(excess_position_counts) == best_excess_positions)
        else:
            _bound_continuity_by_incumbent(
                model, consistency_penalty, solution_solver
            )
        model.clear_hints()
        for variable in (*assignments.values(), *bench_assignments.values()):
            model.AddHint(variable, solution_solver.Value(variable))

    _report_progress(progress_callback, CONSISTENCY_PROGRESS)
    # Give the next lexicographic tier its own focused slice. A smaller
    # two-inning count outranks tail polish once the higher tiers are proven.
    # Otherwise keep optimizing the complete lexicographic expression.
    continuity_prefix_proven = one_inning_proven and excess_proven
    model.Minimize(
        (
            sum(two_inning_stints) * two_inning_cost
            + continuity_tail_penalty
        )
        if continuity_prefix_proven
        else consistency_penalty
    )
    _bound_continuity_by_incumbent(
        model, consistency_penalty, solution_solver
    )
    two_inning_budget = min(
        2.0,
        max(0.1, (max_solve_seconds - (monotonic() - started_at)) * 0.95),
    )

    def solve_two_inning_neighborhood(seed: int):
        neighborhood_model = model.clone()
        neighborhood_solver = cp_model.CpSolver()
        neighborhood_solver.parameters.max_time_in_seconds = two_inning_budget
        neighborhood_solver.parameters.num_search_workers = 4
        neighborhood_solver.parameters.random_seed = seed
        neighborhood_solver.parameters.use_lns_only = seed == 43
        neighborhood_status = neighborhood_solver.Solve(neighborhood_model)
        return neighborhood_solver, neighborhood_status

    with ThreadPoolExecutor(max_workers=2) as executor:
        two_inning_results = tuple(
            executor.map(solve_two_inning_neighborhood, (42, 43))
        )

    incumbent_continuity = _continuity_vector_from_solver(
        solution_solver,
        one_inning_stints,
        excess_position_counts,
        two_inning_stints,
        distinct_position_counts,
        state_transitions,
    )
    for two_inning_solver, two_inning_status in two_inning_results:
        if two_inning_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue
        candidate_continuity = _continuity_vector_from_solver(
            two_inning_solver,
            one_inning_stints,
            excess_position_counts,
            two_inning_stints,
            distinct_position_counts,
            state_transitions,
        )
        if _candidate_is_no_worse(
            two_inning_status, candidate_continuity, incumbent_continuity
        ):
            solution_solver = two_inning_solver
            solution_status = two_inning_status
            incumbent_continuity = candidate_continuity

    best_two_inning = incumbent_continuity[2]
    two_inning_proven = continuity_prefix_proven and (
        best_two_inning == 0
        or two_inning_results[0][1] == cp_model.OPTIMAL
    )
    if two_inning_proven:
        model.Add(sum(two_inning_stints) == best_two_inning)
    else:
        _bound_continuity_by_incumbent(
            model, consistency_penalty, solution_solver
        )
    model.clear_hints()
    for variable in (*assignments.values(), *bench_assignments.values()):
        model.AddHint(variable, solution_solver.Value(variable))

    # Tail-only polish is valid only after all higher continuity tiers are
    # proven. Otherwise the full objective must remain live so a better prefix
    # may spend lower-priority quality.
    continuity_through_two_proven = (
        continuity_prefix_proven and two_inning_proven
    )
    model.Minimize(
        continuity_tail_penalty
        if continuity_through_two_proven
        else consistency_penalty
    )

    incumbent_continuity = _continuity_vector_from_solver(
        solution_solver,
        one_inning_stints,
        excess_position_counts,
        two_inning_stints,
        distinct_position_counts,
        state_transitions,
    )
    # A hint is not a quality guarantee. Keep the already legal incumbent in
    # the final search slice while leaving every lexicographically better full
    # vector admissible.
    _bound_continuity_by_incumbent(
        model, consistency_penalty, solution_solver
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(
        0.1, max_solve_seconds - (monotonic() - started_at)
    )
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    final_status = solver.Solve(model)

    final_candidate_accepted = False
    if final_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        candidate_continuity = _continuity_vector_from_solver(
            solver,
            one_inning_stints,
            excess_position_counts,
            two_inning_stints,
            distinct_position_counts,
            state_transitions,
        )
        if _candidate_is_no_worse(
            final_status, candidate_continuity, incumbent_continuity
        ):
            solution_solver = solver
            solution_status = final_status
            final_candidate_accepted = True

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
        and two_inning_proven
        and final_candidate_accepted
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

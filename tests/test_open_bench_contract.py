from collections import Counter
from itertools import groupby

import pytest

from softball_fielding import LineupError, OPEN_RULES, Player, optimize_game
from softball_fielding.models import INNINGS, POSITIONS
from softball_fielding.roster_templates import team_red_roster


TEAM_RED_PREFERENCES = {
    "David R": ("2B", "RC"),
    "Justin": ("1B", "RC"),
    "Andrew": ("C", "2B", "RF"),
    "Kevin": ("2B", "LC"),
    "David": ("RF",),
    "Dung": ("P",),
    "Heather": ("LF", "LC"),
    "Ryan": ("1B", "3B"),
    "Tristan": ("C", "3B"),
    "Brad": ("C", "LF"),
    "AP": ("SS", "LF"),
    "Chris": ("C", "2B", "RF"),
    "Marty": ("SS", "LC"),
}


def player(name, *preferences):
    return Player(name, "Man", frozenset(preferences))


def player_states(result, player_name):
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


def runs(states):
    return [
        (state, len(tuple(run)))
        for state, run in groupby(states)
    ]


def assert_open_assignment_invariants(result, players):
    by_name = {candidate.name: candidate for candidate in players}
    actual_innings = Counter()
    actual_positions = {candidate.name: set() for candidate in players}

    assert len(result.assignments) == INNINGS
    for inning in result.assignments:
        assert set(inning) == set(result.active_positions)
        assert len(set(inning.values())) == result.lineup_size
        actual_innings.update(inning.values())

        for position, name in inning.items():
            actual_positions[name].add(position)
            preferences = by_name[name].preferences
            assert position in preferences or (
                position == "RC"
                and "RF" not in result.active_positions
                and "RF" in preferences
            )

    assert result.player_innings == {
        candidate.name: actual_innings[candidate.name]
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


def test_team_red_template_matches_the_approved_public_roster():
    roster = team_red_roster()

    assert [record["name"] for record in roster] == list(TEAM_RED_PREFERENCES)
    assert len({record["name"].casefold() for record in roster}) == len(roster)
    assert all(record["available"] for record in roster)
    assert {record["gender"] for record in roster} == {"Unspecified"}
    assert {
        record["name"]: tuple(
            position
            for position in POSITIONS
            if position in record["preferences"]
        )
        for record in roster
    } == TEAM_RED_PREFERENCES
    assert {
        position
        for record in roster
        for position in record["preferences"]
    } == set(POSITIONS)


def test_team_red_open_schedule_is_fair_and_minimizes_state_switches():
    roster = team_red_roster()
    players = [
        Player(
            record["name"],
            record["gender"],
            frozenset(record["preferences"]),
        )
        for record in roster
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert result.solver_status == "OPTIMAL"
    assert result.active_positions == POSITIONS
    assert_open_assignment_invariants(result, players)
    assert Counter(result.player_innings.values()) == Counter({5: 9, 6: 3, 7: 1})
    assert result.player_innings["Dung"] == INNINGS
    assert all(inning["P"] == "Dung" for inning in result.assignments)
    assert all(len(positions) <= 2 for positions in result.player_positions.values())

    total_transitions = 0
    one_inning_runs = []
    two_inning_runs = 0
    for candidate in players:
        states = player_states(result, candidate.name)
        state_runs = runs(states)
        total_transitions += sum(
            first != second for first, second in zip(states, states[1:])
        )
        one_inning_runs.extend(
            (candidate.name, state)
            for state, length in state_runs
            if length == 1
        )
        two_inning_runs += sum(length == 2 for _state, length in state_runs)
        assert len(state_runs) == len(set(states))

        bench_innings = INNINGS - result.player_innings[candidate.name]
        bench_runs = [
            length for state, length in state_runs if state == "Bench"
        ]
        assert bench_runs == ([bench_innings] if bench_innings else [])
        assert not any(
            state != "Bench" and length == 1
            for state, length in state_runs
        )

    assert len(one_inning_runs) == 3
    assert {state for _name, state in one_inning_runs} == {"Bench"}
    assert two_inning_runs == 15
    assert total_transitions == 18
    assert sum(len(positions) for positions in result.player_positions.values()) == 19


def test_team_red_requires_its_only_pitcher_to_be_available():
    players = [
        Player(
            record["name"],
            record["gender"],
            frozenset(record["preferences"]),
        )
        for record in team_red_roster()
        if record["name"] != "Dung"
    ]

    with pytest.raises(LineupError, match=r"required position\(s\): P"):
        optimize_game(players, profile=OPEN_RULES)


def test_open_seven_player_roster_fails_without_a_gender_shortage():
    players = [player(f"Player {index}", *POSITIONS) for index in range(7)]

    with pytest.raises(LineupError, match="At least 8 available players") as raised:
        optimize_game(players, profile=OPEN_RULES)

    message = str(raised.value).lower()
    assert "women" not in message
    assert "gender" not in message


def test_open_nine_player_lineup_fills_rc_from_an_rf_preference():
    players = [
        player("Pitcher", "P"),
        player("Catcher", "C"),
        player("First", "1B"),
        player("Second", "2B"),
        player("Third", "3B"),
        player("Short", "SS"),
        player("Left", "LF"),
        player("Left Center", "LC"),
        player("Right Fielder", "RF"),
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert result.active_positions == tuple(
        position for position in POSITIONS if position != "RF"
    )
    assert_open_assignment_invariants(result, players)
    assert set(result.player_innings.values()) == {INNINGS}
    assert all(
        inning["RC"] == "Right Fielder"
        for inning in result.assignments
    )
    assert result.player_positions["Right Fielder"] == ("RC",)
    assert all(
        "Bench" not in player_states(result, name)
        for name in result.player_innings
    )


def test_open_flexible_players_get_fair_contiguous_single_position_runs():
    flexible_names = [f"P-C Flex {index}" for index in range(4)]
    flexible_players = [player(name, "P", "C") for name in flexible_names]
    locked_players = [
        player(position, position)
        for position in POSITIONS
        if position not in {"P", "C"}
    ]
    players = [*flexible_players, *locked_players]

    result = optimize_game(players, profile=OPEN_RULES)

    assert result.active_positions == POSITIONS
    assert_open_assignment_invariants(result, players)
    assert all(
        result.player_innings[candidate.name] == INNINGS
        for candidate in locked_players
    )
    assert Counter(
        result.player_innings[name] for name in flexible_names
    ) == Counter({3: 2, 4: 2})
    assert Counter(
        result.player_positions[name] for name in flexible_names
    ) == Counter({("P",): 2, ("C",): 2})

    total_bench_innings = 0
    for name in flexible_names:
        states = player_states(result, name)
        state_runs = runs(states)
        field_position = result.player_positions[name][0]
        bench_innings = INNINGS - result.player_innings[name]
        total_bench_innings += bench_innings

        assert set(states) == {field_position, "Bench"}
        assert len(state_runs) == 2
        assert {state for state, _length in state_runs} == {
            field_position,
            "Bench",
        }
        assert sorted(length for _state, length in state_runs) == [3, 4]
        assert sum(
            first != second for first, second in zip(states, states[1:])
        ) == 1

    assert total_bench_innings == INNINGS * (len(players) - result.lineup_size)

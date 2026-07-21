from collections import Counter

import pytest

from softball_fielding import LineupError, Player, optimize_game
from softball_fielding.models import INFIELD, OUTFIELD, POSITIONS


def player(name, gender, *preferences):
    return Player(name, gender, frozenset(preferences))


def assert_legal(result, players, minimum_women):
    by_name = {candidate.name: candidate for candidate in players}
    for inning in result.assignments:
        assert set(inning) == set(result.active_positions)
        assert len(set(inning.values())) == result.lineup_size

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


def test_nine_players_omit_rf_and_rf_preference_becomes_rc():
    players = [
        player("W Pitcher", "Woman", "P"),
        player("W Second", "Woman", "2B"),
        player("W Left", "Woman", "LF"),
        player("Catcher", "Man", "C"),
        player("First", "Man", "1B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left Center", "Man", "LC"),
        player("Right Fielder", "Man", "RF"),
    ]

    result = optimize_game(players)

    assert "RF" not in result.active_positions
    assert "C" in result.active_positions
    assert all(inning["RC"] == "Right Fielder" for inning in result.assignments)
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


def test_positional_preferences_are_hard_constraints():
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


def test_playing_time_counts_match_assignments():
    players = [
        player(f"W{index}", "Woman", *POSITIONS) for index in range(4)
    ] + [player(f"M{index}", "Man", *POSITIONS) for index in range(8)]
    result = optimize_game(players)

    actual = Counter(name for inning in result.assignments for name in inning.values())
    assert result.player_innings == {
        candidate.name: actual[candidate.name] for candidate in players
    }

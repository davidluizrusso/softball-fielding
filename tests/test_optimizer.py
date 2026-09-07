from collections import Counter
from itertools import groupby

import pytest

from softball_fielding import (
    LineupError,
    OPEN_RULES,
    Player,
    lineup_plan,
    lineup_shortages,
    optimize_game,
)
from softball_fielding.models import INFIELD, OUTFIELD, POSITIONS


def player(name, gender, *preferences):
    return Player(name, gender, frozenset(preferences))


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
            preferences = by_name[name].preferences
            assert position in preferences or (
                position == "RC"
                and "RF" not in expected_positions
                and "RF" in preferences
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
            preferences = by_name[name].preferences
            assert position in preferences or (
                position == "RC"
                and "RF" not in result.active_positions
                and "RF" in preferences
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


def test_open_full_lineup_does_not_fall_back_when_rf_is_uncovered():
    preferences = tuple(position for position in POSITIONS if position != "RF")
    players = [
        player(f"M{index}", "Man", *preferences) for index in range(10)
    ]

    with pytest.raises(LineupError, match="RF") as raised:
        optimize_game(players, profile=OPEN_RULES)

    assert "gender" not in str(raised.value).lower()


def test_bench_aware_continuity_keeps_paired_position_runs_together():
    players = [
        player(f"{position}-{index}", "Man", position)
        for position in POSITIONS
        for index in range(2)
    ]

    result = optimize_game(players, profile=OPEN_RULES)

    assert_schedule_invariants(result, players, OPEN_RULES)
    assert_equal_share(result)
    metrics = continuity_metrics(result)
    assert metrics == {
        "bench_total": 70,
        "bench_runs": 20,
        "one_inning_state_runs": 0,
        "two_inning_state_runs": 0,
        "excess_field_positions": 0,
        "distinct_field_positions": 20,
        "transitions": 20,
    }


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
        (("LF", "LC", "RC"), "infield"),
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

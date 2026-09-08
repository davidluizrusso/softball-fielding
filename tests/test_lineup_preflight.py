from unittest.mock import Mock

import pytest

import softball_fielding.optimizer as optimizer_module
from softball_fielding import COED_RULES, OPEN_RULES, LineupError, Player
from softball_fielding.models import POSITIONS
from softball_fielding.optimizer import lineup_preflight
from softball_fielding.team_setups import team_red_roster


def player(name, gender, *preferences):
    return Player(name, gender, frozenset(preferences))


def team_red_players(*, absent=()):
    absent_names = set(absent)
    return [
        Player(
            record["name"],
            record["gender"],
            frozenset(record["preferences"]),
        )
        for record in team_red_roster()
        if record["name"] not in absent_names
    ]


@pytest.mark.parametrize(
    ("absent", "position"),
    [
        (("Dung",), "P"),
        (("Justin", "Ryan"), "1B"),
        (("AP", "Marty"), "SS"),
    ],
)
def test_team_red_preflight_reports_canonical_uncovered_positions(
    absent, position
):
    with pytest.raises(LineupError) as raised:
        lineup_preflight(
            team_red_players(absent=absent),
            profile=OPEN_RULES,
        )

    assert str(raised.value) == (
        "No available player is eligible for the following required "
        f"position(s): {position}."
    )


def test_preflight_reports_a_canonical_hall_conflict():
    players = [
        player("Only P and 1B", "Man", "P", "1B"),
        player("Second", "Man", "2B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left", "Man", "LF"),
        player("Left Center", "Man", "LC"),
        player("Right Center", "Man", "RC"),
        player("Right", "Man", "RF"),
        player("Utility One", "Man", "C"),
        player("Utility Two", "Man", "C"),
    ]

    with pytest.raises(LineupError) as raised:
        lineup_preflight(players, profile=OPEN_RULES)

    assert str(raised.value) == (
        "No legal schedule can fill one inning because position eligibility "
        "conflicts: P, 1B require 2 distinct players but have only 1 eligible "
        "player between them for those positions."
    )


def test_preflight_applies_universal_catcher_eligibility():
    players = [
        player("Pitcher", "Man", "P"),
        player("First", "Man", "1B"),
        player("Second", "Man", "2B"),
        player("Third", "Man", "3B"),
        player("Short", "Man", "SS"),
        player("Left", "Man", "LF"),
        player("Left Center", "Man", "LC"),
        player("Right Center", "Man", "RC"),
        player("Right", "Man", "RF"),
        player("Extra", "Man", "RF"),
    ]

    preflight = lineup_preflight(players, profile=OPEN_RULES)

    assert preflight.active_positions == POSITIONS
    assert all("C" in eligibility for eligibility in preflight.eligibility)


def test_eight_player_preflight_applies_the_rf_to_rc_rule():
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

    preflight = lineup_preflight(players, profile=OPEN_RULES)
    right_fielder_index = next(
        index for index, candidate in enumerate(players)
        if candidate.name == "Right Fielder"
    )

    assert preflight.active_positions == tuple(
        position for position in POSITIONS if position not in {"C", "RF"}
    )
    assert preflight.eligibility[right_fielder_index] == ("RC",)


@pytest.mark.parametrize(
    ("player_count", "woman_count", "inactive_positions", "minimum_women"),
    [
        (10, 4, set(), 4),
        (9, 3, {"RF"}, 3),
        (8, 3, {"C", "RF"}, 3),
    ],
)
def test_coed_preflight_accepts_exact_8_9_and_10_player_lineups(
    player_count, woman_count, inactive_positions, minimum_women
):
    players = [
        player(f"Woman {index}", "Woman", *POSITIONS)
        for index in range(woman_count)
    ] + [
        player(f"Man {index}", "Man", *POSITIONS)
        for index in range(player_count - woman_count)
    ]

    preflight = lineup_preflight(players, profile=COED_RULES)

    assert preflight.active_positions == tuple(
        position for position in POSITIONS if position not in inactive_positions
    )
    assert preflight.minimum_women == minimum_women


def test_coed_preflight_reports_a_missing_woman_placement_group():
    players = [
        player("Woman Pitcher", "Woman", "P"),
        player("Woman First", "Woman", "1B"),
        player("Woman Second", "Woman", "2B"),
        player("Woman Third", "Woman", "3B"),
    ] + [
        player(f"Flexible Man {index}", "Man", *POSITIONS)
        for index in range(6)
    ]

    with pytest.raises(LineupError) as raised:
        lineup_preflight(players, profile=COED_RULES)

    assert str(raised.value) == (
        "At least one available woman must be eligible for an active "
        "outfield position."
    )


def test_coed_preflight_detects_a_distinct_assignment_gender_conflict():
    players = [
        player("Woman Pitcher One", "Woman", "P"),
        player("Woman Pitcher Two", "Woman", "P"),
        player("Woman Pitcher Three", "Woman", "P"),
        player("Woman Left", "Woman", "LF"),
    ] + [
        player(f"Flexible Man {index}", "Man", *POSITIONS)
        for index in range(8)
    ]

    with pytest.raises(LineupError) as raised:
        lineup_preflight(players, profile=COED_RULES)

    assert str(raised.value) == (
        "No distinct-player assignment can satisfy the Co-ed minimum-women "
        "and infield/outfield placement rules with the current position "
        "eligibility."
    )


def test_optimizer_calls_the_shared_lineup_preflight(monkeypatch):
    preflight = Mock(side_effect=LineupError("shared preflight sentinel"))
    monkeypatch.setattr(optimizer_module, "lineup_preflight", preflight)
    players = [
        player(f"Player {index}", "Man", *POSITIONS)
        for index in range(10)
    ]

    with pytest.raises(LineupError, match="shared preflight sentinel"):
        optimizer_module.optimize_game(players, profile=OPEN_RULES)

    preflight.assert_called_once_with(tuple(players), profile=OPEN_RULES)

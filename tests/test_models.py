import pytest

from softball_fielding import Player
from softball_fielding.models import (
    COED_RULES,
    OPEN_RULES,
    LeagueRules,
    resolve_league_rules,
)


@pytest.mark.parametrize(
    ("gender", "normalized", "is_woman"),
    [
        ("W", "Woman", True),
        ("female", "Woman", True),
        ("M", "Man", False),
        ("male", "Man", False),
        ("Unspecified", "Unspecified", False),
    ],
)
def test_player_normalizes_supported_gender_aliases(gender, normalized, is_woman):
    candidate = Player("  Casey  ", gender, frozenset({" ss ", "lf"}))

    assert candidate.name == "Casey"
    assert candidate.gender == normalized
    assert candidate.is_woman is is_woman
    assert candidate.preferences == frozenset({"SS", "LF"})


@pytest.mark.parametrize(
    ("name", "gender", "preferences", "message"),
    [
        (" ", "Woman", frozenset({"P"}), "names cannot be blank"),
        (
            "Casey",
            "unknown",
            frozenset({"P"}),
            "must be Woman, Man, or Unspecified",
        ),
        ("Casey", "Woman", frozenset(), "at least one positional preference"),
        ("Casey", "Woman", frozenset({"DH"}), "Unknown position.*DH"),
    ],
)
def test_player_rejects_invalid_domain_values(name, gender, preferences, message):
    with pytest.raises(ValueError, match=message):
        Player(name, gender, preferences)


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (None, COED_RULES),
        ("coed", COED_RULES),
        (" CoEd ", COED_RULES),
        ("open", OPEN_RULES),
        (OPEN_RULES, OPEN_RULES),
    ],
)
def test_resolve_league_rules_accepts_public_profile_forms(profile, expected):
    assert resolve_league_rules(profile) is expected


def test_resolve_league_rules_preserves_a_custom_rules_object():
    custom = LeagueRules(
        key="custom",
        label="Custom",
        full_lineup_minimum_women=2,
        reduced_lineup_minimum_women=1,
        require_woman_infield_and_outfield=False,
    )

    assert resolve_league_rules(custom) is custom


def test_resolve_league_rules_rejects_unknown_profiles():
    with pytest.raises(ValueError, match="Unknown league profile.*mystery"):
        resolve_league_rules("mystery")

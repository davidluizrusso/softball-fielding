"""Domain models for the softball fielding optimizer."""

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple, Union


POSITIONS: Tuple[str, ...] = (
    "P",
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "LF",
    "LC",
    "RC",
    "RF",
)
INFIELD: FrozenSet[str] = frozenset(("P", "C", "1B", "2B", "3B", "SS"))
OUTFIELD: FrozenSet[str] = frozenset(("LF", "LC", "RC", "RF"))
INNINGS = 7


@dataclass(frozen=True)
class LeagueRules:
    """Hard lineup constraints for one league profile."""

    key: str
    label: str
    full_lineup_minimum_women: int
    reduced_lineup_minimum_women: int
    require_woman_infield_and_outfield: bool


COED_RULES = LeagueRules(
    key="coed",
    label="Co-ed",
    full_lineup_minimum_women=4,
    reduced_lineup_minimum_women=3,
    require_woman_infield_and_outfield=True,
)
OPEN_RULES = LeagueRules(
    key="open",
    label="Open (no gender fielding minimums)",
    full_lineup_minimum_women=0,
    reduced_lineup_minimum_women=0,
    require_woman_infield_and_outfield=False,
)
LEAGUE_RULES = (COED_RULES, OPEN_RULES)


def resolve_league_rules(profile: Union[LeagueRules, str, None]) -> LeagueRules:
    """Normalize a public profile argument into a rules object."""

    if profile is None:
        return COED_RULES
    if isinstance(profile, LeagueRules):
        return profile
    normalized = str(profile).strip().lower()
    for rules in LEAGUE_RULES:
        if normalized == rules.key:
            return rules
    raise ValueError(f"Unknown league profile: {profile!r}.")


@dataclass(frozen=True)
class Player:
    """A player available for a single game."""

    name: str
    gender: str
    preferences: FrozenSet[str]

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_gender = self.gender.strip().lower()
        gender_aliases = {
            "w": "Woman",
            "woman": "Woman",
            "f": "Woman",
            "female": "Woman",
            "m": "Man",
            "man": "Man",
            "male": "Man",
        }
        if not normalized_name:
            raise ValueError("Player names cannot be blank.")
        if normalized_gender not in gender_aliases:
            raise ValueError(
                f"Gender for {normalized_name} must be Woman or Man."
            )

        normalized_preferences = frozenset(
            position.strip().upper() for position in self.preferences
        )
        invalid = normalized_preferences.difference(POSITIONS)
        if invalid:
            raise ValueError(
                f"Unknown position(s) for {normalized_name}: "
                f"{', '.join(sorted(invalid))}."
            )
        if not normalized_preferences:
            raise ValueError(
                f"{normalized_name} needs at least one positional preference."
            )

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "gender", gender_aliases[normalized_gender])
        object.__setattr__(self, "preferences", normalized_preferences)

    @property
    def is_woman(self) -> bool:
        return self.gender == "Woman"


@dataclass(frozen=True)
class ScheduleResult:
    """A solved seven-inning schedule and its summary data."""

    assignments: Tuple[Dict[str, str], ...]
    active_positions: Tuple[str, ...]
    player_innings: Dict[str, int]
    player_positions: Dict[str, Tuple[str, ...]]
    solver_status: str

    @property
    def lineup_size(self) -> int:
        return len(self.active_positions)

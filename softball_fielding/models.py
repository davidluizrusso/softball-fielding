"""Domain models for the softball fielding optimizer."""

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple


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

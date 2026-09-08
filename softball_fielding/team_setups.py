"""Named roster setups shared by the web app and regression tests."""

import csv
from pathlib import Path
from typing import Dict, List

from .models import POSITIONS


TEAM_RED_ROSTER_CSV = (
    Path(__file__).resolve().parents[1] / "team_red_roster.csv"
)


def _selected(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "x"}


def team_red_roster() -> List[Dict[str, object]]:
    """Load the published Team Red roster without inventing gender data."""

    with TEAM_RED_ROSTER_CSV.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        columns = {str(column).strip().upper() for column in reader.fieldnames or ()}
        required_columns = {"NAME", *POSITIONS}
        missing_columns = sorted(required_columns.difference(columns))
        if missing_columns:
            raise ValueError(
                f"{TEAM_RED_ROSTER_CSV.name} is missing column(s): "
                + ", ".join(missing_columns)
                + "."
            )
        rows = list(reader)

    roster: List[Dict[str, object]] = []
    normalized_names = set()
    for index, row in enumerate(rows, start=1):
        normalized_row = {
            str(column).strip().upper(): value
            for column, value in row.items()
        }
        name = str(normalized_row.get("NAME", "")).strip()
        if not name:
            continue
        normalized_name = name.casefold()
        if normalized_name in normalized_names:
            raise ValueError(
                f"{TEAM_RED_ROSTER_CSV.name} contains duplicate name: {name}."
            )
        normalized_names.add(normalized_name)
        preferences = {
            position
            for position in POSITIONS
            if _selected(normalized_row.get(position, ""))
        }
        # Validate template-specific invariants here. The optimizer constructs
        # and validates Player domain objects at the solve boundary.
        if not preferences:
            raise ValueError(
                f"{TEAM_RED_ROSTER_CSV.name} must include at least one "
                f"position for {name}."
            )
        roster.append(
            {
                "id": f"player-{index}",
                "name": name,
                "gender": "Unspecified",
                "available": True,
                "preferences": preferences,
            }
        )

    return roster

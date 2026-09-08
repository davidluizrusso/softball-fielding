"""Backward-compatible imports for the renamed team-setup loader."""

from .team_setups import TEAM_RED_ROSTER_CSV, team_red_roster

__all__ = ["TEAM_RED_ROSTER_CSV", "team_red_roster"]

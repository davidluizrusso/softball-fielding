"""Softball defensive lineup optimization."""

from .models import (
    COED_RULES,
    LEAGUE_RULES,
    OPEN_RULES,
    LeagueRules,
    Player,
    ScheduleResult,
)
from .optimizer import LineupError, lineup_plan, lineup_shortages, optimize_game

__all__ = [
    "LineupError",
    "COED_RULES",
    "LEAGUE_RULES",
    "OPEN_RULES",
    "LeagueRules",
    "Player",
    "ScheduleResult",
    "lineup_plan",
    "lineup_shortages",
    "optimize_game",
]

# This completion marker must remain after every package import above. The
# Streamlit bootstrap uses it to distinguish a fully rebound package graph
# from a worker that retained pre-deploy modules.
RUNTIME_PACKAGE_VERSION = 2

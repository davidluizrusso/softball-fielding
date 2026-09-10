import subprocess
import sys
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]


def test_stale_package_graph_is_atomically_reloaded_before_team_red_solve():
    script = dedent(
        """
        from concurrent.futures import ThreadPoolExecutor

        import softball_fielding as package
        import softball_fielding.models as models
        import softball_fielding.optimizer as optimizer
        import softball_fielding.team_setups as team_setups
        import softball_fielding.runtime_bootstrap as runtime_bootstrap

        class StalePlayer:
            def __init__(self, name, gender, preferences):
                if str(gender).strip().lower() == "unspecified":
                    raise ValueError(f"Gender for {name} must be Woman or Man.")

        package.RUNTIME_PACKAGE_VERSION = 1
        package.Player = StalePlayer
        models.Player = StalePlayer
        optimizer.Player = StalePlayer
        models.POSITIONS = ("STALE",)
        optimizer.POSITIONS = models.POSITIONS
        team_setups.POSITIONS = models.POSITIONS

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(
                executor.map(
                    lambda _index: runtime_bootstrap.ensure_current_package(3),
                    range(8),
                )
            )

        assert package.RUNTIME_PACKAGE_VERSION == 3
        assert package.Player is models.Player
        assert optimizer.Player is models.Player
        assert optimizer.COED_RULES is models.COED_RULES
        assert team_setups.POSITIONS is models.POSITIONS
        assert package.optimize_game is optimizer.optimize_game
        assert package.lineup_preflight is optimizer.lineup_preflight

        roster = team_setups.team_red_roster()
        players = [
            package.Player(
                str(record["name"]),
                str(record["gender"]),
                frozenset(record["preferences"]),
            )
            for record in roster
            if record["available"]
        ]
        result = package.optimize_game(
            players,
            profile=package.OPEN_RULES,
            max_solve_seconds=15.0,
        )

        assert len(roster) == 14
        assert all(player.gender == "Unspecified" for player in players)
        assert len(result.assignments) == 7
        print("stale graph repaired and Team Red optimized")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert "stale graph repaired and Team Red optimized" in completed.stdout

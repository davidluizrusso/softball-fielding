"""Distinct Community Cloud entrypoint for the team-neutral deployment."""

from pathlib import Path
from runpy import run_path


run_path(
    str(Path(__file__).resolve().with_name("app.py")),
    init_globals={"NEUTRAL_DEPLOYMENT": True},
    run_name="__main__",
)

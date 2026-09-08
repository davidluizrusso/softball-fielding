"""Repair stale package modules left behind by a hot Streamlit deployment."""

from importlib import import_module, reload
from threading import RLock


_RELOAD_LOCK = RLock()


def ensure_current_package(required_version: int) -> None:
    """Atomically refresh the package dependency graph when it is stale."""

    package = import_module("softball_fielding")
    if getattr(package, "RUNTIME_PACKAGE_VERSION", 0) >= required_version:
        return

    with _RELOAD_LOCK:
        package = import_module("softball_fielding")
        if getattr(package, "RUNTIME_PACKAGE_VERSION", 0) >= required_version:
            return

        models = reload(import_module("softball_fielding.models"))
        reload(import_module("softball_fielding.optimizer"))
        reload(import_module("softball_fielding.team_setups"))
        package = reload(package)

        if (
            getattr(package, "RUNTIME_PACKAGE_VERSION", 0)
            < required_version
            or package.Player is not models.Player
        ):
            raise RuntimeError("Softball optimizer package reload did not complete.")

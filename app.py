"""Streamlit interface for the softball fielding optimizer."""

from copy import deepcopy
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from softball_fielding.runtime_bootstrap import ensure_current_package

# Community Cloud can rerun an updated app.py inside a worker whose imported
# package modules still contain pre-deploy code. This version-gated operation
# is a no-op for a coherent process and lock-serializes stale-graph repair.
REQUIRED_PACKAGE_VERSION = 2
ensure_current_package(REQUIRED_PACKAGE_VERSION)

from softball_fielding import (
    COED_RULES,
    LEAGUE_RULES,
    LineupError,
    OPEN_RULES,
    Player,
    lineup_plan,
    optimize_game,
)
from softball_fielding.models import INNINGS, POSITIONS
from softball_fielding.team_setups import team_red_roster


st.set_page_config(
    page_title="Softball Fielding Optimizer",
    page_icon="🥎",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1100px;
        padding-top: 1.75rem;
        padding-bottom: 4rem;
    }
    [data-testid="stButton"] button {
        min-height: 2.75rem;
    }
    [data-testid="stExpander"] summary {
        min-height: 3rem;
    }
    [data-testid="stCheckbox"] label {
        min-height: 2.75rem;
        align-items: center;
    }
    [data-testid="stRadio"] label {
        min-height: 3rem;
        align-items: center;
    }
    .seven-inning-lineup-scroll {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-x: contain;
        -webkit-overflow-scrolling: touch;
    }
    .seven-inning-lineup-scroll:focus-visible {
        outline: 0.2rem solid #ff4b4b;
        outline-offset: 0.15rem;
    }
    .seven-inning-lineup {
        border-collapse: collapse;
        min-width: 72rem;
        width: 100%;
    }
    .seven-inning-lineup caption {
        font-weight: 700;
        padding: 0 0 0.5rem;
        text-align: left;
    }
    .seven-inning-lineup th,
    .seven-inning-lineup td {
        border-bottom: 1px solid rgba(49, 51, 63, 0.2);
        overflow-wrap: anywhere;
        padding: 0.5rem;
        text-align: left;
        vertical-align: top;
    }
    .seven-inning-lineup th:first-child {
        min-width: 4.5rem;
    }
    .seven-inning-lineup th:last-child,
    .seven-inning-lineup td:last-child {
        min-width: 10rem;
    }
    @media (max-width: 640px) {
        .block-container {
            padding: 0.8rem 0.75rem 3rem;
        }
        h1 {
            font-size: 1.85rem !important;
            line-height: 1.15 !important;
        }
        h2, h3 {
            line-height: 1.2 !important;
        }
        [data-testid="stButton"] button,
        [data-testid="stExpander"] summary,
        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label {
            min-height: 3rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


ROSTER_CSV = Path(__file__).with_name("roster_positions.csv")
DEFAULT_ROSTER_VERSION = 1
IS_NEUTRAL_DEPLOYMENT = bool(globals().get("NEUTRAL_DEPLOYMENT", False))
HERE_FOR_THE_BEER_SETUP = "here-for-the-beer"
TEAM_RED_SETUP = "team-red"
BLANK_SETUP = "blank"
SETUP_LABELS = {
    HERE_FOR_THE_BEER_SETUP: "Here For The Beer",
    TEAM_RED_SETUP: "Team Red",
    BLANK_SETUP: "Start blank",
}
SETUP_DEFAULT_PROFILES = {
    HERE_FOR_THE_BEER_SETUP: COED_RULES.key,
    TEAM_RED_SETUP: OPEN_RULES.key,
    BLANK_SETUP: COED_RULES.key,
}
LEGACY_SAMPLE_NAMES = {
    "Alex",
    "Blair",
    "Casey",
    "Drew",
    "Evan",
    "Finley",
    "Gray",
    "Hayden",
    "Jamie",
    "Kai",
    "Logan",
    "Morgan",
}


def selected(value: object) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "x"}


def normalized_gender(value: object) -> str:
    gender = str(value).strip().lower()
    if gender in {"f", "female", "w", "woman"}:
        return "Woman"
    if gender in {"m", "male", "man"}:
        return "Man"
    raise ValueError(f"Unsupported gender value in {ROSTER_CSV.name}: {value!r}.")


def default_roster() -> List[Dict[str, object]]:
    table = pd.read_csv(ROSTER_CSV, encoding="utf-8-sig")
    columns = {str(column).strip().upper(): column for column in table.columns}
    required_columns = {"NAME", "GENDER", *POSITIONS}
    missing_columns = sorted(required_columns.difference(columns))
    if missing_columns:
        raise ValueError(
            f"{ROSTER_CSV.name} is missing column(s): "
            + ", ".join(missing_columns)
            + "."
        )

    roster = []
    for index, (_, row) in enumerate(table.iterrows(), start=1):
        name = str(row[columns["NAME"]]).strip()
        if not name:
            continue
        preferences = {
            position
            for position in POSITIONS
            if selected(row[columns[position]])
        }
        gender = normalized_gender(row[columns["GENDER"]])
        Player(name=name, gender=gender, preferences=frozenset(preferences))
        roster.append(
            {
                "id": f"player-{index}",
                "name": name,
                "gender": gender,
                "available": (
                    selected(row[columns["AVAILABLE"]])
                    if "AVAILABLE" in columns
                    else True
                ),
                "preferences": preferences,
            }
        )

    duplicate_names = sorted(
        {
            str(record["name"])
            for record in roster
            if sum(
                candidate["name"] == record["name"] for candidate in roster
            )
            > 1
        }
    )
    if duplicate_names:
        raise ValueError(
            f"{ROSTER_CSV.name} contains duplicate name(s): "
            + ", ".join(duplicate_names)
            + "."
        )
    return roster


def roster_for_setup(setup_key: str) -> List[Dict[str, object]]:
    if setup_key == HERE_FOR_THE_BEER_SETUP:
        return default_roster()
    if setup_key == TEAM_RED_SETUP:
        return team_red_roster()
    if setup_key == BLANK_SETUP:
        return []
    raise ValueError(f"Unsupported roster setup: {setup_key!r}.")


def initialize_setup(
    setup_key: str,
    *,
    preserve_profile: bool = False,
) -> None:
    """Atomically replace all setup-scoped session state."""

    existing_profile = st.session_state.get("league-profile")
    previous_revision = int(st.session_state.get("roster_revision", -1))
    setup_state_keys = {
        "roster",
        "next_player_id",
        "roster_revision",
        "editing_player_id",
        "player_name_errors",
        "pending_new_player",
        "pending_remove_player_id",
        "confirm_reset",
        "confirm_setup_change",
        "setup_change_widget_snapshot",
        "setup-choice",
        "pending-setup-target",
        "result",
        "result_fingerprint",
        "last_attempt_fingerprint",
        "optimization_seconds",
        "error",
        "inputs_changed",
        "default_roster_version",
    }
    if not preserve_profile:
        setup_state_keys.add("league-profile")
    for key in list(st.session_state):
        key_text = str(key)
        if (
            key in setup_state_keys
            or key_text.startswith("available-")
            or key_text.startswith("draft-")
            or key_text.startswith("edit-")
            or key_text.startswith("remove-")
            or key_text.startswith("confirm-remove-")
            or key_text.startswith("cancel-remove-")
            or key_text.startswith("select-all-")
            or key_text.startswith("clear-all-")
        ):
            del st.session_state[key]

    roster = roster_for_setup(setup_key)
    st.session_state.active_setup = setup_key
    st.session_state.roster = roster
    st.session_state.next_player_id = len(roster) + 1
    st.session_state.roster_revision = previous_revision + 1
    st.session_state.editing_player_id = None
    st.session_state.player_name_errors = {}
    st.session_state.pending_new_player = None
    st.session_state.pending_remove_player_id = None
    st.session_state.confirm_reset = False
    st.session_state.confirm_setup_change = False
    st.session_state.result = None
    st.session_state.error = None
    st.session_state.inputs_changed = False
    if setup_key == HERE_FOR_THE_BEER_SETUP:
        st.session_state.default_roster_version = DEFAULT_ROSTER_VERSION
    if not preserve_profile or existing_profile is None:
        st.session_state["league-profile"] = SETUP_DEFAULT_PROFILES[setup_key]


def begin_setup_change() -> None:
    st.session_state.setup_change_widget_snapshot = {
        key: deepcopy(value)
        for key, value in st.session_state.items()
        if key == "league-profile"
        or str(key).startswith("available-")
    }
    st.session_state.confirm_setup_change = True


def cancel_setup_change() -> None:
    for key, value in st.session_state.get(
        "setup_change_widget_snapshot", {}
    ).items():
        st.session_state[key] = value
    st.session_state.confirm_setup_change = False
    if "setup_change_widget_snapshot" in st.session_state:
        del st.session_state["setup_change_widget_snapshot"]
    if "pending-setup-target" in st.session_state:
        del st.session_state["pending-setup-target"]


def reset_active_roster() -> None:
    initialize_setup(
        st.session_state.active_setup,
        preserve_profile=True,
    )


def begin_roster_reset() -> None:
    st.session_state.confirm_reset = True


def cancel_roster_reset() -> None:
    st.session_state.confirm_reset = False


def roster_from_legacy_table(table: pd.DataFrame) -> List[Dict[str, object]]:
    """Preserve roster edits made before the mobile card interface existed."""

    roster = []
    for index, (_, row) in enumerate(table.iterrows(), start=1):
        roster.append(
            {
                "id": f"player-{index}",
                "name": str(row.get("Name", "")).strip(),
                "gender": str(row.get("Gender", "Woman")),
                "available": bool(row.get("Available", False)),
                "preferences": {
                    position for position in POSITIONS if bool(row.get(position, False))
                },
            }
        )
    return roster


def players_from_roster(roster: List[Dict[str, object]]) -> List[Player]:
    players = []
    for record in roster:
        name = str(record.get("name", "")).strip()
        if not name or not bool(record.get("available", False)):
            continue
        players.append(
            Player(
                name=name,
                gender=str(record.get("gender", "")),
                preferences=frozenset(record.get("preferences", set())),
            )
        )
    return players


def roster_fingerprint(
    roster: List[Dict[str, object]], profile_key: str = COED_RULES.key
) -> tuple:
    return (profile_key,) + tuple(
        (
            record["id"],
            str(record.get("name", "")).strip(),
            record.get("gender"),
            bool(record.get("available", False)),
            tuple(
                position
                for position in POSITIONS
                if position in record.get("preferences", set())
            ),
        )
        for record in roster
    )


def roster_problems(
    roster: List[Dict[str, object]],
) -> tuple[Dict[str, List[tuple[str, str]]], List[str]]:
    """Return per-record guidance and optimization-blocking summaries."""

    problems: Dict[str, List[tuple[str, str]]] = {}
    blocking_messages = []
    available_records = [
        record for record in roster if bool(record.get("available", False))
    ]

    for record in available_records:
        player_id = str(record["id"])
        name = str(record.get("name", "")).strip()
        if not name:
            problems.setdefault(player_id, []).append(
                (
                    "warning",
                    "This available row has no name and is excluded from the lineup.",
                )
            )
        elif not record.get("preferences"):
            message = f"{name} needs at least one positional preference."
            problems.setdefault(player_id, []).append(("error", message))
            blocking_messages.append(message)

    named_records = [
        record
        for record in available_records
        if str(record.get("name", "")).strip()
    ]
    duplicate_names = sorted(
        {
            str(record.get("name", "")).strip()
            for record in named_records
            if sum(
                str(candidate.get("name", "")).strip()
                == str(record.get("name", "")).strip()
                for candidate in named_records
            )
            > 1
        }
    )
    for duplicate_name in duplicate_names:
        message = f"Player names must be unique: {duplicate_name}."
        blocking_messages.append(message)
        for record in named_records:
            if str(record.get("name", "")).strip() == duplicate_name:
                problems.setdefault(str(record["id"]), []).append(
                    ("error", message)
                )

    return problems, blocking_messages


def save_player_edit(
    player_id: str,
    name_key: str,
    gender_key: Optional[str],
    preferences_key: str,
) -> None:
    """Atomically commit one player form before Streamlit rerenders."""

    name = str(st.session_state[name_key]).strip()
    name_errors = dict(st.session_state.get("player_name_errors", {}))
    if not name:
        name_errors[player_id] = "Player name is required."
        st.session_state.player_name_errors = name_errors
        return
    name_errors.pop(player_id, None)
    st.session_state.player_name_errors = name_errors

    profile_key = st.session_state.get("league-profile", COED_RULES.key)
    previous_fingerprint = roster_fingerprint(
        st.session_state.roster,
        profile_key,
    )
    pending_new_player = st.session_state.pending_new_player
    if (
        pending_new_player is not None
        and str(pending_new_player["id"]) == player_id
    ):
        record = pending_new_player
        st.session_state.roster.append(record)
        st.session_state.pending_new_player = None
    else:
        record = next(
            candidate
            for candidate in st.session_state.roster
            if str(candidate["id"]) == player_id
        )
    record["name"] = name
    record["gender"] = (
        st.session_state[gender_key]
        if gender_key is not None
        else "Unspecified"
    )
    record["preferences"] = set(st.session_state[preferences_key] or [])
    st.session_state.editing_player_id = None
    committed_inputs_changed = previous_fingerprint != roster_fingerprint(
        st.session_state.roster,
        profile_key,
    )
    if committed_inputs_changed:
        st.session_state.roster_revision += 1
        st.session_state.result = None
        st.session_state.error = None


def cancel_player_edit(player_id: str) -> None:
    """Discard a draft without changing the committed roster or outcome."""

    pending_new_player = st.session_state.pending_new_player
    if (
        pending_new_player is not None
        and str(pending_new_player["id"]) == player_id
    ):
        st.session_state.pending_new_player = None
    name_errors = dict(st.session_state.get("player_name_errors", {}))
    name_errors.pop(player_id, None)
    st.session_state.player_name_errors = name_errors
    st.session_state.editing_player_id = None


def availability_widget_key(player_id: str) -> str:
    return f"available-{player_id}"


def set_group_availability(
    player_ids: List[str], available: bool
) -> None:
    """Apply a bulk availability choice before the next render."""

    for player_id in player_ids:
        st.session_state[availability_widget_key(player_id)] = available


def schedule_table(result) -> pd.DataFrame:
    rows = []
    active = set(result.active_positions)
    for assignments in result.assignments:
        row = {
            position: (
                assignments.get(position, "—") if position in active else "—"
            )
            for position in POSITIONS
        }
        row["Out"] = ", ".join(
            sorted(set(result.player_innings).difference(assignments.values()))
        )
        rows.append(row)
    table = pd.DataFrame(rows, index=range(1, INNINGS + 1))
    table.index.name = "Inning"
    return table


def accessible_schedule_table(result) -> str:
    """Return one semantic seven-inning lineup table for every viewport."""

    active = set(result.active_positions)
    all_players = set(result.player_innings)
    headers = ("Inning", *POSITIONS, "Bench")
    header_cells = "".join(
        f'<th scope="col">{escape(header)}</th>' for header in headers
    )
    rows = []
    for inning_number, assignments in enumerate(result.assignments, start=1):
        assignment_cells = "".join(
            "<td>"
            + escape(
                str(
                    assignments.get(position, "—")
                    if position in active
                    else "—"
                )
            )
            + "</td>"
            for position in POSITIONS
        )
        bench = sorted(all_players.difference(assignments.values()))
        bench_text = ", ".join(bench) if bench else "None"
        rows.append(
            "<tr>"
            f'<th scope="row">{inning_number}</th>'
            f"{assignment_cells}<td>{escape(bench_text)}</td>"
            "</tr>"
        )
    return (
        '<div class="seven-inning-lineup-scroll" role="region" '
        'aria-label="Scrollable seven-inning lineup" tabindex="0">'
        '<table class="seven-inning-lineup" aria-label="Seven-inning lineup">'
        "<caption>Seven-inning lineup</caption>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def summary_table(result) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Player": name,
                "Innings": innings,
                "Positions": ", ".join(result.player_positions[name]) or "Bench",
            }
            for name, innings in sorted(
                result.player_innings.items(), key=lambda item: (-item[1], item[0])
            )
        ]
    )


st.title("🥎 Softball Fielding Optimizer")
st.caption(
    "Build a legal seven-inning lineup while balancing playing time and keeping positions consistent."
)

if not IS_NEUTRAL_DEPLOYMENT and "active_setup" not in st.session_state:
    st.session_state.active_setup = HERE_FOR_THE_BEER_SETUP

if IS_NEUTRAL_DEPLOYMENT and "active_setup" not in st.session_state:
    st.subheader("Choose a starting setup")
    st.caption(
        "Load one team’s defaults or start with an empty roster. Your choice "
        "and edits stay in this browser session."
    )
    setup_choice = st.radio(
        "Starting setup",
        options=list(SETUP_LABELS),
        format_func=lambda key: SETUP_LABELS[key],
        captions=[
            "Current roster · Co-ed rules",
            "Published roster · Open rules",
            "No players · Choose your league rules",
        ],
        index=None,
        key="setup-choice",
    )
    st.button(
        "Continue",
        type="primary",
        width="stretch",
        disabled=setup_choice is None,
        on_click=initialize_setup,
        args=(setup_choice,),
    )
    st.stop()

active_setup = st.session_state.get(
    "active_setup", HERE_FOR_THE_BEER_SETUP
)
if "roster" not in st.session_state:
    initialize_setup(active_setup)
elif isinstance(st.session_state.roster, pd.DataFrame):
    st.session_state.roster = roster_from_legacy_table(st.session_state.roster)

if (
    active_setup == HERE_FOR_THE_BEER_SETUP
    and st.session_state.get("default_roster_version")
    != DEFAULT_ROSTER_VERSION
):
    current_names = {
        str(record.get("name", "")).strip()
        for record in st.session_state.roster
    }
    if current_names == LEGACY_SAMPLE_NAMES:
        st.session_state.roster = default_roster()
    st.session_state.default_roster_version = DEFAULT_ROSTER_VERSION

if "next_player_id" not in st.session_state:
    st.session_state.next_player_id = len(st.session_state.roster) + 1
if "roster_revision" not in st.session_state:
    st.session_state.roster_revision = 0
if "editing_player_id" not in st.session_state:
    st.session_state.editing_player_id = None
if "player_name_errors" not in st.session_state:
    st.session_state.player_name_errors = {}
if "pending_new_player" not in st.session_state:
    st.session_state.pending_new_player = None
if "pending_remove_player_id" not in st.session_state:
    st.session_state.pending_remove_player_id = None
if "confirm_reset" not in st.session_state:
    st.session_state.confirm_reset = False
if "confirm_setup_change" not in st.session_state:
    st.session_state.confirm_setup_change = False

roster: List[Dict[str, object]] = st.session_state.roster
editing_player_id = st.session_state.editing_player_id
editor_open = editing_player_id is not None
pending_remove_player_id = st.session_state.pending_remove_player_id
setup_change_open = bool(st.session_state.confirm_setup_change)
confirmation_open = (
    pending_remove_player_id is not None
    or st.session_state.confirm_reset
    or setup_change_open
)
interaction_locked = editor_open or confirmation_open

if IS_NEUTRAL_DEPLOYMENT:
    st.caption(f"Current setup: **{SETUP_LABELS[active_setup]}**")
    if setup_change_open:
        setup_targets = [
            setup_key for setup_key in SETUP_LABELS if setup_key != active_setup
        ]
        target_setup = st.radio(
            "Switch to",
            options=setup_targets,
            format_func=lambda key: SETUP_LABELS[key],
            index=None,
            key="pending-setup-target",
        )
        target_label = SETUP_LABELS.get(target_setup)
        if target_label is None:
            st.info("Choose a new setup, then confirm the switch.")
        else:
            st.warning(
                f"Switch to {target_label}? This will discard all roster changes, "
                "availability selections, and the current optimized lineup in this "
                "browser session. This cannot be undone."
            )
        st.button(
            f"Keep {SETUP_LABELS[active_setup]}",
            width="stretch",
            on_click=cancel_setup_change,
        )
        st.button(
            (
                f"Discard changes and switch to {target_label}"
                if target_label is not None
                else "Discard changes and switch"
            ),
            type="primary",
            width="stretch",
            disabled=target_setup is None,
            on_click=initialize_setup,
            args=(target_setup,),
        )
        st.stop()
    st.button(
        "Change roster setup",
        width="stretch",
        disabled=editor_open
        or pending_remove_player_id is not None
        or st.session_state.confirm_reset,
        help=(
            "Finish the current roster action first."
            if editor_open
            or pending_remove_player_id is not None
            or st.session_state.confirm_reset
            else None
        ),
        on_click=begin_setup_change,
    )

profile_by_key = {profile.key: profile for profile in LEAGUE_RULES}
if active_setup == TEAM_RED_SETUP:
    st.session_state["league-profile"] = OPEN_RULES.key
    selected_profile_key = OPEN_RULES.key
    st.info(
        "League rules: **Open (no gender fielding minimums)**. Team Red stays "
        "on Open rules because this roster does not collect gender."
    )
else:
    selected_profile_key = st.selectbox(
        "League rules",
        options=list(profile_by_key),
        format_func=lambda key: profile_by_key[key].label,
        key="league-profile",
        width="stretch",
        disabled=interaction_locked,
    )
league_rules = profile_by_key[selected_profile_key]

with st.expander("Lineup rules", expanded=False):
    if league_rules == COED_RULES:
        st.markdown(
            """
            - **10 fielders:** all positions, at least 4 women.
            - **9 fielders:** no RF, at least 3 women.
            - **8 fielders:** no RF or C, at least 3 women.
            - Every inning has at least one woman in the infield and one in the outfield.
            - Preferences are required. With exactly 8 fielders, an RF preference also permits RC.
            """
        )
    else:
        st.markdown(
            """
            - **10 fielders:** all positions with at least 10 available players.
            - **9 fielders:** no RF with 9 available players.
            - **8 fielders:** no RF or C with 8 available players.
            - Gender does not affect lineup size or fielding eligibility.
            - Preferences are required. With exactly 8 fielders, an RF preference also permits RC.
            """
        )

    st.markdown(
        """
        - **Preferred positions come first.** Fallback eligibility is used only after playing-time fairness is optimized.
        - **Infield fallbacks:** SS permits 3B and 2B; 3B permits 2B. P and 1B are never inferred.
        - **Outfield fallbacks:** LC permits LF, RC, and RF; LF permits RC and RF; RC permits RF.
        - **Catcher fallback:** everyone is eligible for C.
        """
    )

st.subheader("Who’s playing?")
st.caption("Tap a name to toggle availability for this game.")

player_labels = {
    str(record["id"]): str(record.get("name", "")).strip() or "Unnamed player"
    for record in roster
}
if not roster:
    st.info(
        "Roster is empty. Add players and their preferred positions to get "
        "started. You’ll need at least 8 available players to optimize."
    )
    display_roster = []
    availability_groups = ()
elif league_rules == COED_RULES:
    display_roster = sorted(
        roster,
        key=lambda record: (
            0 if record.get("gender") == "Woman" else 1,
            str(record.get("name", "")).strip().casefold(),
        ),
    )
    availability_groups = (("Women", "Woman"), ("Men", "Man"))
else:
    display_roster = sorted(
        roster,
        key=lambda record: str(record.get("name", "")).strip().casefold(),
    )
    availability_groups = (("Players", None),)

available_id_set = set()
for group_label, gender in availability_groups:
    group = (
        display_roster
        if gender is None
        else [
            record
            for record in display_roster
            if record.get("gender") == gender
        ]
    )
    group_ids = [str(record["id"]) for record in group]
    group_key = gender or "players"
    st.markdown(f"**{group_label}**")
    availability_columns = st.columns(2)
    group_available_ids = []
    for index, record in enumerate(group):
        player_id = str(record["id"])
        availability_key = availability_widget_key(player_id)
        if availability_key not in st.session_state:
            st.session_state[availability_key] = bool(
                record.get("available", False)
            )
        with availability_columns[index % len(availability_columns)]:
            is_available = st.checkbox(
                player_labels[player_id],
                key=availability_key,
                disabled=interaction_locked,
            )
        if is_available:
            group_available_ids.append(player_id)
            available_id_set.add(player_id)

    select_column, clear_column = st.columns(2)
    with select_column:
        st.button(
            f"Select all {group_label.lower()}",
            key=f"select-all-{group_key}",
            width="stretch",
            disabled=interaction_locked,
            on_click=set_group_availability,
            args=(group_ids, True),
        )
    with clear_column:
        st.button(
            f"Clear all {group_label.lower()}",
            key=f"clear-all-{group_key}",
            width="stretch",
            disabled=interaction_locked,
            on_click=set_group_availability,
            args=(group_ids, False),
        )
    out_names = [
        player_labels[player_id]
        for player_id in group_ids
        if player_id not in group_available_ids
    ]
    st.caption(
        f"{len(group_available_ids)} available · Out: "
        + (", ".join(out_names) if out_names else "None")
    )

for record in roster:
    record["available"] = str(record["id"]) in available_id_set

named_available = [
    record
    for record in roster
    if bool(str(record.get("name", "")).strip()) and record.get("available")
]
available_women = sum(
    record.get("gender") == "Woman" for record in named_available
)
st.caption(
    f"**{len(named_available)} available players** · "
    + (
        f"**{available_women} available women**"
        if league_rules == COED_RULES
        else "**Open rules: no gender minimums**"
    )
)
st.caption(f"Active profile: **{league_rules.label}**")

readiness_error = None
try:
    planned_positions, _minimum_women = lineup_plan(
        len(named_available), available_women, league_rules
    )
    omitted_positions = [
        position for position in POSITIONS if position not in planned_positions
    ]
    omitted_text = (
        f" without {' and '.join(omitted_positions)}"
        if omitted_positions
        else ""
    )
    st.caption(
        f"**Ready for {len(planned_positions)} fielders{omitted_text}.**"
    )
except LineupError as error:
    readiness_error = str(error)
    st.warning(readiness_error)

player_problems, blocking_roster_messages = roster_problems(roster)
blank_player_count = sum(
    any(severity == "warning" for severity, _message in messages)
    for messages in player_problems.values()
)
if blank_player_count:
    noun = "row is" if blank_player_count == 1 else "rows are"
    st.warning(
        f"{blank_player_count} available unnamed {noun} excluded from optimization."
    )
if blocking_roster_messages:
    st.error("Fix roster details before optimizing: " + " ".join(
        dict.fromkeys(blocking_roster_messages)
    ))

current_fingerprint = roster_fingerprint(roster, league_rules.key)
last_attempt_fingerprint = st.session_state.get("last_attempt_fingerprint")
if (
    last_attempt_fingerprint is not None
    and last_attempt_fingerprint != current_fingerprint
):
    st.session_state.result = None
    st.session_state.error = None
    st.session_state.last_attempt_fingerprint = None
    st.session_state.inputs_changed = True

if editor_open:
    st.info("Finish editing the player by saving or canceling before optimizing.")
elif confirmation_open:
    st.info("Confirm or cancel the pending roster action before optimizing.")
optimize_disabled = (
    interaction_locked
    or readiness_error is not None
    or bool(blocking_roster_messages)
)
optimize_help = None
if editor_open:
    optimize_help = "Save or cancel the open player edit first."
elif confirmation_open:
    optimize_help = "Confirm or cancel the pending roster action first."
elif blocking_roster_messages:
    optimize_help = "Fix the identified player details before optimizing."
elif readiness_error:
    optimize_help = readiness_error
optimize_clicked = st.button(
    "Optimize seven innings",
    type="primary",
    width="stretch",
    disabled=optimize_disabled,
    help=optimize_help,
)

if optimize_clicked:
    optimization_dancer = st.empty()
    optimization_dancer.markdown(
        """
        <style>
        @keyframes softball-stick-figure-dance {
            0% { transform: translateX(-0.35rem) rotate(-7deg); }
            50% { transform: translateY(-0.3rem) rotate(7deg); }
            100% { transform: translateX(0.35rem) rotate(-4deg); }
        }
        .optimization-dancer {
            align-items: center;
            display: flex;
            gap: 0.8rem;
            margin: 0.35rem 0 0.7rem;
        }
        .optimization-dancer__figure {
            animation: softball-stick-figure-dance 0.42s steps(2, jump-none)
                infinite alternate;
            display: inline-block;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 1.1rem;
            font-weight: 700;
            line-height: 0.9;
            text-align: center;
            transform-origin: 50% 100%;
            white-space: pre;
        }
        @media (prefers-reduced-motion: reduce) {
            .optimization-dancer__figure { animation: none; }
        }
        </style>
        <div class="optimization-dancer" role="status"
             aria-label="Optimization in progress">
            <span class="optimization-dancer__figure" aria-hidden="true">\\o/<br> |<br>/ ╲</span>
            <span>Tiny coach is dancing while the lineup cooks.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    optimization_status = st.status(
        "Preparing the optimization…", expanded=False
    )

    def update_optimization_status(message: str) -> None:
        optimization_status.update(label=message, state="running")

    try:
        available_players = players_from_roster(roster)
        optimization_started = perf_counter()
        result = optimize_game(
            available_players,
            profile=league_rules,
            progress_callback=update_optimization_status,
        )
        optimization_seconds = perf_counter() - optimization_started
        optimization_status.update(
            label="Lineup optimization complete.", state="complete"
        )
        optimization_dancer.empty()
        st.session_state.result = result
        st.session_state.result_fingerprint = current_fingerprint
        st.session_state.last_attempt_fingerprint = current_fingerprint
        st.session_state.optimization_seconds = optimization_seconds
        st.session_state.error = None
        st.session_state.inputs_changed = False
    except (LineupError, ValueError) as error:
        optimization_status.update(
            label="Lineup optimization stopped.", state="error"
        )
        optimization_dancer.empty()
        st.session_state.result = None
        st.session_state.error = str(error)
        st.session_state.last_attempt_fingerprint = current_fingerprint
        st.session_state.inputs_changed = False

if st.session_state.get("inputs_changed"):
    st.info("Inputs changed — optimize again.")

if st.session_state.get("error"):
    st.error(st.session_state.error)

result = st.session_state.get("result")
if result:
    st.divider()
    st.subheader("Optimized lineup")
    elapsed_seconds = st.session_state.get("optimization_seconds")
    timing_text = (
        f" · Optimized in {elapsed_seconds:.2f} seconds"
        if elapsed_seconds is not None
        else ""
    )
    st.caption(
        f"{league_rules.label} profile · "
        f"{result.lineup_size} fielders per inning · "
        f"Solver status: {result.solver_status.title()}"
        f"{timing_text}"
    )

    lineup = schedule_table(result)
    st.markdown(accessible_schedule_table(result), unsafe_allow_html=True)

    st.download_button(
        "Download full lineup CSV",
        lineup.to_csv().encode("utf-8"),
        file_name="softball_lineup.csv",
        mime="text/csv",
        width="stretch",
        disabled=interaction_locked,
    )

    st.subheader("Playing time")
    st.dataframe(summary_table(result), hide_index=True, width="stretch")

st.divider()
st.subheader("Player details & preferences")
if active_setup == TEAM_RED_SETUP:
    st.caption(
        "Open a player card to edit their name or preferred positions. "
        "Gender is not collected for this Open-rules roster. The optimizer "
        "may use hierarchy-derived fallback positions only after playing-time fairness."
    )
else:
    st.caption(
        "Open a player card to edit their name, gender, or preferred positions. "
        "The optimizer may use hierarchy-derived fallback positions only after "
        "playing-time fairness."
    )

if st.button(
    "＋ Add first player" if not roster else "＋ Add player",
    width="stretch",
    disabled=interaction_locked,
    help=(
        "Finish the open edit or confirmation first."
        if interaction_locked
        else None
    ),
):
    new_id = st.session_state.next_player_id
    st.session_state.next_player_id += 1
    new_player_id = f"player-{new_id}"
    st.session_state.pending_new_player = {
        "id": new_player_id,
        "name": "",
        "gender": (
            "Unspecified" if active_setup == TEAM_RED_SETUP else "Woman"
        ),
        "available": True,
        "preferences": set(),
    }
    st.session_state.player_name_errors.pop(new_player_id, None)
    st.session_state.editing_player_id = new_player_id
    st.rerun()

if st.session_state.confirm_reset:
    reset_descriptions = {
        HERE_FOR_THE_BEER_SETUP: "the Here For The Beer CSV defaults",
        TEAM_RED_SETUP: "the published Team Red defaults",
        BLANK_SETUP: "a blank roster",
    }
    if IS_NEUTRAL_DEPLOYMENT:
        st.warning(
            "Replace all current session edits with "
            f"{reset_descriptions[active_setup]}? This discards the current "
            "optimized lineup."
        )
        st.button(
            "Keep current roster",
            width="stretch",
            on_click=cancel_roster_reset,
        )
        st.button(
            "Clear roster" if active_setup == BLANK_SETUP else "Reset roster",
            type="primary",
            width="stretch",
            on_click=reset_active_roster,
        )
    else:
        st.warning("Replace all current session edits with the CSV defaults?")
        confirm_column, cancel_column = st.columns(2)
        with confirm_column:
            st.button(
                "Confirm reset",
                type="primary",
                width="stretch",
                on_click=reset_active_roster,
            )
        with cancel_column:
            st.button(
                "Cancel reset",
                width="stretch",
                on_click=cancel_roster_reset,
            )
else:
    if not IS_NEUTRAL_DEPLOYMENT:
        reset_label = "Reset to CSV defaults"
    else:
        reset_label = {
            HERE_FOR_THE_BEER_SETUP: "Reset Here For The Beer roster",
            TEAM_RED_SETUP: "Reset Team Red roster",
            BLANK_SETUP: "Clear roster and start over",
        }[active_setup]
    st.button(
        reset_label,
        width="stretch",
        disabled=interaction_locked,
        help=(
            "Finish the open edit or removal confirmation first."
            if interaction_locked
            else None
        ),
        on_click=begin_roster_reset,
    )

details_roster = list(display_roster)
if st.session_state.pending_new_player is not None:
    details_roster.append(st.session_state.pending_new_player)

for index, record in enumerate(details_roster):
    player_id = str(record["id"])
    display_name = str(record.get("name", "")).strip() or f"Player {index + 1}"
    preference_summary = ", ".join(
        position
        for position in POSITIONS
        if position in record.get("preferences", set())
    ) or "No positions yet"
    availability_label = "Available" if record.get("available") else "Out"
    problem_marker = "⚠ " if player_id in player_problems else ""
    if active_setup == TEAM_RED_SETUP:
        card_label = (
            f"{problem_marker}{display_name} · {availability_label} · "
            f"{preference_summary}"
        )
    else:
        card_label = (
            f"{problem_marker}{display_name} · {record.get('gender')} · "
            f"{availability_label} · {preference_summary}"
        )

    is_editing = editing_player_id == player_id
    is_confirming_remove = pending_remove_player_id == player_id
    with st.expander(
        card_label, expanded=is_editing or is_confirming_remove
    ):
        for severity, message in player_problems.get(player_id, []):
            if severity == "error":
                st.error(message)
            else:
                st.warning(message)
        if is_editing:
            st.caption("Draft changes are applied only when you save.")
            name_key = f"draft-name-{player_id}"
            gender_key = (
                None
                if active_setup == TEAM_RED_SETUP
                else f"draft-gender-{player_id}"
            )
            preferences_key = f"draft-preferences-{player_id}"
            with st.form(f"edit-player-{player_id}", clear_on_submit=False):
                st.text_input(
                    "Player name",
                    value=str(record.get("name", "")),
                    key=name_key,
                )
                name_error = st.session_state.player_name_errors.get(player_id)
                if name_error:
                    st.error(name_error)
                if gender_key is not None:
                    st.selectbox(
                        "Gender",
                        options=["Woman", "Man"],
                        index=0 if record.get("gender") == "Woman" else 1,
                        key=gender_key,
                        width="stretch",
                    )
                st.pills(
                    "Position preferences",
                    options=list(POSITIONS),
                    default=[
                        position
                        for position in POSITIONS
                        if position in record.get("preferences", set())
                    ],
                    selection_mode="multi",
                    key=preferences_key,
                    width="stretch",
                )
                save_column, cancel_column = st.columns(2)
                with save_column:
                    st.form_submit_button(
                        "Save changes",
                        type="primary",
                        width="stretch",
                        on_click=save_player_edit,
                        args=(
                            player_id,
                            name_key,
                            gender_key,
                            preferences_key,
                        ),
                    )
                with cancel_column:
                    st.form_submit_button(
                        "Cancel",
                        width="stretch",
                        on_click=cancel_player_edit,
                        args=(player_id,),
                    )
        elif is_confirming_remove:
            st.warning(f"Remove {display_name} from this session roster?")
            confirm_column, cancel_column = st.columns(2)
            with confirm_column:
                confirm_remove_clicked = st.button(
                    f"Confirm remove {display_name}",
                    key=f"confirm-remove-{player_id}",
                    type="primary",
                    width="stretch",
                )
            with cancel_column:
                cancel_remove_clicked = st.button(
                    "Cancel removal",
                    key=f"cancel-remove-{player_id}",
                    width="stretch",
                )
            if confirm_remove_clicked:
                st.session_state.roster = [
                    candidate
                    for candidate in roster
                    if str(candidate["id"]) != player_id
                ]
                st.session_state.pending_remove_player_id = None
                st.session_state.roster_revision += 1
                st.session_state.result = None
                st.session_state.error = None
                st.rerun()
            if cancel_remove_clicked:
                st.session_state.pending_remove_player_id = None
                st.rerun()
        else:
            if st.button(
                f"Edit {display_name}",
                key=f"edit-{player_id}",
                width="stretch",
                disabled=interaction_locked,
            ):
                st.session_state.player_name_errors.pop(player_id, None)
                st.session_state.editing_player_id = player_id
                st.rerun()
            if st.button(
                f"Remove {display_name}",
                key=f"remove-{player_id}",
                width="stretch",
                disabled=interaction_locked,
            ):
                st.session_state.pending_remove_player_id = player_id
                st.rerun()

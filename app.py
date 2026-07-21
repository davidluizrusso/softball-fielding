"""Streamlit interface for the softball fielding optimizer."""

from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from softball_fielding import LineupError, Player, optimize_game
from softball_fielding.models import INNINGS, POSITIONS


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
        [data-testid="stExpander"] summary {
            min-height: 3rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


ROSTER_CSV = Path(__file__).with_name("roster_positions.csv")
DEFAULT_ROSTER_VERSION = 1
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


def roster_fingerprint(roster: List[Dict[str, object]]) -> tuple:
    return tuple(
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


def schedule_table(result) -> pd.DataFrame:
    rows = []
    active = set(result.active_positions)
    for assignments in result.assignments:
        rows.append(
            {
                position: (
                    assignments.get(position, "—") if position in active else "—"
                )
                for position in POSITIONS
            }
        )
    table = pd.DataFrame(rows, index=range(1, INNINGS + 1))
    table.index.name = "Inning"
    return table


def inning_table(result, inning_number: int) -> pd.DataFrame:
    assignments = result.assignments[inning_number - 1]
    active = set(result.active_positions)
    return pd.DataFrame(
        [
            {
                "Position": position,
                "Player": (
                    assignments.get(position, "—") if position in active else "—"
                ),
            }
            for position in POSITIONS
        ]
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


if "roster" not in st.session_state:
    st.session_state.roster = default_roster()
elif isinstance(st.session_state.roster, pd.DataFrame):
    st.session_state.roster = roster_from_legacy_table(st.session_state.roster)

if st.session_state.get("default_roster_version") != DEFAULT_ROSTER_VERSION:
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

roster: List[Dict[str, object]] = st.session_state.roster

st.title("🥎 Softball Fielding Optimizer")
st.caption(
    "Build a legal seven-inning lineup while balancing playing time and keeping positions consistent."
)

with st.expander("Lineup rules", expanded=False):
    st.markdown(
        """
        - **10 fielders:** all positions, at least 4 women.
        - **9 fielders:** no RF, at least 3 women.
        - **8 fielders:** no RF or C, at least 3 women.
        - Every inning has at least one woman in the infield and one in the outfield.
        - Preferences are required. With 8 or 9 fielders, an RF preference also permits RC.
        """
    )

st.subheader("Who’s playing?")
st.caption("Tap a name to toggle availability for this game.")

player_ids = [str(record["id"]) for record in roster]
player_labels = {
    str(record["id"]): str(record.get("name", "")).strip() or "Unnamed player"
    for record in roster
}
available_ids = st.pills(
    "Available players",
    options=player_ids,
    default=[
        str(record["id"])
        for record in roster
        if bool(record.get("available", False))
    ],
    format_func=lambda player_id: player_labels[player_id],
    selection_mode="multi",
    key=f"availability-{st.session_state.roster_revision}",
    label_visibility="collapsed",
    width="stretch",
) or []
available_id_set = set(available_ids)
for record in roster:
    record["available"] = str(record["id"]) in available_id_set

availability_status = st.empty()
optimize_clicked = st.button(
    "Optimize seven innings", type="primary", width="stretch"
)

st.divider()
st.subheader("Player details & preferences")
st.caption("Open a player card to edit their name, gender, or positions.")

if st.button("＋ Add player", width="stretch"):
    new_id = st.session_state.next_player_id
    st.session_state.next_player_id += 1
    roster.append(
        {
            "id": f"player-{new_id}",
            "name": "",
            "gender": "Woman",
            "available": True,
            "preferences": set(),
        }
    )
    st.session_state.roster_revision += 1
    st.session_state.result = None
    st.session_state.error = None
    st.rerun()

if st.button("Reset to CSV defaults", width="stretch"):
    st.session_state.roster = default_roster()
    st.session_state.next_player_id = len(st.session_state.roster) + 1
    st.session_state.roster_revision += 1
    st.session_state.result = None
    st.session_state.error = None
    st.rerun()

for index, record in enumerate(list(roster)):
    player_id = str(record["id"])
    display_name = str(record.get("name", "")).strip() or f"Player {index + 1}"
    preference_summary = ", ".join(
        position
        for position in POSITIONS
        if position in record.get("preferences", set())
    ) or "No positions yet"
    availability_label = "Available" if record.get("available") else "Out"
    card_label = (
        f"{display_name} · {record.get('gender')} · {availability_label} · "
        f"{preference_summary}"
    )

    with st.expander(card_label, expanded=not bool(str(record.get("name", "")).strip())):
        record["name"] = st.text_input(
            "Player name",
            value=str(record.get("name", "")),
            key=f"name-{player_id}",
        )
        record["gender"] = st.selectbox(
            "Gender",
            options=["Woman", "Man"],
            index=0 if record.get("gender") == "Woman" else 1,
            key=f"gender-{player_id}",
            width="stretch",
        )
        record["preferences"] = set(
            st.pills(
                "Position preferences",
                options=list(POSITIONS),
                default=[
                    position
                    for position in POSITIONS
                    if position in record.get("preferences", set())
                ],
                selection_mode="multi",
                key=f"preferences-{player_id}",
                width="stretch",
            )
            or []
        )
        if st.button(
            f"Remove {display_name}",
            key=f"remove-{player_id}",
            width="stretch",
        ):
            st.session_state.roster = [
                candidate
                for candidate in roster
                if str(candidate["id"]) != player_id
            ]
            st.session_state.roster_revision += 1
            st.session_state.result = None
            st.session_state.error = None
            st.rerun()

named_available = [
    record
    for record in roster
    if bool(str(record.get("name", "")).strip()) and record.get("available")
]
available_women = sum(
    record.get("gender") == "Woman" for record in named_available
)
availability_status.caption(
    f"**{len(named_available)} available players** · "
    f"**{available_women} available women**"
)

current_fingerprint = roster_fingerprint(roster)
if (
    st.session_state.get("result")
    and st.session_state.get("result_fingerprint") != current_fingerprint
):
    st.session_state.result = None
    st.session_state.error = None

if optimize_clicked:
    try:
        available_players = players_from_roster(roster)
        with st.spinner("Optimizing seven innings…"):
            result = optimize_game(available_players)
        st.session_state.result = result
        st.session_state.result_fingerprint = current_fingerprint
        st.session_state.error = None
    except (LineupError, ValueError) as error:
        st.session_state.result = None
        st.session_state.error = str(error)

if st.session_state.get("error"):
    st.error(st.session_state.error)

result = st.session_state.get("result")
if result:
    st.divider()
    st.subheader("Optimized lineup")
    st.caption(
        f"{result.lineup_size} fielders per inning · "
        f"Solver status: {result.solver_status.title()}"
    )

    view_mode = st.selectbox(
        "Lineup view",
        options=["Full matrix", "By inning"],
        index=0,
        width="stretch",
    )
    lineup = schedule_table(result)

    if view_mode == "Full matrix":
        st.dataframe(lineup, width="stretch")
    else:
        inning_number = st.selectbox(
            "Inning",
            options=list(range(1, INNINGS + 1)),
            index=0,
            width="stretch",
        )
        st.dataframe(
            inning_table(result, int(inning_number)),
            hide_index=True,
            width="stretch",
        )
        assigned_names = set(result.assignments[int(inning_number) - 1].values())
        bench = sorted(set(result.player_innings).difference(assigned_names))
        st.caption("**Bench:** " + (", ".join(bench) if bench else "None"))

    st.download_button(
        "Download full lineup CSV",
        lineup.to_csv().encode("utf-8"),
        file_name="softball_lineup.csv",
        mime="text/csv",
        width="stretch",
    )

    st.subheader("Playing time")
    st.dataframe(summary_table(result), hide_index=True, width="stretch")

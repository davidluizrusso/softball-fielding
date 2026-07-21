"""Streamlit interface for the softball fielding optimizer."""

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
    .block-container {max-width: 1200px; padding-top: 2rem;}
    [data-testid="stMetricValue"] {font-size: 1.65rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def sample_roster() -> pd.DataFrame:
    rows = [
        ("Alex", "Woman", True, {"P", "1B", "2B"}),
        ("Blair", "Woman", True, {"C", "2B", "SS"}),
        ("Casey", "Woman", True, {"LF", "LC", "RC", "RF"}),
        ("Drew", "Woman", True, {"3B", "SS", "LF"}),
        ("Evan", "Man", True, {"P", "1B"}),
        ("Finley", "Man", True, {"C", "2B"}),
        ("Gray", "Man", True, {"3B", "SS"}),
        ("Hayden", "Man", True, {"LF", "LC"}),
        ("Jamie", "Man", True, {"LC", "RC", "RF"}),
        ("Kai", "Man", True, {"1B", "RF"}),
        ("Logan", "Man", True, {"2B", "LF"}),
        ("Morgan", "Man", True, {"C", "3B", "RC"}),
    ]
    records: List[Dict[str, object]] = []
    for name, gender, available, preferences in rows:
        record: Dict[str, object] = {
            "Name": name,
            "Gender": gender,
            "Available": available,
        }
        record.update({position: position in preferences for position in POSITIONS})
        records.append(record)
    return pd.DataFrame(records)


def players_from_table(table: pd.DataFrame) -> List[Player]:
    players = []
    for _, row in table.iterrows():
        name = str(row.get("Name", "")).strip()
        if not name or not bool(row.get("Available", False)):
            continue
        gender = str(row.get("Gender", ""))
        preferences = frozenset(
            position for position in POSITIONS if bool(row.get(position, False))
        )
        players.append(Player(name=name, gender=gender, preferences=preferences))
    return players


def schedule_table(result) -> pd.DataFrame:
    rows = []
    active = set(result.active_positions)
    for inning, assignments in enumerate(result.assignments, start=1):
        row = {position: assignments.get(position, "—") if position in active else "—" for position in POSITIONS}
        rows.append(row)
    table = pd.DataFrame(rows, index=range(1, INNINGS + 1))
    table.index.name = "Inning"
    return table


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

st.subheader("Game roster")
st.write("Add players, mark who is available, and select every position each player can play.")

if "roster" not in st.session_state:
    st.session_state.roster = sample_roster()

column_config = {
    "Name": st.column_config.TextColumn("Name", required=True, width="medium"),
    "Gender": st.column_config.SelectboxColumn(
        "Gender", options=["Woman", "Man"], required=True, width="small"
    ),
    "Available": st.column_config.CheckboxColumn("Available", default=True),
}
column_config.update(
    {
        position: st.column_config.CheckboxColumn(position, default=False, width="small")
        for position in POSITIONS
    }
)

previous_roster = st.session_state.roster
edited_roster = st.data_editor(
    st.session_state.roster,
    column_config=column_config,
    column_order=["Name", "Gender", "Available", *POSITIONS],
    hide_index=True,
    num_rows="dynamic",
    width="stretch",
    key="roster_editor",
)
if not edited_roster.equals(previous_roster):
    st.session_state.result = None
    st.session_state.error = None
st.session_state.roster = edited_roster

available_count = int(edited_roster["Available"].fillna(False).sum())
available_women = int(
    (
        edited_roster["Available"].fillna(False)
        & edited_roster["Gender"].eq("Woman")
    ).sum()
)

metric_one, metric_two, action = st.columns([1, 1, 2])
metric_one.metric("Available players", available_count)
metric_two.metric("Available women", available_women)

with action:
    st.write("")
    st.write("")
    optimize_clicked = st.button(
        "Optimize lineup", type="primary", width="stretch"
    )

if optimize_clicked:
    try:
        available_players = players_from_table(edited_roster)
        with st.spinner("Optimizing seven innings…"):
            result = optimize_game(available_players)
        st.session_state.result = result
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
    status_col, size_col = st.columns(2)
    status_col.metric("Solver status", result.solver_status.title())
    size_col.metric("Fielders per inning", result.lineup_size)

    lineup = schedule_table(result)
    st.dataframe(lineup, width="stretch")
    st.download_button(
        "Download lineup CSV",
        lineup.to_csv().encode("utf-8"),
        file_name="softball_lineup.csv",
        mime="text/csv",
    )

    st.subheader("Playing time")
    st.dataframe(summary_table(result), hide_index=True, width="stretch")

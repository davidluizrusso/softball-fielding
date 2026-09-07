from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import softball_fielding
from softball_fielding import LineupError
from softball_fielding.models import (
    COED_RULES,
    INNINGS,
    OPEN_RULES,
    POSITIONS,
    ScheduleResult,
)

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def fake_result(players, *, profile=COED_RULES):
    active_positions, _minimum_women = softball_fielding.lineup_plan(
        len(players),
        sum(candidate.is_woman for candidate in players),
        profile,
    )

    fielders = players[: len(active_positions)]
    assignments = tuple(
        {
            position: candidate.name
            for position, candidate in zip(active_positions, fielders)
        }
        for _ in range(INNINGS)
    )
    positions_by_name = {
        candidate.name: (position,)
        for position, candidate in zip(active_positions, fielders)
    }
    assigned_names = {candidate.name for candidate in fielders}
    return ScheduleResult(
        assignments=assignments,
        active_positions=active_positions,
        player_innings={
            candidate.name: 7 if candidate.name in assigned_names else 0
            for candidate in players
        },
        player_positions={
            candidate.name: positions_by_name.get(candidate.name, tuple())
            for candidate in players
        },
        solver_status="OPTIMAL",
    )


def element_with_key(elements, key):
    return next(element for element in elements if element.key == key)


def element_with_key_prefix(elements, prefix):
    return next(
        element
        for element in elements
        if element.key is not None and element.key.startswith(prefix)
    )


def availability_checkbox(app, player_id):
    return element_with_key(app.checkbox, f"available-{player_id}")


def set_available_player_ids(app, player_ids):
    selected = set(player_ids)
    for record in app.session_state["roster"]:
        availability_checkbox(app, record["id"]).set_value(
            record["id"] in selected
        )
    app.run(timeout=20)


def test_app_loads_csv_defaults_and_optimizes(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "🥎 Softball Fielding Optimizer"
    assert element_with_key(app.selectbox, "league-profile").value == "coed"
    roster = app.session_state["roster"]
    assert len(roster) == 15
    assert sum(record["gender"] == "Woman" for record in roster) == 5
    assert "SS" in next(
        record["preferences"] for record in roster if record["name"] == "Kevin"
    )
    women_labels = [
        availability_checkbox(app, record["id"]).label
        for record in roster
        if record["gender"] == "Woman"
    ]
    men_labels = [
        availability_checkbox(app, record["id"]).label
        for record in roster
        if record["gender"] == "Man"
    ]
    assert sorted(women_labels) == sorted(
        record["name"] for record in roster if record["gender"] == "Woman"
    )
    assert sorted(men_labels) == sorted(
        record["name"] for record in roster if record["gender"] == "Man"
    )

    optimize_button = next(
        button for button in app.button if button.label == "Optimize seven innings"
    )
    optimize_button.click().run(timeout=20)

    assert not app.exception
    assert not app.error
    optimizer.assert_called_once()
    optimized_players = optimizer.call_args.args[0]
    assert len(optimized_players) == 15
    assert sum(candidate.is_woman for candidate in optimized_players) == 5
    assert optimizer.call_args.kwargs == {"profile": COED_RULES}
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert any(
        "Optimized in" in caption.value and "seconds" in caption.value
        for caption in app.caption
    )
    assert any(
        selectbox.label == "Lineup view" and selectbox.value == "By inning"
        for selectbox in app.selectbox
    )
    inning_selector = next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Inning"
    )
    inning_selector.set_value(7).run(timeout=20)
    semantic_lineup = next(
        markdown.value
        for markdown in app.markdown
        if '<table class="accessible-lineup-table"' in markdown.value
    )
    assert "Inning 7 assignments" in semantic_lineup
    assert semantic_lineup.count("<tr>") == len(POSITIONS) + 1
    assert semantic_lineup.count("<td>") == len(POSITIONS) * 2
    assert any(
        caption.value.startswith("**Bench:**") for caption in app.caption
    )

    view_selector = next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Lineup view"
    )
    view_selector.set_value("Full matrix").run(timeout=20)
    assert list(app.dataframe[0].value.columns) == [
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
        "Out",
    ]
    assert len(app.dataframe[0].value) == 7
    assert all(
        len(players_out.split(", ")) == 5
        for players_out in app.dataframe[0].value["Out"]
    )
    assert any(
        button.label == "Download full lineup CSV"
        for button in app.get("download_button")
    )

    first_woman_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    )
    availability_checkbox(app, first_woman_id).set_value(False).run(timeout=20)

    assert not any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert not app.dataframe
    assert any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )


def test_app_surfaces_optimizer_errors_without_showing_a_stale_lineup(monkeypatch):
    message = "No legal schedule can satisfy the selected availability."
    optimizer = Mock(side_effect=LineupError(message))
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)

    optimizer.assert_called_once()
    assert not app.exception
    assert [error.value for error in app.error] == [message]
    assert not any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert not app.dataframe

    first_woman_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    )
    availability_checkbox(app, first_woman_id).set_value(False).run(timeout=20)

    assert not app.error
    assert any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )


def test_add_edit_remove_and_reset_roster(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    original_roster = [
        {
            **record,
            "preferences": set(record["preferences"]),
        }
        for record in app.session_state["roster"]
    ]

    next(button for button in app.button if button.label == "＋ Add player").click().run(
        timeout=20
    )

    added = app.session_state["pending_new_player"]
    assert added == {
        "id": "player-16",
        "name": "",
        "gender": "Woman",
        "available": True,
        "preferences": set(),
    }

    element_with_key_prefix(
        app.text_input, "draft-name-player-16"
    ).set_value("Jordan")
    element_with_key_prefix(
        app.selectbox, "draft-gender-player-16"
    ).set_value("Man")
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-16"
    ).set_value(["P", "RF"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    added = next(
        record for record in app.session_state["roster"] if record["id"] == "player-16"
    )
    assert added["name"] == "Jordan"
    assert added["gender"] == "Man"
    assert added["available"] is True
    assert added["preferences"] == {"P", "RF"}

    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )

    next(button for button in app.button if button.label == "Edit Jordan").click().run(
        timeout=20
    )
    element_with_key_prefix(
        app.text_input, "draft-name-player-16"
    ).set_value("Jordan S")
    element_with_key_prefix(
        app.selectbox, "draft-gender-player-16"
    ).set_value("Woman")
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-16"
    ).set_value(["C", "LF"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    edited = next(
        record for record in app.session_state["roster"] if record["id"] == "player-16"
    )
    assert edited["name"] == "Jordan S"
    assert edited["gender"] == "Woman"
    assert edited["available"] is True
    assert edited["preferences"] == {"C", "LF"}
    assert not any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )

    next(
        button for button in app.button if button.label == "Remove Jordan S"
    ).click().run(timeout=20)
    assert any(
        record["id"] == "player-16" for record in app.session_state["roster"]
    )
    next(
        button
        for button in app.button
        if button.label == "Confirm remove Jordan S"
    ).click().run(timeout=20)
    assert len(app.session_state["roster"]) == len(original_roster)
    assert not any(
        record["id"] == "player-16" for record in app.session_state["roster"]
    )

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value(
        "Changed Kevin"
    )
    element_with_key_prefix(app.selectbox, "draft-gender-player-9").set_value(
        "Woman"
    )
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-9"
    ).set_value(["C"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert app.session_state["result"] is not None

    next(
        button for button in app.button if button.label == "Reset to CSV defaults"
    ).click().run(timeout=20)
    assert app.session_state["roster"] != original_roster
    next(
        button for button in app.button if button.label == "Confirm reset"
    ).click().run(timeout=20)

    assert app.session_state["roster"] == original_roster
    assert app.session_state["result"] is None
    assert not any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )


def test_player_edit_cancel_is_atomic_and_blocks_other_actions(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    original_kevin = {
        **next(
            record
            for record in app.session_state["roster"]
            if record["id"] == "player-9"
        ),
        "preferences": set(
            next(
                record
                for record in app.session_state["roster"]
                if record["id"] == "player-9"
            )["preferences"]
        ),
    }
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_result = app.session_state["result"]

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled
    assert next(
        button for button in app.button if button.label == "＋ Add player"
    ).disabled
    assert next(
        button for button in app.button if button.label == "Reset to CSV defaults"
    ).disabled
    assert element_with_key(app.selectbox, "league-profile").disabled

    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value(
        "Discarded Kevin"
    )
    element_with_key_prefix(app.selectbox, "draft-gender-player-9").set_value(
        "Woman"
    )
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-9"
    ).set_value(["C"])
    next(button for button in app.button if button.label == "Cancel").click().run(
        timeout=20
    )

    assert next(
        record
        for record in app.session_state["roster"]
        if record["id"] == "player-9"
    ) == original_kevin
    assert app.session_state["result"] == original_result

    next(button for button in app.button if button.label == "＋ Add player").click().run(
        timeout=20
    )
    assert app.session_state["pending_new_player"]["id"] == "player-16"
    assert not any(
        record["id"] == "player-16" for record in app.session_state["roster"]
    )
    assert app.session_state["result"] == original_result
    next(button for button in app.button if button.label == "Cancel").click().run(
        timeout=20
    )
    assert app.session_state["pending_new_player"] is None
    assert not any(
        record["id"] == "player-16"
        for record in app.session_state["roster"]
    )
    assert app.session_state["result"] == original_result


def test_noop_player_save_preserves_current_result(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_result = app.session_state["result"]
    original_revision = app.session_state["roster_revision"]
    original_attempt_fingerprint = app.session_state["last_attempt_fingerprint"]
    original_result_fingerprint = app.session_state["result_fingerprint"]
    original_optimization_seconds = app.session_state["optimization_seconds"]
    next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Inning"
    ).set_value(7).run(timeout=20)

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value(
        " Kevin "
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert app.session_state["result"] == original_result
    assert app.session_state["roster_revision"] == original_revision
    assert next(
        record
        for record in app.session_state["roster"]
        if record["id"] == "player-9"
    )["name"] == "Kevin"
    assert (
        app.session_state["last_attempt_fingerprint"]
        == original_attempt_fingerprint
    )
    assert app.session_state["result_fingerprint"] == original_result_fingerprint
    assert app.session_state["optimization_seconds"] == original_optimization_seconds
    optimizer.assert_called_once()
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Lineup view"
    ).value == "By inning"
    assert next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Inning"
    ).value == 7
    assert any(
        button.label == "Download full lineup CSV"
        for button in app.get("download_button")
    )
    assert not any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )


def test_noop_player_save_preserves_current_error(monkeypatch):
    message = "No legal schedule can satisfy the selected availability."
    optimizer = Mock(side_effect=LineupError(message))
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_revision = app.session_state["roster_revision"]

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert [error.value for error in app.error] == [message]
    assert app.session_state["roster_revision"] == original_revision
    assert app.session_state["result"] is None
    assert not app.get("download_button")
    optimizer.assert_called_once()
    assert not any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )


def test_semantic_lineup_escapes_player_names(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    dung_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["name"] == "Dung"
    )
    next(button for button in app.button if button.label == "Edit Dung").click().run(
        timeout=20
    )
    hostile_name = "<img src=x onerror=alert(1)>"
    element_with_key_prefix(app.text_input, f"draft-name-{dung_id}").set_value(
        hostile_name
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)

    semantic_lineup = next(
        markdown.value
        for markdown in app.markdown
        if '<table class="accessible-lineup-table"' in markdown.value
    )
    assert hostile_name not in semantic_lineup
    assert "&lt;img src=x onerror=alert(1)&gt;" in semantic_lineup


def test_destructive_action_cancellation_preserves_roster(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    original_roster = [
        {**record, "preferences": set(record["preferences"])}
        for record in app.session_state["roster"]
    ]
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_result = app.session_state["result"]

    next(button for button in app.button if button.label == "Remove Kevin").click().run(
        timeout=20
    )
    assert app.session_state["roster"] == original_roster
    assert app.session_state["result"] == original_result
    next(
        button for button in app.button if button.label == "Cancel removal"
    ).click().run(timeout=20)
    assert app.session_state["roster"] == original_roster
    assert app.session_state["result"] == original_result

    first_woman_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    )
    availability_checkbox(app, first_woman_id).set_value(False).run(timeout=20)
    changed_roster = [
        {**record, "preferences": set(record["preferences"])}
        for record in app.session_state["roster"]
    ]
    next(
        button for button in app.button if button.label == "Reset to CSV defaults"
    ).click().run(timeout=20)
    assert app.session_state["roster"] == changed_roster
    next(button for button in app.button if button.label == "Cancel reset").click().run(
        timeout=20
    )
    assert app.session_state["roster"] == changed_roster


def test_count_readiness_disables_known_impossible_lineups(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    women = [
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    ]
    men = [
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Man"
    ]
    set_available_player_ids(app, [*women[:2], *men[:5]])

    warning_text = " ".join(warning.value for warning in app.warning)
    assert "At least 8 available players" in warning_text
    assert "At least 3 available women" in warning_text
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled
    optimizer.assert_not_called()


def test_invalid_available_player_is_identified_before_optimization(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-9"
    ).set_value([])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert any(
        "Kevin needs at least one positional preference" in error.value
        for error in app.error
    )
    assert any(
        expander.label.startswith("⚠ Kevin ·") for expander in app.expander
    )
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled
    optimizer.assert_not_called()

    availability_checkbox(app, "player-9").set_value(False).run(timeout=20)
    assert not app.error
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled


def test_available_unnamed_player_warns_but_does_not_block(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    next(button for button in app.button if button.label == "＋ Add player").click().run(
        timeout=20
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert any(
        "available unnamed row is excluded" in warning.value
        for warning in app.warning
    )
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled


def test_duplicate_available_names_block_before_optimization(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    andrew_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["name"] == "Andrew"
    )

    next(button for button in app.button if button.label == "Edit Andrew").click().run(
        timeout=20
    )
    element_with_key_prefix(app.text_input, f"draft-name-{andrew_id}").set_value(
        "Kevin"
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert any(
        "Player names must be unique: Kevin" in error.value for error in app.error
    )
    assert sum(
        expander.label.startswith("⚠ Kevin ·") for expander in app.expander
    ) == 2
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled
    optimizer.assert_not_called()

    availability_checkbox(app, andrew_id).set_value(False).run(timeout=20)
    assert not app.error
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled


def test_league_profile_is_explicit_invalidates_results_and_survives_reset(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    assert element_with_key(app.selectbox, "league-profile").value == "coed"
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert optimizer.call_args.kwargs == {"profile": COED_RULES}
    assert app.session_state["result"] is not None

    element_with_key(app.selectbox, "league-profile").set_value("open").run(
        timeout=20
    )
    assert app.session_state["result"] is None
    assert any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )
    assert any(
        "Active profile: **Open" in caption.value for caption in app.caption
    )

    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert optimizer.call_args.kwargs == {"profile": OPEN_RULES}
    assert app.session_state["result"].lineup_size == 10

    next(
        button for button in app.button if button.label == "Reset to CSV defaults"
    ).click().run(timeout=20)
    next(button for button in app.button if button.label == "Confirm reset").click().run(
        timeout=20
    )
    assert element_with_key(app.selectbox, "league-profile").value == "open"


def test_open_profile_does_not_require_available_women(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    next(
        button for button in app.button if button.label == "Clear all women"
    ).click().run(timeout=20)
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled

    element_with_key(app.selectbox, "league-profile").set_value("open").run(
        timeout=20
    )
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled
    assert not any("available women are required" in item.value for item in app.warning)
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)

    optimized_players = optimizer.call_args.args[0]
    assert len(optimized_players) == 10
    assert not any(candidate.is_woman for candidate in optimized_players)
    assert optimizer.call_args.kwargs == {"profile": OPEN_RULES}
    assert app.session_state["result"].active_positions == POSITIONS


def test_bulk_availability_actions_update_the_roster(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    next(
        button for button in app.button if button.label == "Clear all women"
    ).click().run(timeout=20)
    assert not any(
        record["available"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    )
    assert next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled

    next(
        button for button in app.button if button.label == "Select all women"
    ).click().run(timeout=20)
    assert all(
        record["available"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    )
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled


@pytest.mark.parametrize(
    ("women_count", "men_count", "lineup_size", "inactive_positions"),
    [
        (3, 5, 8, {"C", "RF"}),
        (3, 6, 9, {"RF"}),
        (3, 7, 9, {"RF"}),
        (4, 6, 10, set()),
    ],
)
def test_app_presents_legal_active_positions_for_each_lineup_size(
    monkeypatch, women_count, men_count, lineup_size, inactive_positions
):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    women = [
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Woman"
    ]
    men = [
        record["id"]
        for record in app.session_state["roster"]
        if record["gender"] == "Man"
    ]
    set_available_player_ids(
        app, [*women[:women_count], *men[:men_count]]
    )

    available_count = women_count + men_count
    assert any(
        caption.value.startswith(f"**{available_count} available players**")
        for caption in app.caption
    )
    assert any(
        caption.value.startswith(f"**Ready for {lineup_size} fielders")
        for caption in app.caption
    )
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)

    optimizer.assert_called_once()
    assert len(optimizer.call_args.args[0]) == available_count
    expected_active = tuple(
        position for position in POSITIONS if position not in inactive_positions
    )
    assert app.session_state["result"].active_positions == expected_active
    assert any(
        f"{lineup_size} fielders per inning" in caption.value
        for caption in app.caption
    )

    next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Lineup view"
    ).set_value("Full matrix").run(timeout=20)
    lineup = app.dataframe[0].value
    assert list(lineup.columns) == [*POSITIONS, "Out"]
    for position in expected_active:
        assert (lineup[position] != "—").all()
    for position in inactive_positions:
        assert (lineup[position] == "—").all()
    expected_out_count = available_count - lineup_size
    assert all(
        (len(players_out.split(", ")) if players_out else 0)
        == expected_out_count
        for players_out in lineup["Out"]
    )

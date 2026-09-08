from copy import deepcopy
from html import unescape
from pathlib import Path
import re
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
from softball_fielding.team_setups import team_red_roster

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
NEUTRAL_APP_PATH = Path(__file__).resolve().parents[1] / "neutral_app.py"


def fake_result(players, *, profile=COED_RULES, progress_callback=None):
    if progress_callback is not None:
        progress_callback("Checking the fairest possible playing time…")
        progress_callback("Reducing position changes…")
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


def semantic_lineup(app):
    markup = next(
        markdown.value
        for markdown in app.markdown
        if '<table class="seven-inning-lineup"' in markdown.value
    )
    headers = [
        unescape(value)
        for value in re.findall(r'<th scope="col">(.*?)</th>', markup)
    ]
    body = re.search(r"<tbody>(.*?)</tbody>", markup)
    assert body is not None
    rows = [
        [
            unescape(value)
            for value in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row)
        ]
        for row in re.findall(r"<tr>(.*?)</tr>", body.group(1))
    ]
    return markup, headers, rows


def rendered_markup_contains(app, fragment):
    return any(fragment in str(markdown.value) for markdown in app.markdown)


def test_optimization_indicator_source_is_status_first_and_neutral():
    source = APP_PATH.read_text(encoding="utf-8")
    readme = (APP_PATH.parent / "README.md").read_text(encoding="utf-8")

    assert source.index('update_optimization_status("Optimizing…")') < source.index(
        "optimization_dancer.markdown("
    )
    assert 'role="status"' in source
    assert 'aria-live="polite" aria-atomic="true"' in source
    assert 'data-motion="backward-glide" data-facing="right"' in source
    assert "@media (prefers-reduced-motion: reduce)" in source
    assert "coach" not in source.casefold()
    assert "coach" not in readme.casefold()


def set_available_player_ids(app, player_ids):
    selected = set(player_ids)
    for record in app.session_state["roster"]:
        availability_checkbox(app, record["id"]).set_value(
            record["id"] in selected
        )
    app.run(timeout=20)


def choose_neutral_setup(app, setup_key):
    element_with_key(app.radio, "setup-choice").set_value(setup_key).run(
        timeout=20
    )
    next(button for button in app.button if button.label == "Continue").click().run(
        timeout=20
    )
    return app


def test_neutral_deployment_requires_setup_without_roster_leak(
    monkeypatch, tmp_path
):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "🥎 Softball Fielding Optimizer"
    setup_choice = element_with_key(app.radio, "setup-choice")
    assert setup_choice.label == "Starting setup"
    assert setup_choice.value is None
    assert setup_choice.options == [
        "Here For The Beer",
        "Team Red",
        "Start blank",
    ]
    assert next(
        button for button in app.button if button.label == "Continue"
    ).disabled
    assert not app.checkbox
    assert not app.selectbox
    assert not any(
        button.label.startswith(("Optimize", "＋ Add", "Reset"))
        for button in app.button
    )
    assert not any(
        name in str(element.value)
        for name in ("Dung", "David R", "Kevin", "Heather")
        for element in [*app.markdown, *app.caption, *app.info]
    )
    assert "roster" not in app.session_state.filtered_state


@pytest.mark.parametrize(
    ("setup_key", "expected_count", "expected_profile"),
    [
        ("here-for-the-beer", 15, "coed"),
        ("team-red", 13, "open"),
        ("blank", 0, "coed"),
    ],
)
def test_neutral_startup_paths_load_only_the_selected_setup(
    monkeypatch,
    setup_key,
    expected_count,
    expected_profile,
):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = choose_neutral_setup(
        AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20),
        setup_key,
    )

    assert not app.exception
    assert app.session_state["active_setup"] == setup_key
    assert len(app.session_state["roster"]) == expected_count
    assert app.session_state["league-profile"] == expected_profile
    assert any(
        f"Current setup: **" in caption.value for caption in app.caption
    )

    if setup_key == "team-red":
        assert not any(
            selectbox.label == "League rules" for selectbox in app.selectbox
        )
        assert any("League rules: **Open" in info.value for info in app.info)
        assert {record["gender"] for record in app.session_state["roster"]} == {
            "Unspecified"
        }
        assert all(record["available"] for record in app.session_state["roster"])
        assert not any(
            "Unspecified" in expander.label for expander in app.expander
        )
    elif setup_key == "blank":
        assert any("Roster is empty" in info.value for info in app.info)
        assert any(
            button.label == "＋ Add first player" for button in app.button
        )
        assert not app.checkbox
    else:
        assert element_with_key(app.selectbox, "league-profile").value == "coed"


def test_team_red_hides_gender_and_optimizes_under_locked_open_rules(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = choose_neutral_setup(
        AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20),
        "team-red",
    )

    assert any(item.value == "**Players**" for item in app.markdown)
    assert not any(
        item.value in {"**Women**", "**Men**"} for item in app.markdown
    )
    david_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["name"] == "David R"
    )
    next(
        button for button in app.button if button.label == "Edit David R"
    ).click().run(timeout=20)
    assert not any(selectbox.label == "Gender" for selectbox in app.selectbox)
    element_with_key_prefix(
        app.get("button_group"), f"draft-preferences-{david_id}"
    ).set_value(["2B", "SS"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    david = next(
        record
        for record in app.session_state["roster"]
        if record["id"] == david_id
    )
    assert david["gender"] == "Unspecified"
    assert david["preferences"] == {"2B", "SS"}

    next(button for button in app.button if button.label == "＋ Add player").click().run(
        timeout=20
    )
    added = app.session_state["pending_new_player"]
    assert added["gender"] == "Unspecified"
    assert not any(selectbox.label == "Gender" for selectbox in app.selectbox)
    element_with_key_prefix(app.text_input, f"draft-name-{added['id']}").set_value(
        "Taylor"
    )
    element_with_key_prefix(
        app.get("button_group"), f"draft-preferences-{added['id']}"
    ).set_value(["C", "RF"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    assert next(
        record
        for record in app.session_state["roster"]
        if record["name"] == "Taylor"
    )["gender"] == "Unspecified"

    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert optimizer.call_args.kwargs["profile"] == OPEN_RULES
    assert all(
        candidate.gender == "Unspecified"
        for candidate in optimizer.call_args.args[0]
    )
    assert app.session_state["result"] is not None

    next(
        button for button in app.button if button.label == "Reset Team Red roster"
    ).click().run(timeout=20)
    next(button for button in app.button if button.label == "Reset roster").click().run(
        timeout=20
    )
    assert app.session_state["roster"] == team_red_roster()
    assert app.session_state["league-profile"] == "open"
    assert app.session_state["next_player_id"] == 14
    assert app.session_state["result"] is None


def test_blank_setup_adds_explicit_gender_and_resets_to_empty(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = choose_neutral_setup(
        AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20),
        "blank",
    )

    next(
        button for button in app.button if button.label == "＋ Add first player"
    ).click().run(timeout=20)
    added = app.session_state["pending_new_player"]
    assert added["id"] == "player-1"
    assert added["gender"] == "Woman"
    gender = next(selectbox for selectbox in app.selectbox if selectbox.label == "Gender")
    gender.set_value("Man")
    element_with_key_prefix(app.text_input, "draft-name-player-1").set_value("Jordan")
    element_with_key_prefix(
        app.get("button_group"), "draft-preferences-player-1"
    ).set_value(["P", "SS"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    assert app.session_state["roster"][0]["gender"] == "Man"

    next(
        button for button in app.button if button.label == "Clear roster and start over"
    ).click().run(timeout=20)
    next(button for button in app.button if button.label == "Clear roster").click().run(
        timeout=20
    )
    assert app.session_state["active_setup"] == "blank"
    assert app.session_state["roster"] == []
    assert app.session_state["next_player_id"] == 1
    assert any("Roster is empty" in info.value for info in app.info)


def test_neutral_setup_change_cancel_preserves_and_confirm_reinitializes(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = choose_neutral_setup(
        AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20),
        "here-for-the-beer",
    )
    first_id = app.session_state["roster"][0]["id"]
    availability_checkbox(app, first_id).set_value(False).run(timeout=20)
    element_with_key(app.selectbox, "league-profile").set_value("open").run(
        timeout=20
    )
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    preserved_roster = [
        {**record, "preferences": set(record["preferences"])}
        for record in app.session_state["roster"]
    ]
    preserved_result = app.session_state["result"]
    preserved_fingerprint = app.session_state["result_fingerprint"]

    next(
        button for button in app.button if button.label == "Change roster setup"
    ).click().run(timeout=20)
    assert not app.checkbox
    assert not any(
        button.label == "Optimize seven innings" for button in app.button
    )
    pending_target = element_with_key(app.radio, "pending-setup-target")
    assert pending_target.value is None
    pending_target.set_value("team-red").run(timeout=20)
    assert any("Switch to Team Red?" in warning.value for warning in app.warning)
    next(
        button for button in app.button if button.label == "Keep Here For The Beer"
    ).click().run(timeout=20)

    assert app.session_state["active_setup"] == "here-for-the-beer"
    assert app.session_state["roster"] == preserved_roster
    assert app.session_state["result"] == preserved_result
    assert app.session_state["result_fingerprint"] == preserved_fingerprint
    assert app.session_state["league-profile"] == "open"
    assert not availability_checkbox(app, first_id).value

    next(
        button for button in app.button if button.label == "Change roster setup"
    ).click().run(timeout=20)
    element_with_key(app.radio, "pending-setup-target").set_value("team-red").run(
        timeout=20
    )
    next(
        button
        for button in app.button
        if button.label == "Discard changes and switch to Team Red"
    ).click().run(timeout=20)

    expected = team_red_roster()
    assert app.session_state["active_setup"] == "team-red"
    assert app.session_state["roster"] == expected
    assert app.session_state["league-profile"] == "open"
    assert app.session_state["next_player_id"] == 14
    assert availability_checkbox(app, "player-1").value
    assert app.session_state["result"] is None
    assert "result_fingerprint" not in app.session_state.filtered_state
    assert "pending-setup-target" not in app.session_state.filtered_state



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
    assert optimizer.call_args.kwargs["profile"] == COED_RULES
    assert callable(optimizer.call_args.kwargs["progress_callback"])
    assert not rendered_markup_contains(app, 'class="optimization-status"')
    assert not rendered_markup_contains(app, 'class="optimization-dancer"')
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert any(
        "Optimized in" in caption.value and "seconds" in caption.value
        for caption in app.caption
    )
    assert not any(
        selectbox.label in {"Lineup view", "Inning"}
        for selectbox in app.selectbox
    )
    markup, headers, rows = semantic_lineup(app)
    assert 'aria-label="Seven-inning lineup"' in markup
    assert 'aria-label="Scrollable seven-inning lineup"' in markup
    assert headers == ["Inning", *POSITIONS, "Bench"]
    assert len(rows) == INNINGS
    assert [row[0] for row in rows] == [str(value) for value in range(1, 8)]
    assert all(len(row) == len(POSITIONS) + 2 for row in rows)
    assert all(len(row[-1].split(", ")) == 5 for row in rows)
    assert list(app.dataframe[0].value.columns) == [
        "Player",
        "Innings",
        "Positions",
    ]
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
    assert not rendered_markup_contains(app, 'class="optimization-status"')
    assert not rendered_markup_contains(app, 'class="optimization-dancer"')
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


def test_unexpected_optimizer_error_also_clears_animation(monkeypatch):
    optimizer = Mock(side_effect=RuntimeError("unexpected solver failure"))
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)

    optimizer.assert_called_once()
    assert app.exception
    assert not rendered_markup_contains(app, 'class="optimization-status"')
    assert not rendered_markup_contains(app, 'class="optimization-dancer"')


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

    # The supported optimization domain is capped at 15 available players.
    optimize = next(
        button for button in app.button if button.label == "Optimize seven innings"
    )
    assert optimize.disabled
    assert any(
        "At most 15 available players are supported" in warning.value
        for warning in app.warning
    )
    availability_checkbox(app, "player-15").set_value(False).run(timeout=20)
    assert not next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).disabled

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
    assert not any(
        selectbox.label in {"Lineup view", "Inning"}
        for selectbox in app.selectbox
    )
    assert semantic_lineup(app)[1] == ["Inning", *POSITIONS, "Bench"]
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
        if '<table class="seven-inning-lineup"' in markdown.value
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


@pytest.mark.parametrize("setup_key", ["legacy", "team-red", "blank"])
def test_empty_new_player_name_stays_a_draft_across_setups(
    monkeypatch, setup_key
):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    if setup_key == "legacy":
        app = AppTest.from_file(APP_PATH).run(timeout=20)
    else:
        app = choose_neutral_setup(
            AppTest.from_file(NEUTRAL_APP_PATH).run(timeout=20),
            setup_key,
        )

    if app.session_state["roster"]:
        next(
            button
            for button in app.button
            if button.label == "Optimize seven innings"
        ).click().run(timeout=20)

    committed_roster = deepcopy(app.session_state["roster"])
    committed_state = {
        key: deepcopy(app.session_state.filtered_state.get(key))
        for key in (
            "roster_revision",
            "result",
            "error",
            "result_fingerprint",
            "last_attempt_fingerprint",
            "optimization_seconds",
            "inputs_changed",
        )
    }
    add_label = "＋ Add first player" if not committed_roster else "＋ Add player"
    next(button for button in app.button if button.label == add_label).click().run(
        timeout=20
    )
    pending_id = app.session_state["pending_new_player"]["id"]
    element_with_key_prefix(
        app.text_input, f"draft-name-{pending_id}"
    ).set_value(" \t ")
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert app.session_state["roster"] == committed_roster
    assert app.session_state["pending_new_player"]["id"] == pending_id
    assert app.session_state["editing_player_id"] == pending_id
    assert app.session_state["player_name_errors"] == {
        pending_id: "Player name is required."
    }
    assert any(error.value == "Player name is required." for error in app.error)
    assert not any(checkbox.label == "Unnamed player" for checkbox in app.checkbox)
    for key, expected in committed_state.items():
        assert app.session_state.filtered_state.get(key) == expected

    valid_name = f"Valid {setup_key} player"
    element_with_key_prefix(
        app.text_input, f"draft-name-{pending_id}"
    ).set_value(f" {valid_name} ")
    element_with_key_prefix(
        app.get("button_group"), f"draft-preferences-{pending_id}"
    ).set_value(["C"])
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    saved = next(
        record
        for record in app.session_state["roster"]
        if record["id"] == pending_id
    )
    assert saved["name"] == valid_name
    assert saved["preferences"] == {"C"}
    assert app.session_state["editing_player_id"] is None
    assert not app.session_state["player_name_errors"]

    next(button for button in app.button if button.label == "＋ Add player").click().run(
        timeout=20
    )
    cancelled_id = app.session_state["pending_new_player"]["id"]
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    assert cancelled_id in app.session_state["player_name_errors"]
    next(button for button in app.button if button.label == "Cancel").click().run(
        timeout=20
    )
    assert app.session_state["pending_new_player"] is None
    assert not app.session_state["player_name_errors"]
    assert not any(
        record["id"] == cancelled_id for record in app.session_state["roster"]
    )


def test_empty_existing_player_rename_preserves_committed_outcome(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_roster = deepcopy(app.session_state["roster"])
    original_revision = app.session_state["roster_revision"]
    original_result = app.session_state["result"]
    original_result_fingerprint = app.session_state["result_fingerprint"]
    original_attempt_fingerprint = app.session_state["last_attempt_fingerprint"]
    original_timing = app.session_state["optimization_seconds"]

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value("   ")
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert app.session_state["roster"] == original_roster
    assert app.session_state["roster_revision"] == original_revision
    assert app.session_state["result"] == original_result
    assert app.session_state["result_fingerprint"] == original_result_fingerprint
    assert app.session_state["last_attempt_fingerprint"] == original_attempt_fingerprint
    assert app.session_state["optimization_seconds"] == original_timing
    assert app.session_state["editing_player_id"] == "player-9"
    assert any(error.value == "Player name is required." for error in app.error)

    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value(
        "Kevin Renamed"
    )
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )
    assert next(
        record
        for record in app.session_state["roster"]
        if record["id"] == "player-9"
    )["name"] == "Kevin Renamed"
    assert app.session_state["result"] is None
    assert app.session_state["roster_revision"] == original_revision + 1
    assert not app.session_state["player_name_errors"]


def test_empty_existing_player_rename_preserves_solver_error(monkeypatch):
    solver_message = "No legal schedule can satisfy this roster."
    optimizer = Mock(side_effect=LineupError(solver_message))
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    original_roster = deepcopy(app.session_state["roster"])
    original_revision = app.session_state["roster_revision"]
    original_attempt_fingerprint = app.session_state["last_attempt_fingerprint"]

    next(button for button in app.button if button.label == "Edit Kevin").click().run(
        timeout=20
    )
    element_with_key_prefix(app.text_input, "draft-name-player-9").set_value("\t")
    next(button for button in app.button if button.label == "Save changes").click().run(
        timeout=20
    )

    assert app.session_state["roster"] == original_roster
    assert app.session_state["roster_revision"] == original_revision
    assert app.session_state["error"] == solver_message
    assert app.session_state["last_attempt_fingerprint"] == original_attempt_fingerprint
    assert app.session_state["result"] is None
    assert {error.value for error in app.error} == {
        solver_message,
        "Player name is required.",
    }
    optimizer.assert_called_once()


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
    assert optimizer.call_args.kwargs["profile"] == COED_RULES
    assert callable(optimizer.call_args.kwargs["progress_callback"])
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
    assert optimizer.call_args.kwargs["profile"] == OPEN_RULES
    assert callable(optimizer.call_args.kwargs["progress_callback"])
    assert app.session_state["result"].lineup_size == 10

    next(
        button for button in app.button if button.label == "Reset to CSV defaults"
    ).click().run(timeout=20)
    next(button for button in app.button if button.label == "Confirm reset").click().run(
        timeout=20
    )
    assert element_with_key(app.selectbox, "league-profile").value == "open"


def test_open_profile_uses_one_gender_neutral_availability_group(monkeypatch):
    optimizer = Mock(side_effect=fake_result)
    monkeypatch.setattr(softball_fielding, "optimize_game", optimizer)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    mixed_player_id = next(
        record["id"]
        for record in app.session_state["roster"]
        if record["name"] == "Andrew"
    )

    assert any(item.value == "**Women**" for item in app.markdown)
    assert any(item.value == "**Men**" for item in app.markdown)
    availability_checkbox(app, mixed_player_id).set_value(False).run(timeout=20)

    element_with_key(app.selectbox, "league-profile").set_value("open").run(
        timeout=20
    )

    assert any(item.value == "**Players**" for item in app.markdown)
    assert not any(item.value in {"**Women**", "**Men**"} for item in app.markdown)
    button_labels = {button.label for button in app.button}
    assert "Select all players" in button_labels
    assert "Clear all players" in button_labels
    assert "Select all women" not in button_labels
    assert "Clear all men" not in button_labels
    availability_labels = [
        checkbox.label
        for checkbox in app.checkbox
        if checkbox.key and checkbox.key.startswith("available-")
    ]
    alphabetical_labels = sorted(
        (record["name"] for record in app.session_state["roster"]),
        key=str.casefold,
    )
    # AppTest traverses the two visual columns one column at a time. The UI
    # fills those columns from an alphabetically ordered, row-major list.
    assert availability_labels == (
        alphabetical_labels[::2] + alphabetical_labels[1::2]
    )
    assert not availability_checkbox(app, mixed_player_id).value

    element_with_key(app.selectbox, "league-profile").set_value("coed").run(
        timeout=20
    )
    assert not availability_checkbox(app, mixed_player_id).value

    element_with_key(app.selectbox, "league-profile").set_value("open").run(
        timeout=20
    )
    next(
        button for button in app.button if button.label == "Optimize seven innings"
    ).click().run(timeout=20)
    assert app.session_state["result"] is not None

    next(
        button for button in app.button if button.label == "Clear all players"
    ).click().run(timeout=20)
    assert not any(record["available"] for record in app.session_state["roster"])
    assert app.session_state["result"] is None
    assert any(
        info.value == "Inputs changed — optimize again." for info in app.info
    )

    next(
        button for button in app.button if button.label == "Select all players"
    ).click().run(timeout=20)
    assert all(record["available"] for record in app.session_state["roster"])

    element_with_key(app.selectbox, "league-profile").set_value("coed").run(
        timeout=20
    )
    assert any(item.value == "**Women**" for item in app.markdown)
    assert any(item.value == "**Men**" for item in app.markdown)
    assert all(record["available"] for record in app.session_state["roster"])


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
    assert optimizer.call_args.kwargs["profile"] == OPEN_RULES
    assert callable(optimizer.call_args.kwargs["progress_callback"])
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

    _markup, headers, rows = semantic_lineup(app)
    assert headers == ["Inning", *POSITIONS, "Bench"]
    position_indexes = {
        position: headers.index(position) for position in POSITIONS
    }
    for row in rows:
        for position in expected_active:
            assert row[position_indexes[position]] != "—"
        for position in inactive_positions:
            assert row[position_indexes[position]] == "—"
        active_names = [
            row[position_indexes[position]] for position in expected_active
        ]
        assert len(set(active_names)) == len(active_names)
    expected_out_count = available_count - lineup_size
    assert all(
        (len(row[-1].split(", ")) if row[-1] != "None" else 0)
        == expected_out_count
        for row in rows
    )

from streamlit.testing.v1 import AppTest


def test_app_loads_csv_defaults_and_optimizes():
    app = AppTest.from_file("app.py").run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "🥎 Softball Fielding Optimizer"
    roster = app.session_state["roster"]
    assert len(roster) == 15
    assert sum(record["gender"] == "Woman" for record in roster) == 5
    assert "SS" in next(
        record["preferences"] for record in roster if record["name"] == "Kevin"
    )
    button_groups = app.get("button_group")
    women_group = next(
        group for group in button_groups if group.key.startswith("availability-Woman-")
    )
    men_group = next(
        group for group in button_groups if group.key.startswith("availability-Man-")
    )
    assert [option.content for option in women_group.options] == sorted(
        record["name"] for record in roster if record["gender"] == "Woman"
    )
    assert [option.content for option in men_group.options] == sorted(
        record["name"] for record in roster if record["gender"] == "Man"
    )

    optimize_button = next(
        button for button in app.button if button.label == "Optimize seven innings"
    )
    optimize_button.click().run(timeout=20)

    assert not app.exception
    assert not app.error
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )
    assert any(
        selectbox.label == "Lineup view" and selectbox.value == "Full matrix"
        for selectbox in app.selectbox
    )
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

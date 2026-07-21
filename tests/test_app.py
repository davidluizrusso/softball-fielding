from streamlit.testing.v1 import AppTest


def test_app_loads_and_sample_roster_optimizes():
    app = AppTest.from_file("app.py").run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "🥎 Softball Fielding Optimizer"

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
    ]
    assert len(app.dataframe[0].value) == 7

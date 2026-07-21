from streamlit.testing.v1 import AppTest


def test_app_loads_and_sample_roster_optimizes():
    app = AppTest.from_file("app.py").run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "🥎 Softball Fielding Optimizer"

    app.button[0].click().run(timeout=20)

    assert not app.exception
    assert not app.error
    assert any(
        subheader.value == "Optimized lineup" for subheader in app.subheader
    )

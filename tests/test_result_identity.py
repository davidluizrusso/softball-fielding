from datetime import datetime, timedelta, timezone

import pytest

from softball_fielding.result_identity import (
    ResultIdentity,
    ascii_slug,
    create_result_identity,
    solver_status_explanation,
)


def test_result_identity_uses_stable_display_and_ascii_safe_filename():
    identity = create_result_identity(
        "Téam Red!!!",
        "Open (no gender fielding minimums)",
        "open",
        created_at=datetime(
            2026,
            9,
            8,
            16,
            30,
            12,
            tzinfo=timezone(timedelta(hours=-7)),
        ),
        snapshot_id="AB12CD34",
    )

    assert identity.created_at_text == "2026-09-08 23:30:12 UTC"
    assert identity.filename == "team-red_open_20260908T233012Z_ab12cd34.csv"
    assert identity.snapshot_id == "ab12cd34"
    assert identity.setup_label == "Téam Red!!!"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Here For The Beer", "here-for-the-beer"),
        ("Team Red", "team-red"),
        ("", "custom"),
        ("*玩家 names never belong here*", "names-never-belong-here"),
    ],
)
def test_ascii_slug_is_filename_safe(value, expected):
    assert ascii_slug(value) == expected


def test_result_identity_rejects_ambiguous_time_and_unsafe_snapshot_id():
    with pytest.raises(ValueError, match="timezone"):
        ResultIdentity(
            "Custom",
            "Co-ed",
            "coed",
            datetime(2026, 9, 8),
            "ab12cd34",
        )
    with pytest.raises(ValueError, match="hexadecimal"):
        ResultIdentity(
            "Custom",
            "Co-ed",
            "coed",
            datetime(2026, 9, 8, tzinfo=timezone.utc),
            "player-name",
        )


def test_new_result_identity_gets_a_new_snapshot_but_remains_stable():
    created_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
    first = create_result_identity("Custom", "Co-ed", "coed", created_at=created_at)
    second = create_result_identity("Custom", "Co-ed", "coed", created_at=created_at)

    assert first.filename == first.filename
    assert first.snapshot_id != second.snapshot_id
    assert first.filename != second.filename


@pytest.mark.parametrize(
    ("setup_label", "profile_key", "expected_prefix"),
    [
        ("Here For The Beer", "coed", "here-for-the-beer_coed_"),
        ("Team Red", "open", "team-red_open_"),
        ("Custom", "open", "custom_open_"),
    ],
)
def test_named_and_custom_setups_have_distinct_filename_prefixes(
    setup_label, profile_key, expected_prefix
):
    identity = create_result_identity(
        setup_label,
        profile_key,
        profile_key,
        created_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        snapshot_id="ab12cd34",
    )

    assert identity.filename.startswith(expected_prefix)


def test_solver_status_explanations_are_authoritative_without_overclaiming():
    optimal = solver_status_explanation("OPTIMAL")
    feasible = solver_status_explanation("feasible")

    assert "Legal, authoritative" in optimal
    assert "Every documented optimization priority was proven optimal" in optimal
    assert "Legal, authoritative" in feasible
    assert "Not every possible improvement was proven" in feasible
    assert "proven optimal" not in feasible
    with pytest.raises(ValueError, match="Unsupported"):
        solver_status_explanation("UNKNOWN")

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from matchvet.t10 import SettlementEvidence


def _evidence(**changes: object) -> SettlementEvidence:
    values: dict[str, object] = {
        "fixture_id": "fixture-t10",
        "source_level": "FOOTBALL_DATA",
        "source_key": "football-data",
        "record_id": "fd-t10-1",
        "fixture_status": "COMPLETED",
        "full_time_home_goals": 2,
        "full_time_away_goals": 1,
        "half_time_home_goals": 1,
        "half_time_away_goals": 0,
        "corners_home": 6,
        "corners_away": 4,
    }
    values.update(changes)
    return SettlementEvidence.from_mapping(values)


def test_initial_catalog_has_exactly_the_37_supported_preferences() -> None:
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SettlementResult

    assert len(DEFAULT_PREFERENCE_CATALOG) == 37
    assert len({item.preference_id for item in DEFAULT_PREFERENCE_CATALOG}) == 37
    assert all(
        set(item.possible_results)
        <= {SettlementResult.WIN, SettlementResult.LOSS, SettlementResult.PUSH}
        for item in DEFAULT_PREFERENCE_CATALOG
    )
    assert all(
        SettlementResult.PUSH in item.possible_results
        for item in DEFAULT_PREFERENCE_CATALOG
        if item.family.value == "Asian Handicap" and item.line in {0, 1, -1}
    )


def test_catalog_rejects_prohibited_markets_and_half_outcomes() -> None:
    from fractions import Fraction

    from matchvet.t10 import (
        DEFAULT_PREFERENCE_CATALOG,
        BettingPreference,
        MatchPhase,
        PreferenceFamily,
        SettlementResult,
        T10ValidationError,
    )

    with pytest.raises(T10ValidationError, match="Unsupported or prohibited"):
        DEFAULT_PREFERENCE_CATALOG.resolve("Match Winner", "Home", Fraction(1, 2))
    with pytest.raises(T10ValidationError, match="Unsupported"):
        DEFAULT_PREFERENCE_CATALOG.resolve("Match Winner", "Under")
    with pytest.raises(T10ValidationError, match="outcomes"):
        BettingPreference(
            preference_id="invalid",
            family=PreferenceFamily.MATCH_WINNER,
            selection="Home",
            line=None,
            phase=MatchPhase.FULL_MATCH,
            required_facts=("full_time_home_goals", "full_time_away_goals"),
            possible_results=cast(tuple[SettlementResult, ...], ("HALF_WIN",)),
            settlement_rule="invalid",
            label="invalid",
        )


def test_catalog_records_the_fixed_source_hierarchy_version() -> None:
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SOURCE_HIERARCHY_VERSION

    assert all(
        item.source_hierarchy_version == SOURCE_HIERARCHY_VERSION
        for item in DEFAULT_PREFERENCE_CATALOG
    )
    assert DEFAULT_PREFERENCE_CATALOG.get("asian_handicap_away_plus_1_0").label.endswith(
        "Away +1.0"
    )
    assert DEFAULT_PREFERENCE_CATALOG.get("asian_handicap_home_0_0").to_dict()["line"] == "0.0"


def test_missing_fixture_status_stays_pending() -> None:
    from matchvet.t10 import SettlementGrader

    evidence = SettlementEvidence(
        fixture_id="fixture-missing-status",
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-missing-status",
        full_time_home_goals=2,
        full_time_away_goals=1,
    )
    grade = SettlementGrader().grade("match_winner_home", (evidence,))

    assert grade.grading_state == "PENDING"
    assert grade.settlement_result is None


def test_malformed_provenance_and_assertion_lists_are_rejected() -> None:
    from matchvet.t10 import T10ValidationError

    with pytest.raises(T10ValidationError, match="provenance"):
        SettlementEvidence.from_mapping({**_evidence().to_dict(), "provenance": ["not-an-object"]})
    with pytest.raises(T10ValidationError, match="identifier lists"):
        SettlementEvidence.from_mapping(
            {**_evidence().to_dict(), "source_assertion_ids": "not-an-array"}
        )


@pytest.mark.parametrize(
    (
        "preference_id",
        "home_goals",
        "away_goals",
        "half_home_goals",
        "half_away_goals",
        "home_corners",
        "away_corners",
        "expected",
    ),
    (
        ("match_winner_home", 2, 1, 1, 0, 6, 4, "WIN"),
        ("match_winner_draw", 1, 1, 0, 0, 6, 4, "WIN"),
        ("match_winner_away", 1, 2, 0, 1, 6, 4, "WIN"),
        ("double_chance_1x", 1, 1, 0, 0, 6, 4, "WIN"),
        ("double_chance_x2", 1, 2, 0, 1, 6, 4, "WIN"),
        ("double_chance_12", 2, 1, 1, 0, 6, 4, "WIN"),
        ("match_goals_over_1_5", 1, 1, 0, 0, 6, 4, "WIN"),
        ("first_half_over_1_5", 2, 0, 2, 0, 6, 4, "WIN"),
        ("second_half_over_1_5", 2, 1, 0, 0, 6, 4, "WIN"),
        ("home_team_goals_over_1_5", 2, 0, 1, 0, 6, 4, "WIN"),
        ("away_team_goals_over_1_5", 0, 2, 0, 1, 6, 4, "WIN"),
        ("corner_winner_home", 0, 0, 0, 0, 0, 0, "LOSS"),
        ("total_corners_over_8_5", 4, 4, 0, 0, 4, 4, "LOSS"),
        ("home_corners_over_3_5", 4, 0, 0, 0, 4, 0, "WIN"),
        ("away_corners_over_3_5", 0, 4, 0, 0, 0, 4, "WIN"),
        ("asian_handicap_home_0_0", 2, 1, 1, 0, 6, 4, "WIN"),
        ("asian_handicap_away_0_0", 1, 1, 0, 0, 6, 4, "PUSH"),
        ("asian_handicap_home_plus_1_0", 0, 1, 0, 0, 6, 4, "PUSH"),
        ("asian_handicap_away_plus_1_0", 1, 0, 0, 0, 6, 4, "PUSH"),
        ("asian_handicap_home_plus_1_5", 0, 1, 0, 0, 6, 4, "WIN"),
        ("asian_handicap_away_plus_1_5", 1, 0, 0, 0, 6, 4, "WIN"),
        ("asian_handicap_home_minus_1_0", 2, 1, 1, 0, 6, 4, "PUSH"),
        ("asian_handicap_away_minus_1_0", 1, 2, 0, 1, 6, 4, "PUSH"),
        ("asian_handicap_home_minus_1_5", 2, 0, 1, 0, 6, 4, "WIN"),
        ("asian_handicap_away_minus_1_5", 0, 2, 0, 1, 6, 4, "WIN"),
    ),
)
def test_public_grade_examples(
    preference_id: str,
    home_goals: int,
    away_goals: int,
    half_home_goals: int,
    half_away_goals: int,
    home_corners: int,
    away_corners: int,
    expected: str,
) -> None:
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SettlementGrader

    evidence = _evidence(
        full_time_home_goals=home_goals,
        full_time_away_goals=away_goals,
        half_time_home_goals=half_home_goals,
        half_time_away_goals=half_away_goals,
        corners_home=home_corners,
        corners_away=away_corners,
    )
    grade = SettlementGrader().grade(DEFAULT_PREFERENCE_CATALOG.get(preference_id), (evidence,))

    assert grade.settlement_result == expected
    assert grade.grading_state == "FINAL"


def _score(
    home_goals: int,
    away_goals: int,
    *,
    half_home_goals: int = 0,
    half_away_goals: int = 0,
    home_corners: int = 6,
    away_corners: int = 4,
) -> dict[str, object]:
    return {
        "full_time_home_goals": home_goals,
        "full_time_away_goals": away_goals,
        "half_time_home_goals": half_home_goals,
        "half_time_away_goals": half_away_goals,
        "corners_home": home_corners,
        "corners_away": away_corners,
    }


def _over_cases(
    values: tuple[int, int, int], *, statistic: str
) -> tuple[tuple[str, Mapping[str, object], str], ...]:
    cases: list[tuple[str, Mapping[str, object], str]] = []
    for label, value, expected in (
        ("below", values[0], "LOSS"),
        ("nearest_above", values[1], "WIN"),
        ("above", values[2], "WIN"),
    ):
        if statistic == "match_goals":
            changes = _score(value, 0)
        elif statistic == "first_half_goals":
            changes = _score(value, 0, half_home_goals=value)
        elif statistic == "second_half_goals" or statistic == "home_goals":
            changes = _score(value, 0)
        elif statistic == "away_goals":
            changes = _score(0, value)
        elif statistic == "total_corners" or statistic == "home_corners":
            changes = _score(0, 0, home_corners=value, away_corners=0)
        elif statistic == "away_corners":
            changes = _score(0, 0, home_corners=0, away_corners=value)
        else:
            raise AssertionError(f"unknown boundary statistic: {statistic}")
        cases.append((label, changes, expected))
    return tuple(cases)


def _relation_cases(
    preference_id: str,
    scores: tuple[tuple[str, Mapping[str, object], str], ...],
) -> tuple[str, tuple[tuple[str, Mapping[str, object], str], ...]]:
    return preference_id, scores


BOUNDARY_CASES = (
    _relation_cases(
        "match_winner_home",
        (
            ("below", _score(0, 1), "LOSS"),
            ("on", _score(1, 1), "LOSS"),
            ("above", _score(1, 0), "WIN"),
        ),
    ),
    _relation_cases(
        "match_winner_draw",
        (
            ("below", _score(0, 1), "LOSS"),
            ("on", _score(1, 1), "WIN"),
            ("above", _score(1, 0), "LOSS"),
        ),
    ),
    _relation_cases(
        "match_winner_away",
        (
            ("below", _score(0, 1), "WIN"),
            ("on", _score(1, 1), "LOSS"),
            ("above", _score(1, 0), "LOSS"),
        ),
    ),
    _relation_cases(
        "double_chance_1x",
        (
            ("below", _score(0, 1), "LOSS"),
            ("on", _score(1, 1), "WIN"),
            ("above", _score(1, 0), "WIN"),
        ),
    ),
    _relation_cases(
        "double_chance_x2",
        (
            ("below", _score(0, 1), "WIN"),
            ("on", _score(1, 1), "WIN"),
            ("above", _score(1, 0), "LOSS"),
        ),
    ),
    _relation_cases(
        "double_chance_12",
        (
            ("below", _score(0, 1), "WIN"),
            ("on", _score(1, 1), "LOSS"),
            ("above", _score(1, 0), "WIN"),
        ),
    ),
    ("match_goals_over_1_5", _over_cases((1, 2, 3), statistic="match_goals")),
    ("match_goals_over_2_5", _over_cases((2, 3, 4), statistic="match_goals")),
    ("match_goals_over_3_5", _over_cases((3, 4, 5), statistic="match_goals")),
    ("first_half_over_1_5", _over_cases((1, 2, 3), statistic="first_half_goals")),
    ("second_half_over_1_5", _over_cases((1, 2, 3), statistic="second_half_goals")),
    ("home_team_goals_over_1_5", _over_cases((1, 2, 3), statistic="home_goals")),
    ("home_team_goals_over_2_5", _over_cases((2, 3, 4), statistic="home_goals")),
    ("away_team_goals_over_1_5", _over_cases((1, 2, 3), statistic="away_goals")),
    ("away_team_goals_over_2_5", _over_cases((2, 3, 4), statistic="away_goals")),
    _relation_cases(
        "corner_winner_home",
        (
            ("below", _score(0, 0, home_corners=3, away_corners=4), "LOSS"),
            ("on", _score(0, 0, home_corners=4, away_corners=4), "LOSS"),
            ("above", _score(0, 0, home_corners=5, away_corners=4), "WIN"),
        ),
    ),
    _relation_cases(
        "corner_winner_draw",
        (
            ("below", _score(0, 0, home_corners=3, away_corners=4), "LOSS"),
            ("on", _score(0, 0, home_corners=4, away_corners=4), "WIN"),
            ("above", _score(0, 0, home_corners=5, away_corners=4), "LOSS"),
        ),
    ),
    _relation_cases(
        "corner_winner_away",
        (
            ("below", _score(0, 0, home_corners=3, away_corners=4), "WIN"),
            ("on", _score(0, 0, home_corners=4, away_corners=4), "LOSS"),
            ("above", _score(0, 0, home_corners=5, away_corners=4), "LOSS"),
        ),
    ),
    ("total_corners_over_8_5", _over_cases((8, 9, 10), statistic="total_corners")),
    ("total_corners_over_9_5", _over_cases((9, 10, 11), statistic="total_corners")),
    ("total_corners_over_10_5", _over_cases((10, 11, 12), statistic="total_corners")),
    ("home_corners_over_3_5", _over_cases((3, 4, 5), statistic="home_corners")),
    ("home_corners_over_4_5", _over_cases((4, 5, 6), statistic="home_corners")),
    ("home_corners_over_5_5", _over_cases((5, 6, 7), statistic="home_corners")),
    ("away_corners_over_3_5", _over_cases((3, 4, 5), statistic="away_corners")),
    ("away_corners_over_4_5", _over_cases((4, 5, 6), statistic="away_corners")),
    ("away_corners_over_5_5", _over_cases((5, 6, 7), statistic="away_corners")),
    _relation_cases(
        "asian_handicap_home_0_0",
        (
            ("below", _score(0, 1), "LOSS"),
            ("on", _score(1, 1), "PUSH"),
            ("above", _score(1, 0), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_away_0_0",
        (
            ("below", _score(1, 0), "LOSS"),
            ("on", _score(1, 1), "PUSH"),
            ("above", _score(0, 1), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_home_plus_1_0",
        (
            ("below", _score(0, 2), "LOSS"),
            ("on", _score(0, 1), "PUSH"),
            ("above", _score(1, 1), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_away_plus_1_0",
        (
            ("below", _score(2, 0), "LOSS"),
            ("on", _score(1, 0), "PUSH"),
            ("above", _score(1, 1), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_home_plus_1_5",
        (
            ("below", _score(0, 2), "LOSS"),
            ("on", _score(0, 1), "WIN"),
            ("above", _score(1, 1), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_away_plus_1_5",
        (
            ("below", _score(2, 0), "LOSS"),
            ("on", _score(1, 0), "WIN"),
            ("above", _score(1, 1), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_home_minus_1_0",
        (
            ("below", _score(1, 1), "LOSS"),
            ("on", _score(1, 0), "PUSH"),
            ("above", _score(2, 0), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_away_minus_1_0",
        (
            ("below", _score(1, 1), "LOSS"),
            ("on", _score(0, 1), "PUSH"),
            ("above", _score(0, 2), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_home_minus_1_5",
        (
            ("below", _score(1, 1), "LOSS"),
            ("on", _score(1, 0), "LOSS"),
            ("above", _score(2, 0), "WIN"),
        ),
    ),
    _relation_cases(
        "asian_handicap_away_minus_1_5",
        (
            ("below", _score(1, 1), "LOSS"),
            ("on", _score(0, 1), "LOSS"),
            ("above", _score(0, 2), "WIN"),
        ),
    ),
)


@pytest.mark.parametrize(
    ("preference_id", "cases"),
    BOUNDARY_CASES,
    ids=tuple(item[0] for item in BOUNDARY_CASES),
)
def test_exhaustive_boundary_table_covers_every_v1_preference(
    preference_id: str,
    cases: tuple[tuple[str, Mapping[str, object], str], ...],
) -> None:
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SettlementGrader

    assert preference_id in {item.preference_id for item in DEFAULT_PREFERENCE_CATALOG}
    grader = SettlementGrader()
    for label, changes, expected in cases:
        grade = grader.grade(preference_id, (_evidence(**dict(changes)),))
        assert grade.settlement_result == expected, f"{preference_id} {label}"


def test_exhaustive_boundary_table_ids_match_catalog() -> None:
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG

    assert {preference_id for preference_id, _ in BOUNDARY_CASES} == {
        item.preference_id for item in DEFAULT_PREFERENCE_CATALOG
    }


def test_half_lines_have_no_push_and_second_half_uses_full_minus_first() -> None:
    from matchvet.t10 import SettlementGrader

    grader = SettlementGrader()
    first_half = grader.grade(
        "first_half_over_1_5",
        (_evidence(full_time_home_goals=3, half_time_home_goals=1),),
    )
    second_half = grader.grade(
        "second_half_over_1_5",
        (_evidence(full_time_home_goals=3, half_time_home_goals=1),),
    )
    assert first_half.settlement_result == "LOSS"
    assert second_half.settlement_result == "WIN"
    assert all(grade.settlement_result != "PUSH" for grade in (first_half, second_half))


def test_missing_corners_only_affects_corner_families_and_is_not_inferred() -> None:
    from matchvet.t10 import PreferenceFamily, SettlementGrader

    grades = SettlementGrader().grade_all((_evidence(corners_home=None, corners_away=None),))
    corner_families = {
        PreferenceFamily.CORNER_WINNER,
        PreferenceFamily.TOTAL_CORNERS_OVER,
        PreferenceFamily.HOME_CORNERS_OVER,
        PreferenceFamily.AWAY_CORNERS_OVER,
    }
    goal_grades = [grade for grade in grades if grade.preference.family not in corner_families]
    corner_grades = [grade for grade in grades if grade not in goal_grades]
    assert len(goal_grades) == 25
    assert len(corner_grades) == 12
    assert all(grade.grading_state == "PENDING" for grade in corner_grades)
    assert all(grade.settlement_result is None for grade in corner_grades)
    closed = SettlementGrader().grade_all(
        (_evidence(corners_home=None, corners_away=None),), finalize=True
    )
    assert all(
        grade.settlement_result == "VOID"
        for grade in closed
        if grade.preference.family in corner_families
    )
    assert all(
        grade.settlement_result is not None
        for grade in closed
        if grade.preference.family not in corner_families
    )


def test_extra_time_and_shootout_are_excluded() -> None:
    from matchvet.t10 import SettlementGrader

    evidence = _evidence(
        full_time_home_goals=0,
        full_time_away_goals=0,
        extra_time_home_goals=3,
        shootout_home_goals=5,
    )
    grades = SettlementGrader().grade_all((evidence,))
    assert grades[0].settlement_result == "LOSS"
    assert grades[2].settlement_result == "LOSS"


@pytest.mark.parametrize(
    "status",
    (
        "POSTPONED",
        "CANCELLED",
        "ABANDONED",
        "UNCOMPLETED",
        "FORFEIT",
        "FORFEITED",
        "ADMIN_AWARDED",
    ),
)
def test_final_void_fixture_statuses_are_void_for_all_preferences(status: str) -> None:
    from matchvet.t10 import SettlementGrader

    grades = SettlementGrader().grade_all(
        (_evidence(fixture_status=status, regulation_completed=False),)
    )
    assert len(grades) == 37
    assert all(grade.grading_state == "FINAL" for grade in grades)
    assert all(grade.settlement_result == "VOID" for grade in grades)


@pytest.mark.parametrize("status", ("FORFEIT", "FORFEITED", "ADMIN_AWARDED"))
def test_played_regulation_facts_can_grade_despite_later_administrative_status(
    status: str,
) -> None:
    from matchvet.t10 import SettlementGrader

    grades = SettlementGrader().grade_all(
        (
            _evidence(
                fixture_status=status,
                regulation_completed=True,
                full_time_home_goals=2,
                full_time_away_goals=1,
            ),
        )
    )

    assert grades[0].settlement_result == "WIN"
    assert all(grade.grading_state == "FINAL" for grade in grades)


def test_resumable_suspension_is_pending_then_grades_the_continuation() -> None:
    from matchvet.t10 import SettlementGrader

    grader = SettlementGrader()
    pending = grader.grade_all(
        (_evidence(fixture_status="SUSPENDED", regulation_completed=False, resumable=True),)
    )
    assert all(grade.grading_state == "PENDING" for grade in pending)
    assert all(grade.settlement_result is None for grade in pending)
    completed = _evidence(
        record_id="fd-t10-continuation",
        fixture_status="COMPLETED",
        regulation_completed=True,
        full_time_home_goals=2,
        full_time_away_goals=1,
        half_time_home_goals=1,
        half_time_away_goals=0,
    )
    grades = grader.grade_all((completed,))
    assert all(grade.grading_state == "FINAL" for grade in grades)
    assert grades[0].settlement_result == "WIN"


def test_abandoned_match_is_void_even_if_a_line_was_already_crossed() -> None:
    from matchvet.t10 import SettlementGrader

    grades = SettlementGrader().grade_all(
        (_evidence(fixture_status="ABANDONED", regulation_completed=False),)
    )
    assert all(grade.settlement_result == "VOID" for grade in grades)


def test_invalid_half_relationship_is_pending_then_void_without_repair() -> None:
    from matchvet.t10 import SettlementGrader

    evidence = _evidence(full_time_home_goals=1, half_time_home_goals=2)
    grader = SettlementGrader()
    pending = grader.grade_all((evidence,))
    assert pending[0].settlement_result == "LOSS"
    assert pending[9].settlement_result is None
    assert pending[10].settlement_result is None
    assert pending[10].reason_code == "INVALID_PHASE_RELATIONSHIP"
    closed = grader.grade_all((evidence,), finalize=True)
    assert closed[0].settlement_result == "LOSS"
    assert closed[9].settlement_result == "VOID"
    assert closed[10].settlement_result == "VOID"


def test_source_hierarchy_fallback_and_lower_conflict_are_retained_in_provenance() -> None:
    from matchvet.t10 import SettlementGrader

    official_goals = _evidence(
        source_level="COMPETITION",
        source_key="league-official",
        record_id="league-goals",
        record_set_id="league-set-1",
        full_time_home_goals=2,
        full_time_away_goals=0,
        corners_home=None,
        corners_away=None,
    )
    official_corners = _evidence(
        source_level="FEDERATION",
        source_key="federation-official",
        record_id="fed-corners",
        record_set_id="fed-set-1",
        full_time_home_goals=None,
        full_time_away_goals=None,
        half_time_home_goals=None,
        half_time_away_goals=None,
        corners_home=3,
        corners_away=3,
    )
    lower_conflict = _evidence(
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-conflict",
        full_time_home_goals=0,
        full_time_away_goals=4,
        half_time_home_goals=None,
        half_time_away_goals=None,
        corners_home=9,
        corners_away=0,
    )
    grader = SettlementGrader()
    goal_grade = grader.grade(
        "match_winner_home", (official_goals, official_corners, lower_conflict)
    )
    corner_grade = grader.grade(
        "corner_winner_draw", (official_goals, official_corners, lower_conflict)
    )
    assert goal_grade.settlement_result == "WIN"
    assert goal_grade.selected_source_level == "COMPETITION"
    assert goal_grade.selected_source_record_ids == ("league-goals",)
    considered = cast(
        tuple[Mapping[str, object], ...], goal_grade.provenance["considered_evidence"]
    )
    assert lower_conflict.evidence_id in {item["evidence_id"] for item in considered}
    assert corner_grade.settlement_result == "WIN"
    assert corner_grade.selected_source_level == "FEDERATION"
    assert corner_grade.selected_source_record_ids == ("fed-corners",)
    overridden = cast(
        tuple[Mapping[str, object], ...], corner_grade.provenance["overridden_evidence"]
    )
    assert any(item["record_id"] == "fd-conflict" for item in overridden)


@pytest.mark.parametrize("source_level", ("COMPETITION", "FEDERATION", "CLUB", "FOOTBALL_DATA"))
def test_corner_fallback_walks_the_complete_fixed_source_hierarchy(source_level: str) -> None:
    from matchvet.t10 import SettlementGrader

    levels = ("COMPETITION", "FEDERATION", "CLUB", "FOOTBALL_DATA")
    evidence = [
        _evidence(
            source_level=level,
            source_key=level.lower(),
            record_id=f"{level.lower()}-missing-corners",
            corners_home=None,
            corners_away=None,
        )
        for level in levels
    ]
    selected_index = levels.index(source_level)
    evidence[selected_index] = _evidence(
        source_level=source_level,
        source_key=source_level.lower(),
        record_id=f"{source_level.lower()}-complete-corners",
        corners_home=7,
        corners_away=2,
    )
    grade = SettlementGrader().grade("corner_winner_home", tuple(evidence))
    assert grade.settlement_result == "WIN"
    assert grade.selected_source_level == source_level
    assert grade.selected_source_record_ids == (f"{source_level.lower()}-complete-corners",)


def test_lower_ranked_conflict_does_not_displace_a_complete_higher_source() -> None:
    from matchvet.t10 import SettlementGrader

    higher = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-corners",
        corners_home=5,
        corners_away=2,
    )
    lower_one = _evidence(
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-corners-v1",
        record_set_id="fd-set",
        corners_home=1,
        corners_away=6,
    )
    lower_two = _evidence(
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-corners-v2",
        record_set_id="fd-set",
        corners_home=9,
        corners_away=0,
    )
    grade = SettlementGrader().grade("corner_winner_home", (higher, lower_one, lower_two))
    assert grade.settlement_result == "WIN"
    assert grade.selected_source_level == "COMPETITION"
    overridden = cast(tuple[Mapping[str, object], ...], grade.provenance["overridden_evidence"])
    assert {item["record_id"] for item in overridden} == {
        "fd-corners-v1",
        "fd-corners-v2",
    }


def test_reordering_unchanged_evidence_is_idempotent_at_the_pure_seam() -> None:
    from matchvet.t10 import SettlementGrader

    competition = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-score",
    )
    fallback = _evidence(
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-score",
        full_time_home_goals=0,
        full_time_away_goals=4,
    )
    grader = SettlementGrader()
    first = grader.grade("match_winner_home", (competition, fallback))
    second = grader.grade("match_winner_home", (fallback, competition))
    assert first == second


def test_same_rank_source_conflict_stays_pending_then_void() -> None:
    from matchvet.t10 import SettlementGrader

    first = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-v1",
        full_time_home_goals=2,
    )
    second = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-v2",
        full_time_home_goals=0,
    )
    grader = SettlementGrader()
    pending = grader.grade("match_winner_home", (first, second))
    assert pending.grading_state == "PENDING"
    assert pending.reason_code == "SOURCE_CONFLICT"
    assert pending.settlement_result is None
    closed = grader.grade("match_winner_home", (first, second), finalize=True)
    assert closed.grading_state == "FINAL"
    assert closed.settlement_result == "VOID"
    conflict_ids = cast(tuple[str, ...], pending.provenance["conflict_evidence_ids"])
    assert set(conflict_ids) == {
        first.evidence_id,
        second.evidence_id,
    }


def test_conflicting_records_inside_one_official_record_set_stay_pending() -> None:
    from matchvet.t10 import SettlementGrader

    first = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-score-v1",
        record_set_id="league-revision-1",
        full_time_home_goals=2,
    )
    second = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-score-v1-page-2",
        record_set_id="league-revision-1",
        full_time_home_goals=1,
    )
    lower = _evidence(
        source_level="FOOTBALL_DATA",
        source_key="football-data",
        record_id="fd-replacement",
        full_time_home_goals=0,
        full_time_away_goals=1,
    )
    grade = SettlementGrader().grade("match_winner_home", (first, second, lower))
    assert grade.grading_state == "PENDING"
    assert grade.reason_code == "SOURCE_CONFLICT"


def test_explicit_source_successor_controls_over_its_superseded_record() -> None:
    from matchvet.t10 import SettlementGrader

    original = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-score-v1",
        full_time_home_goals=2,
        full_time_away_goals=0,
    )
    successor = _evidence(
        source_level="COMPETITION",
        source_key="league",
        record_id="league-score-v2",
        full_time_home_goals=0,
        full_time_away_goals=1,
        predecessor_id=original.evidence_id,
    )

    grade = SettlementGrader().grade("match_winner_home", (original, successor))

    assert grade.settlement_result == "LOSS"
    assert grade.selected_source_record_ids == ("league-score-v2",)
    superseded = cast(tuple[Mapping[str, object], ...], grade.provenance["superseded_evidence"])
    assert tuple(item["record_id"] for item in superseded) == ("league-score-v1",)


def test_withdrawn_frozen_recommendation_is_void_without_changing_prediction_reference() -> None:
    from matchvet.t10 import FrozenRecommendation, SettlementGrader

    frozen = FrozenRecommendation(
        recommendation_id="recommendation-1",
        fixture_id="fixture-t10",
        preference_id="match_winner_home",
        matchweek_id="2026-09-11",
        prediction_digest="prediction-frozen",
        frozen_evidence_digest="evidence-frozen",
    )
    grade = SettlementGrader().grade(
        "match_winner_home",
        (_evidence(fixture_status="POSTPONED", regulation_completed=False),),
        frozen_recommendation=frozen,
        withdrawn=True,
    )
    assert grade.settlement_result == "VOID"
    assert grade.reason_code == "WITHDRAWN_RECOMMENDATION"
    assert grade.prediction_digest == "prediction-frozen"
    assert grade.frozen_evidence_digest == "evidence-frozen"
    assert grade.matchweek_id == "2026-09-11"
    assert grade.recommendation_id == "recommendation-1"


def test_t09_historical_match_can_be_adapted_without_losing_provenance() -> None:
    from matchvet.t09 import HistoricalMatch
    from matchvet.t10 import SettlementEvidence, SettlementGrader

    historical = HistoricalMatch(
        fixture_id="fixture-t09",
        home_team_id="team-home",
        away_team_id="team-away",
        kickoff_utc="2026-09-12T15:00:00Z",
        source_key="football-data",
        source_digest="d" * 64,
        fixture_status="COMPLETED",
        full_time_home_goals=2,
        full_time_away_goals=0,
        half_time_home_goals=1,
        half_time_away_goals=0,
        corners_home=5,
        corners_away=2,
    )
    evidence = SettlementEvidence.from_historical_match(historical)
    grade = SettlementGrader().grade("match_winner_home", (historical,))
    assert evidence.source_digest == historical.source_digest
    assert grade.selected_source_level == "FOOTBALL_DATA"
    assert grade.selected_source_record_ids == ("fixture-t09",)


def test_t09_unknown_and_absent_metrics_do_not_become_observed_grading_facts() -> None:
    from matchvet.evidence import EvidenceState
    from matchvet.t09 import HistoricalMatch
    from matchvet.t10 import SettlementEvidence, SettlementGrader

    historical = HistoricalMatch(
        fixture_id="fixture-t09-metric-states",
        home_team_id="team-home",
        away_team_id="team-away",
        kickoff_utc="2026-09-12T15:00:00Z",
        source_key="football-data",
        source_digest="e" * 64,
        fixture_status="COMPLETED",
        full_time_home_goals=2,
        full_time_away_goals=1,
        half_time_home_goals=1,
        half_time_away_goals=0,
        corners_home=6,
        corners_away=4,
        source_assertion_ids=("source-assertion",),
        metric_states={
            "corners_home": EvidenceState.UNKNOWN,
            "corners_away": EvidenceState.ABSENT,
        },
    )
    evidence = SettlementEvidence.from_historical_match(historical)
    grades = SettlementGrader().grade_all((historical,))

    assert evidence.full_time_home_goals == 2
    assert evidence.corners_home is None
    assert evidence.corners_away is None
    assert grades[0].settlement_result == "WIN"
    assert grades[15].grading_state == "PENDING"
    assert grades[15].settlement_result is None
    assert "metric_states" in evidence.provenance


def test_append_only_idempotence_and_correction_preserve_frozen_fields(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import (
        FrozenRecommendation,
        SettlementGrader,
        SettlementGradeRecorder,
        T10IntegrityError,
    )

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        grader = SettlementGrader()
        frozen = FrozenRecommendation(
            recommendation_id="recommendation-1",
            fixture_id="fixture-t10",
            preference_id="match_winner_home",
            matchweek_id="mw-1",
            prediction_digest="prediction-frozen",
            frozen_evidence_digest="evidence-frozen",
        )
        first_evidence = _evidence(
            source_level="COMPETITION", source_key="league", record_id="league-v1"
        )
        first = grader.grade("match_winner_home", (first_evidence,), frozen_recommendation=frozen)
        saved_first = recorder.record(first)
        assert recorder.record(first).grade_id == saved_first.grade_id
        assert len(recorder.grades()) == 1
        correction_evidence = _evidence(
            source_level="COMPETITION",
            source_key="league",
            record_id="league-v2",
            full_time_home_goals=0,
            full_time_away_goals=1,
            predecessor_id=first_evidence.evidence_id,
        )
        correction = grader.grade(
            "match_winner_home", (correction_evidence,), frozen_recommendation=frozen
        )
        saved_correction = recorder.record(correction)
        assert saved_correction.settlement_result == "LOSS"
        assert saved_correction.correction_sequence == 1
        assert saved_correction.predecessor_grade_id == saved_first.grade_id
        assert (
            recorder.current_grade(
                "fixture-t10",
                "match_winner_home",
                matchweek_id="mw-1",
                recommendation_id="recommendation-1",
            )
            == saved_correction
        )
        history = recorder.grades(fixture_id="fixture-t10")
        assert tuple(item.grade_id for item in history) == (
            saved_first.grade_id,
            saved_correction.grade_id,
        )
        assert all(item.prediction_digest == "prediction-frozen" for item in history)
        assert len(recorder.evidence_sets("fixture-t10")) == 2
        with pytest.raises(T10IntegrityError, match="Frozen prediction"):
            recorder.record(
                grader.grade(
                    "match_winner_home",
                    (correction_evidence,),
                    frozen_recommendation=replace(frozen, prediction_digest="prediction-changed"),
                )
            )


def test_lower_authority_late_record_cannot_replace_current_grade(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import SettlementGrader, SettlementGradeRecorder

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        grader = SettlementGrader()
        official = _evidence(
            source_level="COMPETITION",
            source_key="league",
            record_id="league-v1",
            full_time_home_goals=2,
            full_time_away_goals=0,
        )
        saved = recorder.record(grader.grade("match_winner_home", (official,)))
        lower = _evidence(
            source_level="FOOTBALL_DATA",
            source_key="football-data",
            record_id="fd-late",
            full_time_home_goals=0,
            full_time_away_goals=2,
        )
        returned = recorder.record(grader.grade("match_winner_home", (lower,)))
        assert returned == saved
        assert len(recorder.grades()) == 1
        assert len(recorder.evidence_sets("fixture-t10")) == 2


def test_lower_authority_late_record_cannot_break_persisted_high_conflict(
    tmp_path: Path,
) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import SettlementGrader, SettlementGradeRecorder

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        grader = SettlementGrader()
        high_one = _evidence(
            source_level="COMPETITION",
            source_key="league",
            record_id="league-v1",
            full_time_home_goals=2,
            full_time_away_goals=0,
        )
        high_two = _evidence(
            source_level="COMPETITION",
            source_key="league",
            record_id="league-v2",
            full_time_home_goals=0,
            full_time_away_goals=2,
        )
        pending = recorder.record(grader.grade("match_winner_home", (high_one, high_two)))
        lower = _evidence(
            source_level="FOOTBALL_DATA",
            source_key="football-data",
            record_id="fd-late",
            full_time_home_goals=1,
            full_time_away_goals=0,
        )

        returned = recorder.record(grader.grade("match_winner_home", (lower,)))

        assert returned == pending
        assert returned.grading_state == "PENDING"
        assert len(recorder.grades()) == 1
        assert len(recorder.evidence_sets("fixture-t10")) == 3


def test_transaction_rollback_removes_evidence_and_grades_on_failure(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import SettlementGrader, SettlementGradeRecorder

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        grades = SettlementGrader().grade_all((_evidence(),))

        def fail_on_second(index: int) -> None:
            if index == 2:
                raise RuntimeError("injected T10 failure")

        with pytest.raises(RuntimeError, match="injected T10 failure"):
            recorder.record_many(grades, failure_hook=fail_on_second)
        assert recorder.grades() == ()
        assert recorder.evidence_sets() == ()
        connection = sqlite3.connect(private_root / "matchvet.sqlite3")
        assert connection.execute("SELECT COUNT(*) FROM settlement_grades").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM settlement_evidence_sets").fetchone() == (
            0,
        )
        connection.close()


def test_append_only_tables_reject_direct_mutation(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import SettlementGrader, SettlementGradeRecorder

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        saved = recorder.record(SettlementGrader().grade("match_winner_home", (_evidence(),)))
        connection = sqlite3.connect(private_root / "matchvet.sqlite3")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE settlement_grades SET reason = 'tampered' WHERE grade_id = ?",
                (saved.grade_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM settlement_evidence_sets WHERE evidence_set_id = ?",
                (_evidence().evidence_id,),
            )
        connection.close()


def test_frozen_prediction_digest_cannot_be_changed_by_regrade(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t10 import (
        FrozenRecommendation,
        SettlementGrader,
        SettlementGradeRecorder,
        T10IntegrityError,
    )

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = SettlementGradeRecorder(store)
        grader = SettlementGrader()
        frozen = FrozenRecommendation(
            recommendation_id="recommendation-1",
            fixture_id="fixture-t10",
            preference_id="match_winner_home",
            prediction_digest="prediction-frozen",
        )
        recorder.record(
            grader.grade("match_winner_home", (_evidence(),), frozen_recommendation=frozen)
        )
        changed = replace(frozen, frozen_evidence_digest="changed-frozen-evidence")
        with pytest.raises(T10IntegrityError, match="Frozen frozen evidence"):
            recorder.record(
                grader.grade(
                    "match_winner_home",
                    (_evidence(record_id="fd-v2"),),
                    frozen_recommendation=changed,
                )
            )


def test_cli_grades_a_recorded_json_evidence_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from matchvet.cli import main

    input_path = tmp_path / "fixture-evidence.json"
    input_path.write_text(
        json.dumps(
            {
                "fixture_id": "fixture-cli",
                "evidence": [_evidence(fixture_id="fixture-cli").to_dict()],
            }
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "private" / "matchvet.sqlite3"
    result = main(
        (
            "grade",
            "--input",
            str(input_path),
            "--store",
            str(database_path),
            "--json",
        )
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["catalog_count"] == 37
    assert output["fixture_id"] == "fixture-cli"
    assert output["grading_state_counts"] == {"FINAL": 37, "PENDING": 0}
    assert output["settlement_counts"] == {"LOSS": 17, "PUSH": 2, "VOID": 0, "WIN": 18}

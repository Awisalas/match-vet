from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from matchvet.matchweek import FrozenMembership, MatchweekFreeze
    from matchvet.store import Store
    from matchvet.t09 import EvidenceResearchInput, HistoricalMatch, SourceFact, TargetMatch


def _target() -> TargetMatch:
    from matchvet.t09 import TargetMatch

    return TargetMatch(
        matchweek_id="mw-1",
        cutoff_id="cutoff-1",
        fixture_id="fixture-target",
        cutoff_utc="2026-09-18T12:00:00+00:00",
        kickoff_utc="2026-09-18T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
        venue_id="venue-1",
        venue_name="Example Stadium",
    )


def _history(*, missing: tuple[str, ...] = ()) -> tuple[HistoricalMatch, ...]:
    from matchvet.t09 import HistoricalMatch

    rows: list[HistoricalMatch] = []
    for index, (day, home_goals, away_goals, home_corners, away_corners) in enumerate(
        (
            ("2026-09-01T20:00:00+00:00", 1, 0, 5, 2),
            ("2026-08-20T20:00:00+00:00", 2, 1, 6, 4),
            ("2026-07-20T20:00:00+00:00", 0, 0, 3, 5),
            ("2026-05-20T20:00:00+00:00", 3, 1, 7, 2),
        ),
        start=1,
    ):
        rows.append(
            HistoricalMatch(
                fixture_id=f"history-{index}",
                home_team_id="team-home" if index % 2 else "team-away",
                away_team_id="team-away" if index % 2 else "team-home",
                kickoff_utc=day,
                full_time_home_goals=None if "goals" in missing else home_goals,
                full_time_away_goals=None if "goals" in missing else away_goals,
                half_time_home_goals=None if "half_goals" in missing else max(0, home_goals - 1),
                half_time_away_goals=None if "half_goals" in missing else away_goals,
                corners_home=None if "corners" in missing else home_corners,
                corners_away=None if "corners" in missing else away_corners,
                source_assertion_ids=(f"structured-{index}",),
                source_digest=f"digest-{index}",
                source_key="football-data",
                origin_id="origin-football-data",
            )
        )
    return tuple(rows)


def _input(**changes: object) -> EvidenceResearchInput:
    from matchvet.t09 import EvidenceResearchInput

    value = EvidenceResearchInput(target=_target(), history=_history())
    return replace(value, **cast(Any, changes))


def _completed_mandatory_research() -> tuple[Any, ...]:
    from matchvet.t09 import DEFAULT_CATALOG, ResearchAttempt

    target = _target()
    return tuple(
        ResearchAttempt(
            requirement_id=requirement.requirement_id,
            category="MANDATORY_RESEARCH",
            source_key=requirement.source_priority,
            attempted_at_utc=target.cutoff_utc,
            accessibility="ACCESSIBLE",
            outcome="OBSERVED",
            reason="Test fixture records a completed cutoff scan.",
        )
        for requirement in DEFAULT_CATALOG.mandatory()
    )


def _fact(
    fact_id: str,
    *,
    value: object | None,
    state: str = "OBSERVED",
    evidence_type: str = "AVAILABILITY",
    predicate: str = "status",
    origin_id: str | None = "origin-a",
    source_key: str = "club-a",
    published: str | None = "2026-09-18T08:00:00+00:00",
    observed: str = "2026-09-18T08:01:00+00:00",
    effective: str | None = None,
    correlation_group: str = "personnel",
) -> SourceFact:
    from matchvet.t09 import SourceFact

    return SourceFact(
        fact_id=fact_id,
        subject_id="fixture-target",
        evidence_type=evidence_type,
        predicate=predicate,
        state=state,
        value=value,
        source_key=source_key,
        origin_id=origin_id,
        source_assertion_ids=(fact_id,),
        source_digest=f"{fact_id:0<64}"[:64],
        published_at_utc=published,
        observed_at_utc=observed,
        effective_time_utc=effective,
        cutoff_eligibility="CUTOFF_VALID",
        correlation_groups=(correlation_group,),
        affirmative_basis=("AFFIRMATIVE_SOURCE_RECORD" if state == "ABSENT" else None),
        unknown_reason=("SOURCE_NOT_FOUND_AFTER_SEARCH" if state == "UNKNOWN" else None),
    )


def test_catalog_separates_mandatory_research_from_critical_evidence() -> None:
    from matchvet.t09 import EVIDENCE_REQUIREMENT_CATALOG_V1, EvidenceClass

    manager = EVIDENCE_REQUIREMENT_CATALOG_V1.requirement("E-MANAGER")
    fixture = EVIDENCE_REQUIREMENT_CATALOG_V1.requirement("M-FIXTURE")

    assert manager.mandatory_research is True
    assert manager.evidence_class is EvidenceClass.IMPORTANT
    assert fixture.mandatory_research is True
    assert fixture.evidence_class is EvidenceClass.CRITICAL
    assert (
        EVIDENCE_REQUIREMENT_CATALOG_V1.requirement("M-PENALTY-EVENT").mandatory_research is False
    )
    assert (
        EVIDENCE_REQUIREMENT_CATALOG_V1.requirement("M-PROVIDER-XG").evidence_class
        is EvidenceClass.CONTEXT
    )
    assert (
        EVIDENCE_REQUIREMENT_CATALOG_V1.requirement("E-REFEREE-CONTEXT").evidence_class
        is EvidenceClass.CONTEXT
    )
    assert EVIDENCE_REQUIREMENT_CATALOG_V1.version == "1.0.0"


def test_cutoff_leakage_and_unknown_absent_are_distinct() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceState

    facts = (
        _fact("available", value="AVAILABLE"),
        _fact(
            "post-cutoff",
            value="OUT",
            published="2026-09-18T13:00:00+00:00",
            observed="2026-09-18T13:01:00+00:00",
        ),
        _fact("unknown", value=None, state="UNKNOWN", origin_id=None),
        _fact("absent", value=None, state="ABSENT", origin_id="origin-b"),
    )
    result = EvidenceResearcher().build(_input(source_assertions=facts))

    included = {item.fact_id: item for item in result.source_assertions}
    assert included["available"].state is EvidenceState.OBSERVED
    assert included["unknown"].state is EvidenceState.UNKNOWN
    assert included["absent"].state is EvidenceState.ABSENT
    assert "post-cutoff" not in included
    assert {item.fact_id for item in result.post_cutoff_assertions} == {"post-cutoff"}
    assert included["unknown"].value is None
    assert included["absent"].value is None


def test_indeterminate_and_post_cutoff_context_never_becomes_derived_input() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceState

    indeterminate = replace(
        _fact("indeterminate", value=None, state="UNKNOWN", origin_id=None),
        cutoff_eligibility="INDETERMINATE",
        observed_at_utc=None,
        published_at_utc=None,
    )
    result = EvidenceResearcher().build(
        _input(
            source_assertions=(indeterminate,),
            workload={
                "workload_evidence_id": "workload-post",
                "state": "OBSERVED",
                "cutoff_eligibility": "POST_CUTOFF",
                "cutoff_utc": "2026-09-18T13:00:00+00:00",
                "home": {"rest_days": 1.0},
                "away": {"rest_days": 1.0},
            },
            weather={
                "weather_evidence_id": "weather-post",
                "state": "OBSERVED",
                "cutoff_eligibility": "POST_CUTOFF",
                "retrieved_at_utc": "2026-09-18T13:00:00+00:00",
                "values": {"temperature_2m": 40.0},
            },
        )
    )

    assert {item.fact_id for item in result.post_cutoff_assertions} == {
        "indeterminate",
        "weather-post",
        "workload-post",
    }
    features = {item.name: item for item in result.derived_features}
    assert features["D-REST"].state is EvidenceState.UNKNOWN
    assert features["D-REST"].input_ids == ()
    assert features["M-WEATHER"].state is EvidenceState.UNKNOWN
    assert features["M-WEATHER"].input_ids == ()


def test_future_effective_time_can_be_announced_before_cutoff_but_fixture_state_cannot() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceState

    announced = _fact(
        "future-availability",
        value="AVAILABLE",
        effective=_target().kickoff_utc,
    )
    result = EvidenceResearcher().build(_input(source_assertions=(announced,)))
    assert {item.fact_id for item in result.source_assertions} >= {
        "future-availability",
        "fixture-target:M-FIXTURE",
    }

    postponed = EvidenceResearcher().build(
        replace(_input(), target=replace(_target(), fixture_status="POSTPONED"))
    )
    fixture_evaluation = next(
        item
        for item in postponed.requirement_evaluations
        if item.family == "Match Winner" and item.requirement_id == "M-FIXTURE"
    )
    assert fixture_evaluation.state is EvidenceState.UNKNOWN
    assert fixture_evaluation.covered is False


def test_source_provenance_is_required_and_cutoff_metadata_is_authoritative() -> None:
    from matchvet.t09 import EvidenceResearcher, SourceFact, T09ValidationError

    with pytest.raises(T09ValidationError, match="provenance"):
        SourceFact(
            fact_id="unproven-source",
            subject_id="fixture-target",
            evidence_type="AVAILABILITY",
            predicate="status",
            state="OBSERVED",
            value="AVAILABLE",
            source_key="source",
        )

    result = EvidenceResearcher().build(
        _input(
            reproducibility={
                "cutoff_utc": "2099-01-01T00:00:00+00:00",
                "input_source_fact_ids": ("post-cutoff",),
            }
        )
    )
    assert result.reproducibility["cutoff_utc"] == _target().cutoff_utc
    assert result.reproducibility["input_source_fact_ids"] == tuple(
        item.fact_id for item in result.source_assertions
    )


def test_freshness_age_conflicts_and_independent_corroboration() -> None:
    from matchvet.t09 import EvidenceResearcher, FreshnessState

    facts = (
        _fact("a", value="OUT", origin_id="origin-a", source_key="club-a"),
        _fact("b", value="OUT", origin_id="origin-a", source_key="syndicated-b"),
        _fact("c", value="OUT", origin_id="origin-b", source_key="club-b"),
        _fact("d", value="AVAILABLE", origin_id="origin-c", source_key="club-c"),
        _fact(
            "stale",
            value="OUT",
            effective="2026-09-01T08:00:00+00:00",
            published="2026-09-01T08:00:00+00:00",
            observed="2026-09-01T08:01:00+00:00",
        ),
    )
    result = EvidenceResearcher().build(
        _input(
            source_assertions=facts,
            last_material_event_by_team={
                "team-home": "2026-09-10T20:00:00+00:00",
            },
        )
    )

    stale = next(item for item in result.source_assertions if item.fact_id == "stale")
    assert stale.freshness is FreshnessState.STALE
    assert stale.age_seconds_at_cutoff is not None
    assert stale.age_seconds_at_kickoff is not None
    assert any(conflict.status == "UNRESOLVED" for conflict in result.conflicts)
    corroboration = next(item for item in result.corroboration if item.value == "OUT")
    assert corroboration.independent_origin_count == 2
    assert corroboration.correlated_assertion_ids == ("a", "b")

    shared_row = EvidenceResearcher().build(
        _input(
            source_assertions=(
                replace(
                    _fact("shared-a", value="OUT", origin_id="origin-shared-a"),
                    predicate="source_row_status",
                    source_row_key="upstream-row-1",
                    source_assertion_ids=("upstream-row-1",),
                ),
                replace(
                    _fact("shared-b", value="OUT", origin_id="origin-shared-b"),
                    predicate="source_row_status",
                    source_row_key="upstream-row-1",
                    source_assertion_ids=("upstream-row-1",),
                ),
            )
        )
    )
    assert not any(item.predicate == "source_row_status" for item in shared_row.corroboration)


def test_critical_coverage_marks_missing_history_as_model_unavailable() -> None:
    from matchvet.t09 import EvidenceResearcher, ResearchStatus

    result = EvidenceResearcher().build(
        _input(
            history=_history(missing=("corners", "half_goals")),
            mandatory_research=_completed_mandatory_research(),
        )
    )

    assert result.research_sufficiency["Match Winner"].status is ResearchStatus.SUFFICIENT
    assert (
        result.research_sufficiency["Full-Match Total Corners Over"].status
        is ResearchStatus.MODEL_UNAVAILABLE
    )
    assert result.research_sufficiency["First-Half Over"].status is ResearchStatus.MODEL_UNAVAILABLE
    assert result.critical_evidence_coverage["Match Winner"].complete is True
    assert result.critical_evidence_coverage["Full-Match Total Corners Over"].complete is False


def test_conditional_criticality_is_explicit_and_blocks_affected_family() -> None:
    from matchvet.t09 import EvidenceResearcher, MaterialScenario, ResearchStatus

    scenario = MaterialScenario(
        scenario_id="storm",
        family="Match Goals Over",
        requirement_id="M-WEATHER",
        description="A severe storm could move the acceptance boundary.",
    )
    result = EvidenceResearcher().build(
        _input(
            material_scenarios=(scenario,),
            source_assertions=(),
        )
    )

    coverage = result.critical_evidence_coverage["Match Goals Over"]
    assert "M-WEATHER" in coverage.conditional_requirements
    assert coverage.complete is False
    assert result.research_sufficiency["Match Goals Over"].status is ResearchStatus.INSUFFICIENT
    assert any(gap.requirement_id == "M-WEATHER" for gap in result.gaps)


def test_resolved_and_stale_material_conflicts_are_retained_without_duplicate_confirmation() -> (
    None
):
    from matchvet.t09 import CoverageState, EvidenceResearcher, MaterialScenario

    scenario = MaterialScenario(
        scenario_id="availability-scenario",
        family="Match Winner",
        requirement_id="E-AVAILABILITY",
        description="Availability could change the acceptance boundary.",
    )
    facts = (
        _fact("conflict-a", value="OUT", origin_id="origin-a"),
        _fact("conflict-b", value="AVAILABLE", origin_id="origin-b"),
    )
    unresolved = EvidenceResearcher().build(
        _input(source_assertions=facts, material_scenarios=(scenario,))
    )
    conflict = unresolved.conflicts[0]
    evaluation = next(
        item
        for item in unresolved.requirement_evaluations
        if item.family == "Match Winner" and item.requirement_id == "E-AVAILABILITY"
    )
    assert evaluation.status is CoverageState.CONFLICT

    resolved = EvidenceResearcher().build(
        _input(
            source_assertions=facts,
            material_scenarios=(scenario,),
            mandatory_research=_completed_mandatory_research(),
            conflict_resolutions={
                conflict.conflict_id: {
                    "selected_assertion_id": "conflict-a",
                    "basis": ("SOURCE_AUTHORITY",),
                }
            },
        )
    )
    resolved_evaluation = next(
        item
        for item in resolved.requirement_evaluations
        if item.family == "Match Winner" and item.requirement_id == "E-AVAILABILITY"
    )
    assert resolved.conflicts[0].status == "RESOLVED"
    assert resolved_evaluation.status is CoverageState.COVERED

    stale = EvidenceResearcher().build(
        _input(
            source_assertions=facts,
            last_material_event_by_team={
                "fixture-target": "2026-09-18T09:00:00+00:00",
            },
        )
    )
    assert stale.conflicts[0].status == "UNRESOLVED"


def test_h2h_requires_all_comparability_checks_before_it_is_retained_as_context() -> None:
    from matchvet.t09 import CoverageState, EvidenceResearcher

    checks = {key: True for key in ("manager", "personnel", "tactics", "venue", "matchup")}
    not_comparable = _fact(
        "h2h-not-comparable",
        value={"comparable": False, "comparability_checks": checks},
        evidence_type="HEAD_TO_HEAD",
        predicate="comparability",
        correlation_group="head-to-head",
    )
    comparable = replace(
        not_comparable,
        fact_id="h2h-comparable",
        value={"comparable": True, "comparability_checks": checks},
        source_assertion_ids=("h2h-comparable",),
        source_digest="h2h-comparable".ljust(64, "0"),
    )
    incomplete = EvidenceResearcher().build(
        _input(
            source_assertions=(not_comparable,),
            mandatory_research=_completed_mandatory_research(),
        )
    )
    incomplete_evaluation = next(
        item
        for item in incomplete.requirement_evaluations
        if item.family == "Match Winner" and item.requirement_id == "E-HEAD-TO-HEAD"
    )
    assert incomplete_evaluation.status is CoverageState.UNKNOWN
    assert incomplete_evaluation.covered is False

    complete = EvidenceResearcher().build(
        _input(
            source_assertions=(comparable,),
            mandatory_research=_completed_mandatory_research(),
        )
    )
    complete_evaluation = next(
        item
        for item in complete.requirement_evaluations
        if item.family == "Match Winner" and item.requirement_id == "E-HEAD-TO-HEAD"
    )
    assert complete_evaluation.status is CoverageState.COVERED


def test_features_retain_lineage_and_integrate_trend_workload_weather() -> None:
    from matchvet.t09 import EvidenceResearcher

    result = EvidenceResearcher().build(
        _input(
            workload={
                "workload_evidence_id": "workload-1",
                "state": "OBSERVED",
                "home": {"rest_days": 2.0, "schedule_density": {"7": 3}, "congestion_windows": [1]},
                "away": {"rest_days": 5.0, "schedule_density": {"7": 1}, "congestion_windows": []},
            },
            weather={
                "weather_evidence_id": "weather-1",
                "state": "OBSERVED",
                "cutoff_eligibility": "CUTOFF_VALID",
                "retrieved_at_utc": "2026-09-18T10:00:00+00:00",
                "forecast_issue_time_utc": "2026-09-18T09:00:00+00:00",
                "values": {"temperature_2m": 36.0, "wind_speed_10m": 60.0},
            },
        )
    )

    features = {feature.name: feature for feature in result.derived_features}
    assert features["D-OPPONENT-STRENGTH"].input_ids
    assert features["D-VENUE-EFFECT"].input_ids
    assert features["D-RECENCY-STRENGTH"].input_ids
    assert features["D-FORM-HORIZONS"].input_ids
    assert features["D-TREND-DIRECTION"].input_ids
    rest_value = cast(dict[str, object], features["D-REST"].value)
    congestion_value = cast(dict[str, object], features["D-CONGESTION"].value)
    weather_value = cast(dict[str, object], features["M-WEATHER"].value)
    assert rest_value["home"] == 2.0
    assert cast(dict[str, object], congestion_value["home"])["count"] == 1
    assert features["D-CROSS-COMP-WORKLOAD"].input_ids == ("workload-1",)
    assert features["D-REST"].input_digests
    assert features["D-CONGESTION"].input_digests
    assert features["D-CROSS-COMP-WORKLOAD"].input_digests
    assert weather_value["temperature_2m"] == 36.0
    assert features["M-WEATHER"].input_ids == ("weather-1",)
    assert features["M-WEATHER"].input_digests
    opponent_value = cast(dict[str, object], features["D-OPPONENT-STRENGTH"].value)
    home_opponent = cast(dict[str, object], opponent_value["team-home"])
    home_corners = cast(dict[str, object], home_opponent["corners"])
    assert home_corners["matches"] == 4
    assert "structured-1" in features["D-OPPONENT-STRENGTH"].input_ids
    score_value = cast(dict[str, object], features["D-SCORE-STATE"].value)
    home_score = cast(dict[str, object], score_value["home"])
    assert home_score["goal_margin_matches"] == 4
    assert features["D-SCORE-STATE"].input_ids
    assert any(
        scenario.requirement_id == "M-WEATHER" and scenario.family == "Match Goals Over"
        for scenario in result.material_scenarios
    )


def test_match_state_and_regime_changes_do_not_invent_adjusted_history() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceState

    history = tuple(
        replace(
            item,
            red_cards_home=1 if item.fixture_id == "history-1" else 0,
            red_card_minutes=("20",) if item.fixture_id == "history-1" else (),
        )
        for item in _history()
    )
    regime = _fact(
        "regime",
        value={"manager": "new-manager", "regime_start_utc": "2026-08-01T00:00:00+00:00"},
        evidence_type="REGIME_CHANGE",
        predicate="active_regime",
        effective="2026-08-01T00:00:00+00:00",
        origin_id="origin-club",
        source_key="club-home",
    )
    result = EvidenceResearcher().build(_input(history=history, source_assertions=(regime,)))

    state_feature = next(item for item in result.derived_features if item.name == "D-SCORE-STATE")
    regime_feature = next(
        item for item in result.derived_features if item.name == "E-TACTICAL-REGIME"
    )
    assert state_feature.state is EvidenceState.OBSERVED
    state_value = cast(dict[str, object], state_feature.value)
    regime_value = cast(dict[str, object], regime_feature.value)
    assert state_value["timing_known"] is True
    assert regime_value["regime_start_utc"] == "2026-08-01T00:00:00.000000+00:00"
    assert all(item.value is not None for item in result.derived_features if item.input_ids)


def test_frozen_digest_is_deterministic_and_incomplete_research_is_unsafe() -> None:
    from matchvet.t09 import EvidenceResearcher, ResearchStatus

    first = EvidenceResearcher().build(_input())
    second = EvidenceResearcher().build(
        replace(
            _input(),
            source_assertions=tuple(reversed(_input().source_assertions)),
            history=tuple(reversed(_history())),
        )
    )
    assert first.digest == second.digest
    assert first.to_bytes() == second.to_bytes()
    assert first.research_attempts
    assert all(not attempt.performed for attempt in first.research_attempts)
    assert first.safe_for_decision is False

    incomplete = EvidenceResearcher().build(_input(mandatory_research=()))
    assert incomplete.safe_for_decision is False
    assert all(
        item.status is ResearchStatus.INSUFFICIENT
        for item in incomplete.research_sufficiency.values()
    )
    assert all(item.gap_ids for item in first.requirement_evaluations if not item.covered)


@pytest.mark.parametrize(
    ("competition_key", "competition_name"),
    (
        ("premier_league", "Premier League"),
        ("serie_a", "Serie A"),
        ("la_liga", "La Liga"),
        ("bundesliga", "Bundesliga"),
        ("ligue_1", "Ligue 1"),
        ("liga_portugal", "Liga Portugal"),
        ("belgian_pro_league", "Belgian Pro League"),
    ),
)
def test_target_league_evidence_state_smoke(competition_key: str, competition_name: str) -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput, ResearchStatus

    home_team = f"{competition_key}-home"
    away_team = f"{competition_key}-away"
    target = replace(
        _target(),
        matchweek_id=f"mw-{competition_key}",
        cutoff_id=f"cutoff-{competition_key}",
        fixture_id=f"fixture-{competition_key}",
        competition_key=competition_key,
        competition_name=competition_name,
        home_team_id=home_team,
        away_team_id=away_team,
    )
    history = tuple(
        replace(
            item,
            fixture_id=f"{competition_key}-{item.fixture_id}",
            home_team_id=home_team if item.home_team_id == "team-home" else away_team,
            away_team_id=home_team if item.away_team_id == "team-home" else away_team,
            source_assertion_ids=(f"{competition_key}-{item.source_assertion_ids[0]}",),
        )
        for item in _history()
    )
    state = EvidenceResearcher().build(
        EvidenceResearchInput(
            target=target,
            history=history,
            mandatory_research=_completed_mandatory_research(),
        )
    )

    assert state.research_sufficiency["Match Winner"].status is ResearchStatus.SUFFICIENT
    assert state.critical_evidence_coverage["Match Winner"].complete is True
    assert all(item.is_cutoff_valid for item in state.source_assertions)


def test_history_gaps_are_granular_and_force_model_unavailable_only_where_needed() -> None:
    from matchvet.t09 import EvidenceResearcher, ResearchStatus

    result = EvidenceResearcher().build(
        _input(
            history_complete=False,
            history_gaps=("corners",),
            mandatory_research=_completed_mandatory_research(),
        )
    )

    assert result.research_sufficiency["Match Winner"].status is ResearchStatus.SUFFICIENT
    assert (
        result.research_sufficiency["Full-Match Total Corners Over"].status
        is ResearchStatus.MODEL_UNAVAILABLE
    )
    assert result.material_scenarios == ()


def test_sparse_target_team_history_is_model_unavailable_without_silent_shared_fallback() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceState, ResearchStatus

    sparse_history = tuple(
        replace(
            item,
            home_team_id="team-opponent" if item.home_team_id == "team-away" else item.home_team_id,
            away_team_id="team-opponent" if item.away_team_id == "team-away" else item.away_team_id,
        )
        for item in _history()
    )
    result = EvidenceResearcher().build(
        _input(
            history=sparse_history,
            mandatory_research=_completed_mandatory_research(),
        )
    )

    opponent_feature = next(
        item for item in result.derived_features if item.name == "D-OPPONENT-STRENGTH"
    )
    assert opponent_feature.state is EvidenceState.UNKNOWN
    assert result.research_sufficiency["Match Winner"].status is ResearchStatus.MODEL_UNAVAILABLE


def test_inaccessible_mandatory_research_does_not_count_as_complete() -> None:
    from matchvet.t09 import EvidenceResearcher, ResearchStatus

    attempts = list(_completed_mandatory_research())
    attempts[0] = replace(
        attempts[0],
        accessibility="INACCESSIBLE",
        outcome="UNKNOWN",
        reason="The required source was unavailable.",
    )
    result = EvidenceResearcher().build(_input(mandatory_research=tuple(attempts)))

    assert all(
        item.status is ResearchStatus.INSUFFICIENT for item in result.research_sufficiency.values()
    )
    assert any(
        gap.accessibility.value == "INACCESSIBLE"
        for gap in result.gaps
        if gap.requirement_id == attempts[0].requirement_id
    )


def test_post_cutoff_mandatory_research_is_retained_but_cannot_satisfy_requirements() -> None:
    from matchvet.t09 import EvidenceResearcher, ResearchStatus

    attempts = list(_completed_mandatory_research())
    attempts[0] = replace(
        attempts[0],
        attempted_at_utc="2026-09-18T13:00:00+00:00",
        could_change_decision=True,
    )
    result = EvidenceResearcher().build(_input(mandatory_research=tuple(attempts)))

    post_attempt = next(
        item
        for item in result.research_attempts
        if item.requirement_id == attempts[0].requirement_id
    )
    assert str(post_attempt.cutoff_eligibility) == "POST_CUTOFF"
    assert all(
        item.status is ResearchStatus.INSUFFICIENT for item in result.research_sufficiency.values()
    )
    assert not any(
        scenario.requirement_id == attempts[0].requirement_id
        for scenario in result.material_scenarios
    )


def _integration_csv(div: str = "E0") -> bytes:
    return (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC,HS,AS,HST,AST,HY,AY,HR,AR\n"
        b"E0,01/09/2026,20:00,Arsenal,Chelsea,2,0,H,1,0,6,2,14,5,7,2,1,2,0,0\n"
        b"E0,20/08/2026,20:00,Chelsea,Arsenal,1,1,D,0,1,4,5,9,10,3,5,2,1,0,0\n"
        b"E0,20/07/2026,20:00,Arsenal,Liverpool,0,1,A,0,0,3,6,8,11,2,4,1,3,0,0\n"
        b"E0,20/05/2026,20:00,Liverpool,Arsenal,1,3,A,0,2,2,7,7,15,3,8,2,2,0,0\n"
        b"E0,18/09/2026,20:00,Arsenal,Coventry,,,,,,,,,,,,,,,\n"
    ).replace(b"E0,", f"{div},".encode())


def _integration_freeze(
    tmp_path: Path, *, league_key: str = "premier_league"
) -> tuple[Store, MatchweekFreeze]:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import freeze_matchweek
    from matchvet.store import open_store

    league = league_by_key(league_key)
    content = _integration_csv(league.football_data_code)
    store = open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path)
    FixtureHistoryImporter(store, private_root=tmp_path).import_dataset(
        FootballDataCSVParser().parse(
            content,
            league=league,
            season="2026-27",
        ),
        content,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-17T12:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    freeze = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    return store, freeze


def test_store_builder_publishes_manifest_and_restartable_frozen_state(tmp_path: Path) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.t09 import FrozenEvidenceStateRecorder, T09EvidenceBuilder

    store, freeze = _integration_freeze(tmp_path)
    result = T09EvidenceBuilder(store).build(freeze)

    assert len(result.states) == 1
    state = result.states[0]
    assert state.is_frozen is True
    assert state.manifest_digest == result.manifest.digest
    assert (
        ArtifactStore(store).verify_manifest(result.manifest.digest).digest
        == result.manifest.digest
    )
    reread = FrozenEvidenceStateRecorder(store).get(
        freeze.cutoff.matchweek_id, state.target_fixture_id
    )
    assert reread is not None
    assert reread.digest == state.digest
    assert reread.post_cutoff_assertions == ()
    store.close()


def test_store_builder_covers_all_seven_target_league_packs(tmp_path: Path) -> None:
    from matchvet.ingestion import TARGET_LEAGUES
    from matchvet.t09 import FrozenEvidenceStateRecorder, T09EvidenceBuilder

    for league in TARGET_LEAGUES:
        pack_dir = tmp_path / league.key
        pack_dir.mkdir()
        store, freeze = _integration_freeze(pack_dir, league_key=league.key)
        result = T09EvidenceBuilder(
            store,
            mandatory_research=_completed_mandatory_research(),
        ).build(freeze)

        assert len(result.states) == 1
        state = result.states[0]
        assert state.target.competition_key == league.key
        assert state.is_frozen
        reread = FrozenEvidenceStateRecorder(store).get(
            freeze.cutoff.matchweek_id, state.target_fixture_id
        )
        assert reread is not None
        assert reread.digest == state.digest
        store.close()


def test_runner_checkpoint_resume_requires_exact_digests(tmp_path: Path) -> None:
    from matchvet.runs import (
        ResourceObservation,
        RunLifecycleError,
        WorkInterrupted,
    )
    from matchvet.t09 import (
        ResearchAttempt,
        T09EvidenceRunner,
        T09Plan,
        build_t09_input_contract,
    )

    store, _ = _integration_freeze(tmp_path)
    observation = ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=8 * 1024 * 1024 * 1024,
        available_memory_bytes=2 * 1024 * 1024 * 1024,
        available_cpus=4,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )

    def interrupt(_index: int, _membership: FrozenMembership) -> None:
        raise WorkInterrupted("test checkpoint boundary")

    runner = T09EvidenceRunner(store)
    plan = T09Plan("2026-09-18")
    base_contract = build_t09_input_contract(store, plan)
    changed_contract = build_t09_input_contract(
        store,
        plan,
        mandatory_research=(
            ResearchAttempt(
                requirement_id="M-FIXTURE",
                category="MANDATORY_RESEARCH",
                source_key="test-source",
                attempted_at_utc="2026-09-18T11:00:00+00:00",
            ),
        ),
    )
    assert "source" in base_contract.differences(changed_contract)
    with pytest.raises(RunLifecycleError) as failure:
        runner.start(plan, observation=observation, failure_hook=interrupt)
    run_id = failure.value.run_id
    assert run_id

    with pytest.raises(RunLifecycleError, match="MV-RESUME-DIGEST_MISMATCH"):
        runner.resume(
            run_id,
            plan,
            observation=observation,
            model_availability={"Match Winner": False},
        )
    resumed = runner.resume(run_id, plan, observation=observation)
    assert resumed.state.value == "COMPLETE"
    assert runner.last_result is not None
    store.close()

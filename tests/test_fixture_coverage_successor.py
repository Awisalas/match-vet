from dataclasses import replace
from pathlib import Path

import pytest
from test_fixture_coverage import _complete_scope_inputs

from matchvet.active_fixture_coverage import (
    active_fixture_scopes_for_matchweek,
    assess_active_fixture_coverage,
)
from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.fixture_coverage import MatchweekScheduleState, ScopeCoverageState
from matchvet.fixture_coverage_codec import decode_f01, encode_f01


def test_successor_complete_and_exact_replay() -> None:
    scopes = active_fixture_scopes_for_matchweek("2026-09-18", active_scope=SUCCESSOR_SIX_SCOPE)
    inputs = [_complete_scope_inputs(scope, suffix=str(i)) for i, scope in enumerate(scopes)]
    assessment = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=scopes,
        provider_attempts=tuple(item[0] for item in inputs),
        coverage_evidence=tuple(item[1] for item in inputs),
        fixture_revisions=tuple(item[2] for item in inputs),
        identity_resolutions=tuple(item[3] for item in inputs),
        freshness_results=tuple(item[4] for item in inputs),
    )
    assert assessment.contract_version == "fixture-coverage-v4-v4"
    assert assessment.schema_version == 4
    assert assessment.active_scope == SUCCESSOR_SIX_SCOPE
    assert assessment.schedule_state is MatchweekScheduleState.COMPLETE
    assert [item.coverage_state for item in assessment.scope_assessments] == [
        ScopeCoverageState.COMPLETE
    ] * 6
    assert decode_f01(encode_f01(assessment)) == assessment
    for values in (assessment.scope_assessments[::-1], assessment.scope_assessments[:-1]):
        with pytest.raises(ValueError):
            replace(assessment, scope_assessments=values, digest="")


def test_old_and_new_coexist_without_storage_changes(tmp_path: Path) -> None:
    from test_fixture_coverage_repository import _unknown_assessment

    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.store import open_store

    old = _unknown_assessment()
    new = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=active_fixture_scopes_for_matchweek("2026-09-25", active_scope=SUCCESSOR_SIX_SCOPE),
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        repository = FixtureCoverageRepository(store)
        repository.persist(old)
        repository.persist(new)
        old_replay = repository.get(old.digest)
        assert old_replay is not None
        assert encode_f01(old_replay) == encode_f01(old)
        assert repository.get(new.digest) == new
        assert set(
            item.digest for item in repository.list_for_matchweek("2026-27", "2026-09-25")
        ) == {old.digest, new.digest}


@pytest.mark.parametrize("state", tuple(ScopeCoverageState))
def test_each_scope_keeps_existing_evidence_rules(state: ScopeCoverageState) -> None:
    scopes = active_fixture_scopes_for_matchweek("2026-09-18", active_scope=SUCCESSOR_SIX_SCOPE)
    inputs = [
        _complete_scope_inputs(
            scope,
            suffix=str(i),
            affirmatively_empty=state is ScopeCoverageState.CONFIRMED_EMPTY,
            current=state is not ScopeCoverageState.STALE,
            pagination_exhausted=state is not ScopeCoverageState.PARTIAL,
        )
        for i, scope in enumerate(scopes)
    ]
    empty = state in (ScopeCoverageState.CONFIRMED_EMPTY, ScopeCoverageState.UNKNOWN)
    assessment = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=scopes,
        provider_attempts=tuple(v[0] for v in inputs),
        coverage_evidence=()
        if state is ScopeCoverageState.UNKNOWN
        else tuple(v[1] for v in inputs),
        fixture_revisions=() if empty else tuple(v[2] for v in inputs),
        identity_resolutions=() if empty else tuple(v[3] for v in inputs),
        freshness_results=()
        if state is ScopeCoverageState.UNKNOWN
        else tuple(v[4] for v in inputs),
    )
    assert [v.coverage_state for v in assessment.scope_assessments] == [state] * 6
    assert assessment.schedule_state.value == state.value
    assert decode_f01(encode_f01(assessment)) == assessment


def test_one_missing_evidence_scope_still_blocks_six_completeness() -> None:
    scopes = active_fixture_scopes_for_matchweek("2026-09-18", active_scope=SUCCESSOR_SIX_SCOPE)
    inputs = [_complete_scope_inputs(scope, suffix=str(i)) for i, scope in enumerate(scopes[:-1])]
    assessment = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=scopes,
        provider_attempts=tuple(v[0] for v in inputs),
        coverage_evidence=tuple(v[1] for v in inputs),
        fixture_revisions=tuple(v[2] for v in inputs),
        identity_resolutions=tuple(v[3] for v in inputs),
        freshness_results=tuple(v[4] for v in inputs),
    )
    assert assessment.scope_assessments[-1].coverage_state is ScopeCoverageState.UNKNOWN
    assert assessment.schedule_state is MatchweekScheduleState.PARTIAL
    for invalid_scopes in (
        scopes[::-1],
        scopes[:-1],
        (*scopes, replace(scopes[0], league_key="belgian_pro_league")),
    ):
        with pytest.raises(ValueError):
            assess_active_fixture_coverage(
                active_scope=SUCCESSOR_SIX_SCOPE,
                scopes=invalid_scopes,
                provider_attempts=(),
                coverage_evidence=(),
                fixture_revisions=(),
                identity_resolutions=(),
                freshness_results=(),
            )


@pytest.mark.parametrize(
    "mutation",
    (
        "order",
        "missing",
        "bel",
        "contract",
        "schema",
        "bool_schema",
        "scope_id",
        "scope_digest",
        "scope_version",
        "scope_season",
        "scope_order",
    ),
)
def test_successor_payload_dispatch_refuses_malformed_reference(mutation: str) -> None:
    import json

    from matchvet.fixture_coverage import FixtureCoveragePayloadError

    value = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=active_fixture_scopes_for_matchweek("2026-09-25", active_scope=SUCCESSOR_SIX_SCOPE),
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    raw = json.loads(encode_f01(value))
    if mutation == "order":
        raw["scope_assessments"].reverse()
    elif mutation == "missing":
        raw["scope_assessments"].pop()
    elif mutation == "bel":
        raw["scope_assessments"].append(raw["scope_assessments"][0].copy())
        raw["scope_assessments"][-1]["scope"] = {
            **raw["scope_assessments"][-1]["scope"],
            "league_key": "belgian_pro_league",
        }
    elif mutation == "contract":
        raw["contract_version"] = "fixture-coverage-v5-v5"
    elif mutation in ("schema", "bool_schema"):
        raw["schema_version"] = True if mutation == "bool_schema" else 3
    elif mutation == "scope_order":
        raw["active_scope"]["league_keys"].reverse()
    else:
        key, replacement = {
            "scope_id": ("contract_id", "wrong"),
            "scope_digest": ("digest", "sha256:" + "0" * 64),
            "scope_version": ("version", 1),
            "scope_season": ("season", "2025-26"),
        }[mutation]
        raw["active_scope"][key] = replacement
    with pytest.raises(FixtureCoveragePayloadError):
        decode_f01(json.dumps(raw, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def test_successor_rejects_belgian_graph_references() -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState

    value = assess_active_fixture_coverage(
        active_scope=SUCCESSOR_SIX_SCOPE,
        scopes=active_fixture_scopes_for_matchweek("2026-09-25", active_scope=SUCCESSOR_SIX_SCOPE),
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    attempt = ProviderAttempt(
        attempt_id="retained-bel",
        scope_id="belgian_pro_league:2026-27:2026-09-25",
        provider_id="offline",
        capability_id="offline",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-20T12:00:00.000000+00:00",
    )
    with pytest.raises(ValueError):
        replace(value, provider_attempts=(attempt,), digest="")

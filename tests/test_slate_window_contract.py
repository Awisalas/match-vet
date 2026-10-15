from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest


def test_five_league_scope_is_a_new_ordered_contract() -> None:
    from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE

    assert SUCCESSOR_FIVE_SCOPE.version == 3
    assert SUCCESSOR_FIVE_SCOPE.league_keys == (
        "premier_league",
        "serie_a",
        "la_liga",
        "bundesliga",
        "ligue_1",
    )
    assert SUCCESSOR_FIVE_SCOPE.season == "2026-27"


def test_slate_window_has_canonical_half_open_utc_identity() -> None:
    from matchvet.slate_window import SlateWindow

    first = SlateWindow.from_owner_bounds("2026-10-16T00:00:00+01:00", "2026-10-19T00:00:00+01:00")
    same_instants = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    assert first == same_instants
    assert first.start_utc == "2026-10-15T23:00:00.000000+00:00"
    assert first.end_utc == "2026-10-18T23:00:00.000000+00:00"
    assert first.digest.startswith("sha256:")
    assert first.slate_id == f"slate:{first.digest}"


def test_slate_window_refuses_empty_or_reversed_bounds_and_distinguishes_adjacency() -> None:
    from matchvet.slate_window import SlateWindow

    with pytest.raises(ValueError, match="end after start"):
        SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-15T23:00:00Z")
    first = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-16T23:00:00Z")
    adjacent = SlateWindow.from_owner_bounds("2026-10-16T23:00:00Z", "2026-10-17T23:00:00Z")
    assert first.digest != adjacent.digest
    assert first.end_utc == adjacent.start_utc


def test_slate_f01_retains_all_five_unknown_scopes_and_has_canonical_round_trip() -> None:
    from matchvet.fixture_coverage import MatchweekScheduleState, ScopeCoverageState
    from matchvet.slate_fixture_coverage import (
        assess_slate_fixture_coverage,
        decode_slate_f01,
        encode_slate_f01,
    )
    from matchvet.slate_window import SlateWindow

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    assert assessment.schedule_state is MatchweekScheduleState.UNKNOWN
    assert [item.coverage_state.value for item in assessment.scope_assessments] == [
        "UNKNOWN",
        "UNKNOWN",
        "UNKNOWN",
        "UNKNOWN",
        "UNKNOWN",
    ]
    encoded = encode_slate_f01(assessment)
    assert decode_slate_f01(encoded) == assessment
    with pytest.raises(ValueError):
        decode_slate_f01(encoded.replace('"schema_version":5', '"schema_version":4'))
    unsupported_scope = replace(
        assessment.scope_assessments[0], coverage_state=ScopeCoverageState.COMPLETE
    )
    with pytest.raises(ValueError, match="not justified"):
        replace(
            assessment, scope_assessments=(unsupported_scope, *assessment.scope_assessments[1:])
        )


def test_slate_f01_persists_and_reopens_without_a_friday_projection(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.slate_fixture_coverage import (
        SlateFixtureCoverageAssessment,
        assess_slate_fixture_coverage,
    )
    from matchvet.slate_fixture_coverage_repository import SlateFixtureCoverageRepository
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=(),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        repository = FixtureCoverageRepository(store)
        assert repository.persist_slate(assessment) == assessment.digest
        retained = repository.get_any(assessment.digest)
        assert isinstance(retained, SlateFixtureCoverageAssessment)
        assert retained == assessment
        assert SlateFixtureCoverageRepository(store).get(assessment.digest) == assessment


def test_provider_health_v2_binds_failed_attempt_to_exact_interval_f01() -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.provider_health import (
        PROVIDER_HEALTH_V2_CONTRACT_VERSION,
        PROVIDER_HEALTH_V2_SCHEMA_VERSION,
        ProviderHealthRecordV2,
        provider_health_record_to_canonical_json,
        provider_health_v2_record_from_canonical_json,
    )
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    scope_id = f"premier_league:2026-27:{window.slate_id}"
    attempt = ProviderAttempt(
        attempt_id="attempt-unavailable",
        scope_id=scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=(attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    records = build_slate_provider_health_records(assessment)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ProviderHealthRecordV2)
    assert (record.contract_version, record.schema_version) == (
        PROVIDER_HEALTH_V2_CONTRACT_VERSION,
        PROVIDER_HEALTH_V2_SCHEMA_VERSION,
    )
    assert record.requested_scope.scope_kind == "slate-fixture-scope"
    assert record.requested_scope.fixture_scope is not None
    assert record.requested_scope.fixture_scope.scope_id == scope_id
    assert (
        record.digest == "sha256:67ace5c0b8e509dd45f62f83a97ae0eb069b42b1bd314f8073cc4a0141bb0fe1"
    )
    assert "matchweek_friday" not in provider_health_record_to_canonical_json(record)
    assert (
        provider_health_v2_record_from_canonical_json(
            provider_health_record_to_canonical_json(record)
        )
        == record
    )
    with pytest.raises(ValueError):
        from matchvet.provider_health import provider_health_record_from_canonical_json

        provider_health_record_from_canonical_json(provider_health_record_to_canonical_json(record))


def test_interval_f01_preserves_every_state_and_health_keeps_dimensions_separate() -> None:
    from datetime import datetime, timedelta

    from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE
    from matchvet.fixture_coverage import (
        CoverageBasis,
        CoverageBasisKind,
        CoverageBounds,
        CoverageFreshnessResult,
        FixtureIdentityResolution,
        FixtureIdentityState,
        FixtureRevisionReference,
        MatchweekScheduleState,
        ProviderAttempt,
        ProviderAttemptState,
        ProviderCoverageEvidence,
        ScopeCoverageState,
    )
    from matchvet.provider_health import (
        CoverageState,
        FixtureCoverageAssessmentReference,
        FreshnessState,
        ProviderAttemptReference,
        ProviderCoverageEvidenceReference,
    )
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    scopes = tuple(
        f"{league}:2026-27:{window.slate_id}" for league in SUCCESSOR_FIVE_SCOPE.league_keys
    )
    midpoint = (datetime.fromisoformat(window.start_utc) + timedelta(hours=12)).isoformat(
        timespec="microseconds"
    )
    broad_start = (datetime.fromisoformat(window.start_utc) - timedelta(hours=1)).isoformat(
        timespec="microseconds"
    )
    broad_end = (datetime.fromisoformat(window.end_utc) + timedelta(hours=1)).isoformat(
        timespec="microseconds"
    )
    attempts = (
        tuple(
            ProviderAttempt(
                attempt_id=f"attempt-{index}",
                scope_id=scope_id,
                provider_id="openfootball-json",
                capability_id="scheduled-fixtures",
                state=ProviderAttemptState.CAPTURED,
                retrieved_at_utc=f"2026-10-15T12:0{index}:00.000000+00:00",
                capture_id=f"capture-{index}",
                capture_digest=f"{index + 1:064x}",
            )
            for index, scope_id in enumerate(scopes[:4])
        )
        + tuple(
            ProviderAttempt(
                attempt_id=f"attempt-{index}",
                scope_id=scopes[4],
                provider_id="openfootball-json",
                capability_id="scheduled-fixtures",
                state=ProviderAttemptState.CAPTURED,
                retrieved_at_utc=f"2026-10-15T12:{index:02d}:00.000000+00:00",
                capture_id=f"capture-{index}",
                capture_digest=f"{index + 1:064x}",
            )
            for index in (4, 5)
        )
        + (
            ProviderAttempt(
                attempt_id="attempt-empty-response",
                scope_id=scopes[2],
                provider_id="openfootball-json",
                capability_id="scheduled-fixtures",
                state=ProviderAttemptState.CAPTURED,
                retrieved_at_utc="2026-10-15T12:06:00.000000+00:00",
                capture_id="capture-6",
                capture_digest=f"{7:064x}",
            ),
        )
    )
    after_end = (datetime.fromisoformat(window.end_utc) + timedelta(hours=1)).isoformat(
        timespec="microseconds"
    )
    after_after_end = (datetime.fromisoformat(window.end_utc) + timedelta(hours=2)).isoformat(
        timespec="microseconds"
    )
    evidence = (
        ProviderCoverageEvidence(
            evidence_id="complete-range",
            attempt_id=attempts[0].attempt_id,
            scope_id=scopes[0],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[0],
            provider_season="2026-27",
            capture_id=attempts[0].capture_id or "",
            capture_digest=attempts[0].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(broad_start, broad_end),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
        ),
        ProviderCoverageEvidence(
            evidence_id="affirmative-empty",
            attempt_id=attempts[1].attempt_id,
            scope_id=scopes[1],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[1],
            provider_season="2026-27",
            capture_id=attempts[1].capture_id or "",
            capture_digest=attempts[1].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(window.start_utc, window.end_utc),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
            affirmatively_empty=True,
        ),
        ProviderCoverageEvidence(
            evidence_id="partial-range",
            attempt_id=attempts[2].attempt_id,
            scope_id=scopes[2],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[2],
            provider_season="2026-27",
            capture_id=attempts[2].capture_id or "",
            capture_digest=attempts[2].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(window.start_utc, midpoint),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
        ),
        ProviderCoverageEvidence(
            evidence_id="empty-response-without-assertion",
            attempt_id=attempts[6].attempt_id,
            scope_id=scopes[2],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[2],
            provider_season="2026-27",
            capture_id=attempts[6].capture_id or "",
            capture_digest=attempts[6].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(window.start_utc, window.end_utc),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
            affirmatively_empty=False,
        ),
        ProviderCoverageEvidence(
            evidence_id="stale-range",
            attempt_id=attempts[3].attempt_id,
            scope_id=scopes[3],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[3],
            provider_season="2026-27",
            capture_id=attempts[3].capture_id or "",
            capture_digest=attempts[3].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(window.start_utc, window.end_utc),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
        ),
        ProviderCoverageEvidence(
            evidence_id="disjoint-range",
            attempt_id=attempts[4].attempt_id,
            scope_id=scopes[4],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[4],
            provider_season="2026-27",
            capture_id=attempts[4].capture_id or "",
            capture_digest=attempts[4].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(after_end, after_after_end),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
        ),
        ProviderCoverageEvidence(
            evidence_id="touching-range",
            attempt_id=attempts[5].attempt_id,
            scope_id=scopes[4],
            provider_competition_key=SUCCESSOR_FIVE_SCOPE.league_keys[4],
            provider_season="2026-27",
            capture_id=attempts[5].capture_id or "",
            capture_digest=attempts[5].capture_digest or "",
            coverage_basis=CoverageBasis(
                CoverageBasisKind.EXPLICIT_PROVIDER_METADATA, "window-query"
            ),
            bounds=CoverageBounds(window.end_utc, after_end),
            provider_use_policy_id="supported-public-fixture-policy-v1",
            permitted_for_use=True,
            required_partition_ids=("all",),
            accounted_partition_ids=("all",),
            pagination_exhausted=True,
        ),
    )
    revisions = (
        FixtureRevisionReference(
            scope_id=scopes[0],
            fixture_id="fixture-1",
            revision_id="revision-1",
            revision_digest="a" * 64,
            source_capture_ids=("capture-0",),
            source_assertion_ids=("assertion-1",),
        ),
    )
    identities = (
        FixtureIdentityResolution(
            candidate_id="candidate-1",
            scope_id=scopes[0],
            state=FixtureIdentityState.RESOLVED,
            canonical_fixture_id="fixture-1",
            revision_ids=("revision-1",),
        ),
    )
    freshness = tuple(
        CoverageFreshnessResult(
            evidence_id=item.evidence_id,
            policy_id="retained-freshness-policy-v1",
            evaluated_at_utc="2026-10-15T13:00:00.000000+00:00",
            is_current=item.evidence_id != "stale-range",
        )
        for item in evidence
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=attempts,
        coverage_evidence=evidence,
        fixture_revisions=revisions,
        identity_resolutions=identities,
        freshness_results=freshness,
    )
    states = {item.scope.league_key: item.coverage_state for item in assessment.scope_assessments}
    assert tuple(states.values()) == (
        ScopeCoverageState.COMPLETE,
        ScopeCoverageState.CONFIRMED_EMPTY,
        ScopeCoverageState.PARTIAL,
        ScopeCoverageState.STALE,
        ScopeCoverageState.UNKNOWN,
    )
    assert assessment.schedule_state is MatchweekScheduleState.PARTIAL

    records = build_slate_provider_health_records(assessment)
    by_attempt = {
        next(
            reference.attempt_id
            for reference in record.provenance
            if isinstance(reference, ProviderAttemptReference)
        ): record
        for record in records
    }
    stale = by_attempt[attempts[3].attempt_id]
    retained_assessment = next(
        reference
        for reference in stale.provenance
        if isinstance(reference, FixtureCoverageAssessmentReference)
    )
    assert retained_assessment.scope_state == "STALE"
    assert stale.coverage.state is CoverageState.COMPLETE
    assert stale.freshness.state is FreshnessState.UNKNOWN
    assert evidence[0].bounds == CoverageBounds(broad_start, broad_end)
    assert by_attempt[attempts[1].attempt_id].coverage.state is CoverageState.CONFIRMED_EMPTY
    assert by_attempt[attempts[4].attempt_id].coverage.state is CoverageState.UNKNOWN
    assert by_attempt[attempts[5].attempt_id].coverage.state is CoverageState.UNKNOWN
    assert by_attempt[attempts[6].attempt_id].coverage.state is CoverageState.COMPLETE
    assert assessment.scope_assessments[2].coverage_state is ScopeCoverageState.PARTIAL
    disjoint_snapshot = next(
        reference
        for reference in by_attempt[attempts[4].attempt_id].provenance
        if isinstance(reference, ProviderCoverageEvidenceReference)
    )
    assert disjoint_snapshot.bounds_start_utc == after_end


def test_provider_health_v2_persists_replays_and_inspects_exact_attempts(
    tmp_path: Path,
) -> None:
    from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.slate_fixture_coverage import (
        SlateFixtureCoverageAssessment,
        assess_slate_fixture_coverage,
        encode_slate_f01,
    )
    from matchvet.slate_fixture_coverage_repository import SlateFixtureCoverageRepository
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-{index}-{state.value.lower()}",
            scope_id=f"{league}:2026-27:{window.slate_id}",
            provider_id=(
                "openfootball-footballtxt"
                if state is ProviderAttemptState.UNAVAILABLE
                else "openfootball-json"
            ),
            capability_id="scheduled-fixtures",
            state=state,
            retrieved_at_utc=f"2026-10-15T12:{index:02d}:00.000000+00:00",
            http_status=200 if state is ProviderAttemptState.MALFORMED else None,
            capture_id=(f"capture-{index}" if state is ProviderAttemptState.CAPTURED else None),
            capture_digest=(f"{index:064x}" if state is ProviderAttemptState.CAPTURED else None),
        )
        for index, league in enumerate(SUCCESSOR_FIVE_SCOPE.league_keys)
        for state in (
            ProviderAttemptState.CAPTURED,
            ProviderAttemptState.UNAVAILABLE,
            ProviderAttemptState.MALFORMED,
        )
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=attempts,
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    records = build_slate_provider_health_records(assessment)
    assert len(records) == len(attempts) == 15
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        f01_repository = FixtureCoverageRepository(store)
        f01_repository.persist_slate(assessment)
        original_f01_bytes = encode_slate_f01(assessment)
        repository = ProviderHealthRepository(store)
        digests = repository.persist_many(records)
        assert digests == tuple(sorted(record.digest for record in records))
        assert repository.persist_many(records) == digests
        retained_f01 = SlateFixtureCoverageRepository(store).get(assessment.digest)
        assert isinstance(retained_f01, SlateFixtureCoverageAssessment)
        assert encode_slate_f01(retained_f01) == original_f01_bytes
        for record in records:
            assert repository.get(record.digest) == record
        listed = repository.list_for_assessment(assessment.digest)
        assert {record.digest for record in listed} == set(digests)
        inspection = repository.inspect_for_assessment(assessment.digest)
        assert inspection.missing_attempt_ids == ()
        assert {record.digest for record in inspection.records} == set(digests)


def test_provider_health_v2_inspection_reports_missing_and_pair_conflicts_refuse(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    scope_id = f"premier_league:2026-27:{window.slate_id}"
    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-{suffix}",
            scope_id=scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.CAPTURED,
            retrieved_at_utc=f"2026-10-15T12:0{index}:00.000000+00:00",
            capture_id=f"capture-{index}",
            capture_digest=f"{index + 1:064x}",
        )
        for index, suffix in enumerate(("a", "b"))
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=attempts,
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    records = build_slate_provider_health_records(assessment)
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist_slate(assessment)
        repository = ProviderHealthRepository(store)
        first_record = next(
            record
            for record in records
            if any(
                getattr(reference, "attempt_id", None) == attempts[0].attempt_id
                for reference in record.provenance
            )
        )
        repository.persist_many((first_record,))
        inspection = repository.inspect_for_assessment(assessment.digest)
        assert len(inspection.missing_attempt_ids) == 1
        assert inspection.missing_attempt_ids[0] != attempts[0].attempt_id

        changed = build_slate_provider_health_records(
            assessment,
            attempt_diagnostics={attempts[0].attempt_id: "retained adapter diagnostic"},
        )
        changed_record = next(
            record
            for record in changed
            if any(
                getattr(reference, "attempt_id", None) == attempts[0].attempt_id
                for reference in record.provenance
            )
        )
        with pytest.raises(ProviderHealthIntegrityError, match="key cannot retain changed"):
            repository.persist_many((changed_record,))


def test_provider_health_v2_batch_rolls_back_and_checks_current_authority(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    scope_id = f"premier_league:2026-27:{window.slate_id}"
    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-{letter}",
            scope_id=scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc=f"2026-10-15T12:0{index}:00.000000+00:00",
        )
        for index, letter in enumerate(("a", "b"))
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=attempts,
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    records = build_slate_provider_health_records(assessment)
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist_slate(assessment)
        repository = ProviderHealthRepository(store)
        with store.transaction() as transaction:
            transaction.execute(
                """CREATE TRIGGER fail_one_slate_health_insert
                   BEFORE INSERT ON slate_provider_health_records
                   WHEN NEW.attempt_id = 'attempt-b'
                   BEGIN SELECT RAISE(ABORT, 'injected slate health batch failure'); END"""
            )
        with pytest.raises(ProviderHealthIntegrityError):
            repository.persist_many(records)
        assert repository.inspect_for_assessment(assessment.digest).missing_attempt_ids == (
            "attempt-a",
            "attempt-b",
        )

        def deny_write() -> None:
            raise PermissionError("current source authority is unavailable")

        guarded = ProviderHealthRepository(store, write_guard=deny_write)
        with pytest.raises(PermissionError, match="current source authority"):
            guarded.persist_many(records)
        assert repository.inspect_for_assessment(assessment.digest).missing_attempt_ids == (
            "attempt-a",
            "attempt-b",
        )


def test_standard_acquisition_uses_supported_controlled_feeds_for_all_five_scopes(
    tmp_path: Path,
) -> None:
    from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE
    from matchvet.fixture_coverage import ProviderAttemptState
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        StaticSourceFetcher,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.slate_fixture_coverage_acquisition import SlateFixtureCoverageAcquirer
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    sources = {
        openfootball_url(league_by_key(key), SUCCESSOR_FIVE_SCOPE.season): b'{"matches":[]}'
        for key in SUCCESSOR_FIVE_SCOPE.league_keys
    }
    sources[openfootball_text_url(league_by_key("premier_league"), "2026-27")] = (
        b"= OpenFootball schedule\n\nMatchday 1\n"
    )
    sources[openfootball_text_url(league_by_key("serie_a"), "2026-27")] = b"not a schedule"
    fetcher = StaticSourceFetcher(
        sources,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        acquirer = SlateFixtureCoverageAcquirer(
            FixtureHistoryImporter(store, private_root=private_root),
            fetcher,
            attempted_at=lambda: "2026-10-15T12:00:00+00:00",
        )
        acquired = acquirer.acquire(
            SlateWindow.from_owner_bounds("2026-10-16T00:00:00+01:00", "2026-10-19T00:00:00+01:00")
        )
        assert len(fetcher.calls) == 10
        assert tuple(item.scope.league_key for item in acquired.assessment.scope_assessments) == (
            *SUCCESSOR_FIVE_SCOPE.league_keys,
        )
        assert {item.coverage_state.value for item in acquired.assessment.scope_assessments} == {
            "UNKNOWN"
        }
        assert len(acquired.assessment.provider_attempts) == 10
        assert {attempt.state for attempt in acquired.assessment.provider_attempts} == {
            ProviderAttemptState.CAPTURED,
            ProviderAttemptState.UNAVAILABLE,
            ProviderAttemptState.MALFORMED,
        }
        assert len(acquired.health_digests) == 10
        inspection = ProviderHealthRepository(store).inspect_for_assessment(
            acquired.assessment.digest
        )
        assert inspection.missing_attempt_ids == ()
        assert len(inspection.records) == 10


def test_replay_reads_v1_and_v2_f01_and_health_from_one_store(tmp_path: Path) -> None:
    from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE
    from matchvet.fixture_coverage import (
        ProviderAttempt,
        ProviderAttemptState,
        assess_fixture_coverage,
        fixture_scopes_for_matchweek,
    )
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import (
        build_provider_health_records,
        build_slate_provider_health_records,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    old_scope = fixture_scopes_for_matchweek("2026-10-16", season="2026-27")[0]
    old_attempt = ProviderAttempt(
        attempt_id="legacy-attempt-v1",
        scope_id=old_scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    old_assessment = assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-10-16", season="2026-27"),
        provider_attempts=(old_attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    new_scope_id = f"{SUCCESSOR_FIVE_SCOPE.league_keys[0]}:2026-27:{window.slate_id}"
    new_attempt = ProviderAttempt(
        attempt_id="successor-attempt-v2",
        scope_id=new_scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    new_assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=(new_attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    old_records = build_provider_health_records(old_assessment)
    new_records = build_slate_provider_health_records(new_assessment)
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        f01 = FixtureCoverageRepository(store)
        assert f01.persist(old_assessment) == old_assessment.digest
        assert f01.persist_slate(new_assessment) == new_assessment.digest
        health = ProviderHealthRepository(store)
        health.persist_many(old_records)
        health.persist_many(new_records)
        assert f01.get_any(old_assessment.digest) == old_assessment
        assert f01.get_any(new_assessment.digest) == new_assessment
        assert health.get(old_records[0].digest) == old_records[0]
        assert health.get(new_records[0].digest) == new_records[0]
        assert health.list_for_assessment(old_assessment.digest) == old_records
        assert health.list_for_assessment(new_assessment.digest) == new_records


def test_replay_migration_15_failure_rolls_back_and_reopens_historical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from matchvet.fixture_coverage import (
        ProviderAttempt,
        ProviderAttemptState,
        assess_fixture_coverage,
        fixture_scopes_for_matchweek,
    )
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import MIGRATIONS, StoreMode, open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "store.sqlite3"
    scope = fixture_scopes_for_matchweek("2026-10-16", season="2026-27")[0]
    attempt = ProviderAttempt(
        attempt_id="migration-replay-attempt",
        scope_id=scope.scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    assessment = assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-10-16", season="2026-27"),
        provider_attempts=(attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    (record,) = build_provider_health_records(assessment)
    with open_store(database_path, private_root=private_root, migrations=MIGRATIONS[:-1]) as store:
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many((record,))
        old_f01 = (
            store._connection_for_repository()
            .execute(
                "SELECT assessment_json FROM fixture_coverage_assessments "
                "WHERE assessment_digest = ?",
                (assessment.digest,),
            )
            .fetchone()[0]
        )
        old_f05 = (
            store._connection_for_repository()
            .execute(
                "SELECT record_json FROM provider_health_records WHERE record_digest = ?",
                (record.digest,),
            )
            .fetchone()[0]
        )
        old_migrations = tuple(
            store._connection_for_repository()
            .execute(
                "SELECT migration_number, checksum FROM schema_migrations ORDER BY migration_number"
            )
            .fetchall()
        )
    import matchvet.store as store_module

    failing_migration = replace(
        MIGRATIONS[-1],
        statements=(
            *MIGRATIONS[-1].statements,
            "CREATE TABLE migration_15_must_rollback (value TEXT) STRICT",
            "INSERT INTO migration_15_missing_table VALUES (1)",
        ),
    )
    failing_plan = (*MIGRATIONS[:-1], failing_migration)
    monkeypatch.setattr(store_module, "MIGRATIONS", failing_plan)
    with open_store(database_path, private_root=private_root, migrations=failing_plan) as failed:
        assert failed.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert failed.status.schema_version == 14
        assert failed.status.issues[0].code == "MV-STORE-MIGRATION_FAILED"
    monkeypatch.setattr(store_module, "MIGRATIONS", MIGRATIONS)
    raw = sqlite3.connect(database_path)
    assert raw.execute("PRAGMA user_version").fetchone() == (14,)
    assert raw.execute(
        "SELECT count(*) FROM sqlite_schema WHERE name IN "
        "('slate_fixture_coverage_assessments', 'slate_provider_health_records')"
    ).fetchone() == (0,)
    assert (
        raw.execute(
            "SELECT assessment_json FROM fixture_coverage_assessments WHERE assessment_digest = ?",
            (assessment.digest,),
        ).fetchone()[0]
        == old_f01
    )
    assert (
        raw.execute(
            "SELECT record_json FROM provider_health_records WHERE record_digest = ?",
            (record.digest,),
        ).fetchone()[0]
        == old_f05
    )
    assert (
        tuple(
            raw.execute(
                "SELECT migration_number, checksum FROM schema_migrations ORDER BY migration_number"
            )
        )
        == old_migrations
    )
    raw.close()

    with open_store(database_path, private_root=private_root) as replayed:
        assert replayed.status.mode is StoreMode.READ_WRITE
        assert replayed.status.schema_version == 15
        assert FixtureCoverageRepository(replayed).get(assessment.digest) == assessment
        assert ProviderHealthRepository(replayed).get(record.digest) == record


def test_older_schema_refuses_interval_health_writes(tmp_path: Path) -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.provider_health_repository import (
        ProviderHealthPersistenceError,
        ProviderHealthRepository,
    )
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow
    from matchvet.store import MIGRATIONS, open_store

    window = SlateWindow.from_owner_bounds("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    attempt = ProviderAttempt(
        attempt_id="unsupported-store-attempt",
        scope_id=f"premier_league:2026-27:{window.slate_id}",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
    )
    assessment = assess_slate_fixture_coverage(
        window=window,
        provider_attempts=(attempt,),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    record = build_slate_provider_health_records(assessment)[0]
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(
        private_root / "store.sqlite3", private_root=private_root, migrations=MIGRATIONS[:-1]
    ) as old_store:
        with pytest.raises(ProviderHealthPersistenceError, match="does not support"):
            ProviderHealthRepository(old_store).persist_many((record,))
        assert old_store.status.schema_version == 14


def test_v2_f05_uses_assessment_attempt_key_and_refuses_invented_or_corrupt_rows(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import ProviderAttempt, ProviderAttemptState
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_acquisition import build_slate_provider_health_records
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.slate_fixture_coverage import assess_slate_fixture_coverage
    from matchvet.slate_window import SlateWindow
    from matchvet.store import open_store

    def make_assessment(start: str, end: str):
        window = SlateWindow.from_owner_bounds(start, end)
        attempt = ProviderAttempt(
            attempt_id="shared-attempt-id",
            scope_id=f"premier_league:2026-27:{window.slate_id}",
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-10-15T12:00:00.000000+00:00",
        )
        assessment = assess_slate_fixture_coverage(
            window=window,
            provider_attempts=(attempt,),
            coverage_evidence=(),
            fixture_revisions=(),
            identity_resolutions=(),
            freshness_results=(),
        )
        return assessment, build_slate_provider_health_records(assessment)[0]

    first, first_record = make_assessment("2026-10-15T23:00:00Z", "2026-10-18T23:00:00Z")
    second, second_record = make_assessment("2026-10-18T23:00:00Z", "2026-10-21T23:00:00Z")
    _invented, invented_record = make_assessment("2026-10-21T23:00:00Z", "2026-10-24T23:00:00Z")
    assert first_record.digest != second_record.digest
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        f01 = FixtureCoverageRepository(store)
        f01.persist_slate(first)
        f01.persist_slate(second)
        repository = ProviderHealthRepository(store)
        repository.persist_many((first_record, second_record))
        assert repository.list_for_assessment(first.digest) == (first_record,)
        assert repository.list_for_assessment(second.digest) == (second_record,)
        with pytest.raises(ProviderHealthIntegrityError, match="exact persisted interval F01"):
            repository.persist_many((invented_record,))

        connection = store._connection_for_repository()
        connection.execute("DROP TRIGGER slate_provider_health_records_no_update")
        connection.execute(
            "UPDATE slate_provider_health_records SET record_json = '{}' WHERE record_digest = ?",
            (first_record.digest,),
        )
        with pytest.raises(ProviderHealthIntegrityError, match="JSON is invalid"):
            repository.get(first_record.digest)

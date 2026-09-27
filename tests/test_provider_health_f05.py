from __future__ import annotations

from pathlib import Path

import pytest

from matchvet.fixture_coverage import (
    CoverageBasis,
    CoverageBasisKind,
    CoverageBounds,
    FixtureCoverageAssessment,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    assess_fixture_coverage,
    fixture_scopes_for_matchweek,
)
from matchvet.provider_health import (
    CapabilityAvailabilityState,
    CoverageState,
    EvidenceReferenceKind,
    F01FixtureScopeReference,
    F01ProviderAttemptState,
    FailureState,
    FixtureCoverageAssessmentReference,
    FreshnessState,
    ProviderAttemptReference,
    ProviderHealthRecord,
    ReachabilityState,
    StructuralValidityState,
    UsePermissionState,
)
from matchvet.provider_health_acquisition import build_provider_health_records


def _assessment(
    attempts: tuple[ProviderAttempt, ...],
    evidence: tuple[ProviderCoverageEvidence, ...] = (),
) -> FixtureCoverageAssessment:
    return assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-09-25", season="2026-27"),
        provider_attempts=attempts,
        coverage_evidence=evidence,
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )


def test_captured_attempt_records_only_facts_the_parser_and_attempt_establish() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-json",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-json",
        capture_digest="a" * 64,
    )
    assessment = _assessment((attempt,))

    (record,) = build_provider_health_records(assessment)

    assert record.provider.provider_id == "openfootball-json"
    assert record.provider.source_lineage_id == "openfootball-schedule-lineage"
    assert record.capability.capability_id == "scheduled-fixtures"
    assert record.intended_use_id == "matchvet:research-only:upcoming-fixture-acquisition"
    assert record.checked_at_utc == attempt.retrieved_at_utc
    assert record.use_permission.state is UsePermissionState.PERMITTED
    assert record.use_permission.policy is not None
    assert record.use_permission.policy.policy_id == "t06-source-policy"
    assert record.use_permission.policy.version == "v1"
    assert record.use_permission.policy.intended_use_id == record.intended_use_id
    assert record.reachability.state is ReachabilityState.REACHABLE
    assert record.capability_availability.state is CapabilityAvailabilityState.AVAILABLE
    assert record.structural_validity.state is StructuralValidityState.VALID
    assert record.freshness.state is FreshnessState.UNKNOWN
    assert record.coverage.state is CoverageState.UNKNOWN
    assert record.failure.state is FailureState.NO_FAILURE_OBSERVED
    assert ProviderAttemptReference.from_f01(attempt) in record.provenance
    fixture_scope = record.requested_scope.fixture_scope
    assert fixture_scope is not None
    assert (
        FixtureCoverageAssessmentReference.from_f01(assessment, fixture_scope) in record.provenance
    )
    assert any(
        isinstance(reference, ProviderAttemptReference)
        and reference.state is F01ProviderAttemptState.CAPTURED
        and reference.capture_id == "capture-json"
        and reference.capture_digest == "a" * 64
        for reference in record.provenance
    )


def test_malformed_attempt_does_not_imply_missing_capability() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-malformed",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.MALFORMED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-malformed",
        capture_digest="b" * 64,
    )

    (record,) = build_provider_health_records(_assessment((attempt,)))

    assert record.reachability.state is ReachabilityState.REACHABLE
    assert record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
    assert record.structural_validity.state is StructuralValidityState.INVALID
    assert record.failure.state is FailureState.FAILED
    assert tuple(code.value for code in record.failure.reason_codes) == ("MALFORMED_RESPONSE",)
    assert record.freshness.state is FreshnessState.UNKNOWN
    assert record.coverage.state is CoverageState.UNKNOWN


def test_malformed_attempt_without_response_evidence_keeps_reachability_unknown() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-malformed-no-response",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.MALFORMED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )

    (record,) = build_provider_health_records(_assessment((attempt,)))

    assert record.reachability.state is ReachabilityState.UNKNOWN
    assert record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
    assert record.structural_validity.state is StructuralValidityState.INVALID


@pytest.mark.parametrize(
    ("http_status", "reachability", "availability"),
    (
        (404, ReachabilityState.REACHABLE, CapabilityAvailabilityState.UNAVAILABLE),
        (None, ReachabilityState.UNKNOWN, CapabilityAvailabilityState.UNKNOWN),
        (200, ReachabilityState.REACHABLE, CapabilityAvailabilityState.UNKNOWN),
    ),
)
def test_unavailable_attempt_uses_only_its_response_evidence_including_local_limits(
    http_status: int | None,
    reachability: ReachabilityState,
    availability: CapabilityAvailabilityState,
) -> None:
    attempt = ProviderAttempt(
        attempt_id=f"attempt-unavailable-{http_status}",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-footballtxt",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=http_status,
    )

    (record,) = build_provider_health_records(_assessment((attempt,)))

    assert record.reachability.state is reachability
    assert record.capability_availability.state is availability
    assert record.structural_validity.state is StructuralValidityState.UNKNOWN
    assert record.failure.state is FailureState.FAILED
    assert tuple(code.value for code in record.failure.reason_codes) == ("ATTEMPT_UNAVAILABLE",)
    assert record.freshness.state is FreshnessState.UNKNOWN
    assert record.coverage.state is CoverageState.UNKNOWN
    if http_status is None:
        assert record.reachability.state is not ReachabilityState.UNREACHABLE


def test_captured_attempt_with_diagnostic_does_not_claim_no_failure() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-diagnostic",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-diagnostic",
        capture_digest="c" * 64,
    )

    (record,) = build_provider_health_records(
        _assessment((attempt,)), attempt_diagnostics={attempt.attempt_id: "local warning"}
    )

    assert record.failure.state is FailureState.FAILED
    assert tuple(code.value for code in record.failure.reason_codes) == ("ACQUISITION_DIAGNOSTIC",)


def _complete_empty_evidence(attempt: ProviderAttempt) -> ProviderCoverageEvidence:
    scope = fixture_scopes_for_matchweek("2026-09-25", season="2026-27")[0]
    return ProviderCoverageEvidence(
        evidence_id=f"evidence-{attempt.provider_id}",
        attempt_id=attempt.attempt_id,
        scope_id=attempt.scope_id,
        provider_competition_key=scope.league_key,
        provider_season=scope.season,
        capture_id=attempt.capture_id or "missing-capture",
        capture_digest=attempt.capture_digest or "d" * 64,
        coverage_basis=CoverageBasis(
            kind=CoverageBasisKind.EXPLICIT_PROVIDER_METADATA,
            reference_id="provider-schedule-metadata",
        ),
        bounds=CoverageBounds(scope.window_start_utc, scope.window_end_utc),
        provider_use_policy_id="t06-source-policy-v1",
        permitted_for_use=True,
        pagination_exhausted=True,
        affirmatively_empty=True,
    )


def test_coverage_evidence_is_provider_attempt_and_capture_specific() -> None:
    json_attempt = ProviderAttempt(
        attempt_id="attempt-json",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-json",
        capture_digest="a" * 64,
    )
    text_attempt = ProviderAttempt(
        attempt_id="attempt-text",
        scope_id=json_attempt.scope_id,
        provider_id="openfootball-footballtxt",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-text",
        capture_digest="e" * 64,
    )
    evidence = _complete_empty_evidence(text_attempt)

    records = build_provider_health_records(_assessment((json_attempt, text_attempt), (evidence,)))
    json_record = next(
        record for record in records if record.provider.provider_id == "openfootball-json"
    )
    text_record = next(
        record for record in records if record.provider.provider_id == "openfootball-footballtxt"
    )

    assert json_record.coverage.state is CoverageState.UNKNOWN
    assert not any(
        reference.reference_kind is EvidenceReferenceKind.PROVIDER_COVERAGE_EVIDENCE
        for reference in json_record.provenance
    )
    assert text_record.coverage.state is CoverageState.CONFIRMED_EMPTY
    assert text_record.provider.source_lineage_id == json_record.provider.source_lineage_id
    assert text_record.provider.provider_id != json_record.provider.provider_id
    assert text_record.checked_at_utc == text_attempt.retrieved_at_utc


def test_unregistered_provider_permission_stays_unknown() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-unknown-rights",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="unregistered-public-url-provider",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )

    (record,) = build_provider_health_records(_assessment((attempt,)))

    assert record.use_permission.state is UsePermissionState.UNKNOWN
    assert record.use_permission.policy is not None
    assert record.use_permission.policy.intended_use_id == record.intended_use_id


def test_f01_permitted_boolean_does_not_decide_unknown_permission() -> None:
    attempt = ProviderAttempt(
        attempt_id="attempt-public-url-unknown-rights",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="unregistered-public-url-provider",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id="capture-unknown-rights",
        capture_digest="f" * 64,
    )
    evidence = _complete_empty_evidence(attempt)
    assessment = _assessment((attempt,), (evidence,))

    (record,) = build_provider_health_records(assessment)

    assert evidence.permitted_for_use is True
    assert record.use_permission.state is UsePermissionState.UNKNOWN


def test_repository_persists_and_loads_only_the_requested_digest(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    attempt = ProviderAttempt(
        attempt_id="attempt-repository",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )
    assessment = _assessment((attempt,))
    record = build_provider_health_records(assessment)[0]

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)

        repository.persist_many((record,))

        assert repository.get(record.digest) == record
        assert repository.get("sha256:" + "0" * 64) is None
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == (record,)
        assert (
            repository.list_for_matchweek(
                "2026-27",
                "2026-09-25",
                provider_id="openfootball-footballtxt",
            )
            == ()
        )
        assert repository.list_for_matchweek(
            "2026-27",
            "2026-09-25",
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            scope_id=attempt.scope_id,
        ) == (record,)


def test_repository_is_idempotent_and_appends_deterministic_history(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    scope_id = "premier_league:2026-27:2026-09-25"
    captured = tuple(
        ProviderAttempt(
            attempt_id=provider_id,
            scope_id=scope_id,
            provider_id=provider_id,
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        )
        for provider_id in ("openfootball-json", "openfootball-footballtxt")
    )
    first_assessment = _assessment(captured)
    first_records = build_provider_health_records(first_assessment)
    later_attempt = ProviderAttempt(
        attempt_id="openfootball-json-later",
        scope_id=scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T13:00:00.000000+00:00",
    )
    later_assessment = _assessment((later_attempt,))
    later_record = build_provider_health_records(later_assessment)[0]

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        fixture_repository = FixtureCoverageRepository(store)
        fixture_repository.persist(first_assessment)
        fixture_repository.persist(later_assessment)
        repository = ProviderHealthRepository(store)

        repository.persist_many((*first_records, *first_records))
        first_persisted_values = tuple(
            store._connection_for_repository()
            .execute(
                "SELECT record_digest, first_persisted_at_utc FROM provider_health_records "
                "ORDER BY record_digest"
            )
            .fetchall()
        )
        repository.persist_many(first_records)
        assert (
            tuple(
                store._connection_for_repository()
                .execute(
                    "SELECT record_digest, first_persisted_at_utc FROM provider_health_records "
                    "ORDER BY record_digest"
                )
                .fetchall()
            )
            == first_persisted_values
        )
        repository.persist_many((later_record,))

        history = repository.list_for_matchweek("2026-27", "2026-09-25")
        assert [(record.checked_at_utc, record.provider.provider_id) for record in history] == [
            ("2026-09-16T12:00:00.000000+00:00", "openfootball-footballtxt"),
            ("2026-09-16T12:00:00.000000+00:00", "openfootball-json"),
            ("2026-09-16T13:00:00.000000+00:00", "openfootball-json"),
        ]
        assert len(history) == 3
        filtered_history = repository.list_for_matchweek(
            "2026-27",
            "2026-09-25",
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            scope_id=scope_id,
        )
        assert tuple(record.provider.provider_id for record in filtered_history) == (
            "openfootball-json",
            "openfootball-json",
        )


def test_repository_rejects_conflicting_logical_observations_without_writes(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    attempts = tuple(
        ProviderAttempt(
            attempt_id=f"attempt-conflict-{index}",
            scope_id="premier_league:2026-27:2026-09-25",
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=ProviderAttemptState.UNAVAILABLE,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        )
        for index in (1, 2)
    )
    assessment = _assessment(attempts)
    conflicting_records = build_provider_health_records(assessment)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)

        with pytest.raises(ProviderHealthIntegrityError, match="observation key"):
            repository.persist_many(conflicting_records)

        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


def test_repository_rejects_reference_membership_mismatch_before_writing(tmp_path: Path) -> None:
    from dataclasses import replace

    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health import (
        EvidenceBasis,
    )
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    attempt = ProviderAttempt(
        attempt_id="attempt-reference-mismatch",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )
    assessment = _assessment((attempt,))
    record = build_provider_health_records(assessment)[0]
    assessment_reference = next(
        reference
        for reference in record.provenance
        if isinstance(reference, FixtureCoverageAssessmentReference)
    )
    bad_reference = replace(assessment_reference, scope_state="COMPLETE")

    def replaced_evidence(evidence: EvidenceBasis | None) -> EvidenceBasis | None:
        if evidence is None:
            return None
        return replace(
            evidence,
            references=tuple(
                bad_reference if reference == assessment_reference else reference
                for reference in evidence.references
            ),
        )

    bad_record = replace(
        record,
        provenance=tuple(
            bad_reference if reference == assessment_reference else reference
            for reference in record.provenance
        ),
        reachability=replace(
            record.reachability, evidence=replaced_evidence(record.reachability.evidence)
        ),
        capability_availability=replace(
            record.capability_availability,
            evidence=replaced_evidence(record.capability_availability.evidence),
        ),
        structural_validity=replace(
            record.structural_validity,
            evidence=replaced_evidence(record.structural_validity.evidence),
        ),
        failure=replace(record.failure, evidence=replaced_evidence(record.failure.evidence)),
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)

        with pytest.raises(ProviderHealthIntegrityError, match="persisted F03 scope"):
            repository.persist_many((bad_record,))

        assert repository.list_for_matchweek("2026-27", "2026-09-25") == ()


@pytest.mark.parametrize("corruption", ("canonical_json", "assessment_metadata"))
def test_repository_rejects_corrupt_canonical_json_and_indexed_reference_metadata(
    tmp_path: Path,
    corruption: str,
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import (
        ProviderHealthIntegrityError,
        ProviderHealthRepository,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    attempt = ProviderAttempt(
        attempt_id="attempt-corruption",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )
    assessment = _assessment((attempt,))
    other_attempt = ProviderAttempt(
        attempt_id="attempt-corruption-other",
        scope_id="serie_a:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T13:00:00.000000+00:00",
    )
    other_assessment = _assessment((other_attempt,))
    record = build_provider_health_records(assessment)[0]

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        fixture_repository = FixtureCoverageRepository(store)
        fixture_repository.persist(assessment)
        fixture_repository.persist(other_assessment)
        repository = ProviderHealthRepository(store)
        repository.persist_many((record,))
        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER provider_health_records_no_update")
            if corruption == "canonical_json":
                transaction.execute(
                    "UPDATE provider_health_records SET record_json = record_json || ' ' "
                    "WHERE record_digest = ?",
                    (record.digest,),
                )
            else:
                transaction.execute(
                    "UPDATE provider_health_records SET assessment_digest = ? "
                    "WHERE record_digest = ?",
                    (other_assessment.digest, record.digest),
                )

        with pytest.raises(ProviderHealthIntegrityError):
            repository.get(record.digest)


def test_repository_rows_refuse_update_and_delete(tmp_path: Path) -> None:
    import sqlite3

    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    attempt = ProviderAttempt(
        attempt_id="attempt-immutable",
        scope_id="premier_league:2026-27:2026-09-25",
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=ProviderAttemptState.UNAVAILABLE,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )
    assessment = _assessment((attempt,))
    record = build_provider_health_records(assessment)[0]

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many((record,))

        with (
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
            store.transaction() as transaction,
        ):
            transaction.execute(
                "UPDATE provider_health_records SET first_persisted_at_utc = ? "
                "WHERE record_digest = ?",
                ("2026-09-17T12:00:00.000000+00:00", record.digest),
            )
        with (
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
            store.transaction() as transaction,
        ):
            transaction.execute(
                "DELETE FROM provider_health_records WHERE record_digest = ?",
                (record.digest,),
            )


def test_schema_ten_migrates_forward_without_changing_t06_t05_or_f03_values(
    tmp_path: Path,
) -> None:
    import sqlite3

    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import freeze_matchweek, read_frozen_matchweek
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import MIGRATIONS, open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG\n"
        b"E0,25/09/2026,20:00,Arsenal,Coventry,,,,,\n"
    )
    assessment = _assessment(())

    with open_store(
        database_path,
        private_root=private_root,
        migrations=MIGRATIONS[:10],
    ) as old_store:
        importer = FixtureHistoryImporter(old_store, private_root=private_root)
        importer.import_dataset(
            FootballDataCSVParser().parse(
                content, league=league_by_key("premier_league"), season="2026-27"
            ),
            content,
            SourceCaptureInput(
                source_url="https://example.test/E0.csv",
                retrieved_at_utc="2026-09-25T13:00:00.000000+00:00",
                observed_terms="restricted private local test use",
            ),
        )
        frozen = freeze_matchweek(
            old_store,
            "2026-09-25",
            as_of_utc="2026-09-25T13:00:00.000000+00:00",
            created_at_utc="2026-09-25T13:00:00.000000+00:00",
        )
        FixtureCoverageRepository(old_store).persist(assessment)
        capture_ids = tuple(capture.capture_id for capture in importer.source_captures())

    with sqlite3.connect(database_path) as connection:
        old_checksums = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT checksum FROM schema_migrations ORDER BY migration_number"
            ).fetchall()
        )
    assert old_checksums == tuple(migration.checksum for migration in MIGRATIONS[:10])

    with open_store(database_path, private_root=private_root) as migrated:
        assert migrated.status.schema_version == 11
        assert migrated.status.applied_migrations == tuple(range(1, 12))
        assert FixtureCoverageRepository(migrated).get(assessment.digest) == assessment
        assert (
            tuple(
                capture.capture_id
                for capture in FixtureHistoryImporter(
                    migrated, private_root=private_root
                ).source_captures()
            )
            == capture_ids
        )
        assert read_frozen_matchweek(migrated, "2026-09-25") == frozen
        assert ProviderHealthRepository(migrated).list_for_matchweek("2026-27", "2026-09-25") == ()

    with sqlite3.connect(database_path) as connection:
        new_checksums = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT checksum FROM schema_migrations ORDER BY migration_number"
            ).fetchall()
        )
    assert new_checksums[:10] == old_checksums
    assert len(new_checksums) == 11


def test_schema_eleven_refuses_an_older_migration_plan(tmp_path: Path) -> None:
    from matchvet.store import MIGRATIONS, StoreMode, open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    with open_store(database_path, private_root=private_root, migrations=MIGRATIONS[:10]) as store:
        assert store.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert store.status.issues[0].code == "MV-STORE-SCHEMA_TOO_NEW"


@pytest.mark.parametrize("entrypoint", ("scheduled", "t06"))
def test_scheduled_acquisition_persists_one_record_per_attempt_and_no_belgian_record(
    tmp_path: Path,
    entrypoint: str,
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.ingestion import (
        TARGET_LEAGUES,
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        T06AcquisitionRunner,
        football_data_url,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.runs import GIB, ResourceObservation
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    schedule_json = b'{"matches":[]}'
    schedule_text = b"= Empty schedule\n"
    source_bytes = {
        url: content
        for league in TARGET_LEAGUES
        if league.openfootball_supported
        for url, content in (
            (openfootball_url(league, "2026-27"), schedule_json),
            (openfootball_text_url(league, "2026-27"), schedule_text),
        )
    }
    expected_schedule_urls = tuple(
        url
        for league in TARGET_LEAGUES
        if league.openfootball_supported
        for url in (
            openfootball_url(league, "2026-27"),
            openfootball_text_url(league, "2026-27"),
        )
    )
    fetcher = StaticSourceFetcher(source_bytes, retrieved_at_utc="2026-09-16T12:00:00.000000+00:00")

    def no_new_clock_read() -> str:
        raise AssertionError("F05 must reuse each attempt retrieval time.")

    plan = IngestionPlan(current_season="2026-27", matchweek_friday="2026-09-25")
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        acquirer = FixtureHistoryAcquirer(importer, fetcher, attempted_at=no_new_clock_read)
        if entrypoint == "scheduled":
            scheduled = acquirer.acquire_scheduled_fixtures(plan)
            assessment = scheduled.assessment
            measured_bytes = scheduled.bytes_downloaded
            assert fetcher.calls == list(expected_schedule_urls)
        else:
            runner = T06AcquisitionRunner(store, acquirer)
            status = runner.start(
                plan,
                observation=ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0),
            )
            assert status.state.value == "COMPLETE"
            assert runner.last_report is not None
            assert runner.last_report.scheduled_fixtures is not None
            assessment = runner.last_report.scheduled_fixtures.assessment
            measured_bytes = runner.last_report.bytes_downloaded
            assert runner.last_report.scheduled_fixtures.bytes_downloaded == sum(
                map(len, source_bytes.values())
            )
            expected_t06_urls = (
                tuple(football_data_url(league, "2026-27") for league in TARGET_LEAGUES)
                + expected_schedule_urls
            )
            assert fetcher.calls == list(expected_t06_urls)

        assert FixtureCoverageRepository(store).get(assessment.digest) == assessment
        assert assessment.coverage_evidence == ()
        assert len(assessment.scope_assessments) == 7
        assert len(assessment.provider_attempts) == 12
        if entrypoint == "scheduled":
            assert measured_bytes == sum(map(len, source_bytes.values()))
        else:
            assert measured_bytes == 0

        records = ProviderHealthRepository(store).list_for_matchweek("2026-27", "2026-09-25")

        assert len(records) == len(assessment.provider_attempts) == 12
        assert {record.provider.provider_id for record in records} == {
            "openfootball-json",
            "openfootball-footballtxt",
        }
        assert {record.provider.source_lineage_id for record in records} == {
            "openfootball-schedule-lineage"
        }
        assert all(
            record.checked_at_utc == assessment.provider_attempts[0].retrieved_at_utc
            for record in records
        )
        assert all(record.coverage.state is CoverageState.UNKNOWN for record in records)
        assert all(record.freshness.state is FreshnessState.UNKNOWN for record in records)

        belgian = next(
            scope_assessment
            for scope_assessment in assessment.scope_assessments
            if scope_assessment.scope.league_key == "belgian_pro_league"
        )
        assert belgian.scope.scope_id == "belgian_pro_league:2026-27:2026-09-25"
        assert belgian.provider_attempt_ids == ()
        assert len(assessment.scope_assessments) == 7
        assert (
            ProviderHealthRepository(store).list_for_matchweek(
                "2026-27", "2026-09-25", scope_id=belgian.scope.scope_id
            )
            == ()
        )

        db = store._connection_for_repository()
        retained_health_bytes = int(
            db.execute(
                "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat "
                "WHERE name LIKE 'provider_health_records%'"
            ).fetchone()[0]
        )
        assert retained_health_bytes < 4 * 1024 * 1024


def test_scheduled_replay_preserves_f01_f03_references_and_f05_digests(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    source_bytes = {
        openfootball_url(league, "2026-27"): b'{"matches":[]}',
        openfootball_text_url(league, "2026-27"): b"= Empty schedule\n",
    }
    fetcher = StaticSourceFetcher(source_bytes, retrieved_at_utc="2026-09-16T12:00:00.000000+00:00")
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    def no_new_clock_read() -> str:
        raise AssertionError("F05 must reuse each attempt retrieval time.")

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        acquirer = FixtureHistoryAcquirer(importer, fetcher, attempted_at=no_new_clock_read)

        first = acquirer.acquire_scheduled_fixtures(plan)
        repository = ProviderHealthRepository(store)
        first_records = repository.list_for_matchweek("2026-27", "2026-09-25")
        first_persisted_values = tuple(
            store._connection_for_repository()
            .execute(
                "SELECT record_digest, first_persisted_at_utc FROM provider_health_records "
                "ORDER BY record_digest"
            )
            .fetchall()
        )

        second = acquirer.acquire_scheduled_fixtures(plan)
        second_records = repository.list_for_matchweek("2026-27", "2026-09-25")

        assert first.assessment.digest == second.assessment.digest
        assert tuple(record.digest for record in first_records) == tuple(
            record.digest for record in second_records
        )
        assert len(second_records) == len(first.assessment.provider_attempts) == 2
        assert len(importer.source_captures()) == 2
        assert len(fetcher.calls) == 4
        assert (
            tuple(
                store._connection_for_repository()
                .execute(
                    "SELECT record_digest, first_persisted_at_utc FROM provider_health_records "
                    "ORDER BY record_digest"
                )
                .fetchall()
            )
            == first_persisted_values
        )
        assert FixtureCoverageRepository(store).get(first.assessment.digest) == first.assessment

        for attempt in first.assessment.provider_attempts:
            matching_records = tuple(
                record
                for record in second_records
                if any(
                    isinstance(reference, ProviderAttemptReference)
                    and reference.attempt_id == attempt.attempt_id
                    for reference in record.provenance
                )
            )
            assert len(matching_records) == 1
            record = matching_records[0]
            fixture_scope = next(
                scope_assessment.scope
                for scope_assessment in first.assessment.scope_assessments
                if scope_assessment.scope.scope_id == attempt.scope_id
            )
            scope_reference = F01FixtureScopeReference.from_f01(fixture_scope)
            assert ProviderAttemptReference.from_f01(attempt) in record.provenance
            assert (
                FixtureCoverageAssessmentReference.from_f01(first.assessment, scope_reference)
                in record.provenance
            )


def test_cached_attempt_replay_is_idempotent_when_sibling_attempt_changes(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    json_url = openfootball_url(league, "2026-27")
    text_url = openfootball_text_url(league, "2026-27")
    fetcher = StaticSourceFetcher(
        {json_url: b'{"matches":[]}'},
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
    )
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        acquirer = FixtureHistoryAcquirer(
            FixtureHistoryImporter(store, private_root=private_root), fetcher
        )

        first = acquirer.acquire_scheduled_fixtures(plan)
        second = acquirer.acquire_scheduled_fixtures(plan)
        history = ProviderHealthRepository(store).list_for_matchweek("2026-27", "2026-09-25")

        first_json_attempt = next(
            attempt
            for attempt in first.assessment.provider_attempts
            if attempt.provider_id == "openfootball-json"
        )
        second_json_attempt = next(
            attempt
            for attempt in second.assessment.provider_attempts
            if attempt.provider_id == "openfootball-json"
        )
        assert first_json_attempt == second_json_attempt
        assert first.assessment.digest != second.assessment.digest
        json_records = tuple(
            record for record in history if record.provider.provider_id == "openfootball-json"
        )
        text_records = tuple(
            record
            for record in history
            if record.provider.provider_id == "openfootball-footballtxt"
        )
        assert len(json_records) == 1
        assert len(text_records) == 2
        assert any(
            isinstance(reference, FixtureCoverageAssessmentReference)
            and reference.assessment_digest == first.assessment.digest
            for reference in json_records[0].provenance
        )
        assert fetcher.calls == [json_url, text_url, json_url, text_url]


def test_local_resource_limit_through_f02_stays_unknown_in_f05(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.ingestion import (
        DownloadedSource,
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        SourceUnavailable,
        StaticSourceFetcher,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    json_url = openfootball_url(league, "2026-27")
    text_url = openfootball_text_url(league, "2026-27")
    content = b'{"matches":[]}'
    fetcher = StaticSourceFetcher(
        {json_url: content}, retrieved_at_utc="2026-09-16T12:00:00.000000+00:00"
    )
    static_fetch = fetcher.fetch

    def local_limit_fetch(url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource:
        if url == text_url:
            fetcher.calls.append(url)
            raise SourceUnavailable("Local source-byte limit reached.", http_status=200)
        return static_fetch(url, cache_key=cache_key, refresh=refresh)

    monkeypatch.setattr(fetcher, "fetch", local_limit_fetch)
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        acquirer = FixtureHistoryAcquirer(
            FixtureHistoryImporter(store, private_root=private_root), fetcher
        )

        scheduled = acquirer.acquire_scheduled_fixtures(plan)

        text_attempt = next(
            attempt
            for attempt in scheduled.assessment.provider_attempts
            if attempt.provider_id == "openfootball-footballtxt"
        )
        assert text_attempt.state is ProviderAttemptState.UNAVAILABLE
        assert text_attempt.http_status == 200
        records = ProviderHealthRepository(store).list_for_matchweek("2026-27", "2026-09-25")
        text_record = next(
            record
            for record in records
            if record.provider.provider_id == "openfootball-footballtxt"
        )
        assert text_record.reachability.state is ReachabilityState.REACHABLE
        assert text_record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
        assert text_record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert text_record.failure.state is FailureState.FAILED
        assert scheduled.bytes_downloaded == len(content)
        assert fetcher.calls == [json_url, text_url]


@pytest.mark.parametrize("entrypoint", ("scheduled", "t06"))
def test_f05_batch_failure_rolls_back_health_rows_and_keeps_f03_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        T06AcquisitionRunner,
        league_by_key,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.provider_health_repository import (
        ProviderHealthPersistenceError,
        ProviderHealthRepository,
    )
    from matchvet.runs import GIB, ResourceObservation, RunLifecycleError
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    schedule_json = b'{"matches":[]}'
    schedule_text = b"= Empty schedule\n"
    source_bytes = {
        openfootball_url(league, "2026-27"): schedule_json,
        openfootball_text_url(league, "2026-27"): schedule_text,
    }
    fetcher = StaticSourceFetcher(source_bytes, retrieved_at_utc="2026-09-16T12:00:00.000000+00:00")
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        acquirer = FixtureHistoryAcquirer(importer, fetcher)
        original_persist_many = ProviderHealthRepository.persist_many

        def fail_after_one_row(
            self: ProviderHealthRepository, records: tuple[ProviderHealthRecord, ...]
        ) -> tuple[str, ...]:
            with self._store.transaction() as transaction:
                transaction.execute(
                    """
                    CREATE TRIGGER f05_test_fail_second_record
                    BEFORE INSERT ON provider_health_records
                    WHEN (
                        SELECT count(*) FROM provider_health_records
                        WHERE assessment_digest = NEW.assessment_digest
                    ) = 1
                    BEGIN
                        SELECT RAISE(ABORT, 'injected second-row failure');
                    END
                    """
                )
            return original_persist_many(self, records)

        monkeypatch.setattr(ProviderHealthRepository, "persist_many", fail_after_one_row)

        if entrypoint == "scheduled":
            with pytest.raises(ProviderHealthPersistenceError):
                acquirer.acquire_scheduled_fixtures(plan)
        else:
            runner = T06AcquisitionRunner(store, acquirer)
            with pytest.raises(RunLifecycleError):
                runner.start(
                    plan,
                    observation=ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0),
                )

        assessments = FixtureCoverageRepository(store).list_for_matchweek("2026-27", "2026-09-25")
        assert len(assessments) == 1
        assert len(assessments[0].provider_attempts) == 2
        assert {attempt.provider_id for attempt in assessments[0].provider_attempts} == {
            "openfootball-json",
            "openfootball-footballtxt",
        }
        assert len(importer.source_captures()) == 2
        assert ProviderHealthRepository(store).list_for_matchweek("2026-27", "2026-09-25") == ()

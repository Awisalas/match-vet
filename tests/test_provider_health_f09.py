from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from matchvet.fixture_coverage import FixtureCoverageAssessment
from matchvet.provider_health import (
    CapabilityAvailabilityAssessment,
    CapabilityAvailabilityState,
    CapabilityIdentity,
    CoverageApplicability,
    CoverageAssessment,
    CoverageState,
    FacetApplicability,
    FailureAssessment,
    FailureState,
    FreshnessAssessment,
    FreshnessState,
    NamedSelectorFacet,
    PermissionPolicyReference,
    ProviderHealthRecord,
    ProviderIdentity,
    ReachabilityAssessment,
    ReachabilityState,
    RequestedScope,
    ScopeContract,
    ScopeFacet,
    StructuralValidityAssessment,
    StructuralValidityState,
    SubjectIdentifier,
    SubjectKind,
    UsePermissionAssessment,
    UsePermissionState,
    UtcInterval,
    provider_health_record_to_canonical_json,
)
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import open_store
from matchvet.weather import VenueLocation, WeatherRequest


def _request() -> WeatherRequest:
    return WeatherRequest(
        fixture_id="target-arsenal-coventry",
        target_time_utc="2026-09-18T19:00:00+00:00",
        cutoff_utc="2026-09-18T13:00:00+00:00",
        location=VenueLocation(
            "venue-emirates",
            "Emirates",
            51.5549,
            -0.1084,
            "official-venue",
            "https://official.example/venue",
            "2026-09-01T10:00:00+00:00",
        ),
        variables=("temperature_2m",),
    )


def _contextual_record() -> ProviderHealthRecord:
    request = _request()
    intended_use = "matchvet:research-only:t08-weather:non-commercial"
    return ProviderHealthRecord(
        provider=ProviderIdentity("open-meteo", "open-meteo-forecast"),
        capability=CapabilityIdentity(
            "weather-forecast",
            ScopeContract(
                FacetApplicability.NOT_APPLICABLE,
                FacetApplicability.NOT_APPLICABLE,
                FacetApplicability.APPLICABLE,
                FacetApplicability.APPLICABLE,
                ("request_url", "cutoff_utc"),
                CoverageApplicability.APPLICABLE,
            ),
        ),
        requested_scope=RequestedScope(
            "open-meteo-weather-query",
            ScopeFacet.not_applicable(),
            ScopeFacet.not_applicable(),
            ScopeFacet.known(UtcInterval(request.interval_start_utc, request.interval_end_utc)),
            ScopeFacet.known((SubjectIdentifier(SubjectKind.MATCH, request.fixture_id),)),
            (
                NamedSelectorFacet("request_url", ScopeFacet.known((request.url,))),
                NamedSelectorFacet("cutoff_utc", ScopeFacet.known((request.cutoff_utc,))),
            ),
        ),
        intended_use_id=intended_use,
        checked_at_utc="2026-09-18T12:00:00.000000+00:00",
        use_permission=UsePermissionAssessment(
            UsePermissionState.PERMITTED,
            PermissionPolicyReference("f08-open-meteo-non-commercial", "v1", intended_use),
        ),
        reachability=ReachabilityAssessment(ReachabilityState.UNKNOWN),
        capability_availability=CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.UNKNOWN
        ),
        structural_validity=StructuralValidityAssessment(StructuralValidityState.UNKNOWN),
        freshness=FreshnessAssessment(FreshnessState.UNKNOWN),
        coverage=CoverageAssessment(CoverageState.UNKNOWN),
        failure=FailureAssessment(FailureState.UNKNOWN),
    )


def test_contextual_health_replays_exact_scope_and_canonical_bytes_without_f01(
    tmp_path: Path,
) -> None:
    record = _contextual_record()
    encoded = provider_health_record_to_canonical_json(record)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        assert repository.persist_many((record,)) == (record.digest,)
        restored = repository.get(record.digest)
        assert restored == record
        assert restored is not None
        assert restored.requested_scope == record.requested_scope
        assert restored.provenance == ()
        assert provider_health_record_to_canonical_json(restored) == encoded


def test_contextual_retry_is_idempotent_and_replays_after_reopen(tmp_path: Path) -> None:
    record = _contextual_record()
    path = tmp_path / "matchvet.sqlite3"
    with open_store(path, private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        assert repository.persist_many((record, record)) == (record.digest,)
        assert repository.persist_many((record,)) == (record.digest,)
    with open_store(path, private_root=tmp_path) as reopened:
        repository = ProviderHealthRepository(reopened)
        assert repository.get(record.digest) == record
        assert repository.persist_many((record,)) == (record.digest,)


def test_contextual_health_refuses_fixture_attempt_provenance(tmp_path: Path) -> None:
    from matchvet.provider_health import F01ProviderAttemptState, ProviderAttemptReference

    record = _contextual_record()
    attempt = ProviderAttemptReference(
        "fake-fixture-attempt",
        record.requested_scope.scope_id,
        "open-meteo",
        "weather-forecast",
        F01ProviderAttemptState.UNAVAILABLE,
        record.checked_at_utc,
        None,
        None,
        None,
    )
    with pytest.raises(ValueError, match="F01"):
        replace(record, provenance=(attempt,))
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        assert repository.persist_many((record,)) == (record.digest,)
        assert repository.get(record.digest) == record


def test_changed_content_cannot_replace_an_exact_contextual_observation(tmp_path: Path) -> None:
    from matchvet.provider_health_repository import ProviderHealthIntegrityError

    original = _contextual_record()
    conflicting = replace(
        original, use_permission=UsePermissionAssessment(UsePermissionState.UNKNOWN)
    )
    new_observation = replace(original, checked_at_utc="2026-09-18T12:01:00.000000+00:00")
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        repository.persist_many((original,))
        with pytest.raises(ProviderHealthIntegrityError):
            repository.persist_many((new_observation, conflicting))
        assert repository.get(original.digest) == original
        assert repository.get(conflicting.digest) is None
        assert repository.get(new_observation.digest) is None


@pytest.mark.parametrize(
    "family", ["injuries", "suspensions", "lineups", "manager", "referee", "workload"]
)
def test_unresolved_contextual_families_are_not_persisted(tmp_path: Path, family: str) -> None:
    from matchvet.provider_health_repository import ProviderHealthIntegrityError

    record = _contextual_record()
    record = replace(record, capability=replace(record.capability, capability_id=family))
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        with pytest.raises(ProviderHealthIntegrityError, match="Open-Meteo weather"):
            repository.persist_many((record,))
        assert repository.get(record.digest) is None


def test_contextual_scope_and_check_time_are_independent_observation_keys(tmp_path: Path) -> None:
    original = _contextual_record()
    scope = replace(
        original.requested_scope,
        subjects=ScopeFacet.known((SubjectIdentifier(SubjectKind.MATCH, "other-match"),)),
    )
    other_scope = replace(original, requested_scope=scope)
    later = replace(original, checked_at_utc="2026-09-18T12:01:00.000000+00:00")
    other_use = "matchvet:commercial-weather:unapproved"
    unapproved = replace(
        original,
        intended_use_id=other_use,
        use_permission=UsePermissionAssessment(
            UsePermissionState.NOT_PERMITTED,
            PermissionPolicyReference("f08-open-meteo-non-commercial", "v1", other_use),
        ),
    )
    records = (original, other_scope, later, unapproved)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        assert repository.persist_many(records) == tuple(
            sorted(record.digest for record in records)
        )
        assert tuple(repository.get(record.digest) for record in records) == records


def _fixture_observation() -> tuple[FixtureCoverageAssessment, ProviderHealthRecord]:
    from matchvet.fixture_coverage import (
        ProviderAttempt,
        ProviderAttemptState,
        assess_fixture_coverage,
        fixture_scopes_for_matchweek,
    )
    from matchvet.provider_health_acquisition import build_provider_health_records

    assessment = assess_fixture_coverage(
        scopes=fixture_scopes_for_matchweek("2026-09-25", season="2026-27"),
        provider_attempts=(
            ProviderAttempt(
                attempt_id="fixture-attempt-f09-regression",
                scope_id="premier_league:2026-27:2026-09-25",
                provider_id="openfootball-json",
                capability_id="scheduled-fixtures",
                state=ProviderAttemptState.UNAVAILABLE,
                retrieved_at_utc="2026-09-18T12:00:00.000000+00:00",
            ),
        ),
        coverage_evidence=(),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
    )
    plain = build_provider_health_records(assessment)[0]
    return assessment, plain


def test_mixed_batch_keeps_fixture_replay_and_history_unchanged(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository

    assessment, fixture = _fixture_observation()
    context = _contextual_record()
    original_bytes = provider_health_record_to_canonical_json(fixture)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)
        assert repository.persist_many((fixture, context)) == tuple(
            sorted((fixture.digest, context.digest))
        )
        assert repository.get(context.digest) == context
        assert repository.get(fixture.digest) == fixture
        assert repository.list_for_assessment(assessment.digest) == (fixture,)
        assert repository.list_for_matchweek("2026-27", "2026-09-25") == (fixture,)
        restored = repository.get(fixture.digest)
        assert restored is not None
        assert provider_health_record_to_canonical_json(restored) == original_bytes


def test_corrupted_fixture_retry_rolls_back_a_preceding_contextual_insert(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import ProviderHealthIntegrityError
    from matchvet.store import MIGRATIONS

    assessment, fixture = _fixture_observation()
    context = _contextual_record()
    # Force the new context to sort before the corrupted fixture retry,
    # exercising an insert before failure rather than just prevalidation.
    for microsecond in range(100):
        context = replace(context, checked_at_utc=f"2026-09-18T12:00:00.{microsecond:06d}+00:00")
        if context.digest < fixture.digest:
            break
    assert context.digest < fixture.digest
    restore_trigger = next(
        statement
        for statement in MIGRATIONS[11].statements
        if "CREATE TRIGGER provider_health_records_no_update" in statement
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)
        repository.persist_many((fixture,))
        # Direct SQL is used only to inject corruption of retained bytes.
        with store.transaction() as transaction:
            transaction.execute("DROP TRIGGER provider_health_records_no_update")
            transaction.execute(
                "UPDATE provider_health_records SET record_json = record_json || ' ' "
                "WHERE record_digest = ?",
                (fixture.digest,),
            )
            transaction.execute(restore_trigger)
        with pytest.raises(ProviderHealthIntegrityError):
            repository.persist_many((context, fixture))
        assert repository.get(context.digest) is None
        with pytest.raises(ProviderHealthIntegrityError):
            repository.get(fixture.digest)


def test_digest_cannot_silently_replay_from_two_health_tables(tmp_path: Path) -> None:
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.provider_health_repository import ProviderHealthIntegrityError

    assessment, fixture = _fixture_observation()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        FixtureCoverageRepository(store).persist(assessment)
        repository = ProviderHealthRepository(store)
        repository.persist_many((fixture,))
        connection = store._connection_for_repository()
        connection.execute("PRAGMA ignore_check_constraints = ON")
        try:
            with store.transaction() as transaction:
                transaction.execute(
                    """
                    INSERT INTO contextual_provider_health_records (
                        record_digest, record_json, contract_version, record_schema_version,
                        provider_id, capability_id, requested_scope_id, intended_use_id,
                        checked_at_utc, first_persisted_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fixture.digest,
                        provider_health_record_to_canonical_json(fixture),
                        fixture.contract_version,
                        fixture.schema_version,
                        fixture.provider.provider_id,
                        fixture.capability.capability_id,
                        fixture.requested_scope.scope_id,
                        fixture.intended_use_id,
                        fixture.checked_at_utc,
                        fixture.checked_at_utc,
                    ),
                )
        finally:
            connection.execute("PRAGMA ignore_check_constraints = OFF")
        with pytest.raises(ProviderHealthIntegrityError, match="both"):
            repository.get(fixture.digest)


@pytest.mark.parametrize("state", [FreshnessState.FRESH, FreshnessState.STALE])
def test_explicit_weather_freshness_is_preserved_independently_of_other_dimensions(
    tmp_path: Path,
    state: FreshnessState,
) -> None:
    from matchvet.provider_health import (
        CapabilityCoverageEvidenceReference,
        CoverageWitness,
        EvidenceBasis,
        FreshnessPolicyReference,
        OtherVersionedEvidenceReference,
    )

    original = _contextual_record()
    scope_id = original.requested_scope.scope_id
    reference = OtherVersionedEvidenceReference(
        "recorded-weather-evaluation",
        "recorded-open-meteo-health-evaluation",
        "v1",
        "open-meteo",
        "weather-forecast",
        scope_id,
        "a" * 64,
    )
    basis = EvidenceBasis(
        "open-meteo",
        "weather-forecast",
        scope_id,
        (reference,),
        source_as_of_utc="2026-09-18T10:00:00.000000+00:00",
    )
    coverage = CapabilityCoverageEvidenceReference(
        "recorded-hourly-coverage",
        "recorded-open-meteo-hourly-coverage",
        "v1",
        "open-meteo",
        "weather-forecast",
        scope_id,
        "b" * 64,
        scope_complete=True,
        enumeration_complete=True,
        covered_extent_ids=("temperature_2m",),
    )
    record = replace(
        original,
        reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, basis),
        capability_availability=CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.AVAILABLE, basis
        ),
        structural_validity=StructuralValidityAssessment(StructuralValidityState.VALID, basis),
        freshness=FreshnessAssessment(
            state,
            FreshnessPolicyReference("recorded-weather-freshness", "v1", "weather-forecast"),
            basis,
        ),
        coverage=CoverageAssessment(
            CoverageState.COMPLETE,
            CoverageWitness("open-meteo", "weather-forecast", scope_id, (coverage,)),
        ),
        failure=FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=basis),
        provenance=(reference, coverage),
    )
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        repository.persist_many((record,))
        restored = repository.get(record.digest)
        assert restored == record
        assert restored is not None
        assert restored.freshness.state is state
        assert restored.use_permission.state is UsePermissionState.PERMITTED
        assert restored.capability_availability.state is CapabilityAvailabilityState.AVAILABLE
        assert restored.coverage.state is CoverageState.COMPLETE
        assert restored.failure.state is FailureState.NO_FAILURE_OBSERVED


@pytest.mark.parametrize("column", ["requested_scope_id", "capability_id", "record_json"])
def test_contextual_replay_and_retry_refuse_corrupted_scope_capability_or_bytes(
    tmp_path: Path,
    column: str,
) -> None:
    from matchvet.provider_health_repository import ProviderHealthIntegrityError
    from matchvet.store import MIGRATIONS

    record = _contextual_record()
    restore_trigger = MIGRATIONS[13].statements[1]
    value = {
        "requested_scope_id": "sha256:" + "b" * 64,
        "capability_id": "different-capability",
        "record_json": provider_health_record_to_canonical_json(record) + " ",
    }[column]
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        repository.persist_many((record,))
        connection = store._connection_for_repository()
        connection.execute("PRAGMA ignore_check_constraints = ON")
        try:
            with store.transaction() as transaction:
                transaction.execute("DROP TRIGGER contextual_provider_health_records_no_update")
                transaction.execute(
                    f"UPDATE contextual_provider_health_records SET {column} = ? "
                    "WHERE record_digest = ?",
                    (value, record.digest),
                )
                transaction.execute(restore_trigger)
        finally:
            connection.execute("PRAGMA ignore_check_constraints = OFF")
        with pytest.raises(ProviderHealthIntegrityError):
            repository.get(record.digest)
        with pytest.raises(ProviderHealthIntegrityError):
            repository.persist_many((record,))


def test_contextual_unknown_and_unbounded_query_facets_replay_exactly(tmp_path: Path) -> None:
    record = _contextual_record()
    scope = replace(
        record.requested_scope,
        time=ScopeFacet.unknown(),
        subjects=ScopeFacet.unbounded(),
        selectors=(
            NamedSelectorFacet("request_url", ScopeFacet.unknown()),
            NamedSelectorFacet("cutoff_utc", ScopeFacet.unknown()),
        ),
    )
    record = replace(record, requested_scope=scope)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        repository = ProviderHealthRepository(store)
        repository.persist_many((record,))
        restored = repository.get(record.digest)
        assert restored is not None
        assert restored.requested_scope == scope
        assert restored.requested_scope.time.state.value == "UNKNOWN"
        assert restored.requested_scope.subjects.state.value == "UNBOUNDED"
        assert all(
            selector.facet.state.value == "UNKNOWN"
            for selector in restored.requested_scope.selectors
        )
        assert restored.freshness.state is FreshnessState.UNKNOWN
        assert restored.failure.state is FailureState.UNKNOWN

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from matchvet.fixture_coverage import (
    CoverageBasis,
    CoverageBasisKind,
    FixtureScope,
    MatchweekScheduleState,
    ScopeCoverageState,
)
from matchvet.fixture_coverage import (
    FixtureCoverageAssessment as F01FixtureCoverageAssessment,
)
from matchvet.fixture_coverage import (
    FixtureScopeAssessment as F01FixtureScopeAssessment,
)
from matchvet.fixture_coverage import (
    ProviderAttempt as F01ProviderAttempt,
)
from matchvet.fixture_coverage import (
    ProviderAttemptState as F01ProviderAttemptState,
)
from matchvet.fixture_coverage import (
    ProviderCoverageEvidence as F01ProviderCoverageEvidence,
)
from matchvet.provider_health import (
    CapabilityAvailabilityAssessment,
    CapabilityAvailabilityState,
    CapabilityCoverageEvidenceReference,
    CapabilityIdentity,
    CompetitionScope,
    CoverageApplicability,
    CoverageAssessment,
    CoverageState,
    CoverageWitness,
    EvidenceBasis,
    EvidenceReferenceKind,
    F01CoverageBasisKind,
    F01FixtureScopeReference,
    FacetApplicability,
    FailureAssessment,
    FailureReasonCode,
    FailureState,
    FixtureCoverageAssessmentReference,
    FreshnessAssessment,
    FreshnessEvidenceReference,
    FreshnessPolicyReference,
    FreshnessState,
    LocalDateRange,
    NamedSelectorFacet,
    OtherVersionedEvidenceReference,
    PermissionPolicyReference,
    ProviderAttemptReference,
    ProviderCoverageEvidenceReference,
    ProviderHealthRecord,
    ProviderIdentity,
    ProviderMetadataReference,
    ReachabilityAssessment,
    ReachabilityState,
    RequestedScope,
    ScopeContract,
    ScopeFacet,
    ScopeFacetState,
    SeasonScope,
    SourceAssertionReference,
    SourceCaptureReference,
    StructuralValidityAssessment,
    StructuralValidityState,
    SubjectIdentifier,
    SubjectKind,
    UsePermissionAssessment,
    UsePermissionState,
    UtcInterval,
    provider_health_record_from_canonical_json,
    provider_health_record_to_canonical_json,
)
from matchvet.provider_health import (
    F01ProviderAttemptState as HealthF01ProviderAttemptState,
)


def unknown_provider_health_record() -> ProviderHealthRecord:
    capability = CapabilityIdentity(
        capability_id="scheduled-fixtures",
        scope_contract=ScopeContract(
            competition=FacetApplicability.APPLICABLE,
            season=FacetApplicability.APPLICABLE,
            time=FacetApplicability.APPLICABLE,
            subjects=FacetApplicability.APPLICABLE,
            selector_keys=("matchweek", "venue"),
            coverage=CoverageApplicability.APPLICABLE,
        ),
    )
    requested_scope = RequestedScope(
        scope_kind="fixture-query",
        competition=ScopeFacet.unknown(),
        season=ScopeFacet.unknown(),
        time=ScopeFacet.unknown(),
        subjects=ScopeFacet.unknown(),
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.unknown()),
            NamedSelectorFacet("venue", ScopeFacet.unknown()),
        ),
    )
    return ProviderHealthRecord.create(
        provider=ProviderIdentity(
            provider_id="openfootball-json",
            source_lineage_id="openfootball-footballtxt",
        ),
        capability=capability,
        requested_scope=requested_scope,
        intended_use_id="private-matchweek-research",
        checked_at_utc="2026-09-16T12:00:00.000000+00:00",
        use_permission=UsePermissionAssessment(UsePermissionState.UNKNOWN),
        reachability=ReachabilityAssessment(ReachabilityState.UNKNOWN),
        capability_availability=CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.UNKNOWN
        ),
        structural_validity=StructuralValidityAssessment(StructuralValidityState.UNKNOWN),
        freshness=FreshnessAssessment(FreshnessState.UNKNOWN),
        coverage=CoverageAssessment(CoverageState.UNKNOWN),
        failure=FailureAssessment(FailureState.UNKNOWN),
    )


def f01_fixture_scope_reference() -> F01FixtureScopeReference:
    return F01FixtureScopeReference.from_f01(
        FixtureScope(
            league_key="premier_league",
            season="2026-27",
            matchweek_friday="2026-09-18",
        )
    )


def f01_provider_health_record(*, local_time_scope: bool = False) -> ProviderHealthRecord:
    record = unknown_provider_health_record()
    fixture_scope = f01_fixture_scope_reference()
    time_scope = (
        LocalDateRange("2026-09-18", "2026-09-22", "Africa/Lagos")
        if local_time_scope
        else fixture_scope.interval
    )
    return replace(
        record,
        capability=CapabilityIdentity(
            capability_id=record.capability.capability_id,
            scope_contract=ScopeContract(
                competition=FacetApplicability.APPLICABLE,
                season=FacetApplicability.APPLICABLE,
                time=FacetApplicability.APPLICABLE,
                subjects=FacetApplicability.NOT_APPLICABLE,
                selector_keys=(),
                coverage=CoverageApplicability.APPLICABLE,
            ),
        ),
        requested_scope=RequestedScope(
            scope_kind="fixture-query",
            competition=ScopeFacet.known(
                CompetitionScope(fixture_scope.league_key, fixture_scope.league_key)
            ),
            season=ScopeFacet.known(SeasonScope(fixture_scope.season, fixture_scope.season)),
            time=ScopeFacet.known(time_scope),
            subjects=ScopeFacet.not_applicable(),
            selectors=(),
            fixture_scope=fixture_scope,
        ),
    )


def exact_evidence_basis(
    record: ProviderHealthRecord,
    *,
    evidence_id: str = "observation",
    source_as_of_utc: str | None = None,
) -> EvidenceBasis:
    return EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        references=(
            OtherVersionedEvidenceReference(
                evidence_id=evidence_id,
                evidence_kind="provider-observation",
                version="1",
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=record.requested_scope.evidence_scope_id,
                digest=f"sha256:{evidence_id}",
            ),
        ),
        source_as_of_utc=source_as_of_utc,
    )


def exact_coverage_reference(
    record: ProviderHealthRecord,
    *,
    evidence_id: str = "coverage-evidence",
    affirmatively_empty: bool = False,
    partial: bool = False,
) -> ProviderCoverageEvidenceReference:
    time_scope = record.requested_scope.time.value
    bounds_start_utc: str | None
    bounds_end_utc: str | None
    if isinstance(time_scope, UtcInterval):
        bounds_start_utc = time_scope.start_utc
        bounds_end_utc = time_scope.end_utc
    elif isinstance(time_scope, LocalDateRange):
        interval = record.requested_scope.fixture_scope
        bounds_start_utc = None if interval is None else interval.window_start_utc
        bounds_end_utc = None if interval is None else interval.window_end_utc
    else:
        bounds_start_utc = None
        bounds_end_utc = None
    return ProviderCoverageEvidenceReference(
        evidence_id=evidence_id,
        attempt_id="coverage-attempt",
        scope_id=record.requested_scope.evidence_scope_id,
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        provider_competition_key=(
            "eng.1"
            if record.requested_scope.fixture_scope is None
            else record.requested_scope.fixture_scope.league_key
        ),
        provider_season=(
            "2026-27"
            if record.requested_scope.fixture_scope is None
            else record.requested_scope.fixture_scope.season
        ),
        capture_id="coverage-capture",
        capture_digest="sha256:coverage-capture",
        provider_use_policy_id=None,
        permitted_for_use=False,
        coverage_basis_kind=F01CoverageBasisKind.VERSIONED_SOURCE_CONTRACT,
        coverage_basis_id="fixture-list-contract",
        coverage_basis_version="1",
        bounds_start_utc=bounds_start_utc,
        bounds_end_utc=bounds_end_utc,
        required_partition_ids=("query-partition",),
        accounted_partition_ids=() if partial else ("query-partition",),
        pagination_exhausted=True,
        affirmatively_empty=affirmatively_empty,
    )


def exact_coverage_witness(
    record: ProviderHealthRecord,
    evidence: ProviderCoverageEvidenceReference,
) -> CoverageWitness:
    attempt = ProviderAttemptReference(
        attempt_id=evidence.attempt_id,
        scope_id=record.requested_scope.evidence_scope_id,
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        state=HealthF01ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=200,
        capture_id=evidence.capture_id,
        capture_digest=evidence.capture_digest,
    )
    return CoverageWitness(
        record.provider.provider_id,
        record.capability.capability_id,
        record.requested_scope.evidence_scope_id,
        (evidence,),
        (attempt,),
    )


def reachable_for_witness(
    record: ProviderHealthRecord, witness: CoverageWitness
) -> ProviderHealthRecord:
    return replace(
        record,
        reachability=ReachabilityAssessment(
            ReachabilityState.REACHABLE,
            EvidenceBasis(
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=record.requested_scope.evidence_scope_id,
                references=witness.attempts,
            ),
        ),
    )


def generic_coverage_reference(
    record: ProviderHealthRecord,
    *,
    evidence_id: str = "generic-coverage",
    affirmatively_empty: bool = False,
    partial: bool = False,
) -> CapabilityCoverageEvidenceReference:
    return CapabilityCoverageEvidenceReference(
        evidence_id=evidence_id,
        evidence_kind="provider-capability-coverage",
        version="1",
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.scope_id,
        digest=f"sha256:{evidence_id}",
        scope_complete=not partial,
        enumeration_complete=True,
        known_gap_ids=("query-gap",) if partial else (),
        affirmatively_empty=affirmatively_empty,
    )


def generic_coverage_witness(
    record: ProviderHealthRecord,
    evidence: CapabilityCoverageEvidenceReference,
) -> CoverageWitness:
    return CoverageWitness(
        record.provider.provider_id,
        record.capability.capability_id,
        record.requested_scope.scope_id,
        (evidence,),
    )


def contextual_coverage_reference(
    record: ProviderHealthRecord,
    *,
    evidence_id: str = "person-coverage",
    scope_complete: bool = True,
    affirmatively_empty: bool = False,
    covered_extent_ids: tuple[str, ...] = (),
    known_gap_ids: tuple[str, ...] = (),
    capture_id: str | None = None,
    capture_digest: str | None = None,
) -> CapabilityCoverageEvidenceReference:
    return CapabilityCoverageEvidenceReference(
        evidence_id=evidence_id,
        evidence_kind="person-metrics",
        version="3",
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        digest=f"sha256:{evidence_id}",
        scope_complete=scope_complete,
        enumeration_complete=True,
        covered_extent_ids=covered_extent_ids,
        known_gap_ids=known_gap_ids,
        affirmatively_empty=affirmatively_empty,
        capture_id=capture_id,
        capture_digest=capture_digest,
    )


def f01_attempt(*, scope_id: str = "f01-scope") -> F01ProviderAttempt:
    return F01ProviderAttempt(
        attempt_id="f01-attempt",
        scope_id=scope_id,
        provider_id="openfootball-json",
        capability_id="scheduled-fixtures",
        state=F01ProviderAttemptState.CAPTURED,
        retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
        http_status=503,
        capture_id="f01-capture",
        capture_digest="sha256:f01-capture",
    )


def f01_coverage(attempt: F01ProviderAttempt) -> F01ProviderCoverageEvidence:
    return F01ProviderCoverageEvidence(
        evidence_id="f01-coverage",
        attempt_id=attempt.attempt_id,
        scope_id=attempt.scope_id,
        provider_competition_key="premier_league",
        provider_season="2026-27",
        capture_id=attempt.capture_id or "",
        capture_digest=attempt.capture_digest or "",
        coverage_basis=CoverageBasis(
            kind=CoverageBasisKind.VERSIONED_SOURCE_CONTRACT,
            reference_id="fixture-source-contract",
            version="1",
        ),
        provider_use_policy_id="provider-use-v1",
        permitted_for_use=True,
        bounds=None,
        required_partition_ids=(),
        accounted_partition_ids=(),
        pagination_exhausted=True,
        affirmatively_empty=False,
    )


def f01_assessment(
    fixture_scope: FixtureScope,
    attempt: F01ProviderAttempt,
    coverage: F01ProviderCoverageEvidence,
    *,
    include_scope: bool = True,
) -> F01FixtureCoverageAssessment:
    scope_assessments = (
        (
            F01FixtureScopeAssessment(
                scope=fixture_scope,
                coverage_state=ScopeCoverageState.COMPLETE,
                provider_attempt_ids=(attempt.attempt_id,),
                coverage_evidence_ids=(coverage.evidence_id,),
                fixture_revisions=(),
                identity_blocker_candidate_ids=(),
                freshness_results=(),
                current_coverage_evidence_ids=(coverage.evidence_id,),
                stale_coverage_evidence_ids=(),
            ),
        )
        if include_scope
        else ()
    )
    return F01FixtureCoverageAssessment(
        contract_version="fixture-coverage-v2-v2",
        schema_version=2,
        freshness_policy_id=None,
        scope_assessments=scope_assessments,
        provider_attempts=(attempt,),
        coverage_evidence=(coverage,),
        fixture_revisions=(),
        identity_resolutions=(),
        freshness_results=(),
        schedule_state=MatchweekScheduleState.UNKNOWN,
    )


def test_unknown_observation_round_trips_without_inferred_defaults() -> None:
    record = unknown_provider_health_record()

    restored = provider_health_record_from_canonical_json(
        provider_health_record_to_canonical_json(record)
    )

    assert restored == record
    assert restored.use_permission.state is UsePermissionState.UNKNOWN
    assert restored.reachability.state is ReachabilityState.UNKNOWN
    assert restored.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
    assert restored.structural_validity.state is StructuralValidityState.UNKNOWN
    assert restored.freshness.state is FreshnessState.UNKNOWN
    assert restored.coverage.state is CoverageState.UNKNOWN
    assert restored.failure.state is FailureState.UNKNOWN
    assert restored.requested_scope.competition.state is ScopeFacetState.UNKNOWN
    assert restored.requested_scope.season.state is ScopeFacetState.UNKNOWN
    assert restored.requested_scope.time.state is ScopeFacetState.UNKNOWN
    assert restored.requested_scope.subjects.state is ScopeFacetState.UNKNOWN
    assert all(
        selector.facet.state is ScopeFacetState.UNKNOWN
        for selector in restored.requested_scope.selectors
    )


def test_known_permission_requires_its_versioned_intended_use_policy() -> None:
    with pytest.raises(ValueError, match="policy"):
        UsePermissionAssessment(UsePermissionState.PERMITTED)

    wrong_use_policy = PermissionPolicyReference(
        policy_id="public-feed-policy",
        version="3",
        intended_use_id="redistribution",
    )
    with pytest.raises(ValueError, match="intended use"):
        replace(
            unknown_provider_health_record(),
            use_permission=UsePermissionAssessment(
                UsePermissionState.NOT_PERMITTED,
                policy=wrong_use_policy,
            ),
        )

    permitted = replace(
        unknown_provider_health_record(),
        use_permission=UsePermissionAssessment(
            UsePermissionState.PERMITTED,
            policy=PermissionPolicyReference(
                policy_id="private-research-policy",
                version="1",
                intended_use_id="private-matchweek-research",
            ),
        ),
    )
    assert permitted.use_permission.state is UsePermissionState.PERMITTED
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(permitted)
        )
        == permitted
    )


def test_not_applicable_coverage_requires_a_capability_contract() -> None:
    record = unknown_provider_health_record()

    with pytest.raises(ValueError, match="Coverage"):
        replace(record, coverage=CoverageAssessment(CoverageState.NOT_APPLICABLE))

    not_applicable_capability = replace(
        record.capability,
        scope_contract=replace(
            record.capability.scope_contract,
            coverage=CoverageApplicability.NOT_APPLICABLE,
        ),
    )
    accepted = replace(
        record,
        capability=not_applicable_capability,
        coverage=CoverageAssessment(CoverageState.NOT_APPLICABLE),
    )
    assert accepted.coverage.state is CoverageState.NOT_APPLICABLE


def test_scope_facet_states_have_distinct_identities_and_follow_applicability() -> None:
    record = unknown_provider_health_record()
    base_scope = record.requested_scope
    competition_states: tuple[ScopeFacet[CompetitionScope], ...] = (
        ScopeFacet.known(CompetitionScope("premier_league", "eng.1")),
        ScopeFacet.unbounded(),
        ScopeFacet.not_applicable(),
        ScopeFacet.unknown(),
    )
    scopes = tuple(replace(base_scope, competition=facet) for facet in competition_states)

    assert len({scope.scope_id for scope in scopes}) == 4
    assert replace(record, requested_scope=scopes[0]).requested_scope == scopes[0]
    assert replace(record, requested_scope=scopes[1]).requested_scope == scopes[1]
    assert replace(record, requested_scope=scopes[3]).requested_scope == scopes[3]
    with pytest.raises(ValueError, match="competition"):
        replace(record, requested_scope=scopes[2])
    non_applicable_selector_scope = replace(
        base_scope,
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.unknown()),
            NamedSelectorFacet("venue", ScopeFacet.not_applicable()),
        ),
    )
    with pytest.raises(ValueError, match="selector facet"):
        replace(record, requested_scope=non_applicable_selector_scope)

    with pytest.raises(ValueError, match="KNOWN selector"):
        NamedSelectorFacet("venue", ScopeFacet.known("all"))  # type: ignore[arg-type]

    no_competition_contract = replace(
        record.capability.scope_contract,
        competition=FacetApplicability.NOT_APPLICABLE,
    )
    accepted = replace(
        record,
        capability=replace(record.capability, scope_contract=no_competition_contract),
        requested_scope=scopes[2],
    )
    assert accepted.requested_scope.competition.state is ScopeFacetState.NOT_APPLICABLE


def test_record_digest_binds_provider_capability_scope_use_and_check_time() -> None:
    record = unknown_provider_health_record()
    different_scope = replace(
        record.requested_scope,
        season=ScopeFacet.known(SeasonScope("2026-27", "2026-27")),
    )
    variants = (
        record,
        replace(
            record,
            provider=ProviderIdentity("openfootball-footballtxt", "openfootball-footballtxt"),
        ),
        replace(
            record,
            capability=replace(record.capability, capability_id="season-results"),
        ),
        replace(record, requested_scope=different_scope),
        replace(record, intended_use_id="redistribution"),
        replace(record, checked_at_utc="2026-09-16T12:00:01.000000+00:00"),
    )

    assert len({variant.digest for variant in variants}) == len(variants)

    different_provenance = replace(
        record,
        provenance=(
            OtherVersionedEvidenceReference(
                evidence_id="changed-observation",
                evidence_kind="provider-observation",
                version="1",
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=record.requested_scope.evidence_scope_id,
                digest="sha256:changed-observation",
            ),
        ),
    )
    assert different_provenance.digest != record.digest


def test_distinct_feeds_can_share_source_lineage_without_combining_identity() -> None:
    json_feed = unknown_provider_health_record()
    text_feed = replace(
        json_feed,
        provider=ProviderIdentity("openfootball-footballtxt", "openfootball-footballtxt"),
    )

    assert json_feed.provider.provider_id != text_feed.provider.provider_id
    assert json_feed.provider.source_lineage_id == "openfootball-footballtxt"
    assert text_feed.provider.source_lineage_id == json_feed.provider.source_lineage_id
    assert json_feed.digest != text_feed.digest


def test_f01_fixture_scope_is_a_typed_exact_scope_bridge() -> None:
    record = f01_provider_health_record()
    fixture_scope = record.requested_scope.fixture_scope
    assert fixture_scope is not None
    assert record.requested_scope.evidence_scope_id == fixture_scope.scope_id

    with pytest.raises(ValueError, match="competition"):
        replace(
            record.requested_scope,
            competition=ScopeFacet.known(CompetitionScope("la_liga", "esp.1")),
        )
    with pytest.raises(ValueError, match="competition IDs"):
        replace(
            record.requested_scope,
            competition=ScopeFacet.known(CompetitionScope("serie_a", "premier_league")),
        )
    with pytest.raises(ValueError, match="season"):
        replace(
            record.requested_scope,
            season=ScopeFacet.known(SeasonScope("2025-26", "2025-26")),
        )
    with pytest.raises(ValueError, match="season IDs"):
        replace(
            record.requested_scope,
            season=ScopeFacet.known(SeasonScope("2025-26", "2026-27")),
        )
    with pytest.raises(ValueError, match="exact time scope"):
        replace(
            record.requested_scope,
            time=ScopeFacet.known(
                UtcInterval("2026-09-18T00:00:00.000000+00:00", "2026-09-22T00:00:00.000000+00:00")
            ),
        )
    with pytest.raises(ValueError, match="canonical Matchweek"):
        F01FixtureScopeReference(
            league_key="premier_league",
            season="2026-27",
            matchweek_friday="2026-09-18",
            scope_id="premier_league:2026-27:2026-09-18",
            window_start_utc="2026-09-18T00:00:00.000000+00:00",
            window_end_utc="2026-09-22T00:00:00.000000+00:00",
        )

    unattached_attempt = ProviderAttemptReference.from_f01(
        f01_attempt(scope_id=unknown_provider_health_record().requested_scope.scope_id)
    )
    with pytest.raises(ValueError, match="typed FixtureScope"):
        replace(unknown_provider_health_record(), provenance=(unattached_attempt,))

    with pytest.raises(ValueError, match="capture ID"):
        ProviderAttemptReference(
            attempt_id="empty-capture-attempt",
            scope_id=fixture_scope.scope_id,
            provider_id="openfootball-json",
            capability_id="scheduled-fixtures",
            state=HealthF01ProviderAttemptState.CAPTURED,
            retrieved_at_utc="2026-09-16T12:00:00.000000+00:00",
            http_status=200,
            capture_id="",
            capture_digest="",
        )


def test_known_freshness_requires_a_versioned_policy_for_the_capability() -> None:
    record = unknown_provider_health_record()

    with pytest.raises(ValueError, match="freshness policy"):
        FreshnessAssessment(FreshnessState.FRESH)

    policy = FreshnessPolicyReference(
        policy_id="fixture-source-age",
        version="v2",
        capability_id="scheduled-fixtures",
    )
    evidence = EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        references=(
            OtherVersionedEvidenceReference(
                evidence_id="source-as-of",
                evidence_kind="source-as-of-time",
                version="1",
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=record.requested_scope.evidence_scope_id,
                digest="sha256:source-time",
            ),
        ),
        source_as_of_utc="2026-09-15T12:00:00.000000+00:00",
    )
    stale = replace(
        record,
        freshness=FreshnessAssessment(FreshnessState.STALE, policy=policy, evidence=evidence),
    )
    assert stale.freshness.state is FreshnessState.STALE

    wrong_capability_policy = replace(policy, capability_id="season-results")
    with pytest.raises(ValueError, match="capability"):
        replace(
            record,
            freshness=FreshnessAssessment(
                FreshnessState.FRESH,
                policy=wrong_capability_policy,
                evidence=evidence,
            ),
        )


def test_every_explicit_dimension_state_is_typed_and_independent() -> None:
    record = unknown_provider_health_record()
    basis = exact_evidence_basis(record)
    policy = PermissionPolicyReference("research-use", "2", "private-matchweek-research")
    freshness_policy = FreshnessPolicyReference(
        "fixture-age", "v1", record.capability.capability_id
    )
    freshness_basis = exact_evidence_basis(
        record,
        evidence_id="source-as-of",
        source_as_of_utc="2026-09-15T12:00:00.000000+00:00",
    )

    permission_results = (
        UsePermissionAssessment(UsePermissionState.UNKNOWN),
        UsePermissionAssessment(UsePermissionState.PERMITTED, policy),
        UsePermissionAssessment(UsePermissionState.NOT_PERMITTED, policy),
    )
    reachability_results = (
        ReachabilityAssessment(ReachabilityState.UNKNOWN),
        ReachabilityAssessment(ReachabilityState.REACHABLE, basis),
        ReachabilityAssessment(ReachabilityState.UNREACHABLE, basis),
    )
    availability_results = (
        CapabilityAvailabilityAssessment(CapabilityAvailabilityState.UNKNOWN),
        CapabilityAvailabilityAssessment(CapabilityAvailabilityState.AVAILABLE, basis),
        CapabilityAvailabilityAssessment(CapabilityAvailabilityState.UNAVAILABLE, basis),
    )
    validity_results = (
        StructuralValidityAssessment(StructuralValidityState.UNKNOWN),
        StructuralValidityAssessment(StructuralValidityState.VALID, basis),
        StructuralValidityAssessment(StructuralValidityState.INVALID, basis),
    )
    freshness_results = (
        FreshnessAssessment(FreshnessState.UNKNOWN),
        FreshnessAssessment(FreshnessState.FRESH, freshness_policy, freshness_basis),
        FreshnessAssessment(FreshnessState.STALE, freshness_policy, freshness_basis),
    )
    failure_results = (
        FailureAssessment(FailureState.UNKNOWN),
        FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=basis),
        FailureAssessment(
            FailureState.FAILED,
            reason_codes=(FailureReasonCode.unknown_reason(),),
            evidence=basis,
        ),
    )
    coverage_reference = generic_coverage_reference(record)
    affirmative_coverage_reference = generic_coverage_reference(
        record, evidence_id="empty-evidence", affirmatively_empty=True
    )
    coverage_witness = generic_coverage_witness(record, coverage_reference)
    affirmative_coverage_witness = generic_coverage_witness(record, affirmative_coverage_reference)
    partial_coverage_witness = generic_coverage_witness(
        record, generic_coverage_reference(record, partial=True)
    )
    coverage_results = (
        CoverageAssessment(CoverageState.UNKNOWN),
        CoverageAssessment(CoverageState.COMPLETE, coverage_witness),
        CoverageAssessment(CoverageState.CONFIRMED_EMPTY, affirmative_coverage_witness),
        CoverageAssessment(CoverageState.PARTIAL, partial_coverage_witness),
    )

    assert {item.state for item in permission_results} == set(UsePermissionState)
    assert {item.state for item in reachability_results} == set(ReachabilityState)
    assert {item.state for item in availability_results} == set(CapabilityAvailabilityState)
    assert {item.state for item in validity_results} == set(StructuralValidityState)
    assert {item.state for item in freshness_results} == set(FreshnessState)
    assert {item.state for item in failure_results} == set(FailureState)
    assert {item.state for item in coverage_results} == set(CoverageState) - {
        CoverageState.NOT_APPLICABLE
    }
    accepted_states = (
        tuple(replace(record, use_permission=value) for value in permission_results),
        tuple(replace(record, reachability=value) for value in reachability_results),
        tuple(replace(record, capability_availability=value) for value in availability_results),
        tuple(replace(record, structural_validity=value) for value in validity_results),
        tuple(replace(record, freshness=value) for value in freshness_results),
        tuple(replace(record, coverage=value) for value in coverage_results),
        tuple(replace(record, failure=value) for value in failure_results),
    )
    assert tuple(len(values) for values in accepted_states) == (3, 3, 3, 3, 3, 4, 3)
    parsed_but_unfresh = replace(
        record,
        capability_availability=CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.AVAILABLE, basis
        ),
        structural_validity=StructuralValidityAssessment(StructuralValidityState.VALID, basis),
    )
    assert parsed_but_unfresh.freshness.state is FreshnessState.UNKNOWN
    assert parsed_but_unfresh.coverage.state is CoverageState.UNKNOWN

    partial = replace(
        record,
        reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, basis),
        capability_availability=CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.UNAVAILABLE, basis
        ),
        structural_validity=StructuralValidityAssessment(StructuralValidityState.INVALID, basis),
        freshness=freshness_results[2],
        coverage=coverage_results[3],
        failure=failure_results[2],
    )
    assert partial.reachability.state is ReachabilityState.REACHABLE
    assert partial.capability_availability.state is CapabilityAvailabilityState.UNAVAILABLE
    assert partial.structural_validity.state is StructuralValidityState.INVALID
    assert partial.freshness.state is FreshnessState.STALE
    assert partial.coverage.state is CoverageState.PARTIAL
    assert partial.failure.state is FailureState.FAILED
    assert not hasattr(partial, "health")
    assert not hasattr(partial, "is_healthy")
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(partial)
        )
        == partial
    )


def test_known_states_require_exact_scoped_evidence_and_policy_basis() -> None:
    record = unknown_provider_health_record()
    wrong_scope_basis = replace(exact_evidence_basis(record), scope_id="different-query-scope")

    with pytest.raises(ValueError, match="reachability requires an evidence basis"):
        ReachabilityAssessment(ReachabilityState.REACHABLE)
    with pytest.raises(ValueError, match="availability requires an evidence basis"):
        CapabilityAvailabilityAssessment(CapabilityAvailabilityState.AVAILABLE)
    with pytest.raises(ValueError, match="validity requires an evidence basis"):
        StructuralValidityAssessment(StructuralValidityState.VALID)
    with pytest.raises(ValueError, match="evidence basis"):
        replace(record, reachability=ReachabilityAssessment(ReachabilityState.REACHABLE))
    with pytest.raises(ValueError, match="provider/capability/scope"):
        replace(
            record,
            reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, wrong_scope_basis),
        )
    unknown_freshness = FreshnessAssessment(
        FreshnessState.UNKNOWN,
        policy=FreshnessPolicyReference("fixture-age", "v1", record.capability.capability_id),
    )
    unknown_permission = UsePermissionAssessment(
        UsePermissionState.UNKNOWN,
        PermissionPolicyReference("policy", "1", record.intended_use_id),
    )
    assert unknown_freshness.state is FreshnessState.UNKNOWN
    assert unknown_permission.state is UsePermissionState.UNKNOWN
    equivalent_freshness_evidence = replace(
        record,
        freshness=FreshnessAssessment(
            FreshnessState.FRESH,
            policy=FreshnessPolicyReference("fixture-age", "v1", record.capability.capability_id),
            evidence=EvidenceBasis(
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=record.requested_scope.evidence_scope_id,
                references=(
                    FreshnessEvidenceReference(
                        evidence_id="freshness-check",
                        version="1",
                        provider_id=record.provider.provider_id,
                        capability_id=record.capability.capability_id,
                        scope_id=record.requested_scope.evidence_scope_id,
                        digest="sha256:freshness-check",
                    ),
                ),
            ),
        ),
    )
    assert equivalent_freshness_evidence.freshness.state is FreshnessState.FRESH
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(equivalent_freshness_evidence)
        )
        == equivalent_freshness_evidence
    )


def test_attempt_retrieval_time_alone_cannot_establish_freshness() -> None:
    record = f01_provider_health_record()
    fixture_scope = record.requested_scope.fixture_scope
    assert fixture_scope is not None
    attempt = ProviderAttemptReference.from_f01(f01_attempt(scope_id=fixture_scope.scope_id))
    attempt_only_basis = EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        references=(attempt,),
    )
    policy = FreshnessPolicyReference("fixture-age", "v1", record.capability.capability_id)

    with pytest.raises(ValueError, match="source-as-of time or typed versioned freshness evidence"):
        FreshnessAssessment(FreshnessState.FRESH, policy, attempt_only_basis)


def test_scope_subject_time_and_named_filter_values_bind_identity() -> None:
    record = unknown_provider_health_record()
    scope = record.requested_scope
    known_subject = SubjectIdentifier(SubjectKind.TEAM, "arsenal")
    known_time = UtcInterval("2026-09-18T00:00:00.000000+00:00", "2026-09-22T00:00:00.000000+00:00")
    specific = replace(
        scope,
        time=ScopeFacet.known(known_time),
        subjects=ScopeFacet.known((known_subject,)),
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-5",))),
            NamedSelectorFacet("venue", ScopeFacet.known(("emirates",))),
        ),
    )
    changed_time = replace(
        specific,
        time=ScopeFacet.known(
            UtcInterval(
                "2026-09-19T00:00:00.000000+00:00",
                "2026-09-22T00:00:00.000000+00:00",
            )
        ),
    )
    changed_subject = replace(
        specific,
        subjects=ScopeFacet.known((SubjectIdentifier(SubjectKind.TEAM, "chelsea"),)),
    )
    changed_filter = replace(
        specific,
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-6",))),
            NamedSelectorFacet("venue", ScopeFacet.known(("emirates",))),
        ),
    )

    assert (
        len(
            {
                replace(record, requested_scope=value).digest
                for value in (specific, changed_time, changed_subject, changed_filter)
            }
        )
        == 4
    )
    reordered = replace(
        specific,
        subjects=ScopeFacet.known(
            (
                SubjectIdentifier(SubjectKind.TEAM, "arsenal"),
                SubjectIdentifier(SubjectKind.MATCH, "m1"),
            )
        ),
        selectors=(
            NamedSelectorFacet("venue", ScopeFacet.known(("emirates", "national-stadium"))),
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-5",))),
        ),
    )
    normalized = replace(
        specific,
        subjects=ScopeFacet.known(
            (
                SubjectIdentifier(SubjectKind.MATCH, "m1"),
                SubjectIdentifier(SubjectKind.TEAM, "arsenal"),
            )
        ),
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-5",))),
            NamedSelectorFacet("venue", ScopeFacet.known(("national-stadium", "emirates"))),
        ),
    )
    assert reordered.scope_id == normalized.scope_id


def test_local_date_scope_preserves_timezone_and_half_open_bounds() -> None:
    record = unknown_provider_health_record()
    lagos_dates = LocalDateRange("2026-09-18", "2026-09-22", "Africa/Lagos")
    utc_dates = LocalDateRange("2026-09-18", "2026-09-22", "UTC")
    opaque_zone_dates = LocalDateRange("2026-09-18", "2026-09-22", "Mars/Olympus_Mons")
    lagos_scope = replace(record.requested_scope, time=ScopeFacet.known(lagos_dates))
    utc_scope = replace(record.requested_scope, time=ScopeFacet.known(utc_dates))
    opaque_zone_scope = replace(record.requested_scope, time=ScopeFacet.known(opaque_zone_dates))

    assert lagos_scope.scope_id != utc_scope.scope_id
    assert lagos_scope.scope_id != opaque_zone_scope.scope_id
    lagos_record = replace(record, requested_scope=lagos_scope)
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(lagos_record)
        )
        == lagos_record
    )
    with pytest.raises(ValueError, match="end after"):
        LocalDateRange("2026-09-22", "2026-09-22", "Africa/Lagos")
    with pytest.raises(ValueError, match="IANA-style"):
        LocalDateRange("2026-09-18", "2026-09-22", "not-a-zone")
    opaque_zone_record = replace(record, requested_scope=opaque_zone_scope)
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(opaque_zone_record)
        )
        == opaque_zone_record
    )

    local_record = f01_provider_health_record(local_time_scope=True)
    local_reference = exact_coverage_reference(local_record)
    local_witness = exact_coverage_witness(local_record, local_reference)
    local_record = reachable_for_witness(local_record, local_witness)
    accepted = replace(
        local_record,
        coverage=CoverageAssessment(
            CoverageState.COMPLETE,
            local_witness,
        ),
    )
    assert accepted.coverage.state is CoverageState.COMPLETE
    with pytest.raises(ValueError, match="requested time scope"):
        replace(
            local_record,
            coverage=CoverageAssessment(
                CoverageState.COMPLETE,
                exact_coverage_witness(
                    local_record,
                    replace(
                        local_reference,
                        bounds_start_utc="2026-09-10T00:00:00.000000+00:00",
                        bounds_end_utc="2026-09-11T00:00:00.000000+00:00",
                    ),
                ),
            ),
        )


def test_coverage_requires_exact_provider_capability_scope_and_affirmative_empty() -> None:
    record = f01_provider_health_record()
    reference = exact_coverage_reference(record)
    witness = exact_coverage_witness(record, reference)
    record = reachable_for_witness(record, witness)

    mismatched_references = (
        replace(reference, provider_id="different-provider"),
        replace(reference, capability_id="different-capability"),
        replace(reference, scope_id="different-scope"),
    )
    for mismatched_reference in mismatched_references:
        with pytest.raises(ValueError, match="match its witness"):
            CoverageWitness(
                record.provider.provider_id,
                record.capability.capability_id,
                record.requested_scope.evidence_scope_id,
                (mismatched_reference,),
                witness.attempts,
            )
    with pytest.raises(ValueError, match="affirmative"):
        CoverageAssessment(CoverageState.CONFIRMED_EMPTY, witness)
    with pytest.raises(ValueError, match="evidence"):
        CoverageAssessment(CoverageState.COMPLETE)
    with pytest.raises(ValueError, match="PARTIAL evidence"):
        replace(record, coverage=CoverageAssessment(CoverageState.PARTIAL, witness))

    incomplete_reference = replace(
        reference,
        pagination_exhausted=False,
        accounted_partition_ids=(),
        affirmatively_empty=True,
    )
    incomplete_witness = exact_coverage_witness(record, incomplete_reference)
    with pytest.raises(ValueError, match="complete scope"):
        CoverageAssessment(CoverageState.COMPLETE, incomplete_witness)
    with pytest.raises(ValueError, match="CONFIRMED_EMPTY"):
        CoverageAssessment(CoverageState.CONFIRMED_EMPTY, incomplete_witness)

    zero_rows = replace(record, coverage=CoverageAssessment(CoverageState.UNKNOWN))
    assert zero_rows.coverage.state is CoverageState.UNKNOWN
    unknown_with_partial_evidence = CoverageAssessment(CoverageState.UNKNOWN, witness)
    assert unknown_with_partial_evidence.state is CoverageState.UNKNOWN

    changed_attempt_snapshot = replace(
        witness.attempts[0],
        retrieved_at_utc="2026-09-16T12:00:01.000000+00:00",
    )
    with pytest.raises(ValueError, match="identical snapshots"):
        replace(
            record,
            coverage=CoverageAssessment(CoverageState.COMPLETE, witness),
            provenance=(changed_attempt_snapshot,),
        )


def test_coverage_basis_and_empty_evidence_are_internally_consistent() -> None:
    record = f01_provider_health_record()
    reference = exact_coverage_reference(record)
    with pytest.raises(ValueError, match="kind and ID"):
        replace(reference, coverage_basis_kind=None)
    with pytest.raises(ValueError, match="requires a version"):
        replace(reference, coverage_basis_version=None)
    with pytest.raises(ValueError, match="version requires its kind and ID"):
        replace(
            reference,
            coverage_basis_kind=None,
            coverage_basis_id=None,
            coverage_basis_version="orphan-version",
        )
    with pytest.raises(ValueError, match="partition ID"):
        replace(reference, required_partition_ids=(" ",), accounted_partition_ids=())

    with pytest.raises(ValueError, match="non-empty extents"):
        CapabilityCoverageEvidenceReference(
            evidence_id="empty-with-extent",
            evidence_kind="coverage",
            version="1",
            provider_id=record.provider.provider_id,
            capability_id=record.capability.capability_id,
            scope_id=record.requested_scope.scope_id,
            digest="sha256:empty-with-extent",
            scope_complete=True,
            enumeration_complete=True,
            covered_extent_ids=("nonempty-result-set",),
            affirmatively_empty=True,
        )


def test_coverage_evidence_matches_known_competition_season_and_time_facets() -> None:
    scoped_record = f01_provider_health_record()
    coverage_ref = exact_coverage_reference(scoped_record)
    witness = exact_coverage_witness(scoped_record, coverage_ref)
    scoped_record = reachable_for_witness(scoped_record, witness)
    accepted = replace(
        scoped_record,
        coverage=CoverageAssessment(CoverageState.COMPLETE, witness),
    )
    assert accepted.coverage.state is CoverageState.COMPLETE

    for mismatched_reference in (
        replace(coverage_ref, provider_competition_key="esp.1"),
        replace(coverage_ref, provider_season="2025-26"),
        replace(
            coverage_ref,
            bounds_start_utc="2026-09-19T00:00:00.000000+00:00",
        ),
    ):
        mismatched_witness = exact_coverage_witness(scoped_record, mismatched_reference)
        with pytest.raises(ValueError, match=r"requested|COMPLETE evidence"):
            replace(
                scoped_record,
                coverage=CoverageAssessment(CoverageState.COMPLETE, mismatched_witness),
            )


def test_f01_partial_time_bounds_are_contained_and_do_not_claim_complete_scope() -> None:
    scoped_record = f01_provider_health_record()
    partial_ref = replace(
        exact_coverage_reference(scoped_record),
        bounds_start_utc="2026-09-19T00:00:00.000000+00:00",
        bounds_end_utc="2026-09-20T00:00:00.000000+00:00",
    )
    partial_witness = exact_coverage_witness(scoped_record, partial_ref)
    scoped_record = reachable_for_witness(scoped_record, partial_witness)
    partial = replace(
        scoped_record,
        coverage=CoverageAssessment(
            CoverageState.PARTIAL,
            partial_witness,
        ),
    )
    assert partial.coverage.state is CoverageState.PARTIAL
    with pytest.raises(ValueError, match="COMPLETE evidence"):
        replace(
            scoped_record,
            coverage=CoverageAssessment(
                CoverageState.COMPLETE,
                exact_coverage_witness(scoped_record, partial_ref),
            ),
        )

    outside_ref = replace(
        partial_ref,
        bounds_start_utc="2026-09-10T00:00:00.000000+00:00",
        bounds_end_utc="2026-09-11T00:00:00.000000+00:00",
    )
    with pytest.raises(ValueError, match="requested time scope"):
        replace(
            scoped_record,
            coverage=CoverageAssessment(
                CoverageState.PARTIAL,
                exact_coverage_witness(scoped_record, outside_ref),
            ),
        )


def test_contextual_capability_coverage_is_typed_and_not_fixture_only() -> None:
    record = unknown_provider_health_record()
    scope = RequestedScope(
        scope_kind="person-metrics-query",
        competition=ScopeFacet.not_applicable(),
        season=ScopeFacet.not_applicable(),
        time=ScopeFacet.known(
            UtcInterval("2026-09-18T00:00:00.000000+00:00", "2026-09-22T00:00:00.000000+00:00")
        ),
        subjects=ScopeFacet.known((SubjectIdentifier(SubjectKind.PERSON, "person-17"),)),
        selectors=(NamedSelectorFacet("metric", ScopeFacet.known(("minutes", "xg"))),),
    )
    capability = CapabilityIdentity(
        "person-metrics",
        ScopeContract(
            competition=FacetApplicability.NOT_APPLICABLE,
            season=FacetApplicability.NOT_APPLICABLE,
            time=FacetApplicability.APPLICABLE,
            subjects=FacetApplicability.APPLICABLE,
            selector_keys=("metric",),
            coverage=CoverageApplicability.APPLICABLE,
        ),
    )
    contextual = replace(
        record,
        provider=ProviderIdentity("context-api", "context-data-lineage"),
        capability=capability,
        requested_scope=scope,
    )
    complete_reference = contextual_coverage_reference(contextual)
    complete_witness = CoverageWitness(
        contextual.provider.provider_id,
        contextual.capability.capability_id,
        contextual.requested_scope.scope_id,
        (complete_reference,),
    )
    complete = replace(
        contextual,
        coverage=CoverageAssessment(CoverageState.COMPLETE, complete_witness),
    )
    assert complete.coverage.state is CoverageState.COMPLETE
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(complete)
        )
        == complete
    )

    empty_reference = contextual_coverage_reference(
        contextual, evidence_id="person-empty", affirmatively_empty=True
    )
    empty = replace(
        contextual,
        coverage=CoverageAssessment(
            CoverageState.CONFIRMED_EMPTY,
            CoverageWitness(
                contextual.provider.provider_id,
                contextual.capability.capability_id,
                contextual.requested_scope.scope_id,
                (empty_reference,),
            ),
        ),
    )
    assert empty.coverage.state is CoverageState.CONFIRMED_EMPTY

    contradictory_extent = replace(
        generic_coverage_reference(record, evidence_id="person-nonempty"),
        covered_extent_ids=("person-17:minutes",),
    )
    generic_empty = generic_coverage_reference(
        record, evidence_id="generic-empty", affirmatively_empty=True
    )
    with pytest.raises(ValueError, match="cannot combine affirmative empty"):
        CoverageWitness(
            record.provider.provider_id,
            record.capability.capability_id,
            record.requested_scope.scope_id,
            (generic_empty, contradictory_extent),
        )

    partial_reference = contextual_coverage_reference(
        contextual,
        evidence_id="person-partial",
        scope_complete=False,
        covered_extent_ids=("person-17:minutes",),
        known_gap_ids=("person-17:xg",),
    )
    partial = replace(
        contextual,
        coverage=CoverageAssessment(
            CoverageState.PARTIAL,
            CoverageWitness(
                contextual.provider.provider_id,
                contextual.capability.capability_id,
                contextual.requested_scope.scope_id,
                (partial_reference,),
            ),
        ),
    )
    assert partial.coverage.state is CoverageState.PARTIAL

    unlinked_capture = SourceCaptureReference.from_fields(
        capture_id="person-capture",
        source_key="context-api",
        source_id="context-source",
        source_lineage_id=contextual.provider.source_lineage_id,
        capture_digest="sha256:other-content",
    )
    linked_reference = contextual_coverage_reference(
        contextual,
        evidence_id="person-captured",
        capture_id="person-capture",
        capture_digest="sha256:person-capture",
    )
    with pytest.raises(ValueError, match="Source Capture ID and digest"):
        replace(
            contextual,
            coverage=CoverageAssessment(
                CoverageState.COMPLETE,
                CoverageWitness(
                    contextual.provider.provider_id,
                    contextual.capability.capability_id,
                    contextual.requested_scope.scope_id,
                    (linked_reference,),
                ),
            ),
            provenance=(unlinked_capture,),
        )


def test_failure_requires_stable_reason_and_explicit_unknown_reason_code() -> None:
    record = f01_provider_health_record()
    basis = exact_evidence_basis(record, evidence_id="failure-diagnostic")

    with pytest.raises(ValueError, match="reason code"):
        FailureAssessment(FailureState.FAILED, evidence=basis)
    with pytest.raises(ValueError, match="FAILED"):
        replace(record, failure=FailureAssessment(FailureState.FAILED))
    with pytest.raises(ValueError, match="uppercase"):
        FailureReasonCode("timeout")
    failure = FailureAssessment(
        FailureState.FAILED,
        reason_codes=(FailureReasonCode.unknown_reason(),),
        evidence=basis,
    )
    assert failure.reason_codes[0].value == "UNKNOWN_REASON"
    assert FailureAssessment(FailureState.UNKNOWN).state is FailureState.UNKNOWN
    assert FailureAssessment(FailureState.UNKNOWN, evidence=basis).state is FailureState.UNKNOWN
    malformed_attempt = replace(
        f01_attempt(scope_id=record.requested_scope.evidence_scope_id),
        state=F01ProviderAttemptState.MALFORMED,
    )
    malformed_reference = ProviderAttemptReference.from_f01(malformed_attempt)
    malformed_basis = EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        references=(malformed_reference,),
    )
    with pytest.raises(ValueError, match="cannot support NO_FAILURE_OBSERVED"):
        replace(
            record,
            reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, malformed_basis),
            failure=FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=malformed_basis),
        )
    error_attempt = ProviderAttemptReference.from_f01(
        f01_attempt(scope_id=record.requested_scope.evidence_scope_id)
    )
    error_basis = EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=record.requested_scope.evidence_scope_id,
        references=(error_attempt,),
    )
    with pytest.raises(ValueError, match="cannot support NO_FAILURE_OBSERVED"):
        replace(
            record,
            reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, error_basis),
            failure=FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=error_basis),
        )


def test_f01_capture_is_provenance_and_http_response_does_not_fill_other_dimensions() -> None:
    record = f01_provider_health_record()
    fixture_scope = record.requested_scope.fixture_scope
    assert fixture_scope is not None
    fixture_scope_id = fixture_scope.scope_id
    attempt = f01_attempt(scope_id=fixture_scope_id)
    attempt_reference = ProviderAttemptReference.from_f01(attempt)
    assert attempt_reference.state is HealthF01ProviderAttemptState.CAPTURED
    basis = EvidenceBasis(
        provider_id=record.provider.provider_id,
        capability_id=record.capability.capability_id,
        scope_id=fixture_scope_id,
        references=(attempt_reference,),
    )
    with pytest.raises(ValueError, match="establishes reachability"):
        replace(record, provenance=(attempt_reference,))
    with pytest.raises(ValueError, match="establishes reachability"):
        replace(
            record,
            capability_availability=CapabilityAvailabilityAssessment(
                CapabilityAvailabilityState.UNKNOWN, basis
            ),
        )

    observed = replace(
        record,
        reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, basis),
        provenance=(attempt_reference,),
    )

    assert attempt_reference.http_status == 503
    assert observed.reachability.state is ReachabilityState.REACHABLE
    assert observed.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
    assert observed.structural_validity.state is StructuralValidityState.UNKNOWN
    assert observed.freshness.state is FreshnessState.UNKNOWN
    assert observed.coverage.state is CoverageState.UNKNOWN
    assert observed.use_permission.state is UsePermissionState.UNKNOWN
    assert observed.failure.state is FailureState.UNKNOWN
    with pytest.raises(ValueError, match="establishes reachability"):
        replace(
            observed,
            reachability=ReachabilityAssessment(ReachabilityState.UNREACHABLE, basis),
        )
    with pytest.raises(ValueError, match="establishes reachability"):
        replace(observed, reachability=ReachabilityAssessment(ReachabilityState.UNKNOWN, basis))


def test_f01_references_validate_attempt_evidence_capture_digest_and_assessment_scope() -> None:
    base = f01_provider_health_record()
    fixture_scope = base.requested_scope.fixture_scope
    assert fixture_scope is not None
    fixture_scope_id = fixture_scope.scope_id
    attempt = f01_attempt(scope_id=fixture_scope_id)
    attempt_reference = ProviderAttemptReference.from_f01(attempt)
    coverage = f01_coverage(attempt)
    coverage_reference = ProviderCoverageEvidenceReference.from_f01(coverage, attempt_reference)
    capture = SourceCaptureReference.from_f01(
        SimpleNamespace(
            capture_id=attempt.capture_id,
            source_key="openfootball-json",
            source_id="openfootball-source",
            content_sha256=attempt.capture_digest,
            artifact_digest=attempt.capture_digest,
        ),
        source_lineage_id=base.provider.source_lineage_id,
        capture_digest=attempt.capture_digest or "",
    )
    assertion = SourceAssertionReference.from_f01(
        SimpleNamespace(assertion_id="assertion-1", capture_id=capture.capture_id)
    )
    f01_coverage_assessment = f01_assessment(
        FixtureScope(
            fixture_scope.league_key,
            fixture_scope.season,
            fixture_scope.matchweek_friday,
        ),
        attempt,
        coverage,
    )
    with pytest.raises(ValueError, match="typed F01 FixtureCoverageAssessment"):
        FixtureCoverageAssessmentReference.from_f01(
            SimpleNamespace(
                digest="sha256:unchecked",
                contract_version="fixture-coverage-v2-v2",
                schema_version=2,
                scope_assessments=(),
            ),
            fixture_scope,
        )
    with pytest.raises(ValueError, match="digest does not match"):
        replace(f01_coverage_assessment, digest="sha256:tampered")
    assessment = FixtureCoverageAssessmentReference.from_f01(
        f01_coverage_assessment,
        fixture_scope,
    )
    metadata = ProviderMetadataReference(
        "fixture-contract", "v1", base.provider.provider_id, base.capability.capability_id
    )
    provenance = (
        attempt_reference,
        coverage_reference,
        assessment,
        capture,
        assertion,
        metadata,
    )
    attempt_basis = EvidenceBasis(
        provider_id=base.provider.provider_id,
        capability_id=base.capability.capability_id,
        scope_id=fixture_scope_id,
        references=(attempt_reference,),
    )
    observed = replace(
        base,
        reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, attempt_basis),
        provenance=provenance,
    )
    assert {value.reference_kind for value in observed.provenance} == set(EvidenceReferenceKind) - {
        EvidenceReferenceKind.OTHER_VERSIONED_EVIDENCE,
        EvidenceReferenceKind.CAPABILITY_COVERAGE_EVIDENCE,
        EvidenceReferenceKind.FRESHNESS_EVIDENCE,
    }
    assert assessment.scope_state == "COMPLETE"
    assert coverage_reference.permitted_for_use is True
    assert coverage_reference.provider_use_policy_id == "provider-use-v1"
    assert observed.use_permission.state is UsePermissionState.UNKNOWN
    assert (
        provider_health_record_from_canonical_json(
            provider_health_record_to_canonical_json(observed)
        )
        == observed
    )
    assert (
        replace(
            base,
            provenance=tuple(reversed(provenance)),
            reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, attempt_basis),
        ).digest
        == observed.digest
    )

    witness = CoverageWitness(
        base.provider.provider_id,
        base.capability.capability_id,
        fixture_scope_id,
        (coverage_reference,),
        (attempt_reference,),
    )
    assessment_only_basis = EvidenceBasis(
        provider_id=base.provider.provider_id,
        capability_id=base.capability.capability_id,
        scope_id=fixture_scope_id,
        references=(assessment,),
    )
    split_membership_record = replace(
        base,
        reachability=ReachabilityAssessment(ReachabilityState.REACHABLE, assessment_only_basis),
        coverage=CoverageAssessment(CoverageState.UNKNOWN, witness),
    )
    assert split_membership_record.coverage.state is CoverageState.UNKNOWN
    for incomplete_assessment in (
        replace(assessment, provider_attempt_ids=()),
        replace(assessment, coverage_evidence_ids=()),
    ):
        with pytest.raises(ValueError, match="retain referenced"):
            replace(
                base,
                reachability=ReachabilityAssessment(
                    ReachabilityState.REACHABLE,
                    replace(
                        assessment_only_basis,
                        references=(incomplete_assessment,),
                    ),
                ),
                coverage=CoverageAssessment(CoverageState.UNKNOWN, witness),
            )

    for malformed_attempt in (
        replace(attempt, provider_id="different-provider"),
        replace(attempt, capability_id="different-capability"),
        replace(attempt, scope_id="different-scope"),
    ):
        malformed_reference = ProviderAttemptReference.from_f01(malformed_attempt)
        with pytest.raises(ValueError, match="Provider Attempt reference"):
            replace(base, provenance=(malformed_reference,))
    with pytest.raises(ValueError, match="capture references"):
        ProviderCoverageEvidenceReference.from_f01(
            replace(coverage, capture_digest="sha256:different"), attempt_reference
        )
    for mismatch in (
        replace(coverage, attempt_id="different-attempt"),
        replace(coverage, scope_id="different-scope"),
        replace(coverage, capture_id="different-capture"),
        replace(coverage, capture_digest="sha256:different-capture"),
    ):
        with pytest.raises(ValueError):
            ProviderCoverageEvidenceReference.from_f01(mismatch, attempt_reference)
    with pytest.raises(ValueError, match="exactly one matching scope"):
        FixtureCoverageAssessmentReference.from_f01(
            f01_assessment(
                FixtureScope(
                    fixture_scope.league_key,
                    fixture_scope.season,
                    fixture_scope.matchweek_friday,
                ),
                attempt,
                coverage,
                include_scope=False,
            ),
            fixture_scope,
        )
    with pytest.raises(ValueError, match="content digest must match"):
        replace(
            base,
            provenance=(attempt_reference, replace(capture, capture_digest="sha256:other")),
        )
    with pytest.raises(ValueError, match="requested Fixture Scope"):
        replace(
            base,
            provenance=(
                attempt_reference,
                coverage_reference,
                replace(assessment, fixture_scope_id="la_liga:2026-27:2026-09-18"),
                capture,
                assertion,
                metadata,
            ),
        )


def test_canonical_serialization_round_trip_digest_tampering_and_strict_versions() -> None:
    record = unknown_provider_health_record()
    canonical = provider_health_record_to_canonical_json(record)
    restored = provider_health_record_from_canonical_json(canonical)
    assert restored == record
    assert restored.digest == provider_health_record_from_canonical_json(canonical).digest

    with pytest.raises(ValueError, match="digest"):
        provider_health_record_from_canonical_json(
            canonical.replace(record.digest, "sha256:" + "0" * 64)
        )
    unsupported = canonical.replace('"schema_version":1', '"schema_version":99')
    with pytest.raises(ValueError, match="schema version"):
        provider_health_record_from_canonical_json(unsupported)
    unsupported_contract = canonical.replace(
        '"contract_version":"provider-health-v1"',
        '"contract_version":"provider-health-v9"',
    )
    with pytest.raises(ValueError, match="contract version"):
        provider_health_record_from_canonical_json(unsupported_contract)
    with pytest.raises(ValueError, match="canonical"):
        provider_health_record_from_canonical_json(canonical + " ")

    f01_record = f01_provider_health_record()
    f01_canonical = provider_health_record_to_canonical_json(f01_record)
    with pytest.raises(ValueError, match="FixtureScope"):
        provider_health_record_from_canonical_json(
            f01_canonical.replace(
                '"window_start_utc":"2026-09-17T23:00:00.000000+00:00"',
                '"window_start_utc":"2026-09-18T00:00:00.000000+00:00"',
            )
        )
    invalid = canonical.replace('"scope_kind":"fixture-query"', '"scope_kind":" "')
    with pytest.raises(ValueError):
        provider_health_record_from_canonical_json(invalid)
    duplicate_key = canonical.replace("{", '{"contract_version":"provider-health-v1",', 1)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        provider_health_record_from_canonical_json(duplicate_key)
    reordered_payload = json.loads(canonical)
    reordered_payload["requested_scope"]["selectors"].reverse()
    reordered_json = json.dumps(
        reordered_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    with pytest.raises(ValueError, match="normalized form"):
        provider_health_record_from_canonical_json(reordered_json)


def test_normalized_observations_and_set_like_values_have_deterministic_digests() -> None:
    record = unknown_provider_health_record()
    first = replace(
        record.requested_scope,
        selectors=(
            NamedSelectorFacet("venue", ScopeFacet.known(("emirates", "national-stadium"))),
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-5",))),
        ),
    )
    second = replace(
        record.requested_scope,
        selectors=(
            NamedSelectorFacet("matchweek", ScopeFacet.known(("week-5",))),
            NamedSelectorFacet("venue", ScopeFacet.known(("national-stadium", "emirates"))),
        ),
    )
    first_record = replace(record, requested_scope=first)
    second_record = replace(record, requested_scope=second)

    assert first_record.digest == second_record.digest
    assert provider_health_record_to_canonical_json(
        first_record
    ) == provider_health_record_to_canonical_json(second_record)
    changed_provenance = replace(
        first_record,
        provenance=(
            OtherVersionedEvidenceReference(
                evidence_id="new-source-record",
                evidence_kind="provider-observation",
                version="1",
                provider_id=record.provider.provider_id,
                capability_id=record.capability.capability_id,
                scope_id=first_record.requested_scope.evidence_scope_id,
                digest="sha256:new-source-record",
            ),
        ),
    )
    assert changed_provenance.digest != first_record.digest
    changed_check = replace(record, checked_at_utc="2026-09-16T12:00:01.000000+00:00")
    assert changed_check.digest != record.digest

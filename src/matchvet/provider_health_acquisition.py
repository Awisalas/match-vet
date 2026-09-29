"""Build F04 health observations from the exact F01 scheduled-fixture assessment."""

from __future__ import annotations

from collections.abc import Mapping

from matchvet.fixture_coverage import (
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    SupportedFixtureCoverageAssessment,
)
from matchvet.fixture_coverage_codec import is_supported_f01_assessment
from matchvet.provider_health import (
    CapabilityAvailabilityAssessment,
    CapabilityAvailabilityState,
    CapabilityIdentity,
    CompetitionScope,
    CoverageApplicability,
    CoverageAssessment,
    CoverageState,
    CoverageWitness,
    EvidenceBasis,
    EvidenceReference,
    F01FixtureScopeReference,
    FacetApplicability,
    FailureAssessment,
    FailureReasonCode,
    FailureState,
    FixtureCoverageAssessmentReference,
    FreshnessAssessment,
    FreshnessState,
    PermissionPolicyReference,
    ProviderAttemptReference,
    ProviderCoverageEvidenceReference,
    ProviderHealthRecord,
    ProviderIdentity,
    ReachabilityAssessment,
    ReachabilityState,
    RequestedScope,
    ScopeContract,
    ScopeFacet,
    SeasonScope,
    StructuralValidityAssessment,
    StructuralValidityState,
    UsePermissionAssessment,
    UsePermissionState,
    UtcInterval,
)

INTENDED_USE_ID = "matchvet:research-only:upcoming-fixture-acquisition"
PERMISSION_POLICY_ID = "t06-source-policy"
PERMISSION_POLICY_VERSION = "v1"
SCHEDULED_FIXTURE_CAPABILITY_ID = "scheduled-fixtures"
OPENFOOTBALL_LINEAGE_ID = "openfootball-schedule-lineage"

_OPENFOOTBALL_SOURCE_KINDS = {
    "openfootball-json": "OPENFOOTBALL",
    "openfootball-footballtxt": "OPENFOOTBALL_TEXT",
}


def build_provider_health_records(
    assessment: SupportedFixtureCoverageAssessment,
    *,
    attempt_diagnostics: Mapping[str, str] | None = None,
) -> tuple[ProviderHealthRecord, ...]:
    """Create exactly one F04 observation for every attempt in the F01 assessment."""
    if not is_supported_f01_assessment(assessment):
        raise TypeError("F05 requires a supported typed F01 assessment.")
    diagnostics = dict(attempt_diagnostics or {})
    attempts_by_id = {attempt.attempt_id: attempt for attempt in assessment.provider_attempts}
    if not set(diagnostics).issubset(attempts_by_id):
        raise ValueError("F05 diagnostics must identify attempts in the F01 assessment.")

    records = tuple(
        _record_for_attempt(assessment, attempt, diagnostics.get(attempt.attempt_id))
        for attempt in assessment.provider_attempts
    )
    return tuple(sorted(records, key=lambda record: record.digest))


def _record_for_attempt(
    assessment: SupportedFixtureCoverageAssessment,
    attempt: ProviderAttempt,
    diagnostic: str | None,
) -> ProviderHealthRecord:
    matching_scopes = tuple(
        item.scope
        for item in assessment.scope_assessments
        if item.scope.scope_id == attempt.scope_id
    )
    if len(matching_scopes) != 1:
        raise ValueError("F05 requires one matching Fixture Scope in the F01 assessment.")
    fixture_scope = F01FixtureScopeReference.from_f01(matching_scopes[0])
    attempt_reference = ProviderAttemptReference.from_f01(attempt)
    assessment_reference = FixtureCoverageAssessmentReference.from_f01(assessment, fixture_scope)
    coverage_evidence = _matching_coverage_evidence(assessment, attempt, fixture_scope)
    coverage_references = tuple(
        ProviderCoverageEvidenceReference.from_f01(evidence, attempt_reference)
        for evidence in coverage_evidence
    )
    provenance: tuple[EvidenceReference, ...] = (
        attempt_reference,
        assessment_reference,
        *coverage_references,
    )
    evidence = EvidenceBasis(
        provider_id=attempt.provider_id,
        capability_id=attempt.capability_id,
        scope_id=attempt.scope_id,
        references=provenance,
    )

    if attempt.state is ProviderAttemptState.CAPTURED:
        reachability = ReachabilityAssessment(ReachabilityState.REACHABLE, evidence)
        capability = CapabilityAvailabilityAssessment(
            CapabilityAvailabilityState.AVAILABLE, evidence
        )
        structural = StructuralValidityAssessment(StructuralValidityState.VALID, evidence)
        failure = (
            FailureAssessment(FailureState.NO_FAILURE_OBSERVED, evidence=evidence)
            if diagnostic is None
            else FailureAssessment(
                FailureState.FAILED,
                reason_codes=(FailureReasonCode("ACQUISITION_DIAGNOSTIC"),),
                evidence=evidence,
            )
        )
    elif attempt.state is ProviderAttemptState.MALFORMED:
        reachability = (
            ReachabilityAssessment(ReachabilityState.REACHABLE, evidence)
            if attempt.http_status is not None or attempt.capture_id is not None
            else ReachabilityAssessment(ReachabilityState.UNKNOWN)
        )
        capability = CapabilityAvailabilityAssessment(CapabilityAvailabilityState.UNKNOWN)
        structural = StructuralValidityAssessment(StructuralValidityState.INVALID, evidence)
        failure = FailureAssessment(
            FailureState.FAILED,
            reason_codes=(FailureReasonCode("MALFORMED_RESPONSE"),),
            evidence=evidence,
        )
    elif attempt.state is ProviderAttemptState.UNAVAILABLE:
        reachability = (
            ReachabilityAssessment(ReachabilityState.REACHABLE, evidence)
            if attempt.http_status is not None
            else ReachabilityAssessment(ReachabilityState.UNKNOWN)
        )
        capability = (
            CapabilityAvailabilityAssessment(CapabilityAvailabilityState.UNAVAILABLE, evidence)
            if attempt.http_status is not None and attempt.http_status >= 400
            else CapabilityAvailabilityAssessment(CapabilityAvailabilityState.UNKNOWN)
        )
        structural = StructuralValidityAssessment(StructuralValidityState.UNKNOWN)
        failure = FailureAssessment(
            FailureState.FAILED,
            reason_codes=(FailureReasonCode("ATTEMPT_UNAVAILABLE"),),
            evidence=evidence,
        )
    else:
        raise ValueError("F05 cannot map an unsupported F01 Provider Attempt state.")

    record = ProviderHealthRecord(
        provider=ProviderIdentity(
            provider_id=attempt.provider_id,
            source_lineage_id=_source_lineage_id(attempt.provider_id),
        ),
        capability=CapabilityIdentity(
            capability_id=attempt.capability_id,
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
            scope_kind="fixture-scope",
            competition=ScopeFacet.known(
                CompetitionScope(fixture_scope.league_key, fixture_scope.league_key)
            ),
            season=ScopeFacet.known(SeasonScope(fixture_scope.season, fixture_scope.season)),
            time=ScopeFacet.known(
                UtcInterval(fixture_scope.window_start_utc, fixture_scope.window_end_utc)
            ),
            subjects=ScopeFacet.not_applicable(),
            selectors=(),
            fixture_scope=fixture_scope,
        ),
        intended_use_id=INTENDED_USE_ID,
        checked_at_utc=attempt.retrieved_at_utc,
        use_permission=_permission(attempt.provider_id),
        reachability=reachability,
        capability_availability=capability,
        structural_validity=structural,
        freshness=FreshnessAssessment(FreshnessState.UNKNOWN),
        coverage=_coverage_assessment(
            attempt, fixture_scope, attempt_reference, coverage_references
        ),
        failure=failure,
        provenance=provenance,
    )
    return record


def _matching_coverage_evidence(
    assessment: SupportedFixtureCoverageAssessment,
    attempt: ProviderAttempt,
    scope: F01FixtureScopeReference,
) -> tuple[ProviderCoverageEvidence, ...]:
    return tuple(
        evidence
        for evidence in assessment.coverage_evidence
        if (
            evidence.attempt_id == attempt.attempt_id
            and evidence.scope_id == attempt.scope_id
            and evidence.provider_competition_key == scope.league_key
            and evidence.provider_season == scope.season
            and (evidence.capture_id, evidence.capture_digest)
            == (attempt.capture_id, attempt.capture_digest)
        )
    )


def _coverage_assessment(
    attempt: ProviderAttempt,
    fixture_scope: F01FixtureScopeReference,
    attempt_reference: ProviderAttemptReference,
    evidence_references: tuple[ProviderCoverageEvidenceReference, ...],
) -> CoverageAssessment:
    if not evidence_references:
        return CoverageAssessment(CoverageState.UNKNOWN)
    if any(reference.coverage_basis_id is None for reference in evidence_references):
        return CoverageAssessment(CoverageState.UNKNOWN)
    witness = CoverageWitness(
        provider_id=attempt.provider_id,
        capability_id=attempt.capability_id,
        scope_id=attempt.scope_id,
        evidence=evidence_references,
        attempts=(attempt_reference,),
    )
    candidates = (
        (CoverageState.CONFIRMED_EMPTY, witness.has_affirmative_empty_scope_evidence),
        (CoverageState.COMPLETE, witness.has_complete_scope_evidence),
        (CoverageState.PARTIAL, witness.has_partial_extent_or_gap_evidence),
    )
    for state, supported in candidates:
        if not supported:
            continue
        try:
            return CoverageAssessment(state, witness)
        except ValueError:
            continue
    return CoverageAssessment(CoverageState.UNKNOWN)


def _source_lineage_id(provider_id: str) -> str:
    if provider_id in _OPENFOOTBALL_SOURCE_KINDS:
        return OPENFOOTBALL_LINEAGE_ID
    return provider_id


def _permission(provider_id: str) -> UsePermissionAssessment:
    from matchvet.ingestion import _SOURCE_RIGHTS, SourceKind

    source_kind_value = _OPENFOOTBALL_SOURCE_KINDS.get(provider_id)
    rights = (
        None if source_kind_value is None else _SOURCE_RIGHTS.get(SourceKind(source_kind_value))
    )
    policy = PermissionPolicyReference(
        policy_id=PERMISSION_POLICY_ID,
        version=PERMISSION_POLICY_VERSION,
        intended_use_id=INTENDED_USE_ID,
    )
    if rights is None:
        state = UsePermissionState.UNKNOWN
    elif rights.allowed_use in {"CC0", "RESTRICTED_PRIVATE"}:
        state = UsePermissionState.PERMITTED
    else:
        state = UsePermissionState.NOT_PERMITTED
    return UsePermissionAssessment(state, policy)

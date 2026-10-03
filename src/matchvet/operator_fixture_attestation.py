"""Pure, versioned LF02 attestation and F01 v3 derivation contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TypedDict, cast
from urllib.parse import unquote, urlsplit

from matchvet.fixture_coverage import (
    CoverageBounds,
    CoverageFreshnessResult,
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    FixtureScope,
    FixtureScopeAssessment,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderCoverageEvidence,
    ScopeCoverageState,
    _coverage_evidence_from_json,
    _freshness_result_from_json,
    _identity_resolution_from_json,
    _payload_bool,
    _payload_int,
    _payload_list,
    _payload_object,
    _payload_optional_string,
    _payload_string,
    _provider_attempt_from_json,
    _revision_reference_from_json,
    _scope_assessment_from_json,
    fixture_scopes_for_matchweek,
)
from matchvet.ingestion import (
    _parse_date,
    _source_timezone,
    deterministic_identifier,
    league_by_key,
)

OPERATOR_ATTESTATION_CONTRACT_VERSION = "operator-fixture-attestation-v1"
OPERATOR_ATTESTATION_SCHEMA_VERSION = 1
OPERATOR_ATTESTATION_POLICY_ID = "matchvet:operator-fixture-attestation"
OPERATOR_ATTESTATION_POLICY_VERSION = "1"
OPERATOR_ATTESTATION_POLICY_V2_VERSION = "2"
OPERATOR_ATTESTATION_MEDIA_TYPE = "application/vnd.matchvet.operator-fixture-attestation-v1+json"
OPERATOR_ATTESTATION_V2_CONTRACT_VERSION = "operator-fixture-attestation-v2"
OPERATOR_ATTESTATION_V2_SCHEMA_VERSION = 2
OPERATOR_ATTESTATION_V2_MEDIA_TYPE = "application/vnd.matchvet.operator-fixture-attestation-v2+json"
OPERATOR_CANDIDATE_MANIFEST_CONTRACT_VERSION = "operator-fixture-candidate-manifest-v1"
OPERATOR_CANDIDATE_MANIFEST_SCHEMA_VERSION = 1
OPERATOR_CANDIDATE_MANIFEST_V2_CONTRACT_VERSION = "operator-fixture-candidate-manifest-v2"
OPERATOR_CANDIDATE_MANIFEST_V2_SCHEMA_VERSION = 2
OPERATOR_FRESHNESS_CONTRACT_VERSION = "operator-fixture-attestation-freshness-v1"
OPERATOR_FRESHNESS_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCHEDULE_MARKER_RE = re.compile(r"\b(?:TBC|TBA|TBD|PROVISIONAL)\b", re.IGNORECASE)
_MAX_OPERATOR_ID_LENGTH = 100
_MAX_CITATION_VALUE_LENGTH = 512
_MAX_PAGE_SIZE = 20


class OperatorAttestationOutcome(StrEnum):
    CERTIFIED = "CERTIFIED"
    REFUSED = "REFUSED"
    UNCERTAIN = "UNCERTAIN"


class ScheduleRelation(StrEnum):
    EXACT = "EXACT"
    LESS_PRECISE_BUT_COMPATIBLE = "LESS_PRECISE_BUT_COMPATIBLE"
    PROVISIONAL = "PROVISIONAL"
    CONFLICTING = "CONFLICTING"


@dataclass(frozen=True)
class CandidateAssertionFact:
    """One immutable provider assertion referenced by the exact F01 base."""

    assertion_id: str
    capture_id: str
    capture_digest: str
    origin_id: str | None
    source_row_key: str
    subject_kind: str
    subject_key: str
    evidence_type: str
    predicate: str
    raw_field_name: str
    evidence_state: str
    raw_value_json: str | None
    normalized_value_json: str | None
    unknown_reason: str | None
    event_time_utc: str | None
    effective_time_utc: str | None
    created_at_utc: str
    digest: str = ""

    def __post_init__(self) -> None:
        for name in (
            "assertion_id",
            "capture_id",
            "capture_digest",
            "source_row_key",
            "subject_kind",
            "subject_key",
            "evidence_type",
            "predicate",
            "raw_field_name",
            "evidence_state",
        ):
            _non_empty(getattr(self, name), f"Candidate Assertion Fact {name}")
        if _SHA256_RE.fullmatch(self.capture_digest) is None:
            raise ValueError("Candidate Assertion Fact capture digest must be SHA-256.")
        _source_utc(self.created_at_utc)
        for timestamp in (self.event_time_utc, self.effective_time_utc):
            if timestamp is not None:
                _source_utc(timestamp)
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Candidate Assertion Fact digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class CandidateRevisionFact:
    """Exact immutable T04 revision facts; never a projection of the latest fixture."""

    reference: FixtureRevisionReference
    home_team_id: str
    away_team_id: str
    kickoff_state: str
    kickoff_utc: str | None
    kickoff_local_text: str | None
    kickoff_precision: str
    fixture_status: str
    source_round: str | None
    observed_at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, FixtureRevisionReference):
            raise ValueError("Candidate Revision Fact requires its exact F01 revision reference.")
        for name in (
            "home_team_id",
            "away_team_id",
            "kickoff_state",
            "kickoff_precision",
            "fixture_status",
            "observed_at_utc",
        ):
            _non_empty(getattr(self, name), f"Candidate Revision Fact {name}")
        if self.home_team_id == self.away_team_id:
            raise ValueError("Candidate Revision Fact cannot have identical teams.")


@dataclass(frozen=True)
class CandidateManifestEntry:
    """One F01 source candidate, including unresolved and conflicting facts."""

    candidate_id: str
    scope_id: str
    identity_state: FixtureIdentityState
    canonical_fixture_id: str | None
    revision_facts: tuple[CandidateRevisionFact, ...]
    assertion_facts: tuple[CandidateAssertionFact, ...]
    source_capture_ids: tuple[str, ...]
    source_assertion_ids: tuple[str, ...]
    reason_code: str | None
    has_schedule_conflict: bool
    has_provisional_scheduling: bool

    def __post_init__(self) -> None:
        _non_empty(self.candidate_id, "Candidate Manifest candidate_id")
        _non_empty(self.scope_id, "Candidate Manifest scope_id")
        if not isinstance(self.identity_state, FixtureIdentityState):
            raise ValueError("Candidate Manifest identity state is unsupported.")
        if self.identity_state is FixtureIdentityState.RESOLVED:
            if self.canonical_fixture_id is None or self.reason_code is not None:
                raise ValueError("Resolved manifest candidates require only a canonical identity.")
            _non_empty(self.canonical_fixture_id, "Candidate Manifest canonical fixture ID")
        elif self.canonical_fixture_id is not None or self.reason_code is None:
            raise ValueError("Unresolved manifest candidates require a reason and no fixture ID.")
        revision_ids = tuple(item.reference.revision_id for item in self.revision_facts)
        if revision_ids != tuple(sorted(set(revision_ids))):
            raise ValueError("Candidate Revision Facts must use stable revision ordering.")
        _require_sorted_unique(self.source_capture_ids, "Candidate source capture IDs")
        _require_sorted_unique(self.source_assertion_ids, "Candidate source assertion IDs")
        assertion_ids = tuple(item.assertion_id for item in self.assertion_facts)
        if assertion_ids != tuple(sorted(set(assertion_ids))):
            raise ValueError("Candidate Assertion Facts must be sorted and unique.")


@dataclass(frozen=True)
class CandidateManifest:
    """Canonical manifest of all candidate facts in one exact v2 scope."""

    contract_version: str
    schema_version: int
    base_assessment_digest: str
    scope: FixtureScope
    bounds: CoverageBounds
    entries: tuple[CandidateManifestEntry, ...]
    candidate_count: int
    digest: str = ""

    def __post_init__(self) -> None:
        if (
            self.contract_version != OPERATOR_CANDIDATE_MANIFEST_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != OPERATOR_CANDIDATE_MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("Candidate Manifest uses unsupported contract versions.")
        if _DIGEST_RE.fullmatch(self.base_assessment_digest) is None:
            raise ValueError("Candidate Manifest requires an exact F01 assessment digest.")
        if not isinstance(self.scope, FixtureScope) or not isinstance(self.bounds, CoverageBounds):
            raise ValueError("Candidate Manifest requires a typed exact scope and bounds.")
        if self.bounds != CoverageBounds(self.scope.window_start_utc, self.scope.window_end_utc):
            raise ValueError("Candidate Manifest bounds differ from its Fixture Scope.")
        if any(type(item) is not CandidateManifestEntry for item in self.entries):
            raise ValueError("Candidate Manifest v1 requires only v1 entry values.")
        candidate_ids = tuple(item.candidate_id for item in self.entries)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("Candidate Manifest entries must be sorted and unique.")
        if any(item.scope_id != self.scope.scope_id for item in self.entries):
            raise ValueError("Candidate Manifest entries must use its exact Fixture Scope.")
        if type(self.candidate_count) is not int or self.candidate_count != _candidate_count(
            self.entries
        ):
            raise ValueError("Candidate Manifest count must be computed from its entries.")
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Candidate Manifest digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class CandidateManifestEntryV2(CandidateManifestEntry):
    """One v2 candidate with an explicit fixture-level schedule relation."""

    schedule_relation: ScheduleRelation

    def __post_init__(self) -> None:
        CandidateManifestEntry.__post_init__(self)
        if not isinstance(self.schedule_relation, ScheduleRelation):
            raise ValueError("Candidate Manifest v2 requires a typed schedule relation.")
        expected_conflict = self.schedule_relation is ScheduleRelation.CONFLICTING
        expected_provisional = self.schedule_relation is ScheduleRelation.PROVISIONAL
        if (
            self.has_schedule_conflict is not expected_conflict
            or self.has_provisional_scheduling is not expected_provisional
        ):
            raise ValueError("Candidate Manifest v2 flags must project its schedule relation.")


@dataclass(frozen=True)
class CandidateManifestV2:
    """Canonical v2 manifest of candidates in one exact F01 scope."""

    contract_version: str
    schema_version: int
    base_assessment_digest: str
    scope: FixtureScope
    bounds: CoverageBounds
    entries: tuple[CandidateManifestEntryV2, ...]
    candidate_count: int
    digest: str = ""

    def __post_init__(self) -> None:
        if (
            self.contract_version != OPERATOR_CANDIDATE_MANIFEST_V2_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != OPERATOR_CANDIDATE_MANIFEST_V2_SCHEMA_VERSION
        ):
            raise ValueError("Candidate Manifest v2 uses unsupported contract versions.")
        if _DIGEST_RE.fullmatch(self.base_assessment_digest) is None:
            raise ValueError("Candidate Manifest requires an exact F01 assessment digest.")
        if not isinstance(self.scope, FixtureScope) or not isinstance(self.bounds, CoverageBounds):
            raise ValueError("Candidate Manifest requires a typed exact scope and bounds.")
        if self.bounds != CoverageBounds(self.scope.window_start_utc, self.scope.window_end_utc):
            raise ValueError("Candidate Manifest bounds differ from its Fixture Scope.")
        if any(type(item) is not CandidateManifestEntryV2 for item in self.entries):
            raise ValueError("Candidate Manifest v2 requires only v2 entry values.")
        candidate_ids = tuple(item.candidate_id for item in self.entries)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("Candidate Manifest entries must be sorted and unique.")
        if any(item.scope_id != self.scope.scope_id for item in self.entries):
            raise ValueError("Candidate Manifest entries must use its exact Fixture Scope.")
        if type(self.candidate_count) is not int or self.candidate_count != _candidate_count(
            self.entries
        ):
            raise ValueError("Candidate Manifest count must be computed from its entries.")
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Candidate Manifest digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


CandidateManifestValue = CandidateManifest | CandidateManifestV2
CandidateManifestEntryValue = CandidateManifestEntry | CandidateManifestEntryV2


class _ManifestEntryArgs(TypedDict):
    candidate_id: str
    scope_id: str
    identity_state: FixtureIdentityState
    canonical_fixture_id: str | None
    revision_facts: tuple[CandidateRevisionFact, ...]
    assertion_facts: tuple[CandidateAssertionFact, ...]
    source_capture_ids: tuple[str, ...]
    source_assertion_ids: tuple[str, ...]
    reason_code: str | None
    has_schedule_conflict: bool
    has_provisional_scheduling: bool


class _ManifestArgs(TypedDict):
    contract_version: str
    schema_version: int
    base_assessment_digest: str
    scope: FixtureScope
    bounds: CoverageBounds
    candidate_count: int
    digest: str


@dataclass(frozen=True)
class OperatorPublicationRule:
    """One policy-approved publisher/publication identity and official URL scope."""

    publication_id: str
    league_key: str
    publisher_id: str
    publisher_name: str
    competition_id: str
    publication_type: str
    host: str
    path_prefix: str
    example_url: str
    supported_layers: tuple[str, ...]
    path_pattern: str | None = None


@dataclass(frozen=True)
class OperatorAttestationPolicySnapshot:
    policy_id: str
    policy_version: str
    publication_rules: tuple[OperatorPublicationRule, ...]
    required_layer_ids: tuple[tuple[str, tuple[str, ...]], ...]
    required_confirmations: tuple[str, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        if self.policy_id != OPERATOR_ATTESTATION_POLICY_ID:
            raise ValueError("Operator Attestation Policy ID is unsupported.")
        if self.policy_version not in {
            OPERATOR_ATTESTATION_POLICY_VERSION,
            OPERATOR_ATTESTATION_POLICY_V2_VERSION,
        }:
            raise ValueError("Operator Attestation Policy version is unsupported.")
        ids = tuple(rule.publication_id for rule in self.publication_rules)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Operator Attestation Policy publication rules must be ordered.")
        leagues = tuple(item[0] for item in self.required_layer_ids)
        if leagues != tuple(sorted(set(leagues))):
            raise ValueError("Operator Attestation Policy league rules must be ordered.")
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Operator Attestation Policy digest does not match its snapshot.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class OfficialPublicationReference:
    """Minimal human citation metadata; no official publication content is retained."""

    publication_id: str
    publisher_id: str
    competition_id: str
    official_url: str
    title_or_publication_id: str
    publication_date: str | None
    publication_type: str
    claim_scope_id: str
    covers_exact_scope: bool
    complete_for_scope: bool

    def __post_init__(self) -> None:
        for name in (
            "publication_id",
            "publisher_id",
            "competition_id",
            "official_url",
            "title_or_publication_id",
            "publication_type",
            "claim_scope_id",
        ):
            value = getattr(self, name)
            _non_empty(value, f"Official Publication Reference {name}")
            if len(value) > _MAX_CITATION_VALUE_LENGTH:
                raise ValueError(f"Official Publication Reference {name} exceeds its size limit.")
        if self.publication_date is not None:
            _non_empty(self.publication_date, "Official Publication Reference publication_date")
            if len(self.publication_date) > 40:
                raise ValueError("Official Publication Reference date exceeds its size limit.")
        if type(self.covers_exact_scope) is not bool or type(self.complete_for_scope) is not bool:
            raise ValueError("Official Publication Reference coverage confirmations are explicit.")


@dataclass(frozen=True)
class CandidateComparisonConfirmation:
    candidate_id: str
    identity_matches: bool
    date_matches: bool
    kickoff_matches: bool
    status_matches: bool

    def __post_init__(self) -> None:
        _non_empty(self.candidate_id, "Candidate Comparison candidate_id")
        for name in ("identity_matches", "date_matches", "kickoff_matches", "status_matches"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Candidate Comparison confirmations must be explicit booleans.")


@dataclass(frozen=True)
class OperatorComparisonConfirmations:
    all_official_fixtures_represented: bool
    no_extra_matchvet_fixture: bool
    complete_official_publication_covers_scope: bool
    pairing_calendar_layer_checked: bool
    exact_schedule_layer_checked: bool
    latest_applicable_update_checked: bool
    complete_publication_affirms_empty_scope: bool

    def __post_init__(self) -> None:
        if any(type(getattr(self, item.name)) is not bool for item in fields(self)):
            raise ValueError("Operator Comparison confirmations must be explicit booleans.")


@dataclass(frozen=True)
class OperatorCoverageAttestation:
    contract_version: str
    schema_version: int
    attestation_id: str
    base_assessment_digest: str
    scope: FixtureScope
    bounds: CoverageBounds
    candidate_manifest: CandidateManifestValue
    candidate_manifest_digest: str
    observed_candidate_count: int
    operator_id: str
    verified_at_utc: str
    policy_snapshot: OperatorAttestationPolicySnapshot
    policy_digest: str
    publications: tuple[OfficialPublicationReference, ...]
    expected_official_fixture_count: int | None
    candidate_confirmations: tuple[CandidateComparisonConfirmation, ...]
    confirmations: OperatorComparisonConfirmations
    outcome: OperatorAttestationOutcome
    reason: str
    digest: str = ""

    def __post_init__(self) -> None:
        attestation_version = (self.contract_version, self.schema_version)
        manifest_version = (
            self.candidate_manifest.contract_version,
            self.candidate_manifest.schema_version,
        )
        supported_versions = {
            (
                OPERATOR_ATTESTATION_CONTRACT_VERSION,
                OPERATOR_ATTESTATION_SCHEMA_VERSION,
            ): (
                OPERATOR_CANDIDATE_MANIFEST_CONTRACT_VERSION,
                OPERATOR_CANDIDATE_MANIFEST_SCHEMA_VERSION,
            ),
            (
                OPERATOR_ATTESTATION_V2_CONTRACT_VERSION,
                OPERATOR_ATTESTATION_V2_SCHEMA_VERSION,
            ): (
                OPERATOR_CANDIDATE_MANIFEST_V2_CONTRACT_VERSION,
                OPERATOR_CANDIDATE_MANIFEST_V2_SCHEMA_VERSION,
            ),
        }
        if (
            type(self.schema_version) is not int
            or attestation_version not in supported_versions
            or manifest_version != supported_versions[attestation_version]
        ):
            raise ValueError("Operator Coverage Attestation uses unsupported versions.")
        _non_empty(self.attestation_id, "Operator Coverage Attestation ID")
        if _DIGEST_RE.fullmatch(self.base_assessment_digest) is None:
            raise ValueError("Operator Coverage Attestation requires an exact F01 base digest.")
        if self.bounds != CoverageBounds(self.scope.window_start_utc, self.scope.window_end_utc):
            raise ValueError("Operator Coverage Attestation bounds differ from its exact scope.")
        if self.candidate_manifest.base_assessment_digest != self.base_assessment_digest:
            raise ValueError(
                "Operator Coverage Attestation candidate manifest has a different base."
            )
        if self.candidate_manifest.scope != self.scope:
            raise ValueError(
                "Operator Coverage Attestation candidate manifest has a different scope."
            )
        if self.candidate_manifest_digest != self.candidate_manifest.digest:
            raise ValueError(
                "Operator Coverage Attestation manifest digest does not match its value."
            )
        if (
            type(self.observed_candidate_count) is not int
            or self.observed_candidate_count != self.candidate_manifest.candidate_count
        ):
            raise ValueError("Observed candidate count must be computed by MatchVet.")
        if not self.operator_id.strip() or len(self.operator_id) > _MAX_OPERATOR_ID_LENGTH:
            raise ValueError("Operator ID must be stable, nonempty, and within its size limit.")
        _canonical_utc(self.verified_at_utc)
        if self.policy_digest != self.policy_snapshot.digest:
            raise ValueError(
                "Operator Coverage Attestation policy digest does not match its value."
            )
        publication_keys = tuple(
            (item.publication_id, item.official_url) for item in self.publications
        )
        if (
            not self.publications and self.outcome is OperatorAttestationOutcome.CERTIFIED
        ) or publication_keys != tuple(sorted(set(publication_keys))):
            raise ValueError(
                "Certified attestations require ordered official publication references."
            )
        if self.expected_official_fixture_count is not None and (
            type(self.expected_official_fixture_count) is not int
            or self.expected_official_fixture_count < 0
        ):
            raise ValueError(
                "Expected official fixture count must be a nonnegative integer or null."
            )
        candidate_ids = tuple(item.candidate_id for item in self.candidate_confirmations)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("Candidate confirmations must be sorted and unique.")
        if not isinstance(self.confirmations, OperatorComparisonConfirmations):
            raise ValueError("Operator Coverage Attestation requires typed confirmations.")
        if not isinstance(self.outcome, OperatorAttestationOutcome):
            raise ValueError("Operator Coverage Attestation outcome is unsupported.")
        if self.outcome is OperatorAttestationOutcome.CERTIFIED and self.reason:
            raise ValueError("A certified attestation cannot retain a refusal reason.")
        if self.outcome is not OperatorAttestationOutcome.CERTIFIED and not self.reason.strip():
            raise ValueError("A refused or uncertain attestation requires a reason.")
        if len(self.reason) > _MAX_CITATION_VALUE_LENGTH:
            raise ValueError("Operator Coverage Attestation reason exceeds its size limit.")
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Operator Coverage Attestation digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class AttestationArtifactReference:
    attestation: OperatorCoverageAttestation
    artifact_digest: str

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.artifact_digest) is None:
            raise ValueError("Attestation artifact reference requires a content-addressed digest.")


@dataclass(frozen=True)
class OperatorAttestationFreshnessResult:
    contract_version: str
    schema_version: int
    base_assessment_digest: str
    scope: FixtureScope
    bounds: CoverageBounds
    candidate_manifest_digest: str
    policy_digest: str
    attestation_id: str
    attestation_digest: str
    latest_base_attempt_retrieved_at_utc: str
    verification_event_utc: str
    is_valid_for_event: bool

    def __post_init__(self) -> None:
        if (
            self.contract_version != OPERATOR_FRESHNESS_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != OPERATOR_FRESHNESS_SCHEMA_VERSION
        ):
            raise ValueError("Operator Attestation Freshness Result uses unsupported versions.")
        if self.bounds != CoverageBounds(self.scope.window_start_utc, self.scope.window_end_utc):
            raise ValueError("Operator Attestation Freshness bounds differ from its scope.")
        _canonical_utc(self.latest_base_attempt_retrieved_at_utc)
        _canonical_utc(self.verification_event_utc)
        if type(self.is_valid_for_event) is not bool:
            raise ValueError("Operator Attestation Freshness result must be explicit.")


@dataclass(frozen=True)
class OperatorAttestationState:
    base_assessment_digest: str
    evidence: tuple[AttestationArtifactReference, ...]
    freshness_results: tuple[OperatorAttestationFreshnessResult, ...]

    def __post_init__(self) -> None:
        if _DIGEST_RE.fullmatch(self.base_assessment_digest) is None:
            raise ValueError("Operator Attestation State requires an exact v2 base digest.")
        scopes = tuple(item.attestation.scope for item in self.evidence)
        scope_ids = tuple(item.scope_id for item in scopes)
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("Operator Attestation State evidence must use unique scopes.")
        if scopes:
            canonical = fixture_scopes_for_matchweek(
                scopes[0].matchweek_friday, season=scopes[0].season
            )
            if scopes != canonical:
                raise ValueError(
                    "Operator Attestation State evidence must use all seven ordered scopes."
                )
        result_scopes = tuple(item.scope.scope_id for item in self.freshness_results)
        if result_scopes != scope_ids:
            raise ValueError("Operator Attestation State freshness must match its evidence scopes.")


@dataclass(frozen=True)
class AttestedFixtureCoverageAssessment:
    """Independent F01 v3 value; it deliberately does not inherit from v2."""

    contract_version: str
    schema_version: int
    freshness_policy_id: str | None
    scope_assessments: tuple[FixtureScopeAssessment, ...]
    provider_attempts: tuple[ProviderAttempt, ...]
    coverage_evidence: tuple[ProviderCoverageEvidence, ...]
    fixture_revisions: tuple[FixtureRevisionReference, ...]
    identity_resolutions: tuple[FixtureIdentityResolution, ...]
    freshness_results: tuple[CoverageFreshnessResult, ...]
    schedule_state: MatchweekScheduleState
    operator_attestation_state: OperatorAttestationState
    digest: str = ""

    def __post_init__(self) -> None:
        from matchvet.fixture_coverage_codec import (
            FIXTURE_COVERAGE_V3_CONTRACT_VERSION,
            FIXTURE_COVERAGE_V3_SCHEMA_VERSION,
        )

        if (
            self.contract_version != FIXTURE_COVERAGE_V3_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != FIXTURE_COVERAGE_V3_SCHEMA_VERSION
        ):
            raise ValueError("Attested Fixture Coverage Assessment uses unsupported versions.")
        expected = _model_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Attested Fixture Coverage Assessment digest does not match contents.")
        object.__setattr__(self, "digest", expected)


def _policy_rules() -> tuple[OperatorPublicationRule, ...]:
    rules = (
        _rule(
            "premier-league-full-fixture-release",
            "premier_league",
            "premier-league-ltd",
            "Premier League Ltd",
            "FIXTURE_RELEASE",
            "www.premierleague.com",
            "/en/news/4675097/",
            "https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season",
            ("pairings",),
        ),
        _rule(
            "premier-league-updating-calendar",
            "premier_league",
            "premier-league-ltd",
            "Premier League Ltd",
            "UPDATING_CALENDAR",
            "www.premierleague.com",
            "/en/news/1235133",
            "https://www.premierleague.com/en/news/1235133",
            ("pairings", "exact_schedule", "latest_update"),
        ),
        _rule(
            "serie-a-2026-27-calendar",
            "serie_a",
            "lega-serie-a",
            "Lega Serie A",
            "COMPLETE_CALENDAR",
            "www.legaseriea.it",
            "/serie-a/news/calendario-della-serie-a-enilive-2026-27",
            "https://www.legaseriea.it/serie-a/news/calendario-della-serie-a-enilive-2026-27",
            ("pairings",),
        ),
        _rule(
            "serie-a-calendar-results",
            "serie_a",
            "lega-serie-a",
            "Lega Serie A",
            "CALENDAR_RESULTS",
            "www.legaseriea.it",
            "/serie-a/calendario-risultati",
            "https://www.legaseriea.it/serie-a/calendario-risultati",
            ("pairings", "exact_schedule"),
        ),
        _rule(
            "serie-a-anticipi-posticipi",
            "serie_a",
            "lega-serie-a",
            "Lega Serie A",
            "SCHEDULING_NOTICE",
            "www.legaseriea.it",
            "/serie-a/news/anticipi-e-posticipi-",
            "https://www.legaseriea.it/serie-a/news/anticipi-e-posticipi-fino-alla-fine-del-girone-di-andata",
            ("exact_schedule", "latest_update"),
        ),
        _rule(
            "rfef-primera-calendar",
            "la_liga",
            "rfef",
            "Real Federación Española de Fútbol",
            "COMPLETE_CALENDAR",
            "rfef.es",
            "/es/noticias/calendario-completo-primera-division-temporada-202627",
            "https://rfef.es/es/noticias/calendario-completo-primera-division-temporada-202627",
            ("pairings",),
        ),
        _rule(
            "laliga-official-calendar",
            "la_liga",
            "laliga",
            "LALIGA",
            "OFFICIAL_CALENDAR",
            "www.laliga.com",
            "/calendar-2026-2027/laliga-easports",
            "https://www.laliga.com/calendar-2026-2027/laliga-easports",
            ("pairings",),
        ),
        _rule(
            "laliga-horarios",
            "la_liga",
            "laliga",
            "LALIGA",
            "HORARIOS",
            "www.laliga.com",
            "/noticias/horarios-de-la-",
            "https://www.laliga.com/noticias/horarios-de-la-primera-jornada-de-laliga-ea-sports-2026-27",
            ("exact_schedule", "latest_update"),
        ),
        _rule(
            "bundesliga-2026-27-fixture-release",
            "bundesliga",
            "dfl",
            "DFL Deutsche Fußball Liga",
            "FIXTURE_RELEASE",
            "www.bundesliga.com",
            "/en/bundesliga/news/2026-27-season-fixture-schedules-37671",
            "https://www.bundesliga.com/en/bundesliga/news/2026-27-season-fixture-schedules-37671",
            ("pairings",),
        ),
        _rule(
            "bundesliga-confirmed-kickoff-updates",
            "bundesliga",
            "dfl",
            "DFL Deutsche Fußball Liga",
            "KICKOFF_UPDATE",
            "www.bundesliga.com",
            "/en/bundesliga/news/confirmed-kick-off-times-dates-2026-27-fixtures-",
            "https://www.bundesliga.com/en/bundesliga/news/confirmed-kick-off-times-dates-2026-27-fixtures-23955/",
            ("exact_schedule", "latest_update"),
        ),
        _rule(
            "ligue-1-2026-27-calendar",
            "ligue_1",
            "lfp",
            "LFP",
            "SEASON_CALENDAR",
            "ligue1.com",
            "/fr/articles/l1_article_5284-",
            "https://ligue1.com/fr/articles/l1_article_5284-",
            ("pairings",),
        ),
        _rule(
            "ligue-1-programmation",
            "ligue_1",
            "lfp",
            "LFP",
            "PROGRAMMATION",
            "ligue1.com",
            "/fr/articles/",
            "https://ligue1.com/fr/articles/",
            ("exact_schedule", "latest_update"),
            path_pattern=(
                r"/fr/articles/l1_article_[0-9]+-(?:ligue-1-)?(?:la-|le-|les-)?"
                r"(?:programmation|calendrier|horaires?|journ(?:e|é)e?s?)"
                r"(?:-[^/]*)?"
            ),
        ),
        _rule(
            "liga-portugal-professional-calendars",
            "liga_portugal",
            "liga-portugal",
            "Liga Portugal",
            "COMPETITION_CALENDARS",
            "www.ligaportugal.pt",
            "/news/28156/",
            "https://www.ligaportugal.pt/news/28156/os-calendarios-dos-campeonatos-profissionais-202627",
            ("pairings",),
        ),
        _rule(
            "liga-portugal-official-calendar",
            "liga_portugal",
            "liga-portugal",
            "Liga Portugal",
            "OFFICIAL_CALENDAR",
            "www.ligaportugal.pt",
            "/calendar",
            "https://www.ligaportugal.pt/calendar",
            ("pairings",),
        ),
        _rule(
            "liga-portugal-round-updates",
            "liga_portugal",
            "liga-portugal",
            "Liga Portugal",
            "ROUND_SCHEDULE",
            "www.ligaportugal.pt",
            "/news/",
            "https://www.ligaportugal.pt/news/",
            ("exact_schedule", "latest_update"),
            path_pattern=(
                r"/news/[0-9]+/(?:(?:os|as|o|a)-)?"
                r"(?:calend[aá]rios?|jornadas?|"
                r"hor[aá]rios?-(?:dos-jogos|de-jogos|da-jornada)|"
                r"programa[cç][aã]o-(?:dos-jogos|de-jogos|da-jornada|das-jornadas)|"
                r"agendamentos?-(?:dos-jogos|da-jornada))"
                r"(?:-[^/]*)?"
            ),
        ),
        _rule(
            "belgian-pro-league-pairings",
            "belgian_pro_league",
            "pro-league",
            "Pro League",
            "FIXTURE_PAIRINGS",
            "www.proleague.be",
            "/nieuws/kalender-2026-2027",
            "https://www.proleague.be/nieuws/kalender-2026-2027-club-brugge-opent-tegen-kv-kortrijk-eerste-super-sunday-al-op-speeldag-4",
            ("pairings",),
        ),
        _rule(
            "belgian-jpl-calendar",
            "belgian_pro_league",
            "pro-league",
            "Pro League",
            "OFFICIAL_CALENDAR",
            "www.proleague.be",
            "/fr/jpl-calendar",
            "https://www.proleague.be/fr/jpl-calendar",
            ("pairings",),
        ),
        _rule(
            "belgian-schedule-updates",
            "belgian_pro_league",
            "pro-league",
            "Pro League",
            "SCHEDULE_UPDATE",
            "www.proleague.be",
            "/fr/informations/les-calendriers-des-fans-fixes-",
            "https://www.proleague.be/fr/informations/les-calendriers-des-fans-fixes-jusquapres-la-treve-hivernale",
            ("exact_schedule", "latest_update"),
        ),
    )
    return tuple(sorted(rules, key=lambda item: item.publication_id))


def _rule(
    publication_id: str,
    league_key: str,
    publisher_id: str,
    publisher_name: str,
    publication_type: str,
    host: str,
    path_prefix: str,
    example_url: str,
    supported_layers: tuple[str, ...],
    *,
    path_pattern: str | None = None,
) -> OperatorPublicationRule:
    return OperatorPublicationRule(
        publication_id=publication_id,
        league_key=league_key,
        publisher_id=publisher_id,
        publisher_name=publisher_name,
        competition_id=league_key,
        publication_type=publication_type,
        host=host,
        path_prefix=path_prefix,
        example_url=example_url,
        supported_layers=supported_layers,
        path_pattern=path_pattern,
    )


def operator_attestation_policy_v1() -> OperatorAttestationPolicySnapshot:
    """Return the immutable policy snapshot seeded by the complete issue #45 registry."""
    rules = _policy_rules()
    leagues = tuple(sorted({rule.league_key for rule in rules}))
    layers = tuple((league, ("exact_schedule", "latest_update", "pairings")) for league in leagues)
    return OperatorAttestationPolicySnapshot(
        policy_id=OPERATOR_ATTESTATION_POLICY_ID,
        policy_version=OPERATOR_ATTESTATION_POLICY_VERSION,
        publication_rules=rules,
        required_layer_ids=layers,
        required_confirmations=(
            "all_official_fixtures_represented",
            "no_extra_matchvet_fixture",
            "complete_official_publication_covers_scope",
            "pairing_calendar_layer_checked",
            "exact_schedule_layer_checked",
            "latest_applicable_update_checked",
            "candidate_identity_date_kickoff_status_match",
        ),
    )


def operator_attestation_policy_v2() -> OperatorAttestationPolicySnapshot:
    """Return the v2 publication policy, preserving all v1 rules and adding current paths."""
    rules = tuple(
        replace(
            rule,
            path_prefix="/fr/articles/l1_article_",
            example_url="https://ligue1.com/fr/articles/l1_article_5797-",
            path_pattern=(
                r"/fr/articles/(?:l1_article_5797-|l1_article_[0-9]+-"
                r"(?:ligue-1-)?(?:la-|le-|les-)?"
                r"(?:programmation|calendrier|horaires?|journ(?:e|é)e?s?)"
                r"(?:-[^/]*)?)"
            ),
        )
        if rule.publication_id == "ligue-1-programmation"
        else replace(
            rule,
            path_prefix="/",
            example_url=(
                "https://www.ligaportugal.pt/noticias/28531/horarios-definidos-ate-a-12.a-jornada"
            ),
            path_pattern=(
                r"/(?:news|noticias)/[0-9]+/(?:(?:os|as|o|a)-)?"
                r"(?:calend[aá]rios?|jornadas?|"
                r"hor[aá]rios?-(?:dos-jogos|de-jogos|da-jornada)|"
                r"programa[cç][aã]o-(?:dos-jogos|de-jogos|da-jornada|das-jornadas)|"
                r"agendamentos?-(?:dos-jogos|da-jornada)|"
                r"hor[aá]rios?-definidos(?:-[^/]*)?)"
                r"(?:-[^/]*)?"
            ),
        )
        if rule.publication_id == "liga-portugal-round-updates"
        else rule
        for rule in _policy_rules()
    )
    v1 = operator_attestation_policy_v1()
    return OperatorAttestationPolicySnapshot(
        policy_id=OPERATOR_ATTESTATION_POLICY_ID,
        policy_version=OPERATOR_ATTESTATION_POLICY_V2_VERSION,
        publication_rules=rules,
        required_layer_ids=v1.required_layer_ids,
        required_confirmations=v1.required_confirmations,
    )


def policy_publications_for_scope(scope: FixtureScope) -> tuple[OfficialPublicationReference, ...]:
    """Build source references from approved policy seed links for offline domain tests."""
    rules = tuple(rule for rule in _policy_rules() if rule.league_key == scope.league_key)
    return tuple(
        sorted(
            (
                OfficialPublicationReference(
                    publication_id=rule.publication_id,
                    publisher_id=rule.publisher_id,
                    competition_id=rule.competition_id,
                    official_url=rule.example_url,
                    title_or_publication_id=rule.publication_id,
                    publication_date=None,
                    publication_type=rule.publication_type,
                    claim_scope_id=scope.scope_id,
                    covers_exact_scope=True,
                    complete_for_scope=True,
                )
                for rule in rules
            ),
            key=lambda item: (item.publication_id, item.official_url),
        )
    )


def build_candidate_manifest(
    base_assessment: FixtureCoverageAssessment,
    scope_id: str,
    *,
    revision_facts: tuple[CandidateRevisionFact, ...],
    assertion_facts: tuple[CandidateAssertionFact, ...] = (),
) -> CandidateManifestV2:
    """Build a deterministic manifest from only references already retained by the v2 base."""
    _require_v2_base(base_assessment)
    selected_scope = _scope_for_id(base_assessment, scope_id)
    identities = tuple(
        item for item in base_assessment.identity_resolutions if item.scope_id == scope_id
    )
    revision_by_id = {item.reference.revision_id: item for item in revision_facts}
    assertion_by_id = {item.assertion_id: item for item in assertion_facts}
    if len(revision_by_id) != len(revision_facts) or len(assertion_by_id) != len(assertion_facts):
        raise ValueError("Candidate Manifest fact IDs must be unique.")
    base_revisions = {
        item.revision_id: item
        for item in base_assessment.fixture_revisions
        if item.scope_id == scope_id
    }
    used_revision_ids: set[str] = set()
    used_assertion_ids: set[str] = set()
    entries: list[CandidateManifestEntry] = []
    for identity in sorted(identities, key=lambda item: item.candidate_id):
        candidate_revisions: list[CandidateRevisionFact] = []
        expected_source_assertion_ids: set[str] = set(identity.source_assertion_ids)
        expected_capture_ids: set[str] = set(identity.source_capture_ids)
        for revision_id in identity.revision_ids:
            reference = base_revisions.get(revision_id)
            fact = revision_by_id.get(revision_id)
            if reference is None or fact is None or fact.reference != reference:
                raise ValueError(
                    "Candidate Manifest revision facts must match exact base references."
                )
            candidate_revisions.append(fact)
            used_revision_ids.add(revision_id)
            expected_source_assertion_ids.update(reference.source_assertion_ids)
            expected_capture_ids.update(reference.source_capture_ids)
        selected_assertions = tuple(
            sorted(
                (
                    assertion_by_id[item]
                    for item in expected_source_assertion_ids
                    if item in assertion_by_id
                ),
                key=lambda item: item.assertion_id,
            )
        )
        if {item.assertion_id for item in selected_assertions} != expected_source_assertion_ids:
            raise ValueError("Candidate Manifest assertion facts must match exact base references.")
        used_assertion_ids.update(expected_source_assertion_ids)
        entries.append(
            CandidateManifestEntry(
                candidate_id=identity.candidate_id,
                scope_id=scope_id,
                identity_state=identity.state,
                canonical_fixture_id=identity.canonical_fixture_id,
                revision_facts=tuple(
                    sorted(candidate_revisions, key=lambda item: item.reference.revision_id)
                ),
                assertion_facts=selected_assertions,
                source_capture_ids=tuple(sorted(expected_capture_ids)),
                source_assertion_ids=tuple(sorted(expected_source_assertion_ids)),
                reason_code=identity.reason_code,
                has_schedule_conflict=False,
                has_provisional_scheduling=False,
            )
        )
    if used_revision_ids != set(base_revisions) or used_assertion_ids != set(assertion_by_id):
        raise ValueError("Candidate Manifest includes facts outside exact scoped F01 references.")
    classified_entries = _with_manifest_schedule_relations(entries, selected_scope)
    manifest = CandidateManifestV2(
        contract_version=OPERATOR_CANDIDATE_MANIFEST_V2_CONTRACT_VERSION,
        schema_version=OPERATOR_CANDIDATE_MANIFEST_V2_SCHEMA_VERSION,
        base_assessment_digest=base_assessment.digest,
        scope=selected_scope,
        bounds=CoverageBounds(selected_scope.window_start_utc, selected_scope.window_end_utc),
        entries=tuple(classified_entries),
        candidate_count=_candidate_count(tuple(classified_entries)),
    )
    _validate_manifest_binding(base_assessment, manifest)
    return manifest


def _build_candidate_manifest_v1_for_replay(
    base_assessment: FixtureCoverageAssessment,
    scope_id: str,
    *,
    revision_facts: tuple[CandidateRevisionFact, ...],
    assertion_facts: tuple[CandidateAssertionFact, ...],
) -> CandidateManifest:
    """Rebuild an old manifest with its original v1 raw-fact classification."""
    current = build_candidate_manifest(
        base_assessment,
        scope_id,
        revision_facts=revision_facts,
        assertion_facts=assertion_facts,
    )
    entries = [
        CandidateManifestEntry(
            candidate_id=item.candidate_id,
            scope_id=item.scope_id,
            identity_state=item.identity_state,
            canonical_fixture_id=item.canonical_fixture_id,
            revision_facts=item.revision_facts,
            assertion_facts=item.assertion_facts,
            source_capture_ids=item.source_capture_ids,
            source_assertion_ids=item.source_assertion_ids,
            reason_code=item.reason_code,
            has_schedule_conflict=False,
            has_provisional_scheduling=False,
        )
        for item in current.entries
    ]
    classified = _with_manifest_fact_flags(entries)
    manifest = CandidateManifest(
        contract_version=OPERATOR_CANDIDATE_MANIFEST_CONTRACT_VERSION,
        schema_version=OPERATOR_CANDIDATE_MANIFEST_SCHEMA_VERSION,
        base_assessment_digest=current.base_assessment_digest,
        scope=current.scope,
        bounds=current.bounds,
        entries=tuple(classified),
        candidate_count=_candidate_count(tuple(classified)),
    )
    _validate_manifest_binding(base_assessment, manifest)
    return manifest


def _with_manifest_fact_flags(
    entries: list[CandidateManifestEntry],
) -> list[CandidateManifestEntry]:
    revisions_by_fixture: dict[str, list[CandidateRevisionFact]] = {}
    for entry in entries:
        if entry.canonical_fixture_id is not None:
            revisions_by_fixture.setdefault(entry.canonical_fixture_id, []).extend(
                entry.revision_facts
            )
    conflicting_fixture_ids = {
        fixture_id
        for fixture_id, revisions in revisions_by_fixture.items()
        if len(
            {
                (
                    item.home_team_id,
                    item.away_team_id,
                    item.kickoff_state,
                    item.kickoff_utc,
                    item.fixture_status,
                )
                for item in revisions
            }
        )
        > 1
    }
    return [
        replace(
            entry,
            has_schedule_conflict=(
                entry.canonical_fixture_id in conflicting_fixture_ids
                if entry.canonical_fixture_id is not None
                else False
            ),
            has_provisional_scheduling=any(
                _revision_is_provisional(item) for item in entry.revision_facts
            ),
        )
        for entry in entries
    ]


def _revision_is_provisional(value: CandidateRevisionFact) -> bool:
    tbc_tokens = ("TBC", "TBA", "TBD", "PROVISIONAL")
    local = (value.kickoff_local_text or "").upper()
    return (
        value.kickoff_state != "OBSERVED"
        or value.kickoff_utc is None
        or value.kickoff_precision != "INSTANT"
        or value.fixture_status == "UNKNOWN"
        or any(token in local for token in tbc_tokens)
    )


def _with_manifest_schedule_relations(
    entries: list[CandidateManifestEntry], scope: FixtureScope
) -> list[CandidateManifestEntryV2]:
    revisions_by_fixture: dict[str, list[CandidateManifestEntry]] = {}
    for entry in entries:
        fixture_key = entry.canonical_fixture_id or entry.candidate_id
        revisions_by_fixture.setdefault(fixture_key, []).append(entry)
    relations = {
        fixture_key: _classify_fixture_schedule(scope, fixture_entries)
        for fixture_key, fixture_entries in revisions_by_fixture.items()
    }
    output: list[CandidateManifestEntryV2] = []
    for entry in entries:
        fixture_key = entry.canonical_fixture_id or entry.candidate_id
        relation = relations[fixture_key]
        output.append(
            CandidateManifestEntryV2(
                candidate_id=entry.candidate_id,
                scope_id=entry.scope_id,
                identity_state=entry.identity_state,
                canonical_fixture_id=entry.canonical_fixture_id,
                revision_facts=entry.revision_facts,
                assertion_facts=entry.assertion_facts,
                source_capture_ids=entry.source_capture_ids,
                source_assertion_ids=entry.source_assertion_ids,
                reason_code=entry.reason_code,
                has_schedule_conflict=relation is ScheduleRelation.CONFLICTING,
                has_provisional_scheduling=relation is ScheduleRelation.PROVISIONAL,
                schedule_relation=relation,
            )
        )
    return output


def _classify_fixture_schedule(
    scope: FixtureScope, entries: list[CandidateManifestEntry]
) -> ScheduleRelation:
    revisions = [revision for entry in entries for revision in entry.revision_facts]
    if any(entry.identity_state is not FixtureIdentityState.RESOLVED for entry in entries):
        identity_resolved = False
    else:
        identity_resolved = True
    if not revisions:
        return ScheduleRelation.PROVISIONAL

    if len({(item.home_team_id, item.away_team_id) for item in revisions}) > 1:
        return ScheduleRelation.CONFLICTING
    if any(
        item.reference.fixture_id
        != deterministic_identifier(
            "fixture",
            f"{scope.league_key}:{scope.season}:{item.home_team_id}:{item.away_team_id}",
        )
        for item in revisions
    ):
        return ScheduleRelation.CONFLICTING
    fixture_ids = {item.reference.fixture_id for item in revisions}
    canonical_ids = {entry.canonical_fixture_id for entry in entries}
    if len(fixture_ids) > 1 or len(canonical_ids) != 1 or None in canonical_ids:
        return ScheduleRelation.CONFLICTING
    has_provisional_marker = any(
        _SCHEDULE_MARKER_RE.search(value or "") is not None
        for entry in entries
        for revision in entry.revision_facts
        for value in (revision.kickoff_local_text, revision.fixture_status)
    ) or _has_source_schedule_marker(entries)

    concrete_statuses = {
        item.fixture_status.strip().upper()
        for item in revisions
        if item.fixture_status.strip().upper() != "UNKNOWN"
    }
    if len(concrete_statuses) > 1:
        return ScheduleRelation.CONFLICTING

    instant_values: list[datetime] = []
    date_values: list[date] = []
    unusable_schedule = False
    for revision in revisions:
        if revision.kickoff_state != "OBSERVED":
            unusable_schedule = True
        elif revision.kickoff_precision == "INSTANT":
            parsed = _candidate_instant(revision.kickoff_utc)
            if parsed is None:
                unusable_schedule = True
            else:
                instant_values.append(parsed)
        elif revision.kickoff_precision == "DATE":
            parsed_date = _candidate_date(revision.kickoff_local_text)
            if parsed_date is None:
                unusable_schedule = True
            else:
                date_values.append(parsed_date)
        else:
            unusable_schedule = True

    if len(set(instant_values)) > 1 or len(set(date_values)) > 1:
        return ScheduleRelation.CONFLICTING
    if instant_values and date_values:
        league_timezone = league_by_key(scope.league_key).timezone
        instant = instant_values[0]
        for date_value in date_values:
            local_date = instant.astimezone(_source_timezone(league_timezone, date_value)).date()
            if local_date != date_value:
                return ScheduleRelation.CONFLICTING

    if has_provisional_marker:
        return ScheduleRelation.PROVISIONAL
    if not identity_resolved or unusable_schedule or not instant_values or not concrete_statuses:
        return ScheduleRelation.PROVISIONAL
    if date_values:
        return ScheduleRelation.LESS_PRECISE_BUT_COMPATIBLE
    return ScheduleRelation.EXACT


def _candidate_instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _candidate_date(value: str | None) -> date | None:
    return _parse_date(value)


def _has_source_schedule_marker(entries: list[CandidateManifestEntry]) -> bool:
    for entry in entries:
        for assertion in entry.assertion_facts:
            if not _is_schedule_assertion(assertion):
                continue
            if any(
                _SCHEDULE_MARKER_RE.search(value or "") is not None
                for value in (
                    assertion.raw_value_json,
                    assertion.normalized_value_json,
                    assertion.unknown_reason,
                )
            ):
                return True
    return False


def _is_schedule_assertion(value: CandidateAssertionFact) -> bool:
    predicate = value.predicate.casefold().replace("-", "_")
    field_name = re.sub(r"[^a-z]", "", value.raw_field_name.casefold())
    return predicate in {"kickoff", "fixture_status", "status", "date", "time"} or field_name in {
        "date",
        "time",
        "datetime",
        "kickoff",
        "fixturestatus",
        "scheduleddate",
        "scheduledtime",
    }


def make_operator_coverage_attestation(
    *,
    base_assessment: FixtureCoverageAssessment,
    candidate_manifest: CandidateManifestValue,
    operator_id: str,
    verified_at_utc: str,
    publications: tuple[OfficialPublicationReference, ...],
    expected_official_fixture_count: int | None,
    candidate_confirmations: tuple[CandidateComparisonConfirmation, ...],
    confirmations: OperatorComparisonConfirmations,
    outcome: OperatorAttestationOutcome,
    reason: str | None,
) -> OperatorCoverageAttestation:
    """Build an event-bound attestation; impossible certifications become REFUSED."""
    _require_v2_base(base_assessment)
    _validate_manifest_binding(base_assessment, candidate_manifest)
    verified_at = _canonical_utc(verified_at_utc)
    latest_attempt = _latest_attempt_retrieval(base_assessment)
    if verified_at <= latest_attempt:
        raise ValueError("Verification time must be strictly after every base Provider Attempt.")
    if not isinstance(outcome, OperatorAttestationOutcome):
        raise ValueError("Operator Coverage Attestation outcome is unsupported.")
    ordered_publications = tuple(
        sorted(publications, key=lambda item: (item.publication_id, item.official_url))
    )
    ordered_confirmations = tuple(
        sorted(candidate_confirmations, key=lambda item: item.candidate_id)
    )
    attestation_reason = (reason or "").strip()
    attestation_outcome = outcome
    policy = (
        operator_attestation_policy_v1()
        if isinstance(candidate_manifest, CandidateManifest)
        else operator_attestation_policy_v2()
    )
    if outcome is OperatorAttestationOutcome.CERTIFIED:
        failures = _certification_failures(
            base_assessment=base_assessment,
            manifest=candidate_manifest,
            publications=ordered_publications,
            expected_official_fixture_count=expected_official_fixture_count,
            candidate_confirmations=ordered_confirmations,
            confirmations=confirmations,
            policy=policy,
        )
        if failures:
            attestation_outcome = OperatorAttestationOutcome.REFUSED
            attestation_reason = failures[0]
        else:
            attestation_reason = ""
    elif not attestation_reason:
        raise ValueError("Refused or uncertain attestation requires a clear reason.")
    attestation_id = _attestation_id(
        base_assessment.digest,
        candidate_manifest.scope.scope_id,
        operator_id,
        verified_at,
    )
    return OperatorCoverageAttestation(
        contract_version=(
            OPERATOR_ATTESTATION_V2_CONTRACT_VERSION
            if isinstance(candidate_manifest, CandidateManifestV2)
            else OPERATOR_ATTESTATION_CONTRACT_VERSION
        ),
        schema_version=(
            OPERATOR_ATTESTATION_V2_SCHEMA_VERSION
            if isinstance(candidate_manifest, CandidateManifestV2)
            else OPERATOR_ATTESTATION_SCHEMA_VERSION
        ),
        attestation_id=attestation_id,
        base_assessment_digest=base_assessment.digest,
        scope=candidate_manifest.scope,
        bounds=candidate_manifest.bounds,
        candidate_manifest=candidate_manifest,
        candidate_manifest_digest=candidate_manifest.digest,
        observed_candidate_count=candidate_manifest.candidate_count,
        operator_id=operator_id,
        verified_at_utc=verified_at,
        policy_snapshot=policy,
        policy_digest=policy.digest,
        publications=ordered_publications,
        expected_official_fixture_count=expected_official_fixture_count,
        candidate_confirmations=ordered_confirmations,
        confirmations=confirmations,
        outcome=attestation_outcome,
        reason=attestation_reason,
    )


def _certification_failures(
    *,
    base_assessment: FixtureCoverageAssessment,
    manifest: CandidateManifestValue,
    publications: tuple[OfficialPublicationReference, ...],
    expected_official_fixture_count: int | None,
    candidate_confirmations: tuple[CandidateComparisonConfirmation, ...],
    confirmations: OperatorComparisonConfirmations,
    policy: OperatorAttestationPolicySnapshot | None = None,
) -> tuple[str, ...]:
    failures: list[str] = []
    policy = policy or operator_attestation_policy_v2()
    matching_rules: list[OperatorPublicationRule] = []
    for publication in publications:
        rule = matching_official_publication_rule(policy, manifest.scope, publication)
        if rule is None:
            failures.append("Publication identity, type, or URL is not approved by the policy.")
        else:
            matching_rules.append(rule)
    required_layers = _required_layers(policy, manifest.scope.league_key)
    checked_layers = {layer for rule in matching_rules for layer in rule.supported_layers}
    missing_layers = sorted(set(required_layers) - checked_layers)
    if missing_layers:
        failures.append(
            f"Required official publication layers are missing: {', '.join(missing_layers)}."
        )
    if not any(item.covers_exact_scope and item.complete_for_scope for item in publications):
        failures.append("No cited complete official publication covers the exact requested scope.")
    if expected_official_fixture_count is None:
        failures.append("Expected official fixture count is missing.")
    elif expected_official_fixture_count != manifest.candidate_count:
        failures.append("Official fixture count differs from the MatchVet candidate count.")
    if not confirmations.all_official_fixtures_represented:
        failures.append("An official fixture is missing from the MatchVet candidate set.")
    if not confirmations.no_extra_matchvet_fixture:
        failures.append("The MatchVet candidate set contains an extra fixture.")
    if not confirmations.complete_official_publication_covers_scope:
        failures.append("The official publication is incomplete for the exact requested scope.")
    if not confirmations.pairing_calendar_layer_checked:
        failures.append("The complete pairing/calendar layer was not confirmed checked.")
    if not confirmations.exact_schedule_layer_checked:
        failures.append("The exact date and kickoff schedule layer was not confirmed checked.")
    if not confirmations.latest_applicable_update_checked:
        failures.append("The latest applicable official scheduling update was not checked.")

    expected_candidate_ids = {item.candidate_id for item in manifest.entries}
    confirmed_candidate_ids = {item.candidate_id for item in candidate_confirmations}
    if confirmed_candidate_ids != expected_candidate_ids:
        failures.append(
            "Every MatchVet candidate requires an explicit identity/date/kickoff/status check."
        )
    if any(
        not all(
            (item.identity_matches, item.date_matches, item.kickoff_matches, item.status_matches)
        )
        for item in candidate_confirmations
    ):
        failures.append(
            "A candidate identity, date, kickoff, or status disagrees with the official source."
        )
    if any(
        item.identity_state is not FixtureIdentityState.RESOLVED
        or item.canonical_fixture_id is None
        for item in manifest.entries
    ):
        failures.append("Unresolved fixture identity prevents exact official membership.")
    if isinstance(manifest, CandidateManifestV2):
        schedule_relations = tuple(item.schedule_relation for item in manifest.entries)
        if ScheduleRelation.CONFLICTING in schedule_relations:
            failures.append("Conflicting immutable fixture revisions prevent exact membership.")
        if ScheduleRelation.PROVISIONAL in schedule_relations:
            failures.append("Provisional or TBC MatchVet scheduling prevents exact membership.")
    elif any(item.has_schedule_conflict for item in manifest.entries):
        failures.append("Conflicting immutable fixture revisions prevent exact membership.")
    if not isinstance(manifest, CandidateManifestV2) and any(
        item.has_provisional_scheduling for item in manifest.entries
    ):
        failures.append("Provisional or TBC MatchVet scheduling prevents exact membership.")

    if manifest.candidate_count == 0:
        if not confirmations.complete_publication_affirms_empty_scope:
            failures.append("An empty scope requires an affirmative complete official publication.")
        if expected_official_fixture_count != 0:
            failures.append("An empty MatchVet scope requires an official fixture count of zero.")
        if manifest.entries:
            failures.append("Unresolved candidates cannot be treated as an empty scope.")
    else:
        if confirmations.complete_publication_affirms_empty_scope:
            failures.append("A nonempty candidate set cannot be certified as empty.")
    if not base_assessment.provider_attempts:
        failures.append("The exact base assessment has no automatic acquisition event.")
    return tuple(failures)


def derive_attested_fixture_coverage(
    base_assessment: FixtureCoverageAssessment,
    attestations: tuple[AttestationArtifactReference, ...],
) -> AttestedFixtureCoverageAssessment:
    """Purely derive v3 from one exact persisted-v2 value and seven selected events."""
    _require_v2_base(base_assessment)
    expected_scopes = tuple(item.scope for item in base_assessment.scope_assessments)
    canonical_scopes = fixture_scopes_for_matchweek(
        expected_scopes[0].matchweek_friday, season=expected_scopes[0].season
    )
    if expected_scopes != canonical_scopes:
        raise ValueError("F01 v3 derivation requires the exact seven configured Fixture Scopes.")
    if len(attestations) != len(canonical_scopes):
        raise ValueError("F01 v3 derivation requires one explicit attestation per exact scope.")
    by_scope = {item.attestation.scope.scope_id: item for item in attestations}
    if len(by_scope) != len(attestations) or set(by_scope) != {
        scope.scope_id for scope in canonical_scopes
    }:
        raise ValueError("F01 v3 derivation requires seven distinct exact scope attestations.")

    evidence: list[AttestationArtifactReference] = []
    freshness: list[OperatorAttestationFreshnessResult] = []
    states: dict[str, ScopeCoverageState] = {}
    for scope in canonical_scopes:
        selected = by_scope[scope.scope_id]
        _validate_attestation_binding(base_assessment, selected.attestation)
        if selected.attestation.outcome is not OperatorAttestationOutcome.CERTIFIED:
            raise ValueError("Refused or uncertain attestations cannot promote F01 coverage.")
        failures = _certification_failures(
            base_assessment=base_assessment,
            manifest=selected.attestation.candidate_manifest,
            publications=selected.attestation.publications,
            expected_official_fixture_count=selected.attestation.expected_official_fixture_count,
            candidate_confirmations=selected.attestation.candidate_confirmations,
            confirmations=selected.attestation.confirmations,
        )
        if failures:
            raise ValueError(f"Operator attestation no longer validates: {failures[0]}")
        result = _freshness_result(base_assessment, selected.attestation)
        if not result.is_valid_for_event:
            raise ValueError("Operator Attestation Freshness event is invalid for this base.")
        state = (
            ScopeCoverageState.CONFIRMED_EMPTY
            if selected.attestation.observed_candidate_count == 0
            else ScopeCoverageState.COMPLETE
        )
        states[scope.scope_id] = state
        evidence.append(selected)
        freshness.append(result)

    scope_assessments = tuple(
        replace(item, coverage_state=states[item.scope.scope_id])
        for item in base_assessment.scope_assessments
    )
    all_empty = all(value is ScopeCoverageState.CONFIRMED_EMPTY for value in states.values())
    return AttestedFixtureCoverageAssessment(
        contract_version="fixture-coverage-v3-v3",
        schema_version=3,
        freshness_policy_id=base_assessment.freshness_policy_id,
        scope_assessments=scope_assessments,
        provider_attempts=base_assessment.provider_attempts,
        coverage_evidence=base_assessment.coverage_evidence,
        fixture_revisions=base_assessment.fixture_revisions,
        identity_resolutions=base_assessment.identity_resolutions,
        freshness_results=base_assessment.freshness_results,
        schedule_state=(
            MatchweekScheduleState.CONFIRMED_EMPTY if all_empty else MatchweekScheduleState.COMPLETE
        ),
        operator_attestation_state=OperatorAttestationState(
            base_assessment_digest=base_assessment.digest,
            evidence=tuple(evidence),
            freshness_results=tuple(freshness),
        ),
    )


def validate_attested_assessment_base(
    base_assessment: FixtureCoverageAssessment,
    assessment: AttestedFixtureCoverageAssessment,
) -> None:
    """Require every ordinary provider and identity field to equal the exact v2 base."""
    _require_v2_base(base_assessment)
    state = assessment.operator_attestation_state
    if state.base_assessment_digest != base_assessment.digest:
        raise ValueError("F01 v3 assessment references a different v2 base digest.")
    if (
        assessment.freshness_policy_id != base_assessment.freshness_policy_id
        or assessment.provider_attempts != base_assessment.provider_attempts
        or assessment.coverage_evidence != base_assessment.coverage_evidence
        or assessment.fixture_revisions != base_assessment.fixture_revisions
        or assessment.identity_resolutions != base_assessment.identity_resolutions
        or assessment.freshness_results != base_assessment.freshness_results
    ):
        raise ValueError(
            "F01 v3 provider or immutable fixture facts differ from its exact v2 base."
        )
    if len(state.evidence) != 7:
        raise ValueError("F01 v3 requires exactly seven operator attestation artifacts.")
    replayed = derive_attested_fixture_coverage(base_assessment, state.evidence)
    if replayed != assessment:
        raise ValueError("F01 v3 assessment differs from deterministic attestation derivation.")


def operator_attestation_to_canonical_json(value: OperatorCoverageAttestation) -> str:
    """Return canonical attestation bytes represented as compact UTF-8 JSON."""
    if type(value) is not OperatorCoverageAttestation:
        raise FixtureCoveragePayloadError("A typed OperatorCoverageAttestation is required.")
    return _canonical_json(value)


def operator_attestation_from_canonical_json(encoded: str) -> OperatorCoverageAttestation:
    """Decode one exact canonical attestation value and recompute its digest."""
    try:
        raw = _canonical_root(encoded)
        value = _operator_attestation_from_json(raw)
        if operator_attestation_to_canonical_json(value) != encoded:
            raise FixtureCoveragePayloadError(
                "Operator Attestation changes after canonical decode."
            )
        return value
    except FixtureCoveragePayloadError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FixtureCoveragePayloadError(
            "Operator Coverage Attestation payload is invalid."
        ) from error


def attested_fixture_coverage_assessment_to_canonical_json(
    value: AttestedFixtureCoverageAssessment,
) -> str:
    """Serialize the independent F01 v3 payload without changing v2 serialization."""
    if type(value) is not AttestedFixtureCoverageAssessment:
        raise FixtureCoveragePayloadError("A typed F01 v3 assessment is required.")
    if (value.contract_version, value.schema_version) != ("fixture-coverage-v3-v3", 3):
        raise FixtureCoveragePayloadError("F01 v3 contract/schema versions do not match.")
    return _canonical_json(value)


def attested_fixture_coverage_assessment_from_canonical_json(
    encoded: str,
) -> AttestedFixtureCoverageAssessment:
    """Decode v3 using strict typed shapes; F03 later verifies its base and artifacts."""
    try:
        raw_value = _canonical_root(encoded)
        root = _payload_object(
            raw_value,
            (
                "contract_version",
                "schema_version",
                "freshness_policy_id",
                "scope_assessments",
                "provider_attempts",
                "coverage_evidence",
                "fixture_revisions",
                "identity_resolutions",
                "freshness_results",
                "schedule_state",
                "operator_attestation_state",
                "digest",
            ),
            "Attested Fixture Coverage Assessment",
        )
        if (root["contract_version"], root["schema_version"]) != ("fixture-coverage-v3-v3", 3):
            raise FixtureCoveragePayloadError("F01 v3 contract/schema versions do not match.")
        value = AttestedFixtureCoverageAssessment(
            contract_version=_payload_string(root["contract_version"], "contract_version"),
            schema_version=_payload_int(root["schema_version"], "schema_version"),
            freshness_policy_id=_payload_optional_string(
                root["freshness_policy_id"], "freshness_policy_id"
            ),
            scope_assessments=tuple(
                _scope_assessment_from_json(item)
                for item in _payload_list(root["scope_assessments"], "scope_assessments")
            ),
            provider_attempts=tuple(
                _provider_attempt_from_json(item)
                for item in _payload_list(root["provider_attempts"], "provider_attempts")
            ),
            coverage_evidence=tuple(
                _coverage_evidence_from_json(item)
                for item in _payload_list(root["coverage_evidence"], "coverage_evidence")
            ),
            fixture_revisions=tuple(
                _revision_reference_from_json(item)
                for item in _payload_list(root["fixture_revisions"], "fixture_revisions")
            ),
            identity_resolutions=tuple(
                _identity_resolution_from_json(item)
                for item in _payload_list(root["identity_resolutions"], "identity_resolutions")
            ),
            freshness_results=tuple(
                _freshness_result_from_json(item)
                for item in _payload_list(root["freshness_results"], "freshness_results")
            ),
            schedule_state=MatchweekScheduleState(
                _payload_string(root["schedule_state"], "schedule_state")
            ),
            operator_attestation_state=_operator_state_from_json(
                root["operator_attestation_state"]
            ),
            digest=_payload_string(root["digest"], "digest"),
        )
        if attested_fixture_coverage_assessment_to_canonical_json(value) != encoded:
            raise FixtureCoveragePayloadError("F01 v3 payload changes after canonical decode.")
        return value
    except FixtureCoveragePayloadError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FixtureCoveragePayloadError(
            "Attested Fixture Coverage payload is invalid."
        ) from error


def _validate_attestation_binding(
    base_assessment: FixtureCoverageAssessment,
    attestation: OperatorCoverageAttestation,
) -> None:
    if attestation.base_assessment_digest != base_assessment.digest:
        raise ValueError("Operator attestation cannot be reused with a changed base assessment.")
    scope = _scope_for_id(base_assessment, attestation.scope.scope_id)
    if attestation.scope != scope or attestation.bounds != CoverageBounds(
        scope.window_start_utc, scope.window_end_utc
    ):
        raise ValueError(
            "Operator attestation scope, season, Friday, or bounds do not match the base."
        )
    _validate_manifest_binding(base_assessment, attestation.candidate_manifest)
    if attestation.candidate_manifest_digest != attestation.candidate_manifest.digest:
        raise ValueError("Operator attestation candidate manifest digest changed.")
    policy = (
        operator_attestation_policy_v1()
        if attestation.policy_snapshot.policy_version == OPERATOR_ATTESTATION_POLICY_VERSION
        else operator_attestation_policy_v2()
    )
    if attestation.policy_snapshot != policy or attestation.policy_digest != policy.digest:
        raise ValueError("Operator attestation policy snapshot is unsupported or changed.")
    latest_attempt = _latest_attempt_retrieval(base_assessment)
    if attestation.verified_at_utc <= latest_attempt:
        raise ValueError("Operator verification event must follow the latest base acquisition.")


def validate_operator_coverage_attestation(
    base_assessment: FixtureCoverageAssessment,
    attestation: OperatorCoverageAttestation,
) -> None:
    """Validate the exact base, policy, freshness event, and any claimed certification."""
    _require_v2_base(base_assessment)
    if type(attestation) is not OperatorCoverageAttestation:
        raise ValueError("A typed OperatorCoverageAttestation is required.")
    _validate_attestation_binding(base_assessment, attestation)
    if attestation.outcome is OperatorAttestationOutcome.CERTIFIED:
        policy = (
            operator_attestation_policy_v1()
            if attestation.policy_snapshot.policy_version == OPERATOR_ATTESTATION_POLICY_VERSION
            else operator_attestation_policy_v2()
        )
        failures = _certification_failures(
            base_assessment=base_assessment,
            manifest=attestation.candidate_manifest,
            publications=attestation.publications,
            expected_official_fixture_count=attestation.expected_official_fixture_count,
            candidate_confirmations=attestation.candidate_confirmations,
            confirmations=attestation.confirmations,
            policy=policy,
        )
        if failures:
            raise ValueError(f"Certified operator attestation is invalid: {failures[0]}")


def _validate_manifest_binding(
    base_assessment: FixtureCoverageAssessment,
    manifest: CandidateManifestValue,
) -> None:
    if manifest.base_assessment_digest != base_assessment.digest:
        raise ValueError("Candidate manifest cannot be reused with a changed base assessment.")
    scope = _scope_for_id(base_assessment, manifest.scope.scope_id)
    if manifest.scope != scope or manifest.bounds != CoverageBounds(
        scope.window_start_utc, scope.window_end_utc
    ):
        raise ValueError("Candidate manifest scope or bounds differ from the exact v2 base.")
    identities = {
        item.candidate_id: item
        for item in base_assessment.identity_resolutions
        if item.scope_id == scope.scope_id
    }
    entries = {item.candidate_id: item for item in manifest.entries}
    if set(entries) != set(identities):
        raise ValueError("Candidate manifest must retain every scoped base candidate.")
    revision_references = {
        item.revision_id: item
        for item in base_assessment.fixture_revisions
        if item.scope_id == scope.scope_id
    }
    capture_digests = {
        item.capture_id: item.capture_digest
        for item in base_assessment.provider_attempts
        if item.capture_id is not None and item.capture_digest is not None
    }
    for candidate_id, identity in identities.items():
        entry = entries[candidate_id]
        expected_captures = set(identity.source_capture_ids)
        expected_assertions = set(identity.source_assertion_ids)
        for candidate_revision_reference in (
            revision_references[item] for item in identity.revision_ids
        ):
            expected_captures.update(candidate_revision_reference.source_capture_ids)
            expected_assertions.update(candidate_revision_reference.source_assertion_ids)
        if (
            entry.scope_id != identity.scope_id
            or entry.identity_state is not identity.state
            or entry.canonical_fixture_id != identity.canonical_fixture_id
            or entry.reason_code != identity.reason_code
            or entry.source_capture_ids != tuple(sorted(expected_captures))
            or set(entry.source_assertion_ids) != expected_assertions
        ):
            raise ValueError("Candidate manifest identity differs from the exact base candidate.")
        expected_revision_ids = set(identity.revision_ids)
        facts = {item.reference.revision_id: item for item in entry.revision_facts}
        if set(facts) != expected_revision_ids:
            raise ValueError("Candidate manifest revisions differ from the exact base candidate.")
        for revision_id, fact in facts.items():
            matched_revision_reference = revision_references.get(revision_id)
            if matched_revision_reference is None:
                raise ValueError("Candidate manifest revision digest differs from the exact base.")
            if fact.reference != matched_revision_reference:
                raise ValueError("Candidate manifest revision digest differs from the exact base.")
            if not set(matched_revision_reference.source_assertion_ids).issubset(
                entry.source_assertion_ids
            ):
                raise ValueError("Candidate manifest omitted exact revision assertion references.")
            if fact.reference.fixture_id != entry.canonical_fixture_id:
                raise ValueError("Candidate manifest revision identity differs from its base.")
            expected_fixture_id = deterministic_identifier(
                "fixture",
                f"{scope.league_key}:{scope.season}:{fact.home_team_id}:{fact.away_team_id}",
            )
            if expected_fixture_id != fact.reference.fixture_id and not isinstance(
                manifest, CandidateManifestV2
            ):
                raise ValueError("Candidate manifest teams differ from its exact base fixture ID.")
            if fact.reference.revision_digest != _revision_fact_digest(fact):
                raise ValueError("Candidate manifest revision facts do not match their digest.")
        fact_assertion_ids = {item.assertion_id for item in entry.assertion_facts}
        if fact_assertion_ids != set(entry.source_assertion_ids):
            raise ValueError(
                "Candidate manifest assertion facts differ from their exact references."
            )
        if any(
            item.capture_id not in entry.source_capture_ids
            or (
                item.capture_id in capture_digests
                and capture_digests[item.capture_id] != item.capture_digest
            )
            for item in entry.assertion_facts
        ):
            raise ValueError("Candidate manifest assertions differ from exact capture provenance.")
    expected_entries: tuple[CandidateManifestEntryValue, ...]
    if isinstance(manifest, CandidateManifestV2):
        unclassified_entries = [
            CandidateManifestEntry(
                candidate_id=item.candidate_id,
                scope_id=item.scope_id,
                identity_state=item.identity_state,
                canonical_fixture_id=item.canonical_fixture_id,
                revision_facts=item.revision_facts,
                assertion_facts=item.assertion_facts,
                source_capture_ids=item.source_capture_ids,
                source_assertion_ids=item.source_assertion_ids,
                reason_code=item.reason_code,
                has_schedule_conflict=False,
                has_provisional_scheduling=False,
            )
            for item in manifest.entries
        ]
        expected_entries = tuple(_with_manifest_schedule_relations(unclassified_entries, scope))
    else:
        expected_entries = tuple(_with_manifest_fact_flags(list(manifest.entries)))
    if expected_entries != manifest.entries:
        raise ValueError("Candidate manifest conflict or provisional indicators changed.")
    if manifest.candidate_count != _candidate_count(manifest.entries):
        raise ValueError("Candidate manifest count differs from distinct MatchVet fixtures.")


def _freshness_result(
    base_assessment: FixtureCoverageAssessment,
    attestation: OperatorCoverageAttestation,
) -> OperatorAttestationFreshnessResult:
    latest_attempt = _latest_attempt_retrieval(base_assessment)
    return OperatorAttestationFreshnessResult(
        contract_version=OPERATOR_FRESHNESS_CONTRACT_VERSION,
        schema_version=OPERATOR_FRESHNESS_SCHEMA_VERSION,
        base_assessment_digest=base_assessment.digest,
        scope=attestation.scope,
        bounds=attestation.bounds,
        candidate_manifest_digest=attestation.candidate_manifest_digest,
        policy_digest=attestation.policy_digest,
        attestation_id=attestation.attestation_id,
        attestation_digest=attestation.digest,
        latest_base_attempt_retrieved_at_utc=latest_attempt,
        verification_event_utc=attestation.verified_at_utc,
        is_valid_for_event=attestation.verified_at_utc > latest_attempt,
    )


def matching_official_publication_rule(
    policy: OperatorAttestationPolicySnapshot,
    scope: FixtureScope,
    publication: OfficialPublicationReference,
) -> OperatorPublicationRule | None:
    """Match a citation against the supplied immutable official publication policy."""
    rule = next(
        (
            item
            for item in policy.publication_rules
            if item.publication_id == publication.publication_id
        ),
        None,
    )
    if rule is None:
        return None
    try:
        parsed = urlsplit(publication.official_url)
        port = parsed.port
    except ValueError:
        return None
    if (
        rule.league_key != scope.league_key
        or rule.publisher_id != publication.publisher_id
        or rule.competition_id != publication.competition_id
        or rule.publication_type != publication.publication_type
        or publication.claim_scope_id != scope.scope_id
        or parsed.scheme != "https"
        or parsed.hostname != rule.host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.path.startswith(rule.path_prefix)
        or (
            rule.path_pattern is not None
            and re.fullmatch(rule.path_pattern, unquote(parsed.path).casefold()) is None
        )
    ):
        return None
    return rule


def _required_layers(policy: OperatorAttestationPolicySnapshot, league_key: str) -> tuple[str, ...]:
    for league, layers in policy.required_layer_ids:
        if league == league_key:
            return layers
    raise ValueError(f"Operator Attestation Policy has no rules for {league_key}.")


def _candidate_count(entries: tuple[CandidateManifestEntry, ...]) -> int:
    resolved_ids = {
        item.canonical_fixture_id
        for item in entries
        if item.identity_state is FixtureIdentityState.RESOLVED
        and item.canonical_fixture_id is not None
    }
    unresolved_count = sum(
        item.identity_state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY for item in entries
    )
    return len(resolved_ids) + unresolved_count


def _revision_fact_digest(value: CandidateRevisionFact) -> str:
    payload = {
        "fixture_status": value.fixture_status,
        "kickoff_local_text": value.kickoff_local_text,
        "kickoff_precision": value.kickoff_precision,
        "kickoff_state": value.kickoff_state,
        "kickoff_utc": value.kickoff_utc,
        "source_round": value.source_round,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _latest_attempt_retrieval(base_assessment: FixtureCoverageAssessment) -> str:
    if not base_assessment.provider_attempts:
        raise ValueError("The exact automatic base assessment has no Provider Attempt timestamp.")
    return max(item.retrieved_at_utc for item in base_assessment.provider_attempts)


def _require_v2_base(value: object) -> FixtureCoverageAssessment:
    if (
        type(value) is not FixtureCoverageAssessment
        or value.contract_version != "fixture-coverage-v2-v2"
        or type(value.schema_version) is not int
        or value.schema_version != 2
    ):
        raise ValueError(
            "Operator attestation requires an explicitly supplied automatic F01 v2 base."
        )
    return value


def _scope_for_id(base: FixtureCoverageAssessment, scope_id: str) -> FixtureScope:
    matching = tuple(
        item.scope for item in base.scope_assessments if item.scope.scope_id == scope_id
    )
    if len(matching) != 1:
        raise ValueError("Exact Fixture Scope is not present once in the v2 base assessment.")
    return matching[0]


def _attestation_id(base_digest: str, scope_id: str, operator_id: str, verified_at: str) -> str:
    seed = "\0".join((base_digest, scope_id, operator_id, verified_at)).encode("utf-8")
    return f"attestation-{hashlib.sha256(seed).hexdigest()}"


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Operator timestamps must be canonical UTC values.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Operator timestamps must include UTC offset.")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    if canonical != value:
        raise ValueError("Operator timestamps must be canonical UTC values.")
    return canonical


def _source_utc(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Source assertion timestamps must contain valid UTC values.") from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("Source assertion timestamps must include a UTC offset.")


def _non_empty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty.")


def _require_sorted_unique(values: tuple[str, ...], label: str) -> None:
    for value in values:
        _non_empty(value, label)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be sorted and unique.")


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Unsupported LF02 canonical value: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _model_digest(value: object) -> str:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("Digest input must be a dataclass value.")
    payload = {
        item.name: _json_value(getattr(value, item.name))
        for item in fields(value)
        if item.name != "digest"
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _canonical_root(encoded: str) -> Mapping[str, object]:
    raw = json.loads(encoded)
    if not isinstance(raw, dict):
        raise FixtureCoveragePayloadError("Canonical LF02 payload root must be an object.")
    if _canonical_json(raw) != encoded:
        raise FixtureCoveragePayloadError("LF02 payload is not canonical JSON.")
    return cast(Mapping[str, object], raw)


def _object(value: object, keys: tuple[str, ...], label: str) -> Mapping[str, object]:
    try:
        return _payload_object(value, keys, label)
    except FixtureCoveragePayloadError:
        raise


def _scope_from_json(value: object) -> FixtureScope:
    root = _object(value, ("league_key", "season", "matchweek_friday"), "Fixture Scope")
    return FixtureScope(
        league_key=_payload_string(root["league_key"], "league_key"),
        season=_payload_string(root["season"], "season"),
        matchweek_friday=_payload_string(root["matchweek_friday"], "matchweek_friday"),
    )


def _bounds_from_json(value: object) -> CoverageBounds:
    root = _object(value, ("start_utc", "end_utc"), "Coverage Bounds")
    return CoverageBounds(
        start_utc=_payload_string(root["start_utc"], "start_utc"),
        end_utc=_payload_string(root["end_utc"], "end_utc"),
    )


def _assertion_fact_from_json(value: object) -> CandidateAssertionFact:
    keys = (
        "assertion_id",
        "capture_id",
        "capture_digest",
        "origin_id",
        "source_row_key",
        "subject_kind",
        "subject_key",
        "evidence_type",
        "predicate",
        "raw_field_name",
        "evidence_state",
        "raw_value_json",
        "normalized_value_json",
        "unknown_reason",
        "event_time_utc",
        "effective_time_utc",
        "created_at_utc",
        "digest",
    )
    root = _object(value, keys, "Candidate Assertion Fact")
    return CandidateAssertionFact(
        assertion_id=_payload_string(root["assertion_id"], "assertion_id"),
        capture_id=_payload_string(root["capture_id"], "capture_id"),
        capture_digest=_payload_string(root["capture_digest"], "capture_digest"),
        origin_id=_payload_optional_string(root["origin_id"], "origin_id"),
        source_row_key=_payload_string(root["source_row_key"], "source_row_key"),
        subject_kind=_payload_string(root["subject_kind"], "subject_kind"),
        subject_key=_payload_string(root["subject_key"], "subject_key"),
        evidence_type=_payload_string(root["evidence_type"], "evidence_type"),
        predicate=_payload_string(root["predicate"], "predicate"),
        raw_field_name=_payload_string(root["raw_field_name"], "raw_field_name"),
        evidence_state=_payload_string(root["evidence_state"], "evidence_state"),
        raw_value_json=_payload_optional_string(root["raw_value_json"], "raw_value_json"),
        normalized_value_json=_payload_optional_string(
            root["normalized_value_json"], "normalized_value_json"
        ),
        unknown_reason=_payload_optional_string(root["unknown_reason"], "unknown_reason"),
        event_time_utc=_payload_optional_string(root["event_time_utc"], "event_time_utc"),
        effective_time_utc=_payload_optional_string(
            root["effective_time_utc"], "effective_time_utc"
        ),
        created_at_utc=_payload_string(root["created_at_utc"], "created_at_utc"),
        digest=_payload_string(root["digest"], "digest"),
    )


def _revision_fact_from_json(value: object) -> CandidateRevisionFact:
    keys = (
        "reference",
        "home_team_id",
        "away_team_id",
        "kickoff_state",
        "kickoff_utc",
        "kickoff_local_text",
        "kickoff_precision",
        "fixture_status",
        "source_round",
        "observed_at_utc",
    )
    root = _object(value, keys, "Candidate Revision Fact")
    return CandidateRevisionFact(
        reference=_revision_reference_from_json(root["reference"]),
        home_team_id=_payload_string(root["home_team_id"], "home_team_id"),
        away_team_id=_payload_string(root["away_team_id"], "away_team_id"),
        kickoff_state=_payload_string(root["kickoff_state"], "kickoff_state"),
        kickoff_utc=_payload_optional_string(root["kickoff_utc"], "kickoff_utc"),
        kickoff_local_text=_payload_optional_string(
            root["kickoff_local_text"], "kickoff_local_text"
        ),
        kickoff_precision=_payload_string(root["kickoff_precision"], "kickoff_precision"),
        fixture_status=_payload_string(root["fixture_status"], "fixture_status"),
        source_round=_payload_optional_string(root["source_round"], "source_round"),
        observed_at_utc=_payload_string(root["observed_at_utc"], "observed_at_utc"),
    )


def _manifest_entry_from_json(
    value: object, *, version2: bool = False
) -> CandidateManifestEntryValue:
    keys: tuple[str, ...] = (
        "candidate_id",
        "scope_id",
        "identity_state",
        "canonical_fixture_id",
        "revision_facts",
        "assertion_facts",
        "source_capture_ids",
        "source_assertion_ids",
        "reason_code",
        "has_schedule_conflict",
        "has_provisional_scheduling",
    )
    if version2:
        keys = (*keys, "schedule_relation")
    root = _object(value, keys, "Candidate Manifest Entry")
    common: _ManifestEntryArgs = {
        "candidate_id": _payload_string(root["candidate_id"], "candidate_id"),
        "scope_id": _payload_string(root["scope_id"], "scope_id"),
        "identity_state": FixtureIdentityState(
            _payload_string(root["identity_state"], "identity_state")
        ),
        "canonical_fixture_id": _payload_optional_string(
            root["canonical_fixture_id"], "canonical_fixture_id"
        ),
        "revision_facts": tuple(
            _revision_fact_from_json(item)
            for item in _payload_list(root["revision_facts"], "revision_facts")
        ),
        "assertion_facts": tuple(
            _assertion_fact_from_json(item)
            for item in _payload_list(root["assertion_facts"], "assertion_facts")
        ),
        "source_capture_ids": tuple(
            _payload_string(item, "source_capture_id")
            for item in _payload_list(root["source_capture_ids"], "source_capture_ids")
        ),
        "source_assertion_ids": tuple(
            _payload_string(item, "source_assertion_id")
            for item in _payload_list(root["source_assertion_ids"], "source_assertion_ids")
        ),
        "reason_code": _payload_optional_string(root["reason_code"], "reason_code"),
        "has_schedule_conflict": _payload_bool(
            root["has_schedule_conflict"], "has_schedule_conflict"
        ),
        "has_provisional_scheduling": _payload_bool(
            root["has_provisional_scheduling"], "has_provisional_scheduling"
        ),
    }
    if version2:
        return CandidateManifestEntryV2(
            **common,
            schedule_relation=ScheduleRelation(
                _payload_string(root["schedule_relation"], "schedule_relation")
            ),
        )
    return CandidateManifestEntry(**common)


def _manifest_from_json(value: object) -> CandidateManifestValue:
    keys = (
        "contract_version",
        "schema_version",
        "base_assessment_digest",
        "scope",
        "bounds",
        "entries",
        "candidate_count",
        "digest",
    )
    root = _object(value, keys, "Candidate Manifest")
    contract_version = _payload_string(root["contract_version"], "contract_version")
    schema_version = _payload_int(root["schema_version"], "schema_version")
    common: _ManifestArgs = {
        "contract_version": contract_version,
        "schema_version": schema_version,
        "base_assessment_digest": _payload_string(
            root["base_assessment_digest"], "base_assessment_digest"
        ),
        "scope": _scope_from_json(root["scope"]),
        "bounds": _bounds_from_json(root["bounds"]),
        "candidate_count": _payload_int(root["candidate_count"], "candidate_count"),
        "digest": _payload_string(root["digest"], "digest"),
    }
    version2 = (
        contract_version == OPERATOR_CANDIDATE_MANIFEST_V2_CONTRACT_VERSION
        and schema_version == OPERATOR_CANDIDATE_MANIFEST_V2_SCHEMA_VERSION
    )
    if version2:
        entries_v2 = tuple(
            cast(
                CandidateManifestEntryV2,
                _manifest_entry_from_json(item, version2=True),
            )
            for item in _payload_list(root["entries"], "entries")
        )
        return CandidateManifestV2(**common, entries=entries_v2)
    entries_v1 = tuple(
        _manifest_entry_from_json(item) for item in _payload_list(root["entries"], "entries")
    )
    return CandidateManifest(**common, entries=entries_v1)


def _policy_rule_from_json(value: object) -> OperatorPublicationRule:
    keys = (
        "publication_id",
        "league_key",
        "publisher_id",
        "publisher_name",
        "competition_id",
        "publication_type",
        "host",
        "path_prefix",
        "example_url",
        "supported_layers",
        "path_pattern",
    )
    root = _object(value, keys, "Operator Publication Rule")
    return OperatorPublicationRule(
        publication_id=_payload_string(root["publication_id"], "publication_id"),
        league_key=_payload_string(root["league_key"], "league_key"),
        publisher_id=_payload_string(root["publisher_id"], "publisher_id"),
        publisher_name=_payload_string(root["publisher_name"], "publisher_name"),
        competition_id=_payload_string(root["competition_id"], "competition_id"),
        publication_type=_payload_string(root["publication_type"], "publication_type"),
        host=_payload_string(root["host"], "host"),
        path_prefix=_payload_string(root["path_prefix"], "path_prefix"),
        example_url=_payload_string(root["example_url"], "example_url"),
        supported_layers=tuple(
            _payload_string(item, "supported_layer")
            for item in _payload_list(root["supported_layers"], "supported_layers")
        ),
        path_pattern=_payload_optional_string(root["path_pattern"], "path_pattern"),
    )


def _policy_snapshot_from_json(value: object) -> OperatorAttestationPolicySnapshot:
    keys = (
        "policy_id",
        "policy_version",
        "publication_rules",
        "required_layer_ids",
        "required_confirmations",
        "digest",
    )
    root = _object(value, keys, "Operator Attestation Policy Snapshot")
    layer_rows = []
    for item in _payload_list(root["required_layer_ids"], "required_layer_ids"):
        row = _payload_list(item, "required_layer")
        if len(row) != 2:
            raise FixtureCoveragePayloadError("Operator Attestation Policy layer row is malformed.")
        layer_rows.append(
            (
                _payload_string(row[0], "league_key"),
                tuple(
                    _payload_string(layer, "layer_id")
                    for layer in _payload_list(row[1], "layer_ids")
                ),
            )
        )
    return OperatorAttestationPolicySnapshot(
        policy_id=_payload_string(root["policy_id"], "policy_id"),
        policy_version=_payload_string(root["policy_version"], "policy_version"),
        publication_rules=tuple(
            _policy_rule_from_json(item)
            for item in _payload_list(root["publication_rules"], "publication_rules")
        ),
        required_layer_ids=tuple(layer_rows),
        required_confirmations=tuple(
            _payload_string(item, "required_confirmation")
            for item in _payload_list(root["required_confirmations"], "required_confirmations")
        ),
        digest=_payload_string(root["digest"], "digest"),
    )


def _publication_from_json(value: object) -> OfficialPublicationReference:
    keys = (
        "publication_id",
        "publisher_id",
        "competition_id",
        "official_url",
        "title_or_publication_id",
        "publication_date",
        "publication_type",
        "claim_scope_id",
        "covers_exact_scope",
        "complete_for_scope",
    )
    root = _object(value, keys, "Official Publication Reference")
    return OfficialPublicationReference(
        publication_id=_payload_string(root["publication_id"], "publication_id"),
        publisher_id=_payload_string(root["publisher_id"], "publisher_id"),
        competition_id=_payload_string(root["competition_id"], "competition_id"),
        official_url=_payload_string(root["official_url"], "official_url"),
        title_or_publication_id=_payload_string(
            root["title_or_publication_id"], "title_or_publication_id"
        ),
        publication_date=_payload_optional_string(root["publication_date"], "publication_date"),
        publication_type=_payload_string(root["publication_type"], "publication_type"),
        claim_scope_id=_payload_string(root["claim_scope_id"], "claim_scope_id"),
        covers_exact_scope=_payload_bool(root["covers_exact_scope"], "covers_exact_scope"),
        complete_for_scope=_payload_bool(root["complete_for_scope"], "complete_for_scope"),
    )


def _candidate_confirmation_from_json(value: object) -> CandidateComparisonConfirmation:
    keys = ("candidate_id", "identity_matches", "date_matches", "kickoff_matches", "status_matches")
    root = _object(value, keys, "Candidate Comparison Confirmation")
    return CandidateComparisonConfirmation(
        candidate_id=_payload_string(root["candidate_id"], "candidate_id"),
        identity_matches=_payload_bool(root["identity_matches"], "identity_matches"),
        date_matches=_payload_bool(root["date_matches"], "date_matches"),
        kickoff_matches=_payload_bool(root["kickoff_matches"], "kickoff_matches"),
        status_matches=_payload_bool(root["status_matches"], "status_matches"),
    )


def _comparison_from_json(value: object) -> OperatorComparisonConfirmations:
    keys = tuple(item.name for item in fields(OperatorComparisonConfirmations))
    root = _object(value, keys, "Operator Comparison Confirmations")
    return OperatorComparisonConfirmations(**{key: _payload_bool(root[key], key) for key in keys})


def _operator_attestation_from_json(value: object) -> OperatorCoverageAttestation:
    keys = (
        "contract_version",
        "schema_version",
        "attestation_id",
        "base_assessment_digest",
        "scope",
        "bounds",
        "candidate_manifest",
        "candidate_manifest_digest",
        "observed_candidate_count",
        "operator_id",
        "verified_at_utc",
        "policy_snapshot",
        "policy_digest",
        "publications",
        "expected_official_fixture_count",
        "candidate_confirmations",
        "confirmations",
        "outcome",
        "reason",
        "digest",
    )
    root = _object(value, keys, "Operator Coverage Attestation")
    expected_count_value = root["expected_official_fixture_count"]
    expected_count = (
        None
        if expected_count_value is None
        else _payload_int(expected_count_value, "expected_official_fixture_count")
    )
    return OperatorCoverageAttestation(
        contract_version=_payload_string(root["contract_version"], "contract_version"),
        schema_version=_payload_int(root["schema_version"], "schema_version"),
        attestation_id=_payload_string(root["attestation_id"], "attestation_id"),
        base_assessment_digest=_payload_string(
            root["base_assessment_digest"], "base_assessment_digest"
        ),
        scope=_scope_from_json(root["scope"]),
        bounds=_bounds_from_json(root["bounds"]),
        candidate_manifest=_manifest_from_json(root["candidate_manifest"]),
        candidate_manifest_digest=_payload_string(
            root["candidate_manifest_digest"], "candidate_manifest_digest"
        ),
        observed_candidate_count=_payload_int(
            root["observed_candidate_count"], "observed_candidate_count"
        ),
        operator_id=_payload_string(root["operator_id"], "operator_id"),
        verified_at_utc=_payload_string(root["verified_at_utc"], "verified_at_utc"),
        policy_snapshot=_policy_snapshot_from_json(root["policy_snapshot"]),
        policy_digest=_payload_string(root["policy_digest"], "policy_digest"),
        publications=tuple(
            _publication_from_json(item)
            for item in _payload_list(root["publications"], "publications")
        ),
        expected_official_fixture_count=expected_count,
        candidate_confirmations=tuple(
            _candidate_confirmation_from_json(item)
            for item in _payload_list(root["candidate_confirmations"], "candidate_confirmations")
        ),
        confirmations=_comparison_from_json(root["confirmations"]),
        outcome=OperatorAttestationOutcome(_payload_string(root["outcome"], "outcome")),
        reason=_payload_string(root["reason"], "reason"),
        digest=_payload_string(root["digest"], "digest"),
    )


def _artifact_reference_from_json(value: object) -> AttestationArtifactReference:
    root = _object(value, ("attestation", "artifact_digest"), "Attestation Artifact Reference")
    return AttestationArtifactReference(
        attestation=_operator_attestation_from_json(root["attestation"]),
        artifact_digest=_payload_string(root["artifact_digest"], "artifact_digest"),
    )


def _freshness_from_json(value: object) -> OperatorAttestationFreshnessResult:
    keys = (
        "contract_version",
        "schema_version",
        "base_assessment_digest",
        "scope",
        "bounds",
        "candidate_manifest_digest",
        "policy_digest",
        "attestation_id",
        "attestation_digest",
        "latest_base_attempt_retrieved_at_utc",
        "verification_event_utc",
        "is_valid_for_event",
    )
    root = _object(value, keys, "Operator Attestation Freshness Result")
    return OperatorAttestationFreshnessResult(
        contract_version=_payload_string(root["contract_version"], "contract_version"),
        schema_version=_payload_int(root["schema_version"], "schema_version"),
        base_assessment_digest=_payload_string(
            root["base_assessment_digest"], "base_assessment_digest"
        ),
        scope=_scope_from_json(root["scope"]),
        bounds=_bounds_from_json(root["bounds"]),
        candidate_manifest_digest=_payload_string(
            root["candidate_manifest_digest"], "candidate_manifest_digest"
        ),
        policy_digest=_payload_string(root["policy_digest"], "policy_digest"),
        attestation_id=_payload_string(root["attestation_id"], "attestation_id"),
        attestation_digest=_payload_string(root["attestation_digest"], "attestation_digest"),
        latest_base_attempt_retrieved_at_utc=_payload_string(
            root["latest_base_attempt_retrieved_at_utc"], "latest_base_attempt_retrieved_at_utc"
        ),
        verification_event_utc=_payload_string(
            root["verification_event_utc"], "verification_event_utc"
        ),
        is_valid_for_event=_payload_bool(root["is_valid_for_event"], "is_valid_for_event"),
    )


def _operator_state_from_json(value: object) -> OperatorAttestationState:
    root = _object(
        value,
        ("base_assessment_digest", "evidence", "freshness_results"),
        "Operator Attestation State",
    )
    return OperatorAttestationState(
        base_assessment_digest=_payload_string(
            root["base_assessment_digest"], "base_assessment_digest"
        ),
        evidence=tuple(
            _artifact_reference_from_json(item)
            for item in _payload_list(root["evidence"], "evidence")
        ),
        freshness_results=tuple(
            _freshness_from_json(item)
            for item in _payload_list(root["freshness_results"], "freshness_results")
        ),
    )

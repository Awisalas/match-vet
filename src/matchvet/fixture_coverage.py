"""Pure V2 fixture coverage contract, kept separate from V1 ingestion and freeze records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum

from matchvet.ingestion import TARGET_LEAGUES
from matchvet.matchweek import MatchweekWindow

_TARGET_LEAGUE_KEYS = tuple(league.key for league in TARGET_LEAGUES)
FIXTURE_COVERAGE_CONTRACT_VERSION = "fixture-coverage-v2-v1"
FIXTURE_COVERAGE_SCHEMA_VERSION = 1


class ProviderAttemptState(StrEnum):
    CAPTURED = "CAPTURED"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED = "MALFORMED"


class CoverageBasisKind(StrEnum):
    VERSIONED_SOURCE_CONTRACT = "VERSIONED_SOURCE_CONTRACT"
    EXPLICIT_PROVIDER_METADATA = "EXPLICIT_PROVIDER_METADATA"


@dataclass(frozen=True)
class CoverageBasis:
    """Identifies source semantics that establish the meaning of a coverage claim."""

    kind: CoverageBasisKind
    reference_id: str
    version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CoverageBasisKind):
            raise ValueError("Coverage Basis kind must identify a source contract or metadata.")
        _non_empty(self.reference_id, "Coverage Basis reference_id")
        if self.kind is CoverageBasisKind.VERSIONED_SOURCE_CONTRACT:
            if self.version is None:
                raise ValueError("A versioned source contract Coverage Basis requires its version.")
            _non_empty(self.version, "Coverage Basis version")
        elif self.version is not None:
            _non_empty(self.version, "Coverage Basis version")


class ScopeCoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    CONFIRMED_EMPTY = "CONFIRMED_EMPTY"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class FixtureIdentityState(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED_FIXTURE_IDENTITY = "UNRESOLVED_FIXTURE_IDENTITY"


class MatchweekScheduleState(StrEnum):
    COMPLETE = "COMPLETE"
    CONFIRMED_EMPTY = "CONFIRMED_EMPTY"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


def _non_empty(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty.")


def _sorted_unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    for value in values:
        _non_empty(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique.")
    return tuple(sorted(values))


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Timestamps must be canonical UTC values.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamps must include a UTC offset.")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    if canonical != value:
        raise ValueError("Timestamps must be canonical UTC values.")
    return canonical


@dataclass(frozen=True)
class CoverageBounds:
    """A source-backed half-open UTC date range covered by one capture."""

    start_utc: str
    end_utc: str

    def __post_init__(self) -> None:
        start = _canonical_utc(self.start_utc)
        end = _canonical_utc(self.end_utc)
        if start >= end:
            raise ValueError("Coverage Bounds must have an end after their start.")


@dataclass(frozen=True)
class ProviderAttempt:
    """One source attempt; its outcome is independent of the transport status."""

    attempt_id: str
    scope_id: str
    provider_id: str
    capability_id: str
    state: ProviderAttemptState
    retrieved_at_utc: str
    http_status: int | None = None
    capture_id: str | None = None
    capture_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("attempt_id", "scope_id", "provider_id", "capability_id"):
            _non_empty(getattr(self, name), f"Provider Attempt {name}")
        if not isinstance(self.state, ProviderAttemptState):
            raise ValueError("Provider Attempt state must be a V2 Provider Attempt State.")
        _canonical_utc(self.retrieved_at_utc)
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("Provider Attempt HTTP status must be between 100 and 599.")
        if (self.capture_id is None) != (self.capture_digest is None):
            raise ValueError("A Provider Attempt capture requires both ID and digest.")
        if self.state is ProviderAttemptState.CAPTURED and self.capture_id is None:
            raise ValueError("A CAPTURED Provider Attempt requires its capture ID and digest.")
        if self.state is ProviderAttemptState.UNAVAILABLE and self.capture_id is not None:
            raise ValueError("An UNAVAILABLE Provider Attempt cannot reference a capture.")


@dataclass(frozen=True)
class ProviderCoverageEvidence:
    """Coverage claim attached to one captured provider attempt."""

    evidence_id: str
    attempt_id: str
    scope_id: str
    provider_competition_key: str
    provider_season: str
    capture_id: str
    capture_digest: str
    coverage_basis: CoverageBasis | None
    bounds: CoverageBounds | None
    provider_use_policy_id: str | None = None
    permitted_for_use: bool = False
    required_partition_ids: tuple[str, ...] = ()
    accounted_partition_ids: tuple[str, ...] = ()
    pagination_exhausted: bool = False
    affirmatively_empty: bool = False

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "attempt_id",
            "scope_id",
            "provider_competition_key",
            "provider_season",
            "capture_id",
            "capture_digest",
        ):
            _non_empty(getattr(self, name), f"Provider Coverage Evidence {name}")
        if self.provider_use_policy_id is not None:
            _non_empty(
                self.provider_use_policy_id, "Provider Coverage Evidence provider_use_policy_id"
            )
        if self.permitted_for_use and self.provider_use_policy_id is None:
            raise ValueError("Permitted Provider Coverage Evidence requires its use policy ID.")
        if self.coverage_basis is not None and not isinstance(self.coverage_basis, CoverageBasis):
            raise ValueError("Provider Coverage Evidence requires a typed Coverage Basis.")
        required = _sorted_unique(self.required_partition_ids, "Required partition IDs")
        accounted = _sorted_unique(self.accounted_partition_ids, "Accounted partition IDs")
        if not set(accounted).issubset(required):
            raise ValueError("Accounted partition IDs must be declared as required partitions.")
        object.__setattr__(self, "required_partition_ids", required)
        object.__setattr__(self, "accounted_partition_ids", accounted)


@dataclass(frozen=True)
class FixtureRevisionReference:
    """Read-only V1 revision identity and provenance retained by a V2 assessment."""

    scope_id: str
    fixture_id: str
    revision_id: str
    revision_digest: str
    source_capture_ids: tuple[str, ...]
    source_assertion_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("scope_id", "fixture_id", "revision_id", "revision_digest"):
            _non_empty(getattr(self, name), f"Fixture Revision Reference {name}")
        object.__setattr__(
            self,
            "source_capture_ids",
            _sorted_unique(self.source_capture_ids, "Fixture Revision source capture IDs"),
        )
        object.__setattr__(
            self,
            "source_assertion_ids",
            _sorted_unique(self.source_assertion_ids, "Fixture Revision source assertion IDs"),
        )
        if not self.source_capture_ids or not self.source_assertion_ids:
            raise ValueError("Fixture Revision References must retain source provenance.")


@dataclass(frozen=True)
class FixtureIdentityResolution:
    """Identity result for one source candidate, including unresolved blockers."""

    candidate_id: str
    scope_id: str
    state: FixtureIdentityState
    canonical_fixture_id: str | None = None
    revision_ids: tuple[str, ...] = ()
    reason_code: str | None = None
    source_capture_ids: tuple[str, ...] = ()
    source_assertion_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.candidate_id, "Fixture Identity Resolution candidate_id")
        _non_empty(self.scope_id, "Fixture Identity Resolution scope_id")
        if not isinstance(self.state, FixtureIdentityState):
            raise ValueError(
                "Fixture Identity Resolution state must be a V2 Fixture Identity State."
            )
        object.__setattr__(self, "revision_ids", _sorted_unique(self.revision_ids, "Revision IDs"))
        object.__setattr__(
            self,
            "source_capture_ids",
            _sorted_unique(self.source_capture_ids, "Identity source capture IDs"),
        )
        object.__setattr__(
            self,
            "source_assertion_ids",
            _sorted_unique(self.source_assertion_ids, "Identity source assertion IDs"),
        )
        if self.state is FixtureIdentityState.RESOLVED:
            if self.canonical_fixture_id is None:
                raise ValueError("A RESOLVED identity requires a canonical Fixture ID.")
            _non_empty(self.canonical_fixture_id, "Canonical Fixture ID")
            if not self.revision_ids:
                raise ValueError("A RESOLVED identity requires at least one Fixture Revision.")
            if self.reason_code is not None:
                raise ValueError("A RESOLVED identity cannot have an unresolved reason code.")
        else:
            if self.canonical_fixture_id is not None:
                raise ValueError("An unresolved identity cannot claim a canonical Fixture ID.")
            if self.reason_code is None:
                raise ValueError("An unresolved identity requires a blocker reason code.")
            _non_empty(self.reason_code, "Unresolved identity reason code")
            if not self.source_assertion_ids and not self.revision_ids:
                raise ValueError(
                    "An unresolved identity must retain source or revision references."
                )


@dataclass(frozen=True)
class CoverageFreshnessResult:
    """Result from an externally supplied, versioned freshness policy."""

    evidence_id: str
    policy_id: str
    evaluated_at_utc: str
    is_current: bool

    def __post_init__(self) -> None:
        _non_empty(self.evidence_id, "Coverage Freshness Result evidence_id")
        _non_empty(self.policy_id, "Coverage Freshness Result policy_id")
        _canonical_utc(self.evaluated_at_utc)


@dataclass(frozen=True)
class FixtureScopeAssessment:
    scope: FixtureScope
    coverage_state: ScopeCoverageState
    provider_attempt_ids: tuple[str, ...]
    coverage_evidence_ids: tuple[str, ...]
    fixture_revisions: tuple[FixtureRevisionReference, ...]
    identity_blocker_candidate_ids: tuple[str, ...]
    freshness_results: tuple[CoverageFreshnessResult, ...]
    current_coverage_evidence_ids: tuple[str, ...]
    stale_coverage_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FixtureCoverageAssessment:
    contract_version: str
    schema_version: int
    scope_assessments: tuple[FixtureScopeAssessment, ...]
    provider_attempts: tuple[ProviderAttempt, ...]
    coverage_evidence: tuple[ProviderCoverageEvidence, ...]
    fixture_revisions: tuple[FixtureRevisionReference, ...]
    identity_resolutions: tuple[FixtureIdentityResolution, ...]
    freshness_results: tuple[CoverageFreshnessResult, ...]
    schedule_state: MatchweekScheduleState
    digest: str = ""

    def __post_init__(self) -> None:
        expected = _assessment_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Fixture Coverage Assessment digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class FixtureScope:
    """One configured league, season, and Friday-through-Monday Matchweek window."""

    league_key: str
    season: str
    matchweek_friday: str

    def __post_init__(self) -> None:
        if self.league_key not in _TARGET_LEAGUE_KEYS:
            raise ValueError(f"Unknown configured Target League: {self.league_key}")
        if not self.season.strip():
            raise ValueError("Fixture Scope season must not be empty.")
        window = MatchweekWindow.for_friday(self.matchweek_friday)
        if window.friday_local.isoformat() != self.matchweek_friday:
            raise ValueError("Fixture Scope Matchweek Friday must use YYYY-MM-DD.")

    @property
    def scope_id(self) -> str:
        return f"{self.league_key}:{self.season}:{self.matchweek_friday}"

    @property
    def window_start_utc(self) -> str:
        return MatchweekWindow.for_friday(self.matchweek_friday).start_utc

    @property
    def window_end_utc(self) -> str:
        return MatchweekWindow.for_friday(self.matchweek_friday).end_utc


def fixture_scopes_for_matchweek(friday: str, *, season: str) -> tuple[FixtureScope, ...]:
    """Create V2 scopes for the existing fixed seven-league Matchweek."""
    window = MatchweekWindow.for_friday(friday)
    canonical_friday = window.friday_local.isoformat()
    return tuple(
        FixtureScope(league_key=league_key, season=season, matchweek_friday=canonical_friday)
        for league_key in _TARGET_LEAGUE_KEYS
    )


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Unsupported assessment digest value: {type(value).__name__}")


def _assessment_digest(assessment: FixtureCoverageAssessment) -> str:
    payload = {
        item.name: _json_value(getattr(assessment, item.name))
        for item in fields(assessment)
        if item.name != "digest"
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _full_partitions_accounted(evidence: ProviderCoverageEvidence) -> bool:
    return (
        evidence.pagination_exhausted
        and evidence.required_partition_ids == evidence.accounted_partition_ids
    )


def _intersected_bounds(
    scope: FixtureScope, bounds: CoverageBounds
) -> tuple[datetime, datetime] | None:
    scope_start = datetime.fromisoformat(scope.window_start_utc)
    scope_end = datetime.fromisoformat(scope.window_end_utc)
    claim_start = datetime.fromisoformat(bounds.start_utc)
    claim_end = datetime.fromisoformat(bounds.end_utc)
    start = max(scope_start, claim_start)
    end = min(scope_end, claim_end)
    if start >= end:
        return None
    return start, end


def _covers_window(scope: FixtureScope, ranges: list[tuple[datetime, datetime]]) -> bool:
    cursor = datetime.fromisoformat(scope.window_start_utc)
    end = datetime.fromisoformat(scope.window_end_utc)
    for start, range_end in sorted(ranges):
        if range_end <= cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, range_end)
        if cursor >= end:
            return True
    return False


def assess_fixture_coverage(
    *,
    scopes: tuple[FixtureScope, ...],
    provider_attempts: tuple[ProviderAttempt, ...],
    coverage_evidence: tuple[ProviderCoverageEvidence, ...],
    fixture_revisions: tuple[FixtureRevisionReference, ...],
    identity_resolutions: tuple[FixtureIdentityResolution, ...],
    freshness_results: tuple[CoverageFreshnessResult, ...],
) -> FixtureCoverageAssessment:
    """Assess all seven scopes, treating an omitted requested scope as unknown."""
    if not scopes:
        raise ValueError("Fixture Coverage Assessment requires at least one Fixture Scope.")
    provided_league_keys = tuple(scope.league_key for scope in scopes)
    if len(provided_league_keys) != len(set(provided_league_keys)):
        raise ValueError("Fixture Coverage Assessment cannot repeat a Target League scope.")
    first_scope = scopes[0]
    if any(
        scope.season != first_scope.season or scope.matchweek_friday != first_scope.matchweek_friday
        for scope in scopes
    ):
        raise ValueError("Fixture Coverage Assessment scopes must share season and Matchweek.")
    ordered_scopes = fixture_scopes_for_matchweek(
        first_scope.matchweek_friday, season=first_scope.season
    )
    scope_by_id = {scope.scope_id: scope for scope in ordered_scopes}

    attempts_by_id: dict[str, ProviderAttempt] = {}
    captured_source_ids_by_scope: dict[str, set[str]] = {
        scope.scope_id: set() for scope in ordered_scopes
    }
    for attempt in provider_attempts:
        if attempt.attempt_id in attempts_by_id:
            raise ValueError("Provider Attempt IDs must be unique within an assessment.")
        if attempt.scope_id not in scope_by_id:
            raise ValueError("Provider Attempt references a scope outside the assessment.")
        attempts_by_id[attempt.attempt_id] = attempt
        if attempt.state is ProviderAttemptState.CAPTURED and attempt.capture_id is not None:
            captured_source_ids_by_scope[attempt.scope_id].add(attempt.capture_id)

    evidence_by_id: dict[str, ProviderCoverageEvidence] = {}
    for evidence in coverage_evidence:
        if evidence.evidence_id in evidence_by_id:
            raise ValueError("Provider Coverage Evidence IDs must be unique.")
        referenced_attempt = attempts_by_id.get(evidence.attempt_id)
        if referenced_attempt is None or referenced_attempt.scope_id != evidence.scope_id:
            raise ValueError(
                "Provider Coverage Evidence must reference its scope's Provider Attempt."
            )
        if evidence.scope_id not in scope_by_id:
            raise ValueError(
                "Provider Coverage Evidence references a scope outside the assessment."
            )
        evidence_by_id[evidence.evidence_id] = evidence

    revisions_by_id: dict[str, FixtureRevisionReference] = {}
    for revision in fixture_revisions:
        if revision.revision_id in revisions_by_id:
            raise ValueError("Fixture Revision IDs must be unique within an assessment.")
        if revision.scope_id not in scope_by_id:
            raise ValueError("Fixture Revision references a scope outside the assessment.")
        if not set(revision.source_capture_ids).issubset(
            captured_source_ids_by_scope[revision.scope_id]
        ):
            raise ValueError(
                "Fixture Revision source capture IDs must reference captured Provider Attempts "
                "in the same scope."
            )
        revisions_by_id[revision.revision_id] = revision

    candidate_ids: set[str] = set()
    referenced_revision_ids: set[str] = set()
    identities_by_scope: dict[str, list[FixtureIdentityResolution]] = {
        scope.scope_id: [] for scope in ordered_scopes
    }
    for identity in identity_resolutions:
        if identity.candidate_id in candidate_ids:
            raise ValueError("Fixture identity candidate IDs must be unique.")
        candidate_ids.add(identity.candidate_id)
        if identity.scope_id not in scope_by_id:
            raise ValueError(
                "Fixture Identity Resolution references a scope outside the assessment."
            )
        referenced_revisions = []
        for revision_id in identity.revision_ids:
            referenced_revision = revisions_by_id.get(revision_id)
            if referenced_revision is None or referenced_revision.scope_id != identity.scope_id:
                raise ValueError(
                    "Fixture Identity Resolution references an unrelated Fixture Revision."
                )
            referenced_revision_ids.add(revision_id)
            referenced_revisions.append(referenced_revision)
        if identity.state is FixtureIdentityState.RESOLVED and any(
            revision.fixture_id != identity.canonical_fixture_id
            for revision in referenced_revisions
        ):
            raise ValueError("Resolved identity and Fixture Revision IDs must agree.")
        identities_by_scope[identity.scope_id].append(identity)

    if set(revisions_by_id) != referenced_revision_ids:
        raise ValueError("Every Fixture Revision requires an explicit Fixture Identity Resolution.")

    freshness_by_evidence_id: dict[str, CoverageFreshnessResult] = {}
    for freshness in freshness_results:
        if freshness.evidence_id in freshness_by_evidence_id:
            raise ValueError("Each coverage claim has one freshness result per assessment.")
        if freshness.evidence_id not in evidence_by_id:
            raise ValueError("Coverage Freshness Result references unknown evidence.")
        freshness_by_evidence_id[freshness.evidence_id] = freshness

    attempts_by_scope: dict[str, list[ProviderAttempt]] = {
        scope.scope_id: [] for scope in ordered_scopes
    }
    for attempt in provider_attempts:
        attempts_by_scope[attempt.scope_id].append(attempt)
    evidence_by_scope: dict[str, list[ProviderCoverageEvidence]] = {
        scope.scope_id: [] for scope in ordered_scopes
    }
    for evidence in coverage_evidence:
        evidence_by_scope[evidence.scope_id].append(evidence)
    revisions_by_scope: dict[str, list[FixtureRevisionReference]] = {
        scope.scope_id: [] for scope in ordered_scopes
    }
    for revision in fixture_revisions:
        revisions_by_scope[revision.scope_id].append(revision)

    scope_assessments: list[FixtureScopeAssessment] = []
    for scope in ordered_scopes:
        current_evidence_ids: list[str] = []
        stale_evidence_ids: list[str] = []
        current_ranges: list[tuple[datetime, datetime]] = []
        empty_ranges: list[tuple[datetime, datetime]] = []
        for evidence in evidence_by_scope[scope.scope_id]:
            attempt = attempts_by_id[evidence.attempt_id]
            freshness_result = freshness_by_evidence_id.get(evidence.evidence_id)
            if (
                attempt.state is not ProviderAttemptState.CAPTURED
                or attempt.capture_id != evidence.capture_id
                or attempt.capture_digest != evidence.capture_digest
                or not evidence.permitted_for_use
                or evidence.provider_use_policy_id is None
                or evidence.provider_competition_key != scope.league_key
                or evidence.provider_season != scope.season
                or evidence.coverage_basis is None
                or evidence.bounds is None
            ):
                continue
            intersected = _intersected_bounds(scope, evidence.bounds)
            if intersected is None or freshness_result is None:
                continue
            if freshness_result.is_current:
                current_evidence_ids.append(evidence.evidence_id)
                if _full_partitions_accounted(evidence):
                    current_ranges.append(intersected)
                    if evidence.affirmatively_empty:
                        empty_ranges.append(intersected)
            else:
                stale_evidence_ids.append(evidence.evidence_id)

        scoped_identities = identities_by_scope[scope.scope_id]
        unresolved = tuple(
            sorted(
                identity.candidate_id
                for identity in scoped_identities
                if identity.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
            )
        )
        fixture_ids = {
            identity.canonical_fixture_id
            for identity in scoped_identities
            if identity.state is FixtureIdentityState.RESOLVED
        }
        if unresolved and current_evidence_ids:
            state = ScopeCoverageState.PARTIAL
        elif _covers_window(scope, current_ranges) and fixture_ids:
            state = ScopeCoverageState.COMPLETE
        elif (
            _covers_window(scope, current_ranges)
            and not fixture_ids
            and _covers_window(scope, empty_ranges)
        ):
            state = ScopeCoverageState.CONFIRMED_EMPTY
        elif current_evidence_ids:
            state = ScopeCoverageState.PARTIAL
        elif stale_evidence_ids:
            state = ScopeCoverageState.STALE
        else:
            state = ScopeCoverageState.UNKNOWN

        scope_assessments.append(
            FixtureScopeAssessment(
                scope=scope,
                coverage_state=state,
                provider_attempt_ids=tuple(
                    sorted(attempt.attempt_id for attempt in attempts_by_scope[scope.scope_id])
                ),
                coverage_evidence_ids=tuple(
                    sorted(evidence.evidence_id for evidence in evidence_by_scope[scope.scope_id])
                ),
                fixture_revisions=tuple(
                    sorted(revisions_by_scope[scope.scope_id], key=lambda item: item.revision_id)
                ),
                identity_blocker_candidate_ids=unresolved,
                freshness_results=tuple(
                    sorted(
                        (
                            freshness_by_evidence_id[evidence.evidence_id]
                            for evidence in evidence_by_scope[scope.scope_id]
                            if evidence.evidence_id in freshness_by_evidence_id
                        ),
                        key=lambda item: item.evidence_id,
                    )
                ),
                current_coverage_evidence_ids=tuple(sorted(current_evidence_ids)),
                stale_coverage_evidence_ids=tuple(sorted(stale_evidence_ids)),
            )
        )

    complete_states = {ScopeCoverageState.COMPLETE, ScopeCoverageState.CONFIRMED_EMPTY}
    if all(item.coverage_state in complete_states for item in scope_assessments):
        if all(
            item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY for item in scope_assessments
        ):
            schedule_state = MatchweekScheduleState.CONFIRMED_EMPTY
        else:
            schedule_state = MatchweekScheduleState.COMPLETE
    elif any(item.current_coverage_evidence_ids for item in scope_assessments):
        schedule_state = MatchweekScheduleState.PARTIAL
    elif any(item.stale_coverage_evidence_ids for item in scope_assessments):
        schedule_state = MatchweekScheduleState.STALE
    else:
        schedule_state = MatchweekScheduleState.UNKNOWN

    return FixtureCoverageAssessment(
        contract_version=FIXTURE_COVERAGE_CONTRACT_VERSION,
        schema_version=FIXTURE_COVERAGE_SCHEMA_VERSION,
        scope_assessments=tuple(scope_assessments),
        provider_attempts=tuple(
            sorted(provider_attempts, key=lambda item: (item.scope_id, item.attempt_id))
        ),
        coverage_evidence=tuple(
            sorted(coverage_evidence, key=lambda item: (item.scope_id, item.evidence_id))
        ),
        fixture_revisions=tuple(
            sorted(fixture_revisions, key=lambda item: (item.scope_id, item.revision_id))
        ),
        identity_resolutions=tuple(
            sorted(identity_resolutions, key=lambda item: (item.scope_id, item.candidate_id))
        ),
        freshness_results=tuple(sorted(freshness_results, key=lambda item: item.evidence_id)),
        schedule_state=schedule_state,
    )

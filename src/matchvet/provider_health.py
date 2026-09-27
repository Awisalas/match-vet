"""Pure provider health values and their canonical provider-health-v1 encoding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

PROVIDER_HEALTH_CONTRACT_VERSION = "provider-health-v1"
PROVIDER_HEALTH_SCHEMA_VERSION = 1


class ProviderHealthPayloadError(ValueError):
    """A provider health payload is malformed, unsupported, or not canonical."""


def _field(value: object, name: str) -> Any:
    """Read a structural external record without importing its owning module."""
    return getattr(value, name)


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed identifier.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain control characters.")


def _sorted_unique[T](values: tuple[T, ...], key: Callable[[T], str], label: str) -> tuple[T, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be an immutable tuple.")
    if len({key(value) for value in values}) != len(values):
        raise ValueError(f"{label} must not contain duplicate values.")
    return tuple(sorted(values, key=key))


def _canonical_utc(value: str, label: str = "Timestamp") -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a canonical UTC timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset.")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    if canonical != value:
        raise ValueError(f"{label} must use canonical UTC with six fractional digits.")
    return canonical


def _canonical_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must use YYYY-MM-DD.") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use YYYY-MM-DD.")
    return value


class FacetApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CoverageApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScopeFacetState(StrEnum):
    KNOWN = "KNOWN"
    UNBOUNDED = "UNBOUNDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ScopeFacet[T]:
    """One typed query facet with an explicit epistemic or applicability state."""

    state: ScopeFacetState
    value: T | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ScopeFacetState):
            raise ValueError("Scope facet state must be a ScopeFacetState.")
        if self.state is ScopeFacetState.KNOWN and self.value is None:
            raise ValueError("A KNOWN scope facet requires its value.")
        if self.state is not ScopeFacetState.KNOWN and self.value is not None:
            raise ValueError("Only a KNOWN scope facet can carry a value.")

    @classmethod
    def known(cls, value: T) -> ScopeFacet[T]:
        return cls(ScopeFacetState.KNOWN, value)

    @classmethod
    def unbounded(cls) -> ScopeFacet[T]:
        return cls(ScopeFacetState.UNBOUNDED)

    @classmethod
    def not_applicable(cls) -> ScopeFacet[T]:
        return cls(ScopeFacetState.NOT_APPLICABLE)

    @classmethod
    def unknown(cls) -> ScopeFacet[T]:
        return cls(ScopeFacetState.UNKNOWN)


@dataclass(frozen=True, slots=True)
class CompetitionScope:
    competition_id: str
    provider_key: str

    def __post_init__(self) -> None:
        _identifier(self.competition_id, "Competition ID")
        _identifier(self.provider_key, "Provider competition key")


@dataclass(frozen=True, slots=True)
class SeasonScope:
    season_id: str
    provider_value: str

    def __post_init__(self) -> None:
        _identifier(self.season_id, "Season ID")
        _identifier(self.provider_value, "Provider season value")


@dataclass(frozen=True, slots=True)
class UtcInterval:
    """A half-open interval bounded by canonical UTC instants."""

    start_utc: str
    end_utc: str

    def __post_init__(self) -> None:
        start = _canonical_utc(self.start_utc, "UTC interval start")
        end = _canonical_utc(self.end_utc, "UTC interval end")
        if start >= end:
            raise ValueError("UTC intervals must end after they start.")


def _intervals_intersect(first: UtcInterval, second: UtcInterval) -> bool:
    return max(first.start_utc, second.start_utc) < min(first.end_utc, second.end_utc)


def _intervals_cover(requested: UtcInterval, evidence: tuple[UtcInterval, ...]) -> bool:
    cursor = datetime.fromisoformat(requested.start_utc)
    end = datetime.fromisoformat(requested.end_utc)
    intervals = sorted(
        (
            datetime.fromisoformat(value.start_utc),
            datetime.fromisoformat(value.end_utc),
        )
        for value in evidence
    )
    for evidence_start, evidence_end in intervals:
        if evidence_end <= cursor:
            continue
        if evidence_start > cursor:
            return False
        cursor = max(cursor, evidence_end)
        if cursor >= end:
            return True
    return False


@dataclass(frozen=True, slots=True)
class LocalDateRange:
    """A half-open date range retaining an opaque time-zone key for exact scope identity.

    F04 records this key but does not resolve it or convert arbitrary local dates to instants.
    Fixture scopes retain the UTC window computed by their typed F01 scope reference.
    """

    start_date: str
    end_date_exclusive: str
    timezone_name: str

    def __post_init__(self) -> None:
        start = _canonical_date(self.start_date, "Date range start")
        end = _canonical_date(self.end_date_exclusive, "Date range end")
        if start >= end:
            raise ValueError("Date ranges must end after they start.")
        _identifier(self.timezone_name, "Date range time zone")
        components = self.timezone_name.split("/")
        if self.timezone_name != "UTC" and (
            len(components) < 2
            or any(
                component in ("", ".", "..")
                or not component.isascii()
                or not all(character.isalnum() or character in "_+-" for character in component)
                for component in components
            )
        ):
            raise ValueError("Date range time zone must use a stable IANA-style zone key.")


RequestedTimeScope = UtcInterval | LocalDateRange


@dataclass(frozen=True, slots=True)
class F01FixtureScopeReference:
    """Typed projection of the exact F01 league, season, and Matchweek scope."""

    league_key: str
    season: str
    matchweek_friday: str
    scope_id: str
    window_start_utc: str
    window_end_utc: str

    def __post_init__(self) -> None:
        _identifier(self.league_key, "F01 fixture league key")
        _identifier(self.season, "F01 fixture season")
        friday = _canonical_date(self.matchweek_friday, "F01 Matchweek Friday")
        if date.fromisoformat(friday).weekday() != 4:
            raise ValueError("F01 Matchweek date must be a Friday.")
        if self.scope_id != f"{self.league_key}:{self.season}:{friday}":
            raise ValueError("F01 fixture scope ID must match its league, season, and Friday.")
        interval = UtcInterval(self.window_start_utc, self.window_end_utc)
        object.__setattr__(self, "window_start_utc", interval.start_utc)
        object.__setattr__(self, "window_end_utc", interval.end_utc)
        try:
            from matchvet.fixture_coverage import FixtureScope

            original = FixtureScope(
                league_key=self.league_key,
                season=self.season,
                matchweek_friday=friday,
            )
        except (ImportError, TypeError, ValueError) as error:
            raise ValueError(
                "F01 fixture scope fields must describe a valid FixtureScope."
            ) from error
        if (
            original.scope_id != self.scope_id
            or original.window_start_utc != interval.start_utc
            or original.window_end_utc != interval.end_utc
        ):
            raise ValueError("F01 fixture scope window must match its canonical Matchweek.")

    @property
    def interval(self) -> UtcInterval:
        return UtcInterval(self.window_start_utc, self.window_end_utc)

    @classmethod
    def from_f01(cls, scope: object) -> F01FixtureScopeReference:
        """Project a validated F01 FixtureScope, including its computed UTC window."""
        try:
            from matchvet.fixture_coverage import FixtureScope

            if not isinstance(scope, FixtureScope):
                raise ValueError("Expected a typed F01 FixtureScope.")
            return cls(
                league_key=scope.league_key,
                season=scope.season,
                matchweek_friday=scope.matchweek_friday,
                scope_id=scope.scope_id,
                window_start_utc=scope.window_start_utc,
                window_end_utc=scope.window_end_utc,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Value is not a valid F01 FixtureScope.") from error

    @classmethod
    def from_payload(
        cls,
        *,
        league_key: str,
        season: str,
        matchweek_friday: str,
        scope_id: str,
        window_start_utc: str,
        window_end_utc: str,
    ) -> F01FixtureScopeReference:
        """Validate a decoded F01 scope against F01's existing window calculation."""
        try:
            from matchvet.fixture_coverage import FixtureScope

            original = FixtureScope(
                league_key=league_key,
                season=season,
                matchweek_friday=matchweek_friday,
            )
            projected = cls.from_f01(original)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Invalid F01 FixtureScope projection.") from error
        if (projected.scope_id, projected.interval) != (
            scope_id,
            UtcInterval(window_start_utc, window_end_utc),
        ):
            raise ValueError("F01 FixtureScope projection does not match its canonical window.")
        return projected


class SubjectKind(StrEnum):
    MATCH = "MATCH"
    TEAM = "TEAM"
    PERSON = "PERSON"
    VENUE = "VENUE"


@dataclass(frozen=True, slots=True)
class SubjectIdentifier:
    kind: SubjectKind
    subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SubjectKind):
            raise ValueError("Subject kind must be a SubjectKind.")
        _identifier(self.subject_id, "Subject ID")


@dataclass(frozen=True, slots=True)
class NamedSelectorFacet:
    key: str
    facet: ScopeFacet[tuple[str, ...]]

    def __post_init__(self) -> None:
        _identifier(self.key, "Selector key")
        if not isinstance(self.facet, ScopeFacet):
            raise ValueError("Named selectors require a typed ScopeFacet.")
        if self.facet.state is ScopeFacetState.KNOWN:
            values = cast(tuple[str, ...], self.facet.value)
            if (
                not isinstance(values, tuple)
                or not values
                or not all(isinstance(value, str) for value in values)
            ):
                raise ValueError("A KNOWN selector requires at least one value.")
            for value in values:
                _identifier(value, "Selector value")
            normalized = _sorted_unique(values, lambda value: value, "Selector values")
            object.__setattr__(self, "facet", ScopeFacet.known(normalized))


@dataclass(frozen=True, slots=True)
class ScopeContract:
    """Declares which standard query facets and stable selectors a capability uses."""

    competition: FacetApplicability
    season: FacetApplicability
    time: FacetApplicability
    subjects: FacetApplicability
    selector_keys: tuple[str, ...]
    coverage: CoverageApplicability

    def __post_init__(self) -> None:
        for label, value in (
            ("competition", self.competition),
            ("season", self.season),
            ("time", self.time),
            ("subjects", self.subjects),
        ):
            if not isinstance(value, FacetApplicability):
                raise ValueError(f"Scope contract {label} applicability must be typed.")
        if not isinstance(self.coverage, CoverageApplicability):
            raise ValueError("Scope contract coverage applicability must be typed.")
        for key in self.selector_keys:
            _identifier(key, "Scope contract selector key")
        normalized = _sorted_unique(self.selector_keys, lambda key: key, "Scope contract selectors")
        object.__setattr__(self, "selector_keys", normalized)

    def validate(self, scope: RequestedScope) -> None:
        facets = (
            ("competition", self.competition, scope.competition.state),
            ("season", self.season, scope.season.state),
            ("time", self.time, scope.time.state),
            ("subjects", self.subjects, scope.subjects.state),
        )
        for name, applicability, state in facets:
            if applicability is FacetApplicability.APPLICABLE:
                if state is ScopeFacetState.NOT_APPLICABLE:
                    raise ValueError(f"Applicable {name} scope facet cannot be NOT_APPLICABLE.")
            elif state is not ScopeFacetState.NOT_APPLICABLE:
                raise ValueError(f"Non-applicable {name} scope facet must be NOT_APPLICABLE.")
        actual_keys = tuple(selector.key for selector in scope.selectors)
        if actual_keys != self.selector_keys:
            raise ValueError(
                "Requested scope must explicitly include every capability selector key."
            )
        for selector in scope.selectors:
            if selector.facet.state is ScopeFacetState.NOT_APPLICABLE:
                raise ValueError(
                    f"Applicable {selector.key} selector facet cannot be NOT_APPLICABLE."
                )


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider_id: str
    source_lineage_id: str

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "Provider ID")
        _identifier(self.source_lineage_id, "Source lineage ID")


@dataclass(frozen=True, slots=True)
class CapabilityIdentity:
    capability_id: str
    scope_contract: ScopeContract

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "Capability ID")
        if not isinstance(self.scope_contract, ScopeContract):
            raise ValueError("Capability identity requires a typed ScopeContract.")


@dataclass(frozen=True, slots=True)
class RequestedScope:
    scope_kind: str
    competition: ScopeFacet[CompetitionScope]
    season: ScopeFacet[SeasonScope]
    time: ScopeFacet[RequestedTimeScope]
    subjects: ScopeFacet[tuple[SubjectIdentifier, ...]]
    selectors: tuple[NamedSelectorFacet, ...]
    fixture_scope: F01FixtureScopeReference | None = None

    def __post_init__(self) -> None:
        _identifier(self.scope_kind, "Scope kind")
        for label, facet, value_type in (
            ("competition", self.competition, CompetitionScope),
            ("season", self.season, SeasonScope),
            ("time", self.time, (UtcInterval, LocalDateRange)),
        ):
            if not isinstance(facet, ScopeFacet):
                raise ValueError(f"Requested {label} must be a typed ScopeFacet.")
            if facet.state is ScopeFacetState.KNOWN and not isinstance(facet.value, value_type):
                raise ValueError(f"Known requested {label} has the wrong value type.")
        if not isinstance(self.subjects, ScopeFacet):
            raise ValueError("Requested subjects must be a typed ScopeFacet.")
        if self.subjects.state is ScopeFacetState.KNOWN:
            subjects = cast(tuple[SubjectIdentifier, ...], self.subjects.value)
            if not subjects or not all(isinstance(item, SubjectIdentifier) for item in subjects):
                raise ValueError("Known requested subjects require typed subject identifiers.")
            normalized_subjects = _sorted_unique(
                subjects,
                lambda item: f"{item.kind.value}:{item.subject_id}",
                "Requested subjects",
            )
            object.__setattr__(self, "subjects", ScopeFacet.known(normalized_subjects))
        for selector in self.selectors:
            if not isinstance(selector, NamedSelectorFacet):
                raise ValueError("Requested selectors must be typed NamedSelectorFacet values.")
        normalized_selectors = _sorted_unique(
            self.selectors, lambda item: item.key, "Requested selectors"
        )
        object.__setattr__(self, "selectors", normalized_selectors)
        if self.fixture_scope is not None:
            if not isinstance(self.fixture_scope, F01FixtureScopeReference):
                raise ValueError("F01 fixture scope must be a typed F01FixtureScopeReference.")
            if (
                self.competition.state is not ScopeFacetState.KNOWN
                or self.competition.value is None
                or self.competition.value.competition_id != self.fixture_scope.league_key
                or self.competition.value.provider_key != self.fixture_scope.league_key
            ):
                raise ValueError("F01 fixture league must match both requested competition IDs.")
            if (
                self.season.state is not ScopeFacetState.KNOWN
                or self.season.value is None
                or self.season.value.season_id != self.fixture_scope.season
                or self.season.value.provider_value != self.fixture_scope.season
            ):
                raise ValueError("F01 fixture season must match both requested season IDs.")
            if self.time.state is not ScopeFacetState.KNOWN or self.time.value is None:
                raise ValueError("F01 fixture scope requires a known requested time scope.")
            time_scope = self.time.value
            if isinstance(time_scope, UtcInterval):
                matches_time = time_scope == self.fixture_scope.interval
            else:
                matches_time = (
                    time_scope.start_date == self.fixture_scope.matchweek_friday
                    and time_scope.end_date_exclusive
                    == (
                        date.fromisoformat(self.fixture_scope.matchweek_friday) + timedelta(days=4)
                    ).isoformat()
                    and time_scope.timezone_name == "Africa/Lagos"
                )
            if not matches_time:
                raise ValueError("F01 fixture time must match the requested exact time scope.")
            if self.subjects.state is not ScopeFacetState.NOT_APPLICABLE or self.selectors:
                raise ValueError(
                    "F01 FixtureScope only identifies league, season, and Matchweek time scope."
                )

    @property
    def scope_id(self) -> str:
        payload = _scope_payload(self)
        return f"sha256:{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"

    @property
    def evidence_scope_id(self) -> str:
        """Return the exact external scope key when this is an F01 fixture request."""
        return self.fixture_scope.scope_id if self.fixture_scope is not None else self.scope_id

    @property
    def fixture_scope_id(self) -> str | None:
        """Return the F01 scope ID for references that require its external key."""
        return None if self.fixture_scope is None else self.fixture_scope.scope_id


class UsePermissionState(StrEnum):
    PERMITTED = "PERMITTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    UNKNOWN = "UNKNOWN"


class ReachabilityState(StrEnum):
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


class CapabilityAvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class StructuralValidityState(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    CONFIRMED_EMPTY = "CONFIRMED_EMPTY"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FailureState(StrEnum):
    FAILED = "FAILED"
    NO_FAILURE_OBSERVED = "NO_FAILURE_OBSERVED"
    UNKNOWN = "UNKNOWN"


class F01ProviderAttemptState(StrEnum):
    CAPTURED = "CAPTURED"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED = "MALFORMED"


class F01CoverageBasisKind(StrEnum):
    VERSIONED_SOURCE_CONTRACT = "VERSIONED_SOURCE_CONTRACT"
    EXPLICIT_PROVIDER_METADATA = "EXPLICIT_PROVIDER_METADATA"


class EvidenceReferenceKind(StrEnum):
    PROVIDER_ATTEMPT = "PROVIDER_ATTEMPT"
    PROVIDER_COVERAGE_EVIDENCE = "PROVIDER_COVERAGE_EVIDENCE"
    CAPABILITY_COVERAGE_EVIDENCE = "CAPABILITY_COVERAGE_EVIDENCE"
    FIXTURE_COVERAGE_ASSESSMENT = "FIXTURE_COVERAGE_ASSESSMENT"
    SOURCE_CAPTURE = "SOURCE_CAPTURE"
    SOURCE_ASSERTION = "SOURCE_ASSERTION"
    PROVIDER_METADATA = "PROVIDER_METADATA"
    FRESHNESS_EVIDENCE = "FRESHNESS_EVIDENCE"
    OTHER_VERSIONED_EVIDENCE = "OTHER_VERSIONED_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ProviderAttemptReference:
    """Immutable projection of an F01 Provider Attempt, without importing F01."""

    attempt_id: str
    scope_id: str
    provider_id: str
    capability_id: str
    state: F01ProviderAttemptState
    retrieved_at_utc: str
    http_status: int | None
    capture_id: str | None
    capture_digest: str | None

    def __post_init__(self) -> None:
        for label, value in (
            ("attempt ID", self.attempt_id),
            ("scope ID", self.scope_id),
            ("provider ID", self.provider_id),
            ("capability ID", self.capability_id),
        ):
            _identifier(value, f"Provider Attempt reference {label}")
        if not isinstance(self.state, F01ProviderAttemptState):
            raise ValueError("Provider Attempt reference state must be an F01 attempt state.")
        _canonical_utc(self.retrieved_at_utc, "Provider Attempt retrieval time")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("Provider Attempt HTTP status must be an integer from 100 to 599.")
        if (self.capture_id is None) != (self.capture_digest is None):
            raise ValueError("Provider Attempt capture reference requires both ID and digest.")
        if self.capture_id is not None:
            _identifier(self.capture_id, "Provider Attempt capture ID")
        if self.capture_digest is not None:
            _identifier(self.capture_digest, "Provider Attempt capture digest")
        if self.state is F01ProviderAttemptState.CAPTURED and self.capture_id is None:
            raise ValueError("A CAPTURED Provider Attempt requires its capture ID and digest.")
        if self.state is F01ProviderAttemptState.UNAVAILABLE and self.capture_id is not None:
            raise ValueError("An UNAVAILABLE Provider Attempt cannot reference a capture.")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.PROVIDER_ATTEMPT

    @property
    def reference_id(self) -> str:
        return self.attempt_id

    @classmethod
    def from_f01(cls, attempt: object) -> ProviderAttemptReference:
        """Project a structural F01 ProviderAttempt value without loading F01 code."""
        try:
            state = F01ProviderAttemptState(str(_field(attempt, "state")))
            return cls(
                attempt_id=_field(attempt, "attempt_id"),
                scope_id=_field(attempt, "scope_id"),
                provider_id=_field(attempt, "provider_id"),
                capability_id=_field(attempt, "capability_id"),
                state=state,
                retrieved_at_utc=_field(attempt, "retrieved_at_utc"),
                http_status=_field(attempt, "http_status"),
                capture_id=_field(attempt, "capture_id"),
                capture_digest=_field(attempt, "capture_digest"),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Value is not a valid F01 Provider Attempt.") from error


@dataclass(frozen=True, slots=True)
class ProviderCoverageEvidenceReference:
    """F01 provider coverage evidence joined to the attempt that owns its identity."""

    evidence_id: str
    attempt_id: str
    scope_id: str
    provider_id: str
    capability_id: str
    provider_competition_key: str | None
    provider_season: str | None
    capture_id: str
    capture_digest: str
    provider_use_policy_id: str | None
    permitted_for_use: bool
    coverage_basis_kind: F01CoverageBasisKind | None
    coverage_basis_id: str | None
    coverage_basis_version: str | None
    bounds_start_utc: str | None
    bounds_end_utc: str | None
    required_partition_ids: tuple[str, ...]
    accounted_partition_ids: tuple[str, ...]
    pagination_exhausted: bool
    affirmatively_empty: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence ID", self.evidence_id),
            ("attempt ID", self.attempt_id),
            ("scope ID", self.scope_id),
            ("provider ID", self.provider_id),
            ("capability ID", self.capability_id),
            ("capture ID", self.capture_id),
            ("capture digest", self.capture_digest),
        ):
            _identifier(value, f"Provider Coverage Evidence reference {label}")
        if self.provider_use_policy_id is not None:
            _identifier(self.provider_use_policy_id, "Provider use policy ID")
        if type(self.permitted_for_use) is not bool:
            raise ValueError("Provider coverage permitted-for-use flag must be a boolean.")
        if self.permitted_for_use and self.provider_use_policy_id is None:
            raise ValueError("Permitted Provider Coverage Evidence requires its policy ID.")
        if self.coverage_basis_kind is not None and not isinstance(
            self.coverage_basis_kind, F01CoverageBasisKind
        ):
            raise ValueError("Coverage evidence basis kind must be typed.")
        for label, facet_value in (
            ("provider competition key", self.provider_competition_key),
            ("provider season", self.provider_season),
        ):
            if facet_value is not None:
                _identifier(facet_value, f"Provider Coverage Evidence reference {label}")
        if (self.coverage_basis_kind is None) != (self.coverage_basis_id is None):
            raise ValueError("Coverage basis kind and ID must be supplied together.")
        if self.coverage_basis_kind is None and self.coverage_basis_version is not None:
            raise ValueError("Coverage basis version requires its kind and ID.")
        if (
            self.coverage_basis_kind is F01CoverageBasisKind.VERSIONED_SOURCE_CONTRACT
            and self.coverage_basis_version is None
        ):
            raise ValueError("Versioned source contract basis requires a version.")
        if self.coverage_basis_id is not None:
            _identifier(self.coverage_basis_id, "Coverage basis ID")
        if self.coverage_basis_version is not None:
            _identifier(self.coverage_basis_version, "Coverage basis version")
        if (self.bounds_start_utc is None) != (self.bounds_end_utc is None):
            raise ValueError("Coverage evidence bounds require both endpoints.")
        if self.bounds_start_utc is not None and self.bounds_end_utc is not None:
            bounds = UtcInterval(self.bounds_start_utc, self.bounds_end_utc)
            object.__setattr__(self, "bounds_start_utc", bounds.start_utc)
            object.__setattr__(self, "bounds_end_utc", bounds.end_utc)
        required = _sorted_unique(
            self.required_partition_ids, lambda value: value, "Required partition IDs"
        )
        accounted = _sorted_unique(
            self.accounted_partition_ids, lambda value: value, "Accounted partition IDs"
        )
        for value in (*required, *accounted):
            _identifier(value, "Coverage partition ID")
        if not set(accounted).issubset(required):
            raise ValueError("Accounted partitions must be declared as required partitions.")
        object.__setattr__(self, "required_partition_ids", required)
        object.__setattr__(self, "accounted_partition_ids", accounted)
        if (
            type(self.pagination_exhausted) is not bool
            or type(self.affirmatively_empty) is not bool
        ):
            raise ValueError("Coverage evidence flags must be booleans.")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.PROVIDER_COVERAGE_EVIDENCE

    @property
    def reference_id(self) -> str:
        return self.evidence_id

    @classmethod
    def from_f01(
        cls, evidence: object, attempt: ProviderAttemptReference
    ) -> ProviderCoverageEvidenceReference:
        """Project F01 coverage evidence and verify the linked attempt identity."""
        try:
            basis = _field(evidence, "coverage_basis")
            bounds = _field(evidence, "bounds")
            result = cls(
                evidence_id=_field(evidence, "evidence_id"),
                attempt_id=_field(evidence, "attempt_id"),
                scope_id=_field(evidence, "scope_id"),
                provider_id=attempt.provider_id,
                capability_id=attempt.capability_id,
                provider_competition_key=_field(evidence, "provider_competition_key"),
                provider_season=_field(evidence, "provider_season"),
                capture_id=_field(evidence, "capture_id"),
                capture_digest=_field(evidence, "capture_digest"),
                provider_use_policy_id=_field(evidence, "provider_use_policy_id"),
                permitted_for_use=_field(evidence, "permitted_for_use"),
                coverage_basis_kind=(
                    None if basis is None else F01CoverageBasisKind(str(_field(basis, "kind")))
                ),
                coverage_basis_id=(None if basis is None else _field(basis, "reference_id")),
                coverage_basis_version=(None if basis is None else _field(basis, "version")),
                bounds_start_utc=(None if bounds is None else _field(bounds, "start_utc")),
                bounds_end_utc=(None if bounds is None else _field(bounds, "end_utc")),
                required_partition_ids=tuple(_field(evidence, "required_partition_ids")),
                accounted_partition_ids=tuple(_field(evidence, "accounted_partition_ids")),
                pagination_exhausted=_field(evidence, "pagination_exhausted"),
                affirmatively_empty=_field(evidence, "affirmatively_empty"),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Value is not valid F01 Provider Coverage Evidence.") from error
        if result.attempt_id != attempt.attempt_id:
            raise ValueError("Coverage evidence must reference the supplied Provider Attempt.")
        if result.scope_id != attempt.scope_id:
            raise ValueError("Coverage evidence and Provider Attempt scopes must match.")
        if (result.capture_id, result.capture_digest) != (
            attempt.capture_id,
            attempt.capture_digest,
        ):
            raise ValueError(
                "Coverage evidence and Provider Attempt capture references must match."
            )
        return result


@dataclass(frozen=True, slots=True)
class CapabilityCoverageEvidenceReference:
    """Versioned provider coverage evidence for fixture or contextual capabilities."""

    evidence_id: str
    evidence_kind: str
    version: str
    provider_id: str
    capability_id: str
    scope_id: str
    digest: str
    scope_complete: bool
    enumeration_complete: bool
    required_partition_ids: tuple[str, ...] = ()
    accounted_partition_ids: tuple[str, ...] = ()
    covered_extent_ids: tuple[str, ...] = ()
    known_gap_ids: tuple[str, ...] = ()
    affirmatively_empty: bool = False
    capture_id: str | None = None
    capture_digest: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence ID", self.evidence_id),
            ("evidence kind", self.evidence_kind),
            ("evidence version", self.version),
            ("provider ID", self.provider_id),
            ("capability ID", self.capability_id),
            ("scope ID", self.scope_id),
            ("evidence digest", self.digest),
        ):
            _identifier(value, f"Capability Coverage Evidence {label}")
        for label, optional_value in (
            ("capture ID", self.capture_id),
            ("capture digest", self.capture_digest),
        ):
            if optional_value is not None:
                _identifier(optional_value, f"Capability Coverage Evidence {label}")
        if (self.capture_id is None) != (self.capture_digest is None):
            raise ValueError("Capability coverage capture reference requires both ID and digest.")
        if type(self.scope_complete) is not bool or type(self.enumeration_complete) is not bool:
            raise ValueError("Capability coverage completeness flags must be booleans.")
        if type(self.affirmatively_empty) is not bool:
            raise ValueError("Capability coverage affirmative-empty flag must be a boolean.")
        required = _sorted_unique(
            self.required_partition_ids, lambda value: value, "Required coverage partitions"
        )
        accounted = _sorted_unique(
            self.accounted_partition_ids, lambda value: value, "Accounted coverage partitions"
        )
        if not set(accounted).issubset(required):
            raise ValueError("Accounted coverage partitions must be declared as required.")
        covered_extents = _sorted_unique(
            self.covered_extent_ids, lambda value: value, "Covered extent IDs"
        )
        known_gaps = _sorted_unique(self.known_gap_ids, lambda value: value, "Known coverage gaps")
        for value in (*required, *accounted, *covered_extents, *known_gaps):
            _identifier(value, "Coverage partition, extent, or gap ID")
        object.__setattr__(self, "required_partition_ids", required)
        object.__setattr__(self, "accounted_partition_ids", accounted)
        object.__setattr__(self, "covered_extent_ids", covered_extents)
        object.__setattr__(self, "known_gap_ids", known_gaps)
        if self.scope_complete and (
            not self.enumeration_complete or required != accounted or known_gaps
        ):
            raise ValueError(
                "Complete capability coverage requires completed enumeration and no known gaps."
            )
        if self.affirmatively_empty and not self.scope_complete:
            raise ValueError("Affirmatively empty capability evidence must cover the full scope.")
        if self.affirmatively_empty and self.covered_extent_ids:
            raise ValueError(
                "Affirmatively empty capability evidence cannot cover non-empty extents."
            )

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.CAPABILITY_COVERAGE_EVIDENCE

    @property
    def reference_id(self) -> str:
        return self.evidence_id

    @property
    def has_partial_extent_or_gap(self) -> bool:
        return not self.scope_complete and bool(
            self.covered_extent_ids
            or self.known_gap_ids
            or self.accounted_partition_ids
            or set(self.required_partition_ids) - set(self.accounted_partition_ids)
        )


@dataclass(frozen=True, slots=True)
class FixtureCoverageAssessmentReference:
    """Opaque F01 aggregate assessment reference; its state is never reinterpreted."""

    assessment_digest: str
    contract_version: str
    schema_version: int
    fixture_scope_id: str
    scope_state: str
    provider_attempt_ids: tuple[str, ...]
    coverage_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("assessment digest", self.assessment_digest),
            ("contract version", self.contract_version),
            ("fixture scope ID", self.fixture_scope_id),
            ("scope state", self.scope_state),
        ):
            _identifier(value, f"Fixture Coverage Assessment reference {label}")
        if type(self.schema_version) is not int or self.schema_version <= 0:
            raise ValueError("Fixture Coverage Assessment schema version must be positive.")
        for name, values in (
            ("Provider Attempt IDs", self.provider_attempt_ids),
            ("Coverage Evidence IDs", self.coverage_evidence_ids),
        ):
            for value in values:
                _identifier(value, f"Fixture Coverage Assessment {name} member")
            normalized = _sorted_unique(values, lambda value: value, name)
            object.__setattr__(self, name.lower().replace(" ", "_"), normalized)

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.FIXTURE_COVERAGE_ASSESSMENT

    @property
    def reference_id(self) -> str:
        return self.assessment_digest

    @classmethod
    def from_f01(
        cls, assessment: object, fixture_scope: F01FixtureScopeReference
    ) -> FixtureCoverageAssessmentReference:
        """Project one original F01 scope result and its exact evidence membership."""
        if not isinstance(fixture_scope, F01FixtureScopeReference):
            raise ValueError("F01 assessment projection requires a typed FixtureScope reference.")
        try:
            from matchvet.fixture_coverage import FixtureCoverageAssessment

            if not isinstance(assessment, FixtureCoverageAssessment):
                raise ValueError("Expected a typed F01 FixtureCoverageAssessment.")
            matching = tuple(
                value
                for value in _field(assessment, "scope_assessments")
                if _field(_field(value, "scope"), "scope_id") == fixture_scope.scope_id
            )
            if len(matching) != 1:
                raise ValueError("F01 assessment must contain exactly one matching scope.")
            selected = matching[0]
            return cls(
                assessment_digest=_field(assessment, "digest"),
                contract_version=_field(assessment, "contract_version"),
                schema_version=_field(assessment, "schema_version"),
                fixture_scope_id=fixture_scope.scope_id,
                scope_state=str(_field(selected, "coverage_state")),
                provider_attempt_ids=tuple(_field(selected, "provider_attempt_ids")),
                coverage_evidence_ids=tuple(_field(selected, "coverage_evidence_ids")),
            )
        except (AttributeError, TypeError) as error:
            raise ValueError("Value is not a valid F01 Fixture Coverage Assessment.") from error


@dataclass(frozen=True, slots=True)
class SourceCaptureReference:
    """Capture provenance with feed key, source record ID, and lineage kept distinct."""

    capture_id: str
    source_key: str
    source_id: str
    source_lineage_id: str
    capture_digest: str
    content_digest: str | None
    artifact_digest: str | None

    def __post_init__(self) -> None:
        for label, value in (
            ("capture ID", self.capture_id),
            ("source key", self.source_key),
            ("source ID", self.source_id),
            ("source lineage ID", self.source_lineage_id),
            ("capture digest", self.capture_digest),
        ):
            _identifier(value, f"Source Capture reference {label}")
        for label, digest_value in (
            ("content digest", self.content_digest),
            ("artifact digest", self.artifact_digest),
        ):
            if digest_value is not None:
                _identifier(digest_value, f"Source Capture reference {label}")
        if self.content_digest is not None and self.content_digest != self.capture_digest:
            raise ValueError("Source Capture content digest must match its capture digest.")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.SOURCE_CAPTURE

    @property
    def reference_id(self) -> str:
        return self.capture_id

    @classmethod
    def from_fields(
        cls,
        *,
        capture_id: str,
        source_key: str,
        source_id: str,
        source_lineage_id: str,
        capture_digest: str,
        content_digest: str | None = None,
        artifact_digest: str | None = None,
    ) -> SourceCaptureReference:
        return cls(
            capture_id=capture_id,
            source_key=source_key,
            source_id=source_id,
            source_lineage_id=source_lineage_id,
            capture_digest=capture_digest,
            content_digest=content_digest,
            artifact_digest=artifact_digest,
        )

    @classmethod
    def from_f01(
        cls,
        capture: object,
        *,
        source_lineage_id: str,
        capture_digest: str,
        source_key: str | None = None,
    ) -> SourceCaptureReference:
        """Project an F01 capture record while keeping feed key, source ID, and lineage apart."""
        try:
            selected_source_key = source_key or _field(capture, "source_key")
            return cls.from_fields(
                capture_id=_field(capture, "capture_id"),
                source_key=selected_source_key,
                source_id=_field(capture, "source_id"),
                source_lineage_id=source_lineage_id,
                capture_digest=capture_digest,
                content_digest=_field(capture, "content_sha256"),
                artifact_digest=_field(capture, "artifact_digest"),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Value is not a valid F01 Source Capture.") from error


@dataclass(frozen=True, slots=True)
class SourceAssertionReference:
    assertion_id: str
    capture_id: str

    def __post_init__(self) -> None:
        _identifier(self.assertion_id, "Source Assertion ID")
        _identifier(self.capture_id, "Source Assertion capture ID")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.SOURCE_ASSERTION

    @property
    def reference_id(self) -> str:
        return self.assertion_id

    @classmethod
    def from_f01(cls, assertion: object) -> SourceAssertionReference:
        try:
            capture_id = _field(assertion, "capture_id")
            if capture_id is None:
                raise ValueError("F01 Source Assertion must reference a capture.")
            return cls(assertion_id=_field(assertion, "assertion_id"), capture_id=capture_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Value is not a valid F01 Source Assertion.") from error


@dataclass(frozen=True, slots=True)
class ProviderMetadataReference:
    metadata_id: str
    version: str
    provider_id: str
    capability_id: str
    digest: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.metadata_id, "Provider metadata ID")
        _identifier(self.version, "Provider metadata version")
        _identifier(self.provider_id, "Provider metadata provider ID")
        _identifier(self.capability_id, "Provider metadata capability ID")
        if self.digest is not None:
            _identifier(self.digest, "Provider metadata digest")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.PROVIDER_METADATA

    @property
    def reference_id(self) -> str:
        return self.metadata_id


@dataclass(frozen=True, slots=True)
class OtherVersionedEvidenceReference:
    evidence_id: str
    evidence_kind: str
    version: str
    provider_id: str
    capability_id: str
    scope_id: str
    digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence ID", self.evidence_id),
            ("evidence kind", self.evidence_kind),
            ("evidence version", self.version),
            ("provider ID", self.provider_id),
            ("capability ID", self.capability_id),
            ("scope ID", self.scope_id),
            ("evidence digest", self.digest),
        ):
            _identifier(value, f"Versioned evidence {label}")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.OTHER_VERSIONED_EVIDENCE

    @property
    def reference_id(self) -> str:
        return self.evidence_id


@dataclass(frozen=True, slots=True)
class FreshnessEvidenceReference:
    """Versioned source-time or equivalent evidence supporting a freshness result."""

    evidence_id: str
    version: str
    provider_id: str
    capability_id: str
    scope_id: str
    digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence ID", self.evidence_id),
            ("evidence version", self.version),
            ("provider ID", self.provider_id),
            ("capability ID", self.capability_id),
            ("scope ID", self.scope_id),
            ("evidence digest", self.digest),
        ):
            _identifier(value, f"Freshness evidence {label}")

    @property
    def reference_kind(self) -> EvidenceReferenceKind:
        return EvidenceReferenceKind.FRESHNESS_EVIDENCE

    @property
    def reference_id(self) -> str:
        return self.evidence_id


EvidenceReference = (
    ProviderAttemptReference
    | ProviderCoverageEvidenceReference
    | CapabilityCoverageEvidenceReference
    | FixtureCoverageAssessmentReference
    | SourceCaptureReference
    | SourceAssertionReference
    | ProviderMetadataReference
    | FreshnessEvidenceReference
    | OtherVersionedEvidenceReference
)

CoverageEvidenceReference = ProviderCoverageEvidenceReference | CapabilityCoverageEvidenceReference


@dataclass(frozen=True, slots=True)
class EvidenceBasis:
    """Evidence for one dimension, explicitly bound to one provider/capability/scope."""

    provider_id: str
    capability_id: str
    scope_id: str
    references: tuple[EvidenceReference, ...]
    source_as_of_utc: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "Evidence basis provider ID")
        _identifier(self.capability_id, "Evidence basis capability ID")
        _identifier(self.scope_id, "Evidence basis scope ID")
        if not self.references:
            raise ValueError("Evidence basis requires at least one typed reference.")
        if not all(
            isinstance(
                reference,
                (
                    ProviderAttemptReference,
                    ProviderCoverageEvidenceReference,
                    CapabilityCoverageEvidenceReference,
                    FixtureCoverageAssessmentReference,
                    SourceCaptureReference,
                    SourceAssertionReference,
                    ProviderMetadataReference,
                    FreshnessEvidenceReference,
                    OtherVersionedEvidenceReference,
                ),
            )
            for reference in self.references
        ):
            raise ValueError("Evidence basis references must be typed evidence values.")
        normalized = _sorted_unique(
            self.references,
            lambda reference: f"{reference.reference_kind.value}:{reference.reference_id}",
            "Evidence basis references",
        )
        object.__setattr__(self, "references", normalized)
        if self.source_as_of_utc is not None:
            _canonical_utc(self.source_as_of_utc, "Evidence source-as-of time")


@dataclass(frozen=True, slots=True)
class CoverageWitness:
    """Provider-specific coverage evidence tied to one exact capability and query scope."""

    provider_id: str
    capability_id: str
    scope_id: str
    evidence: tuple[CoverageEvidenceReference, ...]
    attempts: tuple[ProviderAttemptReference, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "Coverage witness provider ID")
        _identifier(self.capability_id, "Coverage witness capability ID")
        _identifier(self.scope_id, "Coverage witness scope ID")
        if not self.evidence:
            raise ValueError("Coverage witness requires provider-specific coverage evidence.")
        if not all(
            isinstance(
                value,
                (ProviderCoverageEvidenceReference, CapabilityCoverageEvidenceReference),
            )
            for value in self.evidence
        ):
            raise ValueError("Coverage witness requires typed capability coverage evidence.")
        normalized = _sorted_unique(
            self.evidence,
            lambda value: f"{value.reference_kind.value}:{value.reference_id}",
            "Coverage witness evidence",
        )
        for evidence in normalized:
            if (evidence.provider_id, evidence.capability_id, evidence.scope_id) != (
                self.provider_id,
                self.capability_id,
                self.scope_id,
            ):
                raise ValueError(
                    "Coverage evidence must match its witness provider/capability/scope."
                )
            if (
                isinstance(evidence, ProviderCoverageEvidenceReference)
                and evidence.coverage_basis_id is None
            ):
                raise ValueError("F01 coverage claims require a source coverage basis.")
        normalized_attempts = _sorted_unique(
            self.attempts,
            lambda value: value.attempt_id,
            "Coverage witness attempts",
        )
        f01_evidence = tuple(
            value for value in normalized if isinstance(value, ProviderCoverageEvidenceReference)
        )
        if any(not isinstance(value, ProviderAttemptReference) for value in normalized_attempts):
            raise ValueError("Coverage witness attempts must be typed Provider Attempt references.")
        if {value.attempt_id for value in normalized_attempts} != {
            value.attempt_id for value in f01_evidence
        }:
            raise ValueError("Coverage witness attempts must match its F01 evidence memberships.")
        for evidence in f01_evidence:
            linked = tuple(
                attempt
                for attempt in normalized_attempts
                if attempt.attempt_id == evidence.attempt_id
            )
            if len(linked) != 1:
                raise ValueError("Coverage evidence must have one matching Provider Attempt.")
            attempt = linked[0]
            if (
                attempt.provider_id,
                attempt.capability_id,
                attempt.scope_id,
            ) != (self.provider_id, self.capability_id, self.scope_id):
                raise ValueError(
                    "Coverage attempt must match its witness provider/capability/scope."
                )
            if (attempt.capture_id, attempt.capture_digest) != (
                evidence.capture_id,
                evidence.capture_digest,
            ):
                raise ValueError("Coverage evidence capture must match its Provider Attempt.")
        if any(value.affirmatively_empty for value in normalized) and any(
            isinstance(value, CapabilityCoverageEvidenceReference) and value.covered_extent_ids
            for value in normalized
        ):
            raise ValueError(
                "Coverage witness cannot combine affirmative empty evidence with covered extents."
            )
        object.__setattr__(self, "evidence", normalized)
        object.__setattr__(self, "attempts", normalized_attempts)

    @property
    def has_complete_scope_evidence(self) -> bool:
        return any(
            (
                evidence.scope_complete
                and evidence.enumeration_complete
                and evidence.required_partition_ids == evidence.accounted_partition_ids
            )
            if isinstance(evidence, CapabilityCoverageEvidenceReference)
            else (
                evidence.coverage_basis_id is not None
                and evidence.pagination_exhausted
                and evidence.required_partition_ids == evidence.accounted_partition_ids
            )
            for evidence in self.evidence
        )

    @property
    def has_affirmative_empty_scope_evidence(self) -> bool:
        return any(
            evidence.affirmatively_empty
            and (
                evidence.scope_complete
                and evidence.enumeration_complete
                and evidence.required_partition_ids == evidence.accounted_partition_ids
                if isinstance(evidence, CapabilityCoverageEvidenceReference)
                else (
                    evidence.coverage_basis_id is not None
                    and evidence.pagination_exhausted
                    and evidence.required_partition_ids == evidence.accounted_partition_ids
                )
            )
            for evidence in self.evidence
        )

    @property
    def has_partial_extent_or_gap_evidence(self) -> bool:
        return any(
            evidence.has_partial_extent_or_gap
            if isinstance(evidence, CapabilityCoverageEvidenceReference)
            else (
                evidence.bounds_start_utc is not None
                or evidence.required_partition_ids != evidence.accounted_partition_ids
            )
            for evidence in self.evidence
        )


@dataclass(frozen=True, slots=True)
class PermissionPolicyReference:
    policy_id: str
    version: str
    intended_use_id: str

    def __post_init__(self) -> None:
        _identifier(self.policy_id, "Permission policy ID")
        _identifier(self.version, "Permission policy version")
        _identifier(self.intended_use_id, "Permission policy intended use ID")


@dataclass(frozen=True, slots=True)
class FreshnessPolicyReference:
    policy_id: str
    version: str
    capability_id: str

    def __post_init__(self) -> None:
        _identifier(self.policy_id, "Freshness policy ID")
        _identifier(self.version, "Freshness policy version")
        _identifier(self.capability_id, "Freshness policy capability ID")


@dataclass(frozen=True, slots=True)
class FailureReasonCode:
    value: str

    def __post_init__(self) -> None:
        _identifier(self.value, "Failure reason code")
        if (
            len(self.value) > 64
            or not self.value.isascii()
            or self.value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in self.value
            )
        ):
            raise ValueError("Failure reason codes must be stable uppercase tokens.")

    @classmethod
    def unknown_reason(cls) -> FailureReasonCode:
        return cls("UNKNOWN_REASON")


@dataclass(frozen=True, slots=True)
class UsePermissionAssessment:
    state: UsePermissionState
    policy: PermissionPolicyReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, UsePermissionState):
            raise ValueError("Use permission state must be a UsePermissionState.")
        if self.policy is not None and not isinstance(self.policy, PermissionPolicyReference):
            raise ValueError("Use permission policy must be a PermissionPolicyReference.")
        if self.state is not UsePermissionState.UNKNOWN and self.policy is None:
            raise ValueError("Known use permission requires its versioned policy.")


@dataclass(frozen=True, slots=True)
class ReachabilityAssessment:
    state: ReachabilityState
    evidence: EvidenceBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ReachabilityState):
            raise ValueError("Reachability state must be a ReachabilityState.")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBasis):
            raise ValueError("Reachability evidence must be a typed EvidenceBasis.")
        if self.state is not ReachabilityState.UNKNOWN and self.evidence is None:
            raise ValueError("Known reachability requires an evidence basis.")


@dataclass(frozen=True, slots=True)
class CapabilityAvailabilityAssessment:
    state: CapabilityAvailabilityState
    evidence: EvidenceBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CapabilityAvailabilityState):
            raise ValueError("Capability availability state must be a CapabilityAvailabilityState.")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBasis):
            raise ValueError("Capability availability evidence must be a typed EvidenceBasis.")
        if self.state is not CapabilityAvailabilityState.UNKNOWN and self.evidence is None:
            raise ValueError("Known capability availability requires an evidence basis.")


@dataclass(frozen=True, slots=True)
class StructuralValidityAssessment:
    state: StructuralValidityState
    evidence: EvidenceBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, StructuralValidityState):
            raise ValueError("Structural validity state must be a StructuralValidityState.")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBasis):
            raise ValueError("Structural validity evidence must be a typed EvidenceBasis.")
        if self.state is not StructuralValidityState.UNKNOWN and self.evidence is None:
            raise ValueError("Known structural validity requires an evidence basis.")


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    state: FreshnessState
    policy: FreshnessPolicyReference | None = None
    evidence: EvidenceBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, FreshnessState):
            raise ValueError("Freshness state must be a FreshnessState.")
        if self.policy is not None and not isinstance(self.policy, FreshnessPolicyReference):
            raise ValueError("Freshness policy must be a FreshnessPolicyReference.")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBasis):
            raise ValueError("Freshness evidence must be a typed EvidenceBasis.")
        if self.state is not FreshnessState.UNKNOWN and (
            self.policy is None or self.evidence is None
        ):
            raise ValueError(
                "Known freshness requires a versioned freshness policy and evidence basis."
            )
        if (
            self.state is not FreshnessState.UNKNOWN
            and self.evidence is not None
            and self.evidence.source_as_of_utc is None
            and not any(
                isinstance(reference, FreshnessEvidenceReference)
                for reference in self.evidence.references
            )
        ):
            raise ValueError(
                "Known freshness requires source-as-of time or typed versioned freshness evidence."
            )


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    state: CoverageState
    witness: CoverageWitness | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CoverageState):
            raise ValueError("Coverage state must be a CoverageState.")
        if self.witness is not None and not isinstance(self.witness, CoverageWitness):
            raise ValueError("Coverage witness must be a typed CoverageWitness.")
        requires_witness = self.state in (
            CoverageState.COMPLETE,
            CoverageState.CONFIRMED_EMPTY,
            CoverageState.PARTIAL,
        )
        if requires_witness and self.witness is None:
            raise ValueError("Known provider coverage requires exact-scope coverage evidence.")
        if (
            self.state is CoverageState.COMPLETE
            and self.witness is not None
            and not self.witness.has_complete_scope_evidence
        ):
            raise ValueError("COMPLETE requires evidence that closes the complete scope.")
        if (
            self.state is CoverageState.CONFIRMED_EMPTY
            and self.witness is not None
            and not self.witness.has_affirmative_empty_scope_evidence
        ):
            raise ValueError(
                "CONFIRMED_EMPTY requires affirmative evidence that closes the complete scope."
            )
        if (
            self.state is CoverageState.PARTIAL
            and self.witness is not None
            and not self.witness.has_partial_extent_or_gap_evidence
        ):
            raise ValueError("PARTIAL requires evidence of covered scope or explicit known gaps.")
        if self.state is CoverageState.NOT_APPLICABLE and self.witness is not None:
            raise ValueError("NOT_APPLICABLE coverage cannot carry a coverage claim witness.")


@dataclass(frozen=True, slots=True)
class FailureAssessment:
    state: FailureState
    reason_codes: tuple[FailureReasonCode, ...] = ()
    evidence: EvidenceBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, FailureState):
            raise ValueError("Failure state must be a FailureState.")
        if any(not isinstance(value, FailureReasonCode) for value in self.reason_codes):
            raise ValueError("Failure reason codes must be typed FailureReasonCode values.")
        normalized = _sorted_unique(
            self.reason_codes, lambda value: value.value, "Failure reason codes"
        )
        object.__setattr__(self, "reason_codes", normalized)
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBasis):
            raise ValueError("Failure evidence must be a typed EvidenceBasis.")
        if self.state is FailureState.FAILED:
            if not self.reason_codes:
                raise ValueError("FAILED requires at least one stable failure reason code.")
            if self.evidence is None:
                raise ValueError("FAILED requires a failure evidence basis.")
        elif self.state is FailureState.NO_FAILURE_OBSERVED:
            if self.reason_codes or self.evidence is None:
                raise ValueError(
                    "NO_FAILURE_OBSERVED requires evidence and no failure reason code."
                )
        elif self.reason_codes:
            raise ValueError("UNKNOWN failure must not carry failure reason codes.")


@dataclass(frozen=True, slots=True)
class ProviderHealthRecord:
    provider: ProviderIdentity
    capability: CapabilityIdentity
    requested_scope: RequestedScope
    intended_use_id: str
    checked_at_utc: str
    use_permission: UsePermissionAssessment
    reachability: ReachabilityAssessment
    capability_availability: CapabilityAvailabilityAssessment
    structural_validity: StructuralValidityAssessment
    freshness: FreshnessAssessment
    coverage: CoverageAssessment
    failure: FailureAssessment
    provenance: tuple[EvidenceReference, ...] = ()
    contract_version: str = field(default=PROVIDER_HEALTH_CONTRACT_VERSION, init=False)
    schema_version: int = field(default=PROVIDER_HEALTH_SCHEMA_VERSION, init=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderIdentity):
            raise ValueError("Provider Health Record requires a typed ProviderIdentity.")
        if not isinstance(self.capability, CapabilityIdentity):
            raise ValueError("Provider Health Record requires a typed CapabilityIdentity.")
        if not isinstance(self.requested_scope, RequestedScope):
            raise ValueError("Provider Health Record requires a typed RequestedScope.")
        self.capability.scope_contract.validate(self.requested_scope)
        _identifier(self.intended_use_id, "Intended use ID")
        _canonical_utc(self.checked_at_utc, "Provider health check time")
        for name, value, value_type in (
            ("use permission", self.use_permission, UsePermissionAssessment),
            ("reachability", self.reachability, ReachabilityAssessment),
            (
                "capability availability",
                self.capability_availability,
                CapabilityAvailabilityAssessment,
            ),
            ("structural validity", self.structural_validity, StructuralValidityAssessment),
            ("freshness", self.freshness, FreshnessAssessment),
            ("coverage", self.coverage, CoverageAssessment),
            ("failure", self.failure, FailureAssessment),
        ):
            if not isinstance(value, value_type):
                raise ValueError(f"Provider Health Record requires a typed {name} assessment.")
        if any(
            not isinstance(
                reference,
                (
                    ProviderAttemptReference,
                    ProviderCoverageEvidenceReference,
                    CapabilityCoverageEvidenceReference,
                    FixtureCoverageAssessmentReference,
                    SourceCaptureReference,
                    SourceAssertionReference,
                    ProviderMetadataReference,
                    OtherVersionedEvidenceReference,
                ),
            )
            for reference in self.provenance
        ):
            raise ValueError("Provider Health provenance references must be typed.")
        normalized_provenance = _sorted_unique(
            self.provenance,
            lambda reference: f"{reference.reference_kind.value}:{reference.reference_id}",
            "Provider Health provenance references",
        )
        object.__setattr__(self, "provenance", normalized_provenance)
        coverage_is_not_applicable = self.coverage.state is CoverageState.NOT_APPLICABLE
        contract_marks_coverage_not_applicable = (
            self.capability.scope_contract.coverage is CoverageApplicability.NOT_APPLICABLE
        )
        if coverage_is_not_applicable != contract_marks_coverage_not_applicable:
            raise ValueError("Coverage applicability must match the capability scope contract.")
        if (
            self.use_permission.policy is not None
            and self.use_permission.policy.intended_use_id != self.intended_use_id
        ):
            raise ValueError("Permission policy must match the record's intended use.")
        if (
            self.freshness.policy is not None
            and self.freshness.policy.capability_id != self.capability.capability_id
        ):
            raise ValueError("Freshness policy must match the record's capability.")
        if self.provenance:
            provenance_reference_keys = {
                f"{reference.reference_kind.value}:{reference.reference_id}"
                for reference in self.provenance
            }
            coverage_references: tuple[EvidenceReference, ...] = ()
            if self.coverage.witness is not None:
                coverage_references = tuple(
                    reference
                    for reference in (
                        *self.coverage.witness.attempts,
                        *self.coverage.witness.evidence,
                    )
                    if f"{reference.reference_kind.value}:{reference.reference_id}"
                    not in provenance_reference_keys
                )
            self._validate_evidence_basis(
                EvidenceBasis(
                    provider_id=self.provider.provider_id,
                    capability_id=self.capability.capability_id,
                    scope_id=self.requested_scope.evidence_scope_id,
                    references=(*self.provenance, *coverage_references),
                ),
                "record provenance",
            )
        for assessment_name, assessment in (
            ("reachability", self.reachability),
            ("capability availability", self.capability_availability),
            ("structural validity", self.structural_validity),
            ("freshness", self.freshness),
            ("failure", self.failure),
        ):
            dimension_evidence = assessment.evidence
            state = assessment.state
            if state.value != "UNKNOWN" and dimension_evidence is None:
                raise ValueError(f"Known {assessment_name} requires an evidence basis.")
            if dimension_evidence is None:
                continue
            self._validate_evidence_basis(dimension_evidence, assessment_name)
        if self.coverage.witness is not None:
            witness = self.coverage.witness
            expected_identity = (
                self.provider.provider_id,
                self.capability.capability_id,
                self.requested_scope.evidence_scope_id,
            )
            if (witness.provider_id, witness.capability_id, witness.scope_id) != expected_identity:
                raise ValueError(
                    "Coverage witness must match the record provider/capability/scope."
                )
            for coverage_evidence_ref in witness.evidence:
                self._validate_coverage_reference(coverage_evidence_ref)
        self._validate_f01_assessment_membership()
        self._validate_coverage_state_scope()
        if (
            any(
                isinstance(reference, ProviderAttemptReference)
                and (reference.http_status is not None or reference.capture_id is not None)
                for reference in self._all_evidence_references()
            )
            and self.reachability.state is not ReachabilityState.REACHABLE
        ):
            raise ValueError("An HTTP response or retained capture establishes reachability.")
        if self.failure.state is FailureState.NO_FAILURE_OBSERVED and any(
            isinstance(reference, ProviderAttemptReference)
            and (
                reference.state
                in (F01ProviderAttemptState.UNAVAILABLE, F01ProviderAttemptState.MALFORMED)
                or (reference.http_status is not None and reference.http_status >= 400)
            )
            for reference in self._all_evidence_references()
        ):
            raise ValueError(
                "Explicit failed Provider Attempt evidence cannot support NO_FAILURE_OBSERVED."
            )
        self._validate_referenced_capture_consistency()
        semantic = _record_payload(self)
        digest = hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()
        object.__setattr__(self, "digest", f"sha256:{digest}")

    def _validate_f01_assessment_membership(self) -> None:
        references = self._all_evidence_references()

        attempts = {
            reference.attempt_id
            for reference in references
            if isinstance(reference, ProviderAttemptReference)
        }
        coverage_ids = {
            reference.evidence_id
            for reference in references
            if isinstance(reference, ProviderCoverageEvidenceReference)
        }
        for assessment_reference in (
            reference
            for reference in references
            if isinstance(reference, FixtureCoverageAssessmentReference)
        ):
            if self.requested_scope.fixture_scope_id != assessment_reference.fixture_scope_id:
                raise ValueError("F01 assessment reference must match the requested Fixture Scope.")
            if not attempts.issubset(assessment_reference.provider_attempt_ids):
                raise ValueError("F01 assessment reference must retain referenced attempts.")
            if not coverage_ids.issubset(assessment_reference.coverage_evidence_ids):
                raise ValueError(
                    "F01 assessment reference must retain referenced coverage evidence."
                )

    def _all_evidence_references(self) -> tuple[EvidenceReference, ...]:
        references = list(self.provenance)
        for assessment in (
            self.reachability,
            self.capability_availability,
            self.structural_validity,
            self.freshness,
            self.failure,
        ):
            if assessment.evidence is not None:
                references.extend(assessment.evidence.references)
        if self.coverage.witness is not None:
            references.extend(self.coverage.witness.attempts)
            references.extend(self.coverage.witness.evidence)
        return tuple(references)

    def _validate_referenced_capture_consistency(self) -> None:
        references = self._all_evidence_references()
        reference_snapshots: dict[tuple[str, str], EvidenceReference] = {}
        capture_digests: dict[str, str] = {}
        for reference in references:
            key = (reference.reference_kind.value, reference.reference_id)
            prior = reference_snapshots.get(key)
            if prior is not None and prior != reference:
                raise ValueError("Repeated evidence reference IDs must retain identical snapshots.")
            reference_snapshots[key] = reference
            if isinstance(
                reference,
                (
                    ProviderAttemptReference,
                    ProviderCoverageEvidenceReference,
                    CapabilityCoverageEvidenceReference,
                    SourceCaptureReference,
                ),
            ):
                capture_id = reference.capture_id
                capture_digest = reference.capture_digest
            else:
                continue
            if capture_id is None:
                continue
            if capture_digest is None:
                continue
            prior_digest = capture_digests.get(capture_id)
            if prior_digest is not None and prior_digest != capture_digest:
                raise ValueError("Repeated capture IDs must retain one consistent digest.")
            capture_digests[capture_id] = capture_digest

    def _validate_evidence_basis(self, basis: EvidenceBasis, label: str) -> None:
        expected_identity = (
            self.provider.provider_id,
            self.capability.capability_id,
            self.requested_scope.evidence_scope_id,
        )
        if (basis.provider_id, basis.capability_id, basis.scope_id) != expected_identity:
            raise ValueError(f"{label} evidence must match the record provider/capability/scope.")
        f01_references = tuple(
            reference
            for reference in basis.references
            if isinstance(
                reference,
                (
                    ProviderAttemptReference,
                    ProviderCoverageEvidenceReference,
                    FixtureCoverageAssessmentReference,
                ),
            )
        )
        if f01_references and self.requested_scope.fixture_scope is None:
            raise ValueError("F01 evidence requires its typed FixtureScope reference.")
        attempts: tuple[ProviderAttemptReference, ...] = tuple(
            reference
            for reference in basis.references
            if isinstance(reference, ProviderAttemptReference)
        )
        coverage: tuple[CoverageEvidenceReference, ...] = tuple(
            reference
            for reference in basis.references
            if isinstance(
                reference, (ProviderCoverageEvidenceReference, CapabilityCoverageEvidenceReference)
            )
        )
        captures: tuple[SourceCaptureReference, ...] = tuple(
            reference
            for reference in basis.references
            if isinstance(reference, SourceCaptureReference)
        )
        assertions: tuple[SourceAssertionReference, ...] = tuple(
            reference
            for reference in basis.references
            if isinstance(reference, SourceAssertionReference)
        )
        for attempt_ref in attempts:
            if (
                attempt_ref.provider_id,
                attempt_ref.capability_id,
                attempt_ref.scope_id,
            ) != expected_identity:
                raise ValueError("Provider Attempt reference must match record identity and scope.")
        for coverage_ref in coverage:
            self._validate_coverage_reference(coverage_ref)
            if isinstance(coverage_ref, CapabilityCoverageEvidenceReference):
                continue
            linked_attempts = tuple(
                attempt_ref
                for attempt_ref in attempts
                if attempt_ref.attempt_id == coverage_ref.attempt_id
            )
            if len(linked_attempts) != 1:
                raise ValueError(
                    "Coverage evidence requires its matching Provider Attempt reference."
                )
            attempt_ref = linked_attempts[0]
            if (attempt_ref.scope_id, attempt_ref.capture_id, attempt_ref.capture_digest) != (
                coverage_ref.scope_id,
                coverage_ref.capture_id,
                coverage_ref.capture_digest,
            ):
                raise ValueError("Coverage evidence scope and capture must match its attempt.")
        for capture_ref in captures:
            if capture_ref.source_lineage_id != self.provider.source_lineage_id:
                raise ValueError("Source Capture lineage must match the provider lineage.")
            linked_attempts = tuple(
                attempt_ref
                for attempt_ref in attempts
                if attempt_ref.capture_id == capture_ref.capture_id
            )
            linked_coverage = tuple(
                coverage_ref
                for coverage_ref in coverage
                if coverage_ref.capture_id == capture_ref.capture_id
            )
            if not linked_attempts and not linked_coverage:
                raise ValueError(
                    "Source Capture reference must match a referenced attempt/evidence."
                )
            for linked_attempt in linked_attempts:
                if linked_attempt.capture_digest != capture_ref.capture_digest:
                    raise ValueError(
                        "Source Capture ID and digest must match its evidence reference."
                    )
            for linked_coverage_ref in linked_coverage:
                if linked_coverage_ref.capture_digest != capture_ref.capture_digest:
                    raise ValueError(
                        "Source Capture ID and digest must match its evidence reference."
                    )
        for assertion_ref in assertions:
            if not any(
                capture_ref.capture_id == assertion_ref.capture_id for capture_ref in captures
            ):
                raise ValueError("Source Assertion requires its matching Source Capture reference.")
        for evidence_ref in basis.references:
            if (
                isinstance(evidence_ref, ProviderMetadataReference)
                and (
                    evidence_ref.provider_id,
                    evidence_ref.capability_id,
                )
                != expected_identity[:2]
            ):
                raise ValueError("Provider metadata reference must match provider/capability.")
            if (
                isinstance(evidence_ref, FreshnessEvidenceReference)
                and (
                    evidence_ref.provider_id,
                    evidence_ref.capability_id,
                    evidence_ref.scope_id,
                )
                != expected_identity
            ):
                raise ValueError(
                    "Freshness evidence reference must match record identity and scope."
                )
            if (
                isinstance(evidence_ref, OtherVersionedEvidenceReference)
                and (
                    evidence_ref.provider_id,
                    evidence_ref.capability_id,
                    evidence_ref.scope_id,
                )
                != expected_identity
            ):
                raise ValueError(
                    "Versioned evidence reference must match record identity and scope."
                )
            if (
                isinstance(evidence_ref, CapabilityCoverageEvidenceReference)
                and (
                    evidence_ref.provider_id,
                    evidence_ref.capability_id,
                    evidence_ref.scope_id,
                )
                != expected_identity
            ):
                raise ValueError(
                    "Capability coverage evidence must match record identity and scope."
                )

    def _validate_coverage_reference(self, evidence: CoverageEvidenceReference) -> None:
        expected_identity = (
            self.provider.provider_id,
            self.capability.capability_id,
            self.requested_scope.evidence_scope_id,
        )
        if (evidence.provider_id, evidence.capability_id, evidence.scope_id) != expected_identity:
            raise ValueError("Coverage evidence must match the record provider/capability/scope.")
        if isinstance(evidence, CapabilityCoverageEvidenceReference):
            return
        fixture_scope = self.requested_scope.fixture_scope
        if fixture_scope is None:
            raise ValueError("F01 coverage requires its typed FixtureScope reference.")
        competition = self.requested_scope.competition
        season = self.requested_scope.season
        if (
            competition.state is ScopeFacetState.KNOWN
            and competition.value is not None
            and evidence.provider_competition_key != competition.value.provider_key
        ):
            raise ValueError("Coverage evidence competition must match requested scope.")
        if (
            season.state is ScopeFacetState.KNOWN
            and season.value is not None
            and evidence.provider_season != season.value.provider_value
        ):
            raise ValueError("Coverage evidence season must match requested scope.")
        if evidence.bounds_start_utc is not None:
            requested_time = self.requested_scope.time
            if requested_time.state is ScopeFacetState.KNOWN:
                requested_interval = fixture_scope.interval
                if evidence.bounds_end_utc is None:
                    raise ValueError("Coverage evidence bounds require both endpoints.")
                evidence_interval = UtcInterval(evidence.bounds_start_utc, evidence.bounds_end_utc)
                if (
                    evidence_interval.start_utc < requested_interval.start_utc
                    or evidence_interval.end_utc > requested_interval.end_utc
                ):
                    raise ValueError("Coverage evidence bounds fall outside requested time scope.")

    def _validate_coverage_state_scope(self) -> None:
        state = self.coverage.state
        witness = self.coverage.witness
        if (
            state
            not in (
                CoverageState.COMPLETE,
                CoverageState.CONFIRMED_EMPTY,
                CoverageState.PARTIAL,
            )
            or witness is None
        ):
            return
        generic = tuple(
            evidence
            for evidence in witness.evidence
            if isinstance(evidence, CapabilityCoverageEvidenceReference)
        )
        f01 = tuple(
            evidence
            for evidence in witness.evidence
            if isinstance(evidence, ProviderCoverageEvidenceReference)
        )
        fixture_scope = self.requested_scope.fixture_scope
        requested_interval = None if fixture_scope is None else fixture_scope.interval

        def f01_closes_scope(
            evidence: ProviderCoverageEvidenceReference,
        ) -> bool:
            return (
                evidence.coverage_basis_id is not None
                and evidence.pagination_exhausted
                and evidence.required_partition_ids == evidence.accounted_partition_ids
            )

        def f01_ranges(*, empty_only: bool = False) -> tuple[UtcInterval, ...]:
            return tuple(
                UtcInterval(evidence.bounds_start_utc, evidence.bounds_end_utc)
                for evidence in f01
                if f01_closes_scope(evidence)
                and evidence.bounds_start_utc is not None
                and evidence.bounds_end_utc is not None
                and (not empty_only or evidence.affirmatively_empty)
            )

        if requested_interval is None:
            f01_full_scope = any(f01_closes_scope(evidence) for evidence in f01)
            f01_empty_scope = any(
                evidence.affirmatively_empty and f01_closes_scope(evidence) for evidence in f01
            )
            f01_partial_support = any(
                evidence.bounds_start_utc is not None
                or evidence.required_partition_ids != evidence.accounted_partition_ids
                for evidence in f01
            )
        else:
            f01_full_scope = _intervals_cover(requested_interval, f01_ranges())
            f01_empty_scope = _intervals_cover(requested_interval, f01_ranges(empty_only=True))
            f01_partial_support = (
                any(
                    evidence.required_partition_ids != evidence.accounted_partition_ids
                    or (
                        evidence.bounds_start_utc is not None
                        and evidence.bounds_end_utc is not None
                        and _intervals_intersect(
                            requested_interval,
                            UtcInterval(evidence.bounds_start_utc, evidence.bounds_end_utc),
                        )
                    )
                    for evidence in f01
                )
                and not f01_full_scope
            )

        generic_full_scope = any(
            evidence.scope_complete
            and evidence.enumeration_complete
            and evidence.required_partition_ids == evidence.accounted_partition_ids
            for evidence in generic
        )
        generic_empty_scope = any(
            evidence.affirmatively_empty
            and evidence.scope_complete
            and evidence.enumeration_complete
            and evidence.required_partition_ids == evidence.accounted_partition_ids
            for evidence in generic
        )
        generic_partial_support = any(evidence.has_partial_extent_or_gap for evidence in generic)
        has_full_scope = generic_full_scope or f01_full_scope
        if state is CoverageState.COMPLETE and not has_full_scope:
            raise ValueError("COMPLETE evidence must close the requested time and query scope.")
        if state is CoverageState.CONFIRMED_EMPTY and not (generic_empty_scope or f01_empty_scope):
            raise ValueError(
                "CONFIRMED_EMPTY requires affirmative evidence that closes the requested scope."
            )
        if state is CoverageState.PARTIAL and (
            has_full_scope or not (generic_partial_support or f01_partial_support)
        ):
            raise ValueError(
                "PARTIAL evidence must show covered scope or a known gap "
                "without full scope closure."
            )

    @classmethod
    def create(
        cls,
        *,
        provider: ProviderIdentity,
        capability: CapabilityIdentity,
        requested_scope: RequestedScope,
        intended_use_id: str,
        checked_at_utc: str,
        use_permission: UsePermissionAssessment,
        reachability: ReachabilityAssessment,
        capability_availability: CapabilityAvailabilityAssessment,
        structural_validity: StructuralValidityAssessment,
        freshness: FreshnessAssessment,
        coverage: CoverageAssessment,
        failure: FailureAssessment,
        provenance: tuple[EvidenceReference, ...] = (),
    ) -> ProviderHealthRecord:
        return cls(
            provider=provider,
            capability=capability,
            requested_scope=requested_scope,
            intended_use_id=intended_use_id,
            checked_at_utc=checked_at_utc,
            use_permission=use_permission,
            reachability=reachability,
            capability_availability=capability_availability,
            structural_validity=structural_validity,
            freshness=freshness,
            coverage=coverage,
            failure=failure,
            provenance=provenance,
        )


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, FailureReasonCode):
        return value.value
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(
        value,
        (
            ProviderAttemptReference,
            ProviderCoverageEvidenceReference,
            CapabilityCoverageEvidenceReference,
            FixtureCoverageAssessmentReference,
            SourceCaptureReference,
            SourceAssertionReference,
            ProviderMetadataReference,
            FreshnessEvidenceReference,
            OtherVersionedEvidenceReference,
        ),
    ):
        result = {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
        result["reference_kind"] = value.reference_kind.value
        return result
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Unsupported provider health value: {type(value).__name__}")


def _scope_payload(scope: RequestedScope) -> dict[str, object]:
    return cast(dict[str, object], _json_value(scope))


def _record_payload(record: ProviderHealthRecord) -> dict[str, object]:
    return {
        item.name: _json_value(getattr(record, item.name))
        for item in fields(record)
        if item.name != "digest"
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def provider_health_record_to_canonical_json(record: ProviderHealthRecord) -> str:
    """Return a complete provider health record in canonical JSON form."""
    if not isinstance(record, ProviderHealthRecord):
        raise TypeError("Expected a ProviderHealthRecord.")
    return _canonical_json(_json_value(record))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderHealthPayloadError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _object(value: object, keys: tuple[str, ...], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProviderHealthPayloadError(f"{label} must be an object.")
    if set(value) != set(keys):
        raise ProviderHealthPayloadError(f"{label} has missing or unsupported fields.")
    return cast(dict[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ProviderHealthPayloadError(f"{label} must be a string.")
    return value


def _enum(enum_type: type[StrEnum], value: object, label: str) -> StrEnum:
    raw = _string(value, label)
    try:
        return enum_type(raw)
    except ValueError as error:
        raise ProviderHealthPayloadError(f"{label} has an unsupported state.") from error


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ProviderHealthPayloadError(f"{label} must be an array.")
    return cast(list[object], value)


def _facet[T](
    value: object,
    label: str,
    parse_known: Callable[[object], T],
) -> ScopeFacet[T]:
    item = _object(value, ("state", "value"), label)
    state = cast(ScopeFacetState, _enum(ScopeFacetState, item["state"], f"{label} state"))
    raw_value = item["value"]
    if state is ScopeFacetState.KNOWN:
        return ScopeFacet.known(parse_known(raw_value))
    if raw_value is not None:
        raise ProviderHealthPayloadError(f"Non-KNOWN {label} must not carry a value.")
    return ScopeFacet(state)


def _competition_from_json(value: object) -> CompetitionScope:
    item = _object(value, ("competition_id", "provider_key"), "Competition scope")
    return CompetitionScope(
        competition_id=_string(item["competition_id"], "competition_id"),
        provider_key=_string(item["provider_key"], "provider_key"),
    )


def _season_from_json(value: object) -> SeasonScope:
    item = _object(value, ("season_id", "provider_value"), "Season scope")
    return SeasonScope(
        season_id=_string(item["season_id"], "season_id"),
        provider_value=_string(item["provider_value"], "provider_value"),
    )


def _time_scope_from_json(value: object) -> RequestedTimeScope:
    if not isinstance(value, dict):
        raise ProviderHealthPayloadError("Requested time scope must be an object.")
    if set(value) == {"start_utc", "end_utc"}:
        return UtcInterval(
            start_utc=_string(value["start_utc"], "start_utc"),
            end_utc=_string(value["end_utc"], "end_utc"),
        )
    if set(value) == {"start_date", "end_date_exclusive", "timezone_name"}:
        return LocalDateRange(
            start_date=_string(value["start_date"], "start_date"),
            end_date_exclusive=_string(value["end_date_exclusive"], "end_date_exclusive"),
            timezone_name=_string(value["timezone_name"], "timezone_name"),
        )
    raise ProviderHealthPayloadError("Requested time scope has an unsupported shape.")


def _fixture_scope_from_json(value: object) -> F01FixtureScopeReference:
    item = _object(
        value,
        (
            "league_key",
            "matchweek_friday",
            "scope_id",
            "season",
            "window_end_utc",
            "window_start_utc",
        ),
        "F01 FixtureScope reference",
    )
    try:
        return F01FixtureScopeReference.from_payload(
            league_key=_string(item["league_key"], "league_key"),
            season=_string(item["season"], "season"),
            matchweek_friday=_string(item["matchweek_friday"], "matchweek_friday"),
            scope_id=_string(item["scope_id"], "scope_id"),
            window_start_utc=_string(item["window_start_utc"], "window_start_utc"),
            window_end_utc=_string(item["window_end_utc"], "window_end_utc"),
        )
    except ValueError as error:
        raise ProviderHealthPayloadError("F01 FixtureScope reference is inconsistent.") from error


def _subject_from_json(value: object) -> SubjectIdentifier:
    item = _object(value, ("kind", "subject_id"), "Subject identifier")
    return SubjectIdentifier(
        kind=cast(SubjectKind, _enum(SubjectKind, item["kind"], "subject kind")),
        subject_id=_string(item["subject_id"], "subject_id"),
    )


def _selector_from_json(value: object) -> NamedSelectorFacet:
    item = _object(value, ("key", "facet"), "Named selector")
    facet = _facet(
        item["facet"],
        "selector facet",
        lambda raw: tuple(
            _string(entry, "selector value") for entry in _list(raw, "selector values")
        ),
    )
    return NamedSelectorFacet(key=_string(item["key"], "selector key"), facet=facet)


def _scope_from_json(value: object) -> RequestedScope:
    item = _object(
        value,
        (
            "competition",
            "fixture_scope",
            "scope_kind",
            "season",
            "selectors",
            "subjects",
            "time",
        ),
        "Requested scope",
    )
    return RequestedScope(
        scope_kind=_string(item["scope_kind"], "scope_kind"),
        competition=_facet(item["competition"], "competition facet", _competition_from_json),
        season=_facet(item["season"], "season facet", _season_from_json),
        time=_facet(item["time"], "time facet", _time_scope_from_json),
        subjects=_facet(
            item["subjects"],
            "subjects facet",
            lambda raw: tuple(_subject_from_json(entry) for entry in _list(raw, "subjects")),
        ),
        selectors=tuple(
            _selector_from_json(entry) for entry in _list(item["selectors"], "selectors")
        ),
        fixture_scope=(
            None
            if item["fixture_scope"] is None
            else _fixture_scope_from_json(item["fixture_scope"])
        ),
    )


def _scope_contract_from_json(value: object) -> ScopeContract:
    item = _object(
        value,
        ("competition", "coverage", "season", "selector_keys", "subjects", "time"),
        "Scope contract",
    )
    return ScopeContract(
        competition=cast(
            FacetApplicability,
            _enum(FacetApplicability, item["competition"], "competition applicability"),
        ),
        season=cast(
            FacetApplicability, _enum(FacetApplicability, item["season"], "season applicability")
        ),
        time=cast(
            FacetApplicability, _enum(FacetApplicability, item["time"], "time applicability")
        ),
        subjects=cast(
            FacetApplicability,
            _enum(FacetApplicability, item["subjects"], "subjects applicability"),
        ),
        selector_keys=tuple(
            _string(entry, "selector key")
            for entry in _list(item["selector_keys"], "selector_keys")
        ),
        coverage=cast(
            CoverageApplicability,
            _enum(CoverageApplicability, item["coverage"], "coverage applicability"),
        ),
    )


def _permission_policy_from_json(value: object) -> PermissionPolicyReference | None:
    if value is None:
        return None
    item = _object(value, ("intended_use_id", "policy_id", "version"), "Permission policy")
    return PermissionPolicyReference(
        policy_id=_string(item["policy_id"], "policy_id"),
        version=_string(item["version"], "version"),
        intended_use_id=_string(item["intended_use_id"], "intended_use_id"),
    )


def _freshness_policy_from_json(value: object) -> FreshnessPolicyReference | None:
    if value is None:
        return None
    item = _object(value, ("capability_id", "policy_id", "version"), "Freshness policy")
    return FreshnessPolicyReference(
        policy_id=_string(item["policy_id"], "policy_id"),
        version=_string(item["version"], "version"),
        capability_id=_string(item["capability_id"], "capability_id"),
    )


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProviderHealthPayloadError(f"{label} must be a boolean.")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(entry, label) for entry in _list(value, label))


def _evidence_reference_from_json(value: object) -> EvidenceReference:
    if not isinstance(value, dict) or "reference_kind" not in value:
        raise ProviderHealthPayloadError("Evidence reference must identify its type.")
    item = cast(dict[str, object], value)
    kind = cast(
        EvidenceReferenceKind,
        _enum(EvidenceReferenceKind, item["reference_kind"], "evidence reference kind"),
    )
    if kind is EvidenceReferenceKind.PROVIDER_ATTEMPT:
        fields = (
            "attempt_id",
            "capture_digest",
            "capture_id",
            "capability_id",
            "http_status",
            "provider_id",
            "retrieved_at_utc",
            "scope_id",
            "state",
        )
        parsed = _object(item, (*fields, "reference_kind"), "Provider Attempt reference")
        http_status = parsed["http_status"]
        if http_status is not None and (type(http_status) is not int):
            raise ProviderHealthPayloadError("Provider Attempt HTTP status must be an integer.")
        return ProviderAttemptReference(
            attempt_id=_string(parsed["attempt_id"], "attempt_id"),
            scope_id=_string(parsed["scope_id"], "scope_id"),
            provider_id=_string(parsed["provider_id"], "provider_id"),
            capability_id=_string(parsed["capability_id"], "capability_id"),
            state=cast(
                F01ProviderAttemptState,
                _enum(F01ProviderAttemptState, parsed["state"], "F01 attempt state"),
            ),
            retrieved_at_utc=_string(parsed["retrieved_at_utc"], "retrieved_at_utc"),
            http_status=http_status,
            capture_id=_optional_string(parsed["capture_id"], "capture_id"),
            capture_digest=_optional_string(parsed["capture_digest"], "capture_digest"),
        )
    if kind is EvidenceReferenceKind.PROVIDER_COVERAGE_EVIDENCE:
        coverage_keys = (
            "accounted_partition_ids",
            "affirmatively_empty",
            "attempt_id",
            "bounds_end_utc",
            "bounds_start_utc",
            "capability_id",
            "capture_digest",
            "capture_id",
            "coverage_basis_id",
            "coverage_basis_kind",
            "coverage_basis_version",
            "evidence_id",
            "pagination_exhausted",
            "permitted_for_use",
            "provider_competition_key",
            "provider_id",
            "provider_season",
            "provider_use_policy_id",
            "required_partition_ids",
            "scope_id",
        )
        parsed = _object(item, (*coverage_keys, "reference_kind"), "Coverage Evidence reference")
        return ProviderCoverageEvidenceReference(
            evidence_id=_string(parsed["evidence_id"], "evidence_id"),
            attempt_id=_string(parsed["attempt_id"], "attempt_id"),
            scope_id=_string(parsed["scope_id"], "scope_id"),
            provider_id=_string(parsed["provider_id"], "provider_id"),
            capability_id=_string(parsed["capability_id"], "capability_id"),
            provider_competition_key=_optional_string(
                parsed["provider_competition_key"], "provider_competition_key"
            ),
            provider_season=_optional_string(parsed["provider_season"], "provider_season"),
            capture_id=_string(parsed["capture_id"], "capture_id"),
            capture_digest=_string(parsed["capture_digest"], "capture_digest"),
            coverage_basis_id=_optional_string(parsed["coverage_basis_id"], "coverage_basis_id"),
            coverage_basis_kind=(
                None
                if parsed["coverage_basis_kind"] is None
                else cast(
                    F01CoverageBasisKind,
                    _enum(
                        F01CoverageBasisKind,
                        parsed["coverage_basis_kind"],
                        "coverage basis kind",
                    ),
                )
            ),
            coverage_basis_version=_optional_string(
                parsed["coverage_basis_version"], "coverage_basis_version"
            ),
            bounds_start_utc=_optional_string(parsed["bounds_start_utc"], "bounds_start_utc"),
            bounds_end_utc=_optional_string(parsed["bounds_end_utc"], "bounds_end_utc"),
            required_partition_ids=_string_tuple(
                parsed["required_partition_ids"], "required partition ID"
            ),
            accounted_partition_ids=_string_tuple(
                parsed["accounted_partition_ids"], "accounted partition ID"
            ),
            pagination_exhausted=_boolean(parsed["pagination_exhausted"], "pagination_exhausted"),
            provider_use_policy_id=_optional_string(
                parsed["provider_use_policy_id"], "provider_use_policy_id"
            ),
            permitted_for_use=_boolean(parsed["permitted_for_use"], "permitted_for_use"),
            affirmatively_empty=_boolean(parsed["affirmatively_empty"], "affirmatively_empty"),
        )
    if kind is EvidenceReferenceKind.CAPABILITY_COVERAGE_EVIDENCE:
        capability_coverage_keys = (
            "accounted_partition_ids",
            "affirmatively_empty",
            "capture_digest",
            "capture_id",
            "capability_id",
            "covered_extent_ids",
            "digest",
            "enumeration_complete",
            "evidence_id",
            "evidence_kind",
            "known_gap_ids",
            "provider_id",
            "required_partition_ids",
            "scope_complete",
            "scope_id",
            "version",
        )
        parsed = _object(
            item,
            (*capability_coverage_keys, "reference_kind"),
            "Capability Coverage Evidence reference",
        )
        return CapabilityCoverageEvidenceReference(
            evidence_id=_string(parsed["evidence_id"], "evidence_id"),
            evidence_kind=_string(parsed["evidence_kind"], "evidence_kind"),
            version=_string(parsed["version"], "version"),
            provider_id=_string(parsed["provider_id"], "provider_id"),
            capability_id=_string(parsed["capability_id"], "capability_id"),
            scope_id=_string(parsed["scope_id"], "scope_id"),
            digest=_string(parsed["digest"], "digest"),
            scope_complete=_boolean(parsed["scope_complete"], "scope_complete"),
            enumeration_complete=_boolean(parsed["enumeration_complete"], "enumeration_complete"),
            required_partition_ids=_string_tuple(
                parsed["required_partition_ids"], "required partition ID"
            ),
            accounted_partition_ids=_string_tuple(
                parsed["accounted_partition_ids"], "accounted partition ID"
            ),
            covered_extent_ids=_string_tuple(parsed["covered_extent_ids"], "covered extent ID"),
            known_gap_ids=_string_tuple(parsed["known_gap_ids"], "known gap ID"),
            affirmatively_empty=_boolean(parsed["affirmatively_empty"], "affirmatively_empty"),
            capture_id=_optional_string(parsed["capture_id"], "capture_id"),
            capture_digest=_optional_string(parsed["capture_digest"], "capture_digest"),
        )
    if kind is EvidenceReferenceKind.FIXTURE_COVERAGE_ASSESSMENT:
        assessment_keys = (
            "assessment_digest",
            "contract_version",
            "coverage_evidence_ids",
            "fixture_scope_id",
            "provider_attempt_ids",
            "schema_version",
            "scope_state",
        )
        parsed = _object(
            item,
            (*assessment_keys, "reference_kind"),
            "Fixture Coverage Assessment reference",
        )
        return FixtureCoverageAssessmentReference(
            assessment_digest=_string(parsed["assessment_digest"], "assessment_digest"),
            contract_version=_string(parsed["contract_version"], "contract_version"),
            schema_version=parsed["schema_version"]
            if type(parsed["schema_version"]) is int
            else cast(int, _raise_payload("schema_version must be an integer.")),
            fixture_scope_id=_string(parsed["fixture_scope_id"], "fixture_scope_id"),
            scope_state=_string(parsed["scope_state"], "scope_state"),
            provider_attempt_ids=_string_tuple(parsed["provider_attempt_ids"], "attempt ID"),
            coverage_evidence_ids=_string_tuple(
                parsed["coverage_evidence_ids"], "coverage evidence ID"
            ),
        )
    if kind is EvidenceReferenceKind.SOURCE_CAPTURE:
        keys = (
            "artifact_digest",
            "capture_digest",
            "capture_id",
            "content_digest",
            "source_id",
            "source_key",
            "source_lineage_id",
        )
        parsed = _object(item, (*keys, "reference_kind"), "Source Capture reference")
        return SourceCaptureReference(
            capture_id=_string(parsed["capture_id"], "capture_id"),
            source_key=_string(parsed["source_key"], "source_key"),
            source_id=_string(parsed["source_id"], "source_id"),
            source_lineage_id=_string(parsed["source_lineage_id"], "source_lineage_id"),
            capture_digest=_string(parsed["capture_digest"], "capture_digest"),
            content_digest=_optional_string(parsed["content_digest"], "content_digest"),
            artifact_digest=_optional_string(parsed["artifact_digest"], "artifact_digest"),
        )
    if kind is EvidenceReferenceKind.SOURCE_ASSERTION:
        parsed = _object(item, ("assertion_id", "capture_id", "reference_kind"), "Source Assertion")
        return SourceAssertionReference(
            assertion_id=_string(parsed["assertion_id"], "assertion_id"),
            capture_id=_string(parsed["capture_id"], "capture_id"),
        )
    if kind is EvidenceReferenceKind.PROVIDER_METADATA:
        parsed = _object(
            item,
            ("capability_id", "digest", "metadata_id", "provider_id", "reference_kind", "version"),
            "Provider Metadata reference",
        )
        return ProviderMetadataReference(
            metadata_id=_string(parsed["metadata_id"], "metadata_id"),
            version=_string(parsed["version"], "version"),
            provider_id=_string(parsed["provider_id"], "provider_id"),
            capability_id=_string(parsed["capability_id"], "capability_id"),
            digest=_optional_string(parsed["digest"], "digest"),
        )
    if kind is EvidenceReferenceKind.FRESHNESS_EVIDENCE:
        freshness_keys = (
            "capability_id",
            "digest",
            "evidence_id",
            "provider_id",
            "scope_id",
            "version",
        )
        parsed = _object(item, (*freshness_keys, "reference_kind"), "Freshness evidence reference")
        return FreshnessEvidenceReference(
            evidence_id=_string(parsed["evidence_id"], "evidence_id"),
            version=_string(parsed["version"], "version"),
            provider_id=_string(parsed["provider_id"], "provider_id"),
            capability_id=_string(parsed["capability_id"], "capability_id"),
            scope_id=_string(parsed["scope_id"], "scope_id"),
            digest=_string(parsed["digest"], "digest"),
        )
    other_evidence_keys = (
        "capability_id",
        "digest",
        "evidence_id",
        "evidence_kind",
        "provider_id",
        "scope_id",
        "version",
    )
    parsed = _object(item, (*other_evidence_keys, "reference_kind"), "Versioned evidence reference")
    return OtherVersionedEvidenceReference(
        evidence_id=_string(parsed["evidence_id"], "evidence_id"),
        evidence_kind=_string(parsed["evidence_kind"], "evidence_kind"),
        version=_string(parsed["version"], "version"),
        provider_id=_string(parsed["provider_id"], "provider_id"),
        capability_id=_string(parsed["capability_id"], "capability_id"),
        scope_id=_string(parsed["scope_id"], "scope_id"),
        digest=_string(parsed["digest"], "digest"),
    )


def _raise_payload(message: str) -> object:
    raise ProviderHealthPayloadError(message)


def _evidence_basis_from_json(value: object) -> EvidenceBasis | None:
    if value is None:
        return None
    item = _object(
        value,
        ("capability_id", "provider_id", "references", "scope_id", "source_as_of_utc"),
        "Evidence basis",
    )
    return EvidenceBasis(
        provider_id=_string(item["provider_id"], "provider_id"),
        capability_id=_string(item["capability_id"], "capability_id"),
        scope_id=_string(item["scope_id"], "scope_id"),
        references=tuple(
            _evidence_reference_from_json(entry)
            for entry in _list(item["references"], "evidence references")
        ),
        source_as_of_utc=_optional_string(item["source_as_of_utc"], "source_as_of_utc"),
    )


def _evidence_references_from_json(value: object) -> tuple[EvidenceReference, ...]:
    return tuple(
        _evidence_reference_from_json(entry) for entry in _list(value, "evidence references")
    )


def _coverage_witness_from_json(value: object) -> CoverageWitness | None:
    if value is None:
        return None
    item = _object(
        value,
        ("attempts", "capability_id", "evidence", "provider_id", "scope_id"),
        "Coverage witness",
    )
    evidence: list[CoverageEvidenceReference] = []
    for entry in _list(item["evidence"], "coverage evidence"):
        parsed = _evidence_reference_from_json(entry)
        if not isinstance(
            parsed, (ProviderCoverageEvidenceReference, CapabilityCoverageEvidenceReference)
        ):
            raise ProviderHealthPayloadError(
                "Coverage witness requires typed capability coverage evidence."
            )
        evidence.append(parsed)
    attempts: list[ProviderAttemptReference] = []
    for entry in _list(item["attempts"], "coverage attempts"):
        parsed = _evidence_reference_from_json(entry)
        if not isinstance(parsed, ProviderAttemptReference):
            raise ProviderHealthPayloadError(
                "Coverage witness requires Provider Attempt references."
            )
        attempts.append(parsed)
    return CoverageWitness(
        provider_id=_string(item["provider_id"], "provider_id"),
        capability_id=_string(item["capability_id"], "capability_id"),
        scope_id=_string(item["scope_id"], "scope_id"),
        evidence=tuple(evidence),
        attempts=tuple(attempts),
    )


def _identity_from_json(value: object) -> ProviderIdentity:
    item = _object(value, ("provider_id", "source_lineage_id"), "Provider identity")
    return ProviderIdentity(
        provider_id=_string(item["provider_id"], "provider_id"),
        source_lineage_id=_string(item["source_lineage_id"], "source_lineage_id"),
    )


def _capability_from_json(value: object) -> CapabilityIdentity:
    item = _object(value, ("capability_id", "scope_contract"), "Capability identity")
    return CapabilityIdentity(
        capability_id=_string(item["capability_id"], "capability_id"),
        scope_contract=_scope_contract_from_json(item["scope_contract"]),
    )


def _assessment_fields(
    value: object,
    label: str,
    keys: tuple[str, ...] = ("evidence", "state"),
) -> dict[str, object]:
    return _object(value, keys, label)


def _assessment_evidence_from_json(
    value: object,
    label: str,
    keys: tuple[str, ...] = ("evidence", "state"),
) -> EvidenceBasis | None:
    item = _assessment_fields(value, label, keys)
    return _evidence_basis_from_json(item["evidence"])


def _failure_reason_codes_from_json(value: object) -> tuple[FailureReasonCode, ...]:
    item = _object(value, ("evidence", "reason_codes", "state"), "Failure assessment")
    return tuple(
        FailureReasonCode(_string(raw, "failure reason code"))
        for raw in _list(item["reason_codes"], "failure reason codes")
    )


def _state_from_assessment(
    value: object,
    label: str,
    state_type: type[StrEnum],
    keys: tuple[str, ...] = ("evidence", "state"),
) -> StrEnum:
    return _enum(state_type, _assessment_fields(value, label, keys)["state"], f"{label} state")


def _record_from_json(value: object) -> ProviderHealthRecord:
    item = _object(
        value,
        (
            "capability",
            "capability_availability",
            "checked_at_utc",
            "contract_version",
            "coverage",
            "digest",
            "failure",
            "freshness",
            "intended_use_id",
            "provider",
            "provenance",
            "reachability",
            "requested_scope",
            "schema_version",
            "structural_validity",
            "use_permission",
        ),
        "Provider Health Record",
    )
    if _string(item["contract_version"], "contract_version") != PROVIDER_HEALTH_CONTRACT_VERSION:
        raise ProviderHealthPayloadError("Unsupported Provider Health contract version.")
    schema_version = item["schema_version"]
    if type(schema_version) is not int or schema_version != PROVIDER_HEALTH_SCHEMA_VERSION:
        raise ProviderHealthPayloadError("Unsupported Provider Health schema version.")
    record = ProviderHealthRecord.create(
        provider=_identity_from_json(item["provider"]),
        capability=_capability_from_json(item["capability"]),
        requested_scope=_scope_from_json(item["requested_scope"]),
        intended_use_id=_string(item["intended_use_id"], "intended_use_id"),
        checked_at_utc=_string(item["checked_at_utc"], "checked_at_utc"),
        provenance=_evidence_references_from_json(item["provenance"]),
        use_permission=_use_permission_from_json(item["use_permission"]),
        reachability=ReachabilityAssessment(
            cast(
                ReachabilityState,
                _state_from_assessment(item["reachability"], "reachability", ReachabilityState),
            ),
            evidence=_assessment_evidence_from_json(item["reachability"], "reachability"),
        ),
        capability_availability=CapabilityAvailabilityAssessment(
            cast(
                CapabilityAvailabilityState,
                _state_from_assessment(
                    item["capability_availability"],
                    "capability_availability",
                    CapabilityAvailabilityState,
                ),
            ),
            evidence=_assessment_evidence_from_json(
                item["capability_availability"], "capability_availability"
            ),
        ),
        structural_validity=StructuralValidityAssessment(
            cast(
                StructuralValidityState,
                _state_from_assessment(
                    item["structural_validity"],
                    "structural_validity",
                    StructuralValidityState,
                ),
            ),
            evidence=_assessment_evidence_from_json(
                item["structural_validity"], "structural_validity"
            ),
        ),
        freshness=FreshnessAssessment(
            cast(
                FreshnessState,
                _state_from_assessment(
                    item["freshness"], "freshness", FreshnessState, ("evidence", "policy", "state")
                ),
            ),
            policy=_freshness_policy_from_json(
                _assessment_fields(item["freshness"], "freshness", ("evidence", "policy", "state"))[
                    "policy"
                ]
            ),
            evidence=_assessment_evidence_from_json(
                item["freshness"], "freshness", ("evidence", "policy", "state")
            ),
        ),
        coverage=CoverageAssessment(
            cast(
                CoverageState,
                _state_from_assessment(
                    item["coverage"], "coverage", CoverageState, ("state", "witness")
                ),
            ),
            witness=_coverage_witness_from_json(
                _object(item["coverage"], ("state", "witness"), "Coverage assessment")["witness"]
            ),
        ),
        failure=FailureAssessment(
            cast(
                FailureState,
                _state_from_assessment(
                    item["failure"], "failure", FailureState, ("evidence", "reason_codes", "state")
                ),
            ),
            reason_codes=_failure_reason_codes_from_json(item["failure"]),
            evidence=_assessment_evidence_from_json(
                item["failure"], "failure", ("evidence", "reason_codes", "state")
            ),
        ),
    )
    if _string(item["digest"], "digest") != record.digest:
        raise ProviderHealthPayloadError(
            "Provider Health Record digest does not match its contents."
        )
    return record


def _use_permission_from_json(value: object) -> UsePermissionAssessment:
    item = _object(value, ("policy", "state"), "Use permission assessment")
    return UsePermissionAssessment(
        state=cast(
            UsePermissionState,
            _enum(UsePermissionState, item["state"], "use permission state"),
        ),
        policy=_permission_policy_from_json(item["policy"]),
    )


def provider_health_record_from_canonical_json(encoded: str) -> ProviderHealthRecord:
    """Rebuild a record only when its complete payload is canonical and self-consistent."""
    try:
        raw = json.loads(encoded, object_pairs_hook=_unique_object)
        if _canonical_json(raw) != encoded:
            raise ProviderHealthPayloadError("Provider Health payload is not canonical JSON.")
        record = _record_from_json(raw)
        if provider_health_record_to_canonical_json(record) != encoded:
            raise ProviderHealthPayloadError("Provider Health payload is not in normalized form.")
        return record
    except ProviderHealthPayloadError:
        raise
    except (TypeError, ValueError, KeyError) as error:
        raise ProviderHealthPayloadError("Provider Health payload is invalid.") from error

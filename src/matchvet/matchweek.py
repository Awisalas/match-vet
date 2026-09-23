"""T05 frozen Matchweek membership and post-cutoff fixture handling.

This module deliberately stops at schedule state.  It does not acquire source
evidence, build an Evidence State, calculate a prediction, vet a preference, or
publish a recommendation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from matchvet.artifacts import (
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestVersion,
    SnapshotManifest,
)
from matchvet.ingestion import deterministic_identifier
from matchvet.runs import (
    MIB,
    SETTLED_RESOURCE_BUDGET,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunPhase,
    RunStatus,
    WorkContext,
    WorkResult,
)
from matchvet.store import MIGRATIONS, CanonicalIdentifier, Store, VersionIdentity

try:
    AFRICA_LAGOS: tzinfo = ZoneInfo("Africa/Lagos")
except ZoneInfoNotFoundError:
    # Africa/Lagos has a fixed UTC+01:00 offset.  The fallback keeps the
    # local-first CLI usable on minimal Termux images without the tzdata wheel.
    AFRICA_LAGOS = timezone(timedelta(hours=1), "Africa/Lagos")
MATCHWEEK_TIMEZONE = "Africa/Lagos"
MATCHWEEK_LEAD_TIME = timedelta(hours=6)
MATCHWEEK_LEAD_TIME_SECONDS = int(MATCHWEEK_LEAD_TIME.total_seconds())
MATCHWEEK_RULES_NAME = "t05-v1"
MATCHWEEK_RULES_KIND = "matchweek_membership"
MATCHWEEK_MANIFEST_SCHEMA_VERSION = 1


class MembershipState(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    INDETERMINATE = "INDETERMINATE"


class AppendixEventKind(StrEnum):
    FIXTURE_ADDED_AFTER_CUTOFF = "FIXTURE_ADDED_AFTER_CUTOFF"
    MOVED_IN_AFTER_CUTOFF = "MOVED_IN_AFTER_CUTOFF"
    SAME_WINDOW_KICKOFF_CHANGE = "SAME_WINDOW_KICKOFF_CHANGE"
    MOVED_OUTSIDE_WINDOW = "MOVED_OUTSIDE_WINDOW"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    INVALID_PREMATCH_TIMING = "INVALID_PREMATCH_TIMING"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    REVISION_LEARNED_AFTER_CUTOFF = "REVISION_LEARNED_AFTER_CUTOFF"


class AppendixDisposition(StrEnum):
    APPENDIX_ONLY = "APPENDIX_ONLY"
    PRESERVED = "PRESERVED"
    WITHDRAWN = "WITHDRAWN"


class MatchweekError(Exception):
    """A deterministic T05 refusal or integrity failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_utc(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(
                "Timestamp must be an ISO-8601 value with a timezone offset."
            ) from error
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _date_value(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(AFRICA_LAGOS).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Matchweek Friday must use YYYY-MM-DD.") from error


@dataclass(frozen=True)
class MatchweekWindow:
    """The inclusive-Friday/exclusive-Tuesday calendar window."""

    friday_local: date

    def __post_init__(self) -> None:
        if self.friday_local.weekday() != 4:
            raise ValueError("Matchweek boundaries must start on Friday.")

    @classmethod
    def for_friday(cls, value: date | datetime | str) -> MatchweekWindow:
        return cls(_date_value(value))

    @property
    def start_local(self) -> datetime:
        return datetime.combine(self.friday_local, time.min, AFRICA_LAGOS)

    @property
    def end_local(self) -> datetime:
        return self.start_local + timedelta(days=4)

    @property
    def start_utc(self) -> str:
        return self.start_local.astimezone(UTC).isoformat(timespec="microseconds")

    @property
    def end_utc(self) -> str:
        return self.end_local.astimezone(UTC).isoformat(timespec="microseconds")

    def contains(self, value: str | datetime) -> bool:
        instant = _parse_utc(value) if isinstance(value, str) else value.astimezone(UTC)
        return self.start_local.astimezone(UTC) <= instant < self.end_local.astimezone(UTC)


@dataclass(frozen=True)
class MatchweekResearchCutoff:
    cutoff_id: str
    matchweek_id: str
    cutoff_utc: str
    earliest_included_fixture_id: str
    earliest_included_kickoff_utc: str
    lead_time_seconds: int = MATCHWEEK_LEAD_TIME_SECONDS
    digest: str = ""

    def __post_init__(self) -> None:
        cutoff = _canonical_utc(self.cutoff_utc)
        kickoff = _canonical_utc(self.earliest_included_kickoff_utc)
        if cutoff != self.cutoff_utc or kickoff != self.earliest_included_kickoff_utc:
            raise ValueError("Research Cutoff timestamps must be canonical UTC values.")
        if self.lead_time_seconds != MATCHWEEK_LEAD_TIME_SECONDS:
            raise ValueError("The T05 Matchweek Research Cutoff lead time is six hours.")
        expected = _sha256(
            _canonical_json(
                {
                    "cutoff_id": self.cutoff_id,
                    "cutoff_utc": self.cutoff_utc,
                    "earliest_included_fixture_id": self.earliest_included_fixture_id,
                    "earliest_included_kickoff_utc": self.earliest_included_kickoff_utc,
                    "lead_time_seconds": self.lead_time_seconds,
                    "matchweek_id": self.matchweek_id,
                }
            )
        )
        if self.digest and self.digest != expected:
            raise ValueError("Research Cutoff digest does not match its immutable fields.")
        object.__setattr__(self, "digest", expected)


@dataclass(frozen=True)
class FrozenMembership:
    membership_id: str
    matchweek_id: str
    subject_kind: str
    subject_id: str
    membership_state: MembershipState
    target_match: bool
    controlling_revision_id: str | None
    controlling_revision_digest: str | None
    source_authority_rank: int
    source_authority: str
    original_kickoff_utc: str | None
    original_kickoff_local_text: str | None
    material_conflict: bool
    conflict_predicates: tuple[str, ...]
    reason_code: str
    reason: str
    decision_state: str
    digest: str = ""

    def __post_init__(self) -> None:
        if self.subject_kind not in {"FIXTURE", "UNRESOLVED_FIXTURE_ROW"}:
            raise ValueError("Frozen membership subject kind is invalid.")
        if self.membership_state is MembershipState.INCLUDED and not self.target_match:
            raise ValueError("INCLUDED membership must be a Target Match.")
        if self.membership_state is not MembershipState.INCLUDED and self.target_match:
            raise ValueError("Only INCLUDED membership can be a Target Match.")
        if (self.controlling_revision_id is None) != (self.controlling_revision_digest is None):
            raise ValueError("A controlling Fixture Revision requires both ID and digest.")
        if tuple(sorted(set(self.conflict_predicates))) != self.conflict_predicates:
            raise ValueError("Membership conflict predicates must be sorted and unique.")
        if self.original_kickoff_utc is not None:
            canonical = _canonical_utc(self.original_kickoff_utc)
            if canonical != self.original_kickoff_utc:
                raise ValueError("Membership kickoff timestamps must be canonical UTC values.")
        expected = _sha256(_canonical_json(self._payload()))
        if self.digest and self.digest != expected:
            raise ValueError("Frozen membership digest does not match its immutable fields.")
        object.__setattr__(self, "digest", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "conflict_predicates": list(self.conflict_predicates),
            "controlling_revision_digest": self.controlling_revision_digest,
            "controlling_revision_id": self.controlling_revision_id,
            "decision_state": self.decision_state,
            "matchweek_id": self.matchweek_id,
            "material_conflict": self.material_conflict,
            "membership_id": self.membership_id,
            "membership_state": self.membership_state.value,
            "original_kickoff_local_text": self.original_kickoff_local_text,
            "original_kickoff_utc": self.original_kickoff_utc,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "source_authority": self.source_authority,
            "source_authority_rank": self.source_authority_rank,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "target_match": self.target_match,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FrozenMembership:
        conflict_predicates = value.get("conflict_predicates")
        if not isinstance(conflict_predicates, list) or not all(
            isinstance(item, str) for item in conflict_predicates
        ):
            raise MatchweekError(
                "MV-T05-MANIFEST_MALFORMED", "Membership conflict predicates are invalid."
            )
        return cls(
            membership_id=_string(value, "membership_id"),
            matchweek_id=_string(value, "matchweek_id"),
            subject_kind=_string(value, "subject_kind"),
            subject_id=_string(value, "subject_id"),
            membership_state=MembershipState(_string(value, "membership_state")),
            target_match=_bool(value, "target_match"),
            controlling_revision_id=_optional_string(value, "controlling_revision_id"),
            controlling_revision_digest=_optional_string(value, "controlling_revision_digest"),
            source_authority_rank=_int(value, "source_authority_rank"),
            source_authority=_string(value, "source_authority"),
            original_kickoff_utc=_optional_string(value, "original_kickoff_utc"),
            original_kickoff_local_text=_optional_string(value, "original_kickoff_local_text"),
            material_conflict=_bool(value, "material_conflict"),
            conflict_predicates=tuple(conflict_predicates),
            reason_code=_string(value, "reason_code"),
            reason=_string(value, "reason"),
            decision_state=_string(value, "decision_state"),
            digest=_string(value, "digest"),
        )


@dataclass(frozen=True)
class PostCutoffValidityReview:
    """The binary T05 validity gate for preserving a frozen decision."""

    identity_unchanged: bool | None = None
    scope_unchanged: bool | None = None
    kickoff_after_cutoff: bool | None = None
    no_postponement_or_cancellation: bool | None = None
    pre_match_valid: bool | None = None
    critical_evidence_valid: bool | None = None
    research_sufficiency_valid: bool | None = None
    information_boundary_valid: bool | None = None

    @property
    def passed(self) -> bool:
        return all(
            value is True
            for value in (
                self.identity_unchanged,
                self.scope_unchanged,
                self.kickoff_after_cutoff,
                self.no_postponement_or_cancellation,
                self.pre_match_valid,
                self.critical_evidence_valid,
                self.research_sufficiency_valid,
                self.information_boundary_valid,
            )
        )

    def to_dict(self) -> dict[str, bool | None]:
        return {
            "critical_evidence_valid": self.critical_evidence_valid,
            "identity_unchanged": self.identity_unchanged,
            "information_boundary_valid": self.information_boundary_valid,
            "kickoff_after_cutoff": self.kickoff_after_cutoff,
            "no_postponement_or_cancellation": self.no_postponement_or_cancellation,
            "pre_match_valid": self.pre_match_valid,
            "research_sufficiency_valid": self.research_sufficiency_valid,
            "scope_unchanged": self.scope_unchanged,
        }


@dataclass(frozen=True)
class PostCutoffFixtureAppendixEntry:
    appendix_id: str
    event_key: str
    matchweek_id: str
    subject_kind: str
    subject_id: str
    fixture_id: str | None
    membership_id: str | None
    revision_id: str | None
    revision_digest: str | None
    event_kind: AppendixEventKind
    disposition: AppendixDisposition
    settlement_result: str | None
    original_kickoff_utc: str | None
    current_kickoff_utc: str | None
    observed_at_utc: str
    validity_review: PostCutoffValidityReview
    reason_code: str
    reason: str
    digest: str = ""

    def __post_init__(self) -> None:
        if self.disposition is AppendixDisposition.WITHDRAWN:
            if self.settlement_result != "VOID":
                raise ValueError("Withdrawn appendix entries must have a VOID settlement state.")
        elif self.settlement_result is not None:
            raise ValueError("Only withdrawn appendix entries can have a settlement state.")
        for timestamp in (
            self.original_kickoff_utc,
            self.current_kickoff_utc,
            self.observed_at_utc,
        ):
            if timestamp is not None and _canonical_utc(timestamp) != timestamp:
                raise ValueError("Appendix timestamps must be canonical UTC values.")
        expected = _sha256(_canonical_json(self._payload()))
        if self.digest and self.digest != expected:
            raise ValueError("Appendix entry digest does not match its immutable fields.")
        object.__setattr__(self, "digest", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "current_kickoff_utc": self.current_kickoff_utc,
            "event_key": self.event_key,
            "event_kind": self.event_kind.value,
            "fixture_id": self.fixture_id,
            "matchweek_id": self.matchweek_id,
            "membership_id": self.membership_id,
            "observed_at_utc": self.observed_at_utc,
            "original_kickoff_utc": self.original_kickoff_utc,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "revision_digest": self.revision_digest,
            "revision_id": self.revision_id,
            "settlement_result": self.settlement_result,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "validity_review": self.validity_review.to_dict(),
            "disposition": self.disposition.value,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["appendix_id"] = self.appendix_id
        payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class MembershipManifest:
    """The deterministic T05 artifact containing frozen membership."""

    matchweek_id: str
    season: str
    friday_local: str
    window_start_utc: str
    window_end_utc: str
    cutoff_id: str
    cutoff_utc: str
    memberships: tuple[FrozenMembership, ...]
    rules_version: str = MATCHWEEK_RULES_NAME
    schema_version: int = MATCHWEEK_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATCHWEEK_MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported T05 membership manifest schema.")
        if tuple(item.membership_id for item in self.memberships) != tuple(
            sorted(item.membership_id for item in self.memberships)
        ):
            raise ValueError("Membership manifest entries must be sorted by immutable ID.")
        if len({item.membership_id for item in self.memberships}) != len(self.memberships):
            raise ValueError("Membership manifest entries must be unique.")
        for timestamp in (self.window_start_utc, self.window_end_utc, self.cutoff_utc):
            if _canonical_utc(timestamp) != timestamp:
                raise ValueError("Membership manifest timestamps must be canonical UTC values.")

    def _payload(self) -> dict[str, object]:
        return {
            "cutoff_id": self.cutoff_id,
            "cutoff_utc": self.cutoff_utc,
            "friday_local": self.friday_local,
            "matchweek_id": self.matchweek_id,
            "memberships": [item.to_dict() for item in self.memberships],
            "rules_version": self.rules_version,
            "schema_version": self.schema_version,
            "season": self.season,
            "window_end_utc": self.window_end_utc,
            "window_start_utc": self.window_start_utc,
        }

    @property
    def aggregate_sha256(self) -> str:
        return _sha256(_canonical_json(self._payload()))

    def to_bytes(self) -> bytes:
        payload = self._payload()
        payload["aggregate_sha256"] = self.aggregate_sha256
        return _canonical_json(payload)

    @property
    def digest(self) -> str:
        return _sha256(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> MembershipManifest:
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MatchweekError(
                "MV-T05-MANIFEST_MALFORMED", "Membership manifest JSON is malformed."
            ) from error
        if not isinstance(value, dict):
            raise MatchweekError(
                "MV-T05-MANIFEST_MALFORMED", "Membership manifest root is not an object."
            )
        expected_keys = {
            "aggregate_sha256",
            "cutoff_id",
            "cutoff_utc",
            "friday_local",
            "matchweek_id",
            "memberships",
            "rules_version",
            "schema_version",
            "season",
            "window_end_utc",
            "window_start_utc",
        }
        if set(value) != expected_keys:
            raise MatchweekError(
                "MV-T05-MANIFEST_MALFORMED", "Membership manifest keys are invalid."
            )
        memberships = value.get("memberships")
        if not isinstance(memberships, list) or not all(
            isinstance(item, dict) for item in memberships
        ):
            raise MatchweekError(
                "MV-T05-MANIFEST_MALFORMED", "Membership manifest entries are invalid."
            )
        manifest = cls(
            matchweek_id=_string(value, "matchweek_id"),
            season=_string(value, "season"),
            friday_local=_string(value, "friday_local"),
            window_start_utc=_string(value, "window_start_utc"),
            window_end_utc=_string(value, "window_end_utc"),
            cutoff_id=_string(value, "cutoff_id"),
            cutoff_utc=_string(value, "cutoff_utc"),
            memberships=tuple(FrozenMembership.from_dict(item) for item in memberships),
            rules_version=_string(value, "rules_version"),
            schema_version=_int(value, "schema_version"),
        )
        aggregate = _string(value, "aggregate_sha256")
        if aggregate != manifest.aggregate_sha256:
            raise MatchweekError(
                "MV-T05-MANIFEST_DIGEST_MISMATCH", "Membership aggregate digest is invalid."
            )
        if manifest.to_bytes() != data:
            raise MatchweekError(
                "MV-T05-MANIFEST_NONCANONICAL", "Membership manifest JSON is not canonical."
            )
        return manifest


@dataclass(frozen=True)
class MatchweekFreeze:
    window: MatchweekWindow
    season: str
    cutoff: MatchweekResearchCutoff
    memberships: tuple[FrozenMembership, ...]
    snapshot_manifest_digest: str
    membership_manifest_digest: str
    revision_snapshot_digest: str
    appendix: tuple[PostCutoffFixtureAppendixEntry, ...] = ()

    @property
    def target_matches(self) -> tuple[FrozenMembership, ...]:
        return tuple(item for item in self.memberships if item.target_match)

    @property
    def indeterminate_memberships(self) -> tuple[FrozenMembership, ...]:
        return tuple(
            item
            for item in self.memberships
            if item.membership_state is MembershipState.INDETERMINATE
        )

    @property
    def normal_coverage_denominator(self) -> int:
        """Only frozen INCLUDED Target Matches enter normal coverage metrics."""
        return len(self.target_matches)

    @property
    def excluded_memberships(self) -> tuple[FrozenMembership, ...]:
        return tuple(
            item for item in self.memberships if item.membership_state is MembershipState.EXCLUDED
        )

    @property
    def withdrawn_fixture_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.subject_id
                    for item in self.appendix
                    if item.disposition is AppendixDisposition.WITHDRAWN
                    and item.fixture_id is not None
                }
            )
        )


@dataclass(frozen=True)
class _SourceSupport:
    retrieved_at_utc: str
    source_published_at_utc: str | None
    content_sha256: str
    source_key: str
    source_class: str


@dataclass(frozen=True)
class _RevisionCandidate:
    fixture_id: str
    identity_state: str
    league_key: str
    season: str
    home_team_name: str
    away_team_name: str
    revision_id: str
    revision_digest: str
    kickoff_state: str
    kickoff_utc: str | None
    kickoff_local_text: str | None
    kickoff_precision: str
    fixture_status: str
    observed_at_utc: str
    supports: tuple[_SourceSupport, ...]

    def valid_supports(self, boundary: datetime) -> tuple[_SourceSupport, ...]:
        if _parse_utc(self.observed_at_utc) > boundary:
            return ()
        supports = tuple(
            support
            for support in self.supports
            if _parse_utc(support.retrieved_at_utc) <= boundary
            and (
                support.source_published_at_utc is None
                or _parse_utc(support.source_published_at_utc) <= boundary
            )
        )
        if supports:
            return supports
        if not self.supports and _parse_utc(self.observed_at_utc) <= boundary:
            return (
                _SourceSupport(
                    retrieved_at_utc=self.observed_at_utc,
                    source_published_at_utc=None,
                    content_sha256="",
                    source_key="fixture_revision_observed_at",
                    source_class="OBSERVATION",
                ),
            )
        return ()

    def post_cutoff_supports(self, cutoff: datetime, as_of: datetime) -> tuple[_SourceSupport, ...]:
        return tuple(
            support
            for support in self.supports
            if cutoff < _parse_utc(support.retrieved_at_utc) <= as_of
        )


@dataclass(frozen=True)
class _UnresolvedFixture:
    unresolved_id: str
    league_key: str
    season: str
    home_name: str
    away_name: str
    resolution_state: str
    kickoff_utc: str | None
    observed_at_utc: str


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise MatchweekError("MV-T05-MANIFEST_MALFORMED", f"Manifest field {key} is invalid.")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise MatchweekError("MV-T05-MANIFEST_MALFORMED", f"Manifest field {key} is invalid.")
    return item


def _bool(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise MatchweekError("MV-T05-MANIFEST_MALFORMED", f"Manifest field {key} is invalid.")
    return item


def _int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise MatchweekError("MV-T05-MANIFEST_MALFORMED", f"Manifest field {key} is invalid.")
    return item


def _authority_rank(source_key: str, source_class: str) -> int:
    """Return the settled T05 authority level for a source-backed fact."""
    normalized_class = source_class.strip().upper().replace(" ", "_")
    normalized_key = source_key.strip().casefold()
    if normalized_class in {"OFFICIAL_COMPETITION", "OFFICIAL_LEAGUE"}:
        return 500
    if normalized_class in {"OFFICIAL_FEDERATION", "OFFICIAL_ASSOCIATION"}:
        return 490
    if normalized_class == "OFFICIAL_CLUB":
        return 480
    if normalized_class == "OFFICIAL":
        return 470
    if normalized_class == "STRUCTURED_PROVIDER":
        return 300
    if normalized_class in {"OPEN_DATASET", "OPEN_SOURCE_DATASET"}:
        return 200
    if "football-data.co.uk" in normalized_key:
        return 300
    if "openfootball" in normalized_key:
        return 200
    return 100


def _authority_label(supports: Sequence[_SourceSupport]) -> tuple[int, str]:
    if not supports:
        return 0, "UNKNOWN"
    ranked = sorted(
        (
            _authority_rank(support.source_key, support.source_class),
            support.source_class or "UNKNOWN",
            support.source_key,
        )
        for support in supports
    )
    rank, source_class, source_key = ranked[-1]
    return rank, f"{source_class}:{source_key}"


def _revision_key(
    candidate: _RevisionCandidate,
    boundary: datetime,
) -> tuple[int, datetime, str, str]:
    supports = candidate.valid_supports(boundary)
    rank, _ = _authority_label(supports)
    latest_observation = max(_parse_utc(item.retrieved_at_utc) for item in supports)
    return rank, latest_observation, candidate.revision_id, candidate.revision_digest


def _select_revision(
    candidates: Sequence[_RevisionCandidate], boundary: datetime
) -> _RevisionCandidate | None:
    valid = [candidate for candidate in candidates if candidate.valid_supports(boundary)]
    if not valid:
        return None
    return max(valid, key=lambda candidate: _revision_key(candidate, boundary))


def _source_snapshot_digest(candidates: Sequence[_RevisionCandidate]) -> str:
    payload = [
        {
            "fixture_id": candidate.fixture_id,
            "identity_state": candidate.identity_state,
            "revision_digest": candidate.revision_digest,
            "revision_id": candidate.revision_id,
            "supports": [
                {
                    "content_sha256": support.content_sha256,
                    "retrieved_at_utc": support.retrieved_at_utc,
                    "source_published_at_utc": support.source_published_at_utc,
                    "source_class": support.source_class,
                    "source_key": support.source_key,
                }
                for support in sorted(
                    candidate.supports,
                    key=lambda item: (
                        item.retrieved_at_utc,
                        item.source_class,
                        item.source_key,
                        item.content_sha256,
                    ),
                )
            ],
        }
        for candidate in sorted(candidates, key=lambda item: item.revision_id)
    ]
    return _sha256(_canonical_json(payload))


def _membership_id(matchweek_id: str, subject_kind: str, subject_id: str) -> str:
    return deterministic_identifier(
        "frozen_membership", f"{matchweek_id}:{subject_kind}:{subject_id}"
    )


def _matchweek_id(season: str, friday: date) -> str:
    return deterministic_identifier("matchweek", f"{season}:{friday.isoformat()}")


def _cutoff_id(matchweek_id: str) -> str:
    return deterministic_identifier("research_cutoff", matchweek_id)


def _snapshot_id(matchweek_id: str) -> str:
    return deterministic_identifier("snapshot_manifest", f"t05:{matchweek_id}")


def _version_manifest_id() -> str:
    return deterministic_identifier("version_manifest", "t05:matchweek-membership:v1")


def _membership_rules_version() -> VersionIdentity:
    payload = {
        "authority_levels": {
            "official_competition": 500,
            "official_federation": 490,
            "official_club": 480,
            "official": 470,
            "structured_provider": 300,
            "open_dataset": 200,
        },
        "lead_time_seconds": MATCHWEEK_LEAD_TIME_SECONDS,
        "rules_name": MATCHWEEK_RULES_NAME,
        "timezone": MATCHWEEK_TIMEZONE,
        "window": "FRIDAY_00_INCLUSIVE_TO_TUESDAY_00_EXCLUSIVE",
    }
    content_sha256 = _sha256(_canonical_json(payload))
    return VersionIdentity(
        identifier=CanonicalIdentifier(
            "version",
            deterministic_identifier("version", f"{MATCHWEEK_RULES_KIND}:{content_sha256}"),
        ),
        definition_id=CanonicalIdentifier(
            "version_definition",
            deterministic_identifier("version_definition", MATCHWEEK_RULES_KIND),
        ),
        kind=MATCHWEEK_RULES_KIND,
        name=MATCHWEEK_RULES_NAME,
        content_sha256=content_sha256,
        canonical_contract_version=1,
        created_at_utc="2026-01-01T00:00:00.000000+00:00",
    )


def _load_revision_candidates(store: Store, season: str) -> tuple[_RevisionCandidate, ...]:
    connection = store._connection_for_repository()
    fixture_rows = connection.execute(
        """
        SELECT f.fixture_id, f.identity_state, l.league_key, s.season_label,
               home.canonical_name, away.canonical_name
        FROM fixtures AS f
        JOIN target_leagues AS l ON l.league_id = f.league_id
        JOIN competition_seasons AS s ON s.season_id = f.season_id
        JOIN teams AS home ON home.team_id = f.home_team_id
        JOIN teams AS away ON away.team_id = f.away_team_id
        WHERE s.season_label = ?
        ORDER BY f.fixture_id
        """,
        (season,),
    ).fetchall()
    candidates: list[_RevisionCandidate] = []
    for fixture_row in fixture_rows:
        fixture_id = str(fixture_row[0])
        revision_rows = connection.execute(
            """
            SELECT r.revision_id, r.revision_digest, r.kickoff_state,
                   r.kickoff_utc, r.kickoff_local_text, r.kickoff_precision,
                   r.fixture_status, r.observed_at_utc
            FROM fixture_revisions AS r
            WHERE r.fixture_id = ?
            ORDER BY r.observed_at_utc, r.revision_id
            """,
            (fixture_id,),
        ).fetchall()
        for revision_row in revision_rows:
            revision_id = str(revision_row[0])
            support_rows = connection.execute(
                """
                SELECT sc.retrieved_at_utc, sc.source_published_at_utc, sc.content_sha256,
                       si.source_key, si.source_class
                FROM source_captures AS sc
                JOIN source_identities AS si ON si.source_id = sc.source_id
                WHERE sc.capture_id = (
                    SELECT source_capture_id
                    FROM fixture_revisions
                    WHERE revision_id = ?
                )
                UNION
                SELECT sc.retrieved_at_utc, sc.source_published_at_utc, sc.content_sha256,
                       si.source_key, si.source_class
                FROM fixture_revision_assertions AS fra
                JOIN source_assertions AS sa ON sa.assertion_id = fra.assertion_id
                JOIN source_captures AS sc ON sc.capture_id = sa.capture_id
                JOIN source_identities AS si ON si.source_id = sc.source_id
                WHERE fra.revision_id = ?
                ORDER BY retrieved_at_utc, source_class, source_key, content_sha256
                """,
                (revision_id, revision_id),
            ).fetchall()
            supports = tuple(
                _SourceSupport(
                    retrieved_at_utc=_canonical_utc(str(row[0])),
                    source_published_at_utc=(
                        _canonical_utc(str(row[1])) if row[1] is not None else None
                    ),
                    content_sha256=str(row[2]),
                    source_key=str(row[3]),
                    source_class=str(row[4]),
                )
                for row in support_rows
            )
            candidates.append(
                _RevisionCandidate(
                    fixture_id=fixture_id,
                    identity_state=str(fixture_row[1]),
                    league_key=str(fixture_row[2]),
                    season=str(fixture_row[3]),
                    home_team_name=str(fixture_row[4]),
                    away_team_name=str(fixture_row[5]),
                    revision_id=revision_id,
                    revision_digest=str(revision_row[1]),
                    kickoff_state=str(revision_row[2]),
                    kickoff_utc=(
                        _canonical_utc(str(revision_row[3]))
                        if revision_row[3] is not None
                        else None
                    ),
                    kickoff_local_text=(
                        str(revision_row[4]) if revision_row[4] is not None else None
                    ),
                    kickoff_precision=str(revision_row[5]),
                    fixture_status=str(revision_row[6]),
                    observed_at_utc=_canonical_utc(str(revision_row[7])),
                    supports=supports,
                )
            )
    return tuple(candidates)


def _load_unresolved_fixtures(store: Store, season: str) -> tuple[_UnresolvedFixture, ...]:
    connection = store._connection_for_repository()
    rows = connection.execute(
        """
        SELECT u.unresolved_id, l.league_key, s.season_label,
               u.home_name, u.away_name, u.resolution_state,
               sa.normalized_value_json,
               COALESCE(kickoff_capture.retrieved_at_utc, base_capture.retrieved_at_utc)
        FROM unresolved_fixture_rows AS u
        JOIN target_leagues AS l ON l.league_id = u.league_id
        JOIN competition_seasons AS s ON s.season_id = u.season_id
        JOIN source_captures AS base_capture ON base_capture.capture_id = u.capture_id
        LEFT JOIN source_assertions AS sa
          ON sa.subject_kind = 'UNRESOLVED_FIXTURE_ROW'
         AND sa.subject_key = u.unresolved_id
         AND sa.predicate = 'kickoff'
        LEFT JOIN source_captures AS kickoff_capture ON kickoff_capture.capture_id = sa.capture_id
        WHERE s.season_label = ?
        ORDER BY u.unresolved_id,
                 COALESCE(kickoff_capture.retrieved_at_utc, base_capture.retrieved_at_utc)
        """,
        (season,),
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[0])].append(tuple(row))
    unresolved: list[_UnresolvedFixture] = []
    for unresolved_id, values in sorted(grouped.items()):
        first = values[0]
        kickoff: str | None = None
        observed: str | None = None
        for row in values:
            if row[6] is not None:
                try:
                    parsed: object = json.loads(str(row[6]))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, str):
                    try:
                        kickoff = _canonical_utc(parsed)
                    except ValueError:
                        kickoff = None
            if row[7] is not None:
                observed = _canonical_utc(str(row[7]))
        if observed is None:
            continue
        unresolved.append(
            _UnresolvedFixture(
                unresolved_id=unresolved_id,
                league_key=str(first[1]),
                season=str(first[2]),
                home_name=str(first[3]),
                away_name=str(first[4]),
                resolution_state=str(first[5]),
                kickoff_utc=kickoff,
                observed_at_utc=observed,
            )
        )
    return tuple(unresolved)


_MATERIAL_CONFLICT_PREDICATES = frozenset(
    {"kickoff", "home_team", "away_team", "venue", "competition", "status", "fixture_status"}
)


def _material_conflicts(store: Store, fixture_id: str, boundary: datetime) -> tuple[str, ...]:
    connection = store._connection_for_repository()
    rows = connection.execute(
        """
        SELECT c.predicate, sa.normalized_value_json, sc.retrieved_at_utc
        FROM conflict_sets AS c
        JOIN conflict_assertions AS ca ON ca.conflict_id = c.conflict_id
        JOIN source_assertions AS sa ON sa.assertion_id = ca.assertion_id
        JOIN source_captures AS sc ON sc.capture_id = sa.capture_id
        WHERE c.subject_kind = 'FIXTURE'
          AND c.subject_key = ?
          AND c.status != 'RESOLVED'
          AND c.predicate IN (
              'kickoff', 'home_team', 'away_team', 'venue', 'competition', 'status',
              'fixture_status'
          )
          AND sc.retrieved_at_utc <= ?
        ORDER BY c.predicate, sa.normalized_value_json
        """,
        (fixture_id, boundary.isoformat()),
    ).fetchall()
    values: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        predicate = str(row[0])
        if predicate not in _MATERIAL_CONFLICT_PREDICATES:
            continue
        values[predicate].add(str(row[1]))
    return tuple(sorted(predicate for predicate, entries in values.items() if len(entries) >= 2))


def _latest_candidate_by_fixture(
    candidates: Sequence[_RevisionCandidate], boundary: datetime
) -> dict[str, _RevisionCandidate]:
    grouped: dict[str, list[_RevisionCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.fixture_id].append(candidate)
    selected: dict[str, _RevisionCandidate] = {}
    for fixture_id, fixture_candidates in grouped.items():
        chosen = _select_revision(fixture_candidates, boundary)
        if chosen is not None:
            selected[fixture_id] = chosen
    return selected


def _eligible_schedule(candidate: _RevisionCandidate | None, window: MatchweekWindow) -> bool:
    if candidate is None or candidate.identity_state != "CONFIRMED":
        return False
    if candidate.kickoff_state != "OBSERVED" or candidate.kickoff_utc is None:
        return False
    if candidate.fixture_status.strip().upper() not in {"SCHEDULED", "CONFIRMED"}:
        return False
    return window.contains(candidate.kickoff_utc)


def _derive_cutoff(
    candidates: Sequence[_RevisionCandidate],
    window: MatchweekWindow,
    as_of: datetime,
) -> tuple[datetime, _RevisionCandidate]:
    # Start from every schedule revision known by ``as_of``.  The current
    # pointer may already show a post-cutoff postponement or move-out, but the
    # original scheduled revision still determines the historical cutoff.
    eligible = [
        candidate
        for candidate in candidates
        if candidate.valid_supports(as_of) and _eligible_schedule(candidate, window)
    ]
    if not eligible:
        raise MatchweekError(
            "MV-T05-NO_ELIGIBLE_FIXTURE",
            "No cutoff candidate has a scheduled kickoff in the requested Matchweek.",
        )
    earliest = min(eligible, key=lambda item: (_parse_utc(item.kickoff_utc or ""), item.fixture_id))
    cutoff = _parse_utc(earliest.kickoff_utc or "") - MATCHWEEK_LEAD_TIME
    seen: set[str] = set()
    for _ in range(8):
        selected = _latest_candidate_by_fixture(candidates, cutoff)
        included = [
            candidate for candidate in selected.values() if _eligible_schedule(candidate, window)
        ]
        if not included:
            raise MatchweekError(
                "MV-T05-NO_CUTOFF_VALID_FIXTURE",
                "No scheduled fixture was known by the derived Research Cutoff.",
            )
        earliest = min(
            included,
            key=lambda item: (_parse_utc(item.kickoff_utc or ""), item.fixture_id),
        )
        next_cutoff = _parse_utc(earliest.kickoff_utc or "") - MATCHWEEK_LEAD_TIME
        if next_cutoff == cutoff:
            return cutoff, earliest
        key = cutoff.isoformat()
        if key in seen:
            return cutoff, earliest
        seen.add(key)
        cutoff = next_cutoff
    return cutoff, earliest


def _build_memberships(
    store: Store,
    *,
    matchweek_id: str,
    window: MatchweekWindow,
    season: str,
    cutoff: datetime,
    candidates: Sequence[_RevisionCandidate],
) -> tuple[FrozenMembership, ...]:
    grouped: dict[str, list[_RevisionCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.fixture_id].append(candidate)
    memberships: list[FrozenMembership] = []
    for fixture_id, fixture_candidates in sorted(grouped.items()):
        chosen = _select_revision(fixture_candidates, cutoff)
        latest_known = _select_revision(
            fixture_candidates, max(_parse_utc(item.observed_at_utc) for item in fixture_candidates)
        )
        reference = chosen or latest_known or fixture_candidates[0]
        rank, authority = _authority_label(
            chosen.valid_supports(cutoff) if chosen is not None else ()
        )
        revision_id = chosen.revision_id if chosen is not None else None
        revision_digest = chosen.revision_digest if chosen is not None else None
        kickoff = chosen.kickoff_utc if chosen is not None else None
        local_text = chosen.kickoff_local_text if chosen is not None else None
        conflict_predicates = (
            _material_conflicts(store, fixture_id, cutoff) if chosen is not None else ()
        )
        material_conflict = bool(conflict_predicates)
        if reference.identity_state != "CONFIRMED":
            state = MembershipState.INDETERMINATE
            target = False
            reason_code = "IDENTITY_UNRESOLVED"
            reason = "Canonical Fixture identity was not confirmed at the Research Cutoff."
            decision_state = "NO_DECISION_INDETERMINATE"
        elif chosen is None:
            state = MembershipState.EXCLUDED
            target = False
            reason_code = "NO_CUTOFF_VALID_REVISION"
            reason = (
                "No Fixture Revision for this confirmed fixture was valid at the Research Cutoff."
            )
            decision_state = "NO_DECISION_EXCLUDED"
        elif chosen.kickoff_state != "OBSERVED" or kickoff is None:
            state = MembershipState.INDETERMINATE
            target = False
            reason_code = "KICKOFF_UNKNOWN"
            reason = "The confirmed fixture had no cutoff-valid observed kickoff."
            decision_state = "NO_DECISION_INDETERMINATE"
        elif chosen.fixture_status.strip().upper() not in {"SCHEDULED", "CONFIRMED"}:
            state = MembershipState.EXCLUDED
            target = False
            reason_code = "NOT_SCHEDULED_AT_CUTOFF"
            reason = f"Fixture status was {chosen.fixture_status.upper()} at the Research Cutoff."
            decision_state = "NO_DECISION_EXCLUDED"
        elif not window.contains(kickoff):
            state = MembershipState.EXCLUDED
            target = False
            reason_code = "OUTSIDE_MATCHWEEK_WINDOW"
            reason = "The cutoff-valid scheduled kickoff was outside the Friday-to-Monday window."
            decision_state = "NO_DECISION_EXCLUDED"
        else:
            state = MembershipState.INCLUDED
            target = True
            reason_code = "MATERIAL_CONFLICT" if material_conflict else "IN_WINDOW_SCHEDULED"
            reason = (
                "Confirmed identity is in-window, but material fixture details remain unresolved."
                if material_conflict
                else "Confirmed scheduled fixture falls inside the Africa/Lagos Matchweek window."
            )
            decision_state = (
                "MATERIAL_CONFLICT_BLOCKED" if material_conflict else "ELIGIBLE_FOR_VETTING"
            )
        membership = FrozenMembership(
            membership_id=_membership_id(matchweek_id, "FIXTURE", fixture_id),
            matchweek_id=matchweek_id,
            subject_kind="FIXTURE",
            subject_id=fixture_id,
            membership_state=state,
            target_match=target,
            controlling_revision_id=revision_id,
            controlling_revision_digest=revision_digest,
            source_authority_rank=rank,
            source_authority=authority,
            original_kickoff_utc=kickoff,
            original_kickoff_local_text=local_text,
            material_conflict=material_conflict,
            conflict_predicates=conflict_predicates,
            reason_code=reason_code,
            reason=reason,
            decision_state=decision_state,
        )
        memberships.append(membership)

    for unresolved in _load_unresolved_fixtures(store, season):
        if _parse_utc(unresolved.observed_at_utc) > cutoff:
            continue
        memberships.append(
            FrozenMembership(
                membership_id=_membership_id(
                    matchweek_id, "UNRESOLVED_FIXTURE_ROW", unresolved.unresolved_id
                ),
                matchweek_id=matchweek_id,
                subject_kind="UNRESOLVED_FIXTURE_ROW",
                subject_id=unresolved.unresolved_id,
                membership_state=MembershipState.INDETERMINATE,
                target_match=False,
                controlling_revision_id=None,
                controlling_revision_digest=None,
                source_authority_rank=0,
                source_authority="UNKNOWN",
                original_kickoff_utc=unresolved.kickoff_utc,
                original_kickoff_local_text=f"{unresolved.home_name} v {unresolved.away_name}",
                material_conflict=False,
                conflict_predicates=(),
                reason_code="IDENTITY_UNRESOLVED",
                reason="Source rows could not be mapped to one canonical Fixture identity.",
                decision_state="NO_DECISION_INDETERMINATE",
            )
        )
    return tuple(sorted(memberships, key=lambda item: item.membership_id))


def _revision_snapshot_bytes(candidates: Sequence[_RevisionCandidate], as_of: datetime) -> bytes:
    payload = {
        "as_of_utc": as_of.isoformat(timespec="microseconds"),
        "candidates": [
            {
                "away_team_name": candidate.away_team_name,
                "fixture_id": candidate.fixture_id,
                "home_team_name": candidate.home_team_name,
                "identity_state": candidate.identity_state,
                "kickoff_utc": candidate.kickoff_utc,
                "league_key": candidate.league_key,
                "revision_digest": candidate.revision_digest,
                "revision_id": candidate.revision_id,
                "season": candidate.season,
                "supports": [
                    {
                        "content_sha256": support.content_sha256,
                        "retrieved_at_utc": support.retrieved_at_utc,
                        "source_published_at_utc": support.source_published_at_utc,
                        "source_class": support.source_class,
                        "source_key": support.source_key,
                    }
                    for support in sorted(
                        candidate.supports,
                        key=lambda item: (
                            item.retrieved_at_utc,
                            item.source_class,
                            item.source_key,
                            item.content_sha256,
                        ),
                    )
                ],
            }
            for candidate in sorted(candidates, key=lambda item: item.revision_id)
            if _parse_utc(candidate.observed_at_utc) <= as_of
        ],
        "schema_version": 1,
    }
    return _canonical_json(payload)


def _ensure_membership_version(store: Store) -> VersionIdentity:
    version = _membership_rules_version()
    existing = store.version(version.identifier)
    if existing is not None:
        if existing != version:
            raise MatchweekError(
                "MV-T05-RULE_VERSION_CONFLICT",
                "The stored T05 membership rules version does not match the immutable contract.",
            )
        return version
    with store.transaction() as transaction:
        transaction.add_version(version)
    return version


def _insert_freeze(
    store: Store,
    *,
    window: MatchweekWindow,
    season: str,
    cutoff: MatchweekResearchCutoff,
    memberships: Sequence[FrozenMembership],
    snapshot_manifest_digest: str,
    membership_manifest_digest: str,
    revision_snapshot_digest: str,
    frozen_at_utc: str,
) -> None:
    matchweek_id = cutoff.matchweek_id
    with store.transaction() as transaction:
        transaction.add_identifier_if_missing(CanonicalIdentifier("matchweek", matchweek_id))
        transaction.add_identifier_if_missing(
            CanonicalIdentifier("research_cutoff", cutoff.cutoff_id)
        )
        transaction.execute(
            """
            INSERT INTO matchweeks (
                matchweek_id, season_label, friday_local_date, timezone,
                window_start_utc, window_end_utc, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(matchweek_id) DO NOTHING
            """,
            (
                matchweek_id,
                season,
                window.friday_local.isoformat(),
                MATCHWEEK_TIMEZONE,
                window.start_utc,
                window.end_utc,
                frozen_at_utc,
            ),
        )
        transaction.execute(
            """
            INSERT INTO matchweek_research_cutoffs (
                cutoff_id, matchweek_id, cutoff_utc, earliest_included_fixture_id,
                earliest_included_kickoff_utc, lead_time_seconds, cutoff_digest, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cutoff_id) DO NOTHING
            """,
            (
                cutoff.cutoff_id,
                matchweek_id,
                cutoff.cutoff_utc,
                cutoff.earliest_included_fixture_id,
                cutoff.earliest_included_kickoff_utc,
                cutoff.lead_time_seconds,
                cutoff.digest,
                frozen_at_utc,
            ),
        )
        for membership in memberships:
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("frozen_membership", membership.membership_id)
            )
            fixture_id = membership.subject_id if membership.subject_kind == "FIXTURE" else None
            unresolved_id = (
                membership.subject_id
                if membership.subject_kind == "UNRESOLVED_FIXTURE_ROW"
                else None
            )
            transaction.execute(
                """
                INSERT INTO matchweek_memberships (
                    membership_id, matchweek_id, subject_kind, subject_id,
                    fixture_id, unresolved_id, membership_state, target_match,
                    controlling_revision_id, controlling_revision_digest,
                    source_authority_rank, source_authority, original_kickoff_utc,
                    original_kickoff_local_text, material_conflict, conflict_predicates_json,
                    reason_code, reason, decision_state, membership_digest, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(membership_id) DO NOTHING
                """,
                (
                    membership.membership_id,
                    matchweek_id,
                    membership.subject_kind,
                    membership.subject_id,
                    fixture_id,
                    unresolved_id,
                    membership.membership_state.value,
                    int(membership.target_match),
                    membership.controlling_revision_id,
                    membership.controlling_revision_digest,
                    membership.source_authority_rank,
                    membership.source_authority,
                    membership.original_kickoff_utc,
                    membership.original_kickoff_local_text,
                    int(membership.material_conflict),
                    _canonical_json(membership.conflict_predicates).decode("utf-8"),
                    membership.reason_code,
                    membership.reason,
                    membership.decision_state,
                    membership.digest,
                    frozen_at_utc,
                ),
            )
        transaction.execute(
            """
            INSERT INTO matchweek_freeze_records (
                matchweek_id, cutoff_id, snapshot_manifest_digest,
                membership_manifest_digest, revision_snapshot_digest, frozen_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(matchweek_id) DO NOTHING
            """,
            (
                matchweek_id,
                cutoff.cutoff_id,
                snapshot_manifest_digest,
                membership_manifest_digest,
                revision_snapshot_digest,
                frozen_at_utc,
            ),
        )


def _membership_from_row(row: Sequence[object]) -> FrozenMembership:
    try:
        conflict_values: object = json.loads(str(row[15]))
    except json.JSONDecodeError as error:
        raise MatchweekError(
            "MV-T05-STORED_MEMBERSHIP_MALFORMED",
            "Stored membership conflict predicates are not valid JSON.",
        ) from error
    if not isinstance(conflict_values, list) or not all(
        isinstance(item, str) for item in conflict_values
    ):
        raise MatchweekError(
            "MV-T05-STORED_MEMBERSHIP_MALFORMED",
            "Stored membership conflict predicates are malformed.",
        )
    return FrozenMembership(
        membership_id=str(row[0]),
        matchweek_id=str(row[1]),
        subject_kind=str(row[2]),
        subject_id=str(row[3]),
        membership_state=MembershipState(str(row[6])),
        target_match=bool(row[7]),
        controlling_revision_id=str(row[8]) if row[8] is not None else None,
        controlling_revision_digest=str(row[9]) if row[9] is not None else None,
        source_authority_rank=int(str(row[10])),
        source_authority=str(row[11]),
        original_kickoff_utc=str(row[12]) if row[12] is not None else None,
        original_kickoff_local_text=str(row[13]) if row[13] is not None else None,
        material_conflict=bool(row[14]),
        conflict_predicates=tuple(conflict_values),
        reason_code=str(row[16]),
        reason=str(row[17]),
        decision_state=str(row[18]),
        digest=str(row[19]),
    )


def _validity_review_from_json(value: str) -> PostCutoffValidityReview:
    try:
        raw: object = json.loads(value)
    except json.JSONDecodeError as error:
        raise MatchweekError(
            "MV-T05-STORED_APPENDIX_MALFORMED", "Stored appendix validity review is malformed."
        ) from error
    if not isinstance(raw, dict):
        raise MatchweekError(
            "MV-T05-STORED_APPENDIX_MALFORMED", "Stored appendix validity review is malformed."
        )
    fields = (
        "identity_unchanged",
        "scope_unchanged",
        "kickoff_after_cutoff",
        "no_postponement_or_cancellation",
        "pre_match_valid",
        "critical_evidence_valid",
        "research_sufficiency_valid",
        "information_boundary_valid",
    )
    values: dict[str, bool | None] = {}
    for field_name in fields:
        item = raw.get(field_name)
        if item is not None and not isinstance(item, bool):
            raise MatchweekError(
                "MV-T05-STORED_APPENDIX_MALFORMED",
                f"Stored appendix validity field {field_name} is malformed.",
            )
        values[field_name] = item
    return PostCutoffValidityReview(**values)


def _appendix_from_row(row: Sequence[object]) -> PostCutoffFixtureAppendixEntry:
    review = _validity_review_from_json(str(row[15]))
    return PostCutoffFixtureAppendixEntry(
        appendix_id=str(row[0]),
        event_key=str(row[2]),
        matchweek_id=str(row[1]),
        subject_kind=str(row[3]),
        subject_id=str(row[4]),
        fixture_id=str(row[5]) if row[5] is not None else None,
        membership_id=str(row[6]) if row[6] is not None else None,
        revision_id=str(row[7]) if row[7] is not None else None,
        revision_digest=str(row[8]) if row[8] is not None else None,
        event_kind=AppendixEventKind(str(row[9])),
        disposition=AppendixDisposition(str(row[10])),
        settlement_result=str(row[11]) if row[11] is not None else None,
        original_kickoff_utc=str(row[12]) if row[12] is not None else None,
        current_kickoff_utc=str(row[13]) if row[13] is not None else None,
        observed_at_utc=str(row[14]),
        validity_review=review,
        reason_code=str(row[16]),
        reason=str(row[17]),
        digest=str(row[18]),
    )


def _load_freeze(store: Store, matchweek_id: str) -> MatchweekFreeze | None:
    connection = store._connection_for_repository()
    row = connection.execute(
        """
        SELECT mw.season_label, mw.friday_local_date, mw.window_start_utc, mw.window_end_utc,
               c.cutoff_id, c.cutoff_utc, c.earliest_included_fixture_id,
               c.earliest_included_kickoff_utc, c.lead_time_seconds, c.cutoff_digest,
               f.snapshot_manifest_digest, f.membership_manifest_digest,
               f.revision_snapshot_digest
        FROM matchweeks AS mw
        JOIN matchweek_research_cutoffs AS c ON c.matchweek_id = mw.matchweek_id
        JOIN matchweek_freeze_records AS f ON f.matchweek_id = mw.matchweek_id
        WHERE mw.matchweek_id = ?
        """,
        (matchweek_id,),
    ).fetchone()
    if row is None:
        return None
    membership_rows = connection.execute(
        """
        SELECT membership_id, matchweek_id, subject_kind, subject_id,
               fixture_id, unresolved_id, membership_state, target_match,
               controlling_revision_id, controlling_revision_digest,
               source_authority_rank, source_authority, original_kickoff_utc,
               original_kickoff_local_text, material_conflict, conflict_predicates_json,
               reason_code, reason, decision_state, membership_digest, created_at_utc
        FROM matchweek_memberships
        WHERE matchweek_id = ?
        ORDER BY membership_id
        """,
        (matchweek_id,),
    ).fetchall()
    appendix_rows = connection.execute(
        """
        SELECT appendix_id, matchweek_id, event_key, subject_kind, subject_id,
               fixture_id, membership_id, revision_id, revision_digest, event_kind,
               disposition, settlement_result, original_kickoff_utc, current_kickoff_utc,
               observed_at_utc, validity_review_json, reason_code, reason, entry_digest,
               created_at_utc
        FROM post_cutoff_fixture_appendix
        WHERE matchweek_id = ?
        ORDER BY observed_at_utc, appendix_id
        """,
        (matchweek_id,),
    ).fetchall()
    cutoff = MatchweekResearchCutoff(
        cutoff_id=str(row[4]),
        matchweek_id=matchweek_id,
        cutoff_utc=str(row[5]),
        earliest_included_fixture_id=str(row[6]),
        earliest_included_kickoff_utc=str(row[7]),
        lead_time_seconds=int(row[8]),
        digest=str(row[9]),
    )
    return MatchweekFreeze(
        window=MatchweekWindow.for_friday(str(row[1])),
        season=str(row[0]),
        cutoff=cutoff,
        memberships=tuple(_membership_from_row(item) for item in membership_rows),
        snapshot_manifest_digest=str(row[10]),
        membership_manifest_digest=str(row[11]),
        revision_snapshot_digest=str(row[12]),
        appendix=tuple(_appendix_from_row(item) for item in appendix_rows),
    )


def read_frozen_matchweek(
    store: Store, friday: date | datetime | str, *, season: str = "2026-27"
) -> MatchweekFreeze:
    """Read one frozen Matchweek without consulting current schedule state."""
    matchweek_id = _matchweek_id(season, _date_value(friday))
    freeze = _load_freeze(store, matchweek_id)
    if freeze is None:
        raise MatchweekError(
            "MV-T05-MATCHWEEK_NOT_FROZEN", "The requested Matchweek is not frozen."
        )
    return freeze


def freeze_matchweek(
    store: Store,
    friday: date | datetime | str,
    *,
    season: str = "2026-27",
    as_of_utc: str | datetime | None = None,
    created_at_utc: str | datetime | None = None,
    manifest_verified_at_utc: str | None = None,
) -> MatchweekFreeze:
    """Freeze the T05 membership manifest once, idempotently, from T06 revisions."""
    if store.status.mode.value != "READ_WRITE":
        raise PermissionError("Matchweek freezing requires a healthy writable store.")
    window = MatchweekWindow.for_friday(friday)
    matchweek_id = _matchweek_id(season, window.friday_local)
    existing = _load_freeze(store, matchweek_id)
    if existing is not None:
        return existing
    candidates = _load_revision_candidates(store, season)
    if not candidates:
        raise MatchweekError(
            "MV-T05-NO_FIXTURE_REVISIONS",
            "No T06 Fixture Revisions are available for the requested season.",
        )
    if as_of_utc is None:
        as_of = max(_parse_utc(candidate.observed_at_utc) for candidate in candidates)
    else:
        as_of = _parse_utc(_canonical_utc(as_of_utc))
    cutoff_datetime, _ = _derive_cutoff(candidates, window, as_of)
    memberships = _build_memberships(
        store,
        matchweek_id=matchweek_id,
        window=window,
        season=season,
        cutoff=cutoff_datetime,
        candidates=candidates,
    )
    included = tuple(
        item for item in memberships if item.membership_state is MembershipState.INCLUDED
    )
    if not included:
        raise MatchweekError(
            "MV-T05-NO_INCLUDED_MEMBERSHIP",
            "The derived Research Cutoff produced no INCLUDED Target Match.",
        )
    earliest_included = min(
        included,
        key=lambda item: (_parse_utc(item.original_kickoff_utc or ""), item.subject_id),
    )
    expected_cutoff = _parse_utc(earliest_included.original_kickoff_utc or "") - MATCHWEEK_LEAD_TIME
    if expected_cutoff != cutoff_datetime:
        raise MatchweekError(
            "MV-T05-CUTOFF_NOT_STABLE",
            "The Matchweek Research Cutoff did not stabilize at six hours before "
            "the earliest INCLUDED kickoff.",
        )
    cutoff = MatchweekResearchCutoff(
        cutoff_id=_cutoff_id(matchweek_id),
        matchweek_id=matchweek_id,
        cutoff_utc=cutoff_datetime.isoformat(timespec="microseconds"),
        earliest_included_fixture_id=earliest_included.subject_id,
        earliest_included_kickoff_utc=earliest_included.original_kickoff_utc or "",
    )
    membership_manifest = MembershipManifest(
        matchweek_id=matchweek_id,
        season=season,
        friday_local=window.friday_local.isoformat(),
        window_start_utc=window.start_utc,
        window_end_utc=window.end_utc,
        cutoff_id=cutoff.cutoff_id,
        cutoff_utc=cutoff.cutoff_utc,
        memberships=memberships,
    )
    revision_snapshot = _revision_snapshot_bytes(candidates, as_of)
    membership_digest = _sha256(membership_manifest.to_bytes())
    revision_digest = _sha256(revision_snapshot)
    artifacts = ArtifactStore(store)
    membership_artifact = artifacts.publish_artifact(
        membership_manifest.to_bytes(),
        "application/vnd.matchvet.t05-membership-manifest+json",
        expected_digest=membership_digest,
        retention_class="PROTECTED",
    )
    revision_artifact = artifacts.publish_artifact(
        revision_snapshot,
        "application/vnd.matchvet.t05-fixture-revision-snapshot+json",
        expected_digest=revision_digest,
        retention_class="PROTECTED",
    )
    version = _ensure_membership_version(store)
    manifest = SnapshotManifest(
        snapshot_id=CanonicalIdentifier("snapshot_manifest", _snapshot_id(matchweek_id)),
        matchweek_id=CanonicalIdentifier("matchweek", matchweek_id),
        research_cutoff_id=CanonicalIdentifier("research_cutoff", cutoff.cutoff_id),
        version_manifest_id=CanonicalIdentifier("version_manifest", _version_manifest_id()),
        research_cutoff_utc=cutoff.cutoff_utc,
        artifacts=tuple(
            sorted(
                (
                    ManifestArtifact(
                        membership_artifact.artifact_id,
                        membership_artifact.digest,
                        membership_artifact.media_type,
                        membership_artifact.byte_length,
                    ),
                    ManifestArtifact(
                        revision_artifact.artifact_id,
                        revision_artifact.digest,
                        revision_artifact.media_type,
                        revision_artifact.byte_length,
                    ),
                ),
                key=lambda item: item.digest,
            )
        ),
        versions=(ManifestVersion.from_identity(version),),
        retention_omissions=(),
        completeness=ManifestCompleteness("COMPLETE"),
        created_at_utc=_canonical_utc(created_at_utc or cutoff.cutoff_utc),
    )
    snapshot_artifact = artifacts.publish_manifest(
        manifest,
        verified_at_utc=manifest_verified_at_utc,
    )
    frozen_at = _canonical_utc(created_at_utc or cutoff.cutoff_utc)
    _insert_freeze(
        store,
        window=window,
        season=season,
        cutoff=cutoff,
        memberships=memberships,
        snapshot_manifest_digest=snapshot_artifact.digest,
        membership_manifest_digest=membership_artifact.digest,
        revision_snapshot_digest=revision_artifact.digest,
        frozen_at_utc=frozen_at,
    )
    result = _load_freeze(store, matchweek_id)
    if result is None:
        raise MatchweekError(
            "MV-T05-FREEZE_NOT_PUBLISHED", "Frozen Matchweek publication was not durable."
        )
    return result


def _revision_candidate(store: Store, season: str, revision_id: str) -> _RevisionCandidate:
    for candidate in _load_revision_candidates(store, season):
        if candidate.revision_id == revision_id:
            return candidate
    raise MatchweekError(
        "MV-T05-REVISION_NOT_FOUND", f"Fixture Revision {revision_id} does not exist."
    )


def _appendix_row_for_event(store: Store, event_key: str) -> PostCutoffFixtureAppendixEntry | None:
    connection = store._connection_for_repository()
    row = connection.execute(
        """
        SELECT appendix_id, matchweek_id, event_key, subject_kind, subject_id,
               fixture_id, membership_id, revision_id, revision_digest, event_kind,
               disposition, settlement_result, original_kickoff_utc, current_kickoff_utc,
               observed_at_utc, validity_review_json, reason_code, reason, entry_digest,
               created_at_utc
        FROM post_cutoff_fixture_appendix
        WHERE event_key = ?
        """,
        (event_key,),
    ).fetchone()
    return None if row is None else _appendix_from_row(row)


def _post_cutoff_observation(
    candidate: _RevisionCandidate, cutoff: datetime, as_of: datetime
) -> str:
    post = candidate.post_cutoff_supports(cutoff, as_of)
    if post:
        return min(post, key=lambda item: item.retrieved_at_utc).retrieved_at_utc
    return candidate.observed_at_utc


def _default_review_for_unchanged_fixture() -> PostCutoffValidityReview:
    return PostCutoffValidityReview(
        identity_unchanged=True,
        scope_unchanged=True,
        kickoff_after_cutoff=True,
        no_postponement_or_cancellation=True,
        pre_match_valid=True,
        critical_evidence_valid=True,
        research_sufficiency_valid=True,
        information_boundary_valid=True,
    )


def _appendix_entry(
    *,
    freeze: MatchweekFreeze,
    candidate: _RevisionCandidate,
    event_kind: AppendixEventKind,
    disposition: AppendixDisposition,
    observed_at_utc: str,
    validity_review: PostCutoffValidityReview,
    reason_code: str,
    reason: str,
) -> PostCutoffFixtureAppendixEntry:
    membership = next(
        (item for item in freeze.memberships if item.subject_id == candidate.fixture_id), None
    )
    event_key = (
        f"{freeze.cutoff.matchweek_id}:{candidate.fixture_id}:"
        f"{candidate.revision_id}:{event_kind.value}"
    )
    return PostCutoffFixtureAppendixEntry(
        appendix_id=deterministic_identifier("post_cutoff_appendix", event_key),
        event_key=event_key,
        matchweek_id=freeze.cutoff.matchweek_id,
        subject_kind="FIXTURE",
        subject_id=candidate.fixture_id,
        fixture_id=candidate.fixture_id,
        membership_id=membership.membership_id if membership is not None else None,
        revision_id=candidate.revision_id,
        revision_digest=candidate.revision_digest,
        event_kind=event_kind,
        disposition=disposition,
        settlement_result="VOID" if disposition is AppendixDisposition.WITHDRAWN else None,
        original_kickoff_utc=(membership.original_kickoff_utc if membership is not None else None),
        current_kickoff_utc=candidate.kickoff_utc,
        observed_at_utc=observed_at_utc,
        validity_review=validity_review,
        reason_code=reason_code,
        reason=reason,
    )


def _unresolved_appendix_entry(
    *,
    freeze: MatchweekFreeze,
    unresolved: _UnresolvedFixture,
) -> PostCutoffFixtureAppendixEntry:
    membership = next(
        (
            item
            for item in freeze.memberships
            if item.subject_kind == "UNRESOLVED_FIXTURE_ROW"
            and item.subject_id == unresolved.unresolved_id
        ),
        None,
    )
    event_key = (
        f"{freeze.cutoff.matchweek_id}:{unresolved.unresolved_id}:"
        f"{unresolved.observed_at_utc}:IDENTITY_CONFLICT"
    )
    return PostCutoffFixtureAppendixEntry(
        appendix_id=deterministic_identifier("post_cutoff_appendix", event_key),
        event_key=event_key,
        matchweek_id=freeze.cutoff.matchweek_id,
        subject_kind="UNRESOLVED_FIXTURE_ROW",
        subject_id=unresolved.unresolved_id,
        fixture_id=None,
        membership_id=membership.membership_id if membership is not None else None,
        revision_id=None,
        revision_digest=None,
        event_kind=AppendixEventKind.IDENTITY_CONFLICT,
        disposition=AppendixDisposition.APPENDIX_ONLY,
        settlement_result=None,
        original_kickoff_utc=membership.original_kickoff_utc if membership else None,
        current_kickoff_utc=unresolved.kickoff_utc,
        observed_at_utc=unresolved.observed_at_utc,
        validity_review=PostCutoffValidityReview(),
        reason_code="IDENTITY_UNRESOLVED_AFTER_CUTOFF",
        reason=(
            "The post-cutoff source row still has no canonical Fixture identity; "
            "it cannot become a retroactive Target Match."
        ),
    )


def _store_appendix_entry(
    store: Store, entry: PostCutoffFixtureAppendixEntry
) -> PostCutoffFixtureAppendixEntry:
    existing = _appendix_row_for_event(store, entry.event_key)
    if existing is not None:
        return existing
    with store.transaction() as transaction:
        transaction.add_identifier_if_missing(
            CanonicalIdentifier("post_cutoff_appendix", entry.appendix_id)
        )
        transaction.execute(
            """
            INSERT INTO post_cutoff_fixture_appendix (
                appendix_id, matchweek_id, event_key, subject_kind, subject_id,
                fixture_id, membership_id, revision_id, revision_digest, event_kind,
                disposition, settlement_result, original_kickoff_utc, current_kickoff_utc,
                observed_at_utc, validity_review_json, reason_code, reason,
                entry_digest, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_key) DO NOTHING
            """,
            (
                entry.appendix_id,
                entry.matchweek_id,
                entry.event_key,
                entry.subject_kind,
                entry.subject_id,
                entry.fixture_id,
                entry.membership_id,
                entry.revision_id,
                entry.revision_digest,
                entry.event_kind.value,
                entry.disposition.value,
                entry.settlement_result,
                entry.original_kickoff_utc,
                entry.current_kickoff_utc,
                entry.observed_at_utc,
                _canonical_json(entry.validity_review.to_dict()).decode("utf-8"),
                entry.reason_code,
                entry.reason,
                entry.digest,
                entry.observed_at_utc,
            ),
        )
    stored = _appendix_row_for_event(store, entry.event_key)
    if stored is None:
        raise MatchweekError(
            "MV-T05-APPENDIX_NOT_PUBLISHED", "Post-cutoff appendix entry was not durable."
        )
    return stored


def append_post_cutoff_revision(
    store: Store,
    friday: date | datetime | str,
    fixture_id: str,
    *,
    season: str = "2026-27",
    revision_id: str | None = None,
    as_of_utc: str | datetime | None = None,
    validity_review: PostCutoffValidityReview | None = None,
    identity_unchanged: bool = True,
) -> PostCutoffFixtureAppendixEntry:
    """Append one learned revision without changing frozen membership."""
    freeze = read_frozen_matchweek(store, friday, season=season)
    candidates = _load_revision_candidates(store, season)
    fixture_candidates = tuple(item for item in candidates if item.fixture_id == fixture_id)
    if not fixture_candidates:
        raise MatchweekError("MV-T05-FIXTURE_NOT_FOUND", f"Fixture {fixture_id} does not exist.")
    if revision_id is None:
        boundary = (
            _parse_utc(_canonical_utc(as_of_utc))
            if as_of_utc is not None
            else max(_parse_utc(item.observed_at_utc) for item in fixture_candidates)
        )
        candidate = _select_revision(fixture_candidates, boundary)
        if candidate is None:
            raise MatchweekError(
                "MV-T05-REVISION_NOT_FOUND",
                "No Fixture Revision is available for the appendix event.",
            )
    else:
        candidate = _revision_candidate(store, season, revision_id)
        if candidate.fixture_id != fixture_id:
            raise MatchweekError(
                "MV-T05-REVISION_FIXTURE_MISMATCH",
                "The requested Fixture Revision belongs to a different fixture.",
            )
    cutoff = _parse_utc(freeze.cutoff.cutoff_utc)
    as_of = (
        _parse_utc(_canonical_utc(as_of_utc))
        if as_of_utc is not None
        else max(_parse_utc(item.observed_at_utc) for item in fixture_candidates)
    )
    if _parse_utc(candidate.observed_at_utc) > as_of:
        raise MatchweekError(
            "MV-T05-REVISION_NOT_AVAILABLE",
            "The requested Fixture Revision was not known by the appendix observation time.",
        )
    post_supports = candidate.post_cutoff_supports(cutoff, as_of)
    if not post_supports and _parse_utc(candidate.observed_at_utc) <= cutoff:
        raise MatchweekError(
            "MV-T05-REVISION_NOT_POST_CUTOFF",
            "The requested Fixture Revision was already known at the Research Cutoff.",
        )
    observed_at = _post_cutoff_observation(candidate, cutoff, as_of)
    membership = next((item for item in freeze.memberships if item.subject_id == fixture_id), None)
    current_status = candidate.fixture_status.strip().upper()
    current_kickoff = candidate.kickoff_utc
    supplied_review = validity_review
    if supplied_review is not None and not identity_unchanged:
        supplied_review = replace(supplied_review, identity_unchanged=False)
    elif supplied_review is None and not identity_unchanged:
        supplied_review = PostCutoffValidityReview(identity_unchanged=False)
    previously_withdrawn = any(
        item.subject_id == fixture_id and item.disposition is AppendixDisposition.WITHDRAWN
        for item in freeze.appendix
    )
    if membership is None or membership.membership_state is not MembershipState.INCLUDED:
        had_pre_cutoff_revision = any(item.valid_supports(cutoff) for item in fixture_candidates)
        if current_kickoff is not None and freeze.window.contains(current_kickoff):
            event_kind = (
                AppendixEventKind.MOVED_IN_AFTER_CUTOFF
                if had_pre_cutoff_revision
                else AppendixEventKind.FIXTURE_ADDED_AFTER_CUTOFF
            )
            reason_code = "POST_CUTOFF_NOT_A_TARGET"
            reason = (
                "Fixture is inside the frozen window only after the Research Cutoff; "
                "it remains appendix-only."
            )
        else:
            event_kind = AppendixEventKind.REVISION_LEARNED_AFTER_CUTOFF
            reason_code = "POST_CUTOFF_REVISION"
            reason = "A later Fixture Revision was retained outside frozen membership."
        entry = _appendix_entry(
            freeze=freeze,
            candidate=candidate,
            event_kind=event_kind,
            disposition=AppendixDisposition.APPENDIX_ONLY,
            observed_at_utc=observed_at,
            validity_review=supplied_review or PostCutoffValidityReview(),
            reason_code=reason_code,
            reason=reason,
        )
        return _store_appendix_entry(store, entry)
    review = supplied_review
    if previously_withdrawn:
        if current_status == "POSTPONED":
            event_kind = AppendixEventKind.POSTPONED
        elif current_status == "CANCELLED":
            event_kind = AppendixEventKind.CANCELLED
        elif current_kickoff is not None and freeze.window.contains(current_kickoff):
            event_kind = AppendixEventKind.SAME_WINDOW_KICKOFF_CHANGE
        elif current_kickoff is not None and not freeze.window.contains(current_kickoff):
            event_kind = AppendixEventKind.MOVED_OUTSIDE_WINDOW
        else:
            event_kind = AppendixEventKind.REVISION_LEARNED_AFTER_CUTOFF
        entry = _appendix_entry(
            freeze=freeze,
            candidate=candidate,
            event_kind=event_kind,
            disposition=AppendixDisposition.WITHDRAWN,
            observed_at_utc=observed_at,
            validity_review=review or _default_review_for_unchanged_fixture(),
            reason_code="WITHDRAWAL_NOT_RESTORED",
            reason=(
                "The fixture was already withdrawn from the frozen Matchweek; "
                "a later reschedule cannot restore its production decision."
            ),
        )
        return _store_appendix_entry(store, entry)
    if current_status == "POSTPONED":
        event_kind = AppendixEventKind.POSTPONED
        disposition = AppendixDisposition.WITHDRAWN
        reason_code = "POSTPONED_AFTER_CUTOFF"
        reason = "The INCLUDED fixture was postponed after the Research Cutoff."
    elif current_status == "CANCELLED":
        event_kind = AppendixEventKind.CANCELLED
        disposition = AppendixDisposition.WITHDRAWN
        reason_code = "CANCELLED_AFTER_CUTOFF"
        reason = "The INCLUDED fixture was cancelled after the Research Cutoff."
    elif review is not None and review.identity_unchanged is False:
        event_kind = AppendixEventKind.IDENTITY_CONFLICT
        disposition = AppendixDisposition.WITHDRAWN
        reason_code = "IDENTITY_CONFLICT_AFTER_CUTOFF"
        reason = "The post-cutoff update could not preserve canonical Fixture identity."
    elif current_kickoff is None or _parse_utc(current_kickoff) <= cutoff:
        event_kind = AppendixEventKind.INVALID_PREMATCH_TIMING
        disposition = AppendixDisposition.WITHDRAWN
        reason_code = "KICKOFF_NOT_AFTER_CUTOFF"
        reason = "The corrected kickoff was at or before the frozen Research Cutoff."
    elif not freeze.window.contains(current_kickoff):
        event_kind = AppendixEventKind.MOVED_OUTSIDE_WINDOW
        disposition = AppendixDisposition.WITHDRAWN
        reason_code = "MOVED_OUTSIDE_MATCHWEEK"
        reason = "The INCLUDED fixture moved outside the frozen Friday-to-Monday window."
    elif membership.original_kickoff_utc != current_kickoff:
        event_kind = AppendixEventKind.SAME_WINDOW_KICKOFF_CHANGE
        if review is not None and review.passed:
            disposition = AppendixDisposition.PRESERVED
            reason_code = "SAME_WINDOW_VALIDITY_PASSED"
            reason = "The same-window kickoff change passed every pre-match validity assumption."
        else:
            disposition = AppendixDisposition.WITHDRAWN
            reason_code = "SAME_WINDOW_VALIDITY_FAILED"
            reason = (
                "The same-window kickoff change did not prove every pre-match validity assumption."
            )
    else:
        conflict_predicates = _material_conflicts(store, fixture_id, _parse_utc(observed_at))
        if conflict_predicates:
            event_kind = AppendixEventKind.MATERIAL_CONFLICT
            reason_code = "MATERIAL_CONFLICT_AFTER_CUTOFF"
            reason = "A later Fixture Revision retains unresolved material fixture detail conflict."
        else:
            event_kind = AppendixEventKind.REVISION_LEARNED_AFTER_CUTOFF
            reason_code = "POST_CUTOFF_REVISION"
            reason = "A later Fixture Revision was appended without changing frozen membership."
        disposition = AppendixDisposition.PRESERVED
    entry = _appendix_entry(
        freeze=freeze,
        candidate=candidate,
        event_kind=event_kind,
        disposition=disposition,
        observed_at_utc=observed_at,
        validity_review=review or _default_review_for_unchanged_fixture(),
        reason_code=reason_code,
        reason=reason,
    )
    return _store_appendix_entry(store, entry)


def append_post_cutoff_changes(
    store: Store,
    friday: date | datetime | str,
    *,
    season: str = "2026-27",
    as_of_utc: str | datetime | None = None,
    validity_reviews: Mapping[str, PostCutoffValidityReview] | None = None,
) -> tuple[PostCutoffFixtureAppendixEntry, ...]:
    """Append every newly observed T06 revision through the supplied observation time."""
    freeze = read_frozen_matchweek(store, friday, season=season)
    cutoff = _parse_utc(freeze.cutoff.cutoff_utc)
    candidates = _load_revision_candidates(store, season)
    unresolved = _load_unresolved_fixtures(store, season)
    as_of = (
        _parse_utc(_canonical_utc(as_of_utc))
        if as_of_utc is not None
        else max(
            (
                *(_parse_utc(item.observed_at_utc) for item in candidates),
                *(_parse_utc(item.observed_at_utc) for item in unresolved),
            ),
            default=cutoff,
        )
    )
    reviews = validity_reviews or {}
    events: list[PostCutoffFixtureAppendixEntry] = []
    revision_candidates = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.post_cutoff_supports(cutoff, as_of)
            or (
                _parse_utc(candidate.observed_at_utc) > cutoff
                and _parse_utc(candidate.observed_at_utc) <= as_of
            )
        ),
        key=lambda item: (
            _post_cutoff_observation(item, cutoff, as_of),
            item.fixture_id,
            item.revision_id,
        ),
    )
    for candidate in revision_candidates:
        review = reviews.get(candidate.revision_id) or reviews.get(candidate.fixture_id)
        events.append(
            append_post_cutoff_revision(
                store,
                friday,
                candidate.fixture_id,
                season=season,
                revision_id=candidate.revision_id,
                as_of_utc=as_of,
                validity_review=review,
            )
        )
    for item in unresolved:
        observed = _parse_utc(item.observed_at_utc)
        if cutoff < observed <= as_of:
            events.append(
                _store_appendix_entry(
                    store,
                    _unresolved_appendix_entry(
                        freeze=freeze,
                        unresolved=item,
                    ),
                )
            )
    return tuple(sorted(events, key=lambda item: (item.observed_at_utc, item.appendix_id)))


@dataclass(frozen=True)
class FixtureRevisionReference:
    fixture_id: str
    revision_id: str
    revision_digest: str


@dataclass(frozen=True)
class MatchweekReplay:
    freeze: MatchweekFreeze
    controlling_revisions: tuple[FixtureRevisionReference, ...]


def replay_matchweek(
    store: Store,
    friday: date | datetime | str,
    *,
    season: str = "2026-27",
    manifest_digest: str | None = None,
) -> MatchweekReplay:
    """Replay from the frozen manifest and controlling revision IDs only."""
    freeze = read_frozen_matchweek(store, friday, season=season)
    selected_manifest_digest = manifest_digest or freeze.snapshot_manifest_digest
    artifacts = ArtifactStore(store)
    try:
        outer = artifacts.verify_manifest(selected_manifest_digest)
    except Exception as error:
        if isinstance(error, MatchweekError):
            raise
        raise MatchweekError(
            "MV-T05-REPLAY_MANIFEST_INVALID",
            f"Frozen Snapshot Manifest could not be verified: {error}",
        ) from error
    if outer.matchweek_id.value != freeze.cutoff.matchweek_id:
        raise MatchweekError(
            "MV-T05-REPLAY_MANIFEST_MISMATCH",
            "Replay manifest does not belong to the requested Matchweek.",
        )
    if selected_manifest_digest != freeze.snapshot_manifest_digest:
        raise MatchweekError(
            "MV-T05-REPLAY_MANIFEST_MISMATCH",
            "Replay manifest is not the stored frozen Snapshot Manifest.",
        )
    membership_reference = next(
        (
            reference
            for reference in outer.artifacts
            if reference.digest == freeze.membership_manifest_digest
        ),
        None,
    )
    if membership_reference is None:
        raise MatchweekError(
            "MV-T05-REPLAY_MEMBERSHIP_MANIFEST_MISSING",
            "The frozen Snapshot Manifest does not reference the membership artifact.",
        )
    try:
        membership_manifest = MembershipManifest.from_bytes(
            artifacts.read_artifact(membership_reference.digest)
        )
    except Exception as error:
        if isinstance(error, MatchweekError):
            raise
        raise MatchweekError(
            "MV-T05-REPLAY_MEMBERSHIP_MANIFEST_INVALID",
            f"Frozen membership artifact could not be verified: {error}",
        ) from error
    if membership_manifest.digest != freeze.membership_manifest_digest:
        raise MatchweekError(
            "MV-T05-REPLAY_MEMBERSHIP_DIGEST_MISMATCH",
            "The stored membership artifact digest does not match the freeze record.",
        )
    if tuple(membership_manifest.memberships) != tuple(freeze.memberships):
        raise MatchweekError(
            "MV-T05-REPLAY_MEMBERSHIP_MISMATCH",
            "Stored membership rows differ from the frozen membership artifact.",
        )
    try:
        revision_snapshot = artifacts.read_artifact(freeze.revision_snapshot_digest)
    except Exception as error:
        raise MatchweekError(
            "MV-T05-REPLAY_REVISION_SNAPSHOT_INVALID",
            f"Frozen Fixture Revision snapshot could not be verified: {error}",
        ) from error
    if _sha256(revision_snapshot) != freeze.revision_snapshot_digest:
        raise MatchweekError(
            "MV-T05-REPLAY_REVISION_SNAPSHOT_INVALID",
            "Frozen Fixture Revision snapshot digest is invalid.",
        )
    connection = store._connection_for_repository()
    references: list[FixtureRevisionReference] = []
    for membership in freeze.memberships:
        if membership.controlling_revision_id is None:
            continue
        if membership.controlling_revision_digest is None:
            raise MatchweekError(
                "MV-T05-REPLAY_REVISION_DIGEST_MISSING",
                f"Membership {membership.membership_id} has no controlling revision digest.",
            )
        row = connection.execute(
            """
            SELECT fixture_id, revision_digest
            FROM fixture_revisions
            WHERE revision_id = ? AND fixture_id = ?
            """,
            (membership.controlling_revision_id, membership.subject_id),
        ).fetchone()
        if row is None:
            raise MatchweekError(
                "MV-T05-REPLAY_REVISION_MISSING",
                f"Controlling Fixture Revision {membership.controlling_revision_id} is missing.",
            )
        if str(row[1]) != membership.controlling_revision_digest:
            raise MatchweekError(
                "MV-T05-REPLAY_REVISION_DIGEST_MISMATCH",
                f"Controlling Fixture Revision {membership.controlling_revision_id} changed.",
            )
        references.append(
            FixtureRevisionReference(
                fixture_id=membership.subject_id,
                revision_id=membership.controlling_revision_id,
                revision_digest=membership.controlling_revision_digest,
            )
        )
    return MatchweekReplay(freeze, tuple(sorted(references, key=lambda item: item.revision_id)))


@dataclass(frozen=True)
class MatchweekFreezePlan:
    friday: str
    season: str = "2026-27"
    as_of_utc: str | None = None

    def __post_init__(self) -> None:
        MatchweekWindow.for_friday(self.friday)
        if self.as_of_utc is not None:
            canonical = _canonical_utc(self.as_of_utc)
            if canonical != self.as_of_utc:
                raise ValueError("T05 plan observation time must be canonical UTC.")

    @property
    def window(self) -> MatchweekWindow:
        return MatchweekWindow.for_friday(self.friday)

    @property
    def run_key(self) -> str:
        return f"t05-matchweek-freeze:{self.season}:{self.window.friday_local.isoformat()}"

    @property
    def plan_digest(self) -> str:
        return _sha256(
            _canonical_json(
                {
                    "as_of_utc": self.as_of_utc,
                    "friday": self.window.friday_local.isoformat(),
                    "rules": MATCHWEEK_RULES_NAME,
                    "season": self.season,
                }
            )
        )


def build_t05_input_contract(store: Store, plan: MatchweekFreezePlan) -> RunInputContract:
    candidates = _load_revision_candidates(store, plan.season)
    source_digest = _source_snapshot_digest(candidates)
    schema_identity = ":".join(migration.checksum for migration in MIGRATIONS)
    return RunInputContract.from_values(
        {
            "source": f"T06:FIXTURE_REVISIONS:{source_digest}",
            "cutoff": f"T05:MATCHWEEK_RULES:{MATCHWEEK_RULES_NAME}:{plan.plan_digest}",
            "preference_set": "T05:NOT_APPLICABLE",
            "policy": "T05:NOT_APPLICABLE",
            "model": "T05:NOT_APPLICABLE",
            "feature": "T05:SCHEDULE_FIELDS_ONLY",
            "research_rule": "T05:MATCHWEEK_MEMBERSHIP_V1",
            "canonical_contract": "MATCHVET_CANONICAL_CONTRACT_V1",
            "schema": schema_identity,
            "environment": "T05:LOCAL_ONLY",
            "software": "MATCHVET_T05_MATCHWEEK_V1",
        }
    )


class MatchweekFreezeRunner:
    """Run T05 publication through T04's bounded checkpoint lifecycle."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Matchweek freezing requires a healthy writable store.")
        self.store = store
        self.last_freeze: MatchweekFreeze | None = None

    def start(
        self,
        plan: MatchweekFreezePlan,
        *,
        observation: ResourceObservation,
        progress: Callable[[RunStatus], None] | None = None,
    ) -> RunStatus:
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        status = coordinator.start(
            matchweek=plan.run_key,
            inputs=build_t05_input_contract(self.store, plan),
            estimate=self._estimate(),
            observation=observation,
            executor=lambda context: self._execute(plan, context),
            progress=progress,
        )
        self.last_freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        return status

    def resume(
        self,
        run_id: str,
        plan: MatchweekFreezePlan,
        *,
        observation: ResourceObservation,
        progress: Callable[[RunStatus], None] | None = None,
    ) -> RunStatus:
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        status = coordinator.resume(
            run_id,
            inputs=build_t05_input_contract(self.store, plan),
            estimate=self._estimate(),
            observation=observation,
            executor=lambda context: self._execute(plan, context),
            progress=progress,
        )
        self.last_freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        return status

    def _estimate(self) -> ResourceEstimate:
        return ResourceEstimate(
            storage_growth_bytes=MIB,
            peak_memory_bytes=128 * MIB,
            duration_seconds=60,
            network_bytes=0,
            cpu_heavy_operations=1,
        )

    def _execute(self, plan: MatchweekFreezePlan, context: WorkContext) -> WorkResult:
        if context.phase is not RunPhase.EVIDENCE_ACQUISITION:
            return WorkResult.for_phase(context.phase)
        frozen = freeze_matchweek(
            self.store,
            plan.friday,
            season=plan.season,
            as_of_utc=plan.as_of_utc,
        )
        self.last_freeze = frozen
        return WorkResult(
            result_digest=frozen.membership_manifest_digest,
            artifact_digests=(
                frozen.membership_manifest_digest,
                frozen.revision_snapshot_digest,
                frozen.snapshot_manifest_digest,
            ),
        )

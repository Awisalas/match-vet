"""T07 official and contextual Source Evidence.

This module accepts evidence that has already been obtained by an operator or an
approved source adapter.  It never discovers pages, follows links, scrapes a
site, or calls a private endpoint.  It records the source and information state
so later Evidence Research work can decide what is usable at a Matchweek
Research Cutoff.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from matchvet.artifacts import ArtifactStore
from matchvet.ingestion import deterministic_identifier, sha256_bytes
from matchvet.store import CanonicalIdentifier, Store, StoreTransaction


class EvidenceError(Exception):
    """Base class for T07 evidence recording failures."""


class EvidenceValidationError(EvidenceError):
    """An evidence value or canonical reference is invalid."""


class EvidencePolicyError(EvidenceError):
    """A source or retention operation is outside the settled policy."""


class EvidenceIntegrityError(EvidenceError):
    """An immutable identity was reused with different content."""


class EvidenceState(StrEnum):
    OBSERVED = "OBSERVED"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


OBSERVED = EvidenceState.OBSERVED
ABSENT = EvidenceState.ABSENT
UNKNOWN = EvidenceState.UNKNOWN


class SubjectKind(StrEnum):
    FIXTURE = "FIXTURE"
    TEAM = "TEAM"
    PERSON = "PERSON"


class EvidenceType(StrEnum):
    INJURY = "INJURY"
    SUSPENSION = "SUSPENSION"
    AVAILABILITY = "AVAILABILITY"
    EXPECTED_LINEUP = "EXPECTED_LINEUP"
    ROTATION = "ROTATION"
    MANAGER_CHANGE = "MANAGER_CHANGE"
    REGIME_CHANGE = "REGIME_CHANGE"
    TACTICAL_CONTEXT = "TACTICAL_CONTEXT"
    REFEREE_APPOINTMENT = "REFEREE_APPOINTMENT"
    REFEREE_CONTEXT = "REFEREE_CONTEXT"


class EvidenceClass(StrEnum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    CONTEXT = "CONTEXT"


EvidenceMateriality = EvidenceClass


class CutoffEligibility(StrEnum):
    CUTOFF_VALID = "CUTOFF_VALID"
    POST_CUTOFF = "POST_CUTOFF"
    INDETERMINATE = "INDETERMINATE"


class CaptureKind(StrEnum):
    RETAINED = "RETAINED"
    CITATION_ONLY = "CITATION_ONLY"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SourceClass(StrEnum):
    OFFICIAL_COMPETITION = "OFFICIAL_COMPETITION"
    OFFICIAL_FEDERATION = "OFFICIAL_FEDERATION"
    OFFICIAL_LEAGUE = "OFFICIAL_LEAGUE"
    OFFICIAL_CLUB = "OFFICIAL_CLUB"
    OFFICIAL_MANAGER = "OFFICIAL_MANAGER"
    OFFICIAL_EDITORIAL = "OFFICIAL_EDITORIAL"
    STRUCTURED_PROVIDER = "STRUCTURED_PROVIDER"
    OPEN_DATASET = "OPEN_DATASET"
    SPECIALIST_REPORTING = "SPECIALIST_REPORTING"


_SOURCE_CLASS_ALIASES = {
    "OFFICIAL": SourceClass.OFFICIAL_COMPETITION.value,
    "COMPETITION": SourceClass.OFFICIAL_COMPETITION.value,
    "OFFICIAL_COMPETITION": SourceClass.OFFICIAL_COMPETITION.value,
    "FEDERATION": SourceClass.OFFICIAL_FEDERATION.value,
    "OFFICIAL_FEDERATION": SourceClass.OFFICIAL_FEDERATION.value,
    "LEAGUE": SourceClass.OFFICIAL_LEAGUE.value,
    "OFFICIAL_LEAGUE": SourceClass.OFFICIAL_LEAGUE.value,
    "CLUB": SourceClass.OFFICIAL_CLUB.value,
    "OFFICIAL_CLUB": SourceClass.OFFICIAL_CLUB.value,
    "MANAGER": SourceClass.OFFICIAL_MANAGER.value,
    "OFFICIAL_MANAGER": SourceClass.OFFICIAL_MANAGER.value,
    "EDITORIAL": SourceClass.OFFICIAL_EDITORIAL.value,
    "OFFICIAL_EDITORIAL": SourceClass.OFFICIAL_EDITORIAL.value,
    "STRUCTURED": SourceClass.STRUCTURED_PROVIDER.value,
    "PROVIDER": SourceClass.STRUCTURED_PROVIDER.value,
    "STRUCTURED_PROVIDER": SourceClass.STRUCTURED_PROVIDER.value,
    "OPEN": SourceClass.OPEN_DATASET.value,
    "OPEN_DATASET": SourceClass.OPEN_DATASET.value,
    "SPECIALIST": SourceClass.SPECIALIST_REPORTING.value,
    "SPECIALIST_REPORTING": SourceClass.SPECIALIST_REPORTING.value,
}

_SOURCE_RETENTION_CLASSES = frozenset({"RETAIN_PRIVATE", "RETAIN_REUSABLE"})
_PROHIBITED_SOURCE_TOKENS = (
    "scrap",
    "browser",
    "reverse",
    "private_endpoint",
    "private endpoint",
    "crawler",
    "crawl",
    "mirror",
    "bot",
    "automation",
)
_REJECTED_FOUNDATIONS = (
    "api-football",
    "apisports",
    "fbref",
    "flashscore",
    "fotmob",
    "sofascore",
    "sports-reference",
    "sportmonks",
    "thesportsdb",
    "transfermarkt",
    "understat",
)
_EVIDENCE_TYPE_ALIASES = {
    "INJURIES": EvidenceType.INJURY.value,
    "SUSPENSIONS": EvidenceType.SUSPENSION.value,
    "AVAILABILITY_DOUBTFUL": EvidenceType.AVAILABILITY.value,
    "DOUBTFUL": EvidenceType.AVAILABILITY.value,
    "LINEUP": EvidenceType.EXPECTED_LINEUP.value,
    "EXPECTED_ROTATION": EvidenceType.ROTATION.value,
    "MANAGER": EvidenceType.MANAGER_CHANGE.value,
    "REGIME": EvidenceType.REGIME_CHANGE.value,
    "TACTICS": EvidenceType.TACTICAL_CONTEXT.value,
    "TACTICAL": EvidenceType.TACTICAL_CONTEXT.value,
    "REFEREE": EvidenceType.REFEREE_APPOINTMENT.value,
    "REFEREE_APPOINTMENTS": EvidenceType.REFEREE_APPOINTMENT.value,
}
_DEFAULT_EVIDENCE_CLASSES = {
    EvidenceType.INJURY.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.SUSPENSION.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.AVAILABILITY.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.EXPECTED_LINEUP.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.ROTATION.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.MANAGER_CHANGE.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.REGIME_CHANGE.value: EvidenceClass.IMPORTANT.value,
    EvidenceType.TACTICAL_CONTEXT.value: EvidenceClass.CONTEXT.value,
    EvidenceType.REFEREE_APPOINTMENT.value: EvidenceClass.CONTEXT.value,
    EvidenceType.REFEREE_CONTEXT.value: EvidenceClass.CONTEXT.value,
}


def _enum_text(value: str | StrEnum, *, name: str) -> str:
    text = value.value if isinstance(value, StrEnum) else value
    if not isinstance(text, str) or not text.strip():
        raise EvidenceValidationError(f"{name} must be a non-empty string.")
    return text.strip().upper()


def _source_class(value: str | SourceClass) -> str:
    text = _enum_text(value, name="Source class")
    try:
        return _SOURCE_CLASS_ALIASES[text]
    except KeyError as error:
        raise EvidencePolicyError(f"Unsupported source class {text}.") from error


def _evidence_type(value: str | EvidenceType) -> str:
    text = _enum_text(value, name="Evidence type")
    selected = _EVIDENCE_TYPE_ALIASES.get(text, text)
    if selected not in {item.value for item in EvidenceType}:
        raise EvidenceValidationError(f"Unsupported T07 evidence type {selected}.")
    return selected


def _subject_kind(value: str | SubjectKind) -> str:
    text = _enum_text(value, name="Subject kind")
    if text not in {item.value for item in SubjectKind}:
        raise EvidenceValidationError("Evidence subjects must be fixtures, teams, or people.")
    return text


def _evidence_state(value: str | EvidenceState) -> str:
    text = _enum_text(value, name="Evidence state")
    if text not in {item.value for item in EvidenceState}:
        raise EvidenceValidationError("Evidence state must be OBSERVED, ABSENT, or UNKNOWN.")
    return text


def _evidence_class(value: str | EvidenceClass) -> str:
    text = _enum_text(value, name="Evidence class")
    if text not in {item.value for item in EvidenceClass}:
        raise EvidenceValidationError("Evidence class must be CRITICAL, IMPORTANT, or CONTEXT.")
    return text


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise EvidenceValidationError("Evidence values must be JSON-serializable.") from error


def _json_value(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return cast(object | None, json.loads(value))
    except json.JSONDecodeError as error:
        raise EvidenceIntegrityError("Stored evidence value is not canonical JSON.") from error


def _integer_value(value: object) -> int:
    if isinstance(value, bool):
        raise EvidenceIntegrityError("Stored integer value has an invalid type.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise EvidenceIntegrityError("Stored integer value is invalid.") from error
    raise EvidenceIntegrityError("Stored integer value has an invalid type.")


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceValidationError(
            "Timestamps must be ISO-8601 values with an explicit UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise EvidenceValidationError("Timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _optional_utc(value: str | None) -> str | None:
    return _canonical_utc(value) if value is not None else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _normal_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _id_value(value: str | CanonicalIdentifier, *, expected_kind: str | None = None) -> str:
    if isinstance(value, CanonicalIdentifier):
        if expected_kind is not None and value.kind != expected_kind:
            raise EvidenceValidationError(
                f"Expected a {expected_kind} canonical identifier, got {value.kind}."
            )
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError("Canonical references must be non-empty IDs.")
    selected = value.strip()
    try:
        parsed = UUID(selected)
    except ValueError as error:
        raise EvidenceValidationError("Canonical references must be UUIDs.") from error
    if str(parsed) != selected:
        raise EvidenceValidationError("Canonical UUIDs must use canonical lowercase form.")
    return selected


def _validate_source_policy(
    source: SourceIdentity,
    *,
    locator: str | None = None,
) -> None:
    source_class = _source_class(source.source_class)
    del source_class
    searchable = " ".join(
        (
            source.source_key,
            source.base_locator,
            source.access_method,
            locator or "",
        )
    ).casefold()
    if any(token in searchable for token in _PROHIBITED_SOURCE_TOKENS):
        raise EvidencePolicyError(
            "T07 accepts direct or manually cited evidence only; prohibited automation or "
            "private-endpoint access was requested."
        )
    if any(token in searchable for token in _REJECTED_FOUNDATIONS):
        raise EvidencePolicyError("The requested source is a rejected evidence foundation.")
    if not source.source_key.strip() or not source.canonical_name.strip():
        raise EvidenceValidationError("Source identity requires a key and canonical name.")
    if not source.owner.strip() or not source.base_locator.strip():
        raise EvidenceValidationError("Source identity requires owner and base locator.")
    if not source.access_method.strip():
        raise EvidenceValidationError("Source identity requires an access method.")
    if not source.allowed_use.strip() or not source.retention_status.strip():
        raise EvidenceValidationError("Source rights and retention status are required.")
    if source.retention_status.strip().upper() == "RETAIN_REUSABLE" and not source.redistributable:
        raise EvidencePolicyError("Reusable source retention requires redistributable rights.")
    if not source.terms_reference.strip():
        raise EvidenceValidationError("Source terms reference is required.")


def authority_rank(evidence_type: str | EvidenceType, source_class: str | SourceClass) -> int:
    """Return the settled lower-is-stronger authority rank for one assertion."""

    kind = _evidence_type(evidence_type)
    source = _source_class(source_class)
    official = {
        SourceClass.OFFICIAL_COMPETITION.value: 20,
        SourceClass.OFFICIAL_FEDERATION.value: 30,
        SourceClass.OFFICIAL_LEAGUE.value: 40,
        SourceClass.OFFICIAL_CLUB.value: 50,
        SourceClass.OFFICIAL_MANAGER.value: 50,
        SourceClass.OFFICIAL_EDITORIAL.value: 60,
    }
    if kind in {EvidenceType.INJURY.value, EvidenceType.AVAILABILITY.value}:
        ordering = {
            SourceClass.OFFICIAL_CLUB.value: 0,
            SourceClass.OFFICIAL_MANAGER.value: 0,
            SourceClass.OFFICIAL_LEAGUE.value: 10,
            SourceClass.OFFICIAL_COMPETITION.value: 20,
            SourceClass.OFFICIAL_FEDERATION.value: 30,
        }
        if source in ordering:
            return ordering[source]
    elif kind == EvidenceType.SUSPENSION.value:
        ordering = {
            SourceClass.OFFICIAL_COMPETITION.value: 0,
            SourceClass.OFFICIAL_FEDERATION.value: 10,
            SourceClass.OFFICIAL_CLUB.value: 20,
            SourceClass.OFFICIAL_LEAGUE.value: 30,
        }
        if source in ordering:
            return ordering[source]
    elif kind == EvidenceType.EXPECTED_LINEUP.value:
        ordering = {
            SourceClass.OFFICIAL_EDITORIAL.value: 0,
            SourceClass.OFFICIAL_CLUB.value: 10,
            SourceClass.OFFICIAL_MANAGER.value: 10,
            SourceClass.OFFICIAL_LEAGUE.value: 20,
        }
        if source in ordering:
            return ordering[source]
    elif kind in {EvidenceType.MANAGER_CHANGE.value, EvidenceType.REGIME_CHANGE.value}:
        ordering = {
            SourceClass.OFFICIAL_CLUB.value: 0,
            SourceClass.OFFICIAL_MANAGER.value: 0,
            SourceClass.OFFICIAL_LEAGUE.value: 10,
            SourceClass.OFFICIAL_COMPETITION.value: 20,
            SourceClass.OFFICIAL_FEDERATION.value: 30,
        }
        if source in ordering:
            return ordering[source]
    elif kind == EvidenceType.TACTICAL_CONTEXT.value:
        ordering = {
            SourceClass.OFFICIAL_MANAGER.value: 0,
            SourceClass.OFFICIAL_CLUB.value: 10,
            SourceClass.OFFICIAL_COMPETITION.value: 20,
            SourceClass.OFFICIAL_LEAGUE.value: 30,
        }
        if source in ordering:
            return ordering[source]
    elif kind in {
        EvidenceType.REFEREE_APPOINTMENT.value,
        EvidenceType.REFEREE_CONTEXT.value,
    }:
        ordering = {
            SourceClass.OFFICIAL_COMPETITION.value: 0,
            SourceClass.OFFICIAL_FEDERATION.value: 10,
            SourceClass.OFFICIAL_LEAGUE.value: 20,
        }
        if source in ordering:
            return ordering[source]
    if source in official:
        return official[source]
    if source == SourceClass.STRUCTURED_PROVIDER.value:
        return 100
    if source == SourceClass.OPEN_DATASET.value:
        return 110
    if source == SourceClass.SPECIALIST_REPORTING.value:
        return 200
    return 900


def classify_evidence(
    evidence_type: str | EvidenceType,
    source_class: str | SourceClass,
    requested: str | EvidenceClass | None = None,
) -> EvidenceClass:
    """Classify an assertion without making a Research Sufficiency decision."""

    kind = _evidence_type(evidence_type)
    source = _source_class(source_class)
    selected = (
        _evidence_class(requested)
        if requested is not None
        else _DEFAULT_EVIDENCE_CLASSES.get(kind, EvidenceClass.CONTEXT.value)
    )
    if source == SourceClass.SPECIALIST_REPORTING.value:
        if selected == EvidenceClass.CRITICAL.value:
            raise EvidencePolicyError(
                "Specialist reporting is contextual or corroborative only and cannot be "
                "classified as Critical Evidence."
            )
        if requested is None:
            selected = EvidenceClass.CONTEXT.value
    return EvidenceClass(selected)


@dataclass(frozen=True)
class SourceIdentity:
    source_key: str
    canonical_name: str
    owner: str
    source_class: str | SourceClass
    access_method: str
    base_locator: str
    allowed_use: str
    retention_status: str
    redistributable: bool
    terms_reference: str
    source_id: str | None = None
    terms_observed_at_utc: str | None = None

    def __post_init__(self) -> None:
        _validate_source_policy(self)
        object.__setattr__(self, "source_class", _source_class(self.source_class))
        if self.source_id is not None:
            object.__setattr__(
                self,
                "source_id",
                _id_value(self.source_id, expected_kind="source"),
            )
        object.__setattr__(self, "terms_observed_at_utc", _optional_utc(self.terms_observed_at_utc))

    @property
    def authority_scope(self) -> str:
        """Return the normalized source authority scope used by T07 ranking."""

        return str(self.source_class)


@dataclass(frozen=True)
class IndependentOrigin:
    origin_key: str
    organization: str
    locator: str | None = None
    classification: str = "DIRECT_ORIGIN"
    origin_id: str | None = None

    def __post_init__(self) -> None:
        if not self.origin_key.strip() or not self.organization.strip():
            raise EvidenceValidationError("Independent origins require a key and organization.")
        if not self.classification.strip():
            raise EvidenceValidationError("Independent origins require a classification.")
        if self.origin_id is not None:
            object.__setattr__(self, "origin_id", _id_value(self.origin_id, expected_kind="origin"))


@dataclass(frozen=True)
class SourceCaptureInput:
    source: SourceIdentity
    origin: IndependentOrigin
    locator: str
    retrieved_at_utc: str
    published_at_utc: str | None = None
    content: bytes | None = None
    content_sha256: str | None = None
    capture_key: str | None = None
    access_method: str | None = None
    response_status: int = 200
    content_type: str = "text/html"
    capture_kind: str | CaptureKind | None = None
    citation_note: str | None = None
    source_published_at_utc: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceIdentity) or not isinstance(
            self.origin, IndependentOrigin
        ):
            raise EvidenceValidationError(
                "A capture requires a SourceIdentity and IndependentOrigin."
            )
        _validate_source_policy(self.source, locator=self.locator)
        if not self.locator.strip():
            raise EvidenceValidationError("Source capture locator is required.")
        if self.response_status < 100 or self.response_status > 599:
            raise EvidenceValidationError("Source response status must be between 100 and 599.")
        if not self.content_type.strip():
            raise EvidenceValidationError("Source capture content type is required.")
        retrieved = _canonical_utc(self.retrieved_at_utc)
        published = _optional_utc(self.published_at_utc)
        source_published = _optional_utc(self.source_published_at_utc)
        if published is not None and source_published is not None and published != source_published:
            raise EvidenceValidationError("Published-time aliases must carry the same timestamp.")
        selected_published = published or source_published
        object.__setattr__(self, "retrieved_at_utc", retrieved)
        object.__setattr__(self, "published_at_utc", selected_published)
        object.__setattr__(self, "source_published_at_utc", selected_published)
        if self.content is not None and not isinstance(self.content, bytes):
            raise EvidenceValidationError("Retained source content must be bytes.")
        if (
            self.content_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None
        ):
            raise EvidenceValidationError("Content digests must be lowercase SHA-256 values.")
        if self.content is not None:
            actual_digest = sha256_bytes(self.content)
            if self.content_sha256 is not None and self.content_sha256 != actual_digest:
                raise EvidenceIntegrityError("Source content does not match its supplied digest.")
            object.__setattr__(self, "content_sha256", actual_digest)
        selected_kind = self.capture_kind
        if selected_kind is None:
            selected_kind = (
                CaptureKind.RETAINED if self.content is not None else CaptureKind.CITATION_ONLY
            )
        selected_kind_text = _enum_text(selected_kind, name="Capture kind")
        if selected_kind_text not in {item.value for item in CaptureKind}:
            raise EvidenceValidationError("Capture kind must be RETAINED or CITATION_ONLY.")
        if selected_kind_text == CaptureKind.RETAINED.value and self.content is None:
            raise EvidencePolicyError("A retained capture must include source bytes.")
        if selected_kind_text == CaptureKind.CITATION_ONLY.value and self.content is not None:
            raise EvidencePolicyError("Citation-only evidence cannot retain source bytes.")
        if (
            self.source.source_class == SourceClass.SPECIALIST_REPORTING.value
            and self.content is not None
        ):
            raise EvidencePolicyError("Specialist reporting is accepted as citation-only context.")
        object.__setattr__(self, "capture_kind", selected_kind_text)
        if self.access_method is None:
            object.__setattr__(self, "access_method", self.source.access_method)
        elif not self.access_method.strip():
            raise EvidenceValidationError("Source capture access method is required.")
        if self.capture_key is not None and not self.capture_key.strip():
            raise EvidenceValidationError("Capture keys cannot be empty.")


EvidenceCaptureInput = SourceCaptureInput


@dataclass(frozen=True)
class EvidenceAssertionInput:
    subject_kind: str | SubjectKind
    subject_id: str | CanonicalIdentifier
    evidence_type: str | EvidenceType
    predicate: str
    state: str | EvidenceState = EvidenceState.OBSERVED
    value: object | None = None
    evidence_class: str | EvidenceClass | None = None
    materiality: str | EvidenceClass | None = None
    unknown_reason: str | None = None
    affirmative_basis: str | None = None
    event_time_utc: str | None = None
    effective_time_utc: str | None = None
    assertion_key: str | None = None
    source_row_key: str | None = None
    correction_of: str | None = None
    predecessor_assertion_id: str | None = None

    def __post_init__(self) -> None:
        kind = _subject_kind(self.subject_kind)
        object.__setattr__(self, "subject_kind", kind)
        expected_kind = kind.casefold()
        object.__setattr__(
            self,
            "subject_id",
            _id_value(self.subject_id, expected_kind=expected_kind),
        )
        evidence_type = _evidence_type(self.evidence_type)
        object.__setattr__(self, "evidence_type", evidence_type)
        if not self.predicate.strip():
            raise EvidenceValidationError("Evidence predicates are required.")
        state = _evidence_state(self.state)
        object.__setattr__(self, "state", state)
        if state == EvidenceState.OBSERVED.value:
            if self.value is None:
                raise EvidenceValidationError("OBSERVED evidence requires a value.")
            if self.unknown_reason is not None or self.affirmative_basis is not None:
                raise EvidenceValidationError(
                    "OBSERVED evidence cannot carry absence or unknown reasons."
                )
            _canonical_json(self.value)
        elif state == EvidenceState.ABSENT.value:
            if self.value is not None or self.unknown_reason is not None:
                raise EvidenceValidationError(
                    "ABSENT evidence cannot carry a value or unknown reason."
                )
            if not self.affirmative_basis or not self.affirmative_basis.strip():
                raise EvidenceValidationError(
                    "ABSENT evidence requires affirmative provenance basis."
                )
        elif state == EvidenceState.UNKNOWN.value:
            if self.value is not None or self.affirmative_basis is not None:
                raise EvidenceValidationError(
                    "UNKNOWN evidence cannot carry a value or absence basis."
                )
            if not self.unknown_reason or not self.unknown_reason.strip():
                raise EvidenceValidationError("UNKNOWN evidence requires a reason.")
        selected_classes = [
            item for item in (self.evidence_class, self.materiality) if item is not None
        ]
        if len(selected_classes) == 2 and _evidence_class(selected_classes[0]) != _evidence_class(
            selected_classes[1]
        ):
            raise EvidenceValidationError("Evidence class and materiality disagree.")
        selected_class = selected_classes[0] if selected_classes else None
        if selected_class is not None:
            object.__setattr__(self, "evidence_class", _evidence_class(selected_class))
        object.__setattr__(self, "materiality", None)
        object.__setattr__(self, "event_time_utc", _optional_utc(self.event_time_utc))
        object.__setattr__(self, "effective_time_utc", _optional_utc(self.effective_time_utc))
        predecessor = self.correction_of or self.predecessor_assertion_id
        if (
            self.correction_of is not None
            and self.predecessor_assertion_id is not None
            and _id_value(self.correction_of, expected_kind="evidence_assertion")
            != _id_value(
                self.predecessor_assertion_id,
                expected_kind="evidence_assertion",
            )
        ):
            raise EvidenceValidationError("Correction predecessor fields disagree.")
        if predecessor is not None:
            object.__setattr__(
                self,
                "correction_of",
                _id_value(predecessor, expected_kind="evidence_assertion"),
            )
        if self.assertion_key is not None and not self.assertion_key.strip():
            raise EvidenceValidationError("Assertion keys cannot be empty.")
        if self.source_row_key is not None and not self.source_row_key.strip():
            raise EvidenceValidationError("Source row keys cannot be empty.")


AssertionInput = EvidenceAssertionInput


@dataclass(frozen=True)
class PersonRecord:
    person_id: str
    canonical_name: str
    normalized_name: str
    role: str


@dataclass(frozen=True)
class SourceIdentityRecord:
    source_id: str
    source_key: str
    canonical_name: str
    owner: str
    source_class: str
    access_method: str
    base_locator: str
    allowed_use: str
    retention_status: str
    redistributable: bool
    terms_reference: str
    terms_observed_at_utc: str

    @property
    def authority_scope(self) -> str:
        return self.source_class


@dataclass(frozen=True)
class IndependentOriginRecord:
    origin_id: str
    origin_key: str
    organization: str
    locator: str | None
    classification: str


@dataclass(frozen=True)
class SourceCaptureRecord:
    capture_id: str
    source_id: str
    source_key: str
    origin_id: str
    origin_key: str
    locator: str
    access_method: str
    retrieved_at_utc: str
    published_at_utc: str | None
    response_status: int
    content_type: str
    content_sha256: str | None
    byte_length: int
    artifact_digest: str | None
    capture_kind: CaptureKind
    retention_status: str
    rights: Mapping[str, object]
    terms_reference: str
    citation_note: str | None

    @property
    def source_published_at_utc(self) -> str | None:
        return self.published_at_utc


@dataclass(frozen=True)
class CutoffAssessmentRecord:
    assessment_id: str
    assertion_id: str
    research_cutoff_id: str | None
    cutoff_utc: str | None
    eligibility: CutoffEligibility
    reason: str
    assessed_at_utc: str


@dataclass(frozen=True)
class EvidenceAssertionRecord:
    assertion_id: str
    capture_id: str | None
    source_id: str | None
    origin_id: str | None
    source_class: str
    source_row_key: str
    subject_kind: SubjectKind
    subject_id: str
    evidence_type: str
    predicate: str
    evidence_class: EvidenceClass
    authority_rank: int
    state: EvidenceState
    value: object | None
    unknown_reason: str | None
    affirmative_basis: str | None
    event_time_utc: str | None
    effective_time_utc: str | None
    correction_of: str | None
    provenance: Mapping[str, object]
    cutoff_eligibility: CutoffEligibility
    cutoff_reason: str

    @property
    def evidence_state(self) -> EvidenceState:
        return self.state

    @property
    def materiality(self) -> EvidenceClass:
        return self.evidence_class

    @property
    def predecessor_assertion_id(self) -> str | None:
        return self.correction_of


@dataclass(frozen=True)
class EvidenceConflictRecord:
    conflict_id: str
    subject_kind: SubjectKind
    subject_id: str
    evidence_type: str
    predicate: str
    value_digest: str
    status: str
    assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class CorroborationRecord:
    subject_kind: SubjectKind
    subject_id: str
    evidence_type: str
    predicate: str
    value: object
    origin_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]

    @property
    def independent_origin_count(self) -> int:
        return len(self.origin_ids)

    @property
    def count(self) -> int:
        return self.independent_origin_count


@dataclass(frozen=True)
class SourceStatusRecord:
    status_id: str
    source_id: str
    status: SourceStatus
    reason: str
    observed_at_utc: str


@dataclass(frozen=True)
class ConflictResolutionRecord:
    resolution_id: str
    conflict_id: str
    selected_assertion_id: str
    basis: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class EvidenceIngestionResult:
    capture: SourceCaptureRecord
    assertions: tuple[EvidenceAssertionRecord, ...]
    cutoff_assessments: tuple[CutoffAssessmentRecord, ...]
    conflicts: tuple[EvidenceConflictRecord, ...]
    from_existing_capture: bool = False


def _person_role(value: str) -> str:
    text = value.strip().upper()
    if text in {"PLAYER", "MANAGER", "REFEREE", "OTHER"}:
        return text
    if text in {"COACH", "STAFF", "OFFICIAL"}:
        return "OTHER"
    raise EvidenceValidationError("Person roles must be PLAYER, MANAGER, REFEREE, or OTHER.")


class EvidenceRecorder:
    """Record caller-supplied official or contextual evidence in T07 tables."""

    _ALLOWED_RESOLUTION_BASIS = frozenset({"AUTHORITY", "DIRECTNESS", "FRESHNESS", "RELEVANCE"})

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Evidence recording requires a healthy writable store.")
        self._store = store
        self._artifacts = ArtifactStore(store)

    def register_person(
        self,
        canonical_name: str,
        *,
        role: str = "OTHER",
        person_id: str | CanonicalIdentifier | None = None,
        created_at_utc: str | None = None,
    ) -> str:
        if not canonical_name.strip():
            raise EvidenceValidationError("Canonical person name is required.")
        selected_name = canonical_name.strip()
        selected_role = _person_role(role)
        normalized = _normal_name(selected_name)
        selected_id = (
            _id_value(person_id, expected_kind="person")
            if person_id is not None
            else deterministic_identifier("person", f"{selected_role}:{normalized}")
        )
        created = _canonical_utc(created_at_utc) if created_at_utc is not None else _now()
        with self._store.transaction() as transaction:
            existing = transaction.execute(
                """
                SELECT person_id, canonical_name, normalized_name, person_role
                FROM people WHERE person_id = ?
                """,
                (selected_id,),
            ).fetchone()
            if existing is not None:
                if tuple(str(value) for value in existing[1:]) != (
                    selected_name,
                    normalized,
                    selected_role,
                ):
                    raise EvidenceIntegrityError(
                        "Canonical person identity was reused differently."
                    )
                return selected_id
            duplicate = transaction.execute(
                """
                SELECT person_id FROM people
                WHERE normalized_name = ? AND person_role = ?
                """,
                (normalized, selected_role),
            ).fetchone()
            if duplicate is not None:
                if person_id is not None and str(duplicate[0]) != selected_id:
                    raise EvidenceIntegrityError(
                        "Canonical person name and role already belong to another person."
                    )
                return str(duplicate[0])
            transaction.add_identifier_if_missing(CanonicalIdentifier("person", selected_id))
            transaction.execute(
                """
                INSERT INTO people (person_id, canonical_name, normalized_name, person_role,
                                    created_at_utc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (selected_id, selected_name, normalized, selected_role, created),
            )
        return selected_id

    create_person = register_person

    def suspend_source(
        self,
        source: str | CanonicalIdentifier | SourceIdentity,
        *,
        reason: str,
        observed_at_utc: str,
    ) -> SourceStatusRecord:
        source_id = self._source_id_from_value(source)
        if not reason.strip():
            raise EvidenceValidationError("Source suspension requires a reason.")
        observed = _canonical_utc(observed_at_utc)
        return self.set_source_status(source_id, SourceStatus.SUSPENDED, reason, observed)

    def reactivate_source(
        self,
        source: str | CanonicalIdentifier | SourceIdentity,
        *,
        reason: str,
        observed_at_utc: str,
    ) -> SourceStatusRecord:
        source_id = self._source_id_from_value(source)
        if not reason.strip():
            raise EvidenceValidationError("Source reactivation requires a reason.")
        observed = _canonical_utc(observed_at_utc)
        return self.set_source_status(source_id, SourceStatus.ACTIVE, reason, observed)

    def set_source_status(
        self,
        source_id: str | CanonicalIdentifier,
        status: str | SourceStatus,
        reason: str,
        observed_at_utc: str,
    ) -> SourceStatusRecord:
        selected_id = _id_value(source_id, expected_kind="source")
        selected_status = _enum_text(status, name="Source status")
        if selected_status not in {item.value for item in SourceStatus}:
            raise EvidenceValidationError("Source status must be ACTIVE or SUSPENDED.")
        observed = _canonical_utc(observed_at_utc)
        if not reason.strip():
            raise EvidenceValidationError("Source status requires a reason.")
        status_id = deterministic_identifier("source_status", f"{selected_id}:{observed}")
        selected_reason = reason.strip()
        with self._store.transaction() as transaction:
            source_row = transaction.execute(
                "SELECT 1 FROM source_identities WHERE source_id = ?", (selected_id,)
            ).fetchone()
            if source_row is None:
                raise EvidenceValidationError("Source status requires an existing Source Identity.")
            existing = transaction.execute(
                """
                SELECT status, reason
                FROM evidence_source_status
                WHERE status_id = ?
                """,
                (status_id,),
            ).fetchone()
            if existing is not None:
                if tuple(str(value) for value in existing) != (
                    selected_status,
                    selected_reason,
                ):
                    raise EvidenceIntegrityError(
                        "Source status identity was reused with different content."
                    )
                return SourceStatusRecord(
                    status_id,
                    selected_id,
                    SourceStatus(selected_status),
                    selected_reason,
                    observed,
                )
            transaction.add_identifier_if_missing(CanonicalIdentifier("source_status", status_id))
            transaction.execute(
                """
                INSERT INTO evidence_source_status (
                    status_id, source_id, status, reason, observed_at_utc, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(status_id) DO NOTHING
                """,
                (status_id, selected_id, selected_status, selected_reason, observed, _now()),
            )
        return SourceStatusRecord(
            status_id,
            selected_id,
            SourceStatus(selected_status),
            selected_reason,
            observed,
        )

    def ingest(
        self,
        capture: SourceCaptureInput,
        assertions: Iterable[EvidenceAssertionInput],
        *,
        cutoff_utc: str | None = None,
        research_cutoff_id: str | CanonicalIdentifier | None = None,
        failure_hook: Callable[[int], None] | None = None,
    ) -> EvidenceIngestionResult:
        if not isinstance(capture, SourceCaptureInput):
            raise EvidenceValidationError("Evidence ingestion requires a SourceCaptureInput.")
        assertion_inputs = tuple(assertions)
        if not all(isinstance(item, EvidenceAssertionInput) for item in assertion_inputs):
            raise EvidenceValidationError("Evidence ingestion requires typed assertion inputs.")
        cutoff = _optional_utc(cutoff_utc)
        cutoff_id = (
            _id_value(research_cutoff_id, expected_kind="research_cutoff")
            if research_cutoff_id is not None
            else None
        )
        source_id = self._source_id(capture.source)
        origin_id = self._origin_id(capture.origin)
        self._ensure_cutoff_reference(cutoff_id, cutoff)
        source_status = self._source_status_at(source_id, capture.retrieved_at_utc)
        if source_status is SourceStatus.SUSPENDED:
            raise EvidencePolicyError("The Source Identity was suspended at capture time.")
        if (
            capture.source.retention_status.upper() in {"SUSPENDED", "DO_NOT_RETAIN"}
            and capture.content
        ):
            raise EvidencePolicyError("Source rights do not permit retaining this capture.")
        if capture.capture_kind == CaptureKind.RETAINED.value and (
            capture.source.retention_status.upper() not in _SOURCE_RETENTION_CLASSES
            or capture.source.allowed_use.strip().upper() == "CITATION_ONLY"
        ):
            raise EvidencePolicyError(
                "Source rights or retention status does not permit a retained capture."
            )
        for item in assertion_inputs:
            if (
                item.evidence_class is not None
                and capture.source.source_class == SourceClass.SPECIALIST_REPORTING.value
                and _evidence_class(item.evidence_class) == EvidenceClass.CRITICAL.value
            ):
                raise EvidencePolicyError("Specialist reporting cannot be Critical Evidence.")
        capture_id = self._capture_id(capture, source_id, origin_id)
        existing_capture = self._capture_by_id(capture_id)
        artifact_digest: str | None = None
        if existing_capture is None and capture.capture_kind == CaptureKind.RETAINED.value:
            assert capture.content is not None
            retention_class = (
                "REUSABLE"
                if capture.source.retention_status.upper() == "RETAIN_REUSABLE"
                else "PROTECTED"
            )
            artifact_digest = self._artifacts.publish_artifact(
                capture.content,
                capture.content_type,
                expected_digest=capture.content_sha256,
                retention_class=retention_class,
            ).digest
        elif existing_capture is not None:
            self._verify_capture_input_matches(existing_capture, capture)
            artifact_digest = existing_capture.artifact_digest
        inserted_capture = existing_capture is None
        with self._store.transaction() as transaction:
            if inserted_capture:
                self._ensure_source(transaction, capture.source, source_id)
                self._ensure_origin(transaction, capture.origin, origin_id)
                transaction.add_identifier_if_missing(
                    CanonicalIdentifier("source_capture", capture_id)
                )
                rights = {
                    "allowed_use": capture.source.allowed_use,
                    "redistributable": capture.source.redistributable,
                    "retention_status": capture.source.retention_status,
                    "capture_kind": capture.capture_kind,
                    "source_class": capture.source.source_class,
                    "authority_scope": capture.source.source_class,
                    "terms_reference": capture.source.terms_reference,
                }
                transaction.execute(
                    """
                    INSERT INTO evidence_captures (
                        capture_id, source_id, origin_id, capture_key, locator, access_method,
                        retrieved_at_utc, source_published_at_utc, response_status, content_type,
                        content_sha256, byte_length, artifact_digest, capture_kind,
                        retention_status,
                        rights_json, terms_reference, citation_note, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        source_id,
                        origin_id,
                        capture.capture_key or capture.locator,
                        capture.locator,
                        capture.access_method,
                        capture.retrieved_at_utc,
                        capture.published_at_utc,
                        capture.response_status,
                        capture.content_type,
                        capture.content_sha256,
                        len(capture.content) if capture.content is not None else 0,
                        artifact_digest,
                        capture.capture_kind,
                        capture.source.retention_status,
                        _canonical_json(rights),
                        capture.source.terms_reference,
                        capture.citation_note,
                        _now(),
                    ),
                )
            else:
                self._ensure_source(transaction, capture.source, source_id)
                self._ensure_origin(transaction, capture.origin, origin_id)
            found_capture = self._capture_by_id(capture_id, transaction=transaction)
            if found_capture is None:
                raise EvidenceIntegrityError("Source capture was not persisted.")
            capture_record = found_capture
            cutoff_assessments: list[CutoffAssessmentRecord] = []
            records: list[EvidenceAssertionRecord] = []
            conflicts: list[EvidenceConflictRecord] = []
            seen_keys: set[str] = set()
            for index, item in enumerate(assertion_inputs, start=1):
                if failure_hook is not None:
                    failure_hook(index)
                record, assessment, new_conflicts = self._insert_assertion(
                    transaction,
                    item,
                    capture,
                    capture_record,
                    cutoff,
                    cutoff_id,
                    seen_keys,
                )
                records.append(record)
                cutoff_assessments.append(assessment)
                conflicts.extend(new_conflicts)
        return EvidenceIngestionResult(
            capture_record,
            tuple(records),
            tuple(cutoff_assessments),
            tuple(conflicts),
            from_existing_capture=not inserted_capture,
        )

    record = ingest
    ingest_evidence = ingest

    def record_unknown(
        self,
        *,
        subject_kind: str | SubjectKind,
        subject_id: str | CanonicalIdentifier,
        evidence_type: str | EvidenceType,
        predicate: str,
        reason: str,
        evidence_class: str | EvidenceClass | None = None,
        materiality: str | EvidenceClass | None = None,
        cutoff_utc: str | None = None,
        research_cutoff_id: str | CanonicalIdentifier | None = None,
        attempted_at_utc: str | None = None,
    ) -> EvidenceAssertionRecord:
        """Record source silence or an unsuccessful search as UNKNOWN."""

        kind = _subject_kind(subject_kind)
        entity_id = _id_value(subject_id, expected_kind=kind.casefold())
        normalized_type = _evidence_type(evidence_type)
        normalized_predicate = predicate.strip()
        if not normalized_predicate:
            raise EvidenceValidationError("Evidence predicates are required.")
        if not reason.strip():
            raise EvidenceValidationError("UNKNOWN evidence requires a reason.")
        selected_classes = [item for item in (evidence_class, materiality) if item is not None]
        if len(selected_classes) == 2 and _evidence_class(selected_classes[0]) != _evidence_class(
            selected_classes[1]
        ):
            raise EvidenceValidationError("Evidence class and materiality disagree.")
        selected_class = (
            _evidence_class(selected_classes[0])
            if selected_classes
            else _DEFAULT_EVIDENCE_CLASSES.get(normalized_type, EvidenceClass.CONTEXT.value)
        )
        cutoff = _optional_utc(cutoff_utc)
        cutoff_id = (
            _id_value(research_cutoff_id, expected_kind="research_cutoff")
            if research_cutoff_id is not None
            else None
        )
        self._ensure_cutoff_reference(cutoff_id, cutoff)
        assertion_key = deterministic_identifier(
            "evidence_assertion",
            (
                f"unknown:{kind}:{entity_id}:{normalized_type}:"
                f"{normalized_predicate}:{selected_class}:{cutoff or 'none'}"
            ),
        )
        created = _canonical_utc(attempted_at_utc) if attempted_at_utc else _now()
        with self._store.transaction() as transaction:
            self._ensure_canonical_subject(transaction, kind, entity_id)
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("evidence_assertion", assertion_key)
            )
            transaction.execute(
                """
                INSERT INTO evidence_assertions (
                    assertion_id, capture_id, source_id, origin_id, source_class, source_row_key,
                    subject_kind, subject_id, evidence_type, predicate, evidence_class,
                    authority_rank, normalized_value_json, evidence_state, unknown_reason,
                    affirmative_basis, event_time_utc, effective_time_utc, predecessor_assertion_id,
                    provenance_json, created_at_utc
                ) VALUES (?, NULL, NULL, NULL, 'UNKNOWN', ?, ?, ?, ?, ?, ?,
                          900, NULL, 'UNKNOWN', ?, NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(assertion_id) DO NOTHING
                """,
                (
                    assertion_key,
                    "unknown-search",
                    kind,
                    entity_id,
                    normalized_type,
                    normalized_predicate,
                    selected_class,
                    reason.strip(),
                    _canonical_json(
                        {
                            "kind": "UNKNOWN_SEARCH",
                            "attempted_at_utc": created,
                            "reason": reason.strip(),
                        }
                    ),
                    created,
                ),
            )
            assessment = self._insert_cutoff_assessment(
                transaction,
                assertion_key,
                cutoff_id,
                cutoff,
                CutoffEligibility.INDETERMINATE,
                "NO_SOURCE_CAPTURE",
                created,
            )
            return self._assertion_by_id(
                assertion_key, transaction=transaction, assessment=assessment
            )

    def source_captures(self) -> tuple[SourceCaptureRecord, ...]:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT c.capture_id, c.source_id, s.source_key, c.origin_id, o.origin_key,
                   c.locator, c.access_method, c.retrieved_at_utc, c.source_published_at_utc,
                   c.response_status, c.content_type, c.content_sha256, c.byte_length,
                   c.artifact_digest, c.capture_kind, c.retention_status, c.rights_json,
                   c.terms_reference, c.citation_note
            FROM evidence_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            JOIN independent_origins AS o ON o.origin_id = c.origin_id
            ORDER BY c.retrieved_at_utc, c.capture_id
            """
        ).fetchall()
        return tuple(self._capture_from_row(row) for row in rows)

    captures = source_captures

    def people(self) -> tuple[PersonRecord, ...]:
        """Return the immutable canonical people available for evidence attachment."""

        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT person_id, canonical_name, normalized_name, person_role
            FROM people ORDER BY normalized_name, person_role, person_id
            """
        ).fetchall()
        return tuple(
            PersonRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows
        )

    def source_identities(self) -> tuple[SourceIdentityRecord, ...]:
        """Return immutable source identities with their authority and rights metadata."""

        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT source_id, source_key, canonical_name, owner, source_class, access_method,
                   base_locator, allowed_use, retention_status, redistributable,
                   terms_reference, terms_observed_at_utc
            FROM source_identities ORDER BY source_key, source_id
            """
        ).fetchall()
        return tuple(
            SourceIdentityRecord(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
                str(row[7]),
                str(row[8]),
                bool(row[9]),
                str(row[10]),
                str(row[11]),
            )
            for row in rows
        )

    sources = source_identities

    def independent_origins(self) -> tuple[IndependentOriginRecord, ...]:
        """Return immutable independent-origin identities used for corroboration."""

        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT origin_id, origin_key, organization, locator, classification
            FROM independent_origins ORDER BY origin_key, origin_id
            """
        ).fetchall()
        return tuple(
            IndependentOriginRecord(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]) if row[3] is not None else None,
                str(row[4]),
            )
            for row in rows
        )

    def assertions(
        self,
        subject_kind: str | SubjectKind,
        subject_id: str | CanonicalIdentifier,
        *,
        evidence_type: str | EvidenceType | None = None,
        predicate: str | None = None,
        cutoff_utc: str | None = None,
        include_unknown: bool = True,
    ) -> tuple[EvidenceAssertionRecord, ...]:
        kind = _subject_kind(subject_kind)
        entity_id = _id_value(subject_id, expected_kind=kind.casefold())
        cutoff = _optional_utc(cutoff_utc)
        connection = self._store._connection_for_repository()
        conditions = ["a.subject_kind = ?", "a.subject_id = ?"]
        parameters: list[object] = [kind, entity_id]
        if evidence_type is not None:
            conditions.append("a.evidence_type = ?")
            parameters.append(_evidence_type(evidence_type))
        if predicate is not None:
            conditions.append("a.predicate = ?")
            parameters.append(predicate)
        if not include_unknown:
            conditions.append("a.evidence_state != 'UNKNOWN'")
        rows = connection.execute(
            f"""
            SELECT a.assertion_id, a.capture_id, a.source_id, a.origin_id, a.source_class,
                   a.source_row_key, a.subject_kind, a.subject_id, a.evidence_type, a.predicate,
                   a.evidence_class, a.authority_rank, a.normalized_value_json, a.evidence_state,
                   a.unknown_reason, a.affirmative_basis, a.event_time_utc, a.effective_time_utc,
                   a.predecessor_assertion_id, a.provenance_json,
                   ca.eligibility, ca.reason
            FROM evidence_assertions AS a
            LEFT JOIN evidence_cutoff_assessments AS ca
              ON ca.assessment_id = (
                  SELECT latest.assessment_id
                  FROM evidence_cutoff_assessments AS latest
                  WHERE latest.assertion_id = a.assertion_id
                    AND (? IS NULL OR latest.cutoff_utc = ?)
                  ORDER BY latest.assessed_at_utc DESC, latest.assessment_id DESC
                  LIMIT 1
              )
            WHERE {" AND ".join(conditions)}
            ORDER BY a.created_at_utc, a.assertion_id
            """,
            [cutoff, cutoff, *parameters],
        ).fetchall()
        records = tuple(self._assertion_from_row(row, cutoff=cutoff) for row in rows)
        return records

    evidence_assertions = assertions

    def preferred_assertion(
        self,
        subject_kind: str | SubjectKind,
        subject_id: str | CanonicalIdentifier,
        *,
        evidence_type: str | EvidenceType,
        predicate: str,
        cutoff_utc: str | None = None,
    ) -> EvidenceAssertionRecord | None:
        candidates = self.assertions(
            subject_kind,
            subject_id,
            evidence_type=evidence_type,
            predicate=predicate,
            cutoff_utc=cutoff_utc,
            include_unknown=True,
        )
        unknown_candidates = tuple(
            item for item in candidates if item.state is EvidenceState.UNKNOWN
        )
        if cutoff_utc is not None:
            cutoff_valid = tuple(
                item
                for item in candidates
                if item.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
            )
            candidates = cutoff_valid or unknown_candidates
        known = tuple(item for item in candidates if item.state is not EvidenceState.UNKNOWN)
        pool = known or candidates
        if not pool:
            return None
        return sorted(
            pool,
            key=lambda item: (
                item.authority_rank,
                -(self._source_time_sort_key(item)),
                item.assertion_id,
            ),
        )[0]

    def conflicts(
        self,
        subject_kind: str | SubjectKind,
        subject_id: str | CanonicalIdentifier,
        *,
        evidence_type: str | EvidenceType | None = None,
        predicate: str | None = None,
    ) -> tuple[EvidenceConflictRecord, ...]:
        kind = _subject_kind(subject_kind)
        entity_id = _id_value(subject_id, expected_kind=kind.casefold())
        connection = self._store._connection_for_repository()
        conditions = ["c.subject_kind = ?", "c.subject_id = ?"]
        params: list[object] = [kind, entity_id]
        if evidence_type is not None:
            conditions.append("c.evidence_type = ?")
            params.append(_evidence_type(evidence_type))
        if predicate is not None:
            conditions.append("c.predicate = ?")
            params.append(predicate)
        rows = connection.execute(
            f"""
            SELECT c.conflict_id, c.subject_kind, c.subject_id, c.evidence_type,
                   c.predicate, c.value_digest, c.status
            FROM evidence_conflicts AS c
            WHERE {" AND ".join(conditions)}
            ORDER BY c.evidence_type, c.predicate, c.conflict_id
            """,
            params,
        ).fetchall()
        result: list[EvidenceConflictRecord] = []
        for row in rows:
            members = connection.execute(
                """
                SELECT assertion_id FROM evidence_conflict_assertions
                WHERE conflict_id = ? ORDER BY assertion_id
                """,
                (str(row[0]),),
            ).fetchall()
            result.append(
                EvidenceConflictRecord(
                    str(row[0]),
                    SubjectKind(str(row[1])),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                    str(row[6]),
                    tuple(str(member[0]) for member in members),
                )
            )
        return tuple(result)

    conflict_sets = conflicts

    def corroboration(
        self,
        subject_kind: str | SubjectKind,
        subject_id: str | CanonicalIdentifier,
        *,
        evidence_type: str | EvidenceType,
        predicate: str,
        value: object,
        cutoff_utc: str | None = None,
    ) -> CorroborationRecord:
        kind = _subject_kind(subject_kind)
        entity_id = _id_value(subject_id, expected_kind=kind.casefold())
        value_json = _canonical_json(value)
        candidates = self.assertions(
            kind,
            entity_id,
            evidence_type=evidence_type,
            predicate=predicate,
            cutoff_utc=cutoff_utc,
            include_unknown=False,
        )
        candidates = tuple(
            item
            for item in candidates
            if item.state is EvidenceState.OBSERVED and _canonical_json(item.value) == value_json
        )
        if cutoff_utc is not None:
            candidates = tuple(
                item
                for item in candidates
                if item.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
            )
        origins = tuple(
            sorted({item.origin_id for item in candidates if item.origin_id is not None})
        )
        return CorroborationRecord(
            SubjectKind(kind),
            entity_id,
            _evidence_type(evidence_type),
            predicate,
            value,
            cast(tuple[str], origins),
            tuple(item.assertion_id for item in candidates),
        )

    independent_corroboration = corroboration

    def resolve_conflict(
        self,
        conflict_id: str | CanonicalIdentifier,
        selected_assertion_id: str | CanonicalIdentifier,
        *,
        basis: Iterable[str],
        rationale: str,
    ) -> ConflictResolutionRecord:
        selected_conflict_id = _id_value(conflict_id, expected_kind="evidence_conflict")
        selected_assertion = _id_value(selected_assertion_id, expected_kind="evidence_assertion")
        selected_basis = tuple(
            sorted({_enum_text(item, name="Resolution basis") for item in basis})
        )
        if not selected_basis or any(
            item not in self._ALLOWED_RESOLUTION_BASIS for item in selected_basis
        ):
            raise EvidenceValidationError(
                "Conflict resolution basis is limited to authority, directness, "
                "freshness, or relevance."
            )
        if not rationale.strip():
            raise EvidenceValidationError("Conflict resolution requires rationale.")
        selected_rationale = rationale.strip()
        basis_json = _canonical_json(selected_basis)
        connection = self._store._connection_for_repository()
        member = connection.execute(
            """
            SELECT 1 FROM evidence_conflict_assertions
            WHERE conflict_id = ? AND assertion_id = ?
            """,
            (selected_conflict_id, selected_assertion),
        ).fetchone()
        if member is None:
            raise EvidenceValidationError(
                "A conflict resolution must select one of its assertions."
            )
        resolution_id = deterministic_identifier(
            "evidence_conflict_resolution",
            f"{selected_conflict_id}:{selected_assertion}:{_canonical_json(selected_basis)}",
        )
        with self._store.transaction() as transaction:
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("evidence_conflict_resolution", resolution_id)
            )
            existing = transaction.execute(
                """
                SELECT conflict_id, selected_assertion_id, basis_json, rationale
                FROM evidence_conflict_resolutions
                WHERE resolution_id = ?
                """,
                (resolution_id,),
            ).fetchone()
            if existing is not None:
                if tuple(str(value) for value in existing) != (
                    selected_conflict_id,
                    selected_assertion,
                    basis_json,
                    selected_rationale,
                ):
                    raise EvidenceIntegrityError(
                        "Conflict resolution identity was reused with different content."
                    )
            else:
                transaction.execute(
                    """
                    INSERT INTO evidence_conflict_resolutions (
                        resolution_id, conflict_id, selected_assertion_id, basis_json,
                        rationale, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolution_id,
                        selected_conflict_id,
                        selected_assertion,
                        basis_json,
                        selected_rationale,
                        _now(),
                    ),
                )
        return ConflictResolutionRecord(
            resolution_id,
            selected_conflict_id,
            selected_assertion,
            selected_basis,
            selected_rationale,
        )

    def conflict_resolutions(
        self, conflict_id: str | CanonicalIdentifier
    ) -> tuple[ConflictResolutionRecord, ...]:
        """Return append-only resolutions recorded for one material conflict."""

        selected_id = _id_value(conflict_id, expected_kind="evidence_conflict")
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT resolution_id, conflict_id, selected_assertion_id, basis_json, rationale
            FROM evidence_conflict_resolutions
            WHERE conflict_id = ? ORDER BY created_at_utc, resolution_id
            """,
            (selected_id,),
        ).fetchall()
        result: list[ConflictResolutionRecord] = []
        for row in rows:
            basis = _json_value(str(row[3]))
            if not isinstance(basis, list) or not all(isinstance(item, str) for item in basis):
                raise EvidenceIntegrityError("Stored conflict resolution basis is invalid.")
            result.append(
                ConflictResolutionRecord(
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    tuple(basis),
                    str(row[4]),
                )
            )
        return tuple(result)

    def correction_chain(
        self, assertion_id: str | CanonicalIdentifier
    ) -> tuple[EvidenceAssertionRecord, ...]:
        selected_id = _id_value(assertion_id, expected_kind="evidence_assertion")
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            WITH RECURSIVE chain(assertion_id) AS (
                SELECT ?
                UNION ALL
                SELECT a.predecessor_assertion_id
                FROM evidence_assertions AS a
                JOIN chain AS c ON c.assertion_id = a.assertion_id
                WHERE a.predecessor_assertion_id IS NOT NULL
            )
            SELECT a.assertion_id, a.capture_id, a.source_id, a.origin_id, a.source_class,
                   a.source_row_key, a.subject_kind, a.subject_id, a.evidence_type, a.predicate,
                   a.evidence_class, a.authority_rank, a.normalized_value_json, a.evidence_state,
                   a.unknown_reason, a.affirmative_basis, a.event_time_utc, a.effective_time_utc,
                   a.predecessor_assertion_id, a.provenance_json, ca.eligibility, ca.reason
            FROM evidence_assertions AS a
            JOIN chain AS c ON c.assertion_id = a.assertion_id
            LEFT JOIN evidence_cutoff_assessments AS ca
              ON ca.assessment_id = (
                  SELECT latest.assessment_id
                  FROM evidence_cutoff_assessments AS latest
                  WHERE latest.assertion_id = a.assertion_id
                  ORDER BY latest.assessed_at_utc DESC, latest.assessment_id DESC
                  LIMIT 1
              )
            ORDER BY a.created_at_utc, a.assertion_id
            """,
            (selected_id,),
        ).fetchall()
        return tuple(self._assertion_from_row(row, cutoff=None) for row in rows)

    corrections = correction_chain

    def source_status_history(
        self, source: str | CanonicalIdentifier | SourceIdentity
    ) -> tuple[SourceStatusRecord, ...]:
        source_id = self._source_id_from_value(source)
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT status_id, source_id, status, reason, observed_at_utc
            FROM evidence_source_status
            WHERE source_id = ? ORDER BY observed_at_utc, status_id
            """,
            (source_id,),
        ).fetchall()
        return tuple(
            SourceStatusRecord(
                str(row[0]), str(row[1]), SourceStatus(str(row[2])), str(row[3]), str(row[4])
            )
            for row in rows
        )

    def _source_id(self, source: SourceIdentity) -> str:
        return source.source_id or deterministic_identifier("source", source.source_key)

    def _origin_id(self, origin: IndependentOrigin) -> str:
        return origin.origin_id or deterministic_identifier("origin", origin.origin_key)

    def _source_id_from_value(self, source: str | CanonicalIdentifier | SourceIdentity) -> str:
        if isinstance(source, SourceIdentity):
            return self._source_id(source)
        return _id_value(source, expected_kind="source")

    def _capture_id(self, capture: SourceCaptureInput, source_id: str, origin_id: str) -> str:
        identity = {
            "capture_key": capture.capture_key or capture.locator,
            "content_sha256": capture.content_sha256,
            "kind": capture.capture_kind,
            "locator": capture.locator,
            "origin_id": origin_id,
            "published_at_utc": capture.published_at_utc,
            "retrieved_at_utc": capture.retrieved_at_utc,
            "source_id": source_id,
        }
        return deterministic_identifier("source_capture", f"t07:{_canonical_json(identity)}")

    def _source_status_at(self, source_id: str, retrieved_at_utc: str) -> SourceStatus:
        connection = self._store._connection_for_repository()
        row = connection.execute(
            """
            SELECT status FROM evidence_source_status
            WHERE source_id = ? AND observed_at_utc <= ?
            ORDER BY observed_at_utc DESC, status_id DESC LIMIT 1
            """,
            (source_id, retrieved_at_utc),
        ).fetchone()
        return SourceStatus(str(row[0])) if row is not None else SourceStatus.ACTIVE

    def _ensure_cutoff_reference(self, cutoff_id: str | None, cutoff: str | None) -> None:
        if cutoff_id is None:
            return
        connection = self._store._connection_for_repository()
        row = connection.execute(
            "SELECT cutoff_utc FROM matchweek_research_cutoffs WHERE cutoff_id = ?", (cutoff_id,)
        ).fetchone()
        if row is None:
            raise EvidenceValidationError("Research Cutoff ID is not a canonical T05 cutoff.")
        stored_cutoff = _canonical_utc(str(row[0]))
        if cutoff is None or stored_cutoff != cutoff:
            raise EvidenceValidationError("Research Cutoff ID and cutoff timestamp disagree.")

    def _ensure_source(
        self,
        transaction: StoreTransaction,
        source: SourceIdentity,
        source_id: str,
    ) -> None:
        transaction.add_identifier_if_missing(CanonicalIdentifier("source", source_id))
        row = transaction.execute(
            """
            SELECT source_id, source_key, canonical_name, owner, source_class, access_method,
                   base_locator, allowed_use, retention_status, redistributable, terms_reference
            FROM source_identities WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        expected = (
            source_id,
            source.source_key,
            source.canonical_name,
            source.owner,
            source.source_class,
            source.access_method,
            source.base_locator,
            source.allowed_use,
            source.retention_status,
            int(source.redistributable),
            source.terms_reference,
        )
        if row is not None:
            if tuple(row) != expected:
                raise EvidenceIntegrityError(
                    "Source Identity is immutable and differs from the input."
                )
            return
        by_key = transaction.execute(
            "SELECT source_id FROM source_identities WHERE source_key = ?", (source.source_key,)
        ).fetchone()
        if by_key is not None and str(by_key[0]) != source_id:
            raise EvidenceIntegrityError(
                "Source key already belongs to another canonical Source Identity."
            )
        transaction.execute(
            """
            INSERT INTO source_identities (
                source_id, source_key, canonical_name, owner, source_class, access_method,
                base_locator, allowed_use, retention_status, redistributable, terms_reference,
                terms_observed_at_utc, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source.source_key,
                source.canonical_name,
                source.owner,
                source.source_class,
                source.access_method,
                source.base_locator,
                source.allowed_use,
                source.retention_status,
                int(source.redistributable),
                source.terms_reference,
                source.terms_observed_at_utc or _now(),
                _now(),
            ),
        )

    def _ensure_origin(
        self,
        transaction: StoreTransaction,
        origin: IndependentOrigin,
        origin_id: str,
    ) -> None:
        transaction.add_identifier_if_missing(CanonicalIdentifier("origin", origin_id))
        row = transaction.execute(
            """
            SELECT origin_id, origin_key, organization, locator, classification
            FROM independent_origins WHERE origin_id = ?
            """,
            (origin_id,),
        ).fetchone()
        expected = (
            origin_id,
            origin.origin_key,
            origin.organization,
            origin.locator,
            origin.classification,
        )
        if row is not None:
            if tuple(row) != expected:
                raise EvidenceIntegrityError(
                    "Independent Origin is immutable and differs from input."
                )
            return
        by_key = transaction.execute(
            "SELECT origin_id FROM independent_origins WHERE origin_key = ?", (origin.origin_key,)
        ).fetchone()
        if by_key is not None and str(by_key[0]) != origin_id:
            raise EvidenceIntegrityError("Origin key already belongs to another canonical origin.")
        transaction.execute(
            """
            INSERT INTO independent_origins (
                origin_id, origin_key, organization, locator, classification, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                origin_id,
                origin.origin_key,
                origin.organization,
                origin.locator,
                origin.classification,
                _now(),
            ),
        )

    def _ensure_canonical_subject(
        self,
        transaction: StoreTransaction,
        kind: str,
        subject_id: str,
    ) -> None:
        table = {"FIXTURE": "fixtures", "TEAM": "teams", "PERSON": "people"}[kind]
        row = transaction.execute(
            f"SELECT 1 FROM {table} WHERE {kind.casefold()}_id = ?", (subject_id,)
        ).fetchone()
        if row is None:
            raise EvidenceValidationError(
                "Evidence can attach only to an existing canonical fixture, team, or person."
            )

    def _insert_assertion(
        self,
        transaction: StoreTransaction,
        item: EvidenceAssertionInput,
        capture: SourceCaptureInput,
        capture_record: SourceCaptureRecord,
        cutoff: str | None,
        cutoff_id: str | None,
        seen_keys: set[str],
    ) -> tuple[EvidenceAssertionRecord, CutoffAssessmentRecord, tuple[EvidenceConflictRecord, ...]]:
        kind = _subject_kind(item.subject_kind)
        subject_id = _id_value(item.subject_id, expected_kind=kind.casefold())
        evidence_type = _evidence_type(item.evidence_type)
        state = _evidence_state(item.state)
        predicate = item.predicate.strip()
        self._ensure_canonical_subject(transaction, kind, subject_id)
        selected_class = classify_evidence(
            evidence_type,
            capture.source.source_class,
            item.evidence_class or item.materiality,
        )
        key = (
            item.assertion_key
            or item.source_row_key
            or f"{kind}:{subject_id}:{evidence_type}:{predicate}"
        ).strip()
        if key in seen_keys:
            raise EvidenceValidationError("Assertion keys must be unique within one capture.")
        seen_keys.add(key)
        assertion_id = deterministic_identifier(
            "evidence_assertion", f"{capture_record.capture_id}:{key}"
        )
        existing = transaction.execute(
            """
            SELECT assertion_id, capture_id, source_id, origin_id, source_class, source_row_key,
                   subject_kind, subject_id, evidence_type, predicate, evidence_class,
                   authority_rank, normalized_value_json, evidence_state, unknown_reason,
                   affirmative_basis, event_time_utc, effective_time_utc, predecessor_assertion_id,
                   provenance_json
            FROM evidence_assertions WHERE assertion_id = ?
            """,
            (assertion_id,),
        ).fetchone()
        normalized_value = (
            _canonical_json(item.value) if state == EvidenceState.OBSERVED.value else None
        )
        source_class = capture.source.source_class
        source_row_key = (item.source_row_key or key).strip()
        assertion_authority_rank = authority_rank(evidence_type, source_class)
        provenance = {
            "source_id": capture_record.source_id,
            "origin_id": capture_record.origin_id,
            "capture_id": capture_record.capture_id,
            "source_class": source_class,
            "authority_rank": assertion_authority_rank,
            "locator": capture_record.locator,
            "published_at_utc": capture_record.published_at_utc,
            "retrieved_at_utc": capture_record.retrieved_at_utc,
            "capture_kind": capture_record.capture_kind.value,
            "retention_status": capture_record.retention_status,
            "authority_scope": source_class,
            "rights": dict(capture_record.rights),
        }
        expected = (
            assertion_id,
            capture_record.capture_id,
            capture_record.source_id,
            capture_record.origin_id,
            source_class,
            source_row_key,
            kind,
            subject_id,
            evidence_type,
            predicate,
            selected_class.value,
            assertion_authority_rank,
            normalized_value,
            state,
            item.unknown_reason,
            item.affirmative_basis,
            item.event_time_utc,
            item.effective_time_utc,
            item.correction_of,
            _canonical_json(provenance),
        )
        created = _now()
        if existing is None:
            if item.correction_of is not None:
                predecessor = transaction.execute(
                    """
                    SELECT subject_kind, subject_id, evidence_type, predicate
                    FROM evidence_assertions WHERE assertion_id = ?
                    """,
                    (item.correction_of,),
                ).fetchone()
                if predecessor is None:
                    raise EvidenceValidationError(
                        "A correction must reference an existing assertion."
                    )
                if tuple(str(value) for value in predecessor) != (
                    kind,
                    subject_id,
                    evidence_type,
                    predicate,
                ):
                    raise EvidenceValidationError(
                        "A correction must keep the same subject and predicate."
                    )
            transaction.add_identifier_if_missing(
                CanonicalIdentifier("evidence_assertion", assertion_id)
            )
            transaction.execute(
                """
                INSERT INTO evidence_assertions (
                    assertion_id, capture_id, source_id, origin_id, source_class, source_row_key,
                    subject_kind, subject_id, evidence_type, predicate, evidence_class,
                    authority_rank, normalized_value_json, evidence_state, unknown_reason,
                    affirmative_basis, event_time_utc, effective_time_utc, predecessor_assertion_id,
                    provenance_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*expected, created),
            )
        elif tuple(existing) != expected:
            raise EvidenceIntegrityError(
                "Evidence assertion identity was reused with different content."
            )
        assessment = self._cutoff_assessment_for_input(
            transaction,
            assertion_id,
            capture_record,
            cutoff_id,
            cutoff,
            created,
        )
        conflicts = self._record_conflicts(
            transaction,
            kind,
            subject_id,
            evidence_type,
            predicate,
        )
        return (
            self._assertion_by_id(
                assertion_id,
                transaction=transaction,
                assessment=assessment,
            ),
            assessment,
            conflicts,
        )

    def _cutoff_assessment_for_input(
        self,
        transaction: StoreTransaction,
        assertion_id: str,
        capture: SourceCaptureRecord,
        cutoff_id: str | None,
        cutoff: str | None,
        created_at: str,
    ) -> CutoffAssessmentRecord:
        eligibility, reason = assess_cutoff_eligibility(
            retrieved_at_utc=capture.retrieved_at_utc,
            published_at_utc=capture.published_at_utc,
            cutoff_utc=cutoff,
        )
        return self._insert_cutoff_assessment(
            transaction,
            assertion_id,
            cutoff_id,
            cutoff,
            eligibility,
            reason,
            created_at,
        )

    def _insert_cutoff_assessment(
        self,
        transaction: StoreTransaction,
        assertion_id: str,
        cutoff_id: str | None,
        cutoff: str | None,
        eligibility: CutoffEligibility,
        reason: str,
        assessed_at: str,
    ) -> CutoffAssessmentRecord:
        assessment_key = deterministic_identifier(
            "evidence_cutoff_assessment", f"{assertion_id}:{cutoff or 'none'}"
        )
        transaction.add_identifier_if_missing(
            CanonicalIdentifier("evidence_cutoff_assessment", assessment_key)
        )
        existing = transaction.execute(
            """
            SELECT assertion_id, research_cutoff_id, cutoff_utc, eligibility, reason
            FROM evidence_cutoff_assessments WHERE assessment_id = ?
            """,
            (assessment_key,),
        ).fetchone()
        expected = (assertion_id, cutoff_id, cutoff, eligibility.value, reason)
        if existing is not None:
            if tuple(existing) != expected:
                raise EvidenceIntegrityError(
                    "Cutoff assessment identity was reused with different content."
                )
        else:
            transaction.execute(
                """
                INSERT INTO evidence_cutoff_assessments (
                    assessment_id, assertion_id, research_cutoff_id, cutoff_utc,
                    eligibility, reason, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_key,
                    assertion_id,
                    cutoff_id,
                    cutoff,
                    eligibility.value,
                    reason,
                    assessed_at,
                ),
            )
        row = transaction.execute(
            """
            SELECT assessment_id, assertion_id, research_cutoff_id, cutoff_utc,
                   eligibility, reason, assessed_at_utc
            FROM evidence_cutoff_assessments WHERE assessment_id = ?
            """,
            (assessment_key,),
        ).fetchone()
        if row is None:
            raise EvidenceIntegrityError("Cutoff assessment was not persisted.")
        return CutoffAssessmentRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]) if row[2] is not None else None,
            str(row[3]) if row[3] is not None else None,
            CutoffEligibility(str(row[4])),
            str(row[5]),
            str(row[6]),
        )

    def _record_conflicts(
        self,
        transaction: StoreTransaction,
        kind: str,
        subject_id: str,
        evidence_type: str,
        predicate: str,
    ) -> tuple[EvidenceConflictRecord, ...]:
        rows = transaction.execute(
            """
            SELECT assertion_id, evidence_state, normalized_value_json
            FROM evidence_assertions
            WHERE subject_kind = ? AND subject_id = ? AND evidence_type = ? AND predicate = ?
              AND evidence_state IN ('OBSERVED', 'ABSENT')
            ORDER BY assertion_id
            """,
            (kind, subject_id, evidence_type, predicate),
        ).fetchall()
        values = sorted(
            {
                _canonical_json(
                    {
                        "state": str(row[1]),
                        "value": row[2] if row[1] == EvidenceState.OBSERVED.value else None,
                    }
                )
                for row in rows
            }
        )
        if len(values) < 2:
            return ()
        digest = sha256_bytes(_canonical_json(values).encode("utf-8"))
        conflict_id = deterministic_identifier(
            "evidence_conflict", f"{kind}:{subject_id}:{evidence_type}:{predicate}:{digest}"
        )
        transaction.add_identifier_if_missing(CanonicalIdentifier("evidence_conflict", conflict_id))
        transaction.execute(
            """
            INSERT INTO evidence_conflicts (
                conflict_id, subject_kind, subject_id, evidence_type, predicate,
                value_digest, status, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'UNRESOLVED', ?)
            ON CONFLICT(conflict_id) DO NOTHING
            """,
            (conflict_id, kind, subject_id, evidence_type, predicate, digest, _now()),
        )
        for row in rows:
            transaction.execute(
                """
                INSERT INTO evidence_conflict_assertions (conflict_id, assertion_id)
                VALUES (?, ?) ON CONFLICT(conflict_id, assertion_id) DO NOTHING
                """,
                (conflict_id, str(row[0])),
            )
        return (self._conflict_by_id(conflict_id, transaction=transaction),)

    def _capture_by_id(
        self,
        capture_id: str,
        *,
        transaction: StoreTransaction | None = None,
    ) -> SourceCaptureRecord | None:
        executor: Any = (
            transaction if transaction is not None else self._store._connection_for_repository()
        )
        row = executor.execute(
            """
            SELECT c.capture_id, c.source_id, s.source_key, c.origin_id, o.origin_key,
                   c.locator, c.access_method, c.retrieved_at_utc, c.source_published_at_utc,
                   c.response_status, c.content_type, c.content_sha256, c.byte_length,
                   c.artifact_digest, c.capture_kind, c.retention_status, c.rights_json,
                   c.terms_reference, c.citation_note
            FROM evidence_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            JOIN independent_origins AS o ON o.origin_id = c.origin_id
            WHERE c.capture_id = ?
            """,
            (capture_id,),
        ).fetchone()
        return self._capture_from_row(row) if row is not None else None

    def _verify_capture_input_matches(
        self,
        existing: SourceCaptureRecord,
        capture: SourceCaptureInput,
    ) -> None:
        expected_rights = {
            "allowed_use": capture.source.allowed_use,
            "redistributable": capture.source.redistributable,
            "retention_status": capture.source.retention_status,
            "capture_kind": capture.capture_kind,
            "source_class": capture.source.source_class,
            "authority_scope": capture.source.source_class,
            "terms_reference": capture.source.terms_reference,
        }
        if (
            existing.locator != capture.locator
            or existing.access_method != capture.access_method
            or existing.retrieved_at_utc != capture.retrieved_at_utc
            or existing.published_at_utc != capture.published_at_utc
            or existing.response_status != capture.response_status
            or existing.content_type != capture.content_type
            or existing.capture_kind.value != capture.capture_kind
            or existing.byte_length != (len(capture.content) if capture.content is not None else 0)
            or existing.content_sha256 != capture.content_sha256
            or existing.retention_status != capture.source.retention_status
            or dict(existing.rights) != expected_rights
            or existing.terms_reference != capture.source.terms_reference
            or existing.citation_note != capture.citation_note
        ):
            raise EvidenceIntegrityError(
                "Source capture identity was reused with different metadata."
            )

    def _assertion_by_id(
        self,
        assertion_id: str,
        *,
        transaction: StoreTransaction | None = None,
        assessment: CutoffAssessmentRecord | None = None,
    ) -> EvidenceAssertionRecord:
        executor: Any = (
            transaction if transaction is not None else self._store._connection_for_repository()
        )
        row = executor.execute(
            """
            SELECT assertion_id, capture_id, source_id, origin_id, source_class, source_row_key,
                   subject_kind, subject_id, evidence_type, predicate, evidence_class,
                   authority_rank, normalized_value_json, evidence_state, unknown_reason,
                   affirmative_basis, event_time_utc, effective_time_utc, predecessor_assertion_id,
                   provenance_json
            FROM evidence_assertions WHERE assertion_id = ?
            """,
            (assertion_id,),
        ).fetchone()
        if row is None:
            raise EvidenceIntegrityError("Evidence assertion was not persisted.")
        return self._assertion_from_row(
            (*row, assessment.eligibility.value, assessment.reason)
            if assessment is not None
            else (*row, CutoffEligibility.INDETERMINATE.value, "NO_CUTOFF_ASSESSMENT"),
            cutoff=None,
        )

    def _conflict_by_id(
        self,
        conflict_id: str,
        *,
        transaction: StoreTransaction | None = None,
    ) -> EvidenceConflictRecord:
        executor: Any = (
            transaction if transaction is not None else self._store._connection_for_repository()
        )
        row = executor.execute(
            """
            SELECT conflict_id, subject_kind, subject_id, evidence_type, predicate,
                   value_digest, status
            FROM evidence_conflicts WHERE conflict_id = ?
            """,
            (conflict_id,),
        ).fetchone()
        if row is None:
            raise EvidenceIntegrityError("Evidence conflict was not persisted.")
        members = executor.execute(
            """
            SELECT assertion_id FROM evidence_conflict_assertions
            WHERE conflict_id = ? ORDER BY assertion_id
            """,
            (conflict_id,),
        ).fetchall()
        return EvidenceConflictRecord(
            str(row[0]),
            SubjectKind(str(row[1])),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            tuple(str(member[0]) for member in members),
        )

    def _source_time_sort_key(self, assertion: EvidenceAssertionRecord) -> int:
        timestamp = assertion.provenance.get("published_at_utc") or assertion.provenance.get(
            "retrieved_at_utc"
        )
        if not isinstance(timestamp, str):
            return 0
        try:
            return int(datetime.fromisoformat(timestamp).timestamp() * 1_000_000)
        except ValueError:
            return 0

    @staticmethod
    def _capture_from_row(row: Sequence[object]) -> SourceCaptureRecord:
        rights = _json_value(str(row[16]))
        if not isinstance(rights, dict):
            raise EvidenceIntegrityError("Source capture rights are not an object.")
        return SourceCaptureRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            str(row[7]),
            str(row[8]) if row[8] is not None else None,
            _integer_value(row[9]),
            str(row[10]),
            str(row[11]) if row[11] is not None else None,
            _integer_value(row[12]),
            str(row[13]) if row[13] is not None else None,
            CaptureKind(str(row[14])),
            str(row[15]),
            cast(Mapping[str, object], rights),
            str(row[17]),
            str(row[18]) if row[18] is not None else None,
        )

    @staticmethod
    def _assertion_from_row(
        row: Sequence[object], *, cutoff: str | None
    ) -> EvidenceAssertionRecord:
        del cutoff
        provenance = _json_value(str(row[19]))
        if not isinstance(provenance, dict):
            raise EvidenceIntegrityError("Evidence provenance is not an object.")
        eligibility = str(row[20]) if row[20] is not None else CutoffEligibility.INDETERMINATE.value
        reason = str(row[21]) if row[21] is not None else "NO_CUTOFF_ASSESSMENT"
        return EvidenceAssertionRecord(
            str(row[0]),
            str(row[1]) if row[1] is not None else None,
            str(row[2]) if row[2] is not None else None,
            str(row[3]) if row[3] is not None else None,
            str(row[4]),
            str(row[5]),
            SubjectKind(str(row[6])),
            str(row[7]),
            str(row[8]),
            str(row[9]),
            EvidenceClass(str(row[10])),
            _integer_value(row[11]),
            EvidenceState(str(row[13])),
            _json_value(str(row[12])) if row[12] is not None else None,
            str(row[14]) if row[14] is not None else None,
            str(row[15]) if row[15] is not None else None,
            str(row[16]) if row[16] is not None else None,
            str(row[17]) if row[17] is not None else None,
            str(row[18]) if row[18] is not None else None,
            cast(Mapping[str, object], provenance),
            CutoffEligibility(eligibility),
            reason,
        )


def assess_cutoff_eligibility(
    *,
    retrieved_at_utc: str,
    published_at_utc: str | None,
    cutoff_utc: str | None,
) -> tuple[CutoffEligibility, str]:
    """Apply T05/FR-1 boundary rules without guessing a missing publication time."""

    retrieved = _canonical_utc(retrieved_at_utc)
    published = _optional_utc(published_at_utc)
    cutoff = _optional_utc(cutoff_utc)
    if cutoff is None:
        return CutoffEligibility.INDETERMINATE, "NO_RESEARCH_CUTOFF"
    if published is not None:
        if published <= cutoff:
            return CutoffEligibility.CUTOFF_VALID, "PUBLICATION_AT_OR_BEFORE_CUTOFF"
        return CutoffEligibility.POST_CUTOFF, "PUBLICATION_AFTER_CUTOFF"
    if retrieved <= cutoff:
        return CutoffEligibility.CUTOFF_VALID, "CAPTURE_OBSERVED_AT_OR_BEFORE_CUTOFF"
    return CutoffEligibility.INDETERMINATE, "PUBLICATION_TIME_UNKNOWN_AFTER_CUTOFF"


__all__ = [
    "ABSENT",
    "OBSERVED",
    "UNKNOWN",
    "AssertionInput",
    "CaptureKind",
    "CorroborationRecord",
    "CutoffAssessmentRecord",
    "CutoffEligibility",
    "EvidenceAssertionInput",
    "EvidenceAssertionRecord",
    "EvidenceClass",
    "EvidenceConflictRecord",
    "EvidenceError",
    "EvidenceIngestionResult",
    "EvidenceIntegrityError",
    "EvidenceMateriality",
    "EvidencePolicyError",
    "EvidenceRecorder",
    "EvidenceState",
    "EvidenceType",
    "EvidenceValidationError",
    "IndependentOrigin",
    "IndependentOriginRecord",
    "PersonRecord",
    "SourceCaptureInput",
    "SourceCaptureRecord",
    "SourceClass",
    "SourceIdentity",
    "SourceIdentityRecord",
    "SourceStatus",
    "SourceStatusRecord",
    "SubjectKind",
    "assess_cutoff_eligibility",
    "authority_rank",
    "classify_evidence",
]

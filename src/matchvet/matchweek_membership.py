"""Versioned V2 Matchweek membership decisions and canonical payload rules."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from matchvet.fixture_coverage import fixture_scopes_for_matchweek

F06_CONTRACT_VERSION = "matchweek-membership-freeze-v2"
F06_PAYLOAD_VERSION = 1
F06_POLICY_ID = "matchvet:matchweek-membership"
F06_POLICY_VERSION = "1"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class MembershipState(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class ObservationCode(StrEnum):
    ADDED_IN_WINDOW = "ADDED_IN_WINDOW"
    MOVED_IN = "MOVED_IN"
    MOVED_OUT = "MOVED_OUT"
    RESCHEDULED = "RESCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    KICKOFF_CORRECTED = "KICKOFF_CORRECTED"
    IDENTITY_RESOLVED = "IDENTITY_RESOLVED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    REVISION_OBSERVED = "REVISION_OBSERVED"


class MatchweekMembershipError(ValueError):
    """Stable refusal or integrity failure raised by the F06 interface."""

    def __init__(self, code: str, reason_code: str, message: str) -> None:
        self.code = code
        self.reason_code = reason_code
        super().__init__(message)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    )


def sha256_digest(encoded: str) -> str:
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _digest(value: str, label: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest.")


def _canonical_utc(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be canonical UTC.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset.")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    if canonical != value:
        raise ValueError(f"{label} must be canonical UTC.")
    return canonical


def membership_policy_document() -> dict[str, object]:
    """Return the immutable initial policy rules in canonicalizable form."""
    return {
        "authority": {
            "fallback_source_keys": {
                "football-data.co.uk": 300,
                "openfootball": 200,
            },
            "source_classes": {
                "OFFICIAL_COMPETITION": 500,
                "OFFICIAL_LEAGUE": 500,
                "OFFICIAL_FEDERATION": 490,
                "OFFICIAL_ASSOCIATION": 490,
                "OFFICIAL_CLUB": 480,
                "OFFICIAL": 470,
                "STRUCTURED_PROVIDER": 300,
                "OPEN_DATASET": 200,
                "OPEN_SOURCE_DATASET": 200,
            },
            "normalization": {
                "source_class": "strip_upper_replace_spaces_with_underscores",
                "source_key": "strip_casefold",
            },
            "selection_order": [
                "authority_rank_desc",
                "latest_support_retrieved_at_utc_desc",
                "revision_id_desc",
                "revision_digest_desc",
            ],
            "unknown_rank": 100,
        },
        "candidate_grouping": ["scope_id", "canonical_fixture_id"],
        "contract_version": F06_CONTRACT_VERSION,
        "decision_order": ["canonical_scope_order", "canonical_fixture_id"],
        "membership_window": {
            "timezone": "Africa/Lagos",
            "start": "FRIDAY_00:00_INCLUSIVE",
            "end": "TUESDAY_00:00_EXCLUSIVE",
        },
        "reason_codes": {
            "included": "IN_WINDOW_SCHEDULED",
            "outside": "OUTSIDE_MATCHWEEK_WINDOW",
            "not_scheduled": "NOT_SCHEDULED",
            "postponed": "POSTPONED",
            "cancelled": "CANCELLED",
            "identity_unresolved": "IDENTITY_UNRESOLVED",
            "kickoff_unknown": "KICKOFF_UNKNOWN",
            "status_unknown": "STATUS_UNKNOWN",
            "controlling_revision_missing": "CONTROLLING_REVISION_MISSING",
            "membership_conflict": "MEMBERSHIP_CONFLICT",
            "material_source_conflict": "MATERIAL_SOURCE_CONFLICT",
        },
        "status_mapping": {
            "scheduled": ["SCHEDULED", "CONFIRMED"],
            "postponed": ["POSTPONED"],
            "cancelled": ["CANCELLED", "CANCELED"],
            "not_scheduled": [
                "COMPLETED",
                "COMPLETE",
                "FINAL",
                "FINISHED",
                "PLAYED",
                "IN_PROGRESS",
                "LIVE",
                "SUSPENDED",
                "TEMPORARILY_SUSPENDED",
                "ABANDONED",
                "UNCOMPLETED",
                "FORFEITED",
                "FORFEIT",
                "WALKOVER",
                "AWARDED",
                "ADMIN_AWARDED",
                "ADMINISTRATIVE_AWARD",
                "WITHDRAWN",
                "VOID",
                "REPLAYED",
                "NOT_PLAYED",
            ],
            "unknown": ["UNKNOWN"],
        },
        "version": F06_POLICY_VERSION,
    }


def policy_snapshot(policy_id: str, policy_version: str) -> PolicySnapshot:
    if (policy_id, policy_version) != (F06_POLICY_ID, F06_POLICY_VERSION):
        raise MatchweekMembershipError(
            "MV-F06-POLICY-UNSUPPORTED",
            "POLICY_UNSUPPORTED",
            f"Unsupported F06 membership policy {policy_id!r} version {policy_version!r}.",
        )
    encoded = canonical_json(membership_policy_document())
    return PolicySnapshot(policy_id, policy_version, encoded, sha256_digest(encoded))


@dataclass(frozen=True)
class PolicySnapshot:
    policy_id: str
    policy_version: str
    canonical_json: str
    digest: str

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("F06 policy identity must not be empty.")
        _digest(self.digest, "F06 policy digest")
        if canonical_json(json.loads(self.canonical_json)) != self.canonical_json:
            raise ValueError("F06 policy snapshot must use canonical JSON.")
        if sha256_digest(self.canonical_json) != self.digest:
            raise ValueError("F06 policy snapshot digest does not match its canonical JSON.")

    def to_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "canonical_json": self.canonical_json,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class ScopeSnapshot:
    scope_id: str
    league_key: str
    season: str
    matchweek_friday: str
    coverage_state: str
    window_start_utc: str
    window_end_utc: str


@dataclass(frozen=True)
class AuthoritySupportSnapshot:
    capture_id: str
    capture_digest: str
    assertion_id: str | None
    retrieved_at_utc: str
    source_key: str
    source_class: str
    authority_rank: int


@dataclass(frozen=True)
class FixtureRevisionSnapshot:
    scope_id: str
    fixture_id: str
    revision_id: str
    revision_digest: str
    predecessor_revision_id: str | None
    kickoff_state: str
    kickoff_utc: str | None
    kickoff_local_text: str | None
    kickoff_precision: str
    fixture_status: str
    source_capture_ids: tuple[str, ...]
    source_assertion_ids: tuple[str, ...]
    supports: tuple[AuthoritySupportSnapshot, ...]
    authority_rank: int
    latest_support_retrieved_at_utc: str


@dataclass(frozen=True)
class ConflictSnapshot:
    conflict_id: str
    predicate: str
    value_digest: str
    assertion_ids: tuple[str, ...]
    values: tuple[str, ...]


@dataclass(frozen=True)
class MembershipDecision:
    membership_id: str
    membership_digest: str
    scope_id: str
    fixture_id: str
    candidate_ids: tuple[str, ...]
    decision: MembershipState
    reason_code: str
    reason_codes: tuple[str, ...]
    controlling_revision_id: str
    controlling_revision_digest: str
    controlling_revision: FixtureRevisionSnapshot
    evaluated_revisions: tuple[FixtureRevisionSnapshot, ...]
    conflicts: tuple[ConflictSnapshot, ...]


@dataclass(frozen=True)
class ProviderHealthReference:
    assessment_digest: str
    attempt_id: str
    record_digest: str
    scope_id: str
    provider_id: str
    capability_id: str


@dataclass(frozen=True)
class MatchweekMembershipFreeze:
    freeze_id: str
    freeze_digest: str
    contract_version: str
    payload_version: int
    season: str
    matchweek_friday: str
    assessment_digest: str
    schedule_state: str
    policy: PolicySnapshot
    scopes: tuple[ScopeSnapshot, ...]
    provider_health_references: tuple[ProviderHealthReference, ...]
    memberships: tuple[MembershipDecision, ...]
    membership_set_digest: str
    created_at_utc: str

    def __post_init__(self) -> None:
        if (
            self.contract_version != F06_CONTRACT_VERSION
            or self.payload_version != F06_PAYLOAD_VERSION
        ):
            raise ValueError("F06 freeze contract or payload version is unsupported.")
        _digest(self.freeze_id, "F06 freeze ID")
        _digest(self.freeze_digest, "F06 freeze digest")
        _digest(self.assessment_digest, "F01 assessment digest")
        _digest(self.membership_set_digest, "F06 membership-set digest")
        if not self.season.strip():
            raise ValueError("F06 season must not be empty.")
        expected = fixture_scopes_for_matchweek(self.matchweek_friday, season=self.season)
        if tuple(item.scope_id for item in self.scopes) != tuple(
            item.scope_id for item in expected
        ):
            raise ValueError("F06 freeze scope snapshots must use canonical seven-scope order.")
        _canonical_utc(self.created_at_utc, "F06 created_at_utc")
        scope_order = {
            scope.scope_id: index
            for index, scope in enumerate(
                fixture_scopes_for_matchweek(self.matchweek_friday, season=self.season)
            )
        }
        if self.memberships != tuple(
            sorted(self.memberships, key=lambda item: (scope_order[item.scope_id], item.fixture_id))
        ):
            raise ValueError("F06 membership decisions must use canonical scope/fixture order.")

    def to_payload(self) -> dict[str, object]:
        return freeze_payload(self, include_digest=True)


@dataclass(frozen=True)
class FreezeReference:
    freeze_id: str
    freeze_digest: str
    assessment_digest: str
    policy_id: str
    policy_version: str
    created_at_utc: str
    membership_set_digest: str
    membership_count: int


@dataclass(frozen=True)
class MembershipObservationChange:
    change_code: ObservationCode
    scope_id: str
    fixture_id: str
    candidate_ids: tuple[str, ...]
    revision_ids: tuple[str, ...]
    revision_digests: tuple[str, ...]
    source_capture_ids: tuple[str, ...]
    source_assertion_ids: tuple[str, ...]
    facts: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class MatchweekMembershipObservation:
    observation_id: str
    observation_digest: str
    freeze_id: str
    assessment_digest: str
    assessment_state: str
    recorded_at_utc: str
    scopes: tuple[ScopeSnapshot, ...]
    changes: tuple[MembershipObservationChange, ...]

    def __post_init__(self) -> None:
        _digest(self.observation_id, "F06 observation ID")
        _digest(self.observation_digest, "F06 observation digest")
        _digest(self.freeze_id, "F06 freeze ID")
        _digest(self.assessment_digest, "F01 assessment digest")
        _canonical_utc(self.recorded_at_utc, "F06 recorded_at_utc")
        if not self.assessment_state:
            raise ValueError("F06 observation requires the later F01 aggregate state.")
        if len(self.scopes) != 7:
            raise ValueError("F06 observation must retain all seven exact F01 scope states.")
        if tuple(item.scope_id for item in self.scopes) != tuple(
            scope.scope_id
            for scope in fixture_scopes_for_matchweek(
                self.scopes[0].matchweek_friday, season=self.scopes[0].season
            )
        ):
            raise ValueError("F06 observation scopes must use canonical seven-scope order.")
        scope_order = {item.scope_id: index for index, item in enumerate(self.scopes)}
        expected_changes = tuple(
            sorted(
                self.changes,
                key=lambda item: (
                    scope_order[item.scope_id],
                    item.fixture_id,
                    item.change_code.value,
                    item.candidate_ids,
                    item.revision_ids,
                ),
            )
        )
        if self.changes != expected_changes:
            raise ValueError("F06 observation changes must use deterministic order.")


def freeze_identity(
    season: str,
    matchweek_friday: str,
    assessment_digest: str,
    policy: PolicySnapshot,
) -> str:
    return sha256_digest(
        canonical_json(
            {
                "assessment_digest": assessment_digest,
                "contract_version": F06_CONTRACT_VERSION,
                "matchweek_friday": matchweek_friday,
                "policy_digest": policy.digest,
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "season": season,
            }
        )
    )


def membership_identity(freeze_id: str, scope_id: str, fixture_id: str) -> str:
    return sha256_digest(
        canonical_json({"fixture_id": fixture_id, "freeze_id": freeze_id, "scope_id": scope_id})
    )


def decision_payload(decision: MembershipDecision, *, include_digest: bool) -> dict[str, object]:
    payload = cast(dict[str, object], _as_json(decision))
    if not include_digest:
        payload.pop("membership_digest")
    return payload


def membership_digest(decision: MembershipDecision) -> str:
    return sha256_digest(canonical_json(decision_payload(decision, include_digest=False)))


def membership_set_digest(memberships: tuple[MembershipDecision, ...]) -> str:
    return sha256_digest(
        canonical_json(
            [
                {"membership_digest": item.membership_digest, "membership_id": item.membership_id}
                for item in memberships
            ]
        )
    )


def freeze_payload(freeze: MatchweekMembershipFreeze, *, include_digest: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "assessment_digest": freeze.assessment_digest,
        "contract_version": freeze.contract_version,
        "created_at_utc": freeze.created_at_utc,
        "freeze_id": freeze.freeze_id,
        "matchweek_friday": freeze.matchweek_friday,
        "membership_set_digest": freeze.membership_set_digest,
        "memberships": [decision_payload(item, include_digest=True) for item in freeze.memberships],
        "payload_version": freeze.payload_version,
        "policy": freeze.policy.to_payload(),
        "provider_health_references": [
            _as_json(item) for item in freeze.provider_health_references
        ],
        "schedule_state": freeze.schedule_state,
        "scopes": [_as_json(item) for item in freeze.scopes],
        "season": freeze.season,
    }
    if include_digest:
        payload["freeze_digest"] = freeze.freeze_digest
    return payload


def freeze_digest(freeze: MatchweekMembershipFreeze) -> str:
    return sha256_digest(canonical_json(freeze_payload(freeze, include_digest=False)))


def freeze_from_canonical_json(encoded: str) -> MatchweekMembershipFreeze:
    try:
        raw = json.loads(encoded)
        if not isinstance(raw, dict) or canonical_json(raw) != encoded:
            raise ValueError("F06 freeze payload is not a canonical JSON object.")
        policy_raw = _object(raw["policy"], "policy")
        policy = PolicySnapshot(
            policy_id=_string(policy_raw["policy_id"], "policy_id"),
            policy_version=_string(policy_raw["policy_version"], "policy_version"),
            canonical_json=_string(policy_raw["canonical_json"], "canonical_json"),
            digest=_string(policy_raw["digest"], "policy digest"),
        )
        scopes = tuple(
            ScopeSnapshot(
                scope_id=_string(value["scope_id"], "scope_id"),
                league_key=_string(value["league_key"], "league_key"),
                season=_string(value["season"], "scope season"),
                matchweek_friday=_string(value["matchweek_friday"], "scope Friday"),
                coverage_state=_string(value["coverage_state"], "coverage_state"),
                window_start_utc=_string(value["window_start_utc"], "window_start_utc"),
                window_end_utc=_string(value["window_end_utc"], "window_end_utc"),
            )
            for value in _object_array(raw["scopes"], "scopes")
        )
        health = tuple(
            ProviderHealthReference(
                assessment_digest=_string(value["assessment_digest"], "assessment_digest"),
                attempt_id=_string(value["attempt_id"], "attempt_id"),
                record_digest=_string(value["record_digest"], "record_digest"),
                scope_id=_string(value["scope_id"], "scope_id"),
                provider_id=_string(value["provider_id"], "provider_id"),
                capability_id=_string(value["capability_id"], "capability_id"),
            )
            for value in _object_array(raw["provider_health_references"], "provider health refs")
        )
        memberships = tuple(
            _decision_from_object(value)
            for value in _object_array(raw["memberships"], "memberships")
        )
        freeze = MatchweekMembershipFreeze(
            freeze_id=_string(raw["freeze_id"], "freeze_id"),
            freeze_digest=_string(raw["freeze_digest"], "freeze_digest"),
            contract_version=_string(raw["contract_version"], "contract_version"),
            payload_version=_integer(raw["payload_version"], "payload_version"),
            season=_string(raw["season"], "season"),
            matchweek_friday=_string(raw["matchweek_friday"], "matchweek_friday"),
            assessment_digest=_string(raw["assessment_digest"], "assessment_digest"),
            schedule_state=_string(raw["schedule_state"], "schedule_state"),
            policy=policy,
            scopes=scopes,
            provider_health_references=health,
            memberships=memberships,
            membership_set_digest=_string(raw["membership_set_digest"], "membership_set_digest"),
            created_at_utc=_string(raw["created_at_utc"], "created_at_utc"),
        )
        _validate_freeze_digests(freeze)
        if canonical_json(freeze_payload(freeze, include_digest=True)) != encoded:
            raise ValueError("F06 freeze payload changes when reconstructed from canonical JSON.")
        return freeze
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("F06 freeze payload is malformed.") from error


def _decision_from_object(raw: dict[str, object]) -> MembershipDecision:
    controlling = _revision_from_object(
        _object(raw["controlling_revision"], "controlling_revision")
    )
    revisions = tuple(
        _revision_from_object(value)
        for value in _object_array(raw["evaluated_revisions"], "evaluated_revisions")
    )
    conflicts = tuple(
        ConflictSnapshot(
            conflict_id=_string(value["conflict_id"], "conflict_id"),
            predicate=_string(value["predicate"], "predicate"),
            value_digest=_string(value["value_digest"], "value_digest"),
            assertion_ids=_string_array(value["assertion_ids"], "assertion_ids"),
            values=_string_array(value["values"], "values"),
        )
        for value in _object_array(raw["conflicts"], "conflicts")
    )
    return MembershipDecision(
        membership_id=_string(raw["membership_id"], "membership_id"),
        membership_digest=_string(raw["membership_digest"], "membership_digest"),
        scope_id=_string(raw["scope_id"], "scope_id"),
        fixture_id=_string(raw["fixture_id"], "fixture_id"),
        candidate_ids=_string_array(raw["candidate_ids"], "candidate_ids"),
        decision=MembershipState(_string(raw["decision"], "decision")),
        reason_code=_string(raw["reason_code"], "reason_code"),
        reason_codes=_string_array(raw["reason_codes"], "reason_codes"),
        controlling_revision_id=_string(raw["controlling_revision_id"], "controlling_revision_id"),
        controlling_revision_digest=_string(
            raw["controlling_revision_digest"], "controlling_revision_digest"
        ),
        controlling_revision=controlling,
        evaluated_revisions=revisions,
        conflicts=conflicts,
    )


def _revision_from_object(raw: dict[str, object]) -> FixtureRevisionSnapshot:
    support_values = _object_array(raw["supports"], "supports")
    supports = tuple(
        AuthoritySupportSnapshot(
            capture_id=_string(value["capture_id"], "capture_id"),
            capture_digest=_string(value["capture_digest"], "capture_digest"),
            assertion_id=_optional_string(value["assertion_id"], "assertion_id"),
            retrieved_at_utc=_string(value["retrieved_at_utc"], "retrieved_at_utc"),
            source_key=_string(value["source_key"], "source_key"),
            source_class=_string(value["source_class"], "source_class"),
            authority_rank=_integer(value["authority_rank"], "authority_rank"),
        )
        for value in support_values
    )
    return FixtureRevisionSnapshot(
        scope_id=_string(raw["scope_id"], "scope_id"),
        fixture_id=_string(raw["fixture_id"], "fixture_id"),
        revision_id=_string(raw["revision_id"], "revision_id"),
        revision_digest=_string(raw["revision_digest"], "revision_digest"),
        predecessor_revision_id=_optional_string(
            raw["predecessor_revision_id"], "predecessor_revision_id"
        ),
        kickoff_state=_string(raw["kickoff_state"], "kickoff_state"),
        kickoff_utc=_optional_string(raw["kickoff_utc"], "kickoff_utc"),
        kickoff_local_text=_optional_string(raw["kickoff_local_text"], "kickoff_local_text"),
        kickoff_precision=_string(raw["kickoff_precision"], "kickoff_precision"),
        fixture_status=_string(raw["fixture_status"], "fixture_status"),
        source_capture_ids=_string_array(raw["source_capture_ids"], "source_capture_ids"),
        source_assertion_ids=_string_array(raw["source_assertion_ids"], "source_assertion_ids"),
        supports=supports,
        authority_rank=_integer(raw["authority_rank"], "authority_rank"),
        latest_support_retrieved_at_utc=_string(
            raw["latest_support_retrieved_at_utc"], "latest_support_retrieved_at_utc"
        ),
    )


def _validate_freeze_digests(freeze: MatchweekMembershipFreeze) -> None:
    expected_policy = policy_snapshot(freeze.policy.policy_id, freeze.policy.policy_version)
    if freeze.policy != expected_policy:
        raise ValueError("F06 policy snapshot does not match its supported version.")
    if freeze.freeze_id != freeze_identity(
        freeze.season, freeze.matchweek_friday, freeze.assessment_digest, freeze.policy
    ):
        raise ValueError("F06 freeze ID does not match its immutable identity.")
    for item in freeze.memberships:
        if item.membership_id != membership_identity(
            freeze.freeze_id, item.scope_id, item.fixture_id
        ):
            raise ValueError("F06 membership ID does not match its freeze and fixture identity.")
        if item.membership_digest != membership_digest(item):
            raise ValueError("F06 membership digest does not match its canonical decision.")
        if (
            item.controlling_revision.revision_id != item.controlling_revision_id
            or item.controlling_revision.revision_digest != item.controlling_revision_digest
        ):
            raise ValueError("F06 controlling revision snapshot differs from the decision.")
    if freeze.membership_set_digest != membership_set_digest(freeze.memberships):
        raise ValueError("F06 membership-set digest does not match its ordered decisions.")
    if freeze.freeze_digest != freeze_digest(freeze):
        raise ValueError("F06 freeze digest does not match its canonical payload.")


def observation_identity(freeze_id: str, assessment_digest: str) -> str:
    return sha256_digest(
        canonical_json({"assessment_digest": assessment_digest, "freeze_id": freeze_id})
    )


def observation_payload(
    observation: MatchweekMembershipObservation, *, include_digest: bool
) -> dict[str, object]:
    payload = cast(dict[str, object], _as_json(observation))
    if not include_digest:
        payload.pop("observation_digest")
    return payload


def observation_digest(observation: MatchweekMembershipObservation) -> str:
    return sha256_digest(canonical_json(observation_payload(observation, include_digest=False)))


def observation_from_canonical_json(encoded: str) -> MatchweekMembershipObservation:
    try:
        raw = json.loads(encoded)
        if not isinstance(raw, dict) or canonical_json(raw) != encoded:
            raise ValueError("F06 observation payload is not a canonical JSON object.")
        scopes = tuple(
            ScopeSnapshot(
                scope_id=_string(value["scope_id"], "scope_id"),
                league_key=_string(value["league_key"], "league_key"),
                season=_string(value["season"], "scope season"),
                matchweek_friday=_string(value["matchweek_friday"], "scope Friday"),
                coverage_state=_string(value["coverage_state"], "coverage_state"),
                window_start_utc=_string(value["window_start_utc"], "window_start_utc"),
                window_end_utc=_string(value["window_end_utc"], "window_end_utc"),
            )
            for value in _object_array(raw["scopes"], "scopes")
        )
        changes = tuple(
            MembershipObservationChange(
                change_code=ObservationCode(_string(value["change_code"], "change_code")),
                scope_id=_string(value["scope_id"], "scope_id"),
                fixture_id=_string(value["fixture_id"], "fixture_id"),
                candidate_ids=_string_array(value["candidate_ids"], "candidate_ids"),
                revision_ids=_string_array(value["revision_ids"], "revision_ids"),
                revision_digests=_string_array(value["revision_digests"], "revision_digests"),
                source_capture_ids=_string_array(value["source_capture_ids"], "source_capture_ids"),
                source_assertion_ids=_string_array(
                    value["source_assertion_ids"], "source_assertion_ids"
                ),
                facts=tuple(
                    (_string(pair[0], "fact key"), _optional_string(pair[1], "fact value"))
                    for pair in _pair_array(value["facts"], "facts")
                ),
            )
            for value in _object_array(raw["changes"], "changes")
        )
        observation = MatchweekMembershipObservation(
            observation_id=_string(raw["observation_id"], "observation_id"),
            observation_digest=_string(raw["observation_digest"], "observation_digest"),
            freeze_id=_string(raw["freeze_id"], "freeze_id"),
            assessment_digest=_string(raw["assessment_digest"], "assessment_digest"),
            assessment_state=_string(raw["assessment_state"], "assessment_state"),
            recorded_at_utc=_string(raw["recorded_at_utc"], "recorded_at_utc"),
            scopes=scopes,
            changes=changes,
        )
        if observation.observation_id != observation_identity(
            observation.freeze_id, observation.assessment_digest
        ):
            raise ValueError("F06 observation ID does not match its exact assessment identity.")
        if observation.observation_digest != observation_digest(observation):
            raise ValueError("F06 observation digest does not match its canonical payload.")
        if canonical_json(observation_payload(observation, include_digest=True)) != encoded:
            raise ValueError("F06 observation changes when reconstructed from canonical JSON.")
        return observation
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("F06 observation payload is malformed.") from error


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"F06 {label} must be an object.")
    return value


def _object_array(value: object, label: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"F06 {label} must be an array.")
    return tuple(_object(item, label) for item in value)


def _pair_array(value: object, label: str) -> tuple[list[object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"F06 {label} must be an array.")
    pairs: list[list[object]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"F06 {label} entries must be two-item arrays.")
        pairs.append(item)
    return tuple(pairs)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"F06 {label} must be a string.")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"F06 {label} must be a string or null.")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"F06 {label} must be an integer.")
    return value


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"F06 {label} must be an array of strings.")
    return tuple(value)


def _as_json(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _as_json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_as_json(item) for item in value]
    if isinstance(value, list):
        return [_as_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_json(item) for key, item in value.items()}
    return value

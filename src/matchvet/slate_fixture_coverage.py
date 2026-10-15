"""Five-league interval F01 successor with closed canonical serialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from matchvet.active_scope import SUCCESSOR_FIVE_SCOPE, ActiveScopeContract
from matchvet.fixture_coverage import (
    CoverageBounds,
    CoverageFreshnessResult,
    FixtureCoveragePayloadError,
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderAttemptState,
    ProviderCoverageEvidence,
    ScopeCoverageState,
    _full_partitions_accounted,
    _json_value,
    _single_freshness_policy_id,
)
from matchvet.slate_window import SlateWindow

SLATE_FIXTURE_COVERAGE_CONTRACT_VERSION: Final = "fixture-coverage-v5-slate-v1"
SLATE_FIXTURE_COVERAGE_SCHEMA_VERSION: Final = 5


class SlateFixtureCoveragePayloadError(ValueError):
    """A slate F01 payload is unsupported or not canonical."""


@dataclass(frozen=True, slots=True)
class SlateFixtureScope:
    league_key: str
    season: str
    active_scope: ActiveScopeContract
    slate_window: SlateWindow

    def __post_init__(self) -> None:
        if self.league_key not in self.active_scope.league_keys:
            raise ValueError("Slate fixture scope league must belong to the exact active scope.")
        if self.season != self.active_scope.season:
            raise ValueError("Slate fixture scope season must match the exact active scope.")
        if self.active_scope != SUCCESSOR_FIVE_SCOPE:
            raise ValueError("Slate fixture scope requires the installed five-league contract.")

    @property
    def scope_id(self) -> str:
        return f"{self.league_key}:{self.season}:{self.slate_window.slate_id}"

    @property
    def window_start_utc(self) -> str:
        return self.slate_window.start_utc

    @property
    def window_end_utc(self) -> str:
        return self.slate_window.end_utc


@dataclass(frozen=True, slots=True)
class SlateFixtureScopeAssessment:
    scope: SlateFixtureScope
    coverage_state: ScopeCoverageState
    provider_attempt_ids: tuple[str, ...]
    coverage_evidence_ids: tuple[str, ...]
    fixture_revisions: tuple[FixtureRevisionReference, ...]
    identity_blocker_candidate_ids: tuple[str, ...]
    freshness_results: tuple[CoverageFreshnessResult, ...]
    current_coverage_evidence_ids: tuple[str, ...]
    stale_coverage_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SlateFixtureCoverageAssessment:
    active_scope: ActiveScopeContract
    slate_window: SlateWindow
    freshness_policy_id: str | None
    scope_assessments: tuple[SlateFixtureScopeAssessment, ...]
    provider_attempts: tuple[ProviderAttempt, ...]
    coverage_evidence: tuple[ProviderCoverageEvidence, ...]
    fixture_revisions: tuple[FixtureRevisionReference, ...]
    identity_resolutions: tuple[FixtureIdentityResolution, ...]
    freshness_results: tuple[CoverageFreshnessResult, ...]
    schedule_state: MatchweekScheduleState
    contract_version: str = SLATE_FIXTURE_COVERAGE_CONTRACT_VERSION
    schema_version: int = SLATE_FIXTURE_COVERAGE_SCHEMA_VERSION
    digest: str = ""

    def __post_init__(self) -> None:
        if self.active_scope != SUCCESSOR_FIVE_SCOPE:
            raise ValueError("Slate F01 requires the installed five-league scope.")
        if (self.contract_version, self.schema_version) != (
            SLATE_FIXTURE_COVERAGE_CONTRACT_VERSION,
            SLATE_FIXTURE_COVERAGE_SCHEMA_VERSION,
        ):
            raise ValueError("Unsupported five-league interval F01 version.")
        if self.freshness_policy_id != _single_freshness_policy_id(self.freshness_results):
            raise ValueError("Slate F01 freshness policy identity must match its results.")
        expected_scopes = slate_fixture_scopes(self.slate_window, active_scope=self.active_scope)
        if tuple(item.scope for item in self.scope_assessments) != expected_scopes:
            raise ValueError("Slate F01 must retain exactly five ordered scopes for its window.")
        scope_ids = {scope.scope_id for scope in expected_scopes}
        attempts_by_id = {attempt.attempt_id: attempt for attempt in self.provider_attempts}
        if len(attempts_by_id) != len(self.provider_attempts) or any(
            attempt.scope_id not in scope_ids for attempt in self.provider_attempts
        ):
            raise ValueError("Slate F01 attempts must be unique and belong to its five scopes.")
        evidence_by_id = {evidence.evidence_id: evidence for evidence in self.coverage_evidence}
        if len(evidence_by_id) != len(self.coverage_evidence):
            raise ValueError("Slate F01 coverage evidence IDs must be unique.")
        for evidence in self.coverage_evidence:
            attempt = attempts_by_id.get(evidence.attempt_id)
            if (
                evidence.scope_id not in scope_ids
                or attempt is None
                or attempt.scope_id != evidence.scope_id
            ):
                raise ValueError("Slate F01 evidence must match its retained attempt and scope.")
        freshness_by_id = {item.evidence_id: item for item in self.freshness_results}
        if len(freshness_by_id) != len(self.freshness_results) or not set(freshness_by_id) <= set(
            evidence_by_id
        ):
            raise ValueError("Slate F01 freshness results must reference unique retained evidence.")
        revisions_by_id = {item.revision_id: item for item in self.fixture_revisions}
        if len(revisions_by_id) != len(self.fixture_revisions) or any(
            item.scope_id not in scope_ids for item in self.fixture_revisions
        ):
            raise ValueError("Slate F01 revisions must be unique and belong to its five scopes.")
        identities_by_candidate = {item.candidate_id: item for item in self.identity_resolutions}
        if len(identities_by_candidate) != len(self.identity_resolutions):
            raise ValueError("Slate F01 candidate identity IDs must be unique.")
        linked_revisions: set[str] = set()
        for identity in self.identity_resolutions:
            if identity.scope_id not in scope_ids:
                raise ValueError("Slate F01 identity resolutions must belong to its five scopes.")
            for revision_id in identity.revision_ids:
                revision = revisions_by_id.get(revision_id)
                if revision is None or revision.scope_id != identity.scope_id:
                    raise ValueError("Slate F01 identity resolution links an unrelated revision.")
                linked_revisions.add(revision_id)
                if (
                    str(identity.state) == "RESOLVED"
                    and revision.fixture_id != identity.canonical_fixture_id
                ):
                    raise ValueError("Slate F01 resolved identity conflicts with its revision.")
        if linked_revisions != set(revisions_by_id):
            raise ValueError("Every Slate F01 revision requires an identity resolution.")
        for item in self.scope_assessments:
            scope_id = item.scope.scope_id
            scope_attempts = tuple(
                sorted(
                    (attempt for attempt in self.provider_attempts if attempt.scope_id == scope_id),
                    key=lambda value: value.attempt_id,
                )
            )
            scope_evidence = tuple(
                sorted(
                    (
                        evidence
                        for evidence in self.coverage_evidence
                        if evidence.scope_id == scope_id
                    ),
                    key=lambda value: value.evidence_id,
                )
            )
            if item.provider_attempt_ids != tuple(attempt.attempt_id for attempt in scope_attempts):
                raise ValueError("Slate F01 scope attempt membership differs from its assessment.")
            if item.coverage_evidence_ids != tuple(
                evidence.evidence_id for evidence in scope_evidence
            ):
                raise ValueError("Slate F01 scope evidence membership differs from its assessment.")
            if item.fixture_revisions != tuple(
                sorted(
                    (
                        revision
                        for revision in self.fixture_revisions
                        if revision.scope_id == scope_id
                    ),
                    key=lambda value: value.revision_id,
                )
            ):
                raise ValueError("Slate F01 scope revision membership differs from its assessment.")
            scope_freshness = tuple(
                sorted(
                    (
                        freshness_by_id[evidence.evidence_id]
                        for evidence in scope_evidence
                        if evidence.evidence_id in freshness_by_id
                    ),
                    key=lambda value: value.evidence_id,
                )
            )
            if item.freshness_results != scope_freshness:
                raise ValueError("Slate F01 scope freshness results differ from retained evidence.")

            attempt_for_scope = {attempt.attempt_id: attempt for attempt in scope_attempts}
            current_ids: list[str] = []
            stale_ids: list[str] = []
            current_ranges: list[tuple[datetime, datetime]] = []
            empty_ranges: list[tuple[datetime, datetime]] = []
            for evidence in scope_evidence:
                attempt = attempt_for_scope[evidence.attempt_id]
                freshness = freshness_by_id.get(evidence.evidence_id)
                if (
                    attempt.state is not ProviderAttemptState.CAPTURED
                    or attempt.capture_id != evidence.capture_id
                    or attempt.capture_digest != evidence.capture_digest
                    or not evidence.permitted_for_use
                    or evidence.provider_use_policy_id is None
                    or evidence.provider_competition_key != item.scope.league_key
                    or evidence.provider_season != item.scope.season
                    or evidence.coverage_basis is None
                    or evidence.bounds is None
                ):
                    continue
                intersection = _intersection(self.slate_window, evidence.bounds)
                if intersection is None or freshness is None:
                    continue
                if freshness.is_current:
                    current_ids.append(evidence.evidence_id)
                    if _full_partitions_accounted(evidence):
                        current_ranges.append(intersection)
                        if evidence.affirmatively_empty:
                            empty_ranges.append(intersection)
                else:
                    stale_ids.append(evidence.evidence_id)
            if item.current_coverage_evidence_ids != tuple(sorted(current_ids)):
                raise ValueError("Slate F01 current evidence differs from its retained evidence.")
            if item.stale_coverage_evidence_ids != tuple(sorted(stale_ids)):
                raise ValueError("Slate F01 stale evidence differs from its retained evidence.")

            scope_identities = tuple(
                identity for identity in self.identity_resolutions if identity.scope_id == scope_id
            )
            unresolved_ids = tuple(
                sorted(
                    identity.candidate_id
                    for identity in scope_identities
                    if identity.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
                )
            )
            if item.identity_blocker_candidate_ids != unresolved_ids:
                raise ValueError("Slate F01 identity blockers differ from retained resolutions.")
            resolved_fixture_ids = {
                identity.canonical_fixture_id
                for identity in scope_identities
                if identity.state is FixtureIdentityState.RESOLVED
            }
            if unresolved_ids and current_ids:
                expected_coverage_state = ScopeCoverageState.PARTIAL
            elif _covers(self.slate_window, current_ranges) and resolved_fixture_ids:
                expected_coverage_state = ScopeCoverageState.COMPLETE
            elif (
                _covers(self.slate_window, current_ranges)
                and not resolved_fixture_ids
                and _covers(self.slate_window, empty_ranges)
            ):
                expected_coverage_state = ScopeCoverageState.CONFIRMED_EMPTY
            elif current_ids:
                expected_coverage_state = ScopeCoverageState.PARTIAL
            elif stale_ids:
                expected_coverage_state = ScopeCoverageState.STALE
            else:
                expected_coverage_state = ScopeCoverageState.UNKNOWN
            if item.coverage_state is not expected_coverage_state:
                raise ValueError("Slate F01 scope state is not justified by its retained evidence.")
        complete_states = {ScopeCoverageState.COMPLETE, ScopeCoverageState.CONFIRMED_EMPTY}
        if all(item.coverage_state in complete_states for item in self.scope_assessments):
            expected_schedule = (
                MatchweekScheduleState.CONFIRMED_EMPTY
                if all(
                    item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY
                    for item in self.scope_assessments
                )
                else MatchweekScheduleState.COMPLETE
            )
        elif any(item.current_coverage_evidence_ids for item in self.scope_assessments):
            expected_schedule = MatchweekScheduleState.PARTIAL
        elif any(item.stale_coverage_evidence_ids for item in self.scope_assessments):
            expected_schedule = MatchweekScheduleState.STALE
        else:
            expected_schedule = MatchweekScheduleState.UNKNOWN
        if self.schedule_state is not expected_schedule:
            raise ValueError("Slate F01 aggregate state must match its exact five scope states.")
        expected = _assessment_digest(self)
        if self.digest and self.digest != expected:
            raise ValueError("Slate F01 digest does not match its contents.")
        object.__setattr__(self, "digest", expected)


def slate_fixture_scopes(
    window: SlateWindow, *, active_scope: ActiveScopeContract = SUCCESSOR_FIVE_SCOPE
) -> tuple[SlateFixtureScope, ...]:
    if active_scope != SUCCESSOR_FIVE_SCOPE:
        raise ValueError("Slate F01 supports only the installed five-league scope.")
    return tuple(
        SlateFixtureScope(key, active_scope.season, active_scope, window)
        for key in active_scope.league_keys
    )


def assess_slate_fixture_coverage(
    *,
    window: SlateWindow,
    provider_attempts: tuple[ProviderAttempt, ...],
    coverage_evidence: tuple[ProviderCoverageEvidence, ...],
    fixture_revisions: tuple[FixtureRevisionReference, ...],
    identity_resolutions: tuple[FixtureIdentityResolution, ...],
    freshness_results: tuple[CoverageFreshnessResult, ...],
    active_scope: ActiveScopeContract = SUCCESSOR_FIVE_SCOPE,
) -> SlateFixtureCoverageAssessment:
    """Assess all five exact interval scopes, preserving all F01 states and evidence."""
    scopes = slate_fixture_scopes(window, active_scope=active_scope)
    scope_ids = {scope.scope_id for scope in scopes}
    attempts_by_id: dict[str, ProviderAttempt] = {}
    evidence_by_id: dict[str, ProviderCoverageEvidence] = {}
    for attempt in provider_attempts:
        if attempt.attempt_id in attempts_by_id or attempt.scope_id not in scope_ids:
            raise ValueError("Slate F01 attempts must be unique and belong to one exact scope.")
        attempts_by_id[attempt.attempt_id] = attempt
    for evidence in coverage_evidence:
        referenced_attempt = attempts_by_id.get(evidence.attempt_id)
        if (
            evidence.evidence_id in evidence_by_id
            or evidence.scope_id not in scope_ids
            or referenced_attempt is None
            or referenced_attempt.scope_id != evidence.scope_id
        ):
            raise ValueError("Slate F01 coverage evidence must match its exact attempt and scope.")
        evidence_by_id[evidence.evidence_id] = evidence
    if any(item.scope_id not in scope_ids for item in fixture_revisions):
        raise ValueError("Slate F01 identity and revisions must belong to the exact window.")
    if any(item.scope_id not in scope_ids for item in identity_resolutions):
        raise ValueError("Slate F01 identity and revisions must belong to the exact window.")
    freshness_by_id = {item.evidence_id: item for item in freshness_results}
    if len(freshness_by_id) != len(freshness_results) or not set(freshness_by_id) <= set(
        evidence_by_id
    ):
        raise ValueError("Slate F01 freshness results must refer to unique retained evidence.")

    # The established assessor already implements source basis, pagination, and
    # affirmative-empty semantics. A tiny scope adapter supplies this window's exact bounds;
    # its historical Friday constructor is deliberately not invoked.
    return _assess_slate_with_existing_rules(
        active_scope=active_scope,
        window=window,
        scopes=scopes,
        provider_attempts=provider_attempts,
        coverage_evidence=coverage_evidence,
        fixture_revisions=fixture_revisions,
        identity_resolutions=identity_resolutions,
        freshness_results=freshness_results,
    )


def _assess_slate_with_existing_rules(
    *,
    active_scope: ActiveScopeContract,
    window: SlateWindow,
    scopes: tuple[SlateFixtureScope, ...],
    provider_attempts: tuple[ProviderAttempt, ...],
    coverage_evidence: tuple[ProviderCoverageEvidence, ...],
    fixture_revisions: tuple[FixtureRevisionReference, ...],
    identity_resolutions: tuple[FixtureIdentityResolution, ...],
    freshness_results: tuple[CoverageFreshnessResult, ...],
) -> SlateFixtureCoverageAssessment:
    # Reuse the established F01 algebra while keeping interval identity and codecs separate.
    attempt_by_id = {item.attempt_id: item for item in provider_attempts}
    evidence_by_scope: dict[str, list[ProviderCoverageEvidence]] = {
        scope.scope_id: [] for scope in scopes
    }
    for evidence in coverage_evidence:
        evidence_by_scope[evidence.scope_id].append(evidence)
    revisions_by_scope: dict[str, list[FixtureRevisionReference]] = {
        scope.scope_id: [] for scope in scopes
    }
    for revision in fixture_revisions:
        revisions_by_scope[revision.scope_id].append(revision)
    identities_by_scope: dict[str, list[FixtureIdentityResolution]] = {
        scope.scope_id: [] for scope in scopes
    }
    for identity in identity_resolutions:
        identities_by_scope[identity.scope_id].append(identity)
    freshness_by_id = {item.evidence_id: item for item in freshness_results}
    assessments: list[SlateFixtureScopeAssessment] = []
    from matchvet.fixture_coverage import FixtureIdentityState, _full_partitions_accounted

    for scope in scopes:
        current: list[str] = []
        stale: list[str] = []
        current_ranges: list[tuple[datetime, datetime]] = []
        empty_ranges: list[tuple[datetime, datetime]] = []
        for evidence in evidence_by_scope[scope.scope_id]:
            attempt = attempt_by_id[evidence.attempt_id]
            freshness = freshness_by_id.get(evidence.evidence_id)
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
            intersection = _intersection(window, evidence.bounds)
            if intersection is None or freshness is None:
                continue
            if freshness.is_current:
                current.append(evidence.evidence_id)
                if _full_partitions_accounted(evidence):
                    current_ranges.append(intersection)
                    if evidence.affirmatively_empty:
                        empty_ranges.append(intersection)
            else:
                stale.append(evidence.evidence_id)
        identities = identities_by_scope[scope.scope_id]
        unresolved = tuple(
            sorted(
                item.candidate_id
                for item in identities
                if item.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
            )
        )
        fixture_ids = {
            item.canonical_fixture_id
            for item in identities
            if item.state is FixtureIdentityState.RESOLVED
        }
        if unresolved and current:
            state = ScopeCoverageState.PARTIAL
        elif _covers(window, current_ranges) and fixture_ids:
            state = ScopeCoverageState.COMPLETE
        elif _covers(window, current_ranges) and not fixture_ids and _covers(window, empty_ranges):
            state = ScopeCoverageState.CONFIRMED_EMPTY
        elif current:
            state = ScopeCoverageState.PARTIAL
        elif stale:
            state = ScopeCoverageState.STALE
        else:
            state = ScopeCoverageState.UNKNOWN
        assessments.append(
            SlateFixtureScopeAssessment(
                scope=scope,
                coverage_state=state,
                provider_attempt_ids=tuple(
                    sorted(
                        item.attempt_id
                        for item in provider_attempts
                        if item.scope_id == scope.scope_id
                    )
                ),
                coverage_evidence_ids=tuple(
                    sorted(item.evidence_id for item in evidence_by_scope[scope.scope_id])
                ),
                fixture_revisions=tuple(
                    sorted(revisions_by_scope[scope.scope_id], key=lambda item: item.revision_id)
                ),
                identity_blocker_candidate_ids=unresolved,
                freshness_results=tuple(
                    sorted(
                        (
                            freshness_by_id[item.evidence_id]
                            for item in evidence_by_scope[scope.scope_id]
                            if item.evidence_id in freshness_by_id
                        ),
                        key=lambda item: item.evidence_id,
                    )
                ),
                current_coverage_evidence_ids=tuple(sorted(current)),
                stale_coverage_evidence_ids=tuple(sorted(stale)),
            )
        )
    complete = {ScopeCoverageState.COMPLETE, ScopeCoverageState.CONFIRMED_EMPTY}
    if all(item.coverage_state in complete for item in assessments):
        schedule_state = (
            MatchweekScheduleState.CONFIRMED_EMPTY
            if all(
                item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY for item in assessments
            )
            else MatchweekScheduleState.COMPLETE
        )
    elif any(item.current_coverage_evidence_ids for item in assessments):
        schedule_state = MatchweekScheduleState.PARTIAL
    elif any(item.stale_coverage_evidence_ids for item in assessments):
        schedule_state = MatchweekScheduleState.STALE
    else:
        schedule_state = MatchweekScheduleState.UNKNOWN
    return SlateFixtureCoverageAssessment(
        active_scope=active_scope,
        slate_window=window,
        freshness_policy_id=_single_freshness_policy_id(freshness_results),
        scope_assessments=tuple(assessments),
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


def _intersection(window: SlateWindow, bounds: CoverageBounds) -> tuple[datetime, datetime] | None:
    start = max(datetime.fromisoformat(window.start_utc), datetime.fromisoformat(bounds.start_utc))
    end = min(datetime.fromisoformat(window.end_utc), datetime.fromisoformat(bounds.end_utc))
    return None if start >= end else (start, end)


def _covers(window: SlateWindow, ranges: list[tuple[datetime, datetime]]) -> bool:
    cursor = datetime.fromisoformat(window.start_utc)
    end = datetime.fromisoformat(window.end_utc)
    for start, range_end in sorted(ranges):
        if range_end <= cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, range_end)
        if cursor >= end:
            return True
    return False


def _assessment_payload(assessment: SlateFixtureCoverageAssessment) -> dict[str, object]:
    payload = _json_value(assessment)
    if not isinstance(payload, dict):
        raise TypeError("Slate F01 payload must be an object.")
    payload.pop("digest", None)
    return payload


def _assessment_digest(assessment: SlateFixtureCoverageAssessment) -> str:
    canonical = json.dumps(
        _assessment_payload(assessment), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def encode_slate_f01(assessment: SlateFixtureCoverageAssessment) -> str:
    payload = _assessment_payload(assessment)
    payload["digest"] = assessment.digest
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def decode_slate_f01(encoded: str) -> SlateFixtureCoverageAssessment:
    """Decode only canonical v5/schema5 five-league interval assessments."""
    from matchvet.active_scope import ActiveScopeContract
    from matchvet.fixture_coverage import (
        _coverage_evidence_from_json,
        _freshness_result_from_json,
        _identity_resolution_from_json,
        _payload_int,
        _payload_list,
        _payload_object,
        _payload_optional_string,
        _payload_string,
        _payload_string_tuple,
        _provider_attempt_from_json,
        _revision_reference_from_json,
    )

    try:
        root = json.loads(encoded)
        if not isinstance(root, dict):
            raise FixtureCoveragePayloadError("Slate F01 root must be an object.")
        canonical = json.dumps(root, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        if canonical != encoded:
            raise FixtureCoveragePayloadError("Slate F01 JSON is not canonical.")
        root = _payload_object(
            root,
            (
                "active_scope",
                "contract_version",
                "schema_version",
                "slate_window",
                "freshness_policy_id",
                "scope_assessments",
                "provider_attempts",
                "coverage_evidence",
                "fixture_revisions",
                "identity_resolutions",
                "freshness_results",
                "schedule_state",
                "digest",
            ),
            "Slate F01",
        )
        active = _payload_object(
            root["active_scope"],
            ("contract_id", "version", "season", "league_keys", "digest"),
            "Active Scope Contract",
        )
        active_scope = ActiveScopeContract(
            contract_id=_payload_string(active["contract_id"], "contract_id"),
            version=_payload_int(active["version"], "version"),
            season=_payload_string(active["season"], "season"),
            league_keys=_payload_string_tuple(active["league_keys"], "league_keys"),
            digest=_payload_string(active["digest"], "digest"),
        )
        window_value = _payload_object(
            root["slate_window"],
            (
                "start_utc",
                "end_utc",
                "active_scope",
                "contract_id",
                "version",
                "digest",
            ),
            "Slate Window",
        )
        window_active = _payload_object(
            window_value["active_scope"],
            ("contract_id", "version", "season", "league_keys", "digest"),
            "Slate Window Active Scope",
        )
        window_scope = ActiveScopeContract(
            contract_id=_payload_string(window_active["contract_id"], "contract_id"),
            version=_payload_int(window_active["version"], "version"),
            season=_payload_string(window_active["season"], "season"),
            league_keys=_payload_string_tuple(window_active["league_keys"], "league_keys"),
            digest=_payload_string(window_active["digest"], "digest"),
        )
        window = SlateWindow(
            start_utc=_payload_string(window_value["start_utc"], "start_utc"),
            end_utc=_payload_string(window_value["end_utc"], "end_utc"),
            active_scope=window_scope,
            contract_id=_payload_string(window_value["contract_id"], "contract_id"),
            version=_payload_int(window_value["version"], "version"),
            digest=_payload_string(window_value["digest"], "digest"),
        )
        assessments = tuple(
            _decode_scope_assessment(value, window, active_scope)
            for value in _payload_list(root["scope_assessments"], "scope_assessments")
        )
        assessment = SlateFixtureCoverageAssessment(
            contract_version=_payload_string(root["contract_version"], "contract_version"),
            schema_version=_payload_int(root["schema_version"], "schema_version"),
            active_scope=active_scope,
            slate_window=window,
            freshness_policy_id=_payload_optional_string(
                root["freshness_policy_id"], "freshness_policy_id"
            ),
            scope_assessments=assessments,
            provider_attempts=tuple(
                _provider_attempt_from_json(value)
                for value in _payload_list(root["provider_attempts"], "provider_attempts")
            ),
            coverage_evidence=tuple(
                _coverage_evidence_from_json(value)
                for value in _payload_list(root["coverage_evidence"], "coverage_evidence")
            ),
            fixture_revisions=tuple(
                _revision_reference_from_json(value)
                for value in _payload_list(root["fixture_revisions"], "fixture_revisions")
            ),
            identity_resolutions=tuple(
                _identity_resolution_from_json(value)
                for value in _payload_list(root["identity_resolutions"], "identity_resolutions")
            ),
            freshness_results=tuple(
                _freshness_result_from_json(value)
                for value in _payload_list(root["freshness_results"], "freshness_results")
            ),
            schedule_state=MatchweekScheduleState(
                _payload_string(root["schedule_state"], "schedule_state")
            ),
            digest=_payload_string(root["digest"], "digest"),
        )
        if encode_slate_f01(assessment) != encoded:
            raise FixtureCoveragePayloadError("Slate F01 references or ordering are inconsistent.")
        return assessment
    except FixtureCoveragePayloadError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FixtureCoveragePayloadError("Slate F01 payload is invalid.") from error


def _decode_scope_assessment(
    value: object, window: SlateWindow, active_scope: ActiveScopeContract
) -> SlateFixtureScopeAssessment:
    from matchvet.fixture_coverage import (
        _freshness_result_from_json,
        _payload_list,
        _payload_object,
        _payload_string,
        _payload_string_tuple,
        _revision_reference_from_json,
    )

    item = _payload_object(
        value,
        (
            "scope",
            "coverage_state",
            "provider_attempt_ids",
            "coverage_evidence_ids",
            "fixture_revisions",
            "identity_blocker_candidate_ids",
            "freshness_results",
            "current_coverage_evidence_ids",
            "stale_coverage_evidence_ids",
        ),
        "Slate Fixture Scope Assessment",
    )
    scope_value = _payload_object(
        item["scope"],
        ("league_key", "season", "active_scope", "slate_window"),
        "Slate Fixture Scope",
    )
    if scope_value["active_scope"] != _json_value(active_scope) or scope_value[
        "slate_window"
    ] != _json_value(window):
        raise FixtureCoveragePayloadError("Slate F01 scope binds another active scope or window.")
    scope = SlateFixtureScope(
        league_key=_payload_string(scope_value["league_key"], "league_key"),
        season=_payload_string(scope_value["season"], "season"),
        active_scope=active_scope,
        slate_window=window,
    )
    from matchvet.fixture_coverage import ScopeCoverageState

    return SlateFixtureScopeAssessment(
        scope=scope,
        coverage_state=ScopeCoverageState(
            _payload_string(item["coverage_state"], "coverage_state")
        ),
        provider_attempt_ids=_payload_string_tuple(
            item["provider_attempt_ids"], "provider_attempt_ids"
        ),
        coverage_evidence_ids=_payload_string_tuple(
            item["coverage_evidence_ids"], "coverage_evidence_ids"
        ),
        fixture_revisions=tuple(
            _revision_reference_from_json(entry)
            for entry in _payload_list(item["fixture_revisions"], "fixture_revisions")
        ),
        identity_blocker_candidate_ids=_payload_string_tuple(
            item["identity_blocker_candidate_ids"], "identity_blocker_candidate_ids"
        ),
        freshness_results=tuple(
            _freshness_result_from_json(entry)
            for entry in _payload_list(item["freshness_results"], "freshness_results")
        ),
        current_coverage_evidence_ids=_payload_string_tuple(
            item["current_coverage_evidence_ids"], "current_coverage_evidence_ids"
        ),
        stale_coverage_evidence_ids=_payload_string_tuple(
            item["stale_coverage_evidence_ids"], "stale_coverage_evidence_ids"
        ),
    )

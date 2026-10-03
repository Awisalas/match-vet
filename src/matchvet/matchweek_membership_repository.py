"""Exact F01/F05-backed persistence for the immutable V2 membership freeze."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from matchvet.fixture_coverage import (
    FixtureIdentityResolution,
    FixtureIdentityState,
    FixtureRevisionReference,
    FixtureScope,
    MatchweekScheduleState,
    ScopeCoverageState,
    SupportedFixtureCoverageAssessment,
    fixture_scopes_for_matchweek,
)
from matchvet.fixture_coverage_repository import (
    FixtureCoverageIntegrityError,
    FixtureCoverageRepository,
)
from matchvet.ingestion import EvidenceState
from matchvet.matchweek import MatchweekWindow, _authority_rank
from matchvet.matchweek_membership import (
    F06_CONTRACT_VERSION,
    F06_PAYLOAD_VERSION,
    AuthoritySupportSnapshot,
    ConflictSnapshot,
    FixtureRevisionSnapshot,
    FreezeReference,
    MatchweekMembershipError,
    MatchweekMembershipFreeze,
    MatchweekMembershipObservation,
    MembershipDecision,
    MembershipObservationChange,
    MembershipState,
    ObservationCode,
    PolicySnapshot,
    ProviderHealthReference,
    ScopeSnapshot,
    canonical_json,
    decision_payload,
    freeze_digest,
    freeze_from_canonical_json,
    freeze_identity,
    freeze_payload,
    membership_digest,
    membership_identity,
    membership_set_digest,
    observation_digest,
    observation_from_canonical_json,
    observation_identity,
    observation_payload,
    policy_snapshot,
)
from matchvet.operator_fixture_observation import (
    OperatorFixtureObservationIntegrityError,
    verify_operator_fixture_observation_capture,
)
from matchvet.provider_health import ProviderAttemptReference, ProviderHealthRecord
from matchvet.provider_health_repository import (
    ProviderHealthIntegrityError,
    ProviderHealthRepository,
)
from matchvet.store import Store

if TYPE_CHECKING:
    from collections.abc import Mapping


class MatchweekMembershipIntegrityError(MatchweekMembershipError):
    """Stored F06 content or its immutable references failed validation."""


class MatchweekMembershipPersistenceError(MatchweekMembershipError):
    """An F06 root and its children could not be committed atomically."""


class MatchweekMembershipRepository:
    """Create, persist, replay, and enumerate V2 Matchweek membership freezes."""

    def __init__(
        self,
        store: Store,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def freeze_exact(
        self,
        season: str,
        matchweek_friday: str,
        assessment_digest: str,
        policy_id: str,
        policy_version: str,
    ) -> MatchweekMembershipFreeze:
        """Freeze one explicitly named persisted F01 assessment and exact F05 history."""
        scopes = _requested_scopes(season, matchweek_friday)
        policy = policy_snapshot(policy_id, policy_version)
        freeze_id = freeze_identity(season, matchweek_friday, assessment_digest, policy)
        existing = self.get_by_id(freeze_id)
        if existing is not None:
            return existing

        assessment = self._load_assessment(assessment_digest)
        _validate_assessment_gate(assessment, season, matchweek_friday, scopes)
        health_references = self._exact_health_references(assessment)
        memberships = _build_memberships(self._store, assessment, freeze_id, policy)
        created_at_utc = _clock_timestamp(self._clock)
        freeze = _new_freeze(
            freeze_id=freeze_id,
            season=season,
            matchweek_friday=matchweek_friday,
            assessment=assessment,
            policy=policy,
            health_references=health_references,
            memberships=memberships,
            created_at_utc=created_at_utc,
        )
        try:
            return self._persist(freeze, allow_creation_time_winner=True)
        except MatchweekMembershipIntegrityError as error:
            # A concurrent exact request can commit between the initial read and insert.
            if error.code != "MV-F06-IDENTITY-CONFLICT":
                raise
            winner = self.get_by_id(freeze_id)
            if winner is None or _same_request_content(winner, freeze):
                return cast(MatchweekMembershipFreeze, winner)
            raise

    def persist_exact(self, freeze: MatchweekMembershipFreeze) -> MatchweekMembershipFreeze:
        """Validate and atomically persist one caller supplied complete F06 value."""
        return self._persist(freeze, allow_creation_time_winner=False)

    def get_by_id(self, freeze_id: str) -> MatchweekMembershipFreeze | None:
        """Replay one exact F06 freeze by its immutable identity."""
        row = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT freeze_json, freeze_digest, season, matchweek_friday,
                   assessment_digest, policy_id, policy_version, policy_digest,
                   schedule_state, membership_set_digest, membership_count, created_at_utc
            FROM v2_matchweek_membership_freezes
            WHERE freeze_id = ?
            """,
                (freeze_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        try:
            freeze = freeze_from_canonical_json(str(row[0]))
            _validate_root_row(freeze, tuple(row))
            self._validate_stored_children(freeze)
            self._validate_replay_references(freeze)
            return freeze
        except MatchweekMembershipIntegrityError:
            raise
        except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError) as error:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                f"Stored F06 freeze {freeze_id} is malformed or corrupt.",
            ) from error

    def get_by_digest(self, freeze_digest_value: str) -> MatchweekMembershipFreeze | None:
        """Replay one exact F06 freeze by its full payload digest."""
        row = (
            self._store._connection_for_repository()
            .execute(
                "SELECT freeze_id FROM v2_matchweek_membership_freezes WHERE freeze_digest = ?",
                (freeze_digest_value,),
            )
            .fetchone()
        )
        if row is None:
            return None
        freeze = self.get_by_id(str(row[0]))
        if freeze is None or freeze.freeze_digest != freeze_digest_value:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                "Stored F06 freeze digest points to a missing or mismatched identity.",
            )
        return freeze

    def list_for_matchweek(self, season: str, matchweek_friday: str) -> tuple[FreezeReference, ...]:
        """List all explicit freeze identities for a Matchweek in stable order."""
        _requested_scopes(season, matchweek_friday)
        rows = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT freeze_id
            FROM v2_matchweek_membership_freezes
            WHERE season = ? AND matchweek_friday = ?
            ORDER BY created_at_utc, freeze_id
            """,
                (season, matchweek_friday),
            )
            .fetchall()
        )
        references: list[FreezeReference] = []
        for row in rows:
            freeze = self.get_by_id(str(row[0]))
            if freeze is None:
                raise MatchweekMembershipIntegrityError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_MISSING",
                    f"F06 history row {row[0]} disappeared during replay.",
                )
            references.append(
                FreezeReference(
                    freeze_id=freeze.freeze_id,
                    freeze_digest=freeze.freeze_digest,
                    assessment_digest=freeze.assessment_digest,
                    policy_id=freeze.policy.policy_id,
                    policy_version=freeze.policy.policy_version,
                    created_at_utc=freeze.created_at_utc,
                    membership_set_digest=freeze.membership_set_digest,
                    membership_count=len(freeze.memberships),
                )
            )
        return tuple(references)

    def append_observation(
        self, freeze_id: str, assessment_digest: str
    ) -> MatchweekMembershipObservation:
        """Append a later exact F01 assessment without changing original membership."""
        freeze = self.get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekMembershipError(
                "MV-F06-REFERENCE-INTEGRITY",
                "FREEZE_MISSING",
                f"F06 freeze {freeze_id} does not exist.",
            )
        assessment = self._load_assessment(assessment_digest)
        _validate_observation_matchweek(freeze, assessment)
        observation_id = observation_identity(freeze_id, assessment_digest)
        existing = self._get_observation(observation_id)
        if existing is not None:
            return existing
        changes = _build_observation_changes(self._store, freeze, assessment)
        provisional = MatchweekMembershipObservation(
            observation_id=observation_id,
            observation_digest="sha256:" + "0" * 64,
            freeze_id=freeze_id,
            assessment_digest=assessment_digest,
            assessment_state=assessment.schedule_state.value,
            recorded_at_utc=_clock_timestamp(self._clock),
            scopes=_scope_snapshots(assessment),
            changes=changes,
        )
        observation = replace(provisional, observation_digest=observation_digest(provisional))
        encoded = canonical_json(observation_payload(observation, include_digest=True))
        try:
            with self._store.transaction() as transaction:
                current = transaction.execute(
                    """
                    SELECT observation_json
                    FROM v2_matchweek_membership_observations
                    WHERE observation_id = ?
                    """,
                    (observation_id,),
                ).fetchone()
                if current is not None:
                    winner = observation_from_canonical_json(str(current[0]))
                    if _same_observation_content(winner, observation):
                        return winner
                    raise MatchweekMembershipIntegrityError(
                        "MV-F06-IDENTITY-CONFLICT",
                        "IDENTITY_CONFLICT",
                        f"F06 observation identity {observation_id} has conflicting content.",
                    )
                transaction.execute(
                    """
                    INSERT INTO v2_matchweek_membership_observations (
                        observation_id, observation_digest, observation_json, freeze_id,
                        assessment_digest, assessment_state, recorded_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation.observation_id,
                        observation.observation_digest,
                        encoded,
                        observation.freeze_id,
                        observation.assessment_digest,
                        observation.assessment_state,
                        observation.recorded_at_utc,
                    ),
                )
            return observation
        except sqlite3.IntegrityError as error:
            retry_winner = self._get_observation(observation_id)
            if retry_winner is not None and _same_observation_content(retry_winner, observation):
                return retry_winner
            raise MatchweekMembershipPersistenceError(
                "MV-F06-PERSISTENCE-FAILED",
                "PERSISTENCE_FAILED",
                "F06 observation could not be committed atomically.",
            ) from error

    def list_observations(self, freeze_id: str) -> tuple[MatchweekMembershipObservation, ...]:
        """List exact append-only observations in stable recorded order."""
        freeze = self.get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekMembershipError(
                "MV-F06-REFERENCE-INTEGRITY",
                "FREEZE_MISSING",
                f"F06 freeze {freeze_id} does not exist.",
            )
        rows = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT observation_id
            FROM v2_matchweek_membership_observations
            WHERE freeze_id = ?
            ORDER BY recorded_at_utc, observation_id
            """,
                (freeze_id,),
            )
            .fetchall()
        )
        observations: list[MatchweekMembershipObservation] = []
        for row in rows:
            observation = self._get_observation(str(row[0]))
            if observation is None:
                raise _stored_corruption(
                    f"F06 observation {row[0]} disappeared during exact replay."
                )
            observations.append(observation)
        return tuple(observations)

    def _get_observation(self, observation_id: str) -> MatchweekMembershipObservation | None:
        row = (
            self._store._connection_for_repository()
            .execute(
                """
            SELECT observation_json, observation_digest, freeze_id, assessment_digest,
                   assessment_state, recorded_at_utc
            FROM v2_matchweek_membership_observations
            WHERE observation_id = ?
            """,
                (observation_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        try:
            observation = observation_from_canonical_json(str(row[0]))
            if tuple(row[1:]) != (
                observation.observation_digest,
                observation.freeze_id,
                observation.assessment_digest,
                observation.assessment_state,
                observation.recorded_at_utc,
            ):
                raise _stored_corruption(
                    f"F06 observation root columns for {observation_id} differ from its payload."
                )
            self._validate_observation_references(observation)
            return observation
        except MatchweekMembershipIntegrityError:
            raise
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                f"Stored F06 observation {observation_id} is malformed or corrupt.",
            ) from error

    def _validate_observation_references(self, observation: MatchweekMembershipObservation) -> None:
        freeze = self.get_by_id(observation.freeze_id)
        if freeze is None:
            raise _stored_corruption("F06 observation references a missing freeze.")
        assessment = self._load_assessment(observation.assessment_digest)
        _validate_observation_matchweek(freeze, assessment)
        expected_scopes = _scope_snapshots(assessment)
        expected_changes = _build_observation_changes(self._store, freeze, assessment)
        if (
            observation.assessment_state != assessment.schedule_state.value
            or observation.scopes != expected_scopes
            or observation.changes != expected_changes
        ):
            raise _stored_corruption(
                f"F06 observation {observation.observation_id} differs from its exact F01 facts."
            )

    def _load_assessment(self, assessment_digest: str) -> SupportedFixtureCoverageAssessment:
        try:
            assessment = FixtureCoverageRepository(self._store).get(assessment_digest)
        except FixtureCoverageIntegrityError as error:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_CORRUPT",
                f"F06 cannot validate exact F01 assessment {assessment_digest}.",
            ) from error
        except ValueError as error:
            raise MatchweekMembershipError(
                "MV-F06-ASSESSMENT-MISSING",
                "ASSESSMENT_MISSING",
                f"Exact F01 assessment digest {assessment_digest!r} is invalid.",
            ) from error
        if assessment is None:
            raise MatchweekMembershipError(
                "MV-F06-ASSESSMENT-MISSING",
                "ASSESSMENT_MISSING",
                f"Exact F01 assessment {assessment_digest} does not exist.",
            )
        return assessment

    def _exact_health_references(
        self, assessment: SupportedFixtureCoverageAssessment
    ) -> tuple[ProviderHealthReference, ...]:
        try:
            records = ProviderHealthRepository(self._store).list_for_assessment(assessment.digest)
        except ProviderHealthIntegrityError as error:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-HEALTH-INCOMPLETE",
                "HEALTH_HISTORY_INCOMPLETE",
                f"F05 history for exact F01 assessment {assessment.digest} is invalid.",
            ) from error
        attempts = {attempt.attempt_id: attempt for attempt in assessment.provider_attempts}
        records_by_attempt: dict[str, ProviderHealthRecord] = {}
        for record in records:
            attempt_id = _health_attempt_id(record)
            if attempt_id in records_by_attempt:
                raise _health_refusal(
                    assessment.digest, f"F05 has duplicate records for attempt {attempt_id}."
                )
            records_by_attempt[attempt_id] = record
        if set(records_by_attempt) != set(attempts):
            missing = sorted(set(attempts) - set(records_by_attempt))
            extra = sorted(set(records_by_attempt) - set(attempts))
            raise _health_refusal(
                assessment.digest,
                f"F05 attempt history differs from F01. Missing {missing}; unexpected {extra}.",
            )
        scope_order = {
            scope.scope_id: index
            for index, scope in enumerate(
                fixture_scopes_for_matchweek(
                    assessment.scope_assessments[0].scope.matchweek_friday,
                    season=assessment.scope_assessments[0].scope.season,
                )
            )
        }
        result: list[ProviderHealthReference] = []
        for attempt_id, attempt in attempts.items():
            record = records_by_attempt[attempt_id]
            metadata = _health_metadata(record)
            if (
                metadata["assessment_digest"] != assessment.digest
                or metadata["attempt_id"] != attempt_id
                or metadata["scope_id"] != attempt.scope_id
                or metadata["provider_id"] != attempt.provider_id
                or metadata["capability_id"] != attempt.capability_id
            ):
                raise _health_refusal(
                    assessment.digest,
                    f"F05 record {metadata['record_digest']} does not match F01 attempt "
                    f"{attempt_id}.",
                )
            result.append(
                ProviderHealthReference(
                    assessment_digest=assessment.digest,
                    attempt_id=attempt_id,
                    record_digest=str(metadata["record_digest"]),
                    scope_id=attempt.scope_id,
                    provider_id=attempt.provider_id,
                    capability_id=attempt.capability_id,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (scope_order[item.scope_id], item.attempt_id),
            )
        )

    def _persist(
        self,
        freeze: MatchweekMembershipFreeze,
        *,
        allow_creation_time_winner: bool,
    ) -> MatchweekMembershipFreeze:
        _validate_freeze_payload(freeze)
        existing = self.get_by_id(freeze.freeze_id)
        if existing is not None:
            if freeze_payload(existing, include_digest=True) == freeze_payload(
                freeze, include_digest=True
            ):
                return existing
            raise _identity_conflict(freeze.freeze_id)

        scopes = _requested_scopes(freeze.season, freeze.matchweek_friday)
        assessment = self._load_assessment(freeze.assessment_digest)
        _validate_assessment_gate(assessment, freeze.season, freeze.matchweek_friday, scopes)
        health_references = self._exact_health_references(assessment)
        expected_memberships = _build_memberships(
            self._store, assessment, freeze.freeze_id, freeze.policy
        )
        expected = _new_freeze(
            freeze_id=freeze.freeze_id,
            season=freeze.season,
            matchweek_friday=freeze.matchweek_friday,
            assessment=assessment,
            policy=freeze.policy,
            health_references=health_references,
            memberships=expected_memberships,
            created_at_utc=freeze.created_at_utc,
        )
        if freeze_payload(expected, include_digest=True) != freeze_payload(
            freeze, include_digest=True
        ):
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                "Proposed F06 payload does not match its exact F01, F05, and revision references.",
            )

        encoded = canonical_json(freeze_payload(freeze, include_digest=True))
        try:
            with self._store.transaction() as transaction:
                current = transaction.execute(
                    "SELECT freeze_json FROM v2_matchweek_membership_freezes WHERE freeze_id = ?",
                    (freeze.freeze_id,),
                ).fetchone()
                if current is not None:
                    winner = freeze_from_canonical_json(str(current[0]))
                    if freeze_payload(winner, include_digest=True) == freeze_payload(
                        freeze, include_digest=True
                    ) or (allow_creation_time_winner and _same_request_content(winner, freeze)):
                        return winner
                    raise _identity_conflict(freeze.freeze_id)
                transaction.execute(
                    """
                    INSERT INTO v2_matchweek_membership_freezes (
                        freeze_id, freeze_digest, freeze_json, contract_version, payload_version,
                        season, matchweek_friday, assessment_digest, schedule_state, policy_id,
                        policy_version, policy_digest, membership_set_digest, membership_count,
                        created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        freeze.freeze_id,
                        freeze.freeze_digest,
                        encoded,
                        freeze.contract_version,
                        freeze.payload_version,
                        freeze.season,
                        freeze.matchweek_friday,
                        freeze.assessment_digest,
                        freeze.schedule_state,
                        freeze.policy.policy_id,
                        freeze.policy.policy_version,
                        freeze.policy.digest,
                        freeze.membership_set_digest,
                        len(freeze.memberships),
                        freeze.created_at_utc,
                    ),
                )
                for membership in freeze.memberships:
                    transaction.execute(
                        """
                        INSERT INTO v2_matchweek_membership_decisions (
                            membership_id, freeze_id, scope_id, fixture_id, decision, reason_code,
                            controlling_revision_id, controlling_revision_digest,
                            membership_digest, decision_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            membership.membership_id,
                            freeze.freeze_id,
                            membership.scope_id,
                            membership.fixture_id,
                            membership.decision.value,
                            membership.reason_code,
                            membership.controlling_revision_id,
                            membership.controlling_revision_digest,
                            membership.membership_digest,
                            canonical_json(decision_payload(membership, include_digest=True)),
                        ),
                    )
                for reference in freeze.provider_health_references:
                    transaction.execute(
                        """
                        INSERT INTO v2_matchweek_membership_health_refs (
                            freeze_id, assessment_digest, attempt_id, record_digest,
                            scope_id, provider_id, capability_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            freeze.freeze_id,
                            reference.assessment_digest,
                            reference.attempt_id,
                            reference.record_digest,
                            reference.scope_id,
                            reference.provider_id,
                            reference.capability_id,
                        ),
                    )
            return freeze
        except sqlite3.IntegrityError as error:
            raise MatchweekMembershipPersistenceError(
                "MV-F06-PERSISTENCE-FAILED",
                "PERSISTENCE_FAILED",
                "F06 root and child rows could not be committed atomically.",
            ) from error

    def _validate_stored_children(self, freeze: MatchweekMembershipFreeze) -> None:
        connection = self._store._connection_for_repository()
        rows = connection.execute(
            """
            SELECT membership_id, scope_id, fixture_id, decision, reason_code,
                   controlling_revision_id, controlling_revision_digest,
                   membership_digest, decision_json
            FROM v2_matchweek_membership_decisions
            WHERE freeze_id = ? ORDER BY membership_id
            """,
            (freeze.freeze_id,),
        ).fetchall()
        expected_rows = tuple(
            (
                item.membership_id,
                item.scope_id,
                item.fixture_id,
                item.decision.value,
                item.reason_code,
                item.controlling_revision_id,
                item.controlling_revision_digest,
                item.membership_digest,
                canonical_json(decision_payload(item, include_digest=True)),
            )
            for item in sorted(freeze.memberships, key=lambda value: value.membership_id)
        )
        if tuple(tuple(row) for row in rows) != expected_rows:
            raise _stored_corruption(
                f"F06 membership rows for {freeze.freeze_id} differ from root."
            )
        health_rows = connection.execute(
            """
            SELECT assessment_digest, attempt_id, record_digest, scope_id, provider_id,
                   capability_id
            FROM v2_matchweek_membership_health_refs
            WHERE freeze_id = ? ORDER BY scope_id, attempt_id
            """,
            (freeze.freeze_id,),
        ).fetchall()
        expected_health = tuple(
            (
                item.assessment_digest,
                item.attempt_id,
                item.record_digest,
                item.scope_id,
                item.provider_id,
                item.capability_id,
            )
            for item in sorted(
                freeze.provider_health_references,
                key=lambda value: (value.scope_id, value.attempt_id),
            )
        )
        if tuple(tuple(row) for row in health_rows) != expected_health:
            raise _stored_corruption(f"F06 health rows for {freeze.freeze_id} differ from root.")

    def _validate_replay_references(self, freeze: MatchweekMembershipFreeze) -> None:
        scopes = _requested_scopes(freeze.season, freeze.matchweek_friday)
        assessment = self._load_assessment(freeze.assessment_digest)
        _validate_assessment_gate(assessment, freeze.season, freeze.matchweek_friday, scopes)
        if freeze.scopes != _scope_snapshots(assessment):
            raise _stored_corruption(
                f"F06 freeze {freeze.freeze_id} has changed F01 scope snapshots."
            )
        health_refs = self._exact_health_references(assessment)
        if health_refs != freeze.provider_health_references:
            raise _stored_corruption(
                f"F06 freeze {freeze.freeze_id} has missing, extra, or changed F05 references."
            )
        references = {item.revision_id: item for item in assessment.fixture_revisions}
        candidates: dict[tuple[str, str], set[str]] = defaultdict(set)
        expected_revisions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for identity in assessment.identity_resolutions:
            if identity.canonical_fixture_id is None:
                raise _stored_corruption("Frozen F01 assessment contains unresolved identity.")
            key = (identity.scope_id, identity.canonical_fixture_id)
            candidates[key].add(identity.candidate_id)
            expected_revisions[key].update(identity.revision_ids)
        if set(candidates) != {(item.scope_id, item.fixture_id) for item in freeze.memberships}:
            raise _stored_corruption("F06 membership groups differ from exact F01 identities.")
        for membership in freeze.memberships:
            if membership.scope_id not in {scope.scope_id for scope in scopes}:
                raise _stored_corruption("F06 membership points to an unknown Fixture Scope.")
            key = (membership.scope_id, membership.fixture_id)
            if (
                set(membership.candidate_ids) != candidates[key]
                or {item.revision_id for item in membership.evaluated_revisions}
                != expected_revisions[key]
            ):
                raise _stored_corruption(
                    f"F06 candidate or revision references for {membership.fixture_id} differ "
                    "from exact F01 identity links."
                )
            for snapshot in membership.evaluated_revisions:
                reference = references.get(snapshot.revision_id)
                if (
                    reference is None
                    or reference.scope_id != snapshot.scope_id
                    or reference.fixture_id != snapshot.fixture_id
                    or reference.revision_digest != snapshot.revision_digest
                ):
                    raise _stored_corruption(
                        f"F06 revision {snapshot.revision_id} is not in exact F01 assessment."
                    )
                _validate_revision_reference_rows(self._store, reference, snapshot)
            values_by_conflict = _validate_frozen_conflicts(
                self._store, membership.fixture_id, membership.conflicts
            )
            if _has_top_authority_revision_conflict(membership.evaluated_revisions):
                raise _stored_corruption(
                    f"F06 revision snapshots for {membership.fixture_id} contain a frozen "
                    "top-authority membership conflict."
                )
            if _has_top_authority_assertion_conflict(
                membership.conflicts, membership.evaluated_revisions, values_by_conflict
            ):
                raise _stored_corruption(
                    f"F06 conflict snapshots for {membership.fixture_id} contain a frozen "
                    "top-authority membership conflict."
                )
            _validate_stored_decision(membership, freeze.policy)


def _requested_scopes(season: str, matchweek_friday: str) -> tuple[FixtureScope, ...]:
    if not isinstance(season, str) or not season.strip():
        raise MatchweekMembershipError(
            "MV-F06-SCOPE-MISMATCH", "SCOPE_MISMATCH", "F06 season must be a nonempty exact value."
        )
    try:
        scopes = fixture_scopes_for_matchweek(matchweek_friday, season=season)
    except (TypeError, ValueError) as error:
        raise MatchweekMembershipError(
            "MV-F06-SCOPE-MISMATCH",
            "SCOPE_MISMATCH",
            f"F06 Matchweek Friday {matchweek_friday!r} is invalid.",
        ) from error
    if scopes[0].matchweek_friday != matchweek_friday:
        raise MatchweekMembershipError(
            "MV-F06-SCOPE-MISMATCH",
            "SCOPE_MISMATCH",
            "F06 Matchweek Friday must be the exact canonical YYYY-MM-DD value.",
        )
    return scopes


def _validate_assessment_gate(
    assessment: SupportedFixtureCoverageAssessment,
    season: str,
    friday: str,
    expected_scopes: tuple[FixtureScope, ...],
) -> None:
    if not assessment.scope_assessments:
        raise _scope_refusal(assessment.digest, "F01 assessment has no Fixture Scopes.")
    if len(assessment.scope_assessments) != 7:
        raise _scope_refusal(assessment.digest, "F01 assessment must have exactly seven scopes.")
    expected_by_id = {scope.scope_id: scope for scope in expected_scopes}
    actual_ids = tuple(item.scope.scope_id for item in assessment.scope_assessments)
    expected_ids = tuple(scope.scope_id for scope in expected_scopes)
    if actual_ids != expected_ids or len(set(actual_ids)) != 7:
        raise _scope_refusal(
            assessment.digest,
            f"F01 scope order or identity differs. Expected {expected_ids}; got {actual_ids}.",
        )
    unresolved = tuple(
        item.candidate_id
        for item in assessment.identity_resolutions
        if item.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
    )
    if unresolved:
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "IDENTITY_UNRESOLVED",
            f"F01 assessment {assessment.digest} has unresolved candidates {unresolved}.",
        )
    if any(item.identity_blocker_candidate_ids for item in assessment.scope_assessments):
        blocked = tuple(
            candidate_id
            for item in assessment.scope_assessments
            for candidate_id in item.identity_blocker_candidate_ids
        )
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "IDENTITY_UNRESOLVED",
            f"F01 assessment {assessment.digest} has identity blockers {blocked}.",
        )
    for item in assessment.scope_assessments:
        if item.scope != expected_by_id[item.scope.scope_id]:
            raise _scope_refusal(
                assessment.digest,
                f"F01 scope {item.scope.scope_id} has mismatched season, Friday, or bounds.",
            )
        if item.coverage_state not in (
            ScopeCoverageState.COMPLETE,
            ScopeCoverageState.CONFIRMED_EMPTY,
        ):
            raise MatchweekMembershipError(
                "MV-F06-ASSESSMENT-INCOMPLETE",
                "ASSESSMENT_INCOMPLETE",
                f"F01 assessment {assessment.digest} scope {item.scope.scope_id} is "
                f"{item.coverage_state.value}.",
            )
    if assessment.schedule_state not in (
        MatchweekScheduleState.COMPLETE,
        MatchweekScheduleState.CONFIRMED_EMPTY,
    ):
        raise MatchweekMembershipError(
            "MV-F06-ASSESSMENT-INCOMPLETE",
            "ASSESSMENT_INCOMPLETE",
            f"F01 assessment {assessment.digest} aggregate state is "
            f"{assessment.schedule_state.value}.",
        )
    all_empty = all(
        item.coverage_state is ScopeCoverageState.CONFIRMED_EMPTY
        for item in assessment.scope_assessments
    )
    expected_state = (
        MatchweekScheduleState.CONFIRMED_EMPTY if all_empty else MatchweekScheduleState.COMPLETE
    )
    if assessment.schedule_state is not expected_state:
        raise _scope_refusal(
            assessment.digest,
            "F01 aggregate schedule state conflicts with the seven persisted scope states.",
        )
    if assessment.scope_assessments[0].scope.season != season:
        raise _scope_refusal(assessment.digest, "F01 season does not match the explicit request.")
    if assessment.scope_assessments[0].scope.matchweek_friday != friday:
        raise _scope_refusal(assessment.digest, "F01 Friday does not match the explicit request.")


def _build_memberships(
    store: Store,
    assessment: SupportedFixtureCoverageAssessment,
    freeze_id: str,
    policy: PolicySnapshot,
) -> tuple[MembershipDecision, ...]:
    revision_references = {item.revision_id: item for item in assessment.fixture_revisions}
    grouped: dict[tuple[str, str], list[FixtureIdentityResolution]] = defaultdict(list)
    fixture_scopes: dict[str, str] = {}
    for identity in assessment.identity_resolutions:
        if (
            identity.state is not FixtureIdentityState.RESOLVED
            or identity.canonical_fixture_id is None
        ):
            raise MatchweekMembershipError(
                "MV-F06-UNRESOLVED-MEMBERSHIP",
                "IDENTITY_UNRESOLVED",
                f"F01 candidate {identity.candidate_id} has unresolved identity.",
            )
        fixture_id = identity.canonical_fixture_id
        prior_scope = fixture_scopes.setdefault(fixture_id, identity.scope_id)
        if prior_scope != identity.scope_id:
            raise _scope_refusal(
                assessment.digest,
                f"Canonical fixture {fixture_id} is assigned to scopes {prior_scope} and "
                f"{identity.scope_id}.",
            )
        grouped[(identity.scope_id, fixture_id)].append(identity)

    scope_order = {
        scope.scope_id: index
        for index, scope in enumerate(
            fixture_scopes_for_matchweek(
                assessment.scope_assessments[0].scope.matchweek_friday,
                season=assessment.scope_assessments[0].scope.season,
            )
        )
    }
    memberships: list[MembershipDecision] = []
    for (scope_id, fixture_id), identities in grouped.items():
        revision_ids = sorted(
            {revision_id for identity in identities for revision_id in identity.revision_ids}
        )
        if not revision_ids:
            raise MatchweekMembershipError(
                "MV-F06-UNRESOLVED-MEMBERSHIP",
                "CONTROLLING_REVISION_MISSING",
                f"Fixture {fixture_id} in scope {scope_id} has no exact F01 revision.",
            )
        snapshots: list[FixtureRevisionSnapshot] = []
        for revision_id in revision_ids:
            reference = revision_references.get(revision_id)
            if (
                reference is None
                or reference.scope_id != scope_id
                or reference.fixture_id != fixture_id
            ):
                raise MatchweekMembershipError(
                    "MV-F06-UNRESOLVED-MEMBERSHIP",
                    "CONTROLLING_REVISION_MISSING",
                    f"F01 candidate group for {fixture_id} references missing or mismatched "
                    f"revision {revision_id}.",
                )
            snapshots.append(_load_revision_snapshot(store, reference, assessment))
        snapshots.sort(key=lambda item: item.revision_id)
        _refuse_top_authority_conflict(store, fixture_id, snapshots)
        chosen = max(
            snapshots,
            key=lambda item: (
                item.authority_rank,
                datetime.fromisoformat(item.latest_support_retrieved_at_utc),
                item.revision_id,
                item.revision_digest,
            ),
        )
        conflicts = _load_exact_conflicts(store, fixture_id, snapshots)
        status_mapping = json.loads(policy.canonical_json)["status_mapping"]
        decision_state, reason_code = _decide_membership(chosen, status_mapping)
        extra_reasons = (
            ("MATERIAL_SOURCE_CONFLICT",)
            if any(item.predicate not in _MEMBERSHIP_CRITICAL_PREDICATES for item in conflicts)
            else ()
        )
        provisional = MembershipDecision(
            membership_id=membership_identity(freeze_id, scope_id, fixture_id),
            membership_digest="",
            scope_id=scope_id,
            fixture_id=fixture_id,
            candidate_ids=tuple(sorted(identity.candidate_id for identity in identities)),
            decision=decision_state,
            reason_code=reason_code,
            reason_codes=(reason_code, *extra_reasons),
            controlling_revision_id=chosen.revision_id,
            controlling_revision_digest=chosen.revision_digest,
            controlling_revision=chosen,
            evaluated_revisions=tuple(snapshots),
            conflicts=conflicts,
        )
        memberships.append(replace(provisional, membership_digest=membership_digest(provisional)))
    memberships.sort(key=lambda item: (scope_order[item.scope_id], item.fixture_id))
    return tuple(memberships)


_MEMBERSHIP_CRITICAL_PREDICATES = frozenset(
    {"kickoff", "home_team", "away_team", "competition", "status", "fixture_status"}
)


def _load_revision_snapshot(
    store: Store,
    reference: FixtureRevisionReference,
    assessment: SupportedFixtureCoverageAssessment,
) -> FixtureRevisionSnapshot:
    connection = store._connection_for_repository()
    row = connection.execute(
        """
        SELECT r.fixture_id, r.revision_digest, r.predecessor_revision_id,
               r.kickoff_state, r.kickoff_utc, r.kickoff_local_text, r.kickoff_precision,
               r.fixture_status, f.identity_state, league.league_key, season.season_label,
               r.observed_at_utc
        FROM fixture_revisions AS r
        JOIN fixtures AS f ON f.fixture_id = r.fixture_id
        JOIN target_leagues AS league ON league.league_id = f.league_id
        JOIN competition_seasons AS season ON season.season_id = f.season_id
        WHERE r.revision_id = ?
        """,
        (reference.revision_id,),
    ).fetchone()
    if row is None:
        raise MatchweekMembershipError(
            "MV-F06-REFERENCE-INTEGRITY",
            "REFERENCE_MISSING",
            f"Exact F01 Fixture Revision {reference.revision_id} is missing.",
        )
    if (
        str(row[0]) != reference.fixture_id
        or str(row[1]) != reference.revision_digest
        or str(row[8]) != "CONFIRMED"
        or str(row[9]) != _league_for_scope(assessment, reference.scope_id)
        or str(row[10]) != assessment.scope_assessments[0].scope.season
    ):
        raise MatchweekMembershipError(
            "MV-F06-REFERENCE-INTEGRITY",
            "REFERENCE_MISMATCH",
            f"F01 Fixture Revision {reference.revision_id} has a mismatched identity or scope.",
        )

    attempts = {
        item.capture_id: item.capture_digest
        for item in assessment.provider_attempts
        if item.capture_id is not None
    }
    capture_supports: list[AuthoritySupportSnapshot] = []
    for capture_id in reference.source_capture_ids:
        capture = connection.execute(
            """
            SELECT capture.content_sha256, capture.retrieved_at_utc,
                   identity.source_key, identity.source_class
            FROM source_captures AS capture
            JOIN source_identities AS identity ON identity.source_id = capture.source_id
            WHERE capture.capture_id = ?
            """,
            (capture_id,),
        ).fetchone()
        if capture is None:
            raise MatchweekMembershipError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_MISMATCH",
                f"F01 capture {capture_id} for revision {reference.revision_id} is missing or "
                "mismatched.",
            )
        if capture_id in attempts:
            if attempts[capture_id] != str(capture[0]):
                raise MatchweekMembershipError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_MISMATCH",
                    f"F01 capture {capture_id} for revision {reference.revision_id} is missing or "
                    "mismatched.",
                )
        else:
            try:
                manual_observation = verify_operator_fixture_observation_capture(
                    store,
                    capture_id,
                    expected_scope_id=reference.scope_id,
                )
            except OperatorFixtureObservationIntegrityError as error:
                raise MatchweekMembershipError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_MISMATCH",
                    f"F01 capture {capture_id} for revision {reference.revision_id} is missing or "
                    "mismatched.",
                ) from error
            if (
                manual_observation.capture_id != capture_id
                or manual_observation.artifact_digest != str(capture[0])
                or manual_observation.fixture_id != reference.fixture_id
                or manual_observation.revision_id != reference.revision_id
            ):
                raise MatchweekMembershipError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_MISMATCH",
                    f"F01 capture {capture_id} for revision {reference.revision_id} is missing or "
                    "mismatched.",
                )
        source_key = str(capture[2])
        source_class = str(capture[3])
        capture_supports.append(
            AuthoritySupportSnapshot(
                capture_id=capture_id,
                capture_digest=str(capture[0]),
                assertion_id=None,
                retrieved_at_utc=_canonical_utc(str(capture[1])),
                source_key=source_key,
                source_class=source_class,
                authority_rank=_authority_rank(source_key, source_class),
            )
        )
    assertion_supports: list[AuthoritySupportSnapshot] = []
    for assertion_id in reference.source_assertion_ids:
        assertion = connection.execute(
            """
            SELECT capture.capture_id, capture.content_sha256, capture.retrieved_at_utc,
                   identity.source_key, identity.source_class
            FROM source_assertions AS assertion
            JOIN source_captures AS capture ON capture.capture_id = assertion.capture_id
            JOIN source_identities AS identity ON identity.source_id = capture.source_id
            JOIN fixture_revision_assertions AS link
              ON link.assertion_id = assertion.assertion_id
            WHERE assertion.assertion_id = ? AND link.revision_id = ?
            """,
            (assertion_id, reference.revision_id),
        ).fetchone()
        if assertion is None or str(assertion[0]) not in reference.source_capture_ids:
            raise MatchweekMembershipError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_MISMATCH",
                f"F01 assertion {assertion_id} for revision {reference.revision_id} is missing "
                "or mismatched.",
            )
        source_key = str(assertion[3])
        source_class = str(assertion[4])
        assertion_supports.append(
            AuthoritySupportSnapshot(
                capture_id=str(assertion[0]),
                capture_digest=str(assertion[1]),
                assertion_id=assertion_id,
                retrieved_at_utc=_canonical_utc(str(assertion[2])),
                source_key=source_key,
                source_class=source_class,
                authority_rank=_authority_rank(source_key, source_class),
            )
        )
    supports = tuple(
        sorted(
            (*capture_supports, *assertion_supports),
            key=lambda item: (
                item.retrieved_at_utc,
                item.source_class,
                item.source_key,
                item.capture_id,
                item.assertion_id or "",
            ),
        )
    )
    if not supports:
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "CONTROLLING_REVISION_MISSING",
            f"Fixture Revision {reference.revision_id} has no exact authority support.",
        )
    return FixtureRevisionSnapshot(
        scope_id=reference.scope_id,
        fixture_id=reference.fixture_id,
        revision_id=reference.revision_id,
        revision_digest=reference.revision_digest,
        predecessor_revision_id=str(row[2]) if row[2] is not None else None,
        kickoff_state=str(row[3]),
        kickoff_utc=str(row[4]) if row[4] is not None else None,
        kickoff_local_text=str(row[5]) if row[5] is not None else None,
        kickoff_precision=str(row[6]),
        fixture_status=str(row[7]),
        source_capture_ids=reference.source_capture_ids,
        source_assertion_ids=reference.source_assertion_ids,
        supports=supports,
        authority_rank=max(item.authority_rank for item in supports),
        latest_support_retrieved_at_utc=max(item.retrieved_at_utc for item in supports),
    )


def _league_for_scope(assessment: SupportedFixtureCoverageAssessment, scope_id: str) -> str:
    for item in assessment.scope_assessments:
        if item.scope.scope_id == scope_id:
            return item.scope.league_key
    return ""


def _refuse_top_authority_conflict(
    store: Store,
    fixture_id: str,
    snapshots: list[FixtureRevisionSnapshot],
) -> None:
    best_rank = max(item.authority_rank for item in snapshots)
    top = [item for item in snapshots if item.authority_rank == best_rank]
    latest = max(item.latest_support_retrieved_at_utc for item in top)
    controlling_tier = [item for item in top if item.latest_support_retrieved_at_utc == latest]
    values = {_membership_critical_facts(item) for item in controlling_tier}
    conflicts = _load_exact_conflicts(store, fixture_id, snapshots)
    exact_conflicts = _top_conflicting_assertions(store, fixture_id, snapshots)
    if len(values) > 1 or exact_conflicts:
        details = tuple(item.conflict_id for item in conflicts)
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "MEMBERSHIP_CONFLICT",
            f"Top-authority F01 evidence conflicts on membership facts for fixture {fixture_id}; "
            f"conflicts {details}.",
        )


def _membership_critical_facts(snapshot: FixtureRevisionSnapshot) -> tuple[str, str | None]:
    status = snapshot.fixture_status.strip().upper()
    if status in {"SCHEDULED", "CONFIRMED"}:
        status_class = "SCHEDULED"
        kickoff = snapshot.kickoff_utc if snapshot.kickoff_state == "OBSERVED" else None
    elif status == "POSTPONED":
        status_class, kickoff = "POSTPONED", None
    elif status in {"CANCELLED", "CANCELED"}:
        status_class, kickoff = "CANCELLED", None
    else:
        status_class, kickoff = "NOT_SCHEDULED", None
    return status_class, kickoff


def _load_exact_conflicts(
    store: Store,
    fixture_id: str,
    snapshots: list[FixtureRevisionSnapshot] | tuple[FixtureRevisionSnapshot, ...],
) -> tuple[ConflictSnapshot, ...]:
    assertion_ids = tuple(
        sorted(
            {
                assertion_id
                for snapshot in snapshots
                for assertion_id in snapshot.source_assertion_ids
            }
        )
    )
    if not assertion_ids:
        return ()
    placeholders = ",".join("?" for _ in assertion_ids)
    connection = store._connection_for_repository()
    rows = connection.execute(
        f"""
        SELECT assertion.assertion_id, assertion.predicate, assertion.normalized_value_json
        FROM source_assertions AS assertion
        WHERE assertion.subject_kind = 'FIXTURE'
          AND assertion.subject_key = ?
          AND assertion.evidence_state = 'OBSERVED'
          AND assertion.normalized_value_json IS NOT NULL
          AND assertion.assertion_id IN ({placeholders})
        ORDER BY assertion.predicate, assertion.assertion_id
        """,
        (fixture_id, *assertion_ids),
    ).fetchall()
    by_predicate: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        by_predicate[str(row[1])][str(row[0])] = str(row[2])

    conflict_snapshots: list[ConflictSnapshot] = []
    for predicate, assertion_values in sorted(by_predicate.items()):
        values = tuple(sorted(set(assertion_values.values())))
        if len(values) < 2:
            continue
        value_digest = hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()
        conflict = connection.execute(
            """
            SELECT conflict_id FROM conflict_sets
            WHERE subject_kind = 'FIXTURE' AND subject_key = ? AND predicate = ?
              AND value_digest = ? AND status = 'UNRESOLVED'
            """,
            (fixture_id, predicate, value_digest),
        ).fetchone()
        if conflict is None:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_CORRUPT",
                f"F06 exact assertions for fixture {fixture_id} conflict on {predicate}, "
                "but their immutable conflict record is missing.",
            )
        conflict_id = str(conflict[0])
        linked_ids = {
            str(row[0])
            for row in connection.execute(
                f"""
                SELECT assertion_id FROM conflict_assertions
                WHERE conflict_id = ? AND assertion_id IN ({placeholders})
                """,
                (conflict_id, *assertion_ids),
            ).fetchall()
        }
        exact_values = {
            assertion_id: value
            for assertion_id, value in assertion_values.items()
            if assertion_id in linked_ids
        }
        conflict_values = tuple(sorted(set(exact_values.values())))
        if conflict_values != values:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_CORRUPT",
                f"F06 exact conflict record {conflict_id} omits source assertions for "
                f"fixture {fixture_id} predicate {predicate}.",
            )
        conflict_snapshots.append(
            ConflictSnapshot(
                conflict_id=conflict_id,
                predicate=predicate,
                value_digest=value_digest,
                assertion_ids=tuple(sorted(exact_values)),
                values=conflict_values,
            )
        )
    return tuple(conflict_snapshots)


def _validate_frozen_conflicts(
    store: Store,
    fixture_id: str,
    conflicts: tuple[ConflictSnapshot, ...],
) -> dict[str, dict[str, str]]:
    """Validate only conflict evidence named by the freeze, ignoring later links."""
    connection = store._connection_for_repository()
    values_by_conflict: dict[str, dict[str, str]] = {}
    for conflict in conflicts:
        if (
            conflict.conflict_id in values_by_conflict
            or not conflict.assertion_ids
            or tuple(sorted(set(conflict.assertion_ids))) != conflict.assertion_ids
            or tuple(sorted(set(conflict.values))) != conflict.values
        ):
            raise _stored_corruption("F06 frozen conflict snapshot is malformed or duplicated.")
        row = connection.execute(
            """
            SELECT subject_kind, subject_key, predicate, value_digest, status
            FROM conflict_sets WHERE conflict_id = ?
            """,
            (conflict.conflict_id,),
        ).fetchone()
        if row is None or tuple(row) != (
            "FIXTURE",
            fixture_id,
            conflict.predicate,
            conflict.value_digest,
            "UNRESOLVED",
        ):
            raise MatchweekMembershipIntegrityError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_CORRUPT",
                f"F06 conflict {conflict.conflict_id} is missing or has changed immutable facts.",
            )
        assertion_values: dict[str, str] = {}
        for assertion_id in conflict.assertion_ids:
            assertion = connection.execute(
                """
                SELECT assertion.normalized_value_json
                FROM conflict_assertions AS member
                JOIN source_assertions AS assertion ON assertion.assertion_id = member.assertion_id
                WHERE member.conflict_id = ? AND member.assertion_id = ?
                """,
                (conflict.conflict_id, assertion_id),
            ).fetchone()
            if assertion is None:
                raise MatchweekMembershipIntegrityError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_CORRUPT",
                    f"F06 conflict {conflict.conflict_id} lost assertion {assertion_id}.",
                )
            if assertion[0] is not None:
                assertion_values[assertion_id] = str(assertion[0])
        if tuple(sorted(set(assertion_values.values()))) != conflict.values:
            raise _stored_corruption(
                f"F06 conflict {conflict.conflict_id} values differ from their frozen snapshot."
            )
        values_by_conflict[conflict.conflict_id] = assertion_values
    return values_by_conflict


def _has_top_authority_revision_conflict(
    snapshots: tuple[FixtureRevisionSnapshot, ...],
) -> bool:
    if not snapshots:
        return True
    best_rank = max(item.authority_rank for item in snapshots)
    top = [item for item in snapshots if item.authority_rank == best_rank]
    latest = max(item.latest_support_retrieved_at_utc for item in top)
    controlling_tier = [item for item in top if item.latest_support_retrieved_at_utc == latest]
    return len({_membership_critical_facts(item) for item in controlling_tier}) > 1


def _has_top_authority_assertion_conflict(
    conflicts: tuple[ConflictSnapshot, ...],
    snapshots: tuple[FixtureRevisionSnapshot, ...],
    values_by_conflict: Mapping[str, Mapping[str, str]],
) -> bool:
    support_by_assertion = {
        support.assertion_id: support
        for snapshot in snapshots
        for support in snapshot.supports
        if support.assertion_id is not None
    }
    for conflict in conflicts:
        if conflict.predicate not in _MEMBERSHIP_CRITICAL_PREDICATES:
            continue
        values = values_by_conflict.get(conflict.conflict_id, {})
        evidence = [
            (support_by_assertion[assertion_id], value)
            for assertion_id, value in values.items()
            if assertion_id in support_by_assertion
        ]
        if not evidence:
            continue
        top_key = max((support.authority_rank, support.retrieved_at_utc) for support, _ in evidence)
        latest_values = {
            value
            for support, value in evidence
            if (support.authority_rank, support.retrieved_at_utc) == top_key
        }
        if len(latest_values) > 1:
            return True
    return False


def _top_conflicting_assertions(
    store: Store,
    fixture_id: str,
    snapshots: list[FixtureRevisionSnapshot],
) -> tuple[str, ...]:
    conflicts = _load_exact_conflicts(store, fixture_id, snapshots)
    critical = [item for item in conflicts if item.predicate in _MEMBERSHIP_CRITICAL_PREDICATES]
    if not critical:
        return ()
    support_by_assertion = {
        support.assertion_id: support
        for snapshot in snapshots
        for support in snapshot.supports
        if support.assertion_id is not None
    }
    connection = store._connection_for_repository()
    conflicting: list[str] = []
    for conflict in critical:
        values_by_assertion = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                """
                SELECT assertion.assertion_id, assertion.normalized_value_json
                FROM conflict_assertions AS member
                JOIN conflict_sets AS conflict ON conflict.conflict_id = member.conflict_id
                JOIN source_assertions AS assertion ON assertion.assertion_id = member.assertion_id
                WHERE conflict.conflict_id = ?
                  AND conflict.subject_kind = 'FIXTURE'
                  AND conflict.subject_key = ?
                  AND assertion.assertion_id IN (
                      SELECT json_each.value FROM json_each(?)
                  )
                """,
                (
                    conflict.conflict_id,
                    fixture_id,
                    canonical_json(list(conflict.assertion_ids)),
                ),
            ).fetchall()
            if row[1] is not None
        }
        evidence = [
            (support_by_assertion[assertion_id], value)
            for assertion_id, value in values_by_assertion.items()
            if assertion_id in support_by_assertion
        ]
        if not evidence:
            continue
        top_key = max((support.authority_rank, support.retrieved_at_utc) for support, _ in evidence)
        latest_values = {
            value
            for support, value in evidence
            if (support.authority_rank, support.retrieved_at_utc) == top_key
        }
        if len(latest_values) > 1:
            conflicting.append(conflict.conflict_id)
    return tuple(conflicting)


def _decide_membership(
    revision: FixtureRevisionSnapshot,
    status_mapping: Mapping[str, object],
) -> tuple[MembershipState, str]:
    status = revision.fixture_status.strip().upper()
    scheduled = set(cast(list[str], status_mapping["scheduled"]))
    postponed = set(cast(list[str], status_mapping["postponed"]))
    cancelled = set(cast(list[str], status_mapping["cancelled"]))
    not_scheduled = set(cast(list[str], status_mapping["not_scheduled"]))
    unknown = set(cast(list[str], status_mapping["unknown"]))
    if status in postponed:
        return MembershipState.EXCLUDED, "POSTPONED"
    if status in cancelled:
        return MembershipState.EXCLUDED, "CANCELLED"
    if status in unknown or status not in scheduled | not_scheduled:
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "STATUS_UNKNOWN",
            f"Fixture Revision {revision.revision_id} has unsupported status {status!r}.",
        )
    if status in not_scheduled:
        return MembershipState.EXCLUDED, "NOT_SCHEDULED"
    if revision.kickoff_state != EvidenceState.OBSERVED.value or revision.kickoff_utc is None:
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "KICKOFF_UNKNOWN",
            f"Scheduled Fixture Revision {revision.revision_id} has no observed kickoff.",
        )
    try:
        kickoff = datetime.fromisoformat(revision.kickoff_utc)
        in_window = MatchweekWindow.for_friday(_friday_from_scope_id(revision.scope_id)).contains(
            kickoff
        )
    except (TypeError, ValueError) as error:
        raise MatchweekMembershipError(
            "MV-F06-UNRESOLVED-MEMBERSHIP",
            "KICKOFF_UNKNOWN",
            f"Fixture Revision {revision.revision_id} has malformed kickoff evidence.",
        ) from error
    if in_window:
        return MembershipState.INCLUDED, "IN_WINDOW_SCHEDULED"
    return MembershipState.EXCLUDED, "OUTSIDE_MATCHWEEK_WINDOW"


def _friday_from_scope_id(scope_id: str) -> str:
    parts = scope_id.rsplit(":", 2)
    if len(parts) != 3:
        raise ValueError("Fixture Scope ID is malformed.")
    return parts[2]


def _new_freeze(
    *,
    freeze_id: str,
    season: str,
    matchweek_friday: str,
    assessment: SupportedFixtureCoverageAssessment,
    policy: PolicySnapshot,
    health_references: tuple[ProviderHealthReference, ...],
    memberships: tuple[MembershipDecision, ...],
    created_at_utc: str,
) -> MatchweekMembershipFreeze:
    scope_snapshots = _scope_snapshots(assessment)
    provisional = MatchweekMembershipFreeze(
        freeze_id=freeze_id,
        freeze_digest="sha256:" + "0" * 64,
        contract_version=F06_CONTRACT_VERSION,
        payload_version=F06_PAYLOAD_VERSION,
        season=season,
        matchweek_friday=matchweek_friday,
        assessment_digest=assessment.digest,
        schedule_state=assessment.schedule_state.value,
        policy=policy,
        scopes=scope_snapshots,
        provider_health_references=health_references,
        memberships=memberships,
        membership_set_digest=membership_set_digest(memberships),
        created_at_utc=created_at_utc,
    )
    return replace(provisional, freeze_digest=freeze_digest(provisional))


def _scope_snapshots(
    assessment: SupportedFixtureCoverageAssessment,
) -> tuple[ScopeSnapshot, ...]:
    return tuple(
        ScopeSnapshot(
            scope_id=item.scope.scope_id,
            league_key=item.scope.league_key,
            season=item.scope.season,
            matchweek_friday=item.scope.matchweek_friday,
            coverage_state=item.coverage_state.value,
            window_start_utc=item.scope.window_start_utc,
            window_end_utc=item.scope.window_end_utc,
        )
        for item in assessment.scope_assessments
    )


def _validate_observation_matchweek(
    freeze: MatchweekMembershipFreeze,
    assessment: SupportedFixtureCoverageAssessment,
) -> None:
    scope = assessment.scope_assessments[0].scope
    if assessment.digest == freeze.assessment_digest:
        raise MatchweekMembershipError(
            "MV-F06-SCOPE-MISMATCH",
            "OBSERVATION_NOT_LATER",
            "F06 observation must name an F01 assessment distinct from the frozen assessment.",
        )
    if (scope.season, scope.matchweek_friday) != (freeze.season, freeze.matchweek_friday):
        raise MatchweekMembershipError(
            "MV-F06-SCOPE-MISMATCH",
            "SCOPE_MISMATCH",
            f"Later F01 assessment {assessment.digest} does not match freeze "
            f"{freeze.freeze_id} season and Friday.",
        )


def _build_observation_changes(
    store: Store,
    freeze: MatchweekMembershipFreeze,
    assessment: SupportedFixtureCoverageAssessment,
) -> tuple[MembershipObservationChange, ...]:
    original_assessment = FixtureCoverageRepository(store).get(freeze.assessment_digest)
    if original_assessment is None:
        raise _stored_corruption("F06 observation source freeze has a missing F01 assessment.")
    original_candidate_ids = {
        item.candidate_id for item in original_assessment.identity_resolutions
    }
    original_revisions: dict[tuple[str, str], set[str]] = defaultdict(set)
    original_memberships: dict[tuple[str, str], MembershipDecision] = {}
    for membership in freeze.memberships:
        key = (membership.scope_id, membership.fixture_id)
        original_memberships[key] = membership
        original_revisions[key].update(item.revision_id for item in membership.evaluated_revisions)

    revision_references = {item.revision_id: item for item in assessment.fixture_revisions}
    grouped: dict[tuple[str, str], list[FixtureIdentityResolution]] = defaultdict(list)
    for identity in assessment.identity_resolutions:
        if (
            identity.state is FixtureIdentityState.RESOLVED
            and identity.canonical_fixture_id is not None
        ):
            grouped[(identity.scope_id, identity.canonical_fixture_id)].append(identity)

    generated: list[MembershipObservationChange] = []
    status_mapping = json.loads(freeze.policy.canonical_json)["status_mapping"]
    for key, identities in grouped.items():
        scope_id, fixture_id = key
        revision_ids = sorted(
            {revision_id for identity in identities for revision_id in identity.revision_ids}
        )
        snapshots: list[FixtureRevisionSnapshot] = []
        for revision_id in revision_ids:
            reference = revision_references.get(revision_id)
            if (
                reference is None
                or reference.scope_id != scope_id
                or reference.fixture_id != fixture_id
            ):
                raise MatchweekMembershipIntegrityError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_MISMATCH",
                    f"Later F01 identity for {fixture_id} references missing revision "
                    f"{revision_id}.",
                )
            snapshots.append(_load_revision_snapshot(store, reference, assessment))
        snapshots.sort(key=lambda item: item.revision_id)
        if not snapshots:
            continue

        old = original_memberships.get(key)
        old_revision_ids = original_revisions[key]
        codes: set[ObservationCode] = set()
        candidate_ids = tuple(sorted(identity.candidate_id for identity in identities))
        if any(candidate_id not in original_candidate_ids for candidate_id in candidate_ids):
            codes.add(ObservationCode.IDENTITY_RESOLVED)
        if any(item.revision_id not in old_revision_ids for item in snapshots):
            codes.add(ObservationCode.REVISION_OBSERVED)

        conflicts = _load_exact_conflicts(store, fixture_id, snapshots)
        if conflicts:
            codes.add(ObservationCode.SOURCE_CONFLICT)

        old_revision = old.controlling_revision if old is not None else None
        old_in_window = old is not None and old.reason_code == "IN_WINDOW_SCHEDULED"
        for snapshot in snapshots:
            status = snapshot.fixture_status.strip().upper()
            if status in set(cast(list[str], status_mapping["postponed"])):
                codes.add(ObservationCode.POSTPONED)
            elif status in set(cast(list[str], status_mapping["cancelled"])):
                codes.add(ObservationCode.CANCELLED)

            scheduled = status in set(cast(list[str], status_mapping["scheduled"]))
            if (
                not scheduled
                or snapshot.kickoff_state != EvidenceState.OBSERVED.value
                or snapshot.kickoff_utc is None
            ):
                continue
            try:
                kickoff = datetime.fromisoformat(snapshot.kickoff_utc)
                new_in_window = MatchweekWindow.for_friday(freeze.matchweek_friday).contains(
                    kickoff
                )
            except TypeError, ValueError:
                continue
            if old is None:
                if new_in_window:
                    codes.add(ObservationCode.ADDED_IN_WINDOW)
                continue
            if new_in_window and not old_in_window:
                codes.add(ObservationCode.MOVED_IN)
            elif old_in_window and not new_in_window:
                codes.add(ObservationCode.MOVED_OUT)
            if old_revision is not None and old_revision.kickoff_utc != snapshot.kickoff_utc:
                if old_in_window and new_in_window:
                    codes.add(ObservationCode.KICKOFF_CORRECTED)
                else:
                    codes.add(ObservationCode.RESCHEDULED)

        if not codes:
            continue
        facts: tuple[tuple[str, str | None], ...] = tuple(
            sorted(
                (
                    ("later_kickoffs", canonical_json([item.kickoff_utc for item in snapshots])),
                    ("later_statuses", canonical_json([item.fixture_status for item in snapshots])),
                    ("original_kickoff", old_revision.kickoff_utc if old_revision else None),
                    ("original_membership", old.decision.value if old else None),
                    ("conflict_ids", canonical_json([item.conflict_id for item in conflicts])),
                )
            )
        )
        capture_ids = tuple(
            sorted({capture_id for item in snapshots for capture_id in item.source_capture_ids})
        )
        assertion_ids = tuple(
            sorted(
                {assertion_id for item in snapshots for assertion_id in item.source_assertion_ids}
            )
        )
        for code in sorted(codes, key=lambda item: item.value):
            generated.append(
                MembershipObservationChange(
                    change_code=code,
                    scope_id=scope_id,
                    fixture_id=fixture_id,
                    candidate_ids=candidate_ids,
                    revision_ids=tuple(item.revision_id for item in snapshots),
                    revision_digests=tuple(item.revision_digest for item in snapshots),
                    source_capture_ids=capture_ids,
                    source_assertion_ids=assertion_ids,
                    facts=facts,
                )
            )

    scope_order = {item.scope_id: index for index, item in enumerate(_scope_snapshots(assessment))}
    generated.sort(
        key=lambda item: (
            scope_order[item.scope_id],
            item.fixture_id,
            item.change_code.value,
            item.candidate_ids,
            item.revision_ids,
        )
    )
    return tuple(generated)


def _validate_freeze_payload(freeze: MatchweekMembershipFreeze) -> None:
    expected_policy = policy_snapshot(freeze.policy.policy_id, freeze.policy.policy_version)
    if freeze.policy != expected_policy:
        raise MatchweekMembershipIntegrityError(
            "MV-F06-PAYLOAD-CORRUPT",
            "PAYLOAD_CORRUPT",
            "F06 policy snapshot does not match its supported policy identity.",
        )
    if freeze.freeze_id != freeze_identity(
        freeze.season, freeze.matchweek_friday, freeze.assessment_digest, freeze.policy
    ):
        raise MatchweekMembershipIntegrityError(
            "MV-F06-IDENTITY-CONFLICT",
            "IDENTITY_CONFLICT",
            "F06 freeze ID does not match the exact requested identity.",
        )
    if freeze.membership_set_digest != membership_set_digest(freeze.memberships):
        raise MatchweekMembershipIntegrityError(
            "MV-F06-PAYLOAD-CORRUPT",
            "PAYLOAD_CORRUPT",
            "F06 membership-set digest does not match its ordered decisions.",
        )
    if freeze.freeze_digest != freeze_digest(freeze):
        raise MatchweekMembershipIntegrityError(
            "MV-F06-PAYLOAD-CORRUPT",
            "PAYLOAD_CORRUPT",
            "F06 freeze digest does not match its complete immutable payload.",
        )
    for item in freeze.memberships:
        if item.membership_id != membership_identity(
            freeze.freeze_id, item.scope_id, item.fixture_id
        ):
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                f"F06 membership ID for fixture {item.fixture_id} is invalid.",
            )
        if item.membership_digest != membership_digest(item):
            raise MatchweekMembershipIntegrityError(
                "MV-F06-PAYLOAD-CORRUPT",
                "PAYLOAD_CORRUPT",
                f"F06 membership digest for fixture {item.fixture_id} is invalid.",
            )


def _validate_stored_decision(decision: MembershipDecision, policy: PolicySnapshot) -> None:
    if decision.controlling_revision_id != decision.controlling_revision.revision_id:
        raise _stored_corruption("F06 controlling revision ID differs from its snapshot.")
    if decision.controlling_revision_digest != decision.controlling_revision.revision_digest:
        raise _stored_corruption("F06 controlling revision digest differs from its snapshot.")
    for snapshot in decision.evaluated_revisions:
        if not snapshot.supports:
            raise _stored_corruption("F06 authority snapshot has no source support.")
        if snapshot.authority_rank != max(item.authority_rank for item in snapshot.supports):
            raise _stored_corruption("F06 stored authority rank differs from its source snapshot.")
        if snapshot.latest_support_retrieved_at_utc != max(
            item.retrieved_at_utc for item in snapshot.supports
        ):
            raise _stored_corruption("F06 stored support retrieval time is corrupt.")
        for support in snapshot.supports:
            if support.authority_rank != _authority_rank(support.source_key, support.source_class):
                raise _stored_corruption("F06 stored source authority snapshot is corrupt.")
    expected_controller = max(
        decision.evaluated_revisions,
        key=lambda item: (
            item.authority_rank,
            datetime.fromisoformat(item.latest_support_retrieved_at_utc),
            item.revision_id,
            item.revision_digest,
        ),
        default=None,
    )
    if expected_controller is None or expected_controller != decision.controlling_revision:
        raise _stored_corruption("F06 controller does not follow its stored authority snapshots.")
    status_mapping = json.loads(policy.canonical_json)["status_mapping"]
    expected_state, expected_reason = _decide_membership(expected_controller, status_mapping)
    if decision.decision is not expected_state or decision.reason_code != expected_reason:
        raise _stored_corruption("F06 frozen membership differs from its stored revision facts.")
    extra_reasons = (
        ("MATERIAL_SOURCE_CONFLICT",)
        if any(item.predicate not in _MEMBERSHIP_CRITICAL_PREDICATES for item in decision.conflicts)
        else ()
    )
    if decision.reason_codes != (decision.reason_code, *extra_reasons):
        raise _stored_corruption("F06 decision reason annotations differ from its conflict facts.")


def _validate_revision_reference_rows(
    store: Store,
    reference: FixtureRevisionReference,
    snapshot: FixtureRevisionSnapshot,
) -> None:
    connection = store._connection_for_repository()
    revision = connection.execute(
        """
        SELECT fixture_id, revision_digest, source_capture_id, kickoff_state, kickoff_utc,
               kickoff_local_text, kickoff_precision, fixture_status, predecessor_revision_id
        FROM fixture_revisions WHERE revision_id = ?
        """,
        (reference.revision_id,),
    ).fetchone()
    if revision is None or (
        str(revision[0]) != snapshot.fixture_id
        or str(revision[1]) != snapshot.revision_digest
        or str(revision[3]) != snapshot.kickoff_state
        or (None if revision[4] is None else str(revision[4])) != snapshot.kickoff_utc
        or (None if revision[5] is None else str(revision[5])) != snapshot.kickoff_local_text
        or str(revision[6]) != snapshot.kickoff_precision
        or str(revision[7]) != snapshot.fixture_status
        or (None if revision[8] is None else str(revision[8])) != snapshot.predecessor_revision_id
    ):
        raise MatchweekMembershipIntegrityError(
            "MV-F06-REFERENCE-INTEGRITY",
            "REFERENCE_CORRUPT",
            f"F06 revision {snapshot.revision_id} is missing or its immutable facts changed.",
        )
    if (
        reference.scope_id != snapshot.scope_id
        or reference.fixture_id != snapshot.fixture_id
        or reference.revision_digest != snapshot.revision_digest
        or tuple(reference.source_capture_ids) != snapshot.source_capture_ids
        or tuple(reference.source_assertion_ids) != snapshot.source_assertion_ids
    ):
        raise _stored_corruption(f"F06 revision {snapshot.revision_id} differs from F01.")
    if set(snapshot.source_capture_ids) != {item.capture_id for item in snapshot.supports}:
        raise _stored_corruption("F06 authority snapshot omitted or added an F01 source capture.")
    support_assertions = {
        item.assertion_id for item in snapshot.supports if item.assertion_id is not None
    }
    if support_assertions != set(snapshot.source_assertion_ids):
        raise _stored_corruption("F06 authority snapshot omitted an F01 source assertion.")
    for support in snapshot.supports:
        capture = connection.execute(
            "SELECT content_sha256, retrieved_at_utc FROM source_captures WHERE capture_id = ?",
            (support.capture_id,),
        ).fetchone()
        if capture is None or str(capture[0]) != support.capture_digest:
            raise MatchweekMembershipIntegrityError(
                "MV-F06-REFERENCE-INTEGRITY",
                "REFERENCE_CORRUPT",
                f"F06 source capture {support.capture_id} is missing or has a digest mismatch.",
            )
        if _canonical_utc(str(capture[1])) != support.retrieved_at_utc:
            raise _stored_corruption("F06 source capture retrieval time differs from its snapshot.")
        if support.assertion_id is not None:
            assertion = connection.execute(
                """
                SELECT capture_id FROM source_assertions WHERE assertion_id = ?
                """,
                (support.assertion_id,),
            ).fetchone()
            if assertion is None or str(assertion[0]) != support.capture_id:
                raise MatchweekMembershipIntegrityError(
                    "MV-F06-REFERENCE-INTEGRITY",
                    "REFERENCE_CORRUPT",
                    f"F06 source assertion {support.assertion_id} is missing or mismatched.",
                )


def _validate_root_row(freeze: MatchweekMembershipFreeze, row: tuple[object, ...]) -> None:
    expected = (
        freeze.freeze_digest,
        freeze.season,
        freeze.matchweek_friday,
        freeze.assessment_digest,
        freeze.policy.policy_id,
        freeze.policy.policy_version,
        freeze.policy.digest,
        freeze.schedule_state,
        freeze.membership_set_digest,
        len(freeze.memberships),
        freeze.created_at_utc,
    )
    actual = tuple(row[1:])
    if actual != expected:
        raise _stored_corruption(
            f"F06 root columns for {freeze.freeze_id} differ from its payload."
        )


def _health_attempt_id(record: ProviderHealthRecord) -> str:
    values = tuple(
        reference.attempt_id
        for reference in record.provenance
        if isinstance(reference, ProviderAttemptReference)
    )
    if len(values) != 1:
        raise ProviderHealthIntegrityError("F05 record does not identify one exact F01 attempt.")
    return values[0]


def _health_metadata(record: ProviderHealthRecord) -> dict[str, object]:
    from matchvet.provider_health_repository import _record_metadata

    value = _record_metadata(record)
    return {
        "assessment_digest": value.assessment_digest,
        "attempt_id": value.attempt_id,
        "record_digest": value.record_digest,
        "scope_id": value.fixture_scope_id,
        "provider_id": value.provider_id,
        "capability_id": value.capability_id,
    }


def _clock_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError("F06 clock must return a timezone-aware UTC datetime.")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("F06 source timestamp must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _same_request_content(
    left: MatchweekMembershipFreeze,
    right: MatchweekMembershipFreeze,
) -> bool:
    return (
        left.freeze_id == right.freeze_id
        and left.assessment_digest == right.assessment_digest
        and left.policy == right.policy
        and left.season == right.season
        and left.matchweek_friday == right.matchweek_friday
        and left.schedule_state == right.schedule_state
        and left.scopes == right.scopes
        and left.provider_health_references == right.provider_health_references
        and left.memberships == right.memberships
        and left.membership_set_digest == right.membership_set_digest
    )


def _same_observation_content(
    left: MatchweekMembershipObservation,
    right: MatchweekMembershipObservation,
) -> bool:
    return (
        left.observation_id == right.observation_id
        and left.freeze_id == right.freeze_id
        and left.assessment_digest == right.assessment_digest
        and left.assessment_state == right.assessment_state
        and left.scopes == right.scopes
        and left.changes == right.changes
    )


def _scope_refusal(assessment_digest: str, reason: str) -> MatchweekMembershipError:
    return MatchweekMembershipError(
        "MV-F06-SCOPE-MISMATCH", "SCOPE_MISMATCH", f"F01 assessment {assessment_digest}: {reason}"
    )


def _health_refusal(assessment_digest: str, reason: str) -> MatchweekMembershipError:
    return MatchweekMembershipError(
        "MV-F06-HEALTH-INCOMPLETE",
        "HEALTH_HISTORY_INCOMPLETE",
        f"F05 history for exact F01 assessment {assessment_digest}: {reason}",
    )


def _identity_conflict(freeze_id: str) -> MatchweekMembershipIntegrityError:
    return MatchweekMembershipIntegrityError(
        "MV-F06-IDENTITY-CONFLICT",
        "IDENTITY_CONFLICT",
        f"F06 immutable identity {freeze_id} already contains different content.",
    )


def _stored_corruption(message: str) -> MatchweekMembershipIntegrityError:
    return MatchweekMembershipIntegrityError(
        "MV-F06-REFERENCE-INTEGRITY", "REFERENCE_CORRUPT", message
    )

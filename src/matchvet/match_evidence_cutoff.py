"""F07 immutable per-match cutoffs, stored as protected content-addressed artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.matchweek_membership import (
    MatchweekMembershipError,
    MatchweekMembershipFreeze,
    MembershipDecision,
    MembershipState,
    canonical_json,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.store import Store

POLICY_MEDIA_TYPE = "application/vnd.matchvet.match-evidence-cutoff-policy.v1+json"
CUTOFF_MEDIA_TYPE = "application/vnd.matchvet.match-evidence-cutoff.v1+json"


class MatchEvidenceCutoffError(ValueError):
    """An F07 request or immutable reference cannot be verified."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CutoffPolicy:
    """Explicit timing configuration; no production lead time is supplied by F07."""

    policy_id: str
    policy_version: str
    lead_time_seconds: int | None
    schema_version: int = 1
    rule: str = "KICKOFF_MINUS_LEAD_TIME"

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise _refuse("VERSION-UNSUPPORTED", "Unsupported F07 policy schema.")
        if self.rule != "KICKOFF_MINUS_LEAD_TIME":
            raise _refuse("VERSION-UNSUPPORTED", "Unsupported F07 timing rule.")
        if any(type(v) is not str or not v.strip() for v in (self.policy_id, self.policy_version)):
            raise _refuse("POLICY-INVALID", "Policy identity and version must be explicit.")
        if self.lead_time_seconds is not None and (
            type(self.lead_time_seconds) is not int or self.lead_time_seconds <= 0
        ):
            raise _refuse("POLICY-INVALID", "Configured lead time must be a positive integer.")


@dataclass(frozen=True)
class MatchEvidenceCutoff:
    schema_version: int
    freeze_id: str
    freeze_digest: str
    membership_id: str
    membership_digest: str
    fixture_id: str
    fixture_revision_ref: str
    fixture_revision_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    cutoff_at_utc: str

    def to_bytes(self) -> bytes:
        return canonical_json(asdict(self)).encode("utf-8")

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.to_bytes()).hexdigest()

    @property
    def cutoff_id(self) -> str:
        return "f07:" + self.digest.removeprefix("sha256:")


class MatchEvidenceCutoffRepository:
    """Persist and replay exact F06-backed cutoffs without consulting latest revisions."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._artifacts = ArtifactStore(store)
        self._freezes = MatchweekMembershipRepository(store)

    def persist_policy(self, policy: CutoffPolicy) -> str:
        """Publish a policy snapshot; returned SHA-256 names its exact configuration."""
        # Reconstruct to validate even caller-supplied dataclass values.
        validated = CutoffPolicy(**asdict(policy))
        try:
            return self._artifacts.publish_artifact(
                canonical_json(asdict(validated)).encode(), POLICY_MEDIA_TYPE
            ).digest
        except ArtifactError as error:
            raise _refuse("PERSISTENCE-FAILED", str(error)) from error

    def read_policy(self, policy_digest: str) -> CutoffPolicy:
        encoded = self._read(policy_digest, POLICY_MEDIA_TYPE)
        try:
            policy = CutoffPolicy(**json.loads(encoded))
            if canonical_json(asdict(policy)).encode() != encoded:
                raise ValueError("Noncanonical policy payload.")
            return policy
        except (TypeError, ValueError) as error:
            if isinstance(error, MatchEvidenceCutoffError):
                raise
            raise _refuse("POLICY-CORRUPT", "Malformed F07 policy snapshot.") from error

    def persist_exact(
        self, freeze_id: str, membership_id: str, policy_digest: str
    ) -> MatchEvidenceCutoff:
        """Assign a cutoff only to the exact frozen INCLUDED membership named by caller."""
        freeze, policy = self._inputs(freeze_id, policy_digest)
        member = next((m for m in freeze.memberships if m.membership_id == membership_id), None)
        if member is None or member.decision is not MembershipState.INCLUDED:
            raise _refuse("MEMBERSHIP-MISMATCH", "An exact INCLUDED frozen membership is required.")
        return self._persist_cutoff(_cutoff(freeze, member, policy, policy_digest))

    def persist_for_freeze(
        self, freeze_id: str, policy_digest: str
    ) -> tuple[MatchEvidenceCutoff, ...]:
        """Persist every eligible match; interrupted work can retry individual artifacts."""
        freeze, policy = self._inputs(freeze_id, policy_digest)
        return tuple(
            self._persist_cutoff(_cutoff(freeze, member, policy, policy_digest))
            for member in freeze.memberships
            if member.decision is MembershipState.INCLUDED
        )

    def get_by_id(self, cutoff_id: str) -> MatchEvidenceCutoff | None:
        """Read a named cutoff, verifying its full immutable reference chain."""
        digest = _id_digest(cutoff_id)
        if self._store.artifact_metadata(digest) is None:
            return None
        encoded = self._read(digest, CUTOFF_MEDIA_TYPE)
        try:
            cutoff = MatchEvidenceCutoff(**json.loads(encoded))
            if type(cutoff.schema_version) is not int or cutoff.schema_version != 1:
                raise _refuse("VERSION-UNSUPPORTED", "Unsupported F07 cutoff schema.")
            if any(
                type(value) is not str or not value
                for key, value in asdict(cutoff).items()
                if key != "schema_version"
            ):
                raise ValueError("Cutoff reference fields must be nonempty strings.")
            if cutoff.cutoff_id != cutoff_id or cutoff.to_bytes() != encoded:
                raise ValueError("Noncanonical cutoff or identity mismatch.")
            freeze, policy = self._inputs(cutoff.freeze_id, cutoff.policy_digest)
            member = next(
                (m for m in freeze.memberships if m.membership_id == cutoff.membership_id), None
            )
            if member is None or member.decision is not MembershipState.INCLUDED:
                raise ValueError("Cutoff does not name an INCLUDED membership.")
            if cutoff != _cutoff(freeze, member, policy, cutoff.policy_digest):
                raise ValueError("Cutoff differs from its exact immutable references.")
            return cutoff
        except (TypeError, ValueError, KeyError) as error:
            if isinstance(error, MatchEvidenceCutoffError):
                raise
            raise _refuse("REFERENCE-CORRUPT", "F07 cutoff or references are corrupt.") from error

    def replay(self, cutoff_id: str) -> MatchEvidenceCutoff:
        """Required exact read. Missing state cannot be silently replaced or regenerated."""
        cutoff = self.get_by_id(cutoff_id)
        if cutoff is None:
            raise _refuse("CUTOFF-MISSING", "Exact F07 cutoff does not exist.")
        return cutoff

    def replay_for_freeze(
        self, freeze_id: str, policy_digest: str
    ) -> tuple[MatchEvidenceCutoff, ...]:
        """Require a persisted cutoff for every INCLUDED member under this exact policy."""
        freeze, policy = self._inputs(freeze_id, policy_digest)
        return tuple(
            self._replay_expected(_cutoff(freeze, member, policy, policy_digest))
            for member in freeze.memberships
            if member.decision is MembershipState.INCLUDED
        )

    def evidence_is_pre_cutoff(
        self, cutoff_id: str, *, published_at_utc: str | None, retrieved_at_utc: str
    ) -> bool:
        """Check both availability times against stored state, never a later match policy."""
        cutoff = self.replay(cutoff_id)
        boundary = _utc(cutoff.cutoff_at_utc)
        retrieved = _utc(retrieved_at_utc)
        if published_at_utc is None:
            return False
        published = _utc(published_at_utc)
        return published <= retrieved <= boundary

    def _persist_cutoff(self, cutoff: MatchEvidenceCutoff) -> MatchEvidenceCutoff:
        try:
            self._artifacts.publish_artifact(cutoff.to_bytes(), CUTOFF_MEDIA_TYPE)
        except ArtifactError as error:
            raise _refuse("PERSISTENCE-FAILED", str(error)) from error
        return self._replay_expected(cutoff)

    def _replay_expected(self, cutoff: MatchEvidenceCutoff) -> MatchEvidenceCutoff:
        digest = _id_digest(cutoff.cutoff_id)
        if self._store.artifact_metadata(digest) is None:
            raise _refuse("CUTOFF-MISSING", "Exact F07 cutoff does not exist.")
        if self._read(digest, CUTOFF_MEDIA_TYPE) != cutoff.to_bytes():
            raise _refuse("REFERENCE-CORRUPT", "Cutoff differs from its exact references.")
        return cutoff

    def _inputs(
        self, freeze_id: str, policy_digest: str
    ) -> tuple[MatchweekMembershipFreeze, CutoffPolicy]:
        try:
            freeze = self._freezes.get_by_id(freeze_id)
        except MatchweekMembershipError as error:
            raise _refuse("REFERENCE-CORRUPT", "Exact F06 freeze cannot be verified.") from error
        if freeze is None:
            raise _refuse("FREEZE-MISSING", "Exact F06 freeze is required.")
        policy = self.read_policy(policy_digest)
        if policy.lead_time_seconds is None:
            raise _refuse("POLICY-UNCONFIGURED", "F07 requires an explicitly configured lead time.")
        return freeze, policy

    def _read(self, digest: str, media_type: str) -> bytes:
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise _refuse("REFERENCE-INVALID", "An exact artifact SHA-256 is required.")
        metadata = self._store.artifact_metadata(digest)
        if metadata is None:
            raise _refuse("REFERENCE-MISSING", "Required F07 artifact does not exist.")
        if metadata.media_type != media_type or metadata.retention_class != "PROTECTED":
            raise _refuse("REFERENCE-MISMATCH", "F07 artifact type or retention differs.")
        try:
            return self._artifacts.read_artifact(digest)
        except ArtifactError as error:
            raise _refuse(
                "REFERENCE-CORRUPT", "Required F07 artifact failed verification."
            ) from error


def _cutoff(
    freeze: MatchweekMembershipFreeze,
    member: MembershipDecision,
    policy: CutoffPolicy,
    policy_digest: str,
) -> MatchEvidenceCutoff:
    kickoff = member.controlling_revision.kickoff_utc
    if kickoff is None or member.controlling_revision.kickoff_precision != "INSTANT":
        raise _refuse("KICKOFF-INVALID", "An exact controlling kickoff is required.")
    if policy.lead_time_seconds is None:
        raise _refuse("POLICY-UNCONFIGURED", "Cutoff policy has no configured lead time.")
    try:
        boundary = _utc(kickoff) - timedelta(seconds=policy.lead_time_seconds)
    except OverflowError as error:
        raise _refuse("POLICY-INVALID", "Configured lead time exceeds timestamp range.") from error
    return MatchEvidenceCutoff(
        1,
        freeze.freeze_id,
        freeze.freeze_digest,
        member.membership_id,
        member.membership_digest,
        member.fixture_id,
        member.controlling_revision_id,
        member.controlling_revision_digest,
        policy.policy_id,
        policy.policy_version,
        policy_digest,
        boundary.isoformat(timespec="microseconds"),
    )


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("Timestamp must use UTC.")
        return parsed.astimezone(UTC)
    except (TypeError, ValueError) as error:
        raise _refuse("TIMESTAMP-INVALID", "A timezone-aware UTC timestamp is required.") from error


def _id_digest(cutoff_id: str) -> str:
    if type(cutoff_id) is not str or re.fullmatch(r"f07:[0-9a-f]{64}", cutoff_id) is None:
        raise _refuse("IDENTITY-INVALID", "An exact F07 cutoff identity is required.")
    return cutoff_id[4:]


def _refuse(condition: str, message: str) -> MatchEvidenceCutoffError:
    return MatchEvidenceCutoffError("MV-F07-" + condition, message)

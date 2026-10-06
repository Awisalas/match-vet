"""One exact Matchweek selection, acknowledged by the same live commit operation.

A clock provider must bound actual UTC at the instant observe() returns, including
error, rollback and suspension. Source/confidence identify that explicit trust
contract; the default provider cannot establish it and refuses. This is local
application evidence under honest WAL/FULL storage and one catalog history.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from matchvet.artifacts import (
    ArtifactError,
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestVersion,
    SnapshotManifest,
)
from matchvet.f16 import MANIFEST_MEDIA_TYPE as F16_MEDIA_TYPE
from matchvet.f16 import F16Error, F16MatchweekProcessor
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek import MatchweekWindow
from matchvet.matchweek_membership import MatchweekMembershipError
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.research_identity import completion_slot, logical_matchweek_id, selection_slot
from matchvet.store import CanonicalIdentifier, Store, VersionIdentity

CORRECTED_RULE = "MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME"


class MatchweekResearchError(ValueError):
    """An exact selection cannot qualify or the prospective gate is closed."""


@dataclass(frozen=True)
class TrustedUTCUpperBound:
    upper_bound_utc: datetime
    source: str
    confidence: str


class TrustedUTCClock(Protocol):
    def observe(self) -> TrustedUTCUpperBound:
        """Return a trusted bound for actual UTC at return, never a caller timestamp."""
        ...


class _UnavailableClock:
    def observe(self) -> TrustedUTCUpperBound:
        raise MatchweekResearchError("Trusted UTC upper-bound confidence is unavailable.")


@dataclass(frozen=True)
class FrozenMatchweekResearch:
    digest: str
    season: str
    matchweek_friday: str
    freeze_id: str
    policy_digest: str
    cutoff_at_utc: str
    f16_manifest_digest: str
    completion_receipt_digest: str


@dataclass(frozen=True)
class _Graph:
    season: str
    friday: str
    freeze_id: str
    policy_digest: str
    cutoff: str
    f16_digest: str
    references: tuple[ManifestArtifact, ...]

    @property
    def logical_id(self) -> str:
        return _logical_identity(self.season, self.friday)

    @property
    def boundary_id(self) -> CanonicalIdentifier:
        return _identifier(
            "research_cutoff",
            f"matchvet:research-boundary:{self.logical_id}:{self.policy_digest}:{self.cutoff}",
        )


def _identifier(kind: str, name: str) -> CanonicalIdentifier:
    return CanonicalIdentifier(kind, str(uuid.uuid5(uuid.NAMESPACE_URL, name)))


def _logical_identity(season: str, friday: str) -> str:
    if not isinstance(season, str) or not season or season.strip() != season:
        raise MatchweekResearchError("An exact season is required.")
    try:
        window = MatchweekWindow.for_friday(friday)
        if window.friday_local.isoformat() != friday:
            raise ValueError("Noncanonical Friday.")
    except (TypeError, ValueError, AttributeError) as error:
        raise MatchweekResearchError("An exact canonical Matchweek Friday is required.") from error
    return logical_matchweek_id(season, friday)


def _version(role: str) -> VersionIdentity:
    name = f"matchvet:matchweek-research-{role}:postcommit-upper-bound-v1"
    return VersionIdentity(
        identifier=_identifier("version", name),
        definition_id=_identifier("version_definition", f"matchvet:matchweek-research-{role}"),
        kind=f"matchweek_research_{role}",
        name=name,
        content_sha256=hashlib.sha256(name.encode()).hexdigest(),
        canonical_contract_version=1,
    )


def _reference(artifacts: ArtifactStore, digest: str) -> ManifestArtifact:
    record = artifacts.verify_artifact(digest)
    return ManifestArtifact(
        record.artifact_id, record.digest, record.media_type, record.byte_length
    )


class MatchweekResearchRepository:
    """Own admission, commit acknowledgement, one receipt attempt and exact replay."""

    def __init__(self, store: Store, *, clock: TrustedUTCClock | None = None) -> None:
        self._store = store
        self._artifacts = ArtifactStore(store)
        self._clock = clock if clock is not None else _UnavailableClock()
        self._last_bound: datetime | None = None

    def _observe(self) -> str:
        observation = self._clock.observe()
        if not isinstance(observation, TrustedUTCUpperBound) or (
            observation.confidence != "TRUSTED"
            or not observation.source.strip()
            or not isinstance(observation.upper_bound_utc, datetime)
            or observation.upper_bound_utc.tzinfo is None
            or observation.upper_bound_utc.utcoffset() != UTC.utcoffset(observation.upper_bound_utc)
        ):
            raise MatchweekResearchError("Clock observation lacks trusted UTC confidence.")
        bound = observation.upper_bound_utc
        if self._last_bound is not None and bound < self._last_bound:
            raise MatchweekResearchError("Trusted UTC upper bound moved backward.")
        self._last_bound = bound
        return bound.isoformat(timespec="microseconds")

    def _require_before(self, cutoff: str) -> str:
        observed = self._observe()
        if datetime.fromisoformat(observed) >= datetime.fromisoformat(cutoff):
            raise MatchweekResearchError("The common Matchweek cutoff is closed.")
        return observed

    def _admit(self, f16_digest: str) -> _Graph:
        try:
            with self._store._capture_verified_artifacts() as digests:
                manifest = F16MatchweekProcessor(self._store).replay_manifest(f16_digest)
                value = manifest.to_dict()
                freeze = MatchweekMembershipRepository(self._store).get_by_id(value["freeze_id"])
                if freeze is None:
                    raise MatchweekResearchError("Exact F06 freeze is missing.")
                _logical_identity(freeze.season, freeze.matchweek_friday)
                cutoffs = MatchEvidenceCutoffRepository(self._store)
                policy = cutoffs.read_policy(value["cutoff_policy_digest"])
                if policy.rule != CORRECTED_RULE:
                    raise MatchweekResearchError("Selection requires the corrected F07 rule.")
                boundaries = cutoffs.replay_for_freeze(
                    freeze.freeze_id, value["cutoff_policy_digest"]
                )
                if not boundaries or len({item.cutoff_at_utc for item in boundaries}) != 1:
                    raise MatchweekResearchError("One defined common cutoff is required.")
                if {row.cutoff_id for row in manifest.match_results} != {
                    item.cutoff_id for item in boundaries
                }:
                    raise MatchweekResearchError("F16 differs from the whole exact F07 boundary.")
                if len({row.evidence_digest for row in manifest.match_results}) != 1:
                    raise MatchweekResearchError("One exact F11 evidence set is required.")
                references = tuple(
                    _reference(self._artifacts, digest) for digest in sorted(digests)
                )
                return _Graph(
                    freeze.season,
                    freeze.matchweek_friday,
                    freeze.freeze_id,
                    value["cutoff_policy_digest"],
                    boundaries[0].cutoff_at_utc,
                    f16_digest,
                    references,
                )
        except (
            ArtifactError,
            F16Error,
            MatchEvidenceCutoffError,
            MatchweekMembershipError,
        ) as error:
            raise MatchweekResearchError(
                "The complete selected graph failed exact replay."
            ) from error

    def _manifest(
        self,
        graph: _Graph,
        *,
        role: str,
        created: str,
        selection_digest: str | None = None,
    ) -> SnapshotManifest:
        version = _version(role)
        receipt = role == "completion"
        return SnapshotManifest(
            snapshot_id=CanonicalIdentifier(
                "snapshot_manifest",
                completion_slot(graph.logical_id) if receipt else selection_slot(graph.logical_id),
            ),
            matchweek_id=CanonicalIdentifier("matchweek", graph.logical_id),
            research_cutoff_id=graph.boundary_id,
            version_manifest_id=_identifier("version_manifest", version.identifier.value),
            research_cutoff_utc=graph.cutoff,
            artifacts=(_reference(self._artifacts, selection_digest),)
            if selection_digest is not None
            else graph.references,
            versions=(ManifestVersion.from_identity(version),),
            retention_omissions=(),
            completeness=ManifestCompleteness("COMPLETE"),
            created_at_utc=created,
            parent_snapshot_id=CanonicalIdentifier(
                "snapshot_manifest", selection_slot(graph.logical_id)
            )
            if receipt
            else None,
        )

    def seal_completed(self, f16_manifest_digest: str) -> FrozenMatchweekResearch:
        # Refuse nested entry before replay or a caller clock callback can run.
        if self._store._research_owner is not None:
            raise MatchweekResearchError("A selection operation is already active.")
        graph = self._admit(f16_manifest_digest)
        existing = self._store.snapshot_manifest_digest_for_snapshot(
            selection_slot(graph.logical_id)
        )
        if existing is not None:
            existing_selected = self.replay(existing)
            if existing_selected.f16_manifest_digest != f16_manifest_digest:
                raise MatchweekResearchError("The existing exact selection wins.")
            return existing_selected
        try:

            def ensure_selection_open() -> None:
                self._require_before(graph.cutoff)

            with self._store._research_operation(
                graph.logical_id, ensure_selection_open
            ) as operation:
                created = self._require_before(graph.cutoff)
                with self._store.transaction() as transaction:
                    for role in ("selection", "completion"):
                        version = _version(role)
                        existing_version = self._store.version(version.identifier)
                        if existing_version is None:
                            transaction.add_version(version)
                        elif ManifestVersion.from_identity(
                            existing_version
                        ) != ManifestVersion.from_identity(version):
                            raise MatchweekResearchError("Stored completion protocol differs.")
                selection = self._manifest(graph, role="selection", created=created)
                selected = self._artifacts._publish_research_manifest(
                    selection, operation, role="selection"
                )
                # Only a fresh successful return reaches this postcommit observation.
                upper_bound = self._require_before(graph.cutoff)
                operation._acknowledge(upper_bound, graph.cutoff)
                receipt = self._manifest(
                    graph, role="completion", created=upper_bound, selection_digest=selected.digest
                )
                try:
                    self._artifacts._publish_research_manifest(receipt, operation, role="receipt")
                except Exception:
                    # A possibly committed receipt permits only indexed read-only recovery.
                    return self.replay(selected.digest)
                return self.replay(selected.digest)
        except (ArtifactError, RuntimeError, ValueError) as error:
            if isinstance(error, MatchweekResearchError):
                raise
            raise MatchweekResearchError(
                "Selection was not acknowledged by the live operation."
            ) from error

    def require_preselection_open(self, freeze_id: str, policy_digest: str) -> None:
        try:
            freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
            if freeze is None:
                raise MatchweekResearchError("Exact F06 freeze is missing.")
            logical = _logical_identity(freeze.season, freeze.matchweek_friday)
            if (
                self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
                is not None
            ):
                raise MatchweekResearchError("The logical Matchweek selection slot is occupied.")
            repository = MatchEvidenceCutoffRepository(self._store)
            if repository.read_policy(policy_digest).rule != CORRECTED_RULE:
                raise MatchweekResearchError("Preselection requires the corrected F07 rule.")
            cutoffs = repository.replay_for_freeze(freeze_id, policy_digest)
            if not cutoffs or len({item.cutoff_at_utc for item in cutoffs}) != 1:
                raise MatchweekResearchError("A common cutoff is required.")
            self._require_before(cutoffs[0].cutoff_at_utc)
        except (ArtifactError, MatchEvidenceCutoffError, MatchweekMembershipError) as error:
            raise MatchweekResearchError("Exact preselection lineage is invalid.") from error

    def replay_for_matchweek(
        self, *, season: str, matchweek_friday: str
    ) -> FrozenMatchweekResearch:
        logical = _logical_identity(season, matchweek_friday)
        digest = self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
        if digest is None:
            raise MatchweekResearchError("No indexed selection exists for this Matchweek.")
        selected = self.replay(digest)
        if (selected.season, selected.matchweek_friday) != (season, matchweek_friday):
            raise MatchweekResearchError("Indexed selection maps to a different logical Matchweek.")
        return selected

    def replay(self, selection_digest: str) -> FrozenMatchweekResearch:
        try:
            selection = self._artifacts.verify_manifest(selection_digest)
            f16 = tuple(
                ref.digest for ref in selection.artifacts if ref.media_type == F16_MEDIA_TYPE
            )
            if len(f16) != 1:
                raise MatchweekResearchError("Selection must identify exactly one complete F16.")
            graph = self._admit(f16[0])
            expected = self._manifest(graph, role="selection", created=selection.created_at_utc)
            self._validate_manifest(selection, expected)
            if (
                self._store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id))
                != selection_digest
            ):
                raise MatchweekResearchError("Selection is not the exact indexed logical winner.")
            receipt_digest = self._store.snapshot_manifest_digest_for_snapshot(
                completion_slot(graph.logical_id)
            )
            if receipt_digest is None:
                raise MatchweekResearchError(
                    "Selection without an indexed receipt is permanently unqualified."
                )
            receipt = self._artifacts.verify_manifest(receipt_digest)
            expected_receipt = self._manifest(
                graph,
                role="completion",
                created=receipt.created_at_utc,
                selection_digest=selection_digest,
            )
            self._validate_manifest(receipt, expected_receipt)
            if datetime.fromisoformat(receipt.created_at_utc) >= datetime.fromisoformat(
                graph.cutoff
            ):
                raise MatchweekResearchError(
                    "Completion upper bound is not strictly before cutoff."
                )
            return FrozenMatchweekResearch(
                selection_digest,
                graph.season,
                graph.friday,
                graph.freeze_id,
                graph.policy_digest,
                graph.cutoff,
                graph.f16_digest,
                receipt_digest,
            )
        except (
            ArtifactError,
            F16Error,
            MatchEvidenceCutoffError,
            MatchweekMembershipError,
        ) as error:
            raise MatchweekResearchError(
                "Indexed selection or receipt failed exact replay."
            ) from error

    @staticmethod
    def _validate_manifest(actual: SnapshotManifest, expected: SnapshotManifest) -> None:
        from dataclasses import replace

        if actual != replace(
            expected, verification_state="VERIFIED", verified_at_utc=actual.verified_at_utc
        ):
            raise MatchweekResearchError(
                "SnapshotManifest does not satisfy its exact research role."
            )

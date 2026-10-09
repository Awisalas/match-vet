"""One exact Matchweek selection, acknowledged by the same live commit operation.

A clock provider must bound actual UTC at the instant observe() returns, including
error, rollback and suspension. Source/confidence identify that explicit trust
contract; the default provider cannot establish it and refuses. This is local
application evidence under honest WAL/FULL storage and one catalog history.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from matchvet.causal_candidate import CausalCandidateContract
    from matchvet.causal_selection import _CausalGraph
    from matchvet.t15 import PolicyVersion

from matchvet.artifacts import (
    ArtifactError,
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestVersion,
    SnapshotManifest,
)
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

    def __init__(
        self,
        store: Store,
        *,
        clock: TrustedUTCClock | None = None,
        candidate_contract_digest: str | None = None,
        selection_contract: str | None = None,
        advisory_clock: Callable[[], datetime] | None = None,
    ) -> None:
        from matchvet.causal_candidate import writer_contract

        self.selection_contract = writer_contract(candidate_contract_digest, selection_contract)
        self.candidate_contract_digest = candidate_contract_digest
        self._advisory_clock = advisory_clock
        self._candidate_cache: dict[str, CausalCandidateContract] = {}
        self._association_cache: dict[tuple[str, str], str] = {}
        self._boundary_cache: dict[str, tuple[str, str]] = {}
        self._run_association_cache: dict[tuple[str, str, str], tuple[str, str, str | None]] = {}
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

    def _admit(
        self, f16_digest: str, *, references: tuple[ManifestArtifact, ...] | None = None
    ) -> _Graph:
        from matchvet.f16 import F16Error, F16MatchweekProcessor

        try:
            if references is None:
                value = json.loads(self._artifacts.read_artifact(f16_digest))
                scope = (
                    self.indexed_replay_catalog(value["freeze_id"], value["cutoff_policy_digest"])
                    if isinstance(value, dict)
                    and isinstance(value.get("freeze_id"), str)
                    and isinstance(value.get("cutoff_policy_digest"), str)
                    else None
                )
            else:
                scope = frozenset(ref.digest for ref in references)
            with (
                self._store._scope_artifact_catalog(scope),
                self._store._capture_verified_artifacts() as digests,
            ):
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
            json.JSONDecodeError,
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

    def _admit_v2(
        self, f16_digest: str, *, references: tuple[ManifestArtifact, ...] | None = None
    ) -> _CausalGraph:
        from matchvet.causal_selection import _CausalGraph
        from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE, F16MatchweekProcessor

        try:
            metadata = self._store.artifact_metadata(f16_digest)
            if metadata is None or metadata.media_type != CAUSAL_MANIFEST_MEDIA_TYPE:
                raise MatchweekResearchError("Unsupported causal successor F16 contract.")
            root = json.loads(self._artifacts.read_artifact(f16_digest))
            if root.get("schema_version") != 2 or not isinstance(
                root.get("candidate_contract_digest"), str
            ):
                raise MatchweekResearchError("Incomplete causal successor context.")
            scope = (
                frozenset(ref.digest for ref in references)
                if references is not None
                else self.indexed_replay_catalog(root["freeze_id"], root["cutoff_policy_digest"])
            )
            with (
                self._store._scope_artifact_catalog(scope),
                self._store._capture_verified_artifacts() as digests,
            ):
                manifest = F16MatchweekProcessor(self._store).replay_manifest(f16_digest)
                value = manifest.to_dict()
                candidate = self.resolve_candidate(value["candidate_contract_digest"])
                freeze = MatchweekMembershipRepository(self._store).get_by_id(candidate.freeze_id)
                assert freeze is not None
                boundaries = MatchEvidenceCutoffRepository(self._store).replay_for_freeze(
                    candidate.freeze_id, candidate.cutoff_policy_digest
                )
                if {row.cutoff_id for row in manifest.match_results} != {
                    c.cutoff_id for c in boundaries
                } or len({row.evidence_digest for row in manifest.match_results}) != 1:
                    raise MatchweekResearchError("Incomplete homogeneous causal graph.")
                closure = tuple(_reference(self._artifacts, item) for item in sorted(digests))
                if references is not None and closure != references:
                    raise MatchweekResearchError(
                        "Causal bound references differ from the actual complete graph."
                    )
                graph = _CausalGraph(
                    freeze.season,
                    freeze.matchweek_friday,
                    candidate.freeze_id,
                    candidate.cutoff_policy_digest,
                    candidate.cutoff_at_utc,
                    f16_digest,
                    closure,
                    candidate.digest,
                    candidate.freeze_digest,
                    candidate.profile_digest,
                    manifest.match_results[0].model_digest,
                    candidate.engine_contract_digest,
                    candidate.decision_policy_artifact_digest,
                )
                graph.check(self._artifacts)
                return graph
        except MatchweekResearchError:
            raise
        except (
            ArtifactError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
        ) as error:
            raise MatchweekResearchError(
                "Unsupported or incomplete causal successor graph."
            ) from error

    def publish_candidate(
        self,
        *,
        freeze_id: str,
        policy_digest: str,
        profile_digest: str,
        decision_policy: PolicyVersion,
        engine_version: str,
        witness_profile_digest: str,
    ) -> str:
        from matchvet.causal_candidate import publish

        return publish(
            self._store,
            freeze_id=freeze_id,
            policy_digest=policy_digest,
            profile_digest=profile_digest,
            decision_policy=decision_policy,
            engine_version=engine_version,
            witness_profile_digest=witness_profile_digest,
        )

    def resolve_candidate(self, digest: str) -> CausalCandidateContract:
        from matchvet.causal_candidate import resolve

        if self._store._verified_artifacts is not None:
            return resolve(self._store, digest)
        if digest not in self._candidate_cache:
            self._candidate_cache[digest] = resolve(self._store, digest)
        return self._candidate_cache[digest]

    def require_causal_write(self, digest: str) -> None:
        candidate = self.resolve_candidate(digest)
        if (
            self._store.snapshot_manifest_digest_for_snapshot(
                selection_slot(candidate.logical_matchweek_id)
            )
            is not None
        ):
            raise MatchweekResearchError("The logical Matchweek selection slot is occupied.")
        self._candidate_conflicts(candidate.logical_matchweek_id, digest)
        if self._advisory_clock is not None:
            observed = self._advisory_clock()
            if observed.tzinfo is None or observed >= datetime.fromisoformat(
                candidate.cutoff_at_utc
            ):
                raise MatchweekResearchError(
                    "Advisory clock refuses obviously wasted candidate work."
                )

    def validate_context(
        self,
        freeze_id: str,
        policy_digest: str,
        *,
        profile_digest: str | None = None,
        decision_policy_digest: str | None = None,
    ) -> None:
        if self.candidate_contract_digest is None:
            return
        candidate = self.resolve_candidate(self.candidate_contract_digest)
        if (
            (candidate.freeze_id, candidate.cutoff_policy_digest) != (freeze_id, policy_digest)
            or (profile_digest is not None and candidate.profile_digest != profile_digest)
            or (
                decision_policy_digest is not None
                and candidate.decision_policy_digest != decision_policy_digest
            )
        ):
            raise MatchweekResearchError("Explicit candidate descriptor context differs.")

    def _candidate_conflicts(self, logical: str, candidate_digest: str | None) -> None:
        from matchvet.causal_candidate import check_occupancy

        check_occupancy(self, logical, candidate_digest)

    def seal_completed_v2(self, f16_manifest_digest: str) -> FrozenMatchweekResearch:
        from matchvet.causal_selection import _seal

        return _seal(self, f16_manifest_digest)

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

    def inspect_causal(self, selection_digest: str) -> FrozenMatchweekResearch:
        from matchvet.causal_selection import _replay

        selection = self._artifacts.verify_manifest(selection_digest)
        logical = selection.matchweek_id.value
        if self._store.snapshot_manifest_digest_for_snapshot(completion_slot(logical)) is None:
            from matchvet.causal_selection import _manifest_v2, _version_v2
            from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE

            if (
                selection.versions != (ManifestVersion.from_identity(_version_v2("selection")),)
                or self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
                != selection_digest
            ):
                raise MatchweekResearchError("Inspection requires the exact indexed causal winner.")
            roots = [
                ref.digest
                for ref in selection.artifacts
                if ref.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
            ]
            if len(roots) != 1:
                raise MatchweekResearchError("Inspection requires one exact complete F16.")
            graph = self._admit_v2(roots[0], references=selection.artifacts)
            self._validate_manifest(
                selection,
                _manifest_v2(self, graph, role="selection", created=selection.created_at_utc),
            )
            return FrozenMatchweekResearch(
                selection_digest,
                graph.season,
                graph.friday,
                graph.freeze_id,
                graph.policy_digest,
                graph.cutoff,
                graph.f16_digest,
                "",
            )
        return _replay(self, selection_digest, qualify=False)

    def require_preselection_open(self, freeze_id: str, policy_digest: str) -> str:
        if self.candidate_contract_digest is not None:
            raise MatchweekResearchError("Causal admission never returns trusted UTC.")
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
            self._require_candidate_identity(logical, freeze_id, policy_digest)
            return self._require_before(cutoffs[0].cutoff_at_utc)
        except (ArtifactError, MatchEvidenceCutoffError, MatchweekMembershipError) as error:
            raise MatchweekResearchError("Exact preselection lineage is invalid.") from error

    def is_corrected(self, policy_digest: str) -> bool:
        policy = MatchEvidenceCutoffRepository(self._store).read_policy(policy_digest)
        return policy.rule == CORRECTED_RULE

    def _require_candidate_identity(self, logical: str, freeze_id: str, policy_digest: str) -> None:
        from matchvet.f11 import EVIDENCE_MEDIA_TYPE
        from matchvet.f12 import F12_ATTEMPT_MEDIA_TYPE

        cutoffs = MatchEvidenceCutoffRepository(self._store)
        for other_freeze, other_policy, _, _ in self._candidate_runs():
            if (other_freeze, other_policy) == (freeze_id, policy_digest) or not self.is_corrected(
                other_policy
            ):
                continue
            other = MatchweekMembershipRepository(self._store).get_by_id(other_freeze)
            if other is None:
                raise MatchweekResearchError("Candidate F15 freeze is missing.")
            if _logical_identity(other.season, other.matchweek_friday) == logical:
                raise MatchweekResearchError("A different exact candidate boundary already exists.")
        for metadata in self._store.artifact_catalog():
            if metadata.media_type not in {EVIDENCE_MEDIA_TYPE, F12_ATTEMPT_MEDIA_TYPE}:
                continue
            evidence = json.loads(self._artifacts.read_artifact(metadata.digest))
            if metadata.media_type == F12_ATTEMPT_MEDIA_TYPE:
                if evidence["cutoff_id"] not in self._boundary_cache:
                    boundary = cutoffs.replay(evidence["cutoff_id"])
                    self._boundary_cache[evidence["cutoff_id"]] = (
                        boundary.freeze_id,
                        boundary.policy_digest,
                    )
                other_freeze, other_policy = self._boundary_cache[evidence["cutoff_id"]]
            else:
                other_freeze, other_policy = evidence["freeze_id"], evidence["policy_digest"]
            if (other_freeze, other_policy) == (freeze_id, policy_digest):
                continue
            if not self.is_corrected(other_policy):
                continue
            other = MatchweekMembershipRepository(self._store).get_by_id(other_freeze)
            if other is None:
                raise MatchweekResearchError("Candidate F06 freeze is missing.")
            if _logical_identity(other.season, other.matchweek_friday) == logical and (
                other.freeze_id,
                other_policy,
            ) != (freeze_id, policy_digest):
                raise MatchweekResearchError("A different exact candidate boundary already exists.")

    def _candidate_runs(self) -> tuple[tuple[str, str, str, str], ...]:
        from matchvet.runs import RunInputContract

        candidates = []
        rows = (
            self._store._connection_for_repository()
            .execute("SELECT input_contract_json, input_digest FROM research_runs")
            .fetchall()
        )
        for encoded, digest in rows:
            inputs = RunInputContract.from_stored_json(str(encoded))
            values = inputs.identity_values
            if values["canonical_contract"] != "MATCHVET_V2_ANALYZE_MATCHWEEK_V1":
                continue
            if inputs.aggregate_digest != digest:
                raise MatchweekResearchError("Retained F15 candidate identity is invalid.")
            freeze_row = (
                self._store._connection_for_repository()
                .execute(
                    "SELECT freeze_id FROM v2_matchweek_membership_freezes WHERE freeze_digest = ?",
                    (values["source"].removeprefix("F06:"),),
                )
                .fetchone()
            )
            if freeze_row is None:
                raise MatchweekResearchError("Retained F15 candidate freeze is missing.")
            candidates.append(
                (
                    str(freeze_row[0]),
                    values["cutoff"].split(":", 2)[1],
                    values["preference_set"].removeprefix("F14:"),
                    values["policy"].rsplit(":", 1)[1],
                )
            )
        return tuple(candidates)

    def require_candidate_contract(
        self, freeze_id: str, policy_digest: str, profile_digest: str, decision_policy_digest: str
    ) -> None:
        """Pin the whole-slate contract before any new F15/F16 phase or F14 input."""
        self.validate_context(
            freeze_id,
            policy_digest,
            profile_digest=profile_digest,
            decision_policy_digest=decision_policy_digest,
        )
        self.require_candidate_write(freeze_id, policy_digest)
        if self.candidate_contract_digest is not None or not self.is_corrected(policy_digest):
            return
        self._require_contract_identity(
            freeze_id, policy_digest, profile_digest, decision_policy_digest
        )
        self.require_candidate_write(freeze_id, policy_digest)

    def _require_contract_identity(
        self, freeze_id: str, policy_digest: str, profile_digest: str, decision_policy_digest: str
    ) -> None:
        from matchvet.f14 import DECISION_INPUT_MEDIA_TYPE

        for other_freeze, other_policy, profile, decision_policy in self._candidate_runs():
            if (other_freeze, other_policy) == (freeze_id, policy_digest) and (
                profile,
                decision_policy,
            ) != (profile_digest, decision_policy_digest):
                raise MatchweekResearchError(
                    "The frozen candidate profile or decision policy differs."
                )
        for metadata in self._store.artifact_catalog():
            if metadata.media_type != DECISION_INPUT_MEDIA_TYPE:
                continue
            value = json.loads(self._artifacts.read_artifact(metadata.digest))
            if value["cutoff_id"] not in self._boundary_cache:
                cutoff = MatchEvidenceCutoffRepository(self._store).replay(value["cutoff_id"])
                self._boundary_cache[value["cutoff_id"]] = (cutoff.freeze_id, cutoff.policy_digest)
            if self._boundary_cache[value["cutoff_id"]] == (freeze_id, policy_digest) and (
                value["profile_digest"],
                value["policy"].get("policy_digest"),
            ) != (profile_digest, decision_policy_digest):
                raise MatchweekResearchError(
                    "The frozen candidate profile or decision policy differs."
                )

    def require_candidate_write(self, freeze_id: str, policy_digest: str) -> str | None:
        """Dispatch legacy research separately; corrected writes share one authority."""
        self.validate_context(freeze_id, policy_digest)
        if self.candidate_contract_digest is not None:
            self.require_causal_write(self.candidate_contract_digest)
            return None
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekResearchError("Exact F06 freeze is missing.")
        self._candidate_conflicts(_logical_identity(freeze.season, freeze.matchweek_friday), None)
        if self.is_corrected(policy_digest):
            return self.require_preselection_open(freeze_id, policy_digest)
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekResearchError("Exact F06 freeze is missing.")
        logical = _logical_identity(freeze.season, freeze.matchweek_friday)
        if self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical)) is not None:
            raise MatchweekResearchError("The logical Matchweek selection slot is occupied.")
        return None

    def selected_for_boundary(
        self, freeze_id: str, policy_digest: str
    ) -> FrozenMatchweekResearch | None:
        """Resolve only the indexed winner, never a catalog's latest candidate."""
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekResearchError("Exact F06 freeze is missing.")
        logical = _logical_identity(freeze.season, freeze.matchweek_friday)
        digest = self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
        if digest is None:
            return None
        self.validate_context(freeze_id, policy_digest)
        from matchvet.causal_selection import _version_v2

        selection = self._artifacts.verify_manifest(digest)
        causal_selection = selection.versions == (
            ManifestVersion.from_identity(_version_v2("selection")),
        )
        if causal_selection and self.candidate_contract_digest is None:
            raise MatchweekResearchError(
                "Selected causal writer lookup requires explicit candidate context."
            )
        if self.candidate_contract_digest is not None:
            if not causal_selection:
                raise MatchweekResearchError("Selected contract differs from explicit candidate.")
            selected = self.inspect_causal(digest)
            graph = self._admit_v2(selected.f16_manifest_digest, references=selection.artifacts)
            if graph.candidate_digest != self.candidate_contract_digest:
                raise MatchweekResearchError("Selected candidate descriptor differs.")
        else:
            selected = self.replay(digest)
        if (selected.freeze_id, selected.policy_digest) != (freeze_id, policy_digest):
            raise MatchweekResearchError("The selected exact freeze and policy differ.")
        return selected

    def indexed_replay_catalog(self, freeze_id: str, policy_digest: str) -> frozenset[str] | None:
        """Read the frozen catalog view; this does not qualify a selection or a writer."""
        from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
        from matchvet.f16 import MANIFEST_MEDIA_TYPE as F16_MEDIA_TYPE

        if self._store._artifact_catalog_scope is not None:
            return self._store._artifact_catalog_scope
        if self._store._verified_artifacts is not None:
            return None
        if not self.is_corrected(policy_digest):
            return None
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekResearchError("Exact F06 freeze is missing.")
        logical = _logical_identity(freeze.season, freeze.matchweek_friday)
        digest = self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
        if digest is None:
            return None
        selection = self._artifacts.verify_manifest(digest)
        f16 = tuple(
            ref.digest
            for ref in selection.artifacts
            if ref.media_type in {F16_MEDIA_TYPE, CAUSAL_MANIFEST_MEDIA_TYPE}
        )
        if len(f16) != 1:
            raise MatchweekResearchError("Selection must identify exactly one complete F16.")
        value = json.loads(self._artifacts.read_artifact(f16[0]))
        if (value["freeze_id"], value["cutoff_policy_digest"]) != (freeze_id, policy_digest):
            return None
        return frozenset(ref.digest for ref in selection.artifacts)

    def candidate_run_guard(
        self, freeze_id: str, policy_digest: str, contract: tuple[str, str]
    ) -> Callable[[], object]:
        """Guard run metadata without turning its clocks into stage authority."""
        if self.candidate_contract_digest is not None:
            artifacts = self.candidate_artifacts(freeze_id, policy_digest, contract=contract)
            assert artifacts._write_guard is not None
            return artifacts._write_guard
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        if freeze is None:
            raise MatchweekResearchError("Exact F15 freeze is missing.")
        logical = _logical_identity(freeze.season, freeze.matchweek_friday)
        corrected = self.is_corrected(policy_digest)

        def require_run_open() -> None:
            self._candidate_conflicts(logical, None)
            if (
                self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
                is not None
            ):
                raise MatchweekResearchError("The logical Matchweek selection slot is occupied.")
            if corrected:
                self._require_candidate_identity(logical, freeze_id, policy_digest)
                self._require_contract_identity(freeze_id, policy_digest, *contract)

        return require_run_open

    def candidate_artifacts(
        self,
        freeze_id: str,
        policy_digest: str,
        *,
        check_state: Callable[[], object] | None = None,
        contract: tuple[str, str] | None = None,
    ) -> ArtifactStore:
        if self.candidate_contract_digest is not None:
            self.validate_context(freeze_id, policy_digest)
            self.require_causal_write(self.candidate_contract_digest)

            def require_causal_open() -> None:
                assert self.candidate_contract_digest is not None
                self.require_causal_write(self.candidate_contract_digest)
                if contract is not None:
                    self.validate_context(
                        freeze_id,
                        policy_digest,
                        profile_digest=contract[0],
                        decision_policy_digest=contract[1],
                    )
                if check_state is not None:
                    check_state()

            return ArtifactStore(self._store, write_guard=require_causal_open)
        if not self.is_corrected(policy_digest):
            self.require_candidate_write(freeze_id, policy_digest)
            freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
            assert freeze is not None
            logical = _logical_identity(freeze.season, freeze.matchweek_friday)

            def require_legacy_open() -> None:
                self._candidate_conflicts(logical, None)
                if (
                    self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
                    is not None
                ):
                    raise MatchweekResearchError(
                        "The logical Matchweek selection slot is occupied."
                    )
                if check_state is not None:
                    check_state()

            return ArtifactStore(self._store, write_guard=require_legacy_open)
        self.require_preselection_open(freeze_id, policy_digest)
        freeze = MatchweekMembershipRepository(self._store).get_by_id(freeze_id)
        assert freeze is not None
        logical = _logical_identity(freeze.season, freeze.matchweek_friday)
        cutoff = (
            MatchEvidenceCutoffRepository(self._store)
            .replay_for_freeze(freeze_id, policy_digest)[0]
            .cutoff_at_utc
        )

        def require_open() -> None:
            self._candidate_conflicts(logical, None)
            if (
                self._store.snapshot_manifest_digest_for_snapshot(selection_slot(logical))
                is not None
            ):
                raise MatchweekResearchError("The logical Matchweek selection slot is occupied.")
            self._require_before(cutoff)
            self._require_candidate_identity(logical, freeze_id, policy_digest)
            if contract is not None:
                self._require_contract_identity(freeze_id, policy_digest, *contract)
            if check_state is not None:
                check_state()
            self._require_before(cutoff)

        return ArtifactStore(self._store, write_guard=require_open)

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
        from matchvet.causal_selection import _replay, _version_v2
        from matchvet.f16 import MANIFEST_MEDIA_TYPE as F16_MEDIA_TYPE
        from matchvet.f16 import F16Error

        try:
            selection = self._artifacts.verify_manifest(selection_digest)
            if selection.versions == (ManifestVersion.from_identity(_version_v2("selection")),):
                return _replay(self, selection_digest)
            f16 = tuple(
                ref.digest for ref in selection.artifacts if ref.media_type == F16_MEDIA_TYPE
            )
            if len(f16) != 1:
                raise MatchweekResearchError("Selection must identify exactly one complete F16.")
            graph = self._admit(f16[0], references=selection.artifacts)
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

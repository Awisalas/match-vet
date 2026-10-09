"""Exact downstream resolution for qualified causal selection-v2 state."""

from __future__ import annotations

from dataclasses import dataclass

from matchvet.artifacts import ArtifactError, ManifestVersion
from matchvet.causal_candidate import CAUSAL_CONTRACT, CausalCandidateContract, resolve
from matchvet.causal_selection import _version_v2
from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE, F16Error, F16MatchweekProcessor
from matchvet.matchweek_research import (
    FrozenMatchweekResearch,
    MatchweekResearchError,
    MatchweekResearchRepository,
)
from matchvet.research_identity import completion_slot, selection_slot
from matchvet.store import Store


@dataclass(frozen=True)
class QualifiedCausalSelection:
    """Owner-replayed state whose exact graph is presently qualified."""

    selection: FrozenMatchweekResearch
    candidate: CausalCandidateContract
    selection_reader: ManifestVersion

    @property
    def selection_digest(self) -> str:
        return self.selection.digest

    @property
    def completion_receipt_digest(self) -> str:
        return self.selection.completion_receipt_digest

    @property
    def f16_manifest_digest(self) -> str:
        return self.selection.f16_manifest_digest

    @property
    def candidate_contract_digest(self) -> str:
        return self.candidate.digest

    @property
    def engine_contract_digest(self) -> str:
        return self.candidate.engine_contract_digest

    @property
    def engine_version(self) -> str:
        return self.candidate.engine_version

    def lineage_value(self) -> dict[str, object]:
        reader = self.selection_reader
        return {
            "selection_digest": self.selection_digest,
            "completion_receipt_digest": self.completion_receipt_digest,
            "candidate_contract_digest": self.candidate_contract_digest,
            "candidate_contract_version": self.candidate.contract_version,
            "engine_contract_digest": self.engine_contract_digest,
            "engine_version": self.engine_version,
            "selection_reader": {
                "version_id": reader.version_id.value,
                "definition_id": reader.definition_id.value,
                "kind": reader.kind,
                "name": reader.name,
                "content_sha256": reader.content_sha256,
                "canonical_contract_version": reader.canonical_contract_version,
            },
        }


@dataclass(frozen=True)
class InspectedCausalSelection(QualifiedCausalSelection):
    """Historical owner replay that is deliberately not present qualification."""

    qualification_status: str = "HISTORICAL_INSPECTION_ONLY"


def resolve_qualified_causal_selection(
    store: Store, selection_digest: str
) -> QualifiedCausalSelection:
    """Resolve only the indexed, receipted, currently trusted selection-v2 winner.

    Version and reader dispatch happen before owner replay compares the causal
    witness time with the common cutoff. A terminal selection remains inspectable
    through the research repository, but cannot be returned by this resolver.
    """
    owner = MatchweekResearchRepository(store)
    try:
        selection_manifest = owner._artifacts.verify_manifest(selection_digest)
        selection_reader = ManifestVersion.from_identity(_version_v2("selection"))
        if selection_manifest.versions != (selection_reader,):
            raise MatchweekResearchError("Unsupported causal selection version.")

        logical = selection_manifest.matchweek_id.value
        if store.snapshot_manifest_digest_for_snapshot(selection_slot(logical)) != selection_digest:
            raise MatchweekResearchError("Selection is not the exact indexed logical winner.")
        receipt_digest = store.snapshot_manifest_digest_for_snapshot(completion_slot(logical))
        if receipt_digest is None:
            raise MatchweekResearchError("Selection has no exact completion receipt.")

        f16_refs = tuple(
            ref
            for ref in selection_manifest.artifacts
            if ref.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        )
        if len(f16_refs) != 1:
            raise MatchweekResearchError("Selection must identify one causal F16 manifest.")

        # This exact stage replay resolves the candidate and its engine contract
        # before _replay() performs the witness-to-T chronology comparison.
        manifest = F16MatchweekProcessor(store).replay_manifest(f16_refs[0].digest)
        manifest_value = manifest.to_dict()
        candidate_digest = manifest_value.get("candidate_contract_digest")
        if not isinstance(candidate_digest, str):
            raise MatchweekResearchError("Selected causal F16 lacks its candidate contract.")
        candidate = resolve(store, candidate_digest)
        if candidate.contract_version != CAUSAL_CONTRACT:
            raise MatchweekResearchError("Unsupported selected candidate contract.")
        if (
            candidate.freeze_id,
            candidate.cutoff_policy_digest,
            candidate.profile_digest,
            candidate.decision_policy_digest,
        ) != (
            manifest_value.get("freeze_id"),
            manifest_value.get("cutoff_policy_digest"),
            manifest_value.get("profile_digest"),
            manifest_value.get("policy_digest"),
        ):
            raise MatchweekResearchError("Selected candidate contract differs from exact F16.")

        qualified = owner.replay(selection_digest)
        if (
            qualified.completion_receipt_digest != receipt_digest
            or qualified.f16_manifest_digest != manifest.digest
            or qualified.freeze_id != candidate.freeze_id
            or qualified.policy_digest != candidate.cutoff_policy_digest
            or qualified.cutoff_at_utc != candidate.cutoff_at_utc
        ):
            raise MatchweekResearchError("Qualified owner state differs from exact causal graph.")
        return QualifiedCausalSelection(qualified, candidate, selection_reader)
    except MatchweekResearchError:
        raise
    except (ArtifactError, F16Error, TypeError, ValueError, KeyError, AttributeError) as error:
        raise MatchweekResearchError("Exact causal qualification failed replay.") from error


def inspect_causal_selection(store: Store, selection_digest: str) -> InspectedCausalSelection:
    """Replay retained causal history without claiming present qualification."""
    owner = MatchweekResearchRepository(store)
    try:
        selection_manifest = owner._artifacts.verify_manifest(selection_digest)
        selection_reader = ManifestVersion.from_identity(_version_v2("selection"))
        if selection_manifest.versions != (selection_reader,):
            raise MatchweekResearchError("Unsupported causal selection version.")
        logical = selection_manifest.matchweek_id.value
        if store.snapshot_manifest_digest_for_snapshot(selection_slot(logical)) != selection_digest:
            raise MatchweekResearchError("Selection is not the exact indexed logical winner.")
        f16_refs = tuple(
            ref
            for ref in selection_manifest.artifacts
            if ref.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        )
        if len(f16_refs) != 1:
            raise MatchweekResearchError("Selection must identify one causal F16 manifest.")
        manifest = F16MatchweekProcessor(store).replay_manifest(f16_refs[0].digest)
        candidate_digest = manifest.to_dict().get("candidate_contract_digest")
        if not isinstance(candidate_digest, str):
            raise MatchweekResearchError("Selected causal F16 lacks its candidate contract.")
        candidate = resolve(store, candidate_digest)
        inspected = owner.inspect_causal(selection_digest)
        if inspected.f16_manifest_digest != manifest.digest or (
            inspected.freeze_id,
            inspected.policy_digest,
            inspected.cutoff_at_utc,
        ) != (
            candidate.freeze_id,
            candidate.cutoff_policy_digest,
            candidate.cutoff_at_utc,
        ):
            raise MatchweekResearchError("Inspected owner state differs from exact causal graph.")
        return InspectedCausalSelection(inspected, candidate, selection_reader)
    except MatchweekResearchError:
        raise
    except (ArtifactError, F16Error, TypeError, ValueError, KeyError, AttributeError) as error:
        raise MatchweekResearchError("Exact historical causal inspection failed replay.") from error

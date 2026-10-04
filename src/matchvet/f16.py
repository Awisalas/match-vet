"""Durable per-membership orchestration for the F11 to F14 V2 pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.f11 import F11Error, F11EvidenceRepository
from matchvet.f13 import F13Error, ModelContractRepository
from matchvet.f14 import (
    DecisionInputBundle,
    DecisionRepository,
    DecisionResult,
    F14Error,
    PreferenceProfileRepository,
)
from matchvet.match_evidence_cutoff import (
    MatchEvidenceCutoff,
    MatchEvidenceCutoffError,
    MatchEvidenceCutoffRepository,
)
from matchvet.matchweek_membership import MatchweekMembershipFreeze, canonical_json
from matchvet.matchweek_membership_repository import (
    MatchweekMembershipIntegrityError,
    MatchweekMembershipRepository,
)
from matchvet.runs import RunPhase, WorkContext, WorkInterrupted, WorkResult
from matchvet.store import Store
from matchvet.t15 import PolicyStatus, PolicyVersion

MATCH_RESULT_MEDIA_TYPE = "application/vnd.matchvet.f16-match-result.v1+json"
MANIFEST_MEDIA_TYPE = "application/vnd.matchvet.f16-processing-manifest.v1+json"
SCHEMA_VERSION = 1


class F16Error(ValueError):
    """An F16 input, match result, or manifest failed exact replay."""


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class F16MatchResult:
    """Exact immutable references for one INCLUDED membership."""

    membership_id: str
    membership_digest: str
    cutoff_id: str
    cutoff_digest: str
    evidence_digest: str
    model_digest: str
    decision_digest: str
    match_result_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "membership_id": self.membership_id,
            "membership_digest": self.membership_digest,
            "cutoff_id": self.cutoff_id,
            "cutoff_digest": self.cutoff_digest,
            "evidence_digest": self.evidence_digest,
            "model_digest": self.model_digest,
            "decision_digest": self.decision_digest,
            "match_result_digest": self.match_result_digest,
        }


@dataclass(frozen=True)
class F16Manifest:
    canonical_bytes: bytes

    @property
    def digest(self) -> str:
        return _digest(self.canonical_bytes)

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical_bytes))

    @property
    def match_results(self) -> tuple[F16MatchResult, ...]:
        rows = self.to_dict()["matches"]
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise F16Error("F16 manifest match results are malformed.")
        return tuple(F16MatchResult(**cast(dict[str, str], row)) for row in rows)


class F16MatchweekProcessor:
    """Coordinate exact per-match F11/F13/F14 artifacts and their F16 manifest."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)

    def process_phase(
        self,
        context: WorkContext,
        *,
        freeze_id: str,
        cutoff_policy_digest: str,
        cutoff_ids: tuple[str, ...],
        profile_digest: str,
        policy: PolicyVersion,
    ) -> WorkResult:
        freeze = MatchweekMembershipRepository(self.store).get_by_id(freeze_id)
        if freeze is None:
            raise F16Error("Exact F06 freeze is missing.")
        cutoffs = tuple(
            MatchEvidenceCutoffRepository(self.store).replay(cutoff_id) for cutoff_id in cutoff_ids
        )
        self._validate_memberships(freeze, cutoffs, cutoff_policy_digest)
        PreferenceProfileRepository(self.store).replay(profile_digest)
        exact_policy = PolicyVersion.from_mapping(policy.to_dict())
        if (
            exact_policy.mode is not PolicyStatus.RESEARCH_ONLY
            or exact_policy.digest != policy.digest
        ):
            raise F16Error("F16 requires the exact RESEARCH_ONLY policy version.")

        if context.phase is RunPhase.EVIDENCE_ACQUISITION:
            evidence = F11EvidenceRepository(self.store).build_or_replay_for_freeze(
                freeze_id, cutoff_policy_digest
            )
            return WorkResult(evidence.digest, (evidence.digest,))

        if context.phase is RunPhase.FROZEN_EVIDENCE_STATE:
            evidence = F11EvidenceRepository(self.store).build_or_replay_for_freeze(
                freeze_id, cutoff_policy_digest
            )
            model_digests = self._build_models(evidence.digest, cutoffs)
            return WorkResult(_digest(_bytes(model_digests)), model_digests)

        if context.phase is RunPhase.PREFERENCE_VETTING:
            evidence = F11EvidenceRepository(self.store).build_or_replay_for_freeze(
                freeze_id, cutoff_policy_digest
            )
            manifest = self._build_decisions(
                freeze=freeze,
                cutoffs=cutoffs,
                evidence_digest=evidence.digest,
                profile_digest=profile_digest,
                policy=exact_policy,
            )
            value = manifest.to_dict()
            digests = {
                manifest.digest,
                *(row["model_digest"] for row in value["matches"]),
                *(row["decision_digest"] for row in value["matches"]),
                *(row["evidence_digest"] for row in value["matches"]),
                *(row["match_result_digest"] for row in value["matches"]),
            }
            return WorkResult(manifest.digest, tuple(sorted(digests)))

        if context.phase is RunPhase.ADVERSARIAL_REVIEW:
            audit_manifest = self._find_manifest(
                freeze.freeze_digest, cutoff_policy_digest, profile_digest, exact_policy
            )
            if audit_manifest is None:
                raise F16Error("F16 manifest is missing before adversarial review checkpoint.")
            self.artifacts.verify_artifact(audit_manifest.digest)
            return WorkResult(audit_manifest.digest, (audit_manifest.digest,))

        if context.phase is RunPhase.AUDIT_VERIFICATION:
            audit_manifest = self._find_manifest(
                freeze.freeze_digest, cutoff_policy_digest, profile_digest, exact_policy
            )
            if audit_manifest is None:
                raise F16Error("F16 manifest is missing at audit verification.")
            self.artifacts.verify_artifact(audit_manifest.digest)
            raise WorkInterrupted("F16 is durable; F17 owns audit verification and publication.")

        return WorkResult.for_phase(context.phase)

    def completed_artifact_identities(
        self,
        *,
        freeze_id: str,
        cutoff_policy_digest: str,
        profile_digest: str,
        policy: PolicyVersion,
    ) -> tuple[str, ...]:
        freeze = MatchweekMembershipRepository(self.store).get_by_id(freeze_id)
        if freeze is None:
            return ()
        identities: set[str] = set()
        manifest_digests: list[str] = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type == MANIFEST_MEDIA_TYPE:
                try:
                    value = self._read(metadata.digest, MANIFEST_MEDIA_TYPE)
                    self.artifacts.verify_artifact(metadata.digest)
                except F16Error, ArtifactError:
                    continue
                if (
                    value["freeze_digest"],
                    value["cutoff_policy_digest"],
                    value["profile_digest"],
                    value["policy_digest"],
                ) == (
                    freeze.freeze_digest,
                    cutoff_policy_digest,
                    profile_digest,
                    policy.digest,
                ):
                    manifest_digests.append(metadata.digest)
                    identities.add(
                        f"F16_MANIFEST:{metadata.artifact_id.value}:sha256:{metadata.digest}"
                    )
        if len(manifest_digests) > 1:
            raise F16Error("Conflicting F16 manifests name the same immutable inputs.")
        if manifest_digests:
            manifest = self.replay_manifest(manifest_digests[0])
            identities = set()
            for row in manifest.match_results:
                child_metadata = self.store.artifact_metadata(row.match_result_digest)
                if child_metadata is None:
                    raise F16Error(
                        "Verified F16 match result disappeared from the artifact catalog."
                    )
                identities.add(
                    f"F16_MATCH:{row.membership_id}:{child_metadata.artifact_id.value}:"
                    f"sha256:{row.match_result_digest}"
                )
            manifest_metadata = self.store.artifact_metadata(manifest_digests[0])
            if manifest_metadata is None:
                raise F16Error("Verified F16 manifest disappeared from the artifact catalog.")
            identities.add(
                f"F16_MANIFEST:{manifest_metadata.artifact_id.value}:sha256:{manifest_digests[0]}"
            )
        return tuple(sorted(identities))

    def replay_manifest(self, digest: str) -> F16Manifest:
        value = self._read(digest, MANIFEST_MEDIA_TYPE)
        try:
            manifest = F16Manifest(_bytes(value))
            if (
                manifest.digest != digest
                or value.get("schema_version") != SCHEMA_VERSION
                or value.get("status") != "RESEARCH_ONLY"
                or set(value)
                != {
                    "schema_version",
                    "status",
                    "freeze_id",
                    "freeze_digest",
                    "cutoff_policy_digest",
                    "profile_digest",
                    "policy_digest",
                    "policy",
                    "matches",
                }
            ):
                raise F16Error("F16 manifest identity or schema is invalid.")
            typed_rows = [row.to_dict() for row in manifest.match_results]
            if typed_rows != value["matches"]:
                raise F16Error("F16 manifest match result schema is invalid.")
            freeze = MatchweekMembershipRepository(self.store).get_by_id(value["freeze_id"])
            if freeze is None or freeze.freeze_digest != value["freeze_digest"]:
                raise F16Error("F16 manifest does not reference the exact F06 freeze.")
            cutoff_repository = MatchEvidenceCutoffRepository(self.store)
            policy = PolicyVersion.from_mapping(value["policy"])
            if (
                policy.mode is not PolicyStatus.RESEARCH_ONLY
                or policy.digest != value["policy_digest"]
            ):
                raise F16Error("F16 manifest policy is not its exact RESEARCH_ONLY policy.")
            PreferenceProfileRepository(self.store).replay(value["profile_digest"])
            included = {
                row.membership_id: row
                for row in freeze.memberships
                if row.decision.value == "INCLUDED"
            }
            rows = typed_rows
            if not isinstance(rows, list) or len(rows) != len(included):
                raise F16Error("F16 manifest does not cover every INCLUDED membership once.")
            if [row.get("membership_id") for row in rows if isinstance(row, dict)] != sorted(
                included
            ):
                raise F16Error("F16 manifest membership rows are not in canonical order.")
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise F16Error("Malformed F16 manifest membership row.")
                membership_id = row["membership_id"]
                member = included.get(membership_id)
                if member is None or membership_id in seen:
                    raise F16Error(
                        "F16 manifest has missing, duplicate, or non-INCLUDED membership."
                    )
                seen.add(membership_id)
                cutoff = cutoff_repository.replay(row["cutoff_id"])
                if (
                    row["membership_digest"],
                    row["cutoff_digest"],
                    cutoff.membership_id,
                    cutoff.membership_digest,
                    cutoff.fixture_id,
                    cutoff.freeze_digest,
                    cutoff.policy_digest,
                ) != (
                    member.membership_digest,
                    cutoff.digest,
                    member.membership_id,
                    member.membership_digest,
                    member.fixture_id,
                    freeze.freeze_digest,
                    value["cutoff_policy_digest"],
                ):
                    raise F16Error("F16 manifest cutoff differs from exact F06/F07 lineage.")
                child = self._replay_match_result(row["match_result_digest"])
                for key in (
                    "membership_id",
                    "membership_digest",
                    "cutoff_id",
                    "cutoff_digest",
                    "evidence_digest",
                    "model_digest",
                    "decision_digest",
                ):
                    if child.get(key) != row[key]:
                        raise F16Error("F16 manifest child lineage differs from its row.")
                if (
                    child.get("freeze_id"),
                    child.get("freeze_digest"),
                    child.get("cutoff_policy_digest"),
                    child.get("profile_digest"),
                    child.get("policy_digest"),
                ) != (
                    freeze.freeze_id,
                    freeze.freeze_digest,
                    value["cutoff_policy_digest"],
                    value["profile_digest"],
                    value["policy_digest"],
                ):
                    raise F16Error("F16 match result differs from exact manifest inputs.")
            if seen != set(included):
                raise F16Error("F16 manifest membership coverage is incomplete.")
            return manifest
        except F16Error:
            raise
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            F11Error,
            F13Error,
            F14Error,
            MatchEvidenceCutoffError,
            MatchweekMembershipIntegrityError,
        ) as error:
            raise F16Error("Malformed or invalid F16 manifest lineage.") from error

    def _build_models(
        self, evidence_digest: str, cutoffs: tuple[MatchEvidenceCutoff, ...]
    ) -> tuple[str, ...]:
        repository = ModelContractRepository(self.store)
        models = [
            repository.build_from_retained_history(evidence_digest, cutoff.cutoff_id)
            for cutoff in sorted(cutoffs, key=lambda item: item.membership_id)
        ]
        return tuple(sorted({item.digest for item in models}))

    def _build_decisions(
        self,
        *,
        freeze: MatchweekMembershipFreeze,
        cutoffs: tuple[MatchEvidenceCutoff, ...],
        evidence_digest: str,
        profile_digest: str,
        policy: PolicyVersion,
    ) -> F16Manifest:
        memberships = {m.membership_id: m for m in freeze.memberships}
        model_repository = ModelContractRepository(self.store)
        decision_repository = DecisionRepository(self.store)
        rows = []
        for cutoff in sorted(cutoffs, key=lambda item: item.membership_id):
            model_digest = self._find_model_result(evidence_digest, cutoff.cutoff_id)
            if model_digest is None:
                model_digest = model_repository.build_from_retained_history(
                    evidence_digest, cutoff.cutoff_id
                ).digest
            bundle = DecisionInputBundle(
                profile_digest=profile_digest,
                evidence_digest=evidence_digest,
                cutoff_id=cutoff.cutoff_id,
                model_result_digest=model_digest,
                policy={**policy.to_dict(), "policy_digest": policy.digest},
                candidate_inputs={},
            )
            decision = self._build_or_replay_decision(decision_repository, bundle)
            member = memberships[cutoff.membership_id]
            child = {
                "schema_version": SCHEMA_VERSION,
                "status": "RESEARCH_ONLY",
                "freeze_id": freeze.freeze_id,
                "freeze_digest": freeze.freeze_digest,
                "cutoff_policy_digest": cutoff.policy_digest,
                "profile_digest": profile_digest,
                "policy_digest": policy.digest,
                "membership_id": member.membership_id,
                "membership_digest": member.membership_digest,
                "fixture_id": member.fixture_id,
                "cutoff_id": cutoff.cutoff_id,
                "cutoff_digest": cutoff.digest,
                "evidence_digest": evidence_digest,
                "model_digest": model_digest,
                "decision_digest": decision.digest,
                "outcome": decision.to_dict()["outcome"],
            }
            record = self.artifacts.publish_artifact(_bytes(child), MATCH_RESULT_MEDIA_TYPE)
            rows.append(
                F16MatchResult(
                    membership_id=member.membership_id,
                    membership_digest=member.membership_digest,
                    cutoff_id=cutoff.cutoff_id,
                    cutoff_digest=cutoff.digest,
                    evidence_digest=evidence_digest,
                    model_digest=model_digest,
                    decision_digest=decision.digest,
                    match_result_digest=record.digest,
                ).to_dict()
            )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "RESEARCH_ONLY",
            "freeze_id": freeze.freeze_id,
            "freeze_digest": freeze.freeze_digest,
            "cutoff_policy_digest": cutoffs[0].policy_digest if cutoffs else "",
            "profile_digest": profile_digest,
            "policy_digest": policy.digest,
            "policy": policy.to_dict(),
            "matches": rows,
        }
        content = _bytes(payload)
        record = self.artifacts.publish_artifact(content, MANIFEST_MEDIA_TYPE)
        return F16Manifest(content)

    def _find_manifest(
        self,
        freeze_digest: str,
        cutoff_policy_digest: str,
        profile_digest: str,
        policy: PolicyVersion,
    ) -> F16Manifest | None:
        matches = []
        for metadata in self.store.artifact_catalog():
            if metadata.media_type != MANIFEST_MEDIA_TYPE:
                continue
            value = self._read(metadata.digest, MANIFEST_MEDIA_TYPE)
            if (
                value.get("freeze_digest"),
                value.get("cutoff_policy_digest"),
                value.get("profile_digest"),
                value.get("policy_digest"),
            ) == (freeze_digest, cutoff_policy_digest, profile_digest, policy.digest):
                matches.append(metadata.digest)
        if len(matches) > 1:
            raise F16Error("Conflicting F16 manifests name the same immutable inputs.")
        return self.replay_manifest(matches[0]) if matches else None

    def _build_or_replay_decision(
        self, repository: DecisionRepository, bundle: DecisionInputBundle
    ) -> DecisionResult:
        return repository.build_or_replay_decision(bundle)

    def _find_model_result(self, evidence_digest: str, cutoff_id: str) -> str | None:
        return ModelContractRepository(self.store).retained_result_digest(
            evidence_digest, cutoff_id
        )

    def _validate_memberships(
        self,
        freeze: MatchweekMembershipFreeze,
        cutoffs: tuple[MatchEvidenceCutoff, ...],
        policy_digest: str,
    ) -> None:
        included = {
            member.membership_id: member
            for member in freeze.memberships
            if member.decision.value == "INCLUDED"
        }
        if len(cutoffs) != len(included) or {item.membership_id for item in cutoffs} != set(
            included
        ):
            raise F16Error("Exactly one F07 cutoff is required for each INCLUDED membership.")
        if any(
            item.freeze_digest != freeze.freeze_digest
            or item.policy_digest != policy_digest
            or item.membership_digest != included[item.membership_id].membership_digest
            or item.fixture_id != included[item.membership_id].fixture_id
            for item in cutoffs
        ):
            raise F16Error("F07 cutoff differs from the exact F06 membership or policy.")

    def _replay_match_result(self, digest: str) -> dict[str, Any]:
        value = self._read(digest, MATCH_RESULT_MEDIA_TYPE)
        try:
            if (
                value.get("schema_version") != SCHEMA_VERSION
                or value.get("status") != "RESEARCH_ONLY"
                or set(value)
                != {
                    "schema_version",
                    "status",
                    "freeze_id",
                    "freeze_digest",
                    "cutoff_policy_digest",
                    "profile_digest",
                    "policy_digest",
                    "membership_id",
                    "membership_digest",
                    "fixture_id",
                    "cutoff_id",
                    "cutoff_digest",
                    "evidence_digest",
                    "model_digest",
                    "decision_digest",
                    "outcome",
                }
            ):
                raise F16Error("Unsupported F16 match result.")
            cutoff = MatchEvidenceCutoffRepository(self.store).replay(value["cutoff_id"])
            if (
                cutoff.membership_id,
                cutoff.membership_digest,
                cutoff.fixture_id,
                cutoff.digest,
                cutoff.policy_digest,
            ) != (
                value["membership_id"],
                value["membership_digest"],
                value["fixture_id"],
                value["cutoff_digest"],
                value["cutoff_policy_digest"],
            ):
                raise F16Error("F16 match result cutoff lineage is invalid.")
            decision = DecisionRepository(self.store).replay(value["decision_digest"])
            if decision.to_dict()["outcome"] != value["outcome"]:
                raise F16Error("F16 outcome differs from its exact F14 decision.")
            lineage = decision.to_dict()["lineage"]
            if (
                lineage.get("profile_digest"),
                lineage.get("evidence_digest"),
                lineage.get("cutoff_id"),
                lineage.get("f13_model_result_digest"),
                lineage.get("t15_policy_digest"),
            ) != (
                value["profile_digest"],
                value["evidence_digest"],
                value["cutoff_id"],
                value["model_digest"],
                value["policy_digest"],
            ):
                raise F16Error("F14 decision differs from exact F16 lineage.")
            return value
        except F16Error:
            raise
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            F11Error,
            F13Error,
            F14Error,
            MatchEvidenceCutoffError,
        ) as error:
            raise F16Error("Malformed F16 match result lineage.") from error

    def _read(self, digest: str, media_type: str) -> dict[str, Any]:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            media_type,
            "PROTECTED",
        ):
            raise F16Error(f"Missing or invalid protected F16 artifact for {media_type}.")
        content = self.artifacts.read_artifact(digest)
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or _bytes(value) != content:
                raise F16Error("F16 artifact is malformed or noncanonical.")
            return value
        except (TypeError, ValueError) as error:
            raise F16Error("Malformed F16 artifact.") from error

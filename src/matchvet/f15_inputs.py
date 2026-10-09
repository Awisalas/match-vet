"""Reader-safe exact F15 input identity and candidate request reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from matchvet.artifacts import ArtifactError
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f13 import causal_engine_version_identity, engine_version_identity
from matchvet.f14 import F14Error, PreferenceProfileRepository
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import (
    MatchweekMembershipIntegrityError,
    MatchweekMembershipRepository,
)
from matchvet.matchweek_research import MatchweekResearchRepository
from matchvet.runs import RunInputContract
from matchvet.store import Store
from matchvet.t15 import PolicyStatus, PolicyValidationError, PolicyVersion


class AnalyzeMatchweekError(ValueError):
    """An exact immutable F15 predecessor could not be verified."""


@dataclass(frozen=True)
class AnalyzeMatchweekRequest:
    """Exact retained inputs that identify one V2 analysis attempt."""

    matchweek: str
    freeze_id: str
    cutoff_policy_digest: str
    cutoff_ids: tuple[str, ...]
    research_contract_digest: str
    model_version_identity: str
    preference_profile_digest: str
    policy: PolicyVersion
    candidate_contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.matchweek,
                self.freeze_id,
                self.cutoff_policy_digest,
                self.research_contract_digest,
                self.model_version_identity,
                self.preference_profile_digest,
            )
        ):
            raise ValueError("F15 request identities must be explicit non-empty strings.")
        if not self.cutoff_ids or tuple(sorted(set(self.cutoff_ids))) != self.cutoff_ids:
            raise ValueError("F15 cutoff IDs must be non-empty, sorted, and unique.")


def validate_run_inputs(
    store: Store, request: AnalyzeMatchweekRequest, *, research: MatchweekResearchRepository
) -> tuple[RunInputContract, tuple[str, ...]]:
    try:
        if request.candidate_contract_digest != research.candidate_contract_digest:
            raise AnalyzeMatchweekError(
                "F15 candidate descriptor differs from explicit constructor context."
            )
        research.validate_context(
            request.freeze_id,
            request.cutoff_policy_digest,
            profile_digest=request.preference_profile_digest,
            decision_policy_digest=request.policy.digest,
        )
        selection_policy = _validate_selection_policy(request.policy)
        freeze = MatchweekMembershipRepository(store).get_by_id(request.freeze_id)
        if freeze is None:
            raise AnalyzeMatchweekError("Exact F06 freeze is missing.")
        if freeze.matchweek_friday != request.matchweek:
            raise AnalyzeMatchweekError("F06 freeze does not match requested Matchweek.")
        cutoff_repository = MatchEvidenceCutoffRepository(store)
        policy = cutoff_repository.read_policy(request.cutoff_policy_digest)
        cutoffs = tuple(cutoff_repository.replay(cutoff_id) for cutoff_id in request.cutoff_ids)
        if any(
            cutoff.freeze_id != freeze.freeze_id
            or cutoff.freeze_digest != freeze.freeze_digest
            or cutoff.policy_digest != request.cutoff_policy_digest
            for cutoff in cutoffs
        ):
            raise AnalyzeMatchweekError("F07 cutoffs do not match the exact F06 freeze and policy.")
        included_ids = {
            member.membership_id
            for member in freeze.memberships
            if member.decision.value == "INCLUDED"
        }
        if (
            len(cutoffs) != len(included_ids)
            or {cutoff.membership_id for cutoff in cutoffs} != included_ids
        ):
            raise AnalyzeMatchweekError(
                "Exactly one supplied F07 cutoff is required for every INCLUDED F06 membership."
            )
        if policy.lead_time_seconds is None:
            raise AnalyzeMatchweekError("F07 cutoff policy is not configured.")
        if request.research_contract_digest != V2_REQUIREMENT_CATALOG.digest:
            raise AnalyzeMatchweekError("F10 research contract is unsupported or changed.")
        expected_engine = (
            causal_engine_version_identity()
            if request.candidate_contract_digest is not None
            else engine_version_identity()
        )
        if request.model_version_identity != expected_engine:
            raise AnalyzeMatchweekError("F13 engine version identity is unsupported or changed.")
        PreferenceProfileRepository(store).replay(request.preference_profile_digest)
        artifact_digests = tuple(
            sorted(
                {
                    request.cutoff_policy_digest,
                    request.preference_profile_digest,
                    *(cutoff.digest.removeprefix("sha256:") for cutoff in cutoffs),
                }
            )
        )
        predecessor_digests = tuple(
            sorted(
                {
                    freeze.freeze_digest.removeprefix("sha256:"),
                    request.cutoff_policy_digest,
                    request.research_contract_digest,
                    request.preference_profile_digest,
                    selection_policy.digest,
                    *(cutoff.digest.removeprefix("sha256:") for cutoff in cutoffs),
                }
            )
        )
        if request.candidate_contract_digest is not None:
            artifact_digests = tuple(sorted({*artifact_digests, request.candidate_contract_digest}))
            predecessor_digests = tuple(
                sorted({*predecessor_digests, request.candidate_contract_digest})
            )
        values = {
            "source": "F06:" + freeze.freeze_digest,
            "cutoff": "F07:" + request.cutoff_policy_digest + ":" + ",".join(request.cutoff_ids),
            "preference_set": "F14:" + request.preference_profile_digest,
            "policy": "T15_POLICY:" + selection_policy.version + ":" + selection_policy.digest,
            "model": "F13_ENGINE:" + request.model_version_identity,
            "feature": "F13_ENGINE_VERSION_IDENTITY_V1",
            "research_rule": "F10:" + request.research_contract_digest,
            "canonical_contract": "MATCHVET_V2_ANALYZE_MATCHWEEK_V1",
            "schema": "T04_SCHEMA:" + str(store.status.schema_version),
            "environment": "MATCHVET_F15_INTERNAL",
            "software": "MATCHVET_F15_V1",
        }
        if request.candidate_contract_digest is not None:
            from matchvet.causal_candidate import RUN_CONTRACT

            values.update(
                canonical_contract=RUN_CONTRACT + ":" + request.candidate_contract_digest,
                feature="F13_ENGINE_VERSION_IDENTITY_V3",
                software="MATCHVET_F15_CAUSAL_V2",
            )
        return (
            RunInputContract.from_values(
                values,
                artifact_digests=artifact_digests,
                predecessor_digests=predecessor_digests,
            ),
            tuple(
                sorted(
                    {
                        "F06:" + freeze.freeze_digest,
                        "F07_POLICY:" + request.cutoff_policy_digest,
                        "F10:" + request.research_contract_digest,
                        "T15_POLICY:" + selection_policy.digest,
                        "F13_ENGINE:" + request.model_version_identity,
                        "F14:" + request.preference_profile_digest,
                        *("F07_CUTOFF:" + cutoff.digest for cutoff in cutoffs),
                    }
                )
            ),
        )
    except AnalyzeMatchweekError:
        raise
    except (
        ArtifactError,
        MatchEvidenceCutoffError,
        MatchweekMembershipIntegrityError,
        F14Error,
        PolicyValidationError,
        ValueError,
    ) as error:
        raise AnalyzeMatchweekError(
            "An exact immutable F15 predecessor is missing, corrupt, or incompatible."
        ) from error


def _validate_selection_policy(value: object) -> PolicyVersion:
    if not isinstance(value, PolicyVersion):
        raise AnalyzeMatchweekError("F15 requires a valid T15 Selection Policy Version.")
    try:
        policy = PolicyVersion.from_mapping(value.to_dict())
    except (PolicyValidationError, TypeError, ValueError) as error:
        raise AnalyzeMatchweekError("F15 Selection Policy Version is malformed.") from error
    if policy.mode is not PolicyStatus.RESEARCH_ONLY:
        raise AnalyzeMatchweekError("F15 V2 requires a RESEARCH_ONLY Selection Policy Version.")
    return policy


def request_from_candidate(store: Store, candidate_digest: str) -> AnalyzeMatchweekRequest:
    """Resolve exact stored identity for inspection; this helper cannot write."""
    import json

    from matchvet.artifacts import ArtifactStore

    candidate = MatchweekResearchRepository(store).resolve_candidate(candidate_digest)
    freeze = MatchweekMembershipRepository(store).get_by_id(candidate.freeze_id)
    assert freeze is not None
    cutoffs = MatchEvidenceCutoffRepository(store).replay_for_freeze(
        candidate.freeze_id, candidate.cutoff_policy_digest
    )
    return AnalyzeMatchweekRequest(
        freeze.matchweek_friday,
        candidate.freeze_id,
        candidate.cutoff_policy_digest,
        tuple(sorted(c.cutoff_id for c in cutoffs)),
        V2_REQUIREMENT_CATALOG.digest,
        candidate.engine_version,
        candidate.profile_digest,
        PolicyVersion.from_mapping(
            json.loads(
                ArtifactStore(store).read_artifact(candidate.decision_policy_artifact_digest)
            )
        ),
        candidate_contract_digest=candidate_digest,
    )

"""Internal V2 Matchweek analysis entry point over the existing T04 lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from matchvet.artifacts import ArtifactError
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f13 import engine_version_identity
from matchvet.f14 import F14Error, PreferenceProfileRepository
from matchvet.f16 import F16Error, F16MatchweekProcessor
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import (
    MatchweekMembershipIntegrityError,
    MatchweekMembershipRepository,
)
from matchvet.matchweek_research import MatchweekResearchRepository, TrustedUTCClock
from matchvet.runs import (
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunLifecycleError,
    RunPhase,
    RunState,
    RunStatus,
    WorkContext,
    WorkResult,
    default_resource_estimate,
    observe_resources,
    read_run_status,
)
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


@dataclass(frozen=True)
class AnalysisProgress:
    """Durable T04 state and retained artifact identities, without embedded results."""

    run_id: str
    run_state: RunState
    phase: RunPhase
    analysis_state: str
    durable_result_identities: tuple[str, ...]
    analysis_complete: bool
    matchweek_result_identity: str | None
    t04_status: RunStatus


class _AnalyzeExecutor:
    """Run F16 inside the existing T04 phase boundaries."""

    def __init__(
        self,
        store: Store,
        request: AnalyzeMatchweekRequest,
        clock: TrustedUTCClock | None,
        legacy_research: bool,
    ) -> None:
        self._processor = F16MatchweekProcessor(store, clock=clock, legacy_research=legacy_research)
        self._request = request

    def __call__(self, context: WorkContext) -> WorkResult:
        return self._processor.process_phase(
            context,
            freeze_id=self._request.freeze_id,
            cutoff_policy_digest=self._request.cutoff_policy_digest,
            cutoff_ids=self._request.cutoff_ids,
            profile_digest=self._request.preference_profile_digest,
            policy=_validate_selection_policy(self._request.policy),
        )


class AnalyzeMatchweek:
    """Validate exact V2 predecessors and coordinate one T04-backed run."""

    def __init__(
        self, store: Store, *, clock: TrustedUTCClock | None = None, legacy_research: bool = False
    ) -> None:
        self._store = store
        self._clock = clock
        self._legacy_research = legacy_research
        self.research = MatchweekResearchRepository(store, clock=clock)
        self._coordinator = RunCoordinator(store)

    def start(self, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        inputs, verified_ids = self._inputs(request)
        selected = self.research.selected_for_boundary(
            request.freeze_id, request.cutoff_policy_digest
        )
        if selected is not None:
            rows = (
                self._store._connection_for_repository()
                .execute(
                    "SELECT run_id FROM research_runs WHERE matchweek = ? AND input_digest = ?",
                    (request.matchweek, inputs.aggregate_digest),
                )
                .fetchall()
            )
            if len(rows) != 1:
                raise AnalyzeMatchweekError(
                    "Exact selected F16 replay requires an existing run ID."
                )
            return self.inspect(str(rows[0][0]), request)
        if not self._legacy_research and not self.research.is_corrected(
            request.cutoff_policy_digest
        ):
            raise AnalyzeMatchweekError("Prospective F15 requires the corrected F07 rule.")
        self.research.require_candidate_contract(
            request.freeze_id,
            request.cutoff_policy_digest,
            request.preference_profile_digest,
            request.policy.digest,
        )
        try:
            status = self._coordinator.start(
                matchweek=request.matchweek,
                inputs=inputs,
                estimate=default_resource_estimate(),
                observation=_observation(self._store),
                executor=_AnalyzeExecutor(self._store, request, self._clock, self._legacy_research),
            )
        except RunLifecycleError as error:
            if error.error.code == "MV-RUN-RESUME_REQUIRED":
                status = read_run_status(self._store.path, self._store.path.parent, error.run_id)
                return self._progress(status, verified_ids, request)
            if error.run_id:
                status = read_run_status(self._store.path, self._store.path.parent, error.run_id)
                if error.error.code == "MV-RUN-INTERRUPTED":
                    return self._progress(status, verified_ids, request)
            raise
        return self._progress(status, verified_ids, request)

    def inspect(self, run_id: str, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        inputs, verified_ids = self._inputs(request)
        status = read_run_status(self._store.path, self._store.path.parent, run_id)
        if status.input_digest != inputs.aggregate_digest:
            raise AnalyzeMatchweekError("T04 run identity does not match the supplied F15 request.")
        return self._progress(status, verified_ids, request)

    def resume(self, run_id: str, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        if not run_id:
            raise ValueError("An exact T04 run ID is required.")
        inputs, verified_ids = self._inputs(request)
        if (
            self.research.selected_for_boundary(request.freeze_id, request.cutoff_policy_digest)
            is not None
        ):
            return self.inspect(run_id, request)
        if not self._legacy_research and not self.research.is_corrected(
            request.cutoff_policy_digest
        ):
            raise AnalyzeMatchweekError("Prospective F15 requires the corrected F07 rule.")
        self.research.require_candidate_contract(
            request.freeze_id,
            request.cutoff_policy_digest,
            request.preference_profile_digest,
            request.policy.digest,
        )
        try:
            status = self._coordinator.resume(
                run_id,
                inputs=inputs,
                estimate=default_resource_estimate(),
                observation=_observation(self._store),
                executor=_AnalyzeExecutor(self._store, request, self._clock, self._legacy_research),
            )
        except RunLifecycleError as error:
            if error.error.code != "MV-RUN-INTERRUPTED":
                raise
            status = read_run_status(self._store.path, self._store.path.parent, run_id)
        return self._progress(status, verified_ids, request)

    def _inputs(self, request: AnalyzeMatchweekRequest) -> tuple[RunInputContract, tuple[str, ...]]:
        try:
            selection_policy = _validate_selection_policy(request.policy)
            freeze = MatchweekMembershipRepository(self._store).get_by_id(request.freeze_id)
            if freeze is None:
                raise AnalyzeMatchweekError("Exact F06 freeze is missing.")
            if freeze.matchweek_friday != request.matchweek:
                raise AnalyzeMatchweekError("F06 freeze does not match requested Matchweek.")
            cutoff_repository = MatchEvidenceCutoffRepository(self._store)
            policy = cutoff_repository.read_policy(request.cutoff_policy_digest)
            cutoffs = tuple(cutoff_repository.replay(cutoff_id) for cutoff_id in request.cutoff_ids)
            if any(
                cutoff.freeze_id != freeze.freeze_id
                or cutoff.freeze_digest != freeze.freeze_digest
                or cutoff.policy_digest != request.cutoff_policy_digest
                for cutoff in cutoffs
            ):
                raise AnalyzeMatchweekError(
                    "F07 cutoffs do not match the exact F06 freeze and policy."
                )
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
            if request.model_version_identity != engine_version_identity():
                raise AnalyzeMatchweekError(
                    "F13 engine version identity is unsupported or changed."
                )
            PreferenceProfileRepository(self._store).replay(request.preference_profile_digest)
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
            values = {
                "source": "F06:" + freeze.freeze_digest,
                "cutoff": "F07:"
                + request.cutoff_policy_digest
                + ":"
                + ",".join(request.cutoff_ids),
                "preference_set": "F14:" + request.preference_profile_digest,
                "policy": "T15_POLICY:" + selection_policy.version + ":" + selection_policy.digest,
                "model": "F13_ENGINE:" + request.model_version_identity,
                "feature": "F13_ENGINE_VERSION_IDENTITY_V1",
                "research_rule": "F10:" + request.research_contract_digest,
                "canonical_contract": "MATCHVET_V2_ANALYZE_MATCHWEEK_V1",
                "schema": "T04_SCHEMA:" + str(self._store.status.schema_version),
                "environment": "MATCHVET_F15_INTERNAL",
                "software": "MATCHVET_F15_V1",
            }
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
            F16Error,
            PolicyValidationError,
            ValueError,
        ) as error:
            raise AnalyzeMatchweekError(
                "An exact immutable F15 predecessor is missing, corrupt, or incompatible."
            ) from error

    def _progress(
        self,
        status: RunStatus,
        identities: tuple[str, ...],
        request: AnalyzeMatchweekRequest,
    ) -> AnalysisProgress:
        f16_identities = F16MatchweekProcessor(self._store).completed_artifact_identities(
            freeze_id=request.freeze_id,
            cutoff_policy_digest=request.cutoff_policy_digest,
            profile_digest=request.preference_profile_digest,
            policy=_validate_selection_policy(request.policy),
        )
        all_identities = tuple(sorted(set(identities) | set(f16_identities)))
        complete = status.phase is RunPhase.AUDIT_VERIFICATION and any(
            item.startswith("F16_MANIFEST:") for item in f16_identities
        )
        return AnalysisProgress(
            run_id=status.run_id,
            run_state=status.state,
            phase=status.phase,
            analysis_state="F16_COMPLETE_AWAITING_F17" if complete else "IN_PROGRESS",
            durable_result_identities=all_identities,
            analysis_complete=False,
            matchweek_result_identity=None,
            t04_status=status,
        )


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


def _observation(store: Store) -> ResourceObservation:
    observed = observe_resources(store.path)
    return ResourceObservation(
        managed_storage_bytes=observed.managed_storage_bytes,
        free_space_bytes=observed.free_space_bytes,
        available_memory_bytes=observed.available_memory_bytes,
        available_cpus=observed.available_cpus,
        memory_pressure=observed.memory_pressure,
        thermal_pressure=observed.thermal_pressure,
        active_coordinators=0,
    )

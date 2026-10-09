"""Internal V2 Matchweek analysis entry point over the existing T04 lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from matchvet.f15_inputs import (
    AnalyzeMatchweekError as AnalyzeMatchweekError,
)
from matchvet.f15_inputs import (
    AnalyzeMatchweekRequest as AnalyzeMatchweekRequest,
)
from matchvet.f15_inputs import (
    _validate_selection_policy,
    validate_run_inputs,
)
from matchvet.f16 import F16MatchweekProcessor
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
        self._processor = F16MatchweekProcessor(
            store,
            clock=clock,
            legacy_research=legacy_research,
            candidate_contract_digest=request.candidate_contract_digest,
        )
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
        self,
        store: Store,
        *,
        clock: TrustedUTCClock | None = None,
        legacy_research: bool = False,
        candidate_contract_digest: str | None = None,
        selection_contract: str | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._legacy_research = legacy_research
        self.candidate_contract_digest = candidate_contract_digest
        self.research = MatchweekResearchRepository(
            store,
            clock=clock,
            candidate_contract_digest=candidate_contract_digest,
            selection_contract=selection_contract,
        )

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
        self._coordinator = self._guarded_coordinator(request)
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
        if request.candidate_contract_digest is not None:
            status = read_run_status(self._store.path, self._store.path.parent, run_id)
            if status.input_digest != inputs.aggregate_digest:
                raise AnalyzeMatchweekError(
                    "Changed candidate context cannot resume an existing run."
                )
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
        self._coordinator = self._guarded_coordinator(request)
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
        return validate_run_inputs(self._store, request, research=self.research)

    def _guarded_coordinator(self, request: AnalyzeMatchweekRequest) -> RunCoordinator:
        guard = self.research.candidate_run_guard(
            request.freeze_id,
            request.cutoff_policy_digest,
            contract=(request.preference_profile_digest, request.policy.digest),
        )
        return RunCoordinator(self._store, write_guard=guard)

    def _progress(
        self,
        status: RunStatus,
        identities: tuple[str, ...],
        request: AnalyzeMatchweekRequest,
    ) -> AnalysisProgress:
        f16_identities = F16MatchweekProcessor(
            self._store, candidate_contract_digest=self.candidate_contract_digest
        ).completed_artifact_identities(
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

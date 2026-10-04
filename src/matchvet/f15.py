"""Internal V2 Matchweek analysis entry point over the existing T04 lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from matchvet.artifacts import ArtifactError
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f13 import engine_version_identity
from matchvet.f14 import F14Error, PreferenceProfileRepository
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffError, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import (
    MatchweekMembershipIntegrityError,
    MatchweekMembershipRepository,
)
from matchvet.runs import (
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunLifecycleError,
    RunPhase,
    RunState,
    RunStatus,
    WorkContext,
    WorkInterrupted,
    WorkResult,
    default_resource_estimate,
    observe_resources,
    read_run_status,
)
from matchvet.store import Store


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
    """Durable T04 state and real retained identity references, without a match result."""

    run_id: str
    run_state: RunState
    phase: RunPhase
    analysis_state: str
    durable_result_identities: tuple[str, ...]
    analysis_complete: bool
    matchweek_result_identity: str | None
    t04_status: RunStatus


class _BoundaryExecutor:
    """Leave a durable incomplete T04 attempt until downstream work is implemented."""

    def __call__(self, context: WorkContext) -> WorkResult:
        del context
        raise WorkInterrupted("F15 awaits downstream Matchweek analysis work.")


class AnalyzeMatchweek:
    """Validate exact V2 predecessors and coordinate one T04-backed run."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._coordinator = RunCoordinator(store)

    def start(self, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        inputs, verified_ids = self._inputs(request)
        try:
            status = self._coordinator.start(
                matchweek=request.matchweek,
                inputs=inputs,
                estimate=default_resource_estimate(),
                observation=_observation(self._store),
                executor=_BoundaryExecutor(),
            )
        except RunLifecycleError as error:
            if error.error.code == "MV-RUN-RESUME_REQUIRED":
                status = read_run_status(self._store.path, self._store.path.parent, error.run_id)
                return self._progress(status, verified_ids)
            if error.run_id:
                status = read_run_status(self._store.path, self._store.path.parent, error.run_id)
                if error.error.code == "MV-RUN-INTERRUPTED":
                    return self._progress(status, verified_ids)
            raise
        return self._progress(status, verified_ids)

    def inspect(self, run_id: str, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        inputs, verified_ids = self._inputs(request)
        status = read_run_status(self._store.path, self._store.path.parent, run_id)
        if status.input_digest != inputs.aggregate_digest:
            raise AnalyzeMatchweekError("T04 run identity does not match the supplied F15 request.")
        return self._progress(status, verified_ids)

    def resume(self, run_id: str, request: AnalyzeMatchweekRequest) -> AnalysisProgress:
        if not run_id:
            raise ValueError("An exact T04 run ID is required.")
        inputs, verified_ids = self._inputs(request)
        try:
            status = self._coordinator.resume(
                run_id,
                inputs=inputs,
                estimate=default_resource_estimate(),
                observation=_observation(self._store),
                executor=_BoundaryExecutor(),
            )
        except RunLifecycleError as error:
            if error.error.code != "MV-RUN-INTERRUPTED":
                raise
            status = read_run_status(self._store.path, self._store.path.parent, run_id)
        return self._progress(status, verified_ids)

    def _inputs(self, request: AnalyzeMatchweekRequest) -> tuple[RunInputContract, tuple[str, ...]]:
        try:
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
                "policy": "F15:ANALYSIS_PENDING_DOWNSTREAM_OUTPUTS",
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
            ValueError,
        ) as error:
            raise AnalyzeMatchweekError(
                "An exact immutable F15 predecessor is missing, corrupt, or incompatible."
            ) from error

    @staticmethod
    def _progress(status: RunStatus, identities: tuple[str, ...]) -> AnalysisProgress:
        return AnalysisProgress(
            run_id=status.run_id,
            run_state=status.state,
            phase=status.phase,
            analysis_state="IN_PROGRESS",
            durable_result_identities=identities,
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

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import FrameType, MappingProxyType
from typing import Never, Protocol

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.store import MIGRATIONS, CanonicalIdentifier, InspectionStatus, Store, inspect_store

MIB = 1024 * 1024
GIB = 1024 * MIB
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

REQUIRED_IDENTITY_INPUTS = (
    "source",
    "cutoff",
    "preference_set",
    "policy",
    "model",
    "feature",
    "research_rule",
    "canonical_contract",
    "schema",
    "environment",
    "software",
)


class RunPhase(StrEnum):
    PREFLIGHT = "preflight"
    EVIDENCE_ACQUISITION = "evidence_acquisition_and_cutoff_classification"
    FROZEN_EVIDENCE_STATE = "frozen_evidence_state_construction"
    PREFERENCE_VETTING = "full_preference_set_vetting"
    ADVERSARIAL_REVIEW = "adversarial_review_gates_and_ranking"
    AUDIT_VERIFICATION = "audit_verification"
    ATOMIC_PUBLICATION = "atomic_report_and_audit_publication"


RUN_PHASES: tuple[RunPhase, ...] = tuple(RunPhase)


class RunState(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class ResourceBudget:
    managed_storage_cap_bytes: int = 1536 * MIB
    minimum_free_space_bytes: int = 3 * GIB
    target_memory_bytes: int = GIB
    absolute_memory_bytes: int = 1536 * MIB
    minimum_available_memory_bytes: int = 1536 * MIB
    target_duration_seconds: int = 7_200
    hard_duration_seconds: int = 14_400
    maximum_cpu_heavy_operations: int = 2
    reserved_cpus: int = 1
    routine_network_bytes: int = 250 * MIB
    historical_network_bytes: int = 2 * GIB

    @property
    def cleanup_trigger_bytes(self) -> int:
        return self.managed_storage_cap_bytes * 4 // 5

    @property
    def cleanup_target_bytes(self) -> int:
        return self.managed_storage_cap_bytes * 3 // 5


SETTLED_RESOURCE_BUDGET = ResourceBudget()


@dataclass(frozen=True)
class ResourceEstimate:
    storage_growth_bytes: int
    peak_memory_bytes: int
    duration_seconds: int
    network_bytes: int
    cpu_heavy_operations: int

    def __post_init__(self) -> None:
        if (
            min(
                self.storage_growth_bytes,
                self.peak_memory_bytes,
                self.duration_seconds,
                self.network_bytes,
            )
            < 0
        ):
            raise ValueError("Resource estimates cannot be negative.")
        if self.cpu_heavy_operations < 1:
            raise ValueError("A run requires at least one foreground CPU operation.")

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceObservation:
    managed_storage_bytes: int
    free_space_bytes: int
    available_memory_bytes: int
    available_cpus: int
    memory_pressure: bool
    thermal_pressure: bool
    active_coordinators: int

    def __post_init__(self) -> None:
        if (
            min(
                self.managed_storage_bytes,
                self.free_space_bytes,
                self.available_memory_bytes,
                self.active_coordinators,
            )
            < 0
        ):
            raise ValueError("Resource observations cannot be negative.")
        if self.available_cpus < 1:
            raise ValueError("At least one available CPU must be reported.")

    def as_dict(self) -> dict[str, int | bool]:
        return asdict(self)


@dataclass(frozen=True)
class RunError:
    status: str
    code: str
    explanation: str
    last_checkpoint: str
    reuse_state: str
    recovery_command: str
    checkpoint_at_utc: str | None = None


@dataclass(frozen=True)
class PreflightResult:
    accepted: bool
    budget: ResourceBudget
    cpu_concurrency: int
    warnings: tuple[str, ...]
    error: RunError | None = None


def _refusal(code: str, explanation: str, budget: ResourceBudget) -> PreflightResult:
    return PreflightResult(
        accepted=False,
        budget=budget,
        cpu_concurrency=0,
        warnings=(),
        error=RunError(
            status="REFUSED",
            code=code,
            explanation=explanation,
            last_checkpoint="none",
            reuse_state="NONE",
            recovery_command="matchvet run",
        ),
    )


def preflight_resources(
    estimate: ResourceEstimate,
    observation: ResourceObservation,
    budget: ResourceBudget = SETTLED_RESOURCE_BUDGET,
) -> PreflightResult:
    if observation.active_coordinators > 0:
        return _refusal(
            "MV-PREFLIGHT-COORDINATOR_BUSY",
            "Another foreground MatchVet coordinator is active.",
            budget,
        )
    if observation.managed_storage_bytes + estimate.storage_growth_bytes > (
        budget.managed_storage_cap_bytes
    ):
        return _refusal(
            "MV-PREFLIGHT-STORAGE_CAP",
            "Projected managed storage exceeds the 1.5 GiB normal cap.",
            budget,
        )
    if observation.free_space_bytes - estimate.storage_growth_bytes < (
        budget.minimum_free_space_bytes
    ):
        return _refusal(
            "MV-PREFLIGHT-FREE_SPACE",
            "Projected work would leave less than 3 GiB of device free space.",
            budget,
        )
    if estimate.peak_memory_bytes > budget.absolute_memory_bytes:
        return _refusal(
            "MV-PREFLIGHT-MEMORY_LIMIT",
            "Projected peak memory exceeds the 1.5 GiB absolute process budget.",
            budget,
        )
    if observation.available_memory_bytes < budget.minimum_available_memory_bytes:
        return _refusal(
            "MV-PREFLIGHT-AVAILABLE_MEMORY",
            "Available system memory is below the 1.5 GiB start threshold.",
            budget,
        )
    if estimate.duration_seconds > budget.hard_duration_seconds:
        return _refusal(
            "MV-PREFLIGHT-TIME_HARD_LIMIT",
            "Projected execution exceeds the four-hour hard limit.",
            budget,
        )
    if estimate.network_bytes > budget.routine_network_bytes:
        return _refusal(
            "MV-PREFLIGHT-NETWORK_LIMIT",
            "Projected routine network use exceeds 250 MiB.",
            budget,
        )
    if estimate.cpu_heavy_operations > budget.maximum_cpu_heavy_operations:
        return _refusal(
            "MV-PREFLIGHT-CONCURRENCY_LIMIT",
            "Projected CPU-heavy concurrency exceeds the two-operation limit.",
            budget,
        )

    warnings: list[str] = []
    projected_storage = observation.managed_storage_bytes + estimate.storage_growth_bytes
    if projected_storage >= budget.cleanup_trigger_bytes:
        warnings.append(
            "Projected storage reaches the 80% cleanup threshold; disposable cache cleanup "
            "should target 60% of the normal cap."
        )
    if estimate.peak_memory_bytes > budget.target_memory_bytes:
        warnings.append("Projected peak memory exceeds the 1 GiB target.")
    if estimate.duration_seconds > budget.target_duration_seconds:
        warnings.append("Projected execution exceeds the two-hour target.")
    cpu_capacity = max(1, observation.available_cpus - budget.reserved_cpus)
    concurrency = min(estimate.cpu_heavy_operations, cpu_capacity)
    if observation.memory_pressure or observation.thermal_pressure:
        concurrency = min(concurrency, 1)
        pressure = "memory pressure" if observation.memory_pressure else "thermal pressure"
        warnings.append(f"CPU concurrency reduced to one because of {pressure}.")
    elif concurrency < estimate.cpu_heavy_operations:
        warnings.append("CPU concurrency reduced to reserve one CPU for Android.")
    if estimate.peak_memory_bytes > budget.target_memory_bytes:
        concurrency = min(concurrency, 1)
    return PreflightResult(
        accepted=True,
        budget=budget,
        cpu_concurrency=concurrency,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class RunInputContract:
    identity_values: Mapping[str, str]
    digests: Mapping[str, str]
    artifact_digests: tuple[str, ...]
    predecessor_digests: tuple[str, ...]

    @classmethod
    def from_values(
        cls,
        identity_values: Mapping[str, str],
        *,
        artifact_digests: tuple[str, ...] = (),
        predecessor_digests: tuple[str, ...] = (),
    ) -> RunInputContract:
        missing = sorted(set(REQUIRED_IDENTITY_INPUTS) - set(identity_values))
        unexpected = sorted(set(identity_values) - set(REQUIRED_IDENTITY_INPUTS))
        if missing or unexpected:
            raise ValueError(
                f"Run input identities must be exact; missing={missing}; unexpected={unexpected}."
            )
        _require_digest_list(artifact_digests, "artifact")
        _require_digest_list(predecessor_digests, "predecessor")
        values = {name: str(identity_values[name]) for name in REQUIRED_IDENTITY_INPUTS}
        digests = {name: _sha256(values[name].encode()) for name in REQUIRED_IDENTITY_INPUTS}
        digests["artifacts"] = _sha256(_canonical_json(sorted(artifact_digests)))
        digests["predecessors"] = _sha256(_canonical_json(sorted(predecessor_digests)))
        return cls(
            identity_values=MappingProxyType(values),
            digests=MappingProxyType(digests),
            artifact_digests=tuple(sorted(artifact_digests)),
            predecessor_digests=tuple(sorted(predecessor_digests)),
        )

    @classmethod
    def from_stored_json(cls, value: str) -> RunInputContract:
        loaded: object = json.loads(value)
        if not isinstance(loaded, dict):
            raise ValueError("Stored run input contract must be an object.")
        identities = loaded.get("identity_values")
        artifacts = loaded.get("artifact_digests")
        predecessors = loaded.get("predecessor_digests")
        if not isinstance(identities, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in identities.items()
        ):
            raise ValueError("Stored run identity values are malformed.")
        if not isinstance(artifacts, list) or not all(isinstance(item, str) for item in artifacts):
            raise ValueError("Stored run artifact digests are malformed.")
        if not isinstance(predecessors, list) or not all(
            isinstance(item, str) for item in predecessors
        ):
            raise ValueError("Stored run predecessor digests are malformed.")
        return cls.from_values(
            identities,
            artifact_digests=tuple(artifacts),
            predecessor_digests=tuple(predecessors),
        )

    @property
    def aggregate_digest(self) -> str:
        return _sha256(_canonical_json(dict(self.digests)))

    def to_json(self) -> str:
        return _canonical_json(
            {
                "artifact_digests": self.artifact_digests,
                "identity_values": dict(self.identity_values),
                "predecessor_digests": self.predecessor_digests,
            }
        ).decode()

    def differences(self, other: RunInputContract) -> tuple[str, ...]:
        return tuple(
            name
            for name in (*REQUIRED_IDENTITY_INPUTS, "artifacts", "predecessors")
            if self.digests[name] != other.digests[name]
        )


@dataclass(frozen=True)
class WorkContext:
    run_id: str
    stable_key: str
    matchweek: str
    phase: RunPhase
    attempt: int
    mode: str
    input_digest: str
    predecessor_digest: str
    cpu_concurrency: int


@dataclass(frozen=True)
class WorkResult:
    result_digest: str
    artifact_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_digest(self.result_digest, "work result")
        _require_digest_list(self.artifact_digests, "work result artifact")

    @classmethod
    def for_phase(
        cls,
        phase: RunPhase,
        *,
        artifact_digests: tuple[str, ...] = (),
    ) -> WorkResult:
        return cls(
            result_digest=_sha256(f"matchvet-t04-boundary:{phase.value}".encode()),
            artifact_digests=artifact_digests,
        )


class WorkExecutor(Protocol):
    def __call__(self, context: WorkContext) -> WorkResult: ...


class WorkInterrupted(Exception):
    pass


class _HardLimitExpired(BaseException):
    pass


class RunLifecycleError(Exception):
    def __init__(self, error: RunError, run_id: str = "") -> None:
        super().__init__(f"{error.code}: {error.explanation}")
        self.error = error
        self.run_id = run_id


@dataclass(frozen=True)
class WorkUnitStatus:
    stable_key: str
    phase: RunPhase
    attempt: int
    attempt_state: str
    complete: bool
    checkpoint_at_utc: str | None
    elapsed_seconds: int
    mode: str
    input_digest: str
    output_digest: str | None
    artifact_digests: tuple[str, ...]


@dataclass(frozen=True)
class RunStatus:
    schema_version: int
    run_id: str
    matchweek: str
    state: RunState
    phase: RunPhase
    current_attempt: int
    mode: str
    completed_work_units: int
    total_work_units: int
    last_checkpoint: str
    checkpoint_at_utc: str | None
    elapsed_seconds: int
    input_digest: str
    input_digests: dict[str, str]
    resource_preflight: dict[str, object]
    reuse_state: str
    stale: bool
    warnings: tuple[str, ...]
    error_code: str | None
    error_explanation: str | None
    recovery_command: str
    completion_publication_digest: str | None
    decision_state: str
    work_units: tuple[WorkUnitStatus, ...]


@dataclass(frozen=True)
class _RunRecord:
    run_id: str
    matchweek: str
    input_digest: str
    state: RunState
    input_contract_json: str
    mode: str
    current_phase: RunPhase
    elapsed_seconds: int
    last_checkpoint_at_utc: str | None
    last_checkpoint: str | None
    reuse_state: str
    warnings_json: str
    last_error_code: str | None
    last_error_explanation: str | None
    completion_publication_digest: str | None
    resource_contract_json: str


class _BoundaryExecutor:
    def __call__(self, context: WorkContext) -> WorkResult:
        return WorkResult.for_phase(context.phase)


Clock = Callable[[], datetime]
ProgressReporter = Callable[[RunStatus], None]


class RunCoordinator:
    def __init__(
        self,
        store: Store,
        *,
        clock: Clock | None = None,
        budget: ResourceBudget = SETTLED_RESOURCE_BUDGET,
    ) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Run coordination requires a healthy writable store.")
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._budget = budget
        self._repository = _RunRepository(store)
        self._artifacts = ArtifactStore(store)

    def start(
        self,
        *,
        matchweek: str,
        inputs: RunInputContract,
        estimate: ResourceEstimate,
        observation: ResourceObservation,
        executor: WorkExecutor | None = None,
        progress: ProgressReporter | None = None,
    ) -> RunStatus:
        preflight = preflight_resources(estimate, observation, self._budget)
        if not preflight.accepted:
            assert preflight.error is not None
            raise RunLifecycleError(preflight.error)
        self._artifacts.discard_incomplete_staging()
        self._verify_input_artifacts(inputs, "MV-PREFLIGHT-ARTIFACT_INVALID", "matchvet run")
        now = _utc(self._clock())
        owner = _process_token(os.getpid())
        active_run = self._repository.interrupt_abandoned(now)
        if active_run is not None:
            raise RunLifecycleError(_coordinator_busy_error(active_run), active_run)
        compatible = self._repository.compatible_incomplete(matchweek, inputs.aggregate_digest)
        if compatible is not None:
            run_id = compatible.run_id
            raise RunLifecycleError(
                RunError(
                    status="REFUSED",
                    code="MV-RUN-RESUME_REQUIRED",
                    explanation="A compatible unfinished run already exists.",
                    last_checkpoint=compatible.last_checkpoint or "none",
                    reuse_state="REUSABLE",
                    recovery_command=f"matchvet resume {run_id}",
                    checkpoint_at_utc=compatible.last_checkpoint_at_utc,
                ),
                run_id,
            )
        run_id = CanonicalIdentifier.new("research_run").value
        self._repository.create_run(
            run_id=run_id,
            matchweek=matchweek,
            inputs=inputs,
            resource_json=_resource_json(estimate, observation, preflight),
            cpu_concurrency=preflight.cpu_concurrency,
            warnings=preflight.warnings,
            now=now,
            owner_token=owner,
        )
        if progress is not None:
            progress(self._repository.status(run_id))
        return self._execute(run_id, inputs, preflight.cpu_concurrency, executor, progress)

    def resume(
        self,
        run_id: str,
        *,
        inputs: RunInputContract,
        estimate: ResourceEstimate,
        observation: ResourceObservation,
        executor: WorkExecutor | None = None,
        progress: ProgressReporter | None = None,
    ) -> RunStatus:
        preflight = preflight_resources(estimate, observation, self._budget)
        if not preflight.accepted:
            assert preflight.error is not None
            error = _with_recovery(preflight.error, f"matchvet resume {run_id}")
            raise RunLifecycleError(error, run_id)
        self._artifacts.discard_incomplete_staging()
        now = _utc(self._clock())
        active_run = self._repository.interrupt_abandoned(now)
        if active_run is not None:
            raise RunLifecycleError(_coordinator_busy_error(active_run), active_run)
        record = self._repository.run(run_id)
        if record is None:
            raise RunLifecycleError(
                RunError(
                    "REFUSED",
                    "MV-RESUME-RUN_NOT_FOUND",
                    f"Run {run_id} does not exist.",
                    "none",
                    "NONE",
                    "matchvet status",
                ),
                run_id,
            )
        if record.state is RunState.COMPLETE:
            raise RunLifecycleError(
                RunError(
                    "REFUSED",
                    "MV-RESUME-ALREADY_COMPLETE",
                    f"Run {run_id} is already complete.",
                    record.last_checkpoint or "none",
                    "NOT_NEEDED",
                    f"matchvet status {run_id}",
                    record.last_checkpoint_at_utc,
                ),
                run_id,
            )
        stored = RunInputContract.from_stored_json(record.input_contract_json)
        differences = stored.differences(inputs)
        if differences:
            explanation = "Resume inputs differ: " + ", ".join(differences) + "."
            error = RunError(
                "REFUSED",
                "MV-RESUME-DIGEST_MISMATCH",
                explanation,
                record.last_checkpoint or "none",
                "BLOCKED",
                f"matchvet run {record.matchweek}",
                record.last_checkpoint_at_utc,
            )
            self._repository.record_error(run_id, error, now, "BLOCKED")
            raise RunLifecycleError(error, run_id)
        self._verify_input_artifacts(
            inputs,
            "MV-RESUME-ARTIFACT_INVALID",
            f"matchvet doctor --store {self._store.path}",
            run_id,
        )
        self._validate_checkpoints(run_id, inputs)
        self._repository.mark_resumed(
            run_id,
            _resource_json(estimate, observation, preflight),
            preflight.cpu_concurrency,
            preflight.warnings,
            _process_token(os.getpid()),
            now,
        )
        if progress is not None:
            progress(self._repository.status(run_id))
        return self._execute(run_id, inputs, preflight.cpu_concurrency, executor, progress)

    def _execute(
        self,
        run_id: str,
        inputs: RunInputContract,
        cpu_concurrency: int,
        executor: WorkExecutor | None,
        progress: ProgressReporter | None,
    ) -> RunStatus:
        execute = executor or _BoundaryExecutor()
        session_started = self._clock()
        checkpoints = self._repository.checkpoints(run_id)
        predecessor_digest = (
            str(checkpoints[-1][5]) if checkpoints else inputs.digests["predecessors"]
        )
        completed_keys = {str(row[1]) for row in checkpoints}
        run = self._repository.run(run_id)
        assert run is not None
        matchweek = run.matchweek
        for index, phase in enumerate(RUN_PHASES):
            stable_key = _work_key(index, phase, matchweek)
            if stable_key in completed_keys:
                continue
            started = self._clock()
            input_digest = _work_input_digest(
                inputs.aggregate_digest, stable_key, predecessor_digest
            )
            attempt = self._repository.start_attempt(
                run_id,
                stable_key,
                phase,
                input_digest,
                _process_token(os.getpid()),
                _utc(started),
            )
            context = WorkContext(
                run_id=run_id,
                stable_key=stable_key,
                matchweek=matchweek,
                phase=phase,
                attempt=attempt,
                mode="RESEARCH_ONLY",
                input_digest=input_digest,
                predecessor_digest=predecessor_digest,
                cpu_concurrency=cpu_concurrency,
            )
            try:
                elapsed_before = max(0, int((started - session_started).total_seconds()))
                remaining = self._budget.hard_duration_seconds - elapsed_before
                if remaining <= 0:
                    raise _HardLimitExpired
                result = _execute_with_deadline(execute, context, remaining)
            except _HardLimitExpired:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "FAILED",
                    "MV-RUN-HARD_TIME_LIMIT",
                    "The run reached the four-hour hard execution limit.",
                )
            except WorkInterrupted as interrupted:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "INTERRUPTED",
                    "MV-RUN-INTERRUPTED",
                    str(interrupted) or "The foreground coordinator was interrupted.",
                )
            except KeyboardInterrupt:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "INTERRUPTED",
                    "MV-RUN-INTERRUPTED",
                    "The foreground coordinator was interrupted by the terminal.",
                )
            except BaseException as error:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "FAILED",
                    "MV-RUN-WORK_FAILED",
                    f"Work unit {stable_key} failed: {error}",
                )
            ended = self._clock()
            attempt_elapsed = max(0, int((ended - started).total_seconds()))
            session_elapsed = max(0, int((ended - session_started).total_seconds()))
            if session_elapsed > self._budget.hard_duration_seconds:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "FAILED",
                    "MV-RUN-HARD_TIME_LIMIT",
                    "The run reached the four-hour hard execution limit.",
                    ended=ended,
                )
            try:
                for digest in result.artifact_digests:
                    self._artifacts.verify_artifact(digest)
                output_digest = _sha256(
                    _canonical_json(
                        {
                            "artifact_digests": result.artifact_digests,
                            "result_digest": result.result_digest,
                        }
                    )
                )
                self._repository.checkpoint(
                    run_id=run_id,
                    stable_key=stable_key,
                    phase=phase,
                    attempt=attempt,
                    input_digest=input_digest,
                    output_digest=output_digest,
                    artifact_digests=result.artifact_digests,
                    checkpoint_at=_utc(ended),
                    elapsed_seconds=attempt_elapsed,
                )
            except ArtifactError as error:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "FAILED",
                    "MV-RUN-CHECKPOINT_ARTIFACT_INVALID",
                    f"Checkpoint output artifact failed verification: {error.code}.",
                    ended=ended,
                )
            except (OSError, sqlite3.DatabaseError) as error:
                self._stop_attempt(
                    run_id,
                    stable_key,
                    attempt,
                    started,
                    "FAILED",
                    "MV-RUN-CHECKPOINT_FAILED",
                    f"Checkpoint publication failed: {error}.",
                    ended=ended,
                )
            predecessor_digest = output_digest
            if progress is not None:
                progress(self._repository.status(run_id))
        self._publish_completion(run_id, inputs)
        return self._repository.status(run_id)

    def _stop_attempt(
        self,
        run_id: str,
        stable_key: str,
        attempt: int,
        started: datetime,
        attempt_state: str,
        code: str,
        explanation: str,
        *,
        ended: datetime | None = None,
    ) -> Never:
        stopped = ended or self._clock()
        elapsed = max(0, int((stopped - started).total_seconds()))
        status = self._repository.status(run_id)
        error = RunError(
            "INCOMPLETE",
            code,
            explanation,
            status.last_checkpoint,
            "REUSABLE" if status.completed_work_units else "NONE",
            f"matchvet resume {run_id}",
            status.checkpoint_at_utc,
        )
        self._repository.finish_attempt(
            run_id,
            stable_key,
            attempt,
            attempt_state,
            _utc(stopped),
            elapsed,
            error,
        )
        raise RunLifecycleError(error, run_id)

    def _verify_input_artifacts(
        self,
        inputs: RunInputContract,
        code: str,
        recovery_command: str,
        run_id: str = "",
    ) -> None:
        try:
            for digest in inputs.artifact_digests:
                self._artifacts.verify_artifact(digest)
        except ArtifactError as error:
            failure = RunError(
                "REFUSED",
                code,
                f"Required artifact failed verification: {error.code}.",
                "none",
                "BLOCKED",
                recovery_command,
            )
            if run_id:
                status = self._repository.status(run_id)
                failure = RunError(
                    failure.status,
                    failure.code,
                    failure.explanation,
                    status.last_checkpoint,
                    failure.reuse_state,
                    failure.recovery_command,
                    status.checkpoint_at_utc,
                )
                self._repository.record_error(run_id, failure, _utc(self._clock()), "BLOCKED")
            raise RunLifecycleError(failure, run_id) from error

    def _validate_checkpoints(self, run_id: str, inputs: RunInputContract) -> None:
        predecessor = inputs.digests["predecessors"]
        for row in self._repository.checkpoints(run_id):
            stable_key = str(row[1])
            expected = _work_input_digest(inputs.aggregate_digest, stable_key, predecessor)
            if str(row[4]) != expected:
                error = RunError(
                    "REFUSED",
                    "MV-RESUME-CHECKPOINT_MISMATCH",
                    f"Checkpoint input digest differs for {stable_key}.",
                    stable_key,
                    "BLOCKED",
                    f"matchvet run {self._repository.matchweek(run_id)}",
                    str(row[7]),
                )
                self._repository.record_error(run_id, error, _utc(self._clock()), "BLOCKED")
                raise RunLifecycleError(error, run_id)
            for digest in _json_string_tuple(str(row[6])):
                try:
                    self._artifacts.verify_artifact(digest)
                except ArtifactError as artifact_error:
                    error = RunError(
                        "REFUSED",
                        "MV-RESUME-CHECKPOINT_ARTIFACT_INVALID",
                        f"Checkpoint artifact failed verification: {artifact_error.code}.",
                        stable_key,
                        "BLOCKED",
                        f"matchvet doctor --store {self._store.path}",
                        str(row[7]),
                    )
                    self._repository.record_error(run_id, error, _utc(self._clock()), "BLOCKED")
                    raise RunLifecycleError(error, run_id) from artifact_error
            predecessor = str(row[5])

    def _publish_completion(self, run_id: str, inputs: RunInputContract) -> None:
        checkpoints = self._repository.checkpoints(run_id)
        payload = _canonical_json(
            {
                "checkpoint_output_digests": [str(row[5]) for row in checkpoints],
                "input_digest": inputs.aggregate_digest,
                "mode": "RESEARCH_ONLY",
                "run_id": run_id,
                "schema_version": 1,
            }
        )
        try:
            publication = self._artifacts.publish_artifact(
                payload,
                "application/vnd.matchvet.run-completion+json",
                retention_class="REUSABLE",
            )
            self._repository.complete_run(run_id, publication.digest, _utc(self._clock()))
        except (ArtifactError, OSError, sqlite3.DatabaseError) as error:
            status = self._repository.status(run_id)
            failure = RunError(
                "INCOMPLETE",
                "MV-RUN-COMPLETION_PUBLICATION_FAILED",
                f"Atomic run completion publication failed: {error}.",
                status.last_checkpoint,
                "REUSABLE",
                f"matchvet resume {run_id}",
                status.checkpoint_at_utc,
            )
            self._repository.record_error(run_id, failure, _utc(self._clock()), "REUSABLE")
            raise RunLifecycleError(failure, run_id) from error


class _RunRepository:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._connection = store._connection_for_repository()

    def create_run(
        self,
        *,
        run_id: str,
        matchweek: str,
        inputs: RunInputContract,
        resource_json: str,
        cpu_concurrency: int,
        warnings: tuple[str, ...],
        now: str,
        owner_token: str,
    ) -> None:
        with self._store.transaction() as transaction:
            transaction.add_identifier(CanonicalIdentifier("research_run", run_id))
            self._connection.execute(
                """
                INSERT INTO research_runs (
                    run_id, matchweek, state, mode, current_phase, started_at_utc,
                    updated_at_utc, elapsed_seconds, input_contract_json, input_digest,
                    resource_contract_json, cpu_concurrency, warnings_json, reuse_state,
                    coordinator_token
                ) VALUES (?, ?, 'INCOMPLETE', 'RESEARCH_ONLY', ?, ?, ?, 0, ?, ?, ?, ?, ?,
                          'NOT_REUSED', ?)
                """,
                (
                    run_id,
                    matchweek,
                    RunPhase.PREFLIGHT.value,
                    now,
                    now,
                    inputs.to_json(),
                    inputs.aggregate_digest,
                    resource_json,
                    cpu_concurrency,
                    _canonical_json(warnings).decode(),
                    owner_token,
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO run_input_digests (run_id, input_kind, digest)
                VALUES (?, ?, ?)
                """,
                ((run_id, name, digest) for name, digest in sorted(inputs.digests.items())),
            )
            self._connection.executemany(
                """
                INSERT INTO run_work_units (
                    run_id, stable_key, phase, phase_order, mode, input_digest, state,
                    attempt_count, elapsed_seconds, artifact_digests_json
                ) VALUES (?, ?, ?, ?, 'RESEARCH_ONLY', ?, 'PENDING', 0, 0, '[]')
                """,
                (
                    (
                        run_id,
                        _work_key(index, phase, matchweek),
                        phase.value,
                        index,
                        _sha256(
                            _canonical_json(
                                {
                                    "input_digest": inputs.aggregate_digest,
                                    "phase": phase.value,
                                    "stable_key": _work_key(index, phase, matchweek),
                                }
                            )
                        ),
                    )
                    for index, phase in enumerate(RUN_PHASES)
                ),
            )

    def run(self, run_id: str) -> _RunRecord | None:
        return _read_run_record(self._connection, run_id)

    def compatible_incomplete(self, matchweek: str, input_digest: str) -> _RunRecord | None:
        row = self._connection.execute(
            """
            SELECT run_id
            FROM research_runs
            WHERE matchweek = ? AND input_digest = ? AND state = 'INCOMPLETE'
            ORDER BY started_at_utc DESC, run_id DESC
            LIMIT 1
            """,
            (matchweek, input_digest),
        ).fetchone()
        return None if row is None else self.run(str(row[0]))

    def checkpoints(self, run_id: str) -> tuple[tuple[object, ...], ...]:
        rows = self._connection.execute(
            """
            SELECT run_id, stable_key, phase, attempt, input_digest, output_digest,
                   artifact_digests_json, checkpoint_at_utc, elapsed_seconds
            FROM run_checkpoints
            WHERE run_id = ?
            ORDER BY checkpoint_order
            """,
            (run_id,),
        ).fetchall()
        return tuple(tuple(row) for row in rows)

    def matchweek(self, run_id: str) -> str:
        row = self._connection.execute(
            "SELECT matchweek FROM research_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise LookupError(run_id)
        return str(row[0])

    def start_attempt(
        self,
        run_id: str,
        stable_key: str,
        phase: RunPhase,
        input_digest: str,
        owner_token: str,
        started_at: str,
    ) -> int:
        with self._store.transaction():
            row = self._connection.execute(
                """
                SELECT attempt_count FROM run_work_units
                WHERE run_id = ? AND stable_key = ? AND state != 'COMPLETE'
                """,
                (run_id, stable_key),
            ).fetchone()
            if row is None:
                raise sqlite3.IntegrityError("work unit is missing or already complete")
            attempt = int(row[0]) + 1
            self._connection.execute(
                """
                UPDATE run_work_units
                SET state = 'RUNNING', attempt_count = ?, input_digest = ?
                WHERE run_id = ? AND stable_key = ?
                """,
                (attempt, input_digest, run_id, stable_key),
            )
            self._connection.execute(
                """
                INSERT INTO run_attempts (
                    run_id, stable_key, attempt, status, started_at_utc, owner_token,
                    elapsed_seconds
                ) VALUES (?, ?, ?, 'RUNNING', ?, ?, 0)
                """,
                (run_id, stable_key, attempt, started_at, owner_token),
            )
            self._connection.execute(
                """
                UPDATE research_runs
                SET current_phase = ?, updated_at_utc = ?, coordinator_token = ?,
                    last_error_code = NULL, last_error_explanation = NULL
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (phase.value, started_at, owner_token, run_id),
            )
        return attempt

    def checkpoint(
        self,
        *,
        run_id: str,
        stable_key: str,
        phase: RunPhase,
        attempt: int,
        input_digest: str,
        output_digest: str,
        artifact_digests: tuple[str, ...],
        checkpoint_at: str,
        elapsed_seconds: int,
    ) -> None:
        with self._store.transaction():
            order = RUN_PHASES.index(phase)
            artifacts_json = _canonical_json(artifact_digests).decode()
            self._connection.execute(
                """
                INSERT INTO run_checkpoints (
                    run_id, stable_key, phase, checkpoint_order, attempt, input_digest,
                    output_digest, artifact_digests_json, checkpoint_at_utc, elapsed_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stable_key,
                    phase.value,
                    order,
                    attempt,
                    input_digest,
                    output_digest,
                    artifacts_json,
                    checkpoint_at,
                    elapsed_seconds,
                ),
            )
            self._connection.execute(
                """
                UPDATE run_attempts
                SET status = 'COMPLETED', ended_at_utc = ?, elapsed_seconds = ?
                WHERE run_id = ? AND stable_key = ? AND attempt = ? AND status = 'RUNNING'
                """,
                (checkpoint_at, elapsed_seconds, run_id, stable_key, attempt),
            )
            self._connection.execute(
                """
                UPDATE run_work_units
                SET state = 'COMPLETE', checkpoint_at_utc = ?, elapsed_seconds = ?,
                    output_digest = ?, artifact_digests_json = ?
                WHERE run_id = ? AND stable_key = ? AND state = 'RUNNING'
                """,
                (
                    checkpoint_at,
                    elapsed_seconds,
                    output_digest,
                    artifacts_json,
                    run_id,
                    stable_key,
                ),
            )
            self._connection.execute(
                """
                UPDATE research_runs
                SET last_checkpoint = ?, last_checkpoint_at_utc = ?, updated_at_utc = ?,
                    elapsed_seconds = elapsed_seconds + ?, reuse_state = CASE
                        WHEN reuse_state = 'REUSED' THEN 'REUSED' ELSE 'REUSABLE' END
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (phase.value, checkpoint_at, checkpoint_at, elapsed_seconds, run_id),
            )

    def finish_attempt(
        self,
        run_id: str,
        stable_key: str,
        attempt: int,
        attempt_state: str,
        ended_at: str,
        elapsed_seconds: int,
        error: RunError,
    ) -> None:
        with self._store.transaction():
            self._connection.execute(
                """
                UPDATE run_attempts
                SET status = ?, ended_at_utc = ?, elapsed_seconds = ?, error_code = ?,
                    error_explanation = ?
                WHERE run_id = ? AND stable_key = ? AND attempt = ? AND status = 'RUNNING'
                """,
                (
                    attempt_state,
                    ended_at,
                    elapsed_seconds,
                    error.code,
                    error.explanation,
                    run_id,
                    stable_key,
                    attempt,
                ),
            )
            self._connection.execute(
                """
                UPDATE run_work_units SET state = 'PENDING'
                WHERE run_id = ? AND stable_key = ? AND state = 'RUNNING'
                """,
                (run_id, stable_key),
            )
            self._connection.execute(
                """
                UPDATE research_runs
                SET updated_at_utc = ?, elapsed_seconds = elapsed_seconds + ?,
                    last_error_code = ?, last_error_explanation = ?, reuse_state = ?
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (
                    ended_at,
                    elapsed_seconds,
                    error.code,
                    error.explanation,
                    error.reuse_state,
                    run_id,
                ),
            )

    def interrupt_abandoned(self, now: str) -> str | None:
        running = self._connection.execute(
            """
            SELECT run_id, stable_key, attempt, owner_token, started_at_utc
            FROM run_attempts WHERE status = 'RUNNING'
            """
        ).fetchall()
        live = next(
            (str(row[0]) for row in running if _process_token_is_alive(str(row[3]))),
            None,
        )
        if live is not None:
            return live
        if not running:
            return None
        elapsed_by_run: dict[str, int] = {}
        with self._store.transaction():
            for row in running:
                elapsed = _elapsed_between(str(row[4]), now)
                elapsed_by_run[str(row[0])] = elapsed_by_run.get(str(row[0]), 0) + elapsed
                self._connection.execute(
                    """
                    UPDATE run_attempts
                    SET status = 'INTERRUPTED', ended_at_utc = ?, elapsed_seconds = ?,
                        error_code = 'MV-RUN-ABANDONED_ATTEMPT',
                        error_explanation =
                            'The prior foreground coordinator ended without closing.'
                    WHERE run_id = ? AND stable_key = ? AND attempt = ? AND status = 'RUNNING'
                    """,
                    (now, elapsed, str(row[0]), str(row[1]), int(row[2])),
                )
                self._connection.execute(
                    """
                    UPDATE run_work_units SET state = 'PENDING'
                    WHERE run_id = ? AND stable_key = ? AND state = 'RUNNING'
                    """,
                    (str(row[0]), str(row[1])),
                )
            self._connection.executemany(
                """
                UPDATE research_runs
                SET updated_at_utc = ?, elapsed_seconds = elapsed_seconds + ?,
                    last_error_code = 'MV-RUN-ABANDONED_ATTEMPT',
                    last_error_explanation =
                        'The prior foreground coordinator ended without closing.',
                    reuse_state = CASE WHEN last_checkpoint IS NULL THEN 'NONE' ELSE 'REUSABLE' END
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                ((now, elapsed_by_run[run_id], run_id) for run_id in sorted(elapsed_by_run)),
            )
        return None

    def record_error(self, run_id: str, error: RunError, now: str, reuse_state: str) -> None:
        with self._store.transaction():
            self._connection.execute(
                """
                UPDATE research_runs
                SET updated_at_utc = ?, last_error_code = ?, last_error_explanation = ?,
                    reuse_state = ?
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (now, error.code, error.explanation, reuse_state, run_id),
            )

    def mark_resumed(
        self,
        run_id: str,
        resource_json: str,
        cpu_concurrency: int,
        warnings: tuple[str, ...],
        owner_token: str,
        now: str,
    ) -> None:
        with self._store.transaction():
            self._connection.execute(
                """
                UPDATE research_runs
                SET updated_at_utc = ?, resource_contract_json = ?, cpu_concurrency = ?,
                    warnings_json = ?,
                    coordinator_token = ?, reuse_state = 'REUSED', last_error_code = NULL,
                    last_error_explanation = NULL
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (
                    now,
                    resource_json,
                    cpu_concurrency,
                    _canonical_json(warnings).decode(),
                    owner_token,
                    run_id,
                ),
            )

    def complete_run(self, run_id: str, publication_digest: str, now: str) -> None:
        with self._store.transaction():
            self._connection.execute(
                """
                INSERT INTO run_completions (run_id, publication_digest, completed_at_utc)
                VALUES (?, ?, ?)
                """,
                (run_id, publication_digest, now),
            )
            self._connection.execute(
                """
                UPDATE research_runs
                SET state = 'COMPLETE', completed_at_utc = ?, updated_at_utc = ?,
                    reuse_state = CASE
                        WHEN reuse_state = 'REUSED' THEN 'REUSED' ELSE 'NOT_REUSED' END,
                    last_error_code = NULL, last_error_explanation = NULL
                WHERE run_id = ? AND state = 'INCOMPLETE'
                """,
                (now, now, run_id),
            )

    def status(self, run_id: str) -> RunStatus:
        return _status_from_connection(self._connection, run_id)


def read_run_status(
    database_path: Path,
    private_root: Path,
    run_id: str | None = None,
) -> RunStatus:
    inspection = inspect_store(database_path, private_root=private_root)
    if inspection.status is InspectionStatus.NOT_CONFIGURED:
        raise LookupError("No MatchVet store is configured.")
    if inspection.status is not InspectionStatus.HEALTHY:
        code = inspection.issues[0].code if inspection.issues else "MV-INTEGRITY-STORE"
        raise RuntimeError(f"{code}: Run status is unavailable until store recovery.")
    connection = sqlite3.connect(f"{Path(inspection.path).as_uri()}?mode=ro", uri=True)
    try:
        selected = run_id
        if selected is None:
            row = connection.execute(
                """
                SELECT run_id FROM research_runs
                ORDER BY started_at_utc DESC, run_id DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                raise LookupError("No MatchVet runs exist.")
            selected = str(row[0])
        return _status_from_connection(connection, selected)
    finally:
        connection.close()


def read_resume_candidate(
    database_path: Path,
    private_root: Path,
    input_factory: Callable[[str], RunInputContract] | None = None,
) -> RunStatus:
    inspection = inspect_store(database_path, private_root=private_root)
    if inspection.status is not InspectionStatus.HEALTHY:
        raise LookupError("A healthy MatchVet store is required to select a run.")
    connection = sqlite3.connect(f"{Path(inspection.path).as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT run_id FROM research_runs
            WHERE state = 'INCOMPLETE'
            ORDER BY started_at_utc DESC, run_id DESC
            """
        ).fetchall()
        builder = input_factory or build_local_input_contract
        compatible: list[RunStatus] = []
        for row in rows:
            status = _status_from_connection(connection, str(row[0]))
            current = builder(status.matchweek)
            if status.input_digests == dict(current.digests):
                compatible.append(status)
        if not compatible:
            raise LookupError("No compatible incomplete MatchVet run is available to resume.")
        if len(compatible) > 1:
            raise LookupError("Multiple compatible incomplete runs exist; pass an exact RUN_ID.")
        return compatible[0]
    finally:
        connection.close()


def build_local_input_contract(matchweek: str) -> RunInputContract:
    schema_identity = ":".join(migration.checksum for migration in MIGRATIONS)
    environment_identity = _canonical_json(
        {
            "machine": platform.machine(),
            "platform": sys.platform,
            "python": platform.python_version(),
            "thread_limits": {
                "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS", "UNSET"),
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "UNSET"),
            },
        }
    ).decode()
    software_identity = _software_identity()
    return RunInputContract.from_values(
        {
            "source": "T04:NO_SOURCE_SNAPSHOT",
            "cutoff": f"T04:UNCONFIGURED_CUTOFF:{matchweek}",
            "preference_set": "T04:UNCONFIGURED_PREFERENCE_SET",
            "policy": "T04:UNCONFIGURED_SELECTION_POLICY",
            "model": "T04:UNCONFIGURED_MODEL",
            "feature": "T04:UNCONFIGURED_FEATURE_RULES",
            "research_rule": "T04:UNCONFIGURED_RESEARCH_RULES",
            "canonical_contract": "MATCHVET_CANONICAL_CONTRACT_V1",
            "schema": schema_identity,
            "environment": environment_identity,
            "software": software_identity,
        }
    )


def default_resource_estimate() -> ResourceEstimate:
    return ResourceEstimate(
        storage_growth_bytes=MIB,
        peak_memory_bytes=128 * MIB,
        duration_seconds=1,
        network_bytes=0,
        cpu_heavy_operations=1,
    )


def observe_resources(database_path: Path) -> ResourceObservation:
    store_root = database_path.parent
    usage_path = _nearest_existing_parent(store_root)
    disk = shutil.disk_usage(usage_path)
    available_memory = _available_memory_bytes()
    return ResourceObservation(
        managed_storage_bytes=_directory_size(store_root),
        free_space_bytes=disk.free,
        available_memory_bytes=available_memory,
        available_cpus=os.cpu_count() or 1,
        memory_pressure=available_memory < 2 * GIB,
        thermal_pressure=_thermal_pressure(),
        active_coordinators=0,
    )


def _read_run_record(connection: sqlite3.Connection, run_id: str) -> _RunRecord | None:
    row = connection.execute(
        """
        SELECT
            runs.run_id, runs.matchweek, runs.input_digest, runs.state,
            runs.input_contract_json, runs.mode, runs.current_phase, runs.elapsed_seconds,
            runs.last_checkpoint_at_utc, runs.last_checkpoint, runs.reuse_state,
            runs.warnings_json, runs.last_error_code, runs.last_error_explanation,
            completions.publication_digest, runs.resource_contract_json
        FROM research_runs AS runs
        LEFT JOIN run_completions AS completions ON completions.run_id = runs.run_id
        WHERE runs.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return _RunRecord(
        run_id=str(row[0]),
        matchweek=str(row[1]),
        input_digest=str(row[2]),
        state=RunState(str(row[3])),
        input_contract_json=str(row[4]),
        mode=str(row[5]),
        current_phase=RunPhase(str(row[6])),
        elapsed_seconds=int(row[7]),
        last_checkpoint_at_utc=str(row[8]) if row[8] is not None else None,
        last_checkpoint=str(row[9]) if row[9] is not None else None,
        reuse_state=str(row[10]),
        warnings_json=str(row[11]),
        last_error_code=str(row[12]) if row[12] is not None else None,
        last_error_explanation=str(row[13]) if row[13] is not None else None,
        completion_publication_digest=str(row[14]) if row[14] is not None else None,
        resource_contract_json=str(row[15]),
    )


def _status_from_connection(connection: sqlite3.Connection, run_id: str) -> RunStatus:
    record = _read_run_record(connection, run_id)
    if record is None:
        raise LookupError(f"Run {run_id} does not exist.")
    unit_rows = connection.execute(
        """
        SELECT
            units.stable_key, units.phase, units.attempt_count, units.state,
            units.checkpoint_at_utc,
            CASE
                WHEN attempts.status IS NULL THEN units.elapsed_seconds
                ELSE attempts.elapsed_seconds
            END,
            units.mode,
            units.input_digest, units.output_digest, units.artifact_digests_json,
            attempts.status, attempts.started_at_utc
        FROM run_work_units AS units
        LEFT JOIN run_attempts AS attempts
          ON attempts.run_id = units.run_id
         AND attempts.stable_key = units.stable_key
         AND attempts.attempt = units.attempt_count
        WHERE units.run_id = ?
        ORDER BY units.phase_order
        """,
        (run_id,),
    ).fetchall()
    status_now = _utc(datetime.now(UTC))
    work_units = tuple(
        WorkUnitStatus(
            stable_key=str(unit[0]),
            phase=RunPhase(str(unit[1])),
            attempt=int(unit[2]),
            attempt_state=str(unit[10] or "PENDING"),
            complete=str(unit[3]) == "COMPLETE",
            checkpoint_at_utc=str(unit[4]) if unit[4] is not None else None,
            elapsed_seconds=(
                _elapsed_between(str(unit[11]), status_now)
                if str(unit[10] or "PENDING") == "RUNNING" and unit[11] is not None
                else int(unit[5])
            ),
            mode=str(unit[6]),
            input_digest=str(unit[7]),
            output_digest=str(unit[8]) if unit[8] is not None else None,
            artifact_digests=_json_string_tuple(str(unit[9])),
        )
        for unit in unit_rows
    )
    stale = any(
        unit.attempt_state == "RUNNING"
        and not _process_token_is_alive(
            str(
                connection.execute(
                    """
                    SELECT owner_token FROM run_attempts
                    WHERE run_id = ? AND stable_key = ? AND attempt = ?
                    """,
                    (run_id, unit.stable_key, unit.attempt),
                ).fetchone()[0]
            )
        )
        for unit in work_units
    )
    warnings = list(_json_string_tuple(record.warnings_json))
    if stale:
        warnings.append("The RUNNING attempt has no matching live coordinator and is stale.")
    contract = RunInputContract.from_stored_json(record.input_contract_json)
    completed = sum(unit.complete for unit in work_units)
    current_attempt = next(
        (unit.attempt for unit in work_units if unit.phase is record.current_phase),
        0,
    )
    return RunStatus(
        schema_version=1,
        run_id=record.run_id,
        matchweek=record.matchweek,
        state=record.state,
        phase=record.current_phase,
        current_attempt=current_attempt,
        mode=record.mode,
        completed_work_units=completed,
        total_work_units=len(work_units),
        last_checkpoint=record.last_checkpoint or "none",
        checkpoint_at_utc=record.last_checkpoint_at_utc,
        elapsed_seconds=record.elapsed_seconds
        + sum(unit.elapsed_seconds for unit in work_units if unit.attempt_state == "RUNNING"),
        input_digest=record.input_digest,
        input_digests=dict(contract.digests),
        resource_preflight=_json_object(record.resource_contract_json),
        reuse_state=record.reuse_state,
        stale=stale,
        warnings=tuple(warnings),
        error_code=record.last_error_code,
        error_explanation=record.last_error_explanation,
        recovery_command=(
            f"matchvet status {run_id}"
            if record.state is RunState.COMPLETE
            else f"matchvet resume {run_id}"
        ),
        completion_publication_digest=record.completion_publication_digest,
        decision_state="NO_DECISION",
        work_units=work_units,
    )


def _work_key(index: int, phase: RunPhase, matchweek: str) -> str:
    subject = re.sub(r"[^a-zA-Z0-9_.-]", "_", matchweek)
    return f"{index + 1:02d}:{phase.value}:matchweek:{subject}"


def _work_input_digest(contract_digest: str, stable_key: str, predecessor: str) -> str:
    return _sha256(
        _canonical_json(
            {
                "contract_digest": contract_digest,
                "predecessor_digest": predecessor,
                "stable_key": stable_key,
            }
        )
    )


def _resource_json(
    estimate: ResourceEstimate,
    observation: ResourceObservation,
    preflight: PreflightResult,
) -> str:
    return _canonical_json(
        {
            "budget": asdict(preflight.budget),
            "cpu_concurrency": preflight.cpu_concurrency,
            "estimate": estimate.as_dict(),
            "observation": observation.as_dict(),
            "warnings": preflight.warnings,
        }
    ).decode()


def _with_recovery(error: RunError, recovery_command: str) -> RunError:
    return RunError(
        error.status,
        error.code,
        error.explanation,
        error.last_checkpoint,
        error.reuse_state,
        recovery_command,
        error.checkpoint_at_utc,
    )


def _coordinator_busy_error(run_id: str) -> RunError:
    return RunError(
        "REFUSED",
        "MV-RUN-COORDINATOR_BUSY",
        "A live foreground MatchVet coordinator already owns a run attempt.",
        "none",
        "NONE",
        f"matchvet status {run_id}",
    )


def _elapsed_between(started_at: str, ended_at: str) -> int:
    started = datetime.fromisoformat(started_at)
    ended = datetime.fromisoformat(ended_at)
    return max(0, int((ended - started).total_seconds()))


def _execute_with_deadline(
    executor: WorkExecutor,
    context: WorkContext,
    remaining_seconds: int,
) -> WorkResult:
    def expire(_signal_number: int, _frame: FrameType | None) -> Never:
        raise _HardLimitExpired

    previous_handler = signal.signal(signal.SIGALRM, expire)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(remaining_seconds))
    try:
        return executor(context)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _process_token(pid: int) -> str:
    try:
        stat_contents = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        after_name = stat_contents.rsplit(")", maxsplit=1)[1].split()
        start_ticks = after_name[19]
    except OSError, IndexError:
        start_ticks = "unknown"
    return f"{pid}:{start_ticks}"


def _process_token_is_alive(token: str) -> bool:
    pid_text, separator, _ = token.partition(":")
    if not separator or not pid_text.isdigit():
        return False
    return _process_token(int(pid_text)) == token


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Run lifecycle timestamps must be timezone-aware.")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_digest(value: str, label: str) -> None:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} digests must be lowercase SHA-256 values.")


def _require_digest_list(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} digests must be unique.")
    for value in values:
        _require_digest(value, label)


def _json_string_tuple(value: str) -> tuple[str, ...]:
    loaded: object = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("Stored string list is malformed.")
    return tuple(loaded)


def _json_object(value: str) -> dict[str, object]:
    loaded: object = json.loads(value)
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ValueError("Stored JSON object is malformed.")
    return loaded


def _software_identity() -> str:
    commit = "UNKNOWN"
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError, OSError, subprocess.TimeoutExpired:
        result = None
    if result is not None and result.returncode == 0:
        candidate = result.stdout.strip()
        if re.fullmatch(r"[0-9a-f]{40}", candidate) is not None:
            commit = candidate
    package_root = Path(__file__).parent
    files = sorted(package_root.glob("*.py"))
    files.extend(sorted(package_root.glob("*.json")))
    file_digests = {path.name: _sha256(path.read_bytes()) for path in files}
    return _canonical_json({"git_commit": commit, "package_files": file_digests}).decode()


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        if candidate.parent == candidate:
            raise OSError(f"No existing parent for {path}.")
        candidate = candidate.parent
    return candidate


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            candidate = Path(root) / name
            try:
                if not candidate.is_symlink():
                    total += candidate.stat().st_size
            except OSError:
                continue
    return total


def _available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        pass
    return 0


def _thermal_pressure() -> bool:
    thermal_root = Path("/sys/class/thermal")
    try:
        temperature_paths = tuple(thermal_root.glob("thermal_zone*/temp"))
    except OSError:
        return False
    temperatures: list[int] = []
    for path in temperature_paths:
        try:
            raw = int(path.read_text(encoding="utf-8").strip())
        except OSError, ValueError:
            continue
        temperatures.append(raw if raw < 1_000 else raw // 1_000)
    return bool(temperatures and max(temperatures) >= 70)

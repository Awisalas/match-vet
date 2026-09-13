from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from matchvet.artifacts import ArtifactStore
from matchvet.runs import (
    GIB,
    MIB,
    RUN_PHASES,
    SETTLED_RESOURCE_BUDGET,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunLifecycleError,
    RunPhase,
    RunState,
    WorkContext,
    WorkInterrupted,
    WorkResult,
    preflight_resources,
    read_resume_candidate,
    read_run_status,
)
from matchvet.store import open_store


def _inputs(seed: str = "stable") -> RunInputContract:
    names = (
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
    return RunInputContract.from_values({name: f"{seed}:{name}" for name in names})


def _estimate() -> ResourceEstimate:
    return ResourceEstimate(
        storage_growth_bytes=MIB,
        peak_memory_bytes=256 * MIB,
        duration_seconds=60,
        network_bytes=0,
        cpu_heavy_operations=1,
    )


def _observation() -> ResourceObservation:
    return ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )


def test_input_contract_exposes_immutable_identity_and_digest_mappings() -> None:
    inputs = _inputs()

    with pytest.raises(TypeError):
        inputs.identity_values["model"] = "replacement"  # type: ignore[index]
    with pytest.raises(TypeError):
        inputs.digests["model"] = "0" * 64  # type: ignore[index]


class InterruptAt:
    def __init__(self, phase: RunPhase) -> None:
        self.phase = phase

    def __call__(self, context: WorkContext) -> WorkResult:
        if context.phase is self.phase:
            raise WorkInterrupted("injected Android interruption")
        return WorkResult.for_phase(context.phase)


class RecordingExecutor:
    def __init__(self) -> None:
        self.phases: list[RunPhase] = []

    def __call__(self, context: WorkContext) -> WorkResult:
        self.phases.append(context.phase)
        return WorkResult.for_phase(context.phase)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 13, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def test_resource_preflight_applies_settled_matchweek_budgets() -> None:
    estimate = ResourceEstimate(
        storage_growth_bytes=64 * MIB,
        peak_memory_bytes=512 * MIB,
        duration_seconds=7_200,
        network_bytes=100 * MIB,
        cpu_heavy_operations=2,
    )
    observation = ResourceObservation(
        managed_storage_bytes=256 * MIB,
        free_space_bytes=4 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )

    result = preflight_resources(estimate, observation)

    assert result.accepted is True
    assert result.cpu_concurrency == 2
    assert result.budget.target_duration_seconds == 7_200
    assert result.budget.hard_duration_seconds == 14_400
    assert result.budget.managed_storage_cap_bytes == 1536 * MIB
    assert result.budget.minimum_free_space_bytes == 3 * GIB
    assert result.budget.target_memory_bytes == GIB
    assert result.budget.absolute_memory_bytes == 1536 * MIB
    assert result.budget.routine_network_bytes == 250 * MIB


def test_resource_preflight_refuses_each_hard_violation() -> None:
    safe_observation = ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )
    safe_estimate = ResourceEstimate(
        storage_growth_bytes=MIB,
        peak_memory_bytes=256 * MIB,
        duration_seconds=60,
        network_bytes=MIB,
        cpu_heavy_operations=1,
    )

    failures = (
        (
            replace(safe_estimate, storage_growth_bytes=2 * GIB),
            safe_observation,
            "MV-PREFLIGHT-STORAGE_CAP",
        ),
        (
            safe_estimate,
            replace(safe_observation, free_space_bytes=3 * GIB),
            "MV-PREFLIGHT-FREE_SPACE",
        ),
        (
            replace(safe_estimate, peak_memory_bytes=2 * GIB),
            safe_observation,
            "MV-PREFLIGHT-MEMORY_LIMIT",
        ),
        (
            safe_estimate,
            replace(safe_observation, available_memory_bytes=GIB),
            "MV-PREFLIGHT-AVAILABLE_MEMORY",
        ),
        (
            replace(safe_estimate, duration_seconds=14_401),
            safe_observation,
            "MV-PREFLIGHT-TIME_HARD_LIMIT",
        ),
        (
            replace(safe_estimate, network_bytes=251 * MIB),
            safe_observation,
            "MV-PREFLIGHT-NETWORK_LIMIT",
        ),
        (
            replace(safe_estimate, cpu_heavy_operations=3),
            safe_observation,
            "MV-PREFLIGHT-CONCURRENCY_LIMIT",
        ),
        (
            safe_estimate,
            replace(safe_observation, active_coordinators=1),
            "MV-PREFLIGHT-COORDINATOR_BUSY",
        ),
    )

    for estimate, observation, expected_code in failures:
        result = preflight_resources(estimate, observation)
        assert result.accepted is False
        assert result.error is not None
        assert result.error.code == expected_code
        assert result.error.status == "REFUSED"
        assert result.error.last_checkpoint == "none"
        assert result.error.reuse_state == "NONE"
        assert result.error.recovery_command == "matchvet run"


def test_resource_preflight_reduces_cpu_concurrency_under_pressure() -> None:
    result = preflight_resources(
        ResourceEstimate(
            storage_growth_bytes=0,
            peak_memory_bytes=512 * MIB,
            duration_seconds=7_201,
            network_bytes=0,
            cpu_heavy_operations=2,
        ),
        ResourceObservation(
            managed_storage_bytes=0,
            free_space_bytes=4 * GIB,
            available_memory_bytes=2 * GIB,
            available_cpus=8,
            memory_pressure=True,
            thermal_pressure=False,
            active_coordinators=0,
        ),
    )

    assert result.accepted is True
    assert result.cpu_concurrency == 1
    assert "two-hour target" in result.warnings[0]
    assert "memory pressure" in result.warnings[1]


def test_new_run_checkpoints_each_phase_and_publishes_completion_atomically(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        status = RunCoordinator(store).start(
            matchweek="2026-09-18",
            inputs=_inputs(),
            estimate=_estimate(),
            observation=_observation(),
        )

    assert status.schema_version == 1
    assert status.state is RunState.COMPLETE
    assert status.mode == "RESEARCH_ONLY"
    assert status.completed_work_units == len(RUN_PHASES)
    assert status.total_work_units == len(RUN_PHASES)
    assert [unit.phase for unit in status.work_units] == list(RUN_PHASES)
    assert all(unit.complete for unit in status.work_units)
    assert all(unit.attempt == 1 for unit in status.work_units)
    assert all(unit.checkpoint_at_utc is not None for unit in status.work_units)
    assert status.last_checkpoint == RUN_PHASES[-1].value
    assert status.completion_publication_digest is not None
    assert status.decision_state == "NO_DECISION"

    persisted = read_run_status(database_path, private_root, status.run_id)
    assert persisted == status


def test_valid_resume_reuses_only_completed_digest_matched_work(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    run_id = ""

    with open_store(database_path, private_root=private_root) as store:
        coordinator = RunCoordinator(store)
        with pytest.raises(RunLifecycleError) as interrupted:
            coordinator.start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.EVIDENCE_ACQUISITION),
            )
        run_id = interrupted.value.run_id

    before = read_run_status(database_path, private_root, run_id)
    assert before.state is RunState.INCOMPLETE
    assert before.completed_work_units == 1
    assert before.last_checkpoint == RunPhase.PREFLIGHT.value
    assert before.work_units[1].attempt == 1
    assert before.work_units[1].attempt_state == "INTERRUPTED"
    assert before.decision_state == "NO_DECISION"

    recorder = RecordingExecutor()
    with open_store(database_path, private_root=private_root) as store:
        resumed = RunCoordinator(store).resume(
            run_id,
            inputs=_inputs(),
            estimate=_estimate(),
            observation=_observation(),
            executor=recorder,
        )

    assert recorder.phases == list(RUN_PHASES[1:])
    assert resumed.state is RunState.COMPLETE
    assert resumed.work_units[0].attempt == 1
    assert resumed.work_units[1].attempt == 2
    assert resumed.reuse_state == "REUSED"


def test_compatible_run_lookup_ignores_newer_incompatible_runs(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    compatible_inputs = _inputs("compatible")

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as first_interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=compatible_inputs,
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.EVIDENCE_ACQUISITION),
            )
        with pytest.raises(RunLifecycleError):
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=_inputs("incompatible"),
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.EVIDENCE_ACQUISITION),
            )
        with pytest.raises(RunLifecycleError) as resume_required:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=compatible_inputs,
                estimate=_estimate(),
                observation=_observation(),
            )

    assert resume_required.value.error.code == "MV-RUN-RESUME_REQUIRED"
    assert resume_required.value.run_id == first_interrupted.value.run_id
    candidate = read_resume_candidate(
        database_path,
        private_root,
        input_factory=lambda _matchweek: compatible_inputs,
    )
    assert candidate.run_id == first_interrupted.value.run_id


def test_resume_digest_mismatch_preserves_incomplete_run(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.FROZEN_EVIDENCE_STATE),
            )
        run_id = interrupted.value.run_id

    current = _inputs()
    changed_values = dict(current.identity_values) | {"model": "replacement-model-v2"}
    changed = RunInputContract.from_values(changed_values)
    with (
        open_store(database_path, private_root=private_root) as store,
        pytest.raises(RunLifecycleError) as refused,
    ):
        RunCoordinator(store).resume(
            run_id,
            inputs=changed,
            estimate=_estimate(),
            observation=_observation(),
        )

    assert refused.value.error.code == "MV-RESUME-DIGEST_MISMATCH"
    assert refused.value.error.status == "REFUSED"
    assert refused.value.error.reuse_state == "BLOCKED"
    assert "model" in refused.value.error.explanation
    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.completed_work_units == 2
    assert status.completion_publication_digest is None
    assert status.decision_state == "NO_DECISION"


def test_resume_refuses_a_different_required_input_artifact(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        artifact = ArtifactStore(store).publish_artifact(b"required", "text/plain")
        replacement = ArtifactStore(store).publish_artifact(b"replacement", "text/plain")
        inputs = RunInputContract.from_values(
            _inputs().identity_values,
            artifact_digests=(artifact.digest,),
        )
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=inputs,
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.EVIDENCE_ACQUISITION),
            )
        run_id = interrupted.value.run_id

    changed_inputs = RunInputContract.from_values(
        _inputs().identity_values,
        artifact_digests=(replacement.digest,),
    )

    with (
        open_store(database_path, private_root=private_root) as store,
        pytest.raises(RunLifecycleError) as refused,
    ):
        RunCoordinator(store).resume(
            run_id,
            inputs=changed_inputs,
            estimate=_estimate(),
            observation=_observation(),
        )

    assert refused.value.error.code == "MV-RESUME-DIGEST_MISMATCH"
    assert "artifacts" in refused.value.error.explanation
    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.completed_work_units == 1
    assert status.completion_publication_digest is None
    assert status.decision_state == "NO_DECISION"


def test_failed_checkpoint_keeps_the_previous_safe_boundary(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    def fail_checkpoint_publication(context: WorkContext) -> WorkResult:
        if context.phase is RunPhase.EVIDENCE_ACQUISITION:
            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TRIGGER injected_checkpoint_failure
                BEFORE INSERT ON run_checkpoints
                WHEN NEW.phase = 'evidence_acquisition_and_cutoff_classification'
                BEGIN
                    SELECT RAISE(ABORT, 'injected checkpoint failure');
                END
                """
            )
            connection.commit()
            connection.close()
        return WorkResult.for_phase(context.phase)

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as failed:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=fail_checkpoint_publication,
            )
        run_id = failed.value.run_id

    connection = sqlite3.connect(database_path)
    connection.execute("DROP TRIGGER injected_checkpoint_failure")
    connection.commit()
    connection.close()

    assert failed.value.error.code == "MV-RUN-CHECKPOINT_FAILED"
    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.last_checkpoint == RunPhase.PREFLIGHT.value
    assert status.completed_work_units == 1
    assert status.work_units[1].complete is False
    assert status.work_units[1].attempt_state == "FAILED"
    assert status.completion_publication_digest is None


def test_hard_limit_stops_before_publishing_an_overlong_work_unit(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    clock = MutableClock()

    def overrun(context: WorkContext) -> WorkResult:
        if context.phase is RunPhase.EVIDENCE_ACQUISITION:
            clock.advance(14_401)
        return WorkResult.for_phase(context.phase)

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as failed:
            RunCoordinator(store, clock=clock).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=overrun,
            )
        run_id = failed.value.run_id

    assert failed.value.error.code == "MV-RUN-HARD_TIME_LIMIT"
    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.last_checkpoint == RunPhase.PREFLIGHT.value
    assert status.elapsed_seconds == 14_401
    assert status.decision_state == "NO_DECISION"


def test_hard_limit_interrupts_a_blocked_foreground_work_unit(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    budget = replace(
        SETTLED_RESOURCE_BUDGET,
        target_duration_seconds=1,
        hard_duration_seconds=1,
    )

    def blocked(context: WorkContext) -> WorkResult:
        del context
        time.sleep(5)
        raise AssertionError("hard deadline did not interrupt blocked work")

    started = time.monotonic()
    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as failed:
            RunCoordinator(store, budget=budget).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=replace(_estimate(), duration_seconds=1),
                observation=_observation(),
                executor=blocked,
            )
        run_id = failed.value.run_id

    assert time.monotonic() - started < 3
    assert failed.value.error.code == "MV-RUN-HARD_TIME_LIMIT"
    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.completed_work_units == 0
    assert status.work_units[0].attempt_state == "FAILED"


def test_keyboard_interrupt_records_an_interrupted_attempt(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    def interrupt(context: WorkContext) -> WorkResult:
        if context.phase is RunPhase.EVIDENCE_ACQUISITION:
            raise KeyboardInterrupt
        return WorkResult.for_phase(context.phase)

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as stopped:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=interrupt,
            )
        run_id = stopped.value.run_id

    assert stopped.value.error.code == "MV-RUN-INTERRUPTED"
    status = read_run_status(database_path, private_root, run_id)
    assert status.work_units[1].attempt_state == "INTERRUPTED"
    assert status.last_checkpoint == RunPhase.PREFLIGHT.value


def test_database_rejects_completed_state_without_atomic_publication(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=_inputs(),
                estimate=_estimate(),
                observation=_observation(),
                executor=InterruptAt(RunPhase.EVIDENCE_ACQUISITION),
            )
        run_id = interrupted.value.run_id

    connection = sqlite3.connect(database_path)
    with pytest.raises(sqlite3.IntegrityError, match="completion publication"):
        connection.execute(
            "UPDATE research_runs SET state = 'COMPLETE' WHERE run_id = ?", (run_id,)
        )
    connection.close()

    status = read_run_status(database_path, private_root, run_id)
    assert status.state is RunState.INCOMPLETE
    assert status.completion_publication_digest is None


def test_abandoned_running_attempt_is_detected_and_recovered(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    script = """
import os
import sys
from pathlib import Path
from matchvet.runs import (
    GIB, MIB, REQUIRED_IDENTITY_INPUTS, ResourceEstimate, ResourceObservation,
    RunCoordinator, RunInputContract, RunPhase, WorkResult,
)
from matchvet.store import open_store

class Abandon:
    def __call__(self, context):
        if context.phase is RunPhase.EVIDENCE_ACQUISITION:
            print(context.run_id, flush=True)
            os._exit(23)
        return WorkResult.for_phase(context.phase)

root = Path(sys.argv[1])
database = Path(sys.argv[2])
inputs = RunInputContract.from_values(
    {name: f"stable:{name}" for name in REQUIRED_IDENTITY_INPUTS}
)
with open_store(database, private_root=root) as store:
    RunCoordinator(store).start(
        matchweek="2026-09-18",
        inputs=inputs,
        estimate=ResourceEstimate(MIB, 128 * MIB, 1, 0, 1),
        observation=ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0),
        executor=Abandon(),
    )
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(private_root), str(database_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 23
    run_id = result.stdout.strip()
    connection = sqlite3.connect(database_path)
    started_at = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
    connection.execute(
        """
        UPDATE run_attempts SET started_at_utc = ?
        WHERE run_id = ? AND status = 'RUNNING'
        """,
        (started_at, run_id),
    )
    connection.commit()
    connection.close()
    stale = read_run_status(database_path, private_root, run_id)
    assert stale.state is RunState.INCOMPLETE
    assert stale.stale is True
    assert stale.work_units[1].attempt_state == "RUNNING"
    assert stale.work_units[1].elapsed_seconds >= 89
    assert stale.elapsed_seconds >= 89
    assert "stale" in stale.warnings[-1]
    partial = private_root / "staging" / "artifacts" / ".interrupted.partial"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"incomplete")

    with open_store(database_path, private_root=private_root) as store:
        recovered = RunCoordinator(store).resume(
            run_id,
            inputs=_inputs(),
            estimate=_estimate(),
            observation=_observation(),
        )

    assert recovered.state is RunState.COMPLETE
    assert recovered.stale is False
    assert recovered.work_units[1].attempt == 2
    assert recovered.work_units[1].attempt_state == "COMPLETED"
    assert not partial.exists()

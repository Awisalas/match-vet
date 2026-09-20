from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from matchvet import cli
from matchvet.artifacts import ArtifactStore
from matchvet.runs import (
    GIB,
    MIB,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunLifecycleError,
    RunPhase,
    WorkContext,
    WorkInterrupted,
    WorkResult,
    build_local_input_contract,
)
from matchvet.store import MIGRATIONS, open_store
from matchvet.t17 import OperationVerification, T17Error

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_GUARD = PROJECT_ROOT / "tests" / "no_network"


def run_matchvet(
    *arguments: str,
    path: str | None = None,
    extra_environment: dict[str, str] | None = None,
    cwd: Path = PROJECT_ROOT,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(NETWORK_GUARD), str(PROJECT_ROOT / "src")))
    if path is not None:
        environment["PATH"] = path
    if extra_environment is not None:
        environment.update(extra_environment)

    return subprocess.run(
        [sys.executable, "-m", "matchvet", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _t18_cli_corpus() -> dict[str, object]:
    def observation(
        *,
        match_id: str,
        matchweek_id: str,
        matchweek_start: str,
        kickoff: str,
        cutoff: str,
        outcome_known: str,
        settlement: str,
    ) -> dict[str, object]:
        fixture_revision = {"kickoff_at_utc": kickoff, "match_id": match_id}
        fixture_revision_digest = hashlib.sha256(
            json.dumps(fixture_revision, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        membership_manifest = {
            "fixture_revision_digests": [fixture_revision_digest],
            "matchweek_id": matchweek_id,
        }
        membership_manifest_digest = hashlib.sha256(
            json.dumps(membership_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return {
            "baseline_probability": 0.5,
            "baseline_digest": "f" * 64,
            "baseline_structural_trivial": False,
            "conservative_probability": 0.7,
            "calibration_digest": "e" * 64,
            "correlation_group": "match-result",
            "estimated_probability": 0.8,
            "evidence_digest": "c" * 64,
            "exact_line": "Home",
            "fixture_revision": fixture_revision,
            "fixture_revision_digest": fixture_revision_digest,
            "gates": {"G0": "PASS", "G4": "PASS"},
            "input_digest": "d" * 64,
            "input_observed_at_utc": {
                "fixture_revision": cutoff,
                "membership_manifest": cutoff,
            },
            "kickoff_at_utc": kickoff,
            "league": "Premier League",
            "match_id": match_id,
            "matchweek_id": matchweek_id,
            "matchweek_start_utc": matchweek_start,
            "membership_manifest": membership_manifest,
            "membership_manifest_digest": membership_manifest_digest,
            "model_agreement": 0.8,
            "model_digest": "b" * 64,
            "model_version": "model-1",
            "model_fitted_at_utc": matchweek_start,
            "outcome_known_at_utc": outcome_known,
            "outcome_use": "UNSEEN",
            "policy_digest": "a" * 64,
            "policy_version": "policy-a",
            "prediction_created_at_utc": cutoff,
            "preference_family": "Match Winner",
            "preference_id": "match_winner_home",
            "recommendation": "CANDIDATE",
            "research_cutoff_at_utc": cutoff,
            "selection_components": {"probability": 0.8},
            "selection_strength": 0.8,
            "settlement": settlement,
            "structural_conditions": [],
            "training_data_end_utc": matchweek_start,
            "uncertainty_lower": 0.6,
            "uncertainty_upper": 0.9,
            "uncertainty_width": 0.3,
        }

    return {
        "candidates": [
            {
                "development_data_end_utc": "2026-08-21T00:00:00+00:00",
                "digest": "a" * 64,
                "fold_parameters": {},
                "frozen_at_utc": "2026-08-28T00:00:00+00:00",
                "inspected_evaluation_digests": [],
                "parameters": {"conservative_probability_min": 0.6},
                "status": "RESEARCH_ONLY",
                "version": "policy-a",
            }
        ],
        "config": {
            "calibration_bin_edges": [0.0, 0.5, 1.0],
            "criteria": [
                {
                    "metric": "probability_quality.brier_score",
                    "minimum_effective_sample": 1,
                    "operator": "<=",
                    "threshold": 0.1,
                }
            ],
            "development": {
                "end_utc": "2026-08-21T00:00:00+00:00",
                "name": "DEVELOPMENT",
                "start_utc": "2026-08-07T00:00:00+00:00",
            },
            "evaluation": {
                "end_utc": "2026-09-11T00:00:00+00:00",
                "name": "EVALUATION",
                "start_utc": "2026-08-28T00:00:00+00:00",
            },
            "evaluation_minimum_recommendations": 1,
            "minimum_development_matchweeks": 1,
            "rolling_step_matchweeks": 1,
            "rolling_validation_matchweeks": 1,
            "seed": 17,
            "selection_direction": "MINIMIZE",
            "selection_metric": "probability_quality.brier_score",
            "split_method": "CHRONOLOGICAL",
            "subgroup_minimum_effective_samples": {"league": 1},
            "uncertainty_nominal_coverage": 0.8,
            "validation": {
                "end_utc": "2026-08-28T00:00:00+00:00",
                "name": "VALIDATION",
                "start_utc": "2026-08-21T00:00:00+00:00",
            },
        },
        "observations": [
            observation(
                match_id="validation-match",
                matchweek_id="mw-validation",
                matchweek_start="2026-08-21T00:00:00+00:00",
                kickoff="2026-08-22T14:00:00+00:00",
                cutoff="2026-08-22T08:00:00+00:00",
                outcome_known="2026-08-22T18:00:00+00:00",
                settlement="WIN",
            ),
            observation(
                match_id="evaluation-match",
                matchweek_id="mw-evaluation",
                matchweek_start="2026-08-28T00:00:00+00:00",
                kickoff="2026-08-29T14:00:00+00:00",
                cutoff="2026-08-29T08:00:00+00:00",
                outcome_known="2026-08-29T18:00:00+00:00",
                settlement="WIN",
            ),
        ],
        "schema_version": "matchvet.policy-evaluation-input.v1",
    }


def _safe_estimate() -> ResourceEstimate:
    return ResourceEstimate(MIB, 128 * MIB, 1, 0, 1)


def _safe_observation() -> ResourceObservation:
    return ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0)


def _interrupt_evidence(context: WorkContext) -> WorkResult:
    if context.phase is RunPhase.EVIDENCE_ACQUISITION:
        raise WorkInterrupted("terminal process ended")
    return WorkResult.for_phase(context.phase)


def test_no_arguments_reports_bootstrap_state_and_next_action() -> None:
    result = run_matchvet()

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == (
        "MatchVet\n"
        "State: BOOTSTRAP\n"
        "Mode: RESEARCH_ONLY\n"
        "Store: not configured\n"
        "Active run: none\n"
        "Next action: matchvet doctor\n"
    )


def test_no_arguments_does_not_create_local_or_home_state(tmp_path: Path) -> None:
    working_directory = tmp_path / "work"
    home_directory = tmp_path / "home"
    working_directory.mkdir()
    home_directory.mkdir()

    result = run_matchvet(
        cwd=working_directory,
        extra_environment={
            "HOME": str(home_directory),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )

    assert result.returncode == 0
    assert list(working_directory.iterdir()) == []
    assert list(home_directory.iterdir()) == []


def test_no_arguments_reports_a_healthy_default_store_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_home = tmp_path / "home"
    private_home.mkdir()
    database_path = private_home / ".local" / "share" / "matchvet" / "matchvet.sqlite3"
    with open_store(database_path, private_root=tmp_path):
        pass
    before = database_path.stat().st_mtime_ns
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)
    monkeypatch.setattr(cli, "termux_private_root", lambda: tmp_path)

    cli._show_bootstrap_state()

    assert capsys.readouterr().out == (
        "MatchVet\n"
        "State: READY\n"
        "Mode: RESEARCH_ONLY\n"
        f"Store: healthy; schema {len(MIGRATIONS)}\n"
        "Active run: none\n"
        "Next action: matchvet run\n"
    )
    assert database_path.stat().st_mtime_ns == before


def test_no_arguments_prioritizes_an_older_incomplete_run_over_the_latest_complete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=build_local_input_contract("2026-09-18"),
                estimate=_safe_estimate(),
                observation=_safe_observation(),
                executor=_interrupt_evidence,
            )
        run_id = interrupted.value.run_id
        RunCoordinator(store).start(
            matchweek="2026-09-25",
            inputs=build_local_input_contract("2026-09-25"),
            estimate=_safe_estimate(),
            observation=_safe_observation(),
        )
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)

    cli._show_bootstrap_state()

    output = capsys.readouterr().out
    assert f"Active run: {run_id}; INCOMPLETE; preflight" in output
    assert f"Next action: matchvet resume {run_id}" in output


def test_doctor_captures_the_pinned_environment_without_secrets() -> None:
    secret = "must-not-appear-in-doctor-output"

    result = run_matchvet(
        "doctor",
        "--json",
        extra_environment={"MATCHVET_TEST_SECRET": secret},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert secret not in result.stdout

    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["status"] == "PASS"
    assert report["mode"] == "RESEARCH_ONLY"
    assert report["baseline"] == "termux-aarch64-python-3.14.6-v1"
    assert report["environment"]["python"] == {
        "implementation": "cpython",
        "version": "3.14.6",
        "termux_package_version": "3.14.6-1",
    }
    assert report["environment"]["architecture"] == "aarch64"
    assert report["environment"]["platform"] == "android-24-arm64_v8a"
    assert report["environment"]["termux"]["version"] == "0.118.3"
    assert report["environment"]["termux"]["release"] == "F_DROID"
    assert report["environment"]["android"] == {
        "api_level": "36",
        "version": "16",
    }
    assert report["environment"]["thread_limits"] == {
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
    }
    assert report["environment"]["termux_repositories"]
    assert len(report["environment"]["dpkg_inventory"]) > 100
    assert report["environment"]["storage"] == {
        "private_home": "/data/data/com.termux/files/home",
        "private_prefix": "/data/data/com.termux/files/usr",
        "project_root": str(PROJECT_ROOT),
        "shared_storage": "/storage/emulated/0",
    }
    assert len(report["environment"]["git_commit"]) == 40
    assert report["environment_manifest"]["status"] == "PASS"
    assert report["environment_manifest"]["baseline_sha256"] != "UNKNOWN"
    assert all(
        record["status"] == "PRESENT" for record in report["environment_manifest"]["files"].values()
    )
    assert all(check["status"] == "PASS" for check in report["checks"])


def test_doctor_failure_has_a_stable_code_and_recovery_command() -> None:
    result = run_matchvet("doctor", "--json", path="")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "FAIL"
    assert report["error"] == {
        "code": "MV-PREFLIGHT-ENVIRONMENT_MISMATCH",
        "recovery_command": "scripts/bootstrap-termux.sh",
        "summary": "The current Termux environment does not match the pinned baseline.",
    }
    assert any(
        check["id"] == "command:uv" and check["status"] == "FAIL" for check in report["checks"]
    )


def test_policy_validate_writes_deterministic_research_only_artifact(tmp_path: Path) -> None:
    input_path = tmp_path / "evaluation-input.json"
    first_output = tmp_path / "first-artifact.json"
    second_output = tmp_path / "second-artifact.json"
    unrelated_partial = first_output.with_name(f"{first_output.name}.partial")
    unrelated_partial.write_bytes(b"unrelated")
    input_path.write_text(json.dumps(_t18_cli_corpus()), encoding="utf-8")

    first = run_matchvet(
        "policy",
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(first_output),
        "--json",
    )
    second = run_matchvet(
        "policy",
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(second_output),
        "--json",
    )

    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == ""
    first_summary = json.loads(first.stdout)
    second_summary = json.loads(second.stdout)
    assert first_summary["status"] == "PASS"
    assert first_summary["lifecycle_effect"] == "EVALUATED_RESEARCH_ONLY"
    assert first_summary["frozen_policy"]["status"] == "RESEARCH_ONLY"
    assert first_summary["artifact_digest"] == second_summary["artifact_digest"]
    assert first_output.read_bytes() == second_output.read_bytes()
    assert unrelated_partial.read_bytes() == b"unrelated"
    assert not tuple(tmp_path.glob(f".{first_output.name}.*.partial"))


def test_policy_validate_checkpoint_resume_reproduces_artifact(tmp_path: Path) -> None:
    input_path = tmp_path / "evaluation-input.json"
    first_output = tmp_path / "first-artifact.json"
    replay_output = tmp_path / "replay-artifact.json"
    checkpoint = tmp_path / "checkpoint.json"
    input_path.write_text(json.dumps(_t18_cli_corpus()), encoding="utf-8")

    first = run_matchvet(
        "policy",
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(first_output),
        "--checkpoint",
        str(checkpoint),
        "--json",
    )
    replay = run_matchvet(
        "policy",
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(replay_output),
        "--checkpoint",
        str(checkpoint),
        "--resume",
        "--json",
    )

    assert first.returncode == replay.returncode == 0
    assert first_output.read_bytes() == replay_output.read_bytes()
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert checkpoint_payload["state"] == "COMPLETE"
    assert checkpoint_payload["artifact_digest"] == json.loads(replay.stdout)["artifact_digest"]


def test_policy_validate_future_cutoff_input_fails_without_output(tmp_path: Path) -> None:
    corpus = _t18_cli_corpus()
    observations = corpus["observations"]
    assert isinstance(observations, list)
    evaluation = observations[-1]
    assert isinstance(evaluation, dict)
    evaluation["input_observed_at_utc"] = {"confirmed_lineup": "2026-08-29T13:00:00+00:00"}
    input_path = tmp_path / "leaking-input.json"
    output_path = tmp_path / "artifact.json"
    input_path.write_text(json.dumps(corpus), encoding="utf-8")

    result = run_matchvet(
        "policy",
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--json",
    )

    assert result.returncode == 1
    assert result.stderr == ""
    error = json.loads(result.stdout)
    assert error["status"] == "REFUSED"
    assert error["code"] == "MV-T18-EVALUATION_FAILED"
    assert "after the Research Cutoff" in error["explanation"]
    assert error["recovery_command"] == f"matchvet policy validate --input {input_path}"
    assert not output_path.exists()


def test_help_and_unknown_commands_follow_argparse_contract() -> None:
    help_result = run_matchvet("--help")
    unknown_result = run_matchvet("not-a-command")

    assert help_result.returncode == 0
    assert "usage: matchvet" in help_result.stdout
    assert "doctor" in help_result.stdout
    assert unknown_result.returncode == 2
    assert "invalid choice: 'not-a-command'" in unknown_result.stderr


def test_t17_cli_commands_expose_operation_identity_and_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)

    class FakeResult:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def to_dict(self) -> dict[str, object]:
            return self.payload

    monkeypatch.setattr(
        cli,
        "export_matchweek",
        lambda *args, **kwargs: FakeResult(
            {
                "operation": "export",
                "status": "COMPLETE",
                "source": str(database_path),
                "destination": str(tmp_path / "shared" / "export"),
                "manifest_digest": "a" * 64,
                "verification": {"verified": True},
            }
        ),
    )
    assert (
        cli.main(
            [
                "export",
                "--store",
                str(database_path),
                "--destination",
                str(tmp_path / "shared" / "export"),
                "--json",
            ]
        )
        == 0
    )
    export_payload = json.loads(capsys.readouterr().out)
    assert export_payload["status"] == "COMPLETE"
    assert export_payload["manifest_digest"] == "a" * 64
    assert export_payload["verification"]["verified"] is True

    verification = OperationVerification(
        operation="backup",
        verified=True,
        destination=tmp_path / "shared" / "backup",
        manifest_digest="b" * 64,
        completion_digest="c" * 64,
        details={"object_count": 1},
    )
    monkeypatch.setattr(cli, "verify_backup", lambda path: verification)
    assert cli.main(["backup", "--verify", str(tmp_path / "shared" / "backup"), "--json"]) == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["status"] == "VERIFIED"
    assert verify_payload["manifest_digest"] == "b" * 64
    assert verify_payload["verification"]["verified"] is True

    monkeypatch.setattr(
        cli,
        "restore_backup",
        lambda *args, **kwargs: FakeResult(
            {
                "operation": "restore",
                "status": "COMPLETE",
                "source": str(tmp_path / "shared" / "backup"),
                "destination": str(private_root / "restored" / "matchvet.sqlite3"),
                "manifest_digest": "d" * 64,
                "verification": {"verified": True},
            }
        ),
    )
    assert (
        cli.main(
            [
                "restore",
                "--source",
                str(tmp_path / "shared" / "backup"),
                "--target",
                str(private_root / "restored" / "matchvet.sqlite3"),
                "--json",
            ]
        )
        == 0
    )
    restore_payload = json.loads(capsys.readouterr().out)
    assert restore_payload["status"] == "COMPLETE"
    assert restore_payload["destination"].endswith("restored/matchvet.sqlite3")


def test_t17_cli_runs_real_export_backup_verify_and_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from test_t16 import _audit

    private_root = tmp_path / "private"
    database_path = private_root / "matchvet.sqlite3"
    shared_root = tmp_path / "shared"
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)
    with open_store(database_path, private_root=private_root) as store:
        from matchvet.t16 import publish_matchweek_audit

        publish_matchweek_audit(_audit(), store=store)

    export_destination = shared_root / "export"
    assert (
        cli.main(
            [
                "export",
                "--store",
                str(database_path),
                "--destination",
                str(export_destination),
                "--json",
            ]
        )
        == 0
    )
    export_payload = json.loads(capsys.readouterr().out)
    assert export_payload["status"] == "COMPLETE"
    assert export_payload["verification"]["verified"] is True

    backup_destination = shared_root / "backup"
    assert (
        cli.main(
            [
                "backup",
                "--store",
                str(database_path),
                "--destination",
                str(backup_destination),
                "--json",
            ]
        )
        == 0
    )
    backup_payload = json.loads(capsys.readouterr().out)
    assert backup_payload["status"] == "COMPLETE"
    assert backup_payload["verification"]["verified"] is True

    assert cli.main(["backup", "--verify", str(backup_destination), "--json"]) == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["status"] == "VERIFIED"
    assert verify_payload["verification"]["verified"] is True

    restored_target = private_root / "restored" / "matchvet.sqlite3"
    assert (
        cli.main(
            [
                "restore",
                "--source",
                str(backup_destination),
                "--target",
                str(restored_target),
                "--json",
            ]
        )
        == 0
    )
    restore_payload = json.loads(capsys.readouterr().out)
    assert restore_payload["status"] == "COMPLETE"
    assert restore_payload["verification"]["verified"] is True


def test_t17_cli_errors_keep_stable_code_and_recovery_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    monkeypatch.setattr(cli, "termux_private_root", lambda: private_root)
    monkeypatch.setattr(cli, "default_database_path", lambda: database_path)

    def fail_export(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise T17Error(
            "MV-T17-EXPORT-INCOMPLETE",
            "The associated run is incomplete.",
            status="INCOMPLETE",
            recovery_command="matchvet resume run-1",
        )

    monkeypatch.setattr(cli, "export_matchweek", fail_export)
    result = cli.main(
        [
            "export",
            "--store",
            str(database_path),
            "--destination",
            str(tmp_path / "shared" / "export"),
            "--json",
        ]
    )
    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "INCOMPLETE"
    assert payload["code"] == "MV-T17-EXPORT-INCOMPLETE"
    assert payload["verification"] == "FAIL"
    assert payload["recovery_command"] == "matchvet resume run-1"

    assert cli.main(["backup", "--json"]) == 1
    option_payload = json.loads(capsys.readouterr().out)
    assert option_payload["code"] == "MV-T17-BACKUP-DESTINATION_REQUIRED"


def test_normal_commands_work_with_live_network_sockets_denied() -> None:
    for arguments in ((), ("--help",), ("doctor", "--json")):
        result = run_matchvet(*arguments)

        assert result.returncode == 0
        assert "forbids live network sockets" not in result.stderr


def test_installed_matchvet_command_exposes_the_same_bootstrap_state() -> None:
    executable = Path(sys.executable).parent / "matchvet"

    result = subprocess.run(
        [executable],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith("MatchVet\nState: BOOTSTRAP\n")


def test_human_doctor_report_is_readable_and_keeps_research_only_mode() -> None:
    result = run_matchvet("doctor")

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith(
        "MatchVet doctor\n"
        "Status: PASS\n"
        "Mode: RESEARCH_ONLY\n"
        "Baseline: termux-aarch64-python-3.14.6-v1\n"
    )
    assert "[PASS] python-version: expected 3.14.6; actual 3.14.6" in result.stdout
    assert result.stdout.endswith(
        "Store: not configured\nActive run: none\nNext action: matchvet\n"
    )


def test_run_and_status_commands_expose_checkpointed_research_only_lifecycle(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    started = run_matchvet("run", "2026-09-18", "--store", str(database_path), "--json")

    assert started.returncode == 0
    assert started.stderr == ""
    run = json.loads(started.stdout)
    assert run["state"] == "COMPLETE"
    assert run["mode"] == "RESEARCH_ONLY"
    assert run["completed_work_units"] == 7
    assert run["total_work_units"] == 7
    assert run["decision_state"] == "NO_DECISION"
    assert "PLAY" not in started.stdout
    assert "AVOID" not in started.stdout

    shown = run_matchvet("status", run["run_id"], "--store", str(database_path))

    assert shown.returncode == 0
    assert shown.stderr == ""
    assert f"Run: {run['run_id']}" in shown.stdout
    assert "State: COMPLETE" in shown.stdout
    assert "Phase: atomic_report_and_audit_publication" in shown.stdout
    assert "Work units: 7/7" in shown.stdout
    assert "Last checkpoint: atomic_report_and_audit_publication" in shown.stdout
    assert "Mode: RESEARCH_ONLY" in shown.stdout
    assert "Decision: NO_DECISION" in shown.stdout


def test_run_command_rejects_a_non_friday_matchweek_date(tmp_path: Path) -> None:
    database_path = tmp_path / "private" / "matchvet.sqlite3"

    result = run_matchvet("run", "2026-09-20", "--store", str(database_path), "--json")

    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert error["code"] == "MV-USAGE-DATE_INVALID"
    assert "Matchweek Friday" in error["explanation"]
    assert not database_path.exists()


def test_human_run_streams_preflight_and_checkpoint_progress(tmp_path: Path) -> None:
    database_path = tmp_path / "private" / "matchvet.sqlite3"

    result = run_matchvet("run", "2026-09-18", "--store", str(database_path))

    assert result.returncode == 0
    assert "Preflight: matchweek=2026-09-18" in result.stdout
    assert "Progress: phase=preflight; work=0/7" in result.stdout
    assert "work=7/7" in result.stdout


def test_resume_command_completes_a_compatible_incomplete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    inputs = build_local_input_contract("2026-09-18")
    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=inputs,
                estimate=_safe_estimate(),
                observation=_safe_observation(),
                executor=_interrupt_evidence,
            )
        run_id = interrupted.value.run_id

    resumed = run_matchvet("resume", run_id, "--store", str(database_path), "--json")

    assert resumed.returncode == 0
    output = json.loads(resumed.stdout)
    assert output["run_id"] == run_id
    assert output["state"] == "COMPLETE"
    assert output["reuse_state"] == "REUSED"
    assert output["work_units"][1]["attempt"] == 2


def test_resume_command_reports_stable_digest_mismatch_error(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        with pytest.raises(RunLifecycleError) as interrupted:
            RunCoordinator(store).start(
                matchweek="2026-09-18",
                inputs=build_local_input_contract("different-matchweek-input"),
                estimate=_safe_estimate(),
                observation=_safe_observation(),
                executor=_interrupt_evidence,
            )
        run_id = interrupted.value.run_id

    refused = run_matchvet("resume", run_id, "--store", str(database_path), "--json")

    assert refused.returncode == 1
    error = json.loads(refused.stdout)
    assert error["status"] == "REFUSED"
    assert error["code"] == "MV-RESUME-DIGEST_MISMATCH"
    assert error["last_checkpoint"] == "preflight"
    assert error["checkpoint_at_utc"] is not None
    assert error["reuse_state"] == "BLOCKED"
    assert error["recovery_command"] == "matchvet run 2026-09-18"


def test_doctor_reports_a_configured_store_without_migrating_it(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    result = run_matchvet(
        "doctor",
        "--json",
        "--store",
        str(database_path),
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["store"] == {
        "applied_migrations": list(range(1, len(MIGRATIONS) + 1)),
        "foreign_key_violations": 0,
        "integrity": "ok",
        "issues": [],
        "limits": {
            "attached_databases": 0,
            "columns": 512,
            "expression_depth": 100,
            "sql_length_bytes": 1_048_576,
        },
        "path": str(database_path),
        "pragmas": {
            "application_id": 1_297_499_476,
            "auto_vacuum": 2,
            "busy_timeout": 5_000,
            "foreign_keys": 1,
            "journal_mode": "wal",
            "synchronous": 2,
        },
        "schema_version": len(MIGRATIONS),
        "status": "HEALTHY",
    }
    assert any(
        check["id"] == "store:integrity" and check["status"] == "PASS" for check in report["checks"]
    )
    assert report["artifacts"] == {
        "corrupt": [],
        "malformed_manifests": [],
        "missing": [],
        "orphans": [],
        "staging_orphans": [],
        "unreferenced": [],
    }


def test_doctor_reports_missing_artifacts_without_repairing_them(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        record = ArtifactStore(store).publish_artifact(b"missing", "text/plain")
    (private_root / record.relative_path).unlink()

    result = run_matchvet("doctor", "--json", "--store", str(database_path))

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["artifacts"]["missing"] == [record.digest]
    assert any(
        check["id"] == "artifacts:integrity" and check["status"] == "FAIL"
        for check in report["checks"]
    )


def test_doctor_reports_corruption_without_repairing_the_store(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.sqlite3"
    original = b"not a sqlite database"
    database_path.write_bytes(original)

    result = run_matchvet("doctor", "--json", "--store", str(database_path))

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["store"]["status"] == "RECOVERY_REQUIRED"
    assert report["store"]["integrity"] == "unreadable"
    assert report["error"]["code"] == "MV-STORE-INTEGRITY_FAILED"
    assert database_path.read_bytes() == original

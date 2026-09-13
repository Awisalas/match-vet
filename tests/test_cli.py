from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from matchvet import cli
from matchvet.artifacts import ArtifactStore
from matchvet.store import MIGRATIONS, open_store

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
        "Store: healthy; schema 2\n"
        "Active run: none\n"
        "Next action: matchvet doctor\n"
    )
    assert database_path.stat().st_mtime_ns == before


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


def test_help_and_unknown_commands_follow_argparse_contract() -> None:
    help_result = run_matchvet("--help")
    unknown_result = run_matchvet("not-a-command")

    assert help_result.returncode == 0
    assert "usage: matchvet" in help_result.stdout
    assert "doctor" in help_result.stdout
    assert unknown_result.returncode == 2
    assert "invalid choice: 'not-a-command'" in unknown_result.stderr


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
        "applied_migrations": [1, 2],
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

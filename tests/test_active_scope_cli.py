import json
from pathlib import Path

import pytest

from matchvet import cli
from matchvet.active_scope import SUCCESSOR_SIX_SCOPE


def test_cli_routes_successor_admission_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "termux_private_root", lambda: tmp_path)
    assert (
        cli.main(
            [
                "fixture-admission",
                "--scope-version",
                "2",
                "--store",
                str(tmp_path / "store.sqlite3"),
                "--json",
            ]
        )
        == 0
    )
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["contract_id"] == "t05-active-fixture-admission-v2"
    assert admitted["active_scope"]["digest"] == SUCCESSOR_SIX_SCOPE.digest
    assert admitted["revision_candidates"] == []
    for version in ("1", "3"):
        with pytest.raises(SystemExit):
            cli.main(["fixture-admission", "--scope-version", version])


def test_ingest_cli_explicit_version_two_remains_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "termux_private_root", lambda: tmp_path)
    result = cli.main(
        [
            "ingest",
            "--scope-version",
            "2",
            "--season",
            "2025-26",
            "--json",
            "--store",
            str(tmp_path / "store.sqlite3"),
        ]
    )
    assert result != 0
    assert "2026-27" in capsys.readouterr().out
    assert not (tmp_path / "store.sqlite3").exists()

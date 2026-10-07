"""Build with pre-77 sources; reconstruct exact CB01 receipt/request/response today.

Run: .venv/bin/python .audit/issue-77-implementation/historical-proof.py
Only temporary stores, archived source, deterministic offline responses and retained
TUF fixtures are used. The signed service response is verified separately by the
focused test_cb01_trust tests, since these synthetic batch tokens are not signatures.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
from collections.abc import Callable, Generator
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

BASE = "6470abf"
ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "src/matchvet/cb01.py": "7de7f617d652329146a3fa3c4f2b9638134dfb3c8d4c931bb35b6a90ac200092",
    "src/matchvet/cb01_trust.py": (
        "4f75585163f353bc6dfcac1e566ee1502562d9a03b7c6e2b1fefc2800974c9be"
    ),
    "docs/product-v2/CANDIDATE-INPUT-METHODOLOGY.md": (
        "1ebeb80f33190f18440d2dcfa5b2526d3907223471f4b2711b7445b0ece8e200"
    ),
}


def _deny_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Historical proof forbids network access.")


class _Factory:
    def __init__(self, root: Path) -> None:
        self.root = root

    def mktemp(self, name: str) -> Path:
        path = self.root / name
        path.mkdir()
        return path


def _child(mode: str, source_root: Path, work: Path, oracle: Path) -> None:
    import pytest
    from issue77_support import RetainedWitness
    from test_cb01_repository import EnrollmentCase, enrollment_case

    import matchvet.cb01
    from matchvet.artifacts import ArtifactStore
    from matchvet.cb01 import BootstrapRepository
    from matchvet.cb01_sources import FixtureEnrollmentInput
    from matchvet.store import open_store

    assert Path(matchvet.cb01.__file__).resolve().is_relative_to(source_root.resolve())
    socket.socket.connect = _deny_network  # type: ignore[method-assign]
    if mode == "build":
        factory = cast(
            Callable[[pytest.TempPathFactory], Generator[EnrollmentCase]],
            cast(Any, enrollment_case).__wrapped__,
        )
        fixture = factory(cast(pytest.TempPathFactory, _Factory(work)))
        case = next(fixture)
        with open_store(case.database, private_root=case.root) as store:
            backend = RetainedWitness()
            result = BootstrapRepository(store, witness_backend=backend).enroll_fixture(
                case.request
            )
            assert result.publication_digest is not None
            artifacts = ArtifactStore(store)
            value = {
                "database": str(case.database),
                "root": str(case.root),
                "request": asdict(case.request),
                "batch": result.batch_digest,
                "publication": result.publication_digest,
                "catalog": [asdict(item) for item in store.artifact_catalog()],
                "bytes": {
                    item.digest: base64.b64encode(artifacts.read_artifact(item.digest)).decode()
                    for item in store.artifact_catalog()
                },
            }
            oracle.write_text(json.dumps(value))
        fixture.close()
        print("pre-77 source built a deterministic complete legacy CB01 receipt", flush=True)
    else:
        from matchvet.cb01_replay import RetainedCB01Artifacts

        value = json.loads(oracle.read_text())
        with open_store(Path(value["database"]), private_root=Path(value["root"])) as store:
            backend = RetainedWitness()
            repository = BootstrapRepository(store, witness_backend=backend)
            repository.artifacts = RetainedCB01Artifacts(store)
            before = [asdict(item) for item in store.artifact_catalog()]
            with patch.object(
                ArtifactStore,
                "publish_artifact",
                side_effect=AssertionError("Historical reconstruction must not publish"),
            ):
                replayed_case = repository.replay(value["publication"])
                assert replayed_case.batch_digest == value["batch"]
                result = repository.enroll_fixture(FixtureEnrollmentInput(**value["request"]))
            assert result.publication_digest == value["publication"]
            assert backend.request_count == backend.refresh_count == 0
            assert [asdict(item) for item in store.artifact_catalog()] == before == value["catalog"]
            for digest, content in value["bytes"].items():
                assert ArtifactStore(store).read_artifact(digest) == base64.b64decode(content)
            print(
                f"current reader reconstructed {len(replayed_case.records)} exact legacy records; "
                "zero replay publication writes",
                flush=True,
            )
            summary = {
                "base_commit": BASE,
                "artifact_count": len(before),
                "record_count": len(replayed_case.records),
                "exact_batch_digest": replayed_case.batch_digest,
                "exact_publication_digest": replayed_case.publication_digest,
                "catalog_writes": 0,
                "replay_publication_writes": 0,
                "network_calls": 0,
                "historical_sha256": EXPECTED,
            }
            (ROOT / ".audit/issue-77-implementation/historical-proof-result.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("build", "replay"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--oracle", type=Path)
    args = parser.parse_args()
    if args.mode:
        _child(args.mode, args.source, args.work, args.oracle)
        return
    for filename, digest in EXPECTED.items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
        old = subprocess.run(
            ["git", "show", f"{BASE}:{filename}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        assert (ROOT / filename).read_bytes() == old
    with TemporaryDirectory(prefix="matchvet-issue77-history-") as directory:
        work = Path(directory)
        source = work / "old"
        source.mkdir()
        archive = subprocess.run(
            [
                "git",
                "archive",
                BASE,
                "src",
                "tests",
                "docs/research/cb01-sigstore-witness-2026-10-05",
            ],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            files.extractall(source, filter="data")
        oracle = work / "oracle.json"
        for mode, origin in (("build", source), ("replay", ROOT)):
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(
                str(path) for path in (origin / "src", origin / "tests", ROOT / "tests")
            )
            subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "--mode",
                    mode,
                    "--source",
                    str(origin),
                    "--work",
                    str(work),
                    "--oracle",
                    str(oracle),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )


if __name__ == "__main__":
    main()

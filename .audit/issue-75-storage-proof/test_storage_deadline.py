"""Isolated proof of the existing manifest publication deadline gap, not a selector."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import matchvet.artifacts as artifact_module
from matchvet.artifacts import (
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    SnapshotManifest,
)
from matchvet.store import CanonicalIdentifier, StoreBusyError, open_store

EARLY = "2026-09-25T11:59:59.000000+00:00"
CUTOFF = "2026-09-25T12:00:00.000000+00:00"
LATE = "2026-09-25T12:00:01.000000+00:00"
SNAPSHOT_ID = "00000000-0000-7000-8000-000000000003"


def _identifier(kind: str, tail: int) -> CanonicalIdentifier:
    return CanonicalIdentifier(kind, f"00000000-0000-7000-8000-{tail:012d}")


def _child(root: Path, mode: str) -> None:
    """Inject only time and the SQLite commit system boundary, in a separate process."""
    original_connect = sqlite3.connect
    clock = [EARLY]
    armed = [False]
    artifact_module._utc_now = lambda: clock[0]

    class Connection(sqlite3.Connection):
        def commit(self) -> None:
            if armed[0]:
                # The pending manifest is in the real SQLite transaction. Advance the
                # repository clock before its durable FULL-WAL commit, without sleeping.
                assert self.execute("SELECT count(*) FROM snapshot_manifests").fetchone() == (1,)
                clock[0] = {"early": EARLY, "equal": CUTOFF}.get(mode, LATE)
            super().commit()
            if armed[0] and mode == "crash":
                os._exit(37)

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, **kwargs, factory=Connection)

    with (
        patch("sqlite3.connect", side_effect=connect),
        open_store(root / "matchvet.sqlite3", private_root=root) as store,
    ):
        artifacts = ArtifactStore(store)
        record = artifacts.publish_artifact(b"synthetic dependency", "text/plain")
        manifest = SnapshotManifest(
            snapshot_id=_identifier("snapshot_manifest", 3),
            matchweek_id=_identifier("matchweek", 4),
            research_cutoff_id=_identifier("research_cutoff", 5),
            version_manifest_id=_identifier("version_manifest", 6),
            research_cutoff_utc=CUTOFF,
            artifacts=(
                ManifestArtifact(
                    record.artifact_id, record.digest, record.media_type, record.byte_length
                ),
            ),
            versions=(),
            retention_omissions=(),
            completeness=ManifestCompleteness("COMPLETE"),
            created_at_utc=EARLY,
        )
        armed[0] = True
        published = artifacts.publish_manifest(manifest)
        armed[0] = False
        print(json.dumps({"digest": published.digest, "returned_at": clock[0]}), flush=True)


def _publish_and_reopen(root: Path, mode: str) -> tuple[bytes, dict[str, Any]]:
    root.mkdir()
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(root), mode],
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == (37 if mode == "crash" else 0), child.stderr
    report = json.loads(child.stdout) if child.stdout else {"crashed_after_commit": True}
    with open_store(root / "matchvet.sqlite3", private_root=root) as reopened:
        digest = reopened.snapshot_manifest_digest_for_snapshot(SNAPSHOT_ID)
        assert digest is not None
        artifacts = ArtifactStore(reopened)
        manifest = artifacts.verify_manifest(digest)
        assert manifest.completeness.state == "COMPLETE"
        assert manifest.verified_at_utc == EARLY
        assert artifacts.inspect().orphans == ()
        report["digest_after_restart"] = digest
        report["verified_at_after_restart"] = manifest.verified_at_utc
        return artifacts.read_artifact(digest), report


@pytest.mark.parametrize("mode", ["equal", "late", "crash"])
def test_restart_cannot_distinguish_timely_completion_from_late_or_unconfirmed_commit(
    tmp_path: Path, mode: str
) -> None:
    good_bytes, timely = _publish_and_reopen(tmp_path / "early", "early")
    bad_bytes, unqualified = _publish_and_reopen(tmp_path / mode, mode)
    assert timely["returned_at"] < CUTOFF
    if mode != "crash":
        assert unqualified["returned_at"] >= CUTOFF
    # Same digest and every SnapshotManifest byte despite different completion histories.
    assert bad_bytes == good_bytes
    print(json.dumps({"scenario": mode, "timely": timely, "unqualified": unqualified}))


def test_existing_store_excludes_a_concurrent_writer(tmp_path: Path) -> None:
    with (
        open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path),
        pytest.raises(StoreBusyError),
    ):
        open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path)


if __name__ == "__main__":
    _child(Path(sys.argv[1]), sys.argv[2])

"""Compare real historical codecs and migrations with the pinned implementation base."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from test_artifacts import _manifest, _version

from matchvet.artifacts import ManifestArtifact, SnapshotManifest
from matchvet.store import MIGRATIONS, CanonicalIdentifier

BASE = "5c70bb2"


def load_baseline(name: str, source: str, directory: Path):
    path = directory / f"{name}.py"
    path.write_bytes(subprocess.check_output(["git", "show", f"{BASE}:{source}"]))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


with tempfile.TemporaryDirectory(prefix="issue75-codec-") as root:
    directory = Path(root)
    legacy = load_baseline("issue75_legacy_artifacts", "src/matchvet/artifacts.py", directory)
    legacy_store = load_baseline("issue75_legacy_store", "src/matchvet/store.py", directory)
    manifest = _manifest(
        ManifestArtifact(
            CanonicalIdentifier("artifact", "00000000-0000-7000-8000-000000000007"),
            "2" * 64,
            "text/plain",
            17,
        ),
        _version(),
    )
    digests = []
    for item in (
        manifest,
        replace(manifest, verification_state="VERIFIED", verified_at_utc=manifest.created_at_utc),
    ):
        content = item.to_bytes()
        old = legacy.SnapshotManifest.from_bytes(content)
        assert old.to_bytes() == content
        assert old.digest == item.digest
        assert SnapshotManifest.from_bytes(old.to_bytes()).to_bytes() == content
        digests.append(item.digest)
    assert [(m.number, m.checksum) for m in MIGRATIONS] == [
        (m.number, m.checksum) for m in legacy_store.MIGRATIONS
    ]
    print(
        json.dumps(
            {
                "base": BASE,
                "legacy_roundtrip_digests": digests,
                "unchanged_migrations": len(MIGRATIONS),
                "sqlite_opened": False,
            },
            indent=2,
        )
    )

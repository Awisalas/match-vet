"""Run one public-seam test against a copy of a retained synthetic pytest slate.

This speeds red/green iterations without rebuilding the deterministic F16 graph.
The final focused pytest run builds its own complete isolated fixtures as usual.
Only roots inside the system temporary directory are accepted.
"""

from __future__ import annotations

import argparse
import inspect
import json
import shutil
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from matchvet.artifacts import ArtifactStore  # noqa: E402
from matchvet.cb01_sources import FixtureEnrollmentInput  # noqa: E402
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository  # noqa: E402
from matchvet.matchweek_research import MatchweekResearchRepository  # noqa: E402
from matchvet.store import open_store  # noqa: E402


def main() -> None:
    import pytest
    import test_issue77

    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("test")
    parser.add_argument("--kwargs", type=json.loads, default={})
    args = parser.parse_args()
    assert args.source.resolve().is_relative_to(Path(gettempdir()).resolve())
    assert args.source.name.startswith("issue77-slate")
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Offline only")),
        TemporaryDirectory(prefix="issue77-slice-") as directory,
    ):
        root = Path(directory)
        shutil.copytree(args.source / "objects", root / "objects")
        shutil.copyfile(args.source / "store.sqlite3", root / "store.sqlite3")
        with open_store(root / "store.sqlite3", private_root=root) as store:
            selected = MatchweekResearchRepository(store).replay_for_matchweek(
                season="2026-27", matchweek_friday="2026-09-25"
            )
            freeze = MatchweekMembershipRepository(store).get_by_id(selected.freeze_id)
            assert freeze is not None
            manifest = json.loads(ArtifactStore(store).read_artifact(selected.f16_manifest_digest))
            kickoffs = {
                item.membership_id: item.controlling_revision.kickoff_utc
                for item in freeze.memberships
            }
            requests = tuple(
                FixtureEnrollmentInput(
                    freeze.freeze_id,
                    row["membership_id"],
                    row["cutoff_id"],
                    manifest["profile_digest"],
                    selected.f16_manifest_digest,
                )
                for row in sorted(
                    manifest["matches"], key=lambda row: kickoffs[row["membership_id"]] or ""
                )
            )
            slate = test_issue77.Slate(
                root,
                freeze.freeze_digest,
                selected.policy_digest,
                manifest["profile_digest"],
                selected.digest,
                requests,
            )
            function = getattr(test_issue77, args.test)
            with pytest.MonkeyPatch.context() as monkeypatch:
                supplied = {"slate_store": store, "slate": slate, "monkeypatch": monkeypatch}
                supplied.update(args.kwargs)
                function(**{key: supplied[key] for key in inspect.signature(function).parameters})
            print(f"PASS {args.test}")


if __name__ == "__main__":
    main()

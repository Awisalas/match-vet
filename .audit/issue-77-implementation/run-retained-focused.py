"""Run #77 pytest cases using the synthetic selected slate retained earlier this run.

All stores are new temporary copies. The selected graph replays before use; each
slate_store fixture makes another isolated copy. No domain validation is mocked.
This avoids repeating the expensive two-fixture F16 construction during review.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
from pathlib import Path
from tempfile import gettempdir
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def main() -> None:
    import pytest
    import test_issue77

    from matchvet.artifacts import ArtifactStore
    from matchvet.cb01_sources import FixtureEnrollmentInput
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import MatchweekResearchRepository
    from matchvet.store import open_store

    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--exclude-outcomes", action="store_true")
    args = parser.parse_args()
    assert args.source.resolve().is_relative_to(Path(gettempdir()).resolve())
    assert args.source.name.startswith("issue77-slate")

    @pytest.fixture(scope="module")
    def retained_slate(tmp_path_factory: pytest.TempPathFactory) -> test_issue77.Slate:
        root = tmp_path_factory.mktemp("issue77-retained-pytest")
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
                m.membership_id: m.controlling_revision.kickoff_utc for m in freeze.memberships
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
        return test_issue77.Slate(
            root,
            freeze.freeze_digest,
            selected.policy_digest,
            manifest["profile_digest"],
            selected.digest,
            requests,
        )

    test_issue77.slate = retained_slate
    pytest_args = ["tests/test_issue77.py", "tests/test_issue77_history.py", "-q", "-x"]
    if args.exclude_outcomes:
        pytest_args.extend(["-k", "not test_f19_outcomes_append_without_changing_frozen_inputs"])
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Offline only")):
        result = pytest.main(pytest_args)
    raise SystemExit(result)


if __name__ == "__main__":
    main()

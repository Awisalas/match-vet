from __future__ import annotations

import hashlib
import shutil
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from test_match_evidence_cutoff import _freeze

from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f13 import engine_version_identity
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekError, AnalyzeMatchweekRequest
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.runs import RunState
from matchvet.store import Store, open_store


@dataclass(frozen=True)
class F15Fixture:
    database: Path
    root: Path
    request: AnalyzeMatchweekRequest


@pytest.fixture(scope="module")
def f15_fixture(tmp_path_factory: pytest.TempPathFactory) -> F15Fixture:
    root = Path("/data/data/com.termux/files/home/projects/match-vet/.audit/f15/test-store")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    database = root / "matchvet.sqlite3"
    with open_store(database, private_root=root) as store:
        freeze_id = _freeze(store, root)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy_digest = cutoffs.persist_policy(CutoffPolicy("test", "f15", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, policy_digest)[0]
        profiles = PreferenceProfileRepository(store)
        profile = profiles.build_profile(("match_winner_home",))
        request = AnalyzeMatchweekRequest(
            matchweek="2026-09-25",
            freeze_id=freeze_id,
            cutoff_policy_digest=policy_digest,
            cutoff_ids=(cutoff.cutoff_id,),
            research_contract_digest=V2_REQUIREMENT_CATALOG.digest,
            model_version_identity=engine_version_identity(),
            preference_profile_digest=profile.digest,
        )
    return F15Fixture(database, root, request)


@pytest.fixture
def f15_store(f15_fixture: F15Fixture, tmp_path: Path) -> Generator[Store]:
    root = tmp_path / "store"
    root.mkdir()
    database = root / "matchvet.sqlite3"
    shutil.copytree(f15_fixture.root / "objects", root / "objects")
    shutil.copyfile(f15_fixture.database, database)
    with open_store(database, private_root=root) as store:
        yield store


def test_start_produces_durable_t04_progress_without_claiming_matchweek_complete(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    progress = AnalyzeMatchweek(f15_store).start(f15_fixture.request)
    assert not any("F13_RESULT" in identity for identity in progress.durable_result_identities)

    assert progress.run_id
    assert progress.run_state is RunState.INCOMPLETE
    assert progress.phase.value == "preflight"
    assert progress.analysis_state == "IN_PROGRESS"
    assert any(
        identity.startswith("F06:sha256:") for identity in progress.durable_result_identities
    )
    assert (
        progress.t04_status.input_digests["model"]
        == hashlib.sha256(
            ("F13_ENGINE:" + f15_fixture.request.model_version_identity).encode()
        ).hexdigest()
    )
    assert progress.analysis_complete is False
    assert progress.matchweek_result_identity is None
    assert progress.t04_status.work_units[0].attempt_state == "INTERRUPTED"


def test_compatible_unfinished_run_is_resumed_by_exact_run_id(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    service = AnalyzeMatchweek(f15_store)
    first = service.start(f15_fixture.request)
    resumed = service.resume(first.run_id, f15_fixture.request)

    assert resumed.run_id == first.run_id
    assert resumed.run_state is RunState.INCOMPLETE
    assert resumed.analysis_complete is False


def test_changed_predecessor_input_refuses_resume(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    service = AnalyzeMatchweek(f15_store)
    first = service.start(f15_fixture.request)
    changed = replace(
        f15_fixture.request,
        model_version_identity="0" * 64,
    )

    with pytest.raises(AnalyzeMatchweekError):
        service.resume(first.run_id, changed)


def test_missing_predecessor_artifact_fails_closed(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    metadata = f15_store.artifact_metadata(f15_fixture.request.preference_profile_digest)
    assert metadata is not None
    artifact_path = f15_store.path.parent / metadata.relative_path
    artifact_path.write_bytes(b"corrupt")

    with pytest.raises(AnalyzeMatchweekError):
        AnalyzeMatchweek(f15_store).start(f15_fixture.request)

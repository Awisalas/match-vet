from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_match_evidence_cutoff import _freeze

from matchvet.artifacts import ArtifactStore
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import ModelContractRepository
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import MANIFEST_MEDIA_TYPE, F16MatchweekProcessor
from matchvet.f19 import F19Error, SettlementRepository, SettlementState
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import Store, open_store
from matchvet.t10 import SettlementEvidence, SettlementResult
from matchvet.t15 import PolicyVersion


@dataclass(frozen=True)
class F19Fixture:
    database: Path
    root: Path


@pytest.fixture(scope="module")
def f19_fixture(tmp_path_factory: pytest.TempPathFactory) -> F19Fixture:
    root = tmp_path_factory.mktemp("f19-baseline")
    database = root / "matchvet.sqlite3"
    with open_store(database, private_root=root) as store:
        freeze_id = _freeze(store, root)
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy_digest = cutoffs.persist_policy(CutoffPolicy("test", "f19", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, cutoff_policy_digest)[0]
        evidence = F11EvidenceRepository(store).build_or_replay_for_freeze(
            freeze_id, cutoff_policy_digest
        )
        ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=())
        profile = PreferenceProfileRepository(store).build_profile(
            ("asian_handicap_home_0_0", "match_winner_home")
        )
        policy = PolicyVersion(version="research-policy-v1")
        context = WorkContext(
            run_id="f19-test",
            stable_key="f19-test",
            matchweek="2026-09-25",
            phase=RunPhase.PREFERENCE_VETTING,
            attempt=1,
            mode="TEST",
            input_digest="0" * 64,
            predecessor_digest="0" * 64,
            cpu_concurrency=1,
        )
        F16MatchweekProcessor(store, legacy_research=True).process_phase(
            context,
            freeze_id=freeze_id,
            cutoff_policy_digest=cutoff_policy_digest,
            cutoff_ids=(cutoff.cutoff_id,),
            profile_digest=profile.digest,
            policy=policy,
        )
    return F19Fixture(database, root)


@pytest.fixture
def f19_store(f19_fixture: F19Fixture, tmp_path: Path) -> Generator[Store]:
    root = tmp_path / "store"
    root.mkdir()
    database = root / "matchvet.sqlite3"
    shutil.copytree(f19_fixture.root / "objects", root / "objects")
    shutil.copyfile(f19_fixture.database, database)
    with open_store(database, private_root=root) as store:
        yield store


def _f16_lineage(store: Store) -> tuple[str, str, str]:
    manifest_digest = next(
        metadata.digest
        for metadata in store.artifact_catalog()
        if metadata.media_type == MANIFEST_MEDIA_TYPE
    )
    manifest = json.loads(ArtifactStore(store).read_artifact(manifest_digest))
    match_result_digest = manifest["matches"][0]["match_result_digest"]
    fixture_id = json.loads(ArtifactStore(store).read_artifact(match_result_digest))["fixture_id"]
    return manifest_digest, match_result_digest, fixture_id


def test_f19_versions_preserve_lineage_evidence_and_t10_outcomes(f19_store: Store) -> None:
    manifest_digest, match_result_digest, fixture_id = _f16_lineage(f19_store)
    repository = SettlementRepository(f19_store)

    unknown = SettlementEvidence(
        fixture_id=fixture_id,
        source_key="competition-feed",
        record_id="fixture-unknown",
        fixture_status="UNKNOWN",
        full_time_home_goals=1,
        full_time_away_goals=0,
        provenance={"capture_digest": "a" * 64, "source_url": "https://example.test/result"},
    )
    pending = repository.build(
        manifest_digest, match_result_digest, "match_winner_home", (unknown,)
    )
    assert pending.state is SettlementState.PENDING
    assert pending.settlement_result is None
    assert repository.replay(pending.digest) == pending
    assert (
        repository.build(manifest_digest, match_result_digest, "match_winner_home", (unknown,))
        == pending
    )
    metadata = f19_store.artifact_metadata(pending.digest)
    assert metadata is not None and metadata.retention_class == "PROTECTED"

    wrong_match = SettlementEvidence(
        fixture_id="another-fixture",
        source_key="competition-feed",
        fixture_status="FINISHED",
        full_time_home_goals=1,
        full_time_away_goals=0,
    )
    with pytest.raises(F19Error, match="another fixture"):
        repository.build(manifest_digest, match_result_digest, "match_winner_home", (wrong_match,))
    bookmaker_data = SettlementEvidence(
        fixture_id=fixture_id,
        source_key="competition-feed",
        fixture_status="FINISHED",
        full_time_home_goals=2,
        full_time_away_goals=0,
        provenance={"bookmaker": {"price": 1.8}},
    )
    with pytest.raises(F19Error, match="Bookmaker odds"):
        repository.build(
            manifest_digest, match_result_digest, "match_winner_home", (bookmaker_data,)
        )

    final_home_win = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="competition-feed",
        record_id="score-final-win",
        fixture_status="FINISHED",
        full_time_home_goals=2,
        full_time_away_goals=0,
    )
    with pytest.raises(F19Error, match="requires its predecessor"):
        repository.build(
            manifest_digest,
            match_result_digest,
            "match_winner_home",
            (final_home_win,),
        )
    win = repository.correct(pending.digest, (final_home_win,))
    assert win.state is SettlementState.WIN
    assert win.settlement_result is SettlementResult.WIN
    assert win.predecessor_digest == pending.digest
    assert win.correction_sequence == 1
    assert repository.correct(pending.digest, (final_home_win,)) == win

    conflict_a = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="league",
        record_id="official-v1",
        fixture_status="FINISHED",
        full_time_home_goals=2,
        full_time_away_goals=0,
    )
    conflict_b = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="league",
        record_id="official-v2",
        fixture_status="FINISHED",
        full_time_home_goals=0,
        full_time_away_goals=2,
    )
    conflicting = repository.correct(win.digest, (conflict_a, conflict_b))
    assert conflicting.state is SettlementState.CONFLICTING
    assert conflicting.settlement_result is None
    assert set(conflicting.to_dict()["grade"]["provenance"]["conflict_evidence_ids"]) == {
        conflict_a.evidence_id,
        conflict_b.evidence_id,
    }

    loss_evidence = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="league",
        fixture_status="FINISHED",
        full_time_home_goals=0,
        full_time_away_goals=1,
    )
    loss = repository.correct(conflicting.digest, (loss_evidence,))
    assert loss.settlement_result is SettlementResult.LOSS
    assert loss.predecessor_digest == conflicting.digest

    void_evidence = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="league",
        fixture_status="CANCELLED",
    )
    void = repository.correct(loss.digest, (void_evidence,))
    assert void.settlement_result is SettlementResult.VOID
    assert void.predecessor_digest == loss.digest
    assert repository.replay(pending.digest) == pending

    push_evidence = SettlementEvidence(
        fixture_id=fixture_id,
        source_level="COMPETITION",
        source_key="league",
        fixture_status="FINISHED",
        full_time_home_goals=1,
        full_time_away_goals=1,
    )
    push = repository.build(
        manifest_digest, match_result_digest, "asian_handicap_home_0_0", (push_evidence,)
    )
    assert push.state is SettlementState.PUSH
    assert push.settlement_result is SettlementResult.PUSH

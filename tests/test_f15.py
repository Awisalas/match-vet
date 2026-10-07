from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from test_match_evidence_cutoff import _freeze

from matchvet.artifacts import ArtifactStore
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f13 import engine_version_identity
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekError, AnalyzeMatchweekRequest
from matchvet.f16 import MANIFEST_MEDIA_TYPE, F16Error, F16MatchweekProcessor
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.runs import RunLifecycleError, RunState
from matchvet.store import Store, open_store
from matchvet.t15 import PolicyStatus, PolicyVersion


@dataclass(frozen=True)
class F15Fixture:
    database: Path
    root: Path
    request: AnalyzeMatchweekRequest


@pytest.fixture(scope="module")
def f15_fixture(tmp_path_factory: pytest.TempPathFactory) -> F15Fixture:
    root = tmp_path_factory.mktemp("f15-baseline")
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
            policy=PolicyVersion(version="research-policy-v1"),
        )
        completed = AnalyzeMatchweek(store, legacy_research=True).start(request)
        assert completed.phase.value == "audit_verification"
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
    progress = AnalyzeMatchweek(f15_store, legacy_research=True).start(f15_fixture.request)
    assert progress.run_id
    assert progress.run_state is RunState.INCOMPLETE
    assert progress.phase.value == "audit_verification"
    assert progress.analysis_state == "F16_COMPLETE_AWAITING_F17"
    assert any(identity.startswith("F16_MATCH:") for identity in progress.durable_result_identities)
    assert any(
        identity.startswith("F16_MANIFEST:") for identity in progress.durable_result_identities
    )
    assert any(
        identity.startswith("F06:sha256:") for identity in progress.durable_result_identities
    )
    assert (
        progress.t04_status.input_digests["model"]
        == hashlib.sha256(
            ("F13_ENGINE:" + f15_fixture.request.model_version_identity).encode()
        ).hexdigest()
    )
    expected_policy = (
        "T15_POLICY:" + f15_fixture.request.policy.version + ":" + f15_fixture.request.policy.digest
    )
    assert (
        progress.t04_status.input_digests["policy"]
        == hashlib.sha256(expected_policy.encode()).hexdigest()
    )
    assert "T15_POLICY:" + f15_fixture.request.policy.digest in progress.durable_result_identities
    assert progress.analysis_complete is False
    assert progress.matchweek_result_identity is None
    assert progress.t04_status.work_units[5].attempt_state == "INTERRUPTED"


def test_f16_manifest_covers_each_included_membership_and_all_preferences(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    progress = AnalyzeMatchweek(f15_store, legacy_research=True).start(f15_fixture.request)
    identity = next(
        item for item in progress.durable_result_identities if item.startswith("F16_MANIFEST:")
    )
    manifest_digest = identity.rsplit(":sha256:", 1)[1]
    manifest = json.loads(ArtifactStore(f15_store).read_artifact(manifest_digest))
    replayed = F16MatchweekProcessor(f15_store).replay_manifest(manifest_digest)

    assert replayed.digest == manifest_digest
    assert replayed.to_dict() == manifest
    assert tuple(item.membership_id for item in replayed.match_results) == tuple(
        row["membership_id"] for row in manifest["matches"]
    )
    assert len(manifest["matches"]) == 1
    result = manifest["matches"][0]
    match_digest = result["match_result_digest"]
    match_result = json.loads(ArtifactStore(f15_store).read_artifact(match_digest))
    decision = json.loads(ArtifactStore(f15_store).read_artifact(result["decision_digest"]))
    evidence = json.loads(ArtifactStore(f15_store).read_artifact(result["evidence_digest"]))
    model = json.loads(ArtifactStore(f15_store).read_artifact(result["model_digest"]))
    assert match_result["membership_id"] == result["membership_id"]
    assert match_result["membership_digest"] == result["membership_digest"]
    assert match_result["cutoff_id"] == result["cutoff_id"]
    assert match_result["cutoff_digest"] == result["cutoff_digest"]
    assert match_result["evidence_digest"] == result["evidence_digest"]
    assert match_result["model_digest"] == result["model_digest"]
    assert match_result["decision_digest"] == result["decision_digest"]
    assert decision["status"] == "RESEARCH_ONLY"
    assert decision["outcome"] == "AVOID MATCH"
    assert {row["terminal_result"] for row in decision["preference_results"]} <= {
        "PRIMARY_RECOMMENDATION",
        "SURVIVES_NOT_SELECTED",
        "REJECTED",
    }
    assert len(decision["preference_results"]) == 1
    assert decision["lineage"]["evidence_digest"] == result["evidence_digest"]
    assert decision["lineage"]["cutoff_id"] == result["cutoff_id"]
    assert decision["lineage"]["f13_model_result_digest"] == result["model_digest"]
    assert decision["lineage"]["profile_digest"] == f15_fixture.request.preference_profile_digest
    assert decision["lineage"]["t15_policy_digest"] == f15_fixture.request.policy.digest
    assert evidence["matches"][0]["weather"]["state"] == "UNKNOWN"
    assert all(
        row["model_availability"] != "AVAILABLE" or row["calibrated"]["status"] != "AVAILABLE"
        for row in model["results"].values()
    )


def test_f16_completion_rejects_manifest_missing_included_match(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    progress = AnalyzeMatchweek(f15_store, legacy_research=True).start(f15_fixture.request)
    manifest_digest = next(
        item.rsplit(":sha256:", 1)[1]
        for item in progress.durable_result_identities
        if item.startswith("F16_MANIFEST:")
    )
    malformed = json.loads(ArtifactStore(f15_store).read_artifact(manifest_digest))
    malformed["matches"] = []
    invalid = ArtifactStore(f15_store).publish_artifact(
        canonical_json(malformed).encode(), MANIFEST_MEDIA_TYPE
    )

    with pytest.raises(F16Error):
        F16MatchweekProcessor(f15_store).replay_manifest(invalid.digest)

    with pytest.raises(F16Error):
        F16MatchweekProcessor(f15_store).completed_artifact_identities(
            freeze_id=f15_fixture.request.freeze_id,
            cutoff_policy_digest=f15_fixture.request.cutoff_policy_digest,
            profile_digest=f15_fixture.request.preference_profile_digest,
            policy=f15_fixture.request.policy,
        )


def test_compatible_unfinished_run_is_resumed_by_exact_run_id(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    service = AnalyzeMatchweek(f15_store, legacy_research=True)
    first = service.start(f15_fixture.request)
    before = tuple(item.digest for item in f15_store.artifact_catalog())
    resumed = service.resume(first.run_id, f15_fixture.request)
    after = tuple(item.digest for item in f15_store.artifact_catalog())

    assert resumed.run_id == first.run_id
    assert resumed.run_state is RunState.INCOMPLETE
    assert resumed.analysis_complete is False
    assert resumed.phase.value == "audit_verification"
    assert resumed.analysis_state == "F16_COMPLETE_AWAITING_F17"
    assert resumed.durable_result_identities == first.durable_result_identities
    assert after == before


def test_changed_predecessor_input_refuses_resume(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    service = AnalyzeMatchweek(f15_store, legacy_research=True)
    first = service.start(f15_fixture.request)
    changed = replace(
        f15_fixture.request,
        model_version_identity="0" * 64,
    )

    with pytest.raises(AnalyzeMatchweekError):
        service.resume(first.run_id, changed)


def test_changed_policy_refuses_resume(f15_store: Store, f15_fixture: F15Fixture) -> None:
    service = AnalyzeMatchweek(f15_store, legacy_research=True)
    first = service.start(f15_fixture.request)
    changed = replace(
        f15_fixture.request,
        policy=PolicyVersion(version="research-policy-v2"),
    )

    with pytest.raises(RunLifecycleError) as error:
        service.resume(first.run_id, changed)
    assert error.value.error.code == "MV-RESUME-DIGEST_MISMATCH"


def test_promoted_policy_is_rejected(f15_store: Store, f15_fixture: F15Fixture) -> None:
    request = replace(
        f15_fixture.request,
        policy=PolicyVersion(
            version="promoted-policy-v1",
            status=PolicyStatus.PRODUCTION_PROMOTED,
        ),
    )

    with pytest.raises(AnalyzeMatchweekError):
        AnalyzeMatchweek(f15_store, legacy_research=True).start(request)


def test_malformed_policy_is_rejected(f15_store: Store, f15_fixture: F15Fixture) -> None:
    request = replace(f15_fixture.request, policy={"version": "broken"})  # type: ignore[arg-type]

    with pytest.raises(AnalyzeMatchweekError):
        AnalyzeMatchweek(f15_store, legacy_research=True).start(request)


def test_missing_predecessor_artifact_fails_closed(
    f15_store: Store, f15_fixture: F15Fixture
) -> None:
    metadata = f15_store.artifact_metadata(f15_fixture.request.preference_profile_digest)
    assert metadata is not None
    artifact_path = f15_store.path.parent / metadata.relative_path
    artifact_path.write_bytes(b"corrupt")

    with pytest.raises(AnalyzeMatchweekError):
        AnalyzeMatchweek(f15_store, legacy_research=True).start(f15_fixture.request)

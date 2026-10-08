from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from matchweek_research_support import (
    BEFORE,
    CUTOFF,
    RECEIPT,
    SELECTION,
    Clock,
    install_commit_boundary,
)
from test_matchweek_membership import _persistable_schedule_assessment

from matchvet.artifacts import ArtifactStore
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import F16MatchweekProcessor
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    MatchweekResearchError,
    MatchweekResearchRepository,
    TrustedUTCUpperBound,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import Store, open_store
from matchvet.t15 import PolicyVersion


@dataclass(frozen=True)
class Graph:
    root: Path
    f16: str
    freeze: str
    policy: str
    inputs_root: Path


def _copy_inputs(store: Store, root: Path) -> None:
    shutil.copytree(store.path.parent / "objects", root / "objects")
    with sqlite3.connect(root / "store.sqlite3") as connection:
        store._connection_for_repository().backup(connection)


@pytest.fixture(scope="module")
def graph(tmp_path_factory: pytest.TempPathFactory) -> Graph:
    root = tmp_path_factory.mktemp("research-graph")
    with open_store(root / "store.sqlite3", private_root=root) as store:
        assessment = _persistable_schedule_assessment(
            store,
            root,
            (("2026-09-25", "20:00", "Friday United", "Friday City"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 14, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(
            CutoffPolicy(
                "test-common",
                "1",
                21600,
                rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
            )
        )
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, policy)
        assert {item.cutoff_at_utc for item in boundaries} == {
            CUTOFF.isoformat(timespec="microseconds")
        }
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        inputs_root = tmp_path_factory.mktemp("research-predecessors")
        _copy_inputs(store, inputs_root)
        context = WorkContext(
            "synthetic",
            "synthetic",
            "2026-09-25",
            RunPhase.PREFERENCE_VETTING,
            1,
            "RESEARCH_ONLY",
            "0" * 64,
            "0" * 64,
            1,
        )
        result = F16MatchweekProcessor(store, clock=Clock()).process_phase(
            context,
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=policy,
            cutoff_ids=tuple(sorted(item.cutoff_id for item in boundaries)),
            profile_digest=profile.digest,
            policy=PolicyVersion(version="research-policy-v1"),
        )
        digest = result.result_digest
    return Graph(root, digest, freeze.freeze_id, policy, inputs_root)


@pytest.fixture
def research_store(graph: Graph, tmp_path: Path) -> Generator[Store]:
    shutil.copytree(graph.root / "objects", tmp_path / "objects")
    shutil.copyfile(graph.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


def test_fresh_complete_selection_and_receipt_replay_exactly(
    research_store: Store,
    graph: Graph,
) -> None:
    repository = MatchweekResearchRepository(research_store, clock=Clock())
    selected = repository.seal_completed(graph.f16)
    assert selected.f16_manifest_digest == graph.f16
    assert selected.cutoff_at_utc == "2026-09-25T13:00:00.000000+00:00"
    assert selected == repository.replay(selected.digest)
    assert selected == repository.replay_for_matchweek(
        season="2026-27", matchweek_friday="2026-09-25"
    )
    receipt = ArtifactStore(research_store).verify_manifest(selected.completion_receipt_digest)
    assert receipt.created_at_utc == "2026-09-25T12:00:00.000000+00:00"


def test_object_sync_crossing_cutoff_cannot_start_selection_commit(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from matchvet.research_identity import logical_matchweek_id, selection_slot

    clock = Clock()
    sync = os.fsync

    def crossing_sync(descriptor: int) -> None:
        sync(descriptor)
        operation = research_store._research_owner
        if operation is not None and operation._phase == "selection_attempt":
            clock.value = CUTOFF

    monkeypatch.setattr(os, "fsync", crossing_sync)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=clock).seal_completed(graph.f16)
    assert (
        research_store.snapshot_manifest_digest_for_snapshot(
            selection_slot(logical_matchweek_id("2026-27", "2026-09-25"))
        )
        is None
    )


@pytest.mark.parametrize("value", [CUTOFF, CUTOFF.replace(hour=14)])
def test_cutoff_equality_and_late_proposals_never_assign_a_slot(
    research_store: Store,
    graph: Graph,
    value: datetime,
) -> None:
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        MatchweekResearchRepository(research_store, clock=Clock(value)).seal_completed(graph.f16)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None


@pytest.mark.parametrize(
    "confidence,source,value",
    [
        ("UNESTABLISHED", "system-utc", BEFORE),
        ("SYNCHRONIZED", "system-utc", BEFORE),
        ("TRUSTED", "", BEFORE),
        ("TRUSTED", "test", BEFORE.replace(tzinfo=None)),
    ],
)
def test_clock_uncertainty_refuses_prospective_assignment(
    research_store: Store,
    graph: Graph,
    confidence: str,
    source: str,
    value: datetime,
) -> None:
    class UncertainClock:
        def observe(self) -> TrustedUTCUpperBound:
            return TrustedUTCUpperBound(value, source, confidence)

    with pytest.raises(MatchweekResearchError, match="confidence"):
        MatchweekResearchRepository(research_store, clock=UncertainClock()).seal_completed(
            graph.f16
        )
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None


def test_default_clock_fails_closed(research_store: Store, graph: Graph) -> None:
    with pytest.raises(MatchweekResearchError, match="unavailable"):
        MatchweekResearchRepository(research_store).seal_completed(graph.f16)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None


@pytest.mark.parametrize("failure", ["crossing", "uncertain", "rollback", "confidence"])
def test_unacknowledged_selection_is_permanently_unqualified(
    research_store: Store,
    graph: Graph,
    failure: str,
) -> None:
    clock = Clock()

    class LosingConfidence:
        def observe(self) -> TrustedUTCUpperBound:
            bound = clock.observe()
            if research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is not None:
                return TrustedUTCUpperBound(bound.upper_bound_utc, "test", "UNKNOWN")
            return bound

    def boundary(role: str, when: str) -> None:
        import sqlite3

        if (role, when) == ("selection", "after"):
            if failure == "crossing":
                clock.value = CUTOFF
            if failure == "rollback":
                clock.value = BEFORE.replace(hour=11)
            if failure == "uncertain":
                raise sqlite3.OperationalError("selection return is uncertain")

    commits = install_commit_boundary(research_store, boundary)
    repository = MatchweekResearchRepository(
        research_store,
        clock=LosingConfidence() if failure == "confidence" else clock,
    )
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed(graph.f16)
    assert commits.attempts == ["selection"]
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is not None
    assert research_store.snapshot_manifest_digest_for_snapshot(RECEIPT) is None
    fresh = MatchweekResearchRepository(research_store, clock=Clock())
    with pytest.raises(MatchweekResearchError, match="permanently"):
        fresh.seal_completed(graph.f16)
    with pytest.raises(MatchweekResearchError, match="occupied"):
        fresh.require_preselection_open(graph.freeze, graph.policy)
    assert commits.attempts == ["selection"]


def test_receipt_persistence_can_finish_after_cutoff(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    path_open = Path.open

    def delayed_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        operation = research_store._research_owner
        if operation is not None and operation._phase == "acknowledged":
            clock.value = CUTOFF.replace(hour=14)
        return path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", delayed_open)
    monkeypatch.setattr(
        "matchvet.artifacts._utc_now", lambda: clock.value.isoformat(timespec="microseconds")
    )
    selected = MatchweekResearchRepository(research_store, clock=clock).seal_completed(graph.f16)
    receipt = ArtifactStore(research_store).verify_manifest(selected.completion_receipt_digest)
    assert clock.value > CUTOFF
    assert receipt.created_at_utc == "2026-09-25T12:00:00.000000+00:00"
    assert receipt.verified_at_utc == "2026-09-25T14:00:00.000000+00:00"


def test_ambiguous_receipt_commit_uses_indexed_evidence_without_retry(
    research_store: Store,
    graph: Graph,
) -> None:
    import sqlite3

    def boundary(role: str, when: str) -> None:
        if (role, when) == ("receipt", "after"):
            raise sqlite3.OperationalError("receipt return is uncertain")

    commits = install_commit_boundary(research_store, boundary)
    selected = MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    assert commits.attempts == ["selection", "receipt"]
    assert MatchweekResearchRepository(research_store).replay(selected.digest) == selected
    assert commits.attempts == ["selection", "receipt"]


@dataclass(frozen=True)
class Qualified:
    root: Path
    selection: str
    receipt: str


@pytest.fixture(scope="module")
def qualified(graph: Graph, tmp_path_factory: pytest.TempPathFactory) -> Qualified:
    root = tmp_path_factory.mktemp("qualified-research")
    shutil.copytree(graph.root / "objects", root / "objects")
    shutil.copyfile(graph.root / "store.sqlite3", root / "store.sqlite3")
    with open_store(root / "store.sqlite3", private_root=root) as store:
        selected = MatchweekResearchRepository(store, clock=Clock()).seal_completed(graph.f16)
    return Qualified(root, selected.digest, selected.completion_receipt_digest)


@pytest.fixture
def selected_store(qualified: Qualified, tmp_path: Path) -> Generator[Store]:
    shutil.copytree(qualified.root / "objects", tmp_path / "objects")
    shutil.copyfile(qualified.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


def test_full_exact_replay_after_cutoff_needs_no_clock(
    selected_store: Store,
    qualified: Qualified,
    graph: Graph,
) -> None:
    repository = MatchweekResearchRepository(selected_store)
    exact = repository.replay(qualified.selection)
    assert exact.f16_manifest_digest == graph.f16
    assert repository.replay_for_matchweek(season="2026-27", matchweek_friday="2026-09-25") == exact
    assert repository.seal_completed(graph.f16) == exact
    with pytest.raises(MatchweekResearchError, match="occupied"):
        repository.require_preselection_open(graph.freeze, graph.policy)


@pytest.mark.parametrize("role", ["selection", "receipt"])
@pytest.mark.parametrize("tags", ["original", "omitted", "altered"])
def test_generic_publication_cannot_occupy_reserved_roles_even_idempotently(
    selected_store: Store,
    qualified: Qualified,
    role: str,
    tags: str,
) -> None:
    from dataclasses import replace

    from matchvet.artifacts import ManifestError

    digest = qualified.selection if role == "selection" else qualified.receipt
    artifacts = ArtifactStore(selected_store)
    original = artifacts.verify_manifest(digest)
    manifest = replace(original, verification_state="UNVERIFIED", verified_at_utc=None)
    if tags == "omitted":
        manifest = replace(manifest, versions=())
    if tags == "altered":
        manifest = replace(manifest, versions=(replace(manifest.versions[0], name="generic"),))
    with pytest.raises(ManifestError, match="private"):
        artifacts.publish_manifest(
            manifest, verified_at_utc=BEFORE.isoformat(timespec="microseconds")
        )
    with selected_store.transaction() as transaction, pytest.raises(ValueError, match="private"):
        transaction.record_snapshot_manifest(
            manifest_digest=digest,
            snapshot_id=manifest.snapshot_id.value,
            matchweek_id=manifest.matchweek_id.value,
            research_cutoff_id=manifest.research_cutoff_id.value,
            version_manifest_id=manifest.version_manifest_id.value,
            research_cutoff_utc=manifest.research_cutoff_utc,
            aggregate_sha256=manifest.aggregate_sha256,
            completeness_state="COMPLETE",
            manifest_schema_version=1,
            created_at_utc=manifest.created_at_utc,
            verification_state="VERIFIED",
            verified_at_utc=original.verified_at_utc,
            parent_snapshot_id=original.parent_snapshot_id.value
            if original.parent_snapshot_id
            else None,
        )


@pytest.mark.parametrize(
    "target,action",
    [
        ("receipt", "delete"),
        ("receipt", "corrupt"),
        ("selection", "delete"),
        ("selection", "corrupt"),
        ("f16", "corrupt"),
        ("evidence", "corrupt"),
        ("model", "corrupt"),
        ("decision", "corrupt"),
        ("source", "corrupt"),
    ],
)
def test_deleted_or_corrupted_receipt_and_graph_never_get_repaired(
    selected_store: Store,
    qualified: Qualified,
    graph: Graph,
    target: str,
    action: str,
) -> None:
    import json

    artifacts = ArtifactStore(selected_store)
    selection = artifacts.verify_manifest(qualified.selection)
    row = json.loads(artifacts.read_artifact(graph.f16))["matches"][0]
    target_digest = {
        "receipt": qualified.receipt,
        "selection": qualified.selection,
        "f16": graph.f16,
        "evidence": row["evidence_digest"],
        "model": row["model_digest"],
        "decision": row["decision_digest"],
    }.get(target)
    if target == "source":
        target_digest = next(
            ref.digest for ref in selection.artifacts if ref.media_type == "application/json"
        )
    assert target_digest is not None
    metadata = selected_store.artifact_metadata(target_digest)
    assert metadata is not None
    path = selected_store.path.parent / metadata.relative_path
    if action == "delete":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")
    repository = MatchweekResearchRepository(selected_store, clock=Clock())
    with pytest.raises(MatchweekResearchError):
        repository.replay(qualified.selection)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed(graph.f16)
    assert selected_store.snapshot_manifest_digest_for_snapshot(SELECTION) == qualified.selection
    assert selected_store.snapshot_manifest_digest_for_snapshot(RECEIPT) == qualified.receipt
    assert not path.exists() if action == "delete" else path.read_bytes() == b"corrupt"


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "policy", "freeze", "profile", "cutoff"]
)
def test_incomplete_or_mixed_f16_lineage_cannot_be_selected(
    research_store: Store,
    graph: Graph,
    change: str,
) -> None:
    import json

    from matchvet.f16 import MANIFEST_MEDIA_TYPE
    from matchvet.matchweek_membership import canonical_json

    artifacts = ArtifactStore(research_store)
    value = json.loads(artifacts.read_artifact(graph.f16))
    if change == "missing":
        value["matches"] = []
    elif change == "duplicate":
        value["matches"] *= 2
    elif change == "cutoff":
        value["matches"][0]["cutoff_id"] = "f07:" + "0" * 64
    else:
        value[
            {"policy": "cutoff_policy_digest", "freeze": "freeze_id", "profile": "profile_digest"}[
                change
            ]
        ] = "0" * 64
    candidate = artifacts.publish_artifact(canonical_json(value).encode(), MANIFEST_MEDIA_TYPE)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(candidate.digest)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None


@pytest.mark.parametrize("role", ["selection", "receipt"])
def test_orphan_objects_are_never_selected_or_adopted(
    research_store: Store,
    graph: Graph,
    qualified: Qualified,
    role: str,
) -> None:
    from matchvet.artifacts import MANIFEST_MEDIA_TYPE

    with open_store(qualified.root / "store.sqlite3", private_root=qualified.root) as original:
        digest = qualified.selection if role == "selection" else qualified.receipt
        content = ArtifactStore(original).read_artifact(digest)
    orphan = ArtifactStore(research_store).publish_artifact(content, MANIFEST_MEDIA_TYPE)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock()).replay(orphan.digest)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock(CUTOFF)).seal_completed(graph.f16)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None
    assert research_store.snapshot_manifest_digest_for_snapshot(RECEIPT) is None


@pytest.mark.parametrize(
    "mode,valid_receipt",
    [
        ("selection_after_commit", False),
        ("after_observation", False),
        ("receipt_staging", False),
        ("receipt_before_commit", False),
        ("receipt_after_commit", True),
    ],
)
def test_real_process_crashes_recover_only_already_indexed_receipts(
    research_store: Store,
    graph: Graph,
    mode: str,
    valid_receipt: bool,
) -> None:
    import os
    import subprocess
    import sys

    root = research_store.path.parent
    research_store.close()
    worker = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from matchweek_research_support import crash_worker; "
                "import sys; crash_worker(*sys.argv[1:])"
            ),
            str(root),
            graph.f16,
            mode,
        ],
        env={**os.environ, "PYTHONPATH": "src:tests"},
        capture_output=True,
        text=True,
    )
    assert worker.returncode == 37, worker.stderr
    with open_store(root / "store.sqlite3", private_root=root) as reopened:
        repository = MatchweekResearchRepository(reopened, clock=Clock())
        if valid_receipt:
            selected = repository.replay_for_matchweek(
                season="2026-27", matchweek_friday="2026-09-25"
            )
            assert selected.f16_manifest_digest == graph.f16
        else:
            with pytest.raises(MatchweekResearchError, match="permanently"):
                repository.seal_completed(graph.f16)
            with pytest.raises(MatchweekResearchError):
                MatchweekResearchRepository(reopened, clock=Clock()).seal_completed(graph.f16)
            assert reopened.snapshot_manifest_digest_for_snapshot(RECEIPT) is None


@pytest.fixture(scope="module", autouse=True)
def deterministic_publication_metadata() -> Generator[None]:
    with pytest.MonkeyPatch.context() as patch:

        def stamp() -> str:
            return BEFORE.isoformat(timespec="microseconds")

        patch.setattr("matchvet.artifacts._utc_now", stamp)
        patch.setattr("matchvet.store._utc_now", stamp)
        yield


@pytest.mark.parametrize("failure", ["file", "directory", "root", "receipt"])
def test_sync_failures_refuse_acknowledgement_including_reused_paths(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import os

    sync = os.fsync
    graph_metadata = research_store.artifact_metadata(graph.f16)
    assert graph_metadata is not None
    graph_file = research_store.path.parent / graph_metadata.relative_path
    seen: list[Path] = []

    def failing_sync(descriptor: int) -> None:
        path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        seen.append(path)
        operation = research_store._research_owner
        if operation is not None:
            failed = (
                (failure == "file" and path == graph_file)
                or (failure == "directory" and path == graph_file.parent)
                or (failure == "root" and path == research_store.path.parent)
                or (failure == "receipt" and operation._phase == "receipt_attempt")
            )
            if failed:
                raise OSError("injected sync failure")
        sync(descriptor)

    monkeypatch.setattr(os, "fsync", failing_sync)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    if failure == "receipt":
        assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is not None
        with pytest.raises(MatchweekResearchError, match="permanently"):
            MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    else:
        assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None
    assert research_store.snapshot_manifest_digest_for_snapshot(RECEIPT) is None
    assert seen


def test_existing_graph_files_and_all_containing_directories_are_synced_before_commit(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    sync = os.fsync
    seen: set[Path] = set()
    captured: set[Path] = set()

    def observed_sync(descriptor: int) -> None:
        seen.add(Path(os.readlink(f"/proc/self/fd/{descriptor}")))
        sync(descriptor)

    def boundary(role: str, when: str) -> None:
        if (role, when) == ("selection", "before"):
            captured.update(seen)

    monkeypatch.setattr(os, "fsync", observed_sync)
    install_commit_boundary(research_store, boundary)
    selected = MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    selection = ArtifactStore(research_store).verify_manifest(selected.digest)
    selection_metadata = research_store.artifact_metadata(selected.digest)
    assert selection_metadata is not None
    assert research_store.path.parent / selection_metadata.relative_path in captured
    for reference in selection.artifacts:
        metadata = research_store.artifact_metadata(reference.digest)
        assert metadata is not None
        path = research_store.path.parent / metadata.relative_path
        assert path in captured
        for parent in path.parents:
            assert parent in captured
            if parent == research_store.path.parent:
                break


def test_private_authority_cannot_be_copied_reentered_reused_or_forked(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import copy
    import os
    import pickle

    from matchvet.artifacts import ManifestError, SnapshotManifest

    captured: list[object] = []
    sync = os.fsync
    checked = False

    def probing_sync(descriptor: int) -> None:
        nonlocal checked
        operation = research_store._research_owner
        if operation is not None and operation._phase == "receipt_attempt" and not checked:
            checked = True
            captured.append(operation)
            for copier in (copy.copy, copy.deepcopy, pickle.dumps):
                with pytest.raises(TypeError):
                    copier(operation)
            with pytest.raises(MatchweekResearchError, match="active"):
                MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
            with pytest.raises(RuntimeError):
                operation._start("receipt")
            # Public paths never borrow ambient private authority.
            for path in (research_store.path.parent / "objects" / "sha256").glob("*/*"):
                try:
                    manifest = SnapshotManifest.from_bytes(path.read_bytes())
                except Exception:
                    continue
                if manifest.snapshot_id.value == SELECTION:
                    from dataclasses import replace

                    with pytest.raises(ManifestError, match="private"):
                        ArtifactStore(research_store).publish_manifest(
                            replace(
                                manifest,
                                verification_state="UNVERIFIED",
                                verified_at_utc=None,
                            )
                        )
                    break
            else:
                raise AssertionError("No indexed selection object found.")
            child = os.fork()
            if child == 0:
                try:
                    operation._start("receipt")
                except RuntimeError:
                    os._exit(0)
                os._exit(91)
            _, status = os.waitpid(child, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        sync(descriptor)

    monkeypatch.setattr(os, "fsync", probing_sync)
    selected = MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    assert checked and selected.f16_manifest_digest == graph.f16
    operation = captured[0]
    with pytest.raises(RuntimeError):
        operation._start("receipt")  # type: ignore[attr-defined]
    root = research_store.path.parent
    research_store.close()
    with open_store(root / "store.sqlite3", private_root=root) as reopened:
        assert reopened._research_owner is None
        with pytest.raises(RuntimeError):
            operation._start("receipt")  # type: ignore[attr-defined]
        assert MatchweekResearchRepository(reopened).replay(selected.digest) == selected


def test_preselection_gate_is_shared_and_read_only(research_store: Store, graph: Graph) -> None:
    repository = MatchweekResearchRepository(research_store, clock=Clock())
    before = research_store.artifact_catalog()
    repository.require_preselection_open(graph.freeze, graph.policy)
    assert research_store.artifact_catalog() == before
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        MatchweekResearchRepository(research_store, clock=Clock(CUTOFF)).require_preselection_open(
            graph.freeze, graph.policy
        )
    with pytest.raises(MatchweekResearchError, match="unavailable"):
        MatchweekResearchRepository(research_store).require_preselection_open(
            graph.freeze, graph.policy
        )


def test_valid_generic_manifest_cannot_become_a_domain_selection(
    selected_store: Store,
    qualified: Qualified,
) -> None:
    from dataclasses import replace

    from matchvet.store import CanonicalIdentifier

    artifacts = ArtifactStore(selected_store)
    original = artifacts.verify_manifest(qualified.selection)
    generic = replace(
        original,
        snapshot_id=CanonicalIdentifier.new("snapshot_manifest"),
        verification_state="UNVERIFIED",
        verified_at_utc=None,
    )
    record = artifacts.publish_manifest(generic)
    assert artifacts.verify_manifest(record.digest).completeness.state == "COMPLETE"
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(selected_store).replay(record.digest)
    assert selected_store.snapshot_manifest_digest_for_snapshot(SELECTION) == qualified.selection


def test_forged_logical_mapping_can_only_poison_availability(
    research_store: Store,
    qualified: Qualified,
    graph: Graph,
) -> None:
    from dataclasses import replace

    from matchvet.artifacts import SnapshotManifest
    from matchvet.store import CanonicalIdentifier

    with open_store(
        qualified.root / "store.sqlite3", private_root=qualified.root
    ) as original_store:
        original = ArtifactStore(original_store).verify_manifest(qualified.selection)
    generic: SnapshotManifest = replace(
        original,
        matchweek_id=CanonicalIdentifier.new("matchweek"),
        versions=(),
        verification_state="UNVERIFIED",
        verified_at_utc=None,
    )
    record = ArtifactStore(research_store).publish_manifest(generic)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) == record.digest
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    assert research_store.snapshot_manifest_digest_for_snapshot(RECEIPT) is None


@dataclass(frozen=True)
class Proposals:
    root: Path
    digests: dict[str, str]


def _build_proposal(store: Store, freeze: str, policy: str, profile: str) -> str:
    cutoffs = MatchEvidenceCutoffRepository(store).persist_for_freeze(freeze, policy)
    context = WorkContext(
        "synthetic",
        "synthetic",
        "2026-09-25",
        RunPhase.PREFERENCE_VETTING,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    return (
        F16MatchweekProcessor(store, clock=Clock(), legacy_research=True)
        .process_phase(
            context,
            freeze_id=freeze,
            cutoff_policy_digest=policy,
            cutoff_ids=tuple(sorted(item.cutoff_id for item in cutoffs)),
            profile_digest=profile,
            policy=PolicyVersion(version="research-policy-v1"),
        )
        .result_digest
    )


@pytest.fixture(scope="module")
def proposals(graph: Graph, tmp_path_factory: pytest.TempPathFactory) -> Proposals:
    # Each proposal was independently complete before being imported as audit
    # evidence. Current corrected writers must not create alternate local states.
    root = tmp_path_factory.mktemp("competing-proposals")
    shutil.copytree(graph.inputs_root / "objects", root / "objects")
    shutil.copyfile(graph.inputs_root / "store.sqlite3", root / "store.sqlite3")
    with open_store(root / "store.sqlite3", private_root=root) as store:
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",)).digest
        alternate_profile = (
            PreferenceProfileRepository(store)
            .build_profile(("match_winner_home",), profile_version="alternate-profile")
            .digest
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        alternate_policy = cutoffs.persist_policy(
            CutoffPolicy(
                "test-common", "2", 7200, rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME"
            )
        )
        legacy_policy = cutoffs.persist_policy(CutoffPolicy("legacy", "1", 21600))
        assessment = _persistable_schedule_assessment(
            store, root, (("2026-09-25", "20:00", "Alternate United", "Alternate City"),)
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 14, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        variants = {
            "profile": (graph.freeze, graph.policy, alternate_profile),
            "policy": (graph.freeze, alternate_policy, profile),
            "legacy": (graph.freeze, legacy_policy, profile),
            "freeze": (freeze.freeze_id, graph.policy, profile),
        }
        for boundary, policy, _ in variants.values():
            cutoffs.persist_for_freeze(boundary, policy)
        clean = tmp_path_factory.mktemp("proposal-predecessors")
        _copy_inputs(store, clean)
        digests = {}
        for name, inputs in variants.items():
            branch = tmp_path_factory.mktemp("proposal-" + name)
            shutil.copytree(clean / "objects", branch / "objects")
            shutil.copyfile(clean / "store.sqlite3", branch / "store.sqlite3")
            with open_store(branch / "store.sqlite3", private_root=branch) as branch_store:
                digests[name] = _build_proposal(branch_store, *inputs)
                source = ArtifactStore(branch_store)
                for metadata in branch_store.artifact_catalog():
                    ArtifactStore(store).publish_artifact(
                        source.read_artifact(metadata.digest),
                        metadata.media_type,
                        retention_class=metadata.retention_class,
                    )
        with open_store(graph.root / "store.sqlite3", private_root=graph.root) as original:
            for metadata in original.artifact_catalog():
                ArtifactStore(store).publish_artifact(
                    ArtifactStore(original).read_artifact(metadata.digest),
                    metadata.media_type,
                    retention_class=metadata.retention_class,
                )
    return Proposals(root, digests)


@pytest.fixture
def proposal_store(proposals: Proposals, tmp_path: Path) -> Generator[Store]:
    shutil.copytree(proposals.root / "objects", tmp_path / "objects")
    shutil.copyfile(proposals.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


@pytest.mark.parametrize("variant", ["freeze", "policy", "profile"])
def test_valid_alternate_proposals_share_the_occupied_logical_slot(
    proposal_store: Store,
    graph: Graph,
    proposals: Proposals,
    variant: str,
) -> None:
    repository = MatchweekResearchRepository(proposal_store, clock=Clock())
    selected = repository.seal_completed(graph.f16)
    assert (
        F16MatchweekProcessor(proposal_store).replay_manifest(proposals.digests[variant]).digest
        == proposals.digests[variant]
    )
    with pytest.raises(MatchweekResearchError, match="wins"):
        repository.seal_completed(proposals.digests[variant])
    assert (
        repository.replay_for_matchweek(season="2026-27", matchweek_friday="2026-09-25") == selected
    )


def test_legacy_f07_still_replays_but_cannot_qualify_a_new_selection(
    proposal_store: Store,
    proposals: Proposals,
) -> None:
    digest = proposals.digests["legacy"]
    assert F16MatchweekProcessor(proposal_store).replay_manifest(digest).digest == digest
    with pytest.raises(MatchweekResearchError, match="corrected"):
        MatchweekResearchRepository(proposal_store, clock=Clock()).seal_completed(digest)
    assert proposal_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None


def test_concurrent_competing_manifests_cannot_produce_a_second_winner(
    proposal_store: Store,
    proposals: Proposals,
    graph: Graph,
) -> None:
    import json
    import os
    import subprocess
    import sys

    root = proposal_store.path.parent
    proposal_store.close()
    script = """
import json, sys
from pathlib import Path
from unittest.mock import patch
from matchweek_research_support import BEFORE, Clock
from matchvet.matchweek_research import MatchweekResearchRepository, MatchweekResearchError
from matchvet.store import open_store, StoreBusyError
root, digest = Path(sys.argv[1]), sys.argv[2]
try:
    with patch("matchvet.artifacts._utc_now", lambda: BEFORE.isoformat(timespec="microseconds")):
        with open_store(root / "store.sqlite3", private_root=root) as store:
            selected = MatchweekResearchRepository(store, clock=Clock()).seal_completed(digest)
            print(json.dumps({"status":"selected", "digest":selected.digest,
                              "f16":selected.f16_manifest_digest}))
except StoreBusyError:
    print(json.dumps({"status":"busy"}))
except MatchweekResearchError:
    print(json.dumps({"status":"refused"}))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(root), digest],
            env={**os.environ, "PYTHONPATH": "src:tests"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for digest in (graph.f16, proposals.digests["profile"])
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate()
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))
    winners = [result for result in results if result["status"] == "selected"]
    assert len(winners) == 1
    with open_store(root / "store.sqlite3", private_root=root) as reopened:
        winner = MatchweekResearchRepository(reopened).replay_for_matchweek(
            season="2026-27", matchweek_friday="2026-09-25"
        )
        assert winner.digest == winners[0]["digest"]
        assert winner.f16_manifest_digest == winners[0]["f16"]
        assert len(reopened.snapshot_manifest_digests()) == 2


@pytest.mark.parametrize("setting", ["NORMAL", "DELETE", "transaction"])
def test_selection_refuses_unestablished_sqlite_durability(
    research_store: Store,
    graph: Graph,
    setting: str,
) -> None:
    connection = research_store._connection_for_repository()
    if setting == "NORMAL":
        connection.execute("PRAGMA synchronous = NORMAL")
    elif setting == "DELETE":
        connection.execute("PRAGMA journal_mode = DELETE")
    else:
        connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(MatchweekResearchError, match="acknowledged"):
            MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    finally:
        connection.rollback()
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None
    assert research_store.snapshot_manifest_digest_for_snapshot(RECEIPT) is None


def test_close_during_live_operation_revokes_authority(
    research_store: Store,
    graph: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    sync = os.fsync
    root = research_store.path.parent
    revoked = False

    def close_at_receipt(descriptor: int) -> None:
        nonlocal revoked
        operation = research_store._research_owner
        if operation is not None and operation._phase == "receipt_attempt" and not revoked:
            revoked = True
            research_store.close()
        sync(descriptor)

    monkeypatch.setattr(os, "fsync", close_at_receipt)
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    assert revoked
    with open_store(root / "store.sqlite3", private_root=root) as reopened:
        assert reopened._research_owner is None
        with pytest.raises(MatchweekResearchError, match="permanently"):
            MatchweekResearchRepository(reopened, clock=Clock()).seal_completed(graph.f16)
        assert reopened.snapshot_manifest_digest_for_snapshot(RECEIPT) is None


def test_v1_graph_cannot_be_adopted_as_causal(research_store: Store, graph: Graph) -> None:
    with pytest.raises(MatchweekResearchError, match="successor"):
        MatchweekResearchRepository(research_store).seal_completed_v2(graph.f16)
    assert research_store.snapshot_manifest_digest_for_snapshot(SELECTION) is None

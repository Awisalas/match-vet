"""Recheck changed replay boundaries against the real offline writer fixture."""

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from issue82_support import Successor
from test_issue82 import (
    test_causal_graph_replay_through_read_only_connection,
    test_f11_exact_media_schema_pair_and_history_pair_refuses,
    test_selected_or_terminal_slot_allows_exact_replay_and_refuses_new_graph,
)

from matchvet.artifacts import ArtifactStore
from matchvet.f15_inputs import request_from_candidate
from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
from matchvet.matchweek_research import MatchweekResearchRepository
from matchvet.research_identity import selection_slot
from matchvet.store import open_store

mode, source = sys.argv[1], Path(sys.argv[2])
assert "issue82-" in source.name, "Only isolated #82 fixture stores are accepted"
with tempfile.TemporaryDirectory(prefix="issue82-replay-regression-") as temporary:
    root = Path(temporary)
    shutil.copytree(source / "objects", root / "objects")
    # A consistent backup also supports fixtures still held by the test process.
    with (
        sqlite3.connect(f"file:{source / 'store.sqlite3'}?mode=ro", uri=True) as original,
        sqlite3.connect(root / "store.sqlite3") as destination,
    ):
        original.backup(destination)
    with open_store(root / "store.sqlite3", private_root=root) as store:
        artifacts = ArtifactStore(store)
        manifests = [
            item.digest
            for item in store.artifact_catalog()
            if item.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(manifests) == 1
        manifest = manifests[0]
        candidate = json.loads(artifacts.read_artifact(manifest))["candidate_contract_digest"]
        request = request_from_candidate(store, candidate)
        graph = MatchweekResearchRepository(store)._admit_v2(manifest)
        runs = (
            store._connection_for_repository()
            .execute("SELECT run_id, input_digest FROM research_runs")
            .fetchall()
        )
        assert len(runs) == 1
        case = Successor(root, request, candidate, runs[0][0], runs[0][1], manifest, graph)
        if mode == "media":
            test_f11_exact_media_schema_pair_and_history_pair_refuses(case, store)
        elif mode == "readonly":
            test_causal_graph_replay_through_read_only_connection(case, store)
        else:
            assert mode in {"qualified", "terminal"}
            selection = store.snapshot_manifest_digest_for_snapshot(
                selection_slot(graph.logical_id)
            )
            assert selection is not None
            with pytest.MonkeyPatch.context() as monkeypatch:
                test_selected_or_terminal_slot_allows_exact_replay_and_refuses_new_graph(
                    (case, selection, mode == "qualified"), store, monkeypatch
                )
        print(f"PASS {mode}: actual writer graph and changed replay boundary", flush=True)

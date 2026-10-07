#!/usr/bin/env python3
"""Replay a synthetic chain built by commit 6470abf with current readers.

Run from the repository with its development Python:
    .venv/bin/python .audit/issue-76-implementation/legacy-proof.py

The old and current modules load in separate subprocesses. Stores and extracted
sources live only in a private temporary directory. No fixture/network acquisition
or operational artifact publication occurs. The retained result JSON contains the
old identity literals and exact artifact digests, not private temporary paths.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

BASE_COMMIT = "6470abf"
ADAPTER_LITERAL = "f13-t09-history-context-v2"
FIXTURE_TIME = datetime(2026, 9, 16, 14, tzinfo=UTC)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_origin(source_root: Path) -> None:
    import test_matchweek_membership

    import matchvet.f13

    assert Path(matchvet.f13.__file__).resolve().is_relative_to(source_root.resolve())
    assert Path(test_matchweek_membership.__file__).resolve().is_relative_to(source_root.resolve())


def _build_old(source_root: Path, private_root: Path, oracle_path: Path) -> None:
    from test_matchweek_membership import _persistable_schedule_assessment

    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import RESEARCH_ADAPTER_VERSION, engine_version_identity
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.f16 import F16MatchweekProcessor
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.runs import RunPhase, WorkContext
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion

    _assert_origin(source_root)
    assert RESEARCH_ADAPTER_VERSION == ADAPTER_LITERAL
    private_root.mkdir()
    fixed_utc = FIXTURE_TIME.isoformat(timespec="microseconds")
    with (
        patch("matchvet.artifacts._utc_now", lambda: fixed_utc),
        patch("matchvet.store._utc_now", lambda: fixed_utc),
        open_store(private_root / "store.sqlite3", private_root=private_root) as store,
    ):
        assessment = _persistable_schedule_assessment(
            store,
            private_root,
            (("2026-09-25", "20:00", "Legacy Home", "Legacy Away"),),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store, clock=lambda: FIXTURE_TIME).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoff_repository = MatchEvidenceCutoffRepository(store)
        policy_digest = cutoff_repository.persist_policy(
            CutoffPolicy("issue76-legacy-golden", "1", 3600)
        )
        assert cutoff_repository.read_policy(policy_digest).rule == "KICKOFF_MINUS_LEAD_TIME"
        cutoffs = cutoff_repository.persist_for_freeze(freeze.freeze_id, policy_digest)
        assert len(cutoffs) == 1
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        selection_policy = PolicyVersion(version="issue76-legacy-golden")
        context = WorkContext(
            "synthetic-legacy-proof",
            "synthetic-legacy-proof",
            "2026-09-25",
            RunPhase.PREFERENCE_VETTING,
            1,
            "RESEARCH_ONLY",
            "0" * 64,
            "0" * 64,
            1,
        )
        result = F16MatchweekProcessor(store).process_phase(
            context,
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=policy_digest,
            cutoff_ids=tuple(sorted(row.cutoff_id for row in cutoffs)),
            profile_digest=profile.digest,
            policy=selection_policy,
        )
        artifacts = ArtifactStore(store)
        manifest = F16MatchweekProcessor(store).replay_manifest(result.result_digest)
        assert len(manifest.match_results) == 1
        row = manifest.match_results[0]
        model = json.loads(artifacts.read_artifact(row.model_digest))
        assert model["inputs"]["research_adapter_version"] == ADAPTER_LITERAL
        oracle = {
            "freeze_id": freeze.freeze_id,
            "policy_digest": policy_digest,
            "profile_digest": profile.digest,
            "selection_policy": selection_policy.to_dict(),
            "cutoff_id": row.cutoff_id,
            "cutoff_digest_literal": row.cutoff_digest,
            "cutoff_bytes": base64.b64encode(cutoffs[0].to_bytes()).decode("ascii"),
            "evidence_digest": row.evidence_digest,
            "model_digest": row.model_digest,
            "decision_digest": row.decision_digest,
            "match_result_digest": row.match_result_digest,
            "manifest_digest": manifest.digest,
            "engine_identity_literal": engine_version_identity(),
            "research_adapter_literal": RESEARCH_ADAPTER_VERSION,
            "engine_contract_literal": model["inputs"]["engine_contract"],
            "catalog": [asdict(metadata) for metadata in store.artifact_catalog()],
            "artifact_bytes": {
                metadata.digest: base64.b64encode(artifacts.read_artifact(metadata.digest)).decode(
                    "ascii"
                )
                for metadata in store.artifact_catalog()
            },
        }
        _json(oracle_path, oracle)
    print("old-source synthetic legacy F07/F11/F13/F14/F16 chain retained", flush=True)


def _replay_current(source_root: Path, private_root: Path, oracle_path: Path) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f13 import (
        RESEARCH_ADAPTER_VERSION,
        ModelContractRepository,
        engine_version_identity,
    )
    from matchvet.f14 import DecisionRepository, PreferenceProfileRepository
    from matchvet.f16 import F16MatchweekProcessor
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion

    _assert_origin(source_root)
    golden = json.loads(oracle_path.read_text(encoding="utf-8"))
    assert RESEARCH_ADAPTER_VERSION == golden["research_adapter_literal"] == ADAPTER_LITERAL
    assert engine_version_identity() == golden["engine_identity_literal"]
    with open_store(private_root / "store.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        before = [asdict(metadata) for metadata in store.artifact_catalog()]
        assert before == golden["catalog"]
        cutoff = MatchEvidenceCutoffRepository(store).replay(golden["cutoff_id"])
        assert cutoff.to_bytes() == base64.b64decode(golden["cutoff_bytes"], validate=True)
        assert cutoff.digest == golden["cutoff_digest_literal"]
        assert (
            MatchEvidenceCutoffRepository(store).read_policy(golden["policy_digest"]).rule
            == "KICKOFF_MINUS_LEAD_TIME"
        )
        evidence = F11EvidenceRepository(store).replay(
            golden["evidence_digest"],
            freeze_id=golden["freeze_id"],
            policy_digest=golden["policy_digest"],
        )
        model = ModelContractRepository(store).replay(
            golden["model_digest"], golden["evidence_digest"], golden["cutoff_id"]
        )
        assert model.to_dict()["inputs"]["engine_contract"] == golden["engine_contract_literal"]
        decision = DecisionRepository(store).replay(golden["decision_digest"])
        manifest = F16MatchweekProcessor(store).replay_manifest(golden["manifest_digest"])
        profile = PreferenceProfileRepository(store).replay(golden["profile_digest"])
        assert profile.digest == golden["profile_digest"]
        for kind, value, digest in (
            ("F11", evidence, golden["evidence_digest"]),
            ("F13", model, golden["model_digest"]),
            ("F14", decision, golden["decision_digest"]),
            ("F16", manifest, golden["manifest_digest"]),
        ):
            assert value.digest == digest, kind
            assert value.to_bytes() == base64.b64decode(
                golden["artifact_bytes"][digest], validate=True
            ), kind
        assert manifest.match_results[0].match_result_digest == golden["match_result_digest"]
        identities = F16MatchweekProcessor(store).completed_artifact_identities(
            freeze_id=golden["freeze_id"],
            cutoff_policy_digest=golden["policy_digest"],
            profile_digest=golden["profile_digest"],
            policy=PolicyVersion.from_mapping(golden["selection_policy"]),
        )
        assert any(value.endswith(":sha256:" + manifest.digest) for value in identities)
        for digest, encoded in golden["artifact_bytes"].items():
            exact = base64.b64decode(encoded, validate=True)
            assert hashlib.sha256(exact).hexdigest() == digest
            assert artifacts.read_artifact(digest) == exact
        assert [asdict(metadata) for metadata in store.artifact_catalog()] == before
    print(
        "current readers replayed every old artifact byte/digest without catalog changes",
        flush=True,
    )


def _worker(script: Path, root: Path, mode: str, store: Path, oracle: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root / "tests")))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, str(script), "--worker", mode, str(root), str(store), str(oracle)],
        cwd=root,
        env=environment,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("old", "current"), help=argparse.SUPPRESS)
    parser.add_argument("worker_paths", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument(
        "--report", type=Path, default=Path(__file__).with_name("legacy-proof-result.json")
    )
    args = parser.parse_args()
    if args.worker:
        assert len(args.worker_paths) == 3
        root, store, oracle = map(Path, args.worker_paths)
        operation = _build_old if args.worker == "old" else _replay_current
        operation(root, store, oracle)
        return
    assert not args.worker_paths
    script = Path(__file__).resolve()
    repository = Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", BASE_COMMIT + "^{commit}"], cwd=repository, text=True
    ).strip()
    assert commit.startswith(BASE_COMMIT)
    with TemporaryDirectory(prefix="issue76-legacy-byte-proof-") as temporary:
        private = Path(temporary)
        old_source = private / "source-6470abf"
        old_source.mkdir()
        archive = subprocess.check_output(["git", "archive", commit], cwd=repository)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as extracted:
            extracted.extractall(old_source, filter="data")
        store = private / "store"
        oracle = private / "old-source-oracle.json"
        _worker(script, old_source, "old", store, oracle)
        _worker(script, repository, "current", store, oracle)
        golden = json.loads(oracle.read_text(encoding="utf-8"))
        report = {
            "source_commit": commit,
            "status": "PASS",
            "artifact_count": len(golden["catalog"]),
            "artifact_digests": sorted(golden["artifact_bytes"]),
            "engine_identity_literal": golden["engine_identity_literal"],
            "research_adapter_literal": golden["research_adapter_literal"],
            "engine_contract_literal": golden["engine_contract_literal"],
            "cutoff_digest_literal": golden["cutoff_digest_literal"],
            "evidence_digest_literal": golden["evidence_digest"],
            "model_digest_literal": golden["model_digest"],
            "decision_digest_literal": golden["decision_digest"],
            "manifest_digest_literal": golden["manifest_digest"],
            "catalog_changes": 0,
        }
        _json(args.report.resolve(), report)
        print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

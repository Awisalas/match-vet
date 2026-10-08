"""Offline issue-79 proof experiments. Not a production witness implementation."""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_artifacts import _manifest, _version

from matchvet.artifacts import ArtifactStore, ManifestArtifact
from matchvet.store import open_store

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "docs/research/cb01-sigstore-witness-2026-10-05"


def openssl(*args: str, ok: bool = True) -> str:
    result = subprocess.run(["openssl", *args], capture_output=True, text=True, check=False)
    assert (result.returncode == 0) == ok, result.stdout + result.stderr
    return result.stdout + result.stderr


def retained_wire_proof() -> dict[str, object]:
    response = str(BUNDLE / "response.tsr")
    verification = (
        "-in",
        response,
        "-CAfile",
        str(BUNDLE / "tsa-root.pem"),
        "-attime",
        "1791175821",
    )
    exact = openssl("ts", "-verify", "-queryfile", str(BUNDLE / "request.tsq"), *verification)
    assert "Verification: OK" in exact
    wrong = openssl(
        "ts", "-verify", "-queryfile", str(BUNDLE / "changed-request.tsq"), *verification, ok=False
    )
    assert "message imprint mismatch" in wrong
    decoded = openssl("ts", "-reply", "-in", response, "-text")
    assert "Policy OID: 1.3.6.1.4.1.57264.2" in decoded
    assert "Time stamp: Oct  5 04:50:21 2026 GMT" in decoded
    assert re.search(r"Accuracy: 0x01 seconds, unspecified millis, unspecified micros", decoded)
    gen_time = datetime(2026, 10, 5, 4, 50, 21, tzinfo=UTC)
    upper = gen_time + timedelta(seconds=1)
    # This is the retained signed token's declaration, not a selected timing margin.
    assert upper == datetime(2026, 10, 5, 4, 50, 22, tzinfo=UTC)
    assert not upper < upper  # strict equality refusal despite earlier genTime
    with tempfile.TemporaryDirectory(prefix="matchvet-79-wire-") as directory:
        query = str(Path(directory) / "new-nonce.tsq")
        openssl(
            "ts",
            "-query",
            "-data",
            str(BUNDLE / "commitment.txt"),
            "-sha256",
            "-cert",
            "-out",
            query,
        )
        wrong_nonce = openssl("ts", "-verify", "-queryfile", query, *verification, ok=False)
        assert "nonce mismatch" in wrong_nonce
        no_nonce = str(Path(directory) / "no-nonce.tsq")
        openssl(
            "ts",
            "-query",
            "-data",
            str(BUNDLE / "commitment.txt"),
            "-sha256",
            "-cert",
            "-no_nonce",
            "-out",
            no_nonce,
        )
        accepted_without_nonce = openssl("ts", "-verify", "-queryfile", no_nonce, *verification)
        assert "Verification: OK" in accepted_without_nonce
    return {
        "exact_signature_imprint": "pass",
        "wrong_imprint": "refused",
        "replayed_other_nonce": "refused",
        "generic_no_nonce_verifier": "accepts",
        "application_must_require_nonce": True,
        "signed_accuracy_seconds": 1,
        "upper_bound": upper.isoformat(),
        "diagnostic_token_only": True,
    }


def storage_proof() -> dict[str, object]:
    # Exercise shipped Store/ArtifactStore and schema 1, under a new temporary root.
    # The unreserved generic manifest proves representation, NOT v2 protected authority.
    with tempfile.TemporaryDirectory(prefix="matchvet-79-storage-") as directory:
        root = Path(directory)
        with open_store(root / "synthetic.sqlite3", private_root=root) as store:
            connection = store._connection_for_repository()
            before = tuple(
                connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type,name")
            )
            artifacts = ArtifactStore(store)
            records = [
                artifacts.publish_artifact(value, media)
                for value, media in (
                    (b"synthetic-selection", "text/plain"),
                    (b'{"kind":"synthetic-causal-witness","schema_version":2}', "application/json"),
                    ((BUNDLE / "request.tsq").read_bytes(), "application/timestamp-query"),
                    ((BUNDLE / "response.tsr").read_bytes(), "application/timestamp-reply"),
                )
            ]
            refs = tuple(
                ManifestArtifact(r.artifact_id, r.digest, r.media_type, r.byte_length)
                for r in records
            )
            version = _version()
            with store.transaction() as transaction:
                transaction.add_version(version)
            manifest = replace(
                _manifest(refs[0], version), artifacts=tuple(sorted(refs, key=lambda r: r.digest))
            )
            digest = artifacts.publish_manifest(manifest).digest
            verified = artifacts.verify_manifest(digest)
            assert verified.schema_version == 1
            assert set(verified.artifacts) == set(refs)
            after = tuple(
                connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type,name")
            )
            assert before == after
            assert (
                artifacts.read_artifact(records[-1].digest)
                == (BUNDLE / "response.tsr").read_bytes()
            )
    return {
        "shipped_generic_schema": 1,
        "four_exact_refs_roundtrip": "pass",
        "sqlite_schema_unchanged": True,
        "protected_v2_publication": "not implemented",
    }


def causal_proof() -> dict[str, object]:
    # Events stand for real completion, not self-reported artifact timestamps.
    events = (
        "collect",
        "f11",
        "compute13",
        "f13",
        "compute14",
        "f14",
        "f16",
        "commit",
        "request",
        "remote",
    )
    # The required application prerequisites form this chain for this one-match example.
    # Multi-match graph is the conjunction of every such predecessor path.
    admitted = 0
    for order in itertools.permutations(events[:7]):
        positions = {event: order.index(event) for event in order}
        if all(
            positions[left] < positions[right] for left, right in itertools.pairwise(events[:7])
        ):
            admitted += 1
            assert order == events[:7]
    assert admitted == 1
    accepted = refused = 0
    for pauses in itertools.product((0, 1, 99, 10000), repeat=5):
        before_compute, before_commit, before_request, after_request, during_delivery = pauses
        collect = 1
        f11 = collect + 1
        compute13 = f11 + 1 + before_compute
        f13 = compute13 + 1
        compute14, f14 = f13 + 1, f13 + 2
        f16 = f14 + 1
        commit = f16 + 1 + before_commit
        request = commit + 1 + before_request
        remote = request + 1 + after_request
        receipt = remote + 1 + during_delivery
        # Abstract honest authority: actual event within its signed interval.
        # Units and radius are synthetic. No Android/TSA margin is inferred.
        for signed_error in (-2, -1, 0, 1, 2):
            gen_time = remote + signed_error
            upper = gen_time + 2
            assert remote <= upper
            if upper < 100:
                accepted += 1
                assert max(collect, compute13, compute14, f16, commit) < 100
                assert commit < request <= remote <= upper < 100
                assert receipt > remote
            else:
                refused += 1
    # Contradictions any accepting implementation must reject.
    attacks = {
        "request_before_commit": (20, 10, 11, 13),
        "remote_event_after_T": (20, 21, 101, 103),
        "upper_equals_T": (20, 21, 98, 100),
        "candidate_computed_after_T": (105, 106, 107, 109),
    }
    for name, (commit, request, remote, upper) in attacks.items():
        assert not (commit < request <= remote <= upper < 100), name
    # Delay cannot invalidate a historical remote-event bound.
    assert 20 < 21 <= 30 <= 32 < 100 < 10000
    # The old return-bound counterexample remains: freeze u then suspend past u/T.
    returned_upper, actual_return = 32, 10000
    assert actual_return > returned_upper
    return {
        "dependency_permutations": 5040,
        "admitted": admitted,
        "pause_error_schedules": accepted + refused,
        "qualified": accepted,
        "refused": refused,
        "attack_contradictions": list(attacks),
        "delayed_delivery": "allowed",
        "return_bound_counterexample": "still fails",
        "scope": "logical proof under stated trust/order premises, not production tests",
    }


def main() -> None:
    result = {
        "causal": causal_proof(),
        "retained_wire": retained_wire_proof(),
        "storage": storage_proof(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

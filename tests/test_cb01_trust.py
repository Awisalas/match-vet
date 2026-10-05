from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import matchvet.cb01_trust as cb01_trust
from matchvet.artifacts import ArtifactStore
from matchvet.cb01 import BootstrapRepository, CB01Error
from matchvet.cb01_trust import (
    TIMESTAMP_MEDIA_TYPE,
    CB01TrustError,
    SigstoreWitnessBackend,
    TrustRefresh,
    _parse_ts_query,
    replay_trust_state,
    trust_policy_body,
)
from matchvet.store import open_store

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "docs/research/cb01-sigstore-witness-2026-10-05"


def _captured_trust() -> TrustRefresh:
    return replay_trust_state(
        tuple((_FIXTURES / f"{version}.root.json").read_bytes() for version in range(11, 16)),
        (_FIXTURES / "timestamp.json").read_bytes(),
        (_FIXTURES / "snapshot.json").read_bytes(),
        (_FIXTURES / "targets.json").read_bytes(),
        (_FIXTURES / "trusted_root.json").read_bytes(),
        trust_policy_body(),
    )


def test_captured_sigstore_response_verifies_offline_at_signed_gen_time() -> None:
    request = (_FIXTURES / "request.tsq").read_bytes()
    response = (_FIXTURES / "response.tsr").read_bytes()
    query = _parse_ts_query(request)
    result = SigstoreWitnessBackend().verify_response(
        request,
        f"{query['nonce']:x}",
        response,
        _captured_trust(),
        trust_policy_body(),
        batch_digest=query["imprint"].hex(),
        cutoff_utc="2026-10-05T04:00:00Z",
        kickoff_utc="2026-10-05T05:00:00Z",
    )

    assert result.state == "FAILED"
    assert result.reasons == ()
    assert result.tsa["gen_time_utc"] == "2026-10-05T04:50:21Z"
    assert {name: check["state"] for name, check in result.checks.items()} == {
        name: "UNPERFORMED" if name in {"denominator", "lineage"} else "PASSED"
        for name in result.checks
    }


def test_captured_response_rejects_a_different_batch_commitment() -> None:
    request = (_FIXTURES / "request.tsq").read_bytes()
    response = (_FIXTURES / "response.tsr").read_bytes()
    query = _parse_ts_query(request)
    result = SigstoreWitnessBackend().verify_response(
        request,
        f"{query['nonce']:x}",
        response,
        _captured_trust(),
        trust_policy_body(),
        batch_digest="0" * 64,
        cutoff_utc="2026-10-05T04:00:00Z",
        kickoff_utc="2026-10-05T05:00:00Z",
    )

    assert result.state == "FAILED"
    assert result.checks["imprint"]["state"] == "FAILED"
    assert result.checks["signature"]["state"] == "PASSED"
    assert result.checks["chain"]["state"] == "PASSED"


def test_fresh_refresh_accepts_expired_intermediate_roots_and_checks_final_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = {
        f"{cb01_trust.TUF_BASE_URL}{version}.root.json": (
            _FIXTURES / f"{version}.root.json"
        ).read_bytes()
        for version in range(11, 16)
    }
    fixtures.update(
        {
            f"{cb01_trust.TUF_BASE_URL}timestamp.json": (_FIXTURES / "timestamp.json").read_bytes(),
            f"{cb01_trust.TUF_BASE_URL}165.snapshot.json": (
                _FIXTURES / "snapshot.json"
            ).read_bytes(),
            f"{cb01_trust.TUF_BASE_URL}14.targets.json": (_FIXTURES / "targets.json").read_bytes(),
            f"{cb01_trust.TUF_BASE_URL}trusted_root.json": (
                _FIXTURES / "trusted_root.json"
            ).read_bytes(),
        }
    )

    def fetch(url: str, **_kwargs: object) -> bytes | None:
        return fixtures.get(url)

    now = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(cb01_trust, "_fetch_curl", fetch)
    monkeypatch.setattr(cb01_trust, "_utc_now", lambda: now)
    refreshed = SigstoreWitnessBackend().refresh_trust(trust_policy_body())
    assert refreshed.root_history == tuple(
        (_FIXTURES / f"{version}.root.json").read_bytes() for version in range(11, 16)
    )

    monkeypatch.setattr(cb01_trust, "_utc_now", lambda: datetime(2026, 11, 21, tzinfo=UTC))
    with pytest.raises(CB01TrustError, match="expired"):
        SigstoreWitnessBackend().refresh_trust(trust_policy_body())


def test_captured_tuf_state_rejects_metadata_below_the_frozen_version_floor() -> None:
    state = dict(_captured_trust().state)
    state["timestamp_version"] = 798
    with pytest.raises(CB01TrustError, match="timestamp metadata is below"):
        cb01_trust._validate_tuf_metadata_floor(state, trust_policy_body())


def test_fresh_tuf_refresh_rejects_metadata_older_than_retained_version_floor(
    tmp_path: Path,
) -> None:
    trust = _captured_trust()
    database = tmp_path / "tuf-floor.sqlite3"
    with open_store(database, private_root=tmp_path) as store:
        repository = BootstrapRepository(store)
        repository._retain_trust(trust)
        timestamp = json.loads(trust.timestamp)
        timestamp["signed"]["version"] += 1
        rollback = json.dumps(timestamp, sort_keys=True, separators=(",", ":")).encode()
        ArtifactStore(store).publish_artifact(
            rollback, TIMESTAMP_MEDIA_TYPE, retention_class="PROTECTED"
        )

        with pytest.raises(CB01Error, match="rolled back a retained version"):
            repository._retain_trust(trust)

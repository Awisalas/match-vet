"""Offline source authority mechanics; synthetic configuration only."""

import json
import socket
import threading
from pathlib import Path
from typing import Any

import pytest
from source_authorization_support import SourceOwner, acquisition_manifest, entry

from matchvet.artifacts import ArtifactStore
from matchvet.source_authorization import (
    RAW_MEDIA_TYPE,
    SourceAuthorizationRepository,
    _require_applicable,
    replay_decision,
)
from matchvet.source_manifest import (
    DECISION_MEDIA_TYPE,
    MANIFEST_MEDIA_TYPE,
    POLICY_DIGEST,
    RISK_BASIS,
    SourceAuthorizationError,
    canonical,
    read,
    verify_manifest,
)
from matchvet.store import open_store


def test_default_source_authority_refuses(tmp_path: Path) -> None:
    with (
        open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store,
        pytest.raises(SourceAuthorizationError),
    ):
        SourceAuthorizationRepository(store).authorize("0" * 64)


@pytest.fixture(autouse=True)
def no_remote_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def connect(connection: socket.socket, address: Any) -> None:
        if connection.family != socket.AF_UNIX:
            raise AssertionError("#89 tests forbid remote network access.")
        original(connection, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(
        socket, "create_connection", lambda *_a, **_k: pytest.fail("Network forbidden")
    )


def test_risk_authority_keeps_external_unknown_and_private_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest_digest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "source-owner", store, monkeypatch)
        owner.append(manifest_digest)
        repository = SourceAuthorizationRepository(store)
        decision_digest = repository.authorize(manifest_digest)
        original = ArtifactStore(store).read_artifact(decision_digest)
        decision = replay_decision(store, decision_digest)
        assert decision["contract"] == "research-real-source-use-decision-v2"
        assert decision["state"] == "APPROVED"
        manifest = verify_manifest(store, manifest_digest)
        assert manifest["entries"][0]["internal_basis"] == RISK_BASIS
        assert manifest["entries"][0]["external_permission"]["state"] == "UNKNOWN"
        capture = repository.acquire(
            manifest_digest, lambda: b"private raw", lambda _raw: b"private normalized"
        )
        for identity in (capture.raw_digest, capture.normalized_digest, capture.eligibility_digest):
            metadata = store.artifact_metadata(identity)
            assert metadata is not None and metadata.retention_class == "PROTECTED"
        assert (
            repository.coverage_eligibility(
                capture.eligibility_digest,
                provider="synthetic-provider",
                competition="synthetic-competition",
                season="2026-27",
                capability="scheduled-fixtures",
                raw_digest=capture.raw_digest,
            )
            == capture.eligibility_digest
        )
        with pytest.raises(SourceAuthorizationError):
            repository.coverage_eligibility(
                capture.eligibility_digest,
                provider="other-provider",
                competition="synthetic-competition",
                season="2026-27",
                capability="scheduled-fixtures",
                raw_digest=capture.raw_digest,
            )
        owner.withdraw(manifest_digest)
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(decision_digest)
        assert ArtifactStore(store).read_artifact(decision_digest) == original
        monkeypatch.setattr(
            "matchvet.source_authorization._checkpoint",
            lambda *_a: pytest.fail("Replay called current service"),
        )
        assert replay_decision(store, decision_digest) == decision


@pytest.mark.parametrize("permission", ["UNKNOWN", "REFUSED", "GRANTED"])
def test_external_permission_is_retained_truthfully(
    permission: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        classification = entry(store)
        grant = (
            ArtifactStore(store)
            .publish_artifact(b"Synthetic grant for private research only.", "text/plain")
            .digest
        )
        classification["external_permission"] = {
            "state": permission,
            "evidence": [grant] if permission == "GRANTED" else [],
            "reason": "Synthetic exact external classification.",
        }
        manifest = acquisition_manifest(store, classification)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        decision = SourceAuthorizationRepository(store).authorize(manifest)
        assert replay_decision(store, decision)["state"] == "APPROVED"
        result = verify_manifest(store, manifest)["entries"][0]
        assert result["external_permission"]["state"] == permission
        assert result["retention"]["redistributable"] is False
        assert "REDISTRIBUTION" not in result["requested_operations"]


@pytest.mark.parametrize(
    "change",
    [
        {"continuity": "UNCERTAIN"},
        {"sequence": 0},
        {"head": "f" * 64},
        {"nonce": "0" * 64},
        {"history": "restored-history"},
        {"catalog": "other-catalog"},
    ],
)
def test_stale_conflicting_or_uncertain_checkpoint_refuses(
    change: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        repository = SourceAuthorizationRepository(store)
        prior = repository.authorize(manifest)
        owner.head_changes.update(change)
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(prior)
        assert replay_decision(store, prior)["state"] == "APPROVED"


@pytest.mark.parametrize("boundary", ["dispatch", "acquire", "normalize", "staging"])
def test_mid_operation_withdrawal_refuses_private_admission(
    boundary: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        repository = SourceAuthorizationRepository(store)
        dispatches: list[str] = []

        def acquire() -> bytes:
            dispatches.append("sent")
            if boundary == "acquire":
                owner.withdraw(manifest)
            return b"withdrawn raw source"

        def normalize(_raw: bytes) -> bytes:
            if boundary == "normalize":
                owner.withdraw(manifest)
            return b"withdrawn normalized source"

        if boundary == "dispatch":
            original = repository.authorize

            def authorize(identity: str) -> str:
                result = original(identity)
                owner.withdraw(identity)
                return result

            monkeypatch.setattr(repository, "authorize", authorize)
        if boundary == "staging":
            original_publish = ArtifactStore._publish_object

            def stage(artifacts: ArtifactStore, content: bytes, record: Any) -> None:
                original_publish(artifacts, content, record)
                if content == b"withdrawn raw source":
                    owner.withdraw(manifest)

            monkeypatch.setattr(ArtifactStore, "_publish_object", stage)
        with pytest.raises((SourceAuthorizationError, ValueError)):
            repository.acquire(manifest, acquire, normalize)
        if boundary == "dispatch":
            assert not dispatches
        assert all(item.media_type != RAW_MEDIA_TYPE for item in store.artifact_catalog())


def test_restored_away_withdrawal_and_cached_decision_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        repository = SourceAuthorizationRepository(store)
        decision = repository.authorize(manifest)
        owner.withdraw(manifest)
        (owner.records / "00000000000000000002.json").unlink()
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(decision)
        (owner.records / "00000000000000000002.json").write_bytes(owner.raws[-1])
        owner.append(manifest, "reconcile")
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(decision)


@pytest.mark.parametrize("mutation", ["manifest", "policy", "signature", "key", "purpose", "fork"])
def test_missing_or_forged_current_authority_refuses(
    mutation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        changes: dict[str, Any] = {}
        if mutation == "manifest":
            changes["manifest_digest"] = "0" * 64
        if mutation == "policy":
            changes["policy_digest"] = "0" * 64
        if mutation == "purpose":
            changes["purpose"] = "PLAY"
        raw = owner.append(
            "0" * 64 if mutation == "manifest" else manifest,
            **{k: v for k, v in changes.items() if k != "manifest_digest"},
        )
        path = owner.records / "00000000000000000001.json"
        if mutation == "signature":
            envelope = json.loads(raw)
            envelope["signature"] = "0" * 128
            path.write_bytes(canonical(envelope))
        if mutation == "key":
            owner.config["verification_key"] = "0" * 44
            owner.config_path.write_bytes(canonical(owner.config))
        if mutation == "fork":
            (owner.records / "fork.json").write_bytes(raw)
        with pytest.raises(SourceAuthorizationError):
            SourceAuthorizationRepository(store).authorize(manifest)


def test_changed_terms_need_new_review_and_exact_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        old = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(old)
        repository = SourceAuthorizationRepository(store)
        prior_decision = repository.authorize(old)
        changed = entry(store)
        changed["terms_review"]["identity"] = "synthetic-terms-v2"
        changed["external_permission"]["state"] = "REFUSED"
        new = acquisition_manifest(store, changed)
        with pytest.raises(SourceAuthorizationError):
            repository.authorize(new)
        owner.append(
            old,
            "supersede",
            state="SUPERSEDED",
            reason_codes=["TERMS_CHANGED"],
            replacement_manifest_digest=new,
            adverse={
                "effective_from": "UNKNOWN",
                "published_at": owner.now,
                "observed_at": owner.now,
                "reason": "Changed terms require review.",
            },
        )
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(prior_decision)
        owner.append(new)
        assert replay_decision(store, repository.authorize(new))["state"] == "APPROVED"
        assert replay_decision(store, prior_decision)["state"] == "APPROVED"


@pytest.mark.parametrize(
    "mutation",
    [
        "redistribute",
        "retention",
        "grant",
        "limits",
        "operations",
        "lineage",
        "policy",
        "duplicate",
        "terms",
    ],
)
def test_invalid_manifest_refuses(
    mutation: str,
    tmp_path: Path,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        original = acquisition_manifest(store)
        value = read(store, original, MANIFEST_MEDIA_TYPE)
        classification = value["entries"][0]
        if mutation == "redistribute":
            classification["requested_operations"].append("REDISTRIBUTION")
        if mutation == "retention":
            classification["retention"]["class"] = "REUSABLE"
        if mutation == "grant":
            classification["external_permission"]["state"] = "GRANTED"
        if mutation == "limits":
            classification["technical_limits"]["bypass_access_controls"] = True
        if mutation == "operations":
            del classification["operation_permissions"]["RAW_RETENTION"]
        if mutation == "lineage":
            classification["upstream_lineage"]["identities"] = ["invented-upstream"]
        if mutation == "policy":
            value["policy_digest"] = "0" * 64
        if mutation == "duplicate":
            value["entries"].append(classification)
        if mutation == "terms":
            classification["terms_review"]["digest"] = "UNKNOWN"
        value["projection"]["request"]["entry"] = classification
        altered = (
            ArtifactStore(store).publish_artifact(canonical(value), MANIFEST_MEDIA_TYPE).digest
        )
        with pytest.raises(SourceAuthorizationError):
            verify_manifest(store, altered)


def test_retained_self_signed_decision_has_no_current_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "caller-owner", store, monkeypatch)
        owner.append(manifest)
        repository = SourceAuthorizationRepository(store)
        decision = repository.authorize(manifest)
        assert read(store, decision, DECISION_MEDIA_TYPE)["policy_digest"] == POLICY_DIGEST
        owner.config_path.unlink()
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(decision)
        assert replay_decision(store, decision)["state"] == "APPROVED"


def test_fresh_signed_unix_checkpoint_is_the_current_runtime_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.causal_activation import _checkpoint

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        monkeypatch.setattr("matchvet.source_authorization._checkpoint", _checkpoint)
        # Unix address length is bounded independently of pytest's long paths.
        path = str(tmp_path.parent / ("source-" + tmp_path.name[-12:] + ".sock"))
        owner.config["checkpoint_socket"] = path
        owner.config_path.write_bytes(canonical(owner.config))
        errors: list[Exception] = []
        nonces: list[str] = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(2)
            server.settimeout(5)

            def serve() -> None:
                try:
                    for _ in range(2):
                        connection, _address = server.accept()
                        with connection:
                            connection.settimeout(5)
                            message = b""
                            while not message.endswith(b"\n"):
                                message += connection.recv(4096)
                            request = json.loads(message)
                            assert request["history"] == owner.config["history"]
                            nonces.append(request["nonce"])
                            connection.sendall(
                                owner.checkpoint(owner.config, request["nonce"]) + b"\n"
                            )
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=serve)
            thread.start()
            try:
                repository = SourceAuthorizationRepository(store)
                decision = repository.authorize(manifest)
                repository.require_current(decision)
            finally:
                thread.join(timeout=6)
                Path(path).unlink(missing_ok=True)
            assert not thread.is_alive() and not errors
            assert len(nonces) == 2 and nonces[0] != nonces[1]


@pytest.mark.parametrize("boundary", ["approval", "terms"])
def test_expired_authority_or_review_refuses_before_dispatch(
    boundary: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        classification = entry(store)
        if boundary == "terms":
            classification["terms_review"]["valid_until"] = "2026-10-10T09:00:00Z"
        manifest = acquisition_manifest(store, classification)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(
            manifest,
            not_after="2026-10-10T09:00:00Z" if boundary == "approval" else "2026-11-01T00:00:00Z",
        )
        with pytest.raises(SourceAuthorizationError):
            SourceAuthorizationRepository(store).acquire(
                manifest,
                lambda: pytest.fail("Expired authorization dispatched"),
                lambda value: value,
            )


@pytest.mark.parametrize("state", ["APPROVED", "REFUSED", "UNKNOWN"])
def test_conflicting_active_terms_classifications_refuse(
    state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        original = acquisition_manifest(store)
        changed = entry(store)
        changed["terms_review"]["identity"] = "conflicting-terms-review"
        successor = acquisition_manifest(store, changed)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(original)
        repository = SourceAuthorizationRepository(store)
        cached = repository.authorize(original)
        owner.append(
            successor, state=state, reason_codes=[] if state == "APPROVED" else ["CHANGED_TERMS"]
        )
        with pytest.raises(SourceAuthorizationError):
            repository.authorize(original)
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(cached)
        owner.append(
            original,
            action="supersede",
            state="SUPERSEDED",
            reason_codes=["CHANGED_TERMS"],
            replacement_manifest_digest=successor,
            adverse={
                "effective_from": owner.now,
                "published_at": owner.now,
                "observed_at": owner.now,
                "reason": "Changed terms review",
            },
        )
        replacement = repository.authorize(successor)
        if state == "APPROVED":
            repository.require_current(replacement)
        else:
            assert replay_decision(store, replacement)["state"] == state
            with pytest.raises(SourceAuthorizationError):
                repository.require_current(replacement)


def test_lossless_normalization_keeps_distinct_operations_with_identical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        repository = SourceAuthorizationRepository(store)
        capture = repository.acquire(manifest, lambda: b"identical source", lambda raw: raw)
        assert capture.raw_digest == capture.normalized_digest
        assert (
            repository.coverage_eligibility(
                capture.eligibility_digest,
                provider="synthetic-provider",
                competition="synthetic-competition",
                season="2026-27",
                capability="scheduled-fixtures",
                raw_digest=capture.raw_digest,
            )
            == capture.eligibility_digest
        )


@pytest.mark.parametrize("stage", ["ACQUISITION", "SELECTED_GRAPH", "OUTCOME"])
def test_attribution_alone_cannot_authorize_retained_operations(stage: str, tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        classification = entry(store)
        classification["requested_operations"] = ["ATTRIBUTION"]
        with pytest.raises(SourceAuthorizationError, match="operation authority"):
            _require_applicable(
                {"stage": stage, "entries": [classification]},
                {
                    "state": "APPROVED",
                    "issued_at": "2026-10-10T09:00:00Z",
                    "not_before": "2026-10-10T00:00:00Z",
                    "not_after": "2026-11-01T00:00:00Z",
                },
            )


def test_withdrawn_scope_requires_explicit_reviewed_supersession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        original = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(original)
        repository = SourceAuthorizationRepository(store)
        historical = repository.authorize(original)
        owner.withdraw(original)
        changed = entry(store)
        changed["terms_review"]["identity"] = "review-after-withdrawal"
        successor = acquisition_manifest(store, changed)
        owner.append(successor)
        with pytest.raises(SourceAuthorizationError):
            repository.authorize(successor)
        owner.append(
            original,
            action="supersede",
            state="SUPERSEDED",
            reason_codes=["NEW_REVIEW"],
            replacement_manifest_digest=successor,
            adverse={
                "effective_from": owner.now,
                "published_at": owner.now,
                "observed_at": owner.now,
                "reason": "New independent review",
            },
        )
        repository.require_current(repository.authorize(successor))
        assert replay_decision(store, historical)["state"] == "APPROVED"
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(historical)


def test_fresh_checkpoint_cannot_roll_back_cached_authorization_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = acquisition_manifest(store)
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        owner.now = "2026-10-10T10:00:00Z"
        repository = SourceAuthorizationRepository(store)
        historical = repository.authorize(manifest)
        owner.now = "2026-10-10T09:30:00Z"
        with pytest.raises(SourceAuthorizationError):
            repository.require_current(historical)
        assert replay_decision(store, historical)["issued_at"] == "2026-10-10T10:00:00Z"

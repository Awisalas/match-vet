from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from causal_activation_support import Owner, bundle_fields, fresh_bundle
from causal_selection_support import (
    approval,
    install_admission,
    synthetic_graph,
    synthetic_verify,
    trust,
)

from matchvet.causal_activation import _retained_approval
from matchvet.causal_selection import _load_approval, _WitnessAttempt
from matchvet.causal_trust import _authenticate as _authenticate_uncached
from matchvet.causal_trust import _AuthenticatedTrust, _TrustBundle
from matchvet.causal_witness import WitnessError, _canonical, _digest
from matchvet.matchweek_research import MatchweekResearchError, MatchweekResearchRepository
from matchvet.store import Store, open_store


@cache
def _authenticate(bundle: _TrustBundle) -> _AuthenticatedTrust:
    # Cache only after real verification of these exact immutable offline bytes.
    # Mutations still execute all signature/reference/hash checks. Owner records
    # and fresh checkpoint signatures are never cached.
    return _authenticate_uncached(bundle)


@pytest.fixture(autouse=True)
def exact_offline_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("matchvet.causal_activation._authenticate", _authenticate)
    monkeypatch.setattr("matchvet.causal_trust._authenticate", _authenticate)
    monkeypatch.setattr("causal_activation_support._authenticate", _authenticate)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as value:
        yield value


@pytest.fixture
def owner(store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Owner:
    value = Owner(tmp_path / "owner", store)
    monkeypatch.setattr("matchvet.causal_activation._OWNER_CONFIG", value.config_path)
    monkeypatch.setattr("matchvet.causal_activation._checkpoint", value.checkpoint)
    return value


def test_missing_owner_refuses(store: Store) -> None:
    with pytest.raises(MatchweekResearchError, match="Authenticated causal"):
        _load_approval(store)


def test_valid_activation_is_exact_signed_evidence(owner: Owner, store: Store) -> None:
    state, bundle = _load_approval(store)
    assert (
        state.profile_digest == "7ba7e2f4db4de3aa7ef41d77d9ff5f8fafecb73c6de9c5b297924454f51e5c66"
    )
    assert bundle == trust()
    assert state.owner_record == owner.raws[0]
    assert _digest(state.owner_record) != _digest(state.evidence())
    original, admitted = _retained_approval(state.evidence())
    assert original == state and admitted == bundle
    state.require(_authenticate(bundle), bundle, "2026-10-05T04:50:20Z", "2026-10-05T04:50:22Z")


@pytest.mark.parametrize(
    "missing", ["verification_key", "records", "checkpoint_socket", "approval"]
)
def test_missing_required_authority(owner: Owner, store: Store, missing: str) -> None:
    if missing == "approval":
        for path in owner.records.iterdir():
            path.unlink()
    else:
        del owner.config[missing]
        owner.install()
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "wrong-owner"),
        ("deployment", "wrong-deployment"),
        ("catalog", "/wrong/catalog"),
        ("history", "wrong-history"),
        ("profile_digest", "0" * 64),
        ("purpose", "PLAY"),
        ("issue", 37),
        ("sequence", 2),
        ("sequence", True),
        ("predecessor", "0" * 64),
        ("domain", "wrong-domain"),
        ("schema_version", 2),
        ("algorithm", "none"),
        ("action", "admit"),
        ("not_before", "2026-11-02T00:00:00Z"),
    ],
)
def test_signed_wrong_identity_refuses(owner: Owner, store: Store, field: str, value: Any) -> None:
    body = json.loads(owner.raws[0])["signed"]
    body[field] = value
    (owner.records / "00000000000000000001.json").write_bytes(owner.sign(body))
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint", "https://other.invalid"),
        ("operator", "other"),
        ("policy_oid", "1.2.3"),
        ("policy_revision", "changed"),
        ("policy_sha256", "0" * 64),
        ("signer", "0" * 64),
        ("anchor", "0" * 64),
        ("bootstrap", "0" * 64),
        ("initial_trusted_root", "0" * 64),
        ("timescale", "SMEARED_UTC"),
        ("premises", []),
        ("assurance", "CURRENT_TRUST"),
        ("current_revocation_checked", True),
    ],
)
def test_signed_changed_profile_or_premises_refuses(
    owner: Owner,
    store: Store,
    field: str,
    value: Any,
) -> None:
    body = json.loads(owner.raws[0])["signed"]
    body["profile"][field] = value
    (owner.records / "00000000000000000001.json").write_bytes(owner.sign(body))
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize("attack", ["forged", "modified", "self-key", "self-approval", "catalog"])
def test_caller_authorization_cannot_grant_authority(
    owner: Owner,
    store: Store,
    tmp_path: Path,
    attack: str,
) -> None:
    path = owner.records / "00000000000000000001.json"
    if attack == "forged":
        body = json.loads(path.read_bytes())
        body["signature"] = "00" * 64
        path.write_bytes(_canonical(body))
    elif attack == "modified":
        body = json.loads(path.read_bytes())
        body["signed"]["not_after"] = "2035-01-01T00:00:00Z"
        path.write_bytes(_canonical(body))
    elif attack == "self-key":
        body = json.loads(path.read_bytes())
        body["verification_key"] = owner.key.hex()
        path.write_bytes(_canonical(body))
    else:
        from matchvet.artifacts import ArtifactStore

        ArtifactStore(store).publish_artifact(
            owner.raws[0] if attack == "catalog" else approval().evidence(),
            "application/vnd.matchvet.causal-selection-evidence.v1+octet-stream",
        )
        owner.config_path.unlink()
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_fresh_exact_admission_advances_floors(owner: Owner, store: Store) -> None:
    prior, old = _load_approval(store)
    owner.admit(fresh_bundle())
    state, fresh = _load_approval(store)
    assert [v for _, v, _ in state.floors] == [15, 804, 166, 14]
    assert state.owner_record == owner.raws[-1]
    assert fresh == fresh_bundle()
    state.require(_authenticate(fresh), fresh, "2026-10-10T01:50:00Z", "2026-10-10T01:50:01Z")
    with pytest.raises(WitnessError, match="validity/expiry"):
        prior.require(_authenticate(old), old, "2026-10-10T01:50:00Z", "2026-10-10T01:50:01Z")
    assert _retained_approval(prior.evidence()) == (prior, old)


@pytest.mark.parametrize(
    "boundary,passes",
    [
        ("2026-10-10T01:39:24.999999Z", True),
        ("2026-10-10T01:39:25Z", False),
        ("2026-10-10T01:39:25.000001Z", False),
    ],
)
def test_timestamp799_expiry(owner: Owner, store: Store, boundary: str, passes: bool) -> None:
    state, bundle = _load_approval(store)
    auth = _authenticate(bundle)
    if passes:
        state.require(auth, bundle, "2026-10-10T01:39:24Z", boundary)
    else:
        with pytest.raises(WitnessError):
            state.require(auth, bundle, "2026-10-10T01:39:24Z", boundary)


@pytest.mark.parametrize(
    "lower,upper,passes",
    [
        ("2025-07-04T00:00:00Z", "2025-07-04T00:00:01Z", True),
        ("2025-07-03T23:59:59Z", "2025-07-04T00:00:01Z", False),
        ("2026-10-05T04:50:20Z", "2026-10-05T04:50:22Z", True),
        ("2026-10-05T04:50:20Z", "2026-10-05T04:50:22.000001Z", False),
    ],
)
def test_entire_approval_interval(
    owner: Owner, store: Store, lower: str, upper: str, passes: bool
) -> None:
    body = json.loads(owner.raws[0])["signed"]
    body["not_after"] = "2026-10-05T04:50:22Z"
    raw = owner.sign(body)
    owner.raws[0] = raw
    (owner.records / "00000000000000000001.json").write_bytes(raw)
    state, bundle = _load_approval(store)
    if passes:
        state.require(_authenticate(bundle), bundle, lower, upper)
    else:
        with pytest.raises(WitnessError):
            state.require(_authenticate(bundle), bundle, lower, upper)


@pytest.mark.parametrize("attack", ["signature", "hash", "reference", "equal-hash", "downward"])
def test_invalid_metadata_admission_refuses(owner: Owner, store: Store, attack: str) -> None:
    bundle = fresh_bundle()
    fields = bundle_fields(bundle)
    floors = [list(v) for v in _authenticate(bundle).versions]
    if attack in ("signature", "hash", "reference"):
        role = "timestamp" if attack != "hash" else "trusted_root"
        raw = getattr(bundle, role)
        value = json.loads(raw)
        if attack == "signature":
            value["signatures"][0]["sig"] = "00"
        elif attack == "reference":
            value["signed"]["meta"]["snapshot.json"]["version"] = 999
        else:
            value["mediaType"] = "changed"
        fields[role] = _canonical(value).hex()
    elif attack == "equal-hash":
        # Cryptographically equivalent JSON with changed exact same-version hash.
        fields["targets"] = (bundle.targets + b"\n").hex()
    else:
        owner.admit(bundle)
        fields = bundle_fields(trust())
        floors = [list(v) for v in _authenticate(trust()).versions]
    owner.append("admit", bundle=fields, floors=floors)
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize(
    "changes",
    [
        {"continuity": "UNCERTAIN"},
        {"sequence": 0},
        {"sequence": 2},
        {"head": "0" * 64},
        {"nonce": "00" * 32},
        {"history": "fork"},
        {"floors": []},
    ],
)
def test_bad_independent_checkpoint_refuses(
    owner: Owner, store: Store, changes: dict[str, Any]
) -> None:
    owner.head_changes = changes
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_restored_away_withdrawal_cannot_use_signed_old_records(owner: Owner, store: Store) -> None:
    original, _ = _load_approval(store)
    owner.withdraw()
    withdrawal = owner.records / "00000000000000000002.json"
    raw = withdrawal.read_bytes()
    withdrawal.unlink()
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)
    withdrawal.write_bytes(raw)
    owner.head_changes = {"continuity": "UNCERTAIN"}
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)
    owner.append("reconcile")
    owner.head_changes = {}
    state, _ = _load_approval(store)
    assert state.withdrawn_from == "2026-10-05T04:50:20Z"
    assert _retained_approval(original.evidence())[0] == original


@pytest.fixture
def causal(
    owner: Owner, store: Store, monkeypatch: pytest.MonkeyPatch
) -> tuple[MatchweekResearchRepository, Any, list[_WitnessAttempt]]:
    graph = synthetic_graph(store)
    install_admission(monkeypatch, graph)
    monkeypatch.setattr("matchvet.causal_witness._verify_event", synthetic_verify)
    calls: list[_WitnessAttempt] = []

    def post(attempt: _WitnessAttempt) -> bytes:
        attempt._start_transport()
        calls.append(attempt)
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", post)
    return MatchweekResearchRepository(store), graph, calls


def test_signed_receipt_replay_immutable_after_metadata_and_withdrawal(
    owner: Owner,
    causal: Any,
    store: Store,
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    from matchvet.artifacts import ArtifactStore

    artifacts = ArtifactStore(store)
    original = artifacts.read_artifact(selected.completion_receipt_digest)
    owner.admit(fresh_bundle())
    assert repository.replay(selected.digest) == selected
    assert artifacts.read_artifact(selected.completion_receipt_digest) == original
    owner.withdraw(None)
    with pytest.raises(MatchweekResearchError):
        repository.replay(selected.digest)
    assert repository.inspect_causal(selected.digest) == selected
    owner.config_path.unlink()
    assert repository.inspect_causal(selected.digest) == selected
    assert artifacts.read_artifact(selected.completion_receipt_digest) == original
    assert len(calls) == 1
    with pytest.raises(RuntimeError):
        calls[0]._obtain()


@pytest.mark.parametrize(
    "when", ["before-post", "after-DNS", "receipt-stage", "receipt-insert", "metadata"]
)
def test_mid_operation_owner_change_is_terminal(
    owner: Owner,
    causal: Any,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
    when: str,
) -> None:
    repository, graph, calls = causal
    from matchvet.artifacts import ArtifactStore

    if when == "before-post":
        original = _WitnessAttempt._obtain

        def obtain(attempt: _WitnessAttempt) -> Any:
            owner.withdraw()
            return original(attempt)

        monkeypatch.setattr(_WitnessAttempt, "_obtain", obtain)
    elif when in ("after-DNS", "metadata"):

        def post(attempt: _WitnessAttempt) -> bytes:
            attempt._start_transport()
            if when == "metadata":
                owner.admit(fresh_bundle())
            else:
                owner.withdraw()
            attempt._check_transport()
            pytest.fail("Owner change cannot dispatch")

        monkeypatch.setattr("matchvet.causal_witness._post", post)
    elif when == "receipt-stage":
        original_publish = ArtifactStore.publish_artifact
        changed = False

        def publish(self: ArtifactStore, *args: Any, **kwargs: Any) -> Any:
            nonlocal changed
            if not changed:
                owner.withdraw()
                changed = True
            return original_publish(self, *args, **kwargs)

        monkeypatch.setattr(ArtifactStore, "publish_artifact", publish)
    else:
        from matchvet.store import _ResearchOperation

        original_commit = _ResearchOperation._before_commit

        def before_commit(operation: Any) -> None:
            if operation._phase == "receipt_attempt":
                owner.withdraw()
            original_commit(operation)

        monkeypatch.setattr(_ResearchOperation, "_before_commit", before_commit)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    from matchvet.research_identity import completion_slot, selection_slot

    assert store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id)) is not None
    assert store.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id)) is None
    owner.append("reconcile")
    for _ in range(2):
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) <= 1


def test_reconciliation_preserves_qualified_history_but_no_capability(
    owner: Owner, causal: Any
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    owner.head_changes = {"continuity": "UNCERTAIN"}
    with pytest.raises(MatchweekResearchError):
        repository.replay(selected.digest)
    owner.append("reconcile")
    owner.head_changes = {}
    assert repository.replay(selected.digest) == selected
    assert repository.seal_completed_v2(graph.f16_digest) == selected
    assert len(calls) == 1
    with pytest.raises(RuntimeError):
        calls[0]._start_transport()


def test_self_signed_other_issuer_cannot_override_installed_key(
    owner: Owner,
    store: Store,
    tmp_path: Path,
) -> None:
    private = owner.private.read_bytes()
    owner.private.write_bytes(private[:16] + bytes(reversed(range(32))))
    body = json.loads(owner.raws[0])["signed"]
    from matchvet.causal_trust import _openssl

    other_key = _openssl(
        [
            "pkey",
            "-inform",
            "DER",
            "-in",
            str(owner.private),
            "-pubout",
            "-outform",
            "DER",
        ]
    ).stdout
    body["owner"] = _digest(other_key)
    (owner.records / "00000000000000000001.json").write_bytes(owner.sign(body))
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_advanced_same_version_different_hash_refuses(owner: Owner, store: Store) -> None:
    bundle = fresh_bundle()
    owner.admit(bundle)
    changed = replace(bundle, timestamp=bundle.timestamp + b"\n")
    authenticated = _authenticate(changed)  # Signature-valid; greater than reviewed floor799.
    owner.append(
        "admit", bundle=bundle_fields(changed), floors=[list(v) for v in authenticated.versions]
    )
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_all_copy_local_rollback_cannot_replay_saved_checkpoint(
    owner: Owner,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _ = _load_approval(store)
    checkpoint = bytes.fromhex(json.loads(state.evidence())["checkpoint"])
    owner.withdraw()
    # All local owner copies, including saved checkpoint, return to the old state.
    (owner.records / "00000000000000000002.json").unlink()
    monkeypatch.setattr("matchvet.causal_activation._checkpoint", lambda *_args: checkpoint)
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)
    # A fresh independent response instead exposes the restored-away withdrawal.
    monkeypatch.setattr("matchvet.causal_activation._checkpoint", owner.checkpoint)
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_future_withdrawal_refuses_all_new_work(owner: Owner, causal: Any) -> None:
    repository, graph, calls = causal
    owner.withdraw("2026-10-06T00:00:00Z")
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert calls == []


def test_adverse_boundary_is_separate_from_publication_and_observation(
    owner: Owner, causal: Any
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    owner.withdraw("2026-10-05T04:50:22.000001Z")
    assert repository.replay(selected.digest) == selected
    assert repository.inspect_causal(selected.digest) == selected
    assert len(calls) == 1


def test_changed_or_forged_cached_approval_cannot_dispatch(
    owner: Owner,
    causal: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, graph, calls = causal
    original = _WitnessAttempt._obtain

    def obtain(attempt: _WitnessAttempt) -> Any:
        attempt._approval = replace(attempt._approval, not_after="2035-01-01T00:00:00Z")
        return original(attempt)

    monkeypatch.setattr(_WitnessAttempt, "_obtain", obtain)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert calls == []


def test_retained_key_and_signed_records_are_inspection_only(owner: Owner, store: Store) -> None:
    state, _ = _load_approval(store)
    owner.config_path.unlink()
    inspected, _ = _retained_approval(state.evidence())
    assert inspected == state
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)
    from matchvet.causal_activation import _require_lineage

    with pytest.raises(WitnessError):
        _require_lineage(state, approval())


def test_restart_reconciliation_restores_no_request_or_receipt_capability(
    owner: Owner,
    causal: Any,
    store: Store,
    tmp_path: Path,
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    store.close()
    owner.append("reconcile")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as reopened:
        replay = MatchweekResearchRepository(reopened)
        assert replay.replay(selected.digest) == selected
        assert replay.seal_completed_v2(graph.f16_digest) == selected
        with pytest.raises(RuntimeError):
            calls[0]._start_transport()
    assert len(calls) == 1


def test_issue86_live_continuation_still_requires_separate_source_authorization(
    owner: Owner,
    causal: Any,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, graph, _calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    assert repository.replay(selected.digest) == selected
    from matchvet.research_capture import CaptureError, CaptureIndex, ResearchCaptureRepository

    capture = ResearchCaptureRepository(store)
    # The gate precedes capture-row discovery and CB01. Use the already selected
    # exact digest at the retained-index seam, with genuine current causal authority.
    monkeypatch.setattr(
        capture,
        "replay",
        lambda _digest: CaptureIndex(
            _canonical(
                {
                    "selection": {"digest": selected.digest},
                }
            )
        ),
    )
    before = store.artifact_catalog()
    with pytest.raises(CaptureError, match="Real-source authorization is absent"):
        capture.capture_week(selected.digest, prior_index_digest="retained-index", enroll=True)
    assert store.artifact_catalog() == before


def test_missing_independent_checkpoint_refuses(
    owner: Owner, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exercise the real socket client rather than the synthetic service callback.
    monkeypatch.undo()
    monkeypatch.setattr("matchvet.causal_activation._OWNER_CONFIG", owner.config_path)
    owner.config["checkpoint_socket"] = str(owner.root / "absent.sock")
    owner.install()
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_checkpoint_socket_exchanges_fresh_challenge_and_rejects_old_response(
    owner: Owner,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket
    import tempfile
    import threading

    monkeypatch.undo()
    monkeypatch.setattr("matchvet.causal_activation._OWNER_CONFIG", owner.config_path)
    received: list[dict[str, Any]] = []
    errors: list[BaseException] = []
    with tempfile.TemporaryDirectory(prefix="mv87-checkpoint-") as directory:
        path = str(Path(directory) / "head.sock")
        owner.config["checkpoint_socket"] = path
        owner.install()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(10)

            def serve() -> None:
                try:
                    saved: bytes | None = None
                    for _ in range(2):
                        connection, _address = listener.accept()
                        with connection:
                            connection.settimeout(5)
                            raw = bytearray()
                            while not raw.endswith(b"\n"):
                                raw.extend(connection.recv(65536))
                            request = json.loads(raw)
                            received.append(request)
                            if saved is None:
                                saved = owner.checkpoint(owner.config, request["nonce"])
                            connection.sendall(saved + b"\n")
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=serve)
            thread.start()
            state, _ = _load_approval(store)
            assert state.owner_record == owner.raws[0]
            with pytest.raises(MatchweekResearchError):
                _load_approval(store)
            thread.join(timeout=10)
            assert not thread.is_alive() and not errors
    assert len(received) == 2
    assert received[0]["nonce"] != received[1]["nonce"]
    assert len(bytes.fromhex(received[0]["nonce"])) == 32


@pytest.mark.parametrize("attack", ["duplicate", "noncanonical", "unsigned", "extra", "floors"])
def test_malformed_or_unbound_record_refuses(owner: Owner, store: Store, attack: str) -> None:
    path = owner.records / "00000000000000000001.json"
    raw = owner.raws[0]
    if attack == "duplicate":
        raw = raw.replace(b'"signature":', b'"signature":"00","signature":', 1)
    elif attack == "noncanonical":
        raw += b"\n"
    elif attack == "unsigned":
        raw = _canonical({"signed": json.loads(raw)["signed"]})
    else:
        body = json.loads(raw)["signed"]
        if attack == "extra":
            body["verification_key"] = owner.key.hex()
        else:
            body["floors"][1][1] = 798
        raw = owner.sign(body)
    path.write_bytes(raw)
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize(
    "premise", ["operator_policy_compliance", "uncompromised_authority", "unsmeared_utc"]
)
@pytest.mark.parametrize("flag", [False, 1, None])
def test_explicit_premise_acceptance_requires_true(
    owner: Owner,
    store: Store,
    premise: str,
    flag: Any,
) -> None:
    body = json.loads(owner.raws[0])["signed"]
    body["accepted_premises"][premise] = flag
    (owner.records / "00000000000000000001.json").write_bytes(owner.sign(body))
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


@pytest.mark.parametrize("attack", ["predecessor", "gap", "fork", "reactivation"])
def test_owner_history_requires_append_only_sequence(
    owner: Owner, store: Store, attack: str
) -> None:
    if attack == "predecessor":
        owner.append("reconcile", predecessor="00" * 32)
    elif attack == "gap":
        owner.append("reconcile")
        (owner.records / "00000000000000000002.json").rename(
            owner.records / "00000000000000000003.json"
        )
    elif attack == "fork":
        owner.append("reconcile")
        (owner.records / "fork.json").write_bytes(owner.raws[-1])
    else:
        owner.append("activate")
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)


def test_real_transport_rechecks_owner_after_tls_and_emits_no_request(
    owner: Owner,
    causal: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, graph, calls = causal
    from matchvet.causal_transport import _post

    emitted: list[object] = []

    class Connection:
        sock: Any = None
        response_class: Any = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.sock = self

        def connect(self) -> None:
            owner.withdraw()

        def settimeout(self, _timeout: float) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            emitted.append(args)
            pytest.fail("Authenticated withdrawal must prevent request emission")

        def close(self) -> None:
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    monkeypatch.setattr("matchvet.causal_witness._post", _post)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert not emitted and not calls


def test_metadata_admission_cannot_rewrite_same_version_root_rotation(
    owner: Owner, store: Store
) -> None:
    bundle = trust()
    changed = replace(bundle, roots=(bundle.roots[0] + b"\n", *bundle.roots[1:]))
    authenticated = _authenticate(changed)
    owner.append(
        "admit", bundle=bundle_fields(changed), floors=[list(v) for v in authenticated.versions]
    )
    with pytest.raises(MatchweekResearchError):
        _load_approval(store)

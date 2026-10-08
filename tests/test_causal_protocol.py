from __future__ import annotations

import copy
import os
import pickle
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from causal_selection_support import (
    approval,
    install_admission,
    synthetic_graph,
    synthetic_verify,
    trust,
)

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.causal_selection import (
    _CausalGraph,
    _manifest_v2,
    _WitnessAttempt,
)
from matchvet.causal_trust import _authenticate, _AuthenticatedTrust
from matchvet.causal_witness import WitnessError
from matchvet.causal_witness import _post as _real_post
from matchvet.matchweek_research import MatchweekResearchError, MatchweekResearchRepository
from matchvet.research_identity import completion_slot, selection_slot
from matchvet.store import Store, open_store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as value:
        yield value


def test_fresh_selection_requests_once_and_replays_offline(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = synthetic_graph(store)
    install_admission(monkeypatch, graph)
    monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (approval(), trust()))
    monkeypatch.setattr("matchvet.causal_witness._verify_event", synthetic_verify)
    calls: list[bytes] = []

    def post(attempt: object) -> bytes:
        from matchvet.causal_selection import _WitnessAttempt

        assert isinstance(attempt, _WitnessAttempt)
        calls.append(attempt._start_transport())
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", post)
    repository = MatchweekResearchRepository(store)
    selected = repository.seal_completed_v2(graph.f16_digest)
    assert selected == repository.replay(selected.digest)
    assert selected == repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


@pytest.fixture(scope="module")
def authenticated() -> _AuthenticatedTrust:
    return _authenticate(trust())


@pytest.fixture
def causal(
    store: Store, monkeypatch: pytest.MonkeyPatch, authenticated: _AuthenticatedTrust
) -> tuple[MatchweekResearchRepository, _CausalGraph, list[_WitnessAttempt]]:
    graph = synthetic_graph(store)
    install_admission(monkeypatch, graph)
    monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (approval(), trust()))
    monkeypatch.setattr("matchvet.causal_trust._authenticate", lambda b: authenticated)
    monkeypatch.setattr("matchvet.causal_witness._verify_event", synthetic_verify)
    calls: list[_WitnessAttempt] = []

    def post(attempt: _WitnessAttempt) -> bytes:
        attempt._start_transport()
        calls.append(attempt)
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", post)
    return MatchweekResearchRepository(store), graph, calls


def test_precommit_cannot_request(store: Store, causal: Any) -> None:
    _repository, graph, calls = causal
    with store._research_operation(graph.logical_id, lambda: None) as operation:
        operation._configure_causal(graph, approval(), trust())
        with pytest.raises(RuntimeError):
            operation._begin_witness(graph, approval())
    assert calls == []


def test_callbacks_cannot_duplicate_copy_reconstruct_or_borrow_authority(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    saved: list[_WitnessAttempt] = []

    def post(attempt: _WitnessAttempt) -> bytes:
        saved.append(attempt)
        op = attempt._operation
        for action in (
            lambda: copy.copy(attempt),
            lambda: copy.deepcopy(attempt),
            lambda: pickle.dumps(attempt),
            lambda: copy.copy(op),
            lambda: pickle.dumps(op),
        ):
            with pytest.raises(TypeError):
                action()
        clone = object.__new__(_WitnessAttempt)
        clone.__dict__.update(attempt.__dict__)
        for refused_action in (
            attempt._obtain,
            clone._obtain,
            clone._start_transport,
            lambda: op._begin_witness(graph, approval()),
            lambda: repository.seal_completed_v2(graph.f16_digest),
            lambda: repository.seal_completed(graph.f16_digest),
            lambda: op._start("receipt"),
        ):
            with pytest.raises((RuntimeError, MatchweekResearchError)):
                refused_action()
        attempt._start_transport()
        with pytest.raises(RuntimeError):
            attempt._start_transport()
        calls.append(attempt)
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", post)
    repository.seal_completed_v2(graph.f16_digest)
    with pytest.raises(RuntimeError):
        saved[0]._obtain()
    assert len(calls) == 1


def test_fork_and_thread_cannot_use_authority(causal: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, graph, calls = causal

    def post(attempt: _WitnessAttempt) -> bytes:
        failures: list[str] = []

        def different_thread() -> None:
            try:
                attempt._start_transport()
            except RuntimeError:
                failures.append("thread")

        thread = threading.Thread(target=different_thread)
        thread.start()
        thread.join()
        assert failures == ["thread"]
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                attempt._start_transport()
                os.write(write_fd, b"BAD")
            except RuntimeError:
                os.write(write_fd, b"REFUSED")
            finally:
                os._exit(0)
        os.close(write_fd)
        assert os.read(read_fd, 32) == b"REFUSED"
        os.close(read_fd)
        os.waitpid(pid, 0)
        calls.append(attempt)
        attempt._start_transport()
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", post)
    repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_network_failure_is_terminal_even_before_T(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal

    def failing(attempt: _WitnessAttempt) -> bytes:
        attempt._start_transport()
        calls.append(attempt)
        raise OSError("isolated unavailable source")

    monkeypatch.setattr("matchvet.causal_witness._post", failing)
    for _ in range(2):
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1
    assert (
        repository._store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id))
        is not None
    )
    assert (
        repository._store.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id))
        is None
    )


@pytest.mark.parametrize(
    "upper", ["2026-10-05T05:00:00.000000+00:00", "2026-10-05T05:00:00.000001+00:00"]
)
def test_U_equality_and_lateness_leave_occupied_unqualified(
    causal: Any, monkeypatch: pytest.MonkeyPatch, upper: str
) -> None:
    repository, graph, calls = causal

    def late(*args: Any, **kwargs: Any) -> Any:
        return replace(synthetic_verify(*args, **kwargs), upper=upper)

    monkeypatch.setattr("matchvet.causal_witness._verify_event", late)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["imprint", "nonce"])
def test_verified_result_for_another_request_cannot_acknowledge(
    causal: Any, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    repository, graph, calls = causal

    def wrong(*args: Any, **kwargs: Any) -> Any:
        event = synthetic_verify(*args, **kwargs)
        return replace(event, imprint=b"\0" * 32) if field == "imprint" else replace(event, nonce=1)

    monkeypatch.setattr("matchvet.causal_witness._verify_event", wrong)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1
    assert (
        repository._store.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id))
        is None
    )


def test_exact_graph_sync_failure_prevents_commit_and_entropy(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal

    def fail_sync(self: ArtifactStore, records: Any) -> None:
        assert {r.digest for r in records}.issuperset(r.digest for r in graph.references)
        raise ArtifactError("SYNC_TEST", "sync refused")

    monkeypatch.setattr(ArtifactStore, "_sync_graph", fail_sync)
    monkeypatch.setattr(
        "matchvet.causal_selection.secrets.token_bytes", lambda n: pytest.fail("precommit entropy")
    )
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert calls == []
    assert (
        repository._store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id))
        is None
    )


def test_incomplete_or_changed_graph_cannot_select(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    bad = replace(
        graph, references=tuple(r for r in graph.references if r.digest != graph.model_digest)
    )
    install_admission(monkeypatch, bad)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert calls == []


@pytest.mark.parametrize("when", ["before", "after"])
def test_uncertain_selection_commit_never_requests(causal: Any, when: str) -> None:
    repository, graph, calls = causal
    store = repository._store
    connection = store._connection
    assert connection is not None

    class Boundary:
        def __getattr__(self, name: str) -> Any:
            return getattr(connection, name)

        def commit(self) -> None:
            selected = connection.execute(
                "SELECT 1 FROM snapshot_manifests WHERE snapshot_id = ?",
                (selection_slot(graph.logical_id),),
            ).fetchone()
            if selected and when == "before":
                raise RuntimeError("uncertain selection")
            connection.commit()
            if selected:
                raise RuntimeError("uncertain selection")

    store._connection = cast(sqlite3.Connection, Boundary())
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    store._connection = connection
    assert calls == []
    assert (
        store.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id)) is not None
    ) == (when == "after")
    if when == "after":
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
        assert calls == []


@pytest.mark.parametrize("when", ["before", "after"])
def test_ambiguous_receipt_commit_only_reads_exact_index(causal: Any, when: str) -> None:
    repository, graph, calls = causal
    store = repository._store
    connection = store._connection
    assert connection is not None
    attempts: list[str] = []

    class Boundary:
        def __getattr__(self, name: str) -> Any:
            return getattr(connection, name)

        def commit(self) -> None:
            receipt = connection.execute(
                "SELECT 1 FROM snapshot_manifests WHERE snapshot_id = ?",
                (completion_slot(graph.logical_id),),
            ).fetchone()
            if receipt:
                attempts.append("receipt")
                if when == "before":
                    raise RuntimeError("receipt commit uncertain")
            connection.commit()
            if receipt:
                raise RuntimeError("receipt commit uncertain")

    store._connection = cast(sqlite3.Connection, Boundary())
    if when == "after":
        selected = repository.seal_completed_v2(graph.f16_digest)
        assert selected == repository.replay(selected.digest)
    else:
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    store._connection = connection
    assert attempts == ["receipt"]
    assert len(calls) == 1


def test_lost_receipt_evidence_is_never_adopted(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    publish = ArtifactStore.publish_artifact

    def lose(self: ArtifactStore, *args: Any, **kwargs: Any) -> Any:
        operation = self.store._research_owner
        if operation is not None and operation._phase == "receipt_attempt":
            publish(self, *args, **kwargs)
            raise OSError("lost receipt after orphan witness staging")
        return publish(self, *args, **kwargs)

    monkeypatch.setattr(ArtifactStore, "publish_artifact", lose)
    for _ in range(2):
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1
    assert (
        repository._store.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id))
        is None
    )


def test_receipt_cannot_add_or_omit_evidence(causal: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, graph, calls = causal
    original = ArtifactStore._publish_manifest

    def changed(self: ArtifactStore, manifest: Any, **kwargs: Any) -> Any:
        if self.store._research_owner and self.store._research_owner._phase == "receipt_attempt":
            manifest = replace(manifest, artifacts=manifest.artifacts[:-1])
        return original(self, manifest, **kwargs)

    monkeypatch.setattr(ArtifactStore, "_publish_manifest", changed)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_authenticated_withdrawal_refuses_qualification_preserves_inspection(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    withdrawn = replace(approval(), withdrawn_from="2026-10-05T00:00:00Z")
    monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (withdrawn, trust()))
    with pytest.raises(MatchweekResearchError, match="withdrawal"):
        repository.replay(selected.digest)
    assert selected == repository.inspect_causal(selected.digest)
    assert len(calls) == 1


@pytest.mark.parametrize("role", ["selection", "completion"])
def test_cross_version_occupied_slot_never_obtains_authority(causal: Any, role: str) -> None:
    repository, graph, calls = causal
    store = repository._store
    from matchvet.matchweek_research import _version

    with store.transaction() as tx:
        tx.add_version(_version("selection"))
    with store._research_operation(graph.logical_id, lambda: None) as operation:
        old = repository._manifest(
            graph, role="selection", created="2026-10-05T04:00:00.000000+00:00"
        )
        repository._artifacts._publish_research_manifest(old, operation, role="selection")
    for _ in range(2):
        with pytest.raises(MatchweekResearchError, match="cross-version"):
            repository.seal_completed_v2(graph.f16_digest)
    assert calls == []


def test_wrong_graph_and_profile_cannot_begin_in_original_operation(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    from matchvet.store import _ResearchOperation

    begin = _ResearchOperation._begin_witness

    def guard(self: Any, exact: Any, approved: Any) -> Any:
        for args in (
            (replace(exact, f16_digest="0" * 64), approved),
            (exact, replace(approved, profile_digest="0" * 64)),
        ):
            with pytest.raises(RuntimeError):
                begin(self, *args)
        return begin(self, exact, approved)

    monkeypatch.setattr(_ResearchOperation, "_begin_witness", guard)
    repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_copied_or_forged_event_cannot_enable_receipt(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    from matchvet.store import _ResearchOperation

    accept = _ResearchOperation._accept_witness

    def guard(self: Any, attempt: Any, event: Any) -> None:
        for other in (
            copy.copy(event),
            replace(event, profile_digest="0" * 64),
            replace(event, binding=b"wrong"),
        ):
            with pytest.raises(RuntimeError):
                accept(self, attempt, other)
        accept(self, attempt, event)
        with pytest.raises(RuntimeError):
            accept(self, attempt, event)

    monkeypatch.setattr(_ResearchOperation, "_accept_witness", guard)
    repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_closed_store_cannot_deliver_acknowledgement(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal

    def close(attempt: _WitnessAttempt) -> bytes:
        attempt._start_transport()
        calls.append(attempt)
        attempt._operation._store.close()
        return b"isolated-signed-response"

    monkeypatch.setattr("matchvet.causal_witness._post", close)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_all_graph_objects_and_existing_directories_sync_before_entropy(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    synced: list[set[str]] = []
    sync = ArtifactStore._sync_graph
    entropy = __import__("secrets").token_bytes

    def syncing(self: ArtifactStore, records: Any) -> None:
        sync(self, records)
        synced.append({r.digest for r in records})

    def fresh(n: int) -> bytes:
        assert (
            repository._store.snapshot_manifest_digest_for_snapshot(
                selection_slot(graph.logical_id)
            )
            is not None
        )
        assert synced and synced[0].issuperset(r.digest for r in graph.references)
        assert repository._store._research_owner._phase == "witness_attempt"
        return cast(bytes, entropy(n))

    monkeypatch.setattr(ArtifactStore, "_sync_graph", syncing)
    monkeypatch.setattr("matchvet.causal_selection.secrets.token_bytes", fresh)
    repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_restart_replays_only_exact_indexed_receipt(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    selected = repository.seal_completed_v2(graph.f16_digest)
    old_attempt = calls[0]
    path = repository._store.path
    repository._store.close()
    with open_store(path, private_root=path.parent) as reopened:
        replay = MatchweekResearchRepository(reopened)
        assert replay.replay(selected.digest) == selected
        assert (
            replay.replay_for_matchweek(season=graph.season, matchweek_friday=graph.friday)
            == selected
        )
        assert replay.seal_completed_v2(graph.f16_digest) == selected
        with pytest.raises(RuntimeError):
            old_attempt._obtain()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"history_identity": ""},
        {"history_identity": "uncertain-restore"},
        {"floors": ()},
        {"operator_compliance": False},
        {"timescale": "SMEARED_UTC"},
    ],
)
def test_missing_or_uncertain_approval_refuses_without_transport(
    causal: Any, monkeypatch: pytest.MonkeyPatch, changes: Any
) -> None:
    repository, graph, calls = causal
    state = replace(approval(), **changes)
    monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (state, trust()))
    if changes == {"history_identity": "uncertain-restore"}:
        # A different authoritative identity is known only on replay against the
        # original retained activation, never inferred from arbitrary strings.
        monkeypatch.setattr(
            "matchvet.causal_selection._load_approval", lambda s: (approval(), trust())
        )
        selected = repository.seal_completed_v2(graph.f16_digest)
        monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (state, trust()))
        with pytest.raises(MatchweekResearchError):
            repository.replay(selected.digest)
        assert len(calls) == 1
    else:
        with pytest.raises(WitnessError):
            repository.seal_completed_v2(graph.f16_digest)
        assert calls == []


@pytest.mark.parametrize(
    "mode", ["before-request", "after-signing", "receipt-before-commit", "receipt-after-commit"]
)
def test_process_crashes_never_backfill_or_adopt_orphan_bytes(causal: Any, mode: str) -> None:
    import multiprocessing

    from causal_selection_support import crash_worker

    repository, graph, calls = causal
    path = repository._store.path
    repository._store.close()
    process = multiprocessing.get_context("fork").Process(
        target=crash_worker, args=(str(path.parent), graph, mode)
    )
    process.start()
    process.join(30)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("Isolated crash worker exceeded deadline")
    assert process.exitcode == 37
    marker = path.parent / "request-count"
    assert (marker.read_bytes() if marker.exists() else b"") == (
        b"" if mode == "before-request" else b"1"
    )
    with open_store(path, private_root=path.parent) as reopened:
        replay = MatchweekResearchRepository(reopened)
        assert (
            reopened.snapshot_manifest_digest_for_snapshot(selection_slot(graph.logical_id))
            is not None
        )
        if mode == "receipt-after-commit":
            selected = replay.seal_completed_v2(graph.f16_digest)
            assert selected == replay.replay(selected.digest)
        else:
            for _ in range(2):
                with pytest.raises(MatchweekResearchError):
                    replay.seal_completed_v2(graph.f16_digest)
            assert (
                reopened.snapshot_manifest_digest_for_snapshot(completion_slot(graph.logical_id))
                is None
            )
    assert calls == []


@pytest.mark.parametrize("result", ["redirect", "wrong-media", "unavailable", "oversized", "empty"])
def test_exact_transport_has_one_attempt_no_redirect_retry_or_fallback(
    causal: Any, monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    repository, graph, calls = causal
    requests: list[tuple[str, str, bytes]] = []

    class Socket:
        def settimeout(self, seconds: float) -> None:
            assert 0 < seconds <= 30

    class Response:
        status = 302 if result == "redirect" else 200
        reads = 0

        def getheader(self, key: str, default: str = "") -> str:
            return "text/plain" if result == "wrong-media" else "application/timestamp-reply"

        def isclosed(self) -> bool:
            return False

        def read1(self, size: int) -> bytes:
            self.reads += 1
            if result == "oversized":
                return b"x" * 65536
            return b""

    class Connection:
        sock = Socket()

        def __init__(self, host: str, timeout: int) -> None:
            assert host == "timestamp.sigstore.dev" and timeout == 10

        def connect(self) -> None:
            pass

        def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
            assert method == "POST" and path == "/api/v1/timestamp"
            assert headers["Content-Type"] == "application/timestamp-query"
            requests.append((method, path, body))

        def getresponse(self) -> Response:
            if result == "unavailable":
                raise OSError("isolated source unavailable")
            return Response()

        def close(self) -> None:
            pass

    # Exercise the actual private transport with a fake socket adapter.
    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    monkeypatch.setattr("matchvet.causal_witness._post", _real_post)
    for _ in range(2):
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    assert len(requests) == 1
    assert calls == []


def test_entropy_construction_reentry_cannot_get_another_attempt(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    import secrets

    fresh = secrets.token_bytes
    invocations: list[int] = []

    def entropy(size: int) -> bytes:
        op = repository._store._research_owner
        assert op is not None
        with pytest.raises(RuntimeError):
            op._begin_witness(graph, approval())
        invocations.append(size)
        return fresh(size)

    monkeypatch.setattr("matchvet.causal_selection.secrets.token_bytes", entropy)
    repository.seal_completed_v2(graph.f16_digest)
    assert invocations == [32, 32]
    assert len(calls) == 1


def test_generic_publication_cannot_borrow_v2_receipt_authority(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, graph, calls = causal
    from matchvet.store import _ResearchOperation

    accept = _ResearchOperation._accept_witness

    def accepted(self: Any, attempt: Any, event: Any) -> None:
        accept(self, attempt, event)
        candidate = _manifest_v2(repository, graph, role="completion", created=self._upper_bound)
        with pytest.raises(ArtifactError):
            repository._artifacts.publish_manifest(candidate)
        with pytest.raises(ValueError), repository._store.transaction() as tx:
            tx.record_snapshot_manifest(
                manifest_digest="0" * 64,
                snapshot_id=completion_slot(graph.logical_id),
                matchweek_id=graph.logical_id,
                research_cutoff_id=graph.boundary_id.value,
                version_manifest_id="0" * 36,
                research_cutoff_utc=graph.cutoff,
                aggregate_sha256="0" * 64,
                completeness_state="COMPLETE",
                manifest_schema_version=1,
                created_at_utc=self._upper_bound,
                verification_state="VERIFIED",
                verified_at_utc=self._upper_bound,
                parent_snapshot_id=selection_slot(graph.logical_id),
            )

    monkeypatch.setattr(_ResearchOperation, "_accept_witness", accepted)
    repository.seal_completed_v2(graph.f16_digest)
    assert len(calls) == 1


def test_registered_canonical_versions_do_not_block_another_vacant_slot(causal: Any) -> None:
    from matchvet.causal_selection import _version_v2

    repository, graph, calls = causal
    with repository._store.transaction() as tx:
        for role in ("selection", "completion"):
            tx.add_version(
                replace(_version_v2(role), created_at_utc="2025-01-01T00:00:00.000000+00:00")
            )
    selected = repository.seal_completed_v2(graph.f16_digest)
    assert selected == repository.replay(selected.digest)
    assert len(calls) == 1


@pytest.mark.parametrize("order", ["CB01-first", "causal-first"])
def test_raw_tuf_storage_remains_compatible_with_CB01(causal: Any, order: str) -> None:
    from test_cb01_trust import _captured_trust

    from matchvet.cb01 import BootstrapRepository

    repository, graph, calls = causal
    cb = BootstrapRepository(repository._store)
    cb_trust = _captured_trust()
    if order == "CB01-first":
        cb._retain_trust(cb_trust)
    selected = repository.seal_completed_v2(graph.f16_digest)
    if order == "causal-first":
        cb._retain_trust(cb_trust)
    assert repository.replay(selected.digest) == selected
    assert len(calls) == 1


def test_advisory_receipt_timestamp_callback_cannot_reenter_acceptance(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime as RealDateTime

    repository, graph, calls = causal
    callbacks: list[str] = []

    class Advisory(RealDateTime):
        @classmethod
        def now(cls, tz: Any = None) -> Advisory:
            op = repository._store._research_owner
            if (
                op is not None
                and op._phase == "witness_attempt"
                and op._attempt is not None
                and op._attempt._event is not None
                and not callbacks
            ):
                callbacks.append("during-acceptance")
                with pytest.raises(RuntimeError):
                    op._accept_witness(op._attempt, op._attempt._event)
                with pytest.raises(RuntimeError):
                    op._start("receipt")
            return cls.fromtimestamp(RealDateTime.now(tz).timestamp(), tz)

    monkeypatch.setattr("matchvet.store.datetime", Advisory)
    repository.seal_completed_v2(graph.f16_digest)
    assert callbacks == ["during-acceptance"]
    assert len(calls) == 1


@pytest.mark.parametrize("loss", ["close", "PID"])
def test_ownership_loss_during_connect_refuses_before_request(
    causal: Any, monkeypatch: pytest.MonkeyPatch, loss: str
) -> None:
    repository, graph, _calls = causal
    requested: list[bytes] = []
    original_pid = os.getpid()

    class Socket:
        def settimeout(self, timeout: float) -> None:
            pass

    class Connection:
        sock = Socket()

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def connect(self) -> None:
            if loss == "close":
                repository._store.close()
            else:
                monkeypatch.setattr("os.getpid", lambda: original_pid + 1)

        def request(self, *args: Any, **kwargs: Any) -> None:
            requested.append(kwargs["body"])

        def getresponse(self) -> Any:
            raise OSError("isolated interrupted connection")

        def close(self) -> None:
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    monkeypatch.setattr("matchvet.causal_witness._post", _real_post)
    with pytest.raises(MatchweekResearchError):
        repository.seal_completed_v2(graph.f16_digest)
    assert requested == []


@pytest.mark.parametrize("http_version", ["HTTP/1.0", "HTTP/1.1"])
def test_closing_http_response_is_retained_exactly(
    causal: Any, monkeypatch: pytest.MonkeyPatch, http_version: str
) -> None:
    import socket
    from http.client import HTTPConnection

    repository, graph, calls = causal
    client, peer = socket.socketpair()
    body = b"isolated-signed-response"
    peer.sendall(
        f"{http_version} 200 OK\r\nContent-Type: application/timestamp-reply\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    requests: list[bytes] = []

    class Connection(HTTPConnection):
        def connect(self) -> None:
            self.sock = client

        def request(self, *args: Any, **kwargs: Any) -> None:
            requests.append(kwargs["body"])
            super().request(*args, **kwargs)

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    monkeypatch.setattr("matchvet.causal_witness._post", _real_post)
    try:
        receipt = repository.seal_completed_v2(graph.f16_digest)
        assert repository.replay(receipt.digest).digest == receipt.digest
    finally:
        client.close()
        peer.close()
    assert len(requests) == 1
    assert calls == []


def test_slow_header_reads_use_one_absolute_deadline(
    causal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    from http.client import HTTPConnection

    repository, graph, calls = causal
    elapsed = [0.0]
    requests: list[bytes] = []

    class Drip(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def readinto(self, buffer: Any) -> int:
            elapsed[0] += 5
            buffer[0] = ord("H")
            return 1

    class Socket:
        def settimeout(self, timeout: float) -> None:
            assert timeout > 0

        def sendall(self, raw: bytes) -> None:
            pass

        def makefile(self, mode: str, buffering: int = -1) -> Drip:
            return Drip()

        def close(self) -> None:
            pass

    class Connection(HTTPConnection):
        def connect(self) -> None:
            self.sock = cast(Any, Socket())

        def request(self, *args: Any, **kwargs: Any) -> None:
            requests.append(kwargs["body"])
            super().request(*args, **kwargs)

    monkeypatch.setattr("matchvet.causal_transport.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    monkeypatch.setattr("matchvet.causal_witness._post", _real_post)
    for _ in range(2):
        with pytest.raises(MatchweekResearchError):
            repository.seal_completed_v2(graph.f16_digest)
    assert elapsed[0] == 30
    assert len(requests) == 1
    assert calls == []


def test_competing_processes_can_request_for_only_one_graph(causal: Any) -> None:
    import multiprocessing

    repository, graph, calls = causal
    other = synthetic_graph(repository._store, salt="competing")
    path = repository._store.path
    repository._store.close()
    context = multiprocessing.get_context("fork")
    gate = context.Event()
    results = context.Queue()
    marker = path.parent / "competition-requests"

    def compete(candidate: _CausalGraph) -> None:
        gate.wait(10)
        try:
            with open_store(path, private_root=path.parent) as live:
                patches = pytest.MonkeyPatch()
                install_admission(patches, candidate)

                def post(attempt: _WitnessAttempt) -> bytes:
                    attempt._start_transport()
                    with marker.open("ab") as output:
                        output.write(b"1")
                    return b"isolated-signed-response"

                patches.setattr("matchvet.causal_witness._post", post)
                MatchweekResearchRepository(live).seal_completed_v2(candidate.f16_digest)
                results.put(("qualified", candidate.f16_digest))
        except Exception:
            results.put(("refused", candidate.f16_digest))

    processes = [context.Process(target=compete, args=(candidate,)) for candidate in (graph, other)]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(30)
        if process.is_alive():
            process.kill()
            process.join()
            pytest.fail("Isolated competing operation exceeded deadline")
        assert process.exitcode == 0
    outcomes = [results.get(timeout=2) for _ in processes]
    assert sorted(state for state, _ in outcomes) == ["qualified", "refused"]
    assert marker.read_bytes() == b"1"
    assert calls == []

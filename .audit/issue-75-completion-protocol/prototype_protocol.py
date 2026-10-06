"""THROWAWAY protocol proof. Synthetic graphs, temporary stores; no production owner.

Run: PYTHONPATH=src python .audit/issue-75-completion-protocol/prototype_protocol.py
Guard and attack hooks model a FUTURE API contract; base ArtifactStore lacks the guard.
Virtual time proves ordering branches, not clock accuracy or hardware power-loss safety.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from matchvet.artifacts import (
    ArtifactError,
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestVersion,
    SnapshotManifest,
)
from matchvet.store import CanonicalIdentifier, StoreBusyError, VersionIdentity, open_store

ROOT = Path(__file__).resolve().parent
BASE = datetime(2026, 9, 25, 12, tzinfo=UTC)
T = (BASE + timedelta(seconds=100)).isoformat(timespec="microseconds")
SEASON = "2026-27"
FRIDAY = "2026-09-25"


def stamp(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def identity(kind, number):
    return CanonicalIdentifier(kind, f"00000000-0000-7000-8000-{number:012d}")


def logical_matchweek(season, friday):
    return CanonicalIdentifier(
        "matchweek",
        str(uuid5(NAMESPACE_URL, f"matchvet:logical-matchweek:{season}:{friday}")),
    )


def role_slots(matchweek_id):
    if matchweek_id.kind != "matchweek":
        raise Refusal("role slots require a logical Matchweek identity")
    selection = uuid5(
        NAMESPACE_URL,
        f"matchvet:matchweek-research-selection:{matchweek_id.value}",
    )
    receipt = uuid5(
        NAMESPACE_URL,
        f"matchvet:matchweek-research-completion:{matchweek_id.value}",
    )
    return (
        CanonicalIdentifier("snapshot_manifest", str(selection)),
        CanonicalIdentifier("snapshot_manifest", str(receipt)),
    )


MATCHWEEK = logical_matchweek(SEASON, FRIDAY)
SELECT, RECEIPT = role_slots(MATCHWEEK)
VERSION = VersionIdentity(
    identity("version", 8),
    identity("version_definition", 9),
    "completion_protocol",
    "synthetic-postcommit-v1",
    hashlib.sha256(b"synthetic-postcommit-v1").hexdigest(),
    1,
    stamp(80),
)


class Refusal(Exception):
    pass


class Clock:
    def __init__(self):
        self.wall, self.elapsed = 90, 0

    def advance(self):
        self.wall, self.elapsed = 110, 20

    def observe(self):
        # An assumed trustworthy initial UTC upper bound plus suspend-inclusive
        # elapsed time prevents backwards wall-clock steps from extending T.
        return stamp(max(self.wall, 90 + self.elapsed))


class GuardedArtifacts(ArtifactStore):
    """Synthetic derived-slot guard and private fresh-operation publication path."""

    def __init__(self, store, clock, mode):
        super().__init__(store)
        self.clock, self.mode, self.role = clock, mode, None
        self.reentrant_callback = None
        self.reentrant_checked = False
        self.synced_roles = {}
        self.publication_attempts = {"selection": 0, "receipt": 0}
        self.commit_attempts = {"selection": 0, "receipt": 0}
        self.reconciliation_reads = 0

    def publish_manifest(self, manifest, **kwargs):
        if manifest.snapshot_id in role_slots(manifest.matchweek_id):
            raise Refusal("reserved slot requires live owner operation")
        return super().publish_manifest(manifest, **kwargs)

    def _publish_object(self, content, record):
        super()._publish_object(content, record)
        if self.role is not None:
            if self.mode == "fsync_failure":
                raise OSError("synthetic protocol object durability barrier failure")
            path = self.store.path.parent / record.relative_path
            sync_file_and_parents(path, self.store.path.parent)
            self.synced_roles[self.role] = record.digest
        if (
            self.role == "selection"
            and self.reentrant_callback is not None
            and not self.reentrant_checked
        ):
            self.reentrant_checked = True
            self.reentrant_callback()
        if self.mode == f"{self.role}_object_crash":
            os._exit(37)

    def begin_operation(self, operation):
        state = (self, operation, os.getpid(), self.store)
        if getattr(self.store, "_issue75_completion_operation", None) is not None:
            raise Refusal("completion operation is already active for this Store")
        self.store._issue75_completion_operation = state
        return state

    def end_operation(self, operation, owner_store):
        state = getattr(owner_store, "_issue75_completion_operation", None)
        if state is not None and state[:2] == (self, operation):
            del owner_store._issue75_completion_operation

    def operation_is_live(self, operation, owner_store):
        return (
            getattr(owner_store, "_issue75_completion_operation", None)
            == (self, operation, os.getpid(), owner_store)
            and self.store is owner_store
            and not owner_store._closed
        )

    def _owned_publish(self, manifest, role, operation, owner_store):
        if not self.operation_is_live(operation, owner_store):
            raise Refusal("private publication operation is unavailable")
        if self.role is not None:
            raise Refusal("nested protected publication is forbidden")
        expected = {
            "selection": role_slots(manifest.matchweek_id)[0],
            "receipt": role_slots(manifest.matchweek_id)[1],
        }
        if role not in expected or manifest.snapshot_id != expected[role]:
            raise Refusal("protected publication role or manifest mapping is invalid")
        self.publication_attempts[role] += 1
        self.synced_roles.pop(role, None)
        self.role = role
        try:
            return ArtifactStore.publish_manifest(self, manifest)
        finally:
            self.role = None


def reference(record):
    return ManifestArtifact(
        record.artifact_id, record.digest, record.media_type, record.byte_length
    )


def sync_file_and_parents(path, boundary):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    directory = path.parent
    while True:
        if directory != boundary and boundary not in directory.parents:
            raise AssertionError("protocol object escaped the private store boundary")
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if directory == boundary:
            break
        directory = directory.parent


def flush_graph(artifacts):
    for record in artifacts.store.artifact_catalog():
        path = artifacts.store.path.parent / record.relative_path
        sync_file_and_parents(path, artifacts.store.path.parent)


def replay(artifacts):
    store = artifacts.store
    selection_digest = store.snapshot_manifest_digest_for_snapshot(SELECT.value)
    receipt_digest = store.snapshot_manifest_digest_for_snapshot(RECEIPT.value)
    if selection_digest is None or receipt_digest is None:
        raise Refusal("missing indexed selection or receipt; never backfill")
    selection = artifacts.verify_manifest(selection_digest)
    receipt = artifacts.verify_manifest(receipt_digest)
    selected_record = artifacts.verify_artifact(selection_digest)
    dependency_digest = hashlib.sha256(b"synthetic candidate dependency").hexdigest()
    if (
        selection.snapshot_id != SELECT
        or selection.parent_snapshot_id is not None
        or selection.matchweek_id != MATCHWEEK
        or selection.research_cutoff_id != identity("research_cutoff", 5)
        or selection.version_manifest_id != identity("version_manifest", 6)
        or selection.research_cutoff_utc != T
        or selection.created_at_utc >= T
        or selection.versions != (ManifestVersion.from_identity(VERSION),)
        or selection.artifacts != (reference(artifacts.verify_artifact(dependency_digest)),)
        or selection.completeness != ManifestCompleteness("COMPLETE")
        or selection.retention_omissions
    ):
        raise Refusal("synthetic selection binding invalid")
    if (
        receipt.snapshot_id != RECEIPT
        or receipt.parent_snapshot_id != SELECT
        or receipt.artifacts != (reference(selected_record),)
        or receipt.matchweek_id != selection.matchweek_id
        or receipt.research_cutoff_id != selection.research_cutoff_id
        or receipt.version_manifest_id != selection.version_manifest_id
        or receipt.research_cutoff_utc != selection.research_cutoff_utc
        or receipt.research_cutoff_utc != T
        or receipt.created_at_utc >= T
        or receipt.versions != (ManifestVersion.from_identity(VERSION),)
        or receipt.completeness != ManifestCompleteness("COMPLETE")
        or receipt.retention_omissions
    ):
        raise Refusal("receipt binding invalid")
    for dependency in selection.artifacts:
        artifacts.verify_artifact(dependency.digest)
    return receipt


def seal(artifacts, candidate, attack=None):
    store, clock = artifacts.store, artifacts.clock
    owner_pid, owner_store, operation = os.getpid(), store, object()
    artifacts.begin_operation(operation)
    live, used = True, False
    try:
        existing_digest = store.snapshot_manifest_digest_for_snapshot(SELECT.value)
        if existing_digest is not None:
            existing = artifacts.verify_manifest(existing_digest)
            if (
                replace(existing, verification_state="UNVERIFIED", verified_at_utc=None)
                != candidate
            ):
                raise Refusal("proposal differs from existing immutable assignment")
            return replay(artifacts)  # Never mint from an existing row.
        if clock.observe() >= T:
            raise Refusal("deadline already reached")
        flush_graph(artifacts)
        selected = artifacts._owned_publish(candidate, "selection", operation, owner_store)
        if artifacts.mode in {"pause_before_sample", "forward_clock"}:
            clock.advance()
            if artifacts.mode == "forward_clock":
                clock.elapsed = 0  # Conservative false refusal after a forward step.
        observed = clock.observe()
        if artifacts.mode == "sample_crash":
            os._exit(37)
        if observed >= T:
            raise Refusal("completion observation is not strictly before T")

        def consume(token_operation):
            nonlocal used
            if (
                not live
                or used
                or token_operation is not operation
                or os.getpid() != owner_pid
                or not artifacts.operation_is_live(operation, owner_store)
            ):
                raise Refusal("completion capability unavailable")
            used = True  # Burn before persistence, including an uncertain failure.
            receipt = replace(
                candidate,
                snapshot_id=RECEIPT,
                parent_snapshot_id=SELECT,
                artifacts=(reference(selected),),
                created_at_utc=observed,
                versions=(ManifestVersion.from_identity(VERSION),),
            )
            try:
                artifacts._owned_publish(receipt, "receipt", operation, owner_store)
            except ArtifactError as publication_error:
                artifacts.reconciliation_reads += 1
                try:
                    return replay(artifacts)
                except ArtifactError, Refusal, ValueError, sqlite3.DatabaseError:
                    raise Refusal(
                        "receipt publication failed ambiguously without valid indexed evidence"
                    ) from publication_error
            return replay(artifacts)

        if artifacts.mode in {
            "pause_after_sample",
            "receipt_late",
            "receipt_late_commit_crash",
            "receipt_late_commit_error_after",
        }:
            clock.advance()
        if attack is not None:
            attack(consume, operation)
        result = consume(operation)
        try:
            consume(operation)
        except Refusal:
            pass
        else:
            raise AssertionError("duplicate capability accepted")
        return result
    finally:
        live = False
        artifacts.end_operation(operation, owner_store)


def candidate_for(artifacts):
    stored_version = artifacts.store.version(VERSION.identifier)
    if stored_version is None:
        with artifacts.store.transaction() as transaction:
            transaction.add_version(VERSION)
    elif stored_version != VERSION:
        raise AssertionError("stored completion protocol version changed")
    dependency = artifacts.publish_artifact(b"synthetic candidate dependency", "text/plain")
    return SnapshotManifest(
        SELECT,
        MATCHWEEK,
        identity("research_cutoff", 5),
        identity("version_manifest", 6),
        T,
        (reference(dependency),),
        (ManifestVersion.from_identity(VERSION),),
        (),
        ManifestCompleteness("COMPLETE"),
        stamp(80),
    )


def child(path, mode):
    clock, active = Clock(), [None]
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def commit(self):
            artifacts = active[0]
            role = artifacts.role if artifacts else None
            if role is not None:
                artifacts.commit_attempts[role] += 1
                assert role in artifacts.synced_roles, f"{role} commit preceded object fsync"
            if role == "selection" and mode in {"equal", "late", "rollback"}:
                clock.advance()
                if mode == "equal":
                    clock.wall, clock.elapsed = 100, 10
                if mode == "rollback":
                    clock.wall = 70
            if role == "receipt" and mode == "receipt_transaction_crash":
                os._exit(37)
            if mode == f"{role}_commit_error_before":
                raise sqlite3.OperationalError(f"synthetic {role} error before commit")
            super().commit()
            if mode == f"{role}_commit_error_after" or (
                role == "receipt" and mode == "receipt_late_commit_error_after"
            ):
                raise sqlite3.OperationalError(f"synthetic {role} error after commit")
            if mode == f"{role}_commit_crash" or (
                role == "receipt" and mode == "receipt_late_commit_crash"
            ):
                os._exit(37)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=Connection)

    with (
        patch("sqlite3.connect", side_effect=connect),
        patch("matchvet.artifacts._utc_now", side_effect=lambda: stamp(clock.wall)),
        open_store(path / "store.sqlite3", private_root=path) as store,
    ):
        artifacts = GuardedArtifacts(store, clock, mode)
        active[0] = artifacts
        candidate = candidate_for(artifacts)
        checks = []
        try:
            artifacts.publish_manifest(candidate)
        except Refusal:
            checks.append("generic publication into derived selection slot refused")
        else:
            raise AssertionError("unguarded generic selection")

        if mode == "reentrant_callback":

            def reentrant_callback():
                try:
                    seal(artifacts, candidate)
                except Refusal:
                    checks.append("reentrant Store operation refused")
                else:
                    raise AssertionError("reentrant Store operation accepted")
                try:
                    artifacts.publish_manifest(candidate)
                except Refusal:
                    checks.append("reentrant public reserved publication refused")
                else:
                    raise AssertionError("reentrant public reserved publication accepted")

            artifacts.reentrant_callback = reentrant_callback

        def attacks(consume, operation):
            if mode == "reopen_after_sample":
                store.close()
                with open_store(path / "store.sqlite3", private_root=path) as reopened:
                    artifacts.store = reopened
                    try:
                        consume(operation)
                    except Refusal:
                        checks.append("same-process reopened Store invalidates capability")
                    else:
                        raise AssertionError("capability survived Store reopen")
                raise Refusal("operation owner closed")
            try:
                consume(object())
            except Refusal:
                checks.append("copied/reconstructed operation identity refused")
            else:
                raise AssertionError("copied capability accepted")
            forked = os.fork()
            if forked == 0:
                try:
                    consume(operation)
                except Refusal:
                    os._exit(0)
                os._exit(71)
            assert os.waitpid(forked, 0)[1] == 0
            checks.append("fork capability refused")

        try:
            receipt = seal(
                artifacts,
                candidate,
                attacks if mode in {"early", "reopen_after_sample"} else None,
            )
            assert receipt.created_at_utc < T
            assert seal(artifacts, candidate) == receipt
            for change in (
                {"research_cutoff_id": identity("research_cutoff", 55)},
                {"artifacts": ()},
                {"version_manifest_id": identity("version_manifest", 66)},
            ):
                try:
                    seal(artifacts, replace(candidate, **change))
                except Refusal:
                    assert replay(artifacts) == receipt
                else:
                    raise AssertionError("alternate proposal accepted")
            checks.append("changed cutoff/dependencies/profile-version rejected; original replays")
            result = "qualified"
        except ArtifactError, Refusal, OSError:
            result = "refused"
        if "commit_error" in mode:
            checks.append(
                "attempts "
                f"selection={artifacts.publication_attempts['selection']} "
                f"receipt={artifacts.publication_attempts['receipt']} "
                f"reconciliation_reads={artifacts.reconciliation_reads}"
            )
        print(
            json.dumps(
                {
                    "operation": result,
                    "checks": checks,
                    "publication_attempts": artifacts.publication_attempts,
                    "commit_attempts": artifacts.commit_attempts,
                    "reconciliation_reads": artifacts.reconciliation_reads,
                }
            ),
            flush=True,
        )


def expect_refusal(artifacts):
    try:
        replay(artifacts)
    except Refusal, ArtifactError, ValueError, sqlite3.DatabaseError:
        return
    raise AssertionError("invalid state qualified")


def run():
    results = []
    modes = [
        "early",
        "receipt_late",
        "equal",
        "late",
        "rollback",
        "forward_clock",
        "reopen_after_sample",
        "pause_before_sample",
        "pause_after_sample",
        "selection_object_crash",
        "selection_commit_crash",
        "sample_crash",
        "receipt_object_crash",
        "receipt_transaction_crash",
        "receipt_commit_crash",
        "receipt_late_commit_crash",
        "selection_commit_error_before",
        "selection_commit_error_after",
        "receipt_commit_error_before",
        "receipt_commit_error_after",
        "receipt_late_commit_error_after",
        "reentrant_callback",
        "fsync_failure",
    ]
    accepted = {
        "early",
        "receipt_late",
        "pause_after_sample",
        "receipt_commit_crash",
        "receipt_late_commit_crash",
        "receipt_commit_error_after",
        "receipt_late_commit_error_after",
        "reentrant_callback",
    }
    with tempfile.TemporaryDirectory(
        prefix="PROTOTYPE-issue75-", dir=Path.home() / "tmp"
    ) as temporary:
        for mode in modes:
            path = Path(temporary) / mode
            path.mkdir()
            process = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), str(path), mode],
                capture_output=True,
                text=True,
                check=False,
            )
            assert process.returncode == (37 if mode.endswith("crash") else 0), process.stderr
            with open_store(path / "store.sqlite3", private_root=path) as store:
                artifacts = GuardedArtifacts(store, Clock(), mode)
                if mode in accepted:
                    receipt = replay(artifacts)
                    assert receipt.created_at_utc == stamp(90)
                    if mode in {
                        "receipt_late",
                        "pause_after_sample",
                        "receipt_late_commit_crash",
                        "receipt_late_commit_error_after",
                    }:
                        assert receipt.verified_at_utc >= T
                else:
                    expect_refusal(artifacts)
                    if store.snapshot_manifest_digest_for_snapshot(SELECT.value):
                        # Existing identical selection cannot mint on same/new process reopen.
                        existing = artifacts.verify_manifest(
                            store.snapshot_manifest_digest_for_snapshot(SELECT.value)
                        )
                        try:
                            seal(
                                artifacts,
                                replace(
                                    existing, verification_state="UNVERIFIED", verified_at_utc=None
                                ),
                            )
                        except Refusal:
                            pass
                        else:
                            raise AssertionError("missing receipt backfilled")
                if mode == "early":
                    contender = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()), str(path), "lock"],
                        capture_output=True,
                        text=True,
                    )
                    assert contender.returncode == 0, contender.stderr
                    results.append({"case": "competing_process_writer", "result": "refused"})
                    try:
                        open_store(path / "store.sqlite3", private_root=path)
                    except StoreBusyError:
                        results.append(
                            {"case": "competing_store_same_process", "result": "refused"}
                        )
                    else:
                        raise AssertionError("competing Store acquired writer lock")
                results.append(
                    {
                        "case": mode,
                        "restart": "qualified" if mode in accepted else "refused",
                        "process_exit": process.returncode,
                        "live": json.loads(process.stdout) if process.stdout else "crashed",
                    }
                )
                if "commit_error" in mode:
                    live_result = json.loads(process.stdout)
                    assert live_result["publication_attempts"]["selection"] == 1
                    assert live_result["commit_attempts"]["selection"] == 1
                    if mode.startswith("selection_"):
                        assert live_result["publication_attempts"]["receipt"] == 0
                        assert live_result["reconciliation_reads"] == 0
                    else:
                        assert live_result["publication_attempts"]["receipt"] == 1
                        assert live_result["commit_attempts"]["receipt"] == 1
                        assert live_result["reconciliation_reads"] == 1
            # Same-process reopen has no capability and cannot backfill the absent row.
            if mode == "sample_crash":
                with open_store(path / "store.sqlite3", private_root=path) as store:
                    expect_refusal(GuardedArtifacts(store, Clock(), mode))
                results.append({"case": "same_process_reopen_missing_receipt", "result": "refused"})

        equality_path = Path(temporary) / "never-selected-at-equality"
        equality_path.mkdir()
        equality_clock = Clock()
        equality_clock.wall, equality_clock.elapsed = 100, 10
        with open_store(equality_path / "store.sqlite3", private_root=equality_path) as store:
            artifacts = GuardedArtifacts(store, equality_clock, "initial_equality")
            candidate = candidate_for(artifacts)
            try:
                seal(artifacts, candidate)
            except Refusal:
                pass
            else:
                raise AssertionError("never-selected candidate published at cutoff equality")
            assert artifacts.publication_attempts == {"selection": 0, "receipt": 0}
            assert store.snapshot_manifest_digest_for_snapshot(SELECT.value) is None
            assert store.snapshot_manifest_digest_for_snapshot(RECEIPT.value) is None
        results.append(
            {
                "case": "never_selected_candidate_at_cutoff_equality",
                "result": "refused with zero slot publication attempts and empty indices",
            }
        )

        late_orphan_path = Path(temporary) / "selection-object-late-retry"
        shutil.copytree(Path(temporary) / "selection_object_crash", late_orphan_path)
        late_clock = Clock()
        late_clock.advance()
        with open_store(late_orphan_path / "store.sqlite3", private_root=late_orphan_path) as store:
            artifacts = GuardedArtifacts(store, late_clock, "orphan_late_retry")
            candidate = candidate_for(artifacts)
            expected = replace(
                candidate,
                verification_state="VERIFIED",
                verified_at_utc=stamp(90),
            )
            assert artifacts._object_path(expected.digest).exists()
            assert store.artifact_metadata(expected.digest) is None
            try:
                seal(artifacts, candidate)
            except Refusal:
                pass
            else:
                raise AssertionError("unindexed orphan selection retried after cutoff")
            assert artifacts.publication_attempts == {"selection": 0, "receipt": 0}
            assert store.snapshot_manifest_digest_for_snapshot(SELECT.value) is None
            assert store.snapshot_manifest_digest_for_snapshot(RECEIPT.value) is None
        results.append(
            {
                "case": "unindexed_orphan_selection_retry_after_cutoff",
                "result": "refused with zero slot publication attempts and empty indices",
            }
        )

        retry_path = Path(temporary) / "selection-object-fresh-retry"
        shutil.copytree(Path(temporary) / "selection_object_crash", retry_path)
        with open_store(retry_path / "store.sqlite3", private_root=retry_path) as store:
            artifacts = GuardedArtifacts(store, Clock(), "orphan_retry")
            candidate = candidate_for(artifacts)
            expected = replace(
                candidate,
                verification_state="VERIFIED",
                verified_at_utc=stamp(90),
            )
            orphan_path = artifacts._object_path(expected.digest)
            assert orphan_path.exists()
            assert store.artifact_metadata(expected.digest) is None
        retry_process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(retry_path), "orphan_retry"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert retry_process.returncode == 0, retry_process.stderr
        retry_live = json.loads(retry_process.stdout)
        assert retry_live["operation"] == "qualified"
        assert retry_live["commit_attempts"] == {"selection": 1, "receipt": 1}
        with open_store(retry_path / "store.sqlite3", private_root=retry_path) as store:
            assert replay(GuardedArtifacts(store, Clock(), "orphan_retry"))
        results.append(
            {
                "case": "orphan_selection_object_fresh_retry",
                "result": "qualified after exact reused object synced before commit",
                "live": retry_live,
            }
        )

        poison_path = Path(temporary) / "forged-matchweek-receipt-poison"
        shutil.copytree(Path(temporary) / "sample_crash", poison_path)
        with open_store(poison_path / "store.sqlite3", private_root=poison_path) as store:
            artifacts = GuardedArtifacts(store, Clock(), "wrong_matchweek_poison")
            selected = artifacts.verify_manifest(
                store.snapshot_manifest_digest_for_snapshot(SELECT.value)
            )
            record = artifacts.verify_artifact(selected.digest)
            wrong_matchweek = logical_matchweek("2026-27", "2026-10-02")
            forged = replace(
                selected,
                snapshot_id=RECEIPT,
                matchweek_id=wrong_matchweek,
                parent_snapshot_id=SELECT,
                artifacts=(reference(record),),
                created_at_utc=stamp(90),
                verification_state="UNVERIFIED",
                verified_at_utc=None,
            )
            poisoned = artifacts.publish_manifest(forged)
            assert store.snapshot_manifest_digest_for_snapshot(RECEIPT.value) == poisoned.digest
            expect_refusal(artifacts)
        results.append(
            {
                "case": "forged_matchweek_public_poison_real_receipt_slot",
                "result": "guard allowed invalid mapping; domain replay refused permanently",
            }
        )

        # Privileged base-API writes deliberately bypass the modeled future guard.
        # These are valid generic manifests whose domain binding must still fail.
        variants = (
            "parent",
            "digest",
            "matchweek",
            "policy",
            "cutoff",
            "protocol",
            "profile",
            "incomplete",
        )
        for variant in variants:
            path = Path(temporary) / f"wrong-receipt-{variant}"
            shutil.copytree(Path(temporary) / "sample_crash", path)
            with open_store(path / "store.sqlite3", private_root=path) as store:
                artifacts = GuardedArtifacts(store, Clock(), "wrong")
                selected = artifacts.verify_manifest(
                    store.snapshot_manifest_digest_for_snapshot(SELECT.value)
                )
                record = artifacts.verify_artifact(selected.digest)
                receipt = replace(
                    selected,
                    snapshot_id=RECEIPT,
                    parent_snapshot_id=SELECT,
                    artifacts=(reference(record),),
                    created_at_utc=stamp(90),
                    verification_state="UNVERIFIED",
                    verified_at_utc=None,
                )
                changes = {
                    "parent": {"parent_snapshot_id": identity("snapshot_manifest", 77)},
                    "digest": {"artifacts": selected.artifacts},
                    "matchweek": {"matchweek_id": identity("matchweek", 44)},
                    "policy": {"research_cutoff_id": identity("research_cutoff", 55)},
                    "cutoff": {"research_cutoff_utc": stamp(120)},
                    "protocol": {"versions": ()},
                    "profile": {"version_manifest_id": identity("version_manifest", 66)},
                    "incomplete": {
                        "completeness": ManifestCompleteness("INCOMPLETE", ("dependency",))
                    },
                }
                invalid = ArtifactStore.publish_manifest(
                    artifacts, replace(receipt, **changes[variant])
                )
                artifacts.verify_manifest(invalid.digest)  # Valid generic bytes/index.
                expect_refusal(artifacts)
            results.append(
                {"case": f"generic_valid_wrong_receipt_{variant}", "result": "domain refused"}
            )
        for variant in ("incomplete", "matchweek", "protocol"):
            path = Path(temporary) / f"wrong-selection-{variant}"
            shutil.copytree(Path(temporary) / "selection_object_crash", path)
            with open_store(path / "store.sqlite3", private_root=path) as store:
                artifacts = GuardedArtifacts(store, Clock(), "wrong")
                dependency = artifacts.verify_artifact(
                    hashlib.sha256(b"synthetic candidate dependency").hexdigest()
                )
                candidate = SnapshotManifest(
                    SELECT,
                    MATCHWEEK,
                    identity("research_cutoff", 5),
                    identity("version_manifest", 6),
                    T,
                    (reference(dependency),),
                    (ManifestVersion.from_identity(VERSION),),
                    (),
                    ManifestCompleteness("COMPLETE"),
                    stamp(80),
                )
                change = {
                    "incomplete": {
                        "completeness": ManifestCompleteness("INCOMPLETE", ("dependency",))
                    },
                    "matchweek": {"matchweek_id": identity("matchweek", 44)},
                    "protocol": {"versions": ()},
                }[variant]
                candidate = replace(candidate, **change)
                selected = ArtifactStore.publish_manifest(artifacts, candidate)
                receipt = replace(
                    candidate,
                    snapshot_id=RECEIPT,
                    parent_snapshot_id=SELECT,
                    artifacts=(reference(selected),),
                    created_at_utc=stamp(90),
                    completeness=ManifestCompleteness("COMPLETE"),
                    versions=(ManifestVersion.from_identity(VERSION),),
                )
                ArtifactStore.publish_manifest(artifacts, receipt)
                expect_refusal(artifacts)
            results.append(
                {"case": f"generic_valid_wrong_selection_{variant}", "result": "domain refused"}
            )
        # Corrupt/delete distinct retained objects on separate already-successful stores.
        for ordinal, (label, target, action) in enumerate(
            (label, target, action)
            for label, target in (("selection", SELECT), ("receipt", RECEIPT), ("dependency", None))
            for action in ("corrupt", "delete")
        ):
            mode = "tamper"
            path = Path(temporary) / f"tamper-{ordinal}"
            shutil.copytree(Path(temporary) / "early", path)
            with open_store(path / "store.sqlite3", private_root=path) as store:
                artifacts = GuardedArtifacts(store, Clock(), mode)
                digest = store.snapshot_manifest_digest_for_snapshot((target or SELECT).value)
                if target is None:
                    digest = artifacts.verify_manifest(digest).artifacts[0].digest
                record = store.artifact_metadata(digest)
                object_path = path / record.relative_path
                if action == "delete":
                    object_path.unlink()
                else:
                    object_path.write_bytes(b"CORRUPT PROTOTYPE BYTES")
                expect_refusal(artifacts)
            with open_store(path / "store.sqlite3", private_root=path) as store:
                assert store.status.mode.value == "READ_ONLY_RECOVERY"
                expect_refusal(GuardedArtifacts(store, Clock(), mode))
            results.append(
                {
                    "case": f"{label}_{action}",
                    "result": "refused in process and recovery",
                }
            )
    report = {
        "prototype": "THROWAWAY synthetic manifests; future guard contract",
        "cases": results,
        "all_assertions_passed": True,
        "clock": {
            "raw_rollback_counterexample": "wall=70<T while real elapsed upper bound=110>=T",
            "conservative_bound": (
                "max(wall UTC upper bound, initial UTC upper bound + suspend-inclusive elapsed)"
            ),
            "assumptions": (
                "trusted initial UTC upper bound; trusted elapsed source across suspend; "
                "no VM/process-memory rollback"
            ),
        },
        "limits": [
            "No full F16 lineage or production module integration",
            "os._exit proves process-crash recovery, not hardware power-loss durability",
            "Derived-slot guard remains bypassable by explicitly trusted private Python/raw SQL",
            "Synthetic clocks assume a trusted absolute UTC upper bound and elapsed source",
            "No migration or production module changed; no network or live stores",
        ],
    }
    case_count = len(results)
    report_text = json.dumps(report, indent=2) + "\n"
    summary = json.dumps({"cases": case_count, "all_assertions_passed": True})
    (ROOT / "proof-results.json").write_text(report_text)
    (ROOT / f"proof-results-{case_count}.json").write_text(report_text)
    (ROOT / f"proof-run-{case_count}.txt").write_text(summary + "\n")
    print(summary)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[2] == "lock":
        try:
            open_store(Path(sys.argv[1]) / "store.sqlite3", private_root=Path(sys.argv[1]))
        except StoreBusyError:
            sys.exit(0)
        sys.exit(72)
    elif len(sys.argv) == 3:
        child(Path(sys.argv[1]), sys.argv[2])
    else:
        run()

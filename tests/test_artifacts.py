from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from matchvet.artifacts import (
    ArtifactError,
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestError,
    ManifestVersion,
    RetentionOmission,
    SnapshotManifest,
)
from matchvet.store import CanonicalIdentifier, VersionIdentity, open_store


def _identifier(kind: str, value: str) -> CanonicalIdentifier:
    return CanonicalIdentifier(kind=kind, value=value)


def _version() -> VersionIdentity:
    return VersionIdentity(
        identifier=_identifier("version", "00000000-0000-7000-8000-000000000001"),
        definition_id=_identifier("version_definition", "00000000-0000-7000-8000-000000000002"),
        kind="feature_rules",
        name="v1",
        content_sha256="1" * 64,
        canonical_contract_version=1,
        created_at_utc="2026-09-13T00:00:00.000000+00:00",
    )


def _manifest(artifact: ManifestArtifact, version: VersionIdentity) -> SnapshotManifest:
    return SnapshotManifest(
        snapshot_id=_identifier("snapshot_manifest", "00000000-0000-7000-8000-000000000003"),
        matchweek_id=_identifier("matchweek", "00000000-0000-7000-8000-000000000004"),
        research_cutoff_id=_identifier("research_cutoff", "00000000-0000-7000-8000-000000000005"),
        version_manifest_id=_identifier("version_manifest", "00000000-0000-7000-8000-000000000006"),
        research_cutoff_utc="2026-09-13T06:00:00.000000+00:00",
        artifacts=(artifact,),
        versions=(ManifestVersion.from_identity(version),),
        retention_omissions=(RetentionOmission("source:private", "rights-restricted"),),
        completeness=ManifestCompleteness("COMPLETE"),
        created_at_utc="2026-09-13T06:01:00.000000+00:00",
    )


def test_publish_read_and_verify_artifact(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        record = artifacts.publish_artifact(b"hello MatchVet", "text/plain")

        assert record.digest == hashlib.sha256(b"hello MatchVet").hexdigest()
        assert record.media_type == "text/plain"
        assert record.byte_length == len(b"hello MatchVet")
        assert record.artifact_id.kind == "artifact"
        assert record.artifact_id.value != record.digest
        assert artifacts.read_artifact(record.digest) == b"hello MatchVet"
        assert artifacts.verify_artifact(record.digest) == record


def test_identical_content_deduplicates_and_changed_content_gets_new_digest(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        first = artifacts.publish_artifact(b"same", "text/plain")
        duplicate = artifacts.publish_artifact(b"same", "text/plain")
        changed = artifacts.publish_artifact(b"different", "text/plain")

        assert duplicate == first
        assert changed.digest != first.digest
        objects = sorted(
            path for path in (private_root / "objects" / "sha256").rglob("*") if path.is_file()
        )
        assert [path.name for path in objects] == sorted((first.digest, changed.digest))


def test_existing_content_addressed_object_cannot_be_overwritten_or_mutated(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        record = artifacts.publish_artifact(b"immutable", "text/plain")
        path = private_root / record.relative_path
        path.write_bytes(b"tampered")

        with pytest.raises(ArtifactError) as failed:
            artifacts.verify_artifact(record.digest)
        assert failed.value.code == "MV-ARTIFACT-DIGEST_MISMATCH"

        with pytest.raises(ArtifactError) as republish_failed:
            artifacts.publish_artifact(b"immutable", "text/plain")
        assert republish_failed.value.code == "MV-ARTIFACT-DIGEST_MISMATCH"
        assert path.read_bytes() == b"tampered"


def test_private_artifact_root_symlink_is_rejected_without_writing_outside_store(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    outside = tmp_path / "outside"
    private_root.mkdir()
    outside.mkdir()
    (private_root / "objects").symlink_to(outside, target_is_directory=True)

    store = open_store(private_root / "matchvet.sqlite3", private_root=private_root)
    try:
        with pytest.raises(ArtifactError) as failed:
            ArtifactStore(store).publish_artifact(b"must stay private")
    finally:
        store.close()

    assert failed.value.code == "MV-ARTIFACT-PATH_MISMATCH"
    assert list(outside.iterdir()) == []


def test_catalogued_digest_path_mismatch_is_rejected(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        record = artifacts.publish_artifact(b"path", "text/plain")
        connection = sqlite3.connect(database_path)
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name = 'artifacts_no_update'"
        ).fetchone()
        assert trigger_sql is not None
        connection.execute("DROP TRIGGER artifacts_no_update")
        connection.execute(
            "UPDATE artifacts SET relative_path = 'objects/sha256/00/wrong' WHERE digest = ?",
            (record.digest,),
        )
        connection.execute(str(trigger_sql[0]))
        connection.commit()
        connection.close()

        with pytest.raises(ArtifactError) as failed:
            artifacts.verify_artifact(record.digest)
        assert failed.value.code == "MV-ARTIFACT-PATH_MISMATCH"
        assert record.digest in artifacts.inspect().corrupt


def test_expected_digest_mismatch_writes_no_object_or_catalog_row(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        wrong_digest = "0" * 64
        with pytest.raises(ArtifactError) as failed:
            artifacts.publish_artifact(b"content", expected_digest=wrong_digest)
        assert failed.value.code == "MV-ARTIFACT-DIGEST_MISMATCH"
        assert artifacts.inspect().missing == ()
        assert artifacts.inspect().orphans == ()

    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT count(*) FROM artifacts").fetchone() == (0,)
    connection.close()


def test_missing_and_corrupt_objects_are_rejected_and_reported(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        missing = artifacts.publish_artifact(b"missing", "text/plain")
        (private_root / missing.relative_path).unlink()
        with pytest.raises(ArtifactError) as missing_error:
            artifacts.verify_artifact(missing.digest)
        assert missing_error.value.code == "MV-ARTIFACT-MISSING"
        assert missing.digest in artifacts.inspect().missing

        corrupt = artifacts.publish_artifact(b"corrupt", "text/plain")
        (private_root / corrupt.relative_path).write_bytes(b"changed")
        with pytest.raises(ArtifactError) as corrupt_error:
            artifacts.verify_artifact(corrupt.digest)
        assert corrupt_error.value.code == "MV-ARTIFACT-DIGEST_MISMATCH"
        assert corrupt.digest in artifacts.inspect().corrupt


def test_reopening_store_with_missing_artifact_enters_read_only_recovery(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root) as store:
        record = ArtifactStore(store).publish_artifact(b"protected")
    (private_root / record.relative_path).unlink()

    recovered = open_store(database_path, private_root=private_root)
    try:
        assert recovered.status.mode.value == "READ_ONLY_RECOVERY"
        with pytest.raises(PermissionError):
            recovered.transaction().__enter__()
    finally:
        recovered.close()


def test_database_publication_failure_leaves_a_detectable_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)

        @contextmanager
        def failed_transaction() -> Iterator[None]:
            raise sqlite3.OperationalError("injected publication failure")
            yield

        monkeypatch.setattr(store, "transaction", failed_transaction)
        with pytest.raises(ArtifactError) as failed:
            artifacts.publish_artifact(b"orphan", "text/plain")
        assert failed.value.code == "MV-ARTIFACT-DB_PUBLICATION_FAILED"
        inspection = artifacts.inspect()
        assert len(inspection.orphans) == 1
        assert inspection.unreferenced == ()


def test_artifact_write_failure_creates_no_database_reference(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        digest = hashlib.sha256(b"blocked").hexdigest()
        prefix = private_root / "objects" / "sha256" / digest[:2]
        prefix.parent.mkdir(parents=True)
        prefix.write_bytes(b"not a directory")

        with pytest.raises(ArtifactError) as failed:
            artifacts.publish_artifact(b"blocked", "text/plain")
        assert failed.value.code in {
            "MV-ARTIFACT-PUBLISH_FAILED",
            "MV-ARTIFACT-PATH_MISMATCH",
        }
        assert store.artifact_metadata(digest) is None


def test_publish_manifest_transaction_rolls_back_on_conflicting_snapshot(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        version = _version()
        with store.transaction() as transaction:
            transaction.add_version(version)
        snapshot_id = _identifier("snapshot_manifest", "00000000-0000-7000-8000-000000000003")
        matchweek_id = _identifier("matchweek", "00000000-0000-7000-8000-000000000004")
        with store.transaction() as transaction:
            transaction.add_identifier(snapshot_id)
            transaction.add_identifier(matchweek_id)
        first_artifact = artifacts.publish_artifact(b"first", "application/json")
        first = SnapshotManifest(
            snapshot_id=snapshot_id,
            matchweek_id=matchweek_id,
            research_cutoff_id=_identifier(
                "research_cutoff", "00000000-0000-7000-8000-000000000005"
            ),
            version_manifest_id=_identifier(
                "version_manifest", "00000000-0000-7000-8000-000000000006"
            ),
            research_cutoff_utc="2026-09-13T06:00:00.000000+00:00",
            artifacts=(
                ManifestArtifact(
                    first_artifact.artifact_id,
                    first_artifact.digest,
                    first_artifact.media_type,
                    first_artifact.byte_length,
                ),
            ),
            versions=(ManifestVersion.from_identity(version),),
            retention_omissions=(),
            completeness=ManifestCompleteness("COMPLETE"),
            created_at_utc="2026-09-13T06:01:00.000000+00:00",
        )
        first_record = artifacts.publish_manifest(first)

        second_artifact = artifacts.publish_artifact(b"second", "application/json")
        second = SnapshotManifest(
            snapshot_id=snapshot_id,
            matchweek_id=matchweek_id,
            research_cutoff_id=first.research_cutoff_id,
            version_manifest_id=first.version_manifest_id,
            research_cutoff_utc=first.research_cutoff_utc,
            artifacts=(
                ManifestArtifact(
                    second_artifact.artifact_id,
                    second_artifact.digest,
                    second_artifact.media_type,
                    second_artifact.byte_length,
                ),
            ),
            versions=first.versions,
            retention_omissions=(),
            completeness=ManifestCompleteness("COMPLETE"),
            created_at_utc="2026-09-13T06:02:00.000000+00:00",
        )
        with pytest.raises(ArtifactError) as failed:
            artifacts.publish_manifest(second)
        assert failed.value.code == "MV-ARTIFACT-DB_PUBLICATION_FAILED"
        assert store.snapshot_manifest_metadata(first_record.digest) is not None
        assert store.artifact_metadata(second.digest) is None
        assert len(artifacts.inspect().orphans) == 1


def test_process_crash_after_object_publication_leaves_a_detectable_orphan(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    content = b"crash after publication"
    expected_digest = hashlib.sha256(content).hexdigest()
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from matchvet.artifacts import ArtifactStore
from matchvet.store import open_store

database_path = Path(sys.argv[1])
with open_store(database_path, private_root=database_path.parent) as store:
    @contextmanager
    def crash_before_catalogue():
        os._exit(0)
        yield

    store.transaction = crash_before_catalogue
    ArtifactStore(store).publish_artifact(sys.argv[2].encode(), "text/plain")
""",
            str(database_path),
            content.decode(),
        ],
        check=False,
    )
    assert child.returncode == 0

    with open_store(database_path, private_root=private_root) as store:
        inspection = ArtifactStore(store).inspect()
        assert expected_digest in inspection.orphans
        assert store.artifact_metadata(expected_digest) is None


def test_process_crash_after_database_commit_preserves_verifiable_artifact(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    content = b"crash after commit"
    expected_digest = hashlib.sha256(content).hexdigest()
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from matchvet.artifacts import ArtifactStore
from matchvet.store import open_store

database_path = Path(sys.argv[1])
with open_store(database_path, private_root=database_path.parent) as store:
    original_transaction = store.transaction

    @contextmanager
    def commit_then_crash():
        with original_transaction() as transaction:
            yield transaction
        os._exit(0)

    store.transaction = commit_then_crash
    ArtifactStore(store).publish_artifact(sys.argv[2].encode(), "text/plain")
""",
            str(database_path),
            content.decode(),
        ],
        check=False,
    )
    assert child.returncode == 0

    with open_store(database_path, private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        assert artifacts.read_artifact(expected_digest) == content
        assert expected_digest not in artifacts.inspect().orphans


def test_snapshot_manifest_is_canonical_and_round_trips_with_exact_membership(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        artifact = artifacts.publish_artifact(b"evidence", "application/json")
        version = _version()
        with store.transaction() as transaction:
            transaction.add_version(version)
        manifest = _manifest(
            ManifestArtifact(
                artifact.artifact_id, artifact.digest, artifact.media_type, artifact.byte_length
            ),
            version,
        )
        with store.transaction() as transaction:
            transaction.add_identifier(manifest.snapshot_id)
            transaction.add_identifier(manifest.matchweek_id)

        first = artifacts.publish_manifest(manifest)
        second = artifacts.publish_manifest(manifest)

        assert first == second
        verified = artifacts.verify_manifest(first.digest)
        assert verified.snapshot_id == manifest.snapshot_id
        assert verified.matchweek_id == manifest.matchweek_id
        assert verified.research_cutoff_id == manifest.research_cutoff_id
        assert verified.version_manifest_id == manifest.version_manifest_id
        assert verified.verification_state == "VERIFIED"
        assert verified.verified_at_utc is not None
        assert artifacts.read_artifact(first.digest) == verified.to_bytes()
        assert SnapshotManifest.from_bytes(manifest.to_bytes()) == manifest


def test_manifest_rejects_noncanonical_or_tampered_json(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        artifact = artifacts.publish_artifact(b"evidence", "application/json")
        manifest = _manifest(
            ManifestArtifact(
                artifact.artifact_id, artifact.digest, artifact.media_type, artifact.byte_length
            ),
            _version(),
        )
        canonical = manifest.to_bytes()

        with pytest.raises(ManifestError) as noncanonical:
            SnapshotManifest.from_bytes(b" \n" + canonical + b"\n")
        assert noncanonical.value.code == "MV-MANIFEST-NONCANONICAL"

        tampered = canonical.replace(b'"aggregate_sha256":"', b'"aggregate_sha256":"0', 1)
        with pytest.raises(ManifestError) as aggregate:
            SnapshotManifest.from_bytes(tampered)
        assert aggregate.value.code == "MV-MANIFEST-AGGREGATE_MISMATCH"


def test_inspection_reports_manifest_catalog_mismatch(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        artifact = artifacts.publish_artifact(b"evidence", "application/json")
        version = _version()
        with store.transaction() as transaction:
            transaction.add_version(version)
        manifest = _manifest(
            ManifestArtifact(
                artifact.artifact_id, artifact.digest, artifact.media_type, artifact.byte_length
            ),
            version,
        )
        with store.transaction() as transaction:
            transaction.add_identifier(manifest.snapshot_id)
            transaction.add_identifier(manifest.matchweek_id)
        published = artifacts.publish_manifest(manifest)

        connection = sqlite3.connect(private_root / "matchvet.sqlite3")
        connection.execute("DROP TRIGGER snapshot_manifests_no_update")
        connection.execute(
            "UPDATE snapshot_manifests SET aggregate_sha256 = ? WHERE manifest_digest = ?",
            ("0" * 64, published.digest),
        )
        connection.commit()
        connection.close()

        inspection = artifacts.inspect()
        assert inspection.malformed_manifests == (published.digest,)


def test_manifest_requires_exact_published_versions_and_artifacts(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        artifacts = ArtifactStore(store)
        artifact = artifacts.publish_artifact(b"evidence", "application/json")
        manifest = _manifest(
            ManifestArtifact(
                artifact.artifact_id, artifact.digest, artifact.media_type, artifact.byte_length
            ),
            _version(),
        )

        with pytest.raises(ManifestError) as missing_version:
            artifacts.publish_manifest(manifest)
        assert missing_version.value.code == "MV-MANIFEST-VERSION_MISMATCH"

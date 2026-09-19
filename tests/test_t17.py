from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_t16 import _audit

from matchvet.artifacts import ArtifactStore
from matchvet.runs import GIB, MIB, ResourceEstimate, ResourceObservation
from matchvet.store import CanonicalIdentifier, InspectionStatus, inspect_store, open_store
from matchvet.t16 import build_matchweek_audit, publish_matchweek_audit
from matchvet.t17 import (
    BACKUP_SCHEMA,
    EXPORT_AUDIT_NAME,
    EXPORT_MANIFEST_NAME,
    EXPORT_REPORT_NAME,
    EXPORT_SCHEMA,
    T17_SCHEMA_VERSION,
    BackupManifest,
    BackupResult,
    CompletionMarker,
    ExportManifest,
    T17Error,
    backup_store,
    canonical_json,
    digest_bytes,
    digest_file,
    preflight_operation,
    restore_backup,
    validate_private_target,
    validate_shared_destination,
    verify_backup,
)


def _safe_observation() -> ResourceObservation:
    return ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )


def _estimate() -> ResourceEstimate:
    return ResourceEstimate(
        storage_growth_bytes=MIB,
        peak_memory_bytes=64 * MIB,
        duration_seconds=1,
        network_bytes=0,
        cpu_heavy_operations=1,
    )


def test_canonical_json_and_digest_are_stable() -> None:
    first = canonical_json({"z": 1, "a": [True, "é"]})
    second = canonical_json({"a": [True, "é"], "z": 1})

    assert first == b'{"a":[true,"\\u00e9"],"z":1}'
    assert first == second
    assert digest_bytes(first) == hashlib.sha256(first).hexdigest()


def test_file_digest_reports_length_and_sha256(tmp_path: Path) -> None:
    path = tmp_path / "member"
    path.write_bytes(b"member bytes")

    assert digest_file(path) == (len(b"member bytes"), hashlib.sha256(b"member bytes").hexdigest())


def test_export_manifest_round_trip_has_canonical_identity() -> None:
    payload = {
        "schema": EXPORT_SCHEMA,
        "schema_version": T17_SCHEMA_VERSION,
        "state": "COMPLETE",
        "matchweek_id": "mw-1",
        "audit_id": "audit-1",
        "audit_digest": "a" * 64,
        "mode": "RESEARCH_ONLY",
        "reproducibility": {"software_commit": "b" * 40},
        "members": [
            {
                "path": "audit.json",
                "kind": "AUDIT",
                "media_type": "application/json",
                "byte_length": 2,
                "sha256": "c" * 64,
            }
        ],
        "retention_omissions": [],
    }
    manifest = ExportManifest.from_payload(payload)

    assert manifest.to_bytes() == canonical_json(payload)
    assert manifest.digest == digest_bytes(manifest.to_bytes())
    assert ExportManifest.from_bytes(manifest.to_bytes()) == manifest
    assert manifest.identity == f"export-{manifest.digest[:16]}"


def test_backup_manifest_round_trip_is_strict_and_stable() -> None:
    payload = {
        "schema": BACKUP_SCHEMA,
        "schema_version": T17_SCHEMA_VERSION,
        "state": "COMPLETE",
        "backup_id": "backup-1234567890abcdef",
        "application_id": 1297499476,
        "canonical_contract_version": 1,
        "database": {
            "path": "database.sqlite3",
            "media_type": "application/vnd.sqlite3",
            "byte_length": 4,
            "sha256": "a" * 64,
        },
        "schema_version_authoritative": 9,
        "migration_checksums": ["b" * 64],
        "objects": [],
    }
    manifest = BackupManifest.from_payload(payload)

    assert BackupManifest.from_bytes(manifest.to_bytes()) == manifest
    assert manifest.digest == digest_bytes(manifest.to_bytes())

    malformed = manifest.to_bytes().replace(b'"state":"COMPLETE"', b'"state":"PARTIAL"')
    with pytest.raises(T17Error) as failed:
        BackupManifest.from_bytes(malformed)
    assert failed.value.code == "MV-T17-BACKUP-MANIFEST_INVALID"


def test_completion_marker_requires_complete_state_and_manifest_digest() -> None:
    marker = CompletionMarker.from_payload(
        {
            "schema": "matchvet.t17.completion",
            "schema_version": T17_SCHEMA_VERSION,
            "kind": "EXPORT",
            "state": "COMPLETE",
            "manifest_digest": "a" * 64,
            "identity": "export-aaaaaaaaaaaaaaaa",
        }
    )

    assert CompletionMarker.from_bytes(marker.to_bytes()) == marker
    assert marker.digest == digest_bytes(marker.to_bytes())

    with pytest.raises(T17Error) as failed:
        CompletionMarker.from_payload({**marker.payload, "state": "INCOMPLETE"})
    assert failed.value.code == "MV-T17-MARKER-INCOMPLETE"


def test_t17_error_exposes_stable_recovery_fields() -> None:
    error = T17Error(
        "MV-T17-EXPORT-INCOMPLETE",
        "The Matchweek audit is incomplete.",
        status="INCOMPLETE",
        recovery_command="matchvet status --store /private/store.sqlite3",
        source=Path("/private/store.sqlite3"),
        destination=Path("/shared/export"),
    )

    assert error.code == "MV-T17-EXPORT-INCOMPLETE"
    assert error.status == "INCOMPLETE"
    assert error.recovery_command.endswith("store.sqlite3")
    assert error.to_dict()["source"] == "/private/store.sqlite3"
    assert error.to_dict()["destination"] == "/shared/export"


def test_path_boundaries_reject_private_shared_confusion(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    validate_shared_destination(tmp_path / "shared" / "export", private_root)
    validate_private_target(private_root / "restore" / "matchvet.sqlite3", private_root)

    with pytest.raises(T17Error) as private_destination:
        validate_shared_destination(private_root / "export", private_root)
    assert private_destination.value.code == "MV-T17-PATH-PRIVATE_DESTINATION"

    with pytest.raises(T17Error) as shared_target:
        validate_private_target(tmp_path / "shared" / "store.sqlite3", private_root)
    assert shared_target.value.code == "MV-T17-PATH-NOT_PRIVATE"


def test_resource_preflight_is_deterministic_and_refuses_before_mutation() -> None:
    first = preflight_operation("export", _estimate(), _safe_observation())
    second = preflight_operation("export", _estimate(), _safe_observation())

    assert first == second
    assert first.accepted is True
    assert first.estimate.storage_growth_bytes == MIB

    refused = preflight_operation(
        "backup",
        _estimate(),
        ResourceObservation(
            managed_storage_bytes=0,
            free_space_bytes=3 * GIB,
            available_memory_bytes=2 * GIB,
            available_cpus=3,
            memory_pressure=False,
            thermal_pressure=False,
            active_coordinators=0,
        ),
    )

    assert refused.accepted is False
    assert refused.error is not None
    assert refused.error.code == "MV-T17-BACKUP-PREFLIGHT-FREE_SPACE"


def _private_store(tmp_path: Path) -> tuple[Path, Path]:
    private_root = tmp_path / "private"
    private_root.mkdir()
    return private_root, private_root / "matchvet.sqlite3"


def _safe_resource_observation() -> ResourceObservation:
    return ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=5 * GIB,
        available_memory_bytes=2 * GIB,
        available_cpus=3,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )


def _publish_complete_audit(database_path: Path, private_root: Path) -> None:
    with open_store(database_path, private_root=private_root) as store:
        publish_matchweek_audit(_audit(), store=store)


def _insert_source_capture(
    database_path: Path,
    *,
    private_root: Path,
    content: bytes,
    source_key: str,
    retention_status: str,
    redistributable: bool,
    capture_id: str,
) -> str:
    with open_store(database_path, private_root=private_root) as store:
        artifact = ArtifactStore(store).publish_artifact(
            content,
            "application/octet-stream",
            retention_class="REUSABLE" if redistributable else "PROTECTED",
        )
        source_id = (
            "00000000-0000-7000-8000-000000000101"
            if redistributable
            else "00000000-0000-7000-8000-000000000102"
        )
        origin_id = (
            "00000000-0000-7000-8000-000000000103"
            if redistributable
            else "00000000-0000-7000-8000-000000000104"
        )
        with store.transaction() as transaction:
            for kind, value in (
                ("source", source_id),
                ("origin", origin_id),
                ("source_capture", capture_id),
            ):
                transaction.add_identifier_if_missing(CanonicalIdentifier(kind, value))
            connection = store._connection_for_repository()
            connection.execute(
                """
                INSERT INTO source_identities (
                    source_id, source_key, canonical_name, owner, source_class,
                    access_method, base_locator, allowed_use, retention_status,
                    redistributable, terms_reference, terms_observed_at_utc, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    source_key,
                    source_key,
                    source_key,
                    "OPEN_DATASET",
                    "DIRECT",
                    "https://example.test",
                    "CC0" if redistributable else "RESTRICTED_PRIVATE",
                    retention_status,
                    int(redistributable),
                    "test terms",
                    "2026-09-18T00:00:00.000000+00:00",
                    "2026-09-18T00:00:00.000000+00:00",
                ),
            )
            connection.execute(
                """
                INSERT INTO independent_origins (
                    origin_id, origin_key, organization, locator, classification, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    origin_id,
                    source_key,
                    source_key,
                    "https://example.test",
                    "DIRECT_ORIGIN",
                    "2026-09-18T00:00:00.000000+00:00",
                ),
            )
            connection.execute(
                """
                INSERT INTO source_captures (
                    capture_id, source_id, cache_key, locator, access_method,
                    retrieved_at_utc, source_published_at_utc, response_status,
                    content_type, content_sha256, byte_length, artifact_digest,
                    retention_status, observed_terms, terms_reference, rights_json,
                    collector_version, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    source_id,
                    capture_id,
                    "https://example.test/" + capture_id,
                    "DIRECT",
                    "2026-09-18T00:00:00.000000+00:00",
                    None,
                    200,
                    "application/octet-stream",
                    artifact.digest,
                    artifact.byte_length,
                    artifact.digest,
                    retention_status,
                    "test terms",
                    "test terms",
                    json.dumps(
                        {
                            "allowed_use": "CC0" if redistributable else "RESTRICTED_PRIVATE",
                            "redistributable": redistributable,
                            "retention_status": retention_status,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "test",
                    "2026-09-18T00:00:00.000000+00:00",
                ),
            )
        return artifact.digest


def test_export_publishes_complete_bundle_and_verifies_readback(tmp_path: Path) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    destination = tmp_path / "shared" / "matchweek-export"

    from matchvet.t17 import export_matchweek, verify_export

    result = export_matchweek(
        database_path,
        destination,
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )

    assert result.status == "COMPLETE"
    assert result.destination == destination.resolve()
    assert (destination / EXPORT_REPORT_NAME).is_file()
    assert (destination / EXPORT_AUDIT_NAME).is_file()
    assert (destination / EXPORT_MANIFEST_NAME).is_file()
    assert (destination / "COMPLETE").is_file()
    verification = verify_export(destination)
    assert verification.verified is True
    assert verification.manifest_digest == result.manifest_digest
    assert verification.completion_digest == result.completion_digest


def test_export_identity_is_deterministic_across_destinations(tmp_path: Path) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    from matchvet.t17 import export_matchweek

    first = export_matchweek(
        database_path,
        tmp_path / "shared" / "first",
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )
    second = export_matchweek(
        database_path,
        tmp_path / "shared" / "second",
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )

    assert first.audit_digest == second.audit_digest
    assert first.report_digest == second.report_digest
    assert first.manifest_digest == second.manifest_digest
    assert (first.destination / EXPORT_MANIFEST_NAME).read_bytes() == (
        second.destination / EXPORT_MANIFEST_NAME
    ).read_bytes()


def test_export_manifest_retains_reproducibility_and_safe_raw_evidence_only(
    tmp_path: Path,
) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    allowed = _insert_source_capture(
        database_path,
        private_root=private_root,
        content=b"allowed raw",
        source_key="open-source",
        retention_status="RETAIN_REUSABLE",
        redistributable=True,
        capture_id="00000000-0000-7000-8000-000000000105",
    )
    _insert_source_capture(
        database_path,
        private_root=private_root,
        content=b"restricted raw",
        source_key="private-source",
        retention_status="RETAIN_PRIVATE",
        redistributable=False,
        capture_id="00000000-0000-7000-8000-000000000106",
    )
    from matchvet.t17 import export_matchweek

    result = export_matchweek(
        database_path,
        tmp_path / "shared" / "rights",
        private_root=private_root,
        include_raw_evidence=True,
        resource_observation=_safe_resource_observation(),
    )
    manifest = ExportManifest.from_bytes((result.destination / "manifest.json").read_bytes())
    members = manifest.payload["members"]
    assert isinstance(members, list)
    raw_members = [
        item for item in members if isinstance(item, dict) and item.get("kind") == "RAW_EVIDENCE"
    ]
    assert len(raw_members) == 1
    assert raw_members[0]["sha256"] == allowed
    assert (result.destination / str(raw_members[0]["path"])).read_bytes() == b"allowed raw"
    omissions = manifest.payload["retention_omissions"]
    assert isinstance(omissions, list)
    assert any(item["identifier"] == "00000000-0000-7000-8000-000000000106" for item in omissions)
    reproducibility = manifest.payload["reproducibility"]
    assert isinstance(reproducibility, dict)
    assert "selection_policy" in reproducibility
    assert "software_commit" in reproducibility
    restricted = hashlib.sha256(b"restricted raw").hexdigest()
    assert not (result.destination / "evidence" / "sha256" / restricted[:2] / restricted).exists()


def test_incomplete_run_export_refusal_does_not_create_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path = _private_store(tmp_path)
    incomplete = build_matchweek_audit(
        "mw-2026-09-18",
        (),
        {},
        run_status=SimpleNamespace(run_id="run-1", state="INCOMPLETE", last_checkpoint="none"),
    )
    import matchvet.t17 as t17

    monkeypatch.setattr(t17, "read_audit", lambda *args, **kwargs: incomplete)
    destination = tmp_path / "shared" / "incomplete"
    with pytest.raises(T17Error) as failed:
        t17.export_matchweek(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert failed.value.code == "MV-T17-EXPORT-INCOMPLETE"
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()


def test_export_rejects_collision_and_missing_or_tampered_marker(tmp_path: Path) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    from matchvet.t17 import export_matchweek, verify_export

    destination = tmp_path / "shared" / "collision"
    export_matchweek(
        database_path,
        destination,
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )
    with pytest.raises(T17Error) as collision:
        export_matchweek(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert collision.value.code == "MV-T17-EXPORT-DESTINATION_EXISTS"
    (destination / "COMPLETE").unlink()
    with pytest.raises(T17Error) as missing:
        verify_export(destination)
    assert missing.value.code == "MV-T17-EXPORT-COMPLETION_MISSING"

    export_matchweek(
        database_path,
        tmp_path / "shared" / "tampered",
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )
    tampered = tmp_path / "shared" / "tampered"
    (tampered / "audit.json").write_bytes(b"tampered")
    with pytest.raises(T17Error) as digest:
        verify_export(tampered)
    assert digest.value.code == "MV-T17-EXPORT-DIGEST_MISMATCH"


def test_interrupted_export_leaves_only_unmarked_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    import matchvet.t17 as t17

    def interrupt(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(t17, "_copy_file_verified", interrupt)
    destination = tmp_path / "shared" / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        t17.export_matchweek(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert not destination.exists()
    partial = destination.with_name(destination.name + ".partial")
    assert partial.exists()
    assert not (partial / "COMPLETE").exists()


def test_export_readback_failure_cleans_operation_owned_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    import matchvet.t17 as t17
    from matchvet.t17 import export_matchweek

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise T17Error("MV-T17-EXPORT-READBACK_FAILED", "injected read-back failure")

    monkeypatch.setattr(t17, "_copy_file_verified", fail)
    destination = tmp_path / "shared" / "readback-failure"
    with pytest.raises(T17Error) as failed:
        export_matchweek(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert failed.value.code == "MV-T17-EXPORT-READBACK_FAILED"
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()


def _make_backup(tmp_path: Path) -> tuple[Path, Path, Path, BackupResult]:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    _insert_source_capture(
        database_path,
        private_root=private_root,
        content=b"protected backup evidence",
        source_key="protected-source",
        retention_status="RETAIN_PRIVATE",
        redistributable=False,
        capture_id="00000000-0000-7000-8000-000000000107",
    )
    destination = tmp_path / "shared" / "recovery-bundle"
    result = backup_store(
        database_path,
        destination,
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )
    return private_root, database_path, destination, result


def test_backup_uses_online_snapshot_and_includes_all_catalogued_objects(tmp_path: Path) -> None:
    private_root, database_path, destination, result = _make_backup(tmp_path)

    assert result.status == "COMPLETE"
    assert result.destination == destination.resolve()
    assert (destination / "database.sqlite3").is_file()
    assert (destination / "manifest.json").is_file()
    assert (destination / "COMPLETE").is_file()
    verification = verify_backup(destination)
    assert verification.verified is True
    assert verification.manifest_digest == result.manifest_digest
    assert (
        inspect_store(database_path, private_root=private_root).status is InspectionStatus.HEALTHY
    )

    manifest = BackupManifest.from_bytes((destination / "manifest.json").read_bytes())
    objects = manifest.payload["objects"]
    assert isinstance(objects, list)
    assert objects
    assert all((destination / str(item["path"])).is_file() for item in objects)
    database_member = cast(dict[str, object], manifest.payload["database"])
    assert result.database_digest == str(database_member["sha256"])


def test_backup_manifest_identity_is_deterministic_and_verified(tmp_path: Path) -> None:
    private_root, database_path, first_destination, first = _make_backup(tmp_path)
    second_destination = tmp_path / "shared" / "recovery-bundle-2"
    second = backup_store(
        database_path,
        second_destination,
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )

    assert first.backup_id == second.backup_id
    assert first.manifest_digest == second.manifest_digest
    assert (first_destination / "manifest.json").read_bytes() == (
        second_destination / "manifest.json"
    ).read_bytes()


def test_backup_rejects_corrupt_database_and_resource_floor_before_mutation(
    tmp_path: Path,
) -> None:
    private_root, database_path, destination, _ = _make_backup(tmp_path)
    (destination / "database.sqlite3").write_bytes(b"corrupt")
    with pytest.raises(T17Error) as corrupt:
        verify_backup(destination)
    assert corrupt.value.code == "MV-T17-BACKUP-DIGEST_MISMATCH"

    refused_destination = tmp_path / "shared" / "refused"
    with pytest.raises(T17Error) as refused:
        backup_store(
            database_path,
            refused_destination,
            private_root=private_root,
            resource_observation=ResourceObservation(
                managed_storage_bytes=0,
                free_space_bytes=3 * GIB,
                available_memory_bytes=2 * GIB,
                available_cpus=3,
                memory_pressure=False,
                thermal_pressure=False,
                active_coordinators=0,
            ),
        )
    assert refused.value.code == "MV-T17-BACKUP-PREFLIGHT-FREE_SPACE"
    assert not refused_destination.exists()


def test_interrupted_backup_leaves_only_unmarked_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    import matchvet.t17 as t17

    def interrupt(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(t17, "_copy_file_verified", interrupt)
    destination = tmp_path / "shared" / "interrupted-backup"
    with pytest.raises(KeyboardInterrupt):
        backup_store(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert not destination.exists()
    partial = destination.with_name(destination.name + ".partial")
    assert partial.exists()
    assert not (partial / "COMPLETE").exists()


def test_backup_readback_failure_cleans_operation_owned_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path = _private_store(tmp_path)
    _publish_complete_audit(database_path, private_root)
    import matchvet.t17 as t17

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise T17Error("MV-T17-BACKUP-READBACK_FAILED", "injected read-back failure")

    monkeypatch.setattr(t17, "_copy_file_verified", fail)
    destination = tmp_path / "shared" / "readback-failure-backup"
    with pytest.raises(T17Error) as failed:
        backup_store(
            database_path,
            destination,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert failed.value.code == "MV-T17-BACKUP-READBACK_FAILED"
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()


def test_restore_verifies_then_activates_a_new_private_target(tmp_path: Path) -> None:
    private_root, database_path, source, backup_result = _make_backup(tmp_path)
    target = private_root / "restored" / "matchvet.sqlite3"

    restored = restore_backup(
        source,
        target,
        private_root=private_root,
        resource_observation=_safe_resource_observation(),
    )

    assert restored.status == "COMPLETE"
    assert restored.backup_id == backup_result.backup_id
    assert target.is_file()
    assert digest_file(target) == digest_file(source / "database.sqlite3")
    assert inspect_store(target, private_root=private_root).status is InspectionStatus.HEALTHY
    assert database_path.is_file()


def test_restore_rejects_tampered_backup_and_leaves_authoritative_state_untouched(
    tmp_path: Path,
) -> None:
    private_root, database_path, source, _ = _make_backup(tmp_path)
    authoritative_digest = digest_file(database_path)
    (source / "database.sqlite3").write_bytes(b"tampered")
    target = private_root / "failed-restore" / "matchvet.sqlite3"

    with pytest.raises(T17Error) as failed:
        restore_backup(
            source,
            target,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert failed.value.code == "MV-T17-BACKUP-DIGEST_MISMATCH"
    assert digest_file(database_path) == authoritative_digest
    assert not target.exists()


def test_restore_refuses_existing_target_and_missing_protected_object(tmp_path: Path) -> None:
    private_root, _, source, _ = _make_backup(tmp_path)
    existing_target = private_root / "existing" / "matchvet.sqlite3"
    existing_target.parent.mkdir()
    existing_target.write_bytes(b"keep me")
    with pytest.raises(T17Error) as collision:
        restore_backup(
            source,
            existing_target,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert collision.value.code == "MV-T17-RESTORE-TARGET_EXISTS"
    assert existing_target.read_bytes() == b"keep me"

    parent_collision = private_root / "parent-collision"
    (parent_collision / "objects").mkdir(parents=True)
    with pytest.raises(T17Error) as parent_error:
        restore_backup(
            source,
            parent_collision / "matchvet.sqlite3",
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert parent_error.value.code == "MV-T17-RESTORE-TARGET_PARENT_COLLISION"

    manifest = BackupManifest.from_bytes((source / "manifest.json").read_bytes())
    objects = manifest.payload["objects"]
    assert isinstance(objects, list)
    protected = next(item for item in objects if item.get("retention_class") == "PROTECTED")
    (source / str(protected["path"])).unlink()
    with pytest.raises(T17Error) as missing:
        restore_backup(
            source,
            private_root / "missing-object" / "matchvet.sqlite3",
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert missing.value.code == "MV-T17-BACKUP-MEMBER_MISSING"


def test_failed_restore_activation_leaves_authoritative_store_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path, source, _ = _make_backup(tmp_path)
    authoritative_digest = digest_file(database_path)
    import matchvet.t17 as t17

    original_copy = t17._copy_file_verified

    def fail_activation(
        source: Path,
        target: Path,
        length: int,
        digest: str,
        *,
        error_code: str = "MV-T17-EXPORT-READBACK_FAILED",
    ) -> None:
        if error_code == "MV-T17-RESTORE-ACTIVATION_FAILED":
            original_copy(source, target, length, digest, error_code=error_code)
            raise T17Error("MV-T17-RESTORE-ACTIVATION_FAILED", "injected activation failure")
        original_copy(source, target, length, digest, error_code=error_code)

    monkeypatch.setattr(t17, "_copy_file_verified", fail_activation)
    target = private_root / "failed-activation" / "matchvet.sqlite3"
    with pytest.raises(T17Error) as failed:
        restore_backup(
            source,
            target,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert failed.value.code == "MV-T17-RESTORE-ACTIVATION_FAILED"
    assert digest_file(database_path) == authoritative_digest
    assert not target.exists()


def test_interrupted_restore_cleans_only_its_activation_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root, database_path, source, _ = _make_backup(tmp_path)
    authoritative_digest = digest_file(database_path)
    import matchvet.t17 as t17

    original_copy = t17._copy_file_verified

    def interrupt_activation(
        source: Path,
        target: Path,
        length: int,
        digest: str,
        *,
        error_code: str = "MV-T17-EXPORT-READBACK_FAILED",
    ) -> None:
        if error_code == "MV-T17-RESTORE-ACTIVATION_FAILED":
            original_copy(source, target, length, digest, error_code=error_code)
            raise KeyboardInterrupt
        original_copy(source, target, length, digest, error_code=error_code)

    monkeypatch.setattr(t17, "_copy_file_verified", interrupt_activation)
    target = private_root / "interrupted-activation" / "matchvet.sqlite3"
    with pytest.raises(KeyboardInterrupt):
        restore_backup(
            source,
            target,
            private_root=private_root,
            resource_observation=_safe_resource_observation(),
        )
    assert digest_file(database_path) == authoritative_digest
    assert not target.exists()
    assert not any(path.is_file() for path in target.parent.rglob("*"))


def test_backup_rejects_unmanifested_sidecars(tmp_path: Path) -> None:
    _, _, destination, _ = _make_backup(tmp_path)
    (destination / "database.sqlite3-wal").write_bytes(b"not part of backup")

    with pytest.raises(T17Error) as failed:
        verify_backup(destination)

    assert failed.value.code == "MV-T17-BACKUP-UNEXPECTED_MEMBER"


def test_restore_rejects_incompatible_manifest_and_sqlite_foreign_key_failure(
    tmp_path: Path,
) -> None:
    _, _, source, _ = _make_backup(tmp_path)
    manifest = BackupManifest.from_bytes((source / "manifest.json").read_bytes())
    incompatible_payload = {**manifest.payload, "schema_version_authoritative": 1}
    incompatible = BackupManifest.from_payload(incompatible_payload)
    (source / "manifest.json").write_bytes(incompatible.to_bytes())
    marker = CompletionMarker.from_payload(
        {
            "schema": "matchvet.t17.completion",
            "schema_version": T17_SCHEMA_VERSION,
            "kind": "BACKUP",
            "state": "COMPLETE",
            "manifest_digest": incompatible.digest,
            "identity": incompatible.identity,
        }
    )
    (source / "COMPLETE").write_bytes(marker.to_bytes())
    with pytest.raises(T17Error) as incompatible_error:
        verify_backup(source)
    assert incompatible_error.value.code == "MV-T17-BACKUP-INCOMPATIBLE"

    fk_root = tmp_path / "fk"
    fk_root.mkdir()
    _, _, fk_source, _ = _make_backup(fk_root)
    fk_manifest = BackupManifest.from_bytes((fk_source / "manifest.json").read_bytes())
    database = fk_source / "database.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TRIGGER canonical_identifiers_no_delete")
        connection.execute(
            "DELETE FROM canonical_identifiers "
            "WHERE canonical_id IN (SELECT artifact_id FROM artifacts LIMIT 1)"
        )
        connection.commit()
    finally:
        connection.close()
    database_length, database_digest = digest_file(database)
    fk_payload = {
        **fk_manifest.payload,
        "database": {
            **cast(dict[str, object], fk_manifest.payload["database"]),
            "byte_length": database_length,
            "sha256": database_digest,
        },
    }
    fk_manifest = BackupManifest.from_payload(fk_payload)
    (fk_source / "manifest.json").write_bytes(fk_manifest.to_bytes())
    (fk_source / "COMPLETE").write_bytes(
        CompletionMarker.from_payload(
            {
                "schema": "matchvet.t17.completion",
                "schema_version": T17_SCHEMA_VERSION,
                "kind": "BACKUP",
                "state": "COMPLETE",
                "manifest_digest": fk_manifest.digest,
                "identity": fk_manifest.identity,
            }
        ).to_bytes()
    )
    with pytest.raises(T17Error) as fk_error:
        verify_backup(fk_source)
    assert fk_error.value.code == "MV-T17-BACKUP-SQLITE_FK_FAILED"

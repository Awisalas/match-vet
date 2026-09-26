"""T17 verified export, backup, and restore contracts.

T03 owns the authoritative content-addressed store, T04 owns resource and run
guards, and T16 owns complete Matchweek publication.  This module is the
operational boundary around those contracts.  Shared bundles remain ordinary
copies until their canonical completion marker has been verified.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from matchvet.runs import (
    MIB,
    SETTLED_RESOURCE_BUDGET,
    ResourceBudget,
    ResourceEstimate,
    ResourceObservation,
    observe_resources,
    preflight_resources,
)
from matchvet.store import (
    APPLICATION_ID,
    MIGRATIONS,
    InspectionStatus,
    inspect_store,
    open_store,
    termux_private_root,
)
from matchvet.t16 import (
    T16_AUDIT_MEDIA_TYPE,
    T16_REPORT_MEDIA_TYPE,
    MatchweekAudit,
    T16Error,
    read_audit,
    render_markdown_report,
)

T17_SCHEMA_VERSION = 1
EXPORT_SCHEMA = "matchvet.t17.export"
BACKUP_SCHEMA = "matchvet.t17.backup"
COMPLETION_SCHEMA = "matchvet.t17.completion"
COMPLETION_MARKER_NAME = "COMPLETE"
EXPORT_MANIFEST_NAME = "manifest.json"
BACKUP_MANIFEST_NAME = "manifest.json"
EXPORT_REPORT_NAME = "report.md"
EXPORT_AUDIT_NAME = "audit.json"
BACKUP_DATABASE_NAME = "database.sqlite3"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"(?:export|backup)-[0-9a-f]{16}\Z")
_BACKUP_ID_RE = re.compile(r"backup-[0-9a-f]{16}\Z")


class T17Error(Exception):
    """A stable operational failure that is safe to show to a CLI user."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: str = "REFUSED",
        recovery_command: str = "matchvet doctor",
        source: Path | None = None,
        destination: Path | None = None,
        manifest_digest: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.recovery_command = recovery_command
        self.source = source
        self.destination = destination
        self.manifest_digest = manifest_digest

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "code": self.code,
            "explanation": self.message,
            "source": str(self.source) if self.source is not None else None,
            "destination": str(self.destination) if self.destination is not None else None,
            "manifest_digest": self.manifest_digest,
            "verification": "FAIL",
            "recovery_command": self.recovery_command,
        }


@dataclass(frozen=True)
class OperationPreflight:
    operation: str
    estimate: ResourceEstimate
    accepted: bool
    budget: ResourceBudget
    cpu_concurrency: int
    warnings: tuple[str, ...]
    error: T17Error | None = None


@dataclass(frozen=True)
class OperationVerification:
    operation: str
    verified: bool
    destination: Path
    manifest_digest: str
    completion_digest: str
    details: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "verified": self.verified,
            "destination": str(self.destination),
            "manifest_digest": self.manifest_digest,
            "completion_digest": self.completion_digest,
            "details": _jsonable(self.details),
        }


@dataclass(frozen=True)
class ExportResult:
    operation: str
    status: str
    source: Path
    destination: Path
    manifest_digest: str
    completion_digest: str
    audit_digest: str
    report_digest: str
    verification: OperationVerification

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "status": self.status,
            "source": str(self.source),
            "destination": str(self.destination),
            "manifest_digest": self.manifest_digest,
            "completion_digest": self.completion_digest,
            "audit_digest": self.audit_digest,
            "report_digest": self.report_digest,
            "verification": self.verification.to_dict(),
        }


@dataclass(frozen=True)
class BackupResult:
    operation: str
    status: str
    source: Path
    destination: Path
    backup_id: str
    manifest_digest: str
    completion_digest: str
    database_digest: str
    verification: OperationVerification

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "status": self.status,
            "source": str(self.source),
            "destination": str(self.destination),
            "backup_id": self.backup_id,
            "manifest_digest": self.manifest_digest,
            "completion_digest": self.completion_digest,
            "database_digest": self.database_digest,
            "verification": self.verification.to_dict(),
        }


@dataclass(frozen=True)
class RestoreResult:
    operation: str
    status: str
    source: Path
    destination: Path
    backup_id: str
    manifest_digest: str
    verification: OperationVerification

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "status": self.status,
            "source": str(self.source),
            "destination": str(self.destination),
            "backup_id": self.backup_id,
            "manifest_digest": self.manifest_digest,
            "verification": self.verification.to_dict(),
        }


@dataclass(frozen=True)
class ExportManifest:
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = _normalise_mapping(self.payload)
        _validate_manifest_base(normalized, EXPORT_SCHEMA, "EXPORT")
        for key in ("matchweek_id", "audit_id", "audit_digest", "mode"):
            if not isinstance(normalized.get(key), str) or not str(normalized[key]).strip():
                raise T17Error(
                    "MV-T17-EXPORT-MANIFEST_INVALID", f"Export manifest {key} is invalid."
                )
        _validate_digest(
            str(normalized["audit_digest"]), "audit digest", "MV-T17-EXPORT-MANIFEST_INVALID"
        )
        if not isinstance(normalized.get("reproducibility"), Mapping):
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID", "Export reproducibility metadata is invalid."
            )
        _validate_members(normalized.get("members"), "MV-T17-EXPORT-MANIFEST_INVALID")
        _validate_omissions(normalized.get("retention_omissions"), "MV-T17-EXPORT-MANIFEST_INVALID")
        object.__setattr__(self, "payload", normalized)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ExportManifest:
        return cls(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> ExportManifest:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID", "Export manifest is not valid UTF-8 JSON."
            ) from error
        if not isinstance(value, Mapping) or canonical_json(value) != data:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID", "Export manifest is not canonical JSON."
            )
        return cls(cast(Mapping[str, object], value))

    @property
    def digest(self) -> str:
        return digest_bytes(self.to_bytes())

    @property
    def identity(self) -> str:
        return f"export-{self.digest[:16]}"

    def to_bytes(self) -> bytes:
        return canonical_json(self.payload)


@dataclass(frozen=True)
class BackupManifest:
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = _normalise_mapping(self.payload)
        _validate_manifest_base(normalized, BACKUP_SCHEMA, "BACKUP")
        backup_id = normalized.get("backup_id")
        if not isinstance(backup_id, str) or _BACKUP_ID_RE.fullmatch(backup_id) is None:
            raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup manifest identity is invalid.")
        if normalized.get("application_id") != APPLICATION_ID:
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID", "Backup manifest application identity is invalid."
            )
        if normalized.get("canonical_contract_version") != 1:
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID",
                "Backup canonical contract version is incompatible.",
            )
        database = normalized.get("database")
        if not isinstance(database, Mapping):
            raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup database member is invalid.")
        _validate_member(database, "MV-T17-BACKUP-MANIFEST_INVALID")
        if database.get("path") != BACKUP_DATABASE_NAME:
            raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup database path is invalid.")
        schema_version = normalized.get("schema_version_authoritative")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < 1
        ):
            raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup schema version is invalid.")
        checksums = normalized.get("migration_checksums")
        if not isinstance(checksums, list) or any(
            not isinstance(item, str) or _DIGEST_RE.fullmatch(item) is None for item in checksums
        ):
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID", "Backup migration checksums are invalid."
            )
        _validate_members(normalized.get("objects"), "MV-T17-BACKUP-MANIFEST_INVALID")
        object.__setattr__(self, "payload", normalized)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> BackupManifest:
        return cls(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> BackupManifest:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID", "Backup manifest is not valid UTF-8 JSON."
            ) from error
        if not isinstance(value, Mapping) or canonical_json(value) != data:
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID", "Backup manifest is not canonical JSON."
            )
        return cls(cast(Mapping[str, object], value))

    @property
    def digest(self) -> str:
        return digest_bytes(self.to_bytes())

    @property
    def identity(self) -> str:
        return str(self.payload["backup_id"])

    def to_bytes(self) -> bytes:
        return canonical_json(self.payload)


@dataclass(frozen=True)
class CompletionMarker:
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = _normalise_mapping(self.payload)
        if normalized.get("schema") != COMPLETION_SCHEMA:
            raise T17Error("MV-T17-MARKER-INVALID", "Completion marker schema is invalid.")
        if normalized.get("schema_version") != T17_SCHEMA_VERSION:
            raise T17Error(
                "MV-T17-MARKER-INCOMPATIBLE", "Completion marker version is incompatible."
            )
        if normalized.get("state") != "COMPLETE":
            raise T17Error("MV-T17-MARKER-INCOMPLETE", "Completion marker does not state COMPLETE.")
        if normalized.get("kind") not in {"EXPORT", "BACKUP"}:
            raise T17Error("MV-T17-MARKER-INVALID", "Completion marker kind is invalid.")
        _validate_digest(
            cast(str, normalized.get("manifest_digest")),
            "completion manifest digest",
            "MV-T17-MARKER-INVALID",
        )
        identity = normalized.get("identity")
        if not isinstance(identity, str) or _IDENTITY_RE.fullmatch(identity) is None:
            raise T17Error("MV-T17-MARKER-INVALID", "Completion marker identity is invalid.")
        object.__setattr__(self, "payload", normalized)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CompletionMarker:
        return cls(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> CompletionMarker:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T17Error(
                "MV-T17-MARKER-INVALID", "Completion marker is not valid UTF-8 JSON."
            ) from error
        if not isinstance(value, Mapping) or canonical_json(value) != data:
            raise T17Error("MV-T17-MARKER-INVALID", "Completion marker is not canonical JSON.")
        return cls(cast(Mapping[str, object], value))

    @property
    def digest(self) -> str:
        return digest_bytes(self.to_bytes())

    def to_bytes(self) -> bytes:
        return canonical_json(self.payload)


def canonical_json(value: object) -> bytes:
    """Serialize a JSON-compatible value using MatchVet's canonical contract."""

    try:
        return json.dumps(
            _jsonable(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise T17Error(
            "MV-T17-CANONICAL_JSON_INVALID", "Value cannot be canonical JSON."
        ) from error


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            length += len(chunk)
    return length, digest.hexdigest()


def preflight_operation(
    operation: str,
    estimate: ResourceEstimate,
    observation: ResourceObservation,
    budget: ResourceBudget = SETTLED_RESOURCE_BUDGET,
) -> OperationPreflight:
    selected = operation.strip().upper()
    if selected not in {"EXPORT", "BACKUP", "RESTORE"}:
        raise T17Error("MV-T17-PREFLIGHT-OPERATION_INVALID", "T17 operation is invalid.")
    result = preflight_resources(estimate, observation, budget)
    if result.error is None:
        return OperationPreflight(
            operation=selected.lower(),
            estimate=estimate,
            accepted=result.accepted,
            budget=result.budget,
            cpu_concurrency=result.cpu_concurrency,
            warnings=result.warnings,
        )
    suffix = result.error.code.removeprefix("MV-PREFLIGHT-")
    error = T17Error(
        f"MV-T17-{selected}-PREFLIGHT-{suffix}",
        result.error.explanation,
        status="REFUSED",
        recovery_command=f"matchvet {selected.lower()}",
    )
    return OperationPreflight(
        operation=selected.lower(),
        estimate=estimate,
        accepted=False,
        budget=result.budget,
        cpu_concurrency=0,
        warnings=(),
        error=error,
    )


def validate_shared_destination(destination: Path, private_root: Path) -> Path:
    resolved = _resolved_path(destination)
    root = _resolved_path(private_root)
    if resolved == root or resolved.is_relative_to(root):
        raise T17Error(
            "MV-T17-PATH-PRIVATE_DESTINATION",
            "Export and backup destinations must be outside private authoritative storage.",
            destination=destination,
        )
    return resolved


def validate_private_target(target: Path, private_root: Path) -> Path:
    resolved = _resolved_path(target)
    root = _resolved_path(private_root)
    try:
        termux_root = _resolved_path(termux_private_root())
    except RuntimeError:
        termux_root = root
    if not root.is_relative_to(termux_root) or not resolved.is_relative_to(root):
        raise T17Error(
            "MV-T17-PATH-NOT_PRIVATE",
            "Restore targets must stay inside Termux private storage.",
            destination=target,
        )
    return resolved


def verify_export(destination: Path) -> OperationVerification:
    root = _require_bundle_directory(destination, "EXPORT")
    marker_path = _bundle_member_path(root, COMPLETION_MARKER_NAME, "MV-T17-EXPORT-PATH_INVALID")
    if not marker_path.is_file():
        raise T17Error(
            "MV-T17-EXPORT-COMPLETION_MISSING",
            "The export has no COMPLETE marker and is not publishable.",
            destination=root,
            recovery_command=f"matchvet export --destination {root}",
        )
    marker = _read_marker(marker_path, "EXPORT", root)
    manifest_path = _bundle_member_path(root, EXPORT_MANIFEST_NAME, "MV-T17-EXPORT-PATH_INVALID")
    manifest = _read_export_manifest(manifest_path, root)
    marker_manifest_digest = str(marker.payload["manifest_digest"])
    if manifest.digest != marker_manifest_digest:
        raise T17Error(
            "MV-T17-EXPORT-MANIFEST_DIGEST_MISMATCH",
            "The export completion marker does not match manifest.json.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )
    if marker.payload.get("identity") != manifest.identity:
        raise T17Error(
            "MV-T17-EXPORT-IDENTITY_MISMATCH",
            "The export completion marker identity does not match its manifest.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )

    _verify_bundle_layout(root, manifest, "EXPORT", allow_marker=True)
    members = manifest.payload["members"]
    assert isinstance(members, list)
    member_by_kind = _validate_export_member_contract(manifest, root)
    for raw_member in members:
        assert isinstance(raw_member, Mapping)
        member = cast(Mapping[str, object], raw_member)
        path_text = str(member["path"])
        if path_text in {EXPORT_MANIFEST_NAME, COMPLETION_MARKER_NAME}:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                "The export manifest cannot list its manifest or completion marker.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        member_path = _bundle_member_path(root, path_text, "MV-T17-EXPORT-PATH_INVALID")
        expected_length = _member_length(member)
        expected_digest = str(member["sha256"])
        if not member_path.is_file():
            raise T17Error(
                "MV-T17-EXPORT-MEMBER_MISSING",
                f"The exported member {path_text} is missing.",
                destination=root,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet export --destination {root}",
            )
        try:
            actual_length, actual_digest = digest_file(member_path)
        except OSError as error:
            raise T17Error(
                "MV-T17-EXPORT-READBACK_FAILED",
                f"The exported member {path_text} could not be read back.",
                destination=root,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet export --destination {root}",
            ) from error
        if (actual_length, actual_digest) != (expected_length, expected_digest):
            raise T17Error(
                "MV-T17-EXPORT-DIGEST_MISMATCH",
                f"The exported member {path_text} failed SHA-256 read-back verification.",
                destination=root,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet export --destination {root}",
            )
    audit_member = member_by_kind.get("AUDIT")
    report_member = member_by_kind.get("REPORT")
    if audit_member is None or report_member is None:
        raise T17Error(
            "MV-T17-EXPORT-MEMBER_MISSING",
            "The export must contain audit.json and report.md members.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )
    audit_path = _bundle_member_path(root, str(audit_member["path"]), "MV-T17-EXPORT-PATH_INVALID")
    report_path = _bundle_member_path(
        root, str(report_member["path"]), "MV-T17-EXPORT-PATH_INVALID"
    )
    try:
        audit_value = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(audit_value, Mapping):
            raise ValueError("audit root is not an object")
        audit = MatchweekAudit.from_dict(cast(Mapping[str, object], audit_value))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        T16Error,
        T17Error,
        ValueError,
    ) as error:
        raise T17Error(
            "MV-T17-EXPORT-AUDIT_INVALID",
            "The exported audit cannot be parsed and verified.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        ) from error
    if audit.publication_state.value != "COMPLETE":
        raise T17Error(
            "MV-T17-EXPORT-INCOMPLETE",
            "The exported audit is not complete.",
            status="INCOMPLETE",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )
    expected_report = render_markdown_report(audit).encode("utf-8")
    try:
        report_bytes = report_path.read_bytes()
    except OSError as error:
        raise T17Error(
            "MV-T17-EXPORT-READBACK_FAILED",
            "The exported report could not be read back.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        ) from error
    if report_bytes != expected_report:
        raise T17Error(
            "MV-T17-EXPORT-REPORT_MISMATCH",
            "The exported report does not match the deterministic T16 rendering.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )
    _validate_export_audit_metadata(
        manifest,
        audit,
        audit_bytes=audit.to_bytes(),
        report_bytes=report_bytes,
        destination=root,
    )
    return OperationVerification(
        operation="export",
        verified=True,
        destination=root,
        manifest_digest=manifest.digest,
        completion_digest=marker.digest,
        details={
            "state": "COMPLETE",
            "matchweek_id": manifest.payload["matchweek_id"],
            "audit_id": manifest.payload["audit_id"],
            "mode": manifest.payload["mode"],
            "member_count": len(members),
        },
    )


def verify_backup(destination: Path) -> OperationVerification:
    root = _require_bundle_directory(destination, "BACKUP")
    marker_path = _bundle_member_path(root, COMPLETION_MARKER_NAME, "MV-T17-BACKUP-PATH_INVALID")
    if not marker_path.is_file():
        raise T17Error(
            "MV-T17-BACKUP-COMPLETION_MISSING",
            "The backup has no COMPLETE marker and is not recoverable.",
            destination=root,
            recovery_command=f"matchvet backup --verify {root}",
        )
    marker = _read_marker(marker_path, "BACKUP", root)
    manifest_path = _bundle_member_path(root, BACKUP_MANIFEST_NAME, "MV-T17-BACKUP-PATH_INVALID")
    manifest = _read_backup_manifest(manifest_path, root)
    if manifest.digest != str(marker.payload["manifest_digest"]):
        raise T17Error(
            "MV-T17-BACKUP-MANIFEST_DIGEST_MISMATCH",
            "The backup completion marker does not match manifest.json.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --verify {root}",
        )
    if marker.payload.get("identity") != manifest.identity:
        raise T17Error(
            "MV-T17-BACKUP-IDENTITY_MISMATCH",
            "The backup completion marker identity does not match its manifest.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --verify {root}",
        )
    database_member = cast(Mapping[str, object], manifest.payload["database"])
    database_path = root / str(database_member["path"])
    sidecars = (
        database_path.with_name(database_path.name + "-wal"),
        database_path.with_name(database_path.name + "-shm"),
    )
    sidecars_preexisting = tuple(os.path.lexists(path) for path in sidecars)
    try:
        _verify_bundle_layout(root, manifest, "BACKUP", allow_marker=True)
        details = _verify_backup_contents(root, manifest, readback=False, allow_marker=True)
    finally:
        for sidecar, preexisting in zip(sidecars, sidecars_preexisting, strict=True):
            if not preexisting:
                sidecar.unlink(missing_ok=True)
    return OperationVerification(
        operation="backup",
        verified=True,
        destination=root,
        manifest_digest=manifest.digest,
        completion_digest=marker.digest,
        details=details,
    )


def export_matchweek(
    database_path: Path,
    destination: Path,
    *,
    private_root: Path | None = None,
    matchweek_id: str | None = None,
    include_raw_evidence: bool = False,
    resource_observation: ResourceObservation | None = None,
) -> ExportResult:
    root = _resolved_path(private_root or termux_private_root())
    source = _resolved_path(database_path)
    try:
        destination_path = validate_shared_destination(destination, root)
    except T17Error as error:
        raise _with_paths(error, source, destination) from error
    partial = _partial_path(destination_path)
    try:
        _reject_export_targets(destination_path, partial)
    except T17Error as error:
        raise _with_paths(error, source, destination_path) from error
    initial_preflight = preflight_operation(
        "export",
        _estimate_for_bytes(
            _estimated_database_and_objects(source) if include_raw_evidence else 2 * MIB,
            copies=3,
        ),
        _observation_for_destination(
            database_path=source,
            destination=destination_path,
            supplied=resource_observation,
        ),
    )
    if not initial_preflight.accepted:
        assert initial_preflight.error is not None
        raise _with_paths(initial_preflight.error, source, destination_path)

    try:
        audit = read_audit(source, private_root=root, matchweek_id=matchweek_id)
    except (T16Error, OSError, sqlite3.DatabaseError) as error:
        raise T17Error(
            "MV-T17-EXPORT-SOURCE_UNAVAILABLE",
            f"The complete T16 publication could not be read: {error}.",
            source=source,
            destination=destination_path,
            recovery_command=f"matchvet report --store {source}",
        ) from error
    _require_complete_audit_for_export(audit, source, destination_path)
    inspection = inspect_store(source, private_root=root)
    if inspection.status is not InspectionStatus.HEALTHY:
        issue = inspection.issues[0] if inspection.issues else None
        code = issue.code if issue is not None else "MV-T17-EXPORT-SOURCE_INTEGRITY"
        message = issue.message if issue is not None else "The authoritative store is not healthy."
        raise T17Error(
            "MV-T17-EXPORT-SOURCE_INTEGRITY",
            f"{code}: {message}",
            destination=destination_path,
            recovery_command=f"matchvet doctor --store {source}",
        )

    audit_bytes = audit.to_bytes()
    report_bytes = render_markdown_report(audit).encode("utf-8")
    if digest_bytes(audit_bytes) != _artifact_digest_for_t16(audit, source, destination_path):
        raise T17Error(
            "MV-T17-EXPORT-AUDIT_DIGEST_MISMATCH",
            "The complete audit content does not match its authoritative artifact.",
            source=source,
            destination=destination_path,
            recovery_command=f"matchvet doctor --store {source}",
        )
    raw_members, raw_sources, omissions = _raw_export_members(
        source,
        include_raw_evidence=include_raw_evidence,
        destination=destination_path,
    )
    members: list[dict[str, object]] = [
        _member_payload(
            EXPORT_AUDIT_NAME,
            "AUDIT",
            T16_AUDIT_MEDIA_TYPE,
            audit_bytes,
        ),
        _member_payload(
            EXPORT_REPORT_NAME,
            "REPORT",
            T16_REPORT_MEDIA_TYPE,
            report_bytes,
        ),
        *raw_members,
    ]
    members.sort(key=lambda item: str(item["path"]))
    manifest_payload: dict[str, object] = {
        "schema": EXPORT_SCHEMA,
        "schema_version": T17_SCHEMA_VERSION,
        "state": "COMPLETE",
        "matchweek_id": audit.payload["matchweek_id"],
        "audit_id": audit.audit_id,
        "audit_digest": audit.audit_digest,
        "audit_artifact_digest": digest_bytes(audit_bytes),
        "report_digest": digest_bytes(report_bytes),
        "mode": audit.mode.value,
        "reproducibility": audit.reproducibility,
        "versions": {
            "audit_schema_version": audit.payload["schema_version"],
            "preference_set": audit.payload["preference_set"],
            "selection_policy": audit.payload["selection_policy"],
        },
        "run": audit.payload.get("run", {}),
        "members": members,
        "retention_omissions": omissions,
    }
    manifest = ExportManifest.from_payload(manifest_payload)
    marker = CompletionMarker.from_payload(
        {
            "schema": COMPLETION_SCHEMA,
            "schema_version": T17_SCHEMA_VERSION,
            "kind": "EXPORT",
            "state": "COMPLETE",
            "manifest_digest": manifest.digest,
            "identity": manifest.identity,
        }
    )
    total_bytes = sum(_member_length(cast(Mapping[str, object], item)) for item in members) + len(
        marker.to_bytes()
    )
    preflight = preflight_operation(
        "export",
        _estimate_for_bytes(total_bytes, copies=3),
        _observation_for_destination(
            database_path=source,
            destination=destination_path,
            supplied=resource_observation,
        ),
    )
    if not preflight.accepted:
        assert preflight.error is not None
        raise _with_paths(preflight.error, source, destination_path)

    private_stage = _private_stage(root, "exports", manifest.identity)
    created_destination = False
    try:
        _ensure_directory(private_stage, root)
        stage_members = private_stage / "members"
        _ensure_directory(stage_members, private_stage)
        _write_bytes_verified(stage_members / EXPORT_AUDIT_NAME, audit_bytes)
        _write_bytes_verified(stage_members / EXPORT_REPORT_NAME, report_bytes)
        _write_bytes_verified(private_stage / EXPORT_MANIFEST_NAME, manifest.to_bytes())
        raw_member_by_path = {str(member["path"]): member for member in raw_members}
        for member_path, source_path in raw_sources.items():
            member = raw_member_by_path[member_path]
            target = stage_members / member_path
            _copy_private_source(source_path, target, _member_length(member), str(member["sha256"]))

        _ensure_directory(partial, destination_path.parent)
        for member in members:
            source_path = stage_members / str(member["path"])
            _copy_file_verified(
                source_path,
                partial / str(member["path"]),
                _member_length(cast(Mapping[str, object], member)),
                str(member["sha256"]),
            )
        _copy_file_verified(
            private_stage / EXPORT_MANIFEST_NAME,
            partial / EXPORT_MANIFEST_NAME,
            len(manifest.to_bytes()),
            manifest.digest,
        )
        _verify_export_without_marker(partial, manifest)

        _ensure_directory(destination_path, destination_path.parent)
        created_destination = True
        for member in [
            *members,
            {
                "path": EXPORT_MANIFEST_NAME,
                "byte_length": len(manifest.to_bytes()),
                "sha256": manifest.digest,
            },
        ]:
            source_path = partial / str(member["path"])
            _copy_file_verified(
                source_path,
                destination_path / str(member["path"]),
                _member_length(cast(Mapping[str, object], member)),
                str(member["sha256"]),
            )
        _write_bytes_verified(destination_path / COMPLETION_MARKER_NAME, marker.to_bytes())
        verification = verify_export(destination_path)
    except Exception:
        _remove_operation_path(private_stage, root)
        _remove_operation_path(partial, destination_path.parent)
        if created_destination:
            _remove_operation_path(destination_path, destination_path.parent)
        raise
    else:
        _remove_operation_path(private_stage, root)
        _remove_operation_path(partial, destination_path.parent)
    return ExportResult(
        operation="export",
        status="COMPLETE",
        source=source,
        destination=destination_path,
        manifest_digest=manifest.digest,
        completion_digest=marker.digest,
        audit_digest=audit.audit_digest,
        report_digest=digest_bytes(report_bytes),
        verification=verification,
    )


def backup_store(
    database_path: Path,
    destination: Path,
    *,
    private_root: Path | None = None,
    resource_observation: ResourceObservation | None = None,
) -> BackupResult:
    root = _resolved_path(private_root or termux_private_root())
    source = _resolved_path(database_path)
    try:
        destination_path = validate_shared_destination(destination, root)
    except T17Error as error:
        raise _with_paths(error, source, destination) from error
    partial = _partial_path(destination_path)
    try:
        _reject_bundle_targets(destination_path, partial, "BACKUP")
    except T17Error as error:
        raise _with_paths(error, source, destination_path) from error
    initial_preflight = preflight_operation(
        "backup",
        _estimate_for_bytes(_estimated_database_and_objects(source), copies=3),
        _observation_for_destination(
            database_path=source,
            destination=destination_path,
            supplied=resource_observation,
        ),
    )
    if not initial_preflight.accepted:
        assert initial_preflight.error is not None
        raise _with_paths(initial_preflight.error, source, destination_path)
    inspection = inspect_store(source, private_root=root)
    if inspection.status is not InspectionStatus.HEALTHY:
        issue = inspection.issues[0] if inspection.issues else None
        code = issue.code if issue is not None else "MV-T17-BACKUP-SOURCE_INTEGRITY"
        message = issue.message if issue is not None else "The authoritative store is not healthy."
        raise T17Error(
            "MV-T17-BACKUP-SOURCE_INTEGRITY",
            f"{code}: {message}",
            source=source,
            destination=destination_path,
            recovery_command=f"matchvet doctor --store {source}",
        )

    current_migrations = tuple(migration.checksum for migration in MIGRATIONS)
    _verify_sqlite_database(
        source,
        operation="BACKUP",
        expected_schema_version=len(MIGRATIONS),
        expected_migrations=current_migrations,
        destination=destination_path,
    )
    source_objects = _artifact_catalog_rows(source, destination=destination_path)
    for object_row in source_objects:
        object_path = _catalog_object_path(
            source.parent,
            str(object_row["digest"]),
            str(object_row["relative_path"]),
            source=source,
            destination=destination_path,
        )
        try:
            actual = digest_file(object_path)
        except OSError as error:
            raise T17Error(
                "MV-T17-BACKUP-SOURCE_INTEGRITY",
                f"Catalogued artifact {object_row['digest']} could not be read.",
                source=source,
                destination=destination_path,
                recovery_command=f"matchvet doctor --store {source}",
            ) from error
        object_length = _catalog_byte_length(object_row)
        expected = (object_length, str(object_row["digest"]))
        if actual != expected:
            raise T17Error(
                "MV-T17-BACKUP-SOURCE_INTEGRITY",
                f"Catalogued artifact {object_row['digest']} failed digest verification.",
                source=source,
                destination=destination_path,
                recovery_command=f"matchvet doctor --store {source}",
            )
    private_stage = _private_stage(root, "backups", "backup-pending")
    created_destination = False
    manifest: BackupManifest | None = None
    try:
        _ensure_directory(private_stage, root)
        stage_database = private_stage / BACKUP_DATABASE_NAME
        _online_backup(source, stage_database)
        stage_details = _verify_sqlite_database(
            stage_database,
            operation="BACKUP",
            expected_schema_version=len(MIGRATIONS),
            expected_migrations=current_migrations,
            destination=destination_path,
        )
        stage_objects = _artifact_catalog_rows(stage_database, destination=destination_path)
        if stage_objects != source_objects:
            raise T17Error(
                "MV-T17-BACKUP-SOURCE_CHANGED",
                "The authoritative artifact catalog changed during online backup; retry safely.",
                source=source,
                destination=destination_path,
                recovery_command=f"matchvet backup --destination {destination_path}",
            )
        object_members: list[dict[str, object]] = []
        for object_row in stage_objects:
            digest = str(object_row["digest"])
            relative_path = str(object_row["relative_path"])
            source_object = _catalog_object_path(
                source.parent,
                digest,
                relative_path,
                source=source,
                destination=destination_path,
            )
            stage_object = private_stage / relative_path
            _copy_private_source(
                source_object,
                stage_object,
                _catalog_byte_length(object_row),
                digest,
            )
            object_members.append(
                {
                    "path": relative_path,
                    "kind": "ARTIFACT",
                    "artifact_id": str(object_row["artifact_id"]),
                    "media_type": str(object_row["media_type"]),
                    "byte_length": _catalog_byte_length(object_row),
                    "sha256": digest,
                    "relative_path": relative_path,
                    "created_at_utc": str(object_row["created_at_utc"]),
                    "retention_class": str(object_row["retention_class"]),
                }
            )
        object_members.sort(key=lambda item: str(item["sha256"]))
        database_length, database_digest = digest_file(stage_database)
        database_member = {
            "path": BACKUP_DATABASE_NAME,
            "kind": "DATABASE",
            "media_type": "application/vnd.sqlite3",
            "byte_length": database_length,
            "sha256": database_digest,
        }
        stage_schema_version = stage_details.get("schema_version")
        if isinstance(stage_schema_version, bool) or not isinstance(stage_schema_version, int):
            raise T17Error(
                "MV-T17-BACKUP-DATABASE_SCHEMA_INVALID",
                "The online backup did not report a valid schema version.",
                source=source,
                destination=destination_path,
            )
        manifest = _build_backup_manifest(
            database_member,
            object_members,
            schema_version=stage_schema_version,
            migration_checksums=current_migrations,
        )
        manifest_bytes = manifest.to_bytes()
        _write_bytes_verified(private_stage / BACKUP_MANIFEST_NAME, manifest_bytes)

        _ensure_directory(partial, destination_path.parent)
        for member in _backup_members(manifest):
            path = str(member["path"])
            _copy_file_verified(
                private_stage / path,
                partial / path,
                _member_length(member),
                str(member["sha256"]),
                error_code="MV-T17-BACKUP-READBACK_FAILED",
            )
        _copy_file_verified(
            private_stage / BACKUP_MANIFEST_NAME,
            partial / BACKUP_MANIFEST_NAME,
            len(manifest_bytes),
            manifest.digest,
            error_code="MV-T17-BACKUP-READBACK_FAILED",
        )
        _verify_backup_contents(partial, manifest, readback=True)

        _ensure_directory(destination_path, destination_path.parent)
        created_destination = True
        for member in _backup_members(manifest):
            path = str(member["path"])
            _copy_file_verified(
                partial / path,
                destination_path / path,
                _member_length(member),
                str(member["sha256"]),
                error_code="MV-T17-BACKUP-READBACK_FAILED",
            )
        _copy_file_verified(
            partial / BACKUP_MANIFEST_NAME,
            destination_path / BACKUP_MANIFEST_NAME,
            len(manifest_bytes),
            manifest.digest,
            error_code="MV-T17-BACKUP-READBACK_FAILED",
        )
        marker = CompletionMarker.from_payload(
            {
                "schema": COMPLETION_SCHEMA,
                "schema_version": T17_SCHEMA_VERSION,
                "kind": "BACKUP",
                "state": "COMPLETE",
                "manifest_digest": manifest.digest,
                "identity": manifest.identity,
            }
        )
        _write_bytes_verified(destination_path / COMPLETION_MARKER_NAME, marker.to_bytes())
        verification = verify_backup(destination_path)
        _remove_sqlite_sidecars(destination_path / BACKUP_DATABASE_NAME)
    except T17Error as error:
        _remove_operation_path(private_stage, root)
        _remove_operation_path(partial, destination_path.parent)
        if created_destination:
            _remove_operation_path(destination_path, destination_path.parent)
        raise _with_paths(error, source, destination_path) from error
    except Exception:
        _remove_operation_path(private_stage, root)
        _remove_operation_path(partial, destination_path.parent)
        if created_destination:
            _remove_operation_path(destination_path, destination_path.parent)
        raise
    else:
        _remove_operation_path(private_stage, root)
        _remove_operation_path(partial, destination_path.parent)

    assert manifest is not None
    return BackupResult(
        operation="backup",
        status="COMPLETE",
        source=source,
        destination=destination_path,
        backup_id=manifest.identity,
        manifest_digest=manifest.digest,
        completion_digest=verification.completion_digest,
        database_digest=str(cast(Mapping[str, object], manifest.payload["database"])["sha256"]),
        verification=verification,
    )


def restore_backup(
    source: Path,
    target_database_path: Path,
    *,
    private_root: Path | None = None,
    resource_observation: ResourceObservation | None = None,
) -> RestoreResult:
    root = _resolved_path(private_root or termux_private_root())
    if source.is_symlink():
        raise T17Error(
            "MV-T17-RESTORE-SOURCE_UNSAFE",
            "Restore source bundles cannot be symbolic links.",
            source=source,
            destination=target_database_path,
            recovery_command=f"matchvet backup --verify {source}",
        )
    source_path = _resolved_path(source)
    if source_path == root or source_path.is_relative_to(root):
        raise T17Error(
            "MV-T17-RESTORE-SOURCE_PRIVATE",
            "Restore source bundles must be outside private authoritative storage.",
            source=source_path,
            destination=target_database_path,
            recovery_command=f"matchvet backup --destination {source_path}.new",
        )
    if os.path.lexists(target_database_path):
        raise T17Error(
            "MV-T17-RESTORE-TARGET_EXISTS",
            "Restore requires a new private target and never overwrites an existing database.",
            source=source_path,
            destination=target_database_path,
            recovery_command=(
                f"matchvet restore --source {source_path} --target {target_database_path}.new"
            ),
        )
    try:
        target = validate_private_target(target_database_path, root)
    except T17Error as error:
        raise _with_paths(error, source_path, target_database_path) from error
    if os.path.lexists(target):
        raise T17Error(
            "MV-T17-RESTORE-TARGET_EXISTS",
            "Restore requires a new private target and never overwrites an existing database.",
            source=source_path,
            destination=target,
            recovery_command=f"matchvet restore --source {source_path} --target {target}.new",
        )
    target_objects_root = target.parent / "objects"
    if os.path.lexists(target_objects_root):
        raise T17Error(
            "MV-T17-RESTORE-TARGET_PARENT_COLLISION",
            "Restore requires a new target directory without an existing object store.",
            source=source_path,
            destination=target,
            recovery_command=(
                f"matchvet restore --source {source_path} --target "
                f"{target.parent}.new/matchvet.sqlite3"
            ),
        )

    try:
        manifest_path = _bundle_member_path(
            source_path, BACKUP_MANIFEST_NAME, "MV-T17-BACKUP-PATH_INVALID"
        )
        manifest = _read_backup_manifest(manifest_path, source_path)
        total_bytes = sum(_member_length(member) for member in _backup_members(manifest))
    except T17Error as error:
        raise _with_paths(error, source_path, target) from error
    preflight = preflight_operation(
        "restore",
        _estimate_for_bytes(total_bytes, copies=3),
        _observation_for_destination(
            database_path=target,
            destination=target,
            supplied=resource_observation,
        ),
    )
    if not preflight.accepted:
        assert preflight.error is not None
        raise _with_paths(preflight.error, source_path, target)
    try:
        source_verification = verify_backup(source_path)
    except T17Error as error:
        raise _with_paths(error, source_path, target) from error

    private_stage = _private_stage(root, "restores", manifest.identity)
    created_target = False
    created_objects: list[Path] = []
    try:
        _ensure_directory(private_stage, root)
        for member in _backup_members(manifest):
            path = str(member["path"])
            _copy_file_verified(
                _bundle_member_path(source_path, path, "MV-T17-RESTORE-PATH_INVALID"),
                private_stage / path,
                _member_length(member),
                str(member["sha256"]),
                error_code="MV-T17-RESTORE-READBACK_FAILED",
            )
        manifest_bytes = manifest.to_bytes()
        _copy_file_verified(
            manifest_path,
            private_stage / BACKUP_MANIFEST_NAME,
            len(manifest_bytes),
            manifest.digest,
            error_code="MV-T17-RESTORE-READBACK_FAILED",
        )
        _verify_backup_contents(private_stage, manifest, readback=True)

        manifest_schema_version = cast(int, manifest.payload["schema_version_authoritative"])
        staged_database = private_stage / BACKUP_DATABASE_NAME
        if manifest_schema_version < len(MIGRATIONS):
            try:
                with open_store(staged_database, private_root=root) as staged_store:
                    if staged_store.status.mode.value != "READ_WRITE":
                        raise T17Error(
                            "MV-T17-RESTORE-MIGRATION_FAILED",
                            "The staged backup did not migrate to a writable current store.",
                            source=source_path,
                            destination=target,
                            manifest_digest=manifest.digest,
                        )
            except T17Error:
                raise
            except Exception as error:
                raise T17Error(
                    "MV-T17-RESTORE-MIGRATION_FAILED",
                    "The staged backup could not be forward-migrated to the current schema.",
                    source=source_path,
                    destination=target,
                    manifest_digest=manifest.digest,
                    recovery_command=f"matchvet backup --verify {source_path}",
                ) from error

        staged_inspection = inspect_store(staged_database, private_root=root)
        if staged_inspection.status is not InspectionStatus.HEALTHY:
            issue = staged_inspection.issues[0] if staged_inspection.issues else None
            message = (
                issue.message if issue is not None else "Staged store failed current verification."
            )
            raise T17Error(
                "MV-T17-RESTORE-STORE_VERIFICATION_FAILED",
                message,
                source=source_path,
                destination=target,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet doctor --store {staged_database}",
            )
        current_manifest = _current_schema_backup_manifest(private_stage, staged_database, manifest)
        staged_details = _verify_backup_contents(
            private_stage,
            current_manifest,
            readback=False,
            database_path_override=staged_database,
        )

        _ensure_directory(target.parent, root)
        object_members = manifest.payload.get("objects")
        assert isinstance(object_members, list)
        for raw_member in object_members:
            assert isinstance(raw_member, Mapping)
            member = cast(Mapping[str, object], raw_member)
            relative_path = str(member["path"])
            destination_object = target.parent / relative_path
            if os.path.lexists(destination_object):
                if destination_object.is_symlink() or not destination_object.is_file():
                    raise T17Error(
                        "MV-T17-RESTORE-TARGET_OBJECT_COLLISION",
                        f"Restore target object is not a regular file: {destination_object}.",
                    )
                if digest_file(destination_object) != (
                    _member_length(member),
                    str(member["sha256"]),
                ):
                    raise T17Error(
                        "MV-T17-RESTORE-TARGET_OBJECT_COLLISION",
                        (
                            "Restore target object collides with a different digest: "
                            f"{destination_object}."
                        ),
                    )
                continue
            created_objects.append(destination_object)
            _copy_file_verified(
                private_stage / relative_path,
                destination_object,
                _member_length(member),
                str(member["sha256"]),
                error_code="MV-T17-RESTORE-ACTIVATION_FAILED",
            )

        created_target = True
        staged_length, staged_digest = digest_file(staged_database)
        _copy_file_verified(
            staged_database,
            target,
            staged_length,
            staged_digest,
            error_code="MV-T17-RESTORE-ACTIVATION_FAILED",
        )
        target_details = _verify_backup_contents(
            target.parent,
            current_manifest,
            readback=False,
            database_path_override=target,
        )
        target_inspection = inspect_store(target, private_root=root)
        if target_inspection.status is not InspectionStatus.HEALTHY:
            issue = target_inspection.issues[0] if target_inspection.issues else None
            message = (
                issue.message if issue is not None else "Restored store failed final verification."
            )
            raise T17Error(
                "MV-T17-RESTORE-STORE_VERIFICATION_FAILED",
                message,
                source=source_path,
                destination=target,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet doctor --store {target}",
            )
        target_details = {**staged_details, **target_details}
    except BaseException as error:
        _cleanup_restore_failure(
            private_stage,
            root,
            target,
            target.parent,
            created_target,
            created_objects,
        )
        if isinstance(error, T17Error):
            raise _with_paths(error, source_path, target) from error
        raise
    else:
        _remove_operation_path(private_stage, root)

    restore_verification = OperationVerification(
        operation="restore",
        verified=True,
        destination=target,
        manifest_digest=manifest.digest,
        completion_digest=source_verification.completion_digest,
        details=target_details,
    )
    return RestoreResult(
        operation="restore",
        status="COMPLETE",
        source=source_path,
        destination=target,
        backup_id=manifest.identity,
        manifest_digest=manifest.digest,
        verification=restore_verification,
    )


def _build_backup_manifest(
    database_member: Mapping[str, object],
    object_members: list[dict[str, object]],
    *,
    schema_version: int,
    migration_checksums: tuple[str, ...],
) -> BackupManifest:
    payload: dict[str, object] = {
        "schema": BACKUP_SCHEMA,
        "schema_version": T17_SCHEMA_VERSION,
        "state": "COMPLETE",
        "backup_id": "pending",
        "application_id": APPLICATION_ID,
        "canonical_contract_version": 1,
        "database": dict(database_member),
        "schema_version_authoritative": schema_version,
        "migration_checksums": list(migration_checksums),
        "objects": object_members,
    }
    backup_id = _expected_backup_identity(payload)
    payload["backup_id"] = backup_id
    return BackupManifest.from_payload(payload)


def _backup_members(manifest: BackupManifest) -> list[Mapping[str, object]]:
    database = manifest.payload.get("database")
    objects = manifest.payload.get("objects")
    if not isinstance(database, Mapping) or not isinstance(objects, list):
        raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup members are invalid.")
    members: list[Mapping[str, object]] = [cast(Mapping[str, object], database)]
    for item in objects:
        if not isinstance(item, Mapping):
            raise T17Error("MV-T17-BACKUP-MANIFEST_INVALID", "Backup object member is invalid.")
        members.append(cast(Mapping[str, object], item))
    return members


def _artifact_catalog_rows(
    database_path: Path, *, destination: Path | None = None
) -> tuple[dict[str, object], ...]:
    connection = _readonly_connection(database_path)
    try:
        rows = connection.execute(
            """
            SELECT artifact_id, digest, media_type, byte_length, relative_path,
                   created_at_utc, retention_class
            FROM artifacts
            ORDER BY digest, artifact_id
            """
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise T17Error(
            "MV-T17-BACKUP-DATABASE_SCHEMA_INVALID",
            "The backed-up database has no readable artifact catalog.",
            source=database_path,
            destination=destination,
            recovery_command=f"matchvet doctor --store {database_path}",
        ) from error
    finally:
        connection.close()
    return tuple(
        {
            "artifact_id": str(row[0]),
            "digest": str(row[1]),
            "media_type": str(row[2]),
            "byte_length": int(row[3]),
            "relative_path": str(row[4]),
            "created_at_utc": str(row[5]),
            "retention_class": str(row[6]),
        }
        for row in rows
    )


def _catalog_byte_length(row: Mapping[str, object]) -> int:
    value = row.get("byte_length")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise T17Error("MV-T17-BACKUP-METADATA_INVALID", "Artifact byte length is invalid.")
    return value


def _verify_sqlite_database(
    database_path: Path,
    *,
    operation: str,
    expected_schema_version: int,
    expected_migrations: tuple[str, ...],
    destination: Path,
) -> dict[str, object]:
    prefix = f"MV-T17-{operation}"
    try:
        connection = _readonly_connection(database_path)
    except T17Error as error:
        raise T17Error(
            f"{prefix}-DATABASE_UNREADABLE",
            f"SQLite database could not be opened for verification: {database_path}.",
            source=database_path,
            destination=destination,
            recovery_command=f"matchvet doctor --store {database_path}",
        ) from error
    try:
        try:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            application_id_row = connection.execute("PRAGMA application_id").fetchone()
            schema_version_row = connection.execute("PRAGMA user_version").fetchone()
            journal_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
            migration_rows = connection.execute(
                "SELECT migration_number, name, checksum, canonical_contract_version, "
                "minimum_application_version, maximum_application_version, result "
                "FROM schema_migrations ORDER BY migration_number"
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise T17Error(
                f"{prefix}-DATABASE_UNREADABLE",
                f"SQLite database could not be fully inspected: {database_path}.",
                source=database_path,
                destination=destination,
                recovery_command=f"matchvet doctor --store {database_path}",
            ) from error
        if integrity_rows != [("ok",)]:
            raise T17Error(
                f"{prefix}-SQLITE_INTEGRITY_FAILED",
                "SQLite integrity_check did not report ok.",
                source=database_path,
                destination=destination,
                recovery_command=f"matchvet doctor --store {database_path}",
            )
        if foreign_keys:
            raise T17Error(
                f"{prefix}-SQLITE_FK_FAILED",
                f"SQLite reported {len(foreign_keys)} foreign-key violation(s).",
                source=database_path,
                destination=destination,
                recovery_command=f"matchvet doctor --store {database_path}",
            )
        application_id = int(application_id_row[0]) if application_id_row is not None else 0
        if application_id != APPLICATION_ID:
            raise T17Error(
                f"{prefix}-INCOMPATIBLE",
                "SQLite application identity is not the MatchVet authoritative store.",
                source=database_path,
                destination=destination,
                recovery_command=f"matchvet doctor --store {database_path}",
            )
        schema_version = int(schema_version_row[0]) if schema_version_row is not None else 0
        migration_numbers = tuple(int(row[0]) for row in migration_rows)
        migration_checksums = tuple(str(row[2]) for row in migration_rows)
        expected_plan = MIGRATIONS[:expected_schema_version]
        actual_plan = tuple(
            (
                str(row[1]),
                str(row[2]),
                int(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
            )
            for row in migration_rows
        )
        known_plan = tuple(
            (
                migration.name,
                migration.checksum,
                migration.canonical_contract_version,
                migration.minimum_application_version,
                migration.maximum_application_version,
                "COMPLETED",
            )
            for migration in expected_plan
        )
        if (
            schema_version != expected_schema_version
            or migration_numbers != tuple(range(1, expected_schema_version + 1))
            or migration_checksums != expected_migrations
            or expected_migrations != tuple(migration.checksum for migration in expected_plan)
            or actual_plan != known_plan
            or str(journal_mode_row[0]).lower() != "wal"
        ):
            raise T17Error(
                f"{prefix}-INCOMPATIBLE",
                "SQLite schema, migration, or journal-mode identity is incompatible.",
                source=database_path,
                destination=destination,
                recovery_command=f"matchvet doctor --store {database_path}",
            )
        return {
            "application_id": application_id,
            "schema_version": schema_version,
            "migration_count": len(migration_rows),
            "integrity": "ok",
            "foreign_key_violations": 0,
            "journal_mode": "wal",
        }
    finally:
        connection.close()


def _validate_backup_compatibility(manifest: BackupManifest, destination: Path) -> None:
    if manifest.payload.get("application_id") != APPLICATION_ID:
        raise T17Error(
            "MV-T17-BACKUP-INCOMPATIBLE",
            "The backup application identity is incompatible with this MatchVet build.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {destination}.new",
        )
    schema_version = manifest.payload.get("schema_version_authoritative")
    if type(schema_version) is not int or schema_version < 1 or schema_version > len(MIGRATIONS):
        raise T17Error(
            "MV-T17-BACKUP-INCOMPATIBLE",
            "The backup schema version is not a supported migration-history prefix.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {destination}.new",
        )
    checksums = manifest.payload.get("migration_checksums")
    expected = [migration.checksum for migration in MIGRATIONS[:schema_version]]
    if checksums != expected:
        raise T17Error(
            "MV-T17-BACKUP-INCOMPATIBLE",
            "The backup migration checksums are not a known valid prefix.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {destination}.new",
        )


def _expected_backup_identity(payload: Mapping[str, object]) -> str:
    pending = dict(_normalise_mapping(payload))
    pending["backup_id"] = "pending"
    return f"backup-{digest_bytes(canonical_json(pending))[:16]}"


def _validate_backup_identity(manifest: BackupManifest, destination: Path) -> None:
    if manifest.identity != _expected_backup_identity(manifest.payload):
        raise T17Error(
            "MV-T17-BACKUP-IDENTITY_MISMATCH",
            "The backup identity does not match its canonical manifest content.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {destination}.new",
        )


def _verify_backup_contents(
    root: Path,
    manifest: BackupManifest,
    *,
    readback: bool,
    allow_marker: bool = False,
    database_path_override: Path | None = None,
) -> dict[str, object]:
    _validate_backup_compatibility(manifest, root)
    if database_path_override is None:
        _verify_bundle_layout(root, manifest, "BACKUP", allow_marker=allow_marker)
    members = _backup_members(manifest)
    database_member = members[0]
    database_path = (
        database_path_override
        if database_path_override is not None
        else _bundle_member_path(root, str(database_member["path"]), "MV-T17-BACKUP-PATH_INVALID")
    )
    if not database_path.is_file():
        raise T17Error(
            "MV-T17-BACKUP-READBACK_FAILED" if readback else "MV-T17-BACKUP-MEMBER_MISSING",
            "The backup database member is missing.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --verify {root}",
        )
    actual_database = digest_file(database_path)
    expected_database = (_member_length(database_member), str(database_member["sha256"]))
    if actual_database != expected_database:
        raise T17Error(
            "MV-T17-BACKUP-READBACK_FAILED" if readback else "MV-T17-BACKUP-DIGEST_MISMATCH",
            "The backup database failed SHA-256 verification.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {root}.new",
        )
    database_details = _verify_sqlite_database(
        database_path,
        operation="BACKUP",
        expected_schema_version=cast(int, manifest.payload["schema_version_authoritative"]),
        expected_migrations=tuple(cast(list[str], manifest.payload["migration_checksums"])),
        destination=root,
    )

    seen_paths: set[str] = set()
    seen_digests: set[str] = set()
    for member in members[1:]:
        path_text = str(member["path"])
        digest = str(member["sha256"])
        expected_path = (Path("objects") / "sha256" / digest[:2] / digest).as_posix()
        if (
            path_text in seen_paths
            or digest in seen_digests
            or path_text != expected_path
            or member.get("relative_path") != expected_path
            or path_text in {BACKUP_MANIFEST_NAME, COMPLETION_MARKER_NAME}
        ):
            raise T17Error(
                "MV-T17-BACKUP-MANIFEST_INVALID",
                "Backup object members are not a unique canonical object set.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        seen_paths.add(path_text)
        seen_digests.add(digest)
        object_path = _bundle_member_path(root, path_text, "MV-T17-BACKUP-PATH_INVALID")
        if not object_path.is_file():
            raise T17Error(
                "MV-T17-BACKUP-READBACK_FAILED" if readback else "MV-T17-BACKUP-MEMBER_MISSING",
                f"The backup object {path_text} is missing.",
                destination=root,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet backup --verify {root}",
            )
        if digest_file(object_path) != (_member_length(member), digest):
            raise T17Error(
                "MV-T17-BACKUP-READBACK_FAILED" if readback else "MV-T17-BACKUP-DIGEST_MISMATCH",
                f"The backup object {path_text} failed SHA-256 verification.",
                destination=root,
                manifest_digest=manifest.digest,
                recovery_command=f"matchvet backup --destination {root}.new",
            )

    catalog = _artifact_catalog_rows(database_path, destination=root)
    catalog_by_digest = {str(row["digest"]): row for row in catalog}
    if set(catalog_by_digest) != seen_digests or len(catalog) != len(seen_digests):
        raise T17Error(
            "MV-T17-BACKUP-OBJECT_SET_MISMATCH",
            "The backup object set does not match the database artifact catalog.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet backup --destination {root}.new",
        )
    manifest_by_digest = {str(member["sha256"]): member for member in members[1:]}
    for digest, row in catalog_by_digest.items():
        member = manifest_by_digest[digest]
        for key in (
            "artifact_id",
            "media_type",
            "byte_length",
            "relative_path",
            "created_at_utc",
            "retention_class",
        ):
            if member.get(key) != row[key]:
                raise T17Error(
                    "MV-T17-BACKUP-METADATA_MISMATCH",
                    f"Backup metadata for artifact {digest} does not match the database.",
                    destination=root,
                    manifest_digest=manifest.digest,
                    recovery_command=f"matchvet backup --destination {root}.new",
                )
    _validate_backup_identity(manifest, root)
    return {
        **database_details,
        "database_digest": str(database_member["sha256"]),
        "object_count": len(seen_digests),
        "state": "COMPLETE",
    }


def _current_schema_backup_manifest(
    root: Path, database_path: Path, source_manifest: BackupManifest
) -> BackupManifest:
    database_member = cast(Mapping[str, object], source_manifest.payload["database"])
    byte_length, sha256 = digest_file(database_path)
    current_database_member = {
        **dict(database_member),
        "byte_length": byte_length,
        "sha256": sha256,
    }
    raw_objects = source_manifest.payload.get("objects")
    if not isinstance(raw_objects, list):
        raise T17Error(
            "MV-T17-BACKUP-MANIFEST_INVALID",
            "Backup object members are invalid.",
            destination=root,
            manifest_digest=source_manifest.digest,
        )
    object_members = [dict(cast(Mapping[str, object], item)) for item in raw_objects]
    return _build_backup_manifest(
        current_database_member,
        object_members,
        schema_version=len(MIGRATIONS),
        migration_checksums=tuple(migration.checksum for migration in MIGRATIONS),
    )


def _online_backup(source: Path, target: Path) -> None:
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = _readonly_connection(source)
        target_connection = sqlite3.connect(target, isolation_level=None)
        target_connection.execute("PRAGMA foreign_keys = ON")
        target_connection.execute("PRAGMA synchronous = FULL")
        source_connection.backup(target_connection)
        target_connection.commit()
        descriptor = os.open(target, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(target.parent)
    except (OSError, sqlite3.DatabaseError) as error:
        raise T17Error(
            "MV-T17-BACKUP-ONLINE_BACKUP_FAILED",
            f"SQLite online backup could not be completed: {source}.",
            source=source,
            recovery_command=f"matchvet backup --destination {target.parent}",
        ) from error
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        _remove_sqlite_sidecars(target)


def _remove_sqlite_sidecars(database_path: Path) -> None:
    for sidecar in (
        database_path.with_name(database_path.name + "-wal"),
        database_path.with_name(database_path.name + "-shm"),
    ):
        sidecar.unlink(missing_ok=True)


def _require_complete_audit_for_export(
    audit: MatchweekAudit,
    source: Path,
    destination: Path,
) -> None:
    if audit.publication_state.value != "COMPLETE":
        raise T17Error(
            "MV-T17-EXPORT-INCOMPLETE",
            "Only a COMPLETE Matchweek Audit can be exported.",
            status="INCOMPLETE",
            source=source,
            destination=destination,
            recovery_command=f"matchvet report --store {source}",
        )
    run = audit.payload.get("run")
    if (
        isinstance(run, Mapping)
        and run.get("run_id") not in (None, "")
        and run.get("state") != "COMPLETE"
    ):
        raise T17Error(
            "MV-T17-EXPORT-INCOMPLETE",
            "The associated research run is not COMPLETE; no completed export was created.",
            status="INCOMPLETE",
            source=source,
            destination=destination,
            recovery_command=f"matchvet resume {run.get('run_id')}",
        )


def _artifact_digest_for_t16(
    audit: MatchweekAudit, source: Path, destination: Path | None = None
) -> str:
    digest = digest_bytes(audit.to_bytes())
    connection = _readonly_connection(source)
    try:
        row = connection.execute(
            "SELECT 1 FROM artifacts WHERE digest = ? AND media_type = ?",
            (digest, T16_AUDIT_MEDIA_TYPE),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise T17Error(
            "MV-T17-EXPORT-AUDIT_DIGEST_MISMATCH",
            "The complete audit artifact is not present in the authoritative catalog.",
            source=source,
            destination=destination,
            recovery_command=f"matchvet doctor --store {source}",
        )
    return digest


def _member_payload(path: str, kind: str, media_type: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "kind": kind,
        "media_type": media_type,
        "byte_length": len(content),
        "sha256": digest_bytes(content),
    }


def _raw_export_members(
    database_path: Path,
    *,
    include_raw_evidence: bool,
    destination: Path | None = None,
) -> tuple[list[dict[str, object]], dict[str, Path], list[dict[str, object]]]:
    connection = _readonly_connection(database_path)
    try:
        rows = connection.execute(
            """
            SELECT c.capture_id, c.artifact_digest, c.retention_status,
                   s.redistributable, s.allowed_use, 'SOURCE_CAPTURE', 'RETAINED'
            FROM source_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            UNION ALL
            SELECT c.capture_id, c.artifact_digest, c.retention_status,
                   s.redistributable, s.allowed_use, 'EVIDENCE_CAPTURE', c.capture_kind
            FROM evidence_captures AS c
            JOIN source_identities AS s ON s.source_id = c.source_id
            ORDER BY capture_id
            """
        ).fetchall()
        members_by_digest: dict[str, dict[str, object]] = {}
        source_paths: dict[str, Path] = {}
        omissions: list[dict[str, object]] = []
        for row in rows:
            capture_id = str(row[0])
            digest_value = row[1]
            retention_status = str(row[2]).upper()
            redistributable = bool(row[3])
            allowed_use = str(row[4]).upper()
            capture_kind = str(row[6]).upper()
            if not include_raw_evidence:
                omissions.append({"identifier": capture_id, "reason": "RAW_EVIDENCE_NOT_REQUESTED"})
                continue
            if capture_kind == "CITATION_ONLY" or digest_value is None:
                omissions.append({"identifier": capture_id, "reason": "CITATION_ONLY"})
                continue
            if (
                retention_status != "RETAIN_REUSABLE"
                or not redistributable
                or allowed_use == "CITATION_ONLY"
            ):
                omissions.append(
                    {"identifier": capture_id, "reason": "RAW_EVIDENCE_RIGHTS_RESTRICTED"}
                )
                continue
            digest = str(digest_value)
            metadata = connection.execute(
                """
                SELECT media_type, byte_length, relative_path
                FROM artifacts WHERE digest = ?
                """,
                (digest,),
            ).fetchone()
            if metadata is None:
                raise T17Error(
                    "MV-T17-EXPORT-SOURCE_INTEGRITY",
                    f"Raw evidence artifact {digest} is not catalogued.",
                    source=database_path,
                    destination=destination,
                    recovery_command=f"matchvet doctor --store {database_path}",
                )
            media_type = str(metadata[0])
            byte_length = int(metadata[1])
            relative_path = str(metadata[2])
            object_path = _catalog_object_path(
                database_path.parent,
                digest,
                relative_path,
                source=database_path,
                destination=destination,
            )
            try:
                actual_length, actual_digest = digest_file(object_path)
            except OSError as error:
                raise T17Error(
                    "MV-T17-EXPORT-SOURCE_INTEGRITY",
                    f"Raw evidence artifact {digest} could not be read.",
                    source=database_path,
                    destination=destination,
                    recovery_command=f"matchvet doctor --store {database_path}",
                ) from error
            if (actual_length, actual_digest) != (byte_length, digest):
                raise T17Error(
                    "MV-T17-EXPORT-SOURCE_INTEGRITY",
                    f"Raw evidence artifact {digest} failed digest verification.",
                    source=database_path,
                    destination=destination,
                    recovery_command=f"matchvet doctor --store {database_path}",
                )
            path = f"evidence/sha256/{digest[:2]}/{digest}"
            member = members_by_digest.get(digest)
            if member is None:
                member = {
                    "path": path,
                    "kind": "RAW_EVIDENCE",
                    "media_type": media_type,
                    "byte_length": byte_length,
                    "sha256": digest,
                    "capture_ids": [capture_id],
                    "rights": {
                        "retention_status": retention_status,
                        "redistributable": redistributable,
                    },
                }
                members_by_digest[digest] = member
                source_paths[path] = object_path
            else:
                ids = member.get("capture_ids")
                if isinstance(ids, list):
                    ids.append(capture_id)
        for member in members_by_digest.values():
            ids = member.get("capture_ids")
            if isinstance(ids, list):
                ids.sort()
        omissions.sort(key=lambda item: (str(item["identifier"]), str(item["reason"])))
        return list(members_by_digest.values()), source_paths, omissions
    finally:
        connection.close()


def _catalog_object_path(
    base: Path,
    digest: str,
    relative_path: str,
    *,
    source: Path | None = None,
    destination: Path | None = None,
) -> Path:
    expected = Path("objects") / "sha256" / digest[:2] / digest
    if relative_path != expected.as_posix():
        raise T17Error(
            "MV-T17-EXPORT-SOURCE_INTEGRITY",
            f"Catalogued artifact {digest} has an invalid content-addressed path.",
            source=source,
            destination=destination,
        )
    candidate = (base / relative_path).resolve(strict=False)
    if not candidate.is_relative_to(base.resolve()) or candidate.is_symlink():
        raise T17Error(
            "MV-T17-EXPORT-SOURCE_INTEGRITY",
            f"Catalogued artifact {digest} has an unsafe path.",
            source=source,
            destination=destination,
        )
    return candidate


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro",
            uri=True,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.DatabaseError as error:
        raise T17Error(
            "MV-T17-SOURCE-UNREADABLE",
            f"SQLite source could not be opened read-only: {database_path}.",
            source=database_path,
        ) from error


def _estimate_for_bytes(byte_count: int, *, copies: int = 1) -> ResourceEstimate:
    if copies < 1:
        raise ValueError("A resource estimate requires at least one copy.")
    return ResourceEstimate(
        storage_growth_bytes=max(1, byte_count) * copies,
        peak_memory_bytes=64 * MIB,
        duration_seconds=max(1, byte_count // (10 * MIB) + 1),
        network_bytes=0,
        cpu_heavy_operations=1,
    )


def _estimated_file_bytes(path: Path) -> int:
    try:
        if path.is_file() and not path.is_symlink():
            return max(0, path.stat().st_size)
    except OSError:
        pass
    return 0


def _estimated_database_and_objects(database_path: Path) -> int:
    total = sum(
        _estimated_file_bytes(database_path.with_name(database_path.name + suffix))
        for suffix in ("", "-wal", "-shm")
    )
    try:
        total += sum(_catalog_byte_length(row) for row in _artifact_catalog_rows(database_path))
    except OSError, T17Error, sqlite3.DatabaseError:
        return max(1, total)
    return max(1, total)


def _observation_for_destination(
    *,
    database_path: Path,
    destination: Path,
    supplied: ResourceObservation | None,
) -> ResourceObservation:
    observation = supplied or observe_resources(database_path)
    free_space = observation.free_space_bytes
    for candidate in (database_path.parent, destination.parent):
        try:
            free_space = min(
                free_space, shutil.disk_usage(_nearest_existing_parent(candidate)).free
            )
        except OSError:
            continue
    return replace(observation, free_space_bytes=free_space)


def _nearest_existing_parent(path: Path) -> Path:
    current = path.resolve(strict=False)
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _with_paths(error: T17Error, source: Path, destination: Path) -> T17Error:
    return T17Error(
        error.code,
        error.message,
        status=error.status,
        recovery_command=error.recovery_command,
        source=source,
        destination=destination,
        manifest_digest=error.manifest_digest,
    )


def _reject_export_targets(destination: Path, partial: Path) -> None:
    _reject_bundle_targets(destination, partial, "EXPORT")


def _reject_bundle_targets(destination: Path, partial: Path, operation: str) -> None:
    if os.path.lexists(destination):
        raise T17Error(
            f"MV-T17-{operation}-DESTINATION_EXISTS",
            (
                f"The {operation.lower()} destination already exists; "
                "immutable bundles are never overwritten."
            ),
            destination=destination,
            recovery_command=f"matchvet {operation.lower()} --destination {destination}.new",
        )
    if os.path.lexists(partial):
        raise T17Error(
            f"MV-T17-{operation}-PARTIAL_EXISTS",
            (
                f"An incomplete {operation.lower()} partial target already exists; "
                "it was left untouched."
            ),
            destination=partial,
            recovery_command=f"matchvet {operation.lower()} --destination {destination}.new",
        )


def _partial_path(destination: Path) -> Path:
    return destination.with_name(destination.name + ".partial")


def _private_stage(private_root: Path, operation: str, identity: str) -> Path:
    return private_root / "staging" / "t17" / operation / f"{identity}.{uuid.uuid4().hex}.partial"


def _require_bundle_directory(path: Path, operation: str) -> Path:
    if path.is_symlink():
        raise T17Error(
            f"MV-T17-{operation}-BUNDLE_UNSAFE",
            f"The {operation.lower()} bundle path is a symbolic link.",
            destination=path,
            recovery_command=f"matchvet {operation.lower()}",
        )
    root = _resolved_path(path)
    if root.is_symlink() or not root.is_dir():
        raise T17Error(
            f"MV-T17-{operation}-BUNDLE_MISSING",
            f"The {operation.lower()} bundle directory does not exist.",
            destination=root,
            recovery_command=f"matchvet {operation.lower()}",
        )
    return root


def _read_marker(path: Path, operation: str, destination: Path) -> CompletionMarker:
    try:
        marker = CompletionMarker.from_bytes(path.read_bytes())
    except T17Error as error:
        raise _with_paths(
            error,
            destination,
            destination,
        ) from error
    if marker.payload.get("kind") != operation:
        raise T17Error(
            f"MV-T17-{operation}-MARKER_KIND_MISMATCH",
            f"The completion marker is not a {operation.lower()} marker.",
            destination=destination,
            recovery_command=f"matchvet {operation.lower()}",
        )
    identity = str(marker.payload["identity"])
    expected_prefix = f"{operation.lower()}-"
    if not identity.startswith(expected_prefix):
        raise T17Error(
            f"MV-T17-{operation}-MARKER_IDENTITY_MISMATCH",
            f"The completion marker identity is not a {operation.lower()} identity.",
            destination=destination,
            recovery_command=f"matchvet {operation.lower()}",
        )
    return marker


def _read_export_manifest(path: Path, destination: Path) -> ExportManifest:
    try:
        return ExportManifest.from_bytes(path.read_bytes())
    except FileNotFoundError as error:
        raise T17Error(
            "MV-T17-EXPORT-MANIFEST_MISSING",
            "The export manifest is missing.",
            destination=destination,
            recovery_command=f"matchvet export --destination {destination}",
        ) from error
    except (OSError, T17Error) as error:
        if isinstance(error, T17Error):
            raise _with_paths(error, destination, destination) from error
        raise T17Error(
            "MV-T17-EXPORT-READBACK_FAILED",
            "The export manifest could not be read.",
            destination=destination,
            recovery_command=f"matchvet export --destination {destination}",
        ) from error


def _read_backup_manifest(path: Path, destination: Path) -> BackupManifest:
    try:
        return BackupManifest.from_bytes(path.read_bytes())
    except FileNotFoundError as error:
        raise T17Error(
            "MV-T17-BACKUP-MANIFEST_MISSING",
            "The backup manifest is missing.",
            destination=destination,
            recovery_command=f"matchvet backup --destination {destination}.new",
        ) from error
    except (OSError, T17Error) as error:
        if isinstance(error, T17Error):
            raise _with_paths(error, destination, destination) from error
        raise T17Error(
            "MV-T17-BACKUP-READBACK_FAILED",
            "The backup manifest could not be read.",
            destination=destination,
            recovery_command=f"matchvet backup --verify {destination}",
        ) from error


def _bundle_member_path(root: Path, relative_path: str, code: str) -> Path:
    path = Path(relative_path)
    if (
        not relative_path
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise T17Error(code, f"Bundle member path is unsafe: {relative_path}.", destination=root)
    candidate = root / path
    if not candidate.resolve(strict=False).is_relative_to(root.resolve()) or candidate.is_symlink():
        raise T17Error(code, f"Bundle member path is unsafe: {relative_path}.", destination=root)
    for parent in candidate.relative_to(root).parents:
        if parent == Path("."):
            continue
        if (root / parent).is_symlink():
            raise T17Error(
                code, f"Bundle member path is unsafe: {relative_path}.", destination=root
            )
    return candidate


def _verify_export_without_marker(root: Path, manifest: ExportManifest) -> None:
    _verify_bundle_layout(root, manifest, "EXPORT", allow_marker=False)
    members = manifest.payload["members"]
    assert isinstance(members, list)
    for raw_member in members:
        assert isinstance(raw_member, Mapping)
        member = cast(Mapping[str, object], raw_member)
        path = _bundle_member_path(root, str(member["path"]), "MV-T17-EXPORT-PATH_INVALID")
        if not path.is_file():
            raise T17Error("MV-T17-EXPORT-MEMBER_MISSING", f"Export member {path.name} is missing.")
        actual = digest_file(path)
        expected = (_member_length(member), str(member["sha256"]))
        if actual != expected:
            raise T17Error(
                "MV-T17-EXPORT-READBACK_FAILED",
                f"Export member {member['path']} failed partial read-back verification.",
            )
    manifest_path = root / EXPORT_MANIFEST_NAME
    if not manifest_path.is_file() or digest_file(manifest_path) != (
        len(manifest.to_bytes()),
        manifest.digest,
    ):
        raise T17Error(
            "MV-T17-EXPORT-READBACK_FAILED", "Export manifest failed partial verification."
        )
    _verify_export_semantics(root, manifest)


def _verify_export_semantics(root: Path, manifest: ExportManifest) -> None:
    member_by_kind = _validate_export_member_contract(manifest, root)
    audit_member = member_by_kind.get("AUDIT")
    report_member = member_by_kind.get("REPORT")
    if audit_member is None or report_member is None:
        raise T17Error(
            "MV-T17-EXPORT-MEMBER_MISSING",
            "The export must contain audit.json and report.md members.",
            destination=root,
            manifest_digest=manifest.digest,
        )
    audit_path = _bundle_member_path(root, str(audit_member["path"]), "MV-T17-EXPORT-PATH_INVALID")
    report_path = _bundle_member_path(
        root, str(report_member["path"]), "MV-T17-EXPORT-PATH_INVALID"
    )
    try:
        audit_value = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(audit_value, Mapping):
            raise ValueError("audit root is not an object")
        audit = MatchweekAudit.from_dict(cast(Mapping[str, object], audit_value))
        report_bytes = report_path.read_bytes()
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        T16Error,
        T17Error,
        ValueError,
    ) as error:
        raise T17Error(
            "MV-T17-EXPORT-AUDIT_INVALID",
            "The staged exported audit/report cannot be parsed and verified.",
            destination=root,
            manifest_digest=manifest.digest,
        ) from error
    if audit.publication_state.value != "COMPLETE":
        raise T17Error(
            "MV-T17-EXPORT-INCOMPLETE",
            "The staged exported audit is not complete.",
            status="INCOMPLETE",
            destination=root,
            manifest_digest=manifest.digest,
        )
    if report_bytes != render_markdown_report(audit).encode("utf-8"):
        raise T17Error(
            "MV-T17-EXPORT-REPORT_MISMATCH",
            "The staged exported report does not match the deterministic T16 rendering.",
            destination=root,
            manifest_digest=manifest.digest,
        )
    _validate_export_audit_metadata(
        manifest,
        audit,
        audit_bytes=audit.to_bytes(),
        report_bytes=report_bytes,
        destination=root,
    )


def _validate_export_member_contract(
    manifest: ExportManifest, root: Path
) -> dict[str, Mapping[str, object]]:
    members = manifest.payload["members"]
    assert isinstance(members, list)
    member_by_kind: dict[str, Mapping[str, object]] = {}
    seen_paths: set[str] = set()
    for raw_member in members:
        assert isinstance(raw_member, Mapping)
        member = cast(Mapping[str, object], raw_member)
        path = str(member["path"])
        kind = member.get("kind")
        if not isinstance(kind, str) or kind not in {"AUDIT", "REPORT", "RAW_EVIDENCE"}:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                f"Export member kind is unsupported: {kind!r}.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if path in seen_paths or path in {EXPORT_MANIFEST_NAME, COMPLETION_MARKER_NAME}:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                f"Export member path is duplicated or reserved: {path}.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        seen_paths.add(path)
        if kind in member_by_kind and kind in {"AUDIT", "REPORT"}:
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                f"The export contains duplicate member kind {kind}.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if kind == "AUDIT" and (
            path != EXPORT_AUDIT_NAME or member.get("media_type") != T16_AUDIT_MEDIA_TYPE
        ):
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                "The audit member path or media type is invalid.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if kind == "REPORT" and (
            path != EXPORT_REPORT_NAME or member.get("media_type") != T16_REPORT_MEDIA_TYPE
        ):
            raise T17Error(
                "MV-T17-EXPORT-MANIFEST_INVALID",
                "The report member path or media type is invalid.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if kind == "RAW_EVIDENCE":
            digest = str(member["sha256"])
            expected_path = f"evidence/sha256/{digest[:2]}/{digest}"
            rights = member.get("rights")
            capture_ids = member.get("capture_ids")
            if (
                path != expected_path
                or not isinstance(rights, Mapping)
                or rights.get("retention_status") != "RETAIN_REUSABLE"
                or rights.get("redistributable") is not True
                or not isinstance(capture_ids, list)
                or any(not isinstance(item, str) for item in capture_ids)
                or capture_ids != sorted(set(capture_ids))
            ):
                raise T17Error(
                    "MV-T17-EXPORT-MANIFEST_INVALID",
                    f"Raw evidence member {path} is not rights-safe and canonical.",
                    destination=root,
                    manifest_digest=manifest.digest,
                )
        member_by_kind[kind] = member
    if "AUDIT" not in member_by_kind or "REPORT" not in member_by_kind:
        raise T17Error(
            "MV-T17-EXPORT-MEMBER_MISSING",
            "The export must contain audit.json and report.md members.",
            destination=root,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {root}",
        )
    return member_by_kind


def _validate_export_audit_metadata(
    manifest: ExportManifest,
    audit: MatchweekAudit,
    *,
    audit_bytes: bytes,
    report_bytes: bytes,
    destination: Path,
) -> None:
    expected_versions = {
        "audit_schema_version": audit.payload["schema_version"],
        "preference_set": audit.payload["preference_set"],
        "selection_policy": audit.payload["selection_policy"],
    }
    if (
        manifest.payload.get("matchweek_id") != audit.payload.get("matchweek_id")
        or manifest.payload.get("audit_id") != audit.audit_id
        or manifest.payload.get("mode") != audit.mode.value
        or manifest.payload.get("audit_digest") != audit.audit_digest
    ):
        raise T17Error(
            "MV-T17-EXPORT-AUDIT_IDENTITY_MISMATCH",
            "The exported audit identity does not match manifest.json.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {destination}",
        )
    if (
        manifest.payload.get("audit_artifact_digest") != digest_bytes(audit_bytes)
        or manifest.payload.get("report_digest") != digest_bytes(report_bytes)
        or manifest.payload.get("reproducibility") != audit.reproducibility
        or manifest.payload.get("versions") != expected_versions
        or manifest.payload.get("run", {}) != audit.payload.get("run", {})
    ):
        raise T17Error(
            "MV-T17-EXPORT-METADATA_MISMATCH",
            "The exported reproducibility or version metadata does not match the audit.",
            destination=destination,
            manifest_digest=manifest.digest,
            recovery_command=f"matchvet export --destination {destination}",
        )


def _verify_bundle_layout(
    root: Path,
    manifest: BackupManifest | ExportManifest,
    operation: str,
    *,
    allow_marker: bool,
) -> None:
    members = manifest.payload.get("members")
    if members is None:
        expected_files = {BACKUP_MANIFEST_NAME}
        objects = manifest.payload.get("objects")
        if isinstance(objects, list):
            expected_files.update(
                str(item["path"]) for item in objects if isinstance(item, Mapping)
            )
        database = manifest.payload.get("database")
        if isinstance(database, Mapping):
            expected_files.add(str(database["path"]))
    elif isinstance(members, list):
        expected_files = {EXPORT_MANIFEST_NAME}
        expected_files.update(str(item["path"]) for item in members if isinstance(item, Mapping))
    else:
        raise T17Error(
            f"MV-T17-{operation}-MANIFEST_INVALID",
            "Bundle manifest members are invalid.",
            destination=root,
            manifest_digest=manifest.digest,
        )
    if allow_marker:
        expected_files.add(COMPLETION_MARKER_NAME)
    expected_files = {Path(path).as_posix() for path in expected_files}
    try:
        entries = list(root.rglob("*"))
    except OSError as error:
        raise T17Error(
            f"MV-T17-{operation}-READBACK_FAILED",
            f"The bundle layout could not be inspected: {root}.",
            destination=root,
            manifest_digest=manifest.digest,
        ) from error
    for entry in entries:
        relative = entry.relative_to(root).as_posix()
        if entry.is_symlink() or (not entry.is_file() and not entry.is_dir()):
            raise T17Error(
                f"MV-T17-{operation}-PATH_INVALID",
                f"Bundle contains an unsafe entry: {relative}.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if entry.is_file() and relative not in expected_files:
            raise T17Error(
                f"MV-T17-{operation}-UNEXPECTED_MEMBER",
                f"Bundle contains an unmanifested file: {relative}.",
                destination=root,
                manifest_digest=manifest.digest,
            )
        if entry.is_dir() and not any(
            expected.startswith(relative + "/") for expected in expected_files
        ):
            raise T17Error(
                f"MV-T17-{operation}-UNEXPECTED_MEMBER",
                f"Bundle contains an unmanifested directory: {relative}.",
                destination=root,
                manifest_digest=manifest.digest,
            )


def _write_bytes_verified(path: Path, content: bytes) -> None:
    _ensure_directory(path.parent, _nearest_existing_parent(path.parent))
    partial = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with partial.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if digest_file(partial) != (len(content), digest_bytes(content)):
            raise T17Error(
                "MV-T17-WRITE-READBACK_FAILED", f"File failed write verification: {path}."
            )
        os.replace(partial, path)
        _fsync_directory(path.parent)
        if digest_file(path) != (len(content), digest_bytes(content)):
            raise T17Error(
                "MV-T17-WRITE-READBACK_FAILED", f"File failed read-back verification: {path}."
            )
    except T17Error:
        partial.unlink(missing_ok=True)
        raise
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise T17Error("MV-T17-WRITE_FAILED", f"File could not be written: {path}.") from error


def _copy_private_source(source: Path, target: Path, length: int, digest: str) -> None:
    _copy_stream(source, target, length, digest, "MV-T17-EXPORT-SOURCE_READBACK_FAILED")


def _copy_file_verified(
    source: Path,
    target: Path,
    length: int,
    digest: str,
    *,
    error_code: str = "MV-T17-EXPORT-READBACK_FAILED",
) -> None:
    _copy_stream(source, target, length, digest, error_code)


def _copy_stream(source: Path, target: Path, length: int, digest: str, error_code: str) -> None:
    if source.is_symlink() or not source.is_file():
        raise T17Error(error_code, f"Copy source is not a regular file: {source}.")
    _ensure_directory(target.parent, _nearest_existing_parent(target.parent))
    partial = target.parent / f".{target.name}.{uuid.uuid4().hex}.partial"
    try:
        with source.open("rb") as source_stream, partial.open("wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        if digest_file(partial) != (length, digest):
            raise T17Error(error_code, f"Copied file failed digest verification: {source}.")
        os.replace(partial, target)
        _fsync_directory(target.parent)
        if digest_file(target) != (length, digest):
            raise T17Error(error_code, f"Copied file failed read-back verification: {target}.")
    except T17Error:
        partial.unlink(missing_ok=True)
        raise
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise T17Error(
            error_code, f"Copied file could not be read or written: {target}."
        ) from error


def _ensure_directory(path: Path, boundary: Path) -> None:
    target = path.absolute()
    base = boundary.absolute()
    try:
        relative = target.relative_to(base)
    except ValueError as error:
        raise T17Error(
            "MV-T17-PATH-OUTSIDE_BOUNDARY", f"Path leaves its operation boundary: {path}."
        ) from error
    _ensure_directory_tree(base)
    current = base
    for component in relative.parts:
        current /= component
        try:
            item = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            _fsync_directory(current.parent)
            continue
        except OSError as error:
            raise T17Error(
                "MV-T17-PATH-UNREADABLE", f"Directory cannot be inspected: {current}."
            ) from error
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
            raise T17Error(
                "MV-T17-PATH-UNSAFE", f"Directory component is not a real directory: {current}."
            )


def _ensure_directory_tree(path: Path) -> None:
    target = path.absolute()
    missing: list[Path] = []
    current = target
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    if current.exists():
        item = current.lstat()
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
            raise T17Error(
                "MV-T17-PATH-UNSAFE", f"Directory component is not a real directory: {current}."
            )
    for candidate in reversed(missing):
        candidate.mkdir(mode=0o700)
        _fsync_directory(candidate.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_operation_path(path: Path, boundary: Path) -> None:
    if not os.path.lexists(path):
        return
    target = path.absolute()
    base = boundary.absolute()
    if target == base or not target.is_relative_to(base):
        raise T17Error(
            "MV-T17-CLEANUP-BOUNDARY", f"Refusing cleanup outside operation boundary: {path}."
        )
    item = target.lstat()
    if stat.S_ISLNK(item.st_mode) or stat.S_ISREG(item.st_mode):
        target.unlink()
    elif stat.S_ISDIR(item.st_mode):
        shutil.rmtree(target)
    _fsync_directory(base)


def _cleanup_restore_failure(
    private_stage: Path,
    private_root: Path,
    target: Path,
    target_boundary: Path,
    created_target: bool,
    created_objects: list[Path],
) -> None:
    paths: list[tuple[Path, Path]] = [(private_stage, private_root)]
    if created_target:
        paths.append((target, target_boundary))
    paths.extend((path, target_boundary) for path in reversed(created_objects))
    for path, boundary in paths:
        try:
            _remove_operation_path(path, boundary)
        except OSError, T17Error:
            # Cleanup is best effort and must never replace the original failure.
            continue


def _validate_manifest_base(payload: dict[str, object], schema: str, area: str) -> None:
    prefix = f"MV-T17-{area}-MANIFEST_INVALID"
    if payload.get("schema") != schema:
        raise T17Error(prefix, f"{area.title()} manifest schema is invalid.")
    if payload.get("schema_version") != T17_SCHEMA_VERSION:
        raise T17Error(prefix, f"{area.title()} manifest version is incompatible.")
    if payload.get("state") != "COMPLETE":
        raise T17Error(prefix, f"{area.title()} manifest is not complete.")


def _validate_members(value: object, code: str) -> None:
    if not isinstance(value, list):
        raise T17Error(code, "Manifest members are invalid.")
    for member in value:
        if not isinstance(member, Mapping):
            raise T17Error(code, "Manifest member is invalid.")
        _validate_member(member, code)


def _validate_member(member: Mapping[str, object], code: str) -> None:
    path = member.get("path")
    media_type = member.get("media_type")
    byte_length = member.get("byte_length")
    digest = member.get("sha256")
    if (
        not isinstance(path, str)
        or not path
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        or not isinstance(media_type, str)
        or not media_type
        or isinstance(byte_length, bool)
        or not isinstance(byte_length, int)
        or byte_length < 0
        or not isinstance(digest, str)
        or _DIGEST_RE.fullmatch(digest) is None
    ):
        raise T17Error(code, "Manifest member path, media type, length, or digest is invalid.")


def _member_length(member: Mapping[str, object]) -> int:
    value = member.get("byte_length")
    if isinstance(value, bool) or not isinstance(value, int):
        raise T17Error("MV-T17-MANIFEST_INVALID", "Manifest member length is invalid.")
    return value


def _validate_omissions(value: object, code: str) -> None:
    if not isinstance(value, list):
        raise T17Error(code, "Manifest retention omissions are invalid.")
    for item in value:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("identifier"), str)
            or not isinstance(item.get("reason"), str)
        ):
            raise T17Error(code, "Manifest retention omission is invalid.")


def _validate_digest(value: str, label: str, code: str) -> None:
    if _DIGEST_RE.fullmatch(value) is None:
        raise T17Error(code, f"{label} must be a lowercase SHA-256 digest.")


def _normalise_mapping(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise T17Error("MV-T17-MANIFEST_INVALID", "Manifest payload must be a string-keyed object.")
    normalized = _jsonable(value)
    if not isinstance(normalized, dict):
        raise T17Error("MV-T17-MANIFEST_INVALID", "Manifest payload must be an object.")
    return normalized


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _resolved_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError as error:
        raise T17Error("MV-T17-PATH-UNREADABLE", f"Path cannot be resolved: {path}.") from error


__all__ = [
    "BACKUP_DATABASE_NAME",
    "BACKUP_MANIFEST_NAME",
    "BACKUP_SCHEMA",
    "COMPLETION_MARKER_NAME",
    "COMPLETION_SCHEMA",
    "EXPORT_AUDIT_NAME",
    "EXPORT_MANIFEST_NAME",
    "EXPORT_REPORT_NAME",
    "EXPORT_SCHEMA",
    "T17_SCHEMA_VERSION",
    "BackupManifest",
    "BackupResult",
    "CompletionMarker",
    "ExportManifest",
    "ExportResult",
    "OperationPreflight",
    "OperationVerification",
    "RestoreResult",
    "T17Error",
    "backup_store",
    "canonical_json",
    "digest_bytes",
    "digest_file",
    "export_matchweek",
    "preflight_operation",
    "restore_backup",
    "validate_private_target",
    "validate_shared_destination",
    "verify_backup",
    "verify_export",
]

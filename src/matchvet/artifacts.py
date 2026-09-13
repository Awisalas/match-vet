from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from matchvet.store import (
    ArtifactMetadata,
    CanonicalIdentifier,
    Store,
    VersionIdentity,
    termux_private_root,
)

ARTIFACT_MEDIA_TYPE = "application/octet-stream"
MANIFEST_MEDIA_TYPE = "application/vnd.matchvet.snapshot-manifest+json"
MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_RELATIVE_ROOT = Path("objects") / "sha256"
ARTIFACT_STAGING_RELATIVE_ROOT = Path("staging") / "artifacts"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE_RE = re.compile(r"[^\x00-\x20\x7f]+")


class ArtifactError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ManifestError(ArtifactError):
    pass


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: CanonicalIdentifier
    digest: str
    media_type: str
    byte_length: int
    relative_path: str
    created_at_utc: str
    retention_class: str = "PROTECTED"

    def __post_init__(self) -> None:
        if self.artifact_id.kind != "artifact":
            raise ArtifactError("MV-ARTIFACT-ID_INVALID", "Artifact IDs must be typed as artifact.")
        _require_digest(self.digest, "artifact digest")
        if not _MEDIA_TYPE_RE.fullmatch(self.media_type):
            raise ArtifactError("MV-ARTIFACT-MEDIA_TYPE_INVALID", "Artifact media type is invalid.")
        if self.byte_length < 0:
            raise ArtifactError("MV-ARTIFACT-LENGTH_INVALID", "Artifact length cannot be negative.")
        if self.retention_class not in {"PROTECTED", "REUSABLE", "DISPOSABLE"}:
            raise ArtifactError(
                "MV-ARTIFACT-RETENTION_INVALID", "Artifact retention class is invalid."
            )


@dataclass(frozen=True)
class ManifestArtifact:
    artifact_id: CanonicalIdentifier
    digest: str
    media_type: str
    byte_length: int

    def __post_init__(self) -> None:
        if self.artifact_id.kind != "artifact":
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Manifest artifact IDs must be typed as artifact."
            )
        try:
            _require_digest(self.digest, "manifest artifact digest")
        except ArtifactError as error:
            raise ManifestError("MV-MANIFEST-MALFORMED", str(error)) from error
        if not _MEDIA_TYPE_RE.fullmatch(self.media_type):
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest artifact media type is invalid.")
        if self.byte_length < 0:
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest artifact length is invalid.")


@dataclass(frozen=True)
class ManifestVersion:
    version_id: CanonicalIdentifier
    definition_id: CanonicalIdentifier
    kind: str
    name: str
    content_sha256: str
    canonical_contract_version: int

    @classmethod
    def from_identity(cls, version: VersionIdentity) -> ManifestVersion:
        return cls(
            version_id=version.identifier,
            definition_id=version.definition_id,
            kind=version.kind,
            name=version.name,
            content_sha256=version.content_sha256,
            canonical_contract_version=version.canonical_contract_version,
        )

    def __post_init__(self) -> None:
        if self.version_id.kind != "version":
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Manifest version IDs must be typed as version."
            )
        if self.definition_id.kind != "version_definition":
            raise ManifestError(
                "MV-MANIFEST-MALFORMED",
                "Manifest definition IDs must be typed as version_definition.",
            )
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.kind) is None or not self.name:
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest version metadata is incomplete.")
        try:
            _require_digest(self.content_sha256, "manifest version content digest")
        except ArtifactError as error:
            raise ManifestError("MV-MANIFEST-MALFORMED", str(error)) from error
        if self.canonical_contract_version < 1:
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest version contract is invalid.")


@dataclass(frozen=True)
class RetentionOmission:
    identifier: str
    reason: str

    def __post_init__(self) -> None:
        if not self.identifier or not self.reason:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Retention omissions require identifier and reason."
            )


@dataclass(frozen=True)
class ManifestCompleteness:
    state: str
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in {"COMPLETE", "INCOMPLETE"}:
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest completeness state is invalid.")
        if tuple(sorted(set(self.missing))) != self.missing:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Manifest missing items must be sorted and unique."
            )
        if self.state == "COMPLETE" and self.missing:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "A complete manifest cannot list missing items."
            )
        if self.state == "INCOMPLETE" and not self.missing:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "An incomplete manifest must list missing items."
            )


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: CanonicalIdentifier
    matchweek_id: CanonicalIdentifier
    research_cutoff_id: CanonicalIdentifier
    version_manifest_id: CanonicalIdentifier
    research_cutoff_utc: str
    artifacts: tuple[ManifestArtifact, ...]
    versions: tuple[ManifestVersion, ...]
    retention_omissions: tuple[RetentionOmission, ...]
    completeness: ManifestCompleteness
    created_at_utc: str
    verification_state: str = "UNVERIFIED"
    verified_at_utc: str | None = None
    parent_snapshot_id: CanonicalIdentifier | None = None
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, CanonicalIdentifier) or self.snapshot_id.kind != (
            "snapshot_manifest"
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Snapshot IDs must be typed as snapshot_manifest."
            )
        if not isinstance(self.matchweek_id, CanonicalIdentifier) or self.matchweek_id.kind != (
            "matchweek"
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Matchweek IDs must be typed as matchweek."
            )
        if not isinstance(self.research_cutoff_id, CanonicalIdentifier) or (
            self.research_cutoff_id.kind != "research_cutoff"
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Research Cutoff IDs must be typed as research_cutoff."
            )
        if not isinstance(self.version_manifest_id, CanonicalIdentifier) or (
            self.version_manifest_id.kind != "version_manifest"
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED",
                "Version Manifest IDs must be typed as version_manifest.",
            )
        if self.parent_snapshot_id is not None and (
            not isinstance(self.parent_snapshot_id, CanonicalIdentifier)
            or self.parent_snapshot_id.kind != "snapshot_manifest"
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED",
                "Parent Snapshot IDs must be typed as snapshot_manifest.",
            )
        if self.verification_state not in {"VERIFIED", "UNVERIFIED"}:
            raise ManifestError("MV-MANIFEST-MALFORMED", "Manifest verification state is invalid.")
        if self.verification_state == "VERIFIED" and self.verified_at_utc is None:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED",
                "A verified manifest requires an actual verification timestamp.",
            )
        if self.verification_state == "UNVERIFIED" and self.verified_at_utc is not None:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED",
                "An unverified manifest cannot have a verification timestamp.",
            )
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ManifestError(
                "MV-MANIFEST-SCHEMA_UNSUPPORTED", "Snapshot manifest schema is unsupported."
            )
        _require_utc_timestamp(self.research_cutoff_utc, "research cutoff")
        _require_utc_timestamp(self.created_at_utc, "manifest creation time")
        if self.verified_at_utc is not None:
            _require_utc_timestamp(self.verified_at_utc, "manifest verification time")
        artifact_digests = tuple(item.digest for item in self.artifacts)
        if tuple(sorted(artifact_digests)) != artifact_digests or len(set(artifact_digests)) != len(
            artifact_digests
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Manifest artifacts must be sorted and unique."
            )
        version_ids = tuple(item.version_id.value for item in self.versions)
        if tuple(sorted(version_ids)) != version_ids or len(set(version_ids)) != len(version_ids):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Manifest versions must be sorted and unique."
            )
        omission_keys = tuple((item.identifier, item.reason) for item in self.retention_omissions)
        if tuple(sorted(omission_keys)) != omission_keys or len(set(omission_keys)) != len(
            omission_keys
        ):
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Retention omissions must be sorted and unique."
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "artifacts": [
                {
                    "artifact_id": item.artifact_id.value,
                    "byte_length": item.byte_length,
                    "digest": item.digest,
                    "media_type": item.media_type,
                }
                for item in self.artifacts
            ],
            "completeness": {
                "missing": list(self.completeness.missing),
                "state": self.completeness.state,
            },
            "created_at_utc": self.created_at_utc,
            "matchweek_id": self.matchweek_id.value,
            "parent_snapshot_id": (
                self.parent_snapshot_id.value if self.parent_snapshot_id is not None else None
            ),
            "research_cutoff_utc": self.research_cutoff_utc,
            "research_cutoff_id": self.research_cutoff_id.value,
            "retention_omissions": [
                {"identifier": item.identifier, "reason": item.reason}
                for item in self.retention_omissions
            ],
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id.value,
            "versions": [
                {
                    "canonical_contract_version": item.canonical_contract_version,
                    "content_sha256": item.content_sha256,
                    "definition_id": item.definition_id.value,
                    "kind": item.kind,
                    "name": item.name,
                    "version_id": item.version_id.value,
                }
                for item in self.versions
            ],
            "verification_state": self.verification_state,
            "verified_at_utc": self.verified_at_utc,
            "version_manifest_id": self.version_manifest_id.value,
        }

    @property
    def aggregate_sha256(self) -> str:
        return _sha256(_canonical_json(self._payload()))

    def to_bytes(self) -> bytes:
        payload = self._payload()
        payload["aggregate_sha256"] = self.aggregate_sha256
        return _canonical_json(payload)

    @property
    def digest(self) -> str:
        return _sha256(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> SnapshotManifest:
        try:
            if not isinstance(data, bytes):
                raise TypeError("Manifest bytes are required.")
            text = data.decode("utf-8")
            value = json.loads(text)
            if not isinstance(value, dict):
                raise TypeError("Manifest root must be an object.")
            expected_keys = {
                "aggregate_sha256",
                "artifacts",
                "completeness",
                "created_at_utc",
                "matchweek_id",
                "parent_snapshot_id",
                "research_cutoff_utc",
                "research_cutoff_id",
                "retention_omissions",
                "schema_version",
                "snapshot_id",
                "versions",
                "verification_state",
                "verified_at_utc",
                "version_manifest_id",
            }
            if set(value) != expected_keys:
                raise TypeError("Manifest keys are not the canonical set.")
            artifacts = tuple(_manifest_artifact(item) for item in _list(value["artifacts"]))
            versions = tuple(_manifest_version(item) for item in _list(value["versions"]))
            omissions = tuple(
                _retention_omission(item) for item in _list(value["retention_omissions"])
            )
            completeness = _manifest_completeness(value["completeness"])
            manifest = cls(
                snapshot_id=_canonical_identifier(str(value["snapshot_id"]), "snapshot_manifest"),
                matchweek_id=_canonical_identifier(str(value["matchweek_id"]), "matchweek"),
                research_cutoff_utc=_string(value["research_cutoff_utc"]),
                artifacts=artifacts,
                versions=versions,
                retention_omissions=omissions,
                completeness=completeness,
                created_at_utc=_string(value["created_at_utc"]),
                research_cutoff_id=_canonical_identifier(
                    _string(value["research_cutoff_id"]), "research_cutoff"
                ),
                version_manifest_id=_canonical_identifier(
                    _string(value["version_manifest_id"]), "version_manifest"
                ),
                verification_state=_string(value["verification_state"]),
                verified_at_utc=(
                    None if value["verified_at_utc"] is None else _string(value["verified_at_utc"])
                ),
                parent_snapshot_id=(
                    None
                    if value["parent_snapshot_id"] is None
                    else _canonical_identifier(
                        _string(value["parent_snapshot_id"]), "snapshot_manifest"
                    )
                ),
                schema_version=_integer(value["schema_version"]),
            )
            if _string(value["aggregate_sha256"]) != manifest.aggregate_sha256:
                raise ManifestError(
                    "MV-MANIFEST-AGGREGATE_MISMATCH", "Manifest aggregate digest is invalid."
                )
            if manifest.to_bytes() != data:
                raise ManifestError(
                    "MV-MANIFEST-NONCANONICAL", "Manifest JSON is not canonical UTF-8 JSON."
                )
            return manifest
        except ManifestError:
            raise
        except ArtifactError as error:
            raise ManifestError("MV-MANIFEST-MALFORMED", str(error)) from error
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManifestError(
                "MV-MANIFEST-MALFORMED", "Snapshot manifest JSON is malformed."
            ) from error


@dataclass(frozen=True)
class ArtifactInspection:
    missing: tuple[str, ...] = ()
    corrupt: tuple[str, ...] = ()
    orphans: tuple[str, ...] = ()
    unreferenced: tuple[str, ...] = ()
    malformed_manifests: tuple[str, ...] = ()
    staging_orphans: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return not any(
            (
                self.missing,
                self.corrupt,
                self.malformed_manifests,
            )
        )


def _inspect_catalog(
    catalog: tuple[ArtifactMetadata, ...],
    manifest_metadata: Mapping[str, tuple[str | None, ...]],
    manifest_members: Mapping[str, tuple[tuple[str, str], ...]],
    manifest_versions: Mapping[str, tuple[tuple[str, ...], ...]],
    *,
    object_root: Path,
    staging_root: Path,
    base_path: Path,
) -> ArtifactInspection:
    catalog_by_digest = {item.digest: item for item in catalog}
    missing: list[str] = []
    corrupt: list[str] = []
    malformed_manifests: list[str] = []
    referenced = set(manifest_metadata)
    for digest in manifest_metadata:
        referenced.update(member_digest for _, member_digest in manifest_members.get(digest, ()))

    for metadata in catalog:
        object_path = base_path / metadata.relative_path
        if metadata.relative_path != _relative_object_path(metadata.digest):
            corrupt.append(metadata.digest)
            continue
        if not _private_path_components_are_directories(base_path, metadata.relative_path):
            corrupt.append(metadata.digest)
            continue
        if not object_path.is_file() or object_path.is_symlink():
            missing.append(metadata.digest)
        else:
            try:
                _verify_file(object_path, metadata.digest, metadata.byte_length)
            except ArtifactError:
                corrupt.append(metadata.digest)

        if metadata.digest not in manifest_metadata:
            continue
        try:
            manifest = SnapshotManifest.from_bytes(object_path.read_bytes())
            expected_metadata = (
                metadata.digest,
                manifest.snapshot_id.value,
                manifest.matchweek_id.value,
                manifest.research_cutoff_id.value,
                manifest.version_manifest_id.value,
                manifest.research_cutoff_utc,
                manifest.aggregate_sha256,
                manifest.completeness.state,
                str(manifest.schema_version),
                manifest.created_at_utc,
                manifest.verification_state,
                manifest.verified_at_utc,
                manifest.parent_snapshot_id.value
                if manifest.parent_snapshot_id is not None
                else None,
            )
            expected_members = tuple(
                (reference.artifact_id.value, reference.digest) for reference in manifest.artifacts
            )
            expected_versions = tuple(
                (
                    version.version_id.value,
                    version.definition_id.value,
                    version.kind,
                    version.name,
                    version.content_sha256,
                    str(version.canonical_contract_version),
                )
                for version in manifest.versions
            )
            if (
                metadata.media_type != MANIFEST_MEDIA_TYPE
                or manifest.digest != metadata.digest
                or manifest.verification_state != "VERIFIED"
                or manifest.verified_at_utc is None
                or manifest_metadata[metadata.digest] != expected_metadata
                or manifest_members.get(metadata.digest, ()) != expected_members
                or manifest_versions.get(metadata.digest, ()) != expected_versions
            ):
                malformed_manifests.append(metadata.digest)
        except ArtifactError, OSError:
            malformed_manifests.append(metadata.digest)

    object_digests = _scan_object_digests(object_root)
    staging_orphans = _scan_staging_orphans(staging_root, base_path)
    return ArtifactInspection(
        missing=tuple(sorted(set(missing))),
        corrupt=tuple(sorted(set(corrupt))),
        orphans=tuple(sorted(object_digests - set(catalog_by_digest))),
        unreferenced=tuple(sorted(set(catalog_by_digest) - referenced)),
        malformed_manifests=tuple(sorted(set(malformed_manifests))),
        staging_orphans=staging_orphans,
    )


class ArtifactStore:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.object_root = store.path.parent / ARTIFACT_RELATIVE_ROOT
        self.staging_root = store.path.parent / ARTIFACT_STAGING_RELATIVE_ROOT

    def publish_artifact(
        self,
        content: bytes,
        media_type: str = ARTIFACT_MEDIA_TYPE,
        *,
        expected_digest: str | None = None,
        retention_class: str = "PROTECTED",
    ) -> ArtifactRecord:
        self._ensure_writeable()
        if not isinstance(content, bytes):
            raise ArtifactError("MV-ARTIFACT-CONTENT_INVALID", "Artifact content must be bytes.")
        digest = _sha256(content)
        if expected_digest is not None and digest != _require_digest(
            expected_digest, "expected digest"
        ):
            raise ArtifactError(
                "MV-ARTIFACT-DIGEST_MISMATCH",
                "Artifact content does not match the expected digest.",
            )
        record = ArtifactRecord(
            artifact_id=CanonicalIdentifier.new("artifact"),
            digest=digest,
            media_type=media_type,
            byte_length=len(content),
            relative_path=self._relative_path(digest),
            created_at_utc=_utc_now(),
            retention_class=retention_class,
        )
        self._publish_object(content, record)
        try:
            with self.store.transaction() as transaction:
                transaction.record_artifact(
                    ArtifactMetadata(
                        digest=record.digest,
                        artifact_id=record.artifact_id,
                        media_type=record.media_type,
                        byte_length=record.byte_length,
                        relative_path=record.relative_path,
                        created_at_utc=record.created_at_utc,
                        retention_class=record.retention_class,
                    )
                )
        except (sqlite3.DatabaseError, RuntimeError, ValueError) as error:
            raise ArtifactError(
                "MV-ARTIFACT-DB_PUBLICATION_FAILED",
                "Artifact catalog publication failed; the object remains unreferenced.",
            ) from error
        return self._record_or_raise(digest)

    def publish_manifest(self, manifest: SnapshotManifest) -> ArtifactRecord:
        self._ensure_writeable()
        if not isinstance(manifest, SnapshotManifest):
            raise ManifestError("MV-MANIFEST-MALFORMED", "A SnapshotManifest value is required.")
        if manifest.verification_state != "UNVERIFIED" or manifest.verified_at_utc is not None:
            raise ManifestError(
                "MV-MANIFEST-UNVERIFIED",
                "A Snapshot Manifest must be unverified before publication; publication assigns "
                "verification metadata.",
            )
        for reference in manifest.artifacts:
            record = self.verify_artifact(reference.digest)
            if record.artifact_id != reference.artifact_id:
                raise ArtifactError(
                    "MV-MANIFEST-ARTIFACT_ID_MISMATCH",
                    f"Manifest identity does not match artifact {reference.digest}.",
                )
            if (
                record.media_type != reference.media_type
                or record.byte_length != reference.byte_length
            ):
                raise ArtifactError(
                    "MV-MANIFEST-ARTIFACT_METADATA_MISMATCH",
                    f"Manifest metadata does not match artifact {reference.digest}.",
                )
        for version in manifest.versions:
            stored = self.store.version(version.version_id)
            if stored is None or ManifestVersion.from_identity(stored) != version:
                raise ManifestError(
                    "MV-MANIFEST-VERSION_MISMATCH",
                    f"Manifest version {version.version_id.value} is not an exact stored version.",
                )

        existing_digest = self.store.snapshot_manifest_digest_for_snapshot(
            manifest.snapshot_id.value
        )
        if existing_digest is not None:
            existing = self.verify_manifest(existing_digest)
            if _manifest_publication_key(existing) == _manifest_publication_key(manifest):
                return self._record_or_raise(existing_digest)
            # Keep the artifact-first ordering for a conflicting immutable snapshot.  The
            # bounded transaction below will reject the unique snapshot identity and leave
            # only a detectable orphan object for inspection.

        verified_manifest = replace(
            manifest,
            verification_state="VERIFIED",
            verified_at_utc=_utc_now(),
        )
        content = verified_manifest.to_bytes()
        record = ArtifactRecord(
            artifact_id=CanonicalIdentifier.new("artifact"),
            digest=verified_manifest.digest,
            media_type=MANIFEST_MEDIA_TYPE,
            byte_length=len(content),
            relative_path=self._relative_path(verified_manifest.digest),
            created_at_utc=verified_manifest.created_at_utc,
            retention_class="PROTECTED",
        )
        self._publish_object(content, record)
        try:
            with self.store.transaction() as transaction:
                for identifier in (
                    verified_manifest.snapshot_id,
                    verified_manifest.matchweek_id,
                    verified_manifest.research_cutoff_id,
                    verified_manifest.version_manifest_id,
                    verified_manifest.parent_snapshot_id,
                ):
                    if identifier is not None:
                        transaction.add_identifier_if_missing(identifier)
                transaction.record_artifact(
                    ArtifactMetadata(
                        digest=record.digest,
                        artifact_id=record.artifact_id,
                        media_type=record.media_type,
                        byte_length=record.byte_length,
                        relative_path=record.relative_path,
                        created_at_utc=record.created_at_utc,
                        retention_class=record.retention_class,
                    )
                )
                transaction.record_snapshot_manifest(
                    manifest_digest=verified_manifest.digest,
                    snapshot_id=verified_manifest.snapshot_id.value,
                    matchweek_id=verified_manifest.matchweek_id.value,
                    research_cutoff_id=verified_manifest.research_cutoff_id.value,
                    version_manifest_id=verified_manifest.version_manifest_id.value,
                    research_cutoff_utc=verified_manifest.research_cutoff_utc,
                    aggregate_sha256=verified_manifest.aggregate_sha256,
                    completeness_state=verified_manifest.completeness.state,
                    manifest_schema_version=verified_manifest.schema_version,
                    created_at_utc=verified_manifest.created_at_utc,
                    verification_state=verified_manifest.verification_state,
                    verified_at_utc=verified_manifest.verified_at_utc,
                    parent_snapshot_id=(
                        verified_manifest.parent_snapshot_id.value
                        if verified_manifest.parent_snapshot_id is not None
                        else None
                    ),
                )
                for reference in verified_manifest.artifacts:
                    transaction.record_manifest_artifact(
                        verified_manifest.digest,
                        reference.artifact_id.value,
                        reference.digest,
                    )
                for version in verified_manifest.versions:
                    transaction.record_manifest_version(
                        manifest_digest=verified_manifest.digest,
                        version_id=version.version_id.value,
                        definition_id=version.definition_id.value,
                        version_kind=version.kind,
                        name=version.name,
                        content_sha256=version.content_sha256,
                        canonical_contract_version=version.canonical_contract_version,
                    )
        except (sqlite3.DatabaseError, RuntimeError, ValueError) as error:
            raise ArtifactError(
                "MV-ARTIFACT-DB_PUBLICATION_FAILED",
                "Snapshot Manifest catalog publication failed; the object remains unreferenced.",
            ) from error
        return self._record_or_raise(verified_manifest.digest)

    def verify_artifact(self, digest: str) -> ArtifactRecord:
        self._ensure_readable()
        digest = _require_digest(digest, "artifact digest")
        metadata = self.store.artifact_metadata(digest)
        if metadata is None:
            raise ArtifactError(
                "MV-ARTIFACT-NOT_CATALOGUED", f"Artifact {digest} is not catalogued."
            )
        expected_path = self._object_path(digest)
        if metadata.relative_path != self._relative_path(digest):
            raise ArtifactError(
                "MV-ARTIFACT-PATH_MISMATCH", f"Artifact {digest} has an invalid catalog path."
            )
        if not _private_path_components_are_directories(
            self.store.path.parent, metadata.relative_path
        ):
            raise ArtifactError(
                "MV-ARTIFACT-PATH_MISMATCH", f"Artifact {digest} has an unsafe private path."
            )
        _verify_file(expected_path, digest, metadata.byte_length)
        return _record_from_metadata(metadata)

    def read_artifact(self, digest: str) -> bytes:
        record = self.verify_artifact(digest)
        try:
            content = self._object_path(record.digest).read_bytes()
        except OSError as error:
            raise ArtifactError(
                "MV-ARTIFACT-READ_FAILED", f"Artifact {record.digest} could not be read."
            ) from error
        if len(content) != record.byte_length or _sha256(content) != record.digest:
            raise ArtifactError(
                "MV-ARTIFACT-DIGEST_MISMATCH", f"Artifact {record.digest} changed while reading."
            )
        return content

    def verify_manifest(self, digest: str) -> SnapshotManifest:
        record = self.verify_artifact(digest)
        if record.media_type != MANIFEST_MEDIA_TYPE:
            raise ManifestError(
                "MV-MANIFEST-MEDIA_TYPE_INVALID", "Artifact is not a Snapshot Manifest."
            )
        manifest = SnapshotManifest.from_bytes(self.read_artifact(digest))
        if manifest.digest != digest:
            raise ManifestError(
                "MV-MANIFEST-DIGEST_MISMATCH", "Snapshot Manifest digest does not match its path."
            )
        metadata = self.store.snapshot_manifest_metadata(digest)
        if metadata is None:
            raise ManifestError("MV-MANIFEST-NOT_PUBLISHED", "Snapshot Manifest is not catalogued.")
        expected = (
            digest,
            manifest.snapshot_id.value,
            manifest.matchweek_id.value,
            manifest.research_cutoff_id.value,
            manifest.version_manifest_id.value,
            manifest.research_cutoff_utc,
            manifest.aggregate_sha256,
            manifest.completeness.state,
            str(manifest.schema_version),
            manifest.created_at_utc,
            manifest.verification_state,
            manifest.verified_at_utc,
            manifest.parent_snapshot_id.value if manifest.parent_snapshot_id is not None else None,
        )
        if metadata != expected:
            raise ManifestError(
                "MV-MANIFEST-METADATA_MISMATCH", "Manifest catalog metadata is inconsistent."
            )
        if self.store.snapshot_manifest_artifacts(digest) != tuple(
            (reference.artifact_id.value, reference.digest) for reference in manifest.artifacts
        ):
            raise ManifestError(
                "MV-MANIFEST-MEMBERSHIP_MISMATCH", "Manifest artifact membership is inconsistent."
            )
        stored_versions = self.store.snapshot_manifest_versions(digest)
        expected_versions = tuple(
            (
                version.version_id.value,
                version.definition_id.value,
                version.kind,
                version.name,
                version.content_sha256,
                str(version.canonical_contract_version),
            )
            for version in manifest.versions
        )
        if stored_versions != expected_versions:
            raise ManifestError(
                "MV-MANIFEST-MEMBERSHIP_MISMATCH", "Manifest version membership is inconsistent."
            )
        return manifest

    def inspect(self) -> ArtifactInspection:
        self._ensure_readable()
        catalog = self.store.artifact_catalog()
        manifest_digests = self.store.snapshot_manifest_digests()
        manifest_metadata = {
            digest: self.store.snapshot_manifest_metadata(digest) for digest in manifest_digests
        }
        manifest_members = {
            digest: self.store.snapshot_manifest_artifacts(digest) for digest in manifest_digests
        }
        manifest_versions = {
            digest: self.store.snapshot_manifest_versions(digest) for digest in manifest_digests
        }
        if any(value is None for value in manifest_metadata.values()):
            raise sqlite3.DatabaseError(
                "A Snapshot Manifest catalog row disappeared during inspection."
            )
        return _inspect_catalog(
            catalog,
            {digest: value for digest, value in manifest_metadata.items() if value is not None},
            manifest_members,
            manifest_versions,
            object_root=self.object_root,
            staging_root=self.staging_root,
            base_path=self.store.path.parent,
        )

    def _record_or_raise(self, digest: str) -> ArtifactRecord:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None:
            raise ArtifactError(
                "MV-ARTIFACT-CATALOG_MISSING", f"Artifact {digest} was not catalogued."
            )
        return _record_from_metadata(metadata)

    def _ensure_writeable(self) -> None:
        self.store._ensure_write_allowed()

    def _ensure_readable(self) -> None:
        self.store._ensure_connection_owner()

    def _relative_path(self, digest: str) -> str:
        return (ARTIFACT_RELATIVE_ROOT / digest[:2] / digest).as_posix()

    def _object_path(self, digest: str) -> Path:
        return self.store.path.parent / ARTIFACT_RELATIVE_ROOT / digest[:2] / digest

    def _publish_object(self, content: bytes, record: ArtifactRecord) -> None:
        _ensure_private_directory(self.staging_root, self.store.path.parent)
        _ensure_private_directory(self.object_root, self.store.path.parent)
        stage_path = self.staging_root / f".{record.digest}.{uuid.uuid4().hex}.partial"
        try:
            descriptor = os.open(
                stage_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(content):
                    offset += os.write(descriptor, content[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            stage_length, stage_digest = _sha256_file(stage_path)
            if stage_length != record.byte_length or stage_digest != record.digest:
                raise ArtifactError(
                    "MV-ARTIFACT-DIGEST_MISMATCH", "Staged artifact failed verification."
                )

            target = self._object_path(record.digest)
            _ensure_private_directory(target.parent, self.store.path.parent)
            try:
                target_stat = target.lstat()
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None:
                if stat.S_ISLNK(target_stat.st_mode):
                    raise ArtifactError(
                        "MV-ARTIFACT-PATH_MISMATCH", "Artifact path is a symbolic link."
                    ) from None
                if not stat.S_ISREG(target_stat.st_mode):
                    raise ArtifactError(
                        "MV-ARTIFACT-PATH_MISMATCH", "Artifact path is not a regular file."
                    ) from None
                _verify_file(target, record.digest, record.byte_length)
            else:
                try:
                    _atomic_install_no_replace(stage_path, target)
                except FileExistsError:
                    _verify_file(target, record.digest, record.byte_length)
                _fsync_directory(target.parent)
            stage_path.unlink(missing_ok=True)
            _fsync_directory(self.staging_root)
        except ArtifactError:
            stage_path.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.DatabaseError) as error:
            stage_path.unlink(missing_ok=True)
            raise ArtifactError(
                "MV-ARTIFACT-PUBLISH_FAILED", "Artifact publication failed safely."
            ) from error


def _record_from_metadata(metadata: ArtifactMetadata) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=metadata.artifact_id,
        digest=metadata.digest,
        media_type=metadata.media_type,
        byte_length=metadata.byte_length,
        relative_path=metadata.relative_path,
        created_at_utc=metadata.created_at_utc,
        retention_class=metadata.retention_class,
    )


def _relative_object_path(digest: str) -> str:
    return (ARTIFACT_RELATIVE_ROOT / digest[:2] / digest).as_posix()


def _scan_object_digests(object_root: Path) -> set[str]:
    object_digests: set[str] = set()
    if not object_root.is_dir() or object_root.is_symlink():
        return object_digests
    for prefix in object_root.iterdir():
        if not prefix.is_dir() or prefix.is_symlink():
            continue
        for path in prefix.iterdir():
            if (
                path.is_file()
                and not path.is_symlink()
                and _DIGEST_RE.fullmatch(path.name)
                and prefix.name == path.name[:2]
            ):
                object_digests.add(path.name)
    return object_digests


def _scan_staging_orphans(staging_root: Path, base_path: Path) -> tuple[str, ...]:
    if not staging_root.is_dir() or staging_root.is_symlink():
        return ()
    return tuple(
        sorted(
            str(path.relative_to(base_path))
            for path in staging_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    )


def inspect_artifacts(
    database_path: Path,
    *,
    private_root: Path | None = None,
) -> ArtifactInspection:
    """Inspect catalogued and content-addressed objects without opening a writer."""
    termux_root = termux_private_root()
    resolved_root = private_root.resolve() if private_root is not None else termux_root
    path = database_path.resolve()
    if (
        not resolved_root.is_relative_to(termux_root)
        or not path.is_relative_to(termux_root)
        or not path.is_relative_to(resolved_root)
    ):
        raise ValueError("The authoritative MatchVet database must be in Termux private storage.")
    if not path.exists():
        return ArtifactInspection()
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            catalog = tuple(
                ArtifactMetadata(
                    artifact_id=CanonicalIdentifier(kind="artifact", value=str(row[0])),
                    digest=str(row[1]),
                    media_type=str(row[2]),
                    byte_length=int(row[3]),
                    relative_path=str(row[4]),
                    created_at_utc=str(row[5]),
                    retention_class=str(row[6]),
                )
                for row in connection.execute(
                    """
                    SELECT
                        artifact_id,
                        digest,
                        media_type,
                        byte_length,
                        relative_path,
                        created_at_utc,
                        retention_class
                    FROM artifacts
                    ORDER BY digest
                    """
                )
            )
            manifest_digests = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT manifest_digest FROM snapshot_manifests ORDER BY manifest_digest"
                )
            )
            manifest_metadata = {
                digest: tuple(
                    None if value is None else str(value)
                    for value in connection.execute(
                        """
                        SELECT
                            manifest_digest,
                            snapshot_id,
                            matchweek_id,
                            research_cutoff_id,
                            version_manifest_id,
                            research_cutoff_utc,
                            aggregate_sha256,
                            completeness_state,
                            manifest_schema_version,
                            created_at_utc,
                            verification_state,
                            verified_at_utc,
                            parent_snapshot_id
                        FROM snapshot_manifests
                        WHERE manifest_digest = ?
                        """,
                        (digest,),
                    ).fetchone()
                )
                for digest in manifest_digests
            }
            manifest_versions = {
                digest: tuple(
                    tuple(str(value) for value in row)
                    for row in connection.execute(
                        """
                        SELECT
                            version_id,
                            definition_id,
                            version_kind,
                            name,
                            content_sha256,
                            canonical_contract_version
                        FROM manifest_versions
                        WHERE manifest_digest = ?
                        ORDER BY version_id
                        """,
                        (digest,),
                    )
                )
                for digest in manifest_digests
            }
            manifest_members = {
                digest: tuple(
                    (str(row[0]), str(row[1]))
                    for row in connection.execute(
                        """
                        SELECT artifact_id, artifact_digest
                        FROM manifest_artifacts
                        WHERE manifest_digest = ?
                        ORDER BY artifact_digest
                        """,
                        (digest,),
                    )
                )
                for digest in manifest_digests
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return ArtifactInspection(corrupt=(str(path),))

    return _inspect_catalog(
        catalog,
        {digest: value for digest, value in manifest_metadata.items() if value is not None},
        manifest_members,
        manifest_versions,
        object_root=path.parent / ARTIFACT_RELATIVE_ROOT,
        staging_root=path.parent / ARTIFACT_STAGING_RELATIVE_ROOT,
        base_path=path.parent,
    )


def _verify_file(path: Path, digest: str, byte_length: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("MV-ARTIFACT-MISSING", f"Artifact {digest} is missing.")
    try:
        actual_length, actual_digest = _sha256_file(path)
    except OSError as error:
        raise ArtifactError(
            "MV-ARTIFACT-READ_FAILED", f"Artifact {digest} could not be read."
        ) from error
    if actual_length != byte_length or actual_digest != digest:
        raise ArtifactError(
            "MV-ARTIFACT-DIGEST_MISMATCH", f"Artifact {digest} failed digest verification."
        )


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            length += len(chunk)
    return length, digest.hexdigest()


def _ensure_private_directory(path: Path, boundary: Path) -> None:
    """Create a directory tree without following a symlinked component."""
    try:
        relative = path.relative_to(boundary)
    except ValueError as error:
        raise ArtifactError(
            "MV-ARTIFACT-PATH_MISMATCH", "Artifact paths must stay in private storage."
        ) from error
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(boundary, flags)
        for component in relative.parts:
            if component in {"", ".", ".."}:
                raise ArtifactError(
                    "MV-ARTIFACT-PATH_MISMATCH", "Artifact paths contain an unsafe component."
                )
            created = True
            try:
                os.mkdir(component, 0o700, dir_fd=descriptor)
            except FileExistsError:
                created = False
            if created:
                os.fsync(descriptor)
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except ArtifactError:
        raise
    except OSError as error:
        raise ArtifactError(
            "MV-ARTIFACT-PATH_MISMATCH",
            "Artifact storage contains a missing, non-directory, or symbolic-link component.",
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _private_path_components_are_directories(base: Path, relative_path: str) -> bool:
    current = base
    for component in Path(relative_path).parts[:-1]:
        if component in {"", ".", ".."}:
            return False
        current /= component
        try:
            component_stat = current.lstat()
        except OSError:
            return False
        if not stat.S_ISDIR(component_stat.st_mode):
            return False
    return True


def _atomic_install_no_replace(stage: Path, target: Path) -> None:
    """Atomically install *stage* without replacing an existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError:
        renameat2 = None
    if renameat2 is not None:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(stage),
            -100,
            os.fsencode(target),
            1,  # RENAME_NOREPLACE
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), target)
        if error_number not in {errno.ENOSYS, errno.EINVAL}:
            raise OSError(error_number, os.strerror(error_number), target)
    if hasattr(os, "link"):
        try:
            os.link(stage, target)
        except FileExistsError:
            raise
        stage.unlink()
        return
    raise OSError(errno.ENOTSUP, "Atomic no-replace installation is unavailable", target)


def _require_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ArtifactError("MV-ARTIFACT-DIGEST_INVALID", f"{label} must be lowercase SHA-256.")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _require_utc_timestamp(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ManifestError("MV-MANIFEST-MALFORMED", f"{label} timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ManifestError("MV-MANIFEST-MALFORMED", f"{label} timestamp must be UTC.")
    if parsed.isoformat(timespec="microseconds") != value:
        raise ManifestError("MV-MANIFEST-NONCANONICAL", f"{label} timestamp is not canonical.")


def _canonical_identifier(value: str, kind: str) -> CanonicalIdentifier:
    try:
        return CanonicalIdentifier(kind=kind, value=value)
    except ValueError as error:
        raise ManifestError(
            "MV-MANIFEST-MALFORMED", f"Manifest {kind} identifier is invalid."
        ) from error


def _manifest_publication_key(manifest: SnapshotManifest) -> dict[str, Any]:
    """Return immutable manifest content, excluding publication verification metadata."""
    payload = manifest._payload()
    payload.pop("verification_state", None)
    payload.pop("verified_at_utc", None)
    return payload


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("string required")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("integer required")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("list required")
    return value


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("object required")
    return value


def _exact_keys(value: dict[str, object], keys: set[str]) -> dict[str, object]:
    if set(value) != keys:
        raise TypeError("unexpected object keys")
    return value


def _manifest_artifact(value: object) -> ManifestArtifact:
    item = _exact_keys(_object(value), {"artifact_id", "byte_length", "digest", "media_type"})
    return ManifestArtifact(
        artifact_id=_canonical_identifier(_string(item["artifact_id"]), "artifact"),
        digest=_string(item["digest"]),
        media_type=_string(item["media_type"]),
        byte_length=_integer(item["byte_length"]),
    )


def _manifest_version(value: object) -> ManifestVersion:
    item = _exact_keys(
        _object(value),
        {
            "canonical_contract_version",
            "content_sha256",
            "definition_id",
            "kind",
            "name",
            "version_id",
        },
    )
    return ManifestVersion(
        version_id=_canonical_identifier(_string(item["version_id"]), "version"),
        definition_id=_canonical_identifier(_string(item["definition_id"]), "version_definition"),
        kind=_string(item["kind"]),
        name=_string(item["name"]),
        content_sha256=_string(item["content_sha256"]),
        canonical_contract_version=_integer(item["canonical_contract_version"]),
    )


def _retention_omission(value: object) -> RetentionOmission:
    item = _exact_keys(_object(value), {"identifier", "reason"})
    return RetentionOmission(identifier=_string(item["identifier"]), reason=_string(item["reason"]))


def _manifest_completeness(value: object) -> ManifestCompleteness:
    item = _exact_keys(_object(value), {"missing", "state"})
    return ManifestCompleteness(
        state=_string(item["state"]),
        missing=tuple(_string(item) for item in _list(item["missing"])),
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

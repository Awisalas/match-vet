from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import IO, Self

APPLICATION_ID = 0x4D564554
BUSY_TIMEOUT_MS = 5_000
DEFENSIVE_QUERY_LIMITS = {
    "attached_databases": (sqlite3.SQLITE_LIMIT_ATTACHED, 0),
    "columns": (sqlite3.SQLITE_LIMIT_COLUMN, 512),
    "expression_depth": (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100),
    "sql_length_bytes": (sqlite3.SQLITE_LIMIT_SQL_LENGTH, 1_048_576),
}


class StoreMode(StrEnum):
    READ_WRITE = "READ_WRITE"
    READ_ONLY_RECOVERY = "READ_ONLY_RECOVERY"


class InspectionStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    HEALTHY = "HEALTHY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class StoreBusyError(Exception):
    code = "MV-STORE-WRITER_BUSY"


@dataclass(frozen=True)
class StoreIssue:
    code: str
    message: str


@dataclass(frozen=True)
class StoreStatus:
    mode: StoreMode
    schema_version: int
    applied_migrations: tuple[int, ...]
    migration_count: int
    integrity: str
    foreign_key_violations: int
    pragmas: dict[str, int | str]
    limits: dict[str, int]
    issues: tuple[StoreIssue, ...] = ()


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: CanonicalIdentifier
    digest: str
    media_type: str
    byte_length: int
    relative_path: str
    created_at_utc: str
    retention_class: str


@dataclass(frozen=True)
class StoreInspection:
    path: str
    status: InspectionStatus
    schema_version: int
    applied_migrations: tuple[int, ...]
    integrity: str
    foreign_key_violations: int
    pragmas: dict[str, int | str]
    limits: dict[str, int]
    issues: tuple[StoreIssue, ...] = ()


@dataclass(frozen=True)
class CanonicalIdentifier:
    kind: str
    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.kind) is None:
            raise ValueError("Canonical identifier kinds use lowercase snake case.")
        try:
            parsed = uuid.UUID(self.value)
        except ValueError as error:
            raise ValueError("Canonical identifier values must be UUIDs.") from error
        if str(parsed) != self.value:
            raise ValueError("Canonical identifier UUIDs must use canonical lowercase form.")

    @classmethod
    def new(cls, kind: str) -> CanonicalIdentifier:
        generator: Callable[[], uuid.UUID] = getattr(uuid, "uuid7", uuid.uuid4)
        return cls(kind=kind, value=str(generator()))


@dataclass(frozen=True)
class VersionIdentity:
    identifier: CanonicalIdentifier
    definition_id: CanonicalIdentifier
    kind: str
    name: str
    content_sha256: str
    canonical_contract_version: int
    created_at_utc: str = ""
    predecessor_id: str | None = None

    def __post_init__(self) -> None:
        if self.identifier.kind != "version":
            raise ValueError("A Version Identity requires a version Canonical Identifier.")
        if self.definition_id.kind != "version_definition":
            raise ValueError("A Version Identity requires a stable logical definition identifier.")
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.kind) is None:
            raise ValueError("Version kinds use lowercase snake case.")
        if not self.name:
            raise ValueError("Version names must not be empty.")
        if re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None:
            raise ValueError("Version content digests must be lowercase SHA-256 values.")
        if self.canonical_contract_version < 1:
            raise ValueError("Canonical contract versions start at one.")
        if not self.created_at_utc:
            object.__setattr__(self, "created_at_utc", _utc_now())


def termux_private_root() -> Path:
    base_prefix = Path(sys.base_prefix).resolve()
    if base_prefix.name != "usr" or base_prefix.parent.name != "files":
        raise RuntimeError("MatchVet could not establish the Termux private-storage boundary.")
    return base_prefix.parent


def default_database_path() -> Path:
    return termux_private_root() / "home" / ".local" / "share" / "matchvet" / "matchvet.sqlite3"


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    statements: tuple[str, ...]
    canonical_contract_version: int = 1
    minimum_application_version: str = "0.1.0"
    maximum_application_version: str = "0.1.0"

    @property
    def checksum(self) -> str:
        payload = json.dumps(
            {
                "canonical_contract_version": self.canonical_contract_version,
                "maximum_application_version": self.maximum_application_version,
                "minimum_application_version": self.minimum_application_version,
                "name": self.name,
                "number": self.number,
                "statements": self.statements,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()


MIGRATIONS = (
    Migration(
        number=1,
        name="local_store_foundation",
        statements=(
            """
            CREATE TABLE schema_migrations (
                migration_number INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                canonical_contract_version INTEGER NOT NULL,
                minimum_application_version TEXT NOT NULL,
                maximum_application_version TEXT NOT NULL,
                started_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                result TEXT NOT NULL CHECK (result IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
                software_commit TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE application_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE canonical_identifiers (
                canonical_id TEXT PRIMARY KEY,
                entity_kind TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE version_definitions (
                version_id TEXT PRIMARY KEY
                    REFERENCES canonical_identifiers(canonical_id),
                definition_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                version_kind TEXT NOT NULL,
                name TEXT NOT NULL,
                content_sha256 TEXT NOT NULL
                    CHECK (
                        length(content_sha256) = 64
                        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                canonical_contract_version INTEGER NOT NULL
                    CHECK (canonical_contract_version >= 1),
                created_at_utc TEXT NOT NULL,
                predecessor_id TEXT REFERENCES version_definitions(version_id),
                UNIQUE (definition_id, name),
                UNIQUE (version_kind, name, content_sha256)
            ) STRICT
            """,
            """
            CREATE TABLE integrity_observations (
                observation_id INTEGER PRIMARY KEY,
                checked_at_utc TEXT NOT NULL,
                quick_check_result TEXT NOT NULL,
                foreign_key_violations INTEGER NOT NULL CHECK (foreign_key_violations >= 0),
                migration_result TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('PASS', 'FAIL'))
            ) STRICT
            """,
            """
            CREATE TRIGGER schema_migrations_no_update
            BEFORE UPDATE ON schema_migrations
            BEGIN
                SELECT RAISE(ABORT, 'schema migration history is immutable');
            END
            """,
            """
            CREATE TRIGGER schema_migrations_no_delete
            BEFORE DELETE ON schema_migrations
            BEGIN
                SELECT RAISE(ABORT, 'schema migration history is immutable');
            END
            """,
            """
            CREATE TRIGGER canonical_identifiers_no_update
            BEFORE UPDATE ON canonical_identifiers
            BEGIN
                SELECT RAISE(ABORT, 'canonical identifiers are immutable');
            END
            """,
            """
            CREATE TRIGGER canonical_identifiers_no_delete
            BEFORE DELETE ON canonical_identifiers
            BEGIN
                SELECT RAISE(ABORT, 'canonical identifiers are immutable');
            END
            """,
            """
            CREATE TRIGGER version_definitions_no_update
            BEFORE UPDATE ON version_definitions
            BEGIN
                SELECT RAISE(ABORT, 'version definitions are immutable');
            END
            """,
            """
            CREATE TRIGGER version_definitions_typed_identifiers
            BEFORE INSERT ON version_definitions
            WHEN NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.version_id
                       AND entity_kind = 'version'
                 )
                 OR NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.definition_id
                       AND entity_kind = 'version_definition'
                 )
            BEGIN
                SELECT RAISE(ABORT, 'version definitions require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER version_definitions_same_lineage
            BEFORE INSERT ON version_definitions
            WHEN NEW.predecessor_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1
                     FROM version_definitions AS predecessor
                     WHERE predecessor.version_id = NEW.predecessor_id
                       AND predecessor.definition_id = NEW.definition_id
                 )
            BEGIN
                SELECT RAISE(ABORT, 'version predecessor must belong to the same definition');
            END
            """,
            """
            CREATE TRIGGER version_definitions_no_delete
            BEFORE DELETE ON version_definitions
            BEGIN
                SELECT RAISE(ABORT, 'version definitions are immutable');
            END
            """,
            """
            CREATE TRIGGER integrity_observations_no_update
            BEFORE UPDATE ON integrity_observations
            BEGIN
                SELECT RAISE(ABORT, 'integrity observations are immutable');
            END
            """,
            """
            CREATE TRIGGER integrity_observations_no_delete
            BEFORE DELETE ON integrity_observations
            BEGIN
                SELECT RAISE(ABORT, 'integrity observations are immutable');
            END
            """,
        ),
    ),
    Migration(
        number=2,
        name="immutable_artifacts_and_snapshot_manifests",
        statements=(
            """
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY
                    REFERENCES canonical_identifiers(canonical_id),
                digest TEXT NOT NULL UNIQUE
                    CHECK (
                        length(digest) = 64
                        AND digest NOT GLOB '*[^0-9a-f]*'
                    ),
                media_type TEXT NOT NULL CHECK (length(media_type) > 0),
                byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
                relative_path TEXT NOT NULL UNIQUE,
                created_at_utc TEXT NOT NULL,
                retention_class TEXT NOT NULL
                    CHECK (retention_class IN ('PROTECTED', 'REUSABLE', 'DISPOSABLE'))
            ) STRICT
            """,
            """
            CREATE TABLE snapshot_manifests (
                manifest_digest TEXT PRIMARY KEY
                    REFERENCES artifacts(digest),
                snapshot_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                matchweek_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                research_cutoff_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                version_manifest_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                research_cutoff_utc TEXT NOT NULL,
                aggregate_sha256 TEXT NOT NULL
                    CHECK (
                        length(aggregate_sha256) = 64
                        AND aggregate_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                completeness_state TEXT NOT NULL
                    CHECK (completeness_state IN ('COMPLETE', 'INCOMPLETE')),
                manifest_schema_version INTEGER NOT NULL
                    CHECK (manifest_schema_version >= 1),
                created_at_utc TEXT NOT NULL,
                verification_state TEXT NOT NULL
                    CHECK (verification_state IN ('VERIFIED', 'UNVERIFIED')),
                verified_at_utc TEXT,
                parent_snapshot_id TEXT
                    REFERENCES canonical_identifiers(canonical_id),
                UNIQUE (snapshot_id)
            ) STRICT
            """,
            """
            CREATE TABLE manifest_artifacts (
                manifest_digest TEXT NOT NULL
                    REFERENCES snapshot_manifests(manifest_digest),
                artifact_id TEXT NOT NULL
                    REFERENCES artifacts(artifact_id),
                artifact_digest TEXT NOT NULL
                    REFERENCES artifacts(digest),
                PRIMARY KEY (manifest_digest, artifact_id),
                UNIQUE (manifest_digest, artifact_digest)
            ) STRICT
            """,
            """
            CREATE TRIGGER artifacts_typed_identifiers
            BEFORE INSERT ON artifacts
            WHEN NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.artifact_id
                       AND entity_kind = 'artifact'
                 )
            BEGIN
                SELECT RAISE(ABORT, 'artifacts require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER manifest_artifacts_matching_identity
            BEFORE INSERT ON manifest_artifacts
            WHEN NOT EXISTS (
                     SELECT 1
                     FROM artifacts
                     WHERE artifact_id = NEW.artifact_id
                       AND digest = NEW.artifact_digest
                 )
            BEGIN
                SELECT RAISE(ABORT, 'manifest artifact ID and digest must identify one object');
            END
            """,
            """
            CREATE TABLE manifest_versions (
                manifest_digest TEXT NOT NULL
                    REFERENCES snapshot_manifests(manifest_digest),
                version_id TEXT NOT NULL
                    REFERENCES version_definitions(version_id),
                definition_id TEXT NOT NULL
                    REFERENCES canonical_identifiers(canonical_id),
                version_kind TEXT NOT NULL,
                name TEXT NOT NULL,
                content_sha256 TEXT NOT NULL
                    CHECK (
                        length(content_sha256) = 64
                        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                canonical_contract_version INTEGER NOT NULL
                    CHECK (canonical_contract_version >= 1),
                PRIMARY KEY (manifest_digest, version_id)
            ) STRICT
            """,
            """
            CREATE TRIGGER artifacts_no_update
            BEFORE UPDATE ON artifacts
            BEGIN
                SELECT RAISE(ABORT, 'artifacts are immutable');
            END
            """,
            """
            CREATE TRIGGER artifacts_no_delete
            BEFORE DELETE ON artifacts
            BEGIN
                SELECT RAISE(ABORT, 'artifacts are immutable');
            END
            """,
            """
            CREATE TRIGGER snapshot_manifests_typed_identifiers
            BEFORE INSERT ON snapshot_manifests
            WHEN NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.snapshot_id
                       AND entity_kind = 'snapshot_manifest'
                 )
                 OR NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.matchweek_id
                       AND entity_kind = 'matchweek'
                 )
                 OR NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.research_cutoff_id
                       AND entity_kind = 'research_cutoff'
                 )
                 OR NOT EXISTS (
                     SELECT 1
                     FROM canonical_identifiers
                     WHERE canonical_id = NEW.version_manifest_id
                       AND entity_kind = 'version_manifest'
                 )
                 OR (
                     NEW.parent_snapshot_id IS NOT NULL
                     AND NOT EXISTS (
                         SELECT 1
                         FROM canonical_identifiers
                         WHERE canonical_id = NEW.parent_snapshot_id
                           AND entity_kind = 'snapshot_manifest'
                     )
                 )
            BEGIN
                SELECT RAISE(ABORT, 'snapshot manifests require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER snapshot_manifests_verification_state
            BEFORE INSERT ON snapshot_manifests
            WHEN (NEW.verification_state = 'VERIFIED' AND NEW.verified_at_utc IS NULL)
                 OR (NEW.verification_state = 'UNVERIFIED' AND NEW.verified_at_utc IS NOT NULL)
            BEGIN
                SELECT RAISE(ABORT, 'snapshot manifest verification metadata is inconsistent');
            END
            """,
            """
            CREATE TRIGGER snapshot_manifests_no_update
            BEFORE UPDATE ON snapshot_manifests
            BEGIN
                SELECT RAISE(ABORT, 'snapshot manifests are immutable');
            END
            """,
            """
            CREATE TRIGGER snapshot_manifests_no_delete
            BEFORE DELETE ON snapshot_manifests
            BEGIN
                SELECT RAISE(ABORT, 'snapshot manifests are immutable');
            END
            """,
            """
            CREATE TRIGGER manifest_artifacts_no_update
            BEFORE UPDATE ON manifest_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'manifest artifact membership is immutable');
            END
            """,
            """
            CREATE TRIGGER manifest_artifacts_no_delete
            BEFORE DELETE ON manifest_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'manifest artifact membership is immutable');
            END
            """,
            """
            CREATE TRIGGER manifest_versions_no_update
            BEFORE UPDATE ON manifest_versions
            BEGIN
                SELECT RAISE(ABORT, 'manifest version membership is immutable');
            END
            """,
            """
            CREATE TRIGGER manifest_versions_no_delete
            BEFORE DELETE ON manifest_versions
            BEGIN
                SELECT RAISE(ABORT, 'manifest version membership is immutable');
            END
            """,
        ),
    ),
    Migration(
        number=3,
        name="checkpointed_run_lifecycle",
        statements=(
            """
            CREATE TABLE research_runs (
                run_id TEXT PRIMARY KEY
                    REFERENCES canonical_identifiers(canonical_id),
                matchweek TEXT NOT NULL CHECK (length(matchweek) > 0),
                state TEXT NOT NULL CHECK (state IN ('INCOMPLETE', 'COMPLETE')),
                mode TEXT NOT NULL CHECK (mode = 'RESEARCH_ONLY'),
                current_phase TEXT NOT NULL,
                started_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0),
                input_contract_json TEXT NOT NULL,
                input_digest TEXT NOT NULL
                    CHECK (length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'),
                resource_contract_json TEXT NOT NULL,
                cpu_concurrency INTEGER NOT NULL CHECK (cpu_concurrency BETWEEN 1 AND 2),
                warnings_json TEXT NOT NULL,
                last_checkpoint TEXT,
                last_checkpoint_at_utc TEXT,
                last_error_code TEXT,
                last_error_explanation TEXT,
                reuse_state TEXT NOT NULL
                    CHECK (reuse_state IN ('NONE', 'NOT_REUSED', 'REUSABLE', 'REUSED', 'BLOCKED')),
                coordinator_token TEXT NOT NULL,
                CHECK (
                    (state = 'INCOMPLETE' AND completed_at_utc IS NULL)
                    OR (state = 'COMPLETE' AND completed_at_utc IS NOT NULL)
                ),
                CHECK (
                    (last_checkpoint IS NULL AND last_checkpoint_at_utc IS NULL)
                    OR (last_checkpoint IS NOT NULL AND last_checkpoint_at_utc IS NOT NULL)
                )
            ) STRICT
            """,
            """
            CREATE TABLE run_input_digests (
                run_id TEXT NOT NULL REFERENCES research_runs(run_id),
                input_kind TEXT NOT NULL,
                digest TEXT NOT NULL
                    CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
                PRIMARY KEY (run_id, input_kind)
            ) STRICT
            """,
            """
            CREATE TABLE run_work_units (
                run_id TEXT NOT NULL REFERENCES research_runs(run_id),
                stable_key TEXT NOT NULL,
                phase TEXT NOT NULL,
                phase_order INTEGER NOT NULL CHECK (phase_order BETWEEN 0 AND 6),
                mode TEXT NOT NULL CHECK (mode = 'RESEARCH_ONLY'),
                input_digest TEXT NOT NULL
                    CHECK (length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'),
                state TEXT NOT NULL CHECK (state IN ('PENDING', 'RUNNING', 'COMPLETE')),
                attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
                checkpoint_at_utc TEXT,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0),
                output_digest TEXT
                    CHECK (
                        output_digest IS NULL
                        OR (length(output_digest) = 64
                            AND output_digest NOT GLOB '*[^0-9a-f]*')
                    ),
                artifact_digests_json TEXT NOT NULL,
                PRIMARY KEY (run_id, stable_key),
                UNIQUE (run_id, phase_order),
                CHECK (
                    (state = 'COMPLETE' AND checkpoint_at_utc IS NOT NULL
                        AND output_digest IS NOT NULL)
                    OR (state != 'COMPLETE' AND checkpoint_at_utc IS NULL
                        AND output_digest IS NULL)
                )
            ) STRICT
            """,
            """
            CREATE TABLE run_attempts (
                run_id TEXT NOT NULL,
                stable_key TEXT NOT NULL,
                attempt INTEGER NOT NULL CHECK (attempt >= 1),
                status TEXT NOT NULL
                    CHECK (status IN ('RUNNING', 'COMPLETED', 'INTERRUPTED', 'FAILED')),
                started_at_utc TEXT NOT NULL,
                ended_at_utc TEXT,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0),
                owner_token TEXT NOT NULL,
                error_code TEXT,
                error_explanation TEXT,
                PRIMARY KEY (run_id, stable_key, attempt),
                FOREIGN KEY (run_id, stable_key)
                    REFERENCES run_work_units(run_id, stable_key),
                CHECK (
                    (status = 'RUNNING' AND ended_at_utc IS NULL)
                    OR (status != 'RUNNING' AND ended_at_utc IS NOT NULL)
                )
            ) STRICT
            """,
            """
            CREATE TABLE run_checkpoints (
                run_id TEXT NOT NULL,
                stable_key TEXT NOT NULL,
                phase TEXT NOT NULL,
                checkpoint_order INTEGER NOT NULL CHECK (checkpoint_order BETWEEN 0 AND 6),
                attempt INTEGER NOT NULL,
                input_digest TEXT NOT NULL
                    CHECK (length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'),
                output_digest TEXT NOT NULL
                    CHECK (length(output_digest) = 64 AND output_digest NOT GLOB '*[^0-9a-f]*'),
                artifact_digests_json TEXT NOT NULL,
                checkpoint_at_utc TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0),
                PRIMARY KEY (run_id, stable_key),
                UNIQUE (run_id, checkpoint_order),
                FOREIGN KEY (run_id, stable_key, attempt)
                    REFERENCES run_attempts(run_id, stable_key, attempt)
            ) STRICT
            """,
            """
            CREATE TABLE run_completions (
                run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id),
                publication_digest TEXT NOT NULL UNIQUE REFERENCES artifacts(digest),
                completed_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE INDEX research_runs_matchweek_state
            ON research_runs(matchweek, state, started_at_utc)
            """,
            """
            CREATE INDEX run_attempts_status
            ON run_attempts(status, run_id)
            """,
            """
            CREATE TRIGGER research_runs_typed_identifier
            BEFORE INSERT ON research_runs
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.run_id AND entity_kind = 'research_run'
            )
            BEGIN
                SELECT RAISE(ABORT, 'research runs require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER research_runs_complete_requires_publication
            BEFORE UPDATE OF state ON research_runs
            WHEN NEW.state = 'COMPLETE'
                 AND NOT EXISTS (SELECT 1 FROM run_completions WHERE run_id = NEW.run_id)
            BEGIN
                SELECT RAISE(ABORT, 'completed state requires completion publication');
            END
            """,
            """
            CREATE TRIGGER research_runs_inputs_immutable
            BEFORE UPDATE OF matchweek, mode, started_at_utc, input_contract_json, input_digest
            ON research_runs
            BEGIN
                SELECT RAISE(ABORT, 'research run inputs are immutable');
            END
            """,
            """
            CREATE TRIGGER research_runs_completed_immutable
            BEFORE UPDATE ON research_runs
            WHEN OLD.state = 'COMPLETE'
            BEGIN
                SELECT RAISE(ABORT, 'completed research runs are immutable');
            END
            """,
            """
            CREATE TRIGGER research_runs_no_delete
            BEFORE DELETE ON research_runs
            BEGIN
                SELECT RAISE(ABORT, 'research runs are preserved');
            END
            """,
            """
            CREATE TRIGGER run_input_digests_no_update
            BEFORE UPDATE ON run_input_digests
            BEGIN
                SELECT RAISE(ABORT, 'run input digests are immutable');
            END
            """,
            """
            CREATE TRIGGER run_input_digests_no_delete
            BEFORE DELETE ON run_input_digests
            BEGIN
                SELECT RAISE(ABORT, 'run input digests are immutable');
            END
            """,
            """
            CREATE TRIGGER run_attempts_terminal_immutable
            BEFORE UPDATE ON run_attempts
            WHEN OLD.status != 'RUNNING'
            BEGIN
                SELECT RAISE(ABORT, 'terminal run attempts are immutable');
            END
            """,
            """
            CREATE TRIGGER run_attempts_no_delete
            BEFORE DELETE ON run_attempts
            BEGIN
                SELECT RAISE(ABORT, 'run attempts are preserved');
            END
            """,
            """
            CREATE TRIGGER run_checkpoints_no_update
            BEFORE UPDATE ON run_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'run checkpoints are immutable');
            END
            """,
            """
            CREATE TRIGGER run_checkpoints_no_delete
            BEFORE DELETE ON run_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'run checkpoints are immutable');
            END
            """,
            """
            CREATE TRIGGER run_completions_require_all_checkpoints
            BEFORE INSERT ON run_completions
            WHEN (
                SELECT count(*) FROM run_checkpoints WHERE run_id = NEW.run_id
            ) != 7
            BEGIN
                SELECT RAISE(ABORT, 'completion publication requires every phase checkpoint');
            END
            """,
            """
            CREATE TRIGGER run_completions_no_update
            BEFORE UPDATE ON run_completions
            BEGIN
                SELECT RAISE(ABORT, 'run completion publications are immutable');
            END
            """,
            """
            CREATE TRIGGER run_completions_no_delete
            BEFORE DELETE ON run_completions
            BEGIN
                SELECT RAISE(ABORT, 'run completion publications are immutable');
            END
            """,
        ),
    ),
    Migration(
        number=4,
        name="fixture_history_ingestion",
        statements=(
            """
            CREATE TABLE source_identities (
                source_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                source_key TEXT NOT NULL UNIQUE,
                canonical_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                source_class TEXT NOT NULL,
                access_method TEXT NOT NULL,
                base_locator TEXT NOT NULL,
                allowed_use TEXT NOT NULL,
                retention_status TEXT NOT NULL,
                redistributable INTEGER NOT NULL CHECK (redistributable IN (0, 1)),
                terms_reference TEXT NOT NULL,
                terms_observed_at_utc TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE independent_origins (
                origin_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                origin_key TEXT NOT NULL UNIQUE,
                organization TEXT NOT NULL,
                locator TEXT,
                classification TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE source_captures (
                capture_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                source_id TEXT NOT NULL REFERENCES source_identities(source_id),
                cache_key TEXT NOT NULL,
                locator TEXT NOT NULL,
                access_method TEXT NOT NULL,
                retrieved_at_utc TEXT NOT NULL,
                source_published_at_utc TEXT,
                response_status INTEGER NOT NULL CHECK (response_status BETWEEN 100 AND 599),
                content_type TEXT NOT NULL,
                content_sha256 TEXT NOT NULL
                    CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
                byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
                artifact_digest TEXT NOT NULL REFERENCES artifacts(digest),
                retention_status TEXT NOT NULL,
                observed_terms TEXT NOT NULL,
                terms_reference TEXT NOT NULL,
                rights_json TEXT NOT NULL,
                collector_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (source_id, cache_key, content_sha256, retrieved_at_utc)
            ) STRICT
            """,
            """
            CREATE TABLE target_leagues (
                league_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                league_key TEXT NOT NULL UNIQUE,
                canonical_name TEXT NOT NULL,
                country TEXT NOT NULL,
                football_data_code TEXT NOT NULL UNIQUE,
                openfootball_code TEXT,
                source_timezone TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE competition_seasons (
                season_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                season_label TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (league_id, season_label)
            ) STRICT
            """,
            """
            CREATE TABLE teams (
                team_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (league_id, normalized_name)
            ) STRICT
            """,
            """
            CREATE TABLE team_aliases (
                alias_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                team_id TEXT NOT NULL REFERENCES teams(team_id),
                source_id TEXT REFERENCES source_identities(source_id),
                alias_name TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                mapping_rule_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (league_id, team_id, normalized_alias)
            ) STRICT
            """,
            """
            CREATE TABLE source_team_mappings (
                mapping_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                source_id TEXT NOT NULL REFERENCES source_identities(source_id),
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                source_team_key TEXT,
                source_team_name TEXT NOT NULL,
                mapping_state TEXT NOT NULL
                    CHECK (mapping_state IN ('CONFIRMED', 'AMBIGUOUS', 'UNKNOWN')),
                team_id TEXT REFERENCES teams(team_id),
                candidates_json TEXT NOT NULL,
                mapping_rule_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (source_id, league_id, source_team_key, source_team_name)
            ) STRICT
            """,
            """
            CREATE TABLE fixtures (
                fixture_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                season_id TEXT NOT NULL REFERENCES competition_seasons(season_id),
                home_team_id TEXT NOT NULL REFERENCES teams(team_id),
                away_team_id TEXT NOT NULL REFERENCES teams(team_id),
                identity_state TEXT NOT NULL
                    CHECK (identity_state IN ('CONFIRMED', 'INDETERMINATE')),
                identity_key TEXT NOT NULL UNIQUE,
                created_at_utc TEXT NOT NULL,
                CHECK (home_team_id != away_team_id)
            ) STRICT
            """,
            """
            CREATE TABLE fixture_revisions (
                revision_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),
                predecessor_revision_id TEXT REFERENCES fixture_revisions(revision_id),
                revision_digest TEXT NOT NULL
                    CHECK (length(revision_digest) = 64 AND revision_digest NOT GLOB '*[^0-9a-f]*'),
                kickoff_state TEXT NOT NULL
                    CHECK (kickoff_state IN ('OBSERVED', 'ABSENT', 'UNKNOWN')),
                kickoff_utc TEXT,
                kickoff_local_text TEXT,
                kickoff_precision TEXT NOT NULL,
                fixture_status TEXT NOT NULL,
                source_round TEXT,
                observed_at_utc TEXT NOT NULL,
                source_capture_id TEXT NOT NULL REFERENCES source_captures(capture_id),
                source_assertion_ids_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (fixture_id, revision_digest)
            ) STRICT
            """,
            """
            CREATE TABLE fixture_revision_assertions (
                revision_id TEXT NOT NULL REFERENCES fixture_revisions(revision_id),
                assertion_id TEXT NOT NULL REFERENCES source_assertions(assertion_id),
                PRIMARY KEY (revision_id, assertion_id)
            ) STRICT
            """,
            """
            CREATE TABLE source_assertions (
                assertion_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                capture_id TEXT NOT NULL REFERENCES source_captures(capture_id),
                origin_id TEXT REFERENCES independent_origins(origin_id),
                source_row_key TEXT NOT NULL,
                subject_kind TEXT NOT NULL,
                subject_key TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                predicate TEXT NOT NULL,
                raw_field_name TEXT NOT NULL,
                raw_value_json TEXT,
                normalized_value_json TEXT,
                evidence_state TEXT NOT NULL
                    CHECK (evidence_state IN ('OBSERVED', 'ABSENT', 'UNKNOWN')),
                unknown_reason TEXT,
                event_time_utc TEXT,
                effective_time_utc TEXT,
                created_at_utc TEXT NOT NULL,
                UNIQUE (capture_id, source_row_key, predicate)
            ) STRICT
            """,
            """
            CREATE TABLE match_statistics (
                statistic_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),
                season_id TEXT NOT NULL REFERENCES competition_seasons(season_id),
                metric_key TEXT NOT NULL,
                team_role TEXT NOT NULL,
                phase TEXT NOT NULL,
                evidence_class TEXT NOT NULL
                    CHECK (evidence_class IN ('CORE', 'OPTIONAL_EVIDENCE')),
                evidence_state TEXT NOT NULL
                    CHECK (evidence_state IN ('OBSERVED', 'ABSENT', 'UNKNOWN')),
                value_integer INTEGER CHECK (value_integer IS NULL OR value_integer >= 0),
                value_text TEXT,
                unit TEXT,
                unknown_reason TEXT,
                source_assertion_id TEXT NOT NULL REFERENCES source_assertions(assertion_id),
                created_at_utc TEXT NOT NULL,
                UNIQUE (source_assertion_id, metric_key, team_role, phase),
                CHECK (
                    (evidence_state = 'OBSERVED'
                        AND (value_integer IS NOT NULL OR value_text IS NOT NULL))
                    OR (
                        evidence_state != 'OBSERVED'
                        AND value_integer IS NULL AND value_text IS NULL
                    )
                )
            ) STRICT
            """,
            """
            CREATE TABLE unresolved_fixture_rows (
                unresolved_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                capture_id TEXT NOT NULL REFERENCES source_captures(capture_id),
                source_row_key TEXT NOT NULL,
                league_id TEXT NOT NULL REFERENCES target_leagues(league_id),
                season_id TEXT NOT NULL REFERENCES competition_seasons(season_id),
                home_name TEXT NOT NULL,
                away_name TEXT NOT NULL,
                resolution_state TEXT NOT NULL CHECK (resolution_state IN ('AMBIGUOUS', 'UNKNOWN')),
                candidates_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (capture_id, source_row_key)
            ) STRICT
            """,
            """
            CREATE TABLE conflict_sets (
                conflict_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                subject_kind TEXT NOT NULL,
                subject_key TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_digest TEXT NOT NULL
                    CHECK (length(value_digest) = 64 AND value_digest NOT GLOB '*[^0-9a-f]*'),
                status TEXT NOT NULL CHECK (status = 'UNRESOLVED'),
                created_at_utc TEXT NOT NULL,
                UNIQUE (subject_kind, subject_key, predicate, value_digest)
            ) STRICT
            """,
            """
            CREATE TABLE conflict_assertions (
                conflict_id TEXT NOT NULL REFERENCES conflict_sets(conflict_id),
                assertion_id TEXT NOT NULL REFERENCES source_assertions(assertion_id),
                PRIMARY KEY (conflict_id, assertion_id)
            ) STRICT
            """,
            """
            CREATE INDEX source_assertions_subject_predicate_state
            ON source_assertions(subject_kind, subject_key, predicate, evidence_state)
            """,
            """
            CREATE TRIGGER source_identities_no_update
            BEFORE UPDATE ON source_identities
            BEGIN SELECT RAISE(ABORT, 'source identities are immutable'); END
            """,
            """
            CREATE TRIGGER source_identities_no_delete
            BEFORE DELETE ON source_identities
            BEGIN SELECT RAISE(ABORT, 'source identities are immutable'); END
            """,
            """
            CREATE TRIGGER source_captures_no_update
            BEFORE UPDATE ON source_captures
            BEGIN SELECT RAISE(ABORT, 'source captures are immutable'); END
            """,
            """
            CREATE TRIGGER source_captures_no_delete
            BEFORE DELETE ON source_captures
            BEGIN SELECT RAISE(ABORT, 'source captures are immutable'); END
            """,
            """
            CREATE TRIGGER source_assertions_no_update
            BEFORE UPDATE ON source_assertions
            BEGIN SELECT RAISE(ABORT, 'source assertions are immutable'); END
            """,
            """
            CREATE TRIGGER source_assertions_no_delete
            BEFORE DELETE ON source_assertions
            BEGIN SELECT RAISE(ABORT, 'source assertions are immutable'); END
            """,
            """
            CREATE TRIGGER fixture_revisions_no_update
            BEFORE UPDATE ON fixture_revisions
            BEGIN SELECT RAISE(ABORT, 'fixture revisions are append-only'); END
            """,
            """
            CREATE TRIGGER fixture_revisions_no_delete
            BEFORE DELETE ON fixture_revisions
            BEGIN SELECT RAISE(ABORT, 'fixture revisions are append-only'); END
            """,
            """
            CREATE TRIGGER match_statistics_no_update
            BEFORE UPDATE ON match_statistics
            BEGIN SELECT RAISE(ABORT, 'match statistics are immutable'); END
            """,
            """
            CREATE TRIGGER match_statistics_no_delete
            BEFORE DELETE ON match_statistics
            BEGIN SELECT RAISE(ABORT, 'match statistics are immutable'); END
            """,
            """
            CREATE TRIGGER conflict_sets_no_update
            BEFORE UPDATE ON conflict_sets
            BEGIN SELECT RAISE(ABORT, 'conflict sets are immutable'); END
            """,
            """
            CREATE TRIGGER conflict_sets_no_delete
            BEFORE DELETE ON conflict_sets
            BEGIN SELECT RAISE(ABORT, 'conflict sets are immutable'); END
            """,
            """
            CREATE TRIGGER conflict_assertions_no_update
            BEFORE UPDATE ON conflict_assertions
            BEGIN SELECT RAISE(ABORT, 'conflict assertion links are immutable'); END
            """,
            """
            CREATE TRIGGER conflict_assertions_no_delete
            BEFORE DELETE ON conflict_assertions
            BEGIN SELECT RAISE(ABORT, 'conflict assertion links are immutable'); END
            """,
            """
            CREATE TRIGGER fixture_revision_assertions_no_update
            BEFORE UPDATE ON fixture_revision_assertions
            BEGIN SELECT RAISE(ABORT, 'fixture revision assertion links are immutable'); END
            """,
            """
            CREATE TRIGGER fixture_revision_assertions_no_delete
            BEFORE DELETE ON fixture_revision_assertions
            BEGIN SELECT RAISE(ABORT, 'fixture revision assertion links are immutable'); END
            """,
        ),
    ),
    Migration(
        number=5,
        name="frozen_matchweek_membership",
        statements=(
            """
            CREATE TABLE matchweeks (
                matchweek_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                season_label TEXT NOT NULL,
                friday_local_date TEXT NOT NULL,
                timezone TEXT NOT NULL CHECK (timezone = 'Africa/Lagos'),
                window_start_utc TEXT NOT NULL,
                window_end_utc TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE (season_label, friday_local_date)
            ) STRICT
            """,
            """
            CREATE TABLE matchweek_research_cutoffs (
                cutoff_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                matchweek_id TEXT NOT NULL UNIQUE REFERENCES matchweeks(matchweek_id),
                cutoff_utc TEXT NOT NULL,
                earliest_included_fixture_id TEXT REFERENCES fixtures(fixture_id),
                earliest_included_kickoff_utc TEXT NOT NULL,
                lead_time_seconds INTEGER NOT NULL CHECK (lead_time_seconds = 21600),
                cutoff_digest TEXT NOT NULL
                    CHECK (length(cutoff_digest) = 64 AND cutoff_digest NOT GLOB '*[^0-9a-f]*'),
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE matchweek_memberships (
                membership_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                matchweek_id TEXT NOT NULL REFERENCES matchweeks(matchweek_id),
                subject_kind TEXT NOT NULL
                    CHECK (subject_kind IN ('FIXTURE', 'UNRESOLVED_FIXTURE_ROW')),
                subject_id TEXT NOT NULL,
                fixture_id TEXT REFERENCES fixtures(fixture_id),
                unresolved_id TEXT REFERENCES unresolved_fixture_rows(unresolved_id),
                membership_state TEXT NOT NULL
                    CHECK (membership_state IN ('INCLUDED', 'EXCLUDED', 'INDETERMINATE')),
                target_match INTEGER NOT NULL CHECK (target_match IN (0, 1)),
                controlling_revision_id TEXT REFERENCES fixture_revisions(revision_id),
                controlling_revision_digest TEXT
                    CHECK (
                        controlling_revision_digest IS NULL
                        OR (length(controlling_revision_digest) = 64
                            AND controlling_revision_digest NOT GLOB '*[^0-9a-f]*')
                    ),
                source_authority_rank INTEGER NOT NULL CHECK (source_authority_rank >= 0),
                source_authority TEXT NOT NULL,
                original_kickoff_utc TEXT,
                original_kickoff_local_text TEXT,
                material_conflict INTEGER NOT NULL CHECK (material_conflict IN (0, 1)),
                conflict_predicates_json TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                decision_state TEXT NOT NULL,
                membership_digest TEXT NOT NULL
                    CHECK (
                        length(membership_digest) = 64
                        AND membership_digest NOT GLOB '*[^0-9a-f]*'
                    ),
                created_at_utc TEXT NOT NULL,
                UNIQUE (matchweek_id, subject_kind, subject_id),
                CHECK (
                    (subject_kind = 'FIXTURE' AND fixture_id = subject_id AND unresolved_id IS NULL)
                    OR (
                        subject_kind = 'UNRESOLVED_FIXTURE_ROW'
                        AND unresolved_id = subject_id
                        AND fixture_id IS NULL
                    )
                ),
                CHECK (
                    (membership_state = 'INCLUDED' AND target_match = 1)
                    OR (membership_state != 'INCLUDED' AND target_match = 0)
                ),
                CHECK (
                    (controlling_revision_id IS NULL AND controlling_revision_digest IS NULL)
                    OR (
                        controlling_revision_id IS NOT NULL
                        AND controlling_revision_digest IS NOT NULL
                    )
                )
            ) STRICT
            """,
            """
            CREATE TABLE matchweek_freeze_records (
                matchweek_id TEXT PRIMARY KEY REFERENCES matchweeks(matchweek_id),
                cutoff_id TEXT NOT NULL REFERENCES matchweek_research_cutoffs(cutoff_id),
                snapshot_manifest_digest TEXT NOT NULL
                    REFERENCES snapshot_manifests(manifest_digest),
                membership_manifest_digest TEXT NOT NULL REFERENCES artifacts(digest),
                revision_snapshot_digest TEXT NOT NULL REFERENCES artifacts(digest),
                frozen_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE post_cutoff_fixture_appendix (
                appendix_id TEXT PRIMARY KEY REFERENCES canonical_identifiers(canonical_id),
                matchweek_id TEXT NOT NULL REFERENCES matchweeks(matchweek_id),
                event_key TEXT NOT NULL UNIQUE,
                subject_kind TEXT NOT NULL
                    CHECK (subject_kind IN ('FIXTURE', 'UNRESOLVED_FIXTURE_ROW')),
                subject_id TEXT NOT NULL,
                fixture_id TEXT REFERENCES fixtures(fixture_id),
                membership_id TEXT REFERENCES matchweek_memberships(membership_id),
                revision_id TEXT REFERENCES fixture_revisions(revision_id),
                revision_digest TEXT
                    CHECK (
                        revision_digest IS NULL
                        OR (length(revision_digest) = 64 AND revision_digest NOT GLOB '*[^0-9a-f]*')
                    ),
                event_kind TEXT NOT NULL
                    CHECK (
                        event_kind IN (
                            'FIXTURE_ADDED_AFTER_CUTOFF',
                            'MOVED_IN_AFTER_CUTOFF',
                            'SAME_WINDOW_KICKOFF_CHANGE',
                            'MOVED_OUTSIDE_WINDOW',
                            'POSTPONED',
                            'CANCELLED',
                            'INVALID_PREMATCH_TIMING',
                            'IDENTITY_CONFLICT',
                            'MATERIAL_CONFLICT',
                            'REVISION_LEARNED_AFTER_CUTOFF'
                        )
                    ),
                disposition TEXT NOT NULL
                    CHECK (disposition IN ('APPENDIX_ONLY', 'PRESERVED', 'WITHDRAWN')),
                settlement_result TEXT
                    CHECK (settlement_result IS NULL OR settlement_result = 'VOID'),
                original_kickoff_utc TEXT,
                current_kickoff_utc TEXT,
                observed_at_utc TEXT NOT NULL,
                validity_review_json TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                entry_digest TEXT NOT NULL
                    CHECK (length(entry_digest) = 64 AND entry_digest NOT GLOB '*[^0-9a-f]*'),
                created_at_utc TEXT NOT NULL,
                CHECK (
                    (subject_kind = 'FIXTURE' AND fixture_id = subject_id)
                    OR (subject_kind = 'UNRESOLVED_FIXTURE_ROW' AND fixture_id IS NULL)
                ),
                CHECK (
                    (disposition = 'WITHDRAWN' AND settlement_result = 'VOID')
                    OR (disposition != 'WITHDRAWN' AND settlement_result IS NULL)
                )
            ) STRICT
            """,
            """
            CREATE TRIGGER matchweeks_typed_identifier
            BEFORE INSERT ON matchweeks
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.matchweek_id AND entity_kind = 'matchweek'
            )
            BEGIN
                SELECT RAISE(ABORT, 'matchweeks require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER matchweek_cutoffs_typed_identifier
            BEFORE INSERT ON matchweek_research_cutoffs
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.cutoff_id AND entity_kind = 'research_cutoff'
            )
            BEGIN
                SELECT RAISE(ABORT, 'matchweek cutoffs require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER matchweek_memberships_typed_identifier
            BEFORE INSERT ON matchweek_memberships
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.membership_id AND entity_kind = 'frozen_membership'
            )
            BEGIN
                SELECT RAISE(ABORT, 'matchweek memberships require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER matchweek_freeze_records_typed_identifier
            BEFORE INSERT ON matchweek_freeze_records
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.matchweek_id AND entity_kind = 'matchweek'
            )
            BEGIN
                SELECT RAISE(ABORT, 'matchweek freeze records require typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER post_cutoff_appendix_typed_identifier
            BEFORE INSERT ON post_cutoff_fixture_appendix
            WHEN NOT EXISTS (
                SELECT 1 FROM canonical_identifiers
                WHERE canonical_id = NEW.appendix_id AND entity_kind = 'post_cutoff_appendix'
            )
            BEGIN
                SELECT RAISE(ABORT, 'post-cutoff appendix requires typed canonical identifiers');
            END
            """,
            """
            CREATE TRIGGER matchweeks_no_update
            BEFORE UPDATE ON matchweeks
            BEGIN
                SELECT RAISE(ABORT, 'matchweeks are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweeks_no_delete
            BEFORE DELETE ON matchweeks
            BEGIN
                SELECT RAISE(ABORT, 'matchweeks are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_cutoffs_no_update
            BEFORE UPDATE ON matchweek_research_cutoffs
            BEGIN
                SELECT RAISE(ABORT, 'matchweek research cutoffs are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_cutoffs_no_delete
            BEFORE DELETE ON matchweek_research_cutoffs
            BEGIN
                SELECT RAISE(ABORT, 'matchweek research cutoffs are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_memberships_no_update
            BEFORE UPDATE ON matchweek_memberships
            BEGIN
                SELECT RAISE(ABORT, 'frozen matchweek memberships are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_memberships_no_delete
            BEFORE DELETE ON matchweek_memberships
            BEGIN
                SELECT RAISE(ABORT, 'frozen matchweek memberships are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_freeze_records_no_update
            BEFORE UPDATE ON matchweek_freeze_records
            BEGIN
                SELECT RAISE(ABORT, 'matchweek freeze records are immutable');
            END
            """,
            """
            CREATE TRIGGER matchweek_freeze_records_no_delete
            BEFORE DELETE ON matchweek_freeze_records
            BEGIN
                SELECT RAISE(ABORT, 'matchweek freeze records are immutable');
            END
            """,
            """
            CREATE TRIGGER post_cutoff_appendix_no_update
            BEFORE UPDATE ON post_cutoff_fixture_appendix
            BEGIN
                SELECT RAISE(ABORT, 'post-cutoff fixture appendix entries are immutable');
            END
            """,
            """
            CREATE TRIGGER post_cutoff_appendix_no_delete
            BEFORE DELETE ON post_cutoff_fixture_appendix
            BEGIN
                SELECT RAISE(ABORT, 'post-cutoff fixture appendix entries are immutable');
            END
            """,
        ),
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _validate_private_path(database_path: Path, private_root: Path | None) -> tuple[Path, Path]:
    termux_root = termux_private_root()
    resolved_root = private_root.resolve() if private_root is not None else termux_root
    resolved_path = database_path.resolve()
    if (
        not resolved_root.is_relative_to(termux_root)
        or not resolved_path.is_relative_to(termux_root)
        or not resolved_path.is_relative_to(resolved_root)
    ):
        raise ValueError("The authoritative MatchVet database must be in Termux private storage.")
    return resolved_path, resolved_root


def _acquire_writer_lock(database_path: Path) -> IO[str]:
    lock_path = database_path.parent / ".matchvet-writer.lock"
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock_file.close()
        raise StoreBusyError("Another MatchVet writer already owns this store.") from error
    return lock_file


def _configure_connection(connection: sqlite3.Connection, *, new_database: bool) -> None:
    _apply_defensive_limits(connection)
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    if new_database:
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
    else:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    if journal_mode is None or journal_mode[0] != "wal":
        raise StoreVerificationError(
            "MV-STORE-PRAGMA_MISMATCH",
            "The authoritative store is not using WAL journal mode.",
        )


def _apply_defensive_limits(connection: sqlite3.Connection) -> None:
    for category, limit in DEFENSIVE_QUERY_LIMITS.values():
        connection.setlimit(category, limit)
    _verify_defensive_limits(connection)


def _limit_status(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        name: connection.getlimit(category)
        for name, (category, _) in DEFENSIVE_QUERY_LIMITS.items()
    }


def _verify_defensive_limits(connection: sqlite3.Connection) -> None:
    actual = _limit_status(connection)
    expected = {name: limit for name, (_, limit) in DEFENSIVE_QUERY_LIMITS.items()}
    if actual != expected:
        raise StoreVerificationError(
            "MV-STORE-LIMIT_MISMATCH",
            "SQLite defensive query limits do not match the authoritative profile.",
        )


def _verify_integrity(connection: sqlite3.Connection, *, full: bool = False) -> None:
    pragma = "integrity_check" if full else "quick_check"
    rows = connection.execute(f"PRAGMA {pragma}").fetchall()
    if rows != [("ok",)]:
        raise StoreVerificationError(
            "MV-STORE-INTEGRITY_FAILED",
            f"SQLite {pragma} did not report ok.",
        )
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_violations:
        raise StoreVerificationError(
            "MV-STORE-FOREIGN_KEY_INTEGRITY_FAILED",
            f"SQLite reported {len(foreign_key_violations)} foreign-key violation(s).",
        )


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def _pragma_value(connection: sqlite3.Connection, name: str) -> int | str:
    row = connection.execute(f"PRAGMA {name}").fetchone()
    if row is None or not isinstance(row[0], (int, str)):
        raise sqlite3.DatabaseError(f"SQLite did not report PRAGMA {name}.")
    return row[0]


def _pragma_status(connection: sqlite3.Connection) -> dict[str, int | str]:
    return {
        name: _pragma_value(connection, name)
        for name in (
            "application_id",
            "auto_vacuum",
            "busy_timeout",
            "foreign_keys",
            "journal_mode",
            "synchronous",
        )
    }


def _verify_operating_profile(connection: sqlite3.Connection) -> None:
    expected: dict[str, int | str] = {
        "application_id": APPLICATION_ID,
        "auto_vacuum": 2,
        "busy_timeout": BUSY_TIMEOUT_MS,
        "foreign_keys": 1,
        "journal_mode": "wal",
        "synchronous": 2,
    }
    actual = _pragma_status(connection)
    mismatches = tuple(name for name, value in expected.items() if actual[name] != value)
    if mismatches:
        raise StoreVerificationError(
            "MV-STORE-PRAGMA_MISMATCH",
            f"SQLite settings do not match the authoritative profile: {', '.join(mismatches)}.",
        )


def _applied_migrations(connection: sqlite3.Connection) -> tuple[int, ...]:
    if _schema_version(connection) == 0:
        return ()
    rows = connection.execute(
        "SELECT migration_number FROM schema_migrations ORDER BY migration_number"
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


class StoreVerificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.issue = StoreIssue(code=code, message=message)


def _validate_migration_plan(migrations: tuple[Migration, ...]) -> None:
    numbers = tuple(migration.number for migration in migrations)
    expected = tuple(range(1, len(migrations) + 1))
    if numbers != expected:
        raise ValueError("Migration numbers must be sequential and start at one.")


def _verify_migrations(connection: sqlite3.Connection, migrations: tuple[Migration, ...]) -> None:
    current_version = _schema_version(connection)
    if current_version > len(migrations):
        raise StoreVerificationError(
            "MV-STORE-SCHEMA_TOO_NEW",
            f"Database schema {current_version} is newer than supported schema {len(migrations)}.",
        )
    if current_version == 0:
        return
    try:
        rows = connection.execute(
            """
            SELECT
                migration_number,
                name,
                checksum,
                canonical_contract_version,
                minimum_application_version,
                maximum_application_version,
                completed_at_utc,
                result
            FROM schema_migrations
            ORDER BY migration_number
            """
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise StoreVerificationError(
            "MV-STORE-MIGRATION_LEDGER_INVALID",
            "The migration ledger cannot be read.",
        ) from error
    if tuple(int(row[0]) for row in rows) != tuple(range(1, current_version + 1)):
        raise StoreVerificationError(
            "MV-STORE-MIGRATION_ORDER_INVALID",
            "Applied migrations are not a complete sequential history.",
        )
    for row, migration in zip(rows, migrations, strict=False):
        if row[7] != "COMPLETED" or row[6] is None:
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_INCOMPLETE",
                f"Migration {migration.number} has no verified completion record.",
            )
        if (
            row[1] != migration.name
            or row[2] != migration.checksum
            or int(row[3]) != migration.canonical_contract_version
            or row[4] != migration.minimum_application_version
            or row[5] != migration.maximum_application_version
        ):
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_CHECKSUM_MISMATCH",
                f"Migration {migration.number} does not match the immutable application plan.",
            )


def _normalized_sql(statement: str) -> str:
    return " ".join(statement.split())


def _expected_schema_objects(
    migrations: tuple[Migration, ...], schema_version: int
) -> dict[tuple[str, str], str]:
    expected: dict[tuple[str, str], str] = {}
    for migration in migrations[:schema_version]:
        for statement in migration.statements:
            normalized = _normalized_sql(statement)
            words = normalized.split(maxsplit=3)
            if len(words) < 3 or words[0:2] not in (
                ["CREATE", "TABLE"],
                ["CREATE", "TRIGGER"],
                ["CREATE", "INDEX"],
            ):
                continue
            object_type = words[1].lower()
            expected[(object_type, words[2])] = normalized
    return expected


def _verify_schema_manifest(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...],
) -> None:
    schema_version = _schema_version(connection)
    expected = _expected_schema_objects(migrations, schema_version)
    actual = {
        (str(row[0]), str(row[1])): _normalized_sql(str(row[2]))
        for row in connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_schema
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            """
        )
    }
    if actual != expected:
        raise StoreVerificationError(
            "MV-STORE-SCHEMA_MANIFEST_MISMATCH",
            "The live SQLite schema does not match the immutable migration manifest.",
        )

    expected_indexes = {
        ("application_metadata", "sqlite_autoindex_application_metadata_1", 1, "pk", 0),
        ("canonical_identifiers", "sqlite_autoindex_canonical_identifiers_1", 1, "pk", 0),
        ("version_definitions", "sqlite_autoindex_version_definitions_1", 1, "pk", 0),
        ("version_definitions", "sqlite_autoindex_version_definitions_2", 1, "u", 0),
        ("version_definitions", "sqlite_autoindex_version_definitions_3", 1, "u", 0),
    }
    if schema_version >= 2:
        expected_indexes.update(
            {
                ("artifacts", "sqlite_autoindex_artifacts_1", 1, "pk", 0),
                ("artifacts", "sqlite_autoindex_artifacts_2", 1, "u", 0),
                ("artifacts", "sqlite_autoindex_artifacts_3", 1, "u", 0),
                ("snapshot_manifests", "sqlite_autoindex_snapshot_manifests_1", 1, "pk", 0),
                ("snapshot_manifests", "sqlite_autoindex_snapshot_manifests_2", 1, "u", 0),
                ("manifest_artifacts", "sqlite_autoindex_manifest_artifacts_1", 1, "pk", 0),
                ("manifest_artifacts", "sqlite_autoindex_manifest_artifacts_2", 1, "u", 0),
                ("manifest_versions", "sqlite_autoindex_manifest_versions_1", 1, "pk", 0),
            }
        )
    if schema_version >= 3:
        expected_indexes.update(
            {
                ("research_runs", "sqlite_autoindex_research_runs_1", 1, "pk", 0),
                ("research_runs", "research_runs_matchweek_state", 0, "c", 0),
                ("run_input_digests", "sqlite_autoindex_run_input_digests_1", 1, "pk", 0),
                ("run_work_units", "sqlite_autoindex_run_work_units_1", 1, "pk", 0),
                ("run_work_units", "sqlite_autoindex_run_work_units_2", 1, "u", 0),
                ("run_attempts", "sqlite_autoindex_run_attempts_1", 1, "pk", 0),
                ("run_attempts", "run_attempts_status", 0, "c", 0),
                ("run_checkpoints", "sqlite_autoindex_run_checkpoints_1", 1, "pk", 0),
                ("run_checkpoints", "sqlite_autoindex_run_checkpoints_2", 1, "u", 0),
                ("run_completions", "sqlite_autoindex_run_completions_1", 1, "pk", 0),
                ("run_completions", "sqlite_autoindex_run_completions_2", 1, "u", 0),
            }
        )
    if schema_version >= 4:
        expected_indexes.update(
            {
                ("source_identities", "sqlite_autoindex_source_identities_1", 1, "pk", 0),
                ("source_identities", "sqlite_autoindex_source_identities_2", 1, "u", 0),
                ("independent_origins", "sqlite_autoindex_independent_origins_1", 1, "pk", 0),
                ("independent_origins", "sqlite_autoindex_independent_origins_2", 1, "u", 0),
                ("source_captures", "sqlite_autoindex_source_captures_1", 1, "pk", 0),
                ("source_captures", "sqlite_autoindex_source_captures_2", 1, "u", 0),
                ("target_leagues", "sqlite_autoindex_target_leagues_1", 1, "pk", 0),
                ("target_leagues", "sqlite_autoindex_target_leagues_2", 1, "u", 0),
                ("target_leagues", "sqlite_autoindex_target_leagues_3", 1, "u", 0),
                ("competition_seasons", "sqlite_autoindex_competition_seasons_1", 1, "pk", 0),
                ("competition_seasons", "sqlite_autoindex_competition_seasons_2", 1, "u", 0),
                ("teams", "sqlite_autoindex_teams_1", 1, "pk", 0),
                ("teams", "sqlite_autoindex_teams_2", 1, "u", 0),
                ("team_aliases", "sqlite_autoindex_team_aliases_1", 1, "pk", 0),
                ("team_aliases", "sqlite_autoindex_team_aliases_2", 1, "u", 0),
                ("source_team_mappings", "sqlite_autoindex_source_team_mappings_1", 1, "pk", 0),
                ("source_team_mappings", "sqlite_autoindex_source_team_mappings_2", 1, "u", 0),
                ("fixtures", "sqlite_autoindex_fixtures_1", 1, "pk", 0),
                ("fixtures", "sqlite_autoindex_fixtures_2", 1, "u", 0),
                ("fixture_revisions", "sqlite_autoindex_fixture_revisions_1", 1, "pk", 0),
                ("fixture_revisions", "sqlite_autoindex_fixture_revisions_2", 1, "u", 0),
                (
                    "fixture_revision_assertions",
                    "sqlite_autoindex_fixture_revision_assertions_1",
                    1,
                    "pk",
                    0,
                ),
                ("source_assertions", "sqlite_autoindex_source_assertions_1", 1, "pk", 0),
                ("source_assertions", "sqlite_autoindex_source_assertions_2", 1, "u", 0),
                ("source_assertions", "source_assertions_subject_predicate_state", 0, "c", 0),
                ("match_statistics", "sqlite_autoindex_match_statistics_1", 1, "pk", 0),
                ("match_statistics", "sqlite_autoindex_match_statistics_2", 1, "u", 0),
                (
                    "unresolved_fixture_rows",
                    "sqlite_autoindex_unresolved_fixture_rows_1",
                    1,
                    "pk",
                    0,
                ),
                (
                    "unresolved_fixture_rows",
                    "sqlite_autoindex_unresolved_fixture_rows_2",
                    1,
                    "u",
                    0,
                ),
                ("conflict_sets", "sqlite_autoindex_conflict_sets_1", 1, "pk", 0),
                ("conflict_sets", "sqlite_autoindex_conflict_sets_2", 1, "u", 0),
                ("conflict_assertions", "sqlite_autoindex_conflict_assertions_1", 1, "pk", 0),
            }
        )
    if schema_version >= 5:
        expected_indexes.update(
            {
                ("matchweeks", "sqlite_autoindex_matchweeks_1", 1, "pk", 0),
                ("matchweeks", "sqlite_autoindex_matchweeks_2", 1, "u", 0),
                (
                    "matchweek_research_cutoffs",
                    "sqlite_autoindex_matchweek_research_cutoffs_1",
                    1,
                    "pk",
                    0,
                ),
                (
                    "matchweek_research_cutoffs",
                    "sqlite_autoindex_matchweek_research_cutoffs_2",
                    1,
                    "u",
                    0,
                ),
                (
                    "matchweek_memberships",
                    "sqlite_autoindex_matchweek_memberships_1",
                    1,
                    "pk",
                    0,
                ),
                (
                    "matchweek_memberships",
                    "sqlite_autoindex_matchweek_memberships_2",
                    1,
                    "u",
                    0,
                ),
                (
                    "matchweek_freeze_records",
                    "sqlite_autoindex_matchweek_freeze_records_1",
                    1,
                    "pk",
                    0,
                ),
                (
                    "post_cutoff_fixture_appendix",
                    "sqlite_autoindex_post_cutoff_fixture_appendix_1",
                    1,
                    "pk",
                    0,
                ),
                (
                    "post_cutoff_fixture_appendix",
                    "sqlite_autoindex_post_cutoff_fixture_appendix_2",
                    1,
                    "u",
                    0,
                ),
            }
        )
    actual_indexes: set[tuple[str, str, int, str, int]] = set()
    for table_name in (
        "application_metadata",
        "canonical_identifiers",
        "integrity_observations",
        "schema_migrations",
        "version_definitions",
        "artifacts",
        "snapshot_manifests",
        "manifest_artifacts",
        "manifest_versions",
        "research_runs",
        "run_input_digests",
        "run_work_units",
        "run_attempts",
        "run_checkpoints",
        "run_completions",
        "source_identities",
        "independent_origins",
        "source_captures",
        "target_leagues",
        "competition_seasons",
        "teams",
        "team_aliases",
        "source_team_mappings",
        "fixtures",
        "fixture_revisions",
        "fixture_revision_assertions",
        "source_assertions",
        "match_statistics",
        "unresolved_fixture_rows",
        "conflict_sets",
        "conflict_assertions",
        "matchweeks",
        "matchweek_research_cutoffs",
        "matchweek_memberships",
        "matchweek_freeze_records",
        "post_cutoff_fixture_appendix",
    ):
        actual_indexes.update(
            (table_name, str(row[1]), int(row[2]), str(row[3]), int(row[4]))
            for row in connection.execute(f"PRAGMA index_list({table_name})")
        )
    if actual_indexes != expected_indexes:
        raise StoreVerificationError(
            "MV-STORE-SCHEMA_MANIFEST_MISMATCH",
            "The live SQLite indexes do not match the immutable schema manifest.",
        )


def _verify_canonical_reference_types(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        """
        SELECT count(*)
        FROM version_definitions AS vd
        JOIN canonical_identifiers AS version_identity
            ON version_identity.canonical_id = vd.version_id
        JOIN canonical_identifiers AS definition_identity
            ON definition_identity.canonical_id = vd.definition_id
        WHERE version_identity.entity_kind != 'version'
           OR definition_identity.entity_kind != 'version_definition'
        """
    ).fetchone()
    if row is None or int(row[0]) != 0:
        raise StoreVerificationError(
            "MV-STORE-CANONICAL_TYPE_MISMATCH",
            "Stored version references do not match their required canonical identifier types.",
        )


def _verify_artifact_objects(
    connection: sqlite3.Connection,
    database_path: Path,
) -> None:
    """Verify every catalogued object before allowing normal store writes."""
    rows = connection.execute(
        """
        SELECT digest, byte_length, relative_path
        FROM artifacts
        ORDER BY digest
        """
    ).fetchall()
    for row in rows:
        digest = str(row[0])
        byte_length = int(row[1])
        relative_path = str(row[2])
        expected_relative_path = (Path("objects") / "sha256" / digest[:2] / digest).as_posix()
        if relative_path != expected_relative_path:
            raise StoreVerificationError(
                "MV-STORE-ACTIVE_ARTIFACT_FAILED",
                f"Catalogued artifact {digest} has an invalid private path.",
            )
        object_path = database_path.parent / relative_path
        try:
            if not _private_path_components_are_directories(database_path.parent, relative_path):
                raise OSError("artifact path contains a symbolic link")
            object_stat = object_path.lstat()
            if not stat.S_ISREG(object_stat.st_mode):
                raise OSError("artifact is not a regular file")
            actual_length, actual_digest = _sha256_file(object_path)
        except OSError as error:
            raise StoreVerificationError(
                "MV-STORE-ACTIVE_ARTIFACT_FAILED",
                f"Catalogued artifact {digest} is missing or unreadable.",
            ) from error
        if actual_length != byte_length or actual_digest != digest:
            raise StoreVerificationError(
                "MV-STORE-ACTIVE_ARTIFACT_FAILED",
                f"Catalogued artifact {digest} failed digest verification.",
            )


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            length += len(chunk)
    return length, digest.hexdigest()


def _private_path_components_are_directories(base: Path, relative_path: str) -> bool:
    current = base
    for component in Path(relative_path).parts[:-1]:
        current /= component
        try:
            component_stat = current.lstat()
        except OSError:
            return False
        if not stat.S_ISDIR(component_stat.st_mode):
            return False
    return True


def _verify_application_identity(connection: sqlite3.Connection) -> None:
    application_id = _pragma_value(connection, "application_id")
    if application_id != APPLICATION_ID:
        raise StoreVerificationError(
            "MV-STORE-APPLICATION_ID_MISMATCH",
            "The database is not identified as a MatchVet authoritative store.",
        )


def _apply_migrations(
    connection: sqlite3.Connection,
    software_commit: str,
    migrations: tuple[Migration, ...],
    *,
    new_database: bool,
    database_path: Path,
) -> None:
    current_version = _schema_version(connection)
    migration_backup: Path | None = None
    if current_version < len(migrations) and not new_database:
        if migrations != MIGRATIONS:
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_BACKUP_REQUIRED",
                "An existing store cannot migrate until a verified private backup is available.",
            )
        migration_backup = _create_private_migration_backup(connection, database_path)
    for migration in migrations[current_version:]:
        _verify_integrity(connection, full=True)
        started_at = _utc_now()
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations (
                    migration_number,
                    name,
                    checksum,
                    canonical_contract_version,
                    minimum_application_version,
                    maximum_application_version,
                    started_at_utc,
                    completed_at_utc,
                    result,
                    software_commit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?)
                """,
                (
                    migration.number,
                    migration.name,
                    migration.checksum,
                    migration.canonical_contract_version,
                    migration.minimum_application_version,
                    migration.maximum_application_version,
                    started_at,
                    _utc_now(),
                    software_commit,
                ),
            )
            connection.execute(f"PRAGMA user_version = {migration.number}")
            connection.commit()
            _verify_integrity(connection, full=True)
            _verify_migrations(connection, migrations)
            _verify_schema_manifest(connection, migrations)
            _verify_canonical_reference_types(connection)
        except BaseException:
            connection.rollback()
            raise
    if migration_backup is not None:
        migration_backup.unlink(missing_ok=True)
        _fsync_directory(database_path.parent)


def _create_private_migration_backup(
    connection: sqlite3.Connection,
    database_path: Path,
) -> Path:
    backup_path = database_path.with_name(
        f".{database_path.name}.{uuid.uuid4().hex}.migration-backup"
    )
    backup_connection: sqlite3.Connection | None = None
    try:
        backup_connection = sqlite3.connect(backup_path, isolation_level=None)
        connection.backup(backup_connection)
        _apply_defensive_limits(backup_connection)
        backup_connection.execute("PRAGMA foreign_keys = ON")
        backup_connection.execute("PRAGMA synchronous = FULL")
        _verify_application_identity(backup_connection)
        _verify_integrity(backup_connection, full=True)
        backup_connection.commit()
        descriptor = os.open(backup_path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(database_path.parent)
        return backup_path
    except (OSError, sqlite3.DatabaseError) as error:
        backup_path.unlink(missing_ok=True)
        raise StoreVerificationError(
            "MV-STORE-MIGRATION_BACKUP_FAILED",
            "A verified private pre-migration backup could not be created.",
        ) from error
    finally:
        if backup_connection is not None:
            backup_connection.close()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _recovery_connection(path: Path) -> sqlite3.Connection | None:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None)
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        _apply_defensive_limits(connection)
        return connection
    except sqlite3.DatabaseError:
        return None


def _recovery_status(connection: sqlite3.Connection | None, issue: StoreIssue) -> StoreStatus:
    if connection is None:
        return StoreStatus(
            mode=StoreMode.READ_ONLY_RECOVERY,
            schema_version=0,
            applied_migrations=(),
            migration_count=0,
            integrity="unreadable",
            foreign_key_violations=-1,
            pragmas={},
            limits={},
            issues=(issue,),
        )
    try:
        schema_version = _schema_version(connection)
        applied_migrations = _applied_migrations(connection)
        integrity_row = connection.execute("PRAGMA quick_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row is not None else "missing"
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        pragmas = _pragma_status(connection)
        limits = _limit_status(connection)
    except sqlite3.DatabaseError:
        schema_version = 0
        applied_migrations = ()
        integrity = "unreadable"
        foreign_key_violations = -1
        pragmas = {}
        limits = {}
    return StoreStatus(
        mode=StoreMode.READ_ONLY_RECOVERY,
        schema_version=schema_version,
        applied_migrations=applied_migrations,
        migration_count=len(applied_migrations),
        integrity=integrity,
        foreign_key_violations=foreign_key_violations,
        pragmas=pragmas,
        limits=limits,
        issues=(issue,),
    )


def _record_integrity_observation(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """
            INSERT INTO integrity_observations (
                checked_at_utc,
                quick_check_result,
                foreign_key_violations,
                migration_result,
                outcome
            ) VALUES (?, 'ok', 0, 'VERIFIED', 'PASS')
            """,
            (_utc_now(),),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class Store:
    def __init__(
        self,
        path: Path,
        connection: sqlite3.Connection | None,
        writer_lock: IO[str],
        status: StoreStatus,
    ) -> None:
        self.path = path
        self._connection = connection
        self._writer_lock = writer_lock
        self.status = status
        self._pid = os.getpid()
        self._closed = False

    def _ensure_write_allowed(self) -> None:
        if self._closed:
            raise RuntimeError("The MatchVet store is closed.")
        if os.getpid() != self._pid:
            raise RuntimeError("SQLite connections cannot cross a process boundary.")
        if self.status.mode is not StoreMode.READ_WRITE:
            raise PermissionError("The MatchVet store is in read-only recovery mode.")

    def _ensure_connection_owner(self) -> None:
        if self._closed:
            raise RuntimeError("The MatchVet store is closed.")
        if os.getpid() != self._pid:
            raise RuntimeError("SQLite connections cannot cross a process boundary.")

    def _connection_for_repository(self) -> sqlite3.Connection:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[StoreTransaction]:
        self._ensure_write_allowed()
        assert self._connection is not None
        self._connection.execute("BEGIN IMMEDIATE")
        transaction = StoreTransaction(self._connection)
        try:
            yield transaction
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        finally:
            transaction.close()

    def has_identifier(self, identifier: CanonicalIdentifier) -> bool:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        row = self._connection.execute(
            """
            SELECT 1
            FROM canonical_identifiers
            WHERE canonical_id = ? AND entity_kind = ?
            """,
            (identifier.value, identifier.kind),
        ).fetchone()
        return row is not None

    def version(self, identifier: CanonicalIdentifier) -> VersionIdentity | None:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        row = self._connection.execute(
            """
            SELECT
                version_identity.entity_kind,
                vd.version_id,
                definition_identity.entity_kind,
                vd.definition_id,
                vd.version_kind,
                vd.name,
                vd.content_sha256,
                vd.canonical_contract_version,
                vd.created_at_utc,
                vd.predecessor_id
            FROM version_definitions AS vd
            JOIN canonical_identifiers AS version_identity
                ON version_identity.canonical_id = vd.version_id
            JOIN canonical_identifiers AS definition_identity
                ON definition_identity.canonical_id = vd.definition_id
            WHERE vd.version_id = ?
            """,
            (identifier.value,),
        ).fetchone()
        if row is None:
            return None
        return VersionIdentity(
            identifier=CanonicalIdentifier(kind=str(row[0]), value=str(row[1])),
            definition_id=CanonicalIdentifier(kind=str(row[2]), value=str(row[3])),
            kind=str(row[4]),
            name=str(row[5]),
            content_sha256=str(row[6]),
            canonical_contract_version=int(row[7]),
            created_at_utc=str(row[8]),
            predecessor_id=str(row[9]) if row[9] is not None else None,
        )

    def artifact_metadata(self, digest: str) -> ArtifactMetadata | None:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        row = self._connection.execute(
            """
            SELECT artifact_id, digest, media_type, byte_length, relative_path,
                   created_at_utc, retention_class
            FROM artifacts
            WHERE digest = ?
            """,
            (digest,),
        ).fetchone()
        if row is None:
            return None
        return ArtifactMetadata(
            artifact_id=CanonicalIdentifier(kind="artifact", value=str(row[0])),
            digest=str(row[1]),
            media_type=str(row[2]),
            byte_length=int(row[3]),
            relative_path=str(row[4]),
            created_at_utc=str(row[5]),
            retention_class=str(row[6]),
        )

    def artifact_catalog(self) -> tuple[ArtifactMetadata, ...]:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        rows = self._connection.execute(
            """
            SELECT artifact_id, digest, media_type, byte_length, relative_path,
                   created_at_utc, retention_class
            FROM artifacts
            ORDER BY digest
            """
        ).fetchall()
        return tuple(
            ArtifactMetadata(
                artifact_id=CanonicalIdentifier(kind="artifact", value=str(row[0])),
                digest=str(row[1]),
                media_type=str(row[2]),
                byte_length=int(row[3]),
                relative_path=str(row[4]),
                created_at_utc=str(row[5]),
                retention_class=str(row[6]),
            )
            for row in rows
        )

    def snapshot_manifest_metadata(self, digest: str) -> tuple[str | None, ...] | None:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        row = self._connection.execute(
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
        return (
            tuple(None if value is None else str(value) for value in row)
            if row is not None
            else None
        )

    def snapshot_manifest_digests(self) -> tuple[str, ...]:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        rows = self._connection.execute(
            "SELECT manifest_digest FROM snapshot_manifests ORDER BY manifest_digest"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def snapshot_manifest_digest_for_snapshot(self, snapshot_id: str) -> str | None:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        row = self._connection.execute(
            """
            SELECT manifest_digest
            FROM snapshot_manifests
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def snapshot_manifest_artifacts(self, digest: str) -> tuple[tuple[str, str], ...]:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        rows = self._connection.execute(
            """
            SELECT artifact_id, artifact_digest
            FROM manifest_artifacts
            WHERE manifest_digest = ?
            ORDER BY artifact_digest
            """,
            (digest,),
        ).fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def snapshot_manifest_versions(self, digest: str) -> tuple[tuple[str, ...], ...]:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        rows = self._connection.execute(
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
        ).fetchall()
        return tuple(tuple(str(value) for value in row) for row in rows)

    def run_completion_digests(self) -> tuple[str, ...]:
        self._ensure_connection_owner()
        if self._connection is None:
            raise sqlite3.DatabaseError("The MatchVet database is unreadable.")
        rows = self._connection.execute(
            "SELECT publication_digest FROM run_completions ORDER BY publication_digest"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def close(self) -> None:
        if self._closed:
            return
        if os.getpid() != self._pid:
            self._writer_lock.close()
            self._closed = True
            return
        if self._connection is not None:
            self._connection.close()
        fcntl.flock(self._writer_lock.fileno(), fcntl.LOCK_UN)
        self._writer_lock.close()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        self.close()


class StoreTransaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._pid = os.getpid()
        self._active = True

    def _ensure_active(self) -> None:
        if not self._active:
            raise RuntimeError("The bounded store transaction is closed.")
        if os.getpid() != self._pid:
            raise RuntimeError("Store transactions cannot cross a process boundary.")

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        self._ensure_active()
        return self._connection.execute(sql, parameters)

    def close(self) -> None:
        self._active = False

    def add_identifier(self, identifier: CanonicalIdentifier) -> None:
        self._ensure_active()
        self._connection.execute(
            """
            INSERT INTO canonical_identifiers (canonical_id, entity_kind, created_at_utc)
            VALUES (?, ?, ?)
            """,
            (identifier.value, identifier.kind, _utc_now()),
        )

    def add_identifier_if_missing(self, identifier: CanonicalIdentifier) -> None:
        self._ensure_active()
        if not _identifier_exists(self._connection, identifier):
            self.add_identifier(identifier)

    def add_version(self, version: VersionIdentity) -> None:
        self._ensure_active()
        if version.predecessor_id is not None:
            predecessor = CanonicalIdentifier(kind="version", value=version.predecessor_id)
            if predecessor.value == version.identifier.value:
                raise ValueError("A Version Identity cannot be its own predecessor.")
        if not _identifier_exists(self._connection, version.identifier):
            self.add_identifier(version.identifier)
        if not _identifier_exists(self._connection, version.definition_id):
            self.add_identifier(version.definition_id)
        self._connection.execute(
            """
            INSERT INTO version_definitions (
                version_id,
                definition_id,
                version_kind,
                name,
                content_sha256,
                canonical_contract_version,
                created_at_utc,
                predecessor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.identifier.value,
                version.definition_id.value,
                version.kind,
                version.name,
                version.content_sha256,
                version.canonical_contract_version,
                version.created_at_utc,
                version.predecessor_id,
            ),
        )

    def record_artifact(self, artifact: ArtifactMetadata) -> None:
        self._ensure_active()
        existing = self._connection.execute(
            """
            SELECT artifact_id, media_type, byte_length, relative_path, retention_class
            FROM artifacts
            WHERE digest = ?
            """,
            (artifact.digest,),
        ).fetchone()
        if existing is not None:
            if tuple(existing[1:]) != (
                artifact.media_type,
                artifact.byte_length,
                artifact.relative_path,
                artifact.retention_class,
            ):
                raise sqlite3.IntegrityError("artifact catalog metadata does not match its digest")
            return
        if not _identifier_exists(self._connection, artifact.artifact_id):
            self.add_identifier(artifact.artifact_id)
        self._connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id,
                digest,
                media_type,
                byte_length,
                relative_path,
                created_at_utc,
                retention_class
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id.value,
                artifact.digest,
                artifact.media_type,
                artifact.byte_length,
                artifact.relative_path,
                artifact.created_at_utc,
                artifact.retention_class,
            ),
        )

    def record_snapshot_manifest(
        self,
        *,
        manifest_digest: str,
        snapshot_id: str,
        matchweek_id: str,
        research_cutoff_id: str,
        version_manifest_id: str,
        research_cutoff_utc: str,
        aggregate_sha256: str,
        completeness_state: str,
        manifest_schema_version: int,
        created_at_utc: str,
        verification_state: str,
        verified_at_utc: str | None,
        parent_snapshot_id: str | None,
    ) -> None:
        self._ensure_active()
        self._connection.execute(
            """
            INSERT INTO snapshot_manifests (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(manifest_digest) DO NOTHING
            """,
            (
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
                parent_snapshot_id,
            ),
        )
        row = self._connection.execute(
            """
            SELECT
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
            (manifest_digest,),
        ).fetchone()
        expected = (
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
            parent_snapshot_id,
        )
        if row is None or tuple(row) != expected:
            raise sqlite3.IntegrityError("snapshot manifest metadata does not match its digest")

    def record_manifest_artifact(
        self,
        manifest_digest: str,
        artifact_id: str,
        artifact_digest: str,
    ) -> None:
        self._ensure_active()
        self._connection.execute(
            """
            INSERT INTO manifest_artifacts (manifest_digest, artifact_id, artifact_digest)
            VALUES (?, ?, ?)
            ON CONFLICT(manifest_digest, artifact_id) DO NOTHING
            """,
            (manifest_digest, artifact_id, artifact_digest),
        )
        row = self._connection.execute(
            """
            SELECT artifact_digest
            FROM manifest_artifacts
            WHERE manifest_digest = ? AND artifact_id = ?
            """,
            (manifest_digest, artifact_id),
        ).fetchone()
        if row is None or str(row[0]) != artifact_digest:
            raise sqlite3.IntegrityError("manifest artifact identity does not match its digest")

    def record_manifest_version(
        self,
        *,
        manifest_digest: str,
        version_id: str,
        definition_id: str,
        version_kind: str,
        name: str,
        content_sha256: str,
        canonical_contract_version: int,
    ) -> None:
        self._ensure_active()
        self._connection.execute(
            """
            INSERT INTO manifest_versions (
                manifest_digest,
                version_id,
                definition_id,
                version_kind,
                name,
                content_sha256,
                canonical_contract_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(manifest_digest, version_id) DO NOTHING
            """,
            (
                manifest_digest,
                version_id,
                definition_id,
                version_kind,
                name,
                content_sha256,
                canonical_contract_version,
            ),
        )
        row = self._connection.execute(
            """
            SELECT
                definition_id,
                version_kind,
                name,
                content_sha256,
                canonical_contract_version
            FROM manifest_versions
            WHERE manifest_digest = ? AND version_id = ?
            """,
            (manifest_digest, version_id),
        ).fetchone()
        expected = (
            definition_id,
            version_kind,
            name,
            content_sha256,
            canonical_contract_version,
        )
        if row is None or tuple(row) != expected:
            raise sqlite3.IntegrityError("manifest version metadata does not match its identity")


def _identifier_exists(connection: sqlite3.Connection, identifier: CanonicalIdentifier) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM canonical_identifiers
        WHERE canonical_id = ? AND entity_kind = ?
        """,
        (identifier.value, identifier.kind),
    ).fetchone()
    return row is not None


def open_store(
    database_path: Path,
    *,
    private_root: Path | None = None,
    software_commit: str = "UNKNOWN",
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> Store:
    _validate_migration_plan(migrations)
    path, _ = _validate_private_path(database_path, private_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer_lock = _acquire_writer_lock(path)
    new_database = not path.exists() or path.stat().st_size == 0
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, isolation_level=None)
        if not new_database:
            _verify_application_identity(connection)
        _configure_connection(connection, new_database=new_database)
        _verify_application_identity(connection)
        _verify_operating_profile(connection)
        _verify_integrity(connection)
        _verify_migrations(connection, migrations)
        if _schema_version(connection) > 0:
            _verify_schema_manifest(connection, migrations)
            _verify_canonical_reference_types(connection)
        try:
            _apply_migrations(
                connection,
                software_commit,
                migrations,
                new_database=new_database,
                database_path=path,
            )
        except sqlite3.DatabaseError as error:
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_FAILED",
                "A migration failed and its transaction was rolled back.",
            ) from error
        _verify_migrations(connection, migrations)
        _verify_schema_manifest(connection, migrations)
        _verify_canonical_reference_types(connection)
        if _schema_version(connection) >= 2:
            _verify_artifact_objects(connection, path)
        integrity_row = connection.execute("PRAGMA quick_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row is not None else "missing"
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        _record_integrity_observation(connection)
        applied_migrations = _applied_migrations(connection)
        status = StoreStatus(
            mode=StoreMode.READ_WRITE,
            schema_version=_schema_version(connection),
            applied_migrations=applied_migrations,
            migration_count=len(applied_migrations),
            integrity=integrity,
            foreign_key_violations=foreign_key_violations,
            pragmas=_pragma_status(connection),
            limits=_limit_status(connection),
        )
        return Store(path, connection, writer_lock, status)
    except StoreVerificationError as error:
        if connection is not None:
            connection.close()
        recovery_connection = _recovery_connection(path)
        return Store(
            path,
            recovery_connection,
            writer_lock,
            _recovery_status(recovery_connection, error.issue),
        )
    except sqlite3.DatabaseError as error:
        if connection is not None:
            connection.close()
        recovery_connection = _recovery_connection(path)
        issue = StoreIssue(
            code="MV-STORE-INTEGRITY_FAILED",
            message=f"SQLite could not verify the authoritative store: {error}",
        )
        return Store(
            path,
            recovery_connection,
            writer_lock,
            _recovery_status(recovery_connection, issue),
        )
    except BaseException:
        if connection is not None:
            connection.close()
        writer_lock.close()
        raise


def inspect_store(
    database_path: Path,
    *,
    private_root: Path | None = None,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> StoreInspection:
    _validate_migration_plan(migrations)
    path, _ = _validate_private_path(database_path, private_root)
    if not path.exists():
        return StoreInspection(
            path=str(path),
            status=InspectionStatus.NOT_CONFIGURED,
            schema_version=0,
            applied_migrations=(),
            integrity="not_checked",
            foreign_key_violations=0,
            pragmas={},
            limits={},
        )

    connection = _recovery_connection(path)
    if connection is None:
        return StoreInspection(
            path=str(path),
            status=InspectionStatus.RECOVERY_REQUIRED,
            schema_version=0,
            applied_migrations=(),
            integrity="unreadable",
            foreign_key_violations=-1,
            pragmas={},
            limits={},
            issues=(
                StoreIssue(
                    code="MV-STORE-INTEGRITY_FAILED",
                    message="SQLite could not read the authoritative store.",
                ),
            ),
        )
    try:
        _verify_application_identity(connection)
        _verify_operating_profile(connection)
        _verify_integrity(connection)
        _verify_migrations(connection, migrations)
        schema_version = _schema_version(connection)
        if schema_version < len(migrations):
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_REQUIRED",
                f"Database schema {schema_version} requires migration to {len(migrations)}.",
            )
        _verify_schema_manifest(connection, migrations)
        _verify_canonical_reference_types(connection)
        if schema_version >= 2:
            _verify_artifact_objects(connection, path)
        applied_migrations = _applied_migrations(connection)
        return StoreInspection(
            path=str(path),
            status=InspectionStatus.HEALTHY,
            schema_version=schema_version,
            applied_migrations=applied_migrations,
            integrity="ok",
            foreign_key_violations=0,
            pragmas=_pragma_status(connection),
            limits=_limit_status(connection),
        )
    except StoreVerificationError as error:
        recovery = _recovery_status(connection, error.issue)
        return StoreInspection(
            path=str(path),
            status=InspectionStatus.RECOVERY_REQUIRED,
            schema_version=recovery.schema_version,
            applied_migrations=recovery.applied_migrations,
            integrity=recovery.integrity,
            foreign_key_violations=recovery.foreign_key_violations,
            pragmas=recovery.pragmas,
            limits=recovery.limits,
            issues=recovery.issues,
        )
    except sqlite3.DatabaseError as error:
        return StoreInspection(
            path=str(path),
            status=InspectionStatus.RECOVERY_REQUIRED,
            schema_version=0,
            applied_migrations=(),
            integrity="unreadable",
            foreign_key_violations=-1,
            pragmas={},
            limits={},
            issues=(
                StoreIssue(
                    code="MV-STORE-INTEGRITY_FAILED",
                    message=f"SQLite could not verify the authoritative store: {error}",
                ),
            ),
        )
    finally:
        connection.close()

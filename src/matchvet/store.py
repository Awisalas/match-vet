from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from collections.abc import Iterator
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
        return cls(kind=kind, value=str(uuid.uuid7()))


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
            if len(words) < 3 or words[0:2] not in (["CREATE", "TABLE"], ["CREATE", "TRIGGER"]):
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
    actual_indexes: set[tuple[str, str, int, str, int]] = set()
    for table_name in (
        "application_metadata",
        "canonical_identifiers",
        "integrity_observations",
        "schema_migrations",
        "version_definitions",
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
) -> None:
    current_version = _schema_version(connection)
    if current_version < len(migrations) and not new_database:
        raise StoreVerificationError(
            "MV-STORE-MIGRATION_BACKUP_REQUIRED",
            "An existing store cannot migrate until a verified private backup is available.",
        )
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
            )
        except sqlite3.DatabaseError as error:
            raise StoreVerificationError(
                "MV-STORE-MIGRATION_FAILED",
                "A migration failed and its transaction was rolled back.",
            ) from error
        _verify_migrations(connection, migrations)
        _verify_schema_manifest(connection, migrations)
        _verify_canonical_reference_types(connection)
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

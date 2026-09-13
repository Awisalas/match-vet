from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from matchvet.store import (
    DEFENSIVE_QUERY_LIMITS,
    MIGRATIONS,
    CanonicalIdentifier,
    InspectionStatus,
    Migration,
    StoreBusyError,
    StoreMode,
    VersionIdentity,
    inspect_store,
    open_store,
)


def test_fresh_private_store_is_created_at_current_schema_version(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet" / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as store:
        status = store.status

        assert status.mode is StoreMode.READ_WRITE
        assert status.schema_version == len(MIGRATIONS)
        assert status.applied_migrations == tuple(range(1, len(MIGRATIONS) + 1))
        assert status.integrity == "ok"
        assert status.foreign_key_violations == 0

    assert database_path.is_file()


def test_existing_store_reopens_without_reapplying_migrations(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root) as first:
        assert first.status.migration_count == len(MIGRATIONS)

    with open_store(database_path, private_root=private_root) as reopened:
        assert reopened.status.mode is StoreMode.READ_WRITE
        assert reopened.status.schema_version == len(MIGRATIONS)
        assert reopened.status.applied_migrations == tuple(range(1, len(MIGRATIONS) + 1))
        assert reopened.status.migration_count == len(MIGRATIONS)


def test_migration_ledger_records_reproducibility_metadata(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    commit = "a" * 40
    with open_store(
        database_path,
        private_root=private_root,
        software_commit=commit,
    ):
        pass

    connection = sqlite3.connect(database_path)
    row = connection.execute(
        """
        SELECT
            migration_number,
            checksum,
            canonical_contract_version,
            minimum_application_version,
            maximum_application_version,
            result,
            software_commit
        FROM schema_migrations
        """
    ).fetchone()
    connection.close()

    assert row == (1, MIGRATIONS[0].checksum, 1, "0.1.0", "0.1.0", "COMPLETED", commit)


def test_store_enforces_the_authoritative_sqlite_profile(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        assert store.status.pragmas == {
            "application_id": 1_297_499_476,
            "auto_vacuum": 2,
            "busy_timeout": 5_000,
            "foreign_keys": 1,
            "journal_mode": "wal",
            "synchronous": 2,
        }
        assert store.status.limits == {
            name: limit for name, (_, limit) in DEFENSIVE_QUERY_LIMITS.items()
        }
        assert store._connection is not None
        with pytest.raises(sqlite3.OperationalError, match="too many attached databases"):
            store._connection.execute("ATTACH DATABASE ':memory:' AS forbidden")


def test_store_private_boundary_ignores_hostile_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path
    shared_root = Path("/storage/emulated/0")
    database_path = shared_root / f"matchvet-test-{CanonicalIdentifier.new('test').value}.sqlite3"
    monkeypatch.setenv("HOME", str(shared_root))
    monkeypatch.setenv("PREFIX", str(shared_root))
    monkeypatch.setenv("TERMUX__HOME", str(shared_root))
    monkeypatch.setenv("TERMUX__PREFIX", str(shared_root))

    with pytest.raises(ValueError, match="Termux private storage"):
        open_store(database_path, private_root=shared_root)

    assert not database_path.exists()


def test_inspection_refuses_pragma_drift_without_repairing_it(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    connection = sqlite3.connect(database_path)
    assert connection.execute("PRAGMA journal_mode = DELETE").fetchone() == ("delete",)
    connection.close()

    inspection = inspect_store(database_path, private_root=private_root)

    assert inspection.status is InspectionStatus.RECOVERY_REQUIRED
    assert inspection.issues[0].code == "MV-STORE-PRAGMA_MISMATCH"
    verification = sqlite3.connect(database_path)
    assert verification.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    verification.close()


def test_store_refuses_a_database_outside_private_storage() -> None:
    try:
        open_store(
            Path("/storage/emulated/0/matchvet-must-not-create.sqlite3"),
            private_root=Path("/storage/emulated/0"),
        )
    except ValueError as error:
        assert str(error) == (
            "The authoritative MatchVet database must be in Termux private storage."
        )
    else:
        raise AssertionError("A shared-storage database was accepted.")


def test_canonical_identifiers_and_version_identity_survive_reopen(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    team_id = CanonicalIdentifier.new("team")
    version = VersionIdentity(
        identifier=CanonicalIdentifier.new("version"),
        definition_id=CanonicalIdentifier.new("version_definition"),
        kind="canonical_contract",
        name="v1",
        content_sha256="a" * 64,
        canonical_contract_version=1,
    )

    with (
        open_store(database_path, private_root=private_root) as store,
        store.transaction() as transaction,
    ):
        transaction.add_identifier(team_id)
        transaction.add_version(version)

    with open_store(database_path, private_root=private_root) as reopened:
        assert reopened.has_identifier(team_id)
        assert reopened.version(version.identifier) == version


def test_version_identity_is_immutable_in_the_database(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    version = VersionIdentity(
        identifier=CanonicalIdentifier.new("version"),
        definition_id=CanonicalIdentifier.new("version_definition"),
        kind="environment",
        name="termux-v1",
        content_sha256="b" * 64,
        canonical_contract_version=1,
    )
    with (
        open_store(database_path, private_root=private_root) as store,
        store.transaction() as transaction,
    ):
        transaction.add_version(version)

    connection = sqlite3.connect(database_path)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE version_definitions SET name = 'changed' WHERE version_id = ?",
            (version.identifier.value,),
        )
    connection.close()


def test_wrong_canonical_reference_types_force_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    connection = sqlite3.connect(database_path)
    trigger_sql = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE name = 'version_definitions_typed_identifiers'"
    ).fetchone()
    assert trigger_sql is not None
    wrong_version_id = CanonicalIdentifier.new("team")
    wrong_definition_id = CanonicalIdentifier.new("league")
    connection.executemany(
        """
        INSERT INTO canonical_identifiers (canonical_id, entity_kind, created_at_utc)
        VALUES (?, ?, '2026-09-12T00:00:00+00:00')
        """,
        (
            (wrong_version_id.value, wrong_version_id.kind),
            (wrong_definition_id.value, wrong_definition_id.kind),
        ),
    )
    connection.commit()
    version_insert = """
        INSERT INTO version_definitions (
            version_id,
            definition_id,
            version_kind,
            name,
            content_sha256,
            canonical_contract_version,
            created_at_utc,
            predecessor_id
        ) VALUES (?, ?, 'policy', 'corrupt', ?, 1, '2026-09-12T00:00:00+00:00', NULL)
        """
    values = (wrong_version_id.value, wrong_definition_id.value, "f" * 64)
    with pytest.raises(sqlite3.IntegrityError, match="typed canonical identifiers"):
        connection.execute(version_insert, values)
    connection.rollback()

    connection.execute("DROP TRIGGER version_definitions_typed_identifiers")
    connection.execute(version_insert, values)
    connection.execute(str(trigger_sql[0]))
    connection.commit()
    connection.close()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-CANONICAL_TYPE_MISMATCH"


def test_version_predecessor_must_share_the_stable_logical_identity(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    definition_id = CanonicalIdentifier.new("version_definition")
    first = VersionIdentity(
        identifier=CanonicalIdentifier.new("version"),
        definition_id=definition_id,
        kind="policy",
        name="v1",
        content_sha256="1" * 64,
        canonical_contract_version=1,
    )
    wrong_lineage = VersionIdentity(
        identifier=CanonicalIdentifier.new("version"),
        definition_id=CanonicalIdentifier.new("version_definition"),
        kind="policy",
        name="v2",
        content_sha256="2" * 64,
        canonical_contract_version=1,
        predecessor_id=first.identifier.value,
    )
    successor = replace(
        wrong_lineage,
        identifier=CanonicalIdentifier.new("version"),
        definition_id=definition_id,
        content_sha256="3" * 64,
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        with store.transaction() as transaction:
            transaction.add_version(first)
        with (
            pytest.raises(sqlite3.IntegrityError, match="same definition"),
            store.transaction() as transaction,
        ):
            transaction.add_version(wrong_lineage)
        with store.transaction() as transaction:
            transaction.add_version(successor)

        assert not store.has_identifier(wrong_lineage.identifier)
        assert store.version(successor.identifier) == successor


def test_changed_applied_migration_enters_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    changed_plan = (*MIGRATIONS[:-1], replace(MIGRATIONS[-1], name="changed_after_release"))
    with open_store(
        database_path,
        private_root=private_root,
        migrations=changed_plan,
    ) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-MIGRATION_CHECKSUM_MISMATCH"
        with (
            pytest.raises(PermissionError, match="read-only recovery"),
            recovered.transaction(),
        ):
            pass


def test_applied_migration_ledger_is_immutable(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass

    connection = sqlite3.connect(database_path)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE migration_number = 1",
            ("0" * 64,),
        )
    connection.close()


def test_schema_drift_enters_recovery_without_recreating_missing_objects(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    connection = sqlite3.connect(database_path)
    connection.execute("DROP TRIGGER schema_migrations_no_update")
    connection.commit()
    connection.close()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-SCHEMA_MANIFEST_MISMATCH"

    verification = sqlite3.connect(database_path)
    assert verification.execute(
        "SELECT count(*) FROM sqlite_schema WHERE name = 'schema_migrations_no_update'"
    ).fetchone() == (0,)
    verification.close()


def test_migration_failure_rolls_back_every_statement(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    failing_migration = replace(
        MIGRATIONS[0],
        name="failing_initial_migration",
        statements=(
            *MIGRATIONS[0].statements,
            "CREATE TABLE must_roll_back (value TEXT) STRICT",
            "INSERT INTO table_that_does_not_exist VALUES (1)",
        ),
    )

    with open_store(
        database_path,
        private_root=private_root,
        migrations=(failing_migration,),
    ) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-MIGRATION_FAILED"

    connection = sqlite3.connect(database_path)
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    }
    assert "must_roll_back" not in tables
    assert tables == set()
    assert connection.execute("PRAGMA user_version").fetchone() == (0,)
    connection.close()


def test_existing_store_refuses_migration_without_verified_backup(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    second_migration = Migration(
        number=4,
        name="requires_backup",
        statements=("CREATE TABLE second_table (value TEXT) STRICT",),
    )

    with open_store(
        database_path,
        private_root=private_root,
        migrations=(*MIGRATIONS, second_migration),
    ) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-MIGRATION_BACKUP_REQUIRED"

    connection = sqlite3.connect(database_path)
    assert connection.execute("PRAGMA user_version").fetchone() == (len(MIGRATIONS),)
    assert connection.execute(
        "SELECT count(*) FROM sqlite_schema WHERE name = 'second_table'"
    ).fetchone() == (0,)
    connection.close()


def test_t03_migration_upgrades_a_t02_store_after_private_backup(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with open_store(database_path, private_root=private_root, migrations=MIGRATIONS[:1]) as store:
        assert store.status.schema_version == 1

    with open_store(database_path, private_root=private_root) as upgraded:
        assert upgraded.status.mode is StoreMode.READ_WRITE
        assert upgraded.status.schema_version == len(MIGRATIONS)
        assert upgraded.status.applied_migrations == tuple(range(1, len(MIGRATIONS) + 1))
    assert not list(private_root.glob("*.migration-backup"))


def test_migration_plan_must_be_sequential(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    out_of_order = Migration(number=5, name="skipped_four", statements=("SELECT 1",))

    with pytest.raises(ValueError, match="sequential"):
        open_store(
            private_root / "matchvet.sqlite3",
            private_root=private_root,
            migrations=(*MIGRATIONS, out_of_order),
        )


def test_newer_database_schema_enters_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    connection = sqlite3.connect(database_path)
    connection.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    connection.close()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-SCHEMA_TOO_NEW"


def test_non_matchvet_database_enters_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "other.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE unrelated (value TEXT)")
    connection.commit()
    connection.close()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-APPLICATION_ID_MISMATCH"


def test_incomplete_migration_enters_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    second_migration = Migration(
        number=4,
        name="second_test_migration",
        statements=("CREATE TABLE second_table (value TEXT) STRICT",),
    )
    connection = sqlite3.connect(database_path)
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
        ) VALUES (
                4, ?, ?, 1, '0.1.0', '0.1.0',
            '2026-09-12T00:00:00+00:00', NULL, 'IN_PROGRESS', 'test'
        )
        """,
        (second_migration.name, second_migration.checksum),
    )
    connection.execute("PRAGMA user_version = 4")
    connection.commit()
    connection.close()

    with open_store(
        database_path,
        private_root=private_root,
        migrations=(*MIGRATIONS, second_migration),
    ) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.issues[0].code == "MV-STORE-MIGRATION_INCOMPLETE"


def test_foreign_key_violation_forces_read_only_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    trigger_sql = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE name = 'version_definitions_typed_identifiers'"
    ).fetchone()
    assert trigger_sql is not None
    connection.execute("DROP TRIGGER version_definitions_typed_identifiers")
    definition_id = CanonicalIdentifier.new("version_definition")
    connection.execute(
        """
        INSERT INTO canonical_identifiers (canonical_id, entity_kind, created_at_utc)
        VALUES (?, 'version_definition', '2026-09-12T00:00:00+00:00')
        """,
        (definition_id.value,),
    )
    connection.execute(
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
        ) VALUES (?, ?, 'environment', 'broken', ?, 1, '2026-09-12T00:00:00+00:00', NULL)
        """,
        (CanonicalIdentifier.new("version").value, definition_id.value, "c" * 64),
    )
    connection.execute(str(trigger_sql[0]))
    connection.commit()
    connection.close()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.foreign_key_violations == 1
        assert recovered.status.issues[0].code == "MV-STORE-FOREIGN_KEY_INTEGRITY_FAILED"


def test_foreign_keys_are_enforced_for_normal_writes(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    with open_store(database_path, private_root=private_root):
        pass
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("DROP TRIGGER version_definitions_typed_identifiers")
    connection.execute("DROP TRIGGER version_definitions_same_lineage")
    version_id = CanonicalIdentifier.new("version")
    definition_id = CanonicalIdentifier.new("version_definition")
    connection.executemany(
        """
        INSERT INTO canonical_identifiers (canonical_id, entity_kind, created_at_utc)
        VALUES (?, ?, '2026-09-12T00:00:00+00:00')
        """,
        (
            (version_id.value, version_id.kind),
            (definition_id.value, definition_id.kind),
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(
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
            ) VALUES (?, ?, 'policy', 'v2', ?, 1, '2026-09-12T00:00:00+00:00', ?)
            """,
            (
                version_id.value,
                definition_id.value,
                "d" * 64,
                CanonicalIdentifier.new("version").value,
            ),
        )
    connection.close()


def test_corrupt_database_enters_unreadable_recovery_mode(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    database_path.write_bytes(b"this is not a sqlite database")

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.status.mode is StoreMode.READ_ONLY_RECOVERY
        assert recovered.status.integrity == "unreadable"
        assert recovered.status.issues[0].code == "MV-STORE-INTEGRITY_FAILED"
        with (
            pytest.raises(PermissionError, match="read-only recovery"),
            recovered.transaction(),
        ):
            pass


def test_transaction_failure_rolls_back_the_complete_write_unit(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    identifier = CanonicalIdentifier.new("fixture")

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        with (
            pytest.raises(RuntimeError, match="fault injection"),
            store.transaction() as transaction,
        ):
            transaction.add_identifier(identifier)
            raise RuntimeError("fault injection")

        assert not store.has_identifier(identifier)


def test_transaction_handle_cannot_write_after_its_bounded_unit(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        with store.transaction() as transaction:
            pass

        with pytest.raises(RuntimeError, match="transaction is closed"):
            transaction.add_identifier(CanonicalIdentifier.new("team"))


def test_forked_child_cannot_use_an_inherited_transaction(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    parent_identifier = CanonicalIdentifier.new("team")
    child_identifier = CanonicalIdentifier.new("team")

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        with store.transaction() as transaction:
            child_pid = os.fork()
            if child_pid == 0:
                try:
                    transaction.add_identifier(child_identifier)
                except RuntimeError:
                    os._exit(0)
                os._exit(1)
            _, child_status = os.waitpid(child_pid, 0)
            assert os.waitstatus_to_exitcode(child_status) == 0
            transaction.add_identifier(parent_identifier)

        assert store.has_identifier(parent_identifier)
        assert not store.has_identifier(child_identifier)


def test_second_application_writer_is_refused(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    with (
        open_store(database_path, private_root=private_root),
        pytest.raises(StoreBusyError) as raised,
    ):
        open_store(database_path, private_root=private_root)

    assert raised.value.code == "MV-STORE-WRITER_BUSY"


def test_forked_child_cannot_release_the_parent_writer_lock(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"

    store = open_store(database_path, private_root=private_root)
    try:
        child_pid = os.fork()
        if child_pid == 0:
            store.close()
            os._exit(0)
        _, child_status = os.waitpid(child_pid, 0)
        assert os.waitstatus_to_exitcode(child_status) == 0

        with pytest.raises(StoreBusyError):
            open_store(database_path, private_root=private_root)
    finally:
        store.close()

    with open_store(database_path, private_root=private_root) as reopened:
        assert reopened.status.mode is StoreMode.READ_WRITE


def test_committed_wal_content_is_visible_after_startup_recovery(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    database_path = private_root / "matchvet.sqlite3"
    identifier = CanonicalIdentifier.new("team")
    with open_store(database_path, private_root=private_root):
        pass

    interrupted_writer = subprocess.run(
        [
            sys.executable,
            "-c",
            '''
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA wal_autocheckpoint = 0")
connection.execute(
    """
    INSERT INTO canonical_identifiers (canonical_id, entity_kind, created_at_utc)
    VALUES (?, ?, '2026-09-12T00:00:00+00:00')
    """,
    (sys.argv[2], sys.argv[3]),
)
connection.commit()
os._exit(0)
            ''',
            str(database_path),
            identifier.value,
            identifier.kind,
        ],
        check=False,
    )
    assert interrupted_writer.returncode == 0
    assert database_path.with_name(f"{database_path.name}-wal").exists()

    with open_store(database_path, private_root=private_root) as recovered:
        assert recovered.has_identifier(identifier)

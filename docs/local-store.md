# Local store

MatchVet keeps one authoritative SQLite database in Termux private storage. The default path is `$HOME/.local/share/matchvet/matchvet.sqlite3`. Shared Android storage is never accepted as the live database location. The trusted private-storage boundary comes from the running Termux Python installation, not mutable environment variables.

T02 owns only the store foundation. It does not create artifact storage, snapshots, research runs, evidence, models, or reports.

## Open and inspect

Application code opens the store through `matchvet.store.open_store`. Opening a fresh store creates its parent directory, takes the single-writer lock, applies the schema in a bounded transaction, and verifies the result. Each returned `Store` must be closed or used as a context manager.

`matchvet doctor` inspects the default store. Pass `--store PATH` to inspect another private-storage database. Inspection is read-only. It reports `HEALTHY`, `NOT_CONFIGURED`, or `RECOVERY_REQUIRED` together with schema, migration, integrity, foreign-key, and SQLite setting details.

## SQLite profile

Every authoritative writer uses:

- WAL journal mode
- foreign-key enforcement
- `synchronous=FULL`
- a 5,000 millisecond busy timeout
- incremental auto-vacuum
- the MatchVet SQLite application ID
- defensive limits of 1 MiB SQL text, 512 columns, expression depth 100, and zero attached databases

One private lock file permits one MatchVet writer coordinator. Write work uses explicit bounded transactions. Network, parsing, modelling, and report work must remain outside them.

## Schema version 1

The initial schema contains only:

- the immutable migration ledger
- application metadata
- typed canonical identifier records
- immutable version definitions with separate stable logical IDs, predecessor links, and content digests
- append-only integrity observations

Later tickets add their own entities through new migrations.

## Migration rules

Migrations are application-owned, sequential, and forward-only. Their SHA-256 checksum covers the migration number, name, SQL, canonical-contract version, and compatible application range. MatchVet verifies every applied entry and the live tables, constraints, indexes, and triggers before writing and after each migration.

Never edit a released migration. Add the next numbered migration. Transactional DDL and its completed ledger entry commit together. A failure rolls back the whole migration. An incomplete ledger entry, changed checksum, missing migration, schema drift, or newer schema forces read-only recovery.

T02 can apply the initial migration to a fresh database. It refuses to migrate an existing store until a later backup capability can create and verify the required private SQLite backup. This prevents future schema work from weakening the settled pre-migration recovery rule.

## Recovery behavior

Startup checks the application identity, required SQLite settings, `quick_check`, foreign keys, schema version, and migration checksums. Migrations also run full integrity checks before and after their transaction.

Any failed requirement returns a store in `READ_ONLY_RECOVERY`. The public transaction API refuses writes in that mode. MatchVet preserves the database as found and does not run repair SQL, rewrite migration history, or delete records. Backup and restore arrive in later tickets.

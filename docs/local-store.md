# Local store

MatchVet keeps one authoritative SQLite database and content-addressed object store in Termux private storage. The default database path is `$HOME/.local/share/matchvet/matchvet.sqlite3`. Shared Android storage is never accepted as live state. The trusted private-storage boundary comes from the running Termux Python installation, not mutable environment variables.

T02 owns the store foundation. T03 adds artifact and snapshot records. T04 adds operational
research-run, work-unit, attempt, checkpoint, and completion-publication records. T07 adds
canonical people, contextual source identities and origins, retained or citation-only evidence
captures, cutoff assessments, source status history, corrections, corroboration, and immutable
conflict records. Models, decisions, and reports remain outside this schema.
T06 adds source captures, canonical league/team/fixture identities, structured match statistics,
append-only fixture revisions, source assertions, and retained conflict records. Private source
artifacts remain subject to their source-specific rights and retention metadata. T08 adds
append-only workload schedule context, frozen workload evidence, verified venue locations,
Open-Meteo forecast captures, and Important weather evidence.

## Open and inspect

Application code opens the store through `matchvet.store.open_store`. Opening a fresh store creates its parent directory, takes the single-writer lock, applies the schema in a bounded transaction, and verifies the result. Each returned `Store` must be closed or used as a context manager.

`matchvet doctor` inspects the default store. Pass `--store PATH` to inspect another private-storage database. Inspection is read-only. It reports `HEALTHY`, `NOT_CONFIGURED`, or `RECOVERY_REQUIRED` together with schema, migration, integrity, foreign-key, SQLite setting, and artifact-reference details. Artifact publication and manifest contracts are documented in [the artifact guide](artifacts.md).

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

## Schema version 7

The schema contains:

- the immutable migration ledger
- application metadata
- typed canonical identifier records
- immutable version definitions with separate stable logical IDs, predecessor links, and content digests
- append-only integrity observations
- immutable artifact catalog and Snapshot Manifest membership
- preserved Research Runs and their exact input digests
- bounded work units and attempt history
- immutable safe-boundary checkpoints
- atomic operational completion publications
- source identities and capture metadata, including rights and retention policy
- canonical league, season, team, fixture, and fixture-revision records
- structured statistics, source assertions, unresolved mappings, and conflict sets
- canonical people and contextual evidence assertions for fixtures, teams, and people
- source status history, cutoff eligibility, independent-origin corroboration, corrections, and
  immutable contextual conflict/resolution records
- append-only domestic-cup, continental, international, and other workload schedule context
- frozen Important workload evidence with rest, turnaround, density, congestion, and provenance
- verified venue location provenance and bounded Open-Meteo forecast captures
- cutoff-classified Important weather evidence, including explicit UNKNOWN states

Later tickets add their own entities through new migrations.

## Migration rules

Migrations are application-owned, sequential, and forward-only. Their SHA-256 checksum covers the migration number, name, SQL, canonical-contract version, and compatible application range. MatchVet verifies every applied entry and the live tables, constraints, indexes, and triggers before writing and after each migration.

Never edit a released migration. Add the next numbered migration. Transactional DDL and its completed ledger entry commit together. A failure rolls back the whole migration. An incomplete ledger entry, changed checksum, missing migration, schema drift, or newer schema forces read-only recovery.

The initial migration creates the T02 foundation. Migration 2 adds the T03 artifact catalog and
Snapshot Manifest membership. Migration 3 adds the T04 run lifecycle. Existing stores receive a
verified private SQLite pre-migration copy before a released migration runs. Migration 4 adds the
T06 structured-ingestion records and append-only source assertions. Migration 5 adds T05
Matchweek freeze records and cutoff membership. Migration 6 adds T07 contextual evidence
records. Migration 7 adds T08 workload and weather evidence records. A custom or
unsupported migration plan remains refused until a later backup capability can provide the
required recovery export.

## Recovery behavior

Startup checks the application identity, required SQLite settings, `quick_check`, foreign keys, schema version, and migration checksums. Migrations also run full integrity checks before and after their transaction.

Any failed requirement returns a store in `READ_ONLY_RECOVERY`. The public transaction API refuses writes in that mode. MatchVet preserves the database as found and does not run repair SQL, rewrite migration history, or delete records. Backup and restore arrive in later tickets.

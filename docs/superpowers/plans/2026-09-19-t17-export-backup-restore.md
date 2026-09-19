# T17 export, backup, and restore implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified, marker-gated export and recovery layer for completed MatchVet reports, the authoritative SQLite store, and every catalogued content-addressed object, with safe CLI contracts.

**Architecture:** `matchvet.t17` owns canonical bundle manifests, resource preflight, shared-storage staging/copy/read-back verification, SQLite online backup, and private-target restore. It consumes T16's completed audit/report readers and T03/T04's immutable artifact/run contracts without adding a second authoritative store or changing existing frozen records. Export and backup destinations are ordinary copies; restore validates a complete bundle in isolation, installs only into a new private target, and refuses collisions.

**Tech Stack:** Python 3.14 standard library, `sqlite3.Connection.backup`, SHA-256 streaming digests, canonical UTF-8 JSON, existing T03 `ArtifactStore`, T04 resource budgets, T16 audit/report readers, `argparse`, pytest.

**Spec:** `CONTEXT.md`, GitHub issue #1, and GitHub issue #34, with completed T03/T04/T16 contracts in `docs/artifacts.md`, `docs/local-store.md`, `docs/run-lifecycle.md`, and `docs/matchweek-reports.md`.

## Global Constraints

- Authoritative SQLite and content-addressed objects stay in Termux private storage; shared storage is export and backup only.
- Export accepts only a T16 `COMPLETE` audit and never emits a completed bundle for an incomplete run.
- Export files are `report.md`, `audit.json`, `manifest.json`, and an explicit `COMPLETE` marker; all completed visibility is marker-gated.
- Recovery bundles use SQLite online backup, full SQLite integrity and foreign-key checks, a canonical manifest, every catalogued object required by the database, member SHA-256 digests, and a `COMPLETE` marker.
- Restore verifies compatibility, database integrity, foreign keys, object existence, and every digest before installing into a new private target.
- No existing authoritative store, frozen record, audit, grade, policy, version, or protected object is overwritten or deleted.
- Restricted or citation-only raw evidence is omitted from exports with an explicit retention omission; backup copies preserve the protected bytes needed to restore the database and are never treated as redistribution.
- All operations estimate temporary growth before creating staging, honor T04's storage/free-space/memory/time/concurrency floors, and use only operation-owned disposable cleanup.
- Canonical bytes use UTF-8 JSON, sorted keys, compact separators, `ensure_ascii=True`, and no runtime timestamps in deterministic bundle manifests.
- Stable failures expose `status`, `code`, explanation, source/destination, and an exact recovery command; shared copies are never executable or authoritative state.

## Review Focus

- A complete T16 publication whose associated run is still `INCOMPLETE` must be refused before any destination mutation. Test in Task 2 with an incomplete-run export fixture.
- A bundle with a valid-looking marker but a changed manifest/member/database must fail before restore target creation. Test tamper and missing-marker cases in Tasks 2 and 3.
- A rights-safe export must distinguish reusable retained evidence from restricted retained and citation-only captures without copying prohibited bytes. Test mixed capture rights in Task 2.
- A backup must remain restorable when the source database is in WAL mode and its objects include manifests, completion publications, and protected evidence. Test online-backup round trip in Task 3.
- A failed restore must leave both the current authoritative store and any pre-existing target collision unchanged, including after SQLite/FK/version/object failures. Test restore atomicity and collision in Task 4.

---

### Task 1: Define T17 canonical contracts and resource-safe filesystem helpers

**Files:**
- Create: `src/matchvet/t17.py`
- Create: `tests/test_t17.py`

**Interfaces:**
- Consumes: T03 `ArtifactMetadata`/`ArtifactStore`, T04 `ResourceEstimate`/`ResourceObservation`/`preflight_resources`, T16 `MatchweekAudit`/`read_audit`/`render_markdown_report`, and `MIGRATIONS`/`APPLICATION_ID`.
- Produces: `T17Error`, `ExportManifest`, `BackupManifest`, `OperationVerification`, `ExportResult`, `BackupResult`, `RestoreResult`, `preflight_operation`, `verify_export`, `verify_backup`, `export_matchweek`, `backup_store`, and `restore_backup`.

- [ ] **Step 1: Write the failing contract tests**

  Add tests for canonical manifest bytes and IDs, marker key/state validation, digest and length helpers, private/shared path boundaries, deterministic resource estimates, and stable error fields. Use small real files and a fresh T03 store; do not mock digest results.

- [ ] **Step 2: Run the focused tests and verify the expected red failure**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -q`

  Expected: FAIL because `matchvet.t17` and its public contract types do not exist.

- [ ] **Step 3: Implement only the contracts and helpers**

  Implement canonical JSON/digest helpers, strict manifest parsers, marker parsers, safe regular-file/path checks, streaming copy with fsync/read-back verification, private staging cleanup, operation resource estimation through T04 preflight, and typed result/error values. Keep the operation functions present but raising a stable `MV-T17-NOT_IMPLEMENTED` only if needed for import compatibility; do not add CLI behavior in this task.

- [ ] **Step 4: Run the focused tests and verify green**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -q`

  Expected: PASS for the contract/helper tests.

- [ ] **Step 5: Run type checks for the new seam**

  Run: `.venv/bin/mypy src/matchvet/t17.py tests/test_t17.py`

  Expected: exit 0 with no type errors.

### Task 2: Implement marker-gated completed Matchweek export

**Files:**
- Modify: `src/matchvet/t17.py`
- Modify: `tests/test_t17.py`
- Modify: `docs/artifacts.md`
- Modify: `docs/matchweek-reports.md`

**Interfaces:**
- Consumes: Task 1 contracts; T16 `read_audit`, `render_markdown_report`, `MatchweekAudit`; T07/T06 rights columns in `evidence_captures` and `source_captures`.
- Produces: `export_matchweek(database_path, destination, private_root=None, matchweek_id=None, include_raw_evidence=False, resource_observation=None) -> ExportResult` and `verify_export(destination) -> OperationVerification`.

- [ ] **Step 1: Write failing export tests**

  Cover successful export, deterministic report/audit/manifest digests across two destinations, complete reproducibility/version metadata, reusable raw evidence inclusion, restricted/citation-only omission, incomplete-run refusal, destination collision, missing completion marker, digest mismatch, read-back failure injection, and `KeyboardInterrupt`/`.partial` visibility without a completed marker.

- [ ] **Step 2: Run export tests and verify expected red failure**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'export' -q`

  Expected: FAIL because export and verification are not implemented.

- [ ] **Step 3: Implement export and verification**

  Read only the final T16 publication, require `publication_state == COMPLETE`, require `audit.run.state == COMPLETE` when a run identity is present, render T16's deterministic report, select raw evidence only when retained and redistributable under `RETAIN_REUSABLE`, record all omitted restricted/citation-only/requested-out captures, and build a deterministic manifest with required T16 reproducibility and version data. Stage privately, copy to `<destination>.partial`, fsync every file, read back and verify every member, publish final names without relying on cross-filesystem directory rename, write canonical `COMPLETE` last, then verify the final bundle. On safe exception remove only operation-owned staging; on interruption leave unmarked partial state.

- [ ] **Step 4: Run export tests and verify green**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'export' -q`

  Expected: PASS for all export tests.

- [ ] **Step 5: Update export contract documentation**

  Document bundle layout, marker gating, rights omissions, destination safety, and verification behavior in the two T17-scoped docs.

### Task 3: Implement verified SQLite online backup bundles

**Files:**
- Modify: `src/matchvet/t17.py`
- Modify: `tests/test_t17.py`
- Modify: `docs/local-store.md`

**Interfaces:**
- Consumes: Task 1 contracts; existing private store path validation; T03 artifact catalog and object path contract; `sqlite3.Connection.backup`; current migration checksums.
- Produces: `backup_store(database_path, destination, private_root=None, resource_observation=None) -> BackupResult` and `verify_backup(destination) -> OperationVerification`.

- [ ] **Step 1: Write failing backup tests**

  Cover online backup success, inclusion of every catalogued reachable object, full integrity/FK verification, deterministic manifest identity, shared `.partial` interruption, missing marker, manifest/member/database digest mismatch, corrupt/incomplete bundle rejection, destination collision, and T04 resource-floor refusal before mutation.

- [ ] **Step 2: Run backup tests and verify expected red failure**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'backup' -q`

  Expected: FAIL because backup and verification are not implemented.

- [ ] **Step 3: Implement backup and verification**

  Inspect the healthy private source read-only, run full `integrity_check` and `foreign_key_check`, take the database with `Connection.backup` into private staging, enumerate the exact catalogued artifact rows, stream/copy every object under its canonical relative path, create a deterministic compatibility manifest with migration checksums and member metadata, copy/read back into a shared `.partial` bundle, verify the destination database and every object, and write `COMPLETE` only after verification. Exclude locks, WAL sidecars, caches, and any staging debris from the bundle.

- [ ] **Step 4: Run backup tests and verify green**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'backup' -q`

  Expected: PASS for all backup tests.

- [ ] **Step 5: Update recovery documentation**

  Document the bundle layout, online-backup and object reachability rules, compatibility fields, and shared-storage non-authoritative boundary in `docs/local-store.md`.

### Task 4: Implement safe restore into a new private target

**Files:**
- Modify: `src/matchvet/t17.py`
- Modify: `tests/test_t17.py`
- Modify: `docs/local-store.md`

**Interfaces:**
- Consumes: Task 3 `verify_backup`, `BackupManifest`, object copier, current `MIGRATIONS`, and private store validation.
- Produces: `restore_backup(source, target_database_path, private_root=None, resource_observation=None) -> RestoreResult`.

- [ ] **Step 1: Write failing restore tests**

  Cover successful restore into a fresh private target, digest-equivalent restored database/object state, refusal of corrupt/incomplete/tampered backups, missing protected object, SQLite integrity failure, foreign-key failure, incompatible schema/migration manifest, target collision, and injected activation failure proving the authoritative source remains unchanged.

- [ ] **Step 2: Run restore tests and verify expected red failure**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'restore' -q`

  Expected: FAIL because restore is not implemented.

- [ ] **Step 3: Implement restore and activation**

  Validate the backup fully and preflight the target growth before creating private staging. Require a new private target and reject an existing target database or incompatible parent collision. Copy database and objects into a private `.restore...partial` tree, verify all manifest digests and compatibility again, run full SQLite integrity and foreign-key checks, open the staged store through the existing T03/T04 verification path, then install only into the new target. Verify the installed target once more, remove only operation-owned staging, and leave the authoritative source untouched on every failure.

- [ ] **Step 4: Run restore tests and verify green**

  Run: `.venv/bin/python -m pytest tests/test_t17.py -k 'restore' -q`

  Expected: PASS for all restore tests.

### Task 5: Complete CLI contracts and end-to-end integration

**Files:**
- Modify: `src/matchvet/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_t17.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2 `export_matchweek`, Task 3 `backup_store`/`verify_backup`, Task 4 `restore_backup`.
- Produces: `matchvet export`, `matchvet backup`, `matchvet backup --verify`, and `matchvet restore` with text and JSON status contracts.

- [ ] **Step 1: Write failing CLI tests**

  Cover parser/options, successful JSON and text output for export/backup/verify/restore, source/destination paths, manifest and digest identities, verification result, nonzero stable errors, incomplete refusal, and recovery guidance.

- [ ] **Step 2: Run CLI tests and verify expected red failure**

  Run: `.venv/bin/python -m pytest tests/test_cli.py tests/test_t17.py -k 'cli or export or backup or restore' -q`

  Expected: FAIL because the subcommands and handlers are not registered.

- [ ] **Step 3: Implement CLI handlers and docs**

  Add explicit destination/source/target arguments plus safe aliases, preserve `--store` and `--json`, return structured operation results on success, and convert every `T17Error` to nonzero `REFUSED` or `INCOMPLETE` output with source, destination, manifest identity, verification, stable code, and recovery command. Add the four commands to the README examples.

- [ ] **Step 4: Run CLI tests and verify green**

  Run: `.venv/bin/python -m pytest tests/test_cli.py tests/test_t17.py -q`

  Expected: PASS.

### Task 6: Full verification, bounded Termux smoke, review, commit, push, and issue close

**Files:**
- Modify only T17 files left by Tasks 1-5 after review fixes.

- [ ] **Step 1: Run formatter and lint**

  Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`

  Expected: exit 0.

- [ ] **Step 2: Run mypy**

  Run: `.venv/bin/mypy`

  Expected: exit 0.

- [ ] **Step 3: Run the full test suite**

  Run: `.venv/bin/python -m pytest`

  Expected: exit 0 with zero failures.

- [ ] **Step 4: Run bounded Termux smoke and manual corruption refusal**

  In a fresh private temp root and controlled shared temp root, produce one complete T16 Matchweek artifact set, export it, create and verify a backup, restore it into a separate fresh private target, compare report/audit/object/manifest digests, then alter one backup member and record the refused restore code. Keep the smoke bounded and offline.

- [ ] **Step 5: Perform code review against T17 and storage/recovery invariants**

  Review the complete diff against #34, #1, `CONTEXT.md`, T03/T04/T16 docs, and the tests. Fix every Critical or Important finding with a failing regression test first; record any deferred Minor in the ledger.

- [ ] **Step 6: Commit and push the focused change**

  Run:

  ```bash
  git add src/matchvet/t17.py src/matchvet/cli.py tests/test_t17.py tests/test_cli.py docs/artifacts.md docs/matchweek-reports.md docs/local-store.md README.md docs/superpowers/plans/2026-09-19-t17-export-backup-restore.md
  git commit -m "feat: add MatchVet export backup and restore"
  git push origin main
  ```

  Expected: the commit exists on `main` and the push succeeds.

- [ ] **Step 7: Close #34 only after every acceptance criterion is evidenced**

  Run `gh issue close 34 --comment "Implemented in <commit>; checks and smoke evidence: ..."` only after the full verification, smoke, corruption refusal, and review pass. Report the commit, files, commands, smoke results, recovery behavior, limitations, and newly unblocked frontier.

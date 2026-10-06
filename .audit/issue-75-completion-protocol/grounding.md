# Persistence grounding for #75

This traces the existing repository at the start of the completion-protocol investigation. Source citations name real files and lines. The proposed owner and completion capability are not implemented. Only this grounding record was written during this trace; no database was opened and no old proof file was changed.

## Overview

F16 already produces and replays an exact whole-Matchweek graph. `ArtifactStore` supplies durable object publication followed by an atomic SQLite catalog transaction. A generic `SnapshotManifest` can occupy an immutable unique snapshot slot, but its existing verification timestamp is sampled before that publication. Nothing in the current API turns a successful *new* selection commit into durable evidence that the commit had already completed before T.

The narrow missing layer is a domain-owned completion operation. It must distinguish a newly committed assignment from existing-key replay, observe repository time after the former, and permit exactly one receipt publication using that live observation. Existing manifest/index storage can encode the receipt without a migration; existing public publication APIs do not enforce its provenance.

## Key concepts

- `F16Manifest` binds F06, cutoff policy, profile, policy and each membership's evidence/model/decision/result identities. Its replay resolves the exact F06 freeze, complete INCLUDED membership denominator and per-child lineage (`src/matchvet/f16.py:244`, `:269`, `:280`, `:303`, `:322`). F16 itself currently finds manifests by exact request inputs, not by a sole logical-Matchweek selection (`src/matchvet/f16.py:451`).
- `SnapshotManifest` carries a typed Matchweek identity, cutoff identifier and UTC boundary, version identity, artifact references, completeness, creation and verification timestamps, and optional parent snapshot ID (`src/matchvet/artifacts.py:172`). The canonical bytes and digest include these bindings (`src/matchvet/artifacts.py:262`).
- `snapshot_manifests.snapshot_id` is unique, while `manifest_digest` identifies exact content. Update/delete triggers make the row immutable (`src/matchvet/store.py:353`, `:380`, `:505`, `:512`). A stable slot must be derived only from logical Matchweek identity; policy, freeze, profile and protocol upgrades cannot mint a replacement slot.
- `Store.transaction()` explicitly enters `BEGIN IMMEDIATE`, yields bounded transaction access and calls Python `Connection.commit()` before it returns. Exceptions roll back and close the transaction wrapper (`src/matchvet/store.py:4353`). The configured operating profile is WAL with `synchronous=FULL` (`src/matchvet/store.py:3253`, `:3336`). External durability semantics and assumptions belong in the accompanying primary-source research.

## How it works

### Existing publication and its deadline gap

`F16MatchweekProcessor.process_phase()` validates exact membership/cutoff/profile inputs, builds F11/F13/F14 state by phase and eventually returns the F16 manifest digest (`src/matchvet/f16.py:107`, `:132`, `:145`). This exact candidate must be complete before the new selection operation starts. The selection owner must add the common-T and complete-slate policy checks; current generic artifact verification does not establish them.

`ArtifactStore.publish_manifest()` accepts only an UNVERIFIED input, validates its artifact references and stored versions, then looks up the requested snapshot ID (`src/matchvet/artifacts.py:588`, `:597`, `:603`, `:618`, `:626`). If the slot already contains equivalent publication content, it returns the existing record without a commit (`src/matchvet/artifacts.py:629`). The comparison intentionally removes both `verification_state` and `verified_at_utc` (`src/matchvet/artifacts.py:1259`). A future owner must never treat this branch as a fresh commit or issue a completion capability from it.

For a new manifest, publication samples or accepts `verified_at_utc`, serializes VERIFIED bytes, and publishes the object (`src/matchvet/artifacts.py:637`, `:644`, `:654`). `_publish_object()` writes a private staging file, fsyncs it, verifies its hash, installs it with no replacement, and fsyncs the destination directory before indexing (`src/matchvet/artifacts.py:860`, `:874`, `:901`, `:904`). New directory entries are themselves synchronized while creating the directory tree (`src/matchvet/artifacts.py:1125`, `:1148`). Atomic installation uses `renameat2(RENAME_NOREPLACE)` or a hard-link fallback (`src/matchvet/artifacts.py:1179`).

Only then does one SQLite transaction publish canonical IDs, object metadata, the unique snapshot assignment, artifact memberships and version memberships (`src/matchvet/artifacts.py:656`). `Store.transaction()` commits at `src/matchvet/store.py:4361`; `publish_manifest()` returns its record after leaving that transaction (`src/matchvet/artifacts.py:717`). A clock observation after a proven new-slot return therefore follows the object publication and successful selection commit.

```mermaid
sequenceDiagram
    participant O as Proposed selection owner
    participant A as ArtifactStore
    participant F as Object files
    participant S as Store / SQLite
    O->>A: Publish exact selection into unused stable slot
    A->>F: Write, fsync file, install, fsync directory
    A->>S: Atomic catalog assignment and memberships
    S-->>A: Commit returns successfully
    A-->>O: New publication returns
    O->>O: Sample trusted repository clock; require observation < T
    O->>O: Consume private capability for one receipt attempt
    O->>A: Publish protected receipt binding earlier observation
    A-->>O: Receipt publication completes, possibly after T
```

The original isolated proof correctly demonstrates that the current prepublication timestamp cannot distinguish timely, equal-T, late or crash-after-commit histories. It supplies the same recovered manifest bytes for each (`.audit/issue-75-storage-proof/blocker.md`, `.audit/issue-75-storage-proof/storage-proof-final.txt`, `.audit/issue-75-storage-proof/test_storage_deadline.py`). Its conclusion is limited to the existing contract; it does not rule out a receipt attesting an earlier commit.

### Recovery and ownership

`open_store()` acquires a nonblocking exclusive writer flock before opening SQLite, uses an explicit-transaction connection, checks application identity/profile/integrity/schema and verifies every catalogued object before admitting writes (`src/matchvet/store.py:3242`, `:4896`, `:4910`, `:4937`). Missing or corrupt catalogued bytes produce recovery mode; the recovery connection is read-only and query-only (`src/matchvet/store.py:4062`, `:4244`, `:4955`).

Every Store and transaction wrapper records its creator PID and rejects use after crossing a process boundary. Store close invalidates access and releases ownership (`src/matchvet/store.py:4330`, `:4333`, `:4341`, `:4570`, `:4596`). There is no explicit Store thread mutex. The sqlite connection retains the default thread ownership check because `open_store()` does not override `check_same_thread` (`src/matchvet/store.py:4910`). A future capability must bind the exact live Store instance and operation, not PID or boot identity alone. Closing/reopening the store in the same process must invalidate it. Reentrant callbacks must not allow a second owner operation to manufacture a capability.

Inspection reports object files absent from the catalog as orphans and incomplete staging files separately (`src/matchvet/artifacts.py:503`). Neither is imported by `open_store()`. Staging cleanup only deletes incomplete staging files (`src/matchvet/artifacts.py:521`). A selection object without a committed snapshot index row is not a selected state. A receipt object without its committed receipt index row is not completion evidence. Recovery must not search orphan bytes for an old observation and turn them into a missing receipt.

### Receipt representation and required API change

The smallest compatible representation is a second protected generic `SnapshotManifest`. Give it a deterministic receipt slot under the same stable logical Matchweek, set `parent_snapshot_id` to the selection's slot, and include the exact selected manifest artifact as its required artifact reference. Bind the same Matchweek, cutoff ID/T and policy/protocol version identities. Use a versioned domain interpretation of receipt `created_at_utc` as the repository's post-selection acknowledgement time; keep generic `verified_at_utc` as ordinary receipt-publication verification metadata. That separates the semantic event from later publication and preserves historical timestamp meaning. No new SQLite columns or generic payload fields are needed.

An alternative encoding could use `verified_at_utc` for the acknowledgement via the existing publication override, but that changes its domain meaning and interacts with the existing idempotency comparison. The `created_at_utc` interpretation is clearer if the receipt is constructed at acknowledgement. Both require a new explicit protocol contract; neither timestamp proves its own provenance.

The domain owner must hide admission, fresh assignment, clock observation, one-use receipt creation and replay behind `seal_completed()` / `replay_for_matchweek()`. `ArtifactStore` needs a narrow authorized publication path for reserved selection and receipt manifests. Ordinary callers must be unable to publish into those slots with caller-provided timestamps. A deterministic slot guard must be checkable from stable logical identity and protocol role, including attempts to omit or forge a version tag; merely recognizing an optional caller-supplied tag is insufficient. Exact typed IDs and their derived mappings must be verified on replay.

The capability can remain lexical state of the same uninterrupted operation. Consume it before attempting receipt persistence and invalidate it in every exit path. Do not expose construction, serialization, reconstruction, token import or receipt-backfill APIs. If receipt persistence raises, inspect only for an already committed valid receipt through read-only replay; never start another publication from recovered disk state. A successful commit that outlives its call's crash can be accepted only if the indexed receipt already exists and validates.

The database constraints protect uniqueness and references against normal application writes. They are not an authorization boundary against arbitrary code using `StoreTransaction.execute()` or a user who can replace database files (`src/matchvet/store.py:4608`). The protocol trusts repository code and storage ownership. Any claim of protection against a malicious local writer would need a different trust boundary.

## Where things live

| Owner | Responsibility |
| --- | --- |
| `src/matchvet/f16.py` | Existing candidate production and complete F16 lineage replay. |
| Proposed `src/matchvet/matchweek_research.py` | Logical-Matchweek slot, admission, deadline acknowledgement, receipt authority and complete domain replay. |
| `src/matchvet/artifacts.py` | Generic manifest encoding, verified object publication, immutable manifest publication and index/object consistency. |
| `src/matchvet/store.py` | WAL/FULL connection profile, writer ownership, bounded atomic transactions, immutable index schema and recovery. |
| `docs/design/matchweek-wide-evidence-cutoff.md` and `docs/adr/0001-matchweek-wide-evidence-cutoff.md` | Accepted single-selection architecture; need the explicit completion/receipt distinction. |

## Gotchas and implementation constraints

1. `parent_snapshot_id` is only a foreign key to a typed canonical identifier. Publication can add that ID even when no parent manifest row exists (`src/matchvet/artifacts.py:657`, `src/matchvet/store.py:483`). Domain replay must resolve the stable selection slot and exact selected manifest, check the receipt's artifact reference matches it, and recursively validate F16 lineage. Generic `verify_manifest()` checks its own bytes/index/membership consistency but does not perform this domain graph validation (`src/matchvet/artifacts.py:755`).
2. A restored existing selection with no valid receipt is permanently unqualified. Its immutable slot already supplies the refusal marker; another refusal row need not race a crash. The owner cannot issue a fresh capability even before T from that existing assignment. An alternate freeze/policy/profile cannot change the logical slot.
3. The normal fresh-object path syncs bytes and directories. However, when `_publish_object()` finds an already existing target file, it verifies bytes and skips destination-directory fsync (`src/matchvet/artifacts.py:889`, `:898`, `:904`). A prior interrupted publication may have left that target as an unsynchronized orphan. A production proof must reject orphan promotion for protocol objects or explicitly synchronize the reused object and its parent before considering it durably published. Candidate dependencies also need the declared durable-storage premise; merely seeing bytes after a process crash is not a power-loss proof.
4. A complete receipt is authoritative only under the new domain contract and trusted write path. Copying legacy VERIFIED/COMPLETE bytes, using generic caller timestamp overrides, or minting a fresh namespace after an upgrade cannot qualify a Matchweek.
5. A process pause after the trusted sample and before receipt publication may cross T without changing the selected state. A pause before the sample must be judged by the later sample. Cutoff equality fails. Unbounded clock rollback destroys the ordering proof; wall-clock and persistence assumptions must be explicit.
6. The current schema is sufficient to represent both manifests. The current repository APIs alone are insufficient to enforce fresh-commit capability provenance, reserved slots, operation lifetime or the complete common-T graph. These are implementation requirements for #75 after the design/proof gate, not production changes in this task.

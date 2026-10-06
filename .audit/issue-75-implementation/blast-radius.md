# Issue #75 blast radius

Baseline: `5c70bb2`. The safety boundary is the fresh protected index insertion
followed by a trusted observation and one live receipt attempt. Existing rows can
only replay. Public publication never receives that authority.

## Executable checks

| Required fact | Evidence | Result |
| --- | --- | --- |
| Historical manifest identity and readers are unchanged | `legacy-identity-proof.py`, `legacy-identity-proof.json`; `storage-regressions.txt`; `f16-regressions.txt` | Real baseline/current codec round-trips preserve both manifest digests. All 14 migration checksums match. 48 ArtifactStore/Store and two F16 regressions pass. |
| Recovery cannot backfill a receipt | `guards-crashes-04.txt`, `integrity-06.txt`, `lifetime-durability-07.txt` | Real process exits, reopen, orphan objects, consumed/copied/forked capabilities and corrupted/deleted evidence refuse qualification or replay only an already indexed valid receipt. |
| No second winner can appear | `proposals-05.txt` | Alternate freeze, policy and profile proposals occupy the same logical slot. Competing real processes leave one winner. |
| A new proposal cannot qualify at or after T | `protocol-03.txt`, `green-02.txt` | Equality and late gates refuse; object sync crossing T cannot start selection insertion. A commit returning after T leaves an occupied, permanently unqualified slot. |
| Clock uncertainty fails closed | `protocol-03.txt` | Default unavailable confidence, malformed confidence, rollback and confidence lost after commit refuse qualification. |
| A generic caller cannot occupy a qualifying reserved mapping | `guards-crashes-04.txt`, `integrity-06.txt` | Both publication APIs reject reserved mappings before idempotent paths, including altered or omitted role tags. Wrong logical mappings do not pass domain replay. |

These checks reach blast-radius step 4: real production code exercised in isolated
temporary stores. They do not establish a live clock bound or hardware durability.

## Downstream seams inspected

- `ArtifactStore.publish_manifest` keeps its historical public signature and ordinary
  behavior; only the new deterministic mappings are reserved. SnapshotManifest
  serialization and readers remain unchanged.
- `StoreTransaction.record_snapshot_manifest` keeps its public signature and original
  SQL insertion. Protected insertion requires an exact original Store operation.
  Existing schema uniqueness and the Store writer lock remain the assignment boundary.
- Existing F16 replay validates the full graph; scoped verification capture adds exact
  object references without changing F06/F07/F11/F13/F14/F16 payload identities.
- `require_preselection_open` is a read-only seam for #76. No downstream writer invokes
  it as part of this issue, and no downstream writer enforcement was added.

## Operational limits

Production has no established trusted UTC error bound. The default provider refuses.
WAL/FULL, successful object and directory fsync, honest VFS/device/locking behavior,
and one authoritative catalog history are required. Obsolete backup or writable clone
promotion is outside that contract. Raw SQL, private reflection and privileged file
changes remain trusted escape hatches.

Unqualified occupied slots sacrifice availability permanently after interruption.
This is the accepted protocol, demonstrated by the crash tests. Qualification is never
recovered from an ordinary timestamp, a log, or an orphan object.

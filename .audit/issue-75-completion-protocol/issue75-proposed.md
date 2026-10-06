## Parent

Part of #73: Correct F07 and downstream evidence freeze to one Matchweek-wide cutoff.

## What to build

The exact complete F16 recommendation manifest is selected once for its logical Matchweek, with a durable, verifiable record that selection completed before common cutoff T. Restart or concurrent writers resolve the same selection; a different freeze, policy, profile, model input, or manifest cannot replace it. At or after T, callers can replay only this selected state.

## Scope

- New deep Matchweek research-selection repository/owner.
- Existing protected `SnapshotManifest`, `ArtifactStore`, and `Store` publication/recovery seams; no new SQLite schema unless an isolated proof demonstrates that current storage cannot satisfy atomic single assignment and deadline evidence.
- F16 manifest and its transitive F06/F07/F11/F13/F14 lineage validation.

## Acceptance criteria

- [ ] Seal only a complete F16 manifest with every INCLUDED membership, exact common F07 T/policy, a single selected F11 evidence set, and replayable full lineage.
- [ ] Select once by a stable deterministic logical-Matchweek identity. The uniqueness key does not vary by freeze, cutoff policy, profile, engine/reader version, or proposal digest.
- [ ] Provide exact replay by selection digest and lookup by logical Matchweek; both reject orphan objects, valid but nonselected manifests, and mismatched lineage. Restart never chooses “latest”.
- [ ] Give prospective writers a shared preselection gate: corrected candidate work may proceed only while T is open and no selection exists; once selection exists or T is reached, new collection/selection/decision writes refuse, while exact selected replay remains available.
- [ ] Prove atomic single assignment under concurrent competing proposals and restart. If an incomplete, different, or already selected proposal exists, fail closed and keep it from qualifying as a recommendation.
- [ ] Establish that the exact selected manifest and full graph were durably assigned by a fresh atomic selection commit, followed by a repository-owned UTC completion upper-bound observation strictly before T. Reject equality, late commit/observation, idempotent-return acknowledgement, or an uncertain commit. Caller timestamps, F06 creation time, and ordinary prepublication verification metadata are not proof.
- [ ] Only the same live operation may consume private one-use authority to publish an indexed protected completion receipt binding logical Matchweek, exact selection/F16, common T/policy and supported protocol. Receipt persistence itself may finish after T; it attests the earlier commit and never selects or changes state.
- [ ] Authority never escapes to callers, is never persisted/reconstructed, and binds the original Store/process/operation lifetime. Consume before the first receipt attempt; invalidate on exit, close/reopen and fork. A selected slot without a valid indexed receipt after interruption is permanently unqualified, even before T. Never backfill from selection/catalog rows, logs, timestamps or orphan objects; an already valid receipt may replay after its own commit-return crash.
- [ ] Prevent reentrant publication from borrowing ambient authority. An ambiguous receipt-commit exception permits read-only validation of already indexed evidence, never a second publication attempt. An uncertain selection-commit return cannot issue authority even when recovery finds its row.
- [ ] Preserve two stable role slots in existing SnapshotManifest/index storage with no schema or generic payload-field migration. Receipt parent and artifact reference identify the real exact selection; supported domain creation time carries the postcommit bound, while generic verification time keeps its historical meaning. Guard qualifying reserved mappings at ArtifactStore publication and structured StoreTransaction insertion, including omitted protocol tags, before idempotent paths. Invalid logical mappings fail domain replay; raw SQL/private code remain explicitly trusted.
- [ ] State trusted UTC upper-bound and SQLite WAL/FULL/VFS/fsync/locking assumptions, including one authoritative catalog history without obsolete-backup/clone promotion. Refuse unestablished clock confidence and sync errors; include existing object/directory paths in graph durability. Cover rollback/forward clocks, pauses, copied/duplicate capabilities, same/new-process reopen, corrupted/deleted receipt/graph, alternate policies/freezes/profiles and valid generic but wrong-domain receipts.
- [ ] Implement the accepted postcommit acknowledgement protocol in `docs/design/matchweek-selection-completion-protocol.md` using the existing generic manifest schema. The design and isolated synthetic protocol proof do not complete production #75 acceptance. If implementation disproves schema sufficiency, stop before adding a migration or expanded payload.
- [ ] Focused isolated tests exercise full dependency verification, duplicate proposals, concurrent publication, cutoff equality/crossing, partial publication, reopen/recovery, canonical lookup, orphan rejection, pre-T assignment with post-T receipt persistence, and post-T exact replay. Historical SnapshotManifest canonical bytes and readers keep working.
- [ ] Run focused tests, Ruff for changed Python, and `git diff --check`.

## Blocked by

- #74 — F07 must derive and replay the exact whole-freeze boundary first.

Use only isolated temporary stores and deterministic test inputs. Do not open or modify either live SQLite store, acquire fixtures or network data, publish live F artifacts, or send a Sigstore/RFC3161 request. Do not rewrite historical manifests, migrations, issues, or `.audit` evidence. Do not build downstream F11–F16 writer gates here.

## Completion protocol clarification, 2026-10-06

The selection deadline is unchanged: the exact logical-Matchweek assignment and complete F16 graph must be durable before T, with a trusted postcommit acknowledgement strictly before T. A later receipt only records that earlier fact. No previously unselected candidate may become selected after T.

Accepted design: `docs/design/matchweek-selection-completion-protocol.md`; ADR 0001 and the current cutoff design now distinguish selection from receipt publication. New isolated protocol proof: `.audit/issue-75-completion-protocol/`. Original failed storage proofs: `.audit/issue-75-storage-proof/`, preserved unchanged. Existing schema is sufficient; protected publication hooks still need implementation.

This task delivers design/research/proof records only. All production acceptance checkboxes remain open. #75 stays open and #76 remains blocked. No production code, live-store work, fixture acquisition, or TSA request was performed.

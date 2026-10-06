# Matchweek research repository

`MatchweekResearchRepository` owns the immutable selection of one complete F16
manifest for a logical Matchweek. The accepted protocol is
[Matchweek selection completion](design/matchweek-selection-completion-protocol.md).
It adds no SQLite migration and changes no historical SnapshotManifest payload or
F06/F07/F11/F13/F14/F16 identity.

## Methods

| Method | Result |
| --- | --- |
| `seal_completed(f16_manifest_digest)` | Admit the complete exact graph, assign a fresh selection slot, acknowledge its commit, publish one completion receipt, and return `FrozenMatchweekResearch`. An existing identical qualified selection replays. A different proposal refuses. |
| `replay(selection_digest)` | Verify the indexed selection, indexed receipt, supported role contracts and exact dependency graph. It neither writes nor samples the qualification clock. |
| `replay_for_matchweek(season=..., matchweek_friday=...)` | Resolve the deterministic logical slot and replay its exact selection. |
| `require_preselection_open(freeze_id, policy_digest)` | Verify the corrected whole-freeze F07 boundary, refuse an occupied logical slot, and require a trusted upper bound strictly before T. It performs no publication. #76 will integrate this gate into downstream writers. |

`FrozenMatchweekResearch` identifies the selection digest, logical season and Friday,
F06 freeze, F07 policy and T, F16 manifest, and completion receipt. It contains no
publication authority. Refusal raises `MatchweekResearchError`.

Admission reuses existing exact F16 replay and requires every INCLUDED membership
once, the corrected F07 rule, one common T and policy, and one F11 evidence set.
During replay, the repository captures every object verified by the existing lineage
readers. The selection indexes that exact object closure. Structured F06, fixture,
coverage and provider-health references retain their existing catalog representation
and validation. Replay rejects missing, additional, corrupt or mismatched dependencies.

## Role mappings and authority

Logical Matchweek identity is UUIDv5 over
`matchvet:logical-matchweek:{season}:{friday}`. The selection and completion UUIDv5
slots use `matchvet:matchweek-research-selection:{logical_uuid}` and
`matchvet:matchweek-research-completion:{logical_uuid}`. These slots do not include
freeze, policy, profile, proposal, request, engine, reader or protocol version.

Generic ArtifactStore publication and structured StoreTransaction insertion refuse
both qualifying reserved mappings before their idempotent paths. Private publication
binds the exact original Store, process, thread, live operation and manifest digest.
The Store permits one active operation. Copy and serialization refuse. Closing the
Store, leaving the operation, reopening or forking makes the authority unusable.

A successful fresh selection transaction return is followed by a trusted UTC
upper-bound observation. Only `u < T` acknowledges the selection. Receipt authority
is consumed before verification, staging or the first publication attempt. Receipt
persistence may finish after T. Its `created_at_utc` binds the earlier acknowledgement;
its ordinary `verified_at_utc` remains publication verification metadata.

A selection commit exception creates no receipt authority, even if the indexed row
survives. A receipt publication exception permits one read-only reconciliation of an
already indexed valid receipt. There is no publication retry from recovered state.
An occupied selection without a valid indexed receipt is permanently unqualified.
Receipt and selection orphan objects cannot supply that evidence.

## Clock contract

The constructor accepts a repository-configured `TrustedUTCClock`. `observe()` must
return `TrustedUTCUpperBound` with an aware UTC datetime, a nonempty source identity
and `confidence="TRUSTED"`. The provider contract requires the bound to be at least
actual UTC when `observe()` returns, including measurement error, rollback and any
suspension. The repository rejects decreasing observed bounds during its lifetime.
A provider's source string or a synchronized label alone establishes no accuracy.

The default provider refuses because this repository has no established production
UTC error bound. Ordinary system UTC is never promoted to trusted completion evidence.
Deterministic tests supply synthetic trusted providers. Those tests prove branch and
ordering correctness; they do not establish a live host's UTC confidence.

A gate observation occurs before publication and again after object synchronization,
immediately before the selection transaction. These observations grant no authority.
The qualifying observation follows a fresh successful selection commit return. Equality,
late return, lost confidence, a backward bound or a pause across T refuses acknowledgement.
The resulting occupied slot remains terminal if its transaction committed.

## Durability and limits

The private operation requires WAL mode and `synchronous=FULL`, a fresh transaction
boundary, and the Store's existing exclusive writer lock. Before selection commit,
the publisher synchronizes the selection object, every verified graph object, and
all containing directories through the Store directory. It synchronizes reused files
and existing directory paths. Sync failure propagates before acknowledgement.
The receipt receives the same object and directory barriers before its own commit.

These guarantees assume honest SQLite VFS synchronization, filesystem, device and
locking behavior, and one authoritative catalog history. An obsolete backup, writable
clone or VM rollback cannot replace that history as a new authority. Raw SQL, reflective
private Python and privileged filesystem manipulation remain trusted escape hatches.
The application guard is not cryptographic proof against such operators.

Prospective production qualification remains unavailable until an operational trusted
UTC provider establishes this contract. No live clock proof, live-store operation,
fixture acquisition, timestamp request or downstream #76 writer enforcement is part
of #75's implementation.

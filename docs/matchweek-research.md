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
| `require_preselection_open(freeze_id, policy_digest)` | Verify the corrected whole-freeze F07 boundary and first candidate identity, refuse an occupied logical slot, and return a trusted UTC upper-bound timestamp strictly before T. It performs no publication. |
| `require_candidate_write(freeze_id, policy_digest)` | Call the preselection gate for corrected writers. Explicit legacy research remains separate and cannot write into an occupied logical Matchweek. |
| `selected_for_boundary(freeze_id, policy_digest)` | Replay the indexed logical winner and require its exact freeze and policy. An unreceipted or corrupt occupied slot refuses. With no selection, return `None`. |
| `require_candidate_contract(freeze_id, policy_digest, profile_digest, decision_policy_digest)` | Check the shared prospective gate and pin the profile and decision policy from the first F15 run or F14 input across the whole slate. |
| `candidate_artifacts(freeze_id, policy_digest, check_state=..., contract=...)` | Create an ArtifactStore whose corrected publications recheck time, logical selection and candidate identities before object publication, before catalog commit and after commit return. Module checks also pin exact request, model, attempt or decision state. |

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
UTC provider establishes this contract. Deterministic tests establish code behavior;
they do not establish live UTC confidence.

## F11 through F16 writers

F11, F12, F13, F14, F15 and F16 accept an optional `TrustedUTCClock` at their
Matchweek writer constructors. Orchestration passes that configured provider to
each repository. An absent provider continues to refuse corrected prospective work.
Every direct writer calls the shared owner before acquisition, mutable input
discovery or recommendation writes. Publication checks include the catalog
transaction and its successful return. A sync or commit that crosses T refuses
the operation. Physical orphan bytes or an ambiguously late catalog entry cannot
qualify: prospective retries remain closed and #75 cannot seal them after T.

The first corrected F11 request fixes the logical Matchweek's exact F06 freeze,
F07 policy, common T, workload rules, context and weather locations. Its eligible
history retains only pre-T provenance. Weather needs a known issue time no later
than retrieval, with retrieval no later than T. Acquisition checks the gate before
fetch and again on return or failure. F12 pins the first exact attempt for each
cutoff. Changed requests and later failure metadata cannot replace retained refs.

F13 checks the gate before consuming history or enumerating retained sources.
The first result pins history, calibration cases, baselines, candidate inputs,
availability and the existing research/model identities. F14 pins the exact first
decision bundle and one profile and decision policy across all INCLUDED members,
including partially retained decision inputs. Their replay methods verify retained
bytes through the historical engines; they do not publish refreshed state.

F15 start and resume require the corrected rule and exact candidate contract before
calling the run coordinator. Partial F15 runs pin their boundary, profile and
decision policy before evidence acquisition.
F16 checks each phase directly, including missing phases of interrupted runs.
With a qualified selection, writer-or-replay methods resolve only its F11, F13,
F14 and F16 references. F15 selected resume becomes read-only inspection. Changed
freeze, policy or profile identities refuse even if their timestamps agree.

`legacy_research=True` on F15 or F16 explicitly allows the existing separate
per-match research path. It cannot qualify a Matchweek selection, and it cannot
disable corrected-policy gates. Legacy exact replay and inspection require no
such option. Existing policy, artifact schemas, media types and engine identities
remain unchanged.

Standalone upstream history retention and provider health observations are audit
inputs without selection authority. They may remain available independently.
Selected model and evidence readers resolve frozen references, so later catalog
sources or observations cannot enter the recommendation lineage. F12 exact lookup
uses the selected artifact reference set, including for direct F11/F13/F14 replay.
The transient catalog view refuses writes and restores on exit. Initial #75 sealing
keeps its existing reference closure; selected replay neither discovers later audit
attempts nor promotes incidental audit references to F11 attempts. Stored payloads
remain unchanged. Ordinary retained artifact readers remain available for historical integrity
inspection.

## CB01 and F19 consumers

Corrected CB01 source preparation resolves the exact indexed selection for the
supplied F06 and F07 policy, replays its complete graph and requires the selected
F16 manifest and common T. The manifest supplies the exact Profile and per-member
F11, F13 and F14 identities. The adapter adds no CB01 payload fields and changes
neither historical core software digest. Legacy preparation reconstructs its
original per-match commitments.

`MatchweekEvaluationRepository.inspect_cohort` counts the exact F06 memberships
and enabled Profile preferences before joining explicitly named publications.
Its corrected cohort carries the exact selection, completion receipt, policy and
common forecast origin under
[chronology 0.2.0](product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md). Missing F16 or
selection, failed witnesses and unattempted rows stay unavailable. Legacy policy
and mixed exact identities refuse corrected evaluation. F06 exclusions stay visible
with their original reasons outside the INCLUDED count.

`inspect_denominator(freeze_digest, profile_digest)` is independent of research and
witness artifacts. An admission refusal also carries this full view on
`CB01EvaluationError.denominator`. Exact receipt replay verifies would-be CB01
publications against already-retained bytes without writing or repairing them.
Successful retries retain failed-attempt history. Failures without a provable
selected policy/F16 identity remain in `unavailable_failure_digests` outside the
cohort's attempted rows. Unreadable failures with no provable freeze/Profile anchor
are separate store-wide `catalog_unavailable_failure_digests`; they do not change
cohort row status or count.

F19 checks the selected corrected manifest before settlement, correction or cached
lineage reuse. Its schema, T10 grading and append-only predecessors remain unchanged.
Outcome facts and later witnesses cannot reopen the frozen recommendation graph.

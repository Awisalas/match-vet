# Postcommit acknowledgement design draft

Intent: prove that the exact immutable logical-Matchweek assignment and its complete
dependency graph were durable before common T. A receipt may persist later and
attest to that earlier event. It cannot select, replace, recompute, or repair state.

This is a design sketch for review, not production implementation or completed #75.

## Event and proof

The qualifying event is successful completion of a fresh atomic selection transaction
under WAL/FULL, after its protected object bytes and exact graph have been synchronized.
The transaction inserts the one stable logical-Matchweek slot and exact manifest
memberships. An idempotent return or recovered row is not this event.

The repository observes a trusted UTC completion upper bound u only after that event.
If u >= T, no capability exists. If u < T, one private authority exists on that live
operation's stack. The protected receipt binds u, the exact selection digest, common
T/policy, logical identity and supported protocol. Only its indexed canonical instance
counts as evidence. Receipt verification time is ordinary publication metadata and may
be at/after T.

Under honest persistence and a clock whose bound never understates actual UTC:

`selection durability event <= successful commit return <= actual observation <= u < T`.

Receipt durability is intentionally absent from this inequality. Its later publication
preserves a fact already established by the operation; it does not cause an assignment.

## Private authority

Only a fresh successful assignment creates authority. The same synchronous operation
must own the original Store instance, PID, thread/operation identity and writer lock.
Authority is consumed before one receipt-publication attempt and revoked on every exit.
It is not returned to callers, serialized, logged, pickled, queued, copied, imported,
or retained in background tasks. Fork, close/reopen and resumed operations cannot use it.
If receipt publication fails ambiguously, only read existing evidence; never retry
publication from disk state or a consumed capability.

Existing selection plus valid receipt permits exact replay. Existing selection without
receipt permanently refuses the Matchweek even before T, regardless of candidate/policy.
No additional refusal row is required because the immutable occupied slot is terminal.
Before a selection transaction commits, an orphan object is not an assignment; a fresh
complete operation may still succeed before T, but orphan receipt adoption is forbidden.

## Compatible representation

Use two generic SnapshotManifest records in stable distinct role namespaces. Neither
identity changes with freeze, policy, profile, reader version or receipt contents.
Selection retains the F16 artifact and verified full dependency closure. Receipt has:

- the same logical Matchweek and cutoff ID/T;
- parent_snapshot_id naming the selection slot;
- exactly one artifact reference identifying the selected SnapshotManifest bytes;
- an explicit supported completion-protocol ManifestVersion;
- created_at_utc interpreted by that protocol as repository-observed bound u;
- normal generic verification metadata for its own publication.

Domain replay resolves both deterministic index mappings, validates the parent is a
real indexed selection rather than a bare typed ID, matches the exact digest and common
policy/T, and validates the selected complete F16/F06/F07/F11/F13/F14 graph. Legacy
created_at and verified_at fields retain their existing meanings. No columns or generic
JSON fields are added. The exact namespace guarding strategy remains under arena review.

Existing APIs need a narrow protected fresh-assignment/receipt publication path and a
reserved-slot guard. They currently allow caller timestamps, arbitrary identities and
idempotent returns. A protocol tag alone does not prevent a caller omitting that tag.
Raw SQL, reflective Python or filesystem owners remain trusted; this is not a
cryptographic attestation against hostile local operators or restored process memory.

## Time and durability assumptions

The repository clock must supply a genuine upper bound for actual UTC at observation.
An accurate clock or a documented error bound can satisfy this premise. Current OS UTC
and a clock labeled synchronized do not by themselves certify it. Missing confidence
requires refusal. Forward jumps can falsely refuse; unbounded backward jumps can falsely
qualify with a naive clock and are excluded from the trust premise.

A trusted UTC anchor plus a suspend-inclusive elapsed upper bound can conservatively
prevent rollback from reopening T during one operation. CLOCK_BOOTTIME availability
does not certify initial UTC accuracy, elapsed-clock rate, VM rollback or reboot safety.
Neither anchors nor capability state survive restart. The isolated clock proof assumes
perfect synthetic bounds; it does not establish a live machine's uncertainty bound.

WAL/FULL requires an honest SQLite VFS, fsync, filesystem, device and locking behavior.
Do not change to NORMAL or rollback-journal FULL and assume the same power-loss proof.
Sync selected object files and containing directories even when paths already exist;
the existing reuse path skips its destination-directory fsync. Propagate failures before
acknowledgement. Never accept unindexed orphan bytes as completion evidence.

## Failure table

| Gap/attack | Persistent outcome and rule |
| --- | --- |
| Crash before selection commit | No assignment, or an indexed assignment if commit physically completed; inspect index only. No receipt means no qualification. |
| Crash after selection commit before observation | Occupied selection slot permanently unavailable. |
| Crash after observation before receipt | Same permanent refusal; live authority is gone. |
| Pause before observation across T | Refuse, even if commit may actually have been timely. |
| Pause after valid observation across T | Same operation may finish one receipt attempt. |
| Observation exactly T or later | Terminal unqualified assignment; no receipt authority. |
| Crash during receipt staging/object publication | Unindexed bytes are orphan evidence and never adopted. |
| Crash during receipt transaction | Valid indexed receipt after recovery permits replay; otherwise permanent refusal. |
| Crash after receipt commit but before receipt return | Valid receipt permits replay, including when that receipt commit occurred after T. |
| Competing writers | Store writer lock and unique selection slot permit only one assignment. Losers never receive authority. |
| Same process/boot reopen or new process | New Store/operation has no authority; existing assignment alone cannot mint it. |
| Duplicate, copied or forked authority | Consumed/lifetime/PID/Store/operation checks refuse. |
| Receipt deletion/corruption | Refuse; never recreate. |
| Receipt present, selection/reference corrupt | Refuse complete replay; no replacement. |
| Alternate freeze/policy/profile/F16 | Same occupied logical slot; reject proposal, preserve exact winner. |

## Alternatives

| Option | Judgment |
| --- | --- |
| A. Ordinary second durable row | Safe only if issuance has this fresh-operation authority; reconstruction from earlier rows permits backfill. New row schema unnecessary. |
| B. One transaction with precommit timestamp | Counterexample: commit crosses T while stored timestamp stays early. |
| C. Safety margin/timeout | A heuristic unless maximum sync/pause latency is proved. Timeouts cannot retract a committed assignment after crash. |
| D. Filesystem marker/rename | Can encode the same authorized receipt; requires no-replace, fsync and reference validation, adds a separate recovery/index owner. Alone it proves no pre-T time. |
| E. External timestamp before T | Could witness exact binding under separate witness assumptions; offline task forbids requests and local protocol already suffices under stated trust. |
| F. Lexical private authority inside seal_completed | Simplest capability shape; callers never coordinate commit and receipt. Combine with existing indexed SnapshotManifest. |

## Caller sketch

```python
selected = MatchweekResearchRepository(store).seal_completed(f16_digest)
selected = MatchweekResearchRepository(store).replay_for_matchweek(
	season="2026-27", matchweek_friday="2026-09-25"
)
selected = MatchweekResearchRepository(store).replay(selected.digest)
```

Public methods expose selected state and refusal, not completion tokens or repair steps.
The owner retains the previously sketched API, plus the #75 shared preselection gate.
No #76 callers are modified by this design task.

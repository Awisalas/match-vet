# Matchweek selection completion protocol

Intent: prove that the exact immutable logical-Matchweek assignment and its complete
dependency graph were durable before common T. A receipt may persist later and
attest to that earlier event. It cannot select, replace, recompute, or repair state.

Accepted design clarification for #75, 2026-10-06. Production implementation is still pending. The original storage counterexamples remain preserved under `.audit/issue-75-storage-proof/`.

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
The Store permits only one active selection operation; callbacks and nested operations
cannot borrow its authority. Public publishers always apply the reserved-slot guard.
The private publisher checks the exact operation, role and internally constructed manifest;
an ambient authorization boolean is insufficient.
Authority is consumed before one receipt-publication attempt and revoked on every exit.
It is not returned to callers, serialized, logged, pickled, queued, copied, imported,
or retained in background tasks. Fork, close/reopen and resumed operations cannot use it.
If receipt publication fails ambiguously, only read existing evidence; never retry
publication from disk state or a consumed capability.
An exception after a possible receipt commit may resolve to success through read-only
validation of the already indexed receipt. An exception from the selection commit never
creates authority, even when recovery finds the selection row. Neither path retries a
publication using recovered state.

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
JSON fields are added. The role namespaces and protected publication predicate are specified below.

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
Without any trusted absolute-time bound, a timely execution and a late execution with
the clock rolled back can have identical repository observations. No local receipt
format can distinguish them. Refusal or an additional trusted time source is then required.

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

Single assignment assumes one authoritative protected catalog history. An obsolete
backup, cloned writable Store or VM rollback cannot replace that history and be treated
as a fresh authoritative store. Recovery must retain terminal slots or refuse uncertain
history. SQLite uniqueness proves assignment within that history, not across discarded
or independently writable copies. Preventing hostile history rollback requires a
separate trust boundary.

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
| E. External timestamp before T | A timestamp on candidate bytes alone proves no selection commit. A witness must attest to the actual committed assignment, with exact binding and a pre-T bound under its own trust assumptions. No requests are needed: the local protocol suffices under stated trust. |
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

## Stable identity and publication guard

Canonical logical identity uses the exact validated F06 season and Friday date:
`uuid5(NAMESPACE_URL, "matchvet:logical-matchweek:{season}:{friday}")`.
The selection slot is `uuid5(NAMESPACE_URL,
"matchvet:matchweek-research-selection:{logical_matchweek_uuid}")`.
The receipt slot is `uuid5(NAMESPACE_URL,
"matchvet:matchweek-research-completion:{logical_matchweek_uuid}")`.
These separators never include a protocol or reader version. A collision or logical
identity mismatch refuses; it cannot alias another slate. This introduces only new
selection identities, with no change to any existing artifact identity algorithm.
The new owner's logical UUID does not replace legacy T05 Matchweek IDs or F06 freeze
digests. Admission validates the selected F06's season/Friday tuple and preserves every
existing lineage identifier and canonical byte sequence.

One dependency-free identity helper must be shared by the protected publisher and
reader. Generic `publish_manifest` must reject either role slot derived from its
incoming `matchweek_id` before its existing-key branch. A supported domain receipt
necessarily has those exact identities, so it cannot bypass the generic guard by
omitting or changing a protocol tag. Generic publication with a forged, different
Matchweek ID can occupy an invalid slot, but strict domain replay rejects that object
and permanently refuses the real logical Matchweek. This accepted availability loss
confers no qualification or replacement authority. A global UUIDv8 allocation can
prevent such poisoning, but is unnecessary for the stated safety and trust model.

The internal protected path derives and validates the logical mapping itself, holds
Store writer ownership, and reports a fresh actual insert/commit outcome. It must not
reuse the generic idempotent return as fresh success. For receipt publication, it
accepts only the private live operation authority and constructs the receipt internally;
there is no public input for a receipt timestamp, caller-built manifest or token.
No additional schema trigger promises authorization against raw SQL or private-code
calls. The application boundary and immutable index jointly enforce the protocol.

The same protected-role predicate and live authorization must cover the structured
`StoreTransaction.record_snapshot_manifest` insertion API, not just ArtifactStore's
wrapper. Otherwise a normal lower-level API could backfill a receipt. Generic insertion
must refuse qualifying selection/receipt mappings; only the internal protected
publication transaction may carry authority for that one attempt. Direct SQL through
`execute`, reflective Python, and privileged database manipulation are explicitly trusted
escape hatches and cannot be claimed secure. The isolated subclass models the future
guard, not production enforcement at either layer.

## Interface and module sketch

These signatures are NOT IMPLEMENTED. They retain the deep owner proposed in the
cutoff design. Receipt and capability types stay private.

```python
@dataclass(frozen=True)
class FrozenMatchweekResearch:
	digest: str  # exact selection SnapshotManifest digest
	season: str
	matchweek_friday: str
	freeze_id: str
	policy_digest: str
	cutoff_at_utc: str
	f16_manifest_digest: str
	completion_receipt_digest: str

class MatchweekResearchRepository:
	def seal_completed(self, f16_manifest_digest: str) -> FrozenMatchweekResearch:
		# Validate graph; reject conflicts; commit fresh slot; observe; consume;
		# publish one receipt; return verified replay. No public phase methods.
		raise NotImplementedError

	def replay(self, selection_digest: str) -> FrozenMatchweekResearch:
		raise NotImplementedError

	def replay_for_matchweek(
		self, *, season: str, matchweek_friday: str
	) -> FrozenMatchweekResearch:
		raise NotImplementedError

	def require_preselection_open(self, freeze_id: str, policy_digest: str) -> None:
		# Shared #75 gate only. #76 will integrate writer call sites separately.
		raise NotImplementedError
```

The proposed `matchweek_research.py` owns logical identity, complete graph admission,
clock acknowledgement, private lifetime and replay. ArtifactStore owns a narrow
reserved publication path and file/directory durability barriers. Store retains its
existing writer lock, process/thread ownership, atomic transaction and immutable index.
Capability invalidation must observe exact Store lifetime and close state; a separate
public capability registry or stage coordinator is unnecessary. Full F16 lineage stays
in existing repositories and is checked before assignment and on replay.

## Decision and isolated evidence

Two independent whole designs were compared: indexed generic receipt and no-replace
filesystem receipt. Use the indexed design with the filesystem candidate's lexical
one-operation authority. This reuses existing integrity inspection, object/catalog
verification and backup semantics. The filesystem alternative adds a new canonical
payload parser, path verifier, orphan rules and backup/recovery owner. Neither format
alone proves the clock ordering.

The executable throwaway proof is
`.audit/issue-75-completion-protocol/prototype_protocol.py`:

```sh
PYTHONPATH=src python .audit/issue-75-completion-protocol/prototype_protocol.py
```

It uses synthetic graphs and real temporary Store/ArtifactStore/SnapshotManifest
publication with deterministic clocks and process exits at commit boundaries. It models
the future guarded publisher; it does not implement the production namespace helper,
F16 admission or a real trusted-clock provider. The HTML prototype exposes the state
transitions for manual walkthroughs and makes no persistence claim.

The evidence establishes protocol ordering and process-crash recovery under the stated
assumptions. It does not experimentally establish hardware power-loss durability or
absolute UTC accuracy. SQLite's documented WAL/FULL contract supplies the former
conditional premise. See the cited primary-source [research note](../research/matchweek-selection-completion-protocol-2026-10-06.md)
and the [new proof records](../../.audit/issue-75-completion-protocol/).

The original failed proof still correctly demonstrates the old API's ambiguity. Its
stronger final-evidence-write deadline is not needed for the clarified semantic event.
No new selection occurs after T: later receipt availability concerns only an assignment
already committed and acknowledged before T. Report receipt publication chronology
honestly; this is not independent timestamp or contemporaneous publication evidence.

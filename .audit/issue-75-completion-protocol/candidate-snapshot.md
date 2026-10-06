# Candidate: two protected snapshots, one live completion operation

Design sketch only. No production implementation, store access, schema migration, or manifest JSON change accompanies this candidate. Grounding comes from `grounding.md`, the current `artifacts.py` publication path, `store.py` canonical identifier validation, and `docs/research/matchweek-selection-completion-protocol-2026-10-06.md`.

## Usage first

A caller submits the already produced F16 candidate and receives either the completed selection or a refusal. The owner derives the logical Matchweek, common T, freeze, policy and profile from validated inputs. Callers never construct receipt manifests or supply timestamps.

```python
# Proposed API; NOT IMPLEMENTED.
owner = MatchweekResearch(artifact_store)
result = owner.seal_completed(candidate_f16_digest)
if isinstance(result, CompletedSelection):
    render_research(result.selection)
else:
    render_refusal(result.reason)
```

A later reader requests the sole selection by stable logical Matchweek identity. Replay does not require the original process or trust its current wall clock.

```python
# Proposed API; NOT IMPLEMENTED.
result = MatchweekResearch(reopened_artifact_store).replay_for_matchweek(matchweek)
if isinstance(result, CompletedSelection):
    export_existing_result(result.selection)
else:
    show_unavailable(result.reason)
```

An automated retry uses the same entry point. If a valid receipt exists, it gets the existing result. If the selection is already assigned without a valid receipt, it gets permanent refusal. A different candidate never replaces the assignment.

```python
# Proposed API; NOT IMPLEMENTED.
result = owner.seal_completed(alternate_f16_digest)
# Exact existing successful replay, conflict, or permanent refusal.
# No public resume, acknowledge, issue-token, or backfill method.
```

## Problem

The existing generic manifest's verification timestamp precedes object publication and SQLite commit. It cannot establish that the selection finished before T. The missing fact is an observation made after the successful fresh selection commit. A later durable receipt can preserve that fact, provided only the live operation that made the observation can write the receipt. Receipt durability after T is valid; selection durability after T is not.

## Shape

Keep two ordinary `SnapshotManifest` values in immutable snapshot slots. The first assigns the selected F16 graph; the second records completion. Give the completion protocol one owner and two public operations, per boundary-discipline and interface depth. Callers see domain results, not manifest assembly, storage stages, clock policy, or capabilities.

| Existing field | Selection interpretation | Receipt interpretation |
| --- | --- | --- |
| `snapshot_id` | Stable selection slot derived only from logical Matchweek | Stable receipt slot derived only from logical Matchweek |
| `matchweek_id` | Exact canonical logical Matchweek | Same exact identity |
| `research_cutoff_id`, `research_cutoff_utc` | Validated common cutoff and T | Exact same cutoff and T |
| `artifacts` | Exact F16 and required selection bindings | Required exact selected manifest digest, artifact ID and metadata |
| `parent_snapshot_id` | As specified for selection | Exact selection slot |
| `versions`, `version_manifest_id` | Freeze/policy/profile/protocol contracts | Same required policy/protocol contracts; exact selection binds remaining lineage |
| `created_at_utc` | Ordinary selection creation time | Protocol-defined conservative UTC upper bound sampled after selection commit returns |
| `verified_at_utc` | Ordinary generic verification metadata | Ordinary generic receipt-publication verification metadata |
| `completeness` | COMPLETE only after full domain admission | COMPLETE only for authorized receipt with no omitted required graph |

The receipt's `created_at_utc` is explicitly a domain contract extension. It preserves the generic creation interpretation because the receipt is created when the acknowledgement is made, although a conservative clock bound may lie slightly ahead of the raw wall-clock reading. Legacy manifest bytes retain their current meaning. Protocol version references identify this interpretation; replay accepts only supported exact contracts. The version does not participate in slot identity, so upgrades cannot mint a second selection or receipt.

### Recognizable protected slots

`CanonicalIdentifier` requires a UUID string, so a textual prefix is unavailable. Reserve all snapshot UUIDv8 values for this protocol, identifiable from UUID version bits alone. Derive each protocol slot from SHA-256 of canonical logical identity and a fixed selection/receipt role, retaining 122 hash bits after setting version/variant bits. Specify the exact domain separator, canonical identity bytes and digest truncation before implementation. No extra prefix or role bits need reduce hash entropy; roles belong in the hash input. A collision is a refusal, never alias acceptance, because replay also checks full logical identity.

The guard rejects generic publication into the whole reserved subspace before any equivalent-content/idempotent lookup. This includes manifests with omitted protocol tags, forged tags, or unrelated `matchweek_id`. Merely comparing the supplied slot with the slot derived from the supplied Matchweek is insufficient: a caller can supply the real protected slot with a different Matchweek. The generic public path cannot publish even an otherwise valid receipt into this subspace. Protected publication also re-derives and checks every binding.

Historical reads remain compatible. New generic writes into the newly reserved subspace fail. Inventory existing identifiers before reserving UUIDv8. Existing v4/v5/v7 identifiers remain unchanged; overlapping historical v8 allocation would require reconsidering this proposal. This is an API/namespace extension, not a schema or JSON migration. Arbitrary raw SQL and hostile modifications to repository internals remain outside this application's trust boundary.

The weaker alternative is stable role UUIDv5 slots plus a guard comparing against the manifest's supplied logical identity. Forging an unrelated Matchweek can evade that guard and occupy a real protected slot, but strict replay rejects the resulting identity mismatch. It can poison availability; it cannot qualify a forged valid receipt. A valid backfilled receipt must name the correct logical identity and therefore meets the weaker guard. Consequently UUIDv8 reservation strengthens write isolation and simplifies auditing, but is not necessary for safety if permanent false refusal is acceptable and replay strictly re-derives every mapping. Parent synthesis may reasonably retain UUIDv5 for compatibility. It must describe the guard honestly rather than claim unrelated-identity writes are impossible.

### Data and signatures

```python
# All signatures and types below are a design sketch; NOT IMPLEMENTED.
@dataclass(frozen=True)
class CompletedSelection:
    selection: VerifiedMatchweekSelection
    completion_receipt_digest: ArtifactDigest

@dataclass(frozen=True)
class RefusedSelection:
    reason: RefusalReason
    # Includes ABSENT, ALREADY_ASSIGNED_WITHOUT_RECEIPT, CONFLICT,
    # DEADLINE_UNPROVEN, CLOCK_UNTRUSTED, GRAPH_INVALID, STORAGE_UNCERTAIN.

SelectionResult = CompletedSelection | RefusedSelection

class MatchweekResearch:
    def __init__(self, artifacts: ArtifactStore) -> None:
        raise NotImplementedError

    def seal_completed(self, candidate: ArtifactDigest) -> SelectionResult:
        """Own admission, fresh assignment, observation, one receipt attempt, replay."""
        raise NotImplementedError

    def replay_for_matchweek(self, matchweek: LogicalMatchweek) -> SelectionResult:
        """Read-only exact graph verification; never reconstruct issuance authority."""
        raise NotImplementedError

# Module-private types. None is exported or accepted by a public API.
@dataclass(frozen=True)
class _FreshSelectionCommit:
    exact_selection: VerifiedMatchweekSelection
    operation_identity: object
    store_lifetime_identity: object
    creator_pid: int

@dataclass(frozen=True)
class _Acknowledgement:
    selection_digest: ArtifactDigest
    logical_matchweek: LogicalMatchweek
    cutoff: CommonCutoff
    utc_upper_bound: UtcInstant
    operation_identity: object
    store_lifetime_identity: object
    creator_pid: int

class _CompletionAuthority:
    # A lexical mutable cell, never a serializable value object.
    # Store lifetime also owns a consume-once registry entry keyed by identity.
    # Copies cannot create a second registry entry.
    def _consume_for_receipt(self) -> _Acknowledgement:
        raise NotImplementedError

class _ProtectedSnapshotWriter:
    def _assign_fresh(self, admitted: _AdmittedSelection) -> _FreshSelectionCommit:
        """Return only following this operation's fresh INSERT and successful commit."""
        raise NotImplementedError

    def _publish_receipt_once(self, authority: _CompletionAuthority) -> ArtifactDigest:
        """Consume before the first durable receipt action; no public timestamps."""
        raise NotImplementedError

class _RepositoryClock:
    def _postcommit_utc_upper_bound(self) -> UtcInstant:
        """Supply trusted UTC upper bound or fail; no caller override."""
        raise NotImplementedError
```

`_FreshSelectionCommit` cannot be created by a lookup. It is an internal outcome carried only by the current synchronous operation. The proposed writer is an internal capability of the artifacts/store pair, not a separately user-constructible helper with privileged methods. An underscore alone supplies no authorization. The trusted code boundary, exact live identities, and central consume-once state supply the enforceable application contract.

### Exact ordering and time claim

Let `c` be the instant the successful fresh selection commit returns, `q` the later clock sample, and `U(q)` a trusted upper bound on actual UTC at `q`. The required proof is:

`selection durable <= c <= UTC(q) <= U(q) < T`.

A wall-clock provider can define `U(q) = round_up_to_receipt_precision(W(q) + epsilon)`, where the repository explicitly trusts that its clock is no more than `epsilon` behind UTC at every accepted sample. This is a clock uncertainty contract, not a guessed scheduling margin. `epsilon = 0` states the stronger accurate-clock assumption. Unknown or violated bounds fail closed. Python and SQLite do not supply this error guarantee.

Check discontinuities against a suspend-aware elapsed clock as a diagnostic. Detection requires refusal; absence of detection does not establish UTC accuracy. An optional trusted UTC anchor plus elapsed-time design needs an explicit oscillator error bound and suspend accounting; it is a distinct clock implementation, not an implicit guarantee from `monotonic()`. On this host `CLOCK_BOOTTIME` includes suspension, while the default monotonic clock excludes it. Never silently substitute the latter. Raw wall-clock rollback without a bounded provider invalidates the proof.

The owner samples after `_assign_fresh` has returned and validates `U(q) < T` with strict, precision-safe comparison. It creates the private authority only then. A receipt can be committed arbitrarily later while the same operation and Store lifetime remain valid. No subsequent clock reading changes the already established fact. Receipt `verified_at_utc` is not compared to T.

### Ownership and lifetime

The operation holds the existing exclusive Store writer ownership throughout selection and receipt publication. It uses a nonreentrant internal guard, so callbacks cannot start another completion operation on the same Store. Existing SQLite thread ownership restrictions remain in effect.

Authority binds the exact Store object/lifetime, operation identity, creator PID, selection digest and T. `Store.close()` invalidates that lifetime and consumes all outstanding authority. Opening a new Store in the same process creates a different lifetime even if the path, PID and connection configuration match. A child after `fork()` has a different PID and cannot use its copied state; copied locks or registry cells confer no authority. The parent may complete its own operation. Duplicated Python references share the consume-once cell; shallow/deep copying, pickling and token import are unsupported, and a copied object still has no independent registry entry. Consume before attempting receipt object persistence, then invalidate on every exit. Exception handling can read an already committed receipt but cannot attempt receipt publication again.

### Module map

| Module | Knowledge owned |
| --- | --- |
| Proposed `src/matchvet/matchweek_research.py` | Stable logical identity, reserved-slot derivation, common T, admission, completion authority, clock acknowledgement, exact domain replay |
| `src/matchvet/artifacts.py` | Generic bytes/index consistency; reserved-slot rejection; internal fresh-only publication; durable object handling |
| `src/matchvet/store.py` | Store lifetime invalidation, PID/thread ownership, atomic WAL/FULL commit, unique immutable slot, consume-once authority registry lifetime |
| `src/matchvet/f16.py` | Existing full F16 lineage production and replay |

The namespace predicate has one definition imported by both protected and generic paths. It should live in a small dependency-free portion of the domain contract or existing identifiers contract to avoid a cycle. No separate load/commit/acknowledge/receipt public modules: those would expose temporal coordination to callers.

## Proof and attack table

| Attack or interruption | Required result and argument |
| --- | --- |
| Crash while selection staging bytes are written or before object installation | No indexed selection and no receipt authority. Orphan/staging bytes have no domain status. Fresh future attempt is possible only if slot remains genuinely unassigned and deadline can still be proved. |
| Selection installed but directory not synced; DB transaction absent | Orphan is not selection. Protected publication rejects orphan promotion or explicitly fsyncs reused file and containing directory, including any newly created ancestor directories, before commit. |
| Selection object synced, crash during catalog transaction or commit call | If slot absent, no selection exists; if recovered slot exists, permanent refusal without valid indexed receipt. Commit return was not observed, so no capability exists. |
| Selection commit returns; crash before postcommit sample | Recovered selection stays assigned and unqualified forever. No reconstruction from timestamps. |
| Pause after selection commit before sample | Later sample governs; equality or later T refuses even when selection may have been timely. |
| Sample equals T, or upper bound equals T | Refuse. No rounding down or `<=` comparison. |
| Valid sample; pause across T before receipt | Same live operation may publish receipt after T. The selected graph and witnessed ordering remain unchanged. |
| Crash after valid sample or during receipt staging/install | Authority dies. No indexed receipt means permanent refusal. Never scan/import orphan receipt bytes to recreate authority. |
| Receipt object durable; crash before receipt catalog commit | Same permanent refusal. Object presence cannot prove authorized completed receipt publication. |
| Receipt transaction physically durable but commit never returns to caller | Recovered fully valid indexed receipt qualifies. Its issuance followed the earlier valid observation; receipt commit return before T is not required. |
| Receipt commit returns; crash before caller sees success | Exact replay returns completed selection. |
| Receipt missing, deleted, corrupted, or checksum/index inconsistent | Refuse. Never regenerate from selection, receipt fragments, old logs, or orphan bytes. |
| Receipt present but selection missing or different | Refuse after explicit parent slot lookup and digest comparison. `parent_snapshot_id` only references a canonical identifier, not necessarily an existing snapshot row. |
| F16/F06/evidence child missing, corrupt, incomplete, wrong profile or cutoff | Refuse by recursive domain replay against exact complete INCLUDED denominator and lineage. Generic manifest verification is insufficient. |
| Old generic idempotent publication return | Never produces `_FreshSelectionCommit`. It is read-only replay at most. Guard runs before that return. |
| Generic caller forges old `created_at_utc` or supplied `verified_at_utc` | Generic path rejects reserved UUID subspace independently of caller fields or tags. |
| Caller disguises receipt under unrelated Matchweek or missing protocol version | Slot-only namespace guard still rejects; domain replay also re-derives slot and validates exact versions. |
| Protocol upgrade, alternate policy/freeze/profile/cutoff/F16 | Same stable Matchweek slot. Existing assignment wins; conflict or refusal, never a second selection. |
| Two competing processes | Store flock gives one writer. Unique slot is the final assignment constraint. Loser can replay but cannot acknowledge the winner's commit. |
| Concurrent/reentrant operation within Store | Nonreentrant owner guard and existing thread rules deny a second operation. No overlapping authority issuance. |
| Store close/reopen in same PID | Old lifetime invalid; current lookup cannot mint fresh authority. |
| Process restart or fork | No reconstruction; creator PID mismatch rejects child use, persisted objects provide no token. |
| Duplicate/replay capability, copied reference | Central lifetime registry consumes once before persistence. Second attempt fails even if first raised or produced only an orphan. |
| Commit reports busy/error but data later appears | No fresh-return authority. Fail closed; recovered indexed receipt is accepted only if already independently valid. |
| WAL lost, NORMAL substituted, unsafe journal profile | Preconditions fail. WAL must remain with DB; FULL and truthful fsync/VFS/filesystem are required. Rollback journal requires a separately established durability contract. |
| Wall clock moves backward | Bounded trusted source must reject/cover it; otherwise design cannot assert actual UTC timeliness. Monotonic cross-check alone does not repair it. |
| Clock jumps forward | Conservative refusal if bound reaches T. |
| Arbitrary privileged raw SQL, patched code, whole-store rollback | Outside application trust. There is no local cryptographic proof of provenance or antirollback guarantee. An external witness or protected monotonic storage would be required for that threat model. |

Candidate dependency objects also require durable publication. The existing-object path currently verifies bytes and skips directory fsync. Applying the protected fix only to selection and receipt while admitting unsynced orphan dependency objects would leave the graph durability argument incomplete.

## Alternatives considered

| Shape | Assessment |
| --- | --- |
| Ordinary completion row in a new dedicated table | Can express the same protocol with fewer generic manifest semantics, but adds migration and a second artifact/index model. It still needs protected provenance, fresh-return distinction and lifetime rules. Its public depth can match this candidate; no correctness advantage comes from the row alone. |
| Timestamp inside selection before committing it | Loses because the sample precedes the event it claims to upper-bound. Arbitrary pause or commit latency crosses T while preserving the same timestamp. |
| Start before a safety margin | A guessed latency margin cannot bound scheduler pause or storage latency. A clock uncertainty bound addresses a different premise and cannot be treated as a commit-duration estimate. |
| File marker after commit | Needs protected authoring, file/ancestor fsync, atomic installation and a recovery catalog. Exposes more storage knowledge or rebuilds the existing manifest store inside a new owner. |
| External witness/TSA | Can establish a stronger independent UTC/provenance boundary, with network availability, authentication and deployment consequences. Excluded by task scope and unnecessary under the explicitly trusted repository clock/writer model. |
| One callback-style generic storage transaction with clock and receipt phases | Moves domain timing policy into a generic callback API and admits reentrancy; the owner still has to coordinate the exact fresh path. Smaller production diff but poorer interface depth and harder authority audit. |
| Chosen two protected generic manifests | Uses current immutable storage and verification infrastructure while keeping timing and refusal policy behind one domain owner. Requires a carefully audited protected path; current APIs do not already provide it. |

## Tradeoffs accepted

- We accept permanent false negatives after ambiguous interruption in exchange for never converting recovered selection state into new completion authority.
- We accept a protocol-specific interpretation of existing receipt creation time in exchange for unchanged schema and manifest payload shape.
- We accept an explicit protected UUID allocation in exchange for a slot guard that cannot be bypassed by forged manifest fields.
- We accept trusted clock and durable storage assumptions in exchange for a repository-local protocol with no external witness.
- We accept that whole-store deletion or rollback defeats historical uniqueness outside the stated ownership model; this design cannot prove facts erased by a privileged operator.

## Synthesis decision

Pending parent arena comparison. This candidate recommends the two-snapshot owner as the base because it reuses one existing representation and gives callers one completion operation plus read-only replay. The most valuable constraints to preserve in any synthesis are recognizable namespace protection, explicit fresh commit outcome, Store-lifetime-bound consume-once authority, strict postcommit upper-bound comparison, and recursive graph verification.

## Open questions and risks

What repository clock contract supplies the accepted UTC error bound, and how is an unsupported deployment refused? Should the implementation reserve all UUIDv8 slots, or retain UUIDv5 derivation with strict replay and accept malformed-slot poisoning as a fail-closed result? Can the internal publication change expose a fresh result without inheriting the existing idempotent branch? These are implementation prerequisites, not facts established by the existing APIs. The theoretical protocol is sound only with their stated answers.

## Next implementation step

After design acceptance, implement and audit the recognizable namespace guard and internal fresh-only publication outcome first; the live receipt protocol must never be layered on the current ambiguous return value.

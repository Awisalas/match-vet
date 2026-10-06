# Candidate: lexical acknowledgement with a no-replace receipt file

Status: design sketch only. Every type and signature below is **NOT IMPLEMENTED**. This candidate does not change production code, tests, stores, or prior proof bytes.

## Problem

The exact logical-Matchweek selection must become durable before the common cutoff `T`. The existing `SnapshotManifest.verified_at_utc` cannot prove that ordering because `ArtifactStore.publish_manifest()` samples it before object and catalog publication. A valid proof needs an observation after a fresh selection commit returns.

This candidate keeps the selection in the existing immutable `snapshot_manifests.snapshot_id` slot. The same uninterrupted repository operation samples trusted UTC after that fresh commit. If the sample is strictly before `T`, the operation writes one canonical receipt to a deterministic, no-replace filesystem path. The receipt may become durable after `T`; it records the earlier acknowledgement. No receipt authority crosses the operation boundary.

The filesystem receipt is deliberately different from a second indexed `SnapshotManifest`. It gives the completion fact its own small representation instead of encoding that fact as another snapshot. It also introduces a second persistence format. That trade is acceptable only if the implementation remains as narrow as this sketch.

## Usage first

The caller gets one command and one query. The caller never handles a clock sample, receipt, token, filesystem path, or publication stage.

```python
from matchvet.matchweek_research import (
	MatchweekCompletionRepository,
	SealMatchweekRequest,
)

completion = MatchweekCompletionRepository(store)
outcome = completion.seal_completed(
	SealMatchweekRequest(
		matchweek_id=matchweek_id,
		f16_manifest_digest=f16_manifest_digest,
		freeze_id=freeze_id,
		cutoff_policy_version_id=cutoff_policy_version_id,
		selection_policy_version_id=selection_policy_version_id,
		research_profile_version_id=research_profile_version_id,
		common_cutoff_utc=common_cutoff_utc,
	)
)

if outcome.is_complete:
	publish_research_output(outcome.selection)
else:
	record_refusal(outcome.reason)
```

An operator restart asks for the authoritative result by logical Matchweek identity. Replay computes one stable selection slot and one stable receipt path. It does not scan objects, staging files, or other Matchweek records.

```python
completion = MatchweekCompletionRepository(reopened_store)
replayed = completion.replay_for_matchweek(matchweek_id)

if replayed is None:
	show_not_attempted()
elif replayed.is_complete:
	show_exact_selection(replayed.selection)
else:
	show_permanent_refusal(replayed.reason)
```

An alternate request cannot replace an existing selection. It receives the stored exact result only when the request matches every bound input. Otherwise it receives a conflict.

```python
outcome = completion.seal_completed(alternate_freeze_or_policy_request)
assert outcome.reason == "LOGICAL_MATCHWEEK_ALREADY_ASSIGNED_TO_DIFFERENT_INPUTS"
```

## Shape

### Data structures

`CompletionBinding` is the single source of truth for what the receipt attests. The receipt repeats the common cutoff and policy identities rather than relying only on a digest. Replay still derives the same binding from the selected manifest and recursively verified F16 graph. Both values must match byte for byte.

The final receipt path depends only on the logical Matchweek identity:

```text
<store-parent>/completion-receipts/<sha256(canonical logical Matchweek identity)>.json
```

The path does not contain the freeze, policy, profile, F16 digest, cutoff, or protocol version. Those values cannot create an alternate receipt slot. A protocol upgrade must interpret or reject the same stable slot.

```python
# src/matchvet/matchweek_research.py

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True)
class SealMatchweekRequest:
	matchweek_id: CanonicalIdentifier
	f16_manifest_digest: str
	freeze_id: CanonicalIdentifier
	cutoff_policy_version_id: CanonicalIdentifier
	selection_policy_version_id: CanonicalIdentifier
	research_profile_version_id: CanonicalIdentifier
	common_cutoff_utc: str


@dataclass(frozen=True)
class CompletedMatchweek:
	matchweek_id: CanonicalIdentifier
	selection_snapshot_id: CanonicalIdentifier
	selection_manifest_digest: str
	f16_manifest_digest: str
	acknowledged_at_utc: str
	common_cutoff_utc: str


class CompletionRefusal(StrEnum):
	SELECTION_COMMIT_DID_NOT_RETURN = "SELECTION_COMMIT_DID_NOT_RETURN"
	SELECTION_NOT_BEFORE_CUTOFF = "SELECTION_NOT_BEFORE_CUTOFF"
	SELECTION_EXISTS_WITHOUT_RECEIPT = "SELECTION_EXISTS_WITHOUT_RECEIPT"
	RECEIPT_MISSING_OR_INVALID = "RECEIPT_MISSING_OR_INVALID"
	SELECTION_GRAPH_MISSING_OR_INVALID = "SELECTION_GRAPH_MISSING_OR_INVALID"
	LOGICAL_MATCHWEEK_ALREADY_ASSIGNED_TO_DIFFERENT_INPUTS = (
		"LOGICAL_MATCHWEEK_ALREADY_ASSIGNED_TO_DIFFERENT_INPUTS"
	)
	STORE_OR_PROCESS_CHANGED = "STORE_OR_PROCESS_CHANGED"


@dataclass(frozen=True)
class MatchweekCompletionOutcome:
	is_complete: bool
	selection: CompletedMatchweek | None
	reason: CompletionRefusal | None


@dataclass(frozen=True)
class CompletionBinding:
	protocol_id: str
	matchweek_id: str
	selection_snapshot_id: str
	selection_manifest_digest: str
	f16_manifest_digest: str
	freeze_id: str
	cutoff_policy_version_id: str
	selection_policy_version_id: str
	research_profile_version_id: str
	common_cutoff_utc: str


@dataclass(frozen=True)
class _CompletionReceiptV1:
	schema_version: int
	binding: CompletionBinding
	acknowledged_at_utc: str
	receipt_sha256: str

	def to_canonical_bytes(self) -> bytes:
		raise NotImplementedError("NOT IMPLEMENTED")

	@classmethod
	def from_canonical_bytes(cls, content: bytes) -> "_CompletionReceiptV1":
		raise NotImplementedError("NOT IMPLEMENTED")


@dataclass
class _FreshSelectionCommit:
	"""Private evidence returned only after the new catalog commit returns."""

	store_identity: int
	origin_pid: int
	binding: CompletionBinding
	_consumed: bool = False

	def consume(self, acknowledged_at_utc: str) -> _CompletionReceiptV1:
		"""Invalidate this value, then create the sole authorized receipt."""
		raise NotImplementedError("NOT IMPLEMENTED")


class MatchweekCompletionRepository:
	"""Own selection assignment, acknowledgement, receipt publication, and replay."""

	def __init__(self, store: Store) -> None:
		raise NotImplementedError("NOT IMPLEMENTED")

	def seal_completed(self, request: SealMatchweekRequest) -> MatchweekCompletionOutcome:
		raise NotImplementedError("NOT IMPLEMENTED")

	def replay_for_matchweek(
		self,
		matchweek_id: CanonicalIdentifier,
	) -> MatchweekCompletionOutcome | None:
		raise NotImplementedError("NOT IMPLEMENTED")

	def _publish_fresh_selection(
		self,
		request: SealMatchweekRequest,
	) -> _FreshSelectionCommit | MatchweekCompletionOutcome:
		raise NotImplementedError("NOT IMPLEMENTED")

	def _acknowledge_and_publish_receipt(
		self,
		fresh: _FreshSelectionCommit,
	) -> MatchweekCompletionOutcome:
		raise NotImplementedError("NOT IMPLEMENTED")

	def _replay_exact_binding(
		self,
		binding: CompletionBinding,
		acknowledged_at_utc: str,
	) -> CompletedMatchweek:
		raise NotImplementedError("NOT IMPLEMENTED")
```

The private artifact hook must distinguish a new durable assignment from an existing immutable slot. It also reserves the selection slot namespace. Generic `publish_manifest()` calls must reject any derived selection slot, even when a caller supplies matching bytes.

```python
# src/matchvet/artifacts.py

@dataclass(frozen=True)
class _ReservedManifestPublication:
	record: ArtifactRecord
	was_fresh_commit: bool


class ArtifactStore:
	def _publish_matchweek_selection_once(
		self,
		manifest: SnapshotManifest,
		*,
		expected_snapshot_id: CanonicalIdentifier,
	) -> _ReservedManifestPublication:
		"""Publish one reserved selection and report whether this call committed it."""
		raise NotImplementedError("NOT IMPLEMENTED")
```

The receipt writer is private to the domain module. Its input is `_FreshSelectionCommit`, which never appears in a public return type. Python privacy is an application boundary, not a security boundary.

```python
# private helpers in src/matchvet/matchweek_research.py

def _repository_utc_now() -> datetime:
	"""Read the configured trusted UTC source after selection commit return."""
	raise NotImplementedError("NOT IMPLEMENTED")


def _publish_receipt_no_replace(
	store: Store,
	*,
	origin_pid: int,
	receipt: _CompletionReceiptV1,
) -> None:
	"""Fsync private staged bytes, install once, then fsync the final directory."""
	raise NotImplementedError("NOT IMPLEMENTED")


def _read_receipt_for_matchweek(
	store: Store,
	matchweek_id: CanonicalIdentifier,
) -> _CompletionReceiptV1 | None:
	raise NotImplementedError("NOT IMPLEMENTED")
```

### Operation flow

`seal_completed()` performs these steps without an `await`, callback, hook, or caller-controlled clock:

1. Validate the complete F16 graph, exact F06 freeze, common cutoff, cutoff policy, selection policy, and research profile.
2. Derive the stable selection snapshot ID from the logical Matchweek identity alone.
3. Check the exact receipt path. If a receipt exists without the indexed selection, refuse permanently. An inconsistent restore cannot reopen the logical slot.
4. If the selection slot exists, replay it. Return completion only for an intact matching receipt and graph. Return permanent refusal for a missing or invalid receipt. Return conflict for alternate inputs.
5. Publish the exact selection through `_publish_matchweek_selection_once()`. If it reuses an orphan object file, fsync the object and its parent directory before the catalog transaction.
6. Continue only when the helper reports that this call's catalog commit returned successfully.
7. Confirm that the exact `Store` instance is open and that `os.getpid()` still equals the operation's origin PID.
8. Sample the trusted repository UTC clock. Require `acknowledged_at_utc < common_cutoff_utc`. Equality refuses.
9. Build canonical receipt bytes from the private fresh-commit value and the sample. Mark the local fresh-commit guard consumed before the first filesystem write. No loop or retry can recreate it.
10. Create the private receipt directory with no symbolic-link traversal and fsync its parent if the directory entry is new. Write a same-directory private staging file with `O_CREAT | O_EXCL | O_NOFOLLOW`, mode `0600`. Fsync the file, verify its length and digest, install it at the deterministic final path with no replacement, and fsync the final directory. The writer checks the captured origin PID before each state change.
11. Read the final path and replay the entire graph before returning completion. If publication raised after the no-replace install, inspect only the exact final path. Accept it only when the canonical receipt and graph validate. Never promote a staging file.

The lexical fresh-commit value matters more than the dataclass sketch. The implementation must keep it inside `seal_completed()` and its private direct callees. There is no constructor, serializer, deserializer, import method, retry method, backfill command, public acknowledgement call, or public receipt writer.

### Replay checks

Replay accepts completion only when all checks pass:

- The exact deterministic receipt path is a regular file under private directory components and is not a symbolic link.
- The bytes are canonical V1 receipt bytes, and `receipt_sha256` matches the payload.
- The receipt path hash matches the receipt's logical Matchweek identity.
- The selection snapshot ID equals the stable ID derived from that same logical identity.
- The catalog resolves that slot to the exact receipt `selection_manifest_digest`.
- The selection manifest and all catalog memberships pass `ArtifactStore.verify_manifest()`.
- Domain replay resolves the exact complete F16 graph, F06 freeze, cutoff policy, selection policy, profile, common `T`, and every child lineage.
- The binding derived from that verified graph equals the receipt binding.
- `acknowledged_at_utc` is valid UTC and is strictly less than the bound common `T`.
- The receipt protocol ID is supported. An upgrade cannot derive another final path.

Missing, malformed, noncanonical, corrupt, mismatched, or unsupported data refuses the Matchweek. Replay never repairs it.

### Module map

| Module | Responsibility |
| --- | --- |
| `src/matchvet/matchweek_research.py` | Public command and query, stable IDs, complete domain validation, lexical acknowledgement, receipt format, no-replace receipt publication, and replay. |
| `src/matchvet/artifacts.py` | Existing object and manifest verification plus one private reserved-selection publication hook that reports fresh commit versus replay. Generic publication rejects reserved IDs. |
| `src/matchvet/store.py` | Existing writer lock, process ownership, `BEGIN IMMEDIATE`, WAL plus `synchronous=FULL`, and immutable selection catalog transaction. No schema change. |
| `src/matchvet/f16.py` | Existing exact F16 production and recursive lineage replay. It does not know about receipt persistence. |
| `completion-receipts/` beside the database | Private final receipt files and same-directory temporary files. The application never imports a temporary file as a receipt. Format versioning lives inside the one stable file. |

The public interface has two methods because command and replay have different inputs. Those two calls hide manifest validation, fresh-commit detection, time ordering, no-replace installation, crash recovery, and recursive graph verification. Adding public stage methods would expose the protocol's most dangerous states.

## Attack and recovery table

| Case | Durable state that may remain | Required result and reason |
| --- | --- | --- |
| Crash before selection object staging | Nothing | A later call may attempt the first selection. No assignment exists. |
| Crash after selection staging fsync, before object install | A private partial file | Ignore or delete the partial file. Never derive authority or a selection from it. |
| Crash after selection object install, before catalog commit | An orphan content-addressed object | A later fresh publication may reuse the bytes only after verifying them and fsyncing the file and parent. The later catalog commit is the selection commit. The orphan itself proves no selection. |
| Selection transaction rolls back | An orphan selection object | No acknowledgement. A later fresh catalog assignment may proceed. |
| SQLite commit becomes durable but `commit()` does not return | An indexed selection, no receipt authority | Permanent refusal unless an already authorized intact receipt also survived. The process did not observe successful return and cannot issue authority after restart. |
| Commit returns, then crash or pause before the clock sample | An indexed selection without a receipt | Permanent refusal. A later sample cannot repair the lost ordering observation. |
| Pause before the clock sample crosses `T` | An indexed selection | The later sample is at or after `T`, so refuse. |
| Clock sample equals `T` | An indexed selection | Refuse. The comparison is strict. |
| Clock sample is before `T`, then execution pauses past `T` | An indexed selection and perhaps a later receipt | The receipt remains valid. It records the earlier post-commit acknowledgement, not its own publication time. |
| Crash after valid sample, before receipt staging | An indexed selection | Permanent refusal. The sample was volatile and is never reconstructed. |
| Crash while creating the private receipt directory | An indexed selection and perhaps an empty directory | Refuse unless a valid final receipt exists. A new directory entry must be followed by its parent-directory fsync before use. |
| Crash during receipt write or before its fsync | A receipt partial file | Ignore or delete the partial file. It cannot qualify the Matchweek. |
| Crash after receipt file fsync, before final no-replace install | A receipt partial file | Refuse. Replay checks only the exact final path. |
| Crash after final install, before directory fsync returns | The final receipt may survive or disappear after power loss | Accept only if the exact valid file survives and the full graph validates. Absence or corruption refuses. The live operation already held valid authority before install. |
| Crash after final directory fsync, before method return | A durable final receipt | Replay accepts the exact valid receipt. Receipt publication need not have returned. |
| Existing valid final receipt races installation | The original receipt | Verify it. Accept only if its binding equals the fresh operation's exact binding. No-replace never overwrites it. Under normal operation the writer lock makes this race unreachable. |
| Existing malformed or conflicting final receipt | The bad first file | Permanent refusal. Do not replace, rename aside, or try another path. First assignment of the receipt slot is final. |
| Two processes compete | One process owns `.matchvet-writer.lock` | The other process cannot open a writer. If it later opens, it replays the winner's selection and cannot gain fresh authority. |
| Two calls compete on one process | At most one immutable selection slot | The single SQLite connection and immediate transaction serialize the commit. Only the call that receives `was_fresh_commit=True` may sample the clock. Existing-slot paths never gain authority. |
| Reentrant call after selection commit but before receipt | The selection exists | The reentrant call refuses or replays. It cannot receive fresh authority. The original lexical operation may still finish. No user callback or `await` exists in the critical path. |
| Store closes and reopens in the same process | A new `Store` object | The old operation fails its exact-store and open-state checks. The reopened owner can replay but cannot recreate authority. |
| Process restarts | Only durable selection and receipt state | An intact receipt permits replay. A selected Matchweek with no valid receipt refuses forever. |
| Fork before or after the clock sample | Child memory contains copied locals | Every post-commit step checks the captured origin PID and the original Store owner. The child cannot publish. The parent may continue. |
| Token duplication or replay | No public token exists | The acknowledgement remains lexical state. Receipt bytes deserialize only as evidence for replay, never as write authority. |
| Wall clock steps forward | The sample may appear late | Conservative refusal. No false completion. |
| Wall clock steps backward or reports false UTC | The sample may appear timely after real `T` | The proof fails. The protocol must trust accurate, nonrollback UTC at the sample. A local monotonic clock alone cannot establish UTC. |
| Suspend between commit and sample | No special state | The post-resume UTC sample decides. If suspension crosses `T`, refuse. |
| Suspend after a valid sample | Volatile authority remains in the same operation | A later receipt may still publish. This relies on process memory surviving and the UTC premise at the earlier sample. |
| Reboot | Volatile authority disappears | Replay only. Never reconstruct authority from the selection, WAL, receipt partial, process ID, boot clock, or logs. |
| WAL plus `synchronous=FULL` under a truthful VFS | Committed selection survives stated failures | The post-return sample is ordered after a durable selection commit. Checkpoints are irrelevant to this ordering. |
| Journal mode or synchronous profile changes | Durability premise changes | Refuse operation until the operating profile is re-proved. Rollback journal with weaker syncing is not silently equivalent. |
| Missing or corrupt selection manifest object | Receipt may remain intact | Refuse. A receipt never substitutes for the exact graph. |
| Missing, corrupt, or inconsistent F06, policy, profile, F16, or child lineage | Receipt and selection may remain | Refuse. Replay must verify the complete bound graph. |
| Receipt deleted | The immutable selected slot remains | Permanent refusal. No API can recreate the receipt from disk. |
| Receipt bytes corrupt or truncated | The selected slot remains | Permanent refusal. The final path cannot be replaced through the protocol. |
| Receipt staging file survives beside no final receipt | An orphan partial file | Refuse and optionally clean the partial. Never promote or parse it as authority. |
| Receipt exists but the indexed selection is absent | An orphan final receipt after an inconsistent restore or unauthorized write | Refuse permanently and do not create a selection. Replay never imports the receipt into the catalog or derives authority from it. |
| Alternate freeze, policy, profile, F16, cutoff, or selection arrives | The stable selection and receipt paths are unchanged | Return conflict or the exact existing outcome. Alternate inputs cannot mint another slot or lineage. |
| Protocol version changes | The stable final path is unchanged | Read the existing protocol or refuse. A new protocol ID cannot mint a replacement receipt. |
| Generic artifact or manifest publication targets the reserved selection ID | No selection change | Reject before publication. Reserved-ID protection must be based on the derivation namespace, not an optional caller tag. |
| Privileged process rewrites the database or receipt directory | Arbitrary forged state | No local guarantee. This protocol offers no primitive or trust boundary against a privileged attacker, malicious repository code, memory tampering, a lying VFS, or hostile storage hardware. |

## Synthesis decision

This runner chooses a lexical post-commit acknowledgement plus a deterministic no-replace file receipt. The choice is independent of the arena's final synthesis. It is the smallest direct representation of the fact being proved: one selected manifest, one post-commit time, and one immutable receipt file.

The lexical shape is the load-bearing part. It removes token lifecycle design entirely. The filesystem shape then stores the evidence without presenting it as a second selected snapshot. If the arena finds that adding a private file format and inspection path costs more than reusing `SnapshotManifest`, the indexed second-manifest candidate is a sounder base. The two designs prove the same ordering only when both enforce the same fresh-commit and no-reconstruction rules.

## Tradeoffs accepted

- We accept a second persistence format in exchange for a receipt that directly models completion instead of overloading snapshot semantics.
- We accept permanent refusal after receipt loss or ambiguous publication in exchange for never backfilling evidence.
- We accept false refusals from forward clock steps and pauses before sampling in exchange for a strict, conservative deadline test.
- We accept dependence on WAL plus `synchronous=FULL`, truthful `fsync`, atomic no-replace installation, private directory semantics, and accurate nonrollback UTC in exchange for a repository-local protocol.
- We accept that a valid receipt can appear after `T` in exchange for using the post-selection acknowledgement, rather than receipt publication, as the qualifying event.
- We accept application-level privacy and repository-code trust in exchange for no external witness. Python's private names and filesystem permissions are not capabilities against a privileged attacker.

## Alternatives considered

| Alternative | Why it loses or wins |
| --- | --- |
| Ordinary completion row written with the selection | The row's timestamp is chosen before the transaction commits. It cannot prove that commit returned before `T`. A row in a later transaction works only when guarded by the same private lexical acknowledgement; at that point it is another receipt encoding. |
| Precommit `verified_at_utc` on the selection manifest | Existing publication samples it before object and catalog persistence. It proves preparation time, not durable completion time. |
| Safety margin before `T` | A margin lowers operational risk but does not change event order. A stalled or failed commit can still finish after `T`. No finite margin proves otherwise. |
| Filesystem marker created before selection commit | Its order is backwards. The marker can survive when selection fails or commits late. |
| Public or serializable post-commit token | Callers can duplicate, retain, replay, persist, or import it after reopening. That interface exposes the critical state and makes the protocol shallow. |
| Receipt authority reconstructed from an indexed selection, WAL, object bytes, staging file, PID, or boot ID | Reconstruction erases the distinction between a commit whose return was observed before `T` and an ambiguous commit recovered later. This is forbidden. |
| Second protected `SnapshotManifest` in a receipt slot | This is viable and reuses canonical bytes, content-addressed objects, catalog immutability, and existing verification. It also needs reserved-slot enforcement, a fresh-publication result, domain graph replay, and private lexical authority. It avoids a new file verifier but encodes a completion event as a snapshot and adds catalog rows and memberships. I prefer the direct file while its writer and parser stay local; I prefer the second manifest if existing inspection and backup tooling must account for every protected byte automatically. |
| Later SQLite receipt row in a dedicated table | This is also viable and makes backup and integrity checks simpler. It requires a schema migration and a private insertion path. A unique logical-Matchweek key and immutable triggers are mandatory. The file candidate avoids a migration but inherits filesystem inspection work. |
| External witness or trusted timestamp authority | A witness can defend against some local clock and local writer failures. It adds a new trust domain, protocol, availability dependency, and recovery story. The issue excludes TSA work, and the repository-local threat model does not require it. |

## Red-flag screen

- **Shallow module:** Pass. Callers coordinate no stages. Two public calls hide selection publication, time comparison, receipt persistence, and replay.
- **Information leakage:** Pass with a condition. `CompletionBinding`, receipt bytes, paths, and fresh-commit results stay private to `matchweek_research.py`. The public outcome contains only the selected result and refusal reason.
- **Temporal decomposition:** Pass. One domain owner contains work that happens before commit, after commit, and during replay because all steps protect the same Matchweek completion rule.
- **Pass-through methods:** Pass with a condition. The artifact hook adds reserved namespace enforcement and fresh-versus-existing commit knowledge. A wrapper that only forwards `publish_manifest()` would fail this screen.

## Trust statement

The claim is conditional: trusted repository code observed the exact fresh selection commit return, then observed trusted UTC strictly before the bound common `T`, then used the still-live lexical operation to publish these receipt bytes.

SQLite and the filesystem supply atomicity and durability only under their documented VFS, locking, and `fsync` assumptions. The local wall clock supplies UTC only under the deployment's time premise. The no-replace path prevents normal repository operations from replacing a receipt. None of these mechanisms authenticates evidence against a privileged attacker. This design offers no primitive or trust against someone who can modify process memory, call private code, replace database or receipt files, control the clock, or make the VFS lie.

## Open questions and risks

- Must `open_store()` treat a corrupt completion receipt as whole-store recovery mode, or should only Matchweek completion replay fail closed? I prefer domain-local refusal so unrelated historical data stays readable.
- Does the repository backup contract copy the database, WAL, artifact tree, and `completion-receipts/` directory as one consistency unit? If existing backup tooling knows only catalogued artifacts, the second `SnapshotManifest` is safer operationally.
- Can the supported filesystems always provide the existing `renameat2(RENAME_NOREPLACE)` or hard-link fallback? If neither gives atomic no-replace installation, this candidate must refuse receipt publication.
- Should receipt partial cleanup live beside `ArtifactStore.discard_incomplete_staging()` or remain a private maintenance method on `MatchweekCompletionRepository`? Cleanup must never inspect a partial file for authority.
- What repository clock contract will deployment accept? Without accurate nonrollback UTC, no local design can prove the real-world cutoff.

## Next implementation step

Build an isolated scratch proof of the no-replace receipt writer and crash each boundary before any production module or schema changes.

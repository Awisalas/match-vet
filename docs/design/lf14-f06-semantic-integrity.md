# LF14 F06 semantic integrity

LF14 #57 corrects the confirmed audit defects without replacing historical assertions or changing schema 13. The public interfaces remain freeze_exact, persist_exact, exact reads, and append_observation.

## Contract

Call freeze_exact with membership policy version 2 for corrected semantic comparisons. Policy 1 keeps its original canonical bytes and frozen replay. Schema 13 requires root payload_version=1, so the envelope remains unchanged. Optional policy-2 integrity snapshots and conflict-projection metadata live inside the existing canonical JSON. Legacy encoding omits those additions.

A policy-2 revision snapshot includes ordered canonical home/away IDs, source_round, full content digests for all selected assertions, and derived semantic assertion values. Team values require persisted source/league mapping evidence agreeing with immutable canonical fixture identity. Kickoff values are typed DATE/INSTANT facts in the configured league timezone. Status values use the versioned membership classes. Raw assertion bytes are never changed.

Conflict snapshots are exact selected assertion projections backed by an immutable cumulative conflict record. The projection retains every selected assertion ID and its raw values/digest, plus the historical record digest. A backing record must cover all selected IDs, not just distinct values. Replay validates that recorded backing record and exact projection, ignoring later unrelated links. Equivalent spellings, compatible date precision, and membership-equivalent statuses do not become material conflicts.

All new creation and persist_exact validate revision content digests and complete membership assertion coherence, including the original policy-1 creation interface. Policy-2 replay compares the same validated integrity facts to its frozen snapshots. Legacy replay retains its original contract. A newer revision or alias registry cannot silently reinterpret an old freeze.

The controlling tier uses settled authority and retrieval ordering. A compatible INSTANT wins a same-tier precision tie over DATE so available exact scheduling is used. Unknown membership facts and genuine controlling-tier conflicts fail closed.

Observations use explicit stable candidate identity state transitions for policy 2. A changed candidate ID alone does not establish identity resolution. Policy-1 observations retain their original replay semantics.

## Module sketch

matchweek_membership.py owns policy versions, integrity snapshot dataclasses, canonical encoding, and legacy decoding. matchweek_membership_integrity.py owns validation and derived semantic facts, typed compatibility, and historical conflict projection. matchweek_membership_repository.py uses those facts for policy-2 creation, revalidation, exact replay, and observations while keeping the policy-1 path explicit.

The integrity module exposes load_revision_integrity(store, reference), project_conflicts(store, fixture_id, assertion_ids, semantic_values), material_conflict_values(store, fixture_id, assertion_ids, semantic_values), validate_conflict_projection(store, fixture_id, projection, selected_assertion_ids), and typed revision/assertion comparison helpers. It owns its SQLite queries and raises one integrity error that the repository translates to stable F06 diagnostics.

## Design synthesis

Two designs were explored. Candidate A kept the existing snapshot shape and derived semantics on every read. Candidate B introduced typed integrity evidence inside the JSON envelope. B identified that a root payload2 conflicts with schema13. Both model agents reached a usage limit before producing full design artifacts, so the root synthesized from their concrete findings and repository evidence.

The chosen base is typed optional integrity evidence: it freezes assertion content and canonical comparison values explicitly and allows replay to detect unchanged IDs with altered facts. Graft A's cumulative-history projection and strict raw revision hashing. Reject a literal root payload2 because it would force an unnecessary migration. Reject rewriting historical normalized values because LF12 pins the old manual spelling format.

## Verification seams

The user confirmed public F06 persistence/read/observation interfaces, real importer → F01/F05 persistence, and LF05/LF13 record/replay. Temporary-store SQL is reserved for corruption or failure injection. Each behavior is introduced through a red/green integration slice. Full focused, subsystem, Ruff, mypy, and full-suite verification precede commit/push and live validation.

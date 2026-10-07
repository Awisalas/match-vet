# ADR 0001: One frozen information state per Matchweek

Date: 2026-10-05

Status: accepted and implemented under [#73](https://github.com/Awisalas/match-vet/issues/73); isolated offline acceptance passed in [#78](https://github.com/Awisalas/match-vet/issues/78). Live authoritative validation remains pending.

## Context

The founder requires every match in the seven-league Friday-through-Monday slate to use the information frozen before its earliest eligible kickoff. The glossary preserves that rule, but the intervening V2 direction and implemented F07/F11 contracts use independent match deadlines. Exact F07 identities propagate into models, decisions, processing, and timestamp commitments. Reinterpreting them would invalidate immutable history.

## Decision

Add an explicitly versioned F07 policy rule deriving one cutoff from the earliest exact INCLUDED F06 kickoff. Retain explicit 21600 seconds for the initial corrected policy, based on the settled founder six-hour decision. Preserve the legacy rule and its readers.

Each INCLUDED match retains its existing exact F06/revision/policy-bound F07 reference, with the same common boundary. Complete and select the existing F16 whole-Matchweek manifest before that boundary. Reuse protected generic snapshot manifests for single assignment; after cutoff, allow exact replay and permitted audit/settlement only. Enforce closure through every corrected writer and downstream consumer.

No SQLite migration or F07/downstream payload expansion is required. Isolated compatibility and single-assignment proofs passed during implementation. Old policies, artifacts, released methodology, and evidence retain their original meanings.

### Completion protocol clarification, 2026-10-06

The deadline applies to durability of the exact selection and its complete graph. A
repository UTC upper-bound observation after its fresh atomic commit must be strictly
before T. That same live operation gets private one-use authority to publish a protected
completion receipt. Receipt persistence may finish after T; it records the earlier fact
and cannot select or replace state. This removes the unnecessary deadline on the final
evidence write while preserving the founder's selection deadline.

Use a second existing SnapshotManifest with a stable logical-Matchweek receipt slot,
exact selection artifact/parent binding, supported protocol version and repository
acknowledgement bound in its domain-defined creation time. Generic verification time
retains its original meaning. No schema or generic payload-field migration is required.
The current APIs need a protected fresh-assignment path, reserved-role publication guard
and authority restricted to the original Store/process/operation lifetime.

An indexed selection without valid indexed receipt evidence after crash/reopen remains
permanently unqualified. Recovery must never backfill receipts, adopt orphan bytes or
choose another proposal. Valid receipts require full exact-graph replay. The proof trusts
repository code, a genuine UTC upper bound, and honest SQLite WAL/FULL, fsync and storage
ownership; it provides no cryptographic assurance against a hostile local operator.

See the [protocol specification](../design/matchweek-selection-completion-protocol.md),
[primary-source research](../research/matchweek-selection-completion-protocol-2026-10-06.md),
and [isolated protocol evidence](../../.audit/issue-75-completion-protocol/). The original
failed [storage proofs](../../.audit/issue-75-storage-proof/) are retained unchanged.
Repository implementations for #75 and #76 are complete. Production trusted-UTC validation and the live rebuild remain pending.

## Consequences

Research and computation for later fixtures finish before the earliest fixture's cutoff. A missed or unestablished boundary refuses the whole slate. First computation after cutoff would require a separately designed frozen-input selection contract; it is outside this smallest correction.

CB01 retains fixture batches and its existing strict cutoff-to-own-kickoff witness window, without treating a timestamp as proof of pre-cutoff collection. Evaluation separates legacy and corrected policy cohorts.

See the [correction design](../design/matchweek-wide-evidence-cutoff.md) for admission guards, exact affected contracts, evidence, implementation acceptance, and the future A-store rebuild sequence.

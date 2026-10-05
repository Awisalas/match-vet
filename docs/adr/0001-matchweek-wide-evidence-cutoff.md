# ADR 0001: One frozen information state per Matchweek

Date: 2026-10-05

Status: accepted architecture decision; implementation pending in [#73](https://github.com/Awisalas/match-vet/issues/73).

## Context

The founder requires every match in the seven-league Friday-through-Monday slate to use the information frozen before its earliest eligible kickoff. The glossary preserves that rule, but the intervening V2 direction and implemented F07/F11 contracts use independent match deadlines. Exact F07 identities propagate into models, decisions, processing, and timestamp commitments. Reinterpreting them would invalidate immutable history.

## Decision

Add an explicitly versioned F07 policy rule deriving one cutoff from the earliest exact INCLUDED F06 kickoff. Retain explicit 21600 seconds for the initial corrected policy, based on the settled founder six-hour decision. Preserve the legacy rule and its readers.

Each INCLUDED match retains its existing exact F06/revision/policy-bound F07 reference, with the same common boundary. Complete and select the existing F16 whole-Matchweek manifest before that boundary. Reuse protected generic snapshot manifests for single assignment; after cutoff, allow exact replay and permitted audit/settlement only. Enforce closure through every corrected writer and downstream consumer.

No SQLite migration or F07/downstream payload expansion is expected. Compatibility and single-assignment behavior require isolated proof during implementation. Old policies, artifacts, released methodology, and evidence retain their original meanings.

## Consequences

Research and computation for later fixtures finish before the earliest fixture's cutoff. A missed or unestablished boundary refuses the whole slate. First computation after cutoff would require a separately designed frozen-input selection contract; it is outside this smallest correction.

CB01 retains fixture batches and its existing strict cutoff-to-own-kickoff witness window, without treating a timestamp as proof of pre-cutoff collection. Evaluation separates legacy and corrected policy cohorts.

See the [correction design](../design/matchweek-wide-evidence-cutoff.md) for admission guards, exact affected contracts, evidence, implementation acceptance, and the future A-store rebuild sequence.

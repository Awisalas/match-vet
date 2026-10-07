# F19 V2 settlement contract

## Purpose

F19 attaches later-known result evidence to one exact F16 match result and one enabled preference in its F14 decision. Each settlement version is a protected immutable artifact. It records what the supplied evidence supports at that point in history.

## Usage

```python
repository = SettlementRepository(store)
record = repository.build(
    manifest_digest=f16_manifest_digest,
    match_result_digest=f16_match_result_digest,
    preference_id="match_winner_home",
    evidence=source_evidence,
)
replayed = repository.replay(record.digest)
corrected = repository.correct(record.digest, corrected_source_evidence)
assert corrected.predecessor_digest == record.digest
```

`build` replays the protected F16 manifest and verifies it contains the named match result. F16 replay verifies its F14 decision. F19 then checks that the exact preference is enabled in that decision and is an unchanged T10 preference. Every evidence record must name that match's fixture.

For the corrected Matchweek cutoff policy, F19 also replays the exact indexed
Matchweek selection and completion receipt before using its lineage cache. Only
that selected F16 manifest can receive a settlement or correction. Unselected
candidates, different freezes or policies, and missing completion evidence refuse.
Legacy settlements retain their original per-match policy and exact bytes.

## Settlement states

F19 preserves T10's deterministic grading rules and records one of these states:

| F19 state | T10 grade | Settlement result |
| --- | --- | --- |
| `PENDING` | `PENDING` for incomplete status or missing required facts | None |
| `CONFLICTING` | `PENDING` with `SOURCE_CONFLICT` | None |
| `WIN` | `FINAL` | `WIN` |
| `LOSS` | `FINAL` | `LOSS` |
| `PUSH` | `FINAL` | `PUSH` |
| `VOID` | `FINAL` | `VOID` |

PUSH is a distinct settlement result and does not count as success. Unknown or insufficient evidence remains pending. F19 does not finalize unresolved evidence into VOID.

## Identity, replay, and corrections

The settlement identity contains the F16 manifest digest, F16 match result digest, F14 decision digest, and preference ID. The full canonical record also contains the fixture ID, complete T10 evidence records, T10 grade and provenance, evidence digest, state, result, correction sequence, and predecessor digest.

The canonical protected artifact digest is the settlement version identity. Rebuilding identical evidence for an identity replays the same artifact. Changed evidence requires an explicit predecessor. A correction keeps all four identity values fixed, records a full replacement evidence snapshot, increments the sequence, and points to its predecessor. A predecessor can have one distinct successor; replaying the same successor is idempotent. Earlier versions remain independently replayable, including unresolved conflicts.

Replay validates the artifact digest and schema, replays the exact F16 and F14 lineage, reconstructs the T10 evidence, and recomputes the grade. Any difference fails closed. F19 stores one artifact per version, so it needs no schema migration or mutable current pointer.

## Provenance and boundaries

F19 accepts T10 source evidence records and retains their source identity, authority, times, assertions, and provenance as supplied. It does not acquire data or claim that an operator-entered source record came from an automated provider. Manual T10 grading records are not accepted as F19 evidence and remain in the separate V1 grading path.

F19 does not add F17 behavior, automatic acquisition from F20, markets, or bookmaker odds. Odds fields in retained evidence provenance are rejected.

Later outcomes and post-cutoff source corrections belong to settlement and
evaluation history. They cannot enter the selected F11 evidence, F13 model inputs
or F14 recommendation. Corrected evaluation uses the separate
[chronology 0.2.0](product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md) and explicitly
named CB01 outcome attachments. It never discovers a latest settlement to replace
the outcome version selected by its caller.

## Design choice

One artifact contains the full evidence snapshot and its derived grade. A separate evidence artifact would add a second publication and a possible orphan without a current evidence-reuse or inspection need. ArtifactStore already provides protected content-addressed persistence, and T10 remains the owner of result interpretation.

## Synthesis decision

The single settlement artifact design was selected over a separate evidence-set artifact and settlement artifact. The cross-judge scored it 24/25 and the two-artifact design 22/25. The single artifact records the full evidence snapshot and grade in one replayable object. The alternative adds a second publication without a current evidence reuse need. The design also rejects mutable settlement rows and reuse of the manual T10 recorder because neither meets the V2 provenance and replay boundary.

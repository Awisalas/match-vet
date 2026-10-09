# Causal Matchweek implementation tickets

[Parent #80](https://github.com/Awisalas/match-vet/issues/80) is complete; its
original acceptance matrix and final evidence are in the #84 audit record.
[ADR 0003](../adr/0003-causal-matchweek-selection-witness.md) and the
[accepted architecture](causal-matchweek-selection-witness.md) remain the contract.
This record decomposes implementation without changing that architecture.

| Order | Ticket | Ownership boundary | Blocked by | Current readiness |
| --- | --- | --- | --- | --- |
| 1 | [#81](https://github.com/Awisalas/match-vet/issues/81) | Research/Store selection authority, RFC3161 verification, approved profile and trust provenance, protected v2 completion/replay | None | Completed |
| 2 | [#82](https://github.com/Awisalas/match-vet/issues/82) | Immutable candidate descriptor, stage schemas and all direct/resume writer contracts, cross-version occupancy | #81 (closed) | Completed |
| 3 | [#83](https://github.com/Awisalas/match-vet/issues/83) | Selected-state consumers, CB01 adapter/denominator, F19 and report/evaluation/legacy dispatch | #82 (closed) | Completed |
| 4 | [#84](https://github.com/Awisalas/match-vet/issues/84) | Integrated seven-league successor proof and complete parent acceptance evidence | #83 (closed) | Completed |

All four are native sub-issues. Native blocking edges form
`#81 → #82 → #83 → #84 → #80`; all child issues and the parent acceptance are
complete. Production activation remains refusing under the default configuration.

Each child contains exact scope, explicit non-scope, acceptance criteria, focused
tests, dependencies and a model/skill recommendation. Copies of the published
bodies are retained in [the ticketing record](../../.audit/issue-80-ticketing/README.md).
The first ticket binds candidate contract identity at the protocol boundary and
uses isolated successor graph fixtures. The second ticket authors descriptors and
stage schemas, then connects real stage replay to complete graph admission.
Unsupported stage dispatch stays refusing between those deliveries. No public
capability or admission bypass is introduced to make an intermediate slice usable.

## Parent acceptance coverage

Ordinals below refer to the original 18 acceptance checkboxes in #80, preserved
unchanged in the parent and in the ticketing snapshot. The exact executed mapping
is recorded in the [#84 evidence index](../../.audit/issue-84-implementation/README.md).

| Criterion | Requirement | Implementation owner | Final proof |
| --- | --- | --- | --- |
| 1 | Actual work before immutable artifacts; complete exact durable graph | #81 protocol admission; #82 real stage closure | #84 |
| 2 | Stable slots and confirmed fresh unique winner across versions | #81 | #84 |
| 3 | Postcommit binding/randomness and original operation lifetime | #81 | #84 |
| 4 | Private begin/accept transitions; exact attempt only | #81 | #84 |
| 5 | One request, exact binding/nonce/imprint; no fallback | #81 | #84 |
| 6 | Strict approved Sigstore profile and explicit operator trust | #81 | #84 |
| 7 | Exact signed interval, U<T, accuracy/leap/timescale refusals | #81 | #84 |
| 8 | Authenticated TUF/approval provenance and historical/current trust distinction | #81 | #84 |
| 9 | Admission-only writer gates and advisory metadata | #82 | #84 |
| 10 | Explicit immutable descriptor and every direct/run/stage binding | #82 | #84 |
| 11 | Cross-version occupancy and first guarded publication transaction | #82 | #84 |
| 12 | All direct/resume vacancy checks and immutable selected closure | #82 | #84 |
| 13 | Exact protected v2 receipt closure; unchanged v1 semantics | #81 | #84 |
| 14 | One receipt attempt, terminal loss and no restart backfill | #81 | #84 |
| 15 | Legacy bytes, identities and reader dispatch | #81 receipts; #82 stages; #83 consumers | #84 |
| 16 | Separate CB01 window/core identity, denominator and F19 lineage | #83 | #84 |
| 17 | Integrated suspension/attack/crash/writer/legacy/consumer matrix | #81–#83 focused tests | #84 |
| 18 | Focused real-code/wire evidence, Ruff/mypy/diff and assumptions | Every child | #84 evidence index |

## Delivery constraints

One stable logical Matchweek selection/completion slot spans all versions. The
founder cutoff remains earliest INCLUDED kickoff minus explicit 21600 seconds.
#73–#78 stay historically complete. Old v1/legacy meanings, canonical bytes,
engine identities and CB01 software commitments remain unchanged.

Production refusal persists under the default configuration after this proof. A
child never authorizes an enabled partial adapter. The final proof does not
authorize live activation, production promotion or #70 fitting.

All implementation and proof use isolated temporary stores, deterministic synthetic
graphs and retained offline wire fixtures. No live stores, live fixture acquisition,
TSA/TUF requests, source activation, operational artifacts or SQL migration are in
scope. Tests run in focused Termux-safe batches, with directly affected historical
regressions rather than the full suite. If storage sufficiency is disproved, stop
and record the design question before any migration.

## Protocol delivery, 2026-10-08

#81 implements the isolated private causal protocol, protected v2 receipt and
terminal crash/restart behavior. [Executed evidence](../../.audit/issue-81-implementation/README.md)
covers 121 protocol/wire tests, 68 directly affected #75/v1 and CB01 trust
regressions, 6 focused manifest regressions, strict typing, lint, formatting
and executable historical/schema compatibility checks.

The protocol delivery used isolated graph fixtures. Real successor graph admission
is supplied by the subsequent #82 delivery below. Authenticated production
activation remains refusing.

## Candidate and writer delivery

#82 implements one immutable unqualified descriptor and propagates its exact
`candidate_contract_digest` through direct and resumed F11–F16 work. Explicit
successor contracts preserve historical canonical bytes and engine identities.
The research owner's shared occupancy predicate checks old and new timing-bearing
associations. Descriptor publication alone leaves the candidate vacant; the first
guarded publication pins it inside its transaction.

The existing #81 owner validates the complete actual successor graph, including
F12 weather attempts and exact SQL-backed health preimages. Its witness transport
and protected receipt semantics are unchanged. Selected and terminal-unqualified
slots permit inspection and exact replay, with no new candidate work.

[Focused execution and review evidence](../../.audit/issue-82-implementation/README.md)
records the writer matrix, affected historical regressions, protocol seams, and
the comparison against pre-#82 canonical artifacts.

## Selected-state consumer delivery

#83 implements explicit causal selection-v2 resolution for CB01, F19 and
evaluation. Downstream qualification binds the indexed selection, exact
completion receipt, candidate contract, F16 engine identity and selection reader;
generic completion, candidate-only, terminal, withdrawn, alternate and unsupported
state cannot supply recommendations. Historical inspection remains labeled as
inspection only.

CB01 core and trust-verifier sources remain byte-for-byte unchanged. The adapter
keeps its strict `T < signed genTime < controlling kickoff` check separate from
the causal witness's proof that the complete selected Matchweek existed before
`T`. The `INCLUDED membership × enabled preference` denominator remains complete
when F16, a receipt, a witness or an enrollment attempt is missing or fails.

F19 binds settlement and corrections to the exact selected F16 manifest, match
result and F14 decision, including the causal qualified origin. Cache reuse checks
the current selected state and receipt before using retained artifacts. Correction
records remain append-only and predecessor-linked; outcomes remain settlement
evidence and do not change frozen recommendation inputs. Evaluation labels causal
selection-v2, corrected historical v1 and legacy per-match cohorts separately.

Focused issue #83 consumer tests cover qualification refusal and success, complete
denominators, CB01 role and chronology separation, F19 exact origin/cache/correction
lineage and cohort dispatch. Directly affected #77 retained-wire and strict-time
regressions, historical F19 replay and F13 engine identity tests passed. Ruff,
strict mypy on the five changed source modules, formatting and `git diff --check`
passed. Retained historical commitments reconstruct with unchanged SHA-256 values:
CB01 core `7de7f617d652329146a3fa3c4f2b9638134dfb3c8d4c931bb35b6a90ac200092`,
CB01 trust `4f75585163f353bc6dfcac1e566ee1502562d9a03b7c6e2b1fefc2800974c9be`,
and method 0.1.0 `1ebeb80f33190f18440d2dcfa5b2526d3907223471f4b2711b7445b0ece8e200`.
The implementation is committed as `c6ef6bc`; production activation remains refusing.

## Integrated successor proof, 2026-10-09

#84 completed the isolated seven-scope Friday–Monday path through F06/F07/F11/F12/
F13/F14/F15/F16, fresh causal selection/completion, CB01, evaluation and F19.
The synthetic RFC3161 event is signed locally and checked by the real profile
verifier. Its `U<T` interval is delivered and receipted after T. Reopen replays
offline, and the same store preserves its v1 selection, receipt, canonical graph
bytes and identities. CB01 retains the complete denominator and independently
asserts `T < signed genTime < kickoff`; F19 corrections preserve exact lineage and
frozen prediction inputs.

[Issue #84 evidence and the ordered 18-criterion #80 mapping](../../.audit/issue-84-implementation/README.md)
record every owning child, runnable test/result, retained-wire run, focused
historical regression, final static checks, assumptions and remaining operational
boundary. The integrated success case passed; retained-wire verification passed
7 focused cases; the affected membership module passed 102 cases; focused timing
and occupancy cases passed 5; Ruff, strict mypy, formatting and diff checks
passed. No production fix or schema change was required. #83 and #84 are complete;
#80's 18 acceptance criteria are checked from this executed evidence. Production
profile activation remains disabled.

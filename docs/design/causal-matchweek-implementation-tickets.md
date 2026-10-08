# Causal Matchweek implementation tickets

[Parent #80](https://github.com/Awisalas/match-vet/issues/80) remains open.
[ADR 0003](../adr/0003-causal-matchweek-selection-witness.md) and the
[accepted architecture](causal-matchweek-selection-witness.md) remain the contract.
This record decomposes implementation without changing that architecture.

| Order | Ticket | Ownership boundary | Blocked by | Current readiness |
| --- | --- | --- | --- | --- |
| 1 | [#81](https://github.com/Awisalas/match-vet/issues/81) | Research/Store selection authority, RFC3161 verification, approved profile and trust provenance, protected v2 completion/replay | None | Completed |
| 2 | [#82](https://github.com/Awisalas/match-vet/issues/82) | Immutable candidate descriptor, stage schemas and all direct/resume writer contracts, cross-version occupancy | #81 (closed) | ready-for-agent |
| 3 | [#83](https://github.com/Awisalas/match-vet/issues/83) | Selected-state consumers, CB01 adapter/denominator, F19 and report/evaluation/legacy dispatch | #82 | Blocked |
| 4 | [#84](https://github.com/Awisalas/match-vet/issues/84) | Integrated seven-league successor proof and complete parent acceptance evidence | #83 | Blocked |

All four are native sub-issues. Native blocking edges form
`#81 → #82 → #83 → #84 → #80`. Only #82 has `ready-for-agent`; #81 is complete.
The parent is blocked by #84 and has no implementation readiness label.

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
unchanged in the parent and in the ticketing snapshot. These are planned evidence
obligations, not completed successor acceptance.

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

Production refusal persists until all children and the entire #80 acceptance proof
pass. A child never authorizes an enabled partial adapter. Final proof also does
not authorize live activation, production promotion or #70 fitting.

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

#82 is the next unblocked child and remains open and unstarted. Real successor
admission and authenticated activation still refuse; this delivery does not
qualify a production Matchweek or complete any original parent acceptance proof.
#80, #83 and #84 remain open.

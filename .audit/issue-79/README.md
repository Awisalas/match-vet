# Issue 79 design and isolated proof

Decision: prospective causal selection witness under ADR 0003, using the Sigstore
RFC3161 event bound and an explicit trusted-authority policy-compliance premise.
No production timing mechanism is implemented or activated.

## Records

- `grounding.md` traces actual writer, graph, fresh commit, receipt, replay and CB01 paths.
- `candidate-a.md` and `candidate-b.md` compare local causal witness and remote graph registry.
- `rubric.md`, `review-prompt.md`, `review-*.md`, and `synthesis.md` capture independent judgment.
- `decisions.tsv` is the canonical append-only decision trail.
- `sources/identities.json` pins primary policy/source snapshots by SHA-256 and exact revision.
- `proof.py` and `proof-result.json` are rerunnable isolated experiments.
- `historical-tests*.txt` record the initial import failure and deliberately interrupted broad run; `focused-tests.txt` records the interrupted focused historical rerun; `cb01-trust-tests.txt` records five passing retained-trust tests.

## Run the proof

From the repository root:

```sh
PYTHONPATH=src:tests python .audit/issue-79/proof.py
```

The script makes no network request. It uses only temporary SQLite/object roots
and the existing non-live diagnostic RFC3161 bundle. It does not open configured
live stores. The proof deliberately separates three kinds of evidence:

1. A logical causal model checks 5040 predecessor permutations and 5120 synthetic
   pause/error schedules. Only an honest bounded event strictly before T can
   qualify. Late computation/commit/request and bound equality fail. Delivery
   may occur after T. The old return-time suspension contradiction remains.
   The synthetic two-unit interval is a model premise, not a production allowance.
2. OpenSSL verifies the real retained token, rejects changed imprint and another
   request nonce, and exposes that generic verification accepts a no-nonce request.
   Successor application verification must explicitly require the matching nonce.
   The token's signed one-second accuracy gives its exact diagnostic event upper
   endpoint. This token cannot qualify any operational Matchweek.
3. Shipped Store/ArtifactStore round-trip a four-reference generic schema-1 manifest
   containing synthetic selection/provenance and real diagnostic request/response
   bytes. Comparing sqlite_master before/after proves no schema mutation is needed
   for representation. This does not implement protected v2 domain authority.

The broad historical regression run was interrupted after 11 passing cases in
581.77 seconds. It is not claimed as a full-suite pass. The focused integrated, selected-writer and concurrent-selector rerun was
interrupted during setup after 1021.15 seconds with no completed tests; it is not
a pass. Those unchanged historical integration cases were not needed to claim
a new runtime in this design-only task. The five retained CB01 trust tests then
passed in 26.65 seconds, recorded in `cb01-trust-tests.txt`.

The first storage attempt correctly failed because its artifact refs were unsorted.
The corrected proof applies the existing digest order and passes. No repository
implementation changed to make it pass.

## Blast radius and proof limits

The load-bearing fact is immutable complete selection closure preceding fresh
commit and the remote request. That fact is enforced by existing lineage/durability/
reserved-slot owners under their trusted local premises. Existing real-code tests
exercise the v1 owner; the new logical model explores the event proof. Neither is
misrepresented as a running v2 writer or remote accuracy qualification.

The storage and retained crypto facts reach blast-radius level 4, executable
shipped-code checks. A new protected v2 receipt path, every prospective writer
version and current public deployment's one-second compliance are not executable
production facts here. The first two belong to the corrective issue's tests;
the third is an explicit accepted authority trust premise, not a measured claim.

Real risks requiring successor tests are premature nonce construction, generic
nonce omission, late/unversioned candidate qualification, lazy graph discovery,
receipt reference widening, altered F13 engine identities, old reader acceptance,
current-time TUF bootstrap, callback reentrancy, receipt-loss backfill and stable-slot
uniqueness across versions. CB01's core source/software identity must remain intact.
ADR/design source references and grounding name exact affected locations.

Cleared at the design boundary: arbitrary delivery suspension does not change a
prior signed event; no elapsed-rate or final-return allowance is needed. Generic
schema representation fits without migration. A request event after a trusted
fresh commit with U<T implies commit<T. Version-independent occupied slots prevent
an alternate selection. Historical #73/#74–#78 remain complete and unmodified.

Before activation, implement and run all version-specific successor cases in the
corrective issue. Keep production refusal meanwhile. This task acquires no live
fixtures, changes no policy values, and does not begin #70 fitting.

Corrective issue: [#80](https://github.com/Awisalas/match-vet/issues/80), ready-for-agent,
native child/dependent of #79. No implementation work was started.

The pinned upstream TSA policy contains trailing spaces. The local source-only
.gitattributes preserves its exact bytes for hash verification; authored records
still receive normal whitespace checks.

Design/research/proof commit pushed: `6a9edebdc9ce1a2feede2307b43c4a04c9d9f485`.
Issue #79 is CLOSED with completed acceptance. Issue #80 remains OPEN and
ready-for-agent after its native decision dependency closed. Production
implementation was not started. Final publication/trail closure is committed
separately so it does not invent a self-referential design SHA.

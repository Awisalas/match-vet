# Issue #82 evidence

Base: `a65c033160dd1b6e50a5bf69e9c7e0aecb4e8bf0` on `main`.
Scope: [#82](https://github.com/Awisalas/match-vet/issues/82), implementing
[ADR0003](../../docs/adr/0003-causal-matchweek-selection-witness.md) and the
[accepted design](../../docs/design/causal-matchweek-selection-witness.md).

## Delivered behavior

`CausalCandidateContract` is immutable identity, with exact logical Matchweek,
F06, corrected F07/common T, profile, policy, engine, and witness-profile bindings.
It carries no qualification. F15 run identity and every direct/resumed F11–F16
writer carry the same explicit `candidate_contract_digest`.

The owner checks all supported historical and successor timing-bearing
associations. Descriptor and reusable raw-source publication do not occupy a
candidate. The first guarded run, attempt, evidence, or input publication pins
it inside the existing transaction. Old partial work, ambiguous associations,
changed resume context, and competing descriptors refuse.

Successor schemas are F11 evidence 4, F12 attempt 2, F13 input/result 3,
F14 input/result 3, and F16 child/manifest 2. F15 has a distinct causal run contract
and a protected identity artifact. Historical schemas and engine/adapter identities
remain explicit. Selected and terminal-unqualified slots allow exact replay and
inspection; all new candidate mutation paths refuse. Stored reader context cannot
supply missing writer context.

Actual F15/F16 output reaches #81 admission, including F12 request/response/attempt
lineage, F13 history/calibration dependencies, and exact protected F05/F09 health
preimages. The selection owner's reference set equals the validated transitive
graph. Witness transport, private authority, and protected receipt semantics are
unchanged. CB01/F19 consumers remain unsupported for causal selection until #83.

## Execution

Every fixture store is temporary and synthetic. Test commands set
`PYTHONPATH=tests/no_network:src:tests`, enforcing offline execution. No full suite,
live store, fixture acquisition, TSA/TUF request, SQL migration, production
activation, integrated #84 proof, or #70 fitting was performed.

| Boundary | Evidence |
| --- | --- |
| #82 writer matrix | [Matrix output](writer-final-02.txt), [52 collected cases](writer-cases.txt) |
| Corrected F14 exact replay assertion | [Targeted pytest pass](decision-replay.txt) |
| F12 constructor context and first-attempt replay | [Targeted pytest pass](f12-context.txt) |
| Exact F11 media/schema and history dispatch | [Real-graph replay pass](media-dispatch.txt) |
| Fresh F15 and legacy publication guards | [3 pytest passes](guard-regressions.txt) |
| Missing selected writer context before replay | [1 pytest pass](selected-context.txt) |
| Qualified exact replay and mutation refusal | [Real selected-graph pass](qualified-replay.txt) |
| Terminal exact replay and mutation refusal | [Real selected-graph pass](terminal-replay.txt) |
| Read-only retained history without writer authority | [Minimized failing regression](history-read-only-red.txt), [2 focused passes](history-read-only-green.txt) |
| Complete graph replay through a query-only connection | [Fresh real-graph regression](read-only-graph.txt) |
| Directly affected #76 cases and historical engine/attempt identities | [11 initial passes](historical-tests.txt), [16 fresh passes](historical-tests-02.txt) |
| #81 protocol seams and legacy F11 | [5 passes and retry regression](compatibility-seams.txt), [corrected retry pass](compatibility-seams-02.txt) |
| Historical canonical bytes and software/engine identities | [Executed comparison](compatibility-proof.txt) |
| Strict mypy | [21 affected files](mypy.txt), [changed seams](mypy-final-seam.txt), [read-only fix](mypy-read-only.txt) |
| Ruff and formatting | [Lint](ruff.txt), [24-file formatting check](format.txt) |

The original writer matrix reported four test failures, covered by the targeted
reruns above: an overly strict F14 replay assertion, an incorrect F12 exception
class expectation, and attempted modification of immutable metadata in the
malformed-media fixture, plus retained-history replay constructing a writable
schedule recorder. The recorder still refuses read-only stores; the extracted
query-only reader preserves the exact SQL, ordering, revision filter, and decoding.
The final tests preserve those immutable store rules.
The selected-context case and real selected-state reruns cover the later shared
lookup guard. No failed run is counted as a complete pass.

Final writer coverage is 52 distinct cases: 46 passes in the original 50-case
matrix, four successful targeted reruns, and the two added context/reader
regressions. Both qualified and terminal selected-state cases also pass against
the actual graph with the latest context guard. The complete graph passes through
a query-only connection after the reader fix.

The retained-history regression first failed at the public reader boundary, then
passed with both league history and a persisted cup schedule event under SQLite
query-only mode. The writer constructor remains refused. The added cup assertion
checks its identity and provenance rather than assuming the recorder preserves
implicit cutoff eligibility instead of making it explicit.

The first historical batch stopped at an intentional KeyboardInterrupt after
11 successful cases. The guard fix and fresh batch cover all remaining #76 cases,
including that interruption regression, plus the two historical identity checks.
The legacy F11 publication-hook regression was also fixed and rerun successfully.

`compatibility-proof.py` archives the exact base source and executes both versions
against copies of one offline store. All 30 canonical artifact byte strings,
F11/F13/F14/F16 hashes, F15 inputs, and the historical F13 engine identity match.
This is an executed comparison, not a newly generated expected-value snapshot.

`replay-fixture-regressions.py` takes only an isolated `issue82-*` fixture root,
copies its immutable objects, and backs up its SQLite state into a fresh temporary
store. It validates the actual graph through `_admit_v2`, then calls the changed
tests. Selected-state checks use the existing synthetic approval/event seam;
transport raises if any replay attempts another witness. This supplies no new
cryptographic or integrated proof claim.

## Review and tracking

[Interrogate, code review, diagnosis, and executable blast-radius findings](review.md)
record the resolved issues and one nonblocking contract-table maintenance concern.
Git diff checks confirm that #81's selection/witness/trust protocol files and the
Store/ArtifactStore implementation are unchanged.

The repository ticket map records #82 completion and #83 readiness. #83 remains
unstarted. #80 and #84 remain open, and the original parent acceptance checkboxes
remain reserved for #84's integrated proof.

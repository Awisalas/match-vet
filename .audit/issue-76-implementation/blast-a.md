# Independent blast-radius review A

Reviewed issue #76 work against `6470abf`. This review reads the changing working tree, so remediations below need final regression results. No production or test code was edited, no live SQLite store was opened, and no network data or full suite was acquired.

## What changed

F11 through F16 consult the #75 owner at public prospective writer methods. Corrected publication uses a guarded ArtifactStore. Selected branches resolve the indexed exact F16 winner before candidate discovery and return its references. Default F15/F16 creation now requires the corrected F07 rule. Legacy research creation has explicit dispatch. Existing exact readers, schemas and F13 engine/research-adapter identities stay intact.

## The safety fact and its proof

The shared authority closes corrected direct writer entry at cutoff equality, without relying on orchestration. I executed `F11EvidenceRepository.build` at T and `F16MatchweekProcessor.process_phase` for a missing decision phase at T through the existing public tests. Both refused and left the catalog unchanged.

This reached step 4, execution of real code. `.audit/issue-76-implementation/blast-a-proof-output.txt` retains the command and output: `2 passed in 46.94s`. The public method refusal is the proof. The public catalog assertions establish that refusal did not publish a candidate.

Selected/reopen replay and historical coexistence remain unproven by this reviewer. Root's completed focused results must establish those broader facts. The duplicate selected-chain and legacy-start experiments were interrupted for CPU contention. They yielded no safety evidence.

## Risks requiring closure

1. Reentry can defeat a scan performed only before publication. `ModelContractRepository.build` checks for an existing corrected result at `src/matchvet/f13.py:305`, then consumes a caller iterable at line 314. A history generator can call a second public build while the outer build is suspended. Both can then publish different inputs/results for the same exact evidence/cutoff. F11 has the same possibility through a custom weather client, and F14 checks existing decision inputs before publication. This is a step 3 source trace, not an executed race proof. The likelihood is low for current deterministic callers but material for callback integrations; the cost is two frozen candidate states. Recheck the exact F11 request, F13 result/input, F14 bundle and F16 proposal identity inside publication transactions, or refuse same-Store reentry while a candidate writer owns the operation. Test through a public generator/client seam.

   Separate writers are already excluded by `flock` at `src/matchvet/store.py:3245`; the default SQLite connection at line 5120 also prevents cross-thread connection use. These clear ordinary parallel writer processes. They do not clear same-thread callbacks or iterable reentry.

2. Historical read-only reporting must dispatch independently of a corrected selection for the same logical Matchweek. Reviewer B identified the path from `AnalyzeMatchweek.inspect` to `completed_artifact_identities`, which currently resolves `selected_for_boundary` for legacy requests. A valid old freeze/policy may therefore be rejected because the corrected winner differs. Exact `replay_manifest` itself remains unchanged. See `src/matchvet/f15.py:145`, `src/matchvet/f16.py:222`, and reviewer B's report. This is a step 3 trace, not my execution proof. Add a coexistence regression where legacy inspection and F16 identity reporting still return old exact state after a corrected selection occupies the same logical slot.

## Findings addressed during review

- Publication originally checked time only before SQLite commit. The new check at `src/matchvet/artifacts.py:595` refuses acknowledgement after a commit crosses T. Physical objects/catalog rows may remain after refusal; they must never become selected recommendation lineage. Root's commit-crossing and reopen tests are required to prove that handling.
- Prospective F15/F16 originally allowed the old per-match policy under the unavailable clock. Default refusal now exists at `src/matchvet/f15.py:123` and `src/matchvet/f16.py:156`. Explicit legacy research does not authorize a corrected selection. Verify default refusal and legacy exact replay separately.

## Cleared by source inspection

- F11 build and build-or-replay, F12 publish, F13 build and retained-history discovery, F14 build and build-or-replay, F15 start/resume, and F16 process_phase all invoke the shared authority before corrected prospective work. Entry refusal and direct F16 missing-phase refusal have executable proof above.
- F15 selected resume returns inspection before entering the coordinator. Each unselected F16 phase also checks the gate, so a resumed missing writer cannot rely only on the initial F15 authorization. Broader resume execution evidence remains pending.
- F13 discovery checks the gate before mutable source-catalog enumeration. `retain_history` is an unbound upstream/audit source writer. It cannot alter frozen model inputs through either corrected build seam once those gates close. Root is adding a later-catalog selected-input test to prove this distinction.
- Exact selected F11/F13/F14 paths compare their request, evidence/cutoff or decision bundle with selected F16 references. F16 also compares selected profile and decision policy. There is no latest-candidate replacement rule.
- `RESEARCH_ADAPTER_VERSION` remains `f13-t09-history-context-v2` at `src/matchvet/f13.py:53`; the engine contract, media types, schemas and exact reader bodies retain their historical dispatch. Golden and byte compatibility checks still need root's regression results.
- The owner still installs `_UnavailableClock` by default at `src/matchvet/matchweek_research.py:132`; `_observe` requires explicit trusted UTC confidence at line 138. The weather recorder's UTC fallback is existing standalone audit/legacy behavior. Corrected F11 supplies the shared authority callback. No production wall-clock fallback became trusted.

## Before completion

Close the two risks above with public-seam evidence, then rerun the focused writer, selected/reopen and directly affected historical regressions. Do not treat the two narrow tests as proof of every acceptance criterion. The final identity/publication changes need a final diff review.

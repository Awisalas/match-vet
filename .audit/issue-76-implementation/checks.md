# Issue 76 verification

All research uses isolated temporary stores and deterministic local fixtures. No live store, current fixture acquisition, operational artifact, TSA or Sigstore request, or full suite was used.

## Commands and evidence

| Check | Evidence | State |
| --- | --- | --- |
| Initial full #76 focused run | `focused-all-final.txt`, `partial-weather-final.txt`, `red-audit-catalog-actual.txt` | 23 passed; two fixture errors corrected; partial weather rerun passed; selected audit true red reproduced |
| Final-code #76 focused run, split into 24 cases and the late-audit case | `focused-scope-final.txt`, `green-audit-catalog-final.txt` | 25 passed on final code: 24-case run plus the separate late-audit case |
| Post-scope #75 selection, exact replay, corruption, unacknowledged selection and legacy-policy checks | `f75-scope-final.txt` | 16 passed, 46 deselected |
| Post-scope historical F11 weather retry and F13 observed-context readers | `legacy-readers-scope-final.txt` | 2 passed |
| F11, F12, F13, F14 and F15 regression modules | `regressions-01.txt` and `legacy-fault-hook-final.txt` | 40 passed in initial run; its sole failure passed after the publisher fix |
| Affected #75 selection, cutoff, clock, replay, membership and proposal regressions | `f75-regressions-final.txt` and `f75-proposals-final.txt` | 16 passed; proposal fixture retention-class errors corrected; all five rerun cases passed |
| F07 historical cutoff digest and F13 deterministic identity checks | `identities-final.txt` | 2 passed |
| Archived pre-76 source creates legacy graph; current readers reopen it | `legacy-proof.py`, `legacy-proof-final.txt`, `legacy-scope-final.txt`, `legacy-proof-result.json` | Final rerun passed, 30 historical artifacts unchanged and zero catalog writes |
| Ruff check on changed Python and retained proof | `ruff-final.txt`, `ruff-scope-final.txt`, `ruff-delivery.txt` | Passed |
| Ruff format check on changed Python and retained proof | `format-final.txt`, `format-scope-final.txt`, `format-delivery.txt` | Passed |
| Strict mypy on affected source and tests | `mypy-final.txt`, `mypy-scope-final.txt`, `mypy-delivery.txt` | Passed, final 15 files |
| `git diff --check` | `diff-check-final.txt`, `diff-check-scope-final.txt`, `diff-check-delivery.txt` | Passed |

## Earlier attempts

The red-seam logs retain failures that preceded implementation. `red-07.txt` reproduces the admitted alternate profile across two INCLUDED matches. `focused-02.txt` reproduces the selected F12 domain/artifact digest mismatch. Both code paths were corrected before the final focused run.

Several early failures came from fixtures, rather than missing enforcement. Their output remains visible. `red-06.txt` actually records a passing corrected chain and is not claimed as a failing red test. Interrupted broad blast-radius experiments were inconclusive. The reviewers' narrow direct-writer proofs passed; they are not substituted for the final focused run.

The initial legacy weather retry failure came from replacing the instance publisher and bypassing its injected interruption. Local operation publishers preserve the original instance; the exact failed test passed on the fix. Latest numerical model/replay code and historical contract identities are unchanged.

The selected F12 comparison uses SHA-256 of canonical retained bytes, matching #75 artifact references. The distinct domain digest remains unchanged. No schema or payload redesign was needed.

`focused-final.txt` reached all selected replay and refusal calls, then failed a case-sensitive error-message assertion. The selected profile refused correctly; the expression was corrected before the final complete run.

A final replay review found F12 lookup depending on later audit catalog entries. The public-seam red reproduced the selected replay failure in `red-audit-catalog-actual.txt`. The transient frozen-catalog fix is applied; post-fix tool checks and archived legacy proof passed. Affected weather-reader reruns passed. Selected-audit replay passed, including an idempotent reseal. #75 reruns passed. All remaining 24 final-code focused cases passed. Together with the separate late-audit case, all 25 focused cases passed on the final code. Commit, push and issue closure follow this verification checkpoint.

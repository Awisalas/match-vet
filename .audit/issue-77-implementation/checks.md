# Issue 77 verification

Scope is issue 77 only. All execution used fresh temporary stores, deterministic
synthetic research inputs and retained offline witness fixtures. Test runners
deny socket connections. Neither live SQLite store was opened. No full suite,
fixture acquisition, operational publication or live timestamp request was run.

| Check | Evidence | Result |
| --- | --- | --- |
| Focused CB01, denominator, cohort and chronology pytest | `run-retained-focused.py`, `focused-nodeids.txt`, `focused-split-final.txt` | 47 passed, one deselected; the F19 outcome integration passed separately |
| F19 selected settlement/correction and frozen outcome isolation | `run-slate-slice.py`, `f19-outcomes-final.txt` | Passed, the remaining focused case |
| Directly affected selection/writer regressions | `selection-regressions-01.txt` | 11 passed |
| Historical CB01 and legacy F19 regressions | `legacy-regressions-02.txt` | 4 passed |
| Literal historical software/method hashes and retained signed token boundaries | `history-final.txt` | 7 passed; also included in the 47-case focused command |
| Archived pre-77 CB01 reconstruction | `historical-proof.py`, `historical-proof-final.txt`, `historical-proof-result.json` | 53 exact retained artifacts, two enrollment records, zero catalog changes, zero replay publication and network calls |
| Strict mypy on every changed Python file | `mypy-delivery.txt` | 12 files passed |
| Ruff on changed Python | `ruff-delivery.txt` | Passed |
| Ruff formatting check | `format-delivery.txt` | 12 files formatted |
| Whitespace integrity | `diff-check-final.txt` | Staged and unstaged diff checks passed after complete audit staging |

`sh .audit/issue-77-implementation/check-static.sh` records the exact static-check
commands and Python file list. It uses the previously retained Ruff binary,
strict mypy, formatting, both diff checks and the historical SHA256 comparison.

The two final runners accept only a retained synthetic fixture under the system
temporary directory. They copy it into fresh temporary stores, replay the complete
selected graph before use, and call the public repository functions. They replace
fixture construction, not domain validators.

Earlier interrupted runs are retained as evidence, not counted as terminal
success. `focused-final.txt` printed 39 progress marks before exit 137, whose cause
was not established. The split rerun repeats the complete collected acceptance
set. `focused-01.txt` exposed an incorrect test assertion that failed historical
BatchResult objects contain denominator rows. That assertion was corrected:
failed results retain the historical empty rows, while independent evaluation
still counts all four INCLUDED/preference pairs. `focused-02.txt` was interrupted
to avoid continuing with an older imported test version.

The recovery-mode experiment reached the existing workload reader's healthy Store
gate. Recovery-mode evaluation is not claimed or added. The successful inspection
proof instead forbids Store transactions and base artifact publication and checks
that a missing enrollment artifact is refused without repair.

Adversarial findings and their disposition are in `interrogate-review.md`.
Executable blast-radius proofs are in `blast-radius.md`. Only GPT models were
available, so the review has model/generation diversity without provider diversity.
Numerical profiles from issue 70 remain explicitly unresolved.

Six raw captures contain intentional whitespace from pytest tracebacks or nested
patch context: `admission-diff.patch`, `green-06.txt`, `red-04.txt`, `red-05.txt`,
`red-06.txt` and `review-diff.patch`. Their exact bytes are retained in
`raw-evidence.tar.gz`, rather than changing evidence to satisfy whitespace checks.
Run `tar -xzf .audit/issue-77-implementation/raw-evidence.tar.gz` from the repository
root to restore these task-local evidence paths. Every archived member was compared
byte-for-byte with its original capture before staging. Original local captures
remain untouched; Python and documentation whitespace checks remain enabled.

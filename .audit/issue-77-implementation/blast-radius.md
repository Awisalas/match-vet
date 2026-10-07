# Issue 77 blast radius

The safety fact is that corrected admission joins only the immutable selected
graph, while counting F06/Profile rows before any join. Later facts can append to
F19/evaluation but cannot become selected recommendation inputs. Legacy policy
dispatch retains its original canonical CB01 core and trust software identities.

| Invariant | Executable evidence | Status |
| --- | --- | --- |
| Historical CB01 commitments remain reconstructible | `historical-proof.py`, `historical-proof-final.txt`, `historical-proof-result.json`; archived `6470abf` produces 53 artifacts/two records, current readers reconstruct all bytes with publication forbidden | Passed, real code (level 4) |
| Historical source identities and released method remain unchanged | `historical-sha256-final.txt`, `history-final.txt`; three literal SHA256 checks | Passed, level 4 |
| Full denominator survives missing F16, cutoff/failure artifacts, failed witnesses and unattempted preferences | `focused-split-final.txt`, public-seam tests in `test_issue77.py`; independent count and refusal-attached count; complete 2 × 2 slate | Passed, level 4 |
| Legacy and corrected policies/selections do not mix | `focused-split-final.txt`, exact selected failure/receipt replay; forged anchor/preference/verification tests; legacy equal-T and missing legacy cutoff tests | Passed, level 4 |
| Signed time rule remains strict and fixture-specific | `history-final.txt` verifies retained real CMS signature at cutoff/kickoff equality and 100ns boundaries; eight corrected fixture-window cases in `focused-split-final.txt` | Passed, level 4 |
| F19 remains append-only against exact selected decision/manifest | Legacy F19 regression, selected cache/unselected/alternate manifest tests, predecessor correction test; second Store writer refused | Passed, level 4 |
| Post-cutoff outcomes cannot alter frozen F11/F13/F14 or later-week predictions | `f19-outcomes-final.txt`, isolated `test_f19_outcomes_append_without_changing_frozen_inputs`, selected writer/late-catalog regressions | Passed, level 4 |
| Shared origin and numerical limits remain explicit | `shared-origin-final.txt`, chronology 0.2.0, literal released method hash | Shared-origin test passed; numerical entries remain INCONCLUSIVE |

The review found and fixed two risks beyond the initial adapter diff: failed
attempts could leak across cohort identities, and historical reconstruction could
write staging objects while inspecting receipts. The retained reader now verifies
canonical complete batches/failures and refuses would-be publications that are
not already retained. Failed retries keep their earlier failure history.

The proposed F19 concurrent-writer race was cleared by running the supported Store
ownership refusal test and inspecting its exclusive lock; no settlement/schema
redesign was introduced. Inspection's no-write proof forbids Store transactions
and ArtifactStore publication after setup. It does not claim recovery-mode support,
which the existing selected workload reader does not provide.

These are isolated offline proofs, not live operational validation (level 5).
Neither live SQLite store was opened; no current fixtures, research network data
or new timestamp was acquired. Production trusted UTC availability, #70 numerical
gaps and #78 remain outside this delivery. Final command outcomes are recorded in
`checks.md`.

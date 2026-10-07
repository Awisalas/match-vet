# Spec review

Reviewed working changes from `6470abf2d1f8df4ebe01d2b9f110c5ad01e2e483` through public F11-F16 seams and the shared #75 owner. No tests were executed by this reviewer; root runs the focused groups.

No unresolved static spec findings remain after the fixes below.

- The shared candidate-owner scan includes F12 cutoff-bound attempts and retained F15 run contracts. Interrupted acquisitions and partial runs pin the exact freeze/policy before full F11 retention (`src/matchvet/matchweek_research.py:322`). Stored run inputs are parsed through their existing contract reader and checked against the aggregate digest.
- F11/F13/F14/F16 publishers are captured locally for their live operation. F13 passes its publisher through evaluation and retention, and F16 passes its publisher into complete-slate assembly. Same-instance reentry cannot replace another operation's guard. Historical and upstream publication remain unbound.
- F15 request construction enforces unique IDs, and `_inputs` explicitly checks INCLUDED cardinality.
- F14 scans retained input bundles across the exact corrected freeze/policy. Profile and full T15 policy must match across every member, including input-only partial state; each cutoff also pins its exact bundle (`src/matchvet/f14.py:367`). Root reproduced the original two-member failure in `.audit/issue-76-implementation/red-07.txt`.
- The shared `require_candidate_contract` gate now runs before F15 start/resume, every prospective F16 phase, and F14 assembly. It compares prospective profile/policy with retained F15 contracts and partial F14 bundles. Captured publication guards repeat the contract check. This closes the entry-time alternate-request concern. Root's `.audit/issue-76-implementation/f15-entry-final.txt` records two passing public-seam cases covering partial-run contract variants and a missing writer phase after T.

No schema migration, global engine identity change, production clock fallback, #77 work, or #78 work appeared in the reviewed implementation. Selected dispatch resolves exact retained references; historical replay remains read-only. All final acceptance, regression and tool checks remain the root agent's responsibility.

## Final selected-catalog delta

Reviewed the added Store catalog scope, selection admission/replay scope, and cutoff-bound F12 reads without running tests. No new static spec finding remains.

The scope changes discovery only while selected graph verification or an exact cutoff-bound F12 read is active. Its context manager restores the prior scope on exit, rejects incompatible nested scopes, and Store refuses publication while a selected scope is active (`src/matchvet/store.py:4340`, `:4398`, `:4510`). No SQLite schema, retained bytes, or artifact identity changes were introduced.

Selection replay supplies its recorded reference closure explicitly to `_admit`. Fresh admissions remain unscoped, and active initial graph capture does not acquire an indexed scope, preserving the earlier broad closure behavior (`src/matchvet/matchweek_research.py:159`, `:472`, `:563`). Thus post-selection audit artifacts cannot alter F12 catalog discovery or expand the selected closure, while old qualifying manifests retain their recorded closure.

F11/F13/F14 now pass the exact cutoff when resolving F12 references. F12 verifies that the resolved attempt belongs to that cutoff. Its selected idempotent publication path also requires the exact F11 attempt tuple, rather than accepting an incidental attempt merely because an earlier broad selection closure contains its digest (`src/matchvet/f12.py:239`, `:364`). Unrelated later audit attempts remain available through the ordinary unscoped read API and cannot become selected recommendation references.

Root's late-audit red reproduction is recorded in `.audit/issue-76-implementation/red-audit-catalog-actual.txt`. Green late-audit, #75, legacy and tool results are still pending with root; this delta review is a static conclusion only.

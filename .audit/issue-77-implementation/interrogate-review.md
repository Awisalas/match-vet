# Issue 77 adversarial review

Intent: corrected CB01 and evaluation qualify only the exact selected Matchweek
graph; count the complete F06/Profile denominator before joining evidence; retain
exact legacy commitments; bind append-only F19 to selected decisions; freeze one
corrected forecast origin without choosing #70 numerical profiles.

Reviewers used the same prompt and rubric in `review-prompt.md`, current files,
and the diff from task baseline `ed345eb`.

| Reviewer | Model | Final verdict |
| --- | --- | --- |
| A | gpt-6-astra, high | No findings |
| B | gpt-5.6-sol, max | No findings after fixes |
| C | gpt-6-sol, xhigh | Failure attribution fixed; concurrency finding withdrawn |
| D | gpt-6.1-sol, xhigh | No findings after fixes |

Only GPT models were exposed by this harness. Claude and Grok defaults could not
be used; these supported models supplied generation and model diversity, not
provider diversity. No skill-update PR was opened because the user limited work
to #77.

## Act on

- C: a missing legacy cutoff allowed its failure into corrected attempted rows.
  Unknown policy identities now remain outside cohort failure attribution.
- B: failures from an unselected F16 could join through policy alone. Attribution
  now requires the selected manifest and canonical replay of the complete batch.
- B: enrollment projection could drop the first failed attempt after a successful
  retry. The enrolled row now retains the annotated failure history.
- B: schema-valid forged membership, shortened batch/preferences, and successful
  verification described as failure could enter failure diagnostics. The new
  retained repository calls unchanged core batch/failure reconstruction validators
  and verifies the complete enabled-preference product and exact attempt/result.
- D: existing receipt replay republishes reconstructed artifacts. A retained
  artifact adapter compares already-retained metadata and bytes, refuses missing
  objects, and performs no publication or repair.
- D, lead: explicit admission refusal could hide the independently built
  denominator from the caller. An independent inspection method and admission
  error's `denominator` retain the complete view.
- C: unreadable failures from unrelated cohorts could alter corrected row reasons.
  Unattributed catalog uncertainty is now a separate field and does not change rows.

## Consider

No unresolved correctness finding. Final execution evidence is listed in
`checks.md`; reviewer source inspection alone is not a passing-test claim.

## Noted

The retained inspection adapter prevents writes. Existing selected F16/workload
readers still require healthy Store mode; this task does not add recovery-mode
support. The proof forbids all artifact publication and Store transactions after
test setup instead of claiming unsupported recovery-mode replay.

## Dismissed

- C withdrew the proposed concurrent F19 correction race: `open_store` holds a
  nonblocking exclusive writer lock, the SQLite connection is bound to one thread,
  and Store refuses cross-process use. A second supported writer cannot reach the
  claimed race. The focused F19 test exercises that refusal.
- The preexisting change to `.audit/cb01-implementation/trail-review.md` is outside
  this task and excluded from the commit. No historical audit evidence is rewritten.

## Agreement map

B and C independently identified failure-cohort joins as the principal risk.
D identified replay's publication side effects. A found no concrete safety fault.
The lead retained these findings, added exact batch-entry comparison, and rejected
an unnecessary F19 publication redesign after checking Store ownership.

## Separate code-review axes

Standards (gpt-6-astra): zero documented breaches; one heuristic concern about
positional enrollment tuples. Direct DenominatorRow projections removed the tuple
contract; failure history is explicitly carried into the projection.

Spec (gpt-6-sol): unknown failure catalog attribution was corrected. The unrelated
historical audit modification was preexisting and excluded. No remaining unmet
criterion was identified by source review; acceptance still requires execution.

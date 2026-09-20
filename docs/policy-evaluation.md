# Chronological policy evaluation

T18 evaluates research-only Selection Policy candidates against frozen historical information
states. It does not promote a policy, modify T15 Vetting, or write production state.

Run an offline evaluation with:

```text
.venv/bin/matchvet policy validate \
  --input /private/policy-evaluation-input.json \
  --output /private/policy-evaluation-artifact.json \
  --checkpoint /private/policy-evaluation-checkpoint.json \
  --json
```

Add `--resume` only with the same checkpoint, corpus, candidate definitions, configuration, and
seed. A changed digest refuses resume. The command reads local JSON and makes no network request.

## Input contract

The top-level schema is `matchvet.policy-evaluation-input.v1`. It contains `config`, `candidates`,
and `observations`.

`config` declares three half-open UTC ranges named `DEVELOPMENT`, `VALIDATION`, and `EVALUATION`.
They must be ordered and non-overlapping. Gaps are permitted and appear in the artifact as
`OUTSIDE_DECLARED_PERIODS` exclusions. `split_method` must be `CHRONOLOGICAL`. The configuration
also records rolling-origin Matchweek counts, seed, calibration-bin edges, candidate-selection
metric and direction, subgroup minimum effective samples, evaluation minimum recommendations,
and acceptance criteria. T18 supplies no acceptance threshold or minimum sample when either is
missing.

Each candidate contains its research-only version and digest, the latest Development outcome it
used, its freeze time, parameters, optional parameters learned in each nested fold, and digests of
Final Evaluation windows already inspected. Candidate development data cannot extend beyond the
Development Period. The candidate is frozen only after Validation ends and no later than the start
of Final Evaluation.

Each observation is one frozen preference evaluation and later Settlement Result. It records:

- Match, Matchweek, kickoff, Research Cutoff, prediction, model-fit, training-data-end, and
  outcome-known timestamps.
- League, Preference Family, exact line, preference ID, and correlation group.
- Policy, model, calibration, baseline, evidence, and input identities and SHA-256 digests.
- Frozen Membership Manifest and controlling Fixture Revision payloads with verified SHA-256
  digests.
- Estimated and Conservative Probability, the full WIN/PUSH/LOSS Settlement Distribution when a
  line can PUSH, uncertainty bounds and declared nominal coverage where available, optional width,
  Model Agreement, baseline, gates, Selection Strength, and components. A PUSH-capable catalog
  preference cannot omit its full distribution.
- Recommendation state and WIN, LOSS, PUSH, or VOID settlement.
- Every historical input name and its observation timestamp.

Every row in one Matchweek must use the same Matchweek start and Research Cutoff. Every historical
input timestamp must be at or before that cutoff. Membership and revision content must match their
digests, and the revision identity and kickoff must match the evaluated fixture. A future lineup,
news item, result, correction, schedule revision, feature, or other post-cutoff value fails
the evaluation. The evaluator never substitutes a current fixture pointer or corrected future
state. Every Final Evaluation row must be explicitly `UNSEEN`; a row marked for Development,
Validation, or prior inspection fails. The inspection digest binds the exact Final Evaluation time
window, so changing corpus content cannot make an inspected period unseen again.

Validation chooses the candidate using the declared metric and direction. Final Evaluation may
contain rows for that frozen candidate only. Outcomes for another candidate fail rather than being
silently ignored.

Each nested rolling-origin validation row records its training-data boundary, model-fit time, and
model, calibration, and baseline digests. Those boundaries must precede that fold's validation
Matchweeks, and every development outcome used by the row must have been known by its training
boundary. A completed fold is checkpointed with this provenance and reused on resume.

## Metric semantics

WIN, PUSH, and LOSS enter settlement-aware Brier score and log loss using the frozen Settlement
Distribution. The normalized multiclass Brier score retains the ordinary binary Brier scale.
Observed-versus-predicted output reports each settlement class. WIN calibration, Conservative
Probability coverage, and uncertainty diagnostics treat PUSH as not-WIN without relabeling it LOSS.
VOID is excluded from all probability scoring. Log loss clips only at `1e-15` to keep exact zero or
one inputs finite.

Preference errors are averaged inside each match, then match means are averaged. Preference-level
Brier and log loss remain alongside the match-clustered primary scores for audit. Effective sample
information separately reports preference rows, match clusters, scored and binary match clusters,
recommendation match clusters, and match-plus-correlation-group clusters. Multiple related
preferences from one fixture never increase match-level effective sample size.

Calibration bins report their exact declared edges, row count, match clusters, mean prediction,
and observed success rate. Conservative Probability coverage compares match-clustered observed
success with the mean conservative lower estimate. The aggregate interval comparison is labeled
`aggregate_uncertainty_alignment`; it is not coverage. Empirical uncertainty coverage groups unseen
results by the declared reliability bins and reports the share whose match-clustered observed rate
falls inside that bin's mean interval. It is `INCONCLUSIVE` unless the input declares the interval's
nominal coverage. These are diagnostics, not acceptance decisions unless the input also declares a
criterion.

Settlement metrics retain selected WIN, LOSS, PUSH, and VOID counts. A false positive is a selected
PLAY or research candidate graded LOSS. Its rate and the negative-settlement rate use selected WIN
plus LOSS only. Recommendation/selectivity rates use unique matches. AVOID MATCH is reported as
abstention and never credited as a success.

Subgroups cover league, Preference Family, exact line, Matchweek period, and supplied structural
conditions such as promoted-team or sparse-history state. A subgroup is `SUFFICIENT` only when its
dimension has a declared minimum and its unique-match effective sample meets it. Otherwise it is
`INCONCLUSIVE` and exposes borrowed parent metrics. Exact lines borrow their Preference Family;
other sparse groups borrow the aggregate. Borrowing never turns a sparse local group into a claim
of local reliability.

The artifact also reports hierarchical exact-line baseline lift, structurally trivial selections,
G4 rejection behavior, all mandatory-gate failures, gate leaks into selections, within-match
Selection Strength concordance, Model Agreement by settlement, uncertainty versus absolute error,
component ranges, Matchweek recommendation and false-positive ranges, candidate sensitivity, and
nested-fold threshold and Selection Strength weight ranges where supplied.

## Findings and artifacts

`PASS`, `FAIL`, and `INCONCLUSIVE` apply only to supplied criteria. Too few recommendations or an
undeclared minimum makes the evaluation `INCONCLUSIVE`, even when selection volume is low. Missing
acceptance criteria also makes it `INCONCLUSIVE`. T18 never interprets low volume as successful
conservatism.

The output schema is `matchvet.policy-evaluation.v1`. It contains exact folds and ranges, counts,
effective samples, candidate validation metrics within each nested fold, exclusions and reasons,
frozen candidate identity, every metric family, a row-level observation audit with exact fixture,
input/version identities, and settlement, plus the cutoff-fidelity result, criteria findings, and
reproducibility metadata. Canonical JSON binds the
artifact to the corpus, configuration, seed, policy/model/input digests, folds, algorithm, and
environment. The artifact lifecycle effect is always `EVALUATED_RESEARCH_ONLY`.

Checkpoints use `matchvet.policy-evaluation-checkpoint.v1`. T18 writes a uniquely named,
operation-owned temporary file, flushes and syncs it, and atomically replaces the checkpoint after
a complete fold. Resume reuses those verified fold records instead of recomputing them. The final
checkpoint names the immutable artifact digest. Output artifacts use an exclusive publication lock,
unique temporary file, read-back and digest verification, atomic replace, and directory sync. A
different existing output is never overwritten.

# T18 chronological policy evaluation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline, deterministic evaluator that selects a candidate policy on validation data and evaluates that frozen identity once on a later untouched period without changing production state.

**Architecture:** `matchvet.t18` owns immutable historical observations, declared split/fold definitions, cutoff and inspection checks, match-clustered metrics, subgroup borrowing, diagnostics, deterministic checkpoints, and schema-versioned artifacts. The CLI consumes rights-safe local JSON only. It writes an evaluation artifact but cannot call T15 production validation or mutate a Selection Policy Version.

**Tech Stack:** Python 3.14 standard library, existing T10/T15 domain types, canonical SHA-256 JSON, argparse, pytest.

**Spec:** GitHub issues #1 and #35, `CONTEXT.md`, `docs/research/prediction-and-uncertainty-methods.md`, and the completed T10/T14/T15/T16 contracts.

## Global constraints

- Development, Validation, and untouched Final Evaluation ranges are chronological, disjoint, exact, and Matchweek-boundary based.
- Historical rows contain only frozen, cutoff-valid inputs; any post-cutoff or unavailable-at-cutoff input fails the run.
- Candidate choice uses Validation only. Final Evaluation contains the already-frozen winner only and cannot influence tuning.
- Random splits, odds, profit, staking, volume objectives, inferred minimum samples, and inferred acceptance thresholds are rejected.
- WIN, PUSH, and LOSS enter settlement-aware probability metrics from the frozen distribution; VOID is excluded and PUSH is never relabeled as WIN or LOSS.
- Aggregate estimates cluster preference rows by match. Correlation-group counts remain visible and cannot increase match-level effective sample size.
- Sparse subgroups borrow the declared parent result and remain `INCONCLUSIVE`; they never claim local reliability.
- Artifacts and checkpoints use canonical JSON and input/config/policy/fold/result digests. Resume accepts only the same run identity.
- T18 returns evaluation findings only. It never creates `PRODUCTION_PROMOTED`, edits policy metadata, or changes T15 output.

## Review focus

- A candidate derived from or frozen after its allowed historical boundary must fail before metrics are computed.
- Reusing a previously inspected Final Evaluation window as unseen must fail, while an exact digest-bound replay remains reproducible.
- Multiple preferences from one fixture must contribute one match cluster to effective sample calculations.
- PUSH and VOID must not become wins, losses, or false positives.
- Missing declared subgroup sample rules or acceptance criteria must yield `INCONCLUSIVE`, not defaults.

---

### Task 1: Define chronological data and split contracts

**Files:**
- Create: `src/matchvet/t18.py`
- Create: `tests/test_t18.py`

**Interfaces:**
- Produces `HistoricalEvaluation`, `CandidatePolicy`, `EvaluationConfig`, `ChronologicalFold`, `EvaluationError`, and `generate_rolling_origin_folds`.

- [ ] Write failing public-interface tests for timestamp validation, strict split order, overlap/gap behavior, random split rejection, deterministic folds, candidate derivation/freeze boundaries, previously inspected windows, and prohibited inputs.
- [ ] Run `.venv/bin/python -m pytest tests/test_t18.py -q` and confirm red.
- [ ] Implement immutable validated inputs and deterministic rolling-origin fold generation with exact Matchweek groups.
- [ ] Run the focused tests and mypy for `t18.py` and `test_t18.py`.

### Task 2: Implement match-clustered metrics and subgroup borrowing

**Files:**
- Modify: `src/matchvet/t18.py`
- Modify: `tests/test_t18.py`

**Interfaces:**
- Produces `evaluate_observations` and schema-stable probability, calibration, settlement, subgroup, non-triviality, ranking, gate, uncertainty, and effective-sample payloads.

- [ ] Add hand-computable red tests for Brier score, log loss, reliability bins, observed versus predicted calibration, conservative/interval coverage, WIN/LOSS/PUSH/VOID handling, false positives, AVOID behavior, match clustering, subgroup sufficiency, and parent borrowing.
- [ ] Implement the minimum metric engine that makes those examples green.
- [ ] Add red tests for Non-Triviality lift, easy-line detection, survivor ranking reliability, gate rejection, uncertainty/error ordering, and sensitivity/stability summaries.
- [ ] Implement the diagnostic calculations without acceptance defaults and rerun focused tests plus mypy.

### Task 3: Implement nested selection and immutable artifacts

**Files:**
- Modify: `src/matchvet/t18.py`
- Modify: `tests/test_t18.py`

**Interfaces:**
- Produces `evaluate_policies`, `EvaluationArtifact`, `EvaluationRunner`, and canonical artifact/checkpoint readers.

- [ ] Add red tests proving validation-only candidate selection, one frozen identity in Final Evaluation, insufficient recommendations returning `INCONCLUSIVE`, configured PASS/FAIL criteria, deterministic replay, input tamper rejection, and no promotion side effects.
- [ ] Implement validation selection by an explicit metric/direction and evaluate the selected identity on the untouched range.
- [ ] Add atomic fold checkpoints, same-run resume, interruption behavior, artifact parsing, schema/version/digest verification, exclusions, seeds, and environment metadata.
- [ ] Rerun focused tests and mypy.

### Task 4: Add local CLI and evaluation documentation

**Files:**
- Modify: `src/matchvet/cli.py`
- Modify: `tests/test_cli.py`
- Create: `docs/policy-evaluation.md`
- Modify: `README.md`

**Interfaces:**
- Produces `matchvet policy validate --input <json> --output <json> [--checkpoint <json>] [--resume]`.

- [ ] Add red CLI tests for offline success, stable failures, resume, deterministic output, and no production mutation.
- [ ] Implement JSON parsing, artifact publication through an operation-owned temporary file plus atomic replace, and text/JSON summaries.
- [ ] Document corpus fields, split rules, metric semantics, cutoff failure, declared sample/criteria behavior, resume, and research-only status.
- [ ] Rerun CLI/T18 tests, Ruff, and mypy.

### Task 5: Verify, smoke, review, and deliver

**Files:**
- Modify only T18-scoped files when fixing review findings.

- [ ] Run `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`.
- [ ] Run `.venv/bin/mypy`.
- [ ] Run `.venv/bin/python -m pytest`.
- [ ] Run an offline Termux smoke against a generated rights-safe structural fixture corpus. Inspect boundaries, aggregate/subgroup/calibration/false-positive output, and compare rerun digests.
- [ ] Review the diff against #35 for temporal leakage, statistical validity, scope creep, and production side effects. Fix every material finding with a regression test first.
- [ ] Commit with `feat: add chronological policy evaluation`, push `main`, and close #35 only if every criterion and check passes.

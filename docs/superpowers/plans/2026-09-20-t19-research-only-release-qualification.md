# T19 research-only release qualification implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that the complete T01-T18 MatchVet workflow is reproducible, recoverable, rights-safe, and within the settled Termux budgets for a `RESEARCH_ONLY` software release.

**Architecture:** `matchvet.t19` is a release-engineering module above the existing product seams. It loads one self-authored structural corpus, executes the existing T06-T18 public interfaces, and emits one canonical qualification artifact. A shell entry point runs repository and offline-environment gates around that replay. T19 never changes a `PolicyVersion`, defines a production threshold, or authorizes `PLAY`.

**Tech stack:** Python 3.14 standard library, existing MatchVet T01-T18 interfaces, SQLite, SHA-256 canonical JSON, pytest markers, Ruff, mypy, uv offline mode, and Termux `/proc` and filesystem observations.

**Spec:** GitHub issues #1 and #36, `CONTEXT.md`, `AGENTS.md`, and the completed T01-T18 implementation and docs.

## Global constraints

- The only successful release status is `QUALIFIED_RESEARCH_ONLY`; every missing or failed required gate yields `NOT_QUALIFIED` with exact reasons.
- A T19 result always records `production_promotion: false`; it cannot emit `PLAY`, `AVOID MATCH`, or a production Confidence Label.
- The replay covers exactly the seven configured Target Leagues and exactly the 37 preferences for every included Target Match.
- The corpus contains self-authored structural equivalents only. It records its redistribution basis and includes no Football-Data.co.uk raw rows or disallowed official-page content.
- T19 reuses T06-T18 public interfaces. It does not replace their parsers, models, gate logic, publication, recovery, or evaluation code.
- Resource acceptance uses the budgets already settled in `runs.SETTLED_RESOURCE_BUDGET`. T19 adds measurements, not weaker limits.
- Chronological evaluation checks framework behavior only. It does not invent or pass statistical Production Promotion criteria.
- External checks retain their command, exit code, output digest, elapsed time, and failure reason. A missing proof is a failed gate.

## Review focus

- Resume identity must change when `refresh_current` or `refresh_weather` changes. Otherwise a resumed run can reuse work produced under a different acquisition policy.
- Every T16 publication used by T19 must have explicit environment, software, model, feature, research-rule, policy, source-snapshot, membership, and revision identities. `UNSPECIFIED` is a qualification failure.
- One legitimate sparse or incomplete pack must preserve `MODEL_UNAVAILABLE`, `UNKNOWN`, and T15 `REJECT` without a fallback probability or invented evidence.
- Export must omit restricted raw captures and retain the omission. Backup and restore must preserve every protected object and reproduce the readable audit.
- A second replay from the same corpus must produce the same semantic digest even though temporary paths, timings, and resource observations differ.

## Synthesis decision

The chosen design separates deterministic product replay from machine-specific qualification checks. `run_recorded_replay()` hides T06-T18 composition behind one interface. `qualify_research_only()` combines that result with explicit external gate evidence. This is deeper and easier to test than exposing every phase through a new CLI.

Two alternatives were rejected. A `matchvet qualify` product command would expand the exact v1 CLI and mix release engineering with normal use. A test-only harness would prove the current checkout but provide no canonical artifact or reusable benchmark entry point. Two external architecture runners were attempted and both dropped because the agent quota was exhausted; the completed subsystem traces agreed on the selected seam.

---

### Task 1: Repair exact resume identities

**Files:**
- Modify: `src/matchvet/ingestion.py`
- Modify: `src/matchvet/t08.py`
- Modify: `tests/test_ingestion.py`
- Modify: `tests/test_workload_weather.py`

**Interfaces:**
- `IngestionPlan.plan_digest` binds `refresh_current`.
- `build_t08_input_contract(..., refresh_weather: bool = False)` binds the weather refresh policy, and both T08 runner paths pass it.

- [ ] Add a failing assertion that otherwise-identical T06 plans with opposite `refresh_current` values have different plan and input-contract digests.
- [ ] Add a failing assertion that otherwise-identical T08 runs with opposite `refresh_weather` values have different input-contract digests.
- [ ] Add the two booleans to their canonical input identities and pass `refresh_weather` through `start()` and `resume()`.
- [ ] Run the two focused test files and focused mypy.

### Task 2: Define the corpus and qualification contracts

**Files:**
- Create: `src/matchvet/t19.py`
- Create: `tests/recorded/t19-seven-league.json`
- Create: `tests/test_t19.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `RecordedCorpus.read(path: Path) -> RecordedCorpus` validates the schema, exact league set, rights declaration, UTC times, source modes, and digest.
- `run_recorded_replay(corpus: RecordedCorpus, workspace: Path) -> RecordedReplayResult` is the sole replay interface.
- `qualify_research_only(evidence: QualificationEvidence) -> QualificationManifest` returns `QUALIFIED_RESEARCH_ONLY` only when every fixed software gate passes.
- All external mappings are parsed before internal use. `QualificationManifest` encodes research-only mode and `production_promotion=False` as fixed values.

- [ ] Add red tests for corpus tamper, missing league, non-redistributable material, duplicate fixture, unknown schema, and canonical digest stability.
- [ ] Add red tests for missing/failed gates, budget failure, replay mismatch, production-language leakage, and deterministic qualification bytes.
- [ ] Implement immutable parsed types, canonical serialization, digest verification, fixed required-gate names, and fail-closed status calculation.
- [ ] Register the `recorded_e2e` and `failure_injection` pytest markers.
- [ ] Run `tests/test_t19.py` contract tests and focused mypy.

### Task 3: Compose the all-seven recorded replay

**Files:**
- Modify: `src/matchvet/t19.py`
- Modify: `tests/test_t19.py`
- Modify: `tests/recorded/t19-seven-league.json`

**Interfaces:**
- `run_recorded_replay()` returns per-league ingest, freeze, Evidence State, model-family, 37-row vetting, grading, report, export, recovery, and evaluation evidence plus stable digests.

- [ ] Add one marked red test that expects all seven league keys, one included Target Match per league before withdrawal, one fallback capture, explicit `UNKNOWN`, an append-only conflict, one withdrawn fixture, and no prohibited preference.
- [ ] Generate source bytes from the structural corpus and run T06 ingestion, including the OpenFootball fallback and a controlled conflicting revision.
- [ ] Run T05 freeze, record T07 contextual evidence, then run T08 workload/weather and T09 Evidence State construction.
- [ ] Fit and publish T11, T12, and T13 artifacts, then run T14. Retain both available and legitimate `MODEL_UNAVAILABLE` families.
- [ ] Run T15 with a `RESEARCH_ONLY` policy. Assert 37 unique results per Target Match, G0-G8 audit rows, explicit `REJECT`, and no production decision or label.
- [ ] Build and publish T16 with complete explicit reproducibility identities. Grade all 37 contracts through T10 without inferring missing corners.
- [ ] Export the report, create and verify a backup, restore to a new private target, and compare the restored audit and protected-object identities.
- [ ] Adapt the replay records into T18 historical rows, run chronological validation with no acceptance thresholds, and require `EVALUATED_RESEARCH_ONLY` plus an inconclusive promotion result.
- [ ] Run the replay twice and assert the semantic digest, reports, audits, grades, export manifests, and evaluation artifact are deterministic. Verify each backup and compare restored authoritative state; independent backups retain distinct run IDs, timestamps, and device observations, so their database-byte digests need not match.

### Task 4: Add representative failure injection

**Files:**
- Modify: `src/matchvet/t19.py`
- Modify: `tests/test_t19.py`

**Interfaces:**
- `run_failure_matrix(corpus: RecordedCorpus, workspace: Path) -> tuple[FailureCheck, ...]` runs bounded, recoverable cases and records the stable refusal/recovery code.

- [ ] Add red tests for T06, T05, T08, and T09 interruption/resume with exact input digests.
- [ ] Add red tests for stale/incompatible resume, T16 unmarked partial publication, corrupt artifact, export/backup digest mismatch, incomplete backup, and failed restore atomicity.
- [ ] Add red tests for insufficient free space and safe store read-only behavior after a copied-database integrity failure.
- [ ] Implement only orchestration needed to invoke existing fault hooks and verification functions. Do not duplicate recovery logic.
- [ ] Run the marked failure matrix and focused mypy.

### Task 5: Add the bounded device qualification runner

**Files:**
- Create: `scripts/qualify-research-release.sh`
- Modify: `README.md`
- Create: `docs/research-only-release-qualification.md`

**Interfaces:**
- `scripts/qualify-research-release.sh OUTPUT_DIR` runs the fixed checks and writes `qualification.json`, command logs, replay artifacts, an offline-build record, and resource observations under an operation-owned output directory.

- [ ] Run Ruff check and format check, mypy, default pytest, recorded E2E, and the failure matrix with exact command logging.
- [ ] Verify the installed Termux packages against `environment/termux-packages.lock`, create a clean temporary copy, and run `uv sync --offline --locked --no-python-downloads` against the retained cache.
- [ ] Measure monotonic runtime, `/proc` peak RSS where available, temporary and final managed storage, minimum free space, configured CPU/thread limits, and network bytes for the offline replay.
- [ ] Compare measurements to `SETTLED_RESOURCE_BUDGET`; fail without changing the budget.
- [ ] Write the reference qualification document with the qualified source commit, environment identity, every check, seven-league outcomes, resources, recovery results, known source/statistical limits, and `Production Promotion has NOT occurred`.

### Task 6: Verify, review, and deliver

**Files:**
- Modify only T19-scoped files needed to fix review findings.

- [ ] Run `ruff check .` and `ruff format --check .`.
- [ ] Run `.venv/bin/mypy`.
- [ ] Run `.venv/bin/python -m pytest`.
- [ ] Run `.venv/bin/python -m pytest -m recorded_e2e`.
- [ ] Run the deterministic replay comparison, offline rebuild, device benchmark, and failure matrix through the qualification script.
- [ ] Review the diff from `1f9fcbe` on separate Standards and Spec axes. Fix every material finding with a red test first.
- [ ] Commit the executable T19 change, rerun qualification against that exact commit, and commit the resulting reference document without changing runtime code.
- [ ] Push `main`. Close #36 only when the artifact says `QUALIFIED_RESEARCH_ONLY`; otherwise leave it open and report `NOT QUALIFIED` with the exact failed gates.
- [ ] Report whether #37 is technically unblocked. Do not start it.

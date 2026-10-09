# CandidateInput blocker status

Status date: 2026-10-09.

## Current state

[#70](https://github.com/Awisalas/match-vet/issues/70) remains OPEN with
`needs-info`. [ADR 0004](../adr/0004-candidate-input-estimands-and-consumer-boundaries.md)
is accepted as the semantic contract. [Methodology 0.2.0](CANDIDATE-INPUT-METHODOLOGY-0.2.0.md)
is its accepted, non-executable successor. It leaves methodology 0.1.0,
chronology 0.2.0, released V1 artifacts and readers, CB01 core, and historical
cohorts unchanged.

[#85](https://github.com/Awisalas/match-vet/issues/85) is CLOSED. Its versioned
F13/F14/T15 consumer seam is implemented in commit
`976beb8216d9174d20ff7184e289c09827e12061`. [#86](https://github.com/Awisalas/match-vet/issues/86)
is OPEN with `ready-for-agent`. Its offline bootstrap implementation and
testing are ready to proceed. No real case may qualify, and no live collection
may run, until real-source use and the causal-witness profile are separately
approved and operational. This readiness does not authorize either prerequisite
or supply the missing #70 cohort. #86 implementation has not started. Issue #70
remains OPEN with `needs-info`; implementing #85 does not resolve its
chronological evidence or numerical/profile decisions.

## #85 implementation record

- Added versioned CandidateInput support, exact protected gate-proof readers,
  and F14 replay identities without changing released V1 readers or formats.
- Added T15 joint finalist comparison with an order-independent maximal set
  and unresolved-primary AVOID behavior.
- Focused checks: 51 tests passed across the fast focused run and exact replay;
  Ruff, strict mypy on changed production modules, and `git diff --check` passed.
- Implementation commit: `976beb8216d9174d20ff7184e289c09827e12061`.
- Open blockers: #70 still needs a prospectively captured corrected-chronology
  V2 cohort; #86 live operation still requires separately approved and
  operational real-source use and causal-witness profile.

## #86 readiness record

- Dependencies #69, #71, #72, #80, #84, and #85 are CLOSED.
- #86 is ready for offline bootstrap implementation and testing. No real case
  qualifies and no live collection may run before real-source use and the
  causal-witness profile are separately approved and operational.
- #86 implementation has not started and does not supply the missing #70
  cohort.
- Readiness correction commit SHA:
  `198c96f83e04240fc077d3c5454e5c04613aa941`.

## Decision recorded

- U1 is the probability mass under the frozen joint uncertainty law that
  violates an applicable G5 probability constraint.
- U2 keeps latent probability-interval coverage, predictive coverage, and
  calibration as distinct claims. A single observed outcome cannot establish
  latent probability-interval coverage.
- T1 compares all gate-qualified finalists through one coherent joint object.
  A missing comparison that could change the justified primary produces the
  versioned F14 result `AVOID MATCH` with `PRIMARY_SELECTION_UNRESOLVED`.
- The ADR explicitly amends #13 Section 2, item 4, and Section 6's final
  sentence. It does not silently reinterpret the old primary-selection rule.
- Missing required G6, G7, or G8 support remains UNKNOWN and fails closed.
  Normalization references resolve by component and exact preference through
  only estimand- and settlement-compatible groups.
- No threshold, coefficient, confidence level, sample floor, prior, weight,
  fitted value, or promotion criterion was selected.

## Compatibility and work boundaries

- #85 implemented the versioned consumer and replay contract. It does not
  authorize a statistical fit or production PLAY.
- #86 defines the later prospective evidence bootstrap. It must use the exact
  corrected F06/F07 inputs and #80 selection witness before cutoff, then retain
  CB01's separate post-cutoff, pre-kickoff witness and later source-backed F19
  outcomes by exact digest.
- Preserve every denominator row and its inclusion or exclusion reason. Do
  not backdate publication or retrieval times, refresh a selected graph, use
  legacy per-match records as corrected cases, or weaken UNKNOWN.
- Freeze separate development, validation, and untouched final-evaluation
  manifests before using outcomes for those roles. Reuse removes a case from
  the untouched set.
- No F16 corrective implementation, F17 work, #37 fitting, schema migration,
  live source acquisition, or production activation is authorized here.
- Prior planning records remain in `e89f2934a7985a93065ee67ceb1f49efefc23650`
  and `cfed6bc070168d887029119ace0a39915296992a`.

## Ordered blockers

1. #85's versioned CandidateInput support and joint T1 comparison contract is
   implemented in `976beb8216d9174d20ff7184e289c09827e12061`. Missing support
   remains UNKNOWN, and old readers retain their existing meanings.
2. #86 may implement and test its offline bootstrap path. Separately approve and
   operationalize real-source use and the causal-witness profile before any
   case can qualify or live collection can run. This authorization remains
   pending.
3. Only after authorization, run #86 prospectively. Retain exact cutoff-valid
   inputs, immutable provenance, all denominator rows, and later source-backed
   outcomes. Keep unavailable, unattempted, UNKNOWN, failed, VOID, and
   unsupported states visible.
4. Freeze development, validation, and untouched final-evaluation manifests
   before assigning evidence roles.
5. Resolve the empirical methods and profiles under #13 from eligible
   chronological evidence. Keep #70 `needs-info`, F16 corrective work, F17,
   #37 fitting, and production promotion blocked until their own criteria pass.

## Exact current blocker for #70

MatchVet has no prospectively captured corrected-chronology V2 cohort that
joins exact cutoff-valid inputs, F13 predictions, F14/F16 RESEARCH_ONLY records,
and later source-backed outcomes. Existing historical rows cannot prove earlier
prediction availability, and production causal activation still refuses.
Numerical and profile decisions therefore remain evidence-dependent.

## Earlier repository bookkeeping

- Removed stale `ready-for-agent` from closed #84.
- Corrected #83's stale open/unstarted summary while preserving its historical
  completion evidence.
- The earlier #70 planning and status entries are preserved in the commits
  listed above.

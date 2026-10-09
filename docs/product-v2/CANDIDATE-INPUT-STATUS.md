# CandidateInput blocker status

Status date: 2026-10-09.

## Current state

[#70](https://github.com/Awisalas/match-vet/issues/70) remains OPEN with `needs-info`. It is not ready-for-agent and is not closed. The proposed [methodology 0.2.0](CANDIDATE-INPUT-METHODOLOGY-0.2.0.md) and [ADR 0004](../adr/0004-candidate-input-estimands-and-consumer-boundaries.md) settle design semantics for review; they select no fitted method, profile, threshold, weight, confidence level, sample floor, or promotion rule.

The planning record was committed and pushed in `e89f2934a7985a93065ee67ceb1f49efefc23650`. This status entry is committed separately from that planning record.

## Work recorded

- Classified Q1, R1, B1/B2, A1, S1/S2, C1, U1/U2, M1, P1, and T1 as design-only, compatibility, or evidence-dependent decisions.
- Proposed U1 as uncertainty mass outside the exact G5 probability-constraint region. Separated probability-interval coverage, predictive coverage, and calibration.
- Proposed one joint paired comparison for all gate-qualified finalists. Unknown comparisons that could change the maximal finalist set cannot select a primary.
- Specified group-aware reference resolution and fail-closed G6/G7/G8 support requirements.
- Created child #85 for versioned F13/F14/T15 consumer support and child #86 for a pre-F17 diagnostic evidence-capture path. #70 is blocked by both. #86 is blocked by #85.
- Corrected #83's stale readiness summary while preserving its acceptance and completion evidence. Removed stale `ready-for-agent` from closed #84.
- No production code, schema migration, F16 corrective work, F17 work, #37 fitting, live source activation, or live football-data acquisition was done.

## Evidence path

F06/F07, F11/F13/F14/F16, the causal selection path, CB01, and F19 provide protected record shapes. The #80/#84 causal path has offline integration proof, but production activation still refuses. CB01's post-cutoff witness does not prove pre-cutoff collection; the exact selected graph needs the #80 witness, and source facts need their own provenance.

The retained stores have result rows but no F13/F14 prediction contracts. The inspected source captures lack publication timestamps and cannot establish earlier historical availability. The T19 qualification corpus is synthetic. F21 waits for F18 and F20, while F18 depends on F17 and F17 depends on #70. Child #86 provides a bounded bootstrap plan without requiring F17 publication or F20 automation.

## Ordered blockers

1. Review and accept or amend the proposed non-empirical contract. Implement #85 without fitted values or changes to V1 and method 0.1.0 readers.
2. Separately authorize real source use and the causal witness profile. #86 does not activate either.
3. Implement and operate #86 to retain exact corrected-chronology RESEARCH_ONLY cases before F17. Preserve every denominator row and attach later exact F19 outcomes. Leave unsupported inputs UNKNOWN.
4. Freeze separate development/calibration, validation, and untouched final-evaluation manifests before using outcomes for those roles.
5. Use the eligible cases to resolve the empirical profiles under #13. Keep #70, F16 corrective work, F17, #37 fitting, and Production Promotion blocked until their own criteria pass.

## Exact current blocker for #70

There is no prospectively captured corrected-chronology V2 cohort that joins exact cutoff-valid F11 inputs, F13 predictions, F14/F16 RESEARCH_ONLY records, and later source-backed outcome facts under the selected #80 graph. Production causal activation still refuses, and the F13/F14/T15 consumer support seam is not implemented. Without that cohort and consumer seam, the numerical profiles cannot be fitted or validated without inventing historical availability or thresholds.

## Commits

- Planning records: `e89f2934a7985a93065ee67ceb1f49efefc23650`.
- This status entry is committed separately; its commit is recorded in Git history and the #70 status comment.

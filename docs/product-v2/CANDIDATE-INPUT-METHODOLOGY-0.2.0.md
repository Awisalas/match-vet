# CandidateInput derivation methodology 0.2.0

Contract name: `v2-candidate-input-derivation`. Document version: `0.2.0`.
Decision date: 2026-10-09. Status: **accepted semantic successor; not executable**.

This accepted contract addresses the design-only gaps recorded in [methodology 0.1.0](CANDIDATE-INPUT-METHODOLOGY.md) for [#70](https://github.com/Awisalas/match-vet/issues/70). It leaves that document byte-for-byte unchanged and preserves its legacy per-match cohort. It also leaves [chronology 0.2.0](CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md), all released V1 contracts, and their readers unchanged. No estimator, fitted value, confidence level, sample floor, coefficient, weight, threshold, or promotion rule is selected here.

The accepted durable boundary is [ADR 0004](../adr/0004-candidate-input-estimands-and-consumer-boundaries.md). This document settles semantics and consumer shape only. Method and profile status remain separate: a defined event is not a validated event model, and a complete schema is not evidence of support.

## Accepted semantics

### UNKNOWN and support

Every applicable value has an explicit support state and source. `UNKNOWN`, `UNPERFORMED`, `NOT_APPLICABLE`, `INVALID`, evidenced absence, and observed evidence remain distinct. Missing is never zero, a favorable default, a global fallback, or proof that a reference is independent. A required UNKNOWN blocks that gate and any dependent score. A diagnostic `RESEARCH_ONLY` run may retain the complete case with an unresolved gate and a rejection; it cannot rank the case as supported or produce a Primary Recommendation. An optional UNKNOWN is harmless only when the versioned requirement says the item is inapplicable or not required.

Candidate values are outputs of protected derivation records, not caller assertions. Each record names its exact cutoff-valid inputs, source and rule identities, applicable domain, support state, and exclusion reason. A scalar without a resolvable supporting record is UNKNOWN. `CHECKED` means a procedure ran; it does not mean the claim passed.

### Group-aware normalization

Resolve each Selection Strength component against the candidate's exact T10 preference contract and a protected hierarchy reference. Keep the hierarchy already specified by #12/#13: applicable preference family and exact line, then role, league, and supported context. A fallback is valid only when it preserves the component's estimand and settlement topology. WIN/LOSS and WIN/PUSH/LOSS references cannot be exchanged, nor can unrelated market families share a base rate.

The reference manifest records the chosen group, every ancestor considered, the selected reference digest, and the reason for fallback. Apply the existing T15 normalization, orientation, and weighted-sum operations after resolution. Do not use a PolicyVersion-wide reference for all candidates, a pre-normalized scalar override, or the CandidateInput default as a substitute. If no applicable reference is supported, the component and dependent Selection Strength are UNKNOWN.

This requires a versioned resolver keyed by component and exact preference identity. Current `SelectionStrengthConfig` stores one normalizer per component, and `_selection_strength` receives no preference identity. That contract cannot consume exact-market reference manifests as-is.

### U1: G6 tail-risk estimand

Define G6 tail risk as the probability mass, under the frozen joint uncertainty law for a candidate's settlement-probability vector, on draws that violate one or more applicable probability constraints in that exact PolicyVersion's G5 gate. The draw preserves the market's settlement topology and dependence among WIN, PUSH, and LOSS. It measures uncertainty about whether the candidate's probability distribution satisfies the frozen gate. It does not measure the chance of an extreme realized score or count.

Keep interval width and this gate-violation mass as separate G6 inputs. Use the same identified uncertainty law and source draws as the candidate's F13 probability bounds. The named event and event identity are frozen now; the law, calibration, supported domains, acceptable risk limit, and numerical gate values still require evidence. If the event, thresholds, or uncertainty law is missing or unsupported, tail risk is UNKNOWN and G6 cannot pass.

The alternative count-tail estimand is rejected for this field because it measures match randomness, not uncertainty in the probability constraints that G6 protects. It can remain a separately named predictive-distribution diagnostic.

### U2: coverage and empirical reliability

Keep three claims separate:

- **Probability-interval coverage** concerns whether an interval contains the unobserved conditional settlement probability. One outcome per match does not reveal that probability. Real outcome rows alone cannot certify this claim. A known-truth simulation can support only a clearly labeled model-conditional diagnostic.
- **Predictive coverage** concerns whether an observed categorical settlement outcome falls inside a predeclared predictive outcome region.
- **Calibration** compares full settlement-probability vectors with observed class frequencies over predeclared comparable cases.

G6's `uncertainty_reliable` state is supported only by a protected validation record that names the claim, method, topology, population, chronology, groups, assumptions, and diagnostics. It is not a caller-supplied boolean and does not imply that all three claims were established. Genuine later outcomes can assess full-vector calibration, predictive coverage, proper scores, and the relation between stated uncertainty and observed error. They cannot turn those diagnostics into latent probability-interval coverage. Missing claim-specific support or an unsupported subgroup leaves the state UNKNOWN. The profile's validation procedure and acceptance regions remain evidence-dependent.

This clarifies #13's statement that uncertainty intervals must achieve their intended empirical coverage. The successor policy must name whether each validated interval targets latent probability or a predictive outcome region, and use only evidence appropriate to that target.

### T1: paired Statistical Tie with multiple finalists

Run the tie procedure only after the exact frozen policy has identified the gate-qualified set. Keep that observed set fixed for this comparison. Gate qualification is decided by the gates; T1 does not silently rerun gates inside uncertainty replicates or discard gate-crossing draws. The joint score comparison uses every required supported draw. Any invalid or UNKNOWN comparison input stays visible and can make the affected ordering unresolved.

For every qualified finalist, calculate Selection Strength under the same coherent draw of the shared historical block, model/calibration, baseline, normalization references, and applicable scenario inputs. Preserve the covariance and settlement topology. A historical difference in outcome performance is a validation diagnostic, not the current match's paired strength difference.

Build one simultaneous uncertainty object for all qualified finalists. Candidate A robustly outranks B only when the supported region for their paired difference lies wholly above zero under that common object. If it contains zero, neither candidate robustly outranks the other. The finalists that no other candidate robustly outranks form the maximal set. Apply the existing ordered tie-breakers only within that set: lower uncertainty, stronger Data Quality, lower Failure Risk, stronger Historical Reliability, then user preference order if still indistinguishable. A candidate robustly below another finalist cannot re-enter through a chain of pairwise ties.

If support is UNKNOWN for a comparison that could change the maximal set or its tie-break order, do not choose a primary from the affected finalists. F14 records an unresolved selection as `AVOID MATCH` with a distinct unresolved-primary reason. It does not call the candidates statistically tied merely because the evidence is missing. The joint uncertainty method, interval procedure, block law, confidence level, and validation criteria remain evidence-dependent.

The accepted ADR explicitly amends #13 Section 2, item 4, and Section 6's final sentence. If UNKNOWN comparison support could change the justified primary, F14 records `AVOID MATCH` with the versioned reason `PRIMARY_SELECTION_UNRESOLVED`. Future F17 reporting and evaluation readers must preserve this reason. The amendment changes neither #13's gates nor its score or tie-break order.

Independent marginal intervals are rejected because pairwise overlap need not be transitive. A fixed arbitrary ordering is also rejected because it can conceal a supported strength difference. Current T15 uses pairwise interval overlap inside a comparator passed to `sorted`; a three-finalist cycle was reproduced against that real comparator (see the blast-radius note below).

### G6, G7, and G8 consumer requirements

**G6.** F13/T14 or a versioned adapter must supply the tail-risk event result and a protected uncertainty-validation reference. The reference names the exact supported claim and domain. T15 must reject a missing claim, a mismatched topology, an unsupported group, or an absent profile limit. A successful model fit, `CHECKED` diagnostic, or arbitrary true boolean cannot pass G6.

**G7.** F13/T14 or a versioned adapter must supply a protected reference manifest. It names each required applicable #12 challenger, complete settlement distributions and ranges, dependency group, model/calibration/validation identities, availability state, and the evidence for distinct assumptions and error behavior. Compare the candidate and reference ranges against the frozen acceptance boundary and retain conflicting-outcome findings. A label or perturbed copy does not establish independence. Missing, unavailable, or ineligible required references mean UNKNOWN, not perfect agreement. The required reference set, independence evidence criterion, divergence limits, and supported fallback remain empirical decisions.

**G8.** Review every enabled preference before ranking. The protected review identifies distinct supporting and failure evidence, source and assertion digests, materiality estimand and support, and an exact F13 uncertainty-propagation reference when the risk is represented. A concrete evidence-backed invalidation of a required assumption may veto. Missing or unquantified materiality cannot pass as zero, and an unrepresented risk cannot pass without the exact versioned policy rule that governs it. That rule and its numerical limit must be explicit in every executable profile. No numerical materiality or risk threshold is chosen here.

Retain every credible failure case. Call one case strongest only when the frozen comparison criteria support that ordering. Keep incomparable mechanisms as separate cases; do not force them into one materiality scalar. If the review cannot establish that an unquantified case is immaterial to the decision, the candidate cannot pass G8.

The new consumer must remove implicit support defaults such as `CandidateInput.explanatory=True`. Absence of correlation, explanation, range, or representation support is UNKNOWN. It cannot create independent agreement, a Correlated Secondary Fit, a passing gate, or a stronger score.

## Classification of every open methodology item

| Item | Settled or specified now | Still evidence-dependent |
| --- | --- | --- |
| Q1 | Evidence-only inputs, applicable requirements, coverage diagnostic, and UNKNOWN behavior. Critical gaps cannot be averaged away. | Dimension mappings, aggregation, floors, source/freshness effects, normalization, and supported hierarchy. Requires cutoff-valid evidence and later validation. |
| R1 | Settlement topology; full-vector Brier/log-loss and paired baseline diagnostics; only earlier cases fit baselines; no raw score becomes a second ranking system. | Mapping diagnostics into reliability, shrinkage, recency/regime treatment, precision criteria, subgroup support, and acceptance regions. Requires genuine chronological predictions and outcomes. |
| B1 | Baseline estimand is the exact settlement distribution for the exact preference topology; unrelated markets are not pooled. | Estimator, root/parent structure, concentration, time window, regime treatment, uncertainty, and support criteria. Requires exact-line results and rolling-origin comparison. |
| B2 | Structural triviality requires both a near-automatic baseline and inadequate match-specific discrimination; the two conditions remain separate. | Boundary, discrimination/resolution measure, lift rule, uncertainty, and precision. Requires pre-outcome candidate and baseline predictions. |
| A1 | Evidence-backed failure cases, separate supporting evidence, explicit effect units, and no numeric inference from narrative. Unknown quantitative materiality cannot pass G8. | Effect/occurrence models, materiality mapping, ordering among comparable scenarios, thresholds, and precision. Requires observed cutoff-valid scenarios and later response evidence. |
| S1 | Reuse T15's component arithmetic only after the exact-preference reference resolver; unsupported component is UNKNOWN. | Empirical references, transforms, clipping, coefficient vector, regularization, and selection margins. Requires rolling-origin development and later validation. |
| S2 | Correlation annotation comes from exact settlement overlap and shared evidence/derived chains; no independent-vote credit; useful explanation must be assessed. | Dependence estimates, support, what counts as materially different, and usefulness criteria. Requires paired chronological errors and candidate-specific evidence. |
| C1 | Preserve distribution-level calibration; use an explicit protected manifest of exact prior F13 predictions and later-known outcomes. Known goals/corners alone are not calibration cases. | Fit window, parameter/profile values, identifiability, supported groups, and sufficiency. Requires prior compatible raw forecasts, exact later outcomes, and untouched validation. |
| U1 | G6 tail risk is probability mass outside the exact frozen G5 probability-constraint region under the identified joint uncertainty law. | The uncertainty law, calibration, supported domain, tail precision, and acceptable limit. Requires paired predictions, complete outcomes, and validation of the named event. |
| U2 | Probability-interval coverage, predictive coverage, and calibration are different claims. A single real outcome cannot establish latent-probability coverage. | Validation protocol, acceptance regions, confidence level, subgroup support, and misspecification response. Requires later chronological full-vector outcomes; known-truth simulations support only conditional diagnostics. |
| M1 | Use only the #12 reference families for their declared challenger roles; retain complete distributions, lineage, dependencies, and availability. Missing references are UNKNOWN. | Meaningful independence, eligible reference set by domain, conflict limits, boundary-crossing behavior, and precision. Requires paired later outcomes and distinct error behavior. |
| P1 | Diagnostic `RESEARCH_ONLY` and executable research recommendation policy are separate. Neither weakens a gate or authorizes production PLAY. | Every gate value, sample/precision rule, transform, weight, tie procedure parameter, and confidence band. Requires the predeclared #13 development and later validation protocol. |
| T1 | One fixed qualified set, a coherent simultaneous comparison, maximal non-dominated finalists, existing tie-break order only within that set, and UNKNOWN blocking an affected primary. | Joint law, interval procedure, block selection, confidence level, support precision, and ranking validation. Requires paired same-case scores, dependence-preserving blocks, and later unseen ranking evidence. |

The item IDs remain INCONCLUSIVE until their empirical method and profile are independently validated. Resolving semantics does not close any item that still has evidence-dependent fields.

## Consumer compatibility and blast radius

The versioned support envelope and consumer identities are part of this accepted contract. Implement them as successors; do not reinterpret old artifacts.

- **F13/T14.** F13 records exact raw and calibrated distributions, calibration identity, and availability. Its current contract emits no matching U1 tail-risk or U2 validation claim. Its reference outputs can reuse the primary surface, which is not an independent G7 challenger. A new support manifest must bind to the exact F13 result and cannot be discovered from a mutable latest-artifact scan.
- **F14.** `DecisionInputBundle` already binds the exact policy and CandidateInput bundle. A successor must bind the support envelope, preference-group resolver, and validation/reference identities. Its current parser rejects unknown fields and its current builder maps incomplete support to rejection. Keep that behavior for old artifacts and version any new schema and adapter.
- **T15.** `SelectionStrengthConfig` stores a policy-wide normalizer per component. `_selection_strength` applies it without preference identity. `_g6_gate` accepts a raw boolean, `_g7_gate` accepts scalar agreement/sensitivity without an eligible reference manifest, and `_g8_gate` only checks unrepresented materiality when an optional threshold is present. `CandidateInput.explanatory` defaults true. A successor must require explicit support references and values, preserve `UNKNOWN`, and reject absent required rules.
- **T15 ties.** `_is_tie` compares marginal intervals pair by pair and `_rank_survivors` sorts using that comparator. It cannot represent the paired covariance or simultaneous finalist set in the accepted successor contract. Keep its old policy reader; add the joint comparison only under a new consumer identity.
- **F15/F16 and selection.** Bind all successor F13/F14/T15 schemas, support manifests, profile digest, and group/tie rule identities to new PolicyVersion and run identities. Exact selected replay remains the only source after the common cutoff. Existing V1 and 0.1.0 results remain historical.
- **T18/T19 and #37.** Do not use V1 evaluation output or the synthetic T19 corpus as corrected V2 evidence. T18's current categorical Brier is divided by two and its log loss clips a zero forecast at its epsilon; 0.1.0 specifies an un-clipped infinite log loss. A future V2 evaluator must name its metric version and exact corrected cohort. Do not alter V1 results or silently mix six-hour V1 cohorts with chronology 0.2.0.
- **CB01/F19.** Reuse their exact enrollment, denominator, outcome attachment, settlement, and append-only correction identities. They preserve chronology and outcomes but do not establish CandidateInput eligibility or statistical sufficiency. Keep eligibility NOT_ASSESSED until a separate #70 profile names supported cases.
- **Storage.** Current F13/F14/F19 records use protected artifacts and do not require a SQLite migration for these contracts. Add no migration unless a future isolated proof shows existing artifacts cannot carry the versioned envelopes.

The tie-comparator risk was checked by calling the real `matchvet.t15._compare_results`: two overlapping marginal ties and one non-overlapping pair can produce a cycle among three candidates. That confirms the need for one joint multi-finalist comparison before declaring a T1 profile executable.

## Prospective evidence path and remaining blocker

Existing F06/F07, F11/F13/F14/F16, causal selection, CB01, and F19 provide most of the immutable record shapes. The completed #80/#84 code path has offline integration proof, but production causal activation remains refused. CB01's strict post-T/pre-kickoff witness proves existence of the already selected bytes at its signed time; it does not prove the inputs were collected before T. That proof comes from the exact #80 selection witness, and source capture identity, publication time, retrieval time, and corrections still need their own valid provenance.

There is no eligible retained V2 forecast cohort today. The inspected stores have result rows but no F13/F14 prediction contracts. The 35 retained source captures lack publication time and were retrieved after many historical kickoffs, so they cannot prove those earlier predictions existed. The T19 qualification corpus is synthetic. The existing evidence path has not been activated with live source data.

The main roadmap path is circular for #70 evidence: F17 depends on #70; F18 depends on F17; F20 depends on F18; and F21 collection waits for F18 and F20. A small diagnostic bootstrap must run the already specified F16 pipeline before F17/F20 without making a production recommendation. It can retain raw F13 output and a complete F14 `RESEARCH_ONLY` rejection where CandidateInput support is UNKNOWN. Such raw-only or uncalibrated cases may support only the development roles allowed by a later manifest; they cannot count as calibrated validation or final evaluation.

The minimum safe sequence is:

1. Implement the versioned F13/F14/T15 support and comparison seam in #85. Preserve V1 readers and the 0.1.0 method. Missing support remains UNKNOWN and cannot pass.
2. Build the bounded diagnostic bootstrap in #86. Use exact corrected F06/F07 and the #80 selection witness before T; retain every INCLUDED membership and preference before joining F16, CB01, or outcomes. Complete CB01 with its separate strict `T < signed genTime < own kickoff` witness. Attach later source-backed F19 outcomes and corrections by exact digest.
3. Run only after the approved source and causal witness profile are operationally authorized. Keep unavailable, unattempted, UNKNOWN, failed, VOID, and unsupported rows visible. Do not backdate publication or retrieval times, use legacy per-match cases as corrected cases, or refresh a selected graph.
4. Freeze separate case manifests for development/calibration, validation, and untouched final evaluation before using their outcomes. Reuse moves a case out of the untouched set. Estimate no sample floor until the metric-specific precision target is selected.
5. Resolve numerical profiles from those cases under #13. Keep #37 promotion and F17 publication blocked until their own contracts and acceptance criteria pass.

The minimum additions are the #85 versioned consumer contract and #86 pre-F17 bootstrap runner/case index. No general schema migration, F17 publication, F18 activation, F20 settlement automation, #37 fitting, or production activation is part of this plan.

## Status

#70 remains OPEN with `needs-info`. Acceptance of this contract does not mark it ready-for-agent or close it. The exact remaining blocker is the absence of a prospectively captured, corrected-chronology cohort with exact cutoff-valid inputs, F13 raw/calibrated predictions, and later source-backed outcome facts, plus the consumer seam required to preserve the accepted support semantics. No statistical profile can be selected until those cases exist and the predeclared development, validation, and final-evaluation split and metric-specific precision criteria can be evaluated.

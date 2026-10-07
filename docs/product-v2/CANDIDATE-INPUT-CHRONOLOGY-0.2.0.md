# Corrected Matchweek chronology

Contract name: `v2-candidate-input-chronology`. Document version: `0.2.0`.
Decision date: 2026-10-07. Status: structural chronology is frozen; numerical
derivation remains **INCONCLUSIVE, not executable**.

This successor record implements the chronology part of
[#77](https://github.com/Awisalas/match-vet/issues/77). It applies only to the
corrected Matchweek cohort. The released
[method 0.1.0](CANDIDATE-INPUT-METHODOLOGY.md) remains byte-for-byte unchanged and
continues to describe its legacy per-match-policy cohort. This record does not
relabel old observations or authorize pooling them with corrected evidence.

## One forecast origin

Every INCLUDED membership in the complete seven-league Friday-through-Monday
F06 freeze uses one forecast origin, common T. Its exact F07 policy uses
`MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME`. The initial corrected
policy explicitly sets `lead_time_seconds=21600`. Each per-membership cutoff
keeps its own membership and controlling revision identity while naming that T.
Equal timestamps under different freezes or policy digests are different cohorts.

All research collection, retention, history selection, preprocessing, fitting,
calibration, baseline construction, candidate derivation, adversarial review,
F13 results, F14 decisions and complete F16 publication finish before T.
The [selection owner](../matchweek-research.md) selects that complete graph once,
with the trusted postcommit acknowledgement required by #75. The exact indexed
selection and completion receipt must replay. An unreceipted slot never qualifies.

Case identity retains the exact selection digest, completion receipt digest,
logical season/Friday, F06 freeze and membership digests, controlling revision,
F07 policy digest/rule/common T, Preference Profile, and selected F16/F11/F13/F14
references. Selected F16 replay verifies every INCLUDED membership, the shared
F11 evidence set and the exact model and decision dependency closure.

## Frozen recommendations and later facts

Once selected, and always at or after T, recommendation inputs and decisions can
only replay their selected bytes. Newly discovered model-affecting evidence,
including evidence published before T but collected later, cannot create a revised
recommendation at the same cutoff. Method 0.1.0's same-cutoff revision allowance
does not apply to this corrected cohort.

A later fixture's frozen prediction cannot learn from an earlier fixture's
outcome inside the same Matchweek. All fixtures share the earlier origin T.
Later outcomes, source corrections and post-cutoff evidence may enter separate
F19 settlement and evaluation records. They never flow back into the selected
F11 evidence, F13 inputs/results or F14 recommendation.

Development keeps nested rolling origins over complete Matchweek blocks. Fitting
and rule selection at a later origin may use earlier outcomes only when their
retained availability permits it and the declared development role allows reuse.
Validation selects a frozen profile; final evaluation never selects the profile it
evaluates. Reused evaluation results lose their unseen status. Preserve fixture,
source-origin, shared-team and temporal dependence. Preference rows do not become
independent outcome units.

## Enrollment and evaluation admission

The denominator is the full INCLUDED membership × enabled-preference product
from exact F06 and the Preference Profile. Count it before joining F16, selection,
CB01 attempts, successful witnesses or outcomes. Missing lineage, failed witnesses
and unattempted rows remain explicit unavailable cases. F06 exclusions remain
visible with their own reasons outside the INCLUDED count.

Corrected enrollment requires the exact selected F16 and homogeneous corrected
F07 policy/common T across the complete cohort. CB01 still witnesses one fixture
batch under the strict rule `T < signed RFC3161 genTime < own controlling kickoff`.
A later fixture may receive its witness after an earlier kickoff. That witness
proves existence of committed bytes by genTime, not pre-T evidence collection,
and authorizes no refreshed evidence or decision. Exact old receipts, requests,
tokens and trust states retain their original contracts.

Corrected evaluation accepts only receipts replaying that exact selected lineage.
It retains unavailable denominator rows and uses explicitly named outcome
attachments and settlement versions, never a latest outcome lookup. F19 corrections
append with the exact predecessor and fixed manifest/match/decision/preference
identity. Missing outcomes stay unavailable; PUSH remains a distinct class and
VOID supplies no predictive score.

Legacy `KICKOFF_MINUS_LEAD_TIME` receipts remain legacy evidence even when one
timestamp equals T. Corrected evaluation refuses them and refuses mixed selection,
freeze, Profile, policy or boundary identities. Historical legacy replay remains
available through its original readers. Retrospective work retains that label;
later publication cannot prove a contemporaneous forecast.

## Numerical limits

This record chooses no estimator, fitted constant, confidence level, minimum
sample, normalization, risk mapping, gate threshold or tie profile. Method 0.1.0's
unresolved entries Q1, R1, B1/B2, A1, S1/S2, C1, U1/U2, M1, P1 and T1 remain
INCONCLUSIVE. U1/U2 estimand semantics and T1 multi-finalist comparison also remain
unresolved. Cohort integrity, a valid witness and deterministic replay do not
supply those missing numerical decisions or empirical validation. #70 remains
open with `needs-info`; F17 and promotion retain their existing gates.

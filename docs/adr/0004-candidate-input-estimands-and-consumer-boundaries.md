# CandidateInput estimands and consumer boundaries

Status: proposed for #70 review.

The CandidateInput contract should define uncertainty, coverage, finalist comparison, and support-resolution semantics before fitting any policy values. Keep the 0.1.0 methodology bytes and legacy cohorts unchanged; use a new versioned contract for a joint G5 tail-risk event, distinct empirical calibration and predictive-coverage claims, one coherent multi-finalist comparison, group-compatible normalization references, and fail-closed support manifests. This avoids treating a single realized outcome as latent-probability coverage, avoids cycles from pairwise tie checks, and prevents missing references or materiality from becoming favorable defaults.

## Considered options

- Keep each candidate's current marginal strength interval and compare pairs independently. This matches current T15 behavior but does not define a consistent tie relation for three or more finalists.
- Use one common joint uncertainty object for all qualified candidates and resolve only its maximal, not-robustly-dominated set. This preserves T15's score and tie-break order while giving the match one acyclic comparison.
- Use predictive outcome-tail probability as G6 tail risk. This would mix match randomness with uncertainty in the probabilities used by the policy gates.

## Consequences

F13/F14/T15 need versioned support and reference identities. F14 DecisionInputBundle, F15/F16 run identities, and replay must bind those exact identities. Existing V1 and 0.1.0 artifacts keep their readers and meanings. Numerical limits, profiles, support criteria, and promotion remain evidence-dependent.

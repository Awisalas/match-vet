# CandidateInput estimands and consumer boundaries

Date: 2026-10-09.
Status: accepted semantic contract. Methodology 0.2.0 remains non-executable.

## Context

The accepted #13 policy defines CandidateInput gates and Selection Strength, but
it does not fully specify the U1 tail-risk event, distinguish U2 coverage claims,
or define one coherent comparison for three or more finalists. Current T15 uses
pairwise interval overlap in a sorting comparator. Its consumer inputs also do
not bind the exact preference-group references or the evidence that supports
G6, G7, and G8.

These gaps must be settled before any numerical profile is fit. The successor
contract leaves methodology 0.1.0, chronology 0.2.0, released V1 artifacts and
readers, CB01 core, and historical cohorts unchanged.

## Decision

### U1 and U2

Define U1 as the probability mass, under the frozen joint uncertainty law for
the candidate's settlement-probability vector, that violates one or more
applicable G5 probability constraints in the exact PolicyVersion. The event
concerns uncertainty in the probabilities used by the gates. It does not measure
the predictive chance of an extreme realized score or count.

Keep U2 probability-interval coverage, predictive coverage, and calibration as
separate claims. Probability-interval coverage asks whether an interval contains
the latent conditional settlement probability. One observed outcome per match
cannot establish that claim. Predictive coverage asks whether the observed
settlement lies in a predeclared outcome region. Calibration compares full
settlement-probability vectors with observed class frequencies. A validation
record must name the claim it supports. Known-truth simulation supports only a
model-conditional probability-interval diagnostic.

### T1 across all finalists

After the frozen policy identifies the gate-qualified set, hold that set fixed
for comparison. Use one coherent joint uncertainty object and common supported
draws for every finalist. Derive every paired Selection Strength difference
from that object. A pair is robustly ordered only when its supported difference
region lies wholly on one side of zero. A supported region that contains zero
preserves the #13 paired Statistical Tie and its ordered tie-breakers.

The maximal finalist set contains candidates that no other finalist robustly
outranks. Apply the existing tie-break order only inside that set. Do not sort
three or more finalists with independent pairwise comparator calls. If required
support is UNKNOWN and could change the maximal set or its justified primary,
F14 returns `AVOID MATCH` with the versioned reason
`PRIMARY_SELECTION_UNRESOLVED`. Missing support is not a statistical tie.

### Explicit amendment to accepted #13

Amend #13 Section 2, item 4, and the final sentence of Section 6. The existing
text says:

> If one or more candidates qualify, exactly one becomes the Primary
> Recommendation and the production match decision is PLAY.
>
> The first candidate after this process is the single Primary Recommendation.

The amended contract says:

> If one or more candidates qualify, exactly one becomes the Primary
> Recommendation only when supported comparisons and tie-breakers identify a
> justified primary. If missing or UNKNOWN comparison support could change that
> primary, F14 records `AVOID MATCH` with the versioned reason
> `PRIMARY_SELECTION_UNRESOLVED`. An unresolved primary cannot produce PLAY.
>
> The first candidate after supported comparison and tie resolution is the
> single Primary Recommendation. If required support leaves the primary
> unresolved, F14 records `AVOID MATCH` with `PRIMARY_SELECTION_UNRESOLVED`.

This amendment preserves #13's gates, score, tie-break order, and production
fail-closed rule. It supersedes only the unconditional primary requirement and
the assumption that supported ranking always yields a first candidate. The
closed #13 issue remains an immutable historical record; this ADR is the
explicit successor contract.

### Support and UNKNOWN

Every required value has a protected derivation or support record with an exact
source, rule, profile, cutoff, group, and artifact identity. Keep `UNKNOWN`,
`UNPERFORMED`, `NOT_APPLICABLE`, `INVALID`, evidenced absence, and observed
evidence distinct. Missing or unsupported required support remains UNKNOWN and
cannot pass a gate, contribute a favorable score, or resolve a primary. A
RESEARCH_ONLY record may preserve the complete case and rejection reason, but it
cannot rank an unsupported candidate as qualified or emit a Primary
Recommendation.

Resolve normalization references by component and exact T10 preference through
the compatible hierarchy: preference family and exact line, role, league, then
supported context. A fallback must preserve the component's estimand and
settlement topology. Record the selected reference, ancestors considered,
fallback reason, and digest. If no supported compatible reference exists, the
component and dependent Selection Strength remain UNKNOWN.

G6 requires the named U1 event and a protected U2 validation record that names
its claim, method, topology, population, chronology, group, assumptions, and
diagnostics. G7 requires an exact eligible-reference manifest with complete
settlement distributions, ranges, dependencies, provenance, and availability.
G8 requires distinct supporting and failure evidence, materiality support, and
an exact uncertainty-representation reference when represented. Missing support
in any required G6, G7, or G8 field remains UNKNOWN and fails closed. A caller
boolean, optional threshold, default explanation, or missing reference cannot
turn UNKNOWN into a pass.

## Alternatives rejected

- Independent marginal intervals preserve current T15 behavior but can create
  non-transitive pairwise comparisons among three or more finalists.
- Predictive outcome-tail probability mixes match randomness with uncertainty
  about the probabilities that G5 evaluates.
- Resolving missing comparisons as ties lets missing evidence reach tie-breaks
  and can select a primary without support.
- A global normalizer ignores the exact preference contract and can exchange
  incompatible estimands or settlement topologies.

## Consequences and blast radius

- **F13/T14:** a versioned support manifest must identify exact distributions,
  uncertainty law, validation claims, reference groups, and availability. A
  mutable latest-artifact lookup cannot supply support.
- **F14:** a versioned `DecisionInputBundle` and result must bind the exact
  support, group resolver, policy, and comparison identities. The result must
  preserve `PRIMARY_SELECTION_UNRESOLVED` as an `AVOID MATCH` reason and replay
  it exactly. Existing schemas and readers retain their current behavior.
- **T15:** a successor consumer must resolve group references, reject missing
  G6/G7/G8 support, and compare all finalists from one coherent joint object.
  Current pairwise ranking and raw support inputs remain for their existing
  version only.
- **F15/F16:** successor run identities must retain the exact F13/F14/T15
  schema and support identities. This decision does not authorize F16
  corrective implementation.
- **F17 and evaluation readers:** future readers must preserve the versioned
  unresolved-primary reason instead of treating it as a statistical tie or an
  ordinary candidate rejection. This ADR does not authorize F17 work.
- **V1, 0.1.0, chronology 0.2.0, CB01, and historical cohorts:** preserve their
  bytes, meanings, readers, and enrollment. No migration or reinterpretation is
  authorized.
- **#85:** implement the versioned support-resolution and joint-comparison
  consumer contract. **#86:** remains dependent on #85 before it can capture
  prospective RESEARCH_ONLY cases.

No thresholds, coefficients, confidence levels, sample floors, priors, weights,
fitted values, or promotion criteria are selected here. U1's uncertainty law,
U2 validation procedures, group support, G6/G7/G8 numerical limits, T1 joint
law and interval procedure, and all empirical profiles remain evidence-dependent.

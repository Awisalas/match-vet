# F14 V2 preference and decision contracts

## Problem

F14 binds the founder's enabled preferences and one match decision to exact F10/F13 inputs. T10 owns the approved 37-market engine catalog and T15 owns hard vetting gates and deterministic selection strength. T15 research mode emits research candidates rather than a user-facing Primary Recommendation, so F14 needs a separate immutable result while preserving both V1 contracts and their behavior.

## Usage

```python
profiles = PreferenceProfileRepository(store)
profile = profiles.build_profile(enabled_preference_ids=founder_preferences)

decisions = DecisionRepository(store)
decision = decisions.build_decision(
    profile_digest=profile.digest,
    evidence_digest=evidence_digest,
    cutoff_id=cutoff_id,
    model_digest=f13_result_digest,
    policy=research_only_policy,
    candidate_inputs=candidate_inputs_by_preference,
)
assert decisions.replay(decision.digest) == decision
```

## Shape

`PreferenceProfile` is a frozen schema-versioned record containing the profile version, canonical enabled T10 preference contracts, and a separate engine capability name/version/digest. Its deterministic digest covers canonical JSON; it excludes timestamps and mutable lookups. The builder accepts preference IDs and resolves them only against `DEFAULT_PREFERENCE_CATALOG`, rejecting unknown IDs, duplicates, and any altered, prohibited, trivial, duplicate-line, or baby contract.

`DecisionResult` is a frozen single-match record containing the exact profile, F10 requirement catalog, F13 model result and uncertainty, cutoff/evidence/model references, T15 policy identity, one terminal vetting result per enabled preference, and either one `Primary Recommendation` or `AVOID MATCH`. It always carries `RESEARCH_ONLY`. The primary candidate retains estimated and conservative probability, confidence information, Data Quality, and Risk as separate values.

`PreferenceProfileRepository.build_profile/replay` and `DecisionRepository.build_decision/replay` are the public seams. Both publish and read canonical protected artifacts through `ArtifactStore`; there is no SQLite schema change. Decision replay resolves exact F11/F13 predecessors, checks fixture and profile identity, reconstructs F13 distributions and the frozen evidence state, and recomputes the result from retained policy and candidate inputs. No latest lookup is allowed.

Decision building adapts F13 calibrated distributions to the unchanged T15 interface and supplies a validated subset `PreferenceCatalog` for the enabled profile. T15 remains in `RESEARCH_ONLY` mode and applies its hard gates before ranking. F14 maps only a gate-surviving, quantitatively supported T15 research primary to its one user-facing Primary Recommendation. Missing calibration, UNKNOWN support, incomplete candidate inputs, or any failed gate yields a terminal reject; zero survivors yields AVOID MATCH. Qualitative candidate inputs can affect T15 gates and strength but cannot replace F13 quantitative probabilities. Odds are excluded from all F14 input contracts.

The single `matchvet.f14` module owns profile validation, exact lineage binding, T15 adaptation, terminal-result validation, protected persistence, and replay. This is a deep boundary: callers name exact inputs and receive a complete result without coordinating serialization or predecessor checks. Artifact schemas and T15's research-only vocabulary stay private to the adapter.

## Synthesis decision

Candidate B's explicit immutable `DecisionInputBundle` is the base because it makes the required evidence, profile, policy, and F13 references one complete input boundary; the cross-judge also preferred this shape for exact-reference validation. Candidate A's cohesive profile-bound repository is grafted in: both contracts and their integrity checks live in one F14 module, and the repository persists the exact build bundle for replay. Candidate B's separate service layer is rejected because it would add a pass-through call stage. Both candidates converged on exact artifacts, a T10 subset catalog, unchanged T15, and an F14-only RESEARCH_ONLY primary mapping.

## Tradeoffs accepted

- F14's artifact stores the exact policy and candidate input bundle, increasing protected artifact size in exchange for deterministic offline replay.
- F14 vets only enabled T10 preferences, so its result is profile-complete rather than claiming T15's 37-row full-catalog audit completeness.
- A RESEARCH_ONLY F14 Primary Recommendation is a research decision label and never a production PLAY.

## Alternatives considered

- A raw-input T15 wrapper exposing the T15 result directly hides little complexity: callers must interpret research candidates and separately validate profile/F13 lineage. It lost to the F14-owned result boundary.
- Separate profile, decision-service, and decision-repository modules expose temporal stages and force callers to coordinate them. They lost to one F14 module with two repositories around a cohesive profile-and-decision domain.

## Open questions and risks

- The existing F13 model result may be model-available while calibrated distributions remain unavailable; F14 must treat that state as unsupported for PLAY/Primary Recommendation.
- F14 must rebuild the same frozen T09 Evidence State represented by F13's exact inputs. Any mismatch must fail closed rather than be repaired with a new research call.

## Next implementation step

Implement the profile contract and protected round trip first, then add one decision slice that replays F13 and feeds its calibrated output to T15.

# Require verified odds after candidate selection

Date: 2026-10-15.
Status: accepted product rule by explicit owner instruction. Implementation is not authorized in this reconciliation.

The five-league reset requires verified decimal odds >= 1.20 for the exact selected preference at the frozen pre-lineup publication snapshot. Odds affect publication eligibility only. Selection, ranking, and tie resolution remain independent of odds. A failed gate never substitutes another preference. Missing odds remain UNKNOWN and fail the gate; internal diagnostics may still show the selected candidate.

The 1.20 floor is a product eligibility constraint. It makes no claim about predictive confidence, bookmaker value, or profitability and supplies no missing #70 statistical support. Publication still requires every other applicable research and policy gate.

[ADR 0010](0010-five-league-owner-alpha-reset.md) separately permits R4 to succeed as diagnostic owner-only Telegram alpha without manufacturing a recommendation or AVOID MATCH. The odds gate applies when publishing a recommendation; it does not turn unavailable recommendation qualification into an AVOID MATCH decision.

This prospectively supersedes the evaluation-only odds wording in blueprint section 3.6 and the glossary's statement that missing odds never block a recommendation. It also supersedes evaluation-only odds direction in Product V2 for the new route. The rule does not change released artifacts, readers, digests, historical recommendation membership, or replay semantics.

## Contract consequences

Current F14 decision inputs and F19 settlement evidence reject odds. The successor publication contract must retain the exact selected decision and separate its publication eligibility. It must not reinterpret an old F14 Primary Recommendation or AVOID MATCH, introduce odds into historical input contracts, or recompute old eligibility using today's price or defaults.

A selected candidate with failed publication eligibility is distinct from a completed research decision that rejects every preference. The successor must retain that distinction. Published-recommendation performance must distinguish eligible published recommendations from withheld candidates retained for diagnostics or evaluation. F19 settlement of a preference alone does not establish that a recommendation was published.

## Zero-spend boundary and subsequent decisions

Odds verification must require no paid data, inference, hosting, or other service. The repository has no qualified odds-verification capability contract. Existing retained CSV bytes may contain price columns, but that does not establish a verified offer at the required snapshot. This decision grants no live acquisition or source authority.

[ADR 0009](0009-sportybet-publication-snapshot.md) settles the publication contract by explicit owner instruction: one retained pre-lineup publication-time snapshot per match after selection, SportyBet Nigeria ordinary unboosted standalone pre-match prices, and retained owner-verified captures. Capture, durable commitment, and first Telegram publication all precede either team's confirmed lineup release. Later views use only the retained snapshot. Research and selected-graph chronology retain their original common cutoff. The [reconciliation](../design/refocus-reconciliation.md) records that no product or design decision remains open before specification.

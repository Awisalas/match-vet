# Separate SportyBet publication odds from frozen research

Date: 2026-10-15.
Status: accepted product decisions Q4-Q8 by explicit owner instruction. Documentation only; implementation and live acquisition remain unauthorized in this reconciliation.

The owner-alpha recommendation gate uses one retained, separately versioned publication-time odds snapshot per match after candidate selection. Capture, durable commitment, and first Telegram publication must all occur before either team's confirmed lineup is released. Later views use the retained snapshot only.

This odds snapshot can occur after the existing research cutoff. Research inputs, model results, ranking, and the exact selected preference remain frozen under their original selection contract. Only publication eligibility is assessed later.

SportyBet Nigeria is the fixed owner-alpha Reference Bookmaker. Only ordinary unboosted standalone pre-match prices qualify. Exclude boosts, promos, accumulator-only enhancements, free-bet or other conditional prices, and specials. There is no best-price shopping, bookmaker substitution, preference substitution, or odds-driven ranking. The [verified decimal odds floor of 1.20](0008-odds-publication-eligibility.md) remains unchanged.

Qualified retained owner-verified captures are permitted. They contain the exact fixture, market, side, line, decimal price, bookmaker, timestamp, and evidence. The evidence must establish the matching offer at the publication snapshot. Missing or unverifiable odds remain UNKNOWN and block recommendation publication. Internal diagnostics may retain the selected candidate.

## Chronology and compatibility

This prospectively separates the reset's later publication eligibility from ADR 0003's complete pre-cutoff research selection. Odds observations and eligibility records do not enter the old selected graph. A future publication record references the exact retained selection and its qualifying completion evidence. An unavailable or unqualified selection cannot be repaired by a valid odds capture.

This supersedes any active-direction reading that all publication-eligibility facts must exist by the research cutoff. It does not supersede the research deadline, change the causal witness proof, or amend historical artifact meaning. F14 and F19 retain their existing odds-input refusals and readers. Historical six/seven-league selection, settlement, recommendation, and replay contracts remain unchanged.

A frozen odds snapshot is retained exactly. Later price observations cannot silently replace its price or eligibility. Publication-blocked candidates remain distinct from AVOID MATCH and from published recommendations in the performance record. No published-recommendation count is inferred from a diagnostic candidate or preference settlement alone.

## Zero-spend and source qualification

Owner verification is a permitted alpha path that requires no paid odds feed. It does not establish that any SportyBet feed or offer is currently available, nor does it require an automated integration. Source identity, provenance, private retention, current source authority, and access-control refusal boundaries still apply. No bet, deposit, or purchase is required by this decision.

This decision approves neither a live acquisition nor a bookmaker API. Ambiguous fixture or market mapping, a different side or line, or incompatible period or settlement rules do not verify the selected preference. Unsupported timing or offer applicability remains UNKNOWN.

## Specification readiness

Q7 and Q8 settle the publication lifecycle and exact reference-offer policy above. [ADR 0010](0010-five-league-owner-alpha-reset.md) records the exact Q1-Q3 resolutions: all 37 preferences, diagnostic R4, and a separately versioned Owner-alpha Chronology Purpose preserving #70. The [reconciliation](../design/refocus-reconciliation.md) has no unresolved product or design decision that blocks moving to specification.

Qualification must establish that the capture supports the eligible offer at the retained snapshot and that capture, durable commitment, and first Telegram publication precede either lineup release. Unsupported timing, offer identity, or applicability fails closed. No numeric reuse window for older captures or current-price refresh is assumed. These evidence and contract obligations belong in the specification and subsequent qualification work; they do not reopen the settled product rules.

# Five-league reset reconciliation

Date: 2026-10-15.
Status: product and design decision frontier is empty; ready to move to specification. No implementation, issue changes, live acquisition, or runtime activation is authorized by this record.

The [blueprint](../../MATCHVET_PRODUCT_BLUEPRINT.md) is the product source of truth. The owner's [odds publication rule](../adr/0008-odds-publication-eligibility.md) is settled. Recommendations require verified decimal odds >= 1.20 at the frozen pre-lineup publication snapshot, after selection. Odds never rank candidates or substitute another preference. Missing odds are UNKNOWN and block publication. Diagnostics may still show the selected candidate.

The owner's exact settled-decision ledger is recorded below. [ADR 0010](../adr/0010-five-league-owner-alpha-reset.md) records Q1-Q3 and active reset supersession; [ADR 0009](../adr/0009-sportybet-publication-snapshot.md) records Q4-Q8. All eight questions are closed.

## Contradictions resolved by the blueprint

| Existing direction | Reset rule |
| --- | --- |
| ADR 0007 and current scope definitions include Portugal in six active leagues. | New active work covers ENG, ITA, ESP, GER, FRA through an explicit successor. |
| Existing cost wording excludes ordinary hosting from its paid-data restriction. | The normal workflow requires no paid dependency across data, inference, hosting, storage, or developer services. |
| Product V2 plans intelligence, external service, apps, and subscriptions. | Telegram owner alpha is the delivery priority. The blueprint parks those expansions. |
| F17 and pipeline wiring depend on #70. | Five-league plumbing and diagnostic Telegram alpha proceed independently of #70 fitting. A changed decision policy still requires a successor ADR/version. |
| Historical glossary wording listed incomplete research as an AVOID reason. | Failed or unfinished research remains incomplete. Completed qualified vetting with insufficient support can justify AVOID MATCH. |
| Older odds prose treats prices as optional evaluation context. | The new publication gate requires verified decimal odds >= 1.20 after selection. Historical optional-odds behavior remains unchanged. |

The blueprint already specifies issue dispositions. #37 and #93 are parked, #94 follows the analysis/Telegram slice, #100's six-scope objective and #101 are superseded, and #1 remains historical. #70 remains evidence-policy research. No issues have been changed in this reconciliation.

## Historical boundaries

Seven-league and six-league contracts keep their original versions, bytes, digests, readers, denominator membership, migrations, and replay. In particular, active-scope v2, F01 schema4, and F06 policy3 continue to mean six leagues. The odds rule is prospective and does not retroactively disqualify historical recommendations.

Selection slots remain keyed by season and Friday, independent of scope version. Existing occupied weeks cannot be replaced or requalified. Successor activation uses a declared future unoccupied week after qualification. The actual date is an activation choice.

Friday-through-Monday membership, Africa/Lagos display, the explicit 21600-second common cutoff, and selected-graph chronology remain in force. A separately versioned pre-lineup publication-time odds snapshot follows selection and can occur after the research cutoff. It references the unchanged selected state and affects publication eligibility only.

ADR 0006 already accepts private RESEARCH_ONLY source-use risk. That acceptance is not publisher permission, source completeness, or beta distribution authority. ADR 0006 and its pinned bytes remain unchanged.

## Closed decisions

| ID | Topic | Status |
| --- | --- | --- |
| D1 | Founder preference set | Retain all 37 preferences, including Full-Match Total Corners Over 8.5, 9.5, and 10.5. |
| D2 | Initial Telegram milestone and policy qualification | R4 may succeed as a reproducible diagnostic owner-only RESEARCH_ONLY Telegram alpha without manufacturing a recommendation or AVOID MATCH. Failed or unfinished research remains incomplete. |
| D3 | Private owner-alpha assurance and authority purpose | Create a separately versioned Owner-alpha Chronology Purpose independent of #70, preserving its accepted assurance and refusal rules. Preserve existing #70 purposes, authorities, profiles, policies, artifacts, and replay. |
| D4 | Publication snapshot timing | Separate versioned pre-lineup publication-time odds snapshot after candidate selection. Frozen research inputs retain the existing cutoff. |
| D5 | Reference bookmaker | SportyBet for owner alpha, narrowed to SportyBet Nigeria by D8. No best-price shopping. |
| D6 | Owner verification | Qualified retained owner-verified captures are permitted with exact fixture, market, side, line, price, bookmaker, timestamp, and evidence. Unverifiable or missing odds are UNKNOWN and block publication. |
| D7 | Publication unit and deadline | One retained odds snapshot per match after frozen candidate selection. Capture, durable commitment, and first Telegram publication all occur before either team's confirmed lineup release. Later views use the retained snapshot only. |
| D8 | Exact reference offer | SportyBet Nigeria ordinary unboosted standalone pre-match prices only. Exclude boosts, promos, accumulator-only enhancements, free-bet or other conditional prices, and specials. |

## Settled-decision ledger audit

The documentation audit checked every owner-supplied rule against these records. Every ledger decision is recorded exactly.

| Settled rule | Blueprint | Glossary | Accepted ADR |
| --- | --- | --- | --- |
| All 37 preferences, including total corners O8.5/O9.5/O10.5 | Section 3.5 | Initial Preference Set | 0010 |
| Diagnostic owner-only R4 without manufactured recommendation or AVOID MATCH | Sections 1 and R4 | Diagnostic Telegram Alpha; AVOID MATCH | 0010 |
| Separate versioned owner-alpha chronology purpose preserving #70 | Section 9 | Owner-alpha Chronology Purpose | 0010 |
| Verified decimal odds >= 1.20 only after selection, without ranking or substitution | Section 3.6 | Selected Candidate; Odds Publication Gate | 0008 and 0009 |
| Research and selection frozen at the existing cutoff | Sections 3.4 and 3.6 | Matchweek Research Cutoff; Frozen Publication Snapshot | 0009 and 0010 |
| One separate retained pre-lineup publication snapshot per match; later views use it only | Section 3.6 | Frozen Publication Snapshot; Pre-lineup Recommendation | 0009 |
| Fixed SportyBet Nigeria reference with no best-price shopping | Section 3.6 | Reference Bookmaker | 0009 |
| Qualified retained owner captures with fixture, market, side, line, price, bookmaker, timestamp, evidence | Section 3.6 | Publication Odds Evidence | 0009 |
| Missing or unverifiable odds are UNKNOWN and block publication | Section 3.6 | Odds Publication Gate | 0008 and 0009 |
| Capture, durable commitment, and first Telegram publication precede either confirmed lineup | Section 3.6 | Pre-lineup Recommendation | 0009 |
| Ordinary unboosted standalone pre-match prices only, excluding promotional and conditional prices | Section 3.6 | Eligible Reference Offer | 0009 |

## Specification readiness

No genuinely unresolved product or design decision blocks moving to `$to-spec`. The blueprint, accepted decisions, historical compatibility boundaries, and fail-closed requirements provide the specification inputs.

The specification must carry forward the remaining evidence qualification and define successor contract acceptance at existing application, artifact, and adapter boundaries. No numeric quote-age allowance, alternative bookmaker, research refresh, or replacement candidate is assumed. Source availability, timing evidence, and an executable zero-cost authority plan remain qualification obligations, not unanswered product choices.

## Evidence qualification required after the decisions

The reset requires a no-cost source capability matrix for all five leagues and a qualified SportyBet Nigeria owner-verification path. Existing fixture/history coverage cannot establish current offer availability. Football-Data parsing excludes odds from normalized facts, even though an exact retained input may contain odds columns. The dated September provider probe is not proof of present prices or market coverage. No automated odds feed, paid account, deposit, or purchase is required as an architectural dependency.

Odds qualification must distinguish a missing quote, a verified quote below 1.20, and a verified qualifying quote. Each remains tied to the same selected preference. A price change after the frozen snapshot cannot silently refresh eligibility.

Exact market matching includes period and settlement semantics. A different line or ambiguous handicap mapping cannot verify the selected preference. The retained evidence must establish the eligible SportyBet Nigeria offer at the publication snapshot; an old capture's timestamp alone does not establish current availability. Timing qualification must also establish capture, durable commitment, and first Telegram publication before either team's confirmed lineup release. Unsupported offer identity, timing, or applicability remains UNKNOWN. No extra owner decision is needed to refuse such evidence.

Independent causal/source authority provisioning also needs an executable zero-cost plan. Restoring local Store bytes alone does not establish current authority or rollback independence. Source unavailability or unqualified authority blocks the affected operation rather than creating a paid dependency or weakening refusal rules.

## Evidence pointers

- [Historical scope and successor boundaries](../adr/0007-six-active-leagues-without-paid-data.md).
- [Accepted five-league diagnostic alpha and independent chronology purpose](../adr/0010-five-league-owner-alpha-reset.md).
- [Common-cutoff selected-graph chronology](../adr/0003-causal-matchweek-selection-witness.md).
- [Conditional witness purpose](../adr/0005-research-only-causal-witness-trust-premises.md).
- [Private source-use risk decision](../adr/0006-research-only-public-source-automation-risk.md).
- [F14 decision contract](../f14-v2-decision-contract.md) and [odds-input refusal](../../src/matchvet/f14.py).
- [F19 settlement contract](../f19-v2-settlement-contract.md).
- [Source authority purpose](../../src/matchvet/source_authorization.py), [causal authority purpose](../../src/matchvet/causal_activation.py), and [independent source checkpoint](research-source-authorization.md).
- [Existing ingestion](../../src/matchvet/ingestion.py) and [dated provider probe](../research/upcoming-fixture-provider-capability-2026-09-23.md).

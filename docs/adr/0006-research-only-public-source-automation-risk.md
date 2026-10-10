# Accept public-source automation risk for private RESEARCH_ONLY work

Date: 2026-10-10.
Status: accepted by explicit product-owner instruction on 2026-10-10.
Scope: private/prospective RESEARCH_ONLY MatchVet source use only.

## Context

The earlier source decisions required affirmative publisher/upstream permission
before automated acquisition and durable retention. That requirement prevented
specification of prospective #70 source mechanics even where public sources
were technically usable. The product owner now explicitly accepts the legal,
terms-of-use and database-rights risk of automatically retrieving publicly
accessible information and retaining what MatchVet requires for private research.

## Decision

Replace permission-before-automation for this scope with the internal basis
`PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED`. This is **product-owner risk acceptance**,
never publisher approval, a licence, permission granted or rights clearance.
External permission remains UNKNOWN or REFUSED unless genuine external evidence
establishes a grant. Known restrictive terms remain recorded; they are not
silently converted into permission. Acceptance covers the source-use risk of
such restrictions within this private research scope.

Eligible source classes are public documented APIs, JSON/XML/CSV feeds,
downloadable datasets, ordinary public webpages, fixture/result/statistical
pages, official league/club/federation information, weather and contextual
sources, and their derived statistical/model inputs. Required raw/exact and
normalized retention and private backup/restore/offline replay are included.
Prefer an explicitly open/licensed documented API or dataset, then a public
machine-readable feed, then a documented public page, then HTML extraction only
where no better reliable source exists. No paid dependency is introduced.

The policy permits specifying and implementing these source-use mechanics. It
does not activate a provider, authorize a live run or replace independently
trusted runtime source authorization. No acquisition is authorized in this
decision task. Causal owner configuration, independent checkpoint, signed
approval and event-valid TUF admission remain separate, unprovisioned gates.

## Technical and evidence boundaries

- Never bypass authentication, paywalls, CAPTCHAs, WAF/anti-bot mechanisms or
  access controls; use stolen/private credentials; exploit undocumented
  authenticated/private endpoints; impersonate users; or evade account/IP bans.
- Respect explicit provider rate limits. Use bounded timeouts, retry limits and
  backoff, request/byte budgets and pacing. Do not overwhelm sites. Technical
  refusal makes a source unavailable; do not change identity or route to evade it.
- Retain provider/publisher identity, exact URL/endpoint, retrieval time,
  publication/update time where available (otherwise UNKNOWN), response/content
  digest, necessary exact raw representation, normalized facts, upstream lineage,
  parser/adapter version, request outcome, freshness, coverage and risk basis.
- HTTP 200 does not establish completeness; an empty response does not prove no
  fixtures. Repeated websites are not independent ancestry. Unknown freshness
  stays UNKNOWN; expired evidence stays STALE. Never fabricate facts or times.
- F01/F06 completeness, F07 chronology, F11 evidence quality, CandidateInput,
  released source hierarchies, F13/F14/F16 and causal-selection gates are unchanged.
  Missing evidence remains UNKNOWN, never ABSENT. LF02 attestations and LF05
  manual observations remain separate from Provider Attempts and Provider Health.
- New risk-based captures are private/protected and nonredistributable. No
  commercial, PLAY, Product Promotion or statistical validation is inferred.

## Retention, withdrawal and compatibility

Implement a versioned source-use decision binding an explicit immutable manifest
of the exact graph's dependencies and this policy identity/digest. Overall
APPROVED means internal authorization for that graph, not a publisher grant.
Record external permission separately from the internal risk basis. V1 records,
historical registry meanings and historical capture/receipt bytes remain intact.

Before acquisition require current internal authorization for the source,
operations, purpose and technical limits. Before #86 continuation require exact
selected-graph authorization; later F19 acquisition has its own outcome source
manifest. Recheck current policy/withdrawal at dispatch and admission. Changed
terms/access conditions require review and an exact new retained classification;
do not automatically inherit a prior grant or authorization. Restrictive terms
can still receive explicit current owner risk authorization within this scope.
Owner withdrawal or uncertain authorization stops new acquisition/continuation.
Historical inspection retains original evidence and classification; later
adverse evidence may refuse present use without rewriting historical cases.
Replay/restore uses retained bytes, never mutable live retrieval, and does not
restore acquisition capability merely by restoring Store contents.

## Why

This records the owner's actual choice rather than inventing external rights.
Separating source-use risk from evidence quality allows technical work while
preserving UNKNOWN, chronology, immutable replay and promotion boundaries.
The [automated closure assessment](../research/automated-prospective-source-closure-2026-10-10.md)
identifies the remaining technical work. The older permission-before-automation
planning and #88 outreach remain historical; no permission request succeeded
merely because this decision supersedes their gate.

# MatchVet five-league reset implementation spec

Date: 2026-10-15.
Status: authoritative implementation specification for the settled reset, version 1.0. Documentation only; implementation and runtime activation remain pending.
Repository baseline: `b30e98f177bd1c62dbb29963a9e87eb7abd0f51a`.

## Problem Statement

The owner cannot yet run a trustworthy five-league weekly research loop and inspect it through Telegram at zero required spend. Existing implementations span historical seven-league and six-league contracts. Current source coverage and operational authority are not qualified for the new route, expensive repeated verification impedes normal development, and the old publication chain depends on unresolved decision-policy machinery.

The reset must make useful owner-only research diagnostics available without pretending that unavailable policy support is a recommendation or AVOID MATCH. When a recommendation is justified, a separate publication gate must verify the selected preference's SportyBet Nigeria odds and pre-lineup publication timing. Both the research state and later publication snapshot must be reproducible without rewriting historical evidence.

## Solution

Deliver a local-first five-league weekly system with the CLI as the engineering/operator interface and Telegram as the owner release/testing surface. Keep private SQLite and content-addressed artifacts authoritative. Introduce explicit successor contracts alongside the released implementations, then move one responsibility at a time into named owners.

The first owner milestone is a reproducible diagnostic Telegram alpha. It can complete without a qualified recommendation or AVOID MATCH. Recommendation publication becomes available only when the research selection, decision policy, exact SportyBet Nigeria offer, source authority, and publication chronology independently qualify. Odds affect publication eligibility after selection and never influence ranking or cause preference substitution.

The settled blueprint and ADRs 0008-0010 govern product meaning. This spec defines implementation obligations and acceptance criteria under those decisions. Historical contracts govern their retained artifacts and replay. A contradiction discovered during implementation requires an explicit planning amendment, never an implicit reinterpretation.

## User Stories

1. As the owner, I want exactly ENG Premier League, ITA Serie A, ESP LaLiga, GER Bundesliga, and FRA Ligue 1 in new active work, so that the reset has a fixed scope.
2. As the owner, I want historical Portugal and Belgium records retained, so that earlier research and replay remain trustworthy.
3. As the owner, I want every normal operation to require no paid service, so that I can build and test MatchVet on existing hardware.
4. As the owner, I want source capability and failure states for every active league, so that a successful HTTP response cannot hide an incomplete slate.
5. As the owner, I want empty schedules distinguished from unknown schedules, so that missing data never proves that no matches exist.
6. As the owner, I want unresolved fixture and team identities exposed, so that MatchVet cannot silently omit or misidentify a match.
7. As the owner, I want immutable Friday-through-Monday membership, so that later schedule changes cannot rewrite the original slate.
8. As the owner, I want one common research cutoff six hours before the earliest exact included kickoff, so that later matches receive no later research advantage.
9. As the owner, I want exact source captures, attempts, provenance, and evidence states, so that I can inspect what was and was not established.
10. As the owner, I want UNKNOWN, evidenced absence, unperformed work, and failed work distinguished, so that research gaps cannot become favorable evidence.
11. As the owner, I want all 37 founder preferences retained, including total corners Over 8.5, 9.5, and 10.5, so that unavailable data does not silently shrink the product.
12. As the owner, I want explicit model and calibration availability, so that an available raw model cannot masquerade as validated confidence.
13. As the owner, I want diagnostics before a recommendation policy qualifies, so that the first Telegram milestone delivers useful research without invented decisions.
14. As the owner, I want failed or unfinished research to remain incomplete, so that AVOID MATCH retains its meaning as a completed decision.
15. As the owner, I want a separate versioned owner-alpha chronology purpose, so that alpha can progress independently of #70 without changing its historical contracts.
16. As the owner, I want source and causal authority checked independently, so that permission to inspect retained evidence cannot authorize new collection.
17. As the owner, I want interrupted work to resume only against exact retained inputs, so that restarts cannot change the information boundary.
18. As the owner, I want one strongest justified selected preference when the policy supports it, so that MatchVet does not manufacture volume or competing recommendations.
19. As the owner, I want odds excluded from candidate selection and tie resolution, so that price cannot steer the research decision.
20. As the owner, I want verified decimal odds of at least 1.20 before a recommendation is published, so that every published recommendation satisfies the settled product floor.
21. As the owner, I want SportyBet Nigeria as the fixed reference, so that MatchVet cannot shop across bookmakers for a passing price.
22. As the owner, I want ordinary unboosted standalone pre-match prices only, so that promotions and conditional enhancements cannot satisfy the floor.
23. As the owner, I want qualified retained captures I verify myself accepted during alpha, so that a paid or automated odds feed is not required.
24. As the owner, I want each odds capture to name fixture, market, side, line, price, bookmaker, timestamp, and evidence, so that the offer can be checked against the selected preference.
25. As the owner, I want missing or unverifiable odds to remain UNKNOWN and block publication, so that a guessed or stale offer cannot pass.
26. As the owner, I want a blocked selected candidate visible in diagnostics, so that publication refusal does not erase the research result.
27. As the owner, I want no replacement preference when the odds gate fails, so that a price failure cannot restart candidate selection.
28. As the owner, I want one retained publication-time odds snapshot per match, so that later views reproduce the original eligibility evidence.
29. As the owner, I want capture, durable commitment, and first Telegram publication before either team's confirmed lineup, so that publication remains pre-lineup.
30. As the owner, I want uncertain publication timing exposed and refused, so that local clock labels cannot create chronology assurance.
31. As the owner, I want later views to use only the retained snapshot, so that MatchVet never silently updates a recommendation's price or qualification.
32. As the owner, I want only configured owner chat IDs accepted, so that the alpha remains private.
33. As the owner, I want Telegram secrets outside Git and research artifacts, so that reproducibility does not expose credentials.
34. As the owner, I want `/week` to show the frozen Matchweek and league coverage, so that I can see whether the slate and research are complete.
35. As the owner, I want `/today` to show eligible frozen matches in Africa/Lagos time, so that a current query does not reacquire or change membership.
36. As the owner, I want `/match <id>` to distinguish research, decision, publication, and settlement state, so that diagnostic progress cannot be mistaken for a recommendation.
37. As the owner, I want `/health` to expose source, authority, data, and run failures separately, so that a single healthy label cannot conceal a blocker.
38. As the owner, I want `/record` derived from immutable published-recommendation and settlement identities, so that research candidates cannot inflate the performance record.
39. As the owner, I want pending and conflicting outcomes visible, so that missing results do not become losses, wins, or VOID by default.
40. As the owner, I want corrections appended with exact predecessors, so that earlier decisions and settlements remain independently inspectable.
41. As the owner, I want league, family, policy, scope, and chronology cohorts identified, so that aggregate metrics cannot conceal incompatible or unsupported populations.
42. As the owner, I want all included matches and enabled preferences retained in the research denominator, so that failed or unattempted work cannot disappear from evaluation.
43. As the owner, I want backup and restore to preserve artifacts and refusal behavior, so that recovery cannot restore withdrawn collection authority.
44. As an implementer, I want named domain owners and application boundaries, so that each change has a clear responsibility without a repository-wide rewrite.
45. As an implementer, I want fast, standard, replay, and heavy test lanes, so that frequent feedback remains practical on the development device.
46. As an implementer, I want verification counts and elapsed-time measurements, so that a faster device cannot hide repeated graph traversal.
47. As a reviewer, I want explicit successor dispatch and historical golden replay, so that a five-league change cannot reinterpret six/seven-league bytes.
48. As the owner, I want rollout gates and reversible activation steps, so that offline implementation cannot silently become a live release.
49. As the owner, I want evidence-based policy qualification before predictive claims, so that a running bot cannot imply Production Promotion.
50. As the owner, I want a closed beta only after technical, evidence, source-use, and zero-cost gates pass, so that broader access follows demonstrated readiness.

## Implementation Decisions

### 1. Scope and unchanged preference contracts

New active routes bind the ordered five-league set ENG/ITA/ESP/GER/FRA and the exact season, contract identity, version, and digest. Portugal and Belgium cannot enter the Target Match scope of new active acquisition, admission, freeze, research capture, publication, or active-cohort reporting. Their retained rows may coexist in the same Store and remain readable under historical contracts. Relevant cross-competition Research Context may still inform a five-league Target Match; it cannot create another recommendation league or Target Match.

Every founder profile for this reset enables the same 37 exact preferences. Availability never changes profile membership.

| Preference group | Exact retained selections or lines | Count |
| --- | --- | --- |
| Match Winner | Home, Draw, Away | 3 |
| Double Chance | 1X, X2, 12 | 3 |
| Asian Handicap | Home or Away at 0.0, +1.0, +1.5, -1.0, -1.5 | 10 |
| Match Goal Overs | Over 1.5, 2.5, 3.5 | 3 |
| Team Goal Overs | Home or Away Over 1.5, 2.5 | 4 |
| Half Goal Overs | First-Half Over 1.5; Second-Half Over 1.5 | 2 |
| Full-Match Total Corners Over | Over 8.5, 9.5, 10.5 | 3 |
| Corner Match Winner | Home, Draw, Away | 3 |
| Team Corners Over | Home or Away Over 3.5, 4.5, 5.5 | 6 |
| Total | Existing exact preference identities and settlement rules | 37 |

Keep all Under markets, every Over 0.5 line, trivial corner totals, cards, duplicate handicap lines, and other markets outside the existing founder catalog excluded. Do not change period, side, line, handicap type, regulation-time, extra-time, or settlement semantics to match a bookmaker offer. Engine Market Capability remains distinct from the enabled Preference Profile.

### 2. Completion, decision, and publication are separate claims

The application result exposes workflow completion, research availability/sufficiency, decision qualification, publication eligibility, publication evidence, and settlement independently. These are contract meanings; implementation may choose concrete enum names while preserving the distinctions.

| Condition | Required meaning |
| --- | --- |
| Missing coverage, unfinished acquisition, crash, interrupted required research, or invalid predecessor | Incomplete workflow with exact progress and reasons. No manufactured recommendation or AVOID MATCH. |
| Declared diagnostic work completes, but decision policy or quantitative support is unavailable | Completed diagnostic result with explicit availability and qualification. No claim of a completed recommendation decision. |
| A required investigation completes without establishing a fact | UNKNOWN evidence, distinct from ABSENT and UNPERFORMED. Downstream use follows the qualified policy. |
| Qualified completed vetting justifies no preference | AVOID MATCH with exact policy, reasons, and lineage. |
| Qualified vetting identifies one justified preference | One Selected Candidate, independent of odds. Publication remains a separate gate. |
| Selected Candidate has missing, unverifiable, ineligible, or sub-1.20 odds, or unqualified timing | Publication withheld with retained reasons and diagnostic candidate. No substitution and no odds-induced AVOID MATCH. |
| Selection, decision, offer, authority, timing, and first publication qualify | Published RESEARCH_ONLY recommendation with exact publication evidence. This is not production PLAY. |

R4 succeeds as an owner-only diagnostic alpha. Completion means its declared diagnostic obligations have run and their retained results are reproducible for every included match and all 37 preferences. It does not mean every model is available, a scientific claim is validated, or a recommendation policy exists. Required work that was never performed cannot be relabeled as a completed investigation. A whole-Matchweek diagnostic completion claim requires complete admitted coverage and a complete diagnostic manifest, even though incomplete progress may be inspected.

The current F14 mapping from unsupported inputs to terminal decisions must not supply a manufactured active reset outcome. Add an explicit successor diagnostic contract capable of representing an unavailable decision. Historical F14 artifacts and their readers retain their original meanings. When a real policy is available, actual vetting still requires its full supported inputs and exact lineage.

### 3. Named ownership and application seams

Use a strangler migration. The following are responsibility owners, not a requirement to create every package before product work.

| Owner | Responsibility and boundary |
| --- | --- |
| Scope | Immutable active/historical scope identities, ordered membership, explicit version dispatch, and active-route exclusion. |
| Scheduling | Source-backed fixture identities, coverage assessment, semantic completeness, membership freeze/observation, and common-cutoff derivation. |
| Evidence | Research requirements, attempts, provenance, OBSERVED/ABSENT/UNKNOWN distinctions, freshness, material conflicts, and exact frozen evidence. |
| Prediction | Cutoff-valid history, model inputs/results, calibration availability, uncertainty, and reproducible quantitative outputs. No odds access. |
| Decision | All enabled preferences, supported policy gates, justified comparison, and the single Selected Candidate or qualified AVOID MATCH. No odds access. |
| Chronology and source authorization | Owner-alpha purpose, complete-graph selection and witness validation, exact source-use decisions, current authority, withdrawal, and restoration continuity. Separate source and causal authorities remain separate capabilities. |
| Publication | SportyBet Nigeria offer validation, the post-selection 1.20 gate, one retained snapshot per match, publication commitment, and publication qualification. It cannot select a preference or modify research. |
| Settlement | Exact retained result evidence, unchanged grading semantics, pending/conflicting outcomes, and append-only corrections. Odds do not enter grading. |
| Evaluation and record | Exact cohorts, research denominators, publication/settlement joins, chronological evaluation, and transparent read projections. No invented qualification. |
| Compatibility | Historical readers and adapters, closed version dispatch, and access to retained seven/six-league contracts. No implicit upgrade. |

The application layer coordinates these owners. Prefer the existing `AnalyzeMatchweek` start/resume/inspect boundary and T04 lifecycle for the analysis slice. Add successor request/result dispatch there rather than a second competing run coordinator. Add only the application boundaries needed for later publication and `SettleMatchweek`; publication is not another analysis pass. Read queries return exact domain progress and result identities for both CLI and Telegram.

Source adapters, owner-capture import, Telegram transport, and SQLite/content-addressed persistence implement narrow interfaces. Domain owners do not perform network I/O or depend on Telegram formatting. The Telegram adapter contains no model math, evidence policy, fixture completeness, source authorization, settlement, or database schema logic. Private persistence owns canonical encoding, integrity, bounded transactions, and durable publication.

No new Txx ownership modules. Existing Txx/Fxx/LFxx implementations remain compatibility implementations until a responsibility is safely extracted. Target new modules below approximately 600 lines; justify more than approximately 800 and create no new module above 1,200 lines. Do not expand a giant legacy module when a coherent owner can be safely introduced. Broad file moves, arbitrary rewrites, and a cleanup prerequisite for every product change are excluded.

### 4. Successor contracts and retained identities

Define canonical, immutable contracts and closed dispatch before enabling their writers. Exact numeric version allocation and media names are implementation details to freeze in the affected contract change; existing numbers cannot be reassigned.

| Boundary | Successor obligation | Historical invariant |
| --- | --- | --- |
| Scope and acquisition plan | Bind the exact ordered five-league contract, season, digest, request scope, and source capability. | Seven-league scope v1 and six-league scope v2 keep their bytes and meaning. |
| F01 coverage/admission | Add an explicit five-league contract/schema and mixed-Store filtering, retaining attempts, freshness, coverage, identity resolution, and health references. | Historical F01 v2/v3 seven-league and v4/schema4 six-league readers remain unchanged. |
| F06 membership and observation | Add an explicit policy paired only with the five-league F01 contract. Preserve LF14 semantic integrity, controlling evidence, cumulative conflicts, and immutable observations. | Policies 1/2 retain seven leagues; policy3 retains six. The freeze envelope is not reinterpreted. |
| F07 cutoff | Bind exact successor membership and the explicit 21600-second common rule. | Old per-match and common-cutoff states keep their exact lineage. |
| F11/F12/F13 and run inputs | Carry scope, owner-alpha purpose, freeze, cutoff, evidence/attempt, model, availability, and exact input identities where required. | Reusable primitives remain unchanged under their retained readers; reuse supplies no new chronology claim. |
| Diagnostic result and whole-week manifest | Retain each included match and all enabled preferences, actual research/model references, explicit missing support, and the absence or exact identity of a qualified decision. | Do not coerce this result into an existing F14/F16 schema that requires a different terminal meaning. |
| Research selection and completion | Admit the complete successor graph under a versioned graph validator and owner-alpha purpose, preserving causal proof, unique logical selection, durable commit, and exact receipt replay. | Old graph validators, witness profiles, receipts, and occupied slots retain their original meaning. |
| Publication snapshot and evidence | Bind the exact selected research state, fixture, selected preference, reference offer, capture evidence, gate policy, commitment, timing qualification, and first-publication evidence. | This later state is outside the original research closure and never modifies F14 or F19 odds-input contracts. |
| Capture/cohort/evaluation | Retain scope, purpose, graph, profile, policy, chronology, availability, and explicitly selected outcomes. | Historical capture indexes, CB01 core, cohorts, and enrollment proofs are not upgraded or pooled. |
| Settlement and record | Bind exact compatible selection/decision/preference and outcome/correction identities; separately join publication evidence for recommendation performance. | Historical F19 identities, evidence, grading, and correction chains replay unchanged. |

Shared logical research selection/completion slots remain keyed by season and Friday independently of scope or protocol version. A five-league successor cannot select, replace, backfill, or requalify a week already occupied under six/seven-league or failed selection history. An existing qualified selection supports exact replay only. A new effective week must be explicitly declared and unoccupied.

Do not mutate shared league catalogs, released migrations, canonical encodings, digests, historical manifests, or released artifact meanings. Preserve mixed-Store replay. Unknown versions, incompatible contract pairs, wrong scope ordering, omitted scope identity, foreign graph references, and cross-purpose references fail closed. Historical replay never discovers current defaults or mutable latest inputs.

Prefer the existing Store and ArtifactStore representation. No migration is preauthorized or assumed necessary. A migration is justified only by a demonstrated representation need and requires an additive forward migration, replay proof, and recovery plan. Restore does not grant current acquisition or publication authority.

### 5. Research chronology and independent owner-alpha purpose

The Matchweek is the declared Friday-through-Monday calendar window in Africa/Lagos. Retain canonical UTC timestamps and official local kickoff zones where available. Freeze requires every one of the five Fixture Scopes to be COMPLETE or source-backed CONFIRMED_EMPTY. PARTIAL, UNKNOWN, STALE, unresolved blocking identities, and missing required health evidence prevent a complete freeze. All-scope affirmative-empty coverage may produce an empty freeze, but cannot invent a controlling kickoff or a cutoff.

An affirmative-empty Matchweek may report its retained empty coverage and membership, with research/decision/odds work explicitly not applicable. It cannot manufacture a research cutoff, a recommendation, or a chronology-qualified selected research graph from an absent kickoff.

For nonempty admitted membership, the initial common research cutoff T is the earliest exact INCLUDED kickoff minus the explicitly supplied 21600 seconds. Excluded fixtures and retained Portugal/Belgium rows cannot control T. All prediction-relevant collection, preprocessing, history selection, fitting, calibration, baseline/candidate derivation, and selected diagnostic/decision computation remain on the accepted pre-T side of the boundary. Earlier publication does not make evidence collected after T eligible.

Create a separately versioned private RESEARCH_ONLY Owner-alpha Chronology Purpose independent of #70 corpus collection. Carry forward the accepted conditional authority premises and refusal rules. Explicit successor purpose, source-use policy/authority, graph, selection/completion, and consumer contracts are required wherever the old purpose is bound. A caller flag or changing an issue number in old bytes cannot supply that authority.

Preserve the accepted causal sequence: the complete exact graph is durable and uniquely selected before constructing the fresh witness commitment; the authenticated remote event's qualified upper bound must be strictly before T. Local wall time remains advisory. Known authority invalidation, profile mismatch, missing current approval, uncertain continuity, invalid metadata, incomplete graphs, or late/ambiguous evidence refuse. Do not weaken permanent occupied-slot, one-operation capability, restart, or missing-receipt rules.

A diagnostic graph whose structure differs from the historical full F11/F13/F14/F16 graph needs explicit successor graph/profile validation. Preserve the original timing proof and authority premises; do not claim that an unchanged historical profile already certifies a different closure. Every required per-match diagnostic result must be represented before the graph can qualify. Unknown numerical support remains explicit and supplies no recommendation permission.

Existing #70 purposes, authorities, profiles, policies, cohort roles, artifacts, and replay remain intact. Owner-alpha evidence is not automatically admitted to #70 fitting, production evaluation, or a historical CB01 cohort. Any later consumer must explicitly admit the exact successor population under its frozen methodology. Conditional chronology assurance is not predictive validation.

### 6. Source and odds qualification at zero required spend

Normal build, testing, and operation require no paid data API, inference API, hosting, database, queue, monitoring, CI, developer service, account upgrade, deposit, or purchase. Use existing local hardware and qualified no-cost resources. A free tier that requires payment for the normal workflow cannot become a dependency. Qualification failure leaves the affected operation unavailable.

Create one retained capability matrix and executable acquisition plan for the five leagues. Cover each required capability separately, including upcoming fixtures, historical inputs, context, and results. Prefer operationally usable official sources, then qualified open/licensed data, qualified public machine-readable sources, and bounded permitted public-page extraction.

The matrix must identify:

- Exact provider, publisher, upstream lineage, endpoint/query, competition, season, window, and capability.
- Upcoming-fixture completeness, current-season scope, pagination/partition closure, kickoff precision, team identity, and result/settlement fields.
- Publication/update time when evidenced, observation/retrieval time, parser version, exact raw representation, normalized provenance, and digests.
- Freshness rules and their support, failure classifications, rate limits, request/byte budgets, bounded timeouts/retries/backoff, and fallback behavior.
- External rights status separately from internal risk acceptance, exact intended operations, private retention/replay/backup restrictions, and source authority requirements.
- Which of COMPLETE, CONFIRMED_EMPTY, PARTIAL, STALE, or UNKNOWN each observed condition supports, with reproducible retained evidence.

HTTP success proves neither completeness nor authorization. A historical-results feed does not prove upcoming-fixture or odds health. Related feeds sharing ancestry do not supply independent corroboration. Internal manual citations remain labeled manual and cannot claim automated complete-current coverage.

ADR 0006's private source-use risk acceptance remains unchanged and is never publisher permission. No authentication, paywall, CAPTCHA, WAF, access-control, or ban-evasion bypass is allowed. Respect provider limits and technical refusal. New owner-alpha acquisition, odds-capture admission, graph continuation, and outcome acquisition need appropriate exact successor source-use representation and current authority. Existing source manifests do not implicitly authorize a new stage or purpose.

Qualification must produce an executable zero-cost source/causal authority and independent checkpoint plan. Its continuity state must remain independent of the Store/history rollback domain. Saved approvals or copies of all local files cannot prove present authority. Recheck withdrawal/currentness at the correct protected boundaries. No weakened guarantee is justified by lack of a free service.

For odds, SportyBet Nigeria is fixed. Qualify ordinary unboosted standalone pre-match prices only. Exclude boosts, promos, accumulator-only enhancements, free-bet or other conditional prices, and specials. Never shop for another bookmaker or a different preference.

Qualified retained owner-verified captures are a valid alpha path; an automated feed is not required. Each captures exact fixture, market, side, line, decimal price, bookmaker, timestamp, and evidence. The evidence must establish the actual eligible offer at the publication snapshot. Retain source/offer identity, provenance, capture/import/verification times as distinct facts where applicable, and the verifier's classification. Do not invent a source publication time or treat import time as observation time.

Match exact period, handicap type, line, side, and settlement semantics against the unchanged preference. Ambiguous mapping, an absent field, or unverifiable freshness, applicability, or offer classification is UNKNOWN and fails publication. An evidenced excluded offer type is ineligible and also fails publication. An old CSV price column, an unsupported owner boolean, or a timestamp without offer evidence cannot pass. No numeric age allowance or reuse window for old captures is assumed.

### 7. Post-selection publication contract

Recommendation publication has two independent prerequisites: a qualified fixed Selected Candidate and qualified publication eligibility. The odds owner never supplies prediction features, ranking values, tie-breaks, replacement preferences, or a price/value score. A numerically adequate price cannot repair an unavailable policy or invalid research selection.

The floor is verified decimal odds >= 1.20, inclusive. Compare the exact retained decimal value without rounding a sub-threshold value upward. A verified 1.19 fails the floor; a verified 1.20 meets only the price condition. Missing or unverifiable odds remain UNKNOWN. Both cases withhold publication and retain the diagnostic candidate, without creating AVOID MATCH.

Each match has one retained, separately versioned pre-lineup publication-time odds snapshot after candidate selection. The snapshot may occur after T, but it references the unchanged selected research graph and exact selection/completion identities. Its later offer/timing facts do not enter that earlier closure. Do not mint another snapshot by changing an ancillary version or re-running analysis for the same selected match.

The snapshot/commitment contract retains at least:

- Scope, purpose, Matchweek, fixture/membership, profile, exact selected preference, decision/policy qualification, selected graph, and completion references.
- SportyBet Nigeria offer identity, exact decimal odds, qualified capture/evidence digests, verification classification, and gate version/result/reasons.
- Capture event evidence, durable commitment identity and event evidence, lineup-boundary evidence, and the intended reproducible message/format identity.
- Separate first-publication attempt and receipt/evidence references; secrets never enter any retained research/publication artifact.

Capture, durable commitment, and first Telegram publication must all precede release of either team's confirmed lineup. The earlier lineup release controls. Starting lineups and any post-T match facts are used only to establish publication eligibility/timing or later evaluation, never to revise research or select another preference.

The publication chronology qualification method must establish all three event orderings, account for suspension and network delay, and retain the exact evidence and assumptions. A local clock label, a pre-T research witness, a request-start timestamp, or failure to find a lineup does not prove first Telegram publication was timely. Missing or ambiguous timing fails closed. If no qualified method exists, recommendation publication remains disabled while diagnostic alpha can operate within its own qualified boundary.

Persist the exact snapshot and durable commitment before dispatch. Record first Telegram publication evidence separately after the external event, without rewriting the committed record. Distinguish eligibility, attempted dispatch, confirmed first publication, and ambiguous/failed publication. A send attempt alone is not a published recommendation; a Telegram acknowledgement is not proof that a human read the message.

A timeout or crash cannot justify fresh odds, a replacement preference, a fabricated receipt, or an unbounded retry. Transport recovery can reuse only the exact committed snapshot/message and must preserve the pre-lineup first-publication rule. If prior publication is ambiguous, retain that uncertainty and require evidence-based reconciliation rather than assuming success or no send. Later historical queries never create a new first recommendation publication or promote a blocked candidate.

Later views use the retained snapshot only and identify its time and qualification. They must not show a current-price claim from old evidence, refresh odds, rerank, or reinterpret historical eligibility. Corrections append their own evidence and cannot retrospectively turn a late or unqualified first publication into a timely one.

### 8. Telegram owner alpha and operational queries

Use local long polling for owner-only alpha. Plain HTTP through the existing requests dependency is the initial approach; add a framework only for a concrete demonstrated need. No hosting service or inbound webhook is required.

Accept only configured owner chat IDs. Keep Telegram token and other secrets outside Git, immutable artifacts, URLs in logs, and retained failure payloads. Bound polling, sends, retries, message sizes, and failure handling. Keep deterministic formatting independent of network access.

The initial command surface stays fixed:

| Command | Required application result |
| --- | --- |
| `/week` | Exact active five-league frozen Matchweek, coverage by league, run/research completion, decision availability, and publication summary. |
| `/today` | Eligible matches today from that exact frozen Matchweek using Africa/Lagos boundaries, without new acquisition or membership changes. |
| `/match <id>` | Exact match research/model state, all-preference audit access, decision qualification, selected diagnostic candidate or qualified AVOID MATCH, separate publication state/snapshot, and settlement references. |
| `/record` | Exact cohort/version and retained published-recommendation/settlement projection, plus separate diagnostic/withheld/avoid/unavailable counts. |
| `/health` | Source capability, coverage, data, source/causal authority, timing qualification, and run failures as separate dimensions. |

The active Matchweek and source artifacts must be selected explicitly through application identity/configuration. A human-friendly current-week query may resolve a stored active reference, but cannot silently use a historical six/seven-league default or discover a different model, outcome, or snapshot. No frozen active week is an explicit state, not a newly fabricated empty slate.

Commands are owner inspection/research surfaces; they do not place bets, start conversational AI, provision accounts, change policy, or imply live acquisition authority. Diagnostic messages label RESEARCH_ONLY and unvalidated decision confidence. Legacy candidate, research-avoid, Primary Recommendation, and PLAY labels are not silently translated across contract versions. No production PLAY or unsupported confidence label is introduced.

### 9. Settlement, transparent record, and chronological evaluation

Keep outcome acquisition separate from analysis and later odds qualification. Use exact retained result evidence and authorized outcome-source dependencies. Preserve T10 grading semantics and F19 exact selection/manifest/match/decision/preference lineage. Add successor adapters only where the new graph identity requires them; do not put odds into F19 evidence.

Retain PENDING, CONFLICTING, WIN, LOSS, PUSH, and VOID distinctly. Unknown or insufficient outcomes stay pending; unresolved conflicts are not VOID. Preserve existing source hierarchy and complete result requirements for halves and corners. Do not derive missing counts from a score or a favorable source. Corrections retain the same settlement identity, append replacement evidence with an exact predecessor, and preserve every earlier version.

`/record` counts published recommendations only when exact publication qualification and first-publication evidence exist. A settled preference, a diagnostic selected candidate, or an eligible snapshot without established publication is not a published recommendation. Show diagnostic, withheld, incomplete, qualified AVOID, pending, conflicting, and ambiguous-publication populations separately. An empty recommendation cohort is a valid record, not an excuse to fabricate recommendations during R4/R5.

Every record projection pins its scope/purpose/cohort, profile, model and policy versions, chronology, exact publication identities, and chosen settlement/correction versions. A newer correction creates a new projection; it does not rewrite an earlier report. Count PUSH and VOID separately from wins and losses and expose pending/conflicting evidence. Retain league, preference-family, and supported-line breakdowns without hiding sparse or unsupported subgroups in an aggregate.

The research/evaluation denominator is the complete INCLUDED membership × enabled-preference product before joins to available models, witnesses, publications, or outcomes. Missing and unattempted cases remain visible. F06 exclusions remain separately accounted for. Recommendation performance uses the distinct published subset, with gate-failure and publication-availability selection effects disclosed. Odds-floor filtering does not prove predictive improvement.

Preserve chronological development, later validation, and untouched final evaluation. Do not learn from an earlier fixture's outcome within the same already frozen Matchweek. Preserve fixture, team, source-lineage, and time dependence; 37 preference rows are not 37 independent matches. Old and new scope/purpose/chronology populations cannot be pooled implicitly. CB01 evidence retains its original enrollment meaning and never proves a different pre-T collection or later pre-lineup publication claim.

R6 must derive the minimum defensible decision contract from admissible evidence. No estimator, score component, gate limit, weight, sample floor, normalizer, uncertainty validation, or promotion threshold is invented here. Unsupported components remain UNKNOWN. Any structural change to #70/ADR 0004 requires its own ADR and version, with supported comparison and unresolved-primary behavior preserved until explicitly superseded.

Carry forward ADR 0004's separate U1/U2 estimands and validation claims, exact compatible normalization references, supported G6/G7/G8 inputs, and coherent joint comparison of finalists while that decision applies. Missing comparison support cannot become a tie or justified primary. Evaluate calibration, Brier score, log loss, uncertainty reliability, false positives, subgroup robustness, non-triviality, and cross-family comparison under predeclared chronology and metric uncertainty. These requirements establish no convenient numerical defaults and do not block the diagnostic milestone.

### 10. Verification cost and persistence discipline

Separate immutable graph verification from current-authority validation. Within one logical operation, verify a fixed immutable dependency graph once and pass a private verified context to child operations that use that exact graph. Revalidate at the real current-authority boundary and preserve detection of withdrawal, expiry, identity changes, rollback, and invalidation during validation/admission.

This is not permission to delete per-write safety checks or skip existing final-currentness boundaries. If several independently protected admissions require fresh authority, retain the required checks while sharing immutable validation work. One-operation authority cannot survive operation exit, Store close/reopen, fork, or an unrelated request. No global cache or cross-operation trust reuse is allowed.

Record graph/candidate resolutions, immutable/source-manifest verification counts, current-authority checks at each required boundary, child count, and elapsed time. Multi-match regression cases must demonstrate that unchanged graph verification does not grow per child. Scaling improvements must preserve all refusal behavior; a small fast fixture alone is insufficient proof.

Keep existing private Store, single-writer constraints, short transactions, artifact digests, durable synchronization, and verified recovery. Network requests and model computation stay outside write transactions. Retain curated summaries needed to justify a decision; raw generated audit runs remain outside committed product documentation. A concise current-status document reports qualified capabilities and remaining evidence obligations.

### 11. Rollout phases and safe implementation sequence

These phases define scope and gates, not tickets. Keep WIP at one implementation unit. Offline tests and local configuration never imply activation. Each subsequent implementation unit must have one product outcome, exact historical contracts, acceptance criteria, test lanes, model/effort choice, and rollback notes.

| Phase | Deliverable and sequence | Exit and activation gate |
| --- | --- | --- |
| R0: adopt and specify | Preserve the accepted blueprint, glossary, ADRs, reconciliation, and this spec. Record existing issue dispositions as planning intent. | Settled ledger traceable and no runtime changes. Ticket creation and issue changes remain separate authorized work. |
| R1: five-league successor | First freeze the scope/acquisition/F01 contract; then F06/F07 closed pairing and mixed-Store dispatch; then carry exact identity into downstream graph/consumer contracts. | All five active leagues only; Portugal/Belgium excluded from new routes; six/seven golden replay and occupied-slot refusal. No live activation. |
| R2: practical development | Establish test-lane selectors, reproduce and remove repeated immutable graph verification, document dependency ownership/first safe extraction, and curate current status/audit-output policy. | Device measurements and count regressions improve with unchanged authority/refusal behavior. Only defects that obstruct later work block product progress; no broad rewrite. |
| R3: qualify no-cost sources | Qualify the five-league capability matrix, result/history/context limitations, exact source-use representations, and an executable independent-authority plan. | Coverage/identity/precision/freshness demonstrated from retained evidence. Unqualified capabilities remain unavailable. Provisioning and live runs require their own exact current authority. |
| R4a: diagnostic owner alpha | Introduce owner-alpha purpose and diagnostic request/result/whole-week graph contracts; preserve causal qualification; connect real application progress to CLI and owner-only Telegram queries. | One admitted Matchweek has reproducible per-match/all-preference diagnostics and honest completion. Missing policy never manufactures recommendation/AVOID. Diagnostic milestone does not wait for #70 numerical fitting. |
| R4b: publication contract capability | Implement and prove the separate SportyBet Nigeria capture, snapshot, commitment, timing qualification, message, and first-publication boundaries using controlled evidence. | All odds/chronology/refusal cases pass. Live recommendation publication stays disabled until source, authority, actual decision policy, and publication timing each qualify. This does not block R4a. |
| R5: settlement and record | Connect exact authorized outcomes to compatible F19 settlement and corrections; build immutable record projections. Preserve diagnostic and full-denominator outcome evidence where its contract permits it. | Reproducible WIN/PUSH/LOSS/VOID/pending/conflicting records, exact cohort/version identity, empty recommendation cohort supported, and no diagnostic counts inflated into recommendations. |
| R6: minimum defensible policy | Use genuinely chronological admissible five-league evidence under a frozen development/validation/evaluation plan. Produce explicit policy/support and structural successor decisions where needed. | Executable evidence-justified profile, UNKNOWN/refusal rules, supported markets/groups, non-triviality, comparison, calibration/uncertainty, and promotion criteria. No production promotion is inferred. |
| R7: closed research beta gate | Qualify the complete technical workflow, evidence readiness, publication timing, recovery, performance, source-use/distribution basis, and sustainable zero-spend operation. | All technical/evidence gates pass. Otherwise remain owner-only. Neither a running bot nor calendar pressure opens access. |

R4b's implementation can be proven offline before R6, but a qualifying live publication must wait for actual policy support. R5 can deliver an honest empty published-recommendation record and explicitly labeled research outcomes; it does not depend on inventing recommendations to generate policy evidence. Diagnostic evidence receives no automatic #70 development/validation/final-evaluation role.

Within every successor slice, implement canonical identity and refusal rules first, then exact reader/replay, then protected writer/admission, then application dispatch, and finally adapter exposure. Prove corruption and historical coexistence before activating a new writer. Extract only the responsibility required by that slice. Do not combine a broad refactor with changed behavior unless the old seam demonstrably prevents the behavior.

Activation starts with a declared future unoccupied Matchweek after relevant qualification and current source/causal authority provisioning. Introduce diagnostic access before gated recommendation publication. Record exact installed versions, active references, purpose, owner configuration, and qualification evidence. Do not switch the historical CLI's meanings by silently changing a shared default; new active behavior is explicit.

Rollback disables successor acquisition/publication and returns the operator to inspection or the previously qualified mode. It never rewrites artifacts, removes occupied slots, restores old approvals as current authority, or downgrades readers so that new records acquire old meanings. Preserve compatible readers and retained evidence. Any additive storage change requires verified private backup, forward/recovery behavior, and tested refusal on unsupported versions.

### 12. Acceptance criteria

Each criterion is mandatory for the capability or phase it names. A diagnostic R4 exit does not claim later criteria have passed.

| ID | Observable acceptance |
| --- | --- |
| AC01 | New active requests and retained identities enumerate exactly the five ordered leagues; Portugal and Belgium are refused as Target Matches at every new entry point and excluded from active membership in mixed stores. Relevant Research Context does not enlarge recommendation scope. |
| AC02 | Historical seven/six scope, F01/F06/F07, graph, capture, settlement, and report bytes/digests/readers replay unchanged; pinned ADR 0006 and released migrations are untouched. |
| AC03 | Each scope preserves COMPLETE/CONFIRMED_EMPTY/PARTIAL/STALE/UNKNOWN rules, exact identities and health; missing or empty responses do not establish complete coverage. |
| AC04 | Membership and observations retain LF14 semantic integrity; common T uses the earliest exact INCLUDED five-league kickoff minus explicit 21600 seconds, without excluded or historical-scope contamination. |
| AC05 | All 37 exact preferences remain enabled and visible, including total corners 8.5/9.5/10.5; unsupported families remain explicit rather than being removed. |
| AC06 | R4 returns reproducible diagnostic results and qualification status without forced recommendation/AVOID. A crashed or unperformed required process cannot become completed research. |
| AC07 | Owner-alpha purpose, graph validation, authorities, and consumers are explicitly versioned. Old #70 approvals and purposes cannot authorize the new route or be reinterpreted. |
| AC08 | The whole exact selected research graph qualifies under the accepted pre-T causal proof; late work cannot qualify; occupied weeks and missing/invalid completion evidence refuse replacement or backfill. |
| AC09 | Odds never enter prediction, candidate ranking, tie resolution, or F19 grading. Failed odds cannot trigger another preference, bookmaker, profile, or analysis pass. |
| AC10 | A verified eligible 1.20 price passes the floor; a lower price fails without upward rounding; missing, unverifiable, ambiguous, or nonmatching offers are UNKNOWN and withhold publication. |
| AC11 | Only SportyBet Nigeria ordinary unboosted standalone pre-match prices qualify. Every excluded promotion, boost, accumulator enhancement, free-bet/conditional price, and special refuses. |
| AC12 | Qualified owner captures retain all eight required fields and exact evidence; absent fields, fabricated timing, or mismatched period/settlement/line cannot verify the preference. No automated feed is required. |
| AC13 | Each selected match has one retained separate odds snapshot. Research/selection bytes remain unchanged after it; later views and recovery use that same snapshot only. |
| AC14 | Qualified evidence establishes capture, durable commitment, and first Telegram publication strictly before either confirmed lineup. Unknown, equal, late, or ambiguous timing cannot qualify. Suspension or network delay must be accounted for; either blocks qualification when it makes the required event ordering late or unproven. |
| AC15 | Publication qualification, dispatch attempts, and established first publication remain distinct. A crash/timeout cannot invent a receipt, a new snapshot, or a timely first send. |
| AC16 | Only configured owner chat IDs are served; the five command contracts are deterministic; secret tokens stay outside Git, artifacts, and retained logs. Querying cannot mutate frozen research. |
| AC17 | Settlements retain pending/conflicting and exact WIN/LOSS/PUSH/VOID semantics, source evidence, chosen outcome versions, and append-only corrections without rewriting research or publication. |
| AC18 | `/record` counts only exact established published recommendations, separates avoids/withheld/diagnostic/unavailable cases, and pins cohort/version and correction references. The full research denominator remains intact. |
| AC19 | Backup/restore preserves mixed historical/successor replay and publication evidence. Missing independent continuity or withdrawn authority refuses new operations after restore. |
| AC20 | Multi-match verification-count regressions demonstrate operation-scoped immutable reuse with no cross-operation trust reuse; withdrawal/expiry/identity/refusal cases remain enforced. |
| AC21 | Normal operation and all required qualification paths have no required paid service. Missing no-cost qualification leaves the affected capability disabled rather than selecting a paid fallback. |
| AC22 | Policy and beta readiness are evaluated under explicit chronological, subgroup, uncertainty, source-use, recovery, and operational gates; diagnostics and conditional chronology alone establish no predictive reliability or production PLAY. |

### 13. Settled-decision traceability

| Settled rule | Implementing sections | Acceptance |
| --- | --- | --- |
| All 37 preferences, including total corners Over 8.5, 9.5, 10.5 | 1 and 2 | AC05, AC06 |
| Diagnostic owner-only R4 without manufactured recommendation/AVOID MATCH | 2, 8, and 11 | AC06, AC16 |
| Separate versioned owner-alpha chronology purpose preserving #70 | 4 and 5 | AC02, AC07, AC08 |
| Verified decimal odds >= 1.20 only after selection; no ranking or preference substitution | 6 and 7 | AC09, AC10 |
| Frozen research cutoff distinct from later publication eligibility | 5 and 7 | AC04, AC08, AC13 |
| One retained per-match publication snapshot and retained-only later views | 7 and 8 | AC13, AC15 |
| Fixed SportyBet Nigeria reference with no best-price shopping | 6 and 7 | AC09, AC11 |
| Qualified owner captures with all eight required fields and exact evidence | 6 and 7 | AC12 |
| Missing/unverifiable odds are UNKNOWN and block publication | 2, 6, and 7 | AC10, AC12 |
| Capture, durable commitment, and first Telegram publication before either confirmed lineup | 7 | AC14, AC15 |
| Ordinary unboosted standalone pre-match prices only; excluded promotional/conditional offers | 6 and 7 | AC11 |

## Testing Decisions

### Application seams and prior art

Use the highest existing public seam that proves observable behavior. The primary analysis seam is `AnalyzeMatchweek` start/resume/inspect with real temporary Store and protected artifacts, bounded deterministic source inputs, and controlled authority/time transports. Extend its existing tests for durable progress, exact input binding, incomplete manifest refusal, and selected replay into the new diagnostic route. Do not assert success by calling private helpers that bypass admission.

Publication needs one new cohesive application seam because it occurs after research selection. Test that seam from owner-capture admission through retained snapshot/commitment and controlled Telegram publication, then replay the resulting record. Settlement/record use the existing exact settlement build/correct/replay boundary and a read projection. Prefer these few application/repository seams over a mock network between every module.

Existing prior art includes successor F01/membership-policy coexistence and corruption tests; mixed-Store and occupied-week graph replay; F15 durable progress and exact resume; F14 preference/decision lineage; F19 settlement/correction replay; causal owner activation and source-authorization withdrawal/rollback tests; CB01 denominator/outcome attachment tests; and T17/T19 recovery and release qualification. Reuse retained fixtures and golden expectations under their original contracts. New five-league fixtures do not replace the six/seven goldens.

Good tests prove externally visible contracts: selected identities, immutable bytes/digests, durable results, refusal states, resource/verification budgets, and reproducible messages. Avoid tests that merely mirror implementation branches or require a particular file arrangement. Use real persistence where atomicity, protection, replay, and recovery are the claim. Model and parser unit tests remain appropriate for pure numerical or normalization boundaries.

### Test lanes

The repository currently exposes recorded end-to-end and failure-injection markers, not the complete reset lane scheme. R2 must provide explicit deterministic selectors and documented commands for the following lanes. Do not describe new marker names or commands as already available. Every critical contract case must have a declared lane and remain included in milestone selection.

| Lane | Purpose and required contents | Trigger |
| --- | --- | --- |
| Fast | Focused pure domain/parser tests, exact price/offer/preference checks, deterministic Telegram formatting, and directly affected contract tests. No live network. | Every implementation unit; practical for repeated device use. |
| Standard | Real temporary Store, acquisition/admission to freeze, analysis start/resume/inspect, diagnostic completeness, publication application slice, settlement and record joins, owner-only adapter behavior. | Affected domain slice before completion. |
| Replay | Retained historical golden bytes/digests, closed dispatch, mixed five/six/seven stores, old capture/cohort/settlement/report readers, occupied slots, and backup-format compatibility. | Any scope, dispatch, persistence, artifact, authority-purpose, replay, or compatibility change. |
| Heavy | Full zero-cost recorded weekly loop, causal/source authorization, failure injection, crash/restart, recovery/restore, and integrated successor release qualification with representative scale. | Milestones and changes that alter these guarantees. Not every formatting or narrow pure-domain edit. |

Verification performance has a dedicated regression budget alongside these lanes. Measure both call counts and elapsed time on the supported device with the same multi-match fixtures. Once-only immutable graph verification is a deterministic contract; required fresh current-authority checks are not removed to meet a count target. Establish and retain device measurements before setting a numerical runtime ceiling; no arbitrary seconds budget is invented here.

Required case families include all acceptance criteria and, specifically:

- Every coverage state, affirmative-empty versus missing responses, unresolved identities, conflicting revisions, and excluded fixtures affecting neither membership nor T.
- Every exact preference and banned alternative, unavailable model/calibration/support, all-diagnostic and all-qualified-avoid weeks, and failed research that stays incomplete.
- All authority purposes, wrong keys/profile/pins, changed terms, withdrawal during validation/admission, old saved checkpoints, close/reopen, fork, rollback, and occupied-week cross-version attempts.
- 1.20 exactly, sub-threshold decimals, missing/verifiably ineligible offers, country/bookmaker mismatch, every excluded enhancement, wrong side/line/period/settlement, and incomplete owner evidence.
- Later odds with invariant research selection, one retained snapshot, equal/late/unproven lineup order, suspended commitment/send, a lost response, and read-only historical views after lineups.
- Publication/settlement/report identity joins, all pending/conflicting/VOID/PUSH cases, explicit correction snapshots, unavailable denominator rows, and no inflation from 37 correlated preferences.
- Unauthorized chat IDs, missing token/configuration, deterministic formatting, bounded transport failures, secret redaction, and no network in formatting tests.
- Content corruption, orphan bytes, sync/commit failure, interrupted resume, mixed-store restore, lost current continuity, and repeat/recovery behavior that preserves refusal.

Routine implementation tests use deterministic retained or synthetic evidence and controlled transports. Live source or timing qualification is an explicit bounded operation under current authority, with retained evidence; a passing mock is not proof of real coverage, rights, chronology, or predictive validity. Broad suite baseline failures and device resource limitations must be recorded distinctly from new regressions. A known baseline does not waive a critical integrity or release criterion.

No runtime tests or qualification runs are authorized merely by writing this spec. Implementation units will select the applicable lanes when authorized.

## Out of Scope

- New active Portugal/Belgium support, replacement leagues, dynamic scope reduction, or removing preferences because data is unavailable.
- Any new betting market, Under selection, Over 0.5 line, cards, trivial corner total, changed settlement rule, or duplicate handicap.
- Odds-driven selection, price/value optimization, best-price shopping, alternative-bookmaker fallback, replacement preferences, refreshed research, or second publication-price snapshots.
- Automated SportyBet integration as a prerequisite, bet placement, deposits, free-bet workflows, promotions, affiliate flows, or bookmaker account management.
- Invented statistical components or thresholds, automatic #70 cohort-role assignment, production PLAY, Production Promotion, or validated-confidence claims from diagnostics.
- Trend, Comparable Match, Regime, or Failure Pattern Intelligence as reset dependencies.
- REST service, web/native/Expo clients, user account systems, subscriptions, payments, marketing automation, or chatty AI conversation.
- Required paid infrastructure or developer services, access-control bypass, or widening private source-risk acceptance into permission or distribution rights.
- Repository-wide rewrites, broad file moves, edits to released migrations/ADRs/artifacts, requalification of occupied weeks, or historical byte/digest repair.
- Creating tickets, changing GitHub issues/labels/dependencies, live activation, implementing runtime code, or publishing this spec to the tracker in this authoring task.

## Further Notes

### Authority and source documents

The [product blueprint](../../MATCHVET_PRODUCT_BLUEPRINT.md), [settled reconciliation and ledger audit](refocus-reconciliation.md), and [domain glossary](../../GLOSSARY.md) define current product intent and vocabulary. [ADR 0008](../adr/0008-odds-publication-eligibility.md), [ADR 0009](../adr/0009-sportybet-publication-snapshot.md), and [ADR 0010](../adr/0010-five-league-owner-alpha-reset.md) record the accepted publication and reset decisions. This spec carries all their settled rules forward; it supplies no replacement answers.

Relevant retained contracts are the [active-scope and F01/F06/F07 contract](../active-fixture-scope.md), [research selection repository](../matchweek-research.md), [F14 decision contract](../f14-v2-decision-contract.md), [F19 settlement contract](../f19-v2-settlement-contract.md), [source authorization contract](research-source-authorization.md), [causal owner activation](causal-owner-activation.md), and [corrected chronology methodology](../product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md). Their old scope and timing semantics remain authoritative for their historical versions.

The [common-cutoff decision](../adr/0001-matchweek-wide-evidence-cutoff.md), [return-time clock diagnosis](../adr/0002-production-trusted-utc.md), [causal selection proof](../adr/0003-causal-matchweek-selection-witness.md), [candidate-input semantic contract](../adr/0004-candidate-input-estimands-and-consumer-boundaries.md), [conditional collection assurance](../adr/0005-research-only-causal-witness-trust-premises.md), [private source-risk decision](../adr/0006-research-only-public-source-automation-risk.md), and [historical six-league successor](../adr/0007-six-active-leagues-without-paid-data.md) retain their exact historical meanings. ADR 0010 specifies the active-direction supersession.

### Planning and readiness boundaries

Existing issue dispositions remain blueprint planning intent: #37 and #93 parked, #94 after the diagnostic analysis/Telegram slice, #100's six-scope objective and #101 superseded while preserving evidence, #1 historical, and #70 separate evidence-policy research. This authoring task does not change those issues or assert that their tracker state has changed.

No unresolved product decision blocks decomposition of the reset into implementation units. Current five-league source capability, independent-authority provisioning, SportyBet offer evidence, publication timing, and numerical-policy qualification remain work to prove. They block their affected live capabilities, not writing this spec or delivering a correctly qualified diagnostic alpha.

Keep WIP at one implementation unit. Use GPT-6.1 Sol for substantial planning, shared-contract design, source-policy and statistical decisions, with High by default and Extra High for difficult irreversible choices. Use GPT-6 Luna for explicit implementation units with reasoning effort matched to contract/persistence risk. A newly discovered design decision returns to planning. Broader Telegram beta and any future nonzero-spend choice require their explicit gates; no implementation unit may silently widen scope.

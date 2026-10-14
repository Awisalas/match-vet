# MATCHVET PRODUCT BLUEPRINT — REFOCUS V3

**Status:** Proposed new product source of truth  
**Date:** 2026-10-14  
**Repository baseline audited:** `bc9fda2dee3252db7522a57965706ee26b258800`

## 1. Purpose

MatchVet is a football research and betting-preference vetting system.

For every eligible pre-lineup match in the configured Matchweek, MatchVet should research the match using cutoff-valid evidence, evaluate every enabled Betting Preference, and return either:

- exactly one strongest justified recommendation, or
- `AVOID MATCH` when the evidence or model support is not good enough.

It must prefer correctness and abstention over volume. It must never turn missing evidence into favorable evidence.

The immediate goal is not a mobile app, website, subscription business, or multi-league expansion. The immediate goal is a trustworthy weekly system the owner can run, inspect and test through Telegram.

## 2. Active scope

### 2.1 European top five only

New active MatchVet work covers exactly:

1. ENG Premier League
2. ITA Serie A
3. ESP LaLiga
4. GER Bundesliga
5. FRA Ligue 1

Liga Portugal and Belgian Pro League are not active recommendation leagues.

### 2.2 Historical compatibility

Do not rewrite prior scope contracts.

- Historical seven-league contracts remain readable and replayable.
- The six-league successor remains readable and replayable.
- Create an explicit **five-league active-scope successor** for all new work.
- New active routes must refuse Portugal/Belgium.
- Historical stores may retain Portugal/Belgium rows without those rows entering the new active five-league route.
- Never “fix” old bytes, digests, migrations or released artifact meaning to make them look like the new scope.

The simplest safe design is a new active-scope version, not mutation of v1/v2.

## 3. Hard product constraints

### 3.1 Zero-spend build

MatchVet must be buildable and testable with **no required spend**.

No required:

- paid football/data API,
- paid AI/model inference API,
- paid hosting,
- paid database,
- paid queue,
- paid monitoring platform,
- paid CI,
- paid developer service.

Use existing local hardware, Git/GitHub, Python, SQLite, content-addressed files, Telegram Bot API, and qualified no-cost/public/official football sources.

A service that starts free but requires payment for the normal MatchVet workflow is not an acceptable dependency.

If a future public beta cannot be operated sustainably at zero spend, that becomes an explicit owner decision. It must not silently enter the architecture.

### 3.2 Telegram first

Telegram is the release/testing surface until MatchVet is genuinely ready for users.

Stages:

1. local CLI remains the engineering/operator surface,
2. owner-only Telegram alpha,
3. closed Telegram research beta,
4. broader user access only after the defined gates pass.

No Expo client, native app, web client, account system, subscription system, or payment integration belongs on the active roadmap.

### 3.3 Research-only until earned

`RESEARCH_ONLY` remains the default.

Do not claim validated confidence, production-grade predictive reliability, or “winning” performance until chronological evidence and the promotion criteria justify it.

Experimental outputs may be tested privately, but unsupported numerical components remain UNKNOWN.

### 3.4 Pre-lineup only

Recommendations use the frozen pre-lineup information boundary. MatchVet does not refresh a recommendation after the declared research cutoff merely because a later fixture is farther away.

Settlement and later evaluation are separate.

### 3.5 Preference rules

Keep the existing founder preference families:

- Match Winner (1X2)
- Double Chance (1X, X2, 12)
- Handicap
- Totals, overs only
- First-half overs
- Second-half overs
- Corners: winner, home over, away over
- Team Goals: home/away overs

Keep banned:

- all unders,
- Over 0.5 / Under 0.5,
- trivial corner totals,
- cards unless the product owner explicitly reopens that decision.

Do not add new markets during refocus.

### 3.6 Odds

Odds do not choose the recommendation.

Odds may later be retained as evaluation context, but no price/value optimizer belongs in the selection path.

## 4. Principles that survive the reset

These are non-negotiable unless the owner explicitly changes them through a new decision:

- missing evidence is UNKNOWN, never favorable;
- an empty schedule is not proof of complete coverage;
- artifacts that have been released keep their original meaning;
- corrections append; they do not rewrite history;
- exact source/provenance identity matters;
- historical replay must not silently use current defaults;
- a failed or unfinished research process is not `AVOID MATCH`;
- `AVOID MATCH` is a legitimate completed result;
- source authority, source availability, evidence truth and predictive validity are separate questions;
- no access-control, paywall, CAPTCHA, WAF or ban-evasion bypass;
- no recommendation is allowed to learn from its own later outcome;
- bookmaker odds do not drive ranking.

## 5. New product loop

The active product is one complete weekly loop.

```text
five-league fixture acquisition
    -> semantic completeness / unresolved identities
    -> immutable Matchweek membership
    -> common research cutoff
    -> evidence collection and evidence health
    -> prediction + uncertainty
    -> vet every enabled preference
    -> one recommendation or AVOID
    -> Telegram owner report
    -> outcome acquisition / settlement
    -> transparent performance record
    -> chronological evaluation
```

If one stage is incomplete, the Matchweek is incomplete. Do not fake progress by publishing a later-stage artifact without its required predecessors.

## 6. Telegram alpha

### 6.1 Architecture

Telegram is an adapter, not a domain owner.

The bot may call an application service and format its result. It must not contain:

- model math,
- evidence policy,
- fixture completeness logic,
- settlement logic,
- source authorization logic,
- database schema knowledge beyond an adapter/repository interface.

Use long polling for owner-only alpha so no paid server is required.

The initial implementation should avoid adding a Telegram framework if plain HTTP with the existing `requests` dependency is sufficient.

### 6.2 Initial commands

Keep the first command surface intentionally small:

- `/week` — current frozen Matchweek status and league coverage
- `/today` — eligible matches today from the active frozen Matchweek
- `/match <id>` — one match's research status and terminal decision
- `/record` — settled performance summary for completed research-only recommendations
- `/health` — source/data/run health for the owner

Do not build accounts, onboarding, payments, social features, inline betting, or chatty AI conversation.

### 6.3 Owner-only safety

Initial alpha accepts only configured owner chat IDs.

Secrets such as the Telegram token stay outside Git and outside immutable research artifacts.

The Telegram adapter must have deterministic formatting tests without network access.

## 7. Codebase refocus architecture

The target is a strangler migration, not a rewrite.

### 7.1 New ownership direction

New active work should move toward named ownership:

```text
matchvet/
  domain/
    scope/
    scheduling/
    evidence/
    prediction/
    decision/
    settlement/
  application/
    analyze_matchweek.py
    settle_matchweek.py
  adapters/
    sources/
    telegram/
    sqlite/
  compatibility/
    historical readers/adapters
```

This is a direction, not a demand to move the whole repo before product work continues.

### 7.2 Legacy rules

- Create no new `Txx` ownership modules.
- Do not expand giant legacy files when a coherent new owner can be introduced safely.
- Existing `Txx/Fxx/LFxx` modules remain compatibility implementations until migrated.
- Move one responsibility at a time behind tests.
- Never combine a broad refactor with a new product behavior unless the old seam makes the behavior impossible.

### 7.3 File-size and responsibility discipline

For new files:

- target under ~600 lines,
- require explicit justification beyond ~800 lines,
- do not create a new >1,200-line module.

For existing giant modules:

- no arbitrary rewrite,
- every meaningful touch should avoid making them larger unless extraction would be riskier,
- architecture tickets should gradually create smaller owners and adapters.

These are maintainability guardrails, not mechanical build failures on old files.

## 8. Source and data strategy

Removing Portugal and Belgium reduces active source burden, but does not magically prove top-five coverage.

For each top-five league, freeze an explicit source capability matrix:

- upcoming fixture coverage,
- kickoff precision,
- current season completeness,
- team identity quality,
- result/settlement coverage,
- publication/retrieval timing,
- use/retention constraints,
- fallback path,
- known failure states.

Preferred order remains:

1. official/competition source where operationally usable,
2. qualified open/licensed source,
3. qualified public machine-readable source,
4. bounded public-page extraction only when necessary and allowed by the research policy.

Do not assume “free” means complete. Do not assume HTTP success means authorized. Do not assume a historical-results feed proves upcoming-fixture health.

An internal manual citation path may exist as an owner-alpha fallback, but it must never masquerade as automated complete-current coverage.

## 9. Decision-policy simplification

The statistical principle behind #70 is correct: do not invent policy thresholds.

The implementation shape is too broad to be allowed to freeze the entire product.

Create a new planning decision for the **minimum statistically defensible MatchVet decision contract**.

Rules:

- retain existing model probabilities and uncertainty only where valid;
- unsupported evidence dimensions remain UNKNOWN;
- a missing validated component may block a candidate rather than being replaced with a guessed number;
- prefer fewer well-defined gates over many invented scores;
- do not require every future intelligence concept before internal testing;
- no numerical threshold becomes “real” because it is convenient;
- any simplification that changes #70's frozen structural decisions requires a new ADR/version, not silent reinterpretation.

Until this is resolved, Telegram alpha may show research/model diagnostics and experimental candidate state, but must clearly mark unvalidated decision confidence.

## 10. Test strategy

The suite needs layers.

### Fast lane

Purpose: developer feedback for every ticket.

Includes focused unit tests, parser tests, pure domain tests, and directly affected contract tests.

Target: practical to run repeatedly on the development device.

### Standard lane

Purpose: cross-module proof for the affected domain slice.

Includes acquisition -> store, analysis use-case boundaries, Telegram formatting, settlement projection, etc.

### Replay lane

Purpose: prove historical bytes/digests/readers remain unchanged.

Run when version dispatch, persistence, artifacts, scopes, replay or compatibility code changes.

### Heavy lane

Purpose: milestone proof.

Includes expensive end-to-end source-authorization/causal replay, failure injection, backup/restore and release qualification.

Do not require an unchanged multi-minute heavy path to run after every tiny edit.

### Performance regression

The repeated #89 CURRENT/source-graph verification problem gets a dedicated regression budget.

The design goal is:

- immutable graph verification once per logical operation,
- current-authority validation once at the correct boundary,
- child writes reuse an in-operation verified context,
- no cross-operation trust reuse,
- no weakened refusal behavior.

Measure verification counts as well as elapsed time so a faster device does not hide duplicated work.

## 11. Documentation discipline

### Current truth

`MATCHVET_PRODUCT_BLUEPRINT.md` becomes the product source of truth after adoption.

It does not erase old ADRs/artifacts. Where it supersedes active product direction, create an ADR that states the exact supersession.

### Active documentation set

Keep the agent's shortest path small:

- `MATCHVET_PRODUCT_BLUEPRINT.md`
- `README.md`
- `GLOSSARY.md`
- relevant current ADRs
- active spec/ticket
- one concise current status page

### Historical material

Existing historical docs and `.audit` evidence remain available.

Going forward:

- stop committing raw generated audit runs,
- ignore runtime audit output,
- commit only curated evidence summaries required to justify a decision,
- do not append every implementation diary to a single giant status document.

## 12. Issue and workflow management

Use GitHub Issues as the tracker.

Create one new **MatchVet Refocus** map/epic using Matt Pocock's `$wayfinder` only if decisions are still foggy. Once this blueprint is accepted, use `$grill-with-docs` to reconcile it with the repo, then `$to-spec` and `$to-tickets`.

Keep WIP at one implementation ticket.

Each ticket must have:

- one user/product outcome,
- exact scope,
- exact non-goals,
- acceptance criteria,
- affected historical contracts,
- test lane requirements,
- model/effort recommendation,
- rollback/reversibility note when risky.

Do not create “cleanup” tickets with no measurable end state.

### Existing open issues

- #37: park for later Production Promotion.
- #70: retain as evidence-policy research, but remove it as a blocker for five-league plumbing/Telegram alpha. Plan the minimum defensible policy separately.
- #93: park until five-league history/source path is defined.
- #94: schedule after the five-league analysis/Telegram vertical slice because automatic settlement is part of the weekly loop.
- #100: supersede the six-scope release objective; preserve code/history. Extract the duplicated source-graph verification problem into a five-scope-compatible performance ticket.
- #101: supersede/close as a six-scope qualification target. Replace later with five-league qualification.
- #1: retain as historical origin; this blueprint supersedes its active scope/delivery plan.

## 13. Development model strategy

### GPT-6.1 Sol

Use GPT-6.1 Sol only for high-value planning work:

- product decisions,
- architecture,
- specs,
- ticket decomposition,
- difficult bug strategy,
- statistical methodology design,
- source-policy decisions,
- maintainability/refactor planning,
- ambiguous trade-offs.

Use **High** by default for substantial planning. Use **Extra High** only where the decision is genuinely difficult or expensive to reverse.

It does not perform routine implementation.

### GPT-6 Luna

Use GPT-6 Luna for implementation when the ticket is explicit.

Choose the strongest useful reasoning effort for the task. Prefer higher reasoning for shared contracts, persistence, replay, source authorization, migrations or tricky tests; lower effort for narrow mechanical edits.

If Luna discovers that the ticket requires a design decision, stop implementation and return to GPT-6.1 planning rather than letting the implementer redesign the system.

## 14. Matt Pocock workflow

Matt Pocock's workflow is the default engineering backbone.

Run `$setup-matt-pocock-skills` once per repo if it has not already been configured.

Normal flow:

```text
$grill-with-docs
  -> if one design question needs runnable evidence: $handoff -> $prototype -> $handoff back
  -> if multi-session: $to-spec -> $to-tickets
  -> fresh $implement session per ready ticket
  -> $code-review
  -> $retro
```

If the work is huge and foggy, `$wayfinder` comes first. When decisions are clear, rejoin at `$to-spec`.

Use other installed skills only to strengthen this flow.

High-value MatchVet complements:

- `$domain-modeling` for vocabulary and contract boundaries,
- `$codebase-design` for extracting owners from giant modules,
- `$diagnosing-bugs` for performance/verification defects,
- `$blast-radius` for replay-sensitive changes,
- `$graphify` for dependency/hotspot analysis,
- `$archify` for architecture diagrams,
- `$interrogate` for blind-spot review,
- `$research` for source capability work,
- `$tdd` for defined vertical seams,
- `$caveman` to keep agent output compact,
- `$unslop` for final human-facing docs.

## 15. Refocus implementation phases

### Phase R0 — Adopt the reset

**Planner:** GPT-6.1 Sol, Extra High.

Goals:

1. add this blueprint,
2. write a superseding ADR for five-league active scope + zero-spend + Telegram-first delivery,
3. update the glossary/current README pointers,
4. triage current issues into active/parked/superseded,
5. create the refocus spec and vertical tickets.

No production behavior changes in this phase.

### Phase R1 — Five-league scope successor

**Planner:** GPT-6.1 Sol, High.  
**Implementer:** GPT-6 Luna, high reasoning.

Create the five-league active contract and dispatch.

Acceptance:

- new routes list exactly ENG/ITA/ESP/GER/FRA,
- Portugal/Belgium cannot enter new active acquisition/freeze/capture routes,
- six/seven historical artifacts replay unchanged,
- no migration unless proved necessary,
- replay tests cover mixed stores.

### Phase R2 — Make the repo cheap to change

Parallel product work stops only for defects that make every later ticket expensive.

Tickets should cover:

- source/CURRENT verification duplication from #100,
- explicit test lanes/markers and commands,
- generated audit-output policy,
- architecture dependency map and first extraction seam,
- concise current-status document.

Do not perform a repo-wide file move.

### Phase R3 — Prove zero-cost top-five acquisition

Requalify upcoming fixtures and results for the five leagues only.

Output one capability matrix and one executable acquisition plan.

Acceptance:

- each active league can distinguish COMPLETE / CONFIRMED_EMPTY / PARTIAL / STALE / UNKNOWN,
- no paid service is required,
- source failure is visible,
- manual fallback is explicitly labeled,
- current authority and transport refusal still work.

### Phase R4 — Five-league owner-only Telegram vertical slice

Build the smallest complete owner-facing slice.

One Matchweek should be able to:

1. acquire/freeze the five-league slate,
2. run the existing research/prediction pipeline as far as supported,
3. produce terminal research state per eligible match,
4. format the result in Telegram,
5. persist exact references so the same message can be reproduced,
6. remain owner-only and RESEARCH_ONLY.

This is the first milestone that should feel like “MatchVet works.”

### Phase R5 — Settlement and transparent record

Use/reframe #94 to connect exact retained results to F19 settlement.

Telegram `/record` must use settled immutable records, not hand-edited win/loss counts.

Track:

- recommendation/avoid counts,
- WIN/PUSH/LOSS/VOID/pending correctly,
- league/family breakdowns,
- unresolved/conflicting results,
- exact cohort/version identity.

### Phase R6 — Minimum defensible decision policy

Return to #70 with real five-league chronological data and a smaller product question.

Use GPT-6.1 Sol Extra High plus `$grill-with-docs`, `$research`, `$domain-modeling`, `$prototype` where needed.

Produce:

- the smallest executable policy profile justified by evidence,
- explicit UNKNOWN behavior,
- a frozen development/validation/evaluation scheme,
- supported markets/domains,
- non-triviality rules,
- calibration/reliability requirements,
- promotion criteria.

Do not add future intelligence systems merely to fill empty components.

### Phase R7 — Closed Telegram beta gate

Users do not receive MatchVet simply because the bot runs.

Technical gate:

- active scope is exactly five leagues,
- complete Matchweek workflow runs repeatably,
- source failures fail closed,
- Telegram messages are reproducible from stored artifacts,
- settlement/corrections work,
- backup/restore works,
- no critical integrity defects,
- expensive verification no longer makes normal operation impractical.

Evidence gate:

- enough genuine chronological records exist for the frozen evaluation method,
- no unresolved leakage/chronology failure,
- reported metrics use the exact active cohort,
- confidence labels, if any, are calibrated and justified,
- unsupported families are not promoted by averaging them with supported ones.

If evidence is not ready, continue owner-only research. Calendar pressure is not evidence.

## 16. Explicitly parked work

Until R7 is satisfied, do not actively build:

- Liga Portugal support,
- Belgian Pro League support,
- new betting markets,
- Trend Intelligence,
- Comparable Match Intelligence,
- Regime Intelligence,
- Failure Pattern Intelligence,
- external REST service,
- Expo/React Native app,
- web app,
- user accounts,
- subscriptions,
- payments,
- marketing automation.

These are backlog ideas, not current dependencies.

## 17. Definition of “back on track”

MatchVet is back on track when the owner can run a top-five Matchweek at zero required spend and, through Telegram, see:

- whether the slate is complete,
- what MatchVet knows and does not know,
- one experimental/validated recommendation or AVOID per completed match according to the currently qualified policy,
- why,
- the exact research-only status,
- later settlement,
- an honest performance record,

without waiting for a six/seven-league compatibility project, app build, subscription system, or multi-hour repeated verification path.

Everything else is secondary.

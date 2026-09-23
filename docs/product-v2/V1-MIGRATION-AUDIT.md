# Product V2 V1 migration audit

This audit records the V1 behavior that Product V2 must keep, version, deprecate, or replace. It is a planning document. It does not change production code or GitHub issues.

Keep historical V1 contracts and artifacts under their original versions. Add schema changes with forward-only migrations. Never rewrite released migrations or reinterpret a V1 artifact as a V2 result.

## Fixture acquisition and completeness

**Current behavior.** T06 imports season files from Football-Data.co.uk and uses OpenFootball where configured. The Belgian Pro League has no OpenFootball fallback. T05 freezes the fixture revisions already in the store and does not prove that acquisition covered every eligible fixture. `CONTEXT.md` and open issue #1 retain the V1 2026/27 seven-league, Friday-to-Monday scope. See `src/matchvet/ingestion.py`, `src/matchvet/matchweek.py`, and `docs/matchweek-freeze.md`.

**Disposition.** REPLACE the V1 completeness contract. Keep existing parsers, source records, and append-only fixture revisions for V1.

**Product V2 replacement.** Add replaceable, free, open, or official fixture providers with explicit coverage for each league and requested window. Unknown or incomplete coverage cannot produce a complete Matchweek result.

**Migration risk.** A missing fixture is invisible to membership and can make an incomplete slate appear complete. Provider rights, fixture identity, coverage records, freeze inputs, and historical evaluation depend on this contract.

## Source health and live provider contracts

**Current behavior.** T06 reports acquisition issues, and T07 stores source identity and status history. No live-run contract ties provider availability, freshness, rights, and coverage to Matchweek completeness. See `src/matchvet/ingestion.py`, `src/matchvet/evidence.py`, `src/matchvet/store.py`, and `docs/source-evidence.md`.

**Disposition.** VERSION the source-status records and add a V2 provider-health contract.

**Product V2 replacement.** Each provider reports its queried scope, retrieval time, source rights, freshness, coverage, and failure state. Use those results to distinguish incomplete acquisition from complete coverage. This is an operational requirement; later source-health intelligence remains a separate feature.

**Migration risk.** A health signal without league and time-window coverage can still mark a partial source as usable. New health records must not change the meaning of V1 source captures.

## `matchvet run` orchestration

**Current behavior.** The CLI starts T04 without a work executor. T04 defaults to `_BoundaryExecutor`, which completes lifecycle phases without acquiring fixtures, researching matches, evaluating preferences, or publishing a Matchweek decision. Its input contract contains `NO_SOURCE_SNAPSHOT` and unconfigured policy identities. T16's V1 research report says `RESEARCH_ONLY — NOT A RECOMMENDATION` and uses `Primary Candidate` and `RESEARCH AVOID`. See `src/matchvet/cli.py`, `src/matchvet/runs.py`, `src/matchvet/t16.py`, and `docs/run-lifecycle.md`.

**Disposition.** REPLACE lifecycle-only completion as the meaning of a complete Product V2 run. Keep T04 checkpointing, resume, resource limits, recovery, and `RESEARCH_ONLY` safeguards.

**Product V2 replacement.** Run the actual pipeline from fixture acquisition through research, preference evaluation, decision, audit, and publication. For each eligible match, publish exactly one clearly labeled `RESEARCH_ONLY` Primary Recommendation or AVOID MATCH. An incomplete pipeline or incomplete fixture slate cannot publish as a complete Matchweek result.

**Migration risk.** Existing T04 `COMPLETE` records describe lifecycle completion, not completed analysis. V2 must use distinct stage outputs and versioned run/report contracts.

## Global Matchweek cutoff

**Current behavior.** T05 uses one six-hour `MatchweekResearchCutoff` for membership and evidence. The rule appears in `src/matchvet/matchweek.py`, migration 5 and evidence-state schema in `src/matchvet/store.py`, and the V1 snapshot manifest in `src/matchvet/artifacts.py`. T08–T16 and T18–T19 also consume or validate the shared cutoff.

**Disposition.** VERSION the temporal model. Keep V1 cutoff records and readers unchanged.

**Product V2 replacement.** Freeze Matchweek membership separately from each match's `MatchEvidenceCutoff`. Keep the numeric lead time undecided. Do not introduce an implicit default.

**Migration risk.** Cutoff identity affects evidence, workload and weather, predictions, audits, exports, restore, replay, and chronological evaluation. A partial conversion can mix information states or admit evidence learned after a match's cutoff.

## Contextual evidence

**Current behavior.** T07 records evidence already obtained by an operator or adapter. T08 derives workload and weather context from supplied or persisted inputs. T09 builds frozen evidence states from available records; these modules do not form one automated research workflow. See `src/matchvet/evidence.py`, `src/matchvet/t08.py`, `src/matchvet/t09.py`, `src/matchvet/workload.py`, `src/matchvet/weather.py`, and `docs/source-evidence.md`.

**Disposition.** REPLACE the acquisition boundary. Keep provenance, source hierarchy, rights, corrections, conflicts, and V1 evidence records.

**Product V2 replacement.** Add automated, per-match research against the match's cutoff. Record source attempts and coverage as well as evidence assertions. Missing evidence stays UNKNOWN. It never implies ABSENT.

**Migration risk.** Without recorded attempts and coverage, a constructed evidence state can look like completed research when sources were never checked. Preserve V1 digests and version V2 evidence states.

## Preference Set and Preference Profile

**Current behavior.** V1 uses one immutable 37-preference catalog. T10 grading, T15 policy identity, and T16 audit completeness depend on that catalog. See `CONTEXT.md`, `src/matchvet/t10.py`, `src/matchvet/t15.py`, and `src/matchvet/t16.py`.

**Disposition.** VERSION the preference model. Keep the V1 catalog, identities, and artifacts unchanged.

**Product V2 replacement.** Separate the future user Preference Profile from the engine's market capability. Keep the founder's allowed preferences. Do not add markets. Exclude Unders, cards, Over 0.5, Under 0.5, and trivial or "baby" selections. Evaluate every enabled preference. Keep odds out of ranking and recommendations, and keep recommendations pre-lineup. Any later odds record is an evaluation benchmark only.

**Migration risk.** Changing the V1 catalog in place would alter policy validation, grading, audit completeness, and historical evaluation. Profile changes must not silently change engine capability or V1 policy identity.

## Settlement

**Current behavior.** `matchvet grade` imports operator-supplied JSON evidence. T10 grades deterministically and records corrections as successors. See `src/matchvet/cli.py`, `src/matchvet/t10.py`, `src/matchvet/store.py`, and `docs/settlement-grading.md`.

**Disposition.** KEEP manual settlement for V1 and as a recovery path. VERSION automatic settlement as a V2 acquisition path.

**Product V2 replacement.** Acquire settlement evidence through replaceable, authorized providers and bind each result to the frozen recommendation. Preserve source authority, provenance, conflicts, pending states, and corrections.

**Migration risk.** New providers may require source-enum and schema changes. Automated settlement must not rewrite the recommendation or its original grading evidence.

## Ticket-number architecture

**Current behavior.** Responsibilities follow T01–T19 across `src/matchvet/store.py`, `src/matchvet/runs.py`, `src/matchvet/ingestion.py`, `src/matchvet/matchweek.py`, `src/matchvet/evidence.py`, and `src/matchvet/t08.py` through `src/matchvet/t19.py`. T19 composes V1 modules for recorded replay; it is not the live `run` pipeline.

**Disposition.** DEPRECATE ticket numbers as V2 ownership boundaries after the live workflow works. Keep current module contracts during the live repair.

**Product V2 replacement.** Move responsibilities into domain modules for schedules, membership, research, preferences, predictions, decisions, settlement, and evaluation. Keep compatibility paths for V1 readers and callers.

**Migration risk.** A broad refactor before the live pipeline works would combine structural changes with behavior repair. Later moves can still break imports and serialized contracts, so migrate one boundary at a time.

## Storage and service boundary

**Current behavior.** Private Termux SQLite and the content-addressed object store hold authoritative state. The CLI is the operator interface; no stable app or service API owns the full workflow yet. See `src/matchvet/store.py`, `src/matchvet/artifacts.py`, `src/matchvet/cli.py`, `docs/local-store.md`, and `docs/artifacts.md`.

**Disposition.** KEEP local storage, immutable artifacts, forward-only migrations, backup, and recovery. VERSION new storage and service contracts.

**Product V2 replacement.** Put an application-service boundary between future Android, iOS, and web clients and the domain and store. Keep Termux and the CLI as the engineering and operator interface. Do not build subscriptions now.

**Migration risk.** Direct client access to SQLite would couple app releases to V1 schema and weaken recovery and audit controls. Never edit a released migration or rewrite historical artifacts.

## T20 Production Promotion

**Current behavior.** Open issue [#37](https://github.com/Awisalas/match-vet/issues/37) uses the V1 global six-hour cutoff. T18 validates one cutoff per Matchweek. The T19 qualification corpus is synthetic, calibration was unavailable, and its policy result was inconclusive. Issues #35 and #36, which #37 names as blockers, are closed. See `src/matchvet/t18.py` and `docs/research-only-release-qualification.md`.

**Disposition.** VERSION T20's temporal and evaluation contract. DEFER T20 Production Promotion.

**Product V2 replacement.** Start promotion work only after the V2 live pipeline works and genuine chronological evidence is sufficient. Evaluate against V2 membership and per-match cutoff records. Keep V1 T18 and T20 results historical.

**Migration risk.** V1 evaluation cannot validate V2's per-match information states. Reusing its six-hour assumptions or synthetic evidence could create false promotion evidence.

## Dependency order before intelligence work

Complete these steps in order:

1. Fix fixture acquisition and semantic completeness.
2. Define source health and live provider contracts.
3. Add Matchweek Membership Freeze and per-match Match Evidence Cutoff contracts.
4. Add automated contextual research.
5. Wire a real end-to-end `matchvet run` that produces one research-only decision per eligible match.
6. Add automatic settlement while retaining manual settlement and its history.
7. Complete architecture cleanup and establish the service boundary.
8. Add intelligence features.

Keep V1 contracts and artifacts valid under their original versions throughout this work. T20 Production Promotion also requires sufficient genuine chronological V2 evidence and revalidation. Complete genuine chronological evidence and revalidation before app or service work. Beta, promotion, and subscriptions remain later gates.

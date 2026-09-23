# Product V2 architecture

This document defines the target architecture and the boundary between V1 and V2. It does not require a rewrite. V2 adds versioned contracts alongside V1, then moves one proven responsibility at a time after the live workflow works.

Keep historical V1 artifacts and readers under their original versions. Keep SQLite and the Termux CLI. Use free, open, or official data sources and replaceable provider adapters. Do not add paid data or infrastructure, subscriptions, or an external app API in this phase.

This architecture follows [Product V2 direction](PRODUCT-DIRECTION.md) and the [V1 migration audit](V1-MIGRATION-AUDIT.md).

## Caller contract

The CLI translates operator input into an internal application request. The same use case will later sit behind an external app API, but it does not expose a network interface now.

```python
result = analyze_matchweek.execute(
	AnalyzeMatchweekRequest(
		matchweek=matchweek_key,
		scope_version=scope_version,
		membership_policy_version=membership_policy_version,
		evidence_cutoff_policy_version=evidence_cutoff_policy_version,
		preference_profile_version=preference_profile_version,
		decision_policy_version=decision_policy_version,
		mode="RESEARCH_ONLY",
	)
)

progress = analyze_matchweek.resume(result.run_id)
```

These proposed signatures show the internal contract. They are design sketches, not implemented Python APIs. The core records keep the two time boundaries separate:

```python
@dataclass(frozen=True)
class MatchweekMembershipFreeze:
	freeze_id: str
	schema_version: int
	scope_version: str
	membership_policy_version: str
	frozen_at_utc: str
	fixture_revision_refs: tuple[str, ...]
	coverage_digest: str
	digest: str

@dataclass(frozen=True)
class MatchEvidenceCutoff:
	cutoff_id: str
	schema_version: int
	freeze_id: str
	fixture_id: str
	fixture_revision_ref: str
	policy_version: str
	cutoff_at_utc: str
	digest: str

@dataclass(frozen=True)
class MatchAnalysis:
	fixture_id: str
	cutoff_id: str
	evidence_digest: str
	prediction_digest: str
	preference_result_refs: tuple[str, ...]
	outcome: PrimaryRecommendation | AvoidMatch
	mode: str  # RESEARCH_ONLY
	digest: str

AnalyzeMatchweek.execute(request: AnalyzeMatchweekRequest) -> AnalysisProgress
AnalyzeMatchweek.resume(run_id: str) -> AnalysisProgress
```

The Matchweek publication references the membership freeze and every terminal `MatchAnalysis`. A V2 freeze is never a container for one shared evidence cutoff.

`AnalyzeMatchweek` returns durable progress and the identity of each completed artifact. It reports a complete Matchweek result only after schedule coverage is complete and every eligible match has one terminal decision. An unfinished acquisition or research operation leaves the run incomplete. A completed research attempt can still leave evidence `UNKNOWN`; that uncertainty can support AVOID MATCH. Missing evidence never becomes `ABSENT`.

The request names versioned policies but defines no numeric freeze or cutoff lead time. A run cannot claim a cutoff-valid V2 decision until the applicable policy is configured.

## Dependency flow

```text
Termux and CLI
  -> INTERNAL AnalyzeMatchweek
       -> fixture acquisition and provider-health observations
       -> semantic coverage assessment
       -> immutable Matchweek Membership Freeze
       -> for each frozen match:
            Match Evidence Cutoff
            -> automated research and frozen evidence
            -> models, calibration, and uncertainty
            -> every enabled preference vetted
            -> one RESEARCH_ONLY Primary Recommendation or AVOID MATCH
       -> complete audit and atomic Matchweek publication

INTERNAL settlement use case
  -> settlement providers and manual evidence import
  -> immutable grades and append-only corrections
  -> chronological evaluation after genuine evidence exists

INTERNAL use cases -> repository ports -> SQLite and content-addressed artifacts

Later Android, iOS, and web clients -> EXTERNAL API adapter -> INTERNAL use cases
```

`AnalyzeMatchweek` owns the end-to-end operation. T04 `RunCoordinator` remains its durable run, resource, checkpoint, and recovery mechanism. A completed T04 phase is not proof that the corresponding analysis work happened. Every checkpoint must refer to real, versioned inputs and outputs.

Keep the request identity separate from acquired data. Immutable stage records add the actual source-capture, freeze, cutoff, and analysis digests as the run proceeds. A final V2 manifest references those records. Resume reuses an output only when its recorded inputs still match.

## Domain ownership

These are logical ownership boundaries. The first live implementation can call existing T modules through adapters. It does not need to move every file into a new package first.

| Owner | Responsibility and contract | V1 seam and migration boundary |
|---|---|---|
| Scheduling | Query the configured league and time-window scope. Normalize fixture identity, retain source-backed revisions, and assess coverage, unresolved identities, and known gaps. An empty response is not proof that the schedule is empty. | Extend `ingestion.py` and T06 adapters. Keep existing parsers and fixture history for V1. Do not claim a complete slate without coverage evidence for every configured scope. |
| Provider health | Record provider identity, capability, permitted use, requested scope, retrieval time, freshness, coverage, and failure state. Health is specific to a provider capability and query scope. | Extend T06 acquisition reports and T07 source records. A healthy historical-results feed does not prove upcoming-fixture or contextual-research health. This operational contract is separate from later source-health intelligence. |
| Matchweek membership | Create an immutable Matchweek Membership Freeze from a complete schedule assessment and its controlling fixture revisions. Preserve its scope, policy version, source coverage references, and digest. Later fixture changes append history; they do not rewrite the freeze. | Add a V2 freeze contract beside the V1 T05 manifest. Do not reinterpret or synthesize a V2 freeze from a V1 cutoff-bound manifest. |
| Match Evidence Cutoff | Assign each frozen match its own immutable Match Evidence Cutoff, identified by match, controlling fixture revision, temporal-policy version, and digest. | Add a V2 per-match contract. Keep the membership-freeze policy separate from the evidence-cutoff policy. Neither policy has an implicit numeric lead time. A changed kickoff or policy requires a new versioned analysis state, not an in-place cutoff edit. |
| Research and evidence | Acquire required evidence for every eligible match before deciding. Store source attempts separately from evidence assertions. Preserve publication and retrieval times, source rights, independent origins, conflicts, corrections, and requirement coverage. | Keep T07 provenance and `UNKNOWN` and `ABSENT` semantics. Extend T08 and T09 through V2 adapters that accept a per-match cutoff. Reuse T09 concepts such as research attempts, sufficiency, and frozen evidence where their V1 contract applies. Do not convert failed or unperformed research into `ABSENT`. |
| Models, calibration, and uncertainty | Consume a frozen match-evidence reference and a versioned, cutoff-eligible history snapshot. Produce calibrated probabilities, uncertainty, model availability, and model disagreement. Models do not read mutable latest state or bookmaker odds during a decision. | Keep T11 to T13 distribution models and T14 calibration and uncertainty as V1 components. Version their V2 inputs, fitted artifacts, and outputs. An unavailable model or calibration cannot silently become a valid probability. |
| Preference capability and vetting | Keep engine market capability separate from an immutable Preference Profile snapshot. Vet every enabled, permitted preference. Apply decision gates and rank only justified candidates. Return exactly one strongest justified Primary Recommendation or AVOID MATCH per completed match. | Preserve T10's V1 catalog, IDs, and grading rules. Add no markets. Keep the founder's allowed preferences and exclude Unders, cards, Over 0.5, Under 0.5, and trivial selections. Version T15 policy inputs and the V2 decision contract. Odds do not affect ranking. Recommendations remain pre-lineup. |
| `AnalyzeMatchweek` | Coordinate schedule acquisition, coverage assessment, membership freeze, per-match cutoffs, research, prediction, vetting, audit, and publication. Support resume and bounded work. Do not publish a complete Matchweek result when coverage or required work is incomplete. | Make the CLI call this internal application service. Keep one T04 lifecycle around real work. Use existing T06 to T16 operations where they fit; do not start nested run lifecycles for each module. Add per-match durable result or work records only where needed for correct recovery and audit. |
| Settlement and evaluation | Settle frozen recommendations from authorized source evidence. Preserve pending or conflicting results and append correction records. Evaluate immutable V2 analyses against genuine chronological outcomes without changing the original decision. | Keep manual T10 grading and V1 grades. Add automatic settlement as a separate versioned use case. Separate preference definitions from settlement ownership as modules move out of T10. Keep T18/T20 V1 evaluation contracts historical; defer Production Promotion until the V2 pipeline and genuine chronological evidence pass revalidation. |
| Reporting and audit | Publish one immutable V2 audit with schedule coverage, freeze and per-match cutoff identities, evidence and prediction references, every enabled preference result, uncertainty, decision reason, and `RESEARCH_ONLY` status. Publish the Matchweek report only when the complete-slate gate passes. | Keep T16 V1 report and audit readers. Add a V2 schema; do not relabel V1 `Primary Candidate` or `RESEARCH AVOID` as a V2 decision. Preserve artifact digests and atomic publication. |
| Persistence and repositories | Keep private SQLite as authoritative state and the content-addressed object store for immutable evidence and reports. Domain code uses narrow repository operations for versioned records and artifacts, not generic table CRUD. Keep network calls and model work outside write transactions. | Keep `Store`, `ArtifactStore`, T17 backup and recovery, bounded transactions, and single-writer safeguards. Add forward-only migrations and versioned manifests. Never edit a released migration or rewrite V1 artifacts. |
| Application and external API | The INTERNAL application service accepts domain-level requests and returns domain-level progress and result identities. The EXTERNAL API, when built, translates authenticated mobile or web requests into those internal use cases. | The CLI is the current operator adapter. No external server, remote job system, client access to SQLite, app, or subscription contract is part of this architecture phase. |

## Incremental migration boundaries

1. Improve fixture acquisition and semantic completeness in the existing T06 path. Keep source adapters replaceable and use no paid data or infrastructure.
2. Add provider-health and live-source contracts that report capability, scope, freshness, rights, coverage, and failures.
3. Add V2 Matchweek Membership Freeze and per-match Match Evidence Cutoff contracts with forward-only persistence. Leave their numeric timing policies unset until separately decided.
4. Add automated contextual research through per-match, cutoff-aware adapters. Record source attempts and retain V1 provenance and evidence-state rules.
5. Wire the real `AnalyzeMatchweek` use case into `matchvet run` and `resume`. Connect real outputs to T04 checkpoints and publish only after coverage, research, decisions, and audit validation complete.
6. Add automatic settlement as a separate use case. Keep manual settlement and all V1 grades readable.
7. After the live flow works, move one responsibility at a time from ticket-number modules into the domain owners above. Keep compatibility adapters for V1 callers and artifact readers.
8. Add intelligence features after the live flow and architecture cleanup. Gather genuine chronological V2 evidence and revalidate after those features. Build the external app/service layer only after that revalidation. Keep beta, Production Promotion, and subscriptions at their later Product Direction gates.

Do not create a new persisted workflow model before its idempotency and recovery rules are known. T04 remains the outer lifecycle. Persist per-match artifacts and outcomes by digest; add finer-grained work records only when real interruption or resource limits require them. A partial Matchweek may retain completed match artifacts, but only a complete coverage assessment and terminal result for every eligible match can create the complete V2 publication.

## Version and decision rules

- V1 SQLite migrations, T05 cutoffs, T09 evidence states, T10 preference and settlement records, T11 to T16 outputs, T18 evaluations, and T19 qualification artifacts retain their original meanings and readers.
- V2 freezes, cutoffs, research states, profiles, model outputs, decisions, reports, and run contracts carry explicit versions and digests. Compatibility code may read V1, but it must not translate a V1 global information state into a V2 per-match state.
- A source failure, an unperformed research requirement, and a completed search with no established fact are different states. Preserve those distinctions through persistence, recovery, and reporting.
- A completed research process may return AVOID MATCH when no candidate is justified. An interrupted process remains incomplete and cannot publish an AVOID MATCH as a substitute for unfinished work.
- Production Promotion remains a separate gate. `RESEARCH_ONLY` decisions do not authorize production `PLAY` output.

## Design choice

Use one internal `AnalyzeMatchweek` application service over cohesive domain owners. This keeps the CLI call short and makes the live path explicit while retaining the proven V1 model, evidence, artifact, and recovery code. Keep durable per-match outcomes and digests, but do not add a broad stage-work database before experience shows T04 checkpoint granularity is insufficient.

A distributed service or event bus would add network and operations costs before the local pipeline works. A rewrite organized entirely around the new domain modules would expand the live repair and threaten V1 readers. Both remain out of scope.

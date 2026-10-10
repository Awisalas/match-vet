# Product V2 implementation roadmap

Each entry is one proposed implementation ticket. `Blocked by` uses the roadmap IDs below. Keep V1 artifacts and readers under their original versions. Add V2 contracts alongside them and migrate one boundary at a time.

Require no paid football data or infrastructure. For private RESEARCH_ONLY sources, apply ADR 0006 below; commercial/Product Promotion source requirements remain separate. Keep provider boundaries replaceable.

The original roadmap total remains 53 numbered tickets. Corrective `LF` entries are outside that total; keep F01–F21 numbering unchanged.

## Current RESEARCH_ONLY source policy, 2026-10-10

[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md) supersedes publisher permission as a prerequisite for private RESEARCH_ONLY public automation. It accepts legal/terms/database-rights risk without asserting a licence or external grant. Technical access refusals, bounded transport, lineage, private retention and unchanged evidence gates remain mandatory. The [automated closure assessment](../research/automated-prospective-source-closure-2026-10-10.md) defines current corrective work; no live collection is activated.

LF01/LF02/LF05 and the earlier F08 permission inventory below retain their historical decisions. Manual bridges are compatibility/emergency research paths, not the target prospective architecture. Earlier automated/licensed requirements for Product Promotion remain separate and unchanged; they are not the current RESEARCH_ONLY permission gate. Source families can be risk-eligible while their capability, freshness or completeness remains UNKNOWN.

| Current corrective ticket | State / boundary |
| --- | --- |
| [#89](https://github.com/Awisalas/match-vet/issues/89) internal risk admission and V2 manifest | CLOSED in corrective commit `28661c5abe88ad6e1b63ca8a04e8ed5db7d9387c`; current authorization mechanics complete, real authority remains unprovisioned |
| [#90](https://github.com/Awisalas/match-vet/issues/90) bounded public transport | CLOSED after classifier correction in `f8a602a1def0c9f51d741b6b868e1297478d383b`; dormant CAPTCHA markup no longer blocks usable pages, explicit challenges/refusals still refuse; live acquisition remains disabled |
| [#91](https://github.com/Awisalas/match-vet/issues/91) exact source qualification | CLOSED under B in `288abd30716bbd1aca700220189387017e0639ea`; [raw default calendar is insufficient for current-window coverage](../research/pro-league-calendar-raw-qualification-2026-10-10.md); seven-league gaps retained |
| [#95](https://github.com/Awisalas/match-vet/issues/95) Belgium replacement fixture-source qualification | CLOSED under B; [public edition JSON and filtered terminal offset proven](../research/pro-league-replacement-fixture-source-2026-10-10.md), complete-current status/replacement coverage and automatic identity persistence unqualified |
| [#96](https://github.com/Awisalas/match-vet/issues/96) final official date-window qualification | CLOSED under B; [exact calendar handler traced](../research/pro-league-date-window-calendar-qualification-2026-10-10.md), JPL events preset/window/completeness/currentness/automatic namespace unqualified; no fixture requests; further official probing stops |
| [#97](https://github.com/Awisalas/match-vet/issues/97) free third-party Belgian fixture qualification | OPEN ready-for-agent for bounded research; Football Charts documentation first, free-term/full-window/complete-current/status/identity gates unresolved; OpenFootAPI and API-Football rejected by current availability terms; no qualified replacement |
| [#92](https://github.com/Awisalas/match-vet/issues/92) first automatic Pro League schedule slice | OPEN needs-info after #96 outcome B; native blocked by #97 complete-current Belgian source qualification; no adapter readiness |
| [#93](https://github.com/Awisalas/match-vet/issues/93) retained FT-to-F13 projection | OPEN ready-for-agent; exact chronology and unchanged model support |
| [#94](https://github.com/Awisalas/match-vet/issues/94) retained FT-to-F19 projection | OPEN ready-for-agent; post-kickoff evidence and unchanged settlement hierarchy |

#88 is CLOSED as superseded by the owner risk decision; its independent technical requirements moved to #91. #70 remains OPEN needs-info, #86/#87 CLOSED. These tickets activate no provider or prospective collection; causal operational provisioning remains separate.

## 1. Live foundation

### F01 Define fixture completeness
- **Goal:** Define how MatchVet distinguishes a complete empty schedule from failed, partial, or unresolved fixture acquisition for every configured league and window.
- **Blocked by:** None.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### F02 Restore upcoming fixture acquisition
- **Goal:** Repair the existing free, open, or official provider path used to acquire upcoming fixtures in the configured scope.
- **Blocked by:** F01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$diagnosing-bugs`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### F03 Persist fixture coverage
- **Goal:** Record coverage, known gaps, and unresolved fixture identities with each acquisition result.
- **Blocked by:** F02.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### F04 Define provider health records
- **Goal:** Define versioned provider health fields for capability, permitted use, query scope, freshness, coverage, and failure state.
- **Blocked by:** F03.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### F05 Record fixture provider health
- **Goal:** Attach provider health observations to upcoming fixture acquisition without treating a healthy unrelated feed as proof of fixture health.
- **Blocked by:** F04.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F06 Persist Matchweek Membership Freeze
- **Goal:** Add an immutable V2 freeze tied to complete fixture coverage, controlling fixture revisions, and a versioned membership policy.
- **Blocked by:** F03, F05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### LF01 Resolve the all-seven live fixture coverage blocker
- **Type:** Corrective source-contract and product-decision blocker; outside the original 53-ticket count.
- **Goal:** Preserve F01's proof bar after the audit found no reviewed all-seven automated path satisfying both completeness and use/retention requirements. The product owner selected operator-attested official publications as a temporary Research-Only bridge; this does not approve an automated source or clear rights for Product Promotion.
- **Tracked by:** [#44](https://github.com/Awisalas/match-vet/issues/44).
- **Prerequisites met:** LF09 #52 and the all-seven validation gate; the product-owner bridge decision is recorded in #44.
- **Status:** Complete in #44 (closed) after LF14 produced the real all-seven F06 freeze. The automated/licensed source requirement remains tracked for Product Promotion.

### LF02 Add Research-Only operator-attested official fixture completeness
- **Type:** Corrective Research-Only implementation ticket; outside the original 53-ticket count.
- **Goal:** Add immutable operator attestations bound to one exact automatic F01 assessment and candidate manifest; derive a separately versioned F01 assessment without changing F02, provider health, or the F06 gate.
- **Tracked by:** [#45](https://github.com/Awisalas/match-vet/issues/45).
- **Blocked by:** F01, F03, F05, F06 (all complete); product-owner decision recorded in #44.
- **Status:** Complete in #45 (closed). The all-seven Research-Only freeze subsequently passed under LF14; #44 is closed and F07 is Ready.
- **Size:** L.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### LF03 Resolve scheduled-fixture team aliases without creating duplicate teams
- **Type:** Corrective identity-resolution implementation ticket; outside the original 53-ticket count.
- **Goal:** Resolve schedule names only through an exact existing canonical team identity or a versioned, league-and-season-scoped, operator-confirmed whole-name alias registry. Pin source provenance, fail closed on ambiguity, and preserve all historical team/fixture identities and F01 v2 digests.
- **Tracked by:** [#46](https://github.com/Awisalas/match-vet/issues/46).
- **Blocked by:** None; LF02 #45 is complete.
- **Status:** Complete in #46 (closed). Do not change scheduled acquisition from `KNOWN_ONLY` to `REGISTER_UNKNOWN`.
- **Size:** M.

### LF04 Preserve DATE precision in fixture source assertions and LF02 manifests
- **Type:** Corrective timestamp-compatibility implementation ticket; outside the original 53-ticket count.
- **Goal:** Keep DATE facts as exact calendar dates and INSTANT facts as canonical offset-aware UTC timestamps. Add a strict compatibility rule for old date-only kickoff assertions without rewriting rows, changing F01 v2 digests, or requiring a database migration.
- **Tracked by:** [#47](https://github.com/Awisalas/match-vet/issues/47).
- **Blocked by:** None; LF02 #45 is complete.
- **Status:** Complete in #47 (closed).
- **Size:** S.

### LF05 Add Research-Only official fixture observations for unsupported scopes
- **Type:** Corrective manual-citation implementation ticket; outside the original 53-ticket count.
- **Goal:** Allow minimal immutable operator-cited official fixture facts to seed missing Belgian candidate rows without scraping, acting as a provider, asserting completeness, or changing F01/F06 rules. LF02 remains the separate completeness attestation.
- **Tracked by:** [#48](https://github.com/Awisalas/match-vet/issues/48).
- **Blocked by:** LF03, LF04.
- **Status:** Complete in #48 (closed). Product Promotion remains blocked on a separately accepted automated/licensed source strategy.
- **Size:** M.

### LF06 Prevent duplicate canonical teams during source registration
- **Type:** Corrective source-registration identity-resolution ticket; outside the original 53-ticket count.
- **Goal:** Use one current-database resolver for `KNOWN_ONLY` and `REGISTER_UNKNOWN`. Reuse one unambiguous existing team identity before registration, fail closed on conflicting IDs, and create a deterministic team only when no identity exists.
- **Tracked by:** [#49](https://github.com/Awisalas/match-vet/issues/49).
- **Blocked by:** None; LF02 #45 and LF03 #46 are complete. LF06 is independent of corrective LF07.
- **Status:** Complete in #49 (closed). Preserve all existing team and fixture IDs, source mappings, aliases, F01 v2 bytes, and schema 13.

### LF07 Distinguish compatible schedule precision from real fixture conflicts
- **Type:** Corrective LF02 candidate-manifest classification ticket; outside the original 53-ticket count and separate from original roadmap F07.
- **Goal:** Preserve DATE and INSTANT revisions while distinguishing `LESS_PRECISE_BUT_COMPATIBLE` from `CONFLICTING`. A precise revision never overrides a material disagreement.
- **Tracked by:** [#50](https://github.com/Awisalas/match-vet/issues/50).
- **Blocked by:** None; LF02 #45 and LF04 #47 are complete. LF07 is independent of LF06.
- **Status:** Complete in #50 (closed). Preserve F01 v2 bytes and schema 13; keep prior manifest versions readable and replayable.

### LF08 Complete Premier League fresh-store alias coverage
- **Type:** Corrective registry coverage and snapshot-versioning ticket; outside the original 53-ticket count.
- **Goal:** Audit all 20 current Premier League source spellings and add four proven scoped aliases in an append-only v2 registry. Preserve v1 bytes, policy provenance, frozen normalization, LF06 semantics, and schema 13.
- **Tracked by:** [#51](https://github.com/Awisalas/match-vet/issues/51).
- **Blocked by:** None; corrective LF06 #49 and LF07 #50 are complete.
- **Status:** Complete in #51 (closed). The subsequent real all-seven LF14 validation passed; #44 is closed and original F07 is Ready.

### LF09 Add source-scoped Pro League official team identity mappings
- **Type:** Corrective official manual-citation identity policy ticket; outside the original 53-ticket count.
- **Goal:** Resolve the 15 reviewed official Pro League names against existing Belgian 2026-27 teams only for the LF05 source kind. Preserve OpenFootball policy, existing team identities, and F01 serialization.
- **Tracked by:** [#52](https://github.com/Awisalas/match-vet/issues/52).
- **Blocked by:** None; LF05 #48 and LF08 #51 are complete.
- **Status:** Complete in #52 (closed). The existing nine real Belgian LF05 observations were reused by the successful LF14 freeze; #44 is closed and original F07 is Ready.

### LF14 Correct F06 semantic integrity and immutable-history compatibility
- **Type:** Corrective integrity ticket; outside the original 53-ticket count.
- **Goal:** Compare canonical team identities, typed kickoff compatibility and membership status classes. Project complete selected conflict members from cumulative immutable history. Validate revision/assertion coherence while preserving historical replay and raw provenance.
- **Tracked by:** [#57](https://github.com/Awisalas/match-vet/issues/57).
- **Status:** Complete in #57 (closed). Implementation, review and verification passed: 989 full-suite tests, Ruff and mypy. The existing real 2026-10-09 store produced and replayed 66 persisted INCLUDED decisions with Doctor PASS. No migration, acquisition rerun or new fixture observation was needed.
- **Live proof:** Policy-2 freeze ID `sha256:67ca9688433af7971443523774cce5c587025423fad5d12fb77c729c6a2d96d4`; freeze digest `sha256:560c300066c4c14c9f4771cb2db1e7dd94db8f6cd16528141090022dc32601b6`. Evidence: `.audit/lf14/live-result.json` and `.audit/lf14/live-history-comparison-final.json`.
- **Contract:** Membership policy 2 uses the unchanged schema-13 payload envelope. Historical policy-1 freezes and LF05/LF13 observation bytes retain their original replay contract.

### F07 Persist per-match Match Evidence Cutoff
- **Goal:** Add an immutable cutoff for each frozen match, tied to its fixture revision and a versioned policy. Leave the numeric lead time undecided.
- **Prerequisites met:** F06, LF01 #44, LF02, LF03, LF04, LF05, corrective LF06 #49, corrective LF07 #50, LF08 #51, LF09 #52 and LF14 #57.
- **Status:** Complete in #58. Protected per-match cutoff and policy artifacts bind exact F06 freeze/membership and controlling revision references, with deterministic retry and verified replay. Numeric lead time remains explicitly configurable with no default. See `docs/match-evidence-cutoff.md`.
- **All-seven validation gate:** Passed using the existing 2026-10-09 post-LF10 store and immutable artifacts: seven COMPLETE scopes, 66 canonical candidates, 12 exact health records, 66 persisted policy-2 membership decisions, exact replay and identical retry, reopened-store replay and Doctor PASS. Previous immutable history and failed evidence are unchanged. #44 is closed. The automated/licensed-source requirement remains separate for Product Promotion.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F08 Inventory no-cost contextual sources
- **Goal:** Map the current enabled preferences to free, open, or official contextual sources and their permitted use.
- **Blocked by:** F04, F05 (both complete).
- **Status:** Complete in #59. Historically, the [contextual source inventory](../research/contextual-source-inventory-2026-10-03.md) approved only the existing Open-Meteo weather path under its non-commercial free tier; injury/availability, suspensions, pre-lineup expected lineups, manager changes, referee appointments/context, and new workload sourcing remained UNKNOWN for approved automated and retained sourcing under that earlier permission-first policy. Current risk eligibility follows ADR 0006; operational capability and evidence quality are still unproven.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$research`, `$domain-modeling`.
- **Model:** GPT-6 Luna Max is sufficient.

### F09 Record contextual provider health
- **Goal:** Record health observations for each selected contextual provider and capability before MatchVet relies on its evidence.
- **Blocked by:** F04, F08.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### F10 Define V2 research requirements
- **Goal:** Version the evidence requirements for the founder's enabled preferences and preserve UNKNOWN, ABSENT, conflict, and unperformed states.
- **Blocked by:** F07, F08, F09.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### F11 Make workload and weather evidence cutoff-aware
- **Goal:** Adapt existing workload and weather research to each match's cutoff while retaining source attempts and provenance.
- **Blocked by:** F07, F09, F10.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F12 Add one contextual source adapter
- **Goal:** Connect one approved no-cost provider and evidence family to V2 research attempts, with its provider health and per-match cutoff recorded.
- **Blocked by:** F07, F09, F10.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F13 Version V2 model inputs and uncertainty
- **Status:** Complete in [#64](https://github.com/Awisalas/match-vet/issues/64). See the [V2 model contract](../f13-v2-model-contract.md).
- **Goal:** Bind prediction and calibration outputs to frozen evidence, cutoff-eligible history, and explicit model versions.
- **Blocked by:** F07, F10, F11.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$tdd`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### F14 Add the V2 Preference Profile and decision result
- **Status:** Complete in [#65](https://github.com/Awisalas/match-vet/issues/65). See the [F14 V2 contract](../f14-v2-decision-contract.md).
- **Goal:** Snapshot the founder's allowed preferences separately from engine market capability. Add no markets. Exclude Unders, cards, Over 0.5, Under 0.5, and trivial selections. Vet every enabled preference and return one strongest justified recommendation or AVOID MATCH, labeled RESEARCH_ONLY, before lineups and without odds-based ranking.
- **Blocked by:** F10, F13.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### F15 Add the internal AnalyzeMatchweek use case
- **Status:** Complete in [#66](https://github.com/Awisalas/match-vet/issues/66); corrected in [#67](https://github.com/Awisalas/match-vet/issues/67) and [#68](https://github.com/Awisalas/match-vet/issues/68).
- **Goal:** Define the application-service request, durable progress, and resume entry points used by the CLI.
- **Blocked by:** F03, F06, F07, F10, F13, F14.
- **Size:** S.
- **Contract:** `matchvet.f15.AnalyzeMatchweek` verifies exact F06/F07/F10/F14 inputs, the public F13 engine-version identity, and an exact T15 `RESEARCH_ONLY` Policy Version, then binds them to T04 start, inspect, and resume. Per-match F11/F13 outputs are produced downstream; F15 progress remains `IN_PROGRESS` until result publication exists.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`.
- **Model:** GPT-6 Luna Max is sufficient.

### F16 Process each eligible match
- **Status:** Complete in [#69](https://github.com/Awisalas/match-vet/issues/69). See the [F16 implementation sketch](../design/f16-implementation-sketch.md).
- **Goal:** Research each frozen match as evidence for the betting decision, then predict and vet every enabled preference, with a durable result for each one.
- **Blocked by:** F11, F12, F13, F14, F15.
- **Contract:** The existing T04 phases run exact F11 evidence, one cutoff-bound F13 model result, and one RESEARCH_ONLY F14 decision for every INCLUDED F06 membership. Protected F16 match results and a deterministic manifest are replayable; the run remains INCOMPLETE at AUDIT_VERIFICATION for F17.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### CB01 Bootstrap live chronological evidence before F17
- **Status:** Complete in [#72](https://github.com/Awisalas/match-vet/issues/72). See the [CB01 operator workflow](../design/cb01-operator-workflow.md).
- **Type:** Chronological bootstrap path; outside the original F01-F21 numbering.
- **Goal:** Preserve one outcome-free pre-enrollment per enabled preference for every exact F06 INCLUDED fixture, commit each complete fixture batch to SHA-256, and obtain one verified Sigstore RFC3161 witness before kickoff. Local clocks remain metadata.
- **Blocked by:** None. F06, F07, F10, F11, F13, F14, F16, F19 and ArtifactStore contracts are complete.
- **Relationship to #70:** Supplies genuine pre-kickoff predictions and later exact outcomes for the separate frozen methodology assessment. Does not define #70 estimators, thresholds, cohort roles or eligibility.
- **Relationship to F21:** F21 later adopts the exact CB01 case, batch, enrollment and outcome-attachment identities. It does not replace existing witnesses.
- **Gate:** F17 remains blocked by F16 and [#70](https://github.com/Awisalas/match-vet/issues/70). CB01 does not weaken or bypass either requirement.

### F17 Gate publication and recovery
- **Goal:** Publish the transparent, immutable MatchVet record only after fixture coverage and every eligible match's terminal decision are complete. Include evidence provenance, preference results, uncertainty, decision reason, and RESEARCH_ONLY status. Resume from matching immutable inputs and outputs.
- **Blocked by:** F16 and [#70](https://github.com/Awisalas/match-vet/issues/70), the frozen V2 CandidateInput derivation methodology and corrective dependency.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F18 Wire `matchvet run` to the real pipeline
- **Goal:** Route `run` and `resume` through AnalyzeMatchweek and remove lifecycle success that does not represent completed analysis work.
- **Blocked by:** F17.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$diagnosing-bugs`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F19 Define automatic settlement records
- **Status:** Complete in [#71](https://github.com/Awisalas/match-vet/issues/71). See the [F19 settlement contract](../f19-v2-settlement-contract.md).
- **Goal:** Add a versioned V2 settlement contract for source evidence, pending or conflicting results, and append-only corrections while retaining manual grading.
- **Contract:** Protected F19 artifacts bind the exact F16 manifest and match result, F14 decision, and enabled preference. T10 performs deterministic grading. Pending and conflicting evidence remain explicit, and corrections append full evidence snapshots linked to predecessors. No acquisition or schema migration was added.
- **Blocked by:** F14.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### F20 Settle completed V2 recommendations automatically
- **Goal:** Acquire results from an approved free or official source and settle frozen V2 recommendations without rewriting their original evidence.
- **Blocked by:** F18, F19.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F21 Start chronological V2 evidence collection
- **Goal:** Begin immutable chronological capture of live analyses and settlements as soon as F18 and F20 work, preserving a pre-intelligence baseline.
- **Blocked by:** F18, F20.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

## 2. Architecture cleanup

### A01 Extract scheduling and membership ownership
- **Goal:** Move V2 scheduling and membership responsibilities behind domain boundaries while keeping T06 and T05 V1 readers and callers valid.
- **Blocked by:** F06, F18, F21.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### A02 Extract research and evidence ownership
- **Goal:** Move V2 research and evidence responsibilities behind domain boundaries while preserving the T08 and T09 V1 contracts.
- **Blocked by:** F11, F12, F21.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### A03 Separate the V2 Preference Profile from T10
- **Goal:** Move V2 preference profiles and vetting out of T10 without changing the V1 preference catalog or market capability.
- **Blocked by:** F14, F21.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$codebase-design`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### A04 Separate automatic settlement from T10
- **Goal:** Move V2 automatic settlement ownership out of T10 while keeping manual grading and historical V1 grades readable.
- **Blocked by:** F20, F21.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$codebase-design`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### A05 Add V2 repository boundaries
- **Goal:** Put V2 domain persistence behind narrow repositories over SQLite and the existing artifact store, with forward-only migrations.
- **Blocked by:** A01, A02, A03, A04.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### A06 Retire ticket numbers as V2 ownership boundaries
- **Goal:** Remove direct V2 orchestration between T-number modules one caller at a time, retaining compatibility paths for V1 readers.
- **Blocked by:** A01, A02, A03, A04, A05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

## 3. Intelligence

### I01 Define versioned intelligence capability records
- **Goal:** Give each V2 intelligence capability an independent version, input lineage, and immutable output contract.
- **Blocked by:** A06, F21.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### I02 Add Trend Intelligence
- **Goal:** Add Trend Intelligence as a separately versioned input to V2 match analysis.
- **Blocked by:** I01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$tdd`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### I03 Add Comparable Match Intelligence
- **Goal:** Add Comparable Match Intelligence as a separately versioned input using only cutoff-eligible historical evidence.
- **Blocked by:** I01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$architect`, `$tdd`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### I04 Add Regime Intelligence
- **Goal:** Add Regime Intelligence as a separately versioned input with its own immutable evidence references.
- **Blocked by:** I01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$domain-modeling`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### I05 Add Failure Pattern Intelligence
- **Goal:** Add Failure Pattern Intelligence as a separately versioned input with source-linked failure records.
- **Blocked by:** I01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$tdd`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

## 4. Genuine chronological evidence and revalidation

### E01 Define chronological evaluation and evidence sufficiency
- **Goal:** Define the evidence sufficiency and chronological holdout rules used to evaluate V2 and its intelligence capabilities.
- **Blocked by:** F21, I01.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$research`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### E02 Evaluate Trend Intelligence on unseen evidence
- **Goal:** Measure Trend Intelligence's predictive contribution on later unseen chronological evidence.
- **Blocked by:** E01, I02.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### E03 Evaluate Comparable Match Intelligence on unseen evidence
- **Goal:** Measure Comparable Match Intelligence's predictive contribution on later unseen chronological evidence.
- **Blocked by:** E01, I03.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### E04 Evaluate Regime Intelligence on unseen evidence
- **Goal:** Measure Regime Intelligence's predictive contribution on later unseen chronological evidence.
- **Blocked by:** E01, I04.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### E05 Evaluate Failure Pattern Intelligence on unseen evidence
- **Goal:** Measure Failure Pattern Intelligence's predictive contribution on later unseen chronological evidence.
- **Blocked by:** E01, I05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### E06 Freeze intelligence changes and revalidate V2
- **Goal:** Freeze the planned intelligence versions, then run final V2 revalidation after the evidence sufficiency rule passes.
- **Blocked by:** E02, E03, E04, E05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

## 5. External service and app layer

### X01 Define the external service contract
- **Goal:** Define authenticated external requests and responses over internal use cases without exposing SQLite or V1 schemas to clients.
- **Blocked by:** E06.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$domain-modeling`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### X02 Expose AnalyzeMatchweek through the service
- **Goal:** Add the external service adapter for matchweek submission, progress, and immutable reports over the existing internal application service.
- **Blocked by:** X01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### X03 Scaffold the shared Expo client
- **Goal:** Scaffold the shared Expo and React Native client with typed service integration for Android, iOS, and web.
- **Blocked by:** X02.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### X04 Build Matchweek Home and Match Intelligence
- **Goal:** Build Matchweek Home and Match Intelligence with typed service data. Keep prediction and model logic in the service.
- **Blocked by:** X03.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### X05 Build the remaining shared client views
- **Goal:** Build Trend Intelligence, MatchVet Record, and Preference Profile views from typed service data, then verify the shared client on Android, iOS, and web. Keep prediction and model logic in the service.
- **Blocked by:** X04.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

## 6. Beta

### B01 Prepare an invite-only RESEARCH_ONLY beta
- **Goal:** Release the validated service and clients to a free, invite-only cohort with production PLAY output disabled.
- **Blocked by:** X03, X04, X05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$blast-radius`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### B02 Publish the performance record and evidence-led content
- **Goal:** Publish the transparent MatchVet performance record and evidence-led Matchweek marketing content. Never hide losses or claim guaranteed wins. Keep RESEARCH_ONLY wording until Production Promotion succeeds.
- **Blocked by:** B01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$technical-writing`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

## 7. Production Promotion

### P01 Version T20 qualification for V2
- **Goal:** Define T20 qualification against V2 freezes, per-match cutoffs, immutable decisions, and genuine chronological evidence while preserving V1 results.
- **Blocked by:** E06, B02.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$research`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### P02 Apply the T20 Production Promotion gate
- **Goal:** Keep T20 deferred until the live pipeline works, genuine chronological evidence is sufficient, and final V2 revalidation passes. Record a successful promotion only when these gates pass; otherwise close as FAILED or INCONCLUSIVE. FAILED or INCONCLUSIVE does not unlock subscriptions or paid recommendation launch.
- **Blocked by:** P01.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$research`, `$interrogate`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

## 8. Subscriptions and launch

Do not start any U01-U06 ticket unless P02 records a successful V2 Production Promotion. FAILED or INCONCLUSIVE leaves all commercial tickets blocked.

### U01 Define subscription plans and entitlements
- **Goal:** Design subscriptions for multiple countries and regions, including Nigeria. Keep pricing and entitlements independent of any one country or currency, make country availability configurable, and map one MatchVet Pro entitlement to localized storefront pricing. Start only after successful V2 Production Promotion, without changing the research or recommendation contracts.
- **Blocked by:** P02 successful promotion.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`.
- **Model:** GPT-6 Luna Max is sufficient.

### U02 Enforce entitlements in the service
- **Goal:** Enforce server-side entitlements for protected service operations after successful V2 Production Promotion.
- **Blocked by:** P02 successful promotion, U01, X02.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### U03 Add Android subscriptions
- **Goal:** Connect Android subscription purchases to server-verified entitlements after successful V2 Production Promotion.
- **Blocked by:** P02 successful promotion, U02, X05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### U04 Add iOS subscriptions
- **Goal:** Connect iOS subscription purchases to server-verified entitlements after successful V2 Production Promotion.
- **Blocked by:** P02 successful promotion, U02, X05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### U05 Add web subscriptions
- **Goal:** Connect web subscription purchases to server-verified entitlements after successful V2 Production Promotion.
- **Blocked by:** P02 successful promotion, U02, X05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### U06 Launch subscriptions
- **Goal:** Launch only where MatchVet can legally and commercially offer the subscription. Treat Nigeria as an intended launch market. Check app-store and payment-provider availability and applicable local restrictions before enabling each market. Support additional countries without changing prediction logic or account architecture. Launch only after successful V2 Production Promotion and completed billing and entitlement flows.
- **Blocked by:** P02 successful promotion, U03, U04, U05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$blast-radius`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

## Matchweek-wide cutoff correction tracking

This correction follows [parent #73](https://github.com/Awisalas/match-vet/issues/73)
and the accepted [completion protocol](../design/matchweek-selection-completion-protocol.md).
It supplements the historical roadmap entries above.

| Issue | Delivery | Dependency state |
| --- | --- | --- |
| #74 | Corrected whole-freeze F07 boundary delivered | Complete |
| #75 | Complete F16 selection, protected completion receipt, exact replay and shared preselection gate delivered; see [repository contract](../matchweek-research.md) | Complete |
| #76 | F11–F16 direct writers and resume call the shared gate; exact selected replay and legacy bytes preserved | Complete; pushed in `53bb02c`; #76 closed after focused and affected checks passed |
| #77 | CB01/F19 bind exact selected lineage; complete corrected denominator and chronology 0.2.0 | Complete; closed after validated implementation `f528e31425d54df6ca6ee12d2480f7031838f604` was pushed to main |
| #78 | Prove one corrected information state end to end | Complete; isolated offline acceptance passed and #78 closed |

#73 is complete and closed after the #78 acceptance proof. Live authoritative
validation remains pending: production prospective qualification requires an
operational trusted UTC upper-bound provider, and #70 numerical derivation profiles
remain unresolved. The default clock refuses.

[Production UTC research and ADR 0002](../adr/0002-production-trusted-utc.md)
preserve that refusal. No evaluated source satisfies the unchanged v1 return-time
contract on Termux/Android. The prospective event-boundary decision below does not
reinterpret that historical contract.
[Issue #79](https://github.com/Awisalas/match-vet/issues/79) completed that decision
with accepted [ADR 0003](../adr/0003-causal-matchweek-selection-witness.md).
[Parent #80](https://github.com/Awisalas/match-vet/issues/80) remains open for
prospective causal implementation. Its dependency-ordered children are #81 witness
protocol, #82 candidate/writer contracts, #83 downstream compatibility and #84
integrated successor proof. Only #81 is initially `ready-for-agent`; native blocking
edges are #81 → #82 → #83 → #84 → #80. See the
[child plan and acceptance ownership](../design/causal-matchweek-implementation-tickets.md).
Production refusal remains until the entire parent passes. No live rebuild or
source activation has started; #70 fitting remains separate.

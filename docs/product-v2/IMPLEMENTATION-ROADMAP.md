# Product V2 implementation roadmap

Each entry is one proposed implementation ticket. `Blocked by` uses the roadmap IDs below. Keep V1 artifacts and readers under their original versions. Add V2 contracts alongside them and migrate one boundary at a time.

Use free, open, or official football data and infrastructure that requires no paid dependency. Keep provider boundaries replaceable.

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

### F07 Persist per-match Match Evidence Cutoff
- **Goal:** Add an immutable cutoff for each frozen match, tied to its fixture revision and a versioned policy. Leave the numeric lead time undecided.
- **Blocked by:** F06.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F08 Inventory no-cost contextual sources
- **Goal:** Map the current enabled preferences to free, open, or official contextual sources and their permitted use.
- **Blocked by:** F04, F05.
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
- **Goal:** Bind prediction and calibration outputs to frozen evidence, cutoff-eligible history, and explicit model versions.
- **Blocked by:** F07, F10, F11.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$tdd`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

### F14 Add the V2 Preference Profile and decision result
- **Goal:** Snapshot the founder's allowed preferences separately from engine market capability. Add no markets. Exclude Unders, cards, Over 0.5, Under 0.5, and trivial selections. Vet every enabled preference and return one strongest justified recommendation or AVOID MATCH, labeled RESEARCH_ONLY, before lineups and without odds-based ranking.
- **Blocked by:** F10, F13.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$domain-modeling`, `$architect`, `$tdd`.
- **Model:** GPT-6 Luna Max is sufficient.

### F15 Add the internal AnalyzeMatchweek use case
- **Goal:** Define the application-service request, durable progress, and resume entry points used by the CLI.
- **Blocked by:** F03, F06, F07, F10, F13, F14.
- **Size:** S.
- **Recommended Matt Pocock skills:** `$architect`, `$codebase-design`.
- **Model:** GPT-6 Luna Max is sufficient.

### F16 Process each eligible match
- **Goal:** Research each frozen match as evidence for the betting decision, then predict and vet every enabled preference, with a durable result for each one.
- **Blocked by:** F11, F12, F13, F14, F15.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$architect`, `$tdd`, `$blast-radius`.
- **Model:** GPT-6 Luna Max is sufficient.

### F17 Gate publication and recovery
- **Goal:** Publish the transparent, immutable MatchVet record only after fixture coverage and every eligible match's terminal decision are complete. Include evidence provenance, preference results, uncertainty, decision reason, and RESEARCH_ONLY status. Resume from matching immutable inputs and outputs.
- **Blocked by:** F16.
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
- **Goal:** Add a versioned V2 settlement contract for source evidence, pending or conflicting results, and append-only corrections while retaining manual grading.
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
- **Goal:** Define account states and subscription entitlements only after successful V2 Production Promotion, without changing the research or recommendation contracts.
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
- **Goal:** Release the approved subscription plans across supported clients only after successful V2 Production Promotion and completed billing and entitlement flows.
- **Blocked by:** P02 successful promotion, U03, U04, U05.
- **Size:** M.
- **Recommended Matt Pocock skills:** `$blast-radius`, `$interrogate`.
- **Model:** GPT-6 Luna Max is sufficient.

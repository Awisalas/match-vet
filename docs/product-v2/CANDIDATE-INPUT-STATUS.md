# CandidateInput blocker status

Status date: 2026-10-10.

## Current state

[#70](https://github.com/Awisalas/match-vet/issues/70) remains OPEN with
`needs-info`. [ADR 0004](../adr/0004-candidate-input-estimands-and-consumer-boundaries.md)
is accepted as the semantic contract. [Methodology 0.2.0](CANDIDATE-INPUT-METHODOLOGY-0.2.0.md)
is its accepted, non-executable successor. It leaves methodology 0.1.0,
chronology 0.2.0, released V1 artifacts and readers, CB01 core, and historical
cohorts unchanged.

[#85](https://github.com/Awisalas/match-vet/issues/85) is CLOSED. Its versioned
F13/F14/T15 consumer seam is implemented in commit
`976beb8216d9174d20ff7184e289c09827e12061`. [#86](https://github.com/Awisalas/match-vet/issues/86)
is CLOSED. Its bounded offline bootstrap implementation is complete in commit
`54951a6a5401fa2622028ac99035bde1c8634428`. No qualified prospective #70 cohort
exists yet. Real prospective collection remains blocked until real-source use
and the causal-witness profile are separately approved and operational; neither
prerequisite was approved or activated in #86. Issue #70 remains OPEN with
`needs-info`; implementing #85 and #86 does not resolve its outstanding
chronological evidence or numerical/profile decisions.

[ADR 0005](../adr/0005-research-only-causal-witness-trust-premises.md) accepts
Option A: the existing conditional `matchvet-sigstore-causal-event-v1` assurance
for prospective RESEARCH_ONLY #70 corpus collection only. Published UTC/accuracy
and uncompromised-authority premises are accepted as premises; actual deployment
conformity and affirmative current nonrevocation remain UNKNOWN. Replay retains
`HISTORICAL_RETAINED_TRUST_ONLY`. This decision grants no runtime activation,
real-source authorization, fitting, evidence roles, production PLAY, or promotion.

Readiness remains BLOCKED for operational reasons. #87 mechanics are COMPLETE,
but owner key/configuration and checkpoint continuity are NOT OPERATIONAL. An
owner-signed current approval and event-valid TUF admission are also NOT
OPERATIONAL. The original retained metadata is expired; the
[audit](../research/causal-profile-activation-audit-2026-10-10.md) retains its
factual findings and labels its earlier no-issue decision historical.
Runtime source authorization is SEPARATE AND NOT OPERATIONAL. Source-use
policy is accepted below; no qualified prospective #70 cohort exists.

[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md) accepts
product-owner legal/terms/database-rights risk for private RESEARCH_ONLY automated
public-source acquisition, required raw/normalized retention, private backup/
restore/replay and derived inputs. Internal basis:
`PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED`. This is not publisher permission,
a licence or rights clearance. External UNKNOWN/REFUSED remains separately
recorded. Publisher permission is no longer a prerequisite in this policy scope.
Technical circumvention/refusal, rate limits, source quality, chronology,
completeness and UNKNOWN remain binding.

[#88](https://github.com/Awisalas/match-vet/issues/88) is CLOSED, NOT_PLANNED,
**SUPERSEDED BY PRODUCT-OWNER RISK DECISION**; its outreach history is retained
and no permission request is marked successful. Independent technical identity,
lineage, mapping and capability requirements moved to
[#91](https://github.com/Awisalas/match-vet/issues/91).
The [automated closure assessment](../research/automated-prospective-source-closure-2026-10-10.md)
replaces the manual-first permission proposal: seven official publisher families
for schedules/current revisions/completeness, plus one existing Football-Data
CSV family only if needed for recent FT history and later outcomes. No reviewed
source set yet proves the complete all-seven automatic contract.

[#89](https://github.com/Awisalas/match-vet/issues/89) is CLOSED as completed.
Its two accepted findings are fixed in corrective implementation commit
`28661c5abe88ad6e1b63ca8a04e8ed5db7d9387c`. All 401 focused tests passed, and
the three former expected failures now pass normally. The corrective delivery/status
commit is `17096f7e19dccaaa2235f68b75434ded71f873f9`. The adversarial review and
its findings remain below as historical context. Source authorization mechanics
are complete. Default production still REFUSES because real source authority/
configuration, checkpoint continuity and exact selected-graph approval are not
provisioned.

[#90](https://github.com/Awisalas/match-vet/issues/90) is CLOSED with offline
bounded transport in commit `03d0d1a223256a7795bed3fcf187a07fd125253c`. No
provider adapter or live acquisition was activated. [#93](https://github.com/Awisalas/match-vet/issues/93)
FT-to-F13 projection and [#94](https://github.com/Awisalas/match-vet/issues/94)
FT-to-F19 projection remain OPEN `ready-for-agent`. [#91](https://github.com/Awisalas/match-vet/issues/91)
is CLOSED under criterion B for the exact default Pro League calendar response.
[#92](https://github.com/Awisalas/match-vet/issues/92), the first Pro League automatic
schedule slice, remains OPEN `needs-info` until a replacement contract is qualified. Follow-up
league slices require qualified contracts. LF02/LF05 remain historical/emergency
manual paths, not the intended primary prospective architecture. Optional
weather/context may remain UNKNOWN/UNPERFORMED in honest diagnostic records.

The [Belgium raw-calendar review](../research/pro-league-calendar-raw-qualification-2026-10-10.md)
proves structured fixture/team UUIDs and exact UTC times, but only matchday 8
fixture membership. The inspected response is TECHNICALLY INSUFFICIENT for a
complete current requested window, including cross-round moves. Currentness,
replacement/status semantics and stable automatic mapping remain unqualified.
The prior seven-league table is retained; no other league was researched again.
[#95](https://github.com/Awisalas/match-vet/issues/95) adds the bounded
[replacement JSON qualification](../research/pro-league-replacement-fixture-source-2026-10-10.md)
below; it records another specific outcome B and leaves #92 unready.

## #95 Belgium replacement-source qualification

- New [#95](https://github.com/Awisalas/match-vet/issues/95) records outcome B,
  INSUFFICIENT for the inspected complete-current F01 contract, in
  [replacement-source evidence](../research/pro-league-replacement-fixture-source-2026-10-10.md).
  The exact public JSON family is
  `https://www.proleague.be/api/football_list/football_competition_match/variant_b`.
  Explicitly delivered first-party code proves its path and parameters; a
  no-credential edition sample and terminal-offset probe prove ordinary public access.
- The sample has 15 fixtures, explicit UTC, 17 corroborated team UUIDs and a
  filtered total of 277. The terminal offset returns no rows. These establish
  neither full requested-window membership nor affirmative empty. Live/pending
  and finished/warning fixtures occupy separate mutable status partitions.
  Complete-current coverage, revision/omission/replacement semantics and automatic
  identity persistence remain unqualified. No native publication time was invented.
- The delivered start/end `football_module/football_calendar` events handler is
  a distinct official lead with unqualified preset/schema/coverage. The smallest
  practical source-selection recommendation is to qualify one reliable zero-cost
  third-party Belgian source if no explicit official complete-current contract
  can be supplied. Existing third-party leads are not qualified. Manual Belgium
  remains temporary evidence and does not satisfy full automation.
- Checks passed: original/new private digests and protected modes, corrupt-byte
  rejection, contiguous asset-range reconstruction, exact locator provenance,
  UTC/status and seven fixture comparisons, 17 new source-ID observations and all
  18 canonical targets, unchanged LF05 mapping digest/lineage, documentation
  links/anchors/tables/fences, issue dependency/state checks and `git diff --check`.
  Nine bounded source requests inspected three linked JavaScript assets and two
  JSON locators; no season/club crawl or cross-origin backend contact occurred.
- Research delivery commit: `7b9098b87c64c26f2d0ec581f3acc8768e99de98`.
  #95 CLOSED completed under B; the native edge marking it as a prerequisite for
  #92 remains retained. #92 OPEN `needs-info`, without
  `ready-for-agent`, until an exact complete-current Belgian contract is qualified.
  #91 remains CLOSED under B, #90 CLOSED corrected, #70 OPEN `needs-info`.
  No other league, adapter, real source authority, Store, provider activation,
  causal provisioning, fitting, PLAY or promotion changed. Default live
  acquisition remains disabled.

## #90 refusal-classifier correction

- Regression confirmed the bare `captcha` substring classified a synthetic HTTP
  200 with hidden reCAPTCHA/site-key markup and usable page content as
  `TECHNICAL_REFUSAL`. The retained Pro League response contains the same dormant
  markup/configuration while returning the actual calendar payload.
- Removed only the generic `captcha` token. Added explicit challenge phrases for
  completing or solving a captcha and for captcha-required pages. Dormant script,
  hidden-widget and site-key mentions alone pass. HTTP refusal statuses,
  authentication/WAF headers, login redirects, explicit access-denial language,
  and human/captcha challenge phrases still refuse.
- Deterministic offline checks passed: `tests/test_source_transport.py` (59 passed)
  and focused downloader compatibility cases in `tests/test_ingestion.py` (3
  passed). Changed-file formatter and Ruff passed. Strict mypy passed for
  `src/matchvet/ingestion.py`; `git diff --check` and Markdown/link/table checks
  passed. No source authorization code changed; the transport test used the
  existing synthetic current-authorization seam.
- The corrected implementation and regression tests are committed in
  `f8a602a1def0c9f51d741b6b868e1297478d383b` and pushed. #90 was reopened while
  fixing the acceptance regression, then closed after the corrected test and
  prior refusal cases passed. Its final state is CLOSED. #92 remains OPEN
  `needs-info` and blocked on the replacement Pro League source contract in
  [#91's Belgium evidence](../research/pro-league-calendar-raw-qualification-2026-10-10.md).
- No live network, adapter, provider activation or real source authority was used.
  Default production/live acquisition remains disabled.

Source policy is accepted, and #89 runtime mechanics are COMPLETE. Real source
authority/configuration and checkpoint continuity are NOT PROVISIONED. Causal
#87 mechanics are COMPLETE; owner key/configuration/checkpoint provisioning,
owner-signed current approval and event-valid TUF admission remain NOT
OPERATIONAL. A qualified prospective #70 cohort DOES NOT EXIST. No live run is
authorized.

## #91 Belgium raw-calendar record

- Belgium verdict B: TECHNICALLY INSUFFICIENT for the exact initial response from
  `https://www.proleague.be/jpl-kalender!`. One bounded HTTP 200 response contains
  253848 complete bytes, retrieved at `2026-10-10T15:12:49.042098+00:00`, SHA-256
  `9813e53c40d2228195078dcac501b52f58a26b86d5da3e1a777212428dc2ccf3`.
  Scratch retention was checked before contact; raw bytes remain private locally.
- Embedded `__NEXT_DATA__` supplies nine matchday-8 fixtures, ordered home/away
  team UUIDs, competition/season/edition IDs, explicit UTC `time` values and
  `FullTime`/`SecondHalf`/`PreMatch` period types. Its 34-matchday catalogue does
  not supply other partitions' fixtures, exhaustive UTC-window/empty semantics,
  current replacement coverage or a postponed/cancelled status contract.
- All 18 source UUID/name observations match distinct existing canonical targets.
  Lifetime source-ID stability and automatic mapping authority remain UNKNOWN.
  The unchanged LF05 digest/manual lineage was verified and not relabelled.
- #90's unchanged body classifier flags reCAPTCHA markup/configuration in this
  response. No actual challenge is asserted. Live inspection stopped without
  evasion or classifier changes. No adapter, authority or provider was activated.
- Replacement decision: qualify an explicitly exposed official Pro League
  competition/edition partition/window payload or supported export with complete
  current membership, cross-round revisions, exact UTC and stable identities.
  Exact replacement locator remains UNKNOWN; no backend endpoint was guessed.
- Checks passed: retained byte/digest/locator/time/budget integrity, corrupted-byte
  rejection, offline JSON/UTC/identity checks, unchanged LF05 digest, documentation
  links/structure, issue states/native dependencies and `git diff --check`.
- Research commit `288abd30716bbd1aca700220189387017e0639ea` is pushed to `main`.
  #91 is CLOSED under criterion B. #92 remains OPEN `needs-info`, without
  `ready-for-agent`, despite its native dependencies now being closed.
- Next blocker: the exact public official replacement source contract. Default
  live acquisition remains disabled; operational authorization is unprovisioned.

## #91 initial research record

- Pro League verdict: PARTIAL. Preferred official candidate:
  `https://www.proleague.be/jpl-kalender!`, operated by Pro League NV. Fixtures,
  revision notices and one completed result are evidenced in extracted public
  pages. No exact automated source contract or hard candidate capability/refusal
  failure is proven. No adapter, authority or production acquisition was activated.
- Completeness, currentness and exact kickoff UTC remain unproven. The existing
  LF05 registry digest was verified; its manual-only lineage does not authorize
  automatic mapping. Stable source IDs and an automatic mapping revision remain
  UNKNOWN. No canonical teams were created.
- All seven official families remain PARTIAL. Premier League needs an exact
  maintained feed/window contract; Bundesliga needs structured enumeration and
  controlling updates; LFP and Serie A need exact public schemas, timing and
  current coverage; LALIGA needs timezone and exhaustive rescheduled-window
  semantics; Liga Portugal needs its export contract; Pro League needs the
  exact schema, UTC basis, coverage/currentness and identity contract.
- Football-Data documents FT results, but its `Time` timezone, exact final-status
  semantics and an acquisition plan that avoids odds remain unqualified. No
  CSV, odds or archive was acquired. Its rows cannot acquire COMPETITION authority.
- Checks passed: local Markdown links, table/fence/spacing checks, the exact
  registry digest and documented canonical targets, issue states/dependencies,
  and `git diff --check`. Primary publication checks have the limitations retained
  in the research record: two web fetch timeouts, lost direct-calendar metadata,
  and a Football-Data DNS timeout before any HTTP request. No runtime tests were
  needed for these documentation-only changes.
- Research commit `ffe422f1f9abdc18922c2b843e6d36a7272f5fe5` is pushed to `main`.
  #91 remains OPEN `needs-info`; #92 remains OPEN `needs-info` with #91 its only
  open native blocker. #89/#90 are CLOSED.
- Next blocker: qualify one supported public Pro League representation with
  exact times, complete current requested-window/empty proof, status/revisions
  and a source-scoped mapping contract. Neither close criterion A nor B is
  satisfied. Default live acquisition remains disabled.

## #90 implementation record

- Added bounded HTTPS transport policy to the existing resumable downloader.
  Initial and redirected destinations require explicit public endpoint scope;
  redirects are checked before contact and retain their history. Request,
  response-byte, elapsed-time, pacing, retry, backoff and redirect budgets are
  explicit. Refusal and access-control signals terminate acquisition.
- Operational fetch rechecks separately supplied current #89 authorization.
  Unconfigured production still refuses. No provider adapter or live acquisition
  was enabled. Retained captures include exact transport provenance; schema-2
  cache replay requires that provenance, validates digests, and performs no live
  refresh. Legacy retained caches remain replayable.
- Corrected HTTP-date `Retry-After` handling to preserve fractional waits, so
  retries cannot run early. Transport makes no fixture completeness,
  freshness, publication-time or ABSENT determination.
- Offline checks passed: 46 transport tests, five downloader compatibility
  tests and 14 targeted #89 authorization/withdrawal tests. Changed-file Ruff,
  formatting, strict mypy for `ingestion.py` and `git diff --check` passed.
  Repository-wide Ruff/format checks encounter pre-existing `.audit` and
  Markdown formatting failures; the combined broader capture/research run was
  interrupted in an existing slow F16 successor fixture before completing.
- Implementation commit `03d0d1a223256a7795bed3fcf187a07fd125253c` is pushed to
  `main`. #90 is CLOSED and no longer triaged `ready-for-agent`.
- Remaining blockers: #91 and #92 stay OPEN `needs-info` for exact source and
  schedule-slice qualification. #93/#94 projections remain open. Real source
  authorization/configuration and causal operational key/checkpoint/approval
  remain unprovisioned; default production refuses live fetches.

## #85 implementation record

- Added versioned CandidateInput support, exact protected gate-proof readers,
  and F14 replay identities without changing released V1 readers or formats.
- Added T15 joint finalist comparison with an order-independent maximal set
  and unresolved-primary AVOID behavior.
- Focused checks: 51 tests passed across the fast focused run and exact replay;
  Ruff, strict mypy on changed production modules, and `git diff --check` passed.
- Implementation commit: `976beb8216d9174d20ff7184e289c09827e12061`.
- Open blockers: #70 still needs a prospectively captured corrected-chronology
  V2 cohort; #86 live operation still requires separately approved and
  operational real-source use and causal-witness profile.

## #86 historical readiness record (superseded; before implementation)

This section preserves the readiness decision made before #86 implementation.
The current state is recorded at the top of this file and in the implementation
record below.

- Dependencies #69, #71, #72, #80, #84, and #85 are CLOSED.
- At the time, #86 was ready for offline bootstrap implementation and testing.
  No real case qualified and no live collection could run before real-source
  use and the causal-witness profile were separately approved and operational.
- At the time, #86 implementation had not started and did not supply the
  missing #70 cohort.
- Readiness correction commit SHA:
  `198c96f83e04240fc077d3c5454e5c04613aa941`.

## Decision recorded

- U1 is the probability mass under the frozen joint uncertainty law that
  violates an applicable G5 probability constraint.
- U2 keeps latent probability-interval coverage, predictive coverage, and
  calibration as distinct claims. A single observed outcome cannot establish
  latent probability-interval coverage.
- T1 compares all gate-qualified finalists through one coherent joint object.
  A missing comparison that could change the justified primary produces the
  versioned F14 result `AVOID MATCH` with `PRIMARY_SELECTION_UNRESOLVED`.
- The ADR explicitly amends #13 Section 2, item 4, and Section 6's final
  sentence. It does not silently reinterpret the old primary-selection rule.
- Missing required G6, G7, or G8 support remains UNKNOWN and fails closed.
  Normalization references resolve by component and exact preference through
  only estimand- and settlement-compatible groups.
- No threshold, coefficient, confidence level, sample floor, prior, weight,
  fitted value, or promotion criterion was selected.

## Compatibility and work boundaries

- #85 implemented the versioned consumer and replay contract. It does not
  authorize a statistical fit or production PLAY.
- #86 implemented the bounded prospective evidence bootstrap. It uses the
  exact corrected F06/F07 inputs and #80 selection witness before cutoff, then
  retains CB01's separate post-cutoff, pre-kickoff witness and later
  source-backed F19 outcomes by exact digest.
- Preserve every denominator row and its inclusion or exclusion reason. Do
  not backdate publication or retrieval times, refresh a selected graph, use
  legacy per-match records as corrected cases, or weaken UNKNOWN.
- Freeze separate development, validation, and untouched final-evaluation
  manifests before using outcomes for those roles. Reuse removes a case from
  the untouched set.
- No F16 corrective implementation, F17 work, #37 fitting, schema migration,
  live source acquisition, or production activation is authorized here.
- Prior planning records remain in `e89f2934a7985a93065ee67ceb1f49efefc23650`
  and `cfed6bc070168d887029119ace0a39915296992a`.

## Ordered blockers

1. #85's versioned CandidateInput support and joint T1 comparison contract is
   implemented in `976beb8216d9174d20ff7184e289c09827e12061`. Missing support
   remains UNKNOWN, and old readers retain their existing meanings.
2. #86's offline bootstrap is implemented in
   `54951a6a5401fa2622028ac99035bde1c8634428`. Real-source use and the
   causal-witness profile still require separate approval and operational
   readiness before any case can qualify or live collection can run. ADR 0005
   settles the conditional causal trust-premise choice for RESEARCH_ONLY only.
   #87 mechanics are complete in `3fe2d5f949e3e865fcf7deb5c9a7856a99c27ffc`.
   Owner key/configuration and checkpoint continuity remain NOT OPERATIONAL;
   an owner-signed current approval and event-valid TUF admission remain NOT
   OPERATIONAL. Issue completion activates nothing.
   Source-use policy is now settled by ADR 0006. Publisher permission is not
   required for its private risk-accepted public acquisition scope; external
   permission stays independently UNKNOWN/REFUSED unless evidence proves a grant.
   #89 internal authorization and exact V2 manifest are complete in corrective
   implementation commit `28661c5abe88ad6e1b63ca8a04e8ed5db7d9387c`. Next,
   implement #90 bounded transport, #93 retained FT-to-F13 history and #94 later
   outcome projection. Qualify exact
   automated source contracts in #91 before #92's first Pro League schedule
   adapter, then deliver only genuinely specified additional league slices.
   Preserve all-seven F01/F06 coverage/currentness and canonical identities.
   #88 is superseded/closed; its technical requirements are in #91. The old
   permission-first/manual-first planning below is explicitly historical.
3. After both prerequisites are approved and operational, run #86
   prospectively. Retain exact cutoff-valid inputs, immutable provenance, all
   denominator rows, and later source-backed outcomes. Keep unavailable,
   unattempted, UNKNOWN, failed, VOID, and unsupported states visible. No
   qualified prospective #70 cohort exists yet.
4. Freeze development, validation, and untouched final-evaluation manifests
   before assigning evidence roles.
5. Resolve the empirical methods and profiles under #13 from eligible
   chronological evidence. Keep #70 `needs-info`, F16 corrective work, F17,
   #37 fitting, and production promotion blocked until their own criteria pass.

## Exact current blocker for #70

MatchVet has no prospectively captured corrected-chronology V2 cohort that
joins exact cutoff-valid inputs, F13 predictions, F14/F16 RESEARCH_ONLY records,
and later source-backed outcomes. Existing historical rows cannot prove earlier
prediction availability, and production causal activation still refuses.
Numerical and profile decisions therefore remain evidence-dependent.

## Earlier repository bookkeeping

- Removed stale `ready-for-agent` from closed #84.
- Corrected #83's stale open/unstarted summary while preserving its historical
  completion evidence.
- The earlier #70 planning and status entries are preserved in the commits
  listed above.

## #86 capture-index representation gap (documented before storage change)

At the time this gap was documented, F16 and #80 already retained and replayed
the complete selected graph and its pre-`T` causal witness. CB01 and F19 retain
exact per-fixture/preference publication, enrollment, settlement, and correction
artifacts. Those identities do not provide one immutable snapshot of the
INCLUDED F06 membership × enabled preference denominator, the separate
excluded-membership reasons, and the unattempted/failed/withdrawn/unsupported
rows with their exact later CB01/F19 attachment versions.
`BootstrapRepository.inspect_denominator` is a reconstructed view over the
current failure catalog and selected receipts; it has no content digest or
append-only successor identity. F16 selection manifests end before CB01 and
F19. The analysis concluded that a protected capture-index artifact was
required to freeze this aggregate and its exact replay lineage.
The #86 implementation closed this representation gap without a SQLite
migration.

## #86 implementation record

- Added `ResearchCaptureRepository.capture_week` as the bounded offline index
  and exact-index continuation entry point. It retains the seven-scope F06/F07
  freeze, selected F11/F13/F14/F16 graph, signed pre-`T` #80 witness, complete
  INCLUDED F06 membership × enabled preference denominator, and excluded F06
  reasons in one protected replayable artifact.
- CB01 continuation is gated by an exact protected real-source-use decision
  and the operational qualified causal selection. F19 attachments require the
  exact enrolled row, non-PENDING source-backed evidence, and source timestamps
  strictly after that fixture's controlling kickoff. Corrections are
  append-only. The index assigns no evaluation roles. No SQLite migration was
  added.
- Offline verification: `tests/test_research_capture.py` (8 passed), Ruff,
  formatter, strict mypy for `research_capture.py`, and `git diff --check`.
- Implementation commit: `54951a6a5401fa2622028ac99035bde1c8634428`.
- #86 is closed. #70 remains open with `needs-info` and has no qualified
  prospective cohort yet.
- Real prospective collection remains blocked until real-source use and the
  causal-witness profile are separately approved and operational for the exact
  capture. Neither prerequisite was approved or activated in this ticket.

## Earlier status-log correction, 2026-10-10

- On 2026-10-10, corrected the current-state and readiness wording to reflect
  that #86 is CLOSED and its offline implementation is complete. The earlier
  pre-implementation readiness record remains above as historical context.
- Verified #70 remains OPEN with `needs-info`, #85 is CLOSED, and #86 is CLOSED.
- The remaining live-operation blockers are separate approval and operational
  readiness for real-source use and the causal-witness profile. No qualified
  prospective #70 cohort exists yet.

## Earlier completed step: causal witness activation audit (before ADR 0005)

- On 2026-10-10, retained the [classified research/decision record](../research/causal-profile-activation-audit-2026-10-10.md)
  for `matchvet-sigstore-causal-event-v1`. Readiness remains BLOCKED.
- Reviewed ADR 0003, both requested timing designs, the four causal modules,
  retained #80/#81/#84 trust assets, tests and executed proof records, plus
  current primary Sigstore policy/source/security/TUF evidence. GET-only
  metadata authenticated as root15/timestamp804/snapshot166/targets14 with
  unchanged TrustedRoot and certificate pins. No timestamp request was made.
- At audit completion, resulting implementation issue: none. The prerequisites
  were not all SATISFIED. Normative policy support does not approve UNKNOWN deployment
  conformity or establish current nonrevocation.
- Research/decision commit: `60b728f553382063e86e4083cf84a9367878c4ed`.
- Exact causal-operation blockers: no authenticated production acceptance of
  the operator/key/policy and limited-assurance premises; no operational
  activation/withdrawal owner or restore-safe authoritative history; and the
  original retained timestamp799 metadata expired at
  `2026-10-10T01:39:25Z`. An exact refreshed bundle must be admitted under
  authenticated owner state. Actual unsmeared-UTC/accuracy conformity and
  affirmative current nonrevocation remain UNKNOWN. V1 retains its declared
  historical assurance and cannot satisfy a stricter current-status consumer.
- Real-source authorization remains a separate unresolved prerequisite. No
  qualified prospective #70 cohort exists. #70 remains OPEN with `needs-info`;
  #86 remains CLOSED. No production code, activation, or collection changed.

## Historical step: RESEARCH_ONLY causal trust-premise decision (superseded)

- On 2026-10-10, explicit user confirmation selected Option A. Accepted
  [ADR 0005](../adr/0005-research-only-causal-witness-trust-premises.md) amends
  ADR 0003's collection scope: conditional published UTC/accuracy and
  uncompromised-authority premises suffice for prospective RESEARCH_ONLY #70
  corpus collection. Historical assurance and factual UNKNOWN states remain.
  Hidden authority failures remain a risk. Known authenticated invalidation,
  mismatch, expired event trust, or uncertain owner continuity refuses.
- Evidence reviewed: ADR 0003, causal-selection design, the 2026-10-10
  activation audit, retained #80/#81/#84 proofs, current status, pinned primary
  Sigstore policy, RFC3161 event bounds, and TUF client requirements. Compared
  both options across chronology, failure, integrity, feasibility, complexity,
  corpus accumulation, and later promotion. Affirmative deployment/current-status
  evidence remains UNKNOWN; it was not made a V1 collection prerequisite.
- Created [#87](https://github.com/Awisalas/match-vet/issues/87), then OPEN with
  `ready-for-agent`, for authenticated causal-profile activation/withdrawal and
  restore continuity, exact fresh TUF admission, and unchanged profile/policy/pin
  binding. This records the pre-implementation state only; #87 is now CLOSED and
  its mechanics are complete. Production owner provisioning, activation, and
  collection remain separate operator steps.
- Decision commit: `f3fb7657d7f36fc49096695b976fdf29d450feaf`.
- Checks: local Markdown links and fenced blocks, decision/comparison coverage,
  issue-to-retained-pin consistency, historical/current-state wording, and
  `git diff --check` passed. Verified GitHub #70 OPEN with `needs-info`, #86
  CLOSED, and #87 OPEN. No production code or tests changed or ran.
- Exact remaining causal-operation blockers at that historical point: no
  independently authenticated owner key/current checkpoint and signed
  activation/withdrawal/restore history were provisioned; no fresh exact TUF
  bundle was admitted under that owner authority; and no operational approval
  bound the exact profile, policy, pins, deployment/history, interval, and
  accepted premises.
  The original timestamp799 bundle is expired. Neither this ADR nor issue
  completion supplies runtime approval.
- Real-source authorization and operational readiness remain a separate blocker.
  No qualified prospective #70 cohort exists. #70 stays OPEN with `needs-info`;
  #86 stays CLOSED. F17, #37 fitting, production PLAY, and promotion remain
  blocked. No activation or collection occurred.

## Latest completed implementation: authenticated causal owner mechanics

- Implemented #87's private canonical Ed25519 owner-record verifier, explicit
  RESEARCH_ONLY #70 premise acceptance, exact TUF admission/floor advancement,
  withdrawal, nonce-bound independent checkpoint and authenticated restore lineage.
  [Contract](../design/causal-owner-activation.md) and
  [offline evidence](../../.audit/issue-87-implementation/README.md) define the
  external owner-service responsibility and the all-copy rollback limitation.
- Added schema-2 signed approval retention with legacy dispatch. Historical
  inspection preserves original bytes; present qualification checks current owner
  lineage and known adverse evidence. Dispatch and protected receipt insertion
  recheck current authority. Occupied failure, restart, no-retry/backfill rules,
  unchanged V1/CB01 meanings, UNKNOWN and separate #86 authorization remain.
- Production still refuses. No real owner key/configuration, current checkpoint
  service, production activation or admitted operational metadata is provisioned.
  No TSA/TUF/source acquisition, production Store, SQL migration, PLAY, fitting or
  F17/F18/F20 work occurred. #70 remains OPEN with `needs-info`; #86 remains CLOSED.
- Implementation commit: `3fe2d5f949e3e865fcf7deb5c9a7856a99c27ffc`, pushed to
  `main`. Final validation: 235 focused offline tests passed; formatter, Ruff,
  strict mypy, executable V1/CB01 baseline compatibility, documentation checks,
  and `git diff --check` passed. Independent Standards/Spec review found no
  outstanding blocker. The full suite was not run.
- Delivery verified on 2026-10-10: [#87](https://github.com/Awisalas/match-vet/issues/87)
  CLOSED after implementation, review, checks and push. [Completion evidence](https://github.com/Awisalas/match-vet/issues/87#issuecomment-6093011509)
  records the mechanics-only acceptance. #70 is OPEN with `needs-info`; #86 is
  CLOSED. Default production still refuses because owner authority and operational
  approval remain unprovisioned.
- Remaining prerequisites: independent owner key/configuration and secure signing
  administration; nonrollback checkpoint/head/floors and authenticated Store/history
  restore reconciliation; owner-signed applicable approval binding deployment,
  catalog/history, exact profile/policy/pins/interval and ADR 0005 premises; exact
  compatible event-valid TUF admission; separate approved operational real-source
  authorization; a new eligible unoccupied prospective Matchweek and its complete
  graph followed by the sole qualified witness and protected receipt. No qualified
  prospective #70 cohort exists. Fitting and promotion remain separate and blocked.

## Historical permission-first source-use decision, 2026-10-10 (superseded)

The entries below preserve the earlier permission-first policy and issue states.
ADR 0006 and the current sections supersede their permission/readiness claims;
no historical UNKNOWN became publisher approval.

- [Retained decision](../research/prospective-source-use-decision-2026-10-10.md)
  and [current primary terms evidence](../research/real-source-permission-evidence-2026-10-10.md)
  define the actual source classes and a minimal proposed
  `research-real-source-use-decision-v2` bound to
  `research-source-use-manifest-v1`. An exact selection digest can bind graph
  identity but cannot retain permission evidence absent from the graph.
- No source-authorization implementation issue is created. The original broad
  source inventory is refined by the minimum-closure decision below. Obtain
  permission only for actual acquisition and selected dependencies; Football-Data,
  Open-Meteo, specialist context and calibration sources are optional for the
  initial diagnostic graph. Terms changes/withdrawals block new uses while
  original decisions retain their historical meaning.
- Current blockers: #87 mechanics COMPLETE; owner key/configuration/checkpoint
  provisioning NOT OPERATIONAL; owner-signed current approval and event-valid
  TUF admission NOT OPERATIONAL; real-source authorization SEPARATE AND
  UNRESOLVED; qualified prospective #70 cohort DOES NOT EXIST.
- LF02 attestations and LF05/LF13 manual observations remain separate from
  Provider Attempts and Provider Health. No missing permission becomes approval,
  no missing evidence becomes ABSENT, and no wrapper clears upstream rights.
  Raw/normalized retention and private backup/replay are assessed separately.
  Existing source-rights/F01/F06 contracts, production code and tests are unchanged.
- Default production remains refusing. #70 remains OPEN with `needs-info`;
  #86 and #87 remain CLOSED. No owner provisioning, provider activation,
  authorization, acquisition, collection, PLAY, Product Promotion, F17/F18/F20
  or #70/#37 fitting occurred.
- Research decision/evidence commit:
  `19416e45eaed1a6677e4d47ee65888309de77c04`, pushed to `main`. No implementation
  issue was created. Documentation links, fenced blocks, matrix columns,
  successor/source/timing invariants, current blocker wording and
  `git diff --check` passed. Verified #70 OPEN with `needs-info`, #86 CLOSED and
  #87 CLOSED without `ready-for-agent`. No production code/test diff; no runtime
  tests or full suite ran for these documentation-only changes.

## Historical permission-first minimum closure, 2026-10-10 (superseded)

The entries below preserve the earlier permission-first policy and issue states.
ADR 0006 and the current sections supersede their permission/readiness claims;
no historical UNKNOWN became publisher approval.

- [Dependency decision](../research/minimum-prospective-source-closure-2026-10-10.md)
  and [current dataset licence evidence](../research/minimal-model-dataset-evidence-2026-10-10.md)
  record **B**, not operational approval. Minimum practical inputs: seven-scope
  official completeness/schedule facts, actual LF02 automatic base attempts,
  selected canonical mappings, and one recent provenance-backed full-time goal
  corpus. That corpus can reuse one official publisher's permission. Later F19
  goal outcomes can share the same publishers' grants but remain post-kickoff
  evidence, separate from pre-T prediction inputs.
- Existing manual fixture policies cover Belgium, England, Germany, France and
  Italy only. Spain/Portugal still need the current JSON/TXT adapter's real
  acquisition and exact upstream clearance. No all-manual automatic-base
  substitute, fake attempts, completeness weakening or ambiguous alias import
  is allowed. Football-Data history is avoidable. No new adapter is implemented.
- Weather, specialist context, halves/corners and prior calibration need not
  become supported merely to retain complete RESEARCH_ONLY rejection records.
  Preserve every enabled preference and UNKNOWN/UNPERFORMED/unavailable state.
  No supported Primary, evaluation completeness or validated numerical profile
  is inferred. Explicitly licensed reviewed history releases fail the current
  recency floor; recent alternatives remain unresolved. A small cleared manual
  corpus is a proposal, not a proven numerical/operational fit.
- Remaining rights evidence: named operator/legal capacity; seven actual official
  publisher minimal-fact/citation rights, normalized retention, private backup/
  restore/replay and derived-input basis; OpenFootball maintainers' exact
  Spanish/Portuguese feed and selected mapping upstream inventory plus applicable
  upstream grants. Narrow sendable requests are retained; none was sent.
  One extra dataset/provider grant is conditional on the manual-history route
  failing, not an additional mandatory dependency. No implementation issue.
- #87 mechanics COMPLETE; owner key/configuration/checkpoint provisioning NOT
  OPERATIONAL; owner-signed current approval and event-valid TUF admission NOT
  OPERATIONAL; real-source authorization SEPARATE AND UNRESOLVED; qualified
  prospective #70 cohort DOES NOT EXIST. V2 decision/immutable manifest remains
  required. Default production refuses. #70 OPEN with `needs-info`; #86/#87 CLOSED.
- No acquisition, source approval, production provisioning, live collection,
  F17/F18/F20, #70/#37 fitting, PLAY or Product Promotion occurred. Research
  checks passed: local Markdown links, fenced blocks, matrix columns, current
  blocker wording, static recency arithmetic and `git diff --check`. GitHub
  verified #70 OPEN with `needs-info`, #86 CLOSED and #87 CLOSED without
  `ready-for-agent`. No production code/test changes or runtime tests.
- Research decision/evidence commit:
  `917aad3d08e2aa8ce4e22569c611465bc192b531`. Delivered with the status log to
  `main`; no implementation issue was created. Next blocker: exact current
  publisher/upstream rights evidence for the bounded proposed source closure,
  alongside the separate unprovisioned causal operational prerequisites.
- Human evidence blocker: [#88 — obtain minimum source-permission evidence](https://github.com/Awisalas/match-vet/issues/88).
  #70 is blocked by this human outreach/evidence issue; no source authorization
  implementation issue was created.

## Historical policy delivery: public-source automation risk, 2026-10-10

This records the policy delivery before #89 implementation. The current state
and completed mechanics are recorded above and in the implementation record below.

- Accepted [ADR 0006](../adr/0006-research-only-public-source-automation-risk.md):
  `PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED` for private RESEARCH_ONLY public
  acquisition and required raw/normalized retention, private backup/replay and
  derived statistical inputs. It is owner risk acceptance, never publisher
  permission/licensing/rights clearance. No technical bypass or weaker evidence
  gates. No live run is authorized.
- #88 CLOSED NOT_PLANNED, SUPERSEDED BY PRODUCT-OWNER RISK DECISION; removed
  `ready-for-human`. No permission request succeeded by supersession. Its
  independent technical requirements are tracked in #91.
- Technical tickets: [#89 source authorization/V2 manifest](https://github.com/Awisalas/match-vet/issues/89),
  [#90 bounded public transport](https://github.com/Awisalas/match-vet/issues/90),
  [#91 exact source qualification](https://github.com/Awisalas/match-vet/issues/91),
  [#92 first automatic Pro League schedule slice](https://github.com/Awisalas/match-vet/issues/92),
  [#93 retained FT-to-F13 history](https://github.com/Awisalas/match-vet/issues/93),
  [#94 retained FT-to-F19 outcomes](https://github.com/Awisalas/match-vet/issues/94).
  #89/#90/#93/#94 are OPEN ready-for-agent; #91/#92 OPEN needs-info. No optional
  context implementation is required for the initial diagnostic graph.
- Target closure: seven official publisher schedule/coverage/revision families;
  use their FT results too, or add one existing Football-Data CSV family if needed.
  Exact current capability, source timezone, coverage, freshness, identity and
  lineage are not yet qualified. Manual LF02/LF05 remain separate compatibility
  paths. UNKNOWN/UNPERFORMED diagnostic rows remain visible.
- #70 OPEN needs-info; #86/#87 CLOSED. #87 mechanics COMPLETE; causal owner
  key/configuration/independent checkpoint NOT OPERATIONAL; signed current
  approval/event-valid TUF admission NOT OPERATIONAL; source runtime admission
  and exact graph authorization NOT OPERATIONAL; qualified prospective cohort
  DOES NOT EXIST. Default live collection remains off. Later operation needs
  technical completion, trusted source configuration and causal prerequisites,
  then separately authorized prospective execution. Fitting, F17/F18/F20,
  PLAY and Product Promotion remain blocked.
- Decision/status changes contain no production code or test modifications and
  no live acquisition. Delivery checks and commit SHA are recorded below.
- Checks passed: ten changed Markdown documents, local-link resolution, fenced
  blocks/table structure, current versus historical policy consistency, risk
  boundaries and documentation-only scope; GitHub states/triage and native
  blockers; git diff --check. No runtime tests or full suite were run for this
  decision-only change. #70 retains needs-info; #86/#87 CLOSED; #88 CLOSED
  NOT_PLANNED without ready-for-human. No real source was acquired.
- Decision/policy/status commit: `01948d538537d6ac08d4cac3a2521bc5daabcb49`. This delivery
  record links its SHA; both commits are delivered to main. Current technical
  blockers are #89–#94, with #91/#92 awaiting actual source-contract evidence.
  Publisher permission outreach #88 is superseded, not successful. Separate
  causal operational provisioning and exact runtime source authorization remain
  unprovisioned; no qualified prospective cohort or live run exists.

## Historical implementation delivery: private source authorization, #89, 2026-10-10

- Implementation commit: `40118a4635052ddbebb07509d2e6cab017e4185b`, pushed to
  `main`. #89 CLOSED as completed; `ready-for-agent` removed. This delivery
  record adds the implementation SHA without changing runtime configuration.
- Implemented canonical protected `research-source-use-manifest-v1` and
  `research-real-source-use-decision-v2`, exact selected dependency verification,
  separate outcome manifests and private prospective F01 eligibility sidecars.
  Released V1 source-decision bytes/readers and F01/F04/F05/F06 meanings remain
  unchanged. Historical PERMITTED labels remain historical policy classifications.
- Added independently configured Ed25519 source authority, authenticated
  append-only authorization/withdrawal/supersession and fresh independent
  checkpoint continuity. Source authority remains separate from causal authority.
  Uncertain continuity, conflicting classifications, withdrawal, expired reviews
  and insufficient operations refuse current use; retained replay stays immutable.
- Acquisition, CB01 dispatch and protected admission recheck current authority.
  New risk captures remain private, protected and nonredistributable. Caller
  authorizers, restored approvals and retained keys grant no present authority.
- Default production REFUSES: source authority configuration, signed approvals
  and independent checkpoint service are not provisioned. No provider adapter,
  live fetch, #86 activation, fitting, PLAY or Product Promotion was introduced.
- Checks passed: 283 focused offline tests (45 source authority, 14 selected-graph
  and dispatch, eight capture/outcome, 213 F01/F04/F05/F06 and CB01 schema/trust,
  and three causal-gate/CB01 replay/retry compatibility tests). Formatter, Ruff,
  strict mypy for changed production modules and test helpers, documentation
  links/fences, pinned ADR digest, exact V1 binding, unchanged released schemas
  and `git diff --check` passed. Spec review findings were fixed and re-reviewed.
- Open blockers: #90 bounded transport, #91 seven-scope source qualification,
  #92 first automatic Pro League schedule slice, #93 FT-to-F13 history and #94
  FT-to-F19 outcomes. #91/#92 retain `needs-info`. Causal operational key,
  configuration, checkpoint continuity, owner approval and event-valid TUF
  admission remain unprovisioned. No qualified prospective #70 cohort exists.

## Historical adversarial review: source authorization, #89, 2026-10-10

This review records the findings and issue state at that time. The corrective
implementation and restored acceptance are recorded in the current state above
and in the latest delivery entry below.

- Reviewed `40118a4635052ddbebb07509d2e6cab017e4185b` against #89 and ADR 0006.
  Two MAJOR findings reopen #89 with `ready-for-agent`: withdrawal during final
  validation can permit dispatch or commit protected admission, and the outcome
  manifest omits supplemental fact sources and applicable raw dependencies.
- Retained [review evidence](../research/issue-89-adversarial-review-2026-10-10.md)
  and deterministic offline reproductions. Production code is unchanged. No
  separate corrective ticket expands #89's scope.
- Checks: 45 existing source-authority tests passed; one new review test passed
  and three strict expected failures reproduce the findings. Formatter, Ruff,
  strict mypy for the new Python file, documentation/static checks and
  `git diff --check` passed.
- #90 may proceed with offline transport implementation. Its operational source
  integration depends on corrected #89 acceptance. #90/#91/#92 readiness is
  unchanged; #91/#92 remain `needs-info`. #70 remains OPEN `needs-info`, and
  #86/#87 remain CLOSED.
- Remaining blockers: #89 corrections, #90/#91/#92/#93/#94 and separate causal
  operational key/configuration/checkpoint, owner approval and event-valid TUF
  admission. Default production still REFUSES. No real source authority,
  acquisition capability, live run, fit, PLAY or promotion was provisioned.

## Latest corrective delivery: source authorization, #89, 2026-10-10

- Corrective implementation commit: `28661c5abe88ad6e1b63ca8a04e8ed5db7d9387c`, pushed to
  `main`.
  Both accepted MAJOR findings are fixed. #89 CLOSED as completed and
  `ready-for-agent` removed. This delivery record adds the corrective SHA.
- M1: deterministic retained validation precedes the final fresh independent
  checkpoint. Withdrawal during validation refuses dispatch or rolls back
  protected raw/normalized and CB01 insertion. Refused admission leaves no
  catalogued artifact. The unavoidable interval before an external request
  remains explicit; there is no external atomicity claim.
- M2: OUTCOME binds exact settlement fact-evidence identities and applicable
  retained raw `source_digest` dependencies with source classifications.
  Attachment rejects changed evidence sets and raw identities. Supplements
  refuse until an exact authorization representation exists. Offline historical
  replay follows pinned identities without current authority, network, latest
  lookup or unrelated catalog scans. Pre-T selection and released V1 remain unchanged.
- Before edits: one review test passed and three strict expected failures
  reproduced M1/M2. After correction: all nine review cases pass normally.
  Focused validation has 401 distinct passes across source authority, protected
  artifacts, CB01, T10/F19, capture replay and F01/F05/F06 compatibility.
  One unrelated baseline failure remains in `test_cb01_sources`: its unchanged
  `_support` invocation omits required `f14_digest`. This correction does not
  broaden scope to that test defect.
- Changed-file formatter/Ruff, strict mypy for four production modules and test
  helpers, documentation links/fences, pinned ADR digest, unchanged V1 binding,
  released schema/Store contracts, two-axis review and `git diff --check` passed.
  Slow offline graph checks used an isolated retained fixture and temporary
  memoization of pure immutable Provider Health codecs/metadata and construction
  by complete inputs. Source manifests, raw verification and fresh authority
  checks were never cached. No full suite was required.
- #90 may proceed with offline bounded transport implementation. #90–#94 remain
  technical blockers; #91/#92 still need actual source-contract evidence.
  Real source authority/configuration and separate causal operational key,
  configuration/checkpoint, owner approval and event-valid TUF admission remain
  unprovisioned. #70 OPEN `needs-info`; no qualified prospective cohort exists.
  #86/#87 CLOSED. Default production still REFUSES. No live acquisition, adapter,
  fit, F17/F18/F20, PLAY or Product Promotion was performed or authorized.

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

Readiness remains BLOCKED. [#87](https://github.com/Awisalas/match-vet/issues/87)
specifies authenticated owner activation/withdrawal/restore continuity, admission
of a fresh exact TUF bundle, and exact profile/policy/pin binding. These mechanics
and owner provisioning are not operational. The original retained metadata is
expired; the [audit](../research/causal-profile-activation-audit-2026-10-10.md)
retains its factual findings and labels its earlier no-issue decision historical.
Real-source authorization is still a separate unresolved gate.

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
   #87 must implement authenticated owner history/restore continuity and fresh
   exact metadata admission bound to the unchanged profile/policy/pins. The
   owner must then separately provision authenticated current approval and
   continuity; issue completion alone activates nothing.
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

## Latest completed step: RESEARCH_ONLY causal trust-premise decision

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
- Created [#87](https://github.com/Awisalas/match-vet/issues/87), OPEN with
  `ready-for-agent`, for authenticated causal-profile activation/withdrawal and
  restore continuity, exact fresh TUF admission, and unchanged profile/policy/pin
  binding. The issue allows deterministic offline implementation only; production
  owner provisioning, activation, and collection remain separate operator steps.
- Decision commit: `f3fb7657d7f36fc49096695b976fdf29d450feaf`.
- Checks: local Markdown links and fenced blocks, decision/comparison coverage,
  issue-to-retained-pin consistency, historical/current-state wording, and
  `git diff --check` passed. Verified GitHub #70 OPEN with `needs-info`, #86
  CLOSED, and #87 OPEN. No production code or tests changed or ran.
- Exact remaining causal-operation blockers: #87 mechanics are unimplemented;
  no independently authenticated owner key/current checkpoint and signed
  activation/withdrawal/restore history are provisioned; no fresh exact TUF bundle
  is admitted under that owner authority; and no operational approval binds the
  exact profile, policy, pins, deployment/history, interval, and accepted premises.
  The original timestamp799 bundle is expired. Neither this ADR nor issue
  completion supplies runtime approval.
- Real-source authorization and operational readiness remain a separate blocker.
  No qualified prospective #70 cohort exists. #70 stays OPEN with `needs-info`;
  #86 stays CLOSED. F17, #37 fitting, production PLAY, and promotion remain
  blocked. No activation or collection occurred.

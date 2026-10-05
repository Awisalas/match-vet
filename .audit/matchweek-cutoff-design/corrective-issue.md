## Decision and scope

Implement the founder's clarified **one Matchweek-wide evidence boundary** for the complete seven-Target-League Friday-through-Monday slate. This issue is an implementation follow-up; the architecture task creating it does not perform implementation or authorize live acquisition, rebuilding either SQLite store, operational F artifacts, or timestamp requests.

Design: `docs/design/matchweek-wide-evidence-cutoff.md` and `docs/adr/0001-matchweek-wide-evidence-cutoff.md`.

Current F07 deliberately implements `individual kickoff - lead_time_seconds`, following #58/#62. The correction must add a new policy rule, never reinterpret the old one.

## Required model

`MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME`:

`T = min(exact controlling kickoffs of ALL INCLUDED memberships in the admitted complete F06 freeze) - explicit versioned lead_time_seconds`.

Every INCLUDED membership retains its exact F06/revision/policy-bound F07 reference with the identical T. Restore explicit **21600 seconds** for the initial corrected policy, based on founder resolution #13 and spec #1; retain no implicit F07 default. F06 creation remains persistence metadata, not a cutoff.

Complete all research, F11 evidence, F13 inputs/results, F14 decisions, and the existing complete F16 manifest before T. Pin one exact manifest through a protected existing SnapshotManifest with a stable deterministic logical-Matchweek identity. After selection or T, exact selected replay only. First post-T model computation is outside this smallest correction and would require another design for standalone frozen inputs.

## Acceptance criteria

- [ ] Add new-rule dispatch while keeping F07 schema 1, exact payload fields/digest algorithm, and legacy `KICKOFF_MINUS_LEAD_TIME` arithmetic and canonical bytes unchanged. Use a new honest policy identity/version/digest.
- [ ] Derive from the whole exact F06 freeze even for `persist_exact`; all seven scope provenance and original full-window eligibility must be established. Missing/date-only/ambiguous INCLUDED kickoff, empty included set, undefined earliest/T, unresolved earlier eligibility, or incomplete scope fails before corrected publication.
- [ ] Refuse a cold Saturday/Sunday rebuild that omits an earlier started/completed Friday candidate as NOT_SCHEDULED. Coverage of only remaining upcoming fixtures cannot establish the original Matchweek boundary. Existing selected state always wins; never choose latest.
- [ ] F11 collection and actual retention finish before T. Require known `published <= retrieved <= T`, but reject late collection even with early publication/caller timestamps. Guard jobs that cross T, changed context/location/rules, UNKNOWN/failed-attempt metadata, and every direct writer entry point.
- [ ] Freeze exact history, calibration, baseline/candidate inputs, research/model contracts, profiles, and decision policy before T. No first post-T F13 mutable-catalog enumeration, later in-Matchweek outcomes, refreshed weather, or changed decision state.
- [ ] Introduce one deep research-selection owner with seal, exact replay, and lookup by logical Matchweek. Reuse existing protected SnapshotManifest/index APIs. Its uniqueness key cannot vary with freeze/policy/profile/request or selector reader version. Preserve full dependency closure, one selected F11 digest, uniform F07 policy/T, and complete F16 membership coverage.
- [ ] Prove atomic single assignment and deadline acceptance under concurrent proposals, restart, interruption, and alternate F06/policy/profile. Canonical replay checks the deterministic mapping and rejects orphan/noncanonical proposals. A partial slate or missing pre-T selected state never becomes a recommendation later.
- [ ] Define and prove durable publication completion before T using repository-controlled time and protected completion evidence. Existing ArtifactStore `verified_at` is sampled before publication/catalog write and is insufficient alone. Crossing-T completion or a crash without confirmed pre-T completion refuses qualification. Add a narrow deadline/completion hook if needed without silently changing SQLite schema.
- [ ] F11/F13/F14/F15/F16 consumers validate exact common boundary, policy, freeze, and selected state. Equal timestamps with different identities are not equivalent. Resume after T may only verify/replay retained selected outputs; it cannot execute a missing research/model/decision writer phase.
- [ ] Normal new prospective F15/F16 runs and recommendation enrollment require the corrected rule/selection. Legacy dispatch remains available for explicit historical replay or permitted separate research/audit, never as a bypass into a new live recommendation cohort.
- [ ] New CB01 adapter requires selected exact lineage and homogeneous common boundary. Preserve fixture batches and existing strict `T < signed genTime < own controlling kickoff`, source rights, nonce/transport, pinned trust, exact replay, and existing late-token refusal.
- [ ] Preserve the full INCLUDED-membership × enabled-preference denominator independently of F16 availability. Missing anchors/F16/selection, failed witnesses, and unattempted rows remain unavailable cases; mixed policy receipts cannot qualify or shrink the denominator. The token proves existence by genTime, not pre-T collection or pre-Friday publication.
- [ ] Preserve old `cb01.py` and `cb01_trust.py` software digests/reconstruction through unchanged bytes or explicit historical dispatch. Preserve F13 old engine/research-adapter identity and exact replay; no global version bump that invalidates old artifacts.
- [ ] F19 preserves exact decision/manifest lineage and append-only outcomes/corrections. Post-cutoff evidence enters only permitted separate audit/evaluation/settlement paths.
- [ ] Publish successor chronology for #70 using one shared origin and exact selection/policy; retain released method 0.1.0 unchanged. Reject its old same-cutoff new-evidence allowance for corrected recommendations. Separate legacy and corrected cohorts; never relabel or silently pool them. Numerical profile gaps remain independently unresolved.
- [ ] No migration is expected: prove existing F07 fields and generic manifests suffice using isolated stores. If they do not, return an explicit revised design before adding migration or payload changes. No old rows/artifacts/migrations/immutable audit records are rewritten.
- [ ] Focused offline tests prove all guards and legacy canonical/replay compatibility, including Friday/Monday equality, earliest fixture in a different league, single-member whole-slate refusal, cutoff equality, publication crossing, late input variants, missing/mixed lineage, orphan selector rejection, concurrent/crash recovery, CB01 denominator/chronology/software identity, and F19 replay. No tests open either live store, acquire fixtures, create live operational artifacts, or send a TSA request. Ruff for changed Python; `git diff --check`.

## Dependencies and gates

Completed contract prerequisites: F06 #43/#57, F07 #58, F11 #62, F13 #64, F14 #65, F15 #66–68, F16 #69, F19 #71, CB01 #72. Preserve their released implementations/records as historical policy lineage; the correction adds prospective behavior.

This correction does **not** depend on resolving #70's numerical derivation profiles. Numerical derivation and cutoff implementation can progress separately. Meaningful candidate derivation, genuine corrected-cohort validation, and production promotion still require both the correction and #70's evidence-backed executable profiles. #37 promotion remains gated.

After implementation passes, the separately authorized live route remains: A authoritative, B unmerged → fresh approved all-seven F01/F05 → fresh exact F06 → explicit corrected F07 common T → all F11/F13/F14/F16 plus selection before T → exact replay/CB01 within existing witness windows → later F19/evaluation. Missed T means a future whole Matchweek. Do not perform this rebuild as part of the architecture task.

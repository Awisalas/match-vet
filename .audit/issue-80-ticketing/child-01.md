## Parent

Part of #80.

## What to build

MatchweekResearchRepository durably assigns one exact completed graph, obtains a single fresh postcommit event under matchvet-causal-selection-v2, and protects an exact completion receipt. Timely signed events may be delivered and persisted after T. Interrupted or failed operations leave the stable slot permanently unqualified.

## Exact scope

Selection/qualification owner, its private Store operation and ArtifactStore protected publication seams; private RFC3161 verifier/transport; immutable approved profile and authenticated trust provenance; selection/completion domain-v2 replay. Protocol binding includes the causal candidate contract digest. Descriptor authoring and stage schema/writer dispatch belong to the next child. Exercise this protocol through isolated successor graph fixtures at the private admission seam; do not expose a public graph/capability bypass or adopt a v1 graph as causal. Actual stage reader integration must remain refusing until the next child supplies supported successor schemas.

## Acceptance criteria

- [ ] Repository admission requires exact complete transitive graph and syncs its objects and containing directories before atomic selection. All INCLUDED members/seven scopes, one F11 state, exact F06/F07/common T, profile/model/engine/decision policy and candidate digest are bound. No lazy mutable-history/calibration discovery. The next child supplies actual successor stage dispatch; unsupported graphs refuse.
- [ ] Existing version-independent slots admit only one confirmed fresh insertion. Existing/idempotent/uncertain commit, competing loser, orphan row or occupied cross-version slot has no witness authority. Preserve WAL/FULL/VFS/fsync/locking and single-authoritative-history assumptions.
- [ ] Store's private _begin_witness requires selection_committed in the original live Store/PID/thread operation and constructs/consumes its sole attempt internally. Generate canonical binding plus fresh 256-bit entropy and positive nonce with at least 256 unpredictable bits only after confirmed commit. Transport accepts only that exact attempt. _accept_witness matches exact attempt, request, evidence, winner, graph and profile before receipt authority. Copy/serialization/reentry/fork/exit/close/reopen/reconstruction cannot grant authority.
- [ ] One request to https://timestamp.sigstore.dev/api/v1/timestamp, SHA-256, exact policy OID and certReq, with no retry/fallback or unknown-source redirect. Binding covers purpose/version, stable identity/slot, winner/F16/full graph, F06/F07/T, candidate/profile digests and randomness. Require exact nonce and imprint independently of generic OpenSSL verification.
- [ ] Implement matchvet-sigstore-causal-event-v1 using design-approved endpoint, policy revision/digest and OID 1.3.6.1.4.1.57264.2, approved signer/anchor/algorithm pins, critical timestamp-only EKU, signer identifier, strict unique ASN.1/CMS fields, signature and granted status 0. Independently approve operator/key-to-policy association. State operator-compliance and unsmeared-UTC trust premises explicitly.
- [ ] Parse signed genTime/Accuracy exactly; derive outward-rounded L/U without defaults and require U<T. Reject missing/empty/zero/negative/invalid/unsupported accuracy, >1-second ceiling, equality/late U, non-UTC/leap encodings, known smear/unsupported timescale and intervals crossing a UTC day boundary. Parsing never claims to detect hidden smear.
- [ ] Authenticate bootstrap root v10, rotations, metadata floors, signatures/lengths/target hashes, exact TrustedRoot and chain per the accepted design. Retain full provenance. Require full event interval within approved profile/authority/certificate validity and final metadata expiry bounds; no invented TUF not-before or local/current update-start qualification. Missing authenticated activation/floors or uncertain restore history refuses. Key/policy changes need a new approved profile.
- [ ] Distinguish historical retained verification from current revocation assurance. Missing current status is never reported checked. Known authenticated compromise/withdrawal invalidating an event refuses present qualification while preserving original inspection and occupied slot. Document offline compromise limits.
- [ ] Protected v2 completion references exactly selection plus witness provenance and complete raw request/response/binding/profile/trust/software closure, equal to the privately verified reference set. Generic schema-1 manifests and SQL remain unchanged. Dedicated payload holds event bounds; generic creation/verification times are advisory for v2. Preserve v1 single-ref receipt and timestamp meanings. Selection has no receipt backreference.
- [ ] Consume receipt authority before its first attempt. Commit exception permits read-only validation of an already indexed exact valid receipt only. Missing/invalid/ambiguous/late witness or lost receipt is terminal; restart cannot request/backfill/adopt orphan evidence even before T. Exact indexed valid receipt replays offline after T.

## Explicit non-scope

Prospective descriptor publication, F11–F16/F12/weather/F15 writer/schema migration, CB01/F19/report/evaluation adapters, integrated parent proof and activation. No generic provider registry, public phased workflow or alternate source. Do not change CB01 core or its witness semantics.

## Focused tests

Owner/protected-storage tests for fresh/uncertain/idempotent commit, stable-slot competition, full graph sync and exact ref-set protection; private lifetime and precommit/duplicate/copied/reconstructed/callback/fork refusal before transport; retained-wire nonce/imprint/policy/signer/ASN.1 attacks; exact interval and trust/floor/withdrawal cases; one-attempt request/receipt failures and offline indexed replay. Assert forbidden phases issue no request, retry, receipt or alternate graph. Preserve directly affected #75/v1 manifest regressions. Successor fixture tests prove the protocol boundary only, not real pipeline integration.

## Recommendation

GPT-6.1 Sol with high reasoning; diagnosing-bugs for failure injection and blast-radius for protected publication and legacy receipt dispatch. Keep reviewable commits within this owner; no activation commit.

## Blocked by

None. Can start immediately; ADR 0003 and #79 are settled, and #75–#78 are historically complete.

## Contract and restrictions

Implement ADR 0003 and the accepted causal Matchweek selection design linked by #80. Architecture is settled. Preserve the founder's common T = earliest INCLUDED kickoff minus explicit 21600 seconds, one stable logical Matchweek selection/completion slot across versions, and historical completion of #73–#78. Old v1/legacy meanings, canonical bytes, engine/software identities and readers remain intact. Unsupported successor semantics fail closed. Production refusal remains until every child and the entire #80 acceptance proof pass; child completion never authorizes source activation or partial production qualification.

Use isolated temporary stores, deterministic synthetic graphs and retained offline wire fixtures only. No live-store access, network activation, live fixture acquisition, live TSA/TUF requests, operational artifact publication, SQL migration, #70 fitting or PLAY promotion. Approved configuration in tests is isolated synthetic approval, never live activation. No historical artifact, migration, issue or audit rewrite. Run focused real-code tests and retained-wire checks for this boundary, directly affected v1 regressions, Ruff and mypy for changed Python, and git diff --check. Batch tests for Termux; do not run the full suite.

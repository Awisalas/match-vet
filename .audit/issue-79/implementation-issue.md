Part of #79. Implements ADR 0003 and `docs/design/causal-matchweek-selection-witness.md`.

## Outcome

Implement prospective `matchvet-causal-selection-v2` so the complete exact
Friday–Monday F11/F13/F14/F16 graph is durably selected once, followed by a
fresh same-operation Sigstore RFC3161 event bound strictly before common T.
No local/current-time label qualifies a candidate. Delivery/receipt persistence
may finish after T. Keep the founder rule and explicit 21600-second value.

#73 and #74–#78 remain historically complete under v1 deterministic proofs.
This issue supplies successor behavior/tests, not reopened historical acceptance.
Production refusal stays until this entire versioned path passes. Do not ship
an enabled partial adapter while #76 writers/readers retain incompatible semantics.

## Required scope

- Keep MatchweekResearchRepository as selection/qualification owner and existing
  Store/ArtifactStore durability/private-publication seams. New private RFC3161
  verifier has selection-witness semantics, distinct from CB01.
- Explicit prospective candidate contract and affected F11/F12/F13/F14/F16
  artifact schemas, F13 engine/adapter dispatch and F15 run identity. Current F13
  schema is 2; do not reuse its numeric version or globally alter historical hashes.
- All direct/reentrant/resume writer and acquisition/health metadata paths,
  selected-state CB01/report/evaluation/F19 consumers and legacy reader dispatch.
- Existing generic schema-1 manifests/indexes and stable selection/completion
  slots. No SQL migration unless isolated proof disproves their sufficiency.

## Acceptance

- [ ] Every selected actual collection/computation precedes its immutable artifact;
  exact full transitive graph, all INCLUDED members/seven scopes, one F11 state,
  F06/F07/common T, profile/model/engine/decision policy are validated and synced
  before atomic selection. No lazy mutable-history/calibration discovery.
- [ ] Stable logical-Matchweek identity and role slots ignore protocol version.
  One fresh confirmed unique insertion wins. Existing/idempotent/uncertain commit,
  competing loser or orphan row gets no witness authority. Cross-version occupied
  slots cannot be upgraded, bypassed or replaced.
- [ ] Only original live Store/PID/thread operation constructs canonical binding
  and unpredictable nonce/entropy after confirmed fresh commit. Private authority
  cannot escape, copy, serialize, reenter, cross fork, close/reopen or reconstruct.
- [ ] Store private _begin_witness is available only in selection_committed and
  internally consumes/constructs the sole operation-bound attempt. Transport accepts
  only that exact attempt. _accept_witness matches exact request/evidence/profile
  to it before receipt authority. No caller-built binding or parsed token alone
  can request/acknowledge. Test precommit, duplicate, copy, callback reentry, fork
  and reconstructed attempt refusal before transport.
- [ ] One witness transport attempt, no automatic retry/fallback or unknown-source
  redirect. SHA-256 imprint binds purpose/version, exact winner/graph/F16,
  logical identity, F06/F07/common T, candidate contract, authority profile and
  postcommit randomness. Require exact application nonce and imprint independently
  of generic OpenSSL verification, which permits a no-nonce query.
- [ ] Implement approved `matchvet-sigstore-causal-event-v1` profile: exact endpoint,
  reviewed policy revision/digest, OID 1.3.6.1.4.1.57264.2, pinned approved chain,
  algorithms, critical timestamp-only EKU and signer identifier, granted status 0,
  strict ASN.1/CMS fields, signature, nonce and imprint. Independently bind the
  approved operator/key to reviewed policy, since handler can echo request OID.
  Record explicit operator-compliance trust, not independently measured accuracy.
- [ ] Parse signed genTime/Accuracy exactly. Compute L/U with no guessed/default
  allowance, reject missing/empty/zero/negative/unsupported accuracy or >1-second
  policy ceiling, reject U>=T. Unsmeared discipline is an authority premise;
  DER parsing cannot reveal hidden smear. Refuse known smeared/unsupported sources,
  non-UTC/leap encodings or intervals
  crossing UTC day boundary under first profile. Outward rounding only.
- [ ] Authenticate TUF bootstrap v10/rotations/floors/target hashes, retain exact
  metadata/TrustedRoot/chain, and verify full witnessed interval within approved
  trust/certificate/final-metadata validity without local-time qualification.
  Immutable approved profile plus authenticated activation/withdrawal state
  own source approval. TUF proves approved pin provenance/historical constraints,
  never current update-start time from the same witness. Missing activation/floors
  or uncertain restore history refuses. Never claim historical metadata proves
  latest revocation state. Key/policy
  changes need explicit new approved profiles. Document offline compromise limit and explicit historical-versus-current
  revocation assurance. Known authenticated compromise/withdrawal invalidating
  the event refuses present qualification while preserving exact original
  inspection and occupied slot; never report missing current status as checked.
- [ ] #76 v2 gates return admission only, never trusted UTC. Advisory clocks may
  refuse wasted work; early published/retrieved/attempted/checked timestamps never
  qualify. Remove candidate CUTOFF_VALID authority derived only from local time.
  Split weather health_clock metadata from admission. Preserve source chronology,
  UNKNOWN semantics, exact contract/first-result guards and selected scoping.
- [ ] Retain an immutable unqualified candidate descriptor; F15 run inputs and
  every direct writer constructor carry its exact candidate_contract_digest.
  Shared owner alone dispatches timing semantics. Missing causal context refuses
  before catalog discovery/acquisition/computation, never infers v2 from F07.
  Every F11/F12/F13/F14/F16 input/output binds that same descriptor; read-only
  stored-context resolution never grants writer/witness authority.
- [ ] Cross-version candidate occupancy/first-result predicate scans all supported
  old/new F11/F12/F14/F15 associations by logical Matchweek. Prior timing-bearing
  v1/legacy candidate chain blocks starting causal work despite a vacant selection.
  A descriptor alone is not occupation; first guarded run/attempt/input publication
  pins it under transaction. Exercise old partial state followed by conflicting
  direct v2 work, competing descriptors and changed resume context.
- [ ] All direct and resumed writer paths recheck vacancy at publication boundaries.
  Selected/terminal-unqualified slot allows inspection/exact replay only. Candidate
  work physically completed too late cannot qualify via honest U<T. No later
  evidence/model/decision/artifact can join selected graph or change recommendation.
- [ ] Protect exact completion v2 reference set: selection plus witness provenance
  and complete raw request/response/binding/profile/trust/software closure. Keep
  v1's single-ref predicate and timestamp semantics. V2 event bounds live in
  dedicated payload; generic creation/verification timestamps are advisory.
- [ ] Consume receipt authority before its first attempt. Receipt commit exception
  permits only read-only validation of already indexed exact evidence. Missing,
  invalid, ambiguous or late witness and receipt loss leave occupied slot permanently
  unqualified. Restart cannot request/backfill from selection or orphan response,
  even before T. Valid already indexed receipt replays offline after T.
- [ ] Preserve every v1/legacy canonical byte, engine/software identity and reader.
  No existing v1/legacy candidate/selection is requalified. New domain versions
  fail old readers closed. Unchanged source primitives/F06/F07 keep old semantics.
- [ ] CB01 stays separate under existing T<genTime<kickoff. Add exact qualified
  selection-v2 dispatch without changing CB01 core/software commitment identity,
  omitting denominator failures or treating either token as the other's proof.
  Preserve exact F19 settlement lineage and separate promotion/fitting gates.
- [ ] Successor isolated tests cover suspension before/after request and during
  delivery; precommit request; replay/missing/forged nonce/imprint; wrong winner
  and alternate graph; U equality/late event; timely event delivered after T;
  crashes before request/after signing/during receipt; restart/backfill; unavailable
  network/source; local rollback/forward; reentrancy and competing cross-version
  writers; every direct/resume F11–F16/F12/weather gate; legacy readers/bytes,
  CB01 full denominator/separate chronology and F19 lineage. Negative cases must
  assert no request/retry/receipt/alternate graph beyond permitted phase.
- [ ] Run focused real-code successor tests and retained-wire verification, Ruff,
  mypy for changed Python and git diff --check. Keep existing v1 regressions green.
  Document truth/clock/SQLite/VFS assumptions and operational availability losses.

## Restrictions

Use isolated temporary stores, deterministic synthetic graphs and retained
wire fixtures. Do not open/touch either live SQLite store, acquire live Matchweek
fixtures, activate the source or publish operational artifacts. No #70 fitting,
founder-rule/six-hour change, production PLAY promotion, new remote graph service
or reinterpretation of old artifacts. Production timing implementation belongs
to this issue, not #79; live activation requires its separately scoped operation.

Accepted decision records are pushed in commit 6a9edebdc9ce1a2feede2307b43c4a04c9d9f485.
[ADR 0003](https://github.com/Awisalas/match-vet/blob/6a9edebdc9ce1a2feede2307b43c4a04c9d9f485/docs/adr/0003-causal-matchweek-selection-witness.md) and
[exact architecture](https://github.com/Awisalas/match-vet/blob/6a9edebdc9ce1a2feede2307b43c4a04c9d9f485/docs/design/causal-matchweek-selection-witness.md) are the implementation contract.

## Decision, 2026-10-08

The current user authorization explicitly permits a prospective causal-event
boundary while forbidding production timing implementation. Adopt ADR 0003,
`matchvet-causal-selection-v2`, for new versioned work only. ADR 0002's
actual-at-return impossibility diagnosis remains accepted. The default production
clock/provider continues refusing until the successor implementation passes.

Choose Sigstore RFC3161 as the first witness protocol under an explicit approved,
honest/uncompromised authority and UTC-policy-compliance premise. Its signed
Accuracy defines the event bound; compute U=genTime+accuracy exactly and require
U<T. The handler's fixed one-second assertion is not an independently measured
error, and its echoed policy OID is not independent source qualification.
Approve exact endpoint/signer/policy association through the versioned profile.
No guessed allowance, local/current-time fallback or automatic alternate source.

## Founder invariant and causal proof

Keep the complete exact whole Friday-Monday F11/F13/F14/F16 state before common T,
with unchanged earliest INCLUDED kickoff minus explicit 21600 seconds. After T
no new evidence/model/decision can alter the selected recommendation.

Every actual selected F11 collection and F13/F14 computation precedes its immutable
artifact. Exact artifacts and complete F16 graph are durably validated before C,
the fresh atomic unique logical-Matchweek selection commit. Only confirmed C in
the original private operation may construct the unpredictable selection-bound
request. The authenticated remote event E follows it: all selected work/artifacts
<=C<request<=E<=U<T. Immutable exact closure blocks post-witness additions.
Delivery and protected receipt persistence may finish after T.

This retains honest local code/kernel/storage, collision resistance, WAL/FULL/
fsync/VFS/locking and one authoritative catalog assumptions. The TSA signature
alone does not attest SQLite or prove research was performed.

## #75 and #76 successor semantics

#75 v2 replaces the local postcommit actual-at-return observation with the causal
remote event. Preserve fresh insertion, stable version-independent slots, private
Store/PID/thread lifetime, one request/receipt attempt and exact selected replay.
Missing/invalid/ambiguous/late witness or lost indexed receipt leaves the occupied
Matchweek permanently unqualified. Restart never requests/backfills from persisted
selection or orphan response; only an already indexed valid receipt can replay.

#76 v2 candidate gates enforce vacancy and exact contract/first-result/lineage
rules but cannot qualify using local timestamps. Direct writers and F15 run/resume
carry one explicit immutable candidate-contract digest. Cross-version conflict
checks include old partial chains; v1 candidates are never silently adopted or
hidden by new media types. Local/system time is advisory. Physical late candidate
work may run while vacancy remains, but cannot obtain an honest U<T or alter a
selected graph. This openly changes the stronger v1 physical-writer-stop claim
without weakening the founder selected-state invariant.

## Trust, compatibility and storage

Current revocation assurance is distinct from historical retained-profile replay.
The MatchVet event profile adopts the TSA UTC assertion under uncompromised
authority trust; it does not claim offline signatures satisfy all TSA policy
current-revocation obligations. Known authenticated invalidation refuses present
qualification while retaining original graph/receipt inspection and occupied slot.
TUF authenticates approved pins/historical metadata, not latest status from the
same token. Missing activation/floors or uncertain restore history refuses.

New candidate/run/artifact/engine/domain completion identities are prospective.
Every old v1/legacy byte and reader retains its original meaning. Stable selection
slots span versions. No old selection/candidate is upgraded or requalified.
Existing deterministic #73/#74-#78 acceptance remains historically complete; new
causal semantics require successor tests, not reopening their history.

CB01 remains the separate post-T/pre-kickoff enrollment witness under
T<genTime<kickoff. The new witness proves full selected-state existence pre-T.
No substitution of tokens, windows or core CB01 identity.

Existing generic SnapshotManifest schema1 and SQLite tables can retain exact
versioned request/response/binding/profile/trust/provenance artifacts. New domain
reader/private exact reference predicates are required; no schema migration is
justified or performed.

## Acceptance

- [x] Explicitly authorize feasible prospective remote-event boundary and preserve
  the actual-at-return impossibility diagnosis and founder cutoff.
- [x] Prove full transitive selected research ordering and exact cryptographic
  commitment, with trusted-source and honest-local premises separated.
- [x] Compare RFC3161/Sigstore, nonce-bound Roughtime and stronger hosted mechanisms
  against primary sources; no invented accuracy or elapsed/scheduling margin.
- [x] Define every affected #75/#76 direct/resume/acquisition/health writer gate,
  candidate/version dispatch, first-result conflict, terminal failure/restart rule.
- [x] Exercise isolated suspension/arithmetic counterexamples, retained real wire
  binding and shipped generic storage; disclose unimplemented v2 integration.
- [x] Specify old-proof limits, prospective compatibility, CB01 separation, exact
  provenance, schema sufficiency and operational availability losses.
- [x] Resolve adversarial findings and retain append-only reviewable proof trail.
- [ ] Publish the smallest cohesive implementation-ready successor issue and
  commit/push these design/research/proof records.

## Implementation and records

Successor issue: #80, ready-for-agent, a native child/dependent of #79. The single cohesive correction covers the
owner, RFC3161 profile, all prospective writers and consumer/legacy dispatch.
No partial provider activation. Availability trades include one live TSA request,
no fallback/SLA, terminal postcommit outage/crash/receipt loss and conditional
offline historical trust.

Records: docs/adr/0003-causal-matchweek-selection-witness.md,
docs/design/causal-matchweek-selection-witness.md,
docs/research/causal-matchweek-witness-2026-10-08.md and .audit/issue-79/.

No production timing code or activation, either live SQLite store, live fixture
acquisition/rebuild, operational artifact publication, #70 fitting, founder-rule
or six-hour change is authorized or performed in this decision task.

# Qualify complete Matchweek selection by a causal remote event

Date: 2026-10-08.
Status: accepted prospective design for #79. Production implementation and activation
remain unstarted. Supersedes ADR 0002's boundary choice for new, explicitly versioned
work only. Its actual-at-return impossibility diagnosis remains accepted.

## Decision

Authorize `matchvet-causal-selection-v2`: complete and durably select the exact
whole Friday–Monday F11/F13/F14/F16 graph once, then obtain an authenticated,
fresh-request-bound remote time-stamping event with defensible UTC upper bound
`U < T`. Persist its protected completion receipt afterward. T remains the common
cutoff from the earliest INCLUDED kickoff minus the explicit 21600-second policy.
The founder's rule and six-hour value do not change.

Use RFC3161 and the Sigstore production TSA as the first authority profile.
Qualification deliberately trusts the authority to honor its signed accuracy
assertion and named UTC policy. This is an explicit remote-authority premise,
not a claim of independently audited instance accuracy. The signed event is the
TSA time-stamping event described by TSTInfo, not local response return, delivery,
or receipt persistence. `U = genTime + signed accuracy`, with exact arithmetic
and no omitted uncertainty or guessed Android allowance. Require the whole
interval to fit approved trust validity and the upper endpoint strictly before T.
A bare `genTime < T` is insufficient.

[RFC3161 section 2.4.2](https://www.rfc-editor.org/rfc/rfc3161.html#section-2.4.2)
defines this upper endpoint. Sigstore policy OID `1.3.6.1.4.1.57264.2` requires
UTC within declared accuracy and leap synchronization. Its published monitor does
not itself stop issuance; authority compliance is therefore a trust premise,
not established by the monitoring code. The pinned policy, source inspection,
retained signature proof, Roughtime comparison and stronger-host alternatives
are recorded in [primary research](../research/causal-matchweek-witness-2026-10-08.md).
Do not activate if that explicit operator trust premise is withdrawn or missing.

## Causal proof

For every required acquisition or computation P and exact artifact A, honest
local execution establishes `P < A <= complete graph durability <= C`, where C is
the fresh unique selection commit. Only confirmed fresh commit creates private
same-operation authority to generate unpredictable nonce and commitment B.
The canonical B binds exact selection identity/digest, exact graph/F16, logical
Matchweek, cutoff/policy and witness profile. The authority processes its request
at the authenticated event E. Under the qualified authority premise:

```text
all selected collection/computation < immutable artifacts <= complete graph <= C
C < fresh B/nonce construction < request reception <= E <= U < T
```

Thus the exact qualifying research state, all required artifacts, the full F16
recommendation graph and its durable unique selection exist before T. Selected
closure is immutable. No artifact created after E can enter it. After T no new
evidence, model or decision state can alter the selected recommendation.

The signature alone proves commitment existence. Trusted local code/kernel,
collision and preimage resistance, honest WAL/FULL/VFS/fsync/locking, exact
complete graph validation, and one authoritative catalog history establish
execution and durable commit. These retain #75's local trust premises. This
is not remote execution attestation or protection against a hostile SQLite owner.

## Effect on #75 and #76

Replace #75's v1 postcommit actual-at-return clock acknowledgement only for v2.
Preserve fresh atomic single assignment, complete graph synchronization, one
winner, private Store/process/thread lifetime, one witness attempt, one receipt
attempt, protected indexing and exact selected replay. Receipt delivery and
persistence may finish after T because they record the earlier event.

Replace #76's prospective trusted-current-time writer gates only for new v2
candidate work. Local time may refuse wasteful work, but cannot authorize or
qualify it. Candidate collection/computation/artifacts are unqualified until the
final complete-graph witness passes. Preserve every structural writer guard,
selected catalog scope, exact input/result conflict rule and occupied-slot denial.

This openly supersedes the v1 guarantee that all unselected physical candidate
work stops at actual T. Advisory time cannot enforce that under suspension.
Late candidate work cannot qualify: its causal witness is necessarily late.
This does not weaken the founder invariant, which concerns the complete selected
recommendation state and forbids later changes to it. It does change an existing
implementation contract, so v2 must not use v1 acceptance tests as its timing proof.

## Failure and restart rule

Missing, malformed, ambiguous, wrong-bound or late witness permanently leaves
an occupied logical Matchweek unqualified. No alternative selection replaces it.
Generate no request before confirmed fresh commit or from persisted selection.
A crash, fork, close/reopen or operation exit destroys request/receipt authority.
On restart, verify an already indexed valid receipt only. Never adopt orphan
response bytes, backfill a witness or publish a missing receipt. An ambiguous
receipt commit allows one read-only check of indexed evidence; no publication
retry. Loss before receipt indexing sacrifices that whole Matchweek even if the
remote authority had already signed a timely token.

## Compatibility and storage

New candidate contract, affected timing-bearing artifacts/run identities,
selection, witness profile/provenance and completion domain readers carry explicit
versions. Old bytes and readers keep their original meanings. No v1/legacy
candidate or occupied selection is upgraded, requalified, or used as an implicit
v2 graph. Stable logical selection/completion slots do not include protocol version.
Unchanged historical source primitives, F06 and F07 may remain exact inputs under
their unchanged readers; they do not supply a v2 timing claim.

Keep generic SnapshotManifest schema 1 and existing SQLite tables. New immutable
witness/provenance artifacts and explicit selection/completion domain versions
fit that representation. The v2 completion's private exact reference predicate
must change; v1's single-selection-reference predicate remains intact. No schema
migration is authorized or shown necessary. The isolated storage experiment proves
representation only; successor tests must prove protected v2 publication/replay.

Offline replay verifies the historical retained trust state; it does not certify
current revocation status. The MatchVet profile adopts the TSA UTC assertion
under an uncompromised-authority premise and explicitly does not claim full
current-revocation-policy compliance from offline signatures. Known authenticated
compromise/withdrawal invalidating the event refuses present qualification while
preserving original graph/receipt inspection and permanent slot occupation.

CB01 remains separate: its historical witness proves post-T, pre-kickoff enrollment
under `T < genTime < kickoff`. The new selection witness proves complete selected
Matchweek state before T under `U < T`. Neither witness substitutes for the other.
CB01 identities and existing token semantics remain unchanged. Its corrected
selected-state adapter needs explicit v2 dispatch, with the full denominator intact.

## Consequences and next work

The production default remains refusing until corrective implementation and
successor proofs complete. Availability depends on one live network request and
one honest qualified TSA. No offline, local-clock, Roughtime or alternative-server
fallback is approved. Delay after a timely event is safe; pre-request suspension,
service outage and receipt loss can miss the entire Matchweek. There is no SLA.

#73 and #74–#78 remain historically complete under their deterministic v1 premise.
Successor tests cover the new event proof and all direct/resumed writer paths.
The cohesive corrective [issue #80](https://github.com/Awisalas/match-vet/issues/80)
implements this decision. The [architecture contract](../design/causal-matchweek-selection-witness.md) and
[proof record](../../.audit/issue-79/README.md) define the corrective implementation
scope. This decision authorizes that design, not production timing code, live
SQLite operations, Matchweek acquisition, or #70 fitting.

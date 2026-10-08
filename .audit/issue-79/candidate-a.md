# Candidate A: local selection followed by a causal RFC3161 witness

## Usage, caller's view

The owner accepts one completed prospective F16 graph. It returns qualified exact
selected state or refusal. Callers never receive request, commit or receipt
capabilities.

```python
research = MatchweekResearchRepository(store, witness_policy=qualified_policy)
selected = research.seal_completed_v2(f16_manifest_digest)

# Later, including after T or a process restart.
selected = research.replay_for_matchweek(season="2026-27", matchweek_friday="2026-10-09")

# F11/F13/F14/F16 writers use an explicitly prospective timing profile.
research.require_candidate_write(freeze_id, policy_digest, timing_profile="causal-v2")
```

The last call permits candidate work only. It makes no claim about current UTC or
pre-T qualification. An occupied logical selection slot refuses further candidate
publication, regardless of whether its receipt exists. F11 collection, F13/F14
computation and F16 assembly complete before their immutable artifacts are admitted.

## Problem

The accepted v1 protocol observes an upper bound for actual UTC at function return.
Arbitrary Android suspension makes that requirement impossible. A signed remote
event can establish an earlier event's chronology without predicting delivery time.
The founder rule still requires the complete exact F11/F13/F14/F16 state for the
whole Friday–Monday Matchweek before common T. Neither the rule nor its six-hour
value changes.

## Shape

These signatures are design sketches, not production code. The one deep owner
hides graph admission, unique assignment, commit confirmation, nonce construction,
TSA transport, strict verification and protected receipt publication. A private
protocol adapter owns RFC3161 parsing and trust qualification. Store and
ArtifactStore retain authoritative catalog and durability ownership. Public API
size is two operations, seal and replay, plus existing candidate admission.

```python
@dataclass(frozen=True)
class QualifiedWitnessPolicy:
    identity_digest: str
    protocol: Literal["rfc3161-causal-v2"]
    # Immutable versioned source, TSA OID, TUF bootstrap/trust identities,
    # allowed chain/EKU/algorithms, accuracy semantics and leap convention.

@dataclass(frozen=True)
class FrozenMatchweekResearch:
    selection_digest: str
    completion_receipt_digest: str
    timing_protocol: Literal["causal-v2"]
    # Existing exact season/Friday/F06/F07/F16 references retained.

@dataclass(frozen=True)
class _WitnessBinding:
    protocol: Literal["matchvet-selection-witness-v2"]
    logical_matchweek_id: str
    selection_slot_id: str
    selection_digest: str
    f16_digest: str
    dependency_graph_digest: str
    cutoff_policy_digest: str
    cutoff_at_utc: str
    witness_policy_digest: str
    nonce: bytes

@dataclass(frozen=True)
class _VerifiedRemoteEvent:
    lower_utc: datetime
    upper_utc: datetime
    binding_digest: str
    provenance_digest: str
    # Constructible only by strict policy-qualified verification.

class MatchweekResearchRepository:
    def seal_completed_v2(self, f16_digest: str) -> FrozenMatchweekResearch:
        # Admit exact complete graph under prospective profile.
        # Hold original Store/PID/thread writer ownership for this live operation.
        # Commit fresh unique logical slot after graph durability barriers.
        # Only confirmed fresh commit creates in-memory witness authority.
        # Generate cryptographic nonce and exact request envelope now.
        # Consume one witness request attempt; call qualified remote authority.
        # Verify exact request, signature, nonce, imprint, trust/policy and U<T.
        # Consume one protected receipt attempt; preserve exact provenance.
        # On ambiguous receipt commit, read indexed receipt only.
        raise NotImplementedError

    def replay_for_matchweek(self, *, season: str, matchweek_friday: str):
        # Dispatch exact supported v1/v2 semantics, never reinterpret.
        # V2 verifies indexed selection, witness provenance and whole graph.
        raise NotImplementedError

class _RFC3161Witness:
    def request_and_verify(self, binding: _WitnessBinding) -> _VerifiedRemoteEvent:
        # SHA-256 imprint of canonical, domain-separated binding bytes.
        # Same fresh nonce in TSTInfo must match exactly.
        # Preserve request/response/TUF metadata/chain/qualification policy.
        # No missing-field fallback and no locally invented uncertainty.
        raise NotImplementedError
```

### Causal proof

Let C be confirmed fresh selection commit. Let R be the remote event whose UTC the
qualified TSA records in signed TSTInfo. Let U be the defensible upper bound for R.
For each selected artifact A, its honest collection or computation P(A) precedes
its immutable bytes and durable graph admission. The complete immutable closure is
in the selection before C. After C the same operation generates the unpredictable
nonce and canonical binding, then sends the request to which the TSA responds.

```text
P(F11/F13/F14/F16) <= immutable artifacts <= exact graph durability <= C
C < fresh binding/nonce construction < request reception <= R <= U < T
```

Thus every selected collection/computation and the exact complete recommendation
state existed before T. Response delivery and receipt persistence do not occur in
this inequality. Content addressing, immutable selection memberships, strict F16
closure and selected catalog scoping prevent a post-witness artifact entering the
selected graph. The witness proves existence and order under honest local writers;
it does not attest to the truth of evidence or defeat a hostile filesystem owner.

RFC3161 signs the hash commitment rather than the local commit itself. Fresh
nonce generation and request construction after confirmed C supply the causal
link. Timestamping a previously built candidate commitment would lose that link.

### Trusted bound

RFC3161 `genTime` alone is insufficient. A policy-qualified TSTInfo must supply
documented accuracy semantics or a documented conservative source bound. Derive
U from the full signed fractional time and exact qualified allowance without
rounding down. Reject an absent, malformed, unsupported or unqualified accuracy.
Sigstore is a candidate only if primary documentation establishes its current
policy's UTC error claim and the response matches that qualified policy. The
existing CB01 example's signed one-second accuracy is evidence about that token,
not authority to invent a one-second allowance for any service.

Require the exact TSA policy OID, cryptographically verified trust distribution,
expected signer chain, timestamping EKU, supported algorithms, fresh matching
nonce and exact SHA-256 imprint. Retain signed raw bytes and authenticated trust
metadata for offline replay. HTTPS Date, local clocks and delivery duration never
qualify the event. Any leap/time encoding not defined by the qualification policy
refuses.

Trust bootstrap cannot rely on an unqualified Android wall clock. Authenticate the
explicit source profile and TUF signatures from pinned root material, enforce
retained rollback/version floors, then validate accepted profile, certificate and
trust-metadata validity throughout the signed interval `[genTime-accuracy,
genTime+accuracy]`. The signed event supplies the date used for this qualification.
This does not promise knowledge of the latest root state or later revocation
while offline. A policy's published accuracy claim is the trusted source premise;
a successful query does not experimentally prove that error bound.

### #75 and #76 changes

V2 replaces #75's actual-at-return observation with verified remote-event upper
bound following fresh commit. Existing stable selection and completion role IDs
remain version-independent, so v2 cannot open another slot for a v1 selection.
Replace the private `acknowledge(upper_bound, cutoff)` capability transition with
verification of the exact remote witness binding. Fresh-commit, original operation,
one protected receipt attempt and terminal occupied-slot rules remain.

#76's prospective v2 writer gates retain exact F06/F07 lineage, whole Matchweek,
profile/contract/model admission and occupied-slot denial. Remove their assertion
that a local clock certifies pre-T candidate publication. Do not return a trusted
UTC value to F11/F13/F14/F16 callers. An advisory clock may skip work but cannot
authorize it. Candidate timestamps remain metadata, with all timing qualification
deferred to the final causal witness. Late candidates can exist but cannot alter
an occupied selection and cannot obtain U<T. Candidate existence is distinct from
a qualified recommendation. This preserves the founder's required outcome.

V2 deliberately supersedes any #76 guarantee that all physical candidate work
stops at actual T. An advisory local clock cannot prove that guarantee under
arbitrary suspension. Prospectively versioned candidate work may continue before
selection occupancy without qualification. After selection commit, which a valid
witness proves earlier than T, publication gates deny further state that could
alter the selected graph. Engine and profile version identities must mark this
semantic change explicitly.

Historical #75/#76 deterministic tests remain valid evidence for v1 assumptions.
They do not prove v2. Successor tests must reject candidate timestamp qualification
and demonstrate late-delivered valid witness acceptance, terminal missing witness,
fresh-commit-only request issuance and selected closure invariance.

### Failure and attack table

| Attack or gap | Result |
| --- | --- |
| Suspend before request across T | Request eventually sent cannot earn a truthful U<T; terminal unqualified slot. |
| Suspend after request, before response | Earlier R with U<T permits delayed delivery; late R refuses. |
| Suspend during response delivery | No deadline inference from delivery; signed event decides. |
| Request before C | Private state machine refuses; prebuilt binding/nonce cannot enter v2. |
| Replayed response | Fresh unpredictable nonce plus exact imprint/policy rejects another attempt's token. |
| Wrong selection digest or alternate F16 graph | Canonical binding, indexed winner and full graph validation refuse. |
| Omitted/forged nonce or imprint | Strict mandatory-field verification refuses. |
| Response event after T | U>=T refuses, even if local clock is early. |
| Signed event before T, delivered after T | Accept only when defensible U<T, not merely genTime<T. |
| Crash before request after C | Occupied slot has no receipt; permanently unqualified. |
| Crash after signed event before receipt | Lost live operation cannot publish; permanently unqualified unless a valid receipt was already indexed. |
| Crash during receipt staging | Orphan bytes are never adopted. |
| Crash during receipt transaction | Read existing valid indexed receipt or terminal refusal; no publication retry. |
| Restart/backfill | Reader can verify indexed receipt; no witness request from persisted selection. |
| Network/TSA/Roughtime unavailable | No fallback or local-time qualification; occupied slot terminal. |
| Local rollback/forward | Cannot qualify. Forward advisory time may waste availability only. |
| Competing writers | Original writer ownership and unique stable slot choose one winner; loser gets no authority. |
| Legacy artifact/reader | Exact protocol dispatch or unsupported-version refusal; no v1 upgrade or reinterpretation. |
| CB01 witness substituted | Different purpose/domain separation/window refuses. |

One witness request attempt is the simplest implementation boundary. Disable
automatic transport retry and redirects to unknown authorities. This sacrifices
availability without sacrificing cutoff safety. A retry within the same live
operation could be sound with a new nonce, but it adds unresolved issuance and
response-choice state and is not required for the smallest corrective change.

### Compatibility and storage

Introduce an explicit prospective timing-profile identity for the candidate
pipeline and completion protocol v2. Leave existing F07 founder rule/value and
old artifact bytes unchanged. Never convert a v1 corrected selection, candidate or
legacy artifact into v2 by copying timestamps or minting a new receipt. Retain
exact v1 replay with v1's original trust interpretation. Old readers fail closed
for unknown versions; they must not infer qualification from generic completeness.

The existing generic object catalog and SnapshotManifest tables can store a
canonical witness-provenance artifact and receipt membership without a new SQL
column or migration. A protected v2 receipt references the exact selection and
the witness payload. Revise `_ResearchOperation._bind`, which currently requires
exactly one artifact reference, to authorize this exact v2 shape internally.
Publication guards must cover both ArtifactStore and StoreTransaction. Preserve
normal creation/publication metadata; put event lower/upper bounds in a dedicated
versioned payload rather than changing generic timestamp meaning. Retain exact DER
request/response, binding bytes, trust metadata, selected source/policy identities,
parsed accuracy and verifier policy/version. Source reassessment is an append-only
separate finding; it cannot rewrite original receipt bytes.

## Synthesis decision

Reserved for lead synthesis.

## Tradeoffs accepted

- We accept a permanently unqualified Matchweek after a postcommit network/crash
  failure in exchange for a simple rule forbidding restart witness backfill.
- We accept a single live operation holding writer ownership during remote
  transport in exchange for preserving the existing lexical authority boundary.
- We accept dependence on the qualified remote authority's honest clock and key
  policy in exchange for avoiding an impossible Android return-time premise.
- We accept source-policy updates requiring a new explicit qualification profile
  in exchange for retained offline replay that identifies its original trust.

## Alternatives considered

1. A remote selection service atomically accepts the full exact graph, assigns the
   stable logical slot and records a signed source event. Its public interface can
   also be deep, with one select-and-witness operation, and it hides fresh local
   capability machinery. It introduces deployment, remote storage durability,
   graph upload, trust authority and slot/history ownership. It does not prove a
   local SQLite commit before T unless that remains separately ordered before the
   request. For this repository the existing local durability/slot owner plus a
   qualified timestamp service is smaller operationally.
2. Nonce-bound Roughtime hides less in its public protocol if callers must map a
   nonce back to selection semantics. A private adapter can make interface depth
   equal to RFC3161 by setting NONC to a canonical-binding hash containing fresh
   entropy. It supplies a signed interval directly, but source/key qualification,
   permitted queries, availability and retained implementation support must be
   established. Keep it as fallback design only if RFC3161 accuracy qualification
   fails, not as automatic runtime fallback.
3. Existing actual-at-return clock retains a small interface but requires an
   impossible guarantee under arbitrary process suspension. It loses on validity,
   irrespective of apparent implementation simplicity.

## Open questions and risks

Which exact current Sigstore policy/implementation establishes a defensible UTC
accuracy interval, and how does qualification treat leap instants? Primary-source
research must answer before the protocol can be approved. Implementation must
distinguish authenticated trust/profile floors and interval validity from latest
online revocation knowledge. These are source trust questions, not reasons to
invent scheduling margins.

## Red-flag screen and next implementation step

No public temporal stages, capability registry, transport re-exports or pass-through
coordinator are added. The deep repository owns selection qualification. The
private protocol adapter owns wire/trust semantics, not graph policy. First build
an isolated real Store/ArtifactStore proof with synthetic graphs and strict
recorded witness fixtures; implement production v2 only in the corrective issue.

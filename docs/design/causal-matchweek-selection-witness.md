# Causal Matchweek selection architecture

This is the prospective design accepted in [ADR 0003](../adr/0003-causal-matchweek-selection-witness.md)
for #79, retained as the architecture contract. Its original sketches below
predate the completed #80 implementation and #84 integrated proofs. Runtime
activation remains refused. ADR 0002's return-time impossibility remains true.
The boundary authenticates a historical remote event and makes no
trusted-current-time claim.

[ADR 0005](../adr/0005-research-only-causal-witness-trust-premises.md) accepts the
existing conditional V1 premises for prospective RESEARCH_ONLY #70 corpus
collection only. [#87](https://github.com/Awisalas/match-vet/issues/87) covers the
remaining authenticated activation, withdrawal, restore continuity, and exact
metadata admission mechanics. Neither record activates the profile or grants
real-source authorization; the proof and immutable profile below remain unchanged.

## Caller usage and owner boundary

```python
# Sketch only. These APIs do not exist yet.
research = MatchweekResearchRepository(store, timing_profile=approved_causal_profile)
selected = research.seal_completed_v2(prospective_f16_digest)
# Later and offline, including after T:
selected = research.replay_for_matchweek(season=season, matchweek_friday=friday)
```

The repository owns graph admission, selection uniqueness, fresh commit authority,
remote witness binding, strict cutoff comparison, protected receipt and domain
replay. Store/ArtifactStore own durable catalog/object publication. A private
RFC3161 adapter owns DER/CMS parsing and approved source trust. Callers receive
qualified selected state or refusal, never authority, raw transport stages,
server choice, error allowance or a clock confidence label. Existing writer entry
points receive an explicit prospective candidate contract, not a trusted time.
This keeps protocol complexity behind the selection owner rather than distributing
commit/request/receipt coordination across F11–F16 callers.

```python
@dataclass(frozen=True)
class CausalCandidateContract:
    contract_version: Literal["matchvet-causal-selection-v2"]
    logical_matchweek_id: str
    freeze_digest: str
    cutoff_policy_digest: str
    cutoff_at_utc: str
    profile_digest: str
    decision_policy_digest: str
    engine_contract_digest: str
    witness_profile_digest: str

@dataclass(frozen=True)
class _VerifiedSelectionEvent:
    binding_digest: str
    provenance_digest: str
    lower_bound_utc: str
    upper_bound_utc: str
    # Constructor remains private to strict witness verification.

class MatchweekResearchRepository:
    def require_candidate_write(self, contract: CausalCandidateContract) -> None:
        # Check exact prospective contract, immutable first-result rules and vacancy.
        # A local advisory clock may veto; it cannot qualify or return trusted UTC.
        raise NotImplementedError

    def seal_completed_v2(self, f16_digest: str) -> FrozenMatchweekResearch:
        # Verify complete prospective graph and synchronize immutable closure.
        # Fresh atomic stable-slot commit. Only its confirmed return permits request.
        # Construct fresh canonical commitment+nonce; consume one request attempt.
        # Verify qualified remote event and U<T; bind exact protected receipt set.
        # Consume one receipt attempt, then exact replay or terminal refusal.
        raise NotImplementedError
```

No public event or operation capability constructor is authorized. No clock-type
relocation, generic provider registry or public phased workflow is needed.

## Exact operation sequence

1. Build the exact prospective F11 set for the whole freeze. All source acquisition
   and attempt completion precedes its immutable artifacts. F13 computation must
   precede model artifacts; F14 evaluation must precede decision artifacts. F16
   assembly must follow every required child. Do not defer computation to replay.
2. Validate every INCLUDED member, all seven schedule scopes, exact F06 revisions,
   one common unchanged F07 policy/T, one F11 set, profile/policy/engine identity
   and transitive F11/F12/F13/F14/F16 graph. Capture every replayed reference.
   Sources, history/calibration and candidate numerical inputs must be immutable
   selected dependencies, never lazy reads of mutable catalogs.
3. Sync the closed graph and all existing/new containing directories, then commit
   one protected selection into the existing version-independent logical slot.
   Vacancy checks and fresh insertion occur under the authoritative transaction.
   An idempotent existing row, commit exception or uncertain outcome gets no
   witness authority, even if subsequent lookup discovers a selection row.
4. Only confirmed fresh commit in the original live Store/PID/thread operation
   generates new unpredictable 256-bit entropy and a positive RFC3161 nonce of
   at least 256 unpredictable bits. Build and serialize the commitment now. Do
   not build or timestamp it before commit. Authority is private, noncopyable,
   nonserializable, nonreentrant and invalidated on exit/fork/reopen.
5. Consume one witness attempt before transport. Send one DER TimeStampReq to
   `https://timestamp.sigstore.dev/api/v1/timestamp`; use SHA-256, exact policy OID,
   nonce and certReq. Disable automatic retries and cross-authority redirects.
   Network timeout limits waiting, not UTC error. No write transaction spans HTTP.
6. Verify the exact response and compute the event's interval from authenticated
   TSTInfo. Require `U<T`. Bind the exact evidence digest set privately, then
   consume one protected receipt attempt before staging/publication.
7. Retain and sync the exact witness evidence closure; atomically index the protected
   completion receipt. This may happen after T. On a commit exception, read only
   an already indexed valid receipt, never attempt publication again.
8. Domain replay requires exact indexed selection, receipt, evidence, admitted
   graph and supported protocol. Missing receipt is permanent refusal. Restart
   cannot issue requests or recover receipt authority from persisted selection.

The slots stay occupied after failure. There is no replacement graph, alternative
freeze/policy/profile/version, second chance or restart rescue for that Matchweek.
A candidate run resumed before any selection may continue unqualified candidate
work. A resume with an occupied slot can inspect or replay only. That distinction
must be explicit in F15 and the CLI.

### Private operation transitions

The ordering belongs to Store's private operation type, not a convention in the
caller. Extend the existing owner with these signatures, still unimplemented:

```python
class _ResearchOperation:
    def _begin_witness(self, exact_graph, approved_profile) -> _WitnessAttempt:
        # Require selection_committed, original Store/PID/thread and fresh insertion.
        # Consume the sole request attempt before construction or transport.
        # Generate entropy/nonce and exact commitment/query inside this transition.
        # Keep attempt identity and binding internally; refuse any independent query.
        raise NotImplementedError

    def _accept_witness(self, attempt: _WitnessAttempt, event: _VerifiedSelectionEvent):
        # Require the same sole witness_attempt and exact winning selection/graph.
        # Match event to query/nonce/profile/evidence digest set; require U<T.
        # Bind the exact receipt predicate and enable one receipt attempt.
        raise NotImplementedError
```

Legal phases are `fresh -> selection_attempt -> selection_committed ->
witness_attempt -> acknowledged -> receipt_attempt -> finished`. Failure or scope
exit revokes authority. `_WitnessAttempt` is constructed only by `_begin_witness`,
binds the original operation, and cannot be copied/serialized or passed to another
operation. The private transport accepts that exact operation-produced attempt,
not caller-built `_WitnessBinding` bytes. Parsed signature evidence alone cannot
enable receipt publication; `_accept_witness` checks that exact attempt and source
profile. Adapter callbacks cannot borrow ambient selection/receipt authority.
Precommit construction, idempotent commit, fork/reopen, duplicate attempt and
request built from a persisted selection must fail structurally before transport.

## Bound and cryptographic commitment

The qualifying event E is the TSA time-stamping event asserted in signed TSTInfo
for this postcommit request. It follows reception of the exact request. RFC3161
accuracy bounds that event, not Android receipt or signing response delivery.
Use exact integer microsecond/rational arithmetic, outward conversion if needed:

```text
accuracy = signed seconds + signed millis/1000 + signed micros/1000000
L = genTime - accuracy
U = genTime + accuracy
accept only U < exact common T
```

Missing components inside a present ASN.1 Accuracy are zero under RFC3161.
Missing Accuracy, empty/all-zero Accuracy, negative/invalid components, unsupported
precision/overflow, unknown policy or accuracy above the profile's one-second
policy ceiling refuse. The allowance comes from the signed token and qualified
policy, never a local default. Do not use `ordering=true` as time confidence.
`ordering=false` is acceptable because request causality supplies required order.

Canonical UTF-8 JSON commitment fields are:

| Field | Binding |
| --- | --- |
| `purpose`, `schema_version` | `matchvet-pre-T-selection-witness`, 2; disjoint from CB01 |
| `logical_matchweek_id`, `selection_slot_id` | Existing stable identity/slot for season and Friday |
| `selection_digest`, `f16_digest`, `graph_digest` | Exact indexed winner and canonical complete dependency reference set |
| `freeze_digest`, `cutoff_policy_digest`, `cutoff_at_utc` | Exact unchanged membership/common boundary |
| `candidate_contract_digest`, `witness_profile_digest` | Exact prospective semantics and authority qualification |
| `postcommit_entropy`, `nonce` | Fresh live-operation randomness; RFC3161 nonce also signs the same value |

The SHA-256 messageImprint is over these exact canonical bytes, including entropy
and nonce. TSTInfo must carry that exact SHA-256 OID/imprint, exact mandatory
nonce and policy. Retain raw binding bytes and both DER messages. Recompute every
field against indexed selection and graph during replay. Request nonce alone
without a cryptographic selection commitment does not bind the graph. Digest
binding without postcommit fresh request construction does not prove commit order.

The proof is transitive, for every included member, not merely a timestamp on an
F16 label. Honest collection/computation precedes immutable selected artifacts;
all those artifacts precede complete graph durability and C; fresh request follows
C; E follows reception; qualified E <= U < T. Content addressing, complete exact
closure and selected catalog scoping prevent post-E substitution or lazy discovery.
The remote authority does not attest local execution or SQLite. Retain existing
honest local writer/kernel/storage and one-authoritative-history assumptions.

## Authority qualification and UTC handling

The first profile is `matchvet-sigstore-causal-event-v1`. It explicitly trusts
Sigstore's assertion of the entire declared event accuracy under OID
`1.3.6.1.4.1.57264.2`. The signed token supplies its actual numeric declaration.
The profile pins policy SHA-256
`97a3306df4f0ea5f5f64a938072bb802492b7cf1fca0661b20de0a6c98071bcf`,
the reviewed policy revision, approved algorithms and
TUF-distributed chain. Independently approve the association between the expected
operator/endpoint/signing key and that policy: the pinned handler echoes the
requested OID, so signed OID equality alone is only a binding consistency check. [Primary research](../research/causal-matchweek-witness-2026-10-08.md)
contains exact policy/handler revisions and the retained evidence bundle. The
operator's generic drift monitor alone does not enforce issuance refusal. This
profile accepts operator policy compliance as the trusted-source premise; it
must not describe it as independently audited hardware error.

The initial source identity uses the captured approved Sigstore signer and anchor
DER SHA-256 values `85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7`
and `2aca8fea5d3ce48b01cc77076293c280e6c23ffe44034757ee7833ca9f45d633`.
Bootstrap root v10 SHA-256 is
`836bff947925edfc23eb9ce17af66fb1e43bb5e2bdd240520985ae52b585eae9`.
Initial metadata floors are timestamp 799, snapshot 165 and targets 14, with
authenticated root rotations through at least 15. The retained initial TrustedRoot
SHA-256 is `6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`;
a later authenticated target is retained with its exact digest and must preserve
the approved source/chain or require a new profile. CMS uses SHA-256 and ECDSA
with the approved P-384 signer. Exact algorithm OIDs and certificate constraints
come from the retained DER, not certificate subject strings alone.

Require strict granted status 0, well-formed unique fields and supported DER/CMS,
correct content type/signer certificate identifier, allowed digest/signature
algorithms, valid signature, expected chain, critical timestamp-only EKU, approved
source URI and policy, exact nonce/imprint, and complete retained trust evidence.
Reject status modifications rather than accepting an ambiguous changed request.
Use Sigstore TUF bootstrap root v10 and authenticated rotations, retained
monotonically increasing metadata floors, exact TrustedRoot and approved TSA DER
identities. Pin the exact chosen verified versions/target hashes in the profile;
endpoint or moving main-branch identity alone is insufficient. Key/policy changes
require an explicitly new approved profile, never runtime fallback. The existing
CB01 pinned chain is demonstrable input evidence, not automatic approval for this
new role.

Activation depends on an immutable repository-approved MatchVet profile binding
the exact source pins, policy and approval interval, with authenticated local
activation/withdrawal state under the existing trusted configuration/catalog
boundary. Caller-built profile/provenance bytes do not approve an authority.
TUF evidence authenticates where the approved pins came from and their historical
metadata constraints; the token does not authenticate current TUF update-start
time or latest revocation state. No runtime rule claims ordinary current-time TUF
freshness from the same token being checked. Missing approved activation, missing
rollback floors or uncertain restored catalog/configuration history refuses.
Approved profile state may persist across reboot; request/receipt authority cannot.

Authenticate TUF signatures, lengths, target hashes and rollback floors without
using local wall time to establish UTC freshness. After verifying the token against
the approved pinned authority, require the entire witnessed interval within
profile and authority validity, certificate validity and final retained TUF metadata
expiry bounds. For TUF roles with no signed not-before field, do not invent one:
require U before each final role's expiry and use the separately approved profile/
authority not-before for L. Intermediate roots may be expired only under TUF's rotation rules.
Do not infer current/latest trust from these historical checks. Advisory wall
expiry or TLS checks may deny transport, but cannot approve the witness. A pinned
historical trust state cannot detect later undisclosed compromise or a newer
revocation while offline. This is a declared remote trust limit. Missing or
inconsistent approval/validity evidence refuses. Future trust reassessment appends
a separate record; it never changes the selected graph or historical receipt.

UTC GeneralizedTime and its signed fractional precision must be parsed exactly;
never round the upper endpoint down. The policy requires UTC leap synchronization,
not an unspecified smear. Unsmeared UTC discipline is an authority-approval
premise: GeneralizedTime cannot reveal a source secretly using smear. Refuse a
known smeared source or unsupported declared timescale; do not claim the parser
can detect hidden smear. If independent smear detection is required, this profile
is insufficient and must refuse. The first profile supports only unambiguous UTC values
and ordinary intervals. Reject `:60`, non-UTC/smeared representations, unknown leap
interpretation, or an interval crossing a UTC day boundary. The day-boundary
refusal is a conservative operational restriction that avoids unmodeled positive
or negative leap crossings without inventing an error allowance. Cutoffs retain
existing UTC formatting. A future broader leap profile needs independent approval
and tests; local clock conversion cannot supply it.

### Historical verification and current trust

The Sigstore policy's verification section requires current revocation status
during the certificate lifetime and treats compromised signing keys as invalidating
tokens. Its long-term annex requires evidence of key integrity. The captured
Sigstore chain has no CRL/OCSP distribution fields, so retained TUF material cannot
provide independently current revocation assurance offline.

The MatchVet profile deliberately adopts the policy's UTC accuracy assertion
under the approved uncompromised-authority premise. It does not claim that offline
historical replay satisfies every policy obligation concerning current revocation.
This relying-party limitation is explicit, not an inferred exception to the TSA
policy. Historical replay reports exact bytes and verification under the retained
approved trust state, conditional on that premise; it never labels the source
currently uncompromised merely because its old signature verifies.

If MatchVet already possesses an authenticated compromise declaration or authority
withdrawal invalidating this event, present qualification must refuse. Preserve
the selected graph and original receipt for exact historical inspection, append
the trust finding and keep the slot occupied. No new recommendation, replacement
selection or retroactive receipt is created. This is loss of trust in the deadline
proof, not new football evidence or recomputation changing the selected decision.
Missing current revocation evidence must never be reported as a successful current
revocation check. An offline caller receives the declared historical assurance
only. A stricter current-assurance consumer must refuse until its separately
required authenticated status evidence exists; no such service guarantee is
approved here.

RFC3161 wins because its event-bound semantics, named UTC policy and exact signed
Termux verification are documented. Roughtime also supplies a suitable causal
interval when nonce derives from this commitment, but current public source/key/wire
profiles need qualification and are not approved fallbacks. AWS ClockBound on a
qualified remote host exposes stronger hardware error information, but requires
building and operating a signer; it is not a public witness service. Retain these
as explicit alternatives, not silent runtime substitutions.

## #76 gates by writer

All v2 gates enforce vacancy at entry, before/inside artifact/catalog publication
and after return, plus exact candidate contract and first-result/identity guards.
They convey no UTC qualification. A concurrent selected slot blocks publication;
any already completed external retrieval stays outside the immutable selected
graph. Only an exact complete selected graph with the final witness qualifies.
Local timestamps are labeled advisory acquisition/publication diagnostics.

| Path | Prospective successor semantics |
| --- | --- |
| `require_preselection_open`, `candidate_artifacts`, candidate contract | New versioned admission without `_require_before` authority. Preserve stable slot, common boundary, profile/engine/policy and first-result checks. |
| F11 direct build/build-or-replay, history/catalog discovery | Unqualified collection must actually finish before retained immutable F11 bytes. Freeze request, response and history references; no early timestamp qualification. |
| F11 weather acquisition wrapper and health recorder | Keep pre/post retrieval and persistence vacancy guards. Split `health_clock` metadata from gate result; it must never return a purported trusted UTC value. |
| F12 direct attempt publication, UNKNOWN/failure attempts | Preserve exact request/capture/response lineage, first attempt and immutable outcome. Clock-derived `attempted_at`, `retrieved_at` and `checked_at` remain diagnostics; no cutoff-valid claim derives from them. |
| F13 direct build, retained history/calibration discovery and first model | Snapshot real inputs, retain no selected-week outcomes, complete computation before artifacts. Preserve factual source chronology checks separately from advisory collection time. New engine/adapter identity prevents old result discovery. |
| F14 build/build-or-replay, input assembly | Exact immutable profile/policy/F11/F13 inputs and deterministic computed result precede final graph. No later decision replacement. |
| F15 start/resume/inspect and run input identity | Bind causal contract/witness-profile digest into new run identity. Missing work may resume only with vacancy; selected or terminal unqualified slot permits inspection/replay, never another graph or witness. |
| F16 all phases/direct missing-phase entry | Preserve uniform F06/F07/common-T and full INCLUDED coverage. Publish complete immutable child/graph artifacts before selection. Selected outputs never discover new catalog state. |
| CLI, CB01 selected-state adapter, reports/evaluation/F19 | Dispatch domain qualification version. A candidate F16 or generic COMPLETE manifest alone is never qualified. Preserve denominator and separate enrollment/settlement roles. |

The old `published_at <= retrieved_at <= T` tests remain v1 tests. Under v2,
self-reported or local metadata cannot prove actual collection UTC. Known source
publication facts and temporal eligibility constraints remain required where their
contract calls for them; missing chronology stays UNKNOWN. Actual completed
collection before immutable F11 plus the causal chain establishes selected
collection before T. Successor artifact schemas must remove authoritative labels
based solely on local retrieval time. Do not retain `CUTOFF_VALID` as a v2 candidate
qualification merely because its metadata comparison passed.

Late work may physically run before the slot becomes occupied. It remains
unqualified and cannot obtain an honest U<T. This prospectively changes #76's
stronger physical-writer-stop claim while preserving the complete selected-state
founder invariant. It is explicitly versioned rather than described as an
unchanged gate.

### Direct-entry contract propagation

Retain the prospective candidate descriptor as its own canonical immutable artifact
before any v2 writer work. Its digest is unqualified input identity, not timing
authority or selection. The operator/application supplies the explicit causal
profile and complete descriptor to the research owner; the owner validates its
F06/F07, profile/policy/engine and witness-profile associations. F15 stores its
digest in the new run input contract and passes that same digest to every stage.
A different descriptor cannot resume that run.

Each direct F11/F12/F13/F14/F16 repository constructor receives an explicit
`candidate_contract_digest` for prospective causal creation. The shared research
owner resolves that digest and chooses the protocol; stage callers do not infer
v2 from unchanged F07 or from the current global engine constant. Missing context
never defaults to causal v2. Existing v1 entry semantics remain under v1 dispatch,
including their default clock refusal; a new causal creation request missing its
digest refuses before catalog discovery, external acquisition or computation.

F11 build/build-or-replay validates context before retained-result discovery.
F12 publish requires the attempt's contract digest to equal the constructor's.
F13 build/discovery and F14 input/decision assembly require every dependency and
new result to name the same descriptor. Every F16 phase and its manifest do the
same. Weather acquisition/health closures capture this context, while their
metadata clock remains separate. Domain readers resolve the retained descriptor
from exact stored artifacts for historical replay; that resolution never grants
prospective creation or postcommit witness authority. A stored v1 result cannot
become a v2 result by a lookup hit or copied descriptor field.

Preserve one cross-version candidate conflict predicate in the research owner.
It scans all registered historical and successor F11/F12/F14/F15 candidate
identities, resolves each exact F06 to its logical Matchweek, and applies the same
first-request/attempt/input/result and homogeneous profile/policy rules across
media/schema versions. Merely excluding old media types from a v2 graph is unsafe.
An existing timing-bearing v1/legacy candidate for this logical Matchweek blocks
a new causal candidate chain, even while the selection slot is vacant. Start the
new prospective contract only on a logical Matchweek with no earlier candidate
chain. Unchanged raw historical source primitives are reusable inputs, not such
a chain. Malformed or ambiguous recognized candidate associations refuse.

Publishing the descriptor alone is not candidate occupation. The first retained
run/attempt/evidence/input that uses it pins the active candidate contract under
the existing guarded catalog transaction. Competing descriptor users must recheck
the cross-version predicate inside that transaction before any first-state
publication. This uses existing artifact/run records; it does not add a new
version-dependent selection slot. A dormant descriptor cannot bypass an older
partial run. Successor tests must begin with vacant selection plus retained old
F11/F12/F14/F15 state and prove every conflicting direct v2 write refuses.

## Version dispatch and storage

Use new domain selection/completion version 2 with a distinct witness-provenance
payload/media type. Timing-bearing F11/F12/F13/F14/F16 artifacts and F15 run inputs
receive new schema/contract/adapter identities with causal contract digest. Current
F13 schema is already 2; its successor must use 3 or a distinct new contract name,
not call every artifact numerically v2. Freeze exact historical engine descriptors
rather than globally changing hashes used by old readers. New readers dispatch
by stored schema, contract and engine identity; unsupported versions fail closed.
No v1 candidate or recommendation result is adopted into a new causal selection.
Unchanged raw historical inputs and F06/F07 may remain referenced under their
original semantics. No cutoff rule or lead-time policy version is changed here.

Existing v1 selected replay remains read-only under its original proof. An occupied
v1 slot can neither be upgraded nor bypassed with versioned slot IDs. Old domain
readers must reject new selection/completion versions before timestamp comparisons;
generic `COMPLETE` is not production qualification. Prove that behavior with exact
legacy reader tests. Preserve CB01 core bytes/software identity; add selected-state
adapter dispatch without replacing CB01's post-T token window.

The existing schema stores arbitrary immutable objects, manifest references and
version identities; selection/completion slots already provide atomic uniqueness.
Retain request DER, response DER, canonical commitment, profile, authenticated trust
chain/metadata, parsed interval, verifier/software identity and exact selected graph
as protected content-addressed evidence. A witness-provenance payload names all
these exact refs; completion references the exact selection plus provenance and
its full evidence closure. Require equality to the privately verified reference
set, not a broad allowance for arbitrary extra receipt artifacts. Selection has
no witness backreference, avoiding a digest cycle.

V2 receipt `created_at_utc` is advisory publication metadata. Its event bounds live
in the dedicated signed-evidence payload. V1 keeps its existing created-time bound
meaning. Generic verification time retains its old meaning for both. Existing
SnapshotManifest schema 1 and SQL tables are unchanged; private `_ResearchOperation`
binding and domain readers require successor implementations. No migration is
needed for representation, as the isolated shipped-code storage proof demonstrates.
If protected-domain tests disprove sufficiency, stop and record a new design
question before any migration. This task performs no live migration or writes.

## Attack and recovery requirements

| Attack | Required outcome |
| --- | --- |
| Suspension before request | If E/U reaches T, permanent failure. Never extrapolate an old local sample. |
| Suspension after request | Accept only the authenticated original event with U<T; no delivery bound needed. |
| Suspension during response | Same event rule; late complete delivery is allowed within original live operation. |
| Request sent before commit | Impossible through private transition; injected/prebuilt requests refused. |
| Replayed response | Fresh nonce and commitment mismatch refuse; exact recorded replay allowed only for indexed receipt. |
| Wrong selection digest | Compare commitment to indexed stable-slot winner; refuse. |
| Alternate F16 graph | Compare complete closure and graph digest, not timestamp equivalence; refuse. |
| Forged/omitted nonce or imprint | Mandatory exact verification refuses, even if a generic OpenSSL check passes. |
| Remote event after T | Honest U>=T, refuse. Early genTime alone never passes. |
| Event before T delivered after T | Accept if full verified U<T and same operation owns receipt attempt. |
| Crash before request | If C committed, slot is terminal unqualified. Before C, no witness authority exists. |
| Crash after signed event before receipt | No indexed receipt, terminal unqualified. Do not adopt disk response or query authority. |
| Crash during receipt persistence | Exact already indexed valid receipt replays; orphan/partial receipt stays terminal. |
| Restart/backfill | Reader only; no fresh challenge or receipt from stored selection. |
| Network unavailable | Refusal, no clock fallback; postcommit slot remains occupied. |
| TSA/Roughtime unavailable | No automatic protocol/source fallback. Roughtime is not an approved profile. |
| Local clock rollback/forward | Cannot qualify; can cause advisory/transport availability failure only. |
| Competing selection writers | Fresh unique insertion wins; idempotent loser gets no request capability. Stable slots span versions. |
| Legacy artifact/reader | Exact historical dispatch, new unsupported semantics refused; no reinterpretation. |
| CB01 token offered as selection witness | Purpose/imprint/contract mismatch refuses; opposite time role remains separate. |

## Acceptance successors and implementation split

Historical #73/#74–#78 stay CLOSED. Their proofs remain valid under deterministic
trusted-return clocks. They are insufficient for the new prospective protocol.
Tests asserting unconditional post-T physical candidate refusal, trusted clock
absence/equality at every writer, and v1 created-time receipt qualification require
new version-specific successors. Keep their historical expectations intact.

The smallest cohesive correction is [issue #80](https://github.com/Awisalas/match-vet/issues/80) for the complete
causal selection owner, strict RFC3161 profile, prospective writer versioning and
all reader/consumer dispatch. Splitting activation from writer versioning would
permit unsafe partial qualification. Stage internal commits if useful, but do not
activate any half-migrated pipeline. Use only isolated synthetic stores and retained
wire fixtures. Required successor tests cover every attack above, all direct and
resume paths, altered selected closure, one-slot concurrency, legacy byte/engine
identities, CB01 full denominator and separate windows, and F19 exact lineage.

The current default provider remains unavailable. No production implementation is
claimed by this design proof. Service outage, terminal lost receipt and advisory
forward time sacrifice availability. The chosen rule preserves the cutoff rather
than rescuing a missed Matchweek. Production Promotion and #70 fitting remain
independent gates.

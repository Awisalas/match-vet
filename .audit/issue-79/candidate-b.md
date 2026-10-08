# Candidate B: remote selection registry with signed event attestation

## Problem

A public TSA sees a hash and cannot inspect MatchVet's exact selected graph or
its local durability. This alternative gives a remote Matchweek registry ownership
of graph validation, durable unique assignment and signed UTC event evidence.
The local owner still commits its unique immutable selection before contacting
the registry. The founder's complete whole-Matchweek state, strict common cutoff
and six-hour rule remain unchanged. This candidate proposes no implementation,
provisioning, subscription or live data access.

## Usage, caller's view

The caller completes the existing candidate pipeline and submits its F16 digest.
It sees the same two domain operations as the simpler local/TSA design.

```python
research = RemoteRegisteredMatchweekResearch(store, approved_registry_profile)
selected = research.seal_completed_v2(f16_digest)

# A later run, including one after T, can inspect existing protected evidence.
selected = research.replay_for_matchweek(season="2026-27", matchweek_friday="2026-10-09")

# Prospective writer admission creates an unqualified candidate only.
research.require_candidate_write(freeze_id, cutoff_policy_digest)
```

Callers do not upload individual artifacts, reserve remote slots, sample remote
time, construct requests or retry publication. The owner performs all those
steps inside one fresh operation. Per boundary discipline, network formats and
the remote registry's storage remain private.

## Shape

The local owner validates the exact complete closure, makes graph bytes durable,
and commits its stable logical-Matchweek slot. Only the winning original live
operation receives authority to generate the unpredictable challenge. It builds
a canonical capsule containing the exact selection, its complete dependency
graph and unchanged F07 cutoff policy. The remote registry verifies every digest
and relationship, then atomically commits the same unique logical slot and graph.
It records a qualified UTC event strictly after confirmed remote commit and
signs the capsule identity, challenge and event bound.

These are signatures and pseudocode, not production source:

```python
@dataclass(frozen=True)
class _SelectionCapsule:
    domain: Literal["matchvet-remote-selection-witness-v2"]
    logical_matchweek_id: str
    local_selection_digest: str
    dependency_graph_digest: str
    cutoff_policy_digest: str
    cutoff_at_utc: str
    challenge: bytes
    immutable_graph_bytes: tuple[bytes, ...]

@dataclass(frozen=True)
class _RegistryAttestation:
    capsule_digest: str
    logical_matchweek_id: str
    remote_selection_digest: str
    challenge: bytes
    event_upper_utc: datetime
    registry_policy_digest: str
    exact_signed_evidence: bytes

class RemoteRegisteredMatchweekResearch:
    def seal_completed_v2(self, f16_digest: str) -> FrozenMatchweekResearch:
        # Validate and durably commit one local slot.
        # Only confirmed fresh winner creates capsule/challenge now.
        # Send one request; verify exact attestation and U<T.
        # Publish one protected local receipt or leave slot terminal.
        raise NotImplementedError

    def replay_for_matchweek(self, *, season: str, matchweek_friday: str):
        # Verify already indexed selection/receipt under exact version policy.
        # No remote creation, recovery issuance or orphan adoption.
        raise NotImplementedError

class _RemoteMatchweekRegistry:
    def register_and_attest(self, capsule: _SelectionCapsule) -> _RegistryAttestation:
        # Verify complete capsule and request authentication.
        # Persist complete graph plus unique remote slot transactionally.
        # Require fresh confirmed commit; never issue from previous slot.
        # After commit, read a qualified event interval and require U<T.
        # Sign exact capsule/challenge under pinned registry purpose key.
        raise NotImplementedError
```

The deep public owner hides the whole distributed operation. Two internal owners
have substantive responsibilities: local research durability and remote registry
durability/attestation. They are not pass-through layers. The remote service must
receive complete bytes rather than references to mutable local files. Per the
single-source-of-truth rule, it compares the same canonical selection digest;
it never reruns recommendation selection or creates a competing F16 graph.

Both stable slot identities ignore timing-version changes. An occupied v1 slot
locally or remotely blocks v2 assignment. Remote replicas need one authoritative
uniqueness store; separate per-replica slots would permit competing selections.
This is a shared logical invariant, so isolation cannot replace serialization.

### Causal proof

Let A denote any selected artifact and P(A) its honest collection/computation.
Let C_local and C_remote denote confirmed durable commits. Let E denote the
remote UTC sample event, bounded by U.

```text
P(A) <= immutable A <= complete graph durability <= C_local
C_local < fresh capsule/challenge < request receipt
request receipt <= remote graph validation <= C_remote < E <= U < T
```

Consequently the exact local research graph existed before T, and the remote
registry durably possessed the same selected bytes before T. No new artifact
can enter either committed graph. Delivery and local receipt persistence can
occur after T without moving P(A), C_local, C_remote or E. The signer certifies
its own observed registry operation, which gives stronger graph/durability
attestation than a TSA's opaque imprint. It still cannot independently prove
that local F11 collection actually occurred. That honest-writer premise remains.

### Trusted UTC event

AWS documents ClockBound UTC uncertainty intervals on Linux EC2 and Nitro PTP
hardware error supplied through ENA. A qualified registry deployment could use
that evidence at E. Its signer binds the interval to the postcommit capsule;
it does not claim to bound response delivery or function return.
[EC2 ClockBound](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/compare-timestamps-with-clockbound.html),
[ClockBound source](https://github.com/aws/clock-bound/blob/main/README.md)

The AWS library is not an existing public signed registry service. This candidate
requires new deployment qualification, pinned signing keys, protocol definition,
trust updates, uncertainty-status validation, boot/restart rules and storage
durability controls. A measured uncertainty sample alone does not establish a
host-independent hardware theorem. Operator correctness and truthful error
bounds remain explicit trusted-source premises. If ClockBound cannot guarantee
E rather than only a later return label, the registry must use another qualified
event mechanism or refuse. No scheduling allowance may be guessed.

An alternative registry can commit first and obtain RFC3161 over its own
domain-separated capsule, then countersign the receipt. That uses a documented
event-bound protocol but adds a second service dependency and inherits the TSA's
operator accuracy premise. Merely moving Python to EC2 does not solve the old
literal return-time contract.

### Failure rules

The local process retains one original-operation authority. Suspension before
the remote request can only delay E. Delayed response after a valid pre-T E may
be accepted by that same operation. Crash before local protected receipt leaves
the occupied local slot permanently unqualified. Restart can verify an already
indexed valid receipt, never send a capsule rebuilt from persisted selection,
query the registry to mint a replacement, or adopt orphan attestation bytes.

A remote crash after C_remote but before valid attestation leaves its slot
occupied and unqualified. It cannot create a new event on restart to repair the
old commit. A crash after signing but before response delivery does not justify
fresh issuance. Lost evidence sacrifices qualification; remote and local slot
history still prevents an alternate selection. Signature, challenge, graph,
policy, signer or interval mismatch refuses permanently. Network or registry
unavailability has no local-time or alternate-authority fallback.

### #75/#76 and compatibility

#75 gains a prospective remote-event completion version; stable unique local
selection and fresh-commit capability remain. The completion receipt binds exact
registry attestation and graph provenance. #76 admits unqualified prospective
candidate writes without local UTC qualification and defers pre-T authority to
the final attestation. It keeps occupied-slot denial, immutable graph membership
and exact F06/F07 lineage. Local timestamps remain metadata or work-saving hints.

Existing v1 and legacy artifacts retain their original interpretation. Neither
remote upload nor version changes can qualify an old selection retroactively.
Old readers must refuse unknown versions. CB01 keeps its distinct post-T,
pre-kickoff purpose and token semantics. The registry domain cannot substitute
for CB01 or use a CB01 token to qualify selected research. Existing deterministic
v1 tests remain historical evidence; v2 needs fresh-commit, delayed delivery,
terminal crash, graph binding and cross-version slot tests.

The local generic artifact/manifest catalog can retain capsules and protected
receipts without assuming a SQL migration. The remote service necessarily adds
a complete graph catalog, durable unique logical-Matchweek selection index,
attestation provenance, authentication/authorization and its own transaction
schema. Remote retention, backup restoration and replica uniqueness must preserve
occupied slots forever; restoring an older backup must not allow replacement.

## Synthesis decision

Lead synthesis pending. I recommend rejecting this shape for #79's smallest
correction. Its extra graph attestation is useful only if remote possession and
independently owned registry durability become product requirements. The founder
rule needs the exact graph to exist before T, which the local fresh-commit plus
qualified public TSA chain already proves under honest local execution.

## Tradeoffs accepted

- We accept complete graph upload and an additional durable service in exchange
  for a remote signer attesting its own selected-graph ownership.
- We accept whole-Matchweek unqualification after either host loses evidence in
  exchange for forbidding post-restart attestation backfill.
- We accept external operator, key and storage trust in exchange for UTC event
  evidence that does not depend on Android delivery time.

## Alternatives considered

The local selection plus public RFC3161 witness has equal interface depth and
keeps one existing authoritative slot owner. It hides nonce, trust verification,
durability and receipt authority without deploying a graph registry. It is the
stronger practical choice for this repository. A remote-only selection authority
would hide local capability machinery, but changing the authoritative store and
allowing local import after T exceeds the correction and complicates legacy
uniqueness. The actual-at-return clock remains impossible under arbitrary
suspension and cannot win on apparent API simplicity.

## Open questions and risks

Does remote possession justify an extra service when the founder only requires
selected-state existence before T? Can remote backup/replica procedures preserve
the unique-slot tombstone indefinitely? Can the chosen hosted source qualify an
explicit event interval without falling back to return-time semantics? These
are deployment decisions for a future remote-ownership project, not blockers
that the smaller RFC3161 correction needs to inherit.

## Red-flag screen and next implementation step

No public stage API or wire object is exposed. The two owner modules hide real
knowledge rather than forwarding calls. Duplicate selection policy must be
avoided: remote validation verifies the canonical committed decision and never
recomputes it. The shape has substantial external ownership cost despite its
small client API. If selected later, first prove isolated two-host unique-slot
and crash behavior with synthetic graphs before provisioning any service.

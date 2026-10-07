# Candidate B: a signed witness for a completed selection event

## Problem

A remote authority can witness an event after a durable local selection commit without trusting the phone's elapsed clock. That gives a useful proof of the selection deadline. It cannot implement the current `TrustedUTCClock.observe()` contract, which requires an upper bound on actual UTC at function return, including suspension. Candidate B is therefore **inadmissible as the production trusted clock for #75**. It is an architecture for supplemental historical evidence, or a separately reviewed future completion protocol. Neither use authorizes new production work in this task.

The constraints are the exact F06/F07/F16 graph, fresh protected selection assignment, one live receipt attempt, failclosed prospective F11–F16 writers, and permanent refusal when an indexed selection has no receipt after restart. [ADR 0001](../../docs/adr/0001-matchweek-wide-evidence-cutoff.md) and the current return-time contract remain authoritative. This document sketches signatures only. It changes no production code, database, acquisitions, rebuilds, or #70 work.

## Usage, caller's view

The caller asks for a witness of its completed commit. It never receives a value named current UTC, and the witness does not implement `TrustedUTCClock`.

```python
# Hypothetical internal use in MatchweekResearchRepository, after the exact
# selection publication returned successfully in the same live operation.
from matchvet.selection_witness import SelectionEventWitness

witness = SelectionEventWitness.from_profile(retained_profile_bytes)
proof = witness.attest(operation._fresh_commit_event())
# proof.event_upper_bound_utc concerns the authority's event only.
# No operation._acknowledge(...) call accepts this proof.
```

A future completion v2 may attach this evidence only after a separately valid current-UTC observation has supplied the existing acknowledgement authority.

```python
# Pseudocode for an optional supplement, not an available production method.
proof = witness.attest(operation._fresh_commit_event())
upper_bound = self._require_before(graph.cutoff)  # unchanged clock requirement
operation._acknowledge(upper_bound, graph.cutoff)
# TODO: bind exact witness evidence and trust profile in completion v2.
# TODO: preserve the same one-use private receipt publication path.
```

An offline reader verifies historical evidence without opening writer gates or reconstructing authority.

```python
proof = SelectionEventWitness.verify_retained(
    envelope_bytes,
    expected_selection_digest=selection.digest,
    accepted_profile_digest=receipt_profile_digest,
)
# proof describes a retained event. It does not authorize acknowledgement,
# missing-receipt recovery, collection, or a new prospective write.
```

The runtime production usage remains `MatchweekResearchRepository(store)` with the refusing default until an independently qualified clock is available. Passing this witness as `clock=` is a type error in the sketch and would lack `observe()` at runtime.

## Shape

### Data and signatures

```python
@dataclass(frozen=True)
class SelectionEventProof:
    selection_digest: str
    event_upper_bound_utc: datetime  # aware UTC, rounded outward
    evidence_envelope: bytes       # canonical domain document; raw wire is internal
    profile_digest: str
    # Deliberately no confidence="TRUSTED" or upper_bound_utc clock field.

class _FreshCommitEvent:
    """Opaque, nonserializable capability owned by one live Store operation.

    Construct only after a fresh protected selection commit returned successfully.
    Bound to selection digest, exact graph/Matchweek identity, cutoff, operation,
    process and thread. No constructor from a retained digest or stored token.
    """
    # TODO: private ownership check and fresh challenge issuance.

class SelectionEventWitness:
    @classmethod
    def from_profile(cls, retained_profile_bytes: bytes) -> SelectionEventWitness:
        """Validate a configured immutable trust profile; never learn trust from DNS."""
        raise NotImplementedError

    def attest(self, event: _FreshCommitEvent) -> SelectionEventProof:
        """Issue fresh challenge after validating live event ownership.

        Hide request creation, protocol parsing, pinned trust verification,
        source policy, accuracy handling and canonical evidence construction.
        Failure raises WitnessUnavailable; it grants no receipt authority.
        """
        raise NotImplementedError

    @staticmethod
    def verify_retained(
        envelope_bytes: bytes,
        *,
        expected_selection_digest: str,
        accepted_profile_digest: str,
    ) -> SelectionEventProof:
        """Verify exact evidence under its accepted profile; return historical fact."""
        raise NotImplementedError
```

`SelectionEventProof` construction belongs to the verifier. A dataclass alone is not a security boundary. Store's existing operation ownership remains the authority boundary. The new opaque event handle would expose only a narrow fact about a successful commit; it would never let the witness mutate Store or grant receipt authority. This is `encode-lessons-in-structure` and `boundary-discipline` applied to the distinction between historical evidence and current time.

| Module | Knowledge owned | Interface depth |
| --- | --- | --- |
| `matchweek_research.py` | Exact graph admission, unchanged clock gates, selection/completion protocol dispatch, replay | Caller still seals or replays one exact selection; no transport policy leaks into F11–F16. |
| Hypothetical `selection_witness.py` | Remote witness trust profile, challenge binding, protocol verification, canonical event evidence | One `attest` operation hides networking, wire formats, pinned roots, accuracy and refusal rules. `verify_retained` is its offline counterpart. |
| `store.py` | Durable fresh assignment, private operation ownership, one-use acknowledgement/publication authority | A private fresh-event handle exposes commit identity while retaining all authority in Store. |
| `artifacts.py` | Immutable bytes, protected retention, catalog durability | Existing content and manifest references hold evidence; no special timestamp tables. |

This avoids separate public fetch/parse/validate/save stages and public transport options. Caller-to-witness-to-private-protocol flow needs at most three files. Protocol details stay behind one module; implementation can split private codecs if their size warrants it. Each live operation owns its own challenge state, so concurrent attestations cannot share a mutable last nonce. Static trust profiles may be shared by immutable digest. No cache supplies current time.

### What the signed event proves

Let `c` be completion of the successful durable selection commit, `q` generation of a fresh unpredictable challenge by that same live operation, `s` the authority's processing event, and `r` local verification/return. Under honest local code and storage and the configured authority's UTC accuracy guarantee:

```text
c <= q <= s <= r
s <= U
therefore c <= U
accepting U < T proves c < T
```

No bound on `r - s` or phone oscillator rate is needed for this implication. The authority need not observe SQLite; the local program establishes the first ordering, and the authority signs its response to the later challenge. This remains local application evidence under an honest process/kernel/storage premise. A signature does not independently attest SQLite durability or the moment when the local challenge was generated.

For RFC3161, bind a domain-separated encoding of exact selection digest, logical Matchweek, graph/cutoff identity, operation identity, and fresh entropy in the message imprint. Request and verify the nonce as well. Validate CMS signature, accepted signer chain/key, timestamp EKU, algorithm, exact imprint/nonce/policy, and accuracy. `U = genTime + accuracy`, with outward rounding. Missing accuracy is unknown unless the accepted policy supplies an explicit finite guarantee. The imprint alone is insufficient if the same payload was submitted before commit. Fresh entropy and honest generation after commit establish the causal ordering. These properties follow from [RFC3161 section 2.4.2](https://datatracker.ietf.org/doc/html/rfc3161#section-2.4.2).

For Roughtime, derive the nonce from a domain-separated commitment to those same identities and fresh entropy, using the exact configured wire version's nonce requirements. Verify delegation, pinned root, signature, Merkle inclusion and nonce binding. `U = MIDP + RADI` bounds the signed processing event under the server's guarantee. The historical proof does not perform the elapsed aging described in [RFC10049 section 6](https://datatracker.ietf.org/doc/rfc10049/). A pinned key authenticates the server's assertion; it does not establish operator honesty or clock discipline.

### Why it fails the existing contract

Take `T = 12:00:00`, commit at `11:59:58`, and a correctly signed event with `U = 11:59:59`. Suspend the phone until `12:10:00` after the server signs, or immediately before the provider returns. The token and all its validity checks remain identical. The event proof correctly proves `commit < T`; it does not prove `actual UTC at return <= 11:59:59`.

Another request does not fix this. The last response can also be delayed. A timeout limits waiting only when code runs again; it cannot prevent suspension after the last timeout check. Adding a fixed margin requires a real bound on that entire delay. Returning infinity would fail the finite datetime representation and every `u < T` qualification.

The causal inequality preserves the founder's durable-selection-before-cutoff fact. Replacing `_require_before()` or the postcommit observation with it would weaken #75's stronger existing return-time guarantee. The user forbids that change. Keeping the current clock contract means this design cannot make production selection available.

### Every prospective writer remains dependent on the clock

| Path | Current gate and why an event witness is insufficient |
| --- | --- |
| F11 | `require_candidate_write`, acquisition `require_preselection_open`, provider-health clock and guarded publication require a current bound before further research or writes. A past signed event cannot authorize future collection. |
| F12 | Feature creation enters `require_candidate_write` and `candidate_artifacts`; a witness of an earlier selection event cannot open either. |
| F13 | Model builds/other candidate writes use the same gates and guarded artifacts, with first-model state checks. Proof about another event cannot cover computation/publication after a pause. |
| F14 | `require_candidate_contract`, candidate-write gates, and guarded publication combine clock closure with exact profile/policy identity. Retaining identity checks does not supply missing current time. |
| F15 | Start and resume gate the prospective contract before the coordinator and pass the clock into F16. A new process cannot reuse historical witness bytes to resume prospective work. Exact selected inspection remains read-only. |
| F16 | Whole-Matchweek processing gates contract/candidate writes and propagates the clock to nested F11/F13/F14 collaborators. A final selection witness cannot retrospectively authorize those earlier entry gates. |
| ArtifactStore / selection | Guards execute before object work, around catalog publication, and after commit; selection also has its private precommit callback and repository postcommit observation. Event bounds cannot replace current bounds at these call sites. |

Source anchors are `f11.py:180`, `f12.py:231`, `f13.py:156`, `f14.py:346`, `f15.py:112`, `f16.py:105`, `matchweek_research.py:137`, `matchweek_research.py:504`, and `artifacts.py:551`. Every corrected prospective writer must continue refusing without a qualified `TrustedUTCClock`. A contract-changing proposal would have to review all these paths; changing only selection completion leaves the system unusable and changing only the gates silently weakens it.

### Trust, failure, restart and provenance

An accepted profile pins protocol/version, source roots or certificate policy, signature algorithms, UTC timescale and leap handling, maximum accepted accuracy, source accuracy policy and independent approval of that policy. Signing-key rollover is an authenticated trust configuration change. Generic CB01 TSA identity and a live endpoint response provide no automatic clock-provider authority. A TSA certificate-time bootstrap policy must be explicit and cannot depend on a guessed phone wall clock or disabled chain validation.

Retain the raw signed response and request as protected bytes, with hashes, exact challenge inputs, selection/graph/cutoff identity, operation/boot/process identifiers, accepted profile bytes/digest, verifier version, signed interval, rounding, and verification result. Identifiers help audit local ordering; they are not remote attestations. A v1 evidence envelope states `SELECTED_COMMIT_EVENT_BOUND`, never `CURRENT_UTC_AT_RETURN`. Estimated uncertainty cannot become a hard bound. Unknown error stays unknown.

Bounded network retries use fresh request identity and fresh entropy, each still issued after the same fresh commit. Delayed valid responses may retain historical value but never open current gates. Missing required source, absent accuracy, stale/replayed nonce, bad signature, unsupported version, unverifiable certificate policy or unknown timescale refuses. With multiple required sources, specify the honesty premise. Under an at-least-one-honest premise, use the maximum upper endpoint, not the minimum or median; refuse contradictory policy/interval evidence rather than inventing a consensus guarantee.

Restart destroys the fresh-event capability and the original receipt authority. A retained signed response can explain a historical event only. It cannot turn an indexed selection lacking its indexed receipt into a qualified selection. Crashing after receipt commit uses existing indexed replay; crashing before receipt commit never adopts orphan tokens or receipt bytes. Concurrent operations remain subject to the existing one-owner and stable selection-slot rules. Retried witness network requests are historical evidence attempts, never new selection or receipt attempts.

Current completion v1 has exactly one artifact reference, the selected manifest, and stores the actual-return upper bound in `created_at_utc`. Its bytes, reader, version, and semantics must stay unchanged. The witness cannot be stuffed into the `source` string, which v1 discards, or appended as an extra reference without changing the contract.

A future supplemental completion v2 can use existing generic artifacts and manifests. It must define a new completion protocol version and exact reader, reference the selected manifest plus an immutable evidence envelope, and protect/bind all required raw evidence and profile bytes. Embedding raw bytes in the envelope is one way to make that binding complete; independent blobs require exact references and graph retention. Update the private `_ResearchOperation._bind()` expectation from the v1 singleton only for explicitly acknowledged v2 receipts, using the exact evidence digest(s) already bound to that same live operation. Do not accept arbitrary additional references. Stable logical selection and receipt slots remain unchanged; existing v1 histories replay as v1. Store remains the authority owner. A v2 supplement must retain an independently qualified actual-return upper bound in `created_at_utc`; the event bound belongs inside evidence. These are contract/reader/private-binding changes, with no inherent SQLite schema migration.

## Synthesis decision

Pending parent synthesis. Reject this candidate as a production `TrustedUTCClock`. Its contribution is a distinct causal proof and a type boundary that prevents historical event evidence from being mislabeled current UTC. Only supplemental evidence is compatible with unchanged #75, and it leaves clock qualification unresolved.

## Tradeoffs accepted

- We accept dependence on an explicitly trusted remote source in exchange for an independently verifiable signed processing interval.
- We accept historical proofs arriving after the cutoff in exchange for removing local elapsed-time assumptions from the selection-event inequality alone.
- We accept a distinct evidence API and versioned receipt supplement in exchange for preserving the stronger clock guarantee and existing v1 history.
- We accept continued production refusal because no researched event witness proves UTC at return or opens prospective writer gates.

## Alternatives considered

A remote token wrapped as `TrustedUTCUpperBound` has a small interface but conceals a false contract. It is rejected. The caller cannot detect an unbounded pause after the signed event from token bytes.

A signed interval aged using qualified suspend-inclusive elapsed time hides transport and aging behind the existing clock API and serves every prospective caller. It is the better conditional production shape, but it needs documented device rate/error limits and a bound through actual function return. Candidate B removes those premises only for the historical commit inequality.

A remote service that performs selection and timing together would move the storage owner and deployment boundary. A remote timestamp response to local SQLite does not implement that design. It is much larger than this task and still requires precise semantics for any current-time guarantee exposed back to Termux.

## Open questions and risks

- Can a device/platform profile establish the unchanged actual-UTC-at-return guarantee, including the final sample-to-return scheduling gap and suspension, or must qualification conclude unavailable?
- Which authority has an accepted hard accuracy policy, operational failclosed controls, pinned trust and explicit certificate-time bootstrap adequate for historical witnesses?
- Would supplemental signed evidence justify a new receipt version once a valid current-UTC provider exists?

## Next implementation step

Create only a design/qualification prerequisite for a documented current-UTC return guarantee on the actual execution platform, with refusal as the valid outcome; no witness-to-clock adapter should be implemented.

For candidate B to become the primary completion mechanism, a separate explicitly authorized ticket would have to change the completion semantics and review every prospective writer gate. That permission is absent and the present user constraint forbids it. It is not the recommended next implementation ticket and cannot be smuggled into provider work.

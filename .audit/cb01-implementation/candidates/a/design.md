# Candidate A: one repository owns enrollment

## Problem

CB01 adds an independently timestamped, outcome-free snapshot to the existing immutable F06/F07/F10/F11/F13/F14/F16 chain. ArtifactStore publishes one protected object at a time. It has no complete-batch transaction. The frozen `cb01-v1` contract solves this with one full Preference Profile denominator, one fixture batch witness, and a receipt published after every final record. This candidate implements that contract behind one `BootstrapRepository`; callers never coordinate its preparation, transport, verification, or publication stages. F19 attachment remains a distinct domain operation because settlement happens later and can be corrected. The public API is exactly the five operations in the contract, with no CLI, generic Store change, or #70 methodology.

## Usage

The examples assume exact inspected identities already exist. Values named `anchor`, `lineage`, and `trust_policy_digest` are immutable domain inputs, not newly selected latest versions. Constructor defaults install the production Sigstore trust refresher and RFC3161 witness implementation. Test dependencies are keyword-only private adapters.

```python
from matchvet.cb01 import BootstrapRepository
from matchvet.store import default_database_path, open_store

# The constructor matches the existing open_store API.
with open_store(default_database_path(), software_commit=software_commit) as store:
    bootstrap = BootstrapRepository(store)
    result = bootstrap.enroll_fixture(anchor, lineage, trust_policy_digest)
    # Save these references even when publication failed or rows are incomplete.
    operator_log.save(result.batch_digest, result.attempt_digest,
                      result.publication_digest, result.failure_digest)
    for row in result.rows:
        operator_log.save_row(row.preference_id, row.disposition, row.reasons)
```

Reopen after interruption and explicitly name the original attempt. A retained token can finish publication after kickoff if its signed time was strictly inside the original window. The repository does not obtain a new token while performing this recovery.

```python
with open_store(default_database_path(), software_commit=software_commit) as store:
    bootstrap = BootstrapRepository(store)
    resumed = bootstrap.resume(saved_batch_digest, saved_attempt_digest)
    if resumed.publication_digest is not None:
        view = bootstrap.replay(resumed.publication_digest, ())
        assert all(row.eligibility.is_not_assessed for row in view.rows)

# An operator's separate retry action is explicit and names the failed attempt.
# At most one such retry is allowed; the unchanged batch receives a fresh nonce.
# bootstrap.resume(saved_batch_digest, saved_attempt_digest, retry_failed=True)
```

Later settlement and whole-freeze inspection select exact versions, including a successor that restores an unresolved state.

```python
with open_store(default_database_path(), software_commit=software_commit) as store:
    bootstrap = BootstrapRepository(store)
    attached = bootstrap.attach_outcome(
        enrolled_row_digest, exact_f19_digest,
        exact_fact_evidence=(), predecessor_digest=None,
    )
    corrected = bootstrap.attach_outcome(
        enrolled_row_digest, corrected_f19_digest,
        exact_fact_evidence=supplemental_t10_snapshot_digests,
        predecessor_digest=attached.digest,
    )
    view = bootstrap.replay(exact_receipt_digest, (corrected.digest,))
    denominator = bootstrap.inspect_denominator(
        exact_freeze_digest, exact_profile_digest, exact_receipt_digests,
    )
    # Includes every INCLUDED fixture x every enabled preference, even unattempted.
    operator_log.save_denominator(denominator)
```

`exact_fact_evidence=None` disables distribution-fact attachment. An explicit tuple, including an empty tuple, requests an OutcomeFactAttachment using F19's retained snapshots plus those supplemental exact snapshots. This distinguishes requesting diagnostic resolution from merely attaching a grade without adding a sixth operation.

## Shape

### Domain data first

Public input identities use immutable dataclasses. A present reference and an unavailable reference are distinct variants. Their private serializer produces the contract's exact `Reference` keys; unavailable values always produce explicit nulls and reasons. Caller identity spelling survives unchanged. `Digest` means a validated lowercase bare SHA-256 digest and does not represent prefixed F06/F07 IDs.

```python
@dataclass(frozen=True)
class PresentReference:
    id: str | None
    version: str | None
    digest: Digest

@dataclass(frozen=True)
class UnavailableReference:
    state: Literal["ABSENT", "UNKNOWN", "UNPERFORMED"]
    reasons: tuple[str, ...]

Reference = PresentReference | UnavailableReference

@dataclass(frozen=True)
class DenominatorAnchor:
    freeze: PresentReference
    membership: PresentReference
    fixture_revision: PresentReference
    cutoff: PresentReference
    profile: PresentReference
    # Fixture identities and exact boundaries are derived from upstream replay.
    # The private Anchor artifact includes all frozen contract fields.

@dataclass(frozen=True)
class ExactLineage:
    f06: Reference
    f07: Reference
    f10_catalog: Reference
    f10_requirements: Reference
    f11_evidence: Reference
    f13_input: Reference
    f13_result: Reference
    f13_history: Reference
    f14_profile: Reference
    f14_decision: Reference
    f14_policy: Reference
    f16_manifest: Reference
    f16_match_result: Reference

@dataclass(frozen=True)
class RowResult:
    preference_id: str
    disposition: str
    reasons: tuple[str, ...]
    pre_enrollment_digest: Digest | None
    enrollment_digest: Digest | None

@dataclass(frozen=True)
class BatchResult:
    batch_digest: Digest | None
    attempt_digest: Digest | None
    publication_digest: Digest | None
    failure_digest: Digest | None
    rows: tuple[RowResult, ...]

@dataclass(frozen=True)
class OutcomeAttachment:
    digest: Digest
    enrollment_digest: Digest
    settlement_digest: Digest
    state: SettlementState
    result: SettlementResult | None
    predecessor_digest: Digest | None
    correction_sequence: int
    fact_attachment_digest: Digest | None
```

`CaseView` contains exact publication identity, fixture grouping, a sorted tuple of rows, the selected attachment per row, exact forecast/support states, and nine permanently NOT_ASSESSED eligibility dimensions. `DenominatorView` contains sorted fixture/preference rows and a separate tuple of F06 excluded memberships with their own reasons. Neither view supplies cohort roles, confidence criteria, estimators, or promotion decisions.

Private immutable `PreparedBatch` stores exact canonical PreEnrollment bytes, ordered entry references, batch bytes and digest, validated source identities, and exact cutoff/kickoff instants. `AttemptArtifacts` stores exact request and attempt references, optional result/response/verification references, and a retained trust snapshot. A `VerifiedWitness` can only be constructed by verification after all thirteen checks pass. It contains every digest needed to create identical final records. Publication accepts this type; ordinary preparation cannot publish live records. Per boundary-discipline and encode-lessons-in-structure, protocol bytes are parsed at entry and only validated domain values cross internal boundaries.

```python
class BootstrapRepository:
    def __init__(self, store: Store, *,
                 _trust: _TrustBoundary | None = None,
                 _timestamp: _TimestampBoundary | None = None) -> None:
        raise NotImplementedError

    def enroll_fixture(self, exact_denominator_anchor: DenominatorAnchor,
                       exact_lineage: ExactLineage,
                       trust_policy_digest: str) -> BatchResult:
        """Prepare the entire denominator and complete one bounded witness attempt.

        Replaying identical successful inputs performs no network operation.
        Existing incomplete attempts require explicit exact-attempt resume.
        An unresolved anchor returns denominator rows with reasons and no batch.
        """
        raise NotImplementedError

    def resume(self, batch_digest: str, exact_attempt_digest: str,
               retry_failed: bool = False) -> BatchResult:
        """Reverify retained artifacts; finish only the named attempt.

        retry_failed authorizes the sole remaining attempt over the same batch.
        It never changes the Profile, source lineage, or prepared bytes.
        """
        raise NotImplementedError

    def replay(self, publication_digest: str,
               exact_attachment_digests: tuple[str, ...]) -> CaseView:
        """Verify receipt completeness and the original retained trust snapshot.

        Reject conflicting receipt identity, foreign attachments, and multiple
        selected versions for one row. No latest-version selection or network.
        """
        raise NotImplementedError

    def inspect_denominator(self, freeze_digest: str, profile_digest: str,
                            exact_publication_digests: tuple[str, ...]
                            ) -> DenominatorView:
        """Derive fixture x preference rows first, then join exact receipts.

        Match cataloged failure attempts to their exact anchors. Keep alternative
        forecasts grouped by fixture. Absence yields NOT_ATTEMPTED, never omission.
        """
        raise NotImplementedError

    def attach_outcome(self, enrollment_digest: str, settlement_digest: str,
                       exact_fact_evidence: tuple[str, ...] | None,
                       predecessor_digest: str | None) -> OutcomeAttachment:
        """Append a full replacement attachment after exact F19 replay.

        One predecessor has at most one distinct successor. Identical retries
        return its existing digest. A new unresolved version stays unresolved.
        """
        raise NotImplementedError
```

### Module map

| Module | Knowledge owned | Private signatures |
| --- | --- | --- |
| `cb01.py` | Public repository, complete batch visibility, exact attempt selection, append-only outcome successor identity, catalog scans | `_prepare(anchor, lineage) -> PreparedBatch`; `_finish(prepared, attempt) -> BatchResult`; `_publish(prepared, verified) -> BatchResult`; `_catalog_index() -> CatalogIndex` |
| `_cb01_schema.py` | All frozen v1 key sets and media types, canonical parsing, identity validation, exact UTC instant comparison | `decode(bytes, expected_kind) -> ValidatedEnvelope`; `encode(kind, body) -> bytes`; `utc_instant(text) -> ExactInstant`; `reference_payload(reference) -> ReferencePayload` |
| `_cb01_sources.py` | Upstream namespace spelling, replay bindings, F13 byte-preserving retention, support extraction, immutable full Profile denominator | `replay_sources(store, anchor, lineage) -> SourceSnapshot`; `pre_enrollments(snapshot) -> tuple[PreparedRow, ...]`; `denominator(store, freeze, profile) -> FrozenDenominator` |
| `_cb01_trust.py` | Sigstore bootstrap and current TUF authentication, exact pins/policy, protected raw metadata/certificate retention, offline authentication | `refresh(store, policy) -> RetainedTrust`; `replay(store, trust_state, policy, material) -> RetainedTrust` |
| `_cb01_rfc3161.py` | Nonce/request construction, bounded transport, DER interpretation and exact CMS/signer/EKU/ESS/policy verification | `request(batch_digest, nonce) -> bytes`; `send(request_bytes, limits) -> TransportResult`; `verify(request_bytes, response_bytes, trust, window) -> WitnessChecks` |
| `_cb01_outcomes.py` | Exact F19/T10 provenance, coherent fact sets, per-family count availability, attachment content | `attachment_body(enrollment, settlement, predecessor) -> OutcomeBody`; `resolve_facts(settlement, supplemental, anchor) -> ResolvedFacts` |

The reader traces each operation through `cb01.py` and at most one owning helper for a given decision. Helpers own knowledge, not temporal stages. `_prepare` and `_finish` stay private repository methods. The trust and timestamp boundaries are private injection seams for deterministic fixtures. They return domain results; public callers see no HTTP response, TUF updater, OpenSSL command, ASN.1 object, or intermediate workflow handle. This makes the repository deep without making a deep call chain.

### Persistence and recovery

The exact contract key sets are authoritative. Implement every required envelope, including TrustPolicy and TrustMaterial, without adding workflow stage fields or a competing F13 schema. Retained raw DER, certificate DER, TUF metadata, and TrustedRoot target are separate protected objects. The schema validator checks every nested exact key set, duplicate keys, finite numbers, sorted set fields, ordered chains, canonical byte equality, all version fields, null/state consistency, and bare versus namespaced identities. A schema's own digest is always external.

The repository builds a catalog index from `store.artifact_catalog()` grouped by media type and exact batch/attempt/predecessor identities. It reads and validates cataloged artifacts before trusting index entries. The index exists for one operation and never acts as a mutable latest pointer. Dominant lookups are batch-to-attempts, attempt-to-result/verification, successful-batch-to-receipt, and predecessor-to-successor. Maps are built once at the read boundary rather than searching disk or interpreting orphan files as enrollment state.

One writable Store already excludes another writer. The facade stays synchronous, serializes operations on that owner, and permits only one HTTP request at a time. It adds no lock or transaction layer. Nonce and exact DER request are protected before send. Attempt number and predecessor are retained before send. There are at most two attempts for the exact fixture batch, with no automatic resend. If a crash occurs between request retention and network completion, reopening cannot infer that the request was never sent. It records an unavailable/lost-response failure and requires explicit retry to send a different nonce.

A crash after response retention but before TimestampAttemptResult publication can recover only when the response can be uniquely authenticated against the exact saved request nonce and imprint. If cataloged responses give ambiguous conflicting evidence, fail closed. A file orphan is not a candidate. Catalog reconciliation must happen through the existing protected ArtifactStore APIs before recovery uses the bytes. A missing response never establishes a witness.

`_finish` validates the original batch, each PreEnrollment, every available upstream reference, raw request/response, policy, material, and retained authenticated TUF state. It reproduces the deterministic verification and final record bytes. It publishes missing final records idempotently, verifies the exact expected preference set, then publishes the receipt. Readers accept records only through that complete receipt. An in-window retained token can finish after kickoff; a new token outside the window cannot. Changed lineage creates a distinct case and cannot reuse an earlier token, per make-operations-idempotent and single-source-of-truth.

Only signed genTime establishes ordering. Use an exact UTC representation that separates integer seconds from the fractional decimal digits; do not pass chronology through floating point or datetime microsecond truncation. Offset normalization preserves the fractional value. Reject DATE precision for boundaries. Enforce strict cutoff < genTime < kickoff even at sub-microsecond precision. Accuracy is retained as protocol metadata and does not change these comparisons.

Fresh TUF authentication precedes each new attempt. Preserve the bootstrap v10 bytes, every authenticated root rotation, current root/timestamp/snapshot/targets, target bytes, and two pinned certificate DER objects. Compare current TSA entry and pins against the immutable selected policy. Offline replay authenticates the original retained state; it does not refresh or claim knowledge of later compromise declarations. Intermediate roots can be retained as protected metadata and reconstructed by version/signature from the catalog without expanding frozen envelope keys. Conflicting same-version metadata candidates require rejection or a uniquely authenticated chain.

### Source and outcome invariants

F06/Profile denominator replay is independent of F16 availability. Missing F16 manifests or any mandatory optional-stage input retain explicit unavailable References and complete per-preference rows. They never manufacture a partial manifest. A failed anchor can still appear in whole-freeze inspection; it cannot produce PreEnrollment or a witness batch. Successful witness verification leaves originally INCOMPLETE and EXCLUDED rows in those states.

F11, F13, F14, and F16 are called through replay paths only. Exact F13 retained payloads must agree with protected existing bytes, including all four distributions, fit/configuration, uncertainty, calibration and availability. CB01 adds no model execution or numerical rounding. The PreEnrollment schema excludes all outcomes and F19 identities by construction. Later attachments cannot change any original support or eligibility state.

Fact resolution operates on the exact retained T10 evidence snapshots, never a settlement label. It follows T10 authority, supersession, phase/status and coherent-record-set rules. FT, half-goal and corner sets resolve separately; second-half counts derive only from coherent valid FT/HT pairs under T12 consistency rules. Pending/conflicting/void/incomplete evidence keeps affected families unavailable. Retain complete source snapshots and explicit per-count provenance. Do not use a conveniently resolved preference grade to hide unresolved facts in another family.

## Synthesis decision

Candidate A recommends itself as the base because the frozen five-operation interface hides complete denominator construction, witness policy, durability and recovery. The orchestrator fills the final synthesis decision after comparing independently produced candidates.

## Tradeoffs accepted

- We accept a substantial repository implementation in exchange for callers needing no knowledge of witness stages or publication ordering.
- We accept catalog scanning before operation-local indexing in exchange for no Store migration, mutable CB01 pointer, or new transaction machinery.
- We accept private typed artifact bodies plus one strict wire codec in exchange for public caller types that cannot inject DER or bypass verification.
- We accept a private subprocess or maintained-library adapter for audited crypto/TUF operations in exchange for avoiding a hand-written CMS or TUF signature verifier. The concrete adapter must preserve exact bytes and expose deterministic retained fixtures.
- We accept an unavailable failure when a response was lost in exchange for never silently resending a request that might already have been accepted.

## Alternatives considered

- Public `prepare`, `witness`, and `finalize` operations expose durable stage handles and require the operator to coordinate policy refresh, attempt budget and receipt publication. They make interruption inspection obvious but spread CB01 invariants into callers. Retain those stages privately instead. This candidate is structurally different from a staged workflow design because the durable artifacts form evidence owned by one repository, not a public command/state machine.
- A generic durable workflow engine would hide transaction/retry mechanics but add workflow IDs, mutable progress and framework behavior beyond these fixed evidence artifacts. Its interface would expose lifecycle choices and need generic Store changes without improving the frozen receipt-based acceptance contract.
- One public repository per artifact kind would make each module simple but force callers to understand the entire digest dependency graph and cross-artifact invariants. Knowledge would leak through fourteen constructors and publication calls. Private schema ownership keeps that graph in one place.

## Open questions and risks

- Which maintained TUF client and CMS/DER adapter work with the actual Python 3.14 Termux installation while retaining all authenticated metadata and exact verification arguments? The earlier spike used npm's embedded tuf-js and OpenSSL; production must not depend on an incidental npm internal path.
- How should the immutable TrustPolicy's snapshot-oriented `metadata_digests` fields be interpreted when fresh authenticated metadata versions advance without any changed TSA entry or pins? The attempt's TrustStateIdentity must retain the actual refreshed state without rewriting a selected policy or relaxing the frozen key set.
- Can original TUF authentication be replayed using the recorded metadata issuance context without treating current phone time as witness chronology? Offline replay needs original authenticated-state validation and must distinguish historical validity from present revocation knowledge.
- Does T10 offer a sufficiently narrow stable count-fact resolver, or must `_cb01_outcomes.py` adapt its existing pure authority/coherence helpers? A second implementation of source conflict policy can drift. Any adapter must preserve every family's unavailable state rather than trusting a grade.
- Will catalog scanning remain acceptable at the expected private-store size? Build one validated index per operation first. Add a narrowly scoped persisted index only if measured use proves necessary, outside this implementation's no-migration scope.

## Next implementation step

Build the strict frozen v1 codec and the private source-replay adapter, then exercise `enroll_fixture` through a real reopened ArtifactStore with a complete Profile and missing F16 lineage before adding the witness transport.

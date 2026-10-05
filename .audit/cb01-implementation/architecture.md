# CB01 implementation design and trace

## Problem

CB01 must commit the full F06 INCLUDED fixture by frozen Preference Profile denominator, bind exact F06/F07/F10/F11/F13/F14/F16 inputs, and prove signed RFC3161 time before kickoff. The current ArtifactStore publishes one protected object at a time. It has no batch transaction, and its local creation time is metadata. The last complete publication receipt therefore controls visibility. This design keeps those rules behind the frozen `BootstrapRepository` API and leaves #70, F17, F18, F20, F21, the generic Store, and the production CLI alone.

## Usage

Callers pass exact upstream identities already retained in the store. The repository replays those identities, derives every preference from the exact Profile, and runs one bounded witness attempt for that fixture.

```python
with open_store(database_path, private_root=private_root) as store:
    bootstrap = BootstrapRepository(store)
    request = FixtureEnrollmentInput(
        freeze_id, membership_id, cutoff_id, profile_digest, f16_manifest_digest
    )
    result = bootstrap.enroll_fixture(request)

with open_store(database_path, private_root=private_root) as store:
    bootstrap = BootstrapRepository(store)
    resumed = bootstrap.resume(result.batch_digest, result.attempt_digest)
```

Outcome work happens later, against one exact F19 version and optionally its exact fact evidence. A correction names its exact predecessor. Reads name the receipt and attachment digests to replay.

## Shape

`BootstrapRepository` owns the public lifecycle, exact source joins, denominator, retry budget, catalog conflict checks, and receipt-last publication. Its five operations are `enroll_fixture`, `resume`, `replay`, `inspect_denominator`, and `attach_outcome`. Public inputs are exact references and domain values. No caller sees CMS bytes as parsed objects, shell arguments, HTTP response objects, or intermediate stage handles.

The implemented modules group the knowledge each operation depends on:

- `cb01.py` coordinates the five operations, performs protected-catalog conflict checks, publishes complete receipts last, and binds F19/T10 outcome attachments to enrolled records.
- `cb01_schema.py` encodes and validates the exact v1 envelopes, nested key sets, digests, namespaces, duplicate keys, finite numbers, canonical bytes, and precision-preserving UTC instants.
- `cb01_sources.py` replays F06 through F16 without acquisition or model execution, derives the full F06/Profile denominator before checking optional lineage, and preserves original F13 family payload bytes.
- `cb01_trust.py` bootstraps and refreshes Sigstore TUF, retains exact metadata and TrustedRoot bytes, creates the DER request, sends one bounded RFC3161 request, and verifies the retained token with OpenSSL.

## Implementation trace

The implementation keeps `BootstrapRepository` as the only public lifecycle owner. The actual module split is `cb01.py` for enrollment, recovery, publication, replay, and outcome attachment; `cb01_schema.py` for exact v1 envelopes and canonical bytes; `cb01_sources.py` for read-only upstream replay; and `cb01_trust.py` for Sigstore TUF, RFC3161, and CMS verification. Outcome handling remains in `cb01.py` because it must bind the enrollment receipt, exact F19 correction chain, and T10 fact evidence together. No `cb01_witness.py` or `cb01_outcomes.py` module was created.

The actual public input is `FixtureEnrollmentInput(freeze_id, membership_id, cutoff_id, profile_digest, f16_manifest_digest=None)`. The repository accepts a `Store` and optional `WitnessBackend`; `enroll_fixture(request, trust_policy_digest=None)` prepares the exact denominator. `resume(batch_digest, exact_attempt_digest, retry_failed=False)` names the retained attempt. `replay(publication_digest, exact_attachment_digests=())` and `inspect_denominator(freeze_digest, profile_digest, publication_digests)` use exact identities. `attach_outcome(enrollment_digest, settlement_digest, exact_fact_evidence=None, predecessor_digest=None)` returns the exact outcome and fact attachment digests.

The private `PreparedCase`, `RetainedAttempt`, `ReceivedAttempt`, `VerifiedCase`, and `PublishedCase` types below were architectural state sketches, not implemented Python types. Runtime transitions are guarded in the repository methods and their private helpers. The concrete result types are `BatchResult`, `EnrollmentRow`, `DenominatorView`, and `CaseView` in `cb01.py`.

The private state types record how much evidence exists. Only a `VerifiedCase` can reach finalization.

```python
@dataclass(frozen=True)
class PreparedCase:
    batch_digest: str
    anchor: Anchor
    lineage: Lineage
    entries: tuple[BatchEntry, ...]

@dataclass(frozen=True)
class RetainedAttempt:
    batch_digest: str
    attempt_digest: str
    request_digest: str
    trust_policy_digest: str
    attempt_number: int
    predecessor_attempt_digest: str | None

@dataclass(frozen=True)
class ReceivedAttempt:
    attempt: RetainedAttempt
    result_digest: str
    response_digest: str

@dataclass(frozen=True)
class VerifiedCase:
    received: ReceivedAttempt
    verification_digest: str
    trust_material_digest: str
    signed_gen_time: ExactUtcInstant

@dataclass(frozen=True)
class PublishedCase:
    verified: VerifiedCase
    publication_digest: str
    enrollment_digests: tuple[str, ...]

@dataclass(frozen=True)
class BatchResult:
    batch_digest: str | None
    attempt_digest: str | None
    publication_digest: str | None
    failure_digests: tuple[str, ...]
    rows: tuple[EnrollmentRow, ...]

class BootstrapRepository:
    def __init__(self, store: Store) -> None: ...
    def enroll_fixture(self, anchor: AnchorInput, lineage: LineageInput,
                       trust_policy_digest: str) -> BatchResult: ...
    def resume(self, batch_digest: str, exact_attempt_digest: str,
               *, retry_failed: bool = False) -> BatchResult: ...
    def replay(self, publication_digest: str,
               exact_attachment_digests: tuple[str, ...]) -> CaseView: ...
    def inspect_denominator(self, freeze_digest: str, profile_digest: str,
                            exact_publication_digests: tuple[str, ...]
                            ) -> DenominatorView: ...
    def attach_outcome(self, enrollment_digest: str, settlement_digest: str,
                       exact_fact_evidence: tuple[str, ...] | None,
                       predecessor_digest: str | None) -> OutcomeAttachment: ...
```

`FixtureEnrollmentInput` contains the exact F06 freeze, membership, F07 cutoff, F14 Profile digest, and optional F16 manifest digest. The artifact codec writes complete anchor and lineage shapes, including explicit unavailable states. The Profile, not caller predictions or a primary recommendation, supplies the expected preference IDs. All arrays defined as sets are sorted and unique. The forecast family array uses the existing F13 family order and embeds its exact protected payload without reconstructing or rounding distributions.

A public repository call traces through the coordinator and one owning helper. Helpers do not expose each step as a second public workflow. This keeps the call chain short while keeping timestamp, source replay, and outcome rules out of a single oversized file.

## Recovery and trust

`enroll_fixture` first returns an existing exact successful receipt without network use. Otherwise it prepares one deterministic batch. A fresh authenticated TUF refresh must complete before the repository sends a new RFC3161 request. The exact query, fresh positive nonce, attempt, and selected policy reference are cataloged before POST. A failed TUF refresh, unavailable service, rejected status, malformed response, or verification failure is retained as a failure with every expected preference still present.

`resume` reloads and validates the exact batch and attempt from protected catalog objects. With `retry_failed=False`, it reuses the exact request and any retained response for offline verification and publication. It never makes another network request. With `retry_failed=True`, it may create one new request with a fresh nonce for the unchanged batch, after another authenticated TUF refresh. Two total attempts is the hard cap. Ambiguous same-identity artifacts fail closed.

A retained valid witness may finish publication after kickoff because only signed `genTime` proves chronology. A new witness whose signed time is not strictly after F07 cutoff and before kickoff cannot create live records. Exact fractional digits are retained through UTC normalization and comparison. Local clock and ArtifactStore timestamps never establish this ordering.

Finalization revalidates source artifacts and trust bytes, writes each deterministic `EnrollmentRecord`, and publishes `FixtureEnrollmentPublication` last. A reader recognizes no live row unless the exact receipt names every expected preference and record. No new transaction or mutable latest pointer is added to Store.

Sigstore trust follows the frozen policy: pinned version 10 bootstrap root, every sequential authenticated root update, current timestamp/snapshot/targets metadata, and TUF-verified `trusted_root.json` bytes. TUF signatures and RFC3161 CMS checks use the existing OpenSSL command and Python standard library. curl/OpenSSL calls have the contract's size and timeout limits. The implementation adds no Python crypto/TUF dependency. It retains all exact verified metadata, root-rotation bytes, TrustedRoot bytes, and the identity needed to replay each attempt. No fallback TSA or CRL/OCSP claim is allowed.

F19 attachment replays the exact settlement and exact F16/F14 identities. PENDING and CONFLICTING remain unresolved. WIN, LOSS, PUSH, and VOID remain distinct. Successor attachments append and require a predecessor. Fact resolution consumes exact T10 snapshots, never a grade label; each FT, HT, and corner fact keeps its source provenance or an explicit missing/conflict state. Eligibility fields stay `NOT_ASSESSED`.

## Synthesis decision

Candidate A is the base. It has the clearest ownership map for complete denominator construction, exact attempt selection, protected-catalog conflict checks, and receipt visibility. The independent cross-judge scored it higher on recovery and call-chain clarity. Candidate B's immutable stage values informed the recovery checklist but were not retained as separate runtime types. No prepare/witness/finalize operation is exposed to callers.

Candidate A's maintained-library suggestion is rejected for this repository: the available Python environment has no TUF or cryptography package, and the frozen Termux contract calls for standard-library, OpenSSL, and curl work where sufficient. OpenSSL must be exercised against the retained live Sigstore probe and deterministic test fixtures before this choice is considered verified.

The one-store-object-per-call limitation is accepted. Catalog scans and validated indexes are rebuilt for each operation rather than adding Store tables, custom transactions, or latest pointers. An uncertain send consumes an attempt; only explicit retry may send again.

## Alternatives considered

- Public prepare, witness, and finalize calls make interruption stages visible but move request limits and publication order into callers. They fail the frozen repository seam.
- A generic workflow table could make lookups faster but adds a second mutable record of publication state and a migration. The receipt already gives the required complete-batch boundary.
- Each artifact type owning its own repository would make individual methods small but expose the digest dependency graph and let callers publish partial batches. Those modules remain private helpers.

## Risks to prove

- The OpenSSL CLI must preserve exact RFC3161 status, imprint, nonce, policy, signer, ESS binding, critical EKU, and chain behavior while reporting no certificate dump to the caller.
- The TUF verifier must accept the pinned bootstrap and real sequential Sigstore root chain, then reject bad signatures, stale or wrong targets, and conflicting same-version state.
- ArtifactStore publication must leave partial records invisible until the exact complete receipt exists, and a reopened store must finish from the same retained in-window response after kickoff.
- T10 fact resolution must preserve source conflict and phase rules for all six counts without inferring facts from an F19 grade.

## Verification status

Implementation is complete in the public repository seam. The source-stable CB01 suite passed 31 tests, the affected F13/F14/F16/F19 suites passed 28 tests, and the independent outcome-seam test passed. The earlier run that overlapped a source edit is retained in the decision log but is not acceptance evidence.

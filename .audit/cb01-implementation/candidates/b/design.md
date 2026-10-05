# Candidate B: immutable prepared cases

## Problem

CB01 must preserve one complete Preference Profile denominator through incomplete upstream lineage, a remote timestamp attempt, interrupted artifact publication, and later settlement corrections. ArtifactStore commits one protected object at a time. Its catalog has no transaction spanning the whole batch. The frozen `cb01-v1` contract makes a verified publication receipt the visibility boundary and requires recovery to select exact attempts. This design represents each durable checkpoint as an immutable value. Separate replay and finalization policies decide what those retained values permit.

Grounding comes from `docs/design/cb01-enrollment-contract.md`, `.audit/cb01-implementation/grounding.md`, `CONTEXT.md`, and the existing `ArtifactStore`, `open_store`, F16, and F19 signatures. This candidate changes no frozen schema and proposes no production CLI, database migration, Store change, or #70 methodology.

## Usage

The following examples describe the proposed API. `open_store(database_path, private_root=...)` is the existing constructor. `BootstrapRepository(store)` follows the existing F16 and F19 constructor convention. `exact_anchor`, `exact_lineage`, and the saved digests come from the operator's retained upstream identities. The implementation guide must replace those inputs with an actual fixture's complete construction example.

An operator enrolls every enabled preference for one exact INCLUDED fixture with one call. The repository derives the preferences from the retained Profile.

```python
from matchvet.cb01 import BootstrapRepository
from matchvet.store import open_store

with open_store(database_path, private_root=private_root) as store:
	repository = BootstrapRepository(store)
	result = repository.enroll_fixture(exact_anchor, exact_lineage, trust_policy_digest)
	save_enrollment_result(result)  # application-owned retention of returned identities
```

The returned result has exact batch, attempt, publication, and failure identities where each exists. It always exposes all expected preference rows. A failed witness is a retained domain result. Invalid caller identities and corrupt protected bytes raise a domain integrity error. Neither path sends a second request automatically.

After a restart, the operator names the retained batch and attempt. A retained response permits offline verification and finalization, including after kickoff. A lost response returns a retained failure. The second call below is a separate, explicit operator decision for a failed attempt.

```python
with open_store(database_path, private_root=private_root) as store:
	repository = BootstrapRepository(store)
	result = repository.resume(saved_batch_digest, saved_attempt_digest)
	# Only when the operator explicitly requests the one permitted retry:
	retried = repository.resume(saved_batch_digest, saved_attempt_digest, retry_failed=True)
```

Later analysis names the exact receipt and attachment version it wants. Outcome correction cannot change the witnessed prediction or eligibility.

```python
with open_store(database_path, private_root=private_root) as store:
	repository = BootstrapRepository(store)
	attachment = repository.attach_outcome(
		enrollment_digest, settlement_digest, exact_fact_evidence, predecessor_digest
	)
	case = repository.replay(publication_digest, (attachment.digest,))
	denominator = repository.inspect_denominator(
		freeze_digest, profile_digest, exact_publication_digests
	)
```

## Shape

### Domain data and public signatures

Public inputs are frozen domain values and exact identity strings. They contain no DER, HTTP client, subprocess, command arguments, JSON dictionaries, or ASN.1 types. Upstream prefixed identities remain unchanged. `Digest` validates lowercase bare 64-hex only for new CB01 identities. `ExactDenominatorAnchor` and `ExactLineage` expose the contract's Anchor and Lineage meanings as typed domain fields. They are distinct from the private canonical storage representation.

The type sketch deliberately leaves implementation bodies unfinished. Names used for views below describe immutable domain records, not serialized envelopes.

```python
@dataclass(frozen=True)
class PresentReference:
	id: str | None
	version: str | None
	digest: Digest
	reasons: tuple[str, ...]
	# Factory checks the upstream contract's required ID, version, and namespace.

@dataclass(frozen=True)
class UnavailableReference:
	state: Literal["ABSENT", "UNKNOWN", "UNPERFORMED"]
	reasons: tuple[str, ...]
	# Encoding supplies null for id/version/digest. Reasons must be nonempty.

Reference = PresentReference | UnavailableReference

@dataclass(frozen=True)
class ExactDenominatorAnchor:
	freeze: PresentReference
	membership: PresentReference
	fixture_revision: PresentReference
	cutoff: PresentReference
	profile: PresentReference
	fixture_id: str
	home_team_id: str
	away_team_id: str
	competition_id: str
	season_id: str
	matchweek_id: str
	kickoff_utc: ExactUtcInstant
	cutoff_utc: ExactUtcInstant

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
class BatchResult:
	batch_digest: Digest | None
	attempt_digest: Digest | None
	publication_digest: Digest | None
	failure_digests: tuple[Digest, ...]
	rows: tuple[PreferenceEnrollmentView, ...]
	reasons: tuple[str, ...]

class BootstrapRepository:
	def __init__(self, store: Store) -> None:
		raise NotImplementedError
	def enroll_fixture(self, exact_denominator_anchor: ExactDenominatorAnchor,
			exact_lineage: ExactLineage, trust_policy_digest: Digest) -> BatchResult:
		raise NotImplementedError
	def resume(self, batch_digest: Digest, exact_attempt_digest: Digest,
			*, retry_failed: bool = False) -> BatchResult:
		raise NotImplementedError
	def replay(self, publication_digest: Digest,
			exact_attachment_digests: tuple[Digest, ...]) -> CaseView:
		raise NotImplementedError
	def inspect_denominator(self, freeze_digest: str, profile_digest: str,
			exact_publication_digests: tuple[Digest, ...]) -> DenominatorView:
		raise NotImplementedError
	def attach_outcome(self, enrollment_digest: Digest, settlement_digest: str,
			exact_fact_evidence: ExactFactEvidence | None,
			predecessor_digest: Digest | None) -> OutcomeAttachment:
		raise NotImplementedError
```

`ExactFactEvidence` selects exact retained T10 evidence snapshots plus the frozen fact-resolution rule. It does not accept derived counts supplied by the operator. `None` requests the grade attachment without distribution evaluation. Views preserve unresolved and excluded states, failure reasons, fixture grouping, support states, and all NOT_ASSESSED eligibility dimensions.

`ExactUtcInstant` stores an integer epoch second and an exact decimal fraction with canonical UTC text. Comparison pads decimal fractions to equal precision, without conversion to floats or truncation to Python datetime microseconds. Offset normalization preserves precision. DATE precision cannot instantiate a kickoff boundary.

### Immutable checkpoints

Prepared cases, attempts, and publications are private frozen records. They are reconstructed from protected catalog artifacts on every entry to a public operation. They never act as proof merely because an object was instantiated in memory.

```python
@dataclass(frozen=True)
class PreparedCase:
	batch_digest: Digest
	anchor: ExactDenominatorAnchor
	lineage: ExactLineage
	rows: tuple[PreparedPreference, ...]  # exact Profile order by preference ID
	# Batch and every PreEnrollment have been validated and cataloged.

@dataclass(frozen=True)
class RetainedAttempt:
	prepared: PreparedCase
	attempt_digest: Digest
	request_digest: Digest
	trust_policy_digest: Digest
	attempt_number: int
	predecessor_attempt_digest: Digest | None
	# Exact query and nonce exist before any network call.

@dataclass(frozen=True)
class ReceivedAttempt:
	attempt: RetainedAttempt
	attempt_result_digest: Digest
	response_digest: Digest

@dataclass(frozen=True)
class VerifiedCase:
	received: ReceivedAttempt
	verification_digest: Digest
	trust_material_digest: Digest
	# All 13 required VerificationChecks passed for these exact references.

@dataclass(frozen=True)
class PublishedCase:
	verified: VerifiedCase
	publication_digest: Digest
	records: tuple[PublishedPreference, ...]
```

These records encode increasing evidence, per `encode-lessons-in-structure`. They contain artifact identities, not mutable stage flags. Failure stays a separate immutable `TimestampFailure` reference, so a failed attempt cannot become a verified attempt by changing a field. `TimestampVerification` retains FAILED checks when verification produced a failed result.

This is staging inside one owner, not a prepare/witness/finalize API imposed on the operator. The public methods retain the contract's depth. Callers choose identity and an explicit retry. The repository owns ordering, validation, and publication, per `boundary-discipline`.

### Replay and finalization policies

Replay is a pure decision over retained evidence. It never contacts TUF or the TSA, adopts a newer Profile, or chooses a latest outcome. It validates original TUF signatures and the issuance snapshot's applicability at the signed token time. Metadata expiration today does not silently reinterpret a historical issuance decision. Any reassessment under current trust state is a distinct future artifact.

Finalization accepts only `VerifiedCase`, revalidates its exact sources, and creates deterministic EnrollmentRecords plus the last publication receipt. Its eligibility test is the retained token's signed `cutoff < genTime < kickoff`. It has no wall-clock publication deadline. Thus the same finalizer handles an immediate success and a restart after kickoff, per `make-operations-idempotent`.

```python
def replay_prepared_case(artifacts: ArtifactStore, sources: SourceBindings,
		batch_digest: Digest) -> PreparedCase:
	raise NotImplementedError

def assess_retained_attempt(prepared: PreparedCase,
		retained: AttemptArtifacts, verifier: WitnessVerifier) -> AttemptAssessment:
	# Pure replay policy after protected reads. Returns failed or verified evidence.
	raise NotImplementedError

def choose_resume_action(prepared: PreparedCase, attempts: AttemptHistory,
		selected_attempt: Digest, retry_failed: bool) -> ResumeAction:
	# Return existing publication, verify retained response, fail lost response,
	# or authorize one fresh attempt. Never resubmit an existing request.
	raise NotImplementedError

def finalize_verified_case(artifacts: ArtifactStore,
		verified: VerifiedCase, sources: SourceBindings) -> PublishedCase:
	# Revalidate, reject conflicting siblings, publish missing exact records,
	# then publish the complete receipt. Never calls the network.
	raise NotImplementedError
```

The repository constructs these private services itself. A private test factory substitutes deterministic witness and trust boundaries without exposing wire types on the public constructor.

### Durable recovery

| Retained checkpoint | Resume behavior |
| --- | --- |
| Profile and F06 exist but anchor unresolved | Denominator still shows every pair. No fabricated cutoff or batch. |
| PreEnrollments and batch, no attempt | Enrollment may start the first request only after full replay and fresh authenticated trust selection. |
| Request and TimestampAttempt, no result | Treat as an uncertain send or lost response. Retain explicit failure. Do not resend this request. |
| Raw response and exact TimestampAttemptResult | Reverify the retained response offline. No network call. |
| VERIFIED TimestampVerification, some EnrollmentRecords | Reverify evidence, reuse identical records, create remaining records, publish receipt last. |
| Complete verified receipt | Return that exact publication without another timestamp request. |
| Failed attempt and explicit retry | Preserve failure, refresh authenticated trust, retain a new nonce and request, then send at most one second attempt. |
| Digest-valid uncataloged file | Reconcile through existing ArtifactStore publication only when exact retained identities prove the expected artifact. Never count it as live evidence alone. |

A crash after response-file persistence but before its result is cataloged does not justify searching arbitrary DER objects for a matching token. Only an exact reconciled artifact link can authorize verification. Otherwise the prior attempt remains uncertain. Conservative loss consumes the first attempt budget, which prevents hidden repeat submissions.

The existing Store writer lock serializes all local mutation and enforces one active request. No worker pool or second shared index is added. An in-memory index is rebuilt from protected CB01 catalog entries for the operation. It groups attempts by batch, receipts by batch and selected verification, and outcome successors by predecessor. Duplicate semantic identities with different bytes fail closed. The attempt chain contains at most two attempts, with one distinct successor per predecessor.

Identical input enrollments first derive their deterministic batch digest and inspect exact retained artifacts. A complete prior receipt wins. An uncertain attempt returns its failure and exact identity for resume. A changed lineage creates a distinct case and can never borrow an earlier witness.

### Schema and source ownership

The canonical codec implements the exact v1 envelope and body key sets in the contract for PreEnrollment, FixtureEnrollmentBatch, TimestampAttempt, TimestampAttemptResult, TimestampVerification, EnrollmentRecord, FixtureEnrollmentPublication, TimestampFailure, OutcomeAttachment, OutcomeFactAttachment, TrustPolicy, and TrustMaterial. It also owns each required nested key set. No stage marker, sent flag, own digest, or new checkpoint artifact enters those schemas.

Decode rejects duplicate keys, unknown fields, unsupported versions, noncanonical bytes, nonfinite numbers, unsorted set identities, duplicates, and malformed digests. Encoding preserves explicit nulls and reason-bearing unavailable states. Raw request and response artifacts retain exact DER. Their digests and certificate fingerprints hash exact bytes.

SourceBindings calls only exact upstream replay APIs. It derives the denominator from F06 and Profile before consulting F16. It preserves F06/F07 identifier spellings. It never invokes acquisition, F11 build, F13 model construction, F14 decision creation, or F16 processing. Existing replay-time verification remains the upstream repository's responsibility.

PreparedPreference binds every F13 family payload against the original protected family artifact. CB01 retains those original bytes and their exact numerical representations. It rejects an embedded projection that differs from those bytes. It never constructs forecasts from rounded probabilities. Missing F16 or F13 references remain unavailable, and incomplete rows remain in the batch. All support references retain PRESENT, ABSENT, UNKNOWN, or UNPERFORMED. All eligibility fields remain NOT_ASSESSED.

Sigstore trust is owned by one private witness module. It authenticates the root chain from pinned root-history version 10, timestamp, snapshot, targets, and trusted_root.json hash and length. It retains exact metadata and certificate DER under the selected immutable policy. It enforces the frozen endpoint, pins, SHA-256, token policy OID, exclusive critical timestamping EKU, certificate time at genTime, exact nonce, exact imprint, status 0, CMS signature, ESS signer identity, and every required verification check. A current TUF mismatch fails closed. There is no automatic retry, fallback TSA, CRL claim, or OCSP claim. Retained trust bytes support offline replay; fresh authenticated trust is required for a new attempt.

Outcome policy owns attachment identity, predecessor uniqueness, and T10 fact resolution. It requires exact F19 settlement identity and witnessed fixture, preference, F16, and F14 agreement. Every correction is a full replacement snapshot. Selecting PENDING or CONFLICTING after SETTLED makes that selected view unresolved again. WIN, LOSS, PUSH, and VOID stay distinct. Fact attachments retain six nullable counts and complete evidence provenance. Coherent T10 source sets and T12 HT <= FT rules determine each family independently. A settlement grade cannot supply missing counts or remove a fact conflict.

### Module map

| Proposed module | Knowledge owned |
| --- | --- |
| `src/matchvet/cb01.py` | Public domain API, immutable checkpoints, operation coordination, catalog-derived identity indexes, retry decisions, final receipt publication. |
| `src/matchvet/cb01_codec.py` | All exact canonical envelopes and nested schemas, identity validation, exact instant parsing, protected artifact decoding. |
| `src/matchvet/cb01_sources.py` | F06 through F16 replay binding, complete denominator, retained F13 projections, pre-enrollment support snapshots. |
| `src/matchvet/cb01_witness.py` | TUF trust authentication and retention, query creation, bounded transport, token verification, retained-attempt replay policy. |
| `src/matchvet/cb01_outcomes.py` | F19 binding, append-only correction policy, coherent T10 evidence selection, family outcome availability. |

The modules group domain knowledge rather than load/validate/save phases. A normal trace runs from the repository to one domain owner and its codec. Pure policies remain beside the decisions they protect. No pass-through repository adapter is required.

## Synthesis decision

Pending the parent architect's comparison. This candidate offers immutable prepared-case checkpoints and distinct replay/finalization rules while preserving the already accepted five-method repository API.

## Tradeoffs accepted

- We accept several private frozen value types in exchange for preventing an unverified attempt from reaching the finalizer.
- We accept reconstructing indexes from protected catalog entries in exchange for avoiding a migration or a second mutable source of truth.
- We accept losing a token without an exact retained response link in exchange for bounded requests and defensible recovery.
- We accept an internal network adapter and verifier boundary in exchange for exercising the public repository against deterministic retained responses.

## Alternatives considered

- A public PreparedCase object with witness and finalize methods would make recovery stages visible but require callers to coordinate repository invariants. The frozen contract already rejected that larger interface.
- A single mutable orchestration object with nullable request, response, and receipt fields would expose the same small public interface. It loses because impossible combinations become representable and replay/finalization rules tend to depend on incidental execution state.
- A new transaction log with a mutable batch-status table would make lookup cheaper. It adds storage coordination and a second authority for publication, while the existing receipt already supplies the necessary visibility boundary.

## Open questions and risks

- Can the implementation authenticate a selected TrustPolicy whose exact metadata digests are refreshed before a new attempt without silently substituting a different policy identity? The contract requires an exact selected policy and binds current metadata in that policy. Stale policy selection must fail closed or be resolved explicitly before enrollment.
- Can the chosen RFC3161 decoder preserve all allowed genTime precision and accuracy fields without truncating through datetime? This must be established against retained fixtures before relying on comparison code.
- Which existing ArtifactStore catalog query provides protected entries for reconstruction without creating a new database API? The implementation must use the current Store facilities and reject uncataloged or conflicting artifacts.
- Can every F13 embedded family projection preserve lexical number representations in its canonical artifact while still using the existing family replay checks? If the existing decoded model normalizes numbers, preparation must read the protected bytes directly.

These are implementation risks. They do not reopen the frozen contract or require a new operator approval checkpoint.

## Next implementation step

Implement exact v1 codecs and PreparedCase reconstruction from retained F06/Profile/F07 identities and upstream replay, then exercise missing-F16 and complete-profile cases at the public repository boundary.

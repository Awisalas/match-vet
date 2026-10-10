# Private research source authorization

Issue #89 implements [ADR 0006](../adr/0006-research-only-public-source-automation-risk.md)
for private RESEARCH_ONLY #70 work. The production installation contains no source
authority. Causal owner activation remains a separate prerequisite.

## Immutable evidence

`research-source-use-manifest-v1` is canonical UTF-8 JSON, schema 1. The encoding
uses sorted keys, compact separators and unescaped Unicode. Duplicate keys,
nonfinite values, unsupported fields and conflicting dependencies refuse.
SHA-256 of the complete bytes identifies each protected artifact.

The exact top-level fields are `contract`, `schema_version`, `purpose`, `issue`,
`stage`, `selection_digest`, `projection`, `entries` and `policy_digest`.
Stages are `ACQUISITION`, `SELECTED_GRAPH` and `OUTCOME`.

The selected projection binds the original selection, aggregate graph identity,
completion receipt, F16, candidate, freeze, preference profile, decision and cutoff
policies, logical Matchweek and common T. The complete selection snapshot contains
the exact seven scopes and artifact references. Replay inspects the causal graph
and recomputes the projection from those references. It follows exact primary-key
references into retained source identities, captures, assertions, origins, fixture
revisions and mapping records. It includes the canonical selected rows and exact
raw artifacts. It never reads latest history or adds unrelated Store content.
Selected history, calibration, manual evidence, weather, locations and software
dependencies retain their original artifact identities and embedded facts.

Every projected dependency has one reviewed entry. Each entry contains its exact
dependency ID, provider, publisher, known or UNKNOWN upstream lineage, source and
access types, endpoint, raw and normalized identities, parser version, retrieval,
publication and observation times, competition, season, capability, requested
operations, separate external permission and operation classifications, exact
terms review, internal basis, retention restrictions, attribution and access limits.
Known capture endpoints, digests, times and collector versions must agree with
retained source rows. Unknown publication times stay UNKNOWN.

The policy artifact pins ADR 0006's exact digest and revision. Internal basis is
exactly `PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED`. External permission is independently
`UNKNOWN`, `REFUSED` or `GRANTED`; a grant needs exact protected external evidence.
Internal APPROVED never means publisher approval or rights clearance. Existing
registry PERMITTED labels remain historical policy classifications in retained rows.

Each review classifies automated access, raw retention, normalized retention,
private backup/restore/replay, derived statistical use, attribution and redistribution
separately. Requested redistribution refuses under this policy. New captures and
their eligibility records are PROTECTED, private and nonredistributable. Their
retention and termination constraints remain explicit. Technical limits bind the
planned request count, bytes, timeout and provider rate-limit review. Adapters must
enforce the endpoint and access plan, including no access-control bypass.

Acquisition manifests retain one exact prospective request and have no selection
or acquired dependency closure. They cannot claim identities for future bytes.
The bounded `SourceAuthorizationRepository.acquire` seam requires current authority
before its acquisition callback, after acquisition and at protected admission.
It retains raw and normalized bytes plus `research-source-internal-eligibility-v1`.
The eligibility record binds the exact source, scope, capability, manifest, V2
decision and resulting byte digests. `coverage_eligibility` rechecks those identities
and current authority before returning its digest as an F01 internal use-policy
reference. This supplies no coverage, freshness or completeness evidence. F05 and
F04 permission records retain their released meanings. No SQLite migration is needed.

OUTCOME projections bind the original selection, one exact F19 settlement, and
`fact_evidence_digests` for its complete evidence snapshot. Each evidence record
has a classified `outcome-evidence:<evidence_digest>` dependency with its exact
facts and digest. Applicable retained raw artifacts referenced by `source_digest`
have separate classified dependencies. Both bare and `sha256:` digests resolve
only to exact catalogued bytes. Missing raw bytes are not inferred.

V2 attachment compares the supplied fact-evidence set with that manifest before
authorization. Additions, removals, substitutions, and raw-source mismatches
refuse. Supplemental T10 evidence requires an exact authorization representation;
until supplied, V2 refuses supplements. Released CB01 and V1 readers retain their
original behavior. Replay compares the attached fact-evidence identities with the
authorized set and follows only pinned OUTCOME artifact identities. Retaining raw
bytes later cannot enlarge an old closure; current use requires a new review.

Outcomes have a separate dependency closure. They never change the pre-T selection
or its manifest. Each later correction needs its own review.

## Signed source authority and current continuity

The loader reads only `sys.base_prefix/etc/matchvet/source-authorizer-v1.json`.
There is no caller key, environment override or catalog-discovered approval.
The canonical installation contains exactly `verification_key`, `deployment`,
`catalog`, `history`, `records` and `checkpoint_socket`. The catalog is the resolved
Store path. Records and socket paths are absolute. The installation is owned by
the trusted OS user, is not a symlink and is not group or world writable.

Source records use a separate `matchvet-source-authority-v1` domain and Ed25519 key.
The envelope has exactly `signed` and `signature`. The signature is lowercase hex.
OpenSSL verifies the message consisting of the domain, one NUL byte and canonical
signed JSON. The owner identity is SHA-256 of Ed25519 SubjectPublicKeyInfo DER.
Causal envelopes cannot authorize sources.

Signed fields are exactly `domain`, `schema_version=1`, `algorithm=Ed25519`,
`action`, `owner`, `deployment`, `catalog`, `history`, `sequence`, `predecessor`,
`purpose=RESEARCH_ONLY`, `issue=70`, `manifest_digest`, `policy_digest`, `issued_at`,
`not_before`, `not_after`, `state`, `reason_codes`, `adverse` and
`replacement_manifest_digest`. Validity is inclusive at not_before and exclusive
at not_after. Publication times never decrease.

Numbered records start at `00000000000000000001.json`. Each record binds the exact
preceding envelope digest. `authorize` establishes APPROVED, REFUSED or UNKNOWN
for one exact manifest once. `withdraw` appends WITHDRAWN with reasons and adverse
effective, publication and observation times. UNKNOWN effective time stops present
use. `supersede` records SUPERSEDED and a different reviewed manifest identity.
The replacement needs its own authorization. `reconcile` preserves the existing
state and cannot restore withdrawn capability. A withdrawn classification can be
explicitly superseded by a different reviewed manifest; it cannot be reapproved.
Overlapping approvals and unresolved REFUSED, UNKNOWN or WITHDRAWN classifications
for the same graph, outcome or acquisition scope refuse until explicitly superseded.
Changed terms require a new manifest and current reviewed authorization.

Every current load sends a fresh 256-bit nonce and deployment, catalog and history
identities to the independent Unix checkpoint service. The bounded response is a
source-domain signed envelope. Its fields are exactly `domain`, `schema_version`,
`algorithm`, `action=checkpoint`, `owner`, `deployment`, `catalog`, `history`, `nonce`,
`sequence`, `head`, `continuity=RECONCILED` and `current_time`. The service attests
authoritative current UTC and the complete current history head. Missing, stale,
conflicting, rolled-back or uncertain responses refuse. No cached checkpoint grants
current authority.

The checkpoint's authoritative state and reconciliation evidence must live outside
both Store and source-history backup rollback domains. The installation and service
are independently trusted runtime premises. Local files cannot detect a rollback
of every copy. An operator must reconcile restored state against independent
continuity before the service can attest RECONCILED. Restoring Store artifacts or
old approvals alone restores no acquisition or continuation capability.

## V2 decisions, dispatch and replay

`research-real-source-use-decision-v2` has schema 2. It binds the exact manifest
and policy, stage, selection and projection digest, purpose and issue, issuer,
exact signed authority-record digest, issued time and validity, state and reasons.
Its evidence retains the full signed history, checkpoint and verification key.
These retained bytes support historical signature inspection only.

Research capture starts with the released V1 offline index. New continuation
requires an explicit exact source manifest and current independent V2 authority.
Every dependency must authorize raw and normalized retention, private backup/
restore/replay and derived statistical use. Acquisition also requires automated
access. An attribution-only approval cannot dispatch or admit these operations.
It produces `research-capture-index-v2` with the exact V2 sidecar. Each CB01 trust
refresh and timestamp dispatch rechecks current source authority. The existing
artifact write guard rechecks after staging and inside protected catalog insertion.
All retained-evidence and manifest validation, authority history verification,
classification reads, and validity calculations precede the final fresh checkpoint.
A withdrawal completed during validation either appears in the checked history or
makes the checkpoint disagree with that history. Dispatch then refuses, and the
protected insertion transaction rolls back. No post-commit guard reports a refused
admission after catalog insertion. The minimal interval between the checked current
state and an external request remains unavoidable; there is no network atomicity
claim. Existing attempts and failures
remain retained; this adds no retry or backfill capability. Outcome attachment
requires its own exact OUTCOME manifest and guard.

V1 source decisions keep their exact seven-field bytes and reader. Caller-supplied
V1 authorizers remain constructible for compatibility but grant no current use.
V1 historical capture and outcome readers retain their original behavior. V2
successors preserve all denominator rows, original outcomes and source decisions.
Historical replay uses retained evidence only. It does not load runtime authority,
contact the checkpoint service, acquire sources or fetch terms. Withdrawal and
later terms reviews refuse present use without rewriting original history.

Provider adapters, transport qualification, live acquisition, production keys,
source and causal provisioning, #86 activation, fitting, PLAY and Product Promotion
are outside this implementation.

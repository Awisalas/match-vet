# Causal witness profile activation audit, 2026-10-10

Audit target: `matchvet-sigstore-causal-event-v1`, SHA-256
`7ba7e2f4db4de3aa7ef41d77d9ff5f8fafecb73c6de9c5b297924454f51e5c66`.
This record concerns prospective RESEARCH_ONLY collection. It grants no activation.

Decision: activation remains BLOCKED. The fetched policy and trust pins support
the existing historical-assurance profile, but they do not supply authenticated
production approval, withdrawal handling, or authoritative restore history.
The original retained metadata is expired, and the deployment and current-status
UNKNOWNs below cannot become factual approvals. No activation implementation issue
is created on this evidence. #70 remains OPEN with `needs-info`; #86 remains CLOSED.

## External evidence and classification

Reviewed 2026-10-10 using primary documents, GET-only metadata, SHA-256,
OpenSSL certificate inspection, and offline `_authenticate` verification.
Observed HTTP `Date` values began `2026-10-10T01:45:34Z`. They are observation
metadata, never qualifying UTC. No timestamp request, production approval, or
source acquisition occurred. UNKNOWN does not authorize use.

| Prerequisite | State | Evidence and limit |
| --- | --- | --- |
| Exact RFC3161 endpoint and operator association remain published | SATISFIED | Official [documentation](https://docs.sigstore.dev/cosign/verifying/timestamps/) retains `https://timestamp.sigstore.dev/api/v1/timestamp`. GET returned 405, establishing a route but no issuance or availability guarantee. |
| Current normative policy/OID/UTC accuracy support | SATISFIED | [Policy revision](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md) and SHA-256 `97a3306df4f0ea5f5f64a938072bb802492b7cf1fca0661b20de0a6c98071bcf` are unchanged. OID `1.3.6.1.4.1.57264.2` still promises UTC, leap synchronization, and one-second-or-better accuracy. |
| Actual production policy compliance and unsmeared UTC | UNKNOWN | Policy supports the explicit trust premise; [monitoring](https://github.com/sigstore/timestamp-authority/blob/main/README.md#time-accuracy-and-monitoring) delegates controls to the operator. Reviewed sources authenticate no public-host conformity or smear declaration. |
| Current metadata closure satisfies retained pins and rollback floors | SATISFIED | `_authenticate` verified bootstrap10, sequential roots11 through15, role signatures/references, target length/hash, endpoint, and exact chain pins. Supplied metadata authentication establishes neither globally latest trust nor nonrevocation. |
| Original retained bundle permits new events now | UNSATISFIED | Timestamp799 expired `2026-10-10T01:39:25Z`. Its expiry bound refuses new intervals. A newer authenticated bundle preserving the same target/pins fits v1. |
| Certificate and authority validity now | SATISFIED | Both DER certificates span `2025-04-08T06:59:43Z` through `2035-04-06T06:59:43Z`. [Authority validity](https://raw.githubusercontent.com/sigstore/root-signing/main/targets/trusted_root.json) starts `2025-07-04T00:00:00Z`, without an end. Actual events still need all metadata and activation bounds. |
| Published check for compromise, withdrawal, or pin/policy change | SATISFIED | Policy/TrustedRoot are unchanged. Reviewed advisories below declare no key compromise or timestamp revocation. This bounded search does not prove noncompromise. |
| Authenticated current nonrevocation/key-integrity assurance | UNKNOWN | The certificates have no CRL/OCSP fields. No current TSA status service or noncompromise statement was established. Advisory absence and TUF signatures do not provide that assurance. |
| Declared historical assurance | SATISFIED | `HISTORICAL_RETAINED_TRUST_ONLY`, `current_revocation_checked=False` match [ADR 0003](../adr/0003-causal-matchweek-selection-witness.md) and [design](../design/causal-matchweek-selection-witness.md#historical-verification-and-current-trust). They do not satisfy policy §8's separate current-revocation obligation. |
| Causal execution and immutable replay contract | SATISFIED | Static [selection](../../src/matchvet/causal_selection.py), [witness](../../src/matchvet/causal_witness.py), [transport](../../src/matchvet/causal_transport.py), and retained [#84 proof](../../.audit/issue-84-implementation/README.md) preserve exact binding, one request, `U < T`, occupied failed slots, and separate CB01 chronology. Earlier tests were reviewed, not rerun. |
| Authenticated activation and operator/key/policy acceptance | UNSATISFIED | [`_load_approval`](../../src/matchvet/causal_selection.py) always refuses. [`_Approval`](../../src/matchvet/causal_trust.py) authenticates no issuer itself. The isolated [test approval](../../tests/causal_selection_support.py), expired `2026-10-06T00:00:00Z`, provides no production authority. |
| Operational withdrawal and restore/rollback authority | UNSATISFIED | Checks enforce supplied floors/history/withdrawal bounds. No production owner establishes their authoritative current state. A caller's history string or signed old record cannot detect restored-away withdrawal. |

## Exact fetched trust state

Sigstore identifies the [CDN repository](https://github.com/sigstore/root-signing#tuf-repository-status)
as its production client distribution. The fetched closure was verified with
existing MatchVet code. No `_Approval`, Store, witness operation, or network
transport was constructed. A static sample interval of
`2026-10-10T01:50:00Z` through `2026-10-10T01:50:01Z` passed its validity checks. That sample
checks boundaries only.

| Role | Retained floor | Fetched version | Fetched SHA-256 | Signed expiry |
| --- | --- | --- | --- | --- |
| [root](https://tuf-repo-cdn.sigstore.dev/15.root.json) | 15 | 15 | `73747011d0857ada15479a16c4cae0f3ed03aac698b523b97e1de314ac9d9ca8` | `2026-11-20T13:58:18Z` |
| [timestamp](https://tuf-repo-cdn.sigstore.dev/timestamp.json) | 799 | 804 | `bfce2fedd5a37044f1e48fbc4dcadf4dc8f8835f7d6f5e1414446bcb9f926975` | `2026-10-16T19:26:11Z` |
| [snapshot](https://tuf-repo-cdn.sigstore.dev/166.snapshot.json) | 165 | 166 | `6d61405faa993ba3d07556b79d1e319627cdc06ff879a7b5700967dc25d1d224` | `2036-10-04T08:51:19Z` |
| [targets](https://tuf-repo-cdn.sigstore.dev/14.targets.json) | 14 | 14 | `6a697f7f8908c8ab26c11786ecb490b54acec97fa8c802e399f065f8a0cc1acd` | `2036-05-09T09:00:52Z` |

The authenticated [TrustedRoot target](https://tuf-repo-cdn.sigstore.dev/targets/6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66.trusted_root.json)
is 6787 bytes and still has SHA-256
`6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`.
Its single TSA retains the exact endpoint and two-certificate chain. Signer
SHA-256 remains `85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7`;
anchor remains `2aca8fea5d3ce48b01cc77076293c280e6c23ffe44034757ee7833ca9f45d633`.
Root16 retrieval returned 404. That response is not a signed assertion that no
newer root exists. Snapshot166 contains a metadata reference named
`revocation.json`, but authenticated targets14 delegates only
`registry.npmjs.org/*`. It authorizes no revocation role. GETs of
`revocation.json` and `2.revocation.json` returned 404. Neither the reference nor
the failed retrieval establishes authenticated TSA status.

## Source changes and operational limits

The latest [handler file](https://github.com/sigstore/timestamp-authority/blob/88266e3dc38acb687bd38798c9bff43e180a28ad/pkg/api/timestamp.go)
is revision `88266e3dc38acb687bd38798c9bff43e180a28ad`, different from v1's reviewed
`3593e847b84fa501e2a0729eaea2c6ac982c4ab3`. It still generates from
`time.Now().UTC()`, supplies one-second accuracy, and uses the requested OID or
default. The current code also checks an operator-configured accepted-OID list.
OID equality does not independently attest policy compliance. Repository source
is not the deployed build/configuration. If activation requires binding a newly
reviewed handler revision instead of the original review identity, changing those
profile bytes requires a new immutable profile.

The [README](https://github.com/sigstore/timestamp-authority/blob/main/README.md#time-accuracy-and-monitoring)
says monitoring does not stop issuance. `.UTC()` establishes no unsmeared-clock
discipline. [Google's default NTP uses leap smear](https://docs.cloud.google.com/compute/docs/instances/time-synchronization/configure-ntp),
but generic cloud support does not identify this public endpoint's clock source.
Its host discipline remains UNKNOWN. Day-boundary refusal cannot detect hidden smear.

The policy's [verification requirements](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#8-security-considerations)
require current revocation checks and invalidate compromised-key tokens. Annex A
requires key-integrity evidence. V1 declares conditional historical assurance.
Missing OCSP does not silently add a stricter MatchVet contract, but external
evidence supplies neither local withdrawal controls nor a current-status guarantee.

The current [TSA advisories](https://github.com/sigstore/timestamp-authority/security/advisories)
include [CVE-2026-49835](https://github.com/sigstore/timestamp-authority/security/advisories/GHSA-9c54-x2g4-v92j),
an availability issue from unbounded metric labels, and
[CVE-2026-39984](https://github.com/sigstore/timestamp-authority/security/advisories/GHSA-xm5m-wgh2-rrg3),
a Go verifier certificate-selection issue explicitly excluding the TSA service.
MatchVet's own pinned signer/CMS verifier does not use the affected Go function.
Public deployment patch status is UNKNOWN. The
[root-signing advisory list](https://github.com/sigstore/root-signing/security/advisories)
was empty in the reviewed public response. Public vulnerability reporting has
[private disclosure stages](https://github.com/sigstore/.github/blob/main/SECURITY.md);
absence of a published key-compromise notice is not proof of noncompromise.

## Profile version and assurance decision

An authenticated refresh with the same target/pins can remain within v1's existing
representation. Changing key, endpoint, policy, timescale, assurance, or reviewed
handler identity requires a new immutable profile and explicit approval. Current
metadata and the reviewed advisories do not themselves require a new profile.
The changed upstream handler is a reassessment finding, not evidence that the
public service runs that build or that retained receipts changed meaning.

ADR 0003 permits reliance on the operator's promise and uncompromised authority.
This audit adds no independent hardware-audit requirement. Published support for
the premise is SATISFIED; actual deployment conformity is UNKNOWN; authenticated
MatchVet acceptance is UNSATISFIED. Known-invalidation handling is also
UNSATISFIED without authenticated owner state. V1 cannot satisfy a consumer
requiring affirmative current nonrevocation. That consumer must remain refused
until a separately reviewed immutable assurance profile supplies the evidence.

## Minimum authenticated local mechanism still required

The future trusted configuration owner needs these properties to replace
`_load_approval()` safely. No owner key, interval, or activation record is chosen
in this audit.

1. An owner-signed canonical record binds its domain/schema/action, sequence,
   predecessor, catalog/history identity, profile digest, source/policy/key pins,
   activation interval, trust-bundle digests/floors, timescale, and accepted
   assurance/premises. Its content digest is the immutable approval identity.
2. The private loader obtains the record from the trusted configuration owner
   and verifies an independently installed owner key. The record cannot supply
   its own trusted key. Caller arguments, artifact discovery, or constructing
   `_Approval` cannot grant authority.
3. Activation, floor advancement, and withdrawal append signed records.
   Withdrawal binds the affected profile and effective UTC boundary. Present
   qualification enforces it. Historical inspection retains original approval,
   trust bytes, graph, receipt, and occupied slot.
4. The owner retains an authoritative sequence/head digest outside the catalog's
   backup rollback domain. The loader rejects absent, conflicting, lower, or
   uncertain history and reconciles restores before allowing use. Signatures
   authenticate old records too. If every local copy of the head rolls back,
   local bytes alone cannot detect it. An authenticated owner checkpoint or
   equivalent independent continuity evidence is necessary.
5. Admission verifies the exact authenticated bundle and full event interval
   within existing bounds. Restart restores no request authority. Stable slots,
   one attempt, and separate real-source authorization remain mandatory.

The [TUF client workflow](https://theupdateframework.github.io/specification/latest/#detailed-client-workflow)
separately requires persistent version checks and a fixed update-start time for
ordinary freshness. This proposal retains MatchVet's event-interval semantics.
It does not turn the checked token or local wall time into proof of a globally
latest configuration or trust state.

## Evidence reviewed and exact next blockers

Local review covered both requested designs, ADR 0003, the four production
modules, retained #80/#81/#84 issues/audits/tests, DER/TUF assets, and CandidateInput
status. Their older introductory status prose predates implementation. Closed
issues and present code establish offline completion; activation still refuses.

The next decision must resolve or explicitly authenticate acceptance of the
operator/key/policy, unsmeared-UTC, accuracy, and historical-assurance premises.
Operation also needs an owner-authenticated activation/withdrawal history with
restore continuity and a refreshed, exact metadata bundle whose interval has not
expired. Full current-status assurance is unavailable from the reviewed evidence.
Until these prerequisites pass, the production refusal remains correct and no
activation implementation issue is created. Real-source authorization is a
separate unresolved gate. No qualified prospective #70 cohort exists yet.

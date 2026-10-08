# Causal Matchweek witness protocol research

Reviewed 2026-10-08 for #79. This investigation read primary sources and inspected
the retained, non-live CB01 diagnostic token. It made no new TSA or Roughtime
request, read neither live SQLite store, and acquired no fixtures. The conclusion
authorizes a prospective design subject to an explicit trusted-authority premise;
it does not qualify a running production provider.

## Recommendation and trust boundary

Use RFC3161 with the Sigstore TSA as the first prospective witness profile. Its
signed `accuracy` has a normative event-bound meaning. Use the exact declared
accuracy, never an invented allowance or `genTime` alone. The client must trust
Sigstore to comply with its named UTC accuracy policy. Cryptography authenticates
that assertion; it cannot independently prove an operator's clock is honest.

This premise must be a deliberate versioned authority decision. Existing CB01
trust alone does not approve the new role. If MatchVet instead requires independent
proof that every production Sigstore instance enforces its accuracy promise, the
reviewed sources do not supply it and production must continue refusing. This is
an authority qualification limit, not the Android return-time impossibility.

## A. RFC3161 and Sigstore

RFC3161 sections 2.1, 2.2, 2.3 and 2.4.2 define a TSA event after its request,
signed message imprint and nonce, critical timestamp EKU, signer identification,
and UTC `genTime`. The standard explicitly defines `genTime + accuracy` as an
upper limit on token creation. Accuracy components inside a present `Accuracy`
default individually to zero; an absent `Accuracy` does not mean zero. A policy
may supply it. `ordering=false` does not defeat request causality. Verify status,
policy, hash algorithm, exact imprint, exact mandatory application nonce, CMS
signature, signer identity, chain and trust validity. Reject unsupported extensions
or ambiguous time representations. [RFC3161](https://www.rfc-editor.org/rfc/rfc3161.html#section-2.4.2)

Sigstore policy OID `1.3.6.1.4.1.57264.2` declares accuracy of one second or
better. Sections 7.3.1 and 7.3.2 require UTC traceability, declared accuracy and
correct leap handling. Section 7.4.8 requires suspension of issuance after loss
of calibration until recovery. Section 5.4 permits operator conformance claims
or independent assessment; it does not mandate a public independent audit.
Pin the reviewed policy revision `3a83b1f015affed68763ef73f7729aa478c650e1`.
[Sigstore policy](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md)

The handler reads, parses and validates the entire request before reading UTC.
It copies the request imprint and nonce, sets fixed `Accuracy=1s`, and signs
afterward. That constant is an authority assertion, not a measured uncertainty.
Source inspection used revision `3593e847b84fa501e2a0729eaea2c6ac982c4ab3`.
[Handler source](https://github.com/sigstore/timestamp-authority/blob/3593e847b84fa501e2a0729eaea2c6ac982c4ab3/pkg/api/timestamp.go#L148)
The handler also echoes the requested policy OID, using its default only when
the request omits one. A signed OID match therefore proves request consistency,
not independent source-policy enforcement. The approved profile must separately
associate the expected endpoint/operator/signing key with the reviewed UTC policy.
The generic monitor only reports drift metrics and keeps issuing. Operators
must supply additional controls. No reviewed source established the public
deployment's exact controls. Treat total declared accuracy, including encoding
and token-generation effects, as the accepted operator promise rather than
claiming this code establishes it.
[Monitoring limitation](https://github.com/sigstore/timestamp-authority/blob/3593e847b84fa501e2a0729eaea2c6ac982c4ab3/README.md#time-accuracy-and-monitoring)

Sigstore documents the production endpoint
`https://timestamp.sigstore.dev/api/v1/timestamp` and its verification roots.
It also explains that Rekor v1's signed integrated time is mutable outside its
append-only node. Rekor time therefore supplies no stronger substitute here.
[Sigstore timestamp documentation](https://docs.sigstore.dev/cosign/verifying/timestamps/)
TUF authenticates evolving trust material using a separately pinned bootstrap.
Retain the exact verified root rotations, timestamp/snapshot/targets metadata,
TrustedRoot bytes and selected certificate fingerprints. TUF expiry checks need
an explicit bootstrap policy; untrusted device time cannot establish freshness.
[Sigstore root distribution](https://github.com/sigstore/root-signing)
For the new role, a conservative profile can require the witness's whole UTC
interval inside certificate, authority and retained metadata validity periods,
plus repository-approved authority versions and rollback rejection. This is a
MatchVet policy choice, not an assertion that TUF by itself measures UTC.

Section 8 requires current revocation status during certificate lifetime; Annex A
requires key-integrity evidence for long-term verification. Offline retained TUF
trust is not independently current status. The new MatchVet historical-event
profile therefore declares its reliance on an uncompromised approved authority
and its limit against policy-wide current-revocation assurance. A known
authenticated invalidation must refuse current qualification without rewriting
selected artifacts; retained historical inspection remains distinct. No reviewed
source promises a fresh CRL/OCSP mechanism for this self-signed Sigstore chain.
[Verification obligations](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#8-security-considerations)

### Retained exact-token inspection

OpenSSL decoded the existing diagnostic response as policy
`1.3.6.1.4.1.57264.2`, SHA-256 imprint
`d962360c348c5b4c5b22e7e5342f56470ffe83fee31d41db8a0304b770ad0e98`,
nonce `0x97F4C90FF5708E70`, `genTime=2026-10-05T04:50:21Z`, signed accuracy
one second, and `ordering=no`. Thus its protocol upper bound is
`2026-10-05T04:50:22Z` under the stated authority premise. It is diagnostic
evidence only and may never become a Matchweek witness.
[Retained bundle](cb01-sigstore-witness-2026-10-05/README.md)

These commands ran again in this investigation without network access:

```sh
openssl ts -reply -in docs/research/cb01-sigstore-witness-2026-10-05/response.tsr -text
openssl ts -verify -queryfile docs/research/cb01-sigstore-witness-2026-10-05/request.tsq -in docs/research/cb01-sigstore-witness-2026-10-05/response.tsr -CAfile docs/research/cb01-sigstore-witness-2026-10-05/tsa-root.pem -attime 1791175821
openssl ts -verify -queryfile docs/research/cb01-sigstore-witness-2026-10-05/changed-request.tsq -in docs/research/cb01-sigstore-witness-2026-10-05/response.tsr -CAfile docs/research/cb01-sigstore-witness-2026-10-05/tsa-root.pem -attime 1791175821
```

The exact request returned `Verification: OK`. The changed request returned
`Verification: FAILED` with `message imprint mismatch`. These checks prove
retained signature/imprint verification works on Termux; they do not measure
Sigstore's real UTC accuracy or test a new production completion path.

## B. Nonce-bound Roughtime

RFC10049 is Experimental. Its signed response commits a Merkle root containing
the nonce and declares the server processing interval `MIDP ± RADI`. Servers
must contain true processing time in that interval, use nonzero radius, and
account for leap ambiguity. Timestamps use Unix seconds with 86400-second days.
Verify long-term key, delegation interval, response signature, supported version,
nonce and Merkle inclusion. For this event boundary `U=MIDP+RADI` needs no local
elapsed aging. Binding requires deriving the nonce from a domain-separated
canonical selection commitment and fresh postcommit randomness. A random nonce
plus an unsigned local digest association is insufficient external binding.
[RFC10049 sections 4.1.4, 5.2.5, 5.4 and 6](https://www.rfc-editor.org/rfc/rfc10049.html)

Cloudflare documents UDP port 2003 and Ed25519 root
`0GD7c3yP8xEc4Zl2zeuN2SlLvDVVocjsPSL8/Rl/7zg=`. The service is beta and its
root can change. HTTP documentation or unauthenticated DNS key discovery must
not silently replace a pinned production root.
[Cloudflare usage](https://developers.cloudflare.com/time-services/roughtime/usage/)
Port 2002 and its old key retired on 2024-06-30.
[Deprecation record](https://developers.cloudflare.com/time-services/roughtime/deprecation/)
The published Go client source at revision
`75645289794cfbd71a08f0e7ecf9bc4f3f87d133` supports older draft shapes and
signature contexts, and distinguishes microsecond legacy timestamps from
second IETF timestamps. It is not evidence that the endpoint implements the
new RFC wire profile. Go/UDP are practical from Termux, but protocol adaptation,
raw evidence retention and network reachability would need separate validation.
[Client source](https://github.com/cloudflare/roughtime/blob/75645289794cfbd71a08f0e7ecf9bc4f3f87d133/protocol/protocol.go)

STUPI's public `roughtime.se:2002` advertises draft-19, an atomic-clock
connection, and public timestamping use. Its operator publishes long-term key
`S3AzfZJ5CjSdkJ21ZJGbxqdYP/SoE8fXKY0+aicsehI=`. This is a concrete additional
candidate, not a qualified MatchVet source or availability guarantee.
[Operator service page](https://roughtime.se/)
Neither service removes the trusted-clock premise. RFC3161 is preferable here
because the existing exact-token verification is demonstrated and its named
policy defines UTC accuracy. No Roughtime fallback should be automatic.

## C. Stronger practical mechanism

AWS documents Linux EC2 ClockBound intervals and Nitro PTP hardware error
reported through ENA. This supplies a more explicit hardware error source on
qualified EC2 hosts, not Android. A dedicated service could receive a bound
selection challenge, sample its qualified interval, then sign the challenge and
interval. The qualifying event would be the post-request sample; later signing
and delivery would be harmless. That service would need its own authenticated
protocol, key management and operational qualification. AWS's library does not
already provide a public signed timestamp endpoint.
[AWS EC2 error bounds](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/compare-timestamps-with-clockbound.html),
[ClockBound source documentation](https://github.com/aws/clock-bound/blob/main/README.md)

Two independently qualified authorities can strengthen the honesty premise.
Require both postcommit witnesses and use the maximum upper endpoint. If at
least one is honest, its event alone proves the earlier commit before that
maximum. Minimum or median upper endpoints do not preserve that reasoning.
This is a deduction; no reviewed service supplies an already-qualified
multi-authority MatchVet receipt. The additional availability/deployment cost
does not justify selecting it for the smallest correction.

## Causal proof and operational consequences

Let each collection/computation finish before its immutable content-addressed
artifact. Validate that every exact required F11/F13/F14 artifact belongs to the
closed selected F16 graph. Commit that graph into the unique logical-Matchweek
slot. Only the winning fresh commit receives a process-local witness capability.
It then generates a fresh challenge binding the selection identity and digest,
closed graph manifest, logical Matchweek, exact common cutoff and policy version.
The authority's signed event follows that request. Therefore every required
research event precedes commit, request and witness, and witness is at most U.
Acceptance of `U<T` proves all selected research existed before T. No local
creation timestamp enters this proof.

The proof depends on honest local execution/storage, digest collision
resistance, immutable artifact edges, atomic unique selection and honest
qualified remote authority. A TSA does not attest to SQLite durability or prove
that someone actually performed research. The application must enforce those
causal prerequisites; an externally signed digest alone cannot do so.

Android suspension before transmission can only make the remote event late.
Suspension after transmission or during delivery cannot change the signed
event. Receipt persistence after T records existing evidence. Late, missing,
invalid or ambiguous witnesses permanently leave the slot unqualified. Restart
may verify complete retained evidence, never recreate a challenge from stored
selection. A crash after issuance but before retained complete response loses
qualification; partial writes do not authorize reconstruction. Competing writers
cannot obtain the winning capability or replace the occupied selection.

For #76, local time can prune wasted candidate work but cannot qualify it.
Early timestamps cannot qualify an F11-F16 candidate. Prospective candidate
writers need versioned unqualified-state semantics; only the final closed-graph
causal witness qualifies the immutable selected graph. No artifact produced
after the witness can join that graph. No post-T model/evidence/decision may
alter it. Unavailable network or authority sacrifices the whole Matchweek's
qualification, and there is no local-time fallback.

CB01 remains a separate post-T, pre-kickoff enrollment witness. This research
does not replace its existing `genTime` contract with the new Matchweek upper
bound or reinterpret its tokens. The new witness must use its own domain,
versioned receipt, provenance and reader dispatch. Existing v1/legacy proofs
retain their original meaning; old acceptance tests cannot establish the new
causal timing semantics.

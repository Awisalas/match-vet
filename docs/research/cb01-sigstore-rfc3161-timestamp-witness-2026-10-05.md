# CB01 Sigstore RFC 3161 timestamp witness research

Reviewed 2026-10-05 for CB01 #72. This note records official Sigstore service/trust documentation and one successful unauthenticated Termux request with offline verification.

## Service and usage

Sigstore's timestamp documentation lists `timestamp.sigstore.dev` as a public TSA and shows `https://timestamp.sigstore.dev/api/v1/timestamp` in Cosign's default production signing configuration, with operator `sigstore.dev` and validity starting 2025-07-04. It also says Cosign uses a TSA by default when appropriate. The service README describes its implementation as an RFC 3161 timestamp service and includes the OpenSSL and curl request flow. These sources establish that this is the public client service, not a local-development endpoint. [Sigstore timestamp docs](https://docs.sigstore.dev/cosign/verifying/timestamps/), [TSA service README](https://github.com/sigstore/timestamp-authority/blob/main/README.md)

The request was an ordinary HTTPS POST containing only `application/timestamp-query`. It used no Authorization header, account, API key, client certificate or other credential. The service returned HTTP 200 with `application/timestamp-reply` and a granted response. This proves the observed endpoint accepted this request without client authentication. It is not a service availability guarantee.

I found no published caller authentication requirement, price, quota, rate limit or use restriction in the official client docs, default service configuration, TSA README or TSA policy reviewed. Those documents also do not promise unlimited use, free service, an SLA, or a caller rate budget. The TSA policy says issuance is at TSA discretion and any service level agreement may affect it. One request per exact fixture batch, with no request per preference, is bounded; no numeric request cadence is inferred. The service's security advisory recommends rate limiting for operators to mitigate abusive request volume, but sets no client quota. [TSA policy, sections 6.2 and 7](https://github.com/sigstore/timestamp-authority/blob/main/docs/tsa-policy.md), [operator rate-limit advisory](https://github.com/sigstore/timestamp-authority/security/advisories/GHSA-9c54-x2g4-v92j)

## Termux request and response

The environment used curl 8.21.0 and OpenSSL 3.6.3 on Android arm64. No packages were installed. The temporary commitment was the exact UTF-8 bytes:

```text
CB01 Sigstore RFC3161 feasibility commitment 2026-10-05 fixture-batch placeholder commitment
```

Its SHA-256 was `d962360c348c5b4c5b22e7e5342f56470ffe83fee31d41db8a0304b770ad0e98`. OpenSSL generated a DER request with SHA-256, a random nonce and `certReq`. An unauthenticated POST to the target endpoint received HTTP 200. OpenSSL decoded the response as RFC 3161 status `Granted`, policy OID `1.3.6.1.4.1.57264.2`, exact matching SHA-256 imprint, and exact matching nonce `97f4c90ff5708e70`. The token contains signed `genTime` `2026-10-05 04:50:21 UTC` and accuracy `1 second`. The HTTP Date header was not used for chronology.

The response included signer certificate subject `O=sigstore.dev, CN=sigstore-tsa`, serial `3A13542F0C9061EEBCC1432FCB8A8E8B2A238B0C`, and critical `Time Stamping` EKU. Its issuer is `O=sigstore.dev, CN=sigstore-tsa-selfsigned`. The certificate is valid 2025-04-08 through 2035-04-06. SHA-256 fingerprints over DER are:

| Material | SHA-256 fingerprint |
| --- | --- |
| Signer `sigstore-tsa` | `85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7` |
| Self-signed trust anchor `sigstore-tsa-selfsigned` | `2aca8fea5d3ce48b01cc77076293c280e6c23ffe44034757ee7833ca9f45d633` |

The signer and trust anchor both use ECDSA P-384 with SHA-384 certificate signatures. The token CMS uses SHA-256 as its digest and ECDSA as its signature algorithm. This differs from the DigiCert RSA chain.

## Authenticated TUF trust material

Sigstore documents the TUF repository at `https://tuf-repo-cdn.sigstore.dev/` as the production distribution path for `trusted_root.json`. The root-signing project says keyholders cryptographically sign changes, and production publication follows automated client verification. The Sigstore installation guide documents bootstrapping with TUF root history version 10, then initializing a TUF client against that CDN and fetching the current target. [Root-signing repository](https://github.com/sigstore/root-signing), [Sigstore TUF installation instructions](https://docs.sigstore.dev/cosign/system_config/installation/)

For this check, the documented root-history version 10 was the TUF bootstrap root (SHA-256 `836bff947925edfc23eb9ce17af66fb1e43bb5e2bdd240520985ae52b585eae9`). The already-installed `tuf-js` 4.1.0 client followed and verified the root rotation chain through root version 15 and authenticated timestamp metadata version 799, snapshot version 165 and targets version 14. It then verified the exact `trusted_root.json` bytes against signed target length and SHA-256 before use. No package was installed. The resulting TrustedRoot is media type `application/vnd.dev.sigstore.trustedroot+json;version=0.1`, length 6787, SHA-256 `6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`. The embedded TSA entry names the exact endpoint, subject `sigstore.dev / sigstore-tsa-selfsigned`, and chain containing the signer followed by the self-signed trust anchor. Its `validFor` starts `2025-07-04T00:00:00Z` and has no end.

The signed verification metadata used for this result is retained in the [offline evidence bundle](cb01-sigstore-witness-2026-10-05/README.md): root v15 expires 2026-11-20, timestamp v799 expires 2026-10-10, snapshot v165 and targets v14. The bundle contains the bootstrap and root rotation chain, exact metadata bytes, TrustedRoot target, request, response, extracted token and certificates. Keep the bootstrap-root source/version and verified metadata versions, target digest/length, and selected DER certificate fingerprints in each CB01 trust identity. A moving `main` URL alone is not a trust identity.

OpenSSL verified the raw request/response offline against the self-signed root extracted from the TUF-authenticated TrustedRoot using `-CAfile` and `-attime 1791175821`, the response's signed `genTime`. Verification returned `Verification: OK`. A request for a changed digest failed with `message imprint mismatch`. A truncated response failed ASN.1 decoding. The online TUF refresh and target check occurred before the offline timestamp check; the OpenSSL verification itself made no network request.

## Trust updates and revocation

This TSA uses a self-signed certificate chain whose trust is supplied by Sigstore's TUF TrustedRoot. The signer certificate has no CRL Distribution Points or Authority Information Access/OCSP fields. Do not apply DigiCert's CRL/OCSP assumptions or report CRL/OCSP checking for this Sigstore chain.

CB01 should refresh and cryptographically verify Sigstore TUF metadata before each fixture batch, retain the exact verified metadata chain and TrustedRoot target, and use only the TSA entry whose URI, subject, validity interval and DER chain match the pinned policy. TUF root rotation and signed target updates are Sigstore's trust-update mechanism. A future TrustedRoot can replace/remove the TSA entry or constrain its `validFor` interval. An unknown or changed chain fails closed until a newly authenticated and versioned policy accepts it.

Offline replay of an enrollment proves the token against the exact TUF trust state retained at enrollment. It cannot learn about a later key-compromise declaration while offline. A later TUF trust change that affects an old token needs an explicit, immutable trust reassessment under the newer authenticated root; it must not rewrite the original receipt. Record this limit. The reviewed service materials do not document an OCSP or CRL mechanism for this self-signed TSA chain.

## CB01 chronology decision

The CB01 rule remains strictly `F07 cutoff < verified RFC3161 genTime < fixture kickoff`. The signed time, signature, exact imprint and nonce are chronology evidence. Local system time, HTTP Date, Git timestamps and ArtifactStore `created_at` remain metadata only. Request transport failure, non-granted status, malformed reply, nonce or imprint mismatch, untrusted TUF state, wrong signer/EKU, invalid chain/time, out-of-window `genTime`, incomplete denominator or changed lineage cannot become `ENROLLED_LIVE`. There is no automatic fallback source.

Use one request per exact fixture batch covering the complete frozen preference denominator, not one per preference. This spike demonstrates protocol feasibility and trust verification; it does not implement CB01 or exercise its repository recovery/publication behavior.

## Readiness result

The Sigstore public client service satisfies the bounded CB01 use based on the documented production default and observed anonymous request. No official caller restriction, account requirement, price or numeric rate limit was found in the reviewed materials. This is a finding about the reviewed published sources, not a guarantee of unrestricted future availability. The prior DigiCert service-use blocker is resolved for this choice.

CB01 can proceed to `ready-for-agent` with this versioned Sigstore TUF trust contract and the explicit post-issuance revocation limit. Add CB01 before F17 as the chronological bootstrap. Keep F17 blocked by F16 and #70. Do not change #70 methodology. F21 later adopts these CB01 identities and witnesses.

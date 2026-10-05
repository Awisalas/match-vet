# CB01 RFC 3161 timestamp witness research

Historical DigiCert feasibility note reviewed 2026-10-04 for [CB01 #72](https://github.com/Awisalas/match-vet/issues/72). DigiCert is no longer an active CB01 dependency. The service-use question was subsequently resolved by the Sigstore evaluation in [the 2026-10-05 note](cb01-sigstore-rfc3161-timestamp-witness-2026-10-05.md); retain this file as historical research only. This note records primary-source findings and a successful Termux request and offline cryptographic verification.

## DigiCert endpoint and certificate material

DigiCert documents `http://timestamp.digicert.com` as its public RFC 3161 endpoint. Its current knowledge-base page reports a certificate replacement on 2026-09-03 and lists SHA-256, SHA-384, and SHA-512 responder certificates. Certificate rotation means old tokens need their actual historical signer material. [DigiCert RFC 3161 TSA documentation](https://knowledge.digicert.com/general-information/rfc3161-compliant-time-stamp-authority-server)

The documentation links these current SHA-256 chain files:

- [DigiCert SHA-256 RSA4096 timestamp responder 2026 1](https://knowledge.digicert.com/content/dam/kb/attachments/time-stamp/DigiCertSHA256RSA4096TimestampResponder20261.cer)
- [DigiCert Trusted G4 timestamping RSA4096 SHA256 2025 CA1](https://knowledge.digicert.com/content/dam/kb/attachments/time-stamp/DigiCertTrustedG4TimeStampingRSA4096SHA2562025CA1.pem)
- [DigiCert Trusted Root G4](https://knowledge.digicert.com/content/dam/kb/attachments/time-stamp/DigiCertTrustedRootG4.cer)

These are attachment links extracted from the official documentation. The response's actual signer and issuer determine which chain applies. The root must be an independently accepted trust anchor. A certificate supplied inside an untrusted response cannot appoint itself as trusted.

DigiCert's current CP/CPS is version 7.09, dated 2026-09-03. Section 6.8 states RFC 3161 compliance, synchronization with a UTC(k) source at least every 24 hours, and detection of clock drift. It recommends timestamping signed code. This section does not state an exclusive signed-code restriction. That observation is limited to this section and does not assert an unlimited service entitlement or availability guarantee. [Current CP/CPS, section 6.8](https://www.digicert.com/content/dam/digicert/pdfs/legal/digicert-public-trust-cp-cps-v7-09.pdf#page=77), linked from [DigiCert's legal repository](https://www.digicert.com/legal-repository)

## Protocol and verification

RFC 3161 uses a DER request containing a message imprint. HTTP transport posts `application/timestamp-query` and returns `application/timestamp-reply`. The token contains the imprint, policy OID, serial number, UTC `genTime`, and the TSA signature. A requested nonce must match. A `certReq` request requires the signing certificate in a successful response. The optional `tsa` name is a hint. The signing-certificate attribute identifies the signer even when that name is absent. [RFC 3161, sections 2.4 and 3.4](https://www.rfc-editor.org/rfc/rfc3161)

The SHA-256 imprint is distinct from the signature's hash algorithm. The retained SHA-256 commitment must match the token's message imprint exactly. RFC 3161's optional `accuracy` describes clock deviation; absence does not mean zero deviation. If omitted, the applicable policy may provide the bound. A signed `genTime` proves the TSA's asserted time. A stronger actual-UTC-before-kickoff claim needs the policy's accuracy bound as well. [RFC 3161, section 2.4.2](https://www.rfc-editor.org/rfc/rfc3161)

OpenSSL supports an explicit arbitrary digest, SHA-256 selection, a default random nonce, and `-cert`. Its timestamp verifier accepts the original request, response, trusted CA file, and additional untrusted chain certificates. Certificates embedded in the token can supply the signer and intermediate. A retained response with these embedded certificates and an independently trusted root is enough for offline signature and request verification. [OpenSSL `ts` documentation](https://docs.openssl.org/3.6/man1/openssl-ts/)

The corresponding commands are:

```sh
openssl ts -query -digest "$commitment_sha256" -sha256 -cert -out request.tsq
curl --fail --max-time 30 \
  -H 'Content-Type: application/timestamp-query' \
  -H 'Accept: application/timestamp-reply' \
  --data-binary @request.tsq \
  -o response.tsr http://timestamp.digicert.com
openssl ts -reply -in response.tsr -text
openssl ts -verify -queryfile request.tsq -in response.tsr \
  -CAfile trusted-root.pem -untrusted intermediate.pem \
  -attime "$token_genTime_epoch"
```

These are research command shapes, not a new MatchVet entry point. The epoch value comes from token `genTime` and is accepted only after successful signature verification.

OpenSSL normally validates certificate lifetimes against the system clock. `-attime` supplies an explicit epoch reference for those checks. Using signed `genTime` removes the phone clock from that decision while preserving validity-period checks. Disabling checks with `-no_check_time` is unnecessary. Offline signature and chain validation alone do not prove non-revocation. Explicit CRL checking requires retained applicable CRLs and fails if required CRLs are missing. A verifier must state whether revocation was checked. [OpenSSL verification options](https://docs.openssl.org/3.6/man1/openssl-verification-options/)

## Alternate inspected

Sectigo documents `http://timestamp.sectigo.com` and RFC 3161 support. Its FAQ requests at least 15 seconds between scripted timestamp requests. [Sectigo timestamp FAQ](https://www.sectigo.com/faqs/detail/Time-Stamp-Server-Stamping-Protocols-for-Digital-Signatures-Code-Signing)

Its code-signing CP/CPS version 1.0.0, section 6.8, documents `http://timestamp.sectigo.com/rfc3161` but limits the TSAs to software signing with a Sectigo code-signing certificate. That documented restriction makes this candidate unsuitable as an automatic fallback for an arbitrary CB01 corpus commitment. No Sectigo request is needed to establish that restriction. [Sectigo code-signing CP/CPS, section 6.8](https://www.sectigo.com/uploads/files/Sectigo_CS_CPS_v1_0_0.pdf)

## CB01 implications

F07 cutoffs and kickoffs are per fixture. Define one canonical enrollment batch/root per target fixture and exact F07 cutoff. That root covers every enabled preference for the fixture, including explicit excluded and incomplete entries, so one RFC 3161 request covers the entire fixture preference denominator rather than one request per preference. A later whole-freeze index may reference these roots, but cannot make a late fixture live. The canonical root includes exact artifact digests and versions, F06/F07 denominator and cutoff identity, F10 preference profile, fixture kickoff, and raw prediction/availability state. It contains no settlement or outcome data.

`ENROLLED_LIVE` requires a successfully verified signature and chain, exact SHA-256 imprint and nonce correspondence, acceptable TSA identity/policy, and signed TSA time strictly `F07 cutoff < genTime < controlling kickoff`. Local ArtifactStore timestamps remain metadata. Unreachable service, rejected or malformed response, digest or nonce mismatch, unavailable verification, or `genTime` at or before cutoff or at or after kickoff fails closed. Preserve all expected entries and reasons in the commitment; failure never removes entries from the denominator. The fixture cutoff, kickoff, and source/model artifacts remain independently validated under their existing contracts; a TSA proves only that the committed root existed by its signed time.

This proposal proves the timestamped bytes existed by the TSA's asserted time. It does not independently establish the truth of the committed fixture kickoff, source publication times, model correctness, complete outcomes, or methodology eligibility. Those remain the existing artifact and #70 contracts.

## Observed Termux request and verification

The tested environment has OpenSSL `3.6.3` for `android-arm64` and curl `8.21.0`; no Python package was installed. `openssl ts -help` exposed query, response inspection, and verification options. OpenSSL created a DER RFC 3161 query from a temporary file using SHA-256 and `-cert`; the query contained a nonce and requested the signing certificate.

The request was POSTed to the documented `http://timestamp.digicert.com` endpoint with `application/timestamp-query`; HTTP returned `application/timestamp-reply` and a binary response. The HTTP `Date` header was not used. OpenSSL decoded the response as `Granted`, SHA-256, policy OID `2.16.840.1.114412.7.1`, serial `40B2D8859A1956240A0AF9E74F4626AA`, and signed `genTime` `2026-10-04 19:25:19 UTC`. The returned 32-byte imprint exactly matched the temporary commitment digest `cc7a7b9ac9040ead9113acd70ebe251fa522d9239fecc0567673cae7e1d7830c`, and the response nonce matched the query. Accuracy was unspecified and the optional `TSA` GeneralName was absent; the token did include the signer certificate.

The embedded signer subject is `C=US, O=DigiCert, Inc., CN=DigiCert SHA256 RSA4096 Timestamp Responder 2026 1`; its issuer is the DigiCert Trusted G4 TimeStamping RSA4096 SHA256 2025 CA1 intermediate. Its certificate has critical `Time Stamping` extended key usage and is valid from 2026-08-05 through 2037-11-04. Its SHA-256 fingerprint matched the responder certificate downloaded from DigiCert's official HTTPS link.

Offline verification succeeded with the original query and response, the documented DigiCert Trusted Root G4 certificate as a pinned `CAfile`, the documented timestamp intermediate as untrusted chain material, `-partial_chain`, and `-attime 1791141919` (the token `genTime`). No MatchVet phone-clock value or HTTP header participated in timestamp/certificate time validation. Verification without the intermediate failed with `unable to get issuer certificate`; the successful chain therefore needs the original response/query, an independently provisioned trusted anchor, and the relevant intermediate (extractable from the token or retained separately). A separately generated query for different content failed with `message imprint mismatch`; a corrupted response failed ASN.1 decoding. The response and all probe materials are retained locally under `.audit/cb01-timestamp/digicert/`.

No retry/fallback TSA was used because DigiCert worked. QuoVadis' published timestamp endpoint requires IP registration; that makes it a poor unattended fallback. Sectigo's inspected code-signing CP/CPS limits its TSA to software signing with a Sectigo certificate, so it is not a suitable silent substitute for an arbitrary CB01 root.


## Final readiness review, 2026-10-05

The [CB01 enrollment contract](../design/cb01-enrollment-contract.md) supersedes the proposal above. The committed bytes are outcome-free PreEnrollment payloads followed by one complete sorted fixture batch. The request, response and final records follow the batch digest, so no witness/digest circularity exists. A final receipt exposes the complete record set. Exact recovery may finish after kickoff only with the unchanged batch and a retained verified in-window token. Local catalog times remain metadata.

Certificate validity is checked at signed genTime. The selected material is the exact cross-signed Trusted Root G4 used by the spike as a pinned partial-chain anchor, its exact intermediate, and its exact signer. The contract records their DER SHA-256 fingerprints. The `.cer` root file from the official link is PEM encoded despite its extension; its raw-file digest is not its DER certificate fingerprint.

The spike performed no revocation check. DigiCert CP/CPS v7.09 section 1.3.4 requires relying parties to check CRL or OCSP status before reliance. CB01 v1 therefore requires retained applicable signed CRLs, with coverage of genTime, for the signer and non-anchor intermediate. Missing, stale or unsupported evidence fails closed. OCSP is not an automatic alternate path. The spike's successful chain check does not establish that this added CRL behavior has been implemented or exercised. [CP/CPS section 1.3.4](https://www.digicert.com/content/dam/digicert/pdfs/legal/digicert-public-trust-cp-cps-v7-09.pdf#page=11)

Primary-source review confirmed the endpoint and timestamp policy, but did not establish applicable service permission or rate limits for arbitrary non-code-signing Research-Only fixture commitments. The CP/CPS recommends timestamping signed code, and the public endpoint documentation describes data-record timestamping without supplying a usage entitlement or quota. DigiCert's website terms expressly exclude product/service use. Neither a successful request nor the absence of an explicit restriction verifies suitability. Retain applicable terms or provider confirmation of permitted use, cost/account requirements and cadence/volume before marking #72 ready. Do not borrow Sectigo's request interval or infer a DigiCert quota. [Endpoint documentation](https://knowledge.digicert.com/general-information/rfc3161-compliant-time-stamp-authority-server), [CP/CPS section 6.8](https://www.digicert.com/content/dam/digicert/pdfs/legal/digicert-public-trust-cp-cps-v7-09.pdf#page=77), [website terms](https://www.digicert.com/security-terms)

F19's retained T10 evidence can represent all current F13 full-time, half-time and corner facts, but a preference grade does not guarantee those facts are present or compatible. The contract adds an exact later outcome-fact attachment only for required fact resolution or supplementation, with missing/conflicting counts unavailable and no invented values.

Historical result as of 2026-10-04: #72 remained OPEN / needs-triage on service-use and rate-limit suitability. That DigiCert-specific blocker was resolved by the Sigstore evaluation on 2026-10-05; see the linked current research note. F17's #70 blocker remains preserved.

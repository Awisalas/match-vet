# Offline Sigstore TSA verification evidence

This directory retains the temporary SHA-256 commitment, raw RFC 3161 query and reply, extracted token, TSA certificates, Sigstore TUF bootstrap/rotation metadata and the authenticated `trusted_root.json` target used for the 2026-10-05 feasibility check.

The OpenSSL timestamp verification is repeatable offline with the retained trust anchor and signed token time:

```sh
openssl ts -verify \
  -queryfile request.tsq \
  -in response.tsr \
  -CAfile tsa-root.pem \
  -attime 1791175821
```

Expected result: `Verification: OK`. The raw DER certificate is `tsa-root.der`; to recreate the PEM input:

```sh
openssl x509 -inform DER -in tsa-root.der -out tsa-root.pem
```

The query's message imprint matches `commitment.txt`, and its nonce is checked by the verification. The response token's signed `genTime` is 2026-10-05 04:50:21 UTC. The command uses that signed time to check certificate validity and makes no network request.

The TUF metadata files preserve the verified root v10 bootstrap, root rotation through v15 and timestamp/snapshot/targets versions 799/165/14. `trusted-root-verification.json` records the authenticated target's SHA-256 and length. The `tuf-js` 4.1.0 client verified the sequential root metadata and target hashes before the TSA root was used. Recheck expiry and trust updates before relying on this historical evidence; the captured chain is not a current trust freshness assertion.

`SHA256SUMS` covers the pinned bootstrap/target/request/token evidence files. Check it from this directory with:

```sh
sha256sum -c SHA256SUMS
```

`wrong-digest-verification.txt` and `malformed-verification.txt` preserve the expected negative results: the changed digest fails with an imprint mismatch, and the truncated reply fails ASN.1 parsing.

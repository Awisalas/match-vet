# Production trusted UTC isolated proof

Result: no researched source satisfies #75's unchanged actual-at-return upper
bound on this Termux/Android execution boundary. The default refuses. This record
does not approve hardware accuracy, source operator accuracy, or a production clock.

## Primary executable record

Prototype branch: `prototype/production-trusted-utc-20261007`.
Captured commit: `dc39cf9351954744a58ed0c9b8d11b05e1eecbc9`.
The branch is pushed; it is not merged into main.

- `src/matchvet/trusted_utc_prototype.py`: isolated gate and cryptographic experiments.
- `src/matchvet/trusted_utc_prototype.html`: standalone free-play actions and guided
  state walkthroughs. Open the file in a browser; no server or persistence.
- `.audit/production-trusted-utc/candidate-a.md` and `candidate-b.md`: independent
  complete clock and causal-witness design packages.
- `.audit/production-trusted-utc/grounding.md`: traced ownership and source locations.

From a checkout of that commit:

```sh
PYTHONPATH=src python src/matchvet/trusted_utc_prototype.py
PYTHONPATH=src python src/matchvet/trusted_utc_prototype.py --https
```

The first command is offline. The second makes only three diagnostic HTTPS HEAD
requests, with standard certificate/hostname verification. It does not query NTP,
Roughtime, or a TSA and acquires no fixture data. All SQLite/object files are
created under a TemporaryDirectory and removed; no configured store is opened.

## Evidence and limits

`proof.json` contains nine synthetic gate scenarios, the real default refusal,
synthetic Ed25519 verification, tamper and mismatched-request nonce rejection,
and diagnostic HTTPS outcomes.
The source digest inside that record matches the committed prototype source.
The synthetic public key, signed payload, and signature are retained so the
verification can be repeated independently. The private key is not retained.
An additional offline OpenSSL re-verification of those exact retained bytes passed.
These signatures authenticate fictional interval assertions, not actual UTC.
Adversarial review corrected the free-play causal lineage, replaced a nonce
randomness comparison with actual mismatched-request verification, unified the
refused confidence record, removed its dangling synthetic binding, and clarified that elapsed read error covers both
samples. The first prototype capture remains at `7c92b63` for the decision trail.

The experiment calls the existing private `_require_before()` on an empty isolated
Store. It proves the gate trusts the injected clock's assertion and rejects the
default/equality. Unsafe providers are intentionally injected to expose their
false guarantee. Their acceptance is not a repository bug, completed selection,
or live qualification. The recorded actual-return values are a synthetic oracle.

Counterexamples cover rolled-back wall time, several HTTPS estimates all behind,
delayed signed source intervals, suspend-excluding monotonic time, unqualified
BOOTTIME rate, and suspension after the final BOOTTIME sample. A forward bound
and equality conservatively refuse. The hypothetical exact elapsed case is a
synthetic premise, not a numerical Android margin.

`refused-confidence.json` demonstrates a versioned no-authority result with
source/observation/software provenance and unknown upper bound/error represented
as null. `environment.json` records Android API 36, Python/OpenSSL identity,
BOOTTIME availability, the exact source hash and retained-signature verification.
Resolution/availability does not establish oscillator accuracy.

`html-walkthrough.json` retains five runs of the HTML's pure reducer, including
source-before-commit and alternate-commit identity rejection. Node syntax
checking, Ruff, Python formatting and staged whitespace checking passed for the
prototype. No pytest/full suite or hardware suspend/accuracy test is claimed.

The final sample-to-return counterexample is a logical possibility under the
contract's arbitrary-suspension premise. The prototype illustrates it; repeated
fast executions cannot prove a worst-case latency bound. Device qualification
alone does not remove that gap. No production modules or schemas are changed.

## Tracking

Design/research/proof capture: main commit `55a3a1b`.
[Issue #79](https://github.com/Awisalas/match-vet/issues/79) is open with
`needs-triage`, for the timing-boundary prerequisite. It does not authorize a
production adapter or a changed clock contract. Live rebuild remains unstarted.

# Issue #81 protocol evidence

Scope: private `matchvet-causal-selection-v2` under ADR 0003 and the accepted
design. Successor admission and authenticated activation remain refusing in
production. Tests supply deterministic successor graphs at the private admission
seam and isolated approval state; retained wire fixtures exercise cryptography
separately. No #82 writer/schema work or #83/#84 integration is included.

## Implemented boundary

The original Store/PID/thread operation must confirm a fresh insertion into the
existing version-independent selection slot. The exact graph is validated and
synced through protected publication before commit. Only then may the operation
construct binding bytes, 256 bits of entropy and a positive nonce with 256 random
bits. Copying, pickling, construction, recursion, fork, thread transfer, exit and
close/reopen cannot acquire or restore authority. Concrete transport checks run
before connection and immediately before request dispatch. One attempt is consumed
before transport; the endpoint never redirects, retries or falls back.

The private verifier checks strict DER/RFC3161/CMS, granted status 0, policy,
algorithms, pinned signer/anchor, signer identifier, ESS binding and critical
timestamp-only EKU. Application nonce and SHA-256 imprint equality are mandatory
independently of OpenSSL. Retained TUF root v10, sequential rotations, threshold
signatures, metadata references/hashes/lengths, reviewed floors and exact
TrustedRoot authenticate provenance. Approved operator/key/policy association is
a separate trusted configuration premise. Signed genTime and Accuracy use exact
rational arithmetic and outward rounding; zero/missing/unsupported/>1-second
accuracy, unsupported UTC, day crossing and U >= common T refuse.

The dedicated protected receipt payload holds signed bounds; generic timestamps
are advisory. The exact receipt closes over selection, binding, query, response,
profile, approval, chain, TUF and software evidence. Authority is consumed before
the first evidence/receipt publication. A commit exception can only validate the
already indexed exact expected receipt. Other failures leave an occupied,
unqualified slot. Restart can inspect/replay an indexed receipt, never request,
retry, backfill or adopt orphan bytes. Known authenticated withdrawal refuses
present qualification while original historical inspection remains available.

Offline verification does not establish current revocation status. Operator
policy compliance, uncompromised authority and unsmeared UTC remain explicit
premises; the parser cannot detect hidden smear. Local causality assumes trusted
code/kernel, honest WAL/FULL/VFS/fsync/locking and one authoritative catalog
history. Transport/TLS/deadline failures may reduce availability and cannot grant
qualification.

## TDD and executed checks

Tests use isolated temporary stores, synthetic complete seven-scope Friday–Monday
graphs and retained wire bytes from the existing CB01 research bundle. No live
SQLite store, TSA/TUF request, fixture acquisition or full suite was used.

- `focused-final.txt`: 121 passing final #81 protocol and retained-wire tests.
- `v1-regressions.txt`: 68 tests in `test_matchweek_research.py` and
  `test_cb01_trust.py`, including the actual v1 graph adoption refusal.
- `manifest-regressions.txt`: 6 focused generic manifest regressions.
- `review-regressions.txt`: 14 intermediate review regressions, including
  both publication orders for shared raw TUF objects.
- `mypy-final.txt`, `ruff-final.txt`, `format-final.txt`, `diff-check.txt`:
  final affected-code checks.
- `compatibility-proof.py` / `compatibility-proof.txt`: executable baseline
  comparison against `base.txt` proving unchanged generic manifest code,
  CB01 code, v1 graph/manifest/admission/sealing and SQLite migrations.

Focused cases include uncertain selection commits on either side of commit,
actual competing processes, exact graph sync failures, invalid/copy/reconstruction
and callback authority, fork/thread/close/PID loss, nonce/imprint/profile attacks,
strict wire mutations, exact fractional interval arithmetic, equality/late U,
TUF rollback/rotation/target attacks, withdrawal, real process crashes before
request and after signing, receipt commits on either side of crash, orphan/lost
receipt refusal and exact indexed offline replay after T.

## Blast-radius proof

The safety fact is that only the original operation can advance the stable slots,
and every ambiguous/lost authority path terminates without another transport or
publication. This reaches skill evidence step 4: tests invoke the real Store,
ArtifactStore, owner transitions and private transport, including actual fork
crashes and two-process competition. Retained-wire tests invoke the real parser,
TUF authentication and OpenSSL verification. Real-stage integration and live
authority behavior remain outside #81 and are not claimed proven.

Compatibility reaches step 4 through real #75/v1 regressions plus the executable
baseline proof. Shared raw TUF objects preserve existing physical media types;
both CB01-first and causal-first storage orders pass. Generic manifest schema 1
and SQLite schema remain sufficient without migration.

## Interrogate verdict

Intent: implement only the settled private causal protocol, with strict retained
trust verification and terminal authority loss, preserving historical meanings.

Reviewers used the same scope and standards/spec rubric. Available-model
substitutes were GPT-6.1 Sol/max (A), GPT-5.6 Sol/max (B), GPT-6 Sol/xhigh (C)
and GPT-6 Astra/max (D). B supplied concrete findings before its final turn hit
the model usage limit; A, C and D completed. The lead validated all findings with
real code and chose the fixes; reviewers did not edit files.

Act on, all fixed:

- A/B: version registration compared advisory creation timestamps, refusing a
  later vacant slot. Compare canonical ManifestVersion identity instead.
- A: shared retained TUF digests had incompatible physical media types across
  causal and CB01 publication. Preserve existing raw-object media types.
- A/B/C: extreme supported UTC dates could overflow outward interval arithmetic.
  Convert overflow to a stable fail-closed WitnessError.
- B/D: duck-typed/subclass transport callers could emit unissued query bytes.
  Require concrete original authority and invoke trusted implementations directly.
- D: ownership lost during DNS/TLS could still dispatch. Recheck original owner
  immediately before sending; close/PID tests prove zero requests.
- B: advisory receipt timestamp callback could reenter acceptance and rewind the
  transition. Busy-guard computations and refuse overwriting another phase.
- A: closed HTTP responses could fail after valid body delivery, and slow header
  reads could extend the stated deadline. Test actual local socketpair responses
  and enforce the absolute deadline at each underlying response read.

There were no outstanding Consider/Dismissed findings. Known offline compromise,
operator timescale and local durability premises are Noted trust limits required
by the settled design. Independent agreement was strongest for constructed
transport authority and exact interval overflow. D rechecked both transport
findings in memory and confirmed zero emitted requests and no residual blocker.
A rechecked closing responses, slow headers, dispatch and callback guards; four
focused checks passed and no remaining acceptance blocker was found.

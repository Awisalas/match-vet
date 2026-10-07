# Production trusted UTC decision and confidence shape

This design does not approve a production provider. See
[ADR 0002](../adr/0002-production-trusted-utc.md) and the
[primary-source research](../research/production-trusted-utc-2026-10-07.md).
The default remains unavailable. Availability is secondary to correct refusal.

## Caller view

Current production usage remains:

```python
research = MatchweekResearchRepository(store)  # prospective time refuses
selected = research.replay_for_matchweek(season=season, matchweek_friday=friday)
```

Only after an independently accepted timing premise, a future deep provider
could keep the existing injection shape:

```python
# NOT IMPLEMENTED OR APPROVED.
clock = QualifiedIntervalClock.from_profile(approved_profile_bytes)
selected = MatchweekResearchRepository(store, clock=clock).seal_completed(f16_digest)
# F11–F16 receive the same repository-configured provider in their constructors.
```

Callers do not select servers, uncertainty numbers, retry counts, or elapsed
arithmetic. The provider owns source verification and qualification. Store owns
durability and private publication authority. MatchweekResearchRepository owns
the strict comparison, one winner, completion protocol dispatch, and exact replay.

## Contract and proof obligation

The unchanged contract is:

`selection durability <= commit return <= actual UTC at observe return <= u < T`.

The existing code requires aware UTC, nonempty source, `confidence="TRUSTED"`,
nondecreasing bounds in one repository lifetime, and strict `u < T`. It trusts the
configured provider's guarantee; it cannot infer accuracy from the confidence tag.

Let the last value-producing event fix finite `u`. Suspend the process immediately
after that event, before Python returns. No unchanged result byte observes the
suspension. With no maximum pause premise, actual return UTC can exceed any `u < T`.
No guessed finite safety margin or timeout makes this a bound. This counterexample
also applies to a final native/syscall sample. A sample-time or remotely signed
event bound must not be silently substituted for an actual-at-return bound.

## Conditional mechanism

Roughtime is the best researched anchor protocol: a fresh nonce, pinned public
roots, and signed source interval without initial X.509 wall-time bootstrap.
RFC 10049 is experimental; a service must be qualified for its exact wire version,
keys, UTC timescale, and operator accuracy commitment. A beta endpoint is not an
approved production profile. NTS or RFC3161 are alternative anchors only when
their exact source accuracy and certificate-bootstrap policies are established.

Suppose a source asserts actual processing UTC in `[L,U]`. Read BOOTTIME `b0`
before transmitting a fresh request and `b1` after receiving and verifying it.
Given separately evidenced positive minimum elapsed-counter rate `r`, absolute
error bounds `e0` and `e1` for the two counter readings, and return-delivery bound `d`:

`u = outward_round(U + (b1 - b0 + e0 + e1) / r + d)`.

The interval from request start overcounts time since the source event, so it
covers asymmetric delivery, verification, retries, and suspend before `b1`.
All arithmetic is exact integer/rational arithmetic with outward rounding.
The formula uses counter-seconds for `b0`, `b1`, `e0`, and `e1`, counter-seconds
per elapsed second for `r`, and elapsed seconds for `d`. Raw nanosecond readings
are converted exactly before arithmetic.
No production value for `r`, `e0`, `e1`, or `d` is supplied here. Android documentation
does not establish them; arbitrary suspension makes finite `d` unavailable.

Independent sources require an explicit honesty premise and projection to the
same observation boundary. Under at-least-one-honest-source trust, take the maximum
qualified upper endpoint. A minimum, median, or intersection is unsafe under that
premise. Under all-sources-honest trust, an intersection can be conservative.
Refuse contradictory aligned intervals or violated chained causal ordering.
Raw intervals for different server events need not overlap. A numerical vote
cannot turn estimated or unbounded source errors into guaranteed intervals.

## Clock-confidence v1 record

This is a proposed artifact payload, distinct from completion protocol versioning.
`record_kind="utc_clock_confidence"` and schema 1 identify its shape. The prototype
bundle has a distinct `record_kind="utc_clock_proof_bundle"`. The retained refused
example is the exact `clock_confidence` object extracted from that bundle, not a
second vocabulary. Nothing here makes caller-built bytes trusted. A future artifact
uses canonical JSON; the diagnostic record is pretty-printed for inspection.

| Field group | Required meaning |
| --- | --- |
| Identity | Schema 1, observation UUID, scope `UTC_AT_OBSERVE_RETURN`, UTC timescale; source-policy, verifier/software, dependency/trust-profile content digests and exact protocol versions |
| Result | Trust state `TRUSTED_BOUND`, `ESTIMATE_ONLY`, or `REFUSED`; stable failure code(s); observed estimate and its distinct reference instant/trust state; conservative lower/upper bound or null |
| Uncertainty | Hard-bound or estimated/unknown classification; source interval, read error, elapsed/rate error, return delivery, representation rounding, total bound and cited qualification evidence |
| Sources | Required source/operator identities and honesty policy; pinned roots, chain/delegation policy, key fingerprints, signed time/error fields and units, supported leap/smear interpretation |
| Observations | Untrusted wall estimates explicitly labeled; request-start, receipt, verification and final counter samples; boot/process identity; scope of each observation |
| Binding | Exact raw request/response bytes or protected artifact refs and hashes, nonce/imprint, signature verification outcome, exact qualification profile and freshness check |
| Retention | No operational authority on reconstructed evidence; selection digest bound by its protected completion receipt, not asserted by a free-standing clock document |

All field groups are present in a refused record; unavailable identity, binding,
observation and numeric evidence is explicitly null or unknown. Such nulls prohibit
trust. A trusted result has all required hard-bound terms and exact evidence.
Estimated-only inputs cannot occupy trusted fields. The proof's HTTPS observations
retain metadata only; raw-wire binding/freshness is null or not established.
If two-sided `[L,u]` is justified at the result's reference instant, a declared
estimate `m` has conservative error `max(abs(m-L), abs(u-m))`. Otherwise record
only the supported one-sided bound and mark two-sided uncertainty unknown.
Untrusted wall-time diagnostics never establish observation ordering or freshness.

The rejected causal-witness shape uses a different scope,
`COMMITTED_EVENT_UPPER_BOUND`. Its metadata and signed bytes may describe a prior
event. They must never use `TRUSTED_BOUND` for `UTC_AT_OBSERVE_RETURN`.

## Type and ownership sketch

Signatures only. No production files or modules are introduced.

```python
@dataclass(frozen=True)
class ProvenancedUTCUpperBound(TrustedUTCUpperBound):
    # Canonical domain evidence, not public transport objects.
    confidence_document: bytes

class QualifiedIntervalClock:
    @classmethod
    def from_profile(cls, approved_profile_bytes: bytes) -> TrustedUTCClock:
        # Validate immutable source/device/return guarantees before construction.
        raise NotImplementedError

    def observe(self) -> ProvenancedUTCUpperBound:
        # Fresh per-operation nonce; verify; age using qualified terms;
        # return a true bound with exact evidence, or raise with refused record.
        raise NotImplementedError
```

This future subtype preserves existing deterministic injection. One public
`observe()` owns the complex trust decisions. No mutable shared last-observation
cache supplies receipt evidence. The qualifying call's exact returned document
must travel with that call into its private receipt binding. The existing clock
types stay in their current module unless implementation supplies a real reason
to move them. No pass-through provider registry or public phase coordinator.

## Exact failure behaviour

Current production qualification refuses regardless of network availability,
because return-delivery and local rate premises are absent. These future checks
cannot be bypassed by a successful network reply:

- Refuse missing qualification, unsupported versions/algorithms/timescales,
  host/runtime mismatch, unknown error/rate/delivery terms, overflow, and estimated
  confidence. Equality or later `u` refuses through the repository's existing gate.
- Verify each response against its fresh unpredictable nonce and pinned approved
  profile. Refuse bad signatures, wrong imprint, unknown accuracy/policy, expired
  or revoked trust under the defined bootstrap policy, and missing required sources.
- Refuse clock/boot identity changes and counter rollback. Do not refresh an anchor
  from wall time, restored memory, disk evidence, or a later process. An old signed
  response is historical evidence only. Forward jumps can conservatively refuse.
- With no qualified aging contract, offline prospective work refuses. A future
  qualified offline anchor would need explicit validity limits and live same-boot,
  same-process ownership; none is approved here. Exact selected replay stays offline.
- Retry only within an explicit profile's finite count/backoff/load policy, using
  fresh request identity. Those limits manage availability; they do not prove an
  elapsed bound. All retry/verification delay must be covered by qualified aging.
- VPN/proxy delay or blocked UDP/TLS reduces availability. Keep certificate and
  hostname checks for TLS paths. Default wall-clock certificate validation is not
  secure UTC bootstrap; never disable it to claim clock confidence. Pinned signed
  roots avoid that bootstrap dependency but still require operator accuracy trust.
- Loss of confidence after selection commit keeps the occupied slot permanently
  unqualified. Restart cannot publish a missing receipt or adopt orphan evidence.

## Android and trust requirements

The observed host is Android API 36 with Python 3.14.6 and CLOCK_BOOTTIME available.
These are capability observations, not accuracy qualification. A general Termux
application UID cannot assume privileged Android DUMP/time-service access.
Play services requires an Android app integration and exposes estimates whose
actual error can be larger. A native Android bridge does not remove that limit.

A future profile would need the exact qualified kernel/runtime/device scope,
rate/read guarantees covering temperature, sleep and frequency adjustments,
and the currently unavailable return-delivery guarantee. Trust also includes an
honest local kernel/process/storage and authoritative catalog history. Local
privileged instrumentation or restored process memory can forge local ordering;
remote signatures do not independently attest SQLite completion. Source accuracy,
key approval/rollover/revocation, and authenticated profile distribution must be
explicit. No mechanism here claims protection against a hostile filesystem owner.

## Persistence and #75 impact

No schema migration or live artifact is needed for this task. Proof and confidence
examples are isolated files; prototype code is retained on a separate branch.

If a provider eventually qualifies, retain confidence, raw signed bytes, profiles
and qualification evidence as existing protected generic artifacts. Current
completion v1 has exactly one selection reference and drops source/confidence.
Appending data to it or placing a digest in `source` would not bind provenance.

A distinct completion v2 domain reader would bind the exact selection plus its
confidence document and complete evidence closure. Its one live operation must
bind that exact evidence digest set before consuming its one receipt attempt.
Do not add a broad allowance for arbitrary receipt references. Preserve v1 bytes,
v1 replay, generic manifest schema 1, and the unchanged stable role slots. V2 never
upgrades an occupied v1 slot or permits a second Matchweek winner. Clock trust
cannot be reconstructed from a confidence artifact after restart.

That is a potential reader/private-binding adjustment for provenance. No timing
contract adjustment is accepted. A causal witness could become primary only via
a separately authorized timing design covering all writer gates; this task rejects
using it to bypass the unchanged clock contract.

## Next work

There is no implementation-ready provider ticket.
[Issue #79](https://github.com/Awisalas/match-vet/issues/79) tracks one prerequisite timing
decision: supply a genuine compatible execution guarantee, or explicitly review
a different observation/event contract while preserving every cutoff, writer,
receipt, restart and single-selection acceptance condition. Continue refusing
until that decision is authorized and proved. #70 numerical fitting and live
Matchweek acquisition/rebuild remain separate work.

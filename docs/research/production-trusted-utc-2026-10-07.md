# Production trusted UTC upper bounds on Termux/Android

Research date: 2026-10-07. Primary documentation and source inspection only.
No live Matchweek data, operational SQLite stores, or NTP/Roughtime/TSA requests
were used. The isolated prototype made diagnostic HTTPS Date HEAD probes to
three origins; their estimates established no UTC bound. This note distinguishes
published guarantees, provider assertions,
and deductions for MatchVet. It does not establish a production device's clock
error by observing a few successful network queries.

## The obligation

The existing [`TrustedUTCClock`](../../src/matchvet/matchweek_research.py)
requires its result to bound actual UTC when `observe()` returns. The selection
protocol needs:

`selection commit completed <= actual UTC at observe return <= u < T`.

An authentic timestamp generated remotely after the commit can instead prove
`commit completed <= remote timestamp event <= timestamp + error`.
That is a useful causal proof, but its last event is earlier than the client
return. It is a different contract. Network receipt, verification, scheduling,
and device suspension can take arbitrarily long without changing signed bytes.
This distinction follows from event ordering; it is not an RFC feature.

## Candidate findings

| Candidate | Documented useful property | Gap for the current contract |
| --- | --- | --- |
| Android wall UTC and automatic time | Convenient system-wide UTC estimate | User changes, uncertain synchronization, and no public hard error guarantee |
| Android network UTC / Play services Time API | Values independent of user wall-clock changes; estimated uncertainty | Android disclaims accuracy/security; Play services explicitly permits actual errors larger than estimates |
| NTP with authenticated NTS | Authenticated server responses and synchronization metadata | Server accuracy, asymmetry, local rate, certificate bootstrap, and observation aging remain assumptions |
| Multiple HTTPS Date headers | TLS authenticates the connection and HTTP defines generation-date metadata | No normative UTC error bound; caches/intermediaries; no application nonce binding |
| RFC3161 TSA | Signed imprint, nonce, policy, and token-generation accuracy | Bounds token generation, not receipt/current UTC; generic service software can continue issuing despite drift |
| Roughtime | Signed nonce-bound interval, pinned roots, no initial X.509 wall-time requirement | Server honesty plus an elapsed upper bound through client return are still necessary |
| BOOTTIME anchor | Suspend-inclusive elapsed clock unaffected by wall-time steps | No universal Android oscillator error bound; reboot and final delivery gaps need handling |
| Authenticated interval + qualified elapsed clock | Can conservatively include transit, verification, and suspension | Requires evidence for this device/platform, not a guessed safety allowance |

### Android UTC and uncertainty APIs

`System.currentTimeMillis()` is adjustable wall time. Android's public
`SystemClock.currentNetworkTimeClock()` starts at API 33, avoids user adjustment,
and can throw when no network time is available. Its documentation explicitly
warns that synchronization may be insecure, that it is unsuitable for security
purposes, and that accuracy is not guaranteed. Success or enabled automatic time
therefore cannot be promoted to trusted confidence. [`SystemClock` reference](https://developer.android.com/reference/android/os/SystemClock).

AOSP's network origin uses SNTP over UDP, with a default single-query refresh
approximately daily. Mobile asymmetric delay and subsequent elapsed-clock
inaccuracy affect it; vendors can change synchronization configuration.
The platform's theoretical delay example does not cover server UTC error,
later clock drift, or a hostile source. Its diagnostic shell output is unstable
between releases. [AOSP network time detection](https://source.android.com/docs/core/connect/time/network-time-detection).

Google Play services `TrustedTimeClient` requires an Android application
integration and gives callers `TimeSignal` data rather than exposing a Python
Termux command. The setup documents minimum SDK 21. [Play services Time API setup](https://developers.google.com/location-context/time).
The more specific `TimeSignal` API says acquisition error quantities are
estimates; actual error can be larger. Aging introduces additional local ticker
error. This disqualifies `estimate + estimatedError` as a hard upper bound.
[`TimeSignal` reference](https://developers.google.com/android/reference/com/google/android/gms/time/trustedtime/TimeSignal).

Ordinary Termux code cannot assume access to privileged platform diagnostics:
Android documents `DUMP` as unavailable for third-party applications. An ADB
shell's access is not evidence that an app UID can inspect the same metadata.
[Android permission reference](https://developer.android.com/reference/android/Manifest.permission#DUMP).
Termux:API is an Android add-on that exposes implemented device functions to
command-line programs; its existence does not supply a clock confidence
contract. [Termux:API repository](https://github.com/termux/termux-api).

### NTP, NTS, and trusted network time

NTP describes root delay, root dispersion, and synchronization distance as its
error model. It also states that frequency tolerance is an assumption about
the clock after synchronization and while sources are unreachable. The RFC's
default frequency tolerance is not a measurement or guarantee for this phone.
[RFC 5905, sections 4, 7, and 9](https://datatracker.ietf.org/doc/html/rfc5905).

NTS authenticates NTP client/server packets using TLS key establishment and
AEAD. It does not make an authenticated server's clock correct or eliminate
adversarial delay. Initial NTS-KE certificate validation depends on time; the
RFC discusses the bootstrap problem explicitly and does not claim a perfect
solution. Strict validation can refuse until an independent time interval is
known. Do not disable certificate verification as a route to trusted confidence.
[RFC 8915, sections 3, 8.5, and 8.6](https://www.rfc-editor.org/rfc/rfc8915.html).

Chrony publishes a clock-accuracy formula conditional on the stratum-1 clock
being correct. [`chronyc` tracking documentation](https://chrony-project.org/doc/4.7/chronyc.html#tracking).
Its `maxclockerror` parameter is a maximum **assumed** frequency error;
`maxupdateskew` limits unreliable estimates. Neither a default parameter nor
a short sample history establishes a hardware worst-case bound on Android.
[`chrony.conf` documentation](https://chrony-project.org/doc/4.7/chrony.conf.html#maxclockerror).
Installing a time daemon and observing synchronization is insufficient evidence
for the specific application contract.

Google Public NTP gives no availability or accuracy commitment, does not
support NTS, and recommends avoiding mixed smeared and unsmeared sources.
[Google Public NTP FAQ](https://developers.google.com/time/faq).
Its published smear means returned time can differ from UTC during a leap
event; any chosen provider profile must identify its timescale and conversion
or refuse when semantics are ambiguous. [Google leap smear](https://developers.google.com/time/smear).

### HTTPS Date from independent servers

HTTP Date represents message origination. The sender should use its best
available approximation, but may construct the value at any point in
origination. Intermediaries may insert or replace Date in specified cases.
The protocol provides no finite UTC error guarantee. [RFC 9110, section 6.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-6.6.1).

Inference: querying several independent HTTPS origins can detect gross
disagreement; it cannot turn their unbounded errors into a guaranteed interval.
A median or maximum Date still can be behind true UTC. TLS trust proves peer
identity, not clock accuracy. A nonce in a URL and cache-control directives do
not make Date a signed assertion about that nonce. VPNs, proxies, caches, and
delivery delay require analysis beyond simple RTT correction. Reject this as
qualification authority; it is at most diagnostic input.

### RFC3161 timestamps

RFC3161 provides signed message imprints, policy IDs, and optional accuracy;
the server must reproduce a requested nonce. It explicitly defines
`genTime + accuracy` as an upper limit on token creation time. Missing accuracy
can be supplied by an identified policy; it must not be interpreted as zero.
[RFC 3161, section 2.4.2](https://datatracker.ietf.org/doc/html/rfc3161#section-2.4.2).

Inference: generate a fresh nonce only after successful commit and bind the
exact selection challenge; a validated token then bounds an event after that
commit. It can arrive after T while retaining a pre-T generation bound. This
cannot satisfy `observe()`'s current-at-return requirement. Reusing the CB01
software identity does not silently grant clock-provider authority.

Sigstore's authority repository publishes a baseline policy requiring
one-second-or-better accuracy, but a policy is an operator claim rather than
a local observation. [Sigstore TSA policy](https://github.com/sigstore/timestamp-authority/blob/main/docs/tsa-policy.md).
Its service implementation documentation says drift monitoring increments a
metric and does not itself stop timestamp issuance; the operator must provide
controls. A signed token alone cannot prove those controls are active.
[Sigstore authority time monitoring](https://github.com/sigstore/timestamp-authority#time-accuracy-and-monitoring).

### Roughtime and a safer hybrid

RFC 10049 is experimental. It binds a fresh nonce to a signed response and
requires the server's true processing time to fall inside `MIDP ± RADI`.
Validity authenticates the server's guarantee, not objective clock correctness.
Long-term public keys are its roots of trust. Section 6 expressly assumes a
local frequency-error bound when aging time intervals. This is the strongest
researched protocol fit for an authenticated UTC interval, but it does not
remove the elapsed-time premise. [RFC 10049, sections 3, 5.2.5, 5.4, and 6](https://datatracker.ietf.org/doc/rfc10049/).

Cloudflare publishes a UDP endpoint and Ed25519 root; its service remains beta
and keys may change. Key updates must be authenticated repository trust
changes, rather than automatically trusting DNS or current web content.
[Cloudflare Roughtime endpoint](https://developers.cloudflare.com/time-services/roughtime/usage/).
Cloudflare documents delegation and response verification, and suggests
multiple sources. Its convenience median/clock-offset recipe is an estimate,
not MatchVet's conservative bound algorithm. Existing implementations and
server profiles must identify the exact wire version; do not assume the
current service implements the newest RFC because its documentation says
Roughtime. [Cloudflare client recipes](https://developers.cloudflare.com/time-services/roughtime/recipes/).

## Elapsed time and return-time proof

Linux `CLOCK_BOOTTIME` is monotonic, includes suspend, and avoids discontinuities
from wall-time changes. `CLOCK_MONOTONIC` excludes suspend and can be affected
by incremental frequency adjustments; neither API documentation supplies a
phone-specific worst-case rate guarantee. [Linux clock_gettime manual](https://man7.org/linux/man-pages/man2/clock_gettime.2.html).
Android `elapsedRealtime` similarly includes deep sleep. API availability and
resolution do not establish accuracy. [Android SystemClock reference](https://developer.android.com/reference/android/os/SystemClock).

The following is a mathematical deduction, conditional on explicit trusted
device evidence. Let a signed source assert UTC in `[L, U]` during request
processing. Read BOOTTIME `b0` before transmitting and `b1` at the eventual
observation. If the device contract guarantees
`elapsed_real <= (b1 - b0 + read_error) / minimum_rate`, with positive
`minimum_rate`, then `U + elapsed_upper` covers the whole network exchange,
verification, retry delay, and suspend. Add outward representation rounding
and a separately justified bound through the actual return boundary. No
symmetric-delay assumption is necessary. `read_error`, `minimum_rate`, and any
return-boundary allowance cannot be invented constants. Here `read_error` is the
aggregate differential error of both counter samples, not one sample's error.

The final sample-to-return interval matters. Python can be descheduled after
its final clock read. Returning the value of that read with a fixed guessed
allowance therefore does not bound actual UTC at function return. A timeout
cannot repair a completed operation retroactively. A qualified native or
platform primitive must explain its linearization semantics and bound the
delivery gap, or the contract must explicitly change. An event-time bound and
a return-time bound must not share a confidence tag.

There is no discovered primary-source universal Android/Termux rate or delivery
guarantee adequate for that step. Empirical trials may disprove an assumption
but cannot prove a worst case across temperature, sleep states, kernel
adjustments, and arbitrary scheduling pauses. This is the remaining platform
qualification gap, not a proposal to insert a generic safety margin.

AWS ClockBound is a contrasting qualified-host option: AWS documents clock
error-bound support for EC2 Linux, including Nitro PTP hardware error supplied
through ENA. That is not a guarantee for Android hardware and adds a new
execution/deployment boundary if MatchVet selection moves there.
[AWS ClockBound and PTP error](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/compare-timestamps-with-clockbound.html).

## Failure and operational implications

These are recommended policies derived from the obligation, not guarantees
promised by the sources:

- Refuse absent, unknown, estimated-only, malformed, nonfinite, unauthenticated,
  or unsupported bounds. Refuse `u >= T`, including equality.
- Wall time can be retained for diagnostics; rollback cannot lower an accepted
  bound or refresh an anchor. A forward jump may cause conservative refusal.
- For multiple sources, document the honesty threshold. An interval
  intersection is safe only when every contributing interval is trusted and
  conservatively projected to the same observation boundary.
  Under an at-least-one-honest-source premise, the maximum upper endpoint is
  conservative once those endpoints cover the same return instant; a minimum
  or median is not. Refuse incompatible aligned intervals or violated causal
  ordering rather than resolving disagreement by an undocumented vote. Raw
  intervals from different server processing times need not overlap.
- With no qualified elapsed contract, offline prospective qualification
  refuses. Retained immutable selections may replay offline. With such a
  contract, any offline aging must obey its validity limits and boot identity.
- Reboot, process restart, BOOTTIME rollback, unknown kernel behavior, or
  absent qualification invalidates an operational anchor. A stored token is
  historical evidence and cannot authorize a new observation after restart.
- Network failures, missing required sources, invalid signatures, stale
  nonces, and unsupported versions refuse. Bounded retry counts and backoff
  limit load; successful retries need fresh request identity and their entire
  elapsed interval. Delays and VPN/proxy blockage can reduce availability.
- TLS-based mechanisms retain hostname/chain validation and an explicit
  certificate-time bootstrap policy. Pinning authenticated protocol roots can
  avoid reliance on untrusted device wall time; it does not establish server
  honesty or guard against compromised pinned keys.
- The honest local process/kernel/storage premise remains necessary. Hostile
  root access, instrumentation, code replacement, or restored process memory
  can falsify local event ordering. Remote signatures do not attest to local
  SQLite durability.

## Provenance and decision boundary

A versioned immutable confidence artifact should identify the observation
estimate, conservative upper bound, error terms, source intervals, request
and response hashes, boot/process identity, elapsed samples, key/trust profile,
timescale, software/protocol version, trust state, and refusal reason. Record
unknown error as unknown; do not put zero in its place. Protect original
protocol bytes and the exact trust profile so replay can explain a decision.
Use existing artifact content and references where the protected receipt can
bind them; a database migration is not justified by time research alone.

Recommendation: retain the current production refusal. Select authenticated
interval plus explicitly qualified suspend-inclusive elapsed time as the
conditional architecture candidate. No reviewed mechanism yet proves the
unchanged `observe()` return-time contract on an unspecified Android host.
The smallest next ticket should establish the device qualification and return
semantics, or explicitly propose a distinct causal-completion protocol for
review. It must not implement a provider that labels an estimate as trusted.

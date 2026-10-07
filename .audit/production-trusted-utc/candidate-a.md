# Candidate A: qualified signed interval clock

Candidate status: reject production construction on the current Termux and Android
evidence. A signed UTC interval plus a qualified suspend-inclusive elapsed clock is the
best protocol shape found. It still cannot satisfy the existing return-time contract
when the process may pause for an unbounded time after its final elapsed-clock read.
The default refusing clock must remain in production.

## Problem

`TrustedUTCClock.observe()` must return a finite aware UTC value `u` such that `u` is at
least actual UTC when `observe()` returns. This guarantee includes measurement error,
wall-clock rollback, device suspension, and process suspension. The repository then
requires `u < T`. Android and Termux expose useful estimates and a suspend-inclusive
elapsed counter, but the reviewed platform contracts provide neither a device rate
bound nor a bound from the last elapsed read through the Python return. Remote
authentication proves what a named source said. It does not prove that the source was
correct or keep a received timestamp current while the client is suspended.

The [isolated proof](./proof.json) supports rejection only. Its synthetic signed
interval verifies, its default provider refuses, equality at the cutoff refuses, and a
pause after the final BOOTTIME sample makes the returned value stale. The live HTTPS
diagnostic received two ordinary `Date` values and one HTTP 403 response. All three
remain unqualified because HTTP gives no normative accuracy bound. BOOTTIME was
available on the test host, but availability proves neither a minimum rate nor the
last-sample-to-return bound. None of these results approves a production premise.

## Usage (caller's view)

No production caller can construct this clock today. A future qualified deployment
would have one setup choice: the exact release-approved qualification manifest. The
caller would not choose time sources, error allowances, retry rules, or combination
math.

```python
from pathlib import Path

from matchvet.termux_trusted_utc import (
	QualificationManifestRef,
	open_termux_trusted_utc,
)

clock = open_termux_trusted_utc(
	QualificationManifestRef(
		path=Path(config.trusted_utc_qualification_manifest),
		expected_sha256=config.trusted_utc_qualification_sha256,
	)
)
```

`open_termux_trusted_utc()` must raise `TrustedUTCUnavailable` before any repository
work when a required bound is absent, estimated, out of scope for the current host, or
unknown. The current target reaches `RETURN_BOUND_UNQUALIFIED`.

Existing repository callers keep their present shape:

```python
research = MatchweekResearchRepository(store, clock=clock)
selected = research.seal_completed(f16_manifest_digest)
```

F11 through F16 receive the same instance through their existing constructors:

```python
evidence = F11EvidenceRepository(store, clock=clock).build_or_replay_for_freeze(
	freeze_id,
	policy_digest,
)

result = F16MatchweekProcessor(store, clock=clock).process_phase(
	context,
	freeze_id=freeze_id,
	cutoff_policy_digest=policy_digest,
	cutoff_ids=cutoff_ids,
	profile_digest=profile_digest,
	policy=policy,
)
```

A refusal propagates through the existing prospective gate. There is no fallback to
system UTC, Android network time, an estimated uncertainty, HTTP `Date`, or a retained
anchor from another process.

## Shape

### Public types and signatures

The existing clock protocol remains the repository boundary. The richer result is a
subtype, so current deterministic test clocks and the three-field base result keep
their existing call shape. No production provider exists until every qualification
premise is met.

```python
# src/matchvet/trusted_utc.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class TrustedUTCUpperBound:
	upper_bound_utc: datetime
	source: str
	confidence: str


class TrustedUTCClock(Protocol):
	def observe(self) -> TrustedUTCUpperBound:
		"""Bound actual UTC at this method's return or raise."""
		...


class TrustedUTCUnavailable(RuntimeError):
	code: str
```

`matchvet.matchweek_research` can re-export `TrustedUTCClock` and
`TrustedUTCUpperBound` during a later move, so F11 through F16 need no coordinated
import change. The production factory returns only the protocol. Callers cannot reach
transport or clock-arithmetic options. This is a deep interface: two operations hide
nonce creation, wire parsing, signature checks, source policy, elapsed aging, retry,
host binding, boot checks, and provenance construction.

The provider-private domain types make every accepted premise named and traceable.
Wire objects stay behind the provider boundary.

```python
# src/matchvet/termux_trusted_utc.py

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from matchvet.trusted_utc import TrustedUTCClock, TrustedUTCUpperBound


@dataclass(frozen=True)
class UTCInterval:
	lower_utc: datetime
	upper_utc: datetime
	timescale: Literal["UTC"]
	protocol: Literal["ROUGHTIME_RFC10049", "RFC3161", "NTS_NTP"]
	source_profile_id: str
	request_sha256: str
	response_sha256: str


@dataclass(frozen=True)
class QualifiedTerm:
	name: Literal[
		"elapsed_read_error",
		"minimum_elapsed_rate",
		"return_delivery_error",
		"representation_rounding",
	]
	value_numerator: int | None
	value_denominator: int | None
	state: Literal["QUALIFIED", "UNKNOWN"]
	evidence_digest: str


@dataclass(frozen=True)
class ElapsedTrace:
	clock_id: Literal["CLOCK_BOOTTIME"]
	boot_identity: str
	request_start_ticks_ns: int
	final_ticks_ns: int
	minimum_rate_numerator: int
	minimum_rate_denominator: int
	read_error_upper_ns: int
	aged_elapsed_upper_ns: int
	return_delivery_upper_ns: int
	qualification_digest: str


@dataclass(frozen=True)
class EvidenceBlob:
	media_type: str
	sha256: str
	content: bytes


@dataclass(frozen=True)
class TrustedUTCProvenance:
	contract_version: Literal[1]
	outcome: Literal["TRUSTED_BOUND"]
	estimate_utc: datetime | None
	upper_bound_utc: datetime
	timescale: Literal["UTC"]
	source_policy_id: str
	source_policy_digest: str
	source_intervals: tuple[UTCInterval, ...]
	elapsed: ElapsedTrace
	error_terms: tuple[QualifiedTerm, ...]
	process_identity: str
	software_version: str
	qualification_digest: str
	blobs: tuple[EvidenceBlob, ...]


@dataclass(frozen=True)
class ProvenancedTrustedUTCUpperBound(TrustedUTCUpperBound):
	provenance: TrustedUTCProvenance


@dataclass(frozen=True)
class QualificationManifestRef:
	path: Path
	expected_sha256: str


class _TermuxTrustedUTCClock:
	def observe(self) -> ProvenancedTrustedUTCUpperBound:
		raise NotImplementedError


def open_termux_trusted_utc(
	qualification: QualificationManifestRef,
) -> TrustedUTCClock:
	"""Open only when the approved manifest covers this exact host and runtime."""
	raise NotImplementedError
```

The production result fixes `source` to the approved source-policy identity and fixes
`confidence` to `"TRUSTED"`. Callers cannot supply either value.

An unknown numeric term has `state="UNKNOWN"` and null numeric fields in its canonical
artifact. Zero never substitutes for missing evidence. An accepted observation
contains only qualified required terms. The parser rejects floats, nonfinite values,
negative errors, nonpositive rates, unsupported fields, unsupported protocol versions,
and digest mismatches at the input boundary, per boundary-discipline.

The source parser converts protocol precision to the current aware UTC `datetime` only
after checking the profile's timescale rule. It rounds a lower endpoint down and an
upper endpoint up. It refuses leap-second or smear semantics that the profile cannot
convert conservatively. The provenance artifact retains the source precision and every
outward rounding term.

### Bound computation

For one successful attempt:

1. Read `CLOCK_BOOTTIME` as `b0` before creating and transmitting the fresh request.
2. Verify that the nonce-bound signed source event has UTC in `[L, U]`.
3. Read `CLOCK_BOOTTIME` as `b1` after response receipt and verification.
4. Use only a qualified positive minimum counter rate `r_min` and qualified read error
   `e_read`.
5. Add a separately qualified bound `e_return` through the actual Python method return.
6. Round the UTC result upward by the qualified representation term `e_repr`.

The conditional formula is:

```text
elapsed_upper = ((b1 - b0) + e_read) / r_min
u = round_up_utc(U + elapsed_upper + e_return + e_repr)
```

The fresh nonce places the signed source event after `b0`. Aging from `b0` is therefore
conservative. Network delay, verification time, retries within that attempt, ordinary
scheduling, and suspension before `b1` are inside `elapsed_upper`. No symmetric-network
delay assumption enters the formula.

Multiple source intervals must first be aged to the same final elapsed sample. Under a
policy that trusts every source, the provider may use the smallest aged upper endpoint
after it verifies compatible intervals. Under an explicit at-least-one-honest policy,
only the largest aged upper endpoint is conservative. A minimum, a median, majority
voting, and an intersection are invalid under that weaker premise. The profile fixes
one policy. The caller cannot select it at runtime.

### The return boundary makes the current candidate impossible

Let `e` be the last event at which the immutable returned `datetime` can change. Every
ordinary Python or native implementation has such an event before the Python method
returns. Let its finite value be `u`. The scheduler may suspend the process after `e`
and before the return for any duration `p`. Choose `p` long enough that actual UTC at
return is greater than `u`. The method then violates its contract.

Another elapsed read only moves `e`; it leaves the same pause after the new read. A
timeout cannot revoke a value after the operation has completed. A native extension
still has a gap between its last value update and the Python return. A dynamic result
does not fit the existing frozen `datetime` result, and reading it would create another
last-read gap. `datetime.max` cannot pass the repository's near-term `u < T` check.

Under arbitrary suspension, no finite `e_return` exists. The formula therefore has an
infinite term and cannot produce a finite trusted result. This rejection does not
depend on Roughtime, the network, source honesty, oscillator quality, or observed test
performance.

The reviewed evidence also leaves `r_min` and `e_read` unqualified for a general Android
device. `CLOCK_BOOTTIME` includes suspend and resists wall-clock steps, but those useful
properties do not supply a minimum rate or read-error guarantee. Even a future rate
qualification would leave the return proof above unresolved.

### Source comparison

The guarantees and gaps in this table come from the
[primary-source research](../../docs/research/production-trusted-utc-2026-10-07.md).

| Candidate | Evidence it can supply | Rejection premise for the current contract | Conditional role |
| --- | --- | --- | --- |
| Android system UTC, network UTC, or Play services uncertainty | A local estimate that is independent of some user wall-clock changes | Android disclaims a hard security or accuracy guarantee, and Play services permits actual error beyond its estimate | Diagnostics only |
| NTP with NTS | Authentication of NTS-KE and NTP packets, plus NTP synchronization metadata | NTS does not prove server UTC correctness, network symmetry, local counter rate, or return delivery. Certificate validation also needs an explicit bootstrap policy | Eligible only if an exact service profile adds a trusted finite UTC-error claim and bootstrap evidence |
| HTTPS `Date` | TLS peer authentication and message-origination metadata | HTTP defines no finite UTC error, intermediaries can affect the field, and the value is not signed against the application nonce | Diagnostics only |
| RFC3161 | A signed nonce and imprint with `genTime`; declared accuracy gives an upper token-generation bound | The token bounds an earlier server event. Missing accuracy is not zero, operator controls remain a trust premise, and receipt delay does not satisfy actual-at-return | Conditional interval anchor when an exact policy, accuracy, chain, revocation, and bootstrap profile is approved |
| Roughtime | A signed fresh-nonce interval `[MIDP - RADI, MIDP + RADI]` under a pinned root | The interval trusts server honesty and still needs qualified elapsed aging through return. The reviewed public service is beta and its exact wire version and key lifecycle must be pinned | Preferred conditional interval anchor |
| Signed interval plus `CLOCK_BOOTTIME` | A rollback-resistant upper bound aged across network work, verification, scheduling, and device sleep through the final sample | Android supplies no universal rate bound, and arbitrary suspension after the final sample makes the return term unbounded | Best conditional shape, currently rejected |
| Several signed sources | Fault detection and a bound under a stated honesty threshold | A median or minimum silently assumes more honest sources than an at-least-one policy grants | Optional profile-fixed extension after the single-source proof works |

Roughtime is the cleanest anchor because it signs a nonce-bound interval and can use a
pinned long-term root without relying on the device wall clock for initial X.509
validation. RFC3161 is the best alternate anchor when its accuracy and PKI policy are
complete. Its causal postcommit use remains valuable for another protocol, but that
event-time proof must not carry the `TRUSTED` tag for this clock contract.

### Precise refusal premises

The factory or `observe()` raises a stable refusal when any required premise fails:

| Code | Missing or false premise |
| --- | --- |
| `QUALIFICATION_MISSING` | No exact release-approved qualification manifest is pinned by digest. |
| `QUALIFICATION_UNSUPPORTED` | The manifest version, algorithm, authority, validity scope, or timescale rule is unsupported. |
| `HOST_MISMATCH` | Android build, kernel, runtime, clock implementation, or other declared host binding differs from the qualified scope. |
| `BOOT_IDENTITY_CHANGED` | The boot identity changes, rolls back, or cannot be established during the observation. |
| `SOURCE_BOUND_UNQUALIFIED` | The source has no finite trusted UTC interval under the exact source profile. |
| `SOURCE_AUTHENTICATION_FAILED` | Signature, nonce, imprint, chain, policy, key, revocation, or raw-byte verification fails. |
| `SOURCE_TIMESCALE_UNSUPPORTED` | UTC, smear, or leap behavior cannot be converted with a conservative bound. |
| `SOURCE_POLICY_UNSATISFIED` | Required sources are absent, incompatible, stale, or insufficient for the declared honesty threshold. |
| `ELAPSED_RATE_UNQUALIFIED` | No positive lower rate is established for this exact suspend-inclusive counter and host scope. |
| `ELAPSED_READ_ERROR_UNQUALIFIED` | Counter read and representation error has no finite qualified upper bound. |
| `RETURN_BOUND_UNQUALIFIED` | No finite bound covers the last sample through the actual Python `observe()` return. This is the current decisive refusal. |
| `BOUND_OVERFLOW` | Outward rounding or aging cannot produce a representable aware UTC `datetime`. |
| `NETWORK_UNAVAILABLE` | No fresh authenticated response satisfies the bounded retry policy. |

After a trusted result reaches the repository, the existing checks still reject a
non-`TRUSTED` result, an empty source, a non-UTC datetime, a decreasing bound, and
`u >= T`, including equality. The provider does not know `T` and cannot weaken those
checks.

### Provenance without changing v1 bytes

The current completion v1 receipt remains exact. It has one selection artifact
reference, records `u` as `created_at_utc`, discards source and confidence, and uses the
stable `completion_slot()`. No existing v1 manifest is rewritten or reserialized.

A later production provider would require a completion role v2. V2 still uses generic
`SnapshotManifest` schema 1 and the same stable selection and completion slots. It adds
no column and changes no generic manifest field. Its exact `ManifestVersion` selects
the v2 domain reader. A fresh Matchweek gets one receipt version; an occupied v1 slot
cannot be upgraded.

The completion version name is
`matchvet:matchweek-research-completion:postcommit-upper-bound-v2`, with canonical
contract version 2. The selection role remains on its current v1 contract. The
provenance artifact uses
`application/vnd.matchvet.trusted-utc-observation+json;version=1`. Protocol requests,
responses, public trust material, and qualification records retain distinct exact media
types so the reader never infers a role from list position or a filename.

The v2 receipt directly references a sorted exact set of existing generic artifacts:

- the selected `SnapshotManifest` bytes;
- one canonical trusted-UTC provenance artifact;
- every raw request and response named by that provenance artifact;
- the exact source trust profile and public trust material needed for offline verification;
- the exact device, elapsed-clock, and return-boundary qualification artifacts.

The canonical provenance artifact records the observation estimate, the conservative
upper bound, every source interval, raw-byte digests, the nonce or imprint binding, the
source honesty policy, the timescale rule, `b0`, `b1`, the boot and process identity,
the minimum-rate fraction, each error term, outward rounding, software and protocol
versions, the qualification digest, and the final formula inputs. Unknown values use
an explicit `UNKNOWN` state and null numeric fields. A successful v2 receipt refuses
any unknown required value.

`created_at_utc` remains the exact `upper_bound_utc`. `verified_at_utc` remains ordinary
artifact publication metadata. The receipt reader does not reinterpret either field.
The v2 reader verifies the canonical provenance bytes, raw artifacts, signatures, trust
profiles, recorded host-binding evidence, formula, selection binding, common policy and
cutoff, and the complete selected graph without a network call.

The private live operation must capture the exact provenance digest and referenced
blob digests returned by the clock. It consumes its one receipt attempt before staging
any of those objects. The v2 `_ResearchOperation._bind()` rule accepts only that exact
set, the exact selection digest, and `created_at_utc == upper_bound_utc`. A caller cannot
replace evidence between observation and receipt publication. A failure can leave
unreferenced generic objects, but it cannot mint a second attempt or qualify a receipt.
The existing v1 binding rule stays unchanged.

This representation keeps protocol bytes out of the clock interface used by F11
through F16. It also keeps source-specific parsing out of `ArtifactStore` and `Store`.
The completion reader owns the v1 and v2 domain meanings, per boundary-discipline and
single-source-of-truth.

### Module map

| Module | Ownership |
| --- | --- |
| `matchvet.trusted_utc` | Stable base result, clock protocol, and refusal type. `matchweek_research` temporarily re-exports the existing names. |
| `matchvet.termux_trusted_utc` | One deep provider and its provenance contract. It owns qualification loading, host binding, boot state, nonce creation, protocol adapters, interval combination, elapsed aging, retries, rounding, canonical evidence, and offline evidence verification. |
| `matchvet.matchweek_research` | Existing gate, monotonic accepted-bound check, strict `u < T`, selection admission, and completion v1 or v2 domain replay. |
| `matchvet.artifacts` | Generic content-addressed artifacts and `SnapshotManifest` schema 1. It learns no Roughtime, NTS, TSA, or clock formula. |
| `matchvet.store` | Existing private operation lifetime and exact reserved-slot insertion. A future v2 binding stores only the in-memory expected evidence digests and receipt version. |

Transport adapters remain private to `termux_trusted_utc`; their wire types are never
re-exported. The provider keeps per-instance, per-process anchor state. It never writes
a shared cache. Reboot, process restart, elapsed rollback, or unknown state discards
the anchor and requires a fresh authenticated observation, per separate-state and
boundary-discipline.

### Minimal prerequisite ticket

**Title:** Prove or reject a finite Termux observation return-boundary guarantee

The ticket has one question: can the exact supported Android, kernel, Termux, CPython,
and native-call path supply a finite upper bound from the last value update through the
language-level return of `TrustedUTCClock.observe()`, while covering arbitrary process
and device suspension?

Acceptance requires all of the following:

1. Define the exact return event used by the current contract. Do not replace it with a
   syscall completion, callback, remote signing event, caller comparison, or confidence
   estimate.
2. Cite a primary platform or hardware guarantee for a finite bound through that event,
   including preemption and suspend. Empirical latency trials can falsify a proposed
   number but cannot establish the worst case.
3. Trace the guarantee through CPython and any native boundary. Account for the pause
   after the final native value update and before Python returns.
4. Give a checked proof that the bound remains finite under the task's arbitrary
   suspension premise. Do not insert a chosen timeout or scheduling allowance.
5. If no such guarantee exists, record the contract as infeasible on this execution
   boundary and keep `_UnavailableClock` as the production provider.

This ticket does not implement a provider, touch a live store, rebuild a Matchweek, or
change #70. Only if it succeeds should a later ticket qualify the exact elapsed-counter
rate and one signed UTC source profile.

## Synthesis decision

Pending arena synthesis. Candidate A recommends retaining production refusal and
advancing only the return-boundary prerequisite ticket. If that ticket succeeds, use a
nonce-bound Roughtime interval, qualified `CLOCK_BOOTTIME` aging, and completion v2
provenance as the base. RFC3161 can replace or supplement the signed interval only
under an exact accuracy and PKI profile.

## Tradeoffs accepted

- We accept no prospective production availability in exchange for preserving the
  exact #75 upper-bound premise.
- We accept device-specific qualification in exchange for avoiding an unsupported
  claim about all Android devices.
- We accept conservative refusal on disagreement, overflow, forward jumps, missing
  network evidence, or unknown terms in exchange for never converting uncertainty into
  zero.
- We accept a completion v2 domain reader in exchange for retaining source evidence
  without changing generic manifest schema 1, database schema, stable slots, or any v1
  byte.
- We accept explicit trust in a profiled time authority in exchange for a signed UTC
  interval. A signature alone cannot establish clock honesty.

## Alternatives considered

### Keep only the three-field v1 observation and receipt

This has the smallest code change, but it discards every premise needed to replay the
claim. Callers stay simple while reviewers must trust an unrecorded provider setup. It
loses to v2 provenance if a provider ever qualifies.

### Let callers coordinate sources and elapsed samples

This exposes nonce rules, protocol choice, interval combination, clock aging, and error
terms to each F11 through F16 caller. It creates a shallow clock module and repeats the
same safety decisions across the repository. The single factory and `observe()` pair
hides more complexity behind a smaller public API.

### Use an RFC3161 token as the completion clock

A causal token can prove that a bound event happened after the selected bytes were
committed. Its signed event precedes response receipt and method return. This is a
different contract and cannot carry `TrustedUTCUpperBound.confidence="TRUSTED"` here.

### Use multiple HTTPS dates or a median of network clocks

This can expose gross disagreement. It supplies no finite error guarantee and a median
does not create one. The extra caller-visible source policy would hide little, so this
shape is both unsafe and shallow.

### Return a large future value

Any fixed finite value can be overtaken during an arbitrary final pause. A value large
enough to cover unbounded delay also fails `u < T`. This was the only shape that could
avoid source aging, and the two required inequalities rule it out.

## Open questions and risks

- Can any supported execution boundary identify the Python method return as an atomic
  time observation event, with a documented finite bound under arbitrary suspension?
- Who has authority to approve and revoke a device qualification, and how does a release
  pin its exact digest?
- Does an approved source profile cover leap seconds, smear behavior, key rollover,
  revocation, protocol version, and the authority's finite UTC-error promise?
- Is a beta Roughtime endpoint acceptable for production availability once the local
  proof exists, or must MatchVet operate or contract with another authority?
- If every reviewed Android execution path lacks the return guarantee, should selection
  move to an execution environment with a different contract? That decision is outside
  this candidate and cannot relabel an event-time witness as the current clock.

## Next implementation step

Open the return-boundary prerequisite ticket and keep the production clock unavailable;
do not start the provider or completion v2 work until the ticket proves a finite bound.

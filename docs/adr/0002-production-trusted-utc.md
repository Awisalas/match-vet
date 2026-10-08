# Production trusted UTC remains unavailable under the return-time contract

Date: 2026-10-07.
Status: accepted blocker diagnosis and qualification direction. No production time
source is approved by this decision.

## Problem

The completed #75 protocol requires a finite UTC upper bound covering actual UTC
when `TrustedUTCClock.observe()` returns. The requirement covers suspension and
rollback. Selection acknowledgement additionally requires that bound strictly
before the common cutoff. Android network time, an authentic timestamp, and a
synchronized label do not establish this contract.

The [primary-source research](../research/production-trusted-utc-2026-10-07.md)
evaluates Android time and uncertainty APIs, NTP/NTS, independent HTTPS Date,
RFC3161, Roughtime, and suspend-inclusive elapsed anchors. None establishes the
unchanged contract on the current Termux execution boundary.

## Decision

Keep the default refusing production provider. Do not implement or configure a
provider claiming `TRUSTED` from the researched mechanisms. The operational
blocker remains open; #73 and #74–#78 implementation acceptance remains complete.

The strongest conditional design is a pinned, nonce-bound signed UTC interval,
preferably Roughtime, aged using a qualified suspend-inclusive elapsed upper bound.
It also needs a justified bound through the actual return boundary. Neither local
premise has been established. No oscillator rate, timeout, or scheduling allowance
is selected here.

There is a stronger reason than missing calibration. After the last event fixing
a finite returned value, Android can suspend the process before the return. For
any candidate value below T, a sufficiently long suspension makes actual return
UTC exceed it. Reading another counter only moves this final gap. Under arbitrary
suspension, an informative finite actual-at-return result is impossible. Better
network synchronization or oscillator characterization alone cannot solve that.

A postcommit RFC3161 or Roughtime witness can instead bound a causally later
remote event. This proves `commit <= signed event upper bound < T` independently
of response delivery. It does not satisfy the current clock interface or the
prospective F11–F16 writer gates. Adopting it as primary authority would change
accepted timing semantics and requires a separate explicitly authorized design.
It is rejected as a drop-in clock in this task.

## Synthesis decision

Two independent structural designs were compared: an actual-at-return interval
clock and a causal committed-event witness. Use the first design's refusal and
conditional interval arithmetic; retain the second design's explicit separation
of historical event evidence from current-time authority. Remove the proposed
clock-type relocation and optional supplemental-witness module. They add no
capability while the required premise is unavailable.

The [design](../design/production-trusted-utc.md) records the future confidence
shape and exact refusal rules. The [proof record](../../.audit/production-trusted-utc/README.md)
records the isolated counterexamples, source identities, and prototype branch.

## Consequences

- Prospective production work refuses online and offline until the timing
  premise is resolved. Existing exact selected-state replay remains available.
- No #75 clock, completion, writer, cutoff, or restart contract changes. No live
  store, operational Matchweek artifact, acquisition, rebuild, or #70 fitting.
- Rich clock provenance can fit existing generic artifacts/manifests. A future
  completion v2 reader and exact private binding would be necessary because v1
  retains only one selection reference and the bound. No migration is justified.
- The next issue is a timing-contract decision prerequisite, not a ready provider
  implementation. No production mechanism passed the requested qualification.

[Issue #79](https://github.com/Awisalas/match-vet/issues/79) tracks that prerequisite
with `needs-triage`. It must establish and explicitly authorize a feasible boundary
before a production implementation issue can be ready.

## Rejected alternatives

Android UTC/network/Play services uncertainty lacks a hard guaranteed bound.
HTTPS Date and its median or maximum across origins lack one as well. NTS adds
authentication but leaves accuracy, elapsed aging, and return delivery premises.
RFC3161 and Roughtime provide signed source-event bounds; wrapping those unchanged
as actual-at-return bounds is false. A BOOTTIME anchor covers suspend only when
its rate and read-error limits are qualified, and still has the final delivery gap.
Moving authoritative execution to another host expands ownership/deployment and
does not itself repair the literal return-time requirement.

## Prospective successor, 2026-10-08

[ADR 0003](0003-causal-matchweek-selection-witness.md) now explicitly authorizes
a causal trusted remote event for newly versioned Matchweek selection. The
actual-at-return impossibility above remains accepted. The refusing production
default stays in place until the corrective implementation and successor tests
complete. This decision's unchanged-v1 statements remain historical; they do not
forbid the separately authorized prospective design in ADR 0003.

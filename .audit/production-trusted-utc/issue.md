## Blocker and scope

The unchanged #75 clock contract requires a finite upper bound on actual UTC at
`TrustedUTCClock.observe()` return, including suspension. No researched source
satisfies it on Termux/Android. After any final value-producing event, an unbounded
pause before return can make the returned value stale. This applies even with a
perfect source and elapsed counter.

This is a **timing-contract decision prerequisite**, not an implementation-ready
clock ticket. Keep prospective production time unavailable. #73 and #74–#78 remain
complete; their deterministic proofs do not establish production clock premises.

Read ADR 0002, docs/design/production-trusted-utc.md,
docs/research/production-trusted-utc-2026-10-07.md, and the isolated proof records.

## Required decision

- Identify a supported execution boundary with primary evidence of a genuinely
  compatible finite bound through the exact return event, or explicitly record
  infeasibility under unrestricted Android scheduling.
- If a different observation/event boundary is proposed, obtain separate explicit
  acceptance of that change. Do not silently reinterpret or weaken the existing
  clock contract. Specify every F11–F16 writer gate and completion event it covers.
- For a new design, prove durable selection completion before common T, cutoff
  equality refusal, no qualified later evidence/new state, one winner, terminal
  receipt loss after restart, and immutable selected replay. A token merely signed
  before T cannot authorize subsequent work.
- Distinguish causal remote event bounds from current UTC bounds. Explain why
  source accuracy, nonce binding, observed event and any local elapsed terms cover
  the chosen event; use no invented rate or scheduling margin.
- Pin one qualified source/protocol/trust profile and specify UTC/leap handling,
  missing confidence, offline, disagreement, delay, rollback, suspend and reboot
  refusal. Retain versioned confidence evidence through exact protected manifests.

## Acceptance

- [ ] Choose and explicitly authorize a concrete feasible observation boundary
  or execution model with its proof. Do not close this decision issue merely by
  repeating the already recorded infeasibility diagnosis.
- [ ] State whether #75 timing semantics change; preserve all accepted safety
  conditions and every v1 byte/reader. No clock adapter for historical witnesses.
- [ ] Qualify every numerical/error premise from primary evidence covering the
  execution platform. Empirical latency samples are not worst-case guarantees.
- [ ] Demonstrate the proposed boundary in isolated proof with suspend/return
  counterexamples and full affected writer/selection path coverage.
- [ ] Only after viability is established, create the smallest implementation-ready
  issue. Existing generic artifacts can carry confidence; v2 provenance needs exact
  reader/private binding. Stop and justify any claimed migration need.

## Restrictions

No production clock code or activation yet. No live SQLite access, live Matchweek
acquisition/rebuild, operational artifacts, #70 numerical fitting, or clock-contract
relaxation within this issue's current authorization. A semantics-changing design
requires separate explicit authorization before adoption.

Prototype context: branch `prototype/production-trusted-utc-20261007`, commit
`dc39cf9351954744a58ed0c9b8d11b05e1eecbc9`, including the standalone HTML and
rerunnable isolated Python proof. Design/research/proof capture: commit `55a3a1b` on main.

- [ADR 0002](https://github.com/Awisalas/match-vet/blob/55a3a1b/docs/adr/0002-production-trusted-utc.md)
- [Design and confidence contract](https://github.com/Awisalas/match-vet/blob/55a3a1b/docs/design/production-trusted-utc.md)
- [Primary research](https://github.com/Awisalas/match-vet/blob/55a3a1b/docs/research/production-trusted-utc-2026-10-07.md)
- [Isolated proof record](https://github.com/Awisalas/match-vet/blob/55a3a1b/.audit/production-trusted-utc/README.md)
- [Prototype branch capture](https://github.com/Awisalas/match-vet/tree/dc39cf9351954744a58ed0c9b8d11b05e1eecbc9)

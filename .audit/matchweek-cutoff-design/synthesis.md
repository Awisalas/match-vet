# Cutoff design synthesis

## Candidates and review

Candidate A (gpt-5.6-sol) proposed additive F07 rule dispatch, completion of the existing F16 chain before cutoff, and a generic SnapshotManifest with one deterministic logical-Matchweek identity. Candidate B (gpt-6-astra) proposed a new frozen-input selection aggregate allowing first deterministic computation after cutoff, but preferred the existing F16 alternative if pre-cutoff computation is acceptable. Both outputs were read in full.

The configured/default Claude and Grok runners were unavailable in this harness. Available GPT model families supplied two distinct architectural shapes. A transient thread-limit failure was retried; both candidates completed, with no final dropout. The independent cross-judge was gpt-6-astra.

| Criterion, 1–5 | Parent A | Parent B | Judge A | Judge B |
|---|---:|---:|---:|---:|
| Common cutoff, every writer, late-F06 admission | 5 | 5 | 5 | 5 |
| Original replay and software identities | 4 | 5 | 4 | 5 |
| Smallest schema/wire/migration scope | 5 | 2 | 5 | 2 |
| Deep owner and durable single assignment | 4 | 4 | 4 | 4 |
| CB01/evaluation chronology without extra policy | 2 | 3 | 2 | 3 |

Both parent and judge selected A as the base. One owner hides full-slate admission, canonical selection, closure, and replay behind seal/replay operations; it is not a pass-through CLI wrapper. Existing F16 alone cannot select between alternative freeze/policy/profile manifests. Catalog scanning alone cannot provide atomic single assignment.

## Grafts and rejections

Grafted from B: explicit F13 adapter-contract preservation, existing typed-identifier/foreign-key explanation, source-only compatibility qualification, and the distinction between research closure and independent timestamp proof.

Rejected B's new model-input selection payload and downstream binding versions: the founder does not require first computation after cutoff, and complete existing F16 state gives the smaller correction. This accepts the stricter operating deadline that computation as well as research completes before cutoff.

Rejected both candidates' extra earliest-kickoff deadline for every CB01 witness. The founder clarification bounds research, while the existing released CB01 rule is cutoff < signed genTime < own kickoff. One pre-cutoff whole-slate selection plus the full denominator preserves that contract. Later witness time never authorizes later research. Independent evidence of pre-cutoff collection remains unavailable; no new claim is made.

Strengthened A's selector identity: one stable logical-Matchweek namespace must survive selector reader-version changes. Including a new contract version in the uniqueness key could reopen selection for an already frozen week.

## Cross-judge findings applied

1. ArtifactStore samples verification time before object publication and catalog write. The design now requires durable publication, verification, and a repository-controlled pre-cutoff completion check with protected completion evidence. Missing proof or a crossing-cutoff crash refuses qualification. A narrow persistence hook may be necessary; compatibility is unproven until isolated implementation tests.
2. Digest-only replay could accept an orphan/noncanonical proposal. Replay must verify the deterministic catalog mapping, and lookup by logical Matchweek is included for restart.
3. CB01 binds both core software and trust-module digests. Preserve both identities or implement explicit historical dispatch.

## Verification and limits

The committed read-only probe executes shipped F07 arithmetic and F11 request hashing while blocking SQLite/network connections and trapping F07 construction. It proves the current contradiction and the existing rule discriminator, not the future correction. Source inspection supports schema reuse; no new SnapshotManifest, F06/F07/F11/F13/F14/F16/CB01 artifact, live store access, acquisition, or witness request was used to prove it.

The selected [design](../../docs/design/matchweek-wide-evidence-cutoff.md) and [ADR](../../docs/adr/0001-matchweek-wide-evidence-cutoff.md) record the synthesis. Implementation proof and live rebuild remain deferred under the user's explicit instruction.

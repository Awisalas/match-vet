# CB01 architecture cross-judge

## Verdict

Use **Candidate A** as the base. Graft Candidate B's private immutable evidence checkpoints and its explicit replay/finalization split. Keep both behind the contract's five `BootstrapRepository` operations; do not expose the stages as caller-managed workflow.

| Criterion | A | B | Assessment |
| --- | ---: | ---: | --- |
| CB01 v1 fidelity and scope | 5/5 | 5/5 | Both retain the exact five public operations, full Profile denominator, outcome-free enrollment, exact identities, no CLI/Store changes, and no #70 methodology. |
| Frozen public repository surface | 5/5 | 5/5 | Both make the repository own the protocol and expose typed domain inputs/results rather than transport or wire artifacts. |
| Durable recovery and receipt-last visibility | 5/5 | 4/5 | Both use catalog-derived evidence, exact attempt selection, idempotent records, and receipt-last publication without Store changes. A is more specific about reconciling cataloged response artifacts, rejecting ambiguous candidates, and building validated operation-local indexes. |
| Trust/TUF/RFC3161 replay integrity | 5/5 | 4/5 | Both cover exact request/response bytes, nonce/imprint, signer, policy, TUF retention, offline replay, strict signed-time ordering, and no fallback. A spells out root-rotation retention and conflict handling; B leaves selected-policy versus refreshed metadata semantics as an open implementation question. |
| Call-chain and cognitive burden | 5/5 | 4/5 | Both are shallow at the public seam. A states the common path as repository plus one owning helper and locates coordination decisions in one place. B's extra checkpoint/policy vocabulary is valuable internally but needs to stay private. |

## Reasons and graft

A is the stronger base because it turns the contract into a concrete ownership map: one facade coordinates preparation, exact-attempt recovery, trust, publication, denominator inspection, and outcome attachment, while focused helpers own schema, source replay, witness policy, and facts. Its recovery description handles catalog reconciliation and ambiguous response evidence directly, and it explains how the existing writer lock and per-object ArtifactStore publication are sufficient. The design preserves the receipt as the only visibility boundary and avoids a mutable progress index or Store change.

Graft B's frozen `PreparedCase`, `RetainedAttempt`, `ReceivedAttempt`, `VerifiedCase`, and `PublishedCase` evidence types, with finalization accepting only verified evidence. Also retain B's recovery table as an implementation checklist. These make invalid stage transitions harder to express and clarify which retained evidence permits each recovery action, without expanding the public API.

Both candidates should keep retry eligibility tied to the contract's allowed witness window: a retry may use a new nonce only for the unchanged batch, and a token at or after kickoff cannot establish live enrollment. B's policy-refresh open question is useful as an implementation gate: refresh and retain the actual authenticated TrustState per attempt without mutating or silently substituting the selected immutable policy. Neither sketch is runtime proof; those details still require implementation evidence.

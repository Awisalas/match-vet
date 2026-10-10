# Accept conditional causal witness assurance for RESEARCH_ONLY collection

Date: 2026-10-10.
Status: accepted by explicit user confirmation of Option A on 2026-10-10.
Scope: prospective RESEARCH_ONLY #70 corpus collection only.

Accept Option A, the existing conditional assurance of
`matchvet-sigstore-causal-event-v1`. It is sufficient for collecting an explicitly
qualified research corpus under ADR 0003's stated premises. It grants no runtime
activation, real-source authorization, statistical evidence role, production
PLAY, or Production Promotion.

This is an explicit scope amendment to [ADR 0003](0003-causal-matchweek-selection-witness.md),
not a change to its chronology proof or immutable profile bytes. The [activation
audit](../research/causal-profile-activation-audit-2026-10-10.md) remains the evidence
record. Its factual UNKNOWN findings remain UNKNOWN. This decision accepts
conditional reliance on named promises without establishing previously unknown
facts. Option A is the simplest defensible collection policy because it uses
ADR 0003's already explicit premises and exact evidence retention. Option B
requires additional external evidence absent from the reviewed public service;
it would keep collection refused without improving existing evidence by itself.

## Compare the alternatives

| Criterion | A: accept existing conditional V1 assurance | B: require affirmative deployed-clock and current-nonrevocation evidence |
| --- | --- | --- |
| Chronology correctness | The exact selected graph precedes the bound request and signed event. Strict `U < T` proves timely completion conditional on the accepted authority and honest-local-execution premises. | Retains the same proof and adds independent support for its premises. Stronger evidence still needs its own authentic authority, interval, and deployment binding. |
| Failure modes | Hidden smear, false accuracy, compromised/backdating keys, or undisclosed withdrawal can defeat chronology despite valid signatures. Known invalidation refuses. Outages or receipt loss permanently sacrifice a Matchweek. | Reduces some authority risks if the added evidence covers the exact event. Missing, stale, ambiguous, or unavailable attestation/status evidence blocks collection. It cannot remove every trust assumption. |
| Evidentiary integrity | Retains exact graph, nonce, signature, profile, approval, trust closure, denominator, and later F19 lineage. Historical assurance and factual UNKNOWN states stay explicit. | Must additionally retain exact deployed-clock and status evidence. No retrospective stronger claim can be inferred from an old signature. |
| Feasibility | Existing offline protocol and integrated proofs establish the conditional mechanics. Authenticated owner controls and exact fresh metadata admission remain to implement. | The retained audit found no qualifying public Sigstore deployment/status guarantee. Operator evidence or a separately qualified witness service is needed. |
| Operational complexity | One bounded authority attempt, owner activation/withdrawal continuity, and approved exact metadata updates. | Adds deployment attestation, current-status verification, their validity/freshness rules, and further outage dependencies. |
| Can #70 accumulate data? | Yes after mechanical prerequisites and separate real-source approval pass. Failed, unavailable, and unattempted denominator rows remain visible. | Collection remains refused until the extra evidence exists. The audited public TSA alone does not currently establish it. |
| Later Production Promotion | Collection acceptance establishes no predictive validity or promotion permission. A later promotion decision must assess this corpus's stated assurance and all independent statistical criteria. | Stronger witness assurance still establishes no predictive validity or promotion permission. A later consumer requiring B must assess or exclude A cases that lack its evidence. |

## Accepted collection boundary

For RESEARCH_ONLY corpus collection, accept these existing premises together:

1. Sigstore's published [UTC, leap-synchronization, and declared-accuracy promise](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#732-clock-synchronization-with-utc)
   supplies the remote-authority premise. Independent proof of the deployed
   host's clock discipline is not required by this collection policy.
2. Rely on an uncompromised authority unless authenticated compromise or
   withdrawal evidence invalidates that reliance. Undisclosed compromise remains
   an acknowledged risk, never an affirmatively established ABSENT fact.
3. Retain `HISTORICAL_RETAINED_TRUST_ONLY` and
   `current_revocation_checked=False`. Offline replay claims no affirmative
   current revocation check or full [Sigstore policy compliance](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#8-security-considerations).
4. Refuse on authenticated invalidation, pin/policy mismatch, expired or
   inapplicable event trust, or uncertain owner-state continuity. New work under
   withdrawn approval refuses. Affected retained events lose present
   qualification while exact historical inspection and occupied slots remain.
5. Limit this acceptance to prospective RESEARCH_ONLY evidence collection.
   F17, #37 fitting, production PLAY, and promotion remain separately blocked.

The [RFC3161 event interval](https://www.rfc-editor.org/rfc/rfc3161.html#section-2.4.2),
complete graph, signed upper bound, one request/receipt, permanent failure,
and exact replay rules remain unchanged. CB01 independently requires
`T < signed genTime < own controlling kickoff`. CandidateInput UNKNOWN,
unavailable rows, raw/uncalibrated prediction states, and append-only F19
corrections retain their existing meanings. No evidence roles are assigned.

## Mechanical prerequisites and later use

Runtime activation remains refused until an authenticated owner supplies
activation, withdrawal, and restore continuity; admits a fresh exact TUF bundle;
and binds the exact profile, policy, operator, and pins. Admission preserves
monotonic floors and checks the entire event interval against all applicable
validity/expiry bounds. Advisory wall time or a valid old signature cannot prove
current owner-state continuity. This ADR alone is not authenticated runtime
approval, and source acquisition needs its own authorization.
[#87](https://github.com/Awisalas/match-vet/issues/87) covers only these activation
mechanics. Its completion alone will not provision an owner approval or authorize
collection.

Profile SHA-256 remains
`7ba7e2f4db4de3aa7ef41d77d9ff5f8fafecb73c6de9c5b297924454f51e5c66`.
A compatible authenticated metadata refresh changes no profile identity. Changing
policy, pins, timescale, or assurance requires separate immutable version review.
Old receipts cannot be upgraded, backdated, or reinterpreted.

The [#81 protocol proof](../../.audit/issue-81-implementation/README.md) and
[#84 integrated proof](../../.audit/issue-84-implementation/README.md) establish
conditional execution and replay behavior. They establish neither actual public
clock compliance nor predictive validity. If later promotion demands stronger
assurance, evaluate the original cases under that requirement, retain unsupported
cases as such, and collect new evidence prospectively where necessary.

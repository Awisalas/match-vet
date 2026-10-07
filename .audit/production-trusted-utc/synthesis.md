# UTC design synthesis

Two independent structurally distinct packages were read end to end. Available
Codex models were used: GPT-5.6 Sol for the actual-at-return interval clock and
GPT-6 Astra for the causal committed-event witness. The unavailable skill-default
model families were not used. GPT-6 Luna independently cross-judged both packages.

| Rubric, 0–5 | Interval clock | Causal witness |
| --- | --- | --- |
| Meets actual-at-return contract under arbitrary pauses | 0 | 0 |
| Defensible uncertainty, no invented margin/rate | 5 | 5 |
| All prospective gates and single-assignment/restart safety | 5 | 1 |
| Deep/minimal API and compatible provenance | 4 | 3 |
| Termux/network/offline failure model | 4 | 4 |
| Honest readiness and next action | 5 | 4 |

Lead and cross-judge agree. Neither package is production viable. Scores in the
first row measure capability, not honesty: both explicitly reject activation.
Use the interval clock as conditional base; graft the witness design's distinct
event scope and causal inequality. Reject clock-type relocation and supplemental
witness scaffolding because they add no current capability. No pass-through
provider registry or public phases are needed.

Red-flag screening found no accepted transport leakage or duplicated authority.
The main design retains one future provider owner and existing Store/repository
ownership. Raw wire stays behind the provider, and exact returned provenance
belongs to one observation rather than a mutable last-result cache. The causal
witness cannot implement `TrustedUTCClock` or substitute for writer gates.

The decisive counterexample is a pause after the last value-producing event
and before return. Under arbitrary pause, no finite margin covers that interval.
Android rate qualification alone cannot solve it. Retain current refusal and
track the unresolved timing-boundary decision before writing provider code.

This is a blocked production result, not an implementation completion. The
prototype proves counterexamples and default refusal only. Successful HTTPS
responses and synthetic signatures establish no real provider accuracy.

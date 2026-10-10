# Two-axis code review

Fixed point: `62b7a6a3e80ef87d9292c4df84225f540d9bceb3`.
Reviewed implementation: initial `ff22e98`, subsequently amended for final evidence
and the root-prefix binding check independently re-reviewed below. No reviewer
edited files or ran heavy tests. The implement skill requires this parallel review.

## Standards

No documented-standard violations found. Reviewed AGENTS.md, pyproject.toml,
docs/agents/domain.md, GLOSSARY.md, relevant ADRs, and the specified diff.
Tool-enforced formatting and typing issues were excluded.

One optional judgement call: possible Primitive Obsession in
`causal_activation._history`. Authenticated records remain `dict[str, Any]`, and
`_check_head` consumes those dictionaries directly. Expressions such as
`prior["floors"]` and `value["adverse"]` carry security-relevant invariants through
dynamically typed values. A small private parsed record type, constructed after
canonical signature/schema validation, could make those invariants easier to
inspect and maintain without changing signed bytes.

The private authority boundary remains explicit. Current authority comes from
independently installed configuration and a fresh signed checkpoint. Retained
verification does not itself grant present authority. No blocker or functional
defect was established. Total: zero hard violations, one optional maintainability
finding. Lead disposition: keep the direct validated canonical JSON representation
within #87's minimal scope; no behavioral gap requires another parsed type.

## Spec

No findings. Reviewed complete #87, ADRs 0003/0005, activation audit, owner contract,
retained proofs, implementation and focused tests.

The implementation covers independently installed Ed25519 authority, canonical
signed append-only records, exact authenticated TUF admission and monotonic floors,
fresh nonce-bound authoritative checkpoint verification, stale approval refusal,
checks after DNS/TLS and before protected receipt insertion, authenticated adverse
boundaries, immutable historical inspection, explicit approval-evidence dispatch,
permanent occupied failures and separate #86 source authorization.

The independently provisioned checkpoint service remains responsible for
nonrollback head/floors and authenticated Store/history restore reconciliation.
That external operational prerequisite is explicit. Local files or saved signed
checkpoints cannot substitute for fresh continuity evidence. No production authority
or approval is provisioned. Default production remains refusing.

## Lead follow-up and re-review

The lead found that final-role floors alone did not prevent signature-valid
re-encoding of an earlier admitted intermediate root. Admission now requires the
existing root bytes to remain an exact prefix of the new chain. The new test uses
signature-valid whitespace re-encoding and proves refusal. The Spec reviewer
rechecked the three-line rule, test and documentation: no issue found; this enforces
same-version same-hash across intermediate rotations and permits sequential
extensions without changing released profile/trust logic.

Final counts: Standards zero hard findings, one optional concern; Spec zero
outstanding findings. The root-prefix gap found by the lead is fixed and verified.

The Spec reviewer also rechecked the narrowly permitted Store scope. The protected
admission predicate previously represented only original operation authority, not
current independently authenticated approval lineage after staging. The minimal
insertion check closes that exact authority-representation gap; existing persistent
evidence remains sufficient. No additional schema or implementation change was
requested. The receipt-stage and receipt-insertion tests exercise this necessity.

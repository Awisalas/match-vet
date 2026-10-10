# Adversarial review of source authorization, #89

Reviewed implementation: `40118a4635052ddbebb07509d2e6cab017e4185b`.
Review date: 2026-10-10.
Verdict: MAJOR. Two findings invalidate #89's deterministic acceptance.

## Intent and scope

Review whether [#89](https://github.com/Awisalas/match-vet/issues/89) implements
[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md) with
independent current source authority, exact protected manifests, private research
retention and immutable historical replay. Challenge acquisition, dispatch and
admission without changing production code or using live sources.

Read the issue and its closure comment, ADR 0006, the automated closure assessment,
source-use decision and authorization design. Inspected `source_authorization.py`,
`source_manifest.py`, `research_capture.py`, CB01 dispatch and artifact admission,
T10/F19 outcome evidence, relevant tests and the #90 transport contract.

## Reviewers

The interrogate settings file was absent. Its default model names were unavailable
in this harness, so supported models were requested instead. All reviewers received
the same scope, intent, attack areas and review references, with read-only access.

- Reviewer A, `gpt-6-astra`, reported the withdrawal timing gap and outcome closure
  omissions before its turn ended with a usage-limit error.
- Reviewer B, `gpt-5.6-sol`, did not return usable findings before a usage-limit error.
- Reviewer C, `gpt-6-sol`, reported supplemental outcome evidence and raw-digest
  omissions before its turn ended with a usage-limit error.
- Reviewer D, `gpt-6.1-sol`, completed a review confirming the supplemental outcome
  omission. It did not report another high-confidence finding.

The lead independently traced and reproduced both accepted findings. Partial
reviewer output is corroboration, not a claim that four complete audits finished.

## Act on

### M1. MAJOR: withdrawal during final validation permits a side effect

`SourceAuthorizationRepository.require_current`, lines 474–493, loads a fresh
signed checkpoint before recomputing the manifest and verifying the decision and
classification conflicts. Those checks can take substantial time for a selected
graph. A withdrawal completed during them does not invalidate the earlier head.
The guard returns success to dispatch or protected insertion.

Two deterministic synthetic-owner reproductions hook manifest validation after
the fresh head has been read. They append a valid withdrawal before validation
returns. No stale signature or forged checkpoint is used.

1. At acquisition's final dispatch guard, checkpoint call three, the acquisition
   callback executes after withdrawal. A subsequent guard refuses admission.
2. At raw publication's guard inside the SQLite transaction, checkpoint call
   seven, the raw artifact insertion commits after withdrawal. The post-commit
   guard raises refusal, but the raw artifact is already catalogued.

`acquire`, lines 526–541, and CB01's guarded dispatch/admission share this ordering.
The findings concern completed withdrawals during validation, beyond the small
unavoidable interval between a final current-state check and an external call.
The existing dispatch and staging tests withdraw before the guard reads its head;
they do not exercise this interval inside the guard.

Smallest correction: complete expensive retained-evidence validation before the
final fresh continuity check. Ensure withdrawal during the final guard refuses
dispatch and rolls back protected insertion. Preserve separate causal authority,
V1 behavior and immutable historical replay. Add both boundary regressions.

Raised independently by reviewer A and the lead. Act on because ADR 0006 and #89
require current authorization at dispatch and admission, including withdrawal
during the operation.

### M2. MAJOR: the outcome manifest underprojects admitted source evidence

`source_manifest.outcome_projection`, lines 224–242, closes only the settlement
artifact. `ResearchCaptureRepository.attach_outcome`, lines 242–305, accepts
`exact_fact_evidence` and forwards it after authorizing that settlement manifest.
CB01's `_outcome_evidence_items`, lines 614–647, accepts supplemental same-fixture
T10 snapshots outside the settlement and includes them in `OutcomeFactAttachment`.
Neither current authorization nor capture replay compares the manifest with this
complete fact-evidence set. An authorization for the settlement's source can admit
additional sources without their reviewed manifest entries.

A deterministic reproduction records a supplemental source through the actual
`T10GradingService` in a temporary Store. CB01 accepts it alongside the original
settlement evidence. The original settlement snapshot remains unchanged. Existing
CB01 supplemental-outcome tests also demonstrate this permitted downstream path;
the new V2 outcome tests pass `exact_fact_evidence=None`.

The closure walker has a related omission. It follows selected artifact roots and
SQL primary-key references, scheduling raw artifacts only from matched rows'
`artifact_digest`. It does not follow a T10/F19 evidence `source_digest` to its
retained raw artifact. A reproduction using actual `SettlementEvidence.to_dict`
fields and an existing protected raw artifact returns only the containing JSON
artifact. The source artifact has no dependency entry or separate classification.
Embedding its digest binds the string, but does not verify retained source bytes
or bind their source-use classification.

Smallest correction: bind the complete exact outcome fact-evidence selection,
including each applicable raw source dependency, before authorization. Compare it
at attachment and historical replay. V2 may conservatively refuse supplements
until their exact representation exists. Never add outcomes to the pre-T graph,
scan unrelated/latest Store content or fetch missing bytes during replay.

Raised independently by reviewers A, C and D and verified by the lead. Act on
because #89 requires the exact admitted source dependency closure and a separate
outcome manifest.

## Consider and noted

No additional BLOCKER or MINOR findings were substantiated. The new tests retain
the two known failures without changing production behavior. Three assertions of
required behavior are strict expected failures so their eventual unexpected pass
requires removing the corresponding marker.

## Dismissed or unproven leads

- Caller callbacks are not provider adapters. Endpoint enforcement, request pacing,
  redirects and transport limits remain #90 work; their absence is not an adapter
  implementation defect within #89.
- Restoring every copy of independent checkpoint state defeats the explicit trust
  premise. The design requires authoritative continuity outside Store/history
  rollback. Restored Store artifacts alone do not provide that service.
- Retained verification keys support offline historical inspection. Current use
  loads independent installation configuration and requires matching lineage;
  the retained key alone is not an acquisition capability.
- Loose lineage classifications warrant checking against known retained facts,
  but no additional current-authority bypass or contradictory upstream assertion
  was substantiated in this review. Do not replace a concrete repro with a claim
  that a trusted reviewer can lie.
- Protected private capture metadata does not create a publisher grant. No released
  F04/F05 permission meaning or F01/F06 completeness gate changed during this review.

## Agreement and disposition

The outcome omission has agreement across three reviewers and the lead. The
withdrawal gap has independent reviewer and lead reproductions at dispatch and
admission. Both are correctness failures within #89's existing scope.

#89 is reopened with `ready-for-agent`. No separate corrective ticket is needed;
the smallest corrections belong to its existing acceptance. #70 remains OPEN
`needs-info`; #86/#87 remain CLOSED. #90 may proceed with deterministic offline
transport work, but must not treat #89 as accepted or deliver operational source
integration until these corrections pass. #90/#91/#92 readiness is unchanged.

Remaining blockers are reopened #89, #90 transport, #91 source qualification,
#92 the first automatic Pro League schedule slice, #93 history projection, #94
outcome projection and causal operational provisioning. Default production still
refuses because real source configuration, approvals and checkpoint service are
not provisioned. No source or causal authority was installed by this review.

## Verification

- Existing source authorization tests: 45 passed, deterministic offline.
- New focused review reproductions: one passed, three strict expected failures.
  The failures reproduce two withdrawal boundaries and omitted outcome raw bytes.
- Ruff and formatter passed for the new test file. Strict mypy passed for that
  Python file. Production Python was unchanged.
- Documentation local links, fenced blocks, the exact pinned ADR digest, unchanged
  released V1 binding and `git diff --check` passed.
- No live provider access, production Store, broader suite or production edits.

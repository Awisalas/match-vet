# Independent design review A

Reviewer: inherited Codex harness model, substituted for unavailable configured
Claude reviewer. Scope: ADR 0003, causal architecture/research, grounding, both
candidate packages, rubric and offline proof. No other reviewer was read.

## Verdict

Accept the causal boundary as a prospective design under its explicit honest
local execution/storage and honest approved remote-authority premises. It
preserves the complete selected-state founder invariant. Production refusal
must remain until the cohesive successor implementation and tests complete.
No critical finding. One documentation warning should be incorporated.

## Findings

### Warning: signed policy OID is echoed from the request

Location: `docs/research/causal-matchweek-witness-2026-10-08.md:43` and
`docs/design/causal-matchweek-selection-witness.md:157`.

The source inspection records copied imprint/nonce and fixed accuracy, but omits
that the pinned handler also sets `policyID := req.TSAPolicyOID`, falling back to
the default only when empty. Therefore a returned signed OID alone is not evidence
that this service independently admits or enforces that named policy. A caller
can choose the OID that the handler signs. The existing approval requirement
independently pins the operator, chain and policy, so this is a qualification
explanation gap rather than a counterexample to the accepted causal proof.

Evidence: [pinned Sigstore handler](https://github.com/sigstore/timestamp-authority/blob/3593e847b84fa501e2a0729eaea2c6ac982c4ab3/pkg/api/timestamp.go#L181).
I opened and inspected the primary source independently. No service query ran.

Suggestion: explicitly record the echoed OID behavior in the research and require
authority approval to associate the exact approved signer/endpoint with the
reviewed policy independently of the request-selected OID. Keep strict OID
comparison, but describe it as binding consistency, never source qualification
on its own. Add this premise to the corrective issue's activation checklist.

## Checked and cleared

- RFC3161's authenticated accuracy defines a token-creation upper endpoint.
  The approved profile explicitly trusts the entire assertion, including encoding
  and generation effects; fixed source-code accuracy and generic drift monitoring
  are not falsely presented as independently measured error. See
  [RFC3161 section 2.4.2](https://www.rfc-editor.org/rfc/rfc3161.html#section-2.4.2).
- Request-after-fresh-commit ordering is supplied by trusted local private
  operation transitions and postcommit unpredictable construction. Cryptography
  alone is explicitly not claimed to attest SQLite or honest computation.
- The graph proof is transitive and universal over required artifacts, and exact
  immutable closure blocks alternate/post-event F16 inputs. F13/F14 computation
  must complete before publication; replay cannot supply missing computation.
- Suspension after the witnessed event affects delivery availability, not the
  historical bound. The ordinary-day leap restriction is conservative refusal,
  not an invented uncertainty allowance.
- TUF uses retained authentic material and explicit approved authority versions;
  token interval validity is not called latest-trust or revocation freshness.
  The documented offline compromise limit remains a remote trust premise.
- Every direct/resumed writer family appears in the final architecture matrix.
  F11 health metadata coupling and F12 candidate CUTOFF_VALID labels are
  explicitly addressed. V2 changes physical-writer-stop semantics openly.
- Missing indexed receipt, orphan response, ambiguous selection commit,
  restart/backfill and competing slot/version proposals all refuse. No second
  authority or protocol fallback silently rescues qualification.
- Stored domain/engine dispatch protects historical bytes; F13's existing schema
  2 gets a genuinely new successor identity. Stable role slots span versions.
- CB01 keeps its separate post-T/pre-kickoff semantics and historical core
  identity. Its generic parser/transport is not treated as the new verifier.

## Executed verification and limits

I independently ran:

```sh
PYTHONPATH=src:tests python .audit/issue-79/proof.py
```

Exit succeeded. Results matched `proof-result.json`: 5,120 pause/error schedules,
320 accepted, 4,800 refused; wrong imprint and wrong nonce refused; generic
no-nonce verification accepted, demonstrating why application nonce checks are
mandatory. Real shipped Store/ArtifactStore round-tripped four exact references
under unchanged generic manifest/schema in a temporary synthetic store.

This verifies the logical model, retained RFC3161 diagnostics and generic storage
representation. It does not verify production v2, protected receipt publication,
all successor writer paths, source-instance accuracy or live availability. The
records state these limits correctly. Existing historical tests are historical
evidence, not new protocol acceptance.

## Arena cross-judgment

Scores describe the original candidate packages; the synthesized architecture
subsequently fills their writer/source-detail gaps.

| Criterion | Candidate A | Candidate B | Reason |
| --- | ---: | ---: | --- |
| 1. Complete durable graph before bounded event before T | 2 | 2 | Both preserve local fresh commit and transitive causal ordering. B additionally attests remote possession. |
| 2. Primary signed accuracy/trust/leap/availability evidence | 1 | 1 | A leaves source accuracy qualification as an open research requirement; B has documented AWS primitives but no existing qualified signer. |
| 3. All direct/resumed prospective writer semantics | 1 | 1 | Both specify the correct principle; only synthesized architecture enumerates the full writer matrix and metadata-label changes. |
| 4. Live authority, crash/restart/competition | 2 | 2 | Both preserve original operation, terminal missing receipt and version-independent slots. |
| 5. Deep owner, compatibility, demonstrated storage impact | 2 | 1 | A retains one local authority and generic storage. B creates a second authoritative durability/uniqueness service with unresolved replica/backup operations. |
| Total | 8 | 7 | Choose A as base. |

Red-flag screen: neither candidate exposes temporal transport stages publicly,
adds thin pass-through APIs or leaks wire schemas to callers. A's private adapter
owns protocol/trust knowledge; the deep repository owns graph/selection policy.
B's second owner has real responsibilities, but its extra graph-storage and slot
knowledge creates costly distributed consistency requirements without satisfying
an additional founder requirement. Graft B's honest distinction between remote
graph attestation and hash commitment into A, which the final architecture already
does. Do not graft the remote registry.

## Lead classification

- Act on: explain echoed policy OID and independent source-policy approval.
- Consider: exact profile hashes/approved trust versions must be supplied in the
  corrective implementation before activation; the design does not already ship
  a production-qualified profile.
- Noted: unavailable configured reviewer model substituted by the harness.
- Dismissed: requiring an Android return bound for the new historical event;
  requiring the TSA signature alone to attest local research execution; treating
  receipt loss as recoverable merely because remote issuance may have happened.

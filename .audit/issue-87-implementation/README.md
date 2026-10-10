# Issue #87 offline mechanics

Baseline: `62b7a6a3e80ef87d9292c4df84225f540d9bceb3`.
Scope: ADR 0005 prospective RESEARCH_ONLY #70 collection mechanics only.
The [owner contract](../../docs/design/causal-owner-activation.md) defines the
canonical Ed25519 envelope, installation, challenge/checkpoint protocol, retention
and restore responsibility. The envelope was specified before production code.
No production installation, approval, TSA request, TUF fetch or source collection
occurred. All Stores and owner keys used in tests are isolated and synthetic.

## Implementation and representation

The private loader reads independently installed owner configuration and verifies
exact signed records, contiguous predecessor history, immutable profile/policy/pins,
explicit premise acceptance, exact admitted TUF closure and monotonic role floors.
A fresh nonce-bound independently signed current checkpoint must match the full
history/head/floors and assert reconciled continuity. Stored responses cannot grant
current authority. The external service must keep its authoritative state outside
both backup domains and withhold reconciliation on uncertainty; local bytes cannot
prove an all-copy rollback did not happen.

Schema-2 approval evidence retains exact signed record bytes/signatures, their
approval digest, complete lineage, checkpoint and verification-key bytes. The
existing protected evidence representation suffices. Legacy approval evidence
keeps its original reader and bytes. Historical inspection verifies retained
signatures/metadata without current authorization. Present qualification also
requires independently trusted current lineage and enforces adverse boundaries.
New metadata cannot replace or upgrade the original receipt.

The protected receipt-admission authority gap is that the private insertion
predicate represented the original operation's authority without requiring its
retained approval lineage to remain independently current after evidence/manifest
staging. The eight-line Store check reloads authority after staging and before
protected indexing. Existing persistent evidence representation remains sufficient;
no Store/artifact schema changed. Dispatch
also reloads before transport and after DNS/TLS. Cached object fields cannot extend
approval. Any occupied failure remains terminal, including after reconciliation
and restart. #86 source authorization remains a separate gate.

## Offline evidence

`timestamp.json` and `snapshot.json` are the exact bytes already retained by the
2026-10-10 activation audit in its temporary evidence directory, copied locally.
Their audited SHA-256 identities are respectively
`bfce2fedd5a37044f1e48fbc4dcadf4dc8f8835f7d6f5e1414446bcb9f926975` and
`6d61405faa993ba3d07556b79d1e319627cdc06ff879a7b5700967dc25d1d224`.
Roots11-15, targets14 and TrustedRoot reuse the previously released offline fixture.
This implements no network refresh. The fresh closure authenticates timestamp804,
snapshot166 and the unchanged profile/pins. Timestamp799 cannot qualify intervals
at or beyond `2026-10-10T01:39:25Z`.

The owner tests cache TUF authentication only after real verification of exact
immutable fixture bytes. Every mutated closure runs existing cryptographic checks;
every owner record/checkpoint signature is verified afresh. Witness cryptography
also runs independently in the existing retained-wire tests. New operation tests
use the agreed synthetic complete-graph/response seams from #81. The actual
protected Store and ArtifactStore transitions run, including the real transport's
post-TLS dispatch check and a real local Unix-socket checkpoint exchange.

Executed checks and review results are recorded at delivery below. Intermediate
interrupted batches were superseded; only final completed results count.

## Remaining operational prerequisites

An operator must independently provision the owner verification key/configuration,
secure signing administration, deployment/catalog/history identities, append-only
history, and a live checkpoint service with nonrollback authoritative head/floors
and authenticated Store/history restore reconciliation. The owner must sign an
applicable prospective approval accepting the exact ADR 0005 premises and admit
an exact compatible TUF closure whose complete event interval remains valid.
No production authority or approval is supplied here. The retained timestamp799
is expired; timestamp804 is test evidence, never an operational approval.

Separate real-source authorization must be approved and operational for the exact
freeze, selection, profile and seven scopes. Actual prospective work must start on
an eligible unoccupied Matchweek, complete the unchanged exact graph, and succeed
on the sole bound RFC3161 event with `U < T` and protected receipt. Collection and
all these operational steps remain outside #87. #70 stays OPEN with `needs-info`;
#86 stays CLOSED. F17/F18/F20, #70/#37 fitting, PLAY and promotion remain blocked.

## Completed validation

| Check | Result |
| --- | --- |
| `pytest -q tests/test_causal_activation.py` | 98 passed in 221.97s; `activation-completed.txt` |
| `pytest -q tests/test_causal_protocol.py tests/test_causal_witness.py` | 121 passed in 213.18s; `protocol-tests.txt` |
| Focused V1 fresh receipt/replay, V1-to-causal refusal, generic reserved-role protection, `test_cb01_trust.py`, released CB01/method identity | 16 passed in 269.60s; `compatibility-final.txt` |
| Strict mypy on four changed production modules and two test files | Passed; `mypy.txt` |
| Ruff and formatter on all changed Python plus executable compatibility proof | Passed; `ruff.txt`, `format.txt` |
| Executable baseline comparison | Passed; `compatibility.py`, `compatibility-static.txt` |
| New local Markdown links, fenced blocks, envelope/premise/continuity documentation | Passed; `docs-check.txt` |
| `git diff --check` | Passed; `diff-check.txt` |
| Independent Standards/Spec review, root-prefix fix and Store-scope re-review | No outstanding blocker; `review.md` |

235 focused offline tests passed. No full suite ran. The broader V1 batch was
stopped after ten passing cases because it repeated expensive unchanged graph
construction; the completed 16-test compatibility batch supersedes it. Interrupted
intermediate owner runs also do not count. Read-only inspection confirms the fixed
default owner installation path is absent; no production Store was opened.

Delivery SHA and final #87/#70/#86 tracking state are recorded in the subsequent
repository status entry. Completion supplies mechanics only. Every operational
prerequisite listed above remains external and unprovisioned.

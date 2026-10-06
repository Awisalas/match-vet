# Issue #75 completion-protocol investigation

Design and isolated proof records only. Production #75 is not implemented here, and
#76 remains blocked. The accepted specification is
[`matchweek-selection-completion-protocol.md`](../../docs/design/matchweek-selection-completion-protocol.md).

## Decision

Use an atomic immutable selection slot followed by one protected indexed generic
SnapshotManifest receipt. A fresh successful WAL/FULL selection commit is followed by
a repository UTC upper-bound observation strictly before T. Only the same nonreentrant
live operation may publish its receipt once. The receipt may persist after T: its
subject is the earlier selection commit, not its own publication deadline.

An occupied selection without a valid indexed receipt is terminally unqualified.
Restart cannot mint authority, adopt orphan evidence or replace the selected candidate.
Both ArtifactStore and structured StoreTransaction publication need guarded internal
hooks in future production #75. No SQLite or generic manifest payload migration is
needed by the chosen representation.

## Evidence map

| Records | Purpose |
| --- | --- |
| `requirements.md`, `grounding.md`, research note | Semantic deadline, repository seams and primary-source persistence/time contracts. |
| `candidate-snapshot.md`, `candidate-filesystem.md`, `arena-rubric.md`, `arena-result.md`, `synthesis.md` | Independent protocol comparison and the chosen indexed base plus private authority graft. |
| `prototype_protocol.py`, `proof-results.json`, `proof-run-final.txt` | Latest executable temporary-store proof and its observed output. |
| `proof-results-initial.json`, `proof-results-36.json`, `proof-run-36.txt`, `proof-results-37.json`, `proof-run-37.txt` | Preserved earlier proof checkpoints, superseded by final refinement. |
| `prototype.html`, `check_html.cjs`, `html-check.txt` | Interactive memory-only state walkthrough and executable reducer checks; no persistence claim or browser-rendering verification. |
| `review-prompt.md`, `interrogation.md`, `trail-review.md`, `decisions.tsv` | Independent attacks, resolved findings and append-only decision trail. |
| `issue75-before.json`, `issue75-proposed.md`, `issue75-after.json`, `tracking-before.json`, `tracking-after.json` | Acceptance clarification and unchanged open/blocked state. |
| `prior-evidence-sha256.json`, `preservation-check.txt` | Original failed storage-proof files remain unchanged. |
| `staged-scope.json`, `publication.json` | Authorized staged paths and confirmed design/proof publication to main. |

The baseline hash file includes an ignored Python bytecode cache as a local preservation
check. All 14 durable original files are committed; generated cache files are not.
The original failed proof remains valid for the old APIs, even though the clarified
semantic deadline permits later receipt persistence.

## Reproduce

From the repository root:

```sh
PYTHONPATH=src python .audit/issue-75-completion-protocol/prototype_protocol.py
node .audit/issue-75-completion-protocol/check_html.cjs
```

The Python script creates only deterministic synthetic data in private temporary stores
under the Termux temporary directory. It models proposed publication guards, exercises
actual SQLite/catalog/object publication and exits child processes at injected crash
boundaries. It does not open live stores or acquire external data.

## Limits

These records prove ordering branches and process recovery under the stated premises.
They do not prove full F16 lineage integration, production API guard coverage, hardware
power-loss behavior, a live UTC error bound or protection against privileged/raw SQL
writers. Trust assumes one authoritative catalog history, honest WAL/FULL storage and a
real UTC upper bound. An old backup or independently writable clone cannot replace that
history and become a fresh authority. Without a trusted absolute-time bound, local time
observations cannot distinguish a timely execution from a late execution with clock
rollback; the repository must refuse.

Prior directly affected persistence/F16 regression results are preserved in the original
storage-proof directory. They were not rerun for this design-only change. No production
modules, migrations, immutable artifacts or historical manifest readers were edited.

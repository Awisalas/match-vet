# Issue #75 storage deadline blocker

Implementation stopped at the user's required storage proof gate. No selection owner,
schema change, new production payload, or downstream writer gate was added.

## Executed proof

Run from the repository root:

```sh
PYTHONPATH=src python -m pytest .audit/issue-75-storage-proof/test_storage_deadline.py -q -s
```

The four tests pass. Three compare a successful pre-T publication with publication at T,
publication after T, and a real process exit immediately after a late catalog commit.
They use the real ArtifactStore, FULL-WAL SQLite commits, and Store reopen verification.
Only the repository clock and SQLite commit boundary are injected. Every store lives in
a temporary private directory and every artifact is synthetic.

All four publication histories retain identical SnapshotManifest bytes and digest
`3dd09e5c19a248c3726187f754d9e571bf311d14ee68893bc8e131bb81f59d65`.
After restart, each has `verification_state=VERIFIED`, `completeness=COMPLETE`, and
the same verification time before T. No caller verification timestamp is supplied.
The crash case exits before publish_manifest returns or any completion check can run.
See `storage-proof-final.txt` for the final observed output. The earlier
`storage-proof.txt` also passed before the type-check correction to boundary injection.

The fourth test proves concurrent Store handles are excluded by the writer lock.
It does not prove a new domain selector's competing-proposal behavior.

## Exact missing guarantee

`src/matchvet/artifacts.py:637` samples the repository verification clock before object
publication at line 654 and the catalog transaction at line 656.
`src/matchvet/store.py:4361` commits the transaction. Existing persistence has no
durable record distinguishing a confirmed pre-T completion from the other histories.

`UNIQUE(snapshot_id)` and the writer lock provide immutable single assignment.
They do not establish the completion deadline. Treating the indexed verified manifest
as selected after restart would qualify the equality, late, and unconfirmed crash cases.

A check after commit can refuse a late job while the process runs, but that check's
result is absent after a crash. A second completion manifest alone moves the problem
to its own commit. Its clock is sampled before its publication, and its final durable
write can cross T before the process confirms completion. Deleting or rejecting it
after a late completion leaves a crash window and conflicts with immutable catalog rows.

The required missing contract binds confirmation of the final durable selection write
to a repository-controlled instant strictly before T, with a recovery discriminator
for interrupted or late confirmation. The existing API and manifest fields do not
provide that contract. This proof does not establish that every possible future storage
protocol is impossible. An explicitly agreed completion protocol is required before
adding an owner or changing persistence. A schema addition alone supplies no clock proof.

## Compatibility and scope

Production source, tests, migrations, accepted architecture, historical audit evidence,
and immutable artifact identities have no changes from this run. Proof artifacts and
the append-only decision trail are local under this new audit directory.

#75 remains open and #76 remains blocked by it. No commit, push, issue closure, or live
operation was performed. Existing directly affected persistence and F16 checks are
recorded separately in `regressions.txt`: 22 passed, 35 deselected. Final Ruff, format,
and mypy checks pass in `ruff-final.txt` and `mypy-final.txt`; `git diff --check` is clean.

# Issue #75 implementation evidence

Implementation baseline: `5c70bb2`. Only isolated temporary stores and synthetic
deterministic data were used. No live SQLite store, fixture acquisition, timestamp
request, new migration, or full-suite run was part of this implementation.

The append-only decision trail is `decisions.tsv`. Historical proof directories
remain untouched; `preservation-before.json` and `preservation-check.json` compare
55 original records. Early failed and interrupted runs are retained as evidence;
their names do not imply success. The definitive result is each file's pytest summary.
Three traceback display copies omit trailing whitespace for `git diff --check`;
their `.raw.gz` companions preserve the exact original bytes, with hashes in
`raw-log-hashes.json`. No preexisting audit record was reformatted.

## Completed verification groups

| Evidence | Scope | Result |
| --- | --- | --- |
| `green-01c.txt` | First complete, real two-member graph seal and replay | 1 passed |
| `red-02-traced.txt`, `green-02.txt` | Sync crossing T exposed and then fixed the precommit gate | Failed assertion, then 1 passed |
| `protocol-03.txt` | Clock, cutoff, uncertain selection, late receipt and ambiguous receipt return | 14 passed |
| `guards-crashes-04.txt` | Reserved role guards and five real process crash boundaries | 11 passed |
| `integrity-06.txt` | Corruption, incomplete lineage, orphan objects, fsync, capabilities, shared gate and wrong mappings | 26 passed |
| `proposals-05.txt` | Valid alternate proposals, historical F07 and process competition | 5 passed |
| `lifetime-durability-07.txt` | WAL/FULL, transaction boundary and close lifetime | 4 passed |
| `final-fresh-sync-08.txt` | Final fixture success and strengthened object/directory sync assertions | 2 passed |
| `final-exact-replay-09.txt` | Full exact replay after T with no qualification clock | 1 passed |
| `storage-regressions.txt` | Complete ArtifactStore and Store test modules | 48 passed |
| `f16-regressions.txt` | Existing F16 tests in the F15 test module | 2 passed |
| `mypy-pinned.txt` | Four changed production modules and two test modules, pinned mypy 1.18.2 | Success, 6 files |
| `ruff-final.txt`, `format-final.txt` | Six changed Python modules plus executable codec proof | Passed, 7 files formatted |
| `legacy-identity-proof.json` | Real baseline/current SnapshotManifest codec and migration checksum comparison | Both digests and all 14 checksums match |

All 62 final focused cases have completed passing coverage across these groups;
the final sync rerun duplicates one integrity case. `collection-final.txt` lists the
final cases. The interrupted reviewer subset is not counted; see
`reviewer-interruption.md`. Test subsets
were selected as implementation progressed; their deselection counts therefore refer
to the collection at the time of each run.

## Review and limits

`spec-review.md` and `standards-review.md` contain independent source reviews.
`trail-review.md` records the required different-model audit review.
`blast-radius.md` connects the failure-path evidence to the safety claims.
The trail reviewer identified two completion bookkeeping gaps. This final summary
and the appended verification checkpoint supply the omitted group pointers and
completed replay result without rewriting earlier decisions.

Code correctness is established under the accepted storage and clock contracts.
No operational live UTC confidence or hardware durability proof was performed.
Prospective qualification refuses with the default production clock.

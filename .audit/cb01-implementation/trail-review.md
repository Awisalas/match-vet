# CB01 decision trail review

Reviewed Codex session `01a10a7a-6bb7-72b0-83dd-108a3ee069f4` through `2026-10-05T11:27:45Z`. Its first-line `payload.cwd` is exactly `/data/data/com.termux/files/home/projects/match-vet`. No transcript from another project was inspected.

## Closed findings

The appended rows close the initial gaps for fractional RFC3161 time, complete denominator versus row readiness, the invalidated 29-pass/2-fail run, affected upstream regressions, the stable outcome seam, TUF rollback protection, CandidateInput lineage, static checks, and the source-stable full CB01 rerun. The transcript supports the recorded results:

- Full CB01 suite: 31 passed in 1276.18 seconds, with the recorded `cb01.py` digest unchanged during the run.
- Affected F13/F14/F15/F19 suite: 28 passed in 771.87 seconds.
- Stable outcome seam: 1 passed in 620.01 seconds.
- `ruff check src tests` and `ruff format --check src tests`: pass across 102 Python files. `uv run mypy`: no issues in 102 source files. `git diff --check`: pass.

The later stable outcome, trust, and lineage rows give durable test evidence for the earlier T10, metadata-floor, CandidateInput, and F19 claims. This supersedes the original temporary `/usr/tmp` evidence pointers without rewriting history.

## Reconciliation

- The `11:23Z` performance correction identifies the actual CB01 optimization: per-call verified outcome and fact digest sets in `BootstrapRepository.replay`. It explicitly distinguishes the adjacent, pre-existing F19 lineage cache.
- The `11:23:15Z` row records project-wide mypy passing for 102 source files.
- The `11:24Z` correction separates full F19 projection evidence from recovery retry evidence and points to the exact tests for both.
- The `11:24:15Z` correction explicitly supersedes the earlier unqualified Ruff and format statements. `src tests` passes; default walks report unrelated `.audit` and Markdown findings that were left untouched.

I found no remaining missing decision, invented action, unsupported result, or unresolved drift in the decision trail.

## Final gate status

The functional and scoped quality gates are green. The failed overlapping-source run remains recorded and is superseded by the source-stable 31-pass run. The broad all-files Ruff and formatting diagnostic reports only unrelated workspace artifacts outside the chosen `src tests` quality scope, and the trail states that scope accurately.

At the reviewed transcript boundary, commit, push, roadmap publication, and issue closure were still pending. The release row says they are ready to proceed; it does not claim they already happened.

The decision trail is reconciled with the matching workspace transcript.

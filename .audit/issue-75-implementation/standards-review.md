# Issue 75 Standards review

Reviewed staged changes against baseline `5c70bb2`. Sources included AGENTS.md,
docs/agents/domain.md, GLOSSARY.md, pyproject.toml, ADR 0001, the accepted completion
protocol, and existing Store/ArtifactStore/F16 readers beyond the diff.

No hard documented Standards violations found.

One optional judgement call: possible Duplicated Code. Corrected F07 policy and
common-cutoff validation recur at src/matchvet/matchweek_research.py:168 and :304.
A private common-boundary validator could prevent future drift. This is not a blocker.

Safety inspection found:

- ArtifactStore rejects qualifying reserved mappings before idempotent publication
  at src/matchvet/artifacts.py:597. Structured insertion independently rejects them
  at src/matchvet/store.py:4894.
- Existing selections route directly to replay at
  src/matchvet/matchweek_research.py:246. Receipt ambiguity permits only indexed
  read-only replay at :282. No recovery publication path was found.
- Authority requires original Store/PID/thread ownership at src/matchvet/store.py:4660,
  consumes its receipt attempt before publication at :4670, and revokes on exit at
  :4390. The existing UNIQUE(snapshot_id) and immutable-index triggers remain intact.
- Forging a different logical mapping can poison availability, as explicitly accepted
  by the protocol. Exact domain replay refuses qualification.
- SnapshotManifest canonical encoding and existing reader validation are unchanged.
  The historical canonical/reader subset passed: 3 passed, 15 deselected in 10.42s.

The focused executable safety run and its final result are recorded separately in
reviewer-safety-tests.txt. No live stores, full suite, or network were used.

# MatchVet

MatchVet is a zero-cost, local-first football research and betting-preference vetting engine. The initial product runs in Termux and remains in RESEARCH_ONLY mode until its Selection Policy earns Production Promotion.

T01 provides the installable command-line baseline only. It does not create a database, ingest football data, or make recommendations.

T02 adds the authoritative local SQLite store. See [the local store guide](docs/local-store.md) for its private-storage, migration, and recovery contracts. It still does not ingest football data or create recommendations.

T03 adds immutable content-addressed artifacts and deterministic Snapshot Manifests. See [the artifact guide](docs/artifacts.md) for publication, verification, and orphan-reporting contracts.

T04 adds bounded foreground runs, resource preflight, durable phase checkpoints, status,
and digest-verified resume. See [the run lifecycle guide](docs/run-lifecycle.md). T04 remains
RESEARCH_ONLY and publishes no match decision or report.

T06 adds deterministic all-seven-league fixture and structured match-history ingestion from the
approved Football-Data.co.uk source, with OpenFootball as the permitted fallback where covered.
Use the explicit ingestion command to acquire current data; add one or more `--history-season`
options for historical imports. T06 does not freeze matchweeks, add contextual evidence, or make
predictions.

T05 freezes Matchweek membership from those acquired Fixture Revisions. See the [Matchweek freeze
guide](docs/matchweek-freeze.md). It records the immutable Friday-to-Monday membership manifest,
cutoff, controlling revision digests, and post-cutoff appendix while remaining RESEARCH_ONLY.

T07 records official and contextual Source Evidence against canonical fixtures, teams, and people.
See the [Source Evidence guide](docs/source-evidence.md). It preserves retained or citation-only
captures, independent origins, explicit OBSERVED/ABSENT/UNKNOWN states, cutoff classification,
corroboration, corrections, and conflicts without researching, predicting, or recommending.

## Bootstrap

Use the pinned native Termux packages and Python environment described in [the Termux environment guide](docs/termux-environment.md). Then run:

    scripts/bootstrap-termux.sh
    .venv/bin/matchvet
    .venv/bin/matchvet doctor
    .venv/bin/matchvet run 2026-09-18
    .venv/bin/matchvet status
    .venv/bin/matchvet resume RUN_ID
    .venv/bin/matchvet ingest --season 2026-27 --history-season 2025-26 --json
    .venv/bin/matchvet freeze 2026-09-18 --season 2026-27 --json

To inspect a configured store without changing it:

    .venv/bin/matchvet doctor --store /path/in/termux/private/storage/matchvet.sqlite3

## Checks

    ruff check .
    ruff format --check .
    .venv/bin/mypy
    .venv/bin/pytest

The default test suite is deterministic and does not use the internet.

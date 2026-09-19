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

T08 builds cutoff-valid workload and venue-weather Evidence for frozen Target Matches. See the
[workload and weather guide](docs/workload-weather.md). It derives rest, turnaround, density,
congestion, and cross-competition context from canonical Fixture Revisions, retains verified
Open-Meteo provenance, represents unavailable weather as UNKNOWN, and remains RESEARCH_ONLY.

T10 grades all 37 v1 Betting Preferences from recorded, approved Fixture evidence. See the
[settlement grading guide](docs/settlement-grading.md). It applies the fixed source hierarchy,
keeps pending and VOID distinct, excludes extra time and shootouts, and appends corrections
without rewriting frozen Matchweek state.

T16 publishes complete Matchweek Audits and concise deterministic Matchweek Reports. See the
[Matchweek report guide](docs/matchweek-reports.md). A complete audit retains every Target Match,
all 37 preference evaluations, evidence and reproducibility metadata; the report is the concise
production or explicitly `RESEARCH_ONLY` projection.

T17 adds marker-gated Matchweek export and verified private recovery copies. Shared export and
backup directories are never authoritative or executable state; restore activates only a new
private target after every digest and SQLite integrity check passes.

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
    .venv/bin/matchvet grade --input /path/to/fixture-evidence.json --store /path/to/matchvet.sqlite3 --json
    .venv/bin/matchvet report --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet report --audit --json --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet inspect FIXTURE_ID --json --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet history --json --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet export --store /path/to/matchvet.sqlite3 --destination /shared/matchweek-export
    .venv/bin/matchvet backup --store /path/to/matchvet.sqlite3 --destination /shared/matchvet-backup
    .venv/bin/matchvet backup --verify /shared/matchvet-backup --json
    .venv/bin/matchvet restore --source /shared/matchvet-backup --target /private/restored/matchvet.sqlite3

To inspect a configured store without changing it:

    .venv/bin/matchvet doctor --store /path/in/termux/private/storage/matchvet.sqlite3

## Checks

    ruff check .
    ruff format --check .
    .venv/bin/mypy
    .venv/bin/pytest

The default test suite is deterministic and does not use the internet.

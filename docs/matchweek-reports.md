# T16 Matchweek Audits and Reports

T16 is the publication boundary after T05 membership, T09 frozen Evidence State, and T15
preference vetting. It publishes only a complete run: every INCLUDED Target Match must have one
evaluation for each of the 37 T10 preferences. A missing match, duplicate or missing preference,
mixed policy mode, or incomplete run creates an `INCOMPLETE` audit and cannot create a completed
report.

## Production and research output

Production output uses `PRODUCTION` mode. A `PLAY` card has a `Primary Recommendation`, optional
`Correlated Secondary Fits`, exact preference and line, estimated and conservative probability,
uncertainty, Data Quality, Model Agreement, failure-risk assessment, strongest support and
credible failure case, material evidence gaps or conflicts, historical baseline, and why it ranked
above alternatives. Match-level failures are compact `AVOID MATCH` entries with standardized
rejection categories and reason codes. Withdrawn fixtures are `Withdrawn / VOID` and never become
PLAY or AVOID MATCH.

Research output is explicitly `RESEARCH_ONLY — NOT A RECOMMENDATION`. It uses `Primary Candidate`,
`Correlated Secondary Candidates`, and `RESEARCH AVOID`; it never renders production `PLAY` or
`AVOID MATCH` labels. The audit still retains the complete Vetting Matrix, gates, distributions,
rejection reasons, decisions, evidence identities, snapshot references, policy/model versions,
and the reproducibility record.

## CLI

Read-only readers resolve only the final publication marker:

    .venv/bin/matchvet report --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet report --audit --json --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet inspect FIXTURE_ID --json --store /path/to/matchvet.sqlite3
    .venv/bin/matchvet history --json --store /path/to/matchvet.sqlite3

T17 operational copies are explicit mutating commands with their own marker and recovery
verification contracts:

    .venv/bin/matchvet export --store /path/to/matchvet.sqlite3 --destination /shared/export
    .venv/bin/matchvet backup --store /path/to/matchvet.sqlite3 --destination /shared/backup
    .venv/bin/matchvet backup --verify /shared/backup
    .venv/bin/matchvet restore --source /shared/backup --target /private/restored/matchvet.sqlite3

`report` renders deterministic Markdown by default. `--audit --json` exposes the complete
schema-versioned audit. `inspect` exposes one Target Match, including all 37 preference results.
`history` joins run, audit, grading, mode, and policy state. T17 export and backup/restore status
comes from the dedicated marker-gated operations, which return source/destination, manifest
identity, digest verification, stable failure codes, and recovery guidance in JSON mode.

Audit and report artifacts are written before a final complete-publication marker. Readers ignore
unmarked artifacts, so an interrupted publication cannot appear as a completed report.

T17 export applies the same visibility rule to shared Matchweek copies: the final directory is
never considered publishable until `COMPLETE` verifies the manifest digest and every member. An
incomplete run is refused before destination mutation. The report and audit are deterministic
copies of the T16 publication; the manifest also records reproducibility/version metadata and
rights-safe raw-evidence omissions.

# Fixed active fixture scope

The automatic F01 successor is `fixture-coverage-v4-v4`, schema 4. Its immutable
`active_scope` contains the contract identity, version, season, ordered canonical
league keys, and canonical digest. Version 2 is `matchvet-active-scope-v2` for
2026-27, in this exact order:

1. `premier_league`
2. `serie_a`
3. `la_liga`
4. `bundesliga`
5. `ligue_1`
6. `liga_portugal`

The scope digest is
`sha256:47e48cdf62e8452b9ec869bb99771d975972d6b9514d48e62866bca8f29dbb54`.
It hashes the UTF-8 JSON object containing `contract_id`, `version`, `season`,
and `league_keys`, with sorted keys, ASCII escaping, and compact separators.
F01 includes the complete scope contract in its own canonical digest.
Wrong identities, digests, season, versions, scope counts, or order refuse.
Belgium has no successor scope or UNKNOWN placeholder.

Each required league keeps the existing complete-current and affirmative-empty
rules. Missing evidence remains UNKNOWN. Partial and stale evidence retain their
states. `decode_f01` and `FixtureCoverageRepository.get` dispatch from retained
contract and schema identity without reassessment or current-default lookup.
Old v2 and operator-attested v3 keep their seven scopes and canonical bytes.
The existing SQLite representation stores all three F01 versions without migration.

`IngestionPlan.for_active_scope(active_scope=SUCCESSOR_SIX_SCOPE, ...)` binds
`t06-acquisition-plan-v2` and the exact active contract identity and digest.
Its plan digest includes those references. Scheduled acquisition attempts both
existing OpenFootball feeds for each of the six leagues and retains failed
attempts. Responses alone do not establish completeness. No adapter or provider
is enabled by this contract.

`matchvet ingest --scope-version 2 --season 2026-27` explicitly selects this plan.
The default `--scope-version 1` preserves historical plans and hashes. Both routes
retain #89 source authorization and #90 transport behavior. Default live
acquisition refuses without independently supplied current authority.

`matchvet fixture-admission --scope-version 2 --store STORE --json` exposes the
read-only `t05-active-fixture-admission-v2` route. `load_active_fixture_admission`
filters both retained revisions and unresolved rows to the six contract leagues.
A mixed Store can retain Belgian rows for historical T05 freeze replay without
admitting them to this route. The command publishes no freeze. Historical
`matchvet freeze` remains the original route. F06/F07 successor publication is
[#99](https://github.com/Awisalas/match-vet/issues/99).

Qualified zero-cost complete-current sources and independently supplied source
and causal authority remain operational blockers. Capture/cohort integration is
#100, and separate release qualification is #101. See
[ADR 0007](adr/0007-six-active-leagues-without-paid-data.md) and the
[status log](product-v2/CANDIDATE-INPUT-STATUS.md).

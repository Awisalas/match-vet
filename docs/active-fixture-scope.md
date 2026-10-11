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
`matchvet freeze` remains the original route. F06/F07 successor publication uses
the exact repository contracts below, delivered by [#99](https://github.com/Awisalas/match-vet/issues/99).

Qualified zero-cost complete-current sources and independently supplied source
and causal authority remain operational blockers. Capture/cohort integration is
#100, and separate release qualification is #101. See
[ADR 0007](adr/0007-six-active-leagues-without-paid-data.md) and the
[status log](product-v2/CANDIDATE-INPUT-STATUS.md).


## F06 policy3 and F07

`MatchweekMembershipRepository.freeze_exact` accepts membership policy `3` only
with automatic `fixture-coverage-v4-v4`, schema 4, and the exact scope v2 above.
Its canonical policy JSON binds the complete active contract, including its digest,
and the F01 contract/schema pair. The envelope remains
`matchweek-membership-freeze-v2`, payload version 1.

| Membership policy | Admitted F01 contracts | Population |
| --- | --- | --- |
| 1 | v2/schema2 or operator-attested v3/schema3 | Historical seven |
| 2 | v2/schema2 or operator-attested v3/schema3 | Historical seven with LF14 integrity |
| 3 | Automatic v4/schema4 only | Fixed six with LF14 integrity |

There is no current-default dispatch. Every required scope must be COMPLETE or
source-backed CONFIRMED_EMPTY. All six affirmative-empty scopes may freeze with
zero members. UNKNOWN, PARTIAL, STALE, identity blockers, and missing provider
health prevent freeze. The policy preserves controlling revisions, exact fixture
and team identities, INCLUDED/EXCLUDED decisions, provenance, and digests.

The policy2-only branches audited for policy3 are:

| Branch | Inherited rule | Regression coverage |
| --- | --- | --- |
| Policy document and codec validation | Same LF14 semantics, precision ordering, and mandatory integrity snapshots | Policy hashes, semantic roundtrip, omitted snapshot refusal |
| Membership revision loading | Ordered confirmed canonical teams, home/away roles, typed kickoff, exact revision content and complete assertion references | Alias compatibility, reversed roles, content/status corruption, omitted assertions |
| Membership conflict selection and projection | Exact selected assertions backed by cumulative history; controlling-tier semantic conflict refusal | Compatible DATE/INSTANT and status classes; disagreement, history omission, A/C projection of A/B/C history |
| Replay reference validation | Exact frozen integrity facts and complete material conflict projections, including history digests | Omitted integrity/projection and changed canonical assertion refusal |
| Observation revision loading and conflicts | The same exact revision and cumulative-history integrity | Later source-backed observation and immutable original freeze |
| Observation identity resolution | Only explicit stable candidate state changes establish resolution | Changed candidate ID alone produces no resolution |

Policy3 also refuses duplicate stable candidate IDs and reassignment of a stable
candidate to another fixture or scope. A frozen resolved candidate cannot become
unresolved under that same identity. Malformed typed identities refuse. These
additional checks do not alter historical policy1/2 observation semantics.
Observations retain their original freeze ID and exact later F01 digest; a six/seven
cross-attachment or changed active contract refuses on both write and replay.

F07 policy3 admission requires the explicitly supplied 21600-second lead time and
`MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME`. T uses the earliest exact
kickoff among the actual six-scope INCLUDED memberships. An excluded fixture or
retained Belgian revision cannot control it. F07 binds the exact freeze and member
IDs/digests, which bind policy3 and F01 v4. Historical cutoffs keep their original
freeze lineage and bytes. No scope substitution occurs during replay.

The existing SQLite tables, immutable triggers, protected artifacts, and backup
format support policies 1/2/3 together. No migration is required. Capture/cohort
integration remains #100; this contract supplies no live source or causal authority.

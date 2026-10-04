# F09 contextual provider health

## Problem

`provider-health-v1` supports generic `RequestedScope` values, but F05 persistence
requires exact F01 fixture provenance. F06 membership health references also depend
on the existing fixture table. Open-Meteo weather health therefore needs separate
storage behind the existing repository API.

## Usage

The repository accepts the same immutable `ProviderHealthRecord` for either path:

```python
repository = ProviderHealthRepository(store)
(digest,) = repository.persist_many((weather_health,))
assert repository.get(digest) == weather_health
repository.persist_many((fixture_health, weather_health))
```

T08 automatically records observations at its existing fetch and parse seam.
Independent weather acquisition can opt into the same behavior:

```python
batch = WeatherEvidenceBuilder(
    client, provider_health_repository=ProviderHealthRepository(store)
).build(targets)
for observation in batch.provider_health_records:
    assert repository.get(observation.digest) == observation
```

`T08BuildResult.provider_health_records` exposes the recorded observations.
These audit values do not change the weather evidence payload or its digest.

## Shape

Migration 14 creates `contextual_provider_health_records` with immutable canonical
JSON and digest. Its unique observation key is:

```text
provider_id + capability_id + requested_scope.scope_id
    + intended_use_id + checked_at_utc
```

Only `open-meteo` and `weather-forecast` are admitted. The repository retains the
complete generic scope, including unknown and unbounded facets. It recomputes the
scope digest and compares indexed metadata on replay. Identical records are
idempotent; changed content for an existing key fails. A digest found in both health
tables is an integrity error.

`persist_many` routes typed fixture scopes through the existing F05 metadata and
reference validation. Contextual records use private metadata and replay helpers.
One store transaction covers mixed batches. Fixture history queries continue to
read the existing table. All earlier migration statements and F04 canonical
encoding remain unchanged.

`OpenMeteoHealthRecorder` owns the approved non-commercial T08 permission policy
and outcome mapping. It consumes the real `WeatherRequest`, HTTP response, parser
result, or original exception. Query identity includes the target, venue, interval,
request URL, exact request cache key, and cutoff. A response or parser result from
another query is refused. Observation time is the health check time; a cached
response does not substitute its older retrieval time for that check.

The recorder commits health before weather is returned to its consumer. A health
write failure propagates. It never publishes weather evidence or supplies F01
fixture provenance. No query means no invented provider observation, including
missing venues and absent clients. Unresolved F08 families remain outside F09.

## Health dimensions

Permission denial retains `NOT_PERMITTED` and explicit failure. An unavailable
request retains failure and unknown structural validity and coverage. A malformed
response establishes reachability and invalid structure, while capability
availability and coverage stay unknown. Post-cutoff forecasts retain an explicit
failure. A usable partial forecast records its missing requested variables or
interval as coverage gaps. Missing all requested variables or the target interval
also retains an explicit coverage failure; HTTP 200 alone cannot establish complete
coverage. Existing weather evidence reason codes remain unchanged.

T08 cutoff eligibility does not define a source-age freshness policy. Acquisition
observations therefore retain `UNKNOWN` freshness. The repository preserves
caller-supplied `FRESH` or `STALE` assessments with the existing typed policy and
evidence requirements; F09 introduces no numerical age threshold.

## Synthesis decision

Two independent sketches compared inline routing with a private persistence
strategy class. The cross-review selected inline routing for its smaller public
interface. Private contextual metadata and decoding helpers retain the separate
storage invariants without an extra strategy class. The second sketch supplied
the constraint that cutoff validity must not become an invented freshness rule.

We accept small parallel SQL paths to preserve fixture validation and foreign
keys. A public contextual repository would expose routing and transaction ownership
to callers. Rebuilding the fixture table would put F05 and F06 references at risk.

## Blast radius proof

The safety facts are that the migration leaves the fixture table intact and that
mixed writes share one transaction. Both are exercised against real stores:

- `test_migration14_preserves_fixture_store_and_old_canonical_bytes` creates a
  schema-13 store through public APIs, upgrades it, and compares fixture replay and
  canonical bytes. It also proves old applications refuse writes to schema 14.
- `test_failed_contextual_migration_rolls_back_and_fixture_replay_survives` injects
  a failing migration statement, reopens schema 13 for writing, and then upgrades
  successfully. Fixture replay survives both paths.
- `test_corrupted_fixture_retry_rolls_back_a_preceding_contextual_insert` forces a
  real contextual insert before a fixture replay conflict and proves rollback.
- `test_health_persistence_failure_prevents_t08_weather_publication` fails the
  health write boundary and verifies no weather evidence was published.

Tests use public repository, store, T08, and weather APIs. Direct SQL is limited to
corruption and failure injection. Existing F04/F05 tests cover fixture compatibility.

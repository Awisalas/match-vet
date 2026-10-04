# F11 V2 workload and weather evidence

F11 V2 consumes an exact F06 `freeze_id` and F07 `policy_digest`.
`F11EvidenceRepository.build` replays that freeze and all persisted cutoffs
under that policy. Every INCLUDED membership needs exactly one cutoff with
matching freeze, membership, fixture, controlling revision and policy identities.
Missing state is refused. F11 never creates cutoffs or selects a freeze by date.

```python
from matchvet.f11 import F11EvidenceRepository

repository = F11EvidenceRepository(store)
evidence = repository.build(
    freeze_id, policy_digest, weather_client=client,
    context_fixtures=context, locations=locations,
)
replayed = repository.replay(
    evidence.digest, freeze_id=freeze_id, policy_digest=policy_digest,
)
assert replayed.to_bytes() == evidence.to_bytes()
```

Each match uses its own `cutoff_at_utc` for fixture publication and observation
eligibility and weather location, issue and retrieval eligibility. Workload
uses the existing calculator. Weather uses the existing Open-Meteo builder
and F09 health recorder. Post-cutoff weather stays UNKNOWN.

The protected ArtifactStore evidence set embeds exact F07 cutoff snapshots,
workload and weather evidence, exact F09 health digests, retained weather
response envelope digests, one typed F12 attempt reference for each performed
Open-Meteo request, and a fixture-history artifact digest. A match with no
weather request has no F12 attempt reference. Response
envelopes retain the raw body and its digest separately. Their protected objects can coexist with identical V1 response bytes that have REUSABLE retention,
without changing V1 artifact metadata. No database migration or legacy T05
evidence row is needed. Replay verifies predecessor identities,
source captures, exact F07 and F09 references, F12 attempt outcomes and artifact content. It
recalculates workload from retained history and weather from retained responses.
Failure metadata retains the exception type and HTTP status so a network failure
cannot replay with a permission refusal from another acquisition.
`F11EvidenceSet` holds immutable canonical bytes;
`to_dict()` returns a detached copy for research consumers.

F12 attempt artifacts retain the provider, `weather-forecast` capability,
fixture revision, exact F07 cutoff, exact F09 requested scope and health digest,
acquisition outcome, usability, timestamps, response status, and protected
response artifact reference. F09 health alone never makes an attempt successful.
F11 reuses a retained attempt after an interrupted evidence publication and
does not fetch weather again.

The evidence-set artifact uses media type
`application/vnd.matchvet.f11-evidence-set.v3+json` and schema version 3.
F11 weather response envelopes remain at schema version 2. T08 V1 contracts
and artifacts keep their existing versions.

The canonical request includes freeze, policy, rules, explicit context and
location records. The first build captures acquisition for this request.
Repeating it reuses the retained set, even if current fixture history or the
weather client changes. There is no implicit refresh. Conflicting artifacts
for the same request refuse. New explicit context, locations or rules create
a distinct request. Artifact publication timestamps never enter evidence bytes.

## Architecture decision

T05 remains the legacy V1 freeze. F11 V2 uses F06 and F07 directly.
T08 V1 builders, tables, artifacts and readers keep their current contract.

Two designs were considered: one repository that owns build/replay, and a
separate acquisition snapshot with a public evaluation operation. The repository
was selected because callers need only two operations. It retains the second
design's immutable history/response capture and private replay validation.
The review favored the repository's deterministic retry semantics. A public
acquire/evaluate/persist pipeline would make callers coordinate reference integrity.

This accepts a catalog scan for exact request identity in exchange for using
existing persistence. Initial concurrent acquisitions can produce competing
sets; subsequent reads refuse that ambiguity instead of choosing one.

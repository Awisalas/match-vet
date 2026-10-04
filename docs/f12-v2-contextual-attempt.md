# F12 Open-Meteo contextual research attempts

## Problem

F11 already makes the per-match Open-Meteo request, applies its exact F07
cutoff, retains the response, and records F09 Provider Health. Its anonymous
`weather_attempt` fields do not identify the request as a V2 research attempt.
F12 adds that identity without adding another client or changing T08 V1.

## Usage

F11 remains the caller that performs acquisition:

```python
evidence = F11EvidenceRepository(store).build(
    freeze_id, policy_digest, weather_client=client, locations=locations,
)
attempt_ref = evidence.to_dict()["matches"][0]["contextual_attempt"]
attempt = ContextualAttemptRepository(store).get(attempt_ref["attempt_id"])
assert attempt.digest == attempt_ref["digest"]
```

F11 replay validates the attempt and retained response without a client call.
When no request occurs, `contextual_attempt` is `None`.

## Shape

`ContextualResearchAttempt` is an immutable, versioned value. Its deterministic
ID names one Open-Meteo weather request for one fixture, exact F07 cutoff, and
F09 requested scope. Its digest covers the result, timestamps, status, usability,
response artifact reference, and exact health digest. `ContextualAttemptRepository`
validates those references and stores canonical bytes as a protected
ArtifactStore object. F11 stores only the typed attempt ID and digest beside the
existing weather evidence, response reference, and health digests.

`SUCCEEDED` requires a retained parsed response and usable weather evidence.
Unavailable and malformed responses are `FAILED` and `UNUSABLE`. A missing
client or a request blocked by missing or post-cutoff venue data creates no
attempt. F10 retains its `UNPERFORMED` or `UNKNOWN` result for those cases.

F11 checks for an exact retained attempt before calling the WeatherClient. After
an interrupted evidence publication, it rebuilds weather evidence from that
attempt's response artifact and reuses the same health record. The attempt
artifact has no database row, so F12 needs no schema migration.

## Synthesis decision

The repository-owned candidate was selected because it keeps canonical attempt
serialization, protected persistence, and exact joins behind one interface.
The embedded-value candidate would leave F11 responsible for those checks.
The selected design uses an explicit contract version from the embedded
candidate and adds lookup by exact fixture, cutoff, and requested scope so a
retry after attempt retention does not call Open-Meteo again. A separate scope
digest was omitted because F09's `requested_scope_id` already hashes the exact
canonical scope.

The cross-review found that retry behavior needed to cover interruption after
attempt retention, not only replay after F11 publication. The F11 retry test
forces that interruption and checks the client call count.

## Tradeoffs

- F12 scans protected attempt artifacts to find an exact request. This avoids a
  database index and migration while attempt volume remains small.
- F11 evidence uses schema version 3 because it replaces anonymous attempt
  metadata with the typed F12 reference. Weather response envelopes remain at
  version 2, and T08 V1 keeps its current contract.
- A request with no response still has a failed attempt and exact F09 health
  digest. F09 health alone never establishes success.

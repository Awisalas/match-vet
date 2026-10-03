# LF13 official fixture observations

## Problem and grounding

LF02 certifies fixture completeness, including compatible DATE and INSTANT scheduling facts. Certification does not turn the official kickoff an operator sees into a Fixture Revision. F06 requires an observed exact kickoff. LF13 fills that gap through LF05's existing manual observation repository.

The CLI calls `OperatorFixtureObservationRepository.record`. That repository validates publication identity, resolves existing teams, normalizes kickoff time, and persists an immutable observation through `FixtureHistoryImporter` with `KNOWN_ONLY`. T04 stores the protected artifact, capture, four assertions and Fixture Revision. LF10 replay compares immutable facts except observation time and digest. LF12 verifies the whole chain for F01 persistence and F06. Fresh acquisition now includes verified manual captures from each requested scope.

## Usage

The league selects the version. Belgium uses observation policy v1. Premier League, Serie A, Bundesliga and Ligue 1 use v2 for season 2026-27.

```sh
matchvet fixtures observe official record \
    --store /private/matchvet.sqlite3 \
    --league premier_league --season 2026-27 --friday 2026-10-09 \
    --home Arsenal --away Chelsea --kickoff 2026-10-10T15:00:00+01:00 \
    --status SCHEDULED \
    --official-url https://www.premierleague.com/en/news/1235133 \
    --publication-id premier-league-updating-calendar \
    --publication-type UPDATING_CALENDAR \
    --title 'Official schedule reviewed by operator' --operator-id operator:research
```

This example illustrates the command shape; it does not assert that this pairing occurs on that date. Both names must already resolve in the specified store.

Application callers retain `record(input)`, `get(artifact_digest)` and `list_for_scope(scope_id)`. F06 retains `verify_operator_fixture_observation_capture(store, capture_id, expected_scope_id=...)`.

## Shape

The existing observation dataclass retains its field envelope and canonical digest algorithm. Construction accepts only the exact contract/schema/policy tuples v1/1/1 or v2/2/2, then binds the tuple to the supported league. V2 requires INSTANT. Belgian policy rules, source identity and golden artifact bytes remain unchanged.

The design sketch adds these interfaces behind the repository:

```python
class OperatorFixtureObservationPolicyV2:
    league_key: str
    season: str

    def validate_publication(
        self, *, scope: FixtureScope, publication_id: str,
        publication_type: str, official_url: str,
    ) -> None:
        # Match actual scope and citation with LF02 policy v2.
        # Require exact_schedule and canonical scheduling resource paths.
        raise NotImplementedError


def operator_fixture_observation_policy_v2(
    league_key: str,
) -> OperatorFixtureObservationPolicyV2:
    raise NotImplementedError
```

LF02 owns `matching_official_publication_rule` and the frozen v2 publication registry. The observation policy derives publisher and competition identity from that registry and binds its own digest to LF02's policy digest. It adds exact-scheduling restrictions and rejects query strings, fragments, credentials, invalid ports, traversal and unrelated path suffixes. It does not copy an official host allowlist.

| League | Approved scheduling publication IDs |
| --- | --- |
| Premier League | `premier-league-updating-calendar` |
| Serie A | `serie-a-calendar-results`, `serie-a-anticipi-posticipi` |
| Bundesliga | `bundesliga-confirmed-kickoff-updates` |
| Ligue 1 | `ligue-1-programmation` |

V2 uses a separate `official-fixture-manual-citation-v2` source identity. The verified artifact records the actual publisher, competition, publication URL/title/date, operator, observation time and policy identity/digest. The verifier derives source metadata from ingestion's rights registry and binds that source kind to the artifact's validated league/version. Its existing assertion, fixture and revision checks remain shared.

## Synthesis decision

Two structural candidates were examined: version dispatch in one observation value, and an independent v2 value with a union codec. The independent judge preferred the separate value for stronger static separation. The chosen design keeps one value because fields and provenance are identical, while strict version tuples and league policy checks enforce the difference at construction. The existing golden artifact provides a direct compatibility check. A separate value would repeat fields or add inheritance and union dispatch without hiding more behavior from callers.

The design adopts both candidates' separate source identity, shared LF02 matcher, policy digest binding and version-neutral verifier. Review removed a synthetic publication scope and added traversal rejection after a failing regression test. No repeated implementation friction required scrapping the design.

## Tradeoffs and boundaries

The value can represent two contracts; runtime validation enforces exact version and league combinations. V2 narrows LF02 publication matching with its own versioned resource-path restrictions. A generic v2 source identity covers four publishers; authenticated observation fields retain the specific publisher provenance.

Manual observations are RESEARCH_ONLY and create no Provider Attempts, Provider Health or completeness certification. No store schema or migration changes. After recording exact observations, acquire a fresh assessment and complete LF02/F05/F06 separately. LF13 does not perform the real all-seven validation, close #44 or unpark F07.

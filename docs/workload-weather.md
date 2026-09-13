# T08 workload and weather evidence

T08 is a research-only evidence boundary. It reads the frozen T05 Matchweek and
cutoff-valid T06 Fixture Revision history, then derives schedule context for
each frozen Target Match. It does not predict, grade, rank, recommend, or make
the T09 Research Sufficiency decision.

## Workload

The canonical fixture identity is the source fixture ID plus its immutable
revision identity. Postponed and rescheduled revisions are selected once at
the Research Cutoff; duplicate source observations of one revision are merged
for provenance. Conflicting observations remain explicit and make affected
workload UNKNOWN rather than manufacturing zero rest.

Workload includes:

- elapsed rest days and the exact turnaround before the Target Match
- 7-, 14-, and 28-day unique-fixture density
- all canonical turnaround periods in the configured lookback window
- congestion periods at or below the 72-hour threshold
- domestic-cup, continental, international, and other explicitly sourced
  schedule context without double counting a canonical fixture

Context fixtures are persisted append-only in `workload_schedule_events` with
source locator, observation time, revision identity, cutoff eligibility, and
provenance. Unknown kickoff, postponed/cancelled state, and material conflicts
remain auditable in the derived payload.

## Weather

Weather is Important Evidence. T08 asks only the approved Open-Meteo forecast
endpoint for eligible frozen Target Matches with verified venue coordinates.
Missing venue coordinates, an unavailable client, malformed data, a mismatched
location, an uncovered kickoff interval, or a post-cutoff response produces
`UNKNOWN`; it is never treated as a normal weather observation.

An observed forecast retains the model, issue time and issue-time source,
retrieval/capture time, forecast target and interval, returned coordinates,
verified location provenance, values, units, endpoint attribution, response
status, and content digest. Both forecast issue time and capture time must be
at or before the Research Cutoff for `CUTOFF_VALID` frozen input. Raw valid and
cutoff-classified response bodies are retained as reusable artifacts.

Open-Meteo requests use a private content-addressed cache with a one-hour TTL,
bounded response size, and the routine 250 MiB network budget. T04 owns the
run checkpoints. Durable per-target evidence, immutable artifacts, and cache
reuse make an interrupted evidence phase resumable without silently changing
the frozen input.

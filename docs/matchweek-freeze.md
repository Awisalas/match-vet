# T05 Matchweek freeze

T05 turns the append-only T06 `Fixture Revision` history into one immutable
`Frozen Matchweek Membership` record. It remains `RESEARCH_ONLY`: this layer
does not collect contextual evidence, calculate predictions, grade matches, or
produce recommendations.

## Window and cutoff

The public Matchweek boundary is Friday 00:00 inclusive through Tuesday 00:00
exclusive in `Africa/Lagos`. Every persisted instant is canonical UTC. A
`MatchweekResearchCutoff` is created once, at six hours before the earliest
cutoff-valid `INCLUDED` kickoff. The cutoff, membership rows, and freeze record
are immutable SQLite records.

For each canonical fixture, T05 chooses the highest-authority revision with
valid source support at the cutoff. Within that authority level it chooses the
latest cutoff-valid observation. The membership stores the exact controlling
Fixture Revision ID and digest, its authority, original kickoff, and a
membership-record digest.

Membership states are:

- `INCLUDED`: an in-window scheduled Target Match;
- `EXCLUDED`: a confirmed fixture that fails the cutoff schedule or window
  rules;
- `INDETERMINATE`: canonical fixture identity or required kickoff state is not
  established. These rows receive no match decision and are excluded from the
  normal recommendation-coverage denominator.

A confirmed fixture with an unresolved material detail conflict stays
`INCLUDED`, but its membership records `MATERIAL_CONFLICT_BLOCKED` for the
later AVOID path.

## Post-cutoff appendix

`post_cutoff_fixture_appendix` is append-only. Additions and fixtures moved into
the window remain appendix-only and never become retroactive Target Matches.

An inside-window kickoff change is preserved only when every supplied
`PostCutoffValidityReview` condition passes: identity and scope are unchanged,
the kickoff is after cutoff, no postponement or cancellation occurred, and the
pre-match, Critical Evidence, research-sufficiency, and information-boundary
assumptions remain valid. Otherwise T05 appends `WITHDRAWN / VOID`.

Moves outside the window, postponements, cancellations, invalid pre-match
timing, and identity conflicts append the same withdrawn state. A later
reschedule cannot restore a withdrawn original membership.

## Replay and recovery

The T03 membership and revision snapshot artifacts are published under a T03
`SnapshotManifest`. Historical replay verifies that manifest, loads the stored
membership artifact, and resolves only each frozen revision ID plus digest. It
never follows the current fixture revision pointer.

The CLI publishes through the T04 checkpointed lifecycle:

```text
.venv/bin/matchvet freeze 2026-09-18 --season 2026-27 --json
.venv/bin/matchvet freeze 2026-09-18 --resume RUN_ID --season 2026-27 --json
```

Use `--as-of-utc` for a deterministic observation boundary. T05 plan and
source digests are part of the T04 input contract, so an incompatible resume is
refused instead of silently reusing a changed source state.

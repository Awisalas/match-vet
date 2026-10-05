# F07 Match Evidence Cutoff

This page describes the currently implemented legacy per-match rule. The
[Matchweek-wide correction](design/matchweek-wide-evidence-cutoff.md) is the
accepted target for new recommendations; implementation is pending. Its additive
policy rule must preserve the historical contract described below.

`MatchEvidenceCutoffRepository` persists one immutable V2 Match Evidence Cutoff
for each frozen `INCLUDED` membership. It accepts an exact F06 freeze identity
and a persisted evidence cutoff policy digest. Matchweek Membership Freeze and
Match Evidence Cutoff have separate identities and timing policies.

## Policy contract

`CutoffPolicy(policy_id, policy_version, lead_time_seconds)` has schema version 1
and the supported rule `KICKOFF_MINUS_LEAD_TIME`. F07 supplies no numeric default.
A policy with `lead_time_seconds=None` can be retained, but cannot create or replay
a cutoff. Configured lead time must be a positive integer number of seconds.
Policy versions name configurations; the full policy artifact digest also binds
the exact configuration. Any configuration change has a new digest and creates
separate cutoff state, even if a caller reuses a version label.

`persist_policy` returns the raw 64-character artifact SHA-256. `read_policy`
verifies the protected artifact and supported schema and rule. Policy version
labels are caller-assigned; schema version and rule determine reader support.

## Persist and read contracts

- `persist_exact(freeze_id, membership_id, policy_digest)` persists one exact
  `INCLUDED` membership under the named policy.
- `persist_for_freeze(freeze_id, policy_digest)` persists all `INCLUDED` members
  in frozen membership order. Excluded and indeterminate members receive no cutoff.
- `get_by_id(cutoff_id)` returns an exact verified cutoff or `None` if absent.
- `replay(cutoff_id)` requires the named persisted cutoff.
- `replay_for_freeze(freeze_id, policy_digest)` requires a persisted cutoff for
  every eligible member. It never creates missing records.

Each cutoff binds the freeze ID and digest, membership ID and digest, fixture ID,
controlling Fixture Revision ID and digest, policy ID and version, exact policy
digest, schema version, and UTC boundary. The boundary uses the frozen controller's
`INSTANT` kickoff, never the current revision pointer. A changed fixture revision
requires a new F06 freeze before it can control new F07 state.

Canonical UTF-8 JSON uses sorted keys and compact separators. The cutoff digest
is `sha256:` plus the SHA-256 of those bytes. Its ID is `f07:` plus the same hash.
Neither identity includes a wall-clock creation time. Identical retries retain
identical bytes, identities, and digests.

## Persistence and recovery

Policies and cutoffs use the existing protected T03 artifact store, including
immutable SQLite catalog entries, file verification, recovery, and backup.
No migration is required. Every match publishes independently. Interrupted slate
persistence may leave some complete cutoffs; retry reuses them, while complete
slate replay refuses any missing cutoff. This API does not claim atomic slate
publication or produce a match decision.

Replay verifies artifact bytes and types, the policy, and the full exact F06
reference chain through the public F06 reader. Missing or mismatched references,
corrupt payloads, unconfigured policies, unsupported schemas or rules, and missing
precise kickoffs raise `MatchEvidenceCutoffError` with a stable `MV-F07-*` code.
Historical F06 and V1 artifacts retain their existing readers and meanings.

## Evidence boundary

`evidence_is_pre_cutoff` loads the exact retained cutoff. Evidence is eligible
only when both publication and retrieval times are known UTC instants and
`published_at_utc <= retrieved_at_utc <= cutoff_at_utc`. Unknown publication time
returns false. The exact boundary is inclusive. A later policy or revision cannot
change classification against the original cutoff ID.

F07 does not acquire or freeze contextual evidence. Later V2 evidence workflows
must retain the cutoff identity when applying this boundary.

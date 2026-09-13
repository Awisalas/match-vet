# T07 Source Evidence

`matchvet.evidence.EvidenceRecorder` records caller-supplied evidence that has
already been obtained by an operator or an approved source adapter. It does not
fetch pages, scrape sites, automate a browser, call private endpoints, or add a
new source foundation.

## Evidence boundary

Every assertion names an existing canonical `FIXTURE`, `TEAM`, or `PERSON`.
People can be registered as immutable canonical records; fixtures and teams come
from T06. An assertion cannot create or attach to an ad-hoc entity ID.

The supported evidence types cover injury, suspension, availability or doubtful
status, expected lineup, rotation, manager or regime change, tactical context,
and referee appointment or context. Each assertion is explicitly
`OBSERVED`, `ABSENT`, or `UNKNOWN`:

- `OBSERVED` requires a JSON value and source capture.
- `ABSENT` requires affirmative provenance explaining the reliable negative.
- `UNKNOWN` requires a reason and never implies that the condition is absent.

## Capture and provenance

`SourceIdentity` stores the source key, owner, source class, access method,
locator, authority scope, terms, and rights or retention status.
`IndependentOrigin` identifies the underlying organization or origin. A
`SourceCaptureInput` records the locator, retrieval time, optional publication
time, response metadata, citation, and capture kind.

Retained captures contain bytes, a SHA-256 digest, and a content-addressed
artifact. Citation-only captures contain no page bytes or artifact; their
locator, source identity, origin, rights, and citation note remain auditable.
Retention is checked before an artifact is published. Specialist reporting is
accepted as citation-only contextual or corroborative evidence and cannot be
Critical Evidence.

The settled hierarchy is encoded as an authority rank per evidence type. Lower
ranks are stronger: formal competition or federation sources lead suspensions
and referee appointments; direct club or manager sources lead injuries,
availability, manager state, and tactics; official editorial sources lead
expected lineups. Structured or open sources are lower-ranked fallbacks, and
specialist reporting is contextual or corroborative only. Assertions are never
overwritten when a stronger source arrives.

## Cutoffs, conflicts, and corrections

`assess_cutoff_eligibility` applies the T05 cutoff boundary. A known publication
at or before the cutoff is `CUTOFF_VALID`; a known publication after it is
`POST_CUTOFF`; a missing publication time captured after the cutoff is
`INDETERMINATE`. Exact-boundary timestamps are valid. Read APIs expose all
classifications, while preferred evidence and corroboration use only
cutoff-valid evidence (with an explicit `UNKNOWN` fallback for missing
evidence).

Corroboration counts distinct `IndependentOrigin` IDs, so repeated pages or
syndicated reports from one origin count once. Conflicting observed or
affirmatively absent values create immutable conflict sets. A correction is a
new immutable assertion pointing to its predecessor. Resolution records are
also append-only and may cite only authority, directness, freshness, or
relevance as their basis.

T07 records evidence and its audit trail only. Research sufficiency, workload,
weather, prediction, and recommendation logic remain outside this seam.

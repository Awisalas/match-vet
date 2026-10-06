# Cross-judge result

Judge: gpt-6-sol (`/root/sqlite_research`). Returned 2026-10-06T05:53:50.325Z.
Rubric: `arena-rubric.md`. Candidates: `candidate-snapshot.md` and
`candidate-filesystem.md`. The returned aggregate scores were indexed 12/12 and
filesystem 11/12; no additional criterion scores are inferred here.

Exact returned decision:

> Recommend the indexed two-manifest design, with lexical, one-use authority from the filesystem candidate. Scores: indexed **12/12**, filesystem **11/12**. The filesystem design adds a second persistence and backup path.
>
> A guard on `ArtifactStore.publish_manifest()` alone leaves `StoreTransaction.record_snapshot_manifest()` as a generic insertion route. The design must either guard that route or explicitly include it inside the trusted internal boundary. UUIDv8 reservation closes wrong-Matchweek namespace bypasses; UUIDv5 with strict replay remains safe but permits permanent false refusal through slot poisoning.

The root accepted the indexed base, lexical authority graft, both structured API guards
and the UUIDv5 strict-reader tradeoff. The final design documents invalid-slot poisoning
as refusal rather than qualification. See `synthesis.md` and the protocol specification.
This record preserves the returned judgment; it is not an independently executed test.

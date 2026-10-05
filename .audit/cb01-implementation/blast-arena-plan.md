# CB01 blast-radius arena

## Artifact

Produce two independent read-only audits of the CB01 implementation. Each audit names externally visible regression risks, exact code paths, and the cheapest runtime proof for each material risk. A cross-judge compares both audits against the rubric.

## Rubric

1. Does the implementation follow the frozen CB01 contract without changing #70 or opening F17/F18/F20/F21?
2. Can chronology, Sigstore trust, or signature verification fail open?
3. Can protected persistence, retries, recovery, replay, or receipt selection expose incomplete or conflicting evidence?
4. Can exact upstream replay, the complete denominator, raw F13 values, or F19/T10 facts change or disappear?
5. Could edits to shared F13/F14/F16/F19/ArtifactStore behavior affect existing contracts, migrations, or the production CLI?

## Phases

- [x] Frame the artifact and rubric.
- [x] Fan out two independent implementation audits.
- [x] Cross-judge the audit reports.
- [x] Compare results against the rubric and select findings.
- [x] Graft material findings into the implementation or the synthesis note.
- [x] Verify the final selected findings against executable evidence.

The current-source outcome seam passed, including the interrupted publication, full F19 conflict set, exact T10 supplements, and correction replay. The root-rotation and TUF rollback floors also have deterministic offline regressions. The full CB01 suite is a separate acceptance gate and is recorded in the implementation decision trail.

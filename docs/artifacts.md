# Immutable artifacts and Snapshot Manifests

T03 stores larger retained content outside SQLite in a private, content-addressed object store. The object path is derived only from the lowercase SHA-256 digest:

    objects/sha256/<first-two-digest-characters>/<digest>

Staging files live under `staging/artifacts` on the same private filesystem. Shared Android storage is not used for live objects.

## Artifact publication

`matchvet.artifacts.ArtifactStore` is the public publication seam. `publish_artifact` accepts bytes, a media type, and an optional expected digest. It stages bytes with mode `0600`, flushes and fsyncs them, verifies length and SHA-256, and atomically renames the staged file into its digest path. The containing directory is fsynced before a short SQLite transaction records the catalog entry.

The catalog records an opaque typed artifact ID separately from its content digest, media type, byte length, relative object path, UTC creation time, and retention class. Artifact rows and object content are immutable. If the digest path already exists, MatchVet verifies it and deduplicates identical content; it never overwrites the object. A corrupt or mismatched existing object is an error.

If the database transaction fails after filesystem publication, the object remains an unreferenced, detectable orphan. A failure before publication creates no catalog row. Staging debris is reported separately and is never treated as protected history.

## Snapshot Manifest contract

`SnapshotManifest.to_bytes()` produces canonical UTF-8 JSON with sorted keys, compact separators, exact UTC timestamps, sorted unique artifact and version members, and no insignificant formatting. A newly assembled manifest is explicitly identified by its typed snapshot, Matchweek, Research Cutoff, and version-manifest IDs and remains `UNVERIFIED` until publication. Publication verifies every reference and stamps the actual UTC verification time before writing the immutable verified manifest bytes. Its top-level fields are:

- `snapshot_id` and `matchweek_id` (typed canonical UUID values);
- typed `research_cutoff_id`, `version_manifest_id`, and optional `parent_snapshot_id`;
- `research_cutoff_utc`, `created_at_utc`, and verification state/time;
- exact typed artifact IDs, content digests, media types, and byte-length members;
- exact version IDs, logical definition IDs, names, kinds, contract versions, and content digests;
- explicit `retention_omissions` for citation-only or rights-restricted material;
- `completeness` with `COMPLETE` or `INCOMPLETE` and sorted missing items;
- `schema_version` and an `aggregate_sha256` over the canonical payload excluding that field.

The full canonical bytes receive their own SHA-256 object digest. `publish_manifest` verifies every referenced artifact and exact stored version first, publishes the verified manifest object, and then records the manifest and memberships in one bounded SQLite transaction. Re-publishing the same immutable snapshot content returns the existing verified object; a conflicting snapshot still follows artifact-first ordering and is rejected by the transaction. `verify_manifest` rechecks the object digest, canonical JSON, aggregate digest, catalog metadata, and all memberships before returning it. Malformed JSON, noncanonical bytes, digest mismatches, unknown versions, and inconsistent metadata are rejected.

Citation-only evidence is represented by a retention omission; it does not create a fake raw artifact. A manifest may be incomplete when its explicit completeness state and missing items say so.

## Inspection and recovery

`ArtifactStore.inspect()` and the artifact section of `matchvet doctor --json` report:

- catalogued objects that are missing or whose bytes/digest/path do not verify;
- malformed or inconsistent Snapshot Manifests;
- content-addressed files with no catalog row (`orphans`);
- catalogued objects not reachable from a published manifest (`unreferenced`);
- leftover staging files.

Inspection never deletes, repairs, or rewrites objects, manifests, or protected history. A missing or altered object fails the artifact-integrity doctor check. Orphans remain available for a later explicit retention operation. The artifact catalog and manifest memberships are append-only and protected by SQLite immutability triggers.

## T17 operational export and recovery copies

`matchvet export` is a marker-gated copy of a complete T16 publication. It writes deterministic
`report.md`, `audit.json`, and `manifest.json` members, SHA-256 length/digest metadata, T16
reproducibility and version identities, and a canonical `COMPLETE` marker. The private
authoritative audit and artifact catalog are never replaced. A destination is first populated as
`<destination>.partial`, read back and verified, then copied to its final directory; a directory
without the marker is never a completed Matchweek export.

Raw evidence is opt-in and is copied only when the capture is retained as `RETAIN_REUSABLE` and
its source rights mark it redistributable. Restricted retained bytes and citation-only captures
stay private; the export manifest records deterministic retention omissions. A backup is different:
it is protected recovery material, not a redistribution bundle, and includes the SQLite online
backup plus every catalogued content-addressed object needed by that database.

`matchvet backup` verifies the source with full SQLite integrity and foreign-key checks, records
the application/schema/migration identity, copies the database and all object digests through a
`.partial` destination, verifies the destination, and writes `COMPLETE` last. `matchvet restore`
accepts only such a verified bundle, stages it inside private storage, checks all compatibility,
database, catalog, and object invariants again, and activates only a new private database target.
Shared copies are never authoritative or executable state. Locks, WAL sidecars, caches, and
operation staging debris are not part of a bundle.

T04 uses the same artifact-first contract for an operational run-completion record. The artifact
is published first, then its database reference and the run's `COMPLETE` state commit together.
It is not a Matchweek Report, Matchweek Audit, PLAY, or AVOID MATCH decision. Evidence ingestion,
model output and reports remain later work; T17 export and recovery copies are documented below.

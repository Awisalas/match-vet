# CB01 grounding

## Caller flow

The contract's public caller supplies one exact included membership anchor, its exact upstream lineage, and a trust policy identity. The repository prepares all enabled profile rows, commits their canonical batch bytes once, obtains one Sigstore RFC3161 token, verifies it under the refreshed authenticated TUF state, then publishes per-preference records and a complete receipt last. Recovery names exact batch and attempt digests. Settlement attachment names exact F19 versions and correction predecessors.

## Existing ownership and replay

- `ArtifactStore` owns protected content-addressed file publication and catalog reconciliation. `publish_artifact` publishes one object per call. Each catalog insert uses the Store's existing writer transaction and lock. `created_at_utc` is metadata. CB01 must use this API unchanged; receipt-last publication controls batch visibility.
- F06 is `MatchweekMembershipRepository`. It replays an immutable freeze and its INCLUDED or excluded memberships, with exact controlling fixture revision identities.
- F07 is `MatchEvidenceCutoffRepository`. It replays a prefixed `f07:<digest>` cutoff and validates it against its exact F06 member and policy. The cutoff payload has canonical UTC text and preserves its exact identity spelling.
- F10 is `V2_REQUIREMENT_CATALOG`; the existing catalog digest and each F14 input bind exact requirements.
- F11 is `F11EvidenceRepository.replay(digest, freeze_id=..., policy_digest=...)`. It validates all exact F06/F07 inputs. CB01 must call replay only and must not call its build/acquisition paths.
- F13 is `ModelContractRepository.replay(result_digest, evidence_digest, cutoff_id)`. It replays exact model inputs, retained history, four family fits/distributions/calibration artifacts and verifies deterministic output. The canonical F13 artifact bytes are the source for retained distributions. CB01 must not rebuild these models.
- F14 separates the frozen `PreferenceProfile` from capability. `PreferenceProfileRepository.replay` returns the full sorted enabled preference set. `DecisionRepository.replay` validates the immutable RESEARCH_ONLY decision and requires every enabled preference to have a terminal result.
- F16 is `F16MatchweekProcessor.replay_manifest`. The manifest validates exact F06/F07/F11/F13/F14 references and has exactly one result for each INCLUDED membership in its freeze. Its child result identifies the exact decision.
- F19 is `SettlementRepository.replay`. Each immutable settlement stores exact T10 evidence snapshots, grading state and result, plus an exact F16/F14 identity. Corrections append one successor with a predecessor and increasing sequence. T10 distinguishes pending, conflicting and terminal grades; PUSH is its own result.
- T10 settlement evidence contains the source-level FT, HT and corner facts and provenance needed by CB01. F19's grade cannot supply a missing diagnostic fact. Fact attachment must retain exact evidence and mark each unavailable or conflicting fact explicitly.

## Integration constraints

CB01's public acceptance seam is the proposed `BootstrapRepository` from the frozen contract, against a real ArtifactStore reopened from disk and deterministic fake trust/TSA boundaries. Canonical envelopes need duplicate-key detection, exact nested key sets, canonical byte equality, finite numbers and strict digest/namespace checks. All CB01 objects and raw DER requests/responses use protected ArtifactStore publication. No database migration, generic Store change, production CLI, #70 change or F17/F18/F20/F21 work is allowed.

For chronology, only the signed RFC3161 `genTime` is compared, strictly between the exact F07 cutoff and fixture kickoff. Keep timestamp fractional precision; phone time, HTTP Date and ArtifactStore `created_at_utc` are metadata. Refresh authenticated Sigstore TUF metadata before each new attempt and retain exact bytes and version/digest identities for replay. Policy allows one ordinary request and one explicit retry at most per exact batch, with no automatic retry or alternate TSA. Do not claim CRL/OCSP verification.

## Existing system flow

`F06 freeze -> F07 cutoff -> F11 evidence -> F13 model contract -> F14 profile/decision -> F16 whole-freeze manifest -> F19 settlement versions` is the immutable upstream chain. CB01 adds an outcome-free per-preference snapshot and a batch hash before the TSA request, then writes enrollment records and a receipt afterward. Outcome attachments sit after the receipt and point back to an exact enrolled row.

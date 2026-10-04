# F16 implementation sketch

## Problem

F15 validates exact F06/F07/F10/F13/F14/T15 inputs and drives the existing T04 `RunCoordinator`, but its executor is currently a boundary interruption. F11, F13, and F14 each already own protected immutable artifacts and exact replay. F16 must coordinate them for every `INCLUDED` membership without adding a lifecycle phase, weakening exact lineage, or claiming F17 audit/publication completion.

## Usage

```python
progress = AnalyzeMatchweek(store).start(request)
progress = AnalyzeMatchweek(store).resume(progress.run_id, request)
assert progress.phase is RunPhase.AUDIT_VERIFICATION
assert progress.run_state is RunState.INCOMPLETE
```

The caller continues using the existing F15 request and T04 lifecycle. Progress exposes exact retained artifact identities when F16 work is durable.

## Shape

`AnalyzeMatchweek` supplies a phase-aware executor to the existing `RunCoordinator`. A cohesive `F16MatchweekProcessor` is the F16 boundary. It receives the exact freeze, cutoff policy and cutoffs, profile, and RESEARCH_ONLY policy already verified by F15.

```python
@dataclass(frozen=True)
class F16MatchResult:
    membership_id: str
    membership_digest: str
    cutoff_id: str
    cutoff_digest: str
    evidence_digest: str
    model_digest: str
    decision_digest: str
    match_result_digest: str

class F16MatchweekProcessor:
    def process_phase(
        self,
        context: WorkContext,
        *,
        freeze_id: str,
        cutoff_policy_digest: str,
        cutoff_ids: tuple[str, ...],
        profile_digest: str,
        policy: PolicyVersion,
    ) -> WorkResult: ...
    def replay_manifest(self, digest: str) -> F16Manifest: ...
    def completed_artifact_identities(self, freeze_id: str, policy_digest: str) -> tuple[str, ...]: ...
```

The existing `EVIDENCE_ACQUISITION`, `FROZEN_EVIDENCE_STATE`, and `PREFERENCE_VETTING` T04 work units publish or replay F11, F13, and F14/F16 artifacts respectively. The existing `ADVERSARIAL_REVIEW` checkpoint records that F14 ran its full gates. At `AUDIT_VERIFICATION`, the executor interrupts after verifying the F16 manifest, leaving T04 `INCOMPLETE` for F17.

F11 receives no venue mapping unless an exact retained mapping is explicitly available. F13 gets only retained structured history sources; its builder filters by each cutoff and target identity. F14 receives only derivable candidate inputs. Unsupported values remain absent, making gates reject and allowing AVOID MATCH.

Each protected F16 match artifact binds exact F06/F07 membership and cutoff digests and exact F11/F13/F14 artifact digests. A protected canonical manifest lists one sorted entry per included membership and those same exact references. Replay verifies every child through F11/F13/F14. No mutable persistence or migration is added.

The public surface hides membership joins, idempotent artifact lookup, serialization, and replay integrity behind F16. F15 remains responsible for lifecycle identity; lower pipeline repositories remain the authority for their artifact contracts.

## Synthesis decision

Candidate A's cohesive F16 processor is the base because it concentrates per-match orchestration behind one boundary and keeps F15 as the existing lifecycle owner. The cross-judge scored A 19/20 and B 17/20, favoring A's smaller public surface and existing T04 phase fit. Candidate B's manifest-centered replay rule is grafted in: manifest replay validates every child result and is the sole F16 completion record. Candidate B's idea of passing caller-supplied weather/location options is rejected because F15 has no exact retained venue mapping source; absent a mapping, weather remains UNKNOWN. Both candidates reject new phases, latest lookups, fabricated gate values, and publication.

## Tradeoffs accepted

- F16 scans immutable artifact metadata to recover exact retained results, in exchange for no new mutable repository or migration.
- F13 considers only explicitly retained structured history artifacts; absent such evidence, quantitative model support remains unavailable.
- F16 reaches durable completion before F17 publication, so the run intentionally remains incomplete at audit verification.

## Alternatives considered

- Put all F11/F13/F14 joins directly in F15: this exposes pipeline and replay details to the lifecycle entry point and makes its public surface shallower.
- Make F16 only a manifest writer: callers would still coordinate exact per-match joins and resume rules themselves.

## Open questions and risks

- If multiple retained F13 history sources disagree on a fixture, should a future version add an explicit history-source selection contract? This version fails closed on ambiguity.
- Should F17 later advance the existing audit and publication phases? F16 does not own that decision.

## Next implementation step

Add the public lifecycle regression for one result per included membership and the `AUDIT_VERIFICATION` incomplete state, then fill the F16 processor in vertical slices.

# Matchweek-wide evidence cutoff correction

Current successor: [ADR 0003](../adr/0003-causal-matchweek-selection-witness.md)
and [causal selection architecture](causal-matchweek-selection-witness.md) authorize
a new prospective remote-event boundary for #79. The return-time clock and writer
contracts below retain their historical v1 meaning. They remain implemented and
refusing by default; causal timing code is not implemented. New work must use
explicit successor versions, never reinterpret these artifacts or acceptance proofs.

Status: implementation and isolated offline acceptance are complete under [#73](https://github.com/Awisalas/match-vet/issues/73) and [#78](https://github.com/Awisalas/match-vet/issues/78). Live authoritative validation remains pending.

## Decision

The configured Friday-through-Monday slate across all seven Target Leagues has **one frozen information state**. All research and evidence collection must finish before its common cutoff. Later fixtures receive no extra collection window. Later news, injuries, lineups, weather, schedule observations, outcomes, or refreshed inputs cannot change any recommendation. Permitted audit, evaluation, and F19 settlement remain separate.

Retain F06's assessment-specific membership freeze and F07's exact per-membership references. Introduce a new explicit policy rule:

```text
MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME

K = minimum exact kickoff among every INCLUDED membership of the admitted F06 freeze
T = K - policy.lead_time_seconds
every INCLUDED membership's F07.cutoff_at_utc = T
```

The initial corrected policy explicitly configures **21600 seconds**. F07 still has no implicit numeric default. A missing lead time, empty included set, incomplete slate, missing exact kickoff, or unestablished earliest boundary fails closed.

F06 creation time remains persistence metadata. It is neither T nor a lead-time policy. For prospective corrected use, the selected F01/F05/F06 chain and complete research state must already exist before T.

### Smallest safe closure

Complete the existing F11 evidence, F13 inputs/results, F14 decisions, and whole-slate F16 manifest **before T**, then select that exact manifest once for the logical Matchweek. This operating deadline is stricter than merely freezing inputs before computation; it avoids adding a new input-selection payload and changing F13/F14/F16 schemas. After T, permit exact replay, reporting from retained bytes, and the existing CB01 witness workflow. Do not permit first model assembly, alternative evidence requests, changed profiles/policies, or revised decisions.

Use a versioned domain owner over an existing protected `SnapshotManifest` to pin the selected F16 manifest and its exact dependency closure. The deterministic snapshot identity belongs to the logical Matchweek, under one stable corrected-selection namespace. It must not vary with F06 assessment, cutoff policy, profile, engine version, or request configuration. Existing `UNIQUE(snapshot_id)` provides immutable single assignment. Different proposals cannot become a replacement, even with a later F06 freeze or a new policy label. Research experiments may retain separate artifacts but cannot become another recommendation for the frozen Matchweek.

Once the sole selection exists, it is final even if it was sealed early. A future selector implementation version must resolve the same logical identity; versioning its reader cannot create another selection slot for that Matchweek.

This is a proposed use of the existing manifest schema, not a V1 T05 cutoff record. Typed Matchweek/research-cutoff/version identifiers and exact policy/F06 artifacts establish the new binding; no fabricated V1 row is needed. Domain verification must validate the complete reference graph, timestamps, uniform boundary, and selected F16 identity. Generic manifest verification alone does not establish those rules.

### Proposed caller contract

These APIs are design sketches, not implemented interfaces:

```python
# All collection, input selection, computation, and selection finish before T.
manifest = processor.process(corrected_request)
selected = MatchweekResearchRepository(store).seal_completed(manifest.digest)

# At or after T: exact retained state only; no acquisition or input selection.
selected = MatchweekResearchRepository(store).replay(selected.digest)
enrollment = enrollment_adapter.prepare_selected(selected.digest, fixture_id)

@dataclass(frozen=True)
class FrozenMatchweekResearch:
	digest: str
	season: str
	matchweek_friday: str
	freeze_id: str
	policy_digest: str
	cutoff_at_utc: str
	f16_manifest_digest: str
	# Returned only after canonical selection and full-lineage verification.

class MatchweekResearchRepository:
	def seal_completed(self, f16_manifest_digest: str) -> FrozenMatchweekResearch:
		raise NotImplementedError

	def replay(self, selection_digest: str) -> FrozenMatchweekResearch:
		raise NotImplementedError

	def replay_for_matchweek(
		self, *, season: str, matchweek_friday: str
	) -> FrozenMatchweekResearch:
		raise NotImplementedError
```

The owner belongs in proposed `src/matchvet/matchweek_research.py`. It hides admission, complete-slate validation, protected single assignment, and selection replay. Both replay methods verify the deterministic logical-Matchweek mapping and exact selected F16 digest; supplying another valid manifest digest or an orphan object never qualifies. Lookup by Matchweek supports restart without a caller choosing a candidate. F07 owns policy-rule arithmetic and original-policy dispatch. Corrected F11/F13/F14/F15/F16 and CB01 adapters invoke shared validation; direct repository entry points must enforce the same restrictions. A CLI-only deadline check is insufficient.

## Contradiction and root cause

The shipped F07 rule, `KICKOFF_MINUS_LEAD_TIME`, subtracts the lead from each match's own controlling kickoff. F11 permits different Friday/Monday deadlines and request variants. F13's first history assembly can read a mutable retained-source catalog. A formula-only change therefore leaves late selection and refreshed research possible, including new UNKNOWN/failed-attempt metadata that changes F14 rejection reasons.

The drift was deliberate in the intervening V2 contracts: Product Direction commit `7c0635b`, architecture commit `3b897e3`, [F07 #58](https://github.com/Awisalas/match-vet/issues/58), and [F11 #62](https://github.com/Awisalas/match-vet/issues/62). F07 implemented its then-current specification. The reason that V2 abandoned the founder's shared boundary is not established by the retrieved evidence. The current founder clarification supersedes that direction for new recommendations.

## Six-hour status

Six hours was a settled initial founder/product decision, not an invented replacement or an empirically validated optimum. [#1](https://github.com/Awisalas/match-vet/issues/1), the [owner's #13 resolution](https://github.com/Awisalas/match-vet/issues/13#issuecomment-5646165350), [T05 completion #23](https://github.com/Awisalas/match-vet/issues/23#issuecomment-5654376189), original glossary commit `207cdf9`, and implementation commit `448b930` establish one six-hour batch cutoff. [#37](https://github.com/Awisalas/match-vet/issues/37) still refers to that evaluation rule.

The intervening V2 direction reopened numeric timing and required explicit per-match configuration; it supplied no settled replacement number. Restore **explicit 21600** with the corrected shared rule. Preserve old policies exactly, including other configured lead times. Any later numerical change requires an explicit prospective policy decision and cannot refresh an already frozen Matchweek.

## Admission and freeze invariants

1. Require full-window schedule coverage and exact provenance for all seven scopes. Coverage of only remaining upcoming fixtures is insufficient. Resolve eligibility before choosing K.
2. Validate every INCLUDED kickoff as an exact UTC instant, even when `persist_exact` is called for only one member. Reject an empty slate, missing/date-only kickoff, unresolved potentially earlier eligibility, or an undefined T before publishing corrected cutoff state.
3. Prevent a fresh Saturday/Sunday freeze from excluding a completed Friday fixture as `NOT_SCHEDULED` and falsely moving K forward. Inspect the full-window controlling schedule and excluded/indeterminate candidates. An earlier started/completed in-window eligible fixture, or inability to establish its original eligibility, refuses new prospective admission. Existing selected state is replayed, never replaced.
4. Require first corrected acquisition, input assembly, complete F16 publication, and the exact selection commit to finish strictly before T, using repository-controlled time and actual retained capture/catalog provenance. Caller timestamps or an early `published_at` cannot backdate late collection. A repository clock observation after the fresh selection commit must also be strictly before T. Only persistence of its already authorized completion receipt may finish later; no research, computation or selection gets that exception.
5. Retain F07's provenance predicate `published_at <= retrieved_at <= T`, with known UTC instants. Selection has the stricter completion deadline above. At/after T, only exact replay is allowed, including a retry with apparently old timestamps. Freeze missing facts, UNKNOWN states, attempts, conflicts, workload/weather inputs, history, calibration, baselines, candidate inputs, profiles, and model/research contracts.
6. Validate full included-membership coverage and one exact F06/policy/common T throughout F11/F13/F14/F15/F16 and corrected CB01 enrollment. Equal timestamps under different policies or different freezes do not establish equal provenance.
7. Single assignment and publication guards must survive restart, concurrency, partial publication, and all direct writer entry points. A partial slate is not a complete selected Matchweek. If the complete selected state does not exist by T, mark the run missed/incomplete; do not rescue its later matches.

Publication acceptance means the selected manifest and complete reference graph are durable before the fresh atomic selection commit returns, followed by a repository-controlled UTC completion upper-bound observation strictly before T. `ArtifactStore.publish_manifest` currently samples its verification timestamp before publication; that field alone is insufficient. The accepted [completion protocol](matchweek-selection-completion-protocol.md) uses private one-use authority from that same live operation to publish a second protected generic SnapshotManifest receipt. The receipt may become durable after T because it attests to the earlier selection event. Its ordinary verification time is not deadline evidence.

An indexed selection without a valid indexed receipt after interruption is permanently unqualified, even before T. Recovery never constructs a missing receipt from selection rows, logs, timestamps or orphan objects. A valid receipt can replay after T only with the exact selected graph and canonical mappings intact. Fresh selection commit or acknowledgement at/after T refuses; a pause after valid acknowledgement can delay only its one receipt attempt. This requires narrow protected publication hooks and a trusted UTC bound with honest WAL/FULL and filesystem synchronization. Existing schema and historical manifest bytes/readers suffice; the current public APIs alone do not establish these rules. The original failed proofs remain preserved, and the new isolated protocol proof does not constitute production #75 implementation.

## Contracts affected

| Contract / exact modules | Correction and compatibility requirement |
|---|---|
| F06 `matchweek_membership.py`, `matchweek_membership_repository.py`; upstream F01/F05 | Keep membership schema/policy semantics. New prospective admission validates the exact complete seven-scope schedule, timestamps, excluded earlier candidates, and precise included kickoffs. Later observations remain append-only audit state. |
| F07 `match_evidence_cutoff.py`; `tests/test_match_evidence_cutoff.py` | Add rule dispatch and whole-freeze derivation/validation to persist/read/replay, including single-member APIs. Retain schema 1 and existing cutoff fields/digest algorithm. New rule/policy digest naturally yields new identities. Legacy rule must keep its original arithmetic and bytes. |
| F11 `f11.py`, `weather.py`, `workload.py`; exact F12 `f12.py` attempt references | Require common boundary and pre-T collection/retention. Guard alternate request/configuration paths, retries, late weather UNKNOWN/attempt records, and source selection. Later separately permitted attempts cannot replace selected F12 references. Historical request variants remain replayable under old policy. |
| F13 `f13.py`; existing `t09.py`, `t11.py`–`t14.py` engine contracts | Seal exact history, calibration cases, availability provenance, and model inputs/results before T. No first post-T assembly from latest catalogs or later Matchweek results. Preserve old engine/adapter contracts through unchanged bytes or explicit dispatch; a global adapter bump must not invalidate replay. No statistical algorithm change is required. |
| F14 `f14.py` | Preserve existing exact cutoff/evidence/model/profile/policy identity. Complete before T and admit only selected lineage afterward. New cutoff references yield new decision identities; no schema change is needed solely for a common time. |
| F15 `f15.py` | Bind new rule/policy and common T into existing run inputs/checkpoints; validate complete uniform coverage. Changed policy never resumes a different run. Legacy historical run replay remains available. |
| F16 `f16.py`; proposed `matchweek_research.py`; `artifacts.py` / `store.py` APIs | Complete existing manifest before T; single-assignment selection through existing protected manifest/index. Resume after T replays only the selected state. A narrow publication deadline/completion hook may be needed; isolated proof must establish completion and compatibility. |
| CB01 `cb01_sources.py`, enrollment adapter, `cb01_trust.py`; `cb01.py` compatibility constraint | Require selected exact F16/F07 lineage and homogeneous policy/common T across the complete INCLUDED-membership × enabled-preference denominator. Keep failures, unattempted rows, fixture batches, transport, nonce, trust pins, and historical receipts. Preserve core software identity/reconstruction; see chronology below. |
| F19 `f19.py` | Keep exact decision/manifest settlement lineage and append-only corrections. Outcome collection happens later and cannot become frozen prediction input. No grading/schema change is indicated. |
| #70 / historical evaluation | New evaluations use one shared forecast origin, frozen inputs, explicit policy/selection identity, and outcome availability. Preserve old method 0.1.0 and old-policy cases; do not pool or relabel them as corrected evidence. Numerical derivation profiles remain independently unresolved. |
| Documentation | Clarify glossary and current Product Direction/Architecture. The released #70 methodology, completed issues, old plans, migrations, and historical `.audit` evidence retain their original contents. This decision supplies the successor chronology. |

### CB01 and chronological evaluation

Keep the existing strict witness condition **common T < signed RFC3161 genTime < that fixture's controlling kickoff**. A shared research cutoff does not require replacing fixture batches or imposing a new whole-slate timestamp deadline. The selected whole-slate research state already exists before T. A later fixture's witness cannot authorize later collection, input selection, or decision refresh.

The token proves that its committed bytes existed by signed `genTime`; it does not independently prove pre-T collection or contemporaneous pre-Friday publication. Report those distinctions honestly. A retrospective replay is never relabeled as a contemporaneous forecast. A failed or missing witness remains in the complete denominator. A stored valid token may be resumed/published later only under the existing exact-byte chronology contract; do not issue a replacement late token.

The denominator still comes from the exact admitted F06 freeze and Profile independently of F16 availability. Missing F16, an unsealed/incomplete run, failed anchors, and unattempted preferences remain explicit unavailable rows, never disappear from the denominator. Selected F16 lineage is required for qualifying recommendation enrollment, not for counting a missing case. Mixed policy/boundary receipts are refused; they cannot be combined into a corrected cohort or used to shrink its denominator.

`cb01_sources._software_reference` hashes current `cb01.py` into pre-enrollment identity, and `_assert_prepared_batch` reconstructs exact bytes. CB01 also records the `cb01_trust.py` module digest. Prefer new-policy gates in the source/enrollment adapter without changing those historical core bytes. If implementation needs core/trust changes, explicitly retain historical software-identity dispatch and prove old commitments still reconstruct. A global source hash change is not harmless.

The successor to [#70 methodology 0.1.0](../product-v2/CANDIDATE-INPUT-METHODOLOGY.md) applies this common origin and forbids its old allowance for newly discovered model-affecting evidence at the same original cutoff from creating revised recommendations. Earlier publication does not admit later collection. Frozen later-week predictions cannot train on earlier outcomes from their own Matchweek. Later outcomes can enter separate F19 settlement or a genuinely later evaluation/development origin where permitted.

## Historical artifacts and migration

Old F07/F11/F13/F14/F16/CB01 artifacts remain valid historical artifacts under their exact original per-match policy. They are not corrupted by this decision. They cannot satisfy admission to the corrected prospective cohort merely because an old timestamp happens to equal T. Preserve their bytes, digests, policy rules, software/adapter identities, and readers. Never relabel, rewrite, or recompute them using the new rule.

Normal new prospective F15/F16 runs and recommendation enrollment require the corrected rule and selected state. Legacy-policy dispatch supports explicitly historical replay or permitted separate research/audit; choosing the old rule is not a way to open another live collection window.

**No SQLite schema migration is expected.** F07's existing digest-bound `rule` supports versioning without new fields. Existing generic snapshot manifests have typed identifiers and an immutable unique snapshot ID; they do not require a V1 cutoff-table row. A new selection namespace/contract version is still needed. This design has source-level support, not an executed new-manifest compatibility proof. Before implementation is accepted, isolated tests must prove the proposed use and historical replay. If that fails, revise the design explicitly rather than weakening guarantees or silently adding a migration.

Rejected alternative: a new shared frozen-input selection payload enabling first F13/F14 computation after T. It is viable, but would introduce new input ownership and downstream binding/version work. Reconsider only if pre-T completion cannot meet the product's operational needs; the founder rule still forbids later research or input selection.

## Implementation and proof scope

The corrective issue must cover rule dispatch, complete-slate admission, collection/publication gates, protected selection, all downstream validation, compatibility dispatch, and successor chronology. It does not authorize new markets, scoring rules, fixture acquisition, a live rebuild, or policy promotion.

Focused isolated tests must cover Friday/Monday equality, another league controlling K, missing/ambiguous/date-only kickoff, empty/incomplete scopes, late/crossing-T jobs, pre-publication but post-T retrieval, frozen UNKNOWN states, late F11 variants, first post-T F13 assembly, same-week alternate F06/policy/profile, missing/mixed downstream references, concurrent selector proposals, crash/restart replay, historical canonical bytes and adapter/software identities, CB01 full denominator/witness boundaries, and F19 lineage. No test uses either live store or sends a timestamp request.

Affected suites are `tests/test_match_evidence_cutoff.py`, `test_f11.py`, `test_f13.py`, `test_f14.py`, `test_f15.py` (including F16), `test_cb01_sources.py`, `test_cb01_repository.py`, `test_cb01_trust.py`, and new focused selection/publication tests. Existing F19 lineage coverage remains a regression requirement.

The read-only [probe](../../.audit/matchweek-cutoff-design/probe.py) and [output](../../.audit/matchweek-cutoff-design/probe-output.txt) establish the shipped arithmetic contradiction, digest-bound rule field, unsupported-rule refusal, and distinct F11 request identities. SQLite and network connections were blocked and artifact construction trapped. This does **not** prove the future corrected implementation. No full suite or live validation was performed in this design task.

## Next authoritative-store sequence

1. Implement and pass isolated compatibility/admission tests. Configure the new rule and explicit 21600 policy for an entire future Matchweek with enough time to finish before T. Keep #70's unresolved numerical methodology and promotion gates explicit.
2. Keep A authoritative and B unmerged. Acquire fresh approved F01 fixtures/full-window attestations for all seven scopes, with required manual official Belgian coverage where the approved live route still requires it; retain fresh F05 health. Do not transplant B's identities or old schedule assertions.
3. Create fresh F06 in A. Establish complete original eligibility and exact K/T, then derive/replay every new-rule F07 reference. Refuse any missing prerequisite or already missed cutoff.
4. Collect and retain all Matchweek F11 evidence and selected history/calibration/candidate inputs. Complete F13/F14/F16 and the protected whole-Matchweek selection before T. Unsupported numerical inputs remain UNKNOWN/RESEARCH_ONLY; completed computation is not a promotion qualification.
5. At/after T, replay the selected state only. Perform CB01 enrollment/witnessing under the existing strict per-fixture pre-kickoff window and full denominator; retain failed or missed enrollments. Later F19 settlement/evaluation appends outcomes under the exact frozen lineage.

If T is missed, choose a future whole Matchweek. Neither a fresh Sunday subset nor merging B rescues the missed slate. This task performs none of these live steps. Implementation is the immediate blocker; #70 remains a separate blocker to authoritative numerical candidate derivation and promotion evidence.

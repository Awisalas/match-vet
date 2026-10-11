# Blast radius of six active leagues

Audit date: 2026-10-11. Code baseline: `3a727e3b351fddd1dfb27e29b1a50fe40d17f9d4`.
This audit changes product documentation and issue plans only. Production code,
SQLite migrations, tests, retained artifacts, and source policy bytes are unchanged.

[ADR 0007](../adr/0007-six-active-leagues-without-paid-data.md) records the accepted
product decision. The [reference inventory](six-scope-reference-inventory-2026-10-11.json)
records exact baseline paths, lines, search text, and retained golden digests.
File:line references below describe that baseline. The [offline proof](six-scope-blast-radius-proof-2026-10-11.py)
uses a disposable synthetic Store and disables socket contact. It does not inspect
or alter the operator's production Store.

## Decision and safety fact

Successor active scope must contain exactly ENG/ITA/ESP/GER/FRA/POR, using existing canonical league keys `premier_league`, `serie_a`, `la_liga`, `bundesliga`, `ligue_1`, `liga_portugal` in that order. BEL is outside new active scope. No replacement or BEL UNKNOWN placeholder. Runtime must require no paid football/data provider or API subscription. Ordinary hosting/device/network costs are outside that data-dependency rule.

The compatibility requirement is that legacy catalogs and readers remain version-specific.
Editing the existing shared league tuple changes the interpretation of retained bytes.
The offline proof calls real F01 code and a fully migrated temporary production Store,
including foreign keys and triggers. It first persists and replays a valid legacy
policy1 F06 freeze, then inserts successor *storage shapes* through SQL and replays
the original freeze again. These shapes are not admitted successor domain objects.

Run from the repository root:

```sh
python docs/research/six-scope-blast-radius-proof-2026-10-11.py
```

Observed output:

```text
PASS: six requested scopes still produce the exact old seven-scope UNKNOWN artifact
PASS: removing BEL from global F01 registry breaks exact legacy decode: Fixture Coverage payload is invalid.
PASS: restored registry retains exact original seven-scope bytes/digest
PASS: successor F06 policy3 is currently unsupported; admission remains unimplemented
PASS: real schema stores a new F01 version and six-scope F06 policy snapshot without DDL
PASS: bumping F06 envelope is rejected by actual SQLite CHECK: CHECK constraint failed: contract_version = 'matchweek-membership-freeze-v2'
PASS: legacy F06 freeze still replays after successor-shape rows are inserted
PASS: logical calendar week has one selection slot independent of scope: 1dfbfcba-f96d-56b8-95fc-806d202bf1ff
LIMIT: proposed six-scope readers, semantic validation, cohort dispatch and activation are UNIMPLEMENTED
```

This reaches blast-radius assurance step 4 for the shared-catalog failure, exact
legacy F01 bytes/digest, real SQL representation, unchanged old policy1 F06 replay,
and current logical-slot function. It does not prove policy2 semantic compatibility,
future six readers, new graph admission, cohort dispatch, occupied-week integration,
source completeness, or live operation. Those require the implementation tickets.
The LF14 and unfiltered T05 risks below are verified in source at step 2, with
explicit future regression requirements. No running-app validation was performed.

## Exact production assumptions and breakage

| Module / lines | Current meaning | Required successor behavior |
| --- | --- | --- |
| `src/matchvet/ingestion.py:543` | TARGET_LEAGUES is seven LeagueConfig entries; name/key maps at 560 derived from it | Keep complete legacy identity catalog and seven-plan semantics. Add immutable named six active contract, distinguish activity from identity availability. |
| `src/matchvet/ingestion.py:4945` | IngestionPlan defaults to seven; plan digest at 4972 hashes exact league keys and source-policy-v1 | Explicit successor plan binds active contract/digest; no dynamic list. Leave old digest construction exact. |
| `src/matchvet/cli.py:1163` | Builds IngestionPlan using default catalog | New active route must select six successor explicitly. |
| `src/matchvet/ingestion.py:5420` | Scheduled acquisition builds scopes from legacy fixed factory independently of plan subset | Scope-aware successor acquisition must request exactly six, preserve failed attempts, and assess full declared six scope. |
| `src/matchvet/fixture_coverage.py:16`, `378`, `400`, `859` | League validation and F01 factory use global seven; assess expands omitted requested scopes to seven | Keep exact legacy F01 v2-v2 meaning; successor contract explicitly includes active set digest and six scopes. New omission means missing declared scope and remains UNKNOWN. |
| `src/matchvet/fixture_coverage_codec.py:21`, `60` | Closed concrete type and contract/schema dispatch for automatic v2 and operator-attested v3 | Add concrete successor class and explicit dispatch. Do not alter meanings of old version pairs. |
| `src/matchvet/fixture_coverage_repository.py:712` | Metadata derives canonical order from global seven during old persisted replay | Derive expected membership by exact assessment contract, and preserve legacy order/canonical validation. |
| `src/matchvet/operator_fixture_attestation.py:624`, `1536`, `1628` | State evidence and automatic-v2-derived operator-v3 require seven attestations | Preserve historical operator path. If retained as emergency successor tool it needs explicit six contract; never reuse seven reader or old attestation authority as automatic proof. |
| `src/matchvet/operator_fixture_attestation_cli.py:74`, `83`, `284` | Legacy assembler requires seven exact artifacts | Keep legacy CLI assembly/version explicit. New active invocation cannot accidentally use it. |
| `src/matchvet/matchweek_membership.py:181`, `342`, `407`, `415` | Membership policy only 1/2; freeze and observation expect canonical seven snapshots | Add policy3 which explicitly binds active scope contract/digest and six order; preserve old policy1/2 code and bytes. Scope snapshots and observations derive versioned expected scope. |
| `src/matchvet/matchweek_membership_repository.py:116`, `209`, `464`, `518`, `690`, `800`, `830`, `835` | Creation, observation, persistence, replay and health ordering all derive global seven; gate requires exactly seven | All paths dispatch by exact policy and F01 version; match six order and all six scope proof. This cannot be fixed at acquisition alone. |
| `src/matchvet/matchweek_membership_repository.py:714`, `753`, `971`, `981`, `985`, `1744`, `1758`, `1773` | Strong LF14 integrity often selected only by `policy_version == "2"` | Policy3 must explicitly inherit all policy2 semantic checks. Merely adding 3 to allowed versions would skip ordered-team, typed kickoff, content/assertion and cumulative conflict checks. |
| `src/matchvet/matchweek.py:814` | Legacy T05 revision loader queries every league in retained season, no active filter | New active route must not feed this unfiltered legacy selector. Historical BEL rows could reenter new Matchweeks despite six acquisition. Keep legacy replay exact. |
| `src/matchvet/research_capture.py:453`, `467`, `1472` | Capture index reconstructs seven-scoped freeze; indexes version1/2 preserve exact full denominator | Explicit successor capture index binds active scope/cohort; old decoder and successor-chain checks keep seven. |
| `src/matchvet/t16.py:43`, `957` | Default reproducibility metadata names seven leagues and v1 target set | New active path supplies explicit six scope/version; old report reader and T19 metadata retain exact defaults. Do not implement pending F17. |
| `src/matchvet/t19.py:319`, `545`, `873`, `893`, `903` | Recorded corpus, ingest zip, target expectations use seven catalog | Preserve old seven corpus and reader; new independent six qualification corpus/entry path may be needed later. |

The literal `!=7` in `src/matchvet/store.py:781` is the seven run phases. It is not league cardinality. Likewise T10/T15/T16 retain 37 preference contracts; scope removal never changes preferences, phase counts, settlement topology or thresholds.

## Persisted contract and digest effects

F01 automatic v2-v2, operator v3-v3, candidate manifests and operator state evidence contain the ordered seven scopes. Their canonical assessment digest includes the scopes, identities, attempts and observations. Exact old payload support is in `fixture_coverage.py:423` and `fixture_coverage_codec.py:60`. No hash or record is rewritten.

F06 root scopes, policy snapshot canonical JSON, provider-health references, membership set and per-fixture decisions bind exact assessment lineage. Its root ID at `matchweek_membership.py:433` includes assessment/policy identity; root digest at 505 includes all retained fields. Removing BEL also changes membership IDs even for continuing leagues because the freeze ID changes. Observation payloads at 709 reference exact freeze/assessment and carry complete scope states.

Acquisition plan hashes at `ingestion.py:4972`, run input digests, T05 snapshot manifests, T16 reproducibility records and T19 recorded corpus digests depend directly or transitively on the declared league set. F04 health format is single capability/query scope, not a fixed seven array. F05 health identity is exact assessment digest plus attempt ID. New F01 digest therefore yields distinct health provenance, with no old record migration or reuse by rewriting references.

Causal descriptor at `causal_candidate.py:49` contains exact freeze/common-cutoff/profile/decision-policy/engine digests and logical Matchweek. Freeze canonical bytes are protected at 112. Its closed schema validates exact key/version at 161. Candidate digest binds changed scope transitively, but an explicit successor collection identity is still needed to prevent calling six and seven the same prospective population.

Causal selection graph at `causal_selection.py:66` binds freeze/candidate/f16/common cutoff, with protected selection/completion manifests. F19 at `f19.py:347` resolves exact freeze and logical Matchweek for causal admission. A new active scope does not authorize new trust profile or weaken `U < T`, CB01 `T < signed genTime < kickoff`, or exact predecessor settlement correction.

Source authorization selected projection at `source_manifest.py:246` binds exact candidate/freeze/selection graph. Every new graph requires its own manifest and current classification, with minimal needed provider entries. Old seven-family approvals cannot be assumed to approve new graph identity. Acquisition classification scope at `source_authorization.py:434` is provider/endpoint/competition/season/capability, not target-set cardinality. Preserve existing classifier/authority bytes; do not provision authority.

## F01-F06 meaning

The new required scope is explicit six, while the completeness bar stays identical. Every declared scope must have complete-current coverage or affirmative empty, exact identity, deterministic bounds and source-backed freshness. Omitted required scope remains UNKNOWN and blocks F06. BEL does not appear in a successor assessment at all. F03 persistence/replay and F06 create/replay/observation dispatch must resolve the same immutable contract; accepting arbitrary cardinality would introduce the forbidden dynamic scope.

F02 acquisition has separate full-window evidence and source currentness gates. F04/F05 preserve all attempted providers and failures for exactly requested scopes. F06 keeps all canonical included/excluded candidate decisions, status reasons and LF14 semantic integrity. Full Friday 00:00 through Tuesday 00:00 exclusive Africa/Lagos window remains unchanged, as does common cutoff policy of explicit 21600 seconds before earliest eligible kickoff. Removing BEL can change earliest included kickoff, and therefore all cutoff-bound downstream digests and remaining collection time. Old common cutoff is never recomputed.

## Denominators, #70 and #86

For a new six freeze, the included denominator is
`D6 = count(INCLUDED six-scope memberships) × count(enabled preferences)`.
The full audit view also retains EXCLUDED memberships and every missing, failed,
unavailable or unattempted included preference pair. For otherwise identical
membership facts, removing `b` included Belgian fixtures removes `b × P` included
pairs. There is no fixed proportional adjustment; changed current revisions or
cutoff lineage can also change the new run's facts.


`cb01_evaluation.py:124` constructs exact F06 memberships × enabled preferences before evidence joins, retaining INCLUDED missing rows and EXCLUDED rows. `research_capture.py:550` forms the capture denominator, while 1119 verifies exact included membership × profile and 373 prevents successor index changing size. CB01 core does not divide by seven. For a new six freeze the denominator changes by actual BEL membership, not a hard-coded one-seventh. Existing historical seven denominator must stay complete even when filtered display omits BEL.

The current `MatchweekEvaluation.included_count` at `cb01_evaluation.py:67` counts denominator rows, so it is a preference-pair count, not independent fixture sample size. Do not relabel it as matches during migration. Effective evidence still groups canonical fixture/Matchweek and temporal dependence. T18 `_settlement_metrics` at 1151 calculates match-level rates from actual observations, and `_subgroup_rows` at 1190 groups by exact league/family/line. BEL removal changes population weights, subgroup support, avoid/recommendation/false-positive/calibration sample membership. Mathematical formulas need no seven-to-six coefficient change. Future role manifests and evaluation cohorts must identify the active scope version so a success-only subset or mixed historical seven population cannot silently become six prospective evidence.

#70 remains OPEN needs-info. Scope removal supplies no estimators, support mappings, numerical calibration, genuine evidence roles, validation or fitting. Existing seven-league historical CSVs, CB01 evidence and synthetic releases stay retained in their original versions. They may be referenced only under explicit historical/development role rules, never silently upgraded to contemporaneous six evidence.

#86 remains a CLOSED historical completed seven-scope implementation. Add a successor ticket for six collection/index/cohort dispatch. Keep it inactive until source and causal authority gates are separately operational and six scope schedule completeness is proved. No new fitting/validation/final-evaluation role assigned here.

## Historical identity and schema recommendation

Smallest safe design is a protected active-scope contract artifact with stable contract/version identity, exact ordered six league identities and season, plus digest. Retain legacy seven identity catalog and infer legacy seven only for exact old F01/F06 policy version pairs. New writers require an explicit six contract; no current-default fallback in old readers.

Use successor automatic F01 contract `fixture-coverage-v4-v4`, schema 4, carrying exact active contract digest/ordered scopes. This is the planned successor identity, distinct from old v2/v3; it is not implemented. F06 can retain `matchweek-membership-freeze-v2` envelope/payload1 and use explicit new membership policy3 with a complete embedded active-scope contract/digest. This is a new semantic policy, consistent with existing policy1→2 separation. New policy3 must preserve LF14 policy2 integrity and admit only the exact corresponding F01 successor. Later observation must use freeze policy and compatible assessment version; no cross-scope reattachment.

SQLite migration is not intrinsically required for this design. `store.py:2373` permits arbitrary nonempty F01 contract and positive schema version. `store.py:2880` already carries policy JSON and dynamic scopes; policy version is nonempty and scope count is not constrained by SQL. The offline full-Store SQL proof accepts six scope entries and policy3 storage shapes with unchanged schema version. Exact domain dispatch and protected scope-reference closure still require implementation and tests. If implementation instead changes F06 envelope contract/payload or adds new SQL columns, current `store.py:2907` hard CHECK requires additive schema work. Do not change old migration statements/checksums or rewrite manifests to force that path. Prefer the policy-based design that avoids this need.

Current logical Matchweek ID and reserved slots are season/Friday-only, `research_identity.py:6`; `causal_candidate.py:290` rejects competing associations. ADR 0003 explicitly keeps slot identity independent of protocol version. Preserve occupied historical week denial and start six prospective runs at a new declared effective week. A different scope version must not permit retrying/requalifying an occupied seven week. If a future requirement needs parallel independently scoped histories at the same Friday, that is a separate slot/authority contract amendment, not an incidental part of this change. No such change is needed now.

## Version and artifact dispatch

The recommended successor is explicit and fixed. The planned active-scope artifact
has `id=matchvet-active-scopes`, version 2, season `2026-27`, the six ordered existing
canonical league identities, and a digest over canonical content. Version 1 denotes
legacy seven where old formats already define that scope. Old metadata such as
`2026-27-target-leagues-v1` is retained exactly; it is not rewritten into the new artifact.
No artifact or runtime implementation of this proposal is created by this audit.

| Contract | Retained interpretation | Successor plan |
| --- | --- | --- |
| Target identity catalog, team mappings, source captures | Seven leagues remain identifiable and replayable; LF05 BEL mapping stays manual | Activity is a separate six contract; no team, fixture, or origin identity is recreated |
| F01 `fixture-coverage-v2-v2`, schema 2 | Automatic seven scope assessment, exact bytes/digest | `fixture-coverage-v4-v4`, schema 4, with exact active-scope reference and six scopes |
| F01 operator-attested v3, candidate manifests, LF02 state evidence | Seven scope manual contract and exact candidate/attestation linkage | Keep historical/emergency path. No relabeling as automatic six authority |
| F03 assessment rows and protected artifact closure | Exact version, assessment bytes/digest, scopes and references | Add explicit version admission and replay; old bytes are never converted |
| F04/F05 per-attempt health | Capability/query-specific records tied to exact attempts and assessment | Same evidence meanings, new assessment references; no healthy-feed shortcut |
| F06 freeze-v2 payload 1, policies 1/2 | Seven scopes, exact controlling revisions and old policy snapshots | Same envelope, explicit policy3 canonical JSON binds six contract and F01 schema 4 |
| F06 observations | Exact original freeze/policy and later assessment | Dispatch from retained freeze policy; incompatible scope lineage refuses |
| F07 cutoff and per-match references | Original earliest included kickoff and original T | Same temporal rule on new six freeze, new identity/digest; no old T recomputation |
| Candidate, F11/F13/F14/F15/F16 selected graph | Exact inputs, revisions, freeze/cutoff/profile/model/policy/software closure | Admit explicit successor dependencies, bind six identity in protected closure; new descriptor versions only where closed schemas require them |
| Capture index v1/v2 and chronology 0.2.0 cohorts | Original seven scope and original denominator | Index v3/schema 3 plus explicit six prospective cohort descriptor and activation boundary |
| CB01 enrollment, outcomes, F19 attachments | Exact original pair, graph, witness and settlement correction lineage | Bind new six enrollment/selection. Preserve timing and failure semantics |
| Source manifest and #89 decisions | Exact graph dependencies, retained classifications and risk-policy digest | New exact projections/classifications for new dependencies and separately supplied current authority; no authorization inferred from cache |
| T05/T16/T18/T19 V1 formats and reports | Original seven membership, reproducibility and evaluation population | Separate active entry points, metadata and six qualification corpus; unchanged old readers |
| Logical Matchweek and reserved witness slots | Season/Friday identity, one winner including failed occupancy | Same slot functions; six begins at a declared future unoccupied week |

Scope removal changes the F01 assessment digest, F05 assessment references, F06 policy,
freeze ID/digest, scope snapshots, membership IDs/set digest, F07 references and possibly
T, then candidate/run/model/decision/F16 selection closure, capture index, source manifest,
CB01 enrollment and F19 attachment identities. Per-response byte digests and canonical
team/fixture IDs stay as originally retained. New artifacts receive new hashes; old
manifests, receipts, closure references and denominators never undergo a six-scope rewrite.

## Dependency paths without a literal seven

The full text inventory is supplemented by these semantic dependencies. These modules
need compatibility checks even when their payloads have no seven-entry array.

| Exact modules | Audit disposition |
| --- | --- |
| `src/matchvet/cli.py`, `causal_candidate_cli.py`, `causal_dispatch.py` | New active route must require explicit successor identity and use compatible scope admission; legacy command meanings remain versioned |
| `src/matchvet/provider_health.py`, `provider_health_acquisition.py`, `provider_health_repository.py` | Retain per-attempt semantics, link new assessment identity, verify ordering/closure |
| `src/matchvet/matchweek_membership_integrity.py`, `match_evidence_cutoff.py` | Keep identity/timezone resolution across complete legacy catalog; policy3 inherits LF14 checks, F07 verifies exact successor freeze |
| `src/matchvet/f11.py`, `f11_contracts.py`, `f13.py`, `f13_contracts.py`, `f14.py`, `f15.py`, `f15_inputs.py`, `f16.py` | Exact freeze/cutoff/candidate inputs and protected closure must accept declared successor versions without changing old evidence/estimand/consumer meanings |
| `src/matchvet/causal_candidate.py`, `causal_selection.py`, `matchweek_research.py`, `research_identity.py` | Scope identity propagates through graph admission; keep permanent slot denial, single assignment and exact replay |
| `src/matchvet/cb01.py`, `cb01_evaluation.py`, `cb01_replay.py`, `cb01_schema.py`, `cb01_sources.py`, `f19.py` | Full denominators, exact original enrollment and outcome authority remain. Cohort identity distinguishes six from seven; no causal protocol rewrite |
| `src/matchvet/source_manifest.py`, `source_authorization.py` | Existing current authorization and selected projection semantics stay; new graph closure must be demonstrably bound to six policy |
| `src/matchvet/store.py`, `artifacts.py`, `t17.py` | Mixed old/new storage and protected artifact backup/replay; preserve released migrations and retained catalogs |
| `src/matchvet/t09.py`, `workload.py` | Queries can legitimately use retained out-of-scope history as Research Context; they must not make those rows Target Matches or infer new six prospective evidence roles |
| `src/matchvet/t16.py`, `t18.py`, `t19.py` | New population metadata and separate corpus; retain original report formats, estimands, subgroup metrics and original release claims |
| `scripts/live_fixture_smoke.py:62` | Legacy loop uses `TARGET_LEAGUES` and direct transport. It is not an authorized six operational path. A successor probe/entry point must use explicit scopes and #89/#90; no execution or modification in this audit |
| `scripts/build-t19-manifest.py`, `compare-t19-replays.py`, `qualify-research-release.sh` | Preserve historical seven corpus and qualification. Add separate successor qualification rather than replacing the recorded contract |

`pro_league_team_alias_registry.py`, its v1 JSON, and
`operator_fixture_observation.py` remain available for historical Belgian identity
and manual observation replay. Removing active Belgium does not delete them or
change their authority. `weather_provider_health.py` and workload's numeric 7-day
horizons have no seven-league requirement. The reference inventory includes these
matches so an implementation does not mistake unrelated numbers for scope counts.

## Tests and golden artifacts

Retain exact existing seven fixtures/goldens and seven test assertions. Add parallel six tests rather than rewriting expected old arrays or digests.

| Exact files | What stays historical / new cases needed |
| --- | --- |
| `tests/fixtures/f01_v2_unknown_2026_09_25.json`; `tests/test_fixture_coverage.py:107`, `284`, `345`; `tests/test_fixture_coverage_repository.py:90` | Preserve seven scope/digest golden. Add successor six complete/affirmative-empty, missing declared scope UNKNOWN, explicit extra BEL refusal and mixed-version decode refusal. |
| `tests/fixtures/lf07_v1_empty_attestations.json.gz`, `lf07_v1_v3_empty_assessment.json.gz`, `lf07_v1_conflicting_attestation.json.gz`, `lf07_v1_conflicting_candidate_manifest.json.gz`; `tests/test_operator_fixture_attestation.py:1035`; `test_operator_fixture_attestation_cli.py:494` | Keep legacy exact seven operator path and historical bytes. Do not reinterpret manual registry as successor automatic authority. |
| `tests/fixtures/lf05_v1_observation.json`; `tests/test_operator_fixture_observation.py:87`; `tests/test_lf09.py:106`; `tests/test_lf03.py:634` | Preserve BEL observations, 18 canonical identities and existing registry digests. |
| `tests/test_ingestion.py:197`, `358`, `583`, `674`, `723`; `tests/test_provider_health_f05.py:871`; `tests/test_t09.py:807` | Historical all-seven acquisition tests remain; add six successor plan exact scope and no BEL request, failed attempts, plan digest versions, mixed historic store candidate filtering. |
| `tests/test_matchweek_membership.py:1014`, `1045`, `1876`; `tests/test_lf14.py:352`; `tests/test_match_evidence_cutoff.py:246` | Keep legacy seven gate/replay. Add six all-empty/complete, canonical order, wrong scope/hash, policy3 LF14 integrity, observations, earliest-six cutoff and old cutoff replay. |
| `tests/issue84_support.py:346`, `578`; `tests/test_issue78.py:73`; `tests/causal_selection_support.py:62`; `tests/test_research_capture.py:161`, `538` | Add six synthetic integrated graph separately, no mixed cohort/denominator, occupied old slot refusal and no authority activation. |
| `tests/test_t19.py:222`; `tests/recorded/t19-seven-league.json`; `scripts/qualify-research-release.sh:124` | Preserve seven replay/golden 259 preference/grade counts and seven-target model expectations. New six golden counts derive actual included fixtures, not indiscriminate `7→6` replacement. |
| `tests/test_cb01_repository.py`, `tests/test_cb01_schema.py`, `tests/test_cb01_sources.py`, `tests/test_cb01_trust.py`, `tests/test_f19.py`, `tests/test_source_authorization_review.py` | Preserve exact historic receipt/source/settlement semantics. Add explicit six scope cohort selection, full missing/failed/unattempted denominator and exact lineage proof. |
| `tests/test_f11.py`, `tests/test_f12.py`, `tests/test_f13.py`, `tests/test_f14.py`, `tests/test_f15.py`, `tests/test_matchweek_research.py`, `tests/matchweek_research_support.py`, `tests/test_causal_protocol.py`, `tests/test_causal_witness.py`, `tests/test_causal_activation.py`, `tests/causal_activation_support.py`, `tests/test_source_authorization.py`, `tests/source_authorization_support.py` | Check all exact successor input/version/closure paths and old reader compatibility. Scope version cannot bypass occupied slots or provision current authority. |
| `tests/test_t16.py`, `tests/test_t18.py`, `tests/test_store.py` | Keep historical metadata/defaults and 37 preference semantics. Add successor scope metadata and representative old+new SQL/store replay proof before implementation merge. |

The linked reference inventory records every tracked baseline seven/BEL/UEFA/catalog match, including compressed-golden digests; supplemental dependencies are listed above. Several results are phase, nonce or 37-preference counts and must remain unchanged. Generalized builders such as those using TARGET_LEAGUES are semantic dependencies even when their test names contain no seven.

## Documentation and ADR disposition

Current scope-defining prose is `GLOSSARY.md:11`, `14`, `35`, `38`, `47`; `docs/product-v2/PRODUCT-DIRECTION.md:13`, `19`, `21`; `docs/product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md:16`; roadmap live frontier at `IMPLEMENTATION-ROADMAP.md:19` through 23. New direction must say fixed six active leagues and clarify paid data constraint. The existing product paragraph says no paid football data or infrastructure; this user instruction limits the hard dependency requirement to data providers and does not ban ordinary infrastructure costs.

README:15/55/98 seven references describe implemented legacy ingestion/release checks. Mark them historical implementation capability instead of falsifying completed seven replay. Preserve `docs/research-only-release-qualification.md`, `docs/product-v2/V1-MIGRATION-AUDIT.md`, `docs/superpowers/plans/2026-09-20-t19-research-only-release-qualification.md`, and all retained Belgium qualification documents.

Active design prose requiring seven is in `docs/design/matchweek-wide-evidence-cutoff.md:14`, `93`, `109`, `156`; `docs/design/causal-matchweek-selection-witness.md:82`; `docs/design/research-source-authorization.md:21`; `docs/design/causal-matchweek-implementation-tickets.md:14`, `139`; `docs/product-v2/CANDIDATE-INPUT-STATUS.md` frontier/current blockers plus dated seven history. Update current prospective pointers explicitly while preserving dated seven decisions. `docs/design/lf13-official-fixture-observations.md:31`/76 and LF14 semantic-integrity docs remain historic contracts; add successor pointers where needed.

ADR 0001 records seven-slate original timing rationale; successor decision amends active scope but keeps common-cutoff and historical identities. ADR 0003 reserved slot identity rule remains unchanged. ADR 0004 estimands/consumer boundaries and ADR 0005 trust premises remain unchanged. ADR 0006 risk acceptance cannot substitute for remaining six schedule source proof or provide live authorization. Do not edit its bytes because `source_manifest.py:37` pins ADR digest.

## Implementation tickets and issue disposition

The four planned corrective tickets are outside the original 53-ticket total.
They are OPEN `ready-for-agent`, with native dependency edges. This audit implements
none of them.

| Ticket | Boundary | Native prerequisites |
| --- | --- | --- |
| [#98](https://github.com/Awisalas/match-vet/issues/98) | Fixed active-scope registry, F01 schema 4, F02/F03/CLI successor routing and mixed-store BEL exclusion | None |
| [#99](https://github.com/Awisalas/match-vet/issues/99) | F06 policy3 with all LF14 integrity, exact observations, F07 lineage and real old/new replay | #98 |
| [#100](https://github.com/Awisalas/match-vet/issues/100) | Index v3, six cohort identity, source/causal closure, CB01 denominator and F19 lineage | #98, #99, existing #93 and #94 projections |
| [#101](https://github.com/Awisalas/match-vet/issues/101) | Separate six offline release qualification corpus and operator documentation | #98, #99, #100 |

#92 is CLOSED `NOT_PLANNED`, superseded by this six-league product decision.
It is not a successfully completed Belgian adapter. Its former source-contract
requirements and dependency history remain retained. #91, #95, #96 and #97 remain
CLOSED completed under their insufficiency outcomes; their research is not deleted.

#70 remains OPEN `needs-info`, with #100 as a new native blocker. Scope removal
supplies no missing numerical profile, calibration, support validation or genuine
chronological cohort. #86 remains CLOSED as the completed historical seven-scope
bootstrap; #100 adds the explicit successor. #93/#94 remain separate planned
projection work and are not implemented or researched in this audit. Their retained
records can serve only exact declared population/selection roles.

The original #1 seven-league product specification receives an explicit decision
pointer while keeping its historical body. No source or causal owner approval is
provisioned, no provider activated, and no fitting or PLAY authorized.

## Confirmed risks and cleared concerns

High certainty/high cost: editing global TARGET_LEAGUES breaks legacy F01 decode, proven offline. T19 also requires the exact old catalog at lines 319 and 873; that dependency is verified in source, not rerun here. Remedy is versioned dispatch with old catalog retained.

High certainty/high cost if policy3 is merely whitelisted: LF14 checks selected by equality to policy2 would be skipped. Exact code at membership repository 971/981/985/1744/1773. Before merge use a six policy3 integrity test with reversed teams, typed date/instant conflict and corrupt source reference, and require refusal.

High certainty/medium-to-high cost: six acquisition alone leaves legacy F01 seventh UNKNOWN, and retained BEL rows reenter T05 selector through season-only query. Prove successor exact six scope and historical-BEL-containing store does not include BEL in new freeze.

High certainty/high cost: filtering denominator after evidence joins discards missing/unattempted failures and can bias #70 population. Existing exact denominator loops are good; add scope/cohort binding rather than posthoc row filtering. New six evidence cannot silently join old seven cohort under same label.

High certainty/high cost: changing protocol/scope to evade an occupied Friday would conflict with ADR 0003 permanent refusal/one-winner contract. Keep slot identities, explicit new-week boundary and no rewrite/requalification.

Cleared: no league cardinality in run completion's seven phases; no preference count change; F04 per-query records are naturally scoped; T18 formulas derive actual rows, not denominator seven; canonical BEL identity tables/registries can remain for replay; SQL representation supports new policy3 six set without schema change under the recommended envelope. Production future dispatch/replay is still unproven and must be tested by implementation tickets.

Open blockers are successor scope/version implementation; qualified complete-current zero-cost contracts across the remaining six and exact source/currentness evidence; source and causal authority operational controls; non-executable #70 methodology and genuine explicit evidence cohorts. No live source, production activation or fitting action is justified by this audit. The corrected downloader requires separately supplied current authority at `ingestion.py:3415`; that default refusal remains unchanged.

## Documentation disposition and inventory coverage

The machine inventory contains 530 baseline text matches across 80 paths, with exact lines,
including false positives cleared above. It records seven retained fixture/golden
files with byte counts and digests. The LF07 conflicting candidate manifest is
included even though a text grep cannot see its compressed content. Future changes
must add successor fixtures beside these originals.

Current product definitions change in `GLOSSARY.md`, `PRODUCT-DIRECTION.md`,
`ARCHITECTURE.md`, the current frontier of `IMPLEMENTATION-ROADMAP.md`,
`CANDIDATE-INPUT-STATUS.md`, and the README's active-scope notice. Current prospective
pointers are added to `docs/design/matchweek-wide-evidence-cutoff.md`,
`causal-matchweek-selection-witness.md`, `research-source-authorization.md`, and
`causal-matchweek-implementation-tickets.md`. Their implemented seven contracts
remain historical. ADR 0007 explicitly supersedes ADR 0001's active seven premise,
without changing the common-cutoff rule or rewriting ADR 0001.

The following documents retain their historical populations and claims. A current
reader uses ADR 0007 and this audit rather than interpreting them as live readiness:

- `docs/product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md`, methodology 0.1.0/0.2.0,
  and `V1-MIGRATION-AUDIT.md` retain their original chronology, estimands and cohorts.
- `docs/research-only-release-qualification.md` and its JSON, `docs/run-lifecycle.md`,
  and the T19 implementation plan retain the released seven replay and lifecycle
  meanings. Seven lifecycle phases are unrelated to the league count.
- `docs/design/lf13-official-fixture-observations.md` and the LF14 design retain
  manual mapping and seven membership contracts.
- Dated research under `docs/research/` retains the earlier seven-league source
  capability/coverage audits, contextual inventory, statistical-method and dataset
  assessments, source permission/risk decisions, automated closure proposal,
  #89 review, and all Pro League/Football Charts qualification evidence. The
  inventory lists each exact matched path. These are evidence of earlier decisions,
  not new active-scope defaults or qualified six source contracts.
- ADR 0002 remains the historical actual-at-return diagnosis. ADRs 0003/0005 keep
  occupied-slot and conditional causal assurance semantics; ADR 0004 keeps
  CandidateInput estimands and consumer boundaries. ADR 0006's bytes/digest are
  preserved because the source policy pins them.

## Review synthesis and audit checks

Three independent audit attempts were launched as required by the blast-radius
skill's arena workflow. Usage limits stopped candidates 1 and 2 before complete
writeups; candidate 3 left a complete document, and candidate 2 left a stronger
executable proof. A separate readonly judge scored the surviving document 22/25
and recommended candidate 3 as document base with candidate 2's full-Store proof.
The final audit adds the script disposition, complete reference inventory, version
and closure tables, and explicit source/replay boundaries. Candidate 1's incomplete
proof was not used. No model agreement is treated as source or runtime evidence.

Checks for this audit are the offline proof, exact inventory locator/line checks,
retained golden integrity, canonical league/team mapping consistency, ADR 0006
pinned digest, changed-document links/anchors/tables/fences, issue states and native
dependencies, proof formatting/lint, unchanged production/tests/migrations, and
`git diff --check`. No live football requests or broad test suite are run. The
known unrelated CB01 `_support`/`f14_digest` and F16 defects are left untouched.

The next implementation boundary is #98. After the successor contracts are built,
qualified complete-current zero-cost source contracts for every remaining active
scope and independently supplied current source/causal authority still block live
collection. Removing BEL resolves that product dependency only; it does not prove
those six source contracts or clear #70.

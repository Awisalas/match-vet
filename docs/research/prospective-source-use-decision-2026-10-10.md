# Prospective #70 source-use decision

Reviewed 2026-10-10 against repository commit
`3b401ad33287fbde1e7591c098cdd58854ed4569` and current primary terms.
Scope: one prospective RESEARCH_ONLY #70 selected graph and its bounded #86
continuation. This record defines a proposed successor contract; it grants no
source permission, runtime authority, acquisition, or Product Promotion.

## Verdict

Require a versioned successor to `research-real-source-use-decision-v1`, binding
an explicit immutable source-use manifest. Current evidence does not clear the
actual seven-scope football paths for new prospective collection. Create no
implementation issue yet. Obtain the specific human/provider evidence below
first. #70 remains OPEN with `needs-info`; #86 and #87 remain CLOSED. Causal
mechanics are complete; production owner provisioning and source authorization
remain separate and unprovisioned.

The [current primary permission review](real-source-permission-evidence-2026-10-10.md)
contains source-specific terms, access failures, review/effective dates and gaps.
Earlier [LF01 audit](upcoming-fixture-coverage-source-audit-2026-09-27.md),
[fixture capability review](upcoming-fixture-provider-capability-2026-09-23.md),
[manual-source research](live-blocker-source-research-2026-09-29.md), and
[contextual inventory](contextual-source-inventory-2026-10-03.md) explain existing
paths. Their past permission conclusions do not prove today's terms unchanged.

## Existing contract and exact binding

[research_capture.py](../../src/matchvet/research_capture.py) calls the separately
controlled `SourceUseAuthorizer` before an enrollment continuation. It verifies
one protected canonical decision containing exactly contract, freeze_digest,
profile_digest, scope_ids, selection_digest, state and reason_codes. V1 states
are APPROVED and WITHDRAWN; replay compares that exact body. No authorizer means
refusal. The seam does not itself implement permission review or pre-acquisition
authorization. Historical capture-index replay does not call an authorizer.

[Causal graph admission](../../src/matchvet/matchweek_research.py) replays F16
under an exact artifact catalog and captures every verified artifact reference.
[F11](../../src/matchvet/f11.py) replays fixture provenance, source captures,
locations, weather responses, F09 health and F12 attempts.
[F13](../../src/matchvet/f13.py) binds retained historical rows and their exact
source snapshots, but explicitly does not certify upstream authenticity.
These identity checks do not establish permission. In particular, a normalized
history snapshot or an internally labelled source is not a retained rights grant.

An exact selection_digest can be sufficient *identity binding* under the premise
that the authorizer traverses every dependency and checks all applicable rights.
It cannot bind permission evidence that was never part of the selected graph.
Two authorizers could approve the same graph under different terms, operator-use
classifications or retention assumptions, yet produce the same V1 body. Offline
replay cannot distinguish them or explain the verdict. Even an excellent transient
validator does not solve that retained-evidence gap. The safer simple design is
one manifest plus one decision, both content-addressed, with no new legal registry
or mutable per-provider blanket approval.

## Actual source-use matrix

Statuses apply to the named operation, not an entire publisher. CONDITIONAL grants
no operational approval while a condition is unresolved. UNKNOWN never approves.
Only self-authored records without external content are permitted at the class
level; no complete real graph is currently approved.

| Current path / source class | Prospective disposition | Required retained evidence and limits |
| --- | --- | --- |
| F02 OpenFootball JSON and Football.TXT schedule captures; T06 retained rows; packaged club-alias evidence | CONDITIONAL for repository-owned CC0 contributions; UNKNOWN for unresolved upstream schedule rights | Pin exact repository/file revision, CC0 identity, actual upstream publishers and grants. JSON and TXT share lineage. Raw file, normalized facts and private backup/replay require separate affirmative coverage. The repository dedication cannot clear another publisher's rights. |
| T06 Football-Data.co.uk results/statistics/history, or its weekly fixtures; wrapper-derived copies | PROHIBITED for the published excluded automated commercial/data-training use; UNKNOWN for MatchVet's proposed research classification and durable retention without clarification | Current [use statement](https://football-data.co.uk/data.php) limits intended users and excludes specified automated products. `RESTRICTED_PRIVATE` in MatchVet is no external grant. Require written scope-specific permission including upstream rights, automated use, normalized/raw storage and backup/replay, or replace the input. Do not infer that every private script is categorically prohibited. |
| F11/F12 Open-Meteo forecast response and F09 health | CONDITIONAL | [Current terms](https://open-meteo.com/en/terms) distinguish noncommercial API access from commercial research. Record actual operator/use classification, free-tier limits, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en), attribution and transformation notices. Raw and normalized data retention follows the licence; free access does not extend to undisclosed commercial-entity research. |
| LF02 operator coverage attestations | PERMITTED for the operator's own canonical verification record; CONDITIONAL/UNKNOWN for cited external material and base captures | Exact base, scope, candidate manifest, operator, verification event, policy and official citation identities remain. The attestations cannot clear automatic base-source rights or publisher database restrictions. No official body/PDF/screenshot/bulk copy. No Provider Attempt or Health. |
| LF05 v1 Belgian and LF13 successor v2 official fixture observations across accepted scopes | CONDITIONAL internal manual path; UNKNOWN external permission wherever not established | Exact observation, publisher/publication/URL, minimal fixture facts, operator/time and manual policy digest. Human reading and entry only. These create ordinary source provenance, never Provider Attempts/Health or completeness proof. LF02 remains separate. |
| Official/manual contextual injury, availability, discipline, expected-lineup, manager/referee evidence | UNKNOWN until exact publisher/use review | F10 requirements and the F08 hierarchy grant no ingestion permission. Missing research remains UNPERFORMED/UNKNOWN. No generic extension of the fixture-citation policy and no assumed permission for club/social/press content. |
| Explicit F11 context fixtures, venue coordinates, F13 retained datasets/calibration/input snapshots | CONDITIONAL on each exact external dependency; UNKNOWN without lineage/permission basis | Include source/assertion/revision IDs, raw or normalized representation, dataset licence and upstream grants. Operator-supplied rows or coordinates are not automatically operator-owned facts with cleared rights. A self-authored normalized snapshot cannot erase upstream restrictions. |
| Derived workload, F13 model/calibration/prediction, F14 CandidateInput/decision, F16 assembly | CONDITIONAL on the selected dependency closure | Preserve all upstream source-use IDs and rights constraints through derivation. Computation grants no new rights. Same-lineage material stays visible. Missing model/research facts retain their existing states. |
| OpenFootAPI, football-data.org, API-Football, OpenLigaDB and other researched alternatives | Not configured authorization paths; CONDITIONAL or UNKNOWN as detailed in the primary review | API availability and wrapper terms do not authorize unresolved upstream uses. A licensed subset does not replace all-seven evidence. No adapter/provider activation follows from this record. |
| Official-site scraping, automated pages/PDFs, archived screenshots or bulk official schedules under LF02/LF05 | PROHIBITED by those MatchVet paths; some publishers also expressly restrict these uses | Any different path needs its own source grant and versioned persistence design. Public accessibility is never automation, retention or redistribution permission. |

The [rights registry](../../src/matchvet/ingestion.py) currently records CC0,
RETAIN_REUSABLE and redistributable for OpenFootball, and RESTRICTED_PRIVATE /
RETAIN_PRIVATE for Football-Data. [F05](../../src/matchvet/provider_health_acquisition.py)
projects those categories to PERMITTED for its intended use. These are historical
repository policies, not sufficient current rights evidence for #70. Preserve
their bytes and meanings; assess prospective source use separately, fail closed,
and require a separately reviewed versioned disposition before relying on those
categories for new acquisition/export. No F01/F06 or health semantics change.

[T17](../artifacts.md) backs up every catalogued object needed by the database.
Raw export is separate and only allowed for reusable/redistributable captures.
A private backup still needs permission to copy and retain the exact representation.
A citation-only policy must not masquerade as raw-retention permission or silently
omit a raw object needed by replay. Restricted redistribution is acceptable for
private #70 work if that operation is not requested; unknown required retention
or backup rights are not acceptable.

## Proposed minimal successor

Use `research-source-use-manifest-v1`, schema 1, and
`research-real-source-use-decision-v2`, schema 2. These are design names only.
Retain canonical UTF-8 JSON in protected content-addressed artifacts. Sort unique
dependencies and permission dimensions, reject unsupported fields/versions and
duplicate/conflicting entries. SHA-256 of exact canonical bytes is immutable
identity, not decision authority.

The manifest binds exact selection_digest, graph_digest, F16 manifest digest,
candidate contract, freeze digest, preference profile, cutoff/decision policies,
logical Matchweek and the seven scope IDs. It enumerates every source-bearing
dependency used or retained for that graph, including base F01 attempts/captures,
LF02 and manual observations, rejected/conflicting source evidence retained by
the selected assessment, fixture history, aliases, locations, F09/F12 weather,
F13 historical/calibration/numerical inputs and their upstream origins. Scope is
the selected closure, not the entire Store. Pure software/policy artifacts get
their exact version references without invented third-party source permissions.

Each source-use entry contains only:

- An exact dependency ID/digest and role, plus every graph reference consuming
  it. For database-resident facts, retain the canonical selected identity/facts
  and source/assertion/capture/revision references needed to cross-check replay.
- Source type and access mode: AUTOMATED_API, AUTOMATED_DATASET,
  RETAINED_DATASET_REUSE, MANUAL_CITATION, OPERATOR_ATTESTATION or DERIVED.
  Identify provider, publisher, legal grantor and source locator separately.
- Upstream source-use IDs and a stable shared lineage ID. Unknown upstream
  identity is explicit UNKNOWN. A wrapper grant cannot replace an upstream grant.
- Exact terms/licence/permission-letter identity, URL, version/digest of lawfully
  retained permission evidence, review timestamp, effective date and validity
  bounds or an explicit unspecified date. Bind the operator's real use
  classification and versioned MatchVet policy, including manual policy where
  applicable. No invented effective date or automatic reuse of stale reviews.
- Applicable league/season/scope/capability and requested operations. Distinct
  permission results for automated or manual access, internal RESEARCH_ONLY use, raw retention,
  normalized retention, backup/replay, attribution duties and redistribution.
  Each records PERMITTED, PROHIBITED, UNKNOWN or NOT_APPLICABLE plus basis and
  reason. Retention includes representation, duration, deletion/termination
  constraints and allowed backup recipients/location where specified.
- Source-use result APPROVED, REFUSED or UNKNOWN with exact reasons. APPROVED
  requires every requested operation permitted and all duties satisfied.
  NOT_APPLICABLE needs a concrete explanation and cannot hide a required use.

The V2 decision binds the exact manifest digest and all graph/freeze/profile/scope
identities, RESEARCH_ONLY #70 purpose, independently configured decision-authority
identity, signed decision identity, issue time, validity/current-state evidence,
state and sorted refusal reasons. The maintainer/product owner controls the
review boundary; an operator attests what was checked but cannot grant another
publisher's rights. A caller-supplied authorizer/key, protected artifact or
self-nominated issuer is not independent authority. Use a maintained signature
primitive and a separate domain/configured trust boundary when later specified;
causal-owner activation supplies no source authorization.

Decision states are APPROVED, REFUSED, UNKNOWN, WITHDRAWN and SUPERSEDED. Only
an applicable, independently current APPROVED state permits the requested use.
Every other state retains exact reasons and grants no authority.

Authorization changes are append-only, authenticated decisions with exact
predecessor and targeted manifest/decision/source-use identity: approval,
withdrawal or supersession. Require independently current authoritative state
with restore continuity; uncertain, stale or restored-away withdrawal refuses
new use. A successor may authorize another graph/use interval but cannot broaden
the original signed approval or rewrite a retained decision. Current source
authority must be rechecked before each bounded CB01 side effect and result
admission, including withdrawal during a multi-fixture continuation. No new
retry, replacement graph, backfill or witness capability follows.

Replay recomputes the dependency projection from the exact selected graph,
requires equality with the manifest and verifies permission evidence/decision
identity and authority. Never trust a caller-authored manifest claiming complete
coverage. It retains the original review and status rather than fetching latest
terms or upgrading old decisions. Keep V1 decision/capture readers byte-compatible;
introduce explicit successor dispatch/index representation where needed, since
V1's exact-body equality cannot accept added manifest fields. No migration or
released V1 change is established as necessary by this research.

## Timing and withdrawal

1. Before any network acquisition or manual entry, establish the permission for
   that access mode, intended use, raw/normalized representation and planned
   backup/replay. Existing retained data needs reuse rights before new ingestion
   or computation. Retain the exact applicable review/grant with the resulting
   source-use record. Graph approval after selection cannot retroactively legalize
   acquisition. Do not require a selection digest that does not exist yet.
2. Before selection qualification, validate every acquired/retained dependency
   against those permission records. After immutable selection, retain the final
   exact graph manifest and current authenticated decision before #86 CB01
   continuation. This sidecar can be created after selection because it only
   describes and gates the original graph; it adds no prediction input or causal
   timing claim and never changes the witnessed graph. Missing evidence refuses.
3. F19 post-kickoff sources are future evidence, not members of the pre-T selected
   graph. Before their acquisition and attachment/correction, require separate
   source-use records and exact outcome-source authorization bound to the original
   selection plus outcome evidence. A V2 selected-graph approval cannot authorize
   unspecified future outcome sources.
4. Changed/expired terms or authenticated withdrawal prevents new authorization,
   acquisition, reuse or continuation pending a new review. Immutable historical
   inspection reports the original decision; present use/qualification can refuse
   with appended adverse evidence. Historical approval does not imply permission
   for new copies, backups or distribution. If terms require deletion or restrict
   retained replay, obtain a human disposition; do not promise perpetual replay,
   silently delete evidence or rewrite its history. Prefer grants permitting the
   full retained private recovery lifecycle before acquisition.

## Exact human/provider evidence required

No sufficiently cleared current path for the actual seven-scope graph is
established. Therefore no mechanics implementation issue is created. Obtain:

- Football-Data's written permission for MatchVet's exact automated research,
  history/model-input use, raw/normalized retention and private backup/replay,
  covering its named upstream sources, or select a rights-cleared replacement.
- OpenFootball's exact source-chain evidence for selected schedule/history files
  and alias inputs. Clear the actual rights needed from each upstream publisher;
  the repository's CC0 contribution alone is insufficient where upstream rights
  remain unresolved. Do not claim JSON/TXT are independent corroboration.
- Publisher-specific permission or a qualified, jurisdiction/use-specific rights
  determination for minimal official facts/citations and private research database
  retention/recovery in all seven LF02 scopes and any LF05/LF13 observations.
  Address Premier League's database/deep-link restrictions and every applicable
  publisher's terms. A MatchVet policy approval is not that determination.
- The operator/entity's actual noncommercial-use classification for Open-Meteo,
  attribution compliance and licence identity. A RESEARCH_ONLY software label
  does not decide whether a commercial entity's internal work meets free terms.
- Exact source/licence/retention evidence for any added contextual publication,
  venue/location input, historical/calibration dataset and later F19 source.
  Unperformed contextual research may stay UNKNOWN without inventing a source;
  UNKNOWN rights on evidence actually selected or retained cannot pass.
- A maintainer-approved minimal rights matrix, representation/retention plan and
  source-decision authority/current-continuity contract. Then a narrow offline
  mechanics ticket may be specified, preserving manual/provider separation,
  deterministic retained tests, withdrawal, unchanged F01/F06/UNKNOWN semantics,
  separate causal owner controls and blocked Product Promotion.

## Verification boundary

Only primary terms/licence documentation was browsed. No football data, official
fixture pages for ingestion, credentials, live Store, TSA request or collection
was acquired. Production code/tests remain untouched. Checks cover documentation
links, versioned-contract fields, matrix/timing/manual/withdrawal invariants,
issue states and `git diff --check`. No runtime suite is needed for this decision.

# Minimum automated prospective #70 source closure

Decision date: 2026-10-10. Repository inspected at
`006ba5eef4a4f46b61595ef331512ee5a142bbc2`.
The explicit product-owner instruction is recorded in
[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md).
No live source acquisition or provider capability probe occurred in this task.

## Verdict and smallest architecture

Source-use policy is settled for private RESEARCH_ONLY implementation:
`PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED` is an internal authorization basis;
external permission UNKNOWN/REFUSED remains honestly recorded. The earlier
permission-first verdict B is superseded, not upgraded to rights clearance.
Technical feasibility of an all-seven automated closure remains unproven.

Target seven official competition publisher families for schedule, identity,
kickoff/status revisions and genuine F01 completeness/currentness evidence:
Premier League, Bundesliga/exact publication operator, LFP, Lega Serie A,
LALIGA (retain RFEF ancestry if used), Liga Portugal and Pro League. Reuse those
families for history and later final results if their actual fields suffice.
Otherwise add **one** existing Football-Data.co.uk CSV family for a bounded
recent full-time corpus and later goal outcomes. That is seven target families,
or eight with the results fallback, not a proven operational source set. Do not
count an aggregator and its upstream publishers as independent corroboration.
A separately fetched RFEF publication or any other extra publisher adds an
explicit dependency; do not hide it inside the seven-family target.

An aggregate feed could reduce endpoints, but no reviewed free feed proves all
seven current schedules, exhaustion/affirmative empty semantics, revisions,
identity and exact eligible times. The [dated coverage audit](upcoming-fixture-coverage-source-audit-2026-09-27.md)
and [capability review](upcoming-fixture-provider-capability-2026-09-23.md) are
candidate discovery evidence, not present-day capability approval. Qualify
documentation and exact retained fixtures before selecting any provider. Do not
infer a public/private endpoint, pricing entitlement or pagination capability.

Prefer machine-readable official feeds; use documented public publications only
if their semantics support bounded extraction and completeness. A full-season
calendar alone does not prove current kickoff/status revisions. Shared feeds
may supply rows but cannot supply missing coverage assertions by themselves.
The OpenFootball JSON/TXT paths are reusable parsers for optional observations,
not the minimum primary architecture: they share ancestry, omit Belgium in
scheduled acquisition and currently provide no admissible coverage/freshness
evidence. LF02/LF05 remain historical/emergency manual research paths.

## Concrete discovery locators

These are publication locators already retained in the
[LF02 policy catalog](../../src/matchvet/operator_fixture_attestation.py) and
[LF05 policy](../../src/matchvet/operator_fixture_observation.py), not verified
current automated endpoints. No page was acquired here. Reuse the identities
and candidate publications, never their manual policy as automatic coverage proof.

| Scope / candidate family | Existing public locator | Required automatic qualification |
| --- | --- | --- |
| England / Premier League | [Season schedule](https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season), [amendments](https://www.premierleague.com/en/news/1235133) | Exhaustive requested schedule and current amendments, exact kickoff/status |
| Germany / Bundesliga | [Season schedule](https://www.bundesliga.com/en/bundesliga/news/2026-27-season-fixture-schedules-37671), [kickoff updates](https://www.bundesliga.com/en/bundesliga/news/confirmed-kick-off-times-dates-2026-27-fixtures-23955/) | Complete partitions, update coverage, actual timezone/currentness |
| France / LFP | [Retained season locator](https://ligue1.com/fr/articles/l1_article_5284-), [scheduling publications](https://ligue1.com/fr/articles/) | Actual publication identity, exhausted window, controlling revisions |
| Italy / Lega Serie A | [Calendar/results](https://www.legaseriea.it/serie-a/calendario-risultati), [scheduling updates](https://www.legaseriea.it/serie-a/news/anticipi-e-posticipi-fino-alla-fine-del-girone-di-andata) | Complete window, current timings/status; final goals if present |
| Spain / LALIGA | [Season calendar](https://www.laliga.com/calendar-2026-2027/laliga-easports) | Actual public representation, exhaustive coverage, exact kickoff revisions; RFEF separately if needed |
| Portugal / Liga Portugal | [Calendar](https://www.ligaportugal.pt/calendar), [publications](https://www.ligaportugal.pt/news/) | Exact season/partitions and official timing updates, not guessed currentness |
| Belgium / Pro League | [Competition calendar](https://www.proleague.be/jpl-kalender!), [retained timing publication](https://www.proleague.be/fr/informations/les-calendriers-des-fans-fixes-jusquapres-la-treve-hivernale) | First slice: public bounded representation, complete window/revisions and automated-source team mappings |

Football-Data CSV discovery reuses the existing configured season-result URLs
and parser, not its weekly fixture feed as completeness proof. Identify the exact
bounded files/rows, upstream lineage and Time timezone in #91 before using them
for #93/#94. A results page without usable final status/goals or exact history
kickoff cannot fill those gaps merely because acquisition risk is accepted.

## Dependency table

| Dependency / stage | Requirement | Current path and gap | Automated candidate / required operations | If unavailable |
| --- | --- | --- | --- | --- |
| All-seven schedules, F01–F03/F06 | Mandatory | Six OpenFootball scopes; Belgium skipped; coverage/freshness evidence empty; LF02 manual bridge | Seven official publisher families, or an aggregate only after equivalent proof; bounded acquisition, raw/normalized retention, private replay, exact exhaustive scope/partitions/currentness | No eligible freeze; do not reduce seven scopes or fake completeness |
| Fixture identities, kickoff/status revisions, F02/F06/F07 | Mandatory | Canonical importer and append-only revisions exist; DATE facts cannot supply exact kickoff | Same schedule captures; source-backed exact UTC and current revision semantics | Unresolved identity or time prevents eligibility |
| Canonical team mappings, F02/F06 | Mandatory for selected rows | Source-scoped known-team mapping exists; OpenFootball aliases/manual Pro League aliases are not universal | Exact source-scoped mappings validated against existing canonical identities; retain upstream origin, revision, digest and ambiguity | UNKNOWN/unresolved; no duplicate teams or automatic REGISTER_UNKNOWN |
| Recent FT goals and exact kickoff, F13 | Mandatory for usable raw goal predictions; insufficient inputs may retain unavailable records | CSV/results parsers and F13 retained history exist, but no automatic projection connects them | Same official family if adequate, otherwise one Football-Data CSV family; actual goals/status/UTC, raw/normalized retention and derived inputs | No usable prediction for unsupported family; never invent dates or scores |
| F11 contextual evidence | Optional initial diagnostic inputs | Workload/weather seams; UNKNOWN/UNPERFORMED accepted | Retained selected facts only; optional sources below | Honest research rejection records can still complete |
| F14/F16 calibration and optional preference support | Not mandatory to retain diagnostic rejection records | Empty/unsupported inputs retain reasons | No new external source required; evaluate every enabled preference | No justified Primary/qualified numerical fit inferred |
| Later final results, T10/F19 | Required for joined outcome case, separate post-kickoff phase | Typed settlement and capture attachment exist; automatic source projection missing | Reuse official final records or honestly classified FOOTBALL_DATA rows; result status, regulation goals, source observation/lineage and private replay | Pending/unavailable outcome; no backfilled pre-T evidence |
| Licensed commercial distribution / Product Promotion | Outside #70 collection | Independent promotion and commercial gates | Not covered by owner risk acceptance | PLAY/promotion remain blocked |

For F13, the unchanged default effective sample floor is 3 with a 180-day
half-life; three earlier matches have total recency weight below 3. Four matches
within 60 days can exceed it before regime discounts, but this is an input
feasibility example, not a statistical validation or new threshold. Check actual
retained weights/support. A small suitable corpus need not span seven leagues.
The [dataset investigation](minimal-model-dataset-evidence-2026-10-10.md) retains
why reviewed old licensed releases cannot replace recent inputs without changing
the numerical contract. No licence is asserted to have changed.

## Reuse and exact technical gaps

- [ingestion.py](../../src/matchvet/ingestion.py): reuse parsers, TeamMapper,
  `import_dataset`, append-only source assertions/revisions and bounded capture
  retention. `_acquire_scheduled_fixtures` supplies no F01 coverage/freshness
  proof. Add real source-contract evidence, not an automated LF02 attestation.
- [fixture_coverage.py](../../src/matchvet/fixture_coverage.py): preserve matched
  captured attempt/digest, exact competition/season, coverage bounds/partitions,
  exhaustion, current freshness and affirmative-empty requirements. Its internal
  `permitted_for_use` may reference the risk policy without claiming publisher
  permission. Do not change the COMPLETE bar or frozen membership rules.
- `ResumableSourceDownloader` already limits time, bytes, cache and initial/final
  URLs. Redirects require validation before following, not after contact;
  explicit pacing, provider-limit/Retry-After handling and bounded retries are
  missing. Refusal is terminal for that source, never an evasion opportunity.
- [provider_health_acquisition.py](../../src/matchvet/provider_health_acquisition.py)
  maps old registry labels into policy-based `UsePermissionState` values. Preserve
  that released meaning; add an explicit internal risk-policy eligibility record
  and separately retain actual external grant/restriction evidence. Do not
  relabel external UNKNOWN as licensed permission. Existing OpenFootball reusable/redistributable defaults cannot apply
  to new risk-based captures; use private/protected retention instead.
- [f13.py](../../src/matchvet/f13.py) and
  [f16.py](../../src/matchvet/f16.py): connect selected retained
  FT source assertions to `retain_history` / `build_from_retained_history`.
  T09's existing history construction is not this F16 path. Audit every selected
  history/calibration dependency; exclude accidental legacy Store contamination.
  A Date/Time column without a proven timezone is not exact UTC.
- [research_capture.py](../../src/matchvet/research_capture.py): V1 exact fields
  exclude risk policy and manifest. Preserve its readers and add a V2 decision.
  Reuse F19 attachment and the existing settlement hierarchy COMPETITION →
  FEDERATION → CLUB → FOOTBALL_DATA; never label aggregate data official or
  silently add OpenFootball as a V1 settlement authority.

## Minimum retained authorization contract

Keep the proposed `research-real-source-use-decision-v2` with an explicit
immutable `research-source-use-manifest-v1`. Selection digest binds graph
identity, but cannot bind source-use facts absent from that graph. Do not alter
V1 meanings or introduce a migration without a demonstrated gap.

The manifest binds exact selection/graph, freeze, profile and all relevant
source/capture/citation/attestation/history/calibration dependencies; source type
and access mode; provider/publisher identity and known/unknown upstream lineage;
exact endpoint, raw/normalized artifact digests, parser version, provenance times;
competition/season/capability and operation scope; policy/terms identities,
review/effective dates or UNKNOWN; internal risk basis, separate external
permission state and exact refusal/UNKNOWN reasons; raw versus normalized
retention, private backup/replay and derived use; attribution and distribution
restrictions; manual-policy identities when manual evidence is actually selected.

The decision binds manifest digest, exact risk-policy revision/digest, graph
identities, trusted decision authority, immutable decision identity, validity and
withdrawal/supersession evidence. Missing internal authority, policy or exact
dependency evidence refuses; missing external permission is recorded UNKNOWN
and may be covered by current owner risk acceptance. Missing lineage remains
visible and never becomes independent corroboration. Known terms cannot be
concealed behind a wrapper's licence. Uncertain facts cannot satisfy evidence
gates merely because source use is accepted.

Authorize exact permitted operations before acquisition; retain exact graph
authorization before #86 CB01 continuation. Recheck current authority at dispatch
and protected admission; restore must not revive withdrawn capability. Keep
causal owner activation independent. Later F19 acquisition/attachment binds its
own outcome sources to the original selected case without rewriting its manifest.
Changed terms/access conditions require new review/classification; owner
withdrawal stops new work. Historical inspection remains immutable, while present
use can refuse after adverse evidence. Replay performs no network acquisition.

## Optional automated classes

Weather: reuse the existing Open-Meteo seam after exact venue coordinates,
pre-cutoff forecast times and technical limits are supported. Injuries,
suspensions, manager/team news, referee appointments and expected lineups:
candidate ordinary official league/club/federation publications, with exact
lineage and pre-cutoff freshness. Do not substitute confirmed post-cutoff lineups
for expected ones. Workload derives from known retained fixture history only;
unknown schedule coverage remains a gap. Corners/statistics may reuse selected
CSV or other documented public feeds, but do not infer supported preference
families from missing fields. These are risk-eligible classes, not operational
source approvals. They may initially remain UNKNOWN/UNPERFORMED. No optional
adapter ticket is needed to retain the minimum diagnostic graph.

## Delivery and unresolved gates

Track policy/manifest mechanics in [#89](https://github.com/Awisalas/match-vet/issues/89),
public transport in [#90](https://github.com/Awisalas/match-vet/issues/90),
source-contract qualification in [#91](https://github.com/Awisalas/match-vet/issues/91),
the first Pro League schedule slice in [#92](https://github.com/Awisalas/match-vet/issues/92),
FT-to-F13 projection in [#93](https://github.com/Awisalas/match-vet/issues/93),
and FT-to-F19 projection in [#94](https://github.com/Awisalas/match-vet/issues/94).
#89/#90/#93/#94 are OPEN ready-for-agent; #91/#92 OPEN needs-info. Qualification must
resolve actual source identities, endpoints, lineage, timezone, partition and
revision/currentness semantics; the schedule slice is not implementation-ready
until these are proven. This carries #88's independent technical requirements into #91;
#88 is CLOSED NOT_PLANNED, superseded by the owner decision, without successful
permission requests. Publisher outreach is no longer the RESEARCH_ONLY blocker.

#70 remains OPEN with needs-info, #86/#87 CLOSED. Default live collection stays
off. After technical completion, real causal owner/configuration/checkpoint,
signed current approval and event-valid exact metadata admission, independently
trusted runtime source authorization and a separately authorized prospective
run are still required. No qualified prospective #70 cohort exists, and no
F17/F18/F20, fitting, PLAY or promotion is authorized.

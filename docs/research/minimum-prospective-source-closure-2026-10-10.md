# Minimum prospective #70 source closure, 2026-10-10

## Current decision: automated architecture replaces the manual-first proposal

[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md) accepts
source-use risk for private RESEARCH_ONLY public acquisition and required
retention/replay. Read the [current automated closure](automated-prospective-source-closure-2026-10-10.md).
Publisher permission is no longer a prerequisite in that policy scope; UNKNOWN
permission remains UNKNOWN. LF02/LF05 remain historical/emergency paths, not
the intended primary prospective architecture. Actual all-seven automatic
completeness and source capability still require proof. No live run is authorized.

## Historical permission-first minimum closure (superseded)

The earlier verdict B, manual-source strategy and permission requests below are
retained historical planning, not current implementation/readiness conditions.
No grant was obtained by supersession. Unchanged model, cutoff and evidence
requirements remain applicable.

Decision: **B — a zero-cost closure appears possible, but is not rights-cleared
or operationally demonstrated.** Create no source-authorization implementation
issue. This refinement of the [source-use decision](prospective-source-use-decision-2026-10-10.md)
examines one nonempty prospective RESEARCH_ONLY graph against repository commit
`4146b5a89f9e8ceebc965185ba43e0b5b1671d1b`. It grants no permission or activation.
The [primary permission inventory](real-source-permission-evidence-2026-10-10.md)
remains applicable to sources actually used; it is not a list of sources that
every graph must acquire. The [dataset review](minimal-model-dataset-evidence-2026-10-10.md)
records current primary licences and candidate limitations.

## Minimum graph under unchanged contracts

F06 needs an eligible, fully reconciled **seven-scope** Matchweek, including
evidence for genuinely empty scopes and at least one included real fixture.
F07 binds its controlling revisions and common cutoff T. F11, F13, F14 and F16
must finish before T; the sole causal completion must establish the required
interval before T. The separate #86 CB01 continuation is after T and before
each applicable kickoff. Later results cannot repair this pre-T graph.
See [chronology](../product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md),
[methodology](../product-v2/CANDIDATE-INPUT-METHODOLOGY-0.2.0.md),
[F06](../../src/matchvet/matchweek_membership_repository.py), [F07](../../src/matchvet/match_evidence_cutoff.py), and
[selected replay](../../src/matchvet/causal_selection.py).

The smallest practical football input set is:

1. Exact schedule/identity/status/kickoff facts and official completeness
   publications for all seven scopes, plus the unchanged LF02 attestation
   and actual automatic acquisition base.
2. One small, recent, source-backed full-time goal history snapshot, authored
   by the operator from rights-cleared publications. Its underlying publisher
   can be one already needed for schedules. A separate commercial provider,
   event dataset or all-seven-league history is not mandatory.
3. MatchVet-authored policy/profile, attestations, provenance, evidence and
   derivations. Missing context and unsupported model families remain explicit.

There is an important existing adapter constraint. [LF05 and its V2 policy](../../src/matchvet/operator_fixture_observation.py)
accept Belgium and England/Germany/France/Italy respectively, for 2026–27.
They do **not** accept Spain or Portugal. [LF02](../../src/matchvet/operator_fixture_attestation.py)
requires an explicit automatic F01 V2 base with real Provider Attempt timestamps;
`_latest_attempt_retrieval()` refuses an all-manual base with no attempts.
Human consultation cannot supply Provider Health or synthetic attempts.

The [scheduled-only acquisition path](../../src/matchvet/ingestion.py),
`acquire_scheduled_fixtures()`, avoids Football-Data historical ingestion and
allows a reduced `IngestionPlan.leagues`. For an ordinary week with Spanish
and Portuguese fixtures, the smallest current-adapter proposal is those two
leagues' OpenFootball JSON **and** Football.TXT feeds, plus manual observations
for the other five leagues and official LF02 checks for all seven. The adapter
requests both formats per configured league: four real attempts, not four
independent sources. Raw successful responses must be retained. No feed was
requested here and none is authorized. Clear their actual upstreams first;
repository CC0 alone is insufficient. A hypothetical week with verified empty
Spanish/Portuguese scopes could reduce this further, but no such future window
or permitted automatic base was established. Empty or invented fixtures are
not a workaround. Replacing these feeds or extending the manual policy is
future design/implementation, not a currently supported cleared path.

Canonical identities must already resolve unambiguously. Inspect the exact
selected mapping/alias provenance, including applicable shipped registries and
OpenFootball club candidates; do not inherit ambiguous Football-Data or
OpenFootball rights through an old Store. [F11](../../src/matchvet/f11.py) loads
season fixture history as well as current memberships. Existing mixed Stores
can therefore enlarge the closure. A future bounded collection must audit its
actual dependency inventory; an intended small source set cannot excuse other
retained inputs that enter the graph.

## Dependency table

“Conditional” is not operational approval; missing permission remains UNKNOWN.
The table separates collection of diagnostic cases from passing recommendation
gates. Every enabled preference still gets its denominator row.

| Dependency | Owning stage | Mandatory/optional | Current source | Permission status | Minimal candidate | Exact required rights | Effect if unavailable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Seven-scope schedule completeness, including empty scopes | F01/F06, LF02 | Mandatory | Automatic base plus official publications and operator attestations | Self-authored attestation permitted internally; publications UNKNOWN | Same seven official publication checks; no new provider | Human consultation, minimal facts/citations, normalized retention, private backup/replay | No eligible freeze; stop |
| Exact identities, kickoff, status and controlling fixture revisions | F02/F06/F07, LF05 | Mandatory for included fixtures | OpenFootball; manual five-league policies; canonical mappings | Whole selected lineage UNKNOWN | Manual five leagues; current Spanish/Portuguese feeds only if cleared | Manual fact entry and mappings; authorized automated feed access with exact raw/normalized retention and backup/replay where used | Missing/ambiguous identity or kickoff prevents inclusion/qualification; no fabricated replacement |
| Actual base Provider Attempts and health evidence | LF02/F05/F06 | Mandatory for this bridge | Current JSON/TXT adapter | Repository contribution rights conditional; upstream clearance UNKNOWN | Reduced two-league plan where applicable | Permission before each actual request, metadata retention and any response retention | All-manual bridge cannot certify; no invented attempt |
| Completed full-time goals with exact UTC kickoff and provenance | F13/T09/T11 | Mandatory for usable numerical full-time raw predictions; empty history can only retain unavailable diagnostics | Current Football-Data/OpenFootball lineage | Current exact operations UNKNOWN | Small recent manually recorded official results; same publisher grants | Lawful consultation, normalized goals/identity/time facts, protected authored snapshot, private backup/replay, internal derived statistical inputs | T11 may be MODEL_UNAVAILABLE; no claim that usable raw predictions were produced |
| Half-time goals | F13/T12; later F19 | Preference/family dependent | Same history sources | UNKNOWN if selected | Omit; optionally add under same official grant | Additional phase score facts and their retained provenance | Phase-dependent families/outcomes unavailable; retain rows |
| Corners and other auxiliary statistics | F13/T13; later F19 | Preference/family dependent | Football-Data/specialist inputs | UNKNOWN if selected | Omit | Exact applicable statistics, source hierarchy, fact retention and replay | Corner predictions/settlements unsupported; no zero defaults |
| Weather and venue coordinates | F11/F12/T08 | Optional for diagnostic collection; applicable gate support may require them | Open-Meteo plus venue sources | Conditional access/data licence; venue rights source-specific | No weather request, no external coordinate source | None when omitted; full access/attribution/raw retention rights if added | Weather UNPERFORMED/UNKNOWN; affected gates reject |
| Injuries, lineups, managers/regimes, disciplinary/referee context, additional cup/workload fixtures | F11/T09 | Optional for diagnostic collection; preference/gate dependent for support | T07 official/manual sources and contextual feeds | Source-specific UNKNOWN | No external acquisition; derive only what selected fixture facts actually establish | None for omitted inputs; consultation/citation or raw capture rights if used | Missing research remains UNPERFORMED/UNKNOWN, never ABSENT; do not infer complete workload |
| Prior forecasts/outcomes for calibration, challenger validation, baselines and numerical support | F13/T14; F14/T15 | Optional for initial raw diagnostic corpus; mandatory for applicable calibrated/support gates | No qualified prospective corpus | Not presently available | Empty calibration inputs and unresolved support | No external acquisition for an empty input; future source-backed cases need their own exact rights | Calibration/support UNKNOWN or unavailable; rejection, no Primary |
| Profile, diagnostic policy, review/support records and complete preference denominator | F14/F16 | Mandatory internal graph dependencies | MatchVet-authored protected artifacts | Internal authorship; underlying inputs still conditional | Existing RESEARCH_ONLY contracts, no fabricated evidence | Retain exact authored bytes plus permitted upstream derivations | Incomplete structural graph refuses; unresolved quantitative support rejects |
| Independent owner state, admitted TUF closure, causal completion and receipt | Causal selection/#87, #86 | Mandatory qualification; separate from football permissions | Existing Sigstore profile/mechanics | Mechanics complete; production authority/approval/metadata NOT OPERATIONAL | Existing ADR 0005 profile, independently provisioned later | Separate accepted authority/premises and service use; no football permission supplied | Default refuses; no qualified selection or live continuation |
| Source-backed final status and regulation-time goals | F19/T10, after kickoff | Mandatory for goal outcome research, not pre-T selection | Competition/federation/club evidence before Football-Data in T10 hierarchy | Actual publisher permission UNKNOWN | Manual competition result facts under same bounded grant | Human consultation, normalized evidence/citations, private backup/replay and later internal analysis | UNKNOWN/unresolved settlement remains visible; no empirical evaluation for missing outcomes |
| Commercial reuse, redistribution, product recommendation validation | Product Promotion/T20 | Not needed for #70 diagnostic collection | No approved operational source set | Unapproved; no inference from research | Exclude these operations | Separate permission and validation if ever proposed | Promotion/PLAY stays blocked |

## Why F11 does not force every contextual source

F11 accepts no weather client, no extra context fixtures and no venue inputs.
Its replay verifies exactly the captures/provenance that exist. T09 marks absent
mandatory-research attempts UNPERFORMED and affected support UNKNOWN. That
blocks recommendation gates, but [F14](../../src/matchvet/f14.py) and
[F16](../../src/matchvet/f16.py) can retain complete RESEARCH_ONLY rejections.
They do not require a survivor or supported Primary Recommendation. This is
not permission to make a weather/injury absence assertion or silently omit
required denominator rows. Shared schedule/history lineage stays visible in
the resulting evidence and derived workload/form records.

## F13's actual minimum, and open dataset alternatives

[F13.retain_history()](../../src/matchvet/f13.py) retains a canonical structured
snapshot without requiring a particular provider adapter. `HistoricalMatch`
requires identified real teams/fixtures and exact UTC kickoff; F13 additionally
requires observed-before-cutoff source/assertion provenance. The authored
snapshot is not a licence for its underlying facts. Official pages, PDFs and
screenshots need not be archived for this manual proposal. Retain only the
canonical facts, citations/provenance and their protected authored bytes.

The unchanged [T11](../../src/matchvet/t11.py) defaults require three eligible
rows, an effective recency/regime weight sum of at least three, and the existing
shared-history conditions. Three strictly earlier rows have total recency
weight below three. At least four sufficiently recent distinct real matches
are needed without discounts; four within 60 days have weight sum at least
`4 * 2 ** (-60 / 180) = 3.1748` before any regime discount. This is a necessary
input sufficiency example, not a new research sample floor, proof of numerical
convergence, validation, or permission. The actual selected history must pass
the unchanged fit checks. T11 permits pooled shared history for unseen teams;
seven separate league histories are not structurally required. Do not claim
that pooled outputs establish target-specific research sufficiency or calibrate
them without compatible prior forecast/outcome cases.

The [dataset review](minimal-model-dataset-evidence-2026-10-10.md) found explicit
CC BY grants for the Pappalardo/Wyscout release and an official DFL release,
but neither meets the unchanged 2026 effective-history floor alone. Recent
StatsBomb/Hudl and Impect research agreements leave relevant retained operations
unresolved; other candidates lack proven chronology, scope or rights. No
currently verified replacement establishes both legal and operational closure.
This is evidence of unresolved feasibility, not proof that zero-cost research
is impossible. Prefer the same publishers' small recent result corpus; seek
one additional corpus grant only if that route fails. Football-Data is not a
mandatory dependency and no threshold/profile change is proposed.

## Narrow permission requests and exact remaining grantors

Send nothing automatically. The human should name the actual operator, one
future Matchweek/window, relevant 2026–27 competitions, and a bounded recent
history interval. The official-publication grantors are Football Association
Premier League Ltd, Bundesliga-Gruppe GmbH (or the actual pinned publication
rightsholder), LFP, Lega Calcio Serie A, LALIGA Group International S.L., Liga
Portuguesa de Futebol Profissional, and Pro League. A publisher-specific
competent documented legal basis can replace written permission only if it
resolves these exact operations. No such basis has been retained.

Use this request separately for each of the seven official publishers; request
history only from one chosen publisher and later outcomes only where needed:

> May [named operator] manually consult [exact official publications] to verify
> one seven-league prospective Matchweek's completeness, enter minimal team and
> fixture identities, status and exact UTC kickoff, and keep the publication
> URL, displayed update time and our observation time? For [bounded history
> interval / selected later results, where applicable], may we also record
> completed regulation-time home/away goals and final status? Please confirm
> zero-cost private RESEARCH_ONLY fact/citation retention, protected normalized
> snapshots, private backup/restore/offline replay and derived statistical-model
> inputs. We request no automated website access, page/PDF/screenshot/video
> archive, redistribution or commercial/product use. Please identify your
> authority over these facts/publications, attribution and exact scope/duration,
> and effects of withdrawal on new collection and previously retained facts.

For the **existing Spanish/Portuguese feed and selected alias lineage**, ask
OpenFootball's responsible maintainers separately:

> For [exact repository/file revisions] used for Spanish/Portuguese 2026–27
> JSON and Football.TXT schedules, and [exact selected club/alias entries], what
> are the actual upstream publishers and source revisions? Please provide the
> grants or applicable basis covering automated retrieval of these exact files,
> private raw/normalized retention, backup/restore/replay and statistical
> derivations at zero cost, including every upstream right. Can the responsible
> grantor confirm those operations and required attribution/duration? We will
> not infer upstream permission from CC0 or treat JSON/TXT as independent.

Once identified, request those same narrowly specified downstream operations
from each actual upstream rightsholder. The list cannot be invented now or
replaced with the league website's unrelated access permission. If the answer
does not clear it, the current-adapter path remains UNKNOWN; do not acquire it.
The [dataset note](minimal-model-dataset-evidence-2026-10-10.md) supplies one
optional Football Charts request if an additional recent history source is
needed. That provider is not part of the mandatory set or a configured adapter.

Current primary [Premier League terms](https://www.premierleague.com/en/terms-and-conditions)
reserve database reuse and application deep links absent approval;
[LALIGA website terms](https://www.laliga.com/en-GB/legal/legal-web), §6,
restrict copying/adaptation without permission or an applicable legal basis.
[OpenFootball CC0](https://github.com/openfootball/football.json/blob/master/LICENSE.md),
§4(c), does not clear third-party rights. These were rechecked on 2026-10-10.
The other grantors' findings and primary links are in the
[same-day permission review](real-source-permission-evidence-2026-10-10.md);
the Liga Portugal full-page retry again timed out, so no affirmative clearance
is inferred. Public accessibility and a research label do not answer the requests.

## Outcomes, timing and present decision

F19 accepts typed source-backed [T10 settlement evidence](../../src/matchvet/t10.py),
not operator-assigned grades. Minimal official final status, regulation-completed
state and home/away goals support applicable full-time goal settlements.
Halves/corners need their own observed fields if those outcomes are to be used;
missing values retain UNKNOWN and cannot become a complete evaluation case.
F19 corrections preserve predecessors and exact F16/F14/selection identities.
This later outcome source needs permission before consultation/retention, but
does not belong to, or rewrite, the pre-T prediction graph.

Obtain each access/retention permission **before acquisition**. Before #86
continuation, a separately controlled successor decision must authorize the
exact selected graph and immutable source-use manifest. The V1 selection digest
alone remains insufficient to retain missing rights evidence. Authenticate
withdrawals/supersessions without rewriting historical cases; changed or
uncertain rights prevent new use, and replay/copying retained bytes needs a
surviving lawful basis. No retroactive permission or Product Promotion inference.

No source is newly operationally approved. No implementation issue is created.
#70 remains OPEN with `needs-info`; #86/#87 remain CLOSED. Default production
refuses. Owner provisioning, independent checkpoint continuity, current signed
approval and event-valid admitted metadata remain separate operational blockers.
No qualified prospective #70 cohort exists. Only documentation/static checks
are appropriate for this decision; no live acquisition, adapters, authorization,
model execution, fitting, PLAY or promotion was performed.

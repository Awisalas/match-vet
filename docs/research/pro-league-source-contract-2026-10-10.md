# Pro League automated source-contract qualification

Research date: 2026-10-10. Issue: [#91](https://github.com/Awisalas/match-vet/issues/91).
Implementation target: [#92](https://github.com/Awisalas/match-vet/issues/92).

## Current Belgium verdict

The [bounded raw-calendar follow-up](pro-league-calendar-raw-qualification-2026-10-10.md)
proves **B: TECHNICALLY INSUFFICIENT for the exact default-matchday response**.
Embedded JSON supplies UTC times and structured fixture/team UUIDs, but only
matchday 8 has fixture membership. The response does not supply the complete
current-window/replacement protocol required by #92. #91 closes under criterion B
with the replacement decision retained there; #92 remains OPEN `needs-info`.
The initial review and seven-league table below retain their original dated
findings. No other league was researched in the follow-up.

## Initial review verdict

**PARTIAL: #92 is not implementation-ready.** The preferred official candidate
is the [Pro League JPL calendar](https://www.proleague.be/jpl-kalender!). Public
publication of fixtures is supported, but the inspected representation does not
establish an automated exact kickoff, exhaustive requested-window, currentness
or stable identity contract. No documented official public API/feed was found
in this bounded review. That finding is not a claim that none exists.

The specific observed blocker is the gap between a public calendar view and
the unchanged F01 contract. An adapter specification cannot assert the missing
facts. This review does not establish a hard technical refusal of the candidate
or prove that the underlying HTML/JavaScript lacks those fields. It therefore
does not meet close criterion A, or by itself prove criterion B.

The smallest next decision is to qualify one supported public, structured
Pro League schedule representation containing exact times, full-window
enumeration, status/revision behavior and currentness, or select a separately
qualified replacement official publication contract. Do not promote the
calendar view to completeness evidence, assume an undocumented backend is public,
or substitute an aggregator while an official contract remains unexamined.

## Reviewed boundaries

This note follows [ADR 0006](../adr/0006-research-only-public-source-automation-risk.md),
the [automated closure assessment](automated-prospective-source-closure-2026-10-10.md),
[current source authorization](../design/research-source-authorization.md),
and [bounded transport](../../src/matchvet/ingestion.py). Research inspections
are not operational captures or #89 source authority.

[F01](../../src/matchvet/fixture_coverage.py) requires source-backed exact
competition/season/bounds, accounted required partitions, exhaustion,
freshness and separate affirmative-empty evidence. F02 acquisition and
[F03 persistence](../../src/matchvet/fixture_coverage_repository.py) retain exact
attempts, captures, assertions and revisions. [F04](../../src/matchvet/provider_health.py)
and [F05](../../src/matchvet/provider_health_repository.py) preserve exact
provider-health evidence. [F06](../../src/matchvet/matchweek_membership_repository.py)
requires all seven scopes and resolved identities. A new source contract must
supply evidence for those existing checks; transport success supplies none of
the missing publication semantics.

## Exact candidate and known publication facts

The [privacy policy](https://www.proleague.be/privacy-policy) identifies the
operator as Pro League NV, Belgian enterprise number 0508.600.494. The policy
states a last modification date of 2020-01-29; that is the policy's date, not
a fixture publication or update timestamp. Its footer reserves rights.
External fixture-data permission remains UNKNOWN; privacy terms do not grant
an automated schedule-data licence. ADR 0006 supplies an internal risk basis,
subject to separately supplied current authorization for later operational use.

| Field | Evidence / qualification |
| --- | --- |
| Exact primary URL | `https://www.proleague.be/jpl-kalender!`; public HTML calendar candidate. |
| Publication family | Competition calendar, official scheduling announcements, team fixture/results pages, individual match pages. Only exact inspected locators below are evidenced. |
| Competition / season | The [2026/27 announcement](https://www.proleague.be/nieuws/kalender-2026-2027-club-brugge-opent-tegen-kv-kortrijk-eerste-super-sunday-al-op-speeldag-4) establishes 18 clubs, 34 rounds and no play-offs. Team view exposes `Saison 2026/2027`; no machine competition/season IDs qualified. |
| Representation | Web extraction shows a selected `Speeldag 8`, nine pairings and display names. Raw HTML/schema, stable selectors, structured timestamp fields and feed version remain UNKNOWN. |
| Access | The web tool returned public HTTPS content without a supplied account/key. Exact origin status, full redirects, request count, headers and bytes are not exposed by that tool; ordinary direct machine reachability remains unproven. |
| Window / partitions | No exact date filter, requested half-open UTC bounds or authoritative enumeration protocol qualified. A selected round is not an exhaustive date window because fixtures can move between rounds' nominal dates. |
| Pagination / exhaustion | UNKNOWN. No documented terminal page/partition enumeration or exhaustive response assertion found. Missing pagination controls in extracted text does not prove exhaustion. |
| Completeness | UNPROVEN. The season format and returned matchday rows cannot establish all fixtures in a requested F01 window. |
| Affirmative empty | UNPROVEN. No complete-window negative declaration qualified. An empty extraction remains incomplete/UNKNOWN. |
| Kickoff / timezone | Calendar extraction does not expose kickoff instants. Official news displays local-looking clock times but no explicit timezone/offset contract was identified. UTC conversion basis remains UNKNOWN; do not assert `Europe/Brussels` merely from geography. |
| Status | A [completed match page](https://www.proleague.be/wedstrijden/seizoen-2026-2027-jupiler-pro-league-8-sk-beveren-vs-lommel-sk-659) exposes `Voltooid`, score 1-3 and final commentary. Full machine status vocabulary, cancellation/abandonment handling and regulation-versus-extra-time rules remain UNKNOWN. |
| Revision behavior | Official announcements prove that postponements and rescheduling exist. No revision ID, replacement linkage, deletion behavior or update protocol qualified. |
| Freshness | UNKNOWN for the complete current schedule. A news publication date is not a calendar snapshot/as-of time. Retrieval time is not publication/update time. |
| Upstream | A [first-party partnership announcement](https://www.proleague.be/nieuws/pro-league-and-stats-perform-expand-partnership) identifies Stats Perform/Opta data and website use historically. Exact present calendar endpoint ancestry is UNKNOWN; do not infer independent corroboration. |
| Terms / risk review | Operator privacy policy and copyright reservation observed on 2026-10-10. Fixture-specific current terms, revision identity and effective date remain UNKNOWN. ADR 0006 permits private risk-accepted specification; it grants no publisher permission or current #89 authority. |
| Technical limits | No provider rate policy qualified. No explicit CAPTCHA/WAF/auth refusal was visible in the web representations. This is not proof such controls are absent. No retries or refusal evasion occurred. |

The [September scheduling notice](https://www.proleague.be/nieuws/kalenders-van-fans-liggen-vast-tot-na-de-winterstop)
says exact timings are fixed through the winter break and the next update is
due 8 December. It also retains a possible postponement of KAA Gent versus STVV on
13 December and discusses rescheduled round-3 matches. A separate
[Gent–OH Leuven notice](https://www.proleague.be/nieuws/kaa-gent-stoot-door-in-conference-league-duel-tegen-oh-leuven-verplaatst)
and [Charleroi–OHL notice](https://www.proleague.be/nieuws/sporting-charleroi-ohl-verplaatst-door-bezoek-van-italiaanse-premier)
provide examples of fixture-specific changes. These prove the need to cover
revisions; they do not document a complete revision stream or freshness SLA.

The match-detail heading reverses the teams relative to its URL/result block.
An eventual parser must prove home/away field semantics from structured
representation and reject disagreement. Page title or slug order alone is
insufficient. A completed score by itself does not qualify exact historical
kickoff UTC or all F19 final-result rules.

## Identity mapping

The existing registry is
[`matchvet-pro-league-team-alias-registry-v1`](../../src/matchvet/pro_league_team_alias_registry_v1.json),
digest `sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`,
introduced in commit `4396fcd5532c57a334c986b96c7975ee42cd6ace`.
Its [validator](../../src/matchvet/pro_league_team_alias_registry.py) requires
`OPERATOR_OFFICIAL_FIXTURE_OBSERVATION`, Belgium, season `2026-27`, and the exact
official calendar locator. It is LF05 manual-source authority. It cannot be
relabelled as an automatic-source mapping revision.

The [LF09 retained identity audit](live-blocker-source-research-2026-09-29.md)
records 18 unique canonical teams and 18 resolved manual names after correction.
The candidate automatic source has no qualified stable team-ID namespace or
mapping digest. The following table records canonical targets for future
review, not approved automatic mappings. All calendar names below were visible
in the inspected matchday representation. The first 15 IDs are exact registry
targets; the final three are the existing deterministic canonical-name identity
calculation, not a new production Store observation.

| Exact display name | Existing canonical name | Canonical team ID |
| --- | --- | --- |
| KAA Gent | Gent | `90800c95-58b1-5a21-b919-89fed6318928` |
| KRC Genk | Genk | `ce9f9bd1-03f9-57d3-97b7-7ea31fb6a559` |
| KV Kortrijk | Kortrijk | `bfb32b05-59e6-5648-9b33-7e40ff47bcf8` |
| KV Mechelen | Mechelen | `4d518065-f23c-539a-8050-51a2f6f4ce1f` |
| KVC Westerlo | Westerlo | `9610662f-38c0-5a35-b767-b7d655006148` |
| OH Leuven | Oud-Heverlee Leuven | `4111d7bc-c7e7-5457-971d-092faa24f251` |
| RAAL La Louvière | RAAL La Louviere | `4331bd48-bc75-587d-86f7-f3dae1d26f42` |
| Royal Antwerp FC | Antwerp | `f12e95f1-a648-558e-9876-49ad8ccd2041` |
| Royale Union Saint-Gilloise | St. Gilloise | `84cfc556-c7c7-5dc8-b9a4-cd878ad85a13` |
| RSC Anderlecht | Anderlecht | `43ff030c-9cfd-5071-abfa-f335c1eda2d8` |
| SK Beveren | Beveren | `7eff0929-689e-5023-8fe9-b389e2395dac` |
| Sporting Charleroi | Charleroi | `7503e693-b803-570c-aaa0-67ab4adf0574` |
| Standard de Liège | Standard | `ebfcd84f-fa42-5b5a-98cb-5eac04c76ed2` |
| STVV | St Truiden | `cd8a896e-ba62-5aec-b3fc-1325a28f9fd4` |
| SV Zulte Waregem | Waregem | `0a3eb518-174e-585e-834a-c138cc94d374` |
| Cercle Brugge | Cercle Brugge | `828d351b-d6be-5b2b-91e1-ee11c0d9fda7` |
| Club Brugge | Club Brugge | `477ff95e-ea76-5023-bce8-81c5978d37b1` |
| Lommel SK | Lommel SK | `a80c45ca-228d-535a-945a-92b7ead01f13` |

`https://www.proleague.be/teams/sk-beveren-19` and
`https://www.proleague.be/fr/equipes/rsc-anderlecht-1/fixtures-results` are exact
observed team locators. Suffixes `19` and `1` are not qualified source IDs; their
scope, stability and uniqueness are UNKNOWN. The old OpenFootball club history
has conflicting historical Lommel/Beveren aliases, as retained in LF09 research;
it cannot establish this automatic identity contract. The next mapping must
bind exact source namespace, competition/season, upstream origin, revision and
digest to these existing canonical targets. Ambiguity or a missing canonical
target remains UNKNOWN; no automatic team registration or fuzzy fallback.

## Bounded inspection ledger and evidence limitations

Public web search/open/click inspected only the listed publication families on
2026-10-10, with no supplied credentials, page JavaScript execution, private
backend calls, season crawl, bulk archive or production Store. Search queries
were limited to official-domain schedule/feed/API/terms/upstream discovery.
Search results are cached discovery evidence. Web `open` returned extracted
content and crawler labels, not a #90 response/capture envelope. Crawler dates
are not authoritative fixture update times. The tool does not expose a
verifiable provider request/byte budget, redirects, response digest or precise
retrieval instant; these remain UNKNOWN.

| Inspected public locator | Retained minimum observation |
| --- | --- |
| [Calendar](https://www.proleague.be/jpl-kalender!) | Selected matchday 8 and names; exact kickoff/coverage contract unproven. Tool reported an encoded `!` locator as well; no complete origin redirect chain exposed. |
| [Homepage](https://www.proleague.be/) and [JPL homepage](https://www.proleague.be/jpl) | Official navigation to selected match and scheduling notices; not a scope catalogue. |
| [Privacy](https://www.proleague.be/privacy-policy) | Operator identity, privacy-policy date and rights reservation. |
| [Season announcement](https://www.proleague.be/nieuws/kalender-2026-2027-club-brugge-opent-tegen-kv-kortrijk-eerste-super-sunday-al-op-speeldag-4) | Competition format, staged exact scheduling and potential revisions. |
| [September update](https://www.proleague.be/nieuws/kalenders-van-fans-liggen-vast-tot-na-de-winterstop) | Fixed scheduling horizon plus a conditional postponement. |
| [Gent revision](https://www.proleague.be/nieuws/kaa-gent-stoot-door-in-conference-league-duel-tegen-oh-leuven-verplaatst) and [Charleroi revision](https://www.proleague.be/nieuws/sporting-charleroi-ohl-verplaatst-door-bezoek-van-italiaanse-premier) | Revision publication examples, without exhaustive stream semantics. |
| [Completed match](https://www.proleague.be/wedstrijden/seizoen-2026-2027-jupiler-pro-league-8-sk-beveren-vs-lommel-sk-659) | Completion word, score, home/away ambiguity in heading. |
| [Beveren team](https://www.proleague.be/teams/sk-beveren-19) and [Anderlecht fixtures](https://www.proleague.be/fr/equipes/rsc-anderlecht-1/fixtures-results) | Display identity and season control; no qualified stable ID/time fields. |
| [Data partnership](https://www.proleague.be/nieuws/pro-league-and-stats-perform-expand-partnership) | Historical Stats Perform/Opta relationship; current endpoint lineage unresolved. |

One separate direct calendar inspection was attempted using #90's existing
public-IP validation and pinned verified HTTPS transport, an exact calendar
URL check, one request, maximum 1 MiB, ten-second request/elapsed budget, zero
redirects and zero retries. It used no downloader, authority, Store or provider
activation. The scratch-ledger write failed because `/tmp` was not writable
in this Termux environment. The process exited without retaining its in-memory
response ledger. Response status, precise UTC retrieval time, byte count,
digest and reachability outcome are therefore UNKNOWN. The request was not
repeated. No raw page body or backend/schema claim is admitted from that attempt.

Only these minimal facts and local mapping references are retained. There is
no deterministic parser fixture sufficient to authorize adapter work yet.
Any later live research inspection needs its own bounded, observable evidence
plan; any operational fetch still needs current #89 authorization and #90.

## Seven-league capability table

This is a dated qualification table, not a Provider Health assessment. PARTIAL
means that some first-party publication capability is evidenced. It does not
mean F01 PARTIAL or COMPLETE, and it grants no source authority. UNKNOWN marks
an unproven contract fact. No candidate is QUALIFIED. No technical access refusal
was established in the representations below; terms restrictions are recorded
separately from technical refusal.

Public HTTPS below describes documentation or extracted public pages without
supplied credentials. Origin response envelopes, automatic feed access and
current per-provider rate limits remain unqualified. Existing mappings for
OpenFootball, Football-Data or manual citations are not mappings for these
official automatic source namespaces.

| League / official candidate | Access type | Schedule | Revision / status | Timezone | Completeness proof | Identity mapping | State | Exact next gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Premier League: [380-match release](https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season), [updating ECAL calendar](https://www.premierleague.com/en/news/1235133) | Public HTTPS HTML; consumer calendar contract unqualified | Season pairings and nominal times published | Calendar promises reschedule updates; machine status vocabulary UNKNOWN | Release says UK time; opening notice says BST. Feed UTC semantics unqualified | UNPROVEN for a current date window | Official source namespace and mapping digest unqualified | PARTIAL | Exact public feed, maintained revision coverage and exhaustion/empty semantics |
| Bundesliga: [Bundesliga-Gruppe GmbH](https://www.bundesliga.com/de/bundesliga/info/impressum), [confirmed MD5-11 publication](https://www.bundesliga.com/en/bundesliga/news/confirmed-kick-off-times-dates-2026-27-fixtures-23955) | Public HTTPS HTML and linked PDFs; terms restrict bots | Timed matchday batches published | Later scheduling batches documented; full status/revision stream UNKNOWN | Explicit CET/CEST labels in sampled notice | UNPROVEN for current arbitrary bounds | Official source mapping unqualified | PARTIAL | Exact publication operator binding, structured scope enumeration and controlling updates |
| Ligue 1: LFP [season publication](https://ligue1.com/fr/articles/l1_article_5284-), [legal publisher](https://ligue1.com/fr/legal/legal-notice) | Public HTTPS HTML and linked calendar PDF | 34-round calendar published | Selected programmed times remain conditional; complete status stream UNKNOWN | Exact source timezone UNKNOWN | UNPROVEN | LFP source IDs and mapping unqualified | PARTIAL | Exact public representation, offset/time semantics and complete current programming coverage |
| Serie A: Lega Calcio Serie A [calendar/results](https://www.legaseriea.it/serie-a/calendario-risultati), [season publication](https://www.legaseriea.it/serie-a/news/calendario-della-serie-a-enilive-2026-27) | Public HTTPS HTML and linked PDF | Season calendar published; extracted interactive view says no data available | Scheduling publications exist; machine status semantics UNKNOWN | Exact source timezone UNKNOWN | UNPROVEN; no-data view is not affirmative empty | Official source mapping unqualified | PARTIAL | Public source-native schema, exact times and complete window/revision protocol |
| LALIGA: [season/round results page](https://www.laliga.com/laliga-easports/resultados/2026-27/jornada-1) | Public HTTPS structured HTML | Sample round has dates, times, teams and scores | [Results page](https://www.laliga.com/es-NG/laliga-easports/resultados) discusses changes, cancellation and suspension; machine vocabulary UNKNOWN | Displayed clock has no qualified offset basis | UNPROVEN; a round is not a date window | Official source namespace and mappings unqualified | PARTIAL | Timezone/localization contract and exhausted current window with all rescheduled fixtures |
| Liga Portugal: Liga Portuguesa de Futebol Profissional [calendar](https://www.ligaportugal.pt/calendar), [2026/27 publication](https://www.ligaportugal.pt/news/28156/os-calendarios-dos-campeonatos-profissionais-202627) | Public HTTPS HTML; download control visible | Season, month, competition and team controls; calendar publication evidenced | Complete current status/revision contract UNKNOWN | Exact source timezone UNKNOWN | UNPROVEN; filters/download controls do not prove exhaustion | Official source IDs and mappings unqualified | PARTIAL | Actual public export schema, bound semantics, current dates/status and timezone |
| Belgian Pro League: Pro League NV [JPL calendar](https://www.proleague.be/jpl-kalender!) | Public HTTPS extracted page; direct access unproven | Selected round rows and season format evidenced | Revision articles and one `Voltooid` result evidenced; full vocabulary UNKNOWN | Exact UTC basis UNKNOWN | UNPROVEN | LF05-only registry retained; automatic contract unqualified | PARTIAL | Public schema, exact UTC, exhaustive current window/empty proof and automatic identity namespace |

The Bundesliga legal publication currently names Bundesliga-Gruppe GmbH.
The [legal terms](https://www.bundesliga.com/de/bundesliga/info/rechtliche-hinweise)
reserve automated access and data-mining rights. This restriction is external
evidence under ADR 0006, not a runtime access-control refusal or an external grant.
The Ligue 1 legal notice identifies LFP, SIREN 784714222, while the footer says
LFP Media. The [CGU](https://ligue1.com/fr/legal/cgu) identify LFP and restrict
reuse. A later endpoint review must retain those exact identities rather than
guess the data operator from a footer or confuse the separate Ligue 1+ service.
Current endpoint-specific upstreams remain UNKNOWN for these six families.
Older rights and discovery findings remain in the
[coverage audit](upcoming-fixture-coverage-source-audit-2026-09-27.md), with its
pre-ADR permission gate treated as historical.

The other-six review used bounded web search and the exact public locators above
on 2026-10-10. No feed, PDF season calendar or result CSV was downloaded.
Primary publication text supports the listed capabilities, not current origin
HTTP metadata. Search-only findings and crawler labels are not source snapshots.
The Premier League release and Bundesliga notices identify timezone labels;
the remaining timezone cells stay UNKNOWN rather than inheriting league geography.

## Football-Data recent-history and outcome fallback

The existing family is `https://www.football-data.co.uk/mmz4281/2627/<code>.csv`,
with configured codes E0, D1, F1, I1, SP1, P1 and B1. Those configured locators
are [repository configuration](../../src/matchvet/ingestion.py), not a new live
CSV qualification. The provider [data documentation](https://football-data.co.uk/data.php)
advertises full-time results in CSVs, twice-weekly updates, a shared list of
results upstreams, and restrictions on commercial or data-training products
using bots, scrapers or AI. It supplies no row-specific upstream identity in
that documentation. The published restriction records external REFUSED for its
stated prohibited-use scope, not for ordinary documentation viewing. Broader
operation grants remain UNKNOWN. ADR 0006 may supply an internal risk basis,
but exact #89 operation classifications and current authorization remain
unprovisioned.

The existing parser recognizes `Date`, `Time`, `HomeTeam`, `AwayTeam`, `FTHG`,
`FTAG` and `FTR`. Its `_kickoff` uses the configured league timezone. That is an
implementation assumption, not publisher evidence about the `Time` field.
UK-time file uploads or odds-collection schedules do not establish match kickoff
timezone. The actual `Time` timezone remains UNKNOWN in this review.

The notes endpoint `https://football-data.co.uk/notes.txt` could not be inspected
exactly. The web tool reported an internal error. One separate direct research
attempt used the existing pinned transport, exact HTTPS host/path, a 128 KiB
byte cap, maximum one HTTP request, zero redirects/retries, a five-second DNS
limit, ten-second socket timeout and a twelve-second total budget. Public DNS
resolution timed out before HTTP dispatch. Actual HTTP request count is zero;
no response bytes, status, retrieval time or content digest exist. No alternate
identity or route was attempted after that failure.

Verdict: PARTIAL for the documented FT-results family, not qualified for exact
F13 kickoff UTC. F19 could classify sufficiently supported FT facts honestly as
FOOTBALL_DATA, subject to proof of final status, canonical fixture join and any
corrections. It cannot classify these aggregate rows as COMPETITION evidence.
There is no qualified acquisition plan that avoids odds at the wire level:
the advertised CSVs combine results with odds, and parser field filtering cannot
undo acquisition. No CSV, odds values or archive was acquired. The next gap is
a proven results-only representation or usable exact retained evidence, plus
publisher-backed timezone and final-status semantics. Official-family FT
results remain the preferred candidate when those same facts can be qualified.

## Issue and dependency disposition

#91 remains OPEN `needs-info`. #92 remains OPEN `needs-info`. This review has
not proven close criterion A or a hard candidate capability/refusal failure for
criterion B.
The remaining #92 blocker is exact source-contract qualification in #91;
#89 and #90 mechanics are complete but their closure does not prove a source.
No runtime source or causal authority was provisioned. Default live acquisition
remains disabled, and no adapter or parser fixture claiming completeness was added.

## Validation record

The research agent inspected the cited Pro League publications through the web
tool. A second documentation check returned the privacy-policy operator and
date, but the completed-match and September-update locators timed out in that
tool. These are tool fetch failures, not proven publisher HTTP 400 responses or
access-control refusals. Earlier extracted publication facts remain dated
research observations; current direct reachability remains unproven.

The other-six source checks inspected current official publication results,
the Premier League calendar announcement, Bundesliga and LFP legal identities,
Serie A's calendar view, LALIGA's representative round and Liga Portugal's
calendar controls. Local static checks verify Markdown links and table/fence
structure, the unchanged exact LF05 registry digest, issue states/dependencies
and `git diff --check`. No production code, schema or test file changed.

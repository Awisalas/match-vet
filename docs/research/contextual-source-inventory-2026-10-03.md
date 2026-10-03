# F08 no-cost contextual source inventory

Reviewed 2026-10-03 for MatchVet's 2026/27 Target League Set: Premier League, Serie A, La Liga, Bundesliga, Ligue 1, Liga Portugal, and Belgian Pro League. This inventory covers the existing source-evidence families in [T07](../source-evidence.md), plus T08 workload and weather. It does not select a new evidence requirement or authorize an adapter.

`APPROVED` applies only to the named capability, use, and limits below. `RESEARCH_ONLY` means a source is useful for this inventory or a manually checked research lead, but has no approved MatchVet evidence-ingestion path. `UNKNOWN` permission or undocumented rights never counts as approval. T07's source authority order remains in force: clubs/managers for player and team facts; competitions/federations for discipline and appointments; official editorial sources for expected lineups; independent specialist reporting only as contextual corroboration.

## Inventory

### Open-Meteo forecast API

| Field | Finding |
|---|---|
| Provider / family | Open-Meteo GmbH; forecast weather for T08 Important weather evidence. |
| Target-league coverage | Global coordinates, including venues in all seven Target Leagues; venue coordinates must already be verified. It is location coverage, not league-specific football coverage. |
| Classification / access | Third-party weather service with an HTTP/JSON API. Its official docs describe the Forecast API and parameters. No key is required for the free endpoint. HTTPS requests work from Termux. |
| Freshness / provenance | Model updates vary by provider and region; Open-Meteo publishes model update status. T08 records model, issue time, retrieval time, target interval, returned coordinates, location provenance, response status, and digest. Forecasts are estimates, may be revised, and are not guaranteed accurate, complete, or continuously available. |
| Automated access | Permitted on the free API only for non-commercial use, within 10,000 calls/day, 5,000/hour, and 600/minute. No uptime guarantee. |
| Retention / attribution / redistribution | API data is offered under CC BY 4.0. Retention and redistribution are allowed under that license with appropriate attribution and notice of changes. Credit Open-Meteo, link the CC BY 4.0 license, and indicate changes. MatchVet's current T08 implementation retains bounded responses with provenance. |
| Cost / limits | Free for non-commercial use at stated limits. Commercial products, subscriptions, ads, or commercial promotion require a commercial plan/license. Historical, climate, ensemble, and satellite APIs are not part of the free forecast scope described here. |
| Failure modes | No coordinates, missing interval coverage, stale or post-cutoff issue/retrieval time, malformed response, coordinate mismatch, unavailable service, changed model schedules, forecast error, or rate limit. T08 maps unusable results to UNKNOWN. |
| Status | **APPROVED**, only for existing T08 forecast use while MatchVet's use qualifies as non-commercial and attribution is preserved. Reassess before commercial distribution. |
| Primary evidence | [API documentation](https://open-meteo.com/en/docs), [terms](https://open-meteo.com/en/terms), [pricing and free-tier limits](https://open-meteo.com/en/pricing), [model update status](https://open-meteo.com/en/docs/model-updates), and MatchVet's [T08 contract](../workload-weather.md). |

### Direct club and manager publications

| Field | Finding |
|---|---|
| Provider / families | The relevant club for injury, availability, manager/regime, rotation, and official lineup announcements; manager interviews or press conferences where published by the club. |
| Target-league coverage | Potentially every club in all seven leagues, but publication format, language, access, and level of detail vary by club. No single complete league-wide feed or coverage guarantee was found. |
| Classification / access | Official primary publishers. Public websites, apps, press conferences, and social posts are candidate human-readable channels. No common public API contract was found. |
| Freshness / provenance | Direct statements can establish what that club announced and when. They do not establish a complete player-availability list, an unreported absence, or that a probable lineup is the eventual XI. Timeliness and correction practices vary. Retain publication time and exact origin for any later approved workflow. |
| Automated access | **UNKNOWN / not approved.** No common club API or permission grant was found. Club-site terms vary and must be checked per publisher before automated access or durable capture. The separate league-site terms cited below do not establish rights for member clubs. LaLiga's official app terms, for example, govern that app and limit its use to personal/private end use while restricting reproduction, copying, distribution, and public communication without authorization. |
| Retention / attribution / redistribution | **UNKNOWN / not approved.** Public visibility and a URL citation do not grant MatchVet a right to store page bodies, create an evidence database, or redistribute claims/content. Permission must be established for each applicable source and intended use. |
| Cost / limits | Reading some pages may be free, but no common free API or service tier was documented. Accounts, regional restrictions, and paywalls vary. |
| Termux / failure modes | Manual browser access is generally possible on Android; automated HTTPS compatibility does not grant access rights. Failures include no report, vague/doubtful wording, translation loss, stale content, removed or edited posts, blocked pages, and inconsistent club coverage. |
| Status | **RESEARCH_ONLY** as a source-discovery hierarchy. No approved automated or retained evidence path. A human-readable official statement can guide future research, but it cannot be ingested under this inventory without source-specific permission and retention review. |
| Primary evidence | [Premier League terms](https://www.premierleague.com/en/terms-and-conditions); [Lega Serie A terms, §5.2](https://en.legaseriea.it/terms-and-conditions); [Bundesliga terms, §6](https://www.bundesliga.com/en/bundesliga/info/terms-of-use-services); [LaLiga official app terms](https://www.laliga.com/en-GB/legal/condiciones-app-oficial). These examples establish restrictions for those publishers only; they do not determine every club's terms. |

### API-Football (API-SPORTS)

| Field | Finding |
|---|---|
| Provider / families | Third-party REST API. Its endpoint catalog and plans advertise injuries/suspensions, lineups, player and coach profiles, and fixture records with referee fields. Coach profiles do not establish the time or official basis of a manager change. Its lineup endpoint supplies match lineups as they become available, including during or after a match, not a dependable pre-lineup expected XI. It does not document a referee-context history suitable for MatchVet. |
| Target-league coverage | The public coverage page lists the seven competitions under its names Premier League, Serie A, La Liga/Primera División, Bundesliga, Ligue 1, Primeira Liga, and Jupiler Pro League. That page says detailed coverage varies by season or fixture. Endpoint-specific 2026/27 flags must be checked; league presence alone does not prove availability for injuries or any other family. |
| Classification / access | Third-party, key-authenticated HTTP API. Official documentation describes GET requests and coverage flags; Termux can call it technically over HTTPS. |
| Freshness / provenance | API-SPORTS says injury reports update every four hours; lineup fields may be missing before kickoff and arrive later. It says its data comes from partners and human feeds, gives no accuracy/completeness guarantee, and describes update frequencies as indicative. Provenance is API-SPORTS/partner output, not the original club, disciplinary body, or appointing authority. |
| Automated access | The API supports automated calls under account and rate limits. That technical access does not grant underlying competition rights. Its terms say the operator provides no license for use and publication, requires users to obtain necessary permissions from competent rights holders, and may suspend access after a rights-holder complaint. |
| Retention / attribution / redistribution | No clear grant for durable private evidence retention or an attribution standard was found. Direct resale is prohibited; publication and commercial use may require separate rights-holder licenses. These gaps fail MatchVet's evidence-artifact and future distribution needs. |
| Cost / limits | Free plan is $0 with 100 requests/day and 10/minute; the free plan has season/data limits, and the provider may change plan availability. Each league/family needs exact coverage checks and calls consume quota. |
| Failure modes | League or family coverage can be false or change; lineups may be absent until after kickoff; injuries can be incomplete or delayed; upstream provider gives no accuracy guarantee; quota exhaustion, HTTP/API errors, pagination omissions, or provider/rights-holder access changes. |
| Status | **REJECTED** for MatchVet evidence acquisition and durable capture under the current terms. It is a credible capability candidate, but permission for retained MatchVet evidence and underlying rights is unresolved. It cannot close the pre-lineup lineup, manager-change, or referee-context gaps. |
| Primary evidence | [Coverage list](https://www.api-football.com/coverage), [pricing](https://www.api-football.com/pricing/), [football API guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide), and [terms of service](https://www.api-football.com/terms). The coverage list is dated 2026-10-03; its season/family coverage is not a guarantee. |

### Competition and federation disciplinary publications

| Field | Finding |
|---|---|
| Provider / family | The competition or competent federation's official disciplinary body and published decisions; suspension eligibility. |
| Target-league coverage | The relevant league/federation is authoritative within its jurisdiction for its own competitions. No complete, openly licensed, machine-readable decision source covering all seven Target Leagues was verified. A disciplinary decision may not itself establish whether a ban applies to a particular upcoming competition or fixture. |
| Classification / access | Official primary publishers. Public decisions, notices, or disciplinary lists are candidate channels; no common public API or open data license was identified. |
| Freshness / provenance | A dated formal decision is strong evidence of its stated sanction. Corrections, appeals, competition-specific carryover, and late decisions can change applicability. Do not treat a missing name/search result as ABSENT. |
| Automated access | **UNKNOWN / not approved.** Reviewed league-site rules include explicit restrictions for Serie A, Bundesliga, and Liga Portugal. Other federations and competition sites require source-specific review. |
| Retention / attribution / redistribution | **UNKNOWN / not approved.** No general retention or redistribution grant was found. |
| Cost / Termux | Some pages may be readable without payment; no common free API tier. HTTPS is technically usable on Termux, subject to access limits and rights. |
| Failure modes | Incomplete publication, delayed or appealed ruling, sanction scope ambiguity, same/similar names, competition carryover, page changes, and failure to find a decision. |
| Status | **RESEARCH_ONLY** for identifying official decision sources. There is no approved automated or retained source path across all seven leagues. |
| Primary evidence | [Lega Serie A terms](https://en.legaseriea.it/terms-and-conditions), [Bundesliga terms](https://www.bundesliga.com/en/bundesliga/info/terms-of-use-services), and [Liga Portugal terms](https://www.ligaportugal.pt/pages/termos-e-condicoes). The Liga Portugal terms limit content to personal, non-commercial viewing and prohibit copying, downloading, or retaining it. |

### Official lineup and referee appointment publications

| Field | Finding |
|---|---|
| Provider / families | Official competition/federation appointment publisher for referee assignments; official club/competition editorial publisher for a genuinely announced expected lineup. Confirmed starting XIs published near kickoff fall outside a pre-lineup recommendation cutoff and cannot be substituted as expected-lineup evidence. |
| Target-league coverage | Publishers are league- and match-specific. The Premier League publishes match-official appointments; Liga Portugal rules assign crews and require disclosure before a match. No documented free source with complete, licensed machine coverage for all seven leagues was found. |
| Classification / access | Official primary publishers. Web pages or notices, with no verified common API/feed contract. |
| Freshness / provenance | A formal appointment notice is strong evidence of the assigned crew at publication time, subject to later replacement. Official editorial lineups may show editorial expectation, not confirmed team selection. |
| Automated access | **UNKNOWN / not approved.** Premier League, Bundesliga, Liga Portugal and Serie A terms materially restrict reuse, storage, or automated access. No general permission was established for other target publishers. |
| Retention / attribution / redistribution | **UNKNOWN / not approved.** A public appointment or editorial article does not grant storage or redistribution rights. |
| Cost / Termux | No common free API/free tier documented. HTTPS is technically accessible from Termux where pages are available. |
| Failure modes | Appointment changes, late publication, no coverage, inaccessible archives, editorial prediction mistaken for official team news, and post-cutoff confirmed lineups leaking into a pre-lineup decision. |
| Status | **RESEARCH_ONLY** for source discovery. No approved no-cost automated or retained path. |
| Primary evidence | [Premier League Matchweek appointment example](https://www.premierleague.com/en/news/4688925/match-officials-for-matchweek-1); [Premier League terms](https://www.premierleague.com/en/terms-and-conditions); [Liga Portugal arbitration regulations index](https://www.ligaportugal.pt/pages/estatutos-regulamentos) and [arbitration regulation](https://www.ligaportugal.pt/backoffice/assets/20240716_ra_54dce33333.pdf), which states the appointment/disclosure rule, and [terms](https://www.ligaportugal.pt/pages/termos-e-condicoes). The publication examples establish capability only, not reuse permission or all-seven coverage. |

### Existing workload and fixture context

| Field | Finding |
|---|---|
| Provider / family | T08 derives rest, turnaround, fixture density, congestion, and cross-competition workload from canonical Fixture Revisions and cutoff-valid fixture history. This inventory does not nominate a new workload provider. |
| Target-league coverage | Depends on the particular source records already admitted through fixture acquisition or explicitly sourced context fixtures. A missing cup/continental fixture cannot be inferred as no workload. |
| Classification / access | Inherited per fixture source; official or structured source identity and origin are recorded under existing fixture contracts. OpenFootball's JSON data is CC0 at repository level and its current-season files auto-update daily from manually maintained Football.TXT; this does not prove third-party upstream rights, freshness of the upstream file, completeness, or a blanket right for other feeds. |
| Automated access / retention | No new blanket approval from F08. Existing F01/F02 provider-use policies and LF02 official-publication citation workflow continue to govern schedule evidence. The operator-attested LF02 route stores minimal citation metadata, not copied page bodies, and is RESEARCH_ONLY. Do not extend it to a new source or workload dataset without checking that source's rights. |
| Cost / Termux | OpenFootball files are publicly available without an API key; the repository lists CC0, and ordinary HTTPS/Git access works on Termux. This classification does not remove the source-lineage and completeness limits above. |
| Failure modes | Missing competition schedules, incomplete update horizon, uncertain upstream rights, uncertain or date-only kickoff, changed/postponed fixtures, duplicated feeds with shared lineage, and false zero-rest conclusions. |
| Status | **RESEARCH_ONLY** for F08's new contextual-source selection. Existing schedule source policies remain as already recorded. No additional workload source is approved here. |
| Primary evidence | [OpenFootball football.json repository and update FAQ](https://github.com/openfootball/football.json), [repository license](https://github.com/openfootball/football.json/blob/master/LICENSE.md), MatchVet's [workload contract](../workload-weather.md), and the [existing fixture-source rights audit](upcoming-fixture-coverage-source-audit-2026-09-27.md). |

## Recommended hierarchy

- **Injuries, availability, manager/regime, rotation, and tactical team news:** direct club/manager statement first; independent specialist reporting only as contextual corroboration under T07. No automated source is approved. Lack of a report remains UNKNOWN.
- **Suspensions:** formal competition or federation disciplinary decision first. No automated source is approved. Confirm sanction applicability to the fixture rather than relying on a generic suspension list.
- **Expected lineups:** official club/competition editorial expectation before the cutoff first. A third-party probable XI is corroborative only. A confirmed XI released after the cutoff is post-cutoff evidence. No automated source is approved.
- **Referee assignments:** official competition/federation appointment notice first. No automated source is approved; record later replacement notices as new evidence if a rights-cleared path is established.
- **Workload:** existing cutoff-valid canonical fixture revisions and explicitly sourced cross-competition fixtures, preserving their existing per-source rights and provenance. F08 approves no new feed.
- **Weather:** Open-Meteo Forecast API under the existing T08 path, with CC BY attribution and non-commercial free-tier limits.

## Explicit gaps

1. There is no approved automated, storable no-cost source for injuries/player availability across all seven Target Leagues.
2. There is no approved automated, storable no-cost source for suspensions, expected-lineup evidence, manager/regime changes, or referee assignments across all seven Target Leagues.
3. Coverage and source-specific storage rights for official French, Belgian, and individual club/federation pages remain unverified. Public pages cannot fill this gap by themselves.
4. Referee context, including any source-backed context beyond the assignment itself, remains UNKNOWN. The reviewed API-Football candidate documents assignment fields but not a suitable historical referee-context dataset, and its use rights fail approval.
5. No historical archive was found that preserves what was knowable at MatchVet's pre-match cutoffs for these evidence families. The current research therefore cannot support retrospective validation of their predictive value.
6. Free Open-Meteo access is limited to non-commercial use. The weather path needs a paid/commercial-use decision before any commercial distribution.
7. Workload completeness still depends on the existing fixture-source coverage and rights policies. F08 does not clear broader fixture-source gaps or authorize copying official schedule pages into new datasets.

## Review

Claims above were checked against the cited first-party terms, API documentation, MatchVet's existing source and workload contracts, and the completed issue-level research review. Rights conclusions are source-specific. Where terms or a durable permission grant were not found, status remains RESEARCH_ONLY or UNKNOWN. This is a source inventory, not legal advice or an adapter specification.

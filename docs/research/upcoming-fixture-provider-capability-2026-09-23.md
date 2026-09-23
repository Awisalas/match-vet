# Upcoming fixture provider capability on 2026-09-23

This note records the live state of the no-cost fixture sources used or considered by T06. It supports roadmap ticket F02. It does not add a completeness definition; F01's `ProviderAttempt` and `ProviderCoverageEvidence` remain the contract in [fixture_coverage.py](../../src/matchvet/fixture_coverage.py).

## Live diagnosis

T06 builds a season-results URL for Football-Data.co.uk for every configured league. Its current source codes are E0, I1, SP1, D1, F1, P1, and B1. The fallback codes are `en.1`, `it.1`, `es.1`, `de.1`, `fr.1`, `pt.1`, and no code for Belgian Pro League. `FixtureHistoryAcquirer` tries OpenFootball only when the Football-Data request raises `SourceUnavailable`. A successful response with no future fixtures does not trigger fallback, and a parse error also does not enter fallback. See the [league configuration and URL builders](../../src/matchvet/ingestion.py#L88) and the [acquisition flow](../../src/matchvet/ingestion.py#L2274).

I fetched each configured 2026/27 season CSV on 2026-09-23 and counted rows with a date on or after 2026-09-23 and blank full-time home and away goals. Every request returned HTTP 200, but every file had zero such rows.

| League | Football-Data season CSV | Rows | Future unscored rows |
| --- | --- | ---: | ---: |
| Premier League | [E0](https://www.football-data.co.uk/mmz4281/2627/E0.csv) | 50 | 0 |
| Serie A | [I1](https://www.football-data.co.uk/mmz4281/2627/I1.csv) | 50 | 0 |
| La Liga | [SP1](https://www.football-data.co.uk/mmz4281/2627/SP1.csv) | 69 | 0 |
| Bundesliga | [D1](https://www.football-data.co.uk/mmz4281/2627/D1.csv) | 36 | 0 |
| Ligue 1 | [F1](https://www.football-data.co.uk/mmz4281/2627/F1.csv) | 45 | 0 |
| Liga Portugal | [P1](https://www.football-data.co.uk/mmz4281/2627/P1.csv) | 62 | 0 |
| Belgian Pro League | [B1](https://www.football-data.co.uk/mmz4281/2627/B1.csv) | 63 | 0 |

This is the observed failure: T06's selected season CSV can be retrieved and parsed, but it contains no future schedule rows. Because the response is available, the current fallback path does not run. A successful season CSV download proves neither upcoming schedule coverage nor an empty upcoming schedule.

An isolated live refresh through `FixtureHistoryAcquirer` reproduced the issue at 2026-09-23 19:06 UTC. It returned seven imports, zero acquisition issues, and zero OpenFootball fallback imports. The T06 captures had zero fixture rows in the next seven days. The source-selection failure is distinct from whether a particular Matchweek has scheduled fixtures.

Football-Data.co.uk has a separate [weekly fixtures page](https://www.football-data.co.uk/matches.php) and a [CSV download](https://football-data.co.uk/fixtures.csv). The page describes dates, times, and fixture odds for the latest main-league fixtures, with weekend odds collected on Fridays and midweek odds collected on Tuesdays. The live CSV capture on 2026-09-23 returned 198 rows across 22 divisions. It included all seven target division codes, but its dates ran only from 2026-09-18 through 2026-09-20. The page reported its latest upload as 2026-09-18. It therefore supplied no future fixture on the probe date. This file is a short-horizon feed, not a complete season schedule, and the live capture had no future coverage bounds or completeness metadata. The file also contains bookmaker odds columns. F02 should read only fixture fields and must not pass odds into prediction or retain them as fixture evidence.

## Provider capabilities by league

The two Football-Data routes have different purposes. The season CSVs supplied historical rows in the live capture. The separate fixtures CSV is advertised as a latest-fixtures feed, but its current capture was stale and had no future rows. Football-Data lists all seven divisions in that feed. Its official page says data files are free and says the data is provided for league-match prediction only ([data page](https://www.football-data.co.uk/data.php), [fixtures page](https://www.football-data.co.uk/matches.php)).

OpenFootball's current `football.json` repository lists fixture and result data for the English Premier League, Bundesliga, La Liga, Serie A, Ligue 1, and other competitions. The live 2026/27 directory contains `en.1.json`, `it.1.json`, `es.1.json`, `de.1.json`, `fr.1.json`, and `pt.1.json`, but no Belgian Pro League JSON file ([repository README](https://github.com/openfootball/football.json), [2026/27 directory](https://github.com/openfootball/football.json/tree/master/2026-27)). Direct captures on 2026-09-23 contained future, unscored fixtures in all six target files:

| League | OpenFootball source | Future unscored fixture rows in live capture |
| --- | --- | ---: |
| Premier League | [en.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/en.1.json) | 330 |
| Serie A | [it.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/it.1.json) | 330 |
| La Liga | [es.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/es.1.json) | 311 |
| Bundesliga | [de.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/de.1.json) | 270 |
| Ligue 1 | [fr.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/fr.1.json) | 261 |
| Liga Portugal | [pt.1.json](https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/pt.1.json) | 243 |
| Belgian Pro League | No file in the `football.json` season directory | Not supplied by this adapter |

The live captures contained no fixture rows in the nearest Matchweek, Friday 2026-09-25 through Monday 2026-09-28 in Africa/Lagos. This may be a genuinely empty Matchweek. The rows do not prove that the whole window is empty, so F01 must not return `CONFIRMED_EMPTY` from these captures alone.

The JSON format has a `matches` array with round, date, teams, optional time, and optional score. The `football.json` README says its latest-season JSON files are generated daily from upstream Football.TXT data, but also says the upstream text data has no daily update process. The README gives no freshness or completeness guarantee. A capture can contain scheduled fixtures, but its existence alone does not prove that later fixture changes have been incorporated.

Belgium has a separate [OpenFootball Belgium repository](https://github.com/openfootball/belgium) with a [2026/27 Football.TXT schedule](https://raw.githubusercontent.com/openfootball/belgium/master/2026-27/be1.txt). It lists all 34 rounds and 18 teams. Its header says exact dates and kickoff times are confirmed only for rounds 1 through 7; rounds 8 through 34 list pairings without exact dates or times. This file cannot establish the schedule for a future date-bounded Matchweek when its entries have no dates. T06 does not currently map Belgian Pro League to this repository and its parser accepts JSON, not Football.TXT.

The official Pro League site separately publishes a [2026/27 match calendar page](https://www.proleague.be/fr/jpl-calendar) and says the exact schedule is set through the winter break in its [calendar update](https://www.proleague.be/nieuws/kalenders-van-fans-liggen-vast-tot-na-de-winterstop). The public page is not a documented fixture API or downloadable dataset in the evidence reviewed here, and the page states "© 2026 Pro League. All rights reserved." The investigation found no terms granting automated capture, retention, or redistribution of its schedule. The official site is evidence that Belgian dates are published, but it is not yet an approved machine-ingestion source for T06.

## Cost and permitted use

| Source | Cost and access | Use limit relevant to F02 |
| --- | --- | --- |
| Football-Data.co.uk CSVs | Direct CSV files are free ([data page](https://www.football-data.co.uk/data.php)). The provider advertises a paid API separately ([API page](https://football-data.co.uk/thestatsapi.php)); F02 must not use that API. | The provider says its data is for league-match prediction only. The current T06 source policy is stricter: `RESTRICTED_PRIVATE`, `RETAIN_PRIVATE`, and not redistributable. Keep use local and noncommercial unless the provider grants broader permission. Do not treat the free download as permission to redistribute or include the data in a paid product. |
| OpenFootball `football.json` | Public raw JSON, no API key, and the [repository README](https://github.com/openfootball/football.json) dedicates data and scripts to the public domain under its [CC0 license](https://github.com/openfootball/football.json/blob/master/LICENSE.md). | CC0 permits reuse of the repository's contribution. The upstream schedule data is manually maintained and has no guaranteed update cadence. Store provenance and retrieval time. |
| OpenFootball Belgium | Public raw Football.TXT with the repository's [CC0 license](https://github.com/openfootball/belgium/blob/master/LICENSE.md). | The 2026/27 schedule is incomplete for exact dates and times after round 7. Its source note attributes the schedule to Pro League and VoetbalPrimeur. Do not treat the repository's license as proof that those third-party source sites grant separate reuse rights. |
| Official Pro League site | Public web pages; no fee was found for reading the pages. | No public machine API, open-data license, or automated reuse permission was identified. Do not claim broader permission based only on public access. |

T06 currently stores Football-Data captures as protected private artifacts and OpenFootball captures as reusable CC0 artifacts in the [source-rights registry](../../src/matchvet/ingestion.py#L873). This repository policy does not override a provider's terms. Product V2 also says to use free, open, or official sources and forbids paid data or infrastructure ([Product V2 direction](../product-v2/PRODUCT-DIRECTION.md), [architecture](../product-v2/ARCHITECTURE.md)).

## F02 implications

- Replace the assumption that a successful current-season results CSV contains upcoming fixtures. The live response disproves that assumption.
- Do not select the Football-Data weekly fixtures CSV as a completeness provider. Its live capture was stale, included odds fields, and had no source-backed future bounds or completeness metadata. If a later adapter records fixture observations from it, keep the odds out and let F01 determine coverage.
- OpenFootball can provide no-cost future schedule rows for six leagues. Its public license is suitable for local retained use, but its manually updated upstream files have no guaranteed freshness. Use F01's `ProviderCoverageEvidence` only when the captured source semantics support its scope, bounds, coverage basis, permitted-use policy, and partition accounting.
- Belgian Pro League is the unresolved source. The available open text schedule lacks exact dates and times after round 7, the current Football-Data weekly capture is stale, and the official site has no identified machine-ingestion or reuse contract. If no approved source establishes a requested Belgian Matchweek, report the F01 coverage result as unknown or partial. Do not claim that the schedule is empty.
- Keep the live future-fixture smoke test separately invoked. It can verify that the six OpenFootball feeds return structurally valid future fixture rows, but it cannot establish completeness. Report the Belgian source limitation.
- Keep source attempts and source captures distinct. A failed request, a malformed response, a valid response with no rows, and a valid partial schedule are different observations. F01 already provides the attempt and coverage fields for those distinctions.

## Live probe record

The probe used direct HTTPS GET requests on 2026-09-23. It requested the seven `mmz4281/2627/<division>.csv` season files, the Football-Data `fixtures.csv`, and six OpenFootball `2026-27/<code>.json` files. It parsed CSV or JSON records, counted unscored fixtures whose date was on or after 2026-09-23, and retained the counts above. No credentials or paid service were used. These counts describe the captured responses, not a standing provider guarantee.

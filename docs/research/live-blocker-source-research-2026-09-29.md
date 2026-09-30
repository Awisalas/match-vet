# Live blocker source research, 2026-09-29

Reviewed 2026-09-29. This note records primary-source facts for the live identity and Belgium fixture blockers. Rights conclusions are limited to published terms and notices reviewed here, not legal advice.

## OpenFootball clubs as an alias source

The [OpenFootball clubs README](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/README.md) defines rows as a club name followed by aliases on `|` lines. It gives `Arsenal FC` with `Arsenal` and `FC Arsenal` as aliases. The repository is [CC0 1.0](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/LICENSE.md), which supports retained local research use of the repository contribution. The license also disclaims clearing rights held by other people.

The snapshot is versionable, but it is not a season roster. The repository's latest commit is `ae3800227c449447b3a337fc0aac79a8f02f4c8b`, dated 2025-01-03. The [Belgian club file at that commit](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/belgium/be.clubs.txt) has SHA-256 `e1c3ff0089b55e30aa87be775e9e2a3c0e385d41a12c9efb792401dd2a818cfc`. It includes useful forms such as `Club Brugge KV` for `Club Brugge`, but also historical rows and repeated short names. For example, `Lommel` appears under both `Lommel United` and `KFC Lommel SK`, while `SK Beveren` appears as an alias in the historical Beveren entries. The 2026/27 official roster includes promoted `KV Kortrijk`, `Lommel SK`, and `SK Beveren`; the OpenFootball clubs file does not identify which historical entry is the present competition participant. The [official 2026/27 announcement](https://www.proleague.be/nieuws/kalender-2026-2027-club-brugge-opent-tegen-kv-kortrijk-eerste-super-sunday-al-op-speeldag-4) names those three promoted clubs.

Use OpenFootball clubs as a pinned, CC0 alias candidate source, not as the identity authority. The deterministic repair should use a versioned, league and season scoped operator-confirmed alias registry. Each entry should retain the exact source spelling, competition and season scope, the existing canonical MatchVet team identity, source URL and pinned source revision or digest, and confirmation provenance. Resolve only a whole-name exact match that yields one existing canonical team in scope. Preserve ambiguity as unresolved. A promoted club must receive an explicit scoped registry entry before it can resolve. Do not register a second canonical team or rewrite historical fixture identities. This keeps aliases replayable and auditable while retaining the OpenFootball snapshot's useful candidates.

## Belgian 2026/27 schedule and candidate rows

The current [OpenFootball Belgium schedule](https://github.com/openfootball/belgium/blob/master/2026-27/be1.txt) says rounds 1 through 7 have officially confirmed dates and kickoff times. It says rounds 8 through 34 have fixed pairings but dates and times still to come. The file header dates the source list to 2026-06-18 and lists a planned 2026-09-01 update, but the checked file still leaves later rounds without exact dates. OpenFootball Belgium's [repository licence](https://github.com/openfootball/belgium/blob/master/LICENSE.md) is CC0; its season file names Pro League and VoetbalPrimeur as upstream sources, so the repository licence should not be treated as a grant from those publishers.

The Pro League's own [calendar update](https://www.proleague.be/nieuws/kalenders-van-fans-liggen-vast-tot-na-de-winterstop) says exact Jupiler Pro League match times are set through after the winter break. Its [official Jupiler Pro League calendar](https://www.proleague.be/jpl-kalender!) lists all nine matchday 8 pairings. The official [RSC Anderlecht fixture page](https://www.proleague.be/fr/equipes/rsc-anderlecht-1/fixtures-results) confirms one matchday 8 game, away to Cercle Brugge on Saturday 10 October at 14:00. This confirms that the competition has usable exact schedule facts for the target period while the OpenFootball file does not.

No published Pro League machine-readable fixture API, bulk download contract, or open-data reuse licence was found in the reviewed official pages. The pages are suitable for a human to cite under an explicit MatchVet research policy; public visibility alone does not establish a broader retention, automation, redistribution, or commercial right. MatchVet should not scrape or automatically request the site. A `RESEARCH_ONLY` manual-citation observation is therefore the appropriate row path for this scope: retain only the minimal fixture facts, publisher and publication identity, official URL, observation timestamp, operator identity, and policy version/digest. Store no page body, PDF, screenshot, or bulk copy. Keep it distinct from Provider Attempts and Provider Health, preserve conflicting facts, and leave completeness to LF02 attestation. This is not a commercial-rights claim.

## Other zero-cost sources checked

OpenFootAPI's [Starter plan](https://openfootapi.com/pricing) costs $0 and includes fixture schedules. Its [terms effective 2026-09-07](https://openfootapi.com/terms) permit indefinite caching of exact responses and normalized fields, plus internal research on retained data. The same terms say each upstream source's licence and restrictions still apply. Its [Belgium coverage entry](https://openfootapi.com/coverage) identifies Football-Data.co.uk as the source with a `Free-Open-Data` label. The OpenFootAPI documentation does not substitute for permission from that upstream. On 2026-09-29 at 05:25 UTC, the documented public preview query for competition `comp_pro_league_be`, season `2026/27`, and date `2026-10-09` returned `total_count: 0`; the preview is capped at five rows and is not intended for production use. That response did not provide a usable candidate row for the target date.

Football-Data.co.uk says its data are free but “made available for the purposes of league match prediction only” on its [data page](https://football-data.co.uk/data.php). Its [weekly fixtures page](https://football-data.co.uk/matches.php) describes a latest-fixtures CSV with betting odds and said the latest upload was 2026-09-25 08:45 UK time. A read of the linked CSV on 2026-09-29 contained 41 rows dated 2026-09-25 through 2026-09-28 and no Belgian division rows. The published pages do not state a retained-data licence or an automated-ingestion grant. The weekly feed therefore does not supply the target Belgian facts or clear the retention and automation requirements.

No reviewed zero-cost automated source both supplied the target Belgian candidate rows and documented the upstream rights needed for automated retained research. OpenFootAPI is worth re-evaluating if it publishes clear upstream terms and returns the relevant fixtures; it is not approved on the current evidence. Do not use an undocumented/private endpoint or scrape the Pro League pages.

## Final live blockers: team identity and schedule precision

Reviewed against code `4e703c9b896165673cb54e23e74d40b7744cc044` and the exact F01 v2 base `sha256:bf181cd113b679d7918bd69732a13548bb3d66fbc53d95c0beb456947d1565c5`. The supplied validation database was opened with SQLite `mode=ro` and `PRAGMA query_only=ON`. It reports schema version 13. No database writes, LF05 observations, or LF02 attestations were made.

### Serie A identity trace

The exact assessment has 18 unresolved Serie A identity candidates and one resolved canonical fixture. The 14 spellings below each have one direct canonical-name or alias lookup hit. For 13 spellings, that hit is a source-specific OpenFootball team ID distinct from the existing LF03 target. Frosinone’s LF03 target ID is absent from both `teams` and `canonical_identifiers` in this store.

| Source spelling | `canonical_key()` | LF03 target | Current canonical-name or alias hit |
| --- | --- | --- | --- |
| ACF Fiorentina | `acf fiorentina` | Fiorentina `15f1e37e-7e97-562e-951c-c881321a0592` | ACF Fiorentina `882d79cc-b9f4-51df-a57d-6e3f968d129c` |
| AS Roma | `as roma` | Roma `2876aa97-fd00-5433-ae45-7d2c95113d1e` | AS Roma `9359abc9-3078-52bf-89f0-0429f560cbb7` |
| Atalanta BC | `atalanta bc` | Atalanta `44e329de-5758-5bac-9cf1-d0f778fe36e3` | Atalanta BC `839077fb-daf2-59c9-a8a1-d68dbf36ec36` |
| Bologna FC 1909 | `bologna 1909` | Bologna `fc746cac-1c0f-5fa7-93c4-78970d7d223c` | Bologna FC 1909 `4a0b33f7-3557-5944-8645-5cda340b0cff` |
| Cagliari Calcio | `cagliari calcio` | Cagliari `3a913936-7c05-553a-80ff-f41546d29aaf` | Cagliari Calcio `8d50b1ca-e9a4-5418-a9b5-3604a5efb018` |
| Como 1907 | `como 1907` | Como `71cdfd16-58ef-5eac-a010-cf0845f3349e` | Como 1907 `696726a5-5026-56ef-be79-132ffff200c7` |
| FC Internazionale Milano | `internazionale milano` | Inter `80cf1b85-f7bc-5ed5-9494-69a916d69b76` | FC Internazionale Milano `47f3bce7-8393-5623-be2f-c710cfbfa86b` |
| Frosinone Calcio | `frosinone calcio` | Frosinone `d463f5bd-51b2-56ac-aa9f-cda1e896379a` (missing) | Frosinone Calcio `bf9905a0-223a-5860-ac80-98f8faf94ffd` |
| Genoa CFC | `genoa cfc` | Genoa `1bb95ff8-c591-58d5-8054-5544c3d3745e` | Genoa CFC `5a2e90a3-9807-5632-a907-d60d24b2bbaa` |
| Parma Calcio 1913 | `parma calcio 1913` | Parma `e3124fdd-d515-59fb-a24a-bfc821aa090e` | Parma Calcio 1913 `d5ac4988-c624-5070-91ed-936cf34ef42d` |
| SSC Napoli | `ssc napoli` | Napoli `f32eb93a-88de-5c7c-a2a8-216bf383fc2c` | SSC Napoli `263ca920-b1a4-524c-addc-96b158c388bc` |
| US Lecce | `us lecce` | Lecce `149ae96b-da42-5a4c-8bf2-14904e71ed6c` | US Lecce `48080dd4-cecc-58b0-abb6-73a12170aeaa` |
| US Sassuolo Calcio | `us sassuolo calcio` | Sassuolo `85ea2339-736f-5fda-9323-71821ca4b167` | US Sassuolo Calcio `ecb8d354-ae77-5a5d-a96f-54e7e73dd0d1` |
| Udinese Calcio | `udinese calcio` | Udinese `d58ca08f-dfbd-5cef-8c6a-029b39d8672d` | Udinese Calcio `dc335a29-22cd-5d7c-a13d-8ef553b48fbe` |

The 13 valid LF03 targets were created from Football-Data `I1.csv`, season 2025-26. Their team rows and source mappings were created at `2026-09-29T15:54:29.650383+00:00`; their source capture is `02499e65-9b94-5728-818a-9444aa805fb9` (`football-data:serie_a:2025-26`). Each first appears in a 2025-26 fixture. Their source mappings use `matchvet-t06-team-v1`, which the code writes for `REGISTER_UNKNOWN`. The Football-Data target teams were also registered through that policy.

All 14 direct lookup hits were created from OpenFootball JSON `2026-27/it.1.json` at `2026-09-29T15:56:46.840469+00:00`. Their source capture is `080f70f2-8da2-56e3-9b62-aff4a7c9e5aa` (`openfootball:serie_a:2026-27`). Each first appears in a 2026-27 fixture. Each source mapping uses `matchvet-t06-team-v1`, the rule version `_insert_source_team_mapping()` writes for `REGISTER_UNKNOWN`. Thus 13 names have two competing database IDs: the Football-Data canonical team and the OpenFootball source-spelling team. Frosinone has one OpenFootball team row, but the reviewed target recorded in `team_alias_registry_v1.json` is missing. Its registry confirmation claims that target exists, so the current `KNOWN_ONLY` resolver correctly refuses that invalid target.

The hypothesis is confirmed for the 13 duplicates. `_resolve_team()` uses the database and registry only in the `KNOWN_ONLY` branch (`src/matchvet/ingestion.py:1814-1862`). `REGISTER_UNKNOWN` falls through to `TeamCanonicalizer.resolve_or_register()` (`src/matchvet/ingestion.py:1863-1868`), which registers an unknown spelling without registry evidence (`src/matchvet/ingestion.py:892-897`). The importer loads its in-memory canonicalizer once at construction (`src/matchvet/ingestion.py:1141-1156`). The scheduled F02 path explicitly passes `KNOWN_ONLY` (`src/matchvet/ingestion.py:3177-3182`), while ordinary imports default to `REGISTER_UNKNOWN` (`src/matchvet/ingestion.py:1158-1165`).

I ran the real `FixtureHistoryImporter._resolve_team()` against an in-memory canonicalizer loaded from the pre-OpenFootball team rows and a fake transaction that captured, but did not execute, SQL writes. All 14 calls produced the same team IDs stored in the database. Thirteen differed from existing registry targets; one target was missing. The fake transaction captured 42 insert statements and executed none. The validation database remained query-only. This proves the old path creates the observed IDs without modifying the store.

The phrase “stale in-memory snapshot” is only partly accurate. The importer’s construction time is not persisted, so its age at registration cannot be proven. A fresh `TeamCanonicalizer` still lacks LF03 registry evidence and would miss these differently normalized spellings. The proven root cause is that `REGISTER_UNKNOWN` bypasses the current database-backed LF03 resolver. LF06 therefore uses one shared resolver and keeps ambiguity fail-closed. It does not repair existing IDs in place. Registry-only aliases stay season-scoped and do not become global `team_aliases` rows.

### DATE and INSTANT schedule comparison

I built manifest entries from the exact F01 v2 revision references and ran the real `_with_manifest_fact_flags()` function. It reproduces 4 Premier League, 4 Bundesliga, and 3 Ligue 1 conflicts. Every listed fixture has one JSON INSTANT and one TXT DATE revision, the same ordered teams, `SCHEDULED` status on both revisions, the same league-local date, and only one exact INSTANT. No listed fixture has a competing exact INSTANT or an explicit provisional marker. This Termux environment lacks the Europe zoneinfo database, so conversion used the application’s deterministic `_source_timezone()` fallback and matched the stored source-local offsets.

| League | Teams | JSON revision | TXT revision | Local date | Classification |
| --- | --- | --- | --- | --- | --- |
| Premier League | Chelsea – Bournemouth | INSTANT `2026-10-10T15:00+01:00` (`14:00Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Premier League | Crystal Palace – Nottingham Forest FC | INSTANT `2026-10-11T14:00+01:00` (`13:00Z`), SCHEDULED | DATE `2026-10-11`, SCHEDULED | 2026-10-11 | LESS_PRECISE_BUT_COMPATIBLE |
| Premier League | Aston Villa – Brentford | INSTANT `2026-10-10T15:00+01:00` (`14:00Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Premier League | Ipswich Town FC – Fulham | INSTANT `2026-10-10T15:00+01:00` (`14:00Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Bundesliga | Paderborn – Stuttgart | INSTANT `2026-10-10T15:30+02:00` (`13:30Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Bundesliga | Union Berlin – Elversberg | INSTANT `2026-10-10T15:30+02:00` (`13:30Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Bundesliga | Hoffenheim – Hamburg | INSTANT `2026-10-10T15:30+02:00` (`13:30Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Bundesliga | Augsburg – Bayern Munich | INSTANT `2026-10-10T15:30+02:00` (`13:30Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Ligue 1 | Paris SG – Le Mans | INSTANT `2026-10-10T20:45+02:00` (`18:45Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Ligue 1 | Lorient – Paris FC | INSTANT `2026-10-10T20:45+02:00` (`18:45Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |
| Ligue 1 | Monaco – Toulouse | INSTANT `2026-10-10T20:45+02:00` (`18:45Z`), SCHEDULED | DATE `2026-10-10`, SCHEDULED | 2026-10-10 | LESS_PRECISE_BUT_COMPATIBLE |

One additional compatible pair in the same exact base is outside the reported 11-conflict summary: Lazio – AC Monza has JSON INSTANT `2026-10-11T15:00+02:00` (`13:00Z`) and TXT DATE `2026-10-11`, both SCHEDULED. The same current flag helper would call it a conflict. Across the exact base, all 12 DATE/INSTANT pairs found by the helper are compatible; none is a genuine schedule conflict. The report’s 11 entries are 11 compatible and 0 genuine conflicts, with this extra Serie A pair noted separately.

`_with_manifest_fact_flags()` is the right fixture-level seam because it already groups revisions by canonical fixture (`src/matchvet/operator_fixture_attestation.py:909-947`). Its current tuple compares `kickoff_utc` directly, so `None` for DATE differs from the instant string. `_revision_is_provisional()` is also in scope because it marks every non-INSTANT revision provisional (`src/matchvet/operator_fixture_attestation.py:951-960`). LF07 adds a fixture-level schedule relation, keeps both revisions, clears conflict and provisional flags only for compatible layering with a valid INSTANT, and leaves real material disagreements conflicting. The operator still checks the official date, kickoff, and status.

### Blast radius and validation order

LF06 changes future team resolution in ingestion. It must preserve current team and fixture IDs, `source_team_mappings`, `team_aliases`, F01/F03 records, and existing digests. The team and alias schema has no season column (`src/matchvet/store.py:872-908`), so registry-only evidence must not be copied into a global alias. Current F05 records, the F06 gate, and T17 table shape remain unchanged. Deterministic IDs and replay must remain stable. No migration is needed.

LF07 changes only the derived LF02 candidate-manifest classification and its versioned serialization. It does not rewrite F01 revisions or the F01 v2 assessment. Keep old manifest versions readable for deterministic replay. F05 provider health and F06’s exact assessment gate remain unchanged. Schema 13 remains unchanged.

The corrective tickets are independent: [LF06 #49](https://github.com/Awisalas/match-vet/issues/49) and [LF07 #50](https://github.com/Awisalas/match-vet/issues/50). Both are outside the original 53-ticket roadmap; F01–F21 retain their numbers. After both finish, use a fresh isolated store for the 2026-10-09 reacquisition. Require zero unresolved identities across the six automated leagues and no false DATE/INSTANT conflicts. Validate Belgian team spellings before recording LF05 observations. Then persist the final v2 base, make all seven LF02 attestations, persist v3, write exact F05 records, and produce the real all-seven F06 freeze. Only then may #44 close and original F07 be unparked.


## LF08 Premier League fresh-store audit

[LF08 #51](https://github.com/Awisalas/match-vet/issues/51) is outside the original 53-ticket roadmap. Baseline `8f0c73b49d7e566923b65f0c7705f2410b8b733c`. The failed store `~/.local/share/matchvet/lf-live-2026-10-09-post-lf07/matchvet.sqlite3` was inspected with SQLite `mode=ro` and `PRAGMA query_only=ON`. The exact assessment was `sha256:aa60cf020414983aded52522124b7e5b3bc9f1caface7f332aca3f567aa72553`. No existing database, LF05 observation, or LF02 attestation was changed.

The assessment has eight unresolved Premier League source candidates, all `TEAM_MAPPING_UNRESOLVED`, representing four fixtures across JSON and TXT. Serie A has ten resolved fixtures and no unresolved identities. Bundesliga, La Liga, Liga Portugal, and Ligue 1 also have no unresolved identities.

### All 20 identities

The matrix uses the exact source spellings and current Football-Data-created teams from the failed store. Direct resolution compares frozen normalized names. Persisted aliases use the whole normalized name and yield the same canonical ID as direct evidence. LF03 v1 contains no Premier League entries. Baseline state was also checked by running the existing resolver against the read-only connection with explicit v1 registry evidence.

| OpenFootball spelling | canonical_key | Current canonical name | Canonical ID | Direct | Persisted alias | LF03 v1 | Baseline state |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AFC Bournemouth | `bournemouth` | Bournemouth | `ff2bcf77-6123-5e62-9516-09c9514315c1` | yes | yes | no | CONFIRMED |
| Arsenal FC | `arsenal` | Arsenal | `db616fb4-3858-533b-9cd7-520cafcf2e25` | yes | yes | no | CONFIRMED |
| Aston Villa FC | `aston villa` | Aston Villa | `4008a4d7-0e6a-5dac-93d3-d371d2eb0cca` | yes | yes | no | CONFIRMED |
| Brentford FC | `brentford` | Brentford | `2142677e-3678-566b-b35c-d1a7893e1059` | yes | yes | no | CONFIRMED |
| Brighton & Hove Albion FC | `brighton` | Brighton | `5f235a5b-6064-5d00-bd66-f8eec7831eaa` | yes | yes | no | CONFIRMED |
| Chelsea FC | `chelsea` | Chelsea | `af6d6294-832a-5dce-868b-8ade29327f8c` | yes | yes | no | CONFIRMED |
| Coventry City FC | `coventry` | Coventry | `e44b25fe-09c7-5297-a25d-976ce4d924e3` | yes | yes | no | CONFIRMED |
| Crystal Palace FC | `crystal palace` | Crystal Palace | `f6f37531-1205-5dcb-a9fc-fbaf1bd81468` | yes | yes | no | CONFIRMED |
| Everton FC | `everton` | Everton | `465b0970-d1d3-5204-85ce-74db81c04dfd` | yes | yes | no | CONFIRMED |
| Fulham FC | `fulham` | Fulham | `a3006cad-b766-5108-8369-fa892c5212b2` | yes | yes | no | CONFIRMED |
| Hull City AFC | `hull city` | Hull | `61dd1b63-6d24-5671-b081-333a42ac0227` | no | no | no | UNKNOWN |
| Ipswich Town FC | `ipswich town` | Ipswich | `dacfb3b4-f83e-597d-9b62-3d1e9f01d85f` | no | no | no | UNKNOWN |
| Leeds United FC | `leeds` | Leeds | `b07d235b-3192-52f5-9b1a-7aa2aca72d10` | yes | yes | no | CONFIRMED |
| Liverpool FC | `liverpool` | Liverpool | `f1a2fae4-cd8b-5c84-896d-b005b5fe7cfd` | yes | yes | no | CONFIRMED |
| Manchester City FC | `man city` | Man City | `85cc0f6e-4930-501d-876a-6f70ff8cbe48` | yes | yes | no | CONFIRMED |
| Manchester United FC | `man united` | Man United | `23532f0f-5d04-592e-96f5-4d4f99907cfe` | yes | yes | no | CONFIRMED |
| Newcastle United FC | `newcastle united` | Newcastle | `1d46f53a-8900-511c-ad5c-2c9916d59e6e` | no | no | no | UNKNOWN |
| Nottingham Forest FC | `nottingham` | Nott'm Forest | `2b4920b0-3bd7-591e-9eae-e4cda32d7b6e` | no | no | no | UNKNOWN |
| Sunderland AFC | `sunderland` | Sunderland | `71c9fcc4-8e1b-5232-9911-0361a158ebed` | yes | yes | no | CONFIRMED |
| Tottenham Hotspur FC | `tottenham` | Tottenham | `04603c5f-a432-5ee8-8a66-02424a853c61` | yes | yes | no | CONFIRMED |

Twenty clubs checked: 16 resolve without a registry, four require reviewed registry aliases, and zero are ambiguous or unprovable. The canonical target for each new alias occurs exactly once in the current league and is confirmed by a Football-Data source mapping.

| Matchweek fixture | Failing name and normalized key | Independently resolved opponent |
| --- | --- | --- |
| Hull City AFC vs Everton FC, October 11 | Hull City AFC, `hull city` | Everton FC → Everton |
| Ipswich Town FC vs Fulham FC, October 10 | Ipswich Town FC, `ipswich town` | Fulham FC → Fulham |
| Crystal Palace FC vs Nottingham Forest FC, October 11 | Nottingham Forest FC, `nottingham` | Crystal Palace FC → Crystal Palace |
| Coventry City FC vs Newcastle United FC, October 12 | Newcastle United FC, `newcastle united` | Coventry City FC → Coventry |

### Pinned alias provenance

The LF03-adopted clubs revision remains `ae3800227c449447b3a337fc0aac79a8f02f4c8b`. Exact English file bytes have SHA-256 `272bf00c7cc8991a0dc98493d0963fab18f07435098637a968f700015e83e93e`. Each club header has the exact OpenFootball spelling; its following alias line explicitly names the current canonical team. Both the exact header and canonical alias occur once in this file. No similarity or fuzzy inference was used.

| Source spelling | Pinned club header | Explicit canonical alias line |
| --- | --- | --- |
| Hull City AFC | [line 288](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L288) | [Hull, line 289](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L289) |
| Ipswich Town FC | [line 372](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L372) | [Ipswich, line 373](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L373) |
| Newcastle United FC | [line 181](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L181) | [Newcastle, line 182](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L182) |
| Nottingham Forest FC | [line 378](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L378) | [Nott'm Forest, line 379](https://github.com/openfootball/clubs/blob/ae3800227c449447b3a337fc0aac79a8f02f4c8b/europe/england/eng.clubs.txt#L379) |

Each entry retains `OPENFOOTBALL_CLUBS_CANDIDATE`, the pinned locator and digest, an existing canonical team ID, and the review confirmation. Scope is exactly `premier_league`, `2026-27`, and `openfootball-schedule`. Operator observations do not inherit this lineage.

### Snapshot compatibility and blast radius

`team_alias_registry_v1.json` remains byte-for-byte unchanged. Its file SHA-256 is `252e7eb14f628573b2122844b41f64f8f72ffeec0ef9e2f0026e5698132dac98`; its policy digest remains `sha256:1bdae3b0888acc35e03f691739c16a7930bcf3ff42d7c3d9619842d16a90b86a`.

The append-only successor `matchvet-team-alias-registry-v2` contains every v1 entry unchanged plus the four entries above. Its policy digest is `sha256:7ceb69ae874d8e83f8358960d347b7bedf3a5e229c29b9f50ef7d5e63d0fbccd`; its file SHA-256 is `df3d635d4f9e1d6b9d41ab1305f3d77c99b39043661cb35117b4f62b2747a635`. Both files remain packaged. Decoding returns the declared version, verifies its digest with that version, and applies the same strict entry validation. `default_registry()` selects v2.

The safety condition is that adding registry evidence cannot override a different current team ID. The unchanged LF06 resolver combines current canonical names, persisted aliases, and exact scoped registry evidence by ID, resolving one supported ID and refusing multiple IDs. It also refuses a different current identity when the reviewed target is missing. The historical LF03 corpus deliberately retains its original source-created Premier League IDs: explicit v1 resolves 85 of 86 names, while v2 refuses the four conflicting Premier League identities and the original malformed Gil Vicente spelling. This is expected fail-closed behavior, not an ID migration.

The regression calls the public importer and normal scheduled acquirer in temporary stores. With explicit v1 it produces the original eight unresolved candidates. With v2 it produces four unique canonical fixtures, eight source observations, zero unresolved candidates, matching JSON/TXT fixture IDs, and both feed provenances. It checks all 20 spellings through both source kinds, no historical seasons, unchanged existing fixtures, exactly 20 unchanged canonical teams, unchanged global alias rows, schema 13, and migrations 1–13. A separate replay test verifies that old v1 source mappings and their policy provenance remain unchanged under v2. These are executed-code proofs, not claims about a new live acquisition.

The offline JSON fixture is a four-match reduction of captured OpenFootball JSON digest `bb91f0ab3e8359df163bb9ec98549bfed85e200dd4c32f3bd606b5890d932dd2`. TXT preserves the four corresponding rows and blank kickoff fields from capture `a2366ea9f7f55b8afd666e455666ba9019f9c62da8864f6bcf3adff65300b445`, with the year made explicit after removing earlier rounds. The Football-Data test input uses synthetic results and the audited current canonical names; it contains no historical seasons or redistributed protected result capture.

`canonical_key()`, resolver code, store schema, migrations, F01/F03 serialization, F05/F06 behavior, and T17 implementation are unchanged. The F01 v2 golden remains `sha256:b3b4fada3f37449f48895467fd7f0964679cd31682cc4439bac82fa075c8ee78`.

### Remaining live gate

#44 remains open and original F07 remains parked. After LF08 verification, another fresh isolated real validation must establish zero unresolved identities across all six automated leagues and no false schedule conflicts. The separate all-seven validation sequence, including Belgian spelling validation and later authorized LF05/LF02 work, still gates the real F06 freeze and closure of #44. LF08 itself records no observations or attestations and does not certify live completeness.

### LF08 verification results

The LF08/LF03/LF06 focused identity run passed 61 tests. The requested ingestion, LF05, LF02/LF07, F01/F03, F05/F06, and T17 compatibility selection passed 296 tests under system Python; its remaining test required the repository environment's `requests` dependency and passed there. The full isolated suite passed all 827 tests under `.venv/bin/python`, with network connections disabled and the default store redirected into a temporary Termux private root.

Mypy 1.18.2 passed all 69 source files in the repository environment. Ruff check and format check passed for all 100 files outside the explicitly excluded `.audit/` and `.f02-work/` directories. `git diff --check` passed. An offline wheel build retained both registry files with exact source bytes. Independent standards and spec reviews found no issues. The registry, normalization, store, migration, and golden-file comparisons against the supplied baseline confirmed the preservation claims above.

## LF09 official Pro League identity correction

LF09 [#52](https://github.com/Awisalas/match-vet/issues/52) is outside the original 53-ticket roadmap. Against baseline `47e1eec4644f24a1ce33b5a4176379a4d7220feb`, the validated post-LF08 database was opened read-only with SQLite `mode=ro` and `PRAGMA query_only=ON`. It contains exactly 18 unique Belgian 2026-27 canonical teams. All 15 proposed targets exist once, have distinct normalized names, and their stored IDs match the frozen deterministic team identity calculation. The pre-LF09 official resolution is 3 CONFIRMED, 15 UNKNOWN, and 0 AMBIGUOUS, blocking all nine official matchday 8 fixtures.

The corrective policy is a separate immutable Pro League manual-citation registry for `OPERATOR_OFFICIAL_FIXTURE_OBSERVATION`, Belgian Pro League, and 2026-27. Its 15 exact names cite the approved `www.proleague.be` official competition calendar. The normal LF03 resolver combines current canonical identities, persisted whole-name aliases, and the applicable source registry; conflicts remain ambiguous and missing targets remain unknown. The policy does not expand OpenFootball lineage or make official names available to other source kinds, leagues, or seasons. The reviewed policy digest is pinned, so a coherently retargeted and re-signed entry is refused. Every new Belgian 2026-27 official source mapping, including a direct-name mapping, carries the Pro League contract and digest. No schema change or rewrite of stored mappings is needed.

The temporary-store regression confirms 18 of 18 official source spellings and all nine LF05 pairings are identity-ready. This is an identity check only. #44 remains open, original F07 remains parked, and recording the real LF05 observations and LF02 attestations remains a later step in the all-seven validation sequence. LF09 does not address `Gil Vicente FC [postponed]`.

The official registry contract is `matchvet-pro-league-team-alias-registry-v1`, with digest `sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`. The final LF09/LF03/LF05/LF06/LF08 identity run passed 108 tests, the broader compatibility selection passed 379 tests, and the final isolated suite passed 851 tests. Ruff check, Ruff format check, mypy, and `git diff --check` passed. OpenFootball v1/v2 bytes and policy digests remain unchanged; F01 v2 retains `sha256:b3b4fada3f37449f48895467fd7f0964679cd31682cc4439bac82fa075c8ee78`. Schema 13 and migrations 1–13 remain unchanged.

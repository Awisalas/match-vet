# Pro League date-window calendar qualification

Research date: 2026-10-10. Belgium-only
[#96](https://github.com/Awisalas/match-vet/issues/96), following
[#95](https://github.com/Awisalas/match-vet/issues/95), for
[#92](https://github.com/Awisalas/match-vet/issues/92).

## Decision

**B: INSUFFICIENT. Further Pro League official probing stops here.**
The exact frontend path is GET
`https://www.proleague.be/api/football_module/football_calendar`.
It sends start/end and a nested event preset. The delivered view proves how the
frontend constructs and displays this request, but no retained JPL page supplies
the preset that binds this events service to the Belgian fixture scope.
Completeness, boundary inclusivity, currentness, affirmative empty and automatic
identity mapping remain unproven. #92 remains OPEN `needs-info`.

This is a failed qualification prerequisite, not technical refusal or a claim
that the endpoint cannot ever serve fixtures. No calendar data request was made:
the exact Belgian scope could not be established before contact. Filling in an
invented typology, treating an absent preset as a valid Belgian query, or using a
known UUID in an unproved events namespace would not satisfy the discovery rule.
The representative-window and empty/boundary probes were therefore NOT PERFORMED.

[#97](https://github.com/Awisalas/match-vet/issues/97) is the next bounded
third-party qualification issue. Its first step is Football Charts' free-tier
terms and complete-current contract, not fixture acquisition. OpenFootAPI and
API-Football fail the user's explicit completeness-authority gate below.
No inspected third-party candidate is qualified. Default live acquisition stays
disabled; no adapter, Store or real source/causal authority was activated.

## Exact discovery and request construction

The [retained calendar](pro-league-calendar-raw-qualification-2026-10-10.md) explicitly
links the [webpack runtime](https://www.proleague.be/_next/static/chunks/webpack-6af05fc33c034203.js).
The [retained application](pro-league-replacement-fixture-source-2026-10-10.md)
explicitly imports chunk 4184/module 64184 for its football calendar view.
The runtime maps 4184 to hash `19523322e933f1f8`, builds the static chunk filename,
and sets public path `/_next/`. This constructs exactly the
[calendar view asset](https://www.proleague.be/_next/static/chunks/4184.19523322e933f1f8.js).
Only those two additional official assets were retrieved. No wildcard chunk,
source map, guessed page, team or matchday was requested.

Application module 93098 constructs same-origin `/api/` plus the supplied path
and serializes locale/options with bracket array syntax. The view passes
`football_module/football_calendar` to that public builder with GET, `start`,
`end` and its inherited `preset`. Headers add JSON content type and optional
Content-Language, with no authorization or tokens. This proves the exact frontend
construction, not live availability of this uncontacted endpoint.

| Contract field | Observable source behavior | Qualification |
| --- | --- | --- |
| Method/path | GET `/api/football_module/football_calendar`; non-GET handler returns 404 | Proven from delivered view and handler |
| Window parameters | `start`, `end`; frontend passes ISO strings from visible calendar bounds | Parameter names/instant conversion proven; backend inclusion UNKNOWN |
| Nested preset | `teams`, `typology`, `eventTypes`, `competition` | Names proven; valid JPL preset values/namespace UNKNOWN |
| Competition selection | Optional `competition` becomes equality filter | JPL competition UUID exists in football data, but events namespace binding is unproved |
| Season/edition | No selector forwarded by the calendar handler | Requested-season fixture partition UNKNOWN |
| Status | No match-status filter/contract in handler or view | Required postponement/cancellation/revision membership UNKNOWN |
| Pagination | No pagination parameter forwarded; only upstream `data` returned | Counts, truncation/exhaustion/currentness siblings are not preserved; underlying limits UNKNOWN |
| Frontend result use | Maps returned array directly to display events | Display use proven; complete/current coverage not asserted |

The handler `tX` calls helper `w`. The helper always adds a typology equality
filter, then adds event-type/team membership filters for nonempty supplied lists
and competition equality if supplied. Its generic filter serializer does not
skip undefined values: an absent typology becomes the literal string
`undefined` upstream. That is not an unfiltered Belgian fixture query.
The retained JPL HTML/embedded data has no `football_calendar` module and no
`preset`, `typology` or `eventTypes` values. A display record's `type: game` does
not prove that the input typology should be `game`.

The helper uses the miscellaneous v1 events service, not the football v2 edition
fixture service examined in #95. It passes formatted start/end into
`events/{start}/{end}` and returns the data array. No cross-origin service was
contacted and no credential value was extracted or reused. Knowledge of that
backend construction supplies no direct-public access authority.

## Window and UTC assertions

The representative MatchVet window would be Friday 2026-10-09 00:00 inclusive
to Tuesday 2026-10-13 00:00 exclusive in Africa/Lagos. Using the existing
[MatchVet timezone contract](../matchweek-freeze.md#window-and-cutoff), its exact
UTC bounds are `2026-10-08T23:00:00Z` to `2026-10-12T23:00:00Z`.
These are planned scope bounds, not parameters dispatched to the source.

The frontend calendar navigation sends `firstVisibleDay` and `lastVisibleDay`
of the visible month as `.toISOString()` values. Server-side hydration likewise
uses visible-month dates. The handler parses both with `new Date()` and formats
them with retained module 51257. That formatter uses host-local components and
emits `Z` or an explicit offset, with second precision.

An offline check executed the exact retained formatter function, with date
conversion/padding/argument helpers isolated from the page. Both UTC and
Europe/Brussels host settings preserved the planned bound instants. UTC produced
`2026-10-08T23:00:00Z`; Brussels produced `2026-10-09T01:00:00+02:00` for the same
start instant. This proves the formatting conversion for the planned inputs.
It proves neither source inclusivity nor timezone semantics of returned fixtures.
No source half-open contract, known empty interval or supported season partition
was established, so no F01 window or CONFIRMED_EMPTY assertion was created.

## Completeness, empty and currentness

The public wrapper removes every upstream sibling of `data`. This proves the
wrapper does not preserve count, page, terminal or snapshot siblings; it does not
prove that upstream supplies them or that the response is truncated. No exact
window membership or exhaustion guarantee was found in the delivered code.
The frontend treats the array as its displayed calendar input, without pagination
or a coverage check. Displaying returned records is not a complete fixture-partition
contract.

A hypothetical successful empty array could reflect an unsupported/missing
preset or absent returned events. There is no affirmative-empty basis for the
entire requested Belgian window. No empty response was contacted or promoted.

No explicit update/as-of/revision field or complete-current snapshot assertion is
exposed by the handler or view. Native publication times and atomic API tokens
are not mandatory F01 requirements; a source-backed complete-current snapshot
with persistent identities could suffice. This alternative was not established.
HTTP Date, cache headers, ETag, static asset Last-Modified and retrieval time remain
transport facts, never fixture publication times or freshness results.

The previous private captures contain one `PreMatch` to `SecondHalf` transition,
not an exact moved/rescheduled fixture before/after pair. No such pair is available
to test this unqualified event feed. Actual-date inclusion after rescheduling
therefore remains UNKNOWN. No news update was substituted for a revision stream.

## Fixture and identity semantics

The view distinguishes event and game display records. A game uses its `id`,
ordered `homeTeam`/`awayTeam`, competition and gameweek labels. It constructs
calendar display start from `time || date`; when time is absent it displays an
all-day record. For a timed game it invents a two-hour display duration.
That duration is UI geometry, not source kickoff/end evidence. The view exposes
no fixture status/update semantics. A calendar event ID cannot be assumed to be
the football fixture UUID namespace without a retained sample.

The earlier [18 canonical target observations](pro-league-calendar-raw-qualification-2026-10-10.md#identity-observations)
and #95's 17 corroborated team UUIDs/seven recurring fixture IDs were rechecked.
All 18 targets remain unique and consistent with existing canonical identities.
The LF05 registry retains its original manual lineage and digest
`sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`.
No team was created and no production Store was opened.

There are zero new calendar identity observations. Its source namespace and
persistence against all 18 canonical teams remain UNKNOWN. No automatic-source
mapping revision was approved. Exact matching in the football payloads does not
transfer authority to the miscellaneous events feed.

## Bounded probes and private evidence

Two official asset requests received 16,265 complete bytes. The shared task limit was
four requests and 512 KiB; each probe allowed 256 KiB response bytes, five-second DNS,
ten-second request, fifteen-second probe budget, two-second pacing, zero retries,
zero redirects and zero backoff. Exact HTTPS targets/public IPs were validated
before contact and TLS was pinned/verified. There was no rate response, challenge,
credential, identity change or refusal bypass. Calendar fixture/empty probes and
third-party fixture requests total zero.

| Requested/final URL | Completed retrieval UTC | Status | Bytes | Body SHA-256 |
| --- | --- | --- | --- | --- |
| `https://www.proleague.be/_next/static/chunks/webpack-6af05fc33c034203.js` | `2026-10-10T17:42:09.117967+00:00` | 200 | 12270 | `10a11d1fb39792bab28f4ddc2b352fb7c0d8b2a252d6b7563daf5c2c719c4ea4` |
| `https://www.proleague.be/_next/static/chunks/4184.19523322e933f1f8.js` | `2026-10-10T17:43:10.804230+00:00` | 200 | 3995 | `83e926b707b4c2580c82ce4c63cdd85615869185254abc462932773465d4cee7` |

Both redirect chains are empty. Ledgers retain exact request/start/header/finish
times, public addresses, limits, status, content type, length, Date, ETag,
Last-Modified and cache metadata. Parameters for both asset requests are empty.
The planned fixture window is separately retained as NOT DISPATCHED with the
missing-scope reason, not a fictitious request result.

Private raw assets, DNS/request ledgers, contract observations, formatter results,
checks and documentation provenance are in
`.audit/issue-96-calendar-window-2026-10-10/`, directory 0700/files 0600.
The contract observation file has SHA-256
`cee1d1cfffbfee9570c98d601a4a0b47d4635e9dd6794991e06b93387fbb108c`;
the private retained-file manifest has SHA-256
`6c4a303cef25117f243ce32b0f9eae3d8f8514ad77aced6c262c494e171a3903`.
These locators allow offline digest checks without a source refresh.
No raw source bytes or credentials are committed. Documentation review uses
primary pages through the web reader; exact HTTP response digests/status/times
are unavailable there and are not invented as source captures. Its retained
review/provenance files are derived documentation evidence.

## Fresh third-party ranking

Primary documentation was inspected on 2026-10-10. Ranking is the order for a
bounded contract review, not a ranking of proven completeness. There is no
qualified zero-cost replacement yet.

| Priority | Candidate | Current free capability | F01 completeness-authority verdict |
| --- | --- | --- | --- |
| 1, documentation only | Football Charts | Published keyless REST; current/previous season; Belgium 2026/27 standings | UNKNOWN, not approved; complete window/status/identity contract absent and disclaimer applicability unresolved |
| 2, reject | OpenFootAPI | Free Starter advertises fixtures; documented UTC/IDs/status and Belgium identifier | REJECTED under the user's match-availability/completeness gate |
| 3, reject | API-Football | Free 100 requests/day; exact current Belgian season entitlement unproved | REJECTED under the user's football-data availability gate |

[OpenFootAPI terms](https://openfootapi.com/terms), effective 7 September 2026,
exclude "guaranteed availability of a particular match" and say
"Football information can be delayed, incomplete, corrected, or unavailable."
These clauses concern match information, not merely service uptime. Retention and
internal research are allowed by those terms, but that does not restore F01
completeness. [Documentation](https://openfootapi.com/docs) supplies UTC calendar
date filters, kickoff/identity/status fields and source/count metadata;
[coverage](https://openfootapi.com/coverage) lists `comp_pro_league_be`.
[Free pricing](https://openfootapi.com/pricing) is 5,000 authenticated requests/month,
60/minute. Complete Belgian result entitlement is not proven; no demo key or
fixture endpoint was used. Marketing coverage cannot override the terms.

[API-Football terms](https://www.api-football.com/terms), under Availability of
data, explicitly say competition coverage does not guarantee data availability.
They separately treat update frequencies as indicative. These are data-availability
limitations and fail the user's gate. [Pricing](https://www.api-football.com/pricing)
provides free 100/day with limited seasons; exact Belgian 2026/27 full-result
entitlement remains UNKNOWN. No signup, credentials or feed probes were performed.

[Football Charts developers documentation](https://www.football-charts.com/developers)
publishes its REST base and endpoints, keyless 300/day/IP, current/previous season,
research use with attribution and no resale. Updates are overnight around 06:00
UTC; upcoming fixtures cover a few days ahead. This establishes neither a full
Friday–Tuesday horizon nor complete-current/empty/revision semantics.
The [Belgium 2026/27 page](https://www.football-charts.com/rankings/belgium/jupiler-pro-league/2026-2027/classic)
shows 18 club names, not fixture completeness or an automatic mapping.
The [publisher's MCP repository](https://github.com/ddevetak/footballcharts-mcp)
is a public implementation reference; no connector/package was installed.

[Football Charts Terms of Sale](https://www.football-charts.com/terms), updated
27 September 2026, identify Damir Devetak, Serbia. They explicitly state paid
products/paid-API scope and say "without warranty of completeness". Applicability
to free access is unresolved here. This uncertainty cannot approve free F01
authority. If the selected free contract carries that disclaimer, reject it under
the same rule; otherwise still require a genuine complete-current contract.
No clearly better qualified zero-cost source was found. No odds or archive was
acquired. ADR 0006 owner-risk acceptance does not change these capability verdicts.

## Follow-up and checks

#97 first resolves Football Charts' free contract, full-window horizon and
complete-current/status/identity basis from primary documentation/source.
It may proceed to minimal bounded fixture probes only if those precontact gates
are satisfied. If absent, it must close insufficient without acquisition. It
must not retry rejected candidates to find rows or return to official Pro League
probing. Manual Belgian evidence remains a temporary honest path, not automation.

Checks verify retained old/new digests and protected modes, reject changed bytes,
reconstruct exact linked runtime/view locators, validate budgets/pacing and zero
fixture contact, run the retained formatter offline, check planned UTC bounds,
all 18 canonical targets/manual mapping lineage and documentation links/fences/
tables. Fresh primary source links, issue states/dependencies and `git diff --check`
are checked. Production modules, tests, ADRs, formats/readers and schemas are unchanged.

#96 closes completed under B after delivery. #97 remains OPEN `ready-for-agent`
for bounded research; #92 remains OPEN `needs-info` and blocked by #97. #90/#91/#95
remain CLOSED and #70 OPEN `needs-info`. No other league, #93/#94, causal
provisioning, #86 acquisition, fitting, F17/F18/F20, PLAY or promotion changed.

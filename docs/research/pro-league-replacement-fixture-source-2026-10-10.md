# Pro League replacement fixture source qualification

Research date: 2026-10-10. Belgium only, under
[#95](https://github.com/Awisalas/match-vet/issues/95), for
[#92](https://github.com/Awisalas/match-vet/issues/92).
The [previous calendar inspection](pro-league-calendar-raw-qualification-2026-10-10.md)
remains retained. #91 remains CLOSED under criterion B.

## Decision

**B: INSUFFICIENT for the complete-current F01 schedule contract.**
An exact official, unauthenticated, same-origin JSON path is now established:
`https://www.proleague.be/api/football_list/football_competition_match/variant_b`.
It accepts an edition, a status tab and offset/limit pagination. A minimum sample
and terminal-offset response prove public access, explicit UTC, source identities
and a filtered total. This is a useful replacement for the one-matchday HTML.
It is not yet a proved complete-current requested-window snapshot.

The exact gap is coverage/currentness across status partitions and pagination.
The `fixtures` tab selects live/pending records. Postponed, cancelled and abandoned
records are classified as warning records, selected by the separate `results` tab.
Neither tab exposes a date-window selector or a snapshot/revision boundary in the
inspected handler. The sample supplies no all-status coverage assertion,
replacement/omission contract or proof that successive pages and tabs belong to
one complete current observation. HTTP success, a filtered count and an empty
terminal page cannot supply those missing claims.

This decision applies to the inspected interface, not every official Pro League
source. Access is successful, not REFUSED. Exact kickoff semantics are established;
fixture publication times and a complete-current comparison contract remain
UNKNOWN. #92 remains OPEN `needs-info`, without `ready-for-agent`.
No adapter, real source authority or production acquisition was activated.

## Observable locator construction

The [official calendar](https://www.proleague.be/jpl-kalender!) retained under #91
explicitly delivers three first-party assets used here:

| Asset | Discovery role |
| --- | --- |
| [Catch-all page](https://www.proleague.be/_next/static/chunks/pages/%5B%5B...params%5D%5D-5373773570be0da7.js) | Delegates rendering to shared application module 18567 |
| [Application](https://www.proleague.be/_next/static/chunks/pages/_app-bbcca07184f495da.js) | Public URL builder, football route table, handlers, service classes and status vocabulary |
| [Match list](https://www.proleague.be/_next/static/chunks/1421.f8a2dff180873339.js) | Actual calendar interaction calls the public builder with `football_list/football_competition_match/variant_a` and edition/round/gameweek IDs |

These are exact `script src` values from the retained calendar HTML, resolved
against its validated origin. No guessed chunk, Next data route, source map,
team crawl or endpoint enumeration was used.

In the application, module 93098 exports the public data provider. It constructs
same-origin `/api/` plus the supplied route, then serializes `locale` and supplied
query fields with bracket array encoding. Headers are JSON content type and
optional Content-Language. This builder supplies no authorization, cookie,
subscription key or CAPTCHA token. Module 18567 exports it as `_Gb`.
Module 26460's football route table explicitly binds
`football_list/football_competition_match/variant_b` to handler `tq`.
That handler accepts GET and forwards `activeTab`, `editionId`, `roundIds`,
`groupIds`, `teamId`, `offset` and `limit`, defaulting limit to 15, to `tl`.
It returns the upstream matches object unchanged.

The delivered table and builder expose the exact path; the successful no-credential
GET separately proves its public reachability. The retained page visibly uses
variant A, not variant B. This distinction is recorded rather than claiming the
calendar made our variant B request. No optional round/group/team filter or
undelivered date filter was guessed for the probe.

### Cross-origin service boundary

The retained calendar's `/props/runtimeConfig/apiBaseUrl` is
`https://apim-maker.llt-services.com/makerweb/`. Application module 95681 uses
FOOTBALL v2; module 92426 maps that service to `msfootball`. Its edition games
method and the generic client construct the family
`makerweb/msfootball/api/v2/editions/{editionId}/games`, with language,
serialized pagination and filters. The generic client can append a server-supplied
subscription key and optional authorization.

No cross-origin Maker request was made. No credential/token value was extracted
or reused. The hostname and generic service construction do not establish a
public unauthenticated backend or a permitted direct acquisition path. The
public same-origin proxy is the representation inspected. The publisher/operator
is Pro League NV under the [retained operator review](pro-league-source-contract-2026-10-10.md#exact-candidate-and-known-publication-facts).
Maker platform delivery is observed; exact fixture-data upstream remains UNKNOWN.

## Scope and enumeration

The edition UUID comes directly from the retained public calendar:

| Identity | Value |
| --- | --- |
| Competition | `18d6fee0-d3bb-4624-b4d2-ac5b16ab498c`, Jupiler Pro League |
| Season | `bd52b2d5-437b-46de-a088-1678e062fff1`, Seizoen 2026/2027 |
| Edition | `6582729e-c371-4573-8d59-50674807d96c` |
| Regular round | `c36a5f14-de03-4ec9-93fe-07e9065a8b57` |

The exact [sample request](https://www.proleague.be/api/football_list/football_competition_match/variant_b?locale=nl&activeTab=fixtures&editionId=6582729e-c371-4573-8d59-50674807d96c&offset=0&limit=15)
returns only `total` and `data` at the root. `total` is 277 and `data` contains 15
unique fixtures spanning matchdays 8 and 9. The requested tab is an edition-wide
live/pending partition, not one nominal matchday. The handler supports optional
round/group/team restrictions and sorts fixtures by ascending `date`, then `time`.
Results use descending order and finished/warning states. The sample's first and
last times are `2026-10-10T16:15:00Z` and `2026-10-25T17:30:00Z`.

One [terminal probe](https://www.proleague.be/api/football_list/football_competition_match/variant_b?locale=nl&activeTab=fixtures&editionId=6582729e-c371-4573-8d59-50674807d96c&offset=277&limit=1)
uses the returned count, not a guessed partition. It returns exactly
`{"total":277,"data":[]}`. This establishes an observed terminal offset for this
filtered list. Offsets 15 through 276 were not requested; their membership was
not retained or asserted complete. The terminal empty response means there are
no records at that offset, not no fixtures in a MatchVet window.

No requested-window affirmative-empty state was proven. The 34-round/18-club
competition format supplies no retrieval proof. Edition selection avoids a
nominal-round restriction for the sample, so moved fixtures can in principle
remain discoverable by current time. Actual move-in/move-out and revised nominal
round behavior were not observed and remain unqualified.

A bounded parser could eventually inspect ordered pages until it passes a window,
with both status partitions accounted for. Such a design needs an exact proved
coverage/currentness contract and failure behavior first. Reaching a page beyond
the window, counting rows or inventing a source-backed assertion would not settle
this research gap. The results partition was not requested and its payload,
warning retention and exhaustion were not qualified.

## UTC, status and currentness

Every sampled fixture has an explicit ISO timestamp ending in `Z`. UTC parsing
requires no geographic timezone assumption. The previous calendar separately
supplies `Europe/Brussels` as its display timezone; the adapter would preserve
that only as supported display metadata. Source `date` is not a replacement for
`time`, and an absent/nonexact kickoff must remain UNKNOWN.

The delivered status helper in module 60768 classifies pre-match/scheduled states
as pending, active play states as live, full-time/post-match as finished, and
postponed/cancelled/abandoned as warning. The sample contains `PreMatch` and
`SecondHalf`. This proves a software vocabulary, not observed postponed/cancelled
rows or a complete publisher revision policy. Unknown period types fail closed.

Seven fixture UUIDs recur from the earlier HTML with the same ordered teams and
UTC kickoff. Fixture `59621840-1a44-4395-80ae-b1c5f56c8c55`, RAAL La Louvière
against Club Brugge, changes from `PreMatch` in the 15:12 UTC calendar capture to
`SecondHalf` in the 17:22 UTC JSON capture. This proves a real status update is
observable under the same identity. It does not establish when the source
published that change, identity persistence after rescheduling, or a complete
revision stream.

The responses expose no fixture `updatedAt`, revision ID, snapshot ID or as-of
field. Native publication timestamps are not mandatory if a complete-current
snapshot contract can be proved. Here that alternative remains unproven across
offset pages and status tabs. Sorting has no explicit fixture-ID tie breaker;
status transitions may move rows between tabs during a traversal. Counts alone
cannot detect equal-count replacement, skipped rows or conflicting observations.
No guarantee about removal versus cancellation or later authoritative replacement
was established. F01 does not require an atomic API or a native snapshot token;
the blocker is the missing evidence-backed complete-current coverage contract,
not the pagination mechanism alone. HTTP Date, cache lifetime, ETag, asset modification time and
retrieval time remain transport facts, never fixture publication times or an F01
freshness verdict. A future freshness policy must be separately versioned.

## Automatic identity mapping verdict

The existing [18-row identity observations](pro-league-calendar-raw-qualification-2026-10-10.md#identity-observations)
remain the canonical target list. The new 15-row sample contains 17 distinct team
UUIDs. Every UUID, exact name and slug agrees with that list. Cercle Brugge is not
in the new sample; its retained earlier observation remains evidence, not a new
confirmation. All 18 target IDs remain distinct and agree with MatchVet's existing
deterministic canonical identities. Fifteen also agree with the existing LF05
alias records; the other three use the already reviewed direct canonical names.
No Store was opened and no team was created.

The observed namespace is the Pro League website's client football data for the
exact Belgian 2026/2027 competition/edition above. `competition.source` is `client`,
`competitionMaster` and sampled `teamMaster` are null. UUIDs, not slug numeric
suffixes, are the structured identity keys. Current upstream ancestry and lifetime
persistence remain UNKNOWN. Agreement across two public representations supports
automatic mapping research, but does not establish persistence through reschedule,
merge or replacement.

No automatic mapping authority/revision was created. A future mapping specification
must pin this new automatic source family, exact scope, source UUID/name pairs,
existing canonical targets, review revision and evidence digest. Unknown/conflicting
IDs must refuse with no fuzzy fallback. The LF05 manual registry retains digest
`sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`
and `OPERATOR_OFFICIAL_FIXTURE_OBSERVATION` lineage unchanged.

## Bounded transport and private retention

Nine source requests inspected three distinct JavaScript assets and two JSON
locators. No calendar refresh, results traversal, season crawl or club crawl was
performed. All requests used public-IP validation and pinned TLS for the exact
allowed HTTPS host. No redirects, cookies, credentials, identity changes or
retries were used. Corrected #90 classified no complete response as technical
refusal. No rate-limit/Retry-After or challenge was observed. These observations
are not a guarantee of future availability or rate permission.

Initial probes allowed five requests, 2 MiB combined bytes, 1 MiB per response,
5-second DNS, 10-second request and 15-second probe budgets, with 2-second pacing.
The 5,342,433-byte application exceeded that request budget. Its partial prefix
was retained, not treated as a complete asset. A byte-range continuation also
stopped at its deadline. Later ranges targeted the required shared client and
filled the remaining gap, using the same URL and retained representation ETag.
Before dispatch, limits were explicitly extended to seven requests/3 MiB, then
nine requests/6 MiB with 3 MiB per response, 30-second requests and 35-second probe
budgets. This was bounded static-code discovery, not fixture bulk acquisition.
Each historical ledger retains its actual limits; no failure was erased or
silently retried. The final request count was nine and received bytes 5,400,954.

The research helper reused #90's public-IP validator, pinned verified connection
and corrected refusal classifier. It preserved the exact exposed query using a
scratch request target, without changing production modules. Native bounded DNS
used existing configured resolvers. Scratch retention was checked before contact.
Each probe had a finite elapsed budget; combined request execution was bounded
by its request count and per-probe ceilings. No operational downloader, synthetic
source approval or production Store was invoked.

Exact private bytes, request/DNS ledgers, minimal representative observations,
helper and offline checker are in `.audit/issue-95-belgium-replacement-2026-10-10/`,
directory 0700/files 0600. They are not committed or redistributed. Range responses
retain the generic helper's conservative `HTTP_UNAVAILABLE` classification for
206, although the two tail ranges and middle range completed successfully.
The first two application probes retain `TimeoutError` and incomplete-body state.
The complete application reconstruction is an offline derived artifact assembled
from contiguous retained bytes with matching ETag, Last-Modified and total length,
not a fictitious single HTTP response.

| Private response | Retrieval completed UTC | Status | Bytes | SHA-256 |
| --- | --- | --- | --- | --- |
| `catchall-response.bin` | `2026-10-10T17:18:48.164317+00:00` | 200 | 759 | `397a1de28dc51e2aff3d30569390afad2f9090ffa133f2438d04518d4ea0fc88` |
| `app-response.bin` | `2026-10-10T17:19:09.852316+00:00` | 200, incomplete | 917504 | `67cd8b28d9f86383b79fd43d01f5cc1b6fcf461c234cb6c6c7d1c5c9b28c9379` |
| `app-range-response.bin` | `2026-10-10T17:19:47.590177+00:00` | 206, incomplete | 720896 | `eaa3d68c54232dae2f443ea5dd9ca6fed261ec62d0fbddc3452b2f33ca33e856` |
| `match-list-response.bin` | `2026-10-10T17:20:28.267002+00:00` | 200 | 5273 | `22e5924141b2976ae10545189f0559bed36e601f1772cb20e5cf41d26bdcfd8d` |
| `app-tail-response.bin` | `2026-10-10T17:20:54.260833+00:00` | 206 | 400000 | `4fc34a51f10dc19f02116270a63b389e7da35fd2aa86b6714e1c7d2b92cf761e` |
| `app-client-response.bin` | `2026-10-10T17:21:20.586931+00:00` | 206 | 400000 | `fe216e65f13a5e4c8f05a58469c2aeb5a89e69ab90868231d78b782aad851d3a` |
| `app-middle-response.bin` | `2026-10-10T17:21:56.326700+00:00` | 206 | 2904033 | `1f8de9002887c9f8955914e04c7dc86444b4ae26ca8af0db43f9041e8542f4f7` |
| `edition-fixtures-response.bin` | `2026-10-10T17:22:41.463231+00:00` | 200 | 52466 | `a56e9df33e66cbb709c162dc77867d8acdaaf43c9d7f47f66b11a5ed01c5c1a6` |
| `edition-terminal-response.bin` | `2026-10-10T17:23:43.726575+00:00` | 200 | 23 | `cb830ba19fc18a24d02b206a9c4021987b96c4ac3a0efebdf5f295c7387d4d19` |

Reconstructed application SHA-256 is
`dac0af2613ad32e899a1c126ca9dc08f22ba333f2d669c40222fa0b063cf07d2`.
The private `retained-digests.json` manifest has SHA-256
`081d12c2bf71ebe631e3e4938b84052904090c4cf635d4f1ac10f9377548382f`.
The derived minimal `representative-observations.json` has SHA-256
`6a8f3093f8292bb5152d971306a0e8f86b81ceec683718dc8006a50fdc3b1874`.
The manifest pins every retained artifact. Replay/checks read only those bytes. Corrupt bytes fail the integrity check; no cache refresh is attempted.

## Smallest replacement decision

Do not keep probing the same edition tabs or crawl the season to simulate proof.
The three allowed options have these consequences:

| Option | Evidence and decision |
| --- | --- |
| Explicit public Pro League export/feed | No complete-current export was linked by the inspected calendar. Delivered code also names a `football_module/football_calendar` start/end handler, but its event typology/preset, fixture schema, access and coverage contract are unqualified. It is a separate lead, not a qualified export or permission to invent parameters. This is the smallest distinct official lead if its exact preset is supplied by public material. It returns an events array and drops upstream count metadata; it is not currently a qualified fixture source. Further official work needs explicit material establishing a complete-current contract. |
| Reliable zero-cost third-party machine-readable source | Prefer one bounded Belgium-specific qualification of a documented current-window source with UTC, all required statuses, terminal/current-snapshot semantics, stable IDs and retained ancestry under ADR 0006. Existing [OpenFootAPI/Football-Data leads](live-blocker-source-research-2026-09-29.md#other-zero-cost-sources-checked) do not qualify such a source: capped/empty reviewed previews or weekly fixture data without reviewed Belgian rows and exact timezone/currentness proof. No third-party provider is selected or called here. |
| Retain manual Belgium | LF05/LF02 remain an honest temporary path. They do not satisfy the fully automated architecture or make #92 ready. No manual evidence is relabelled automatic. |

The smallest practical next decision is to allow #92's source selection to include
one qualified zero-cost third-party Belgian schedule source if no explicit official
complete-current contract can be supplied. Official branding must not impose an
indefinite gate. This is a source-selection recommendation, not a claim that a
currently unqualified third party is reliable. Existing canonical targets and F01
proof requirements remain mandatory for whichever source is qualified.

[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md) supplies the
internal owner-risk basis only. External permission/current terms remain under
the retained operator review and UNKNOWN where unproved. No new grant is asserted.
Any subsequent operational request still needs separate CURRENT
[#89 authorization](../design/research-source-authorization.md) and #90 budgets.
Default live acquisition remains disabled. No other league, #93/#94, causal
provisioning, live #86 work, fitting, F17/F18/F20, PLAY or promotion was changed.

## Checks and issue disposition

Offline checks verify original/new artifact digests and permissions, reject a
corrupt-byte control, rebuild range provenance, validate the exact calendar asset
locators and public request construction, parse sampled UTC/status fields, compare
17 source identities and seven fixtures, and verify all 18 canonical target IDs
and the unchanged manual registry digest/lineage. Documentation relative links,
anchors, tables and fences, issue dependencies/states and `git diff --check` are
checked. Link reachability for selected resources is evidenced by retained bounded
responses; uncontacted backend/export leads are labelled unverified.

#95 closes completed under outcome B once the evidence and status update are
pushed. #92 remains OPEN `needs-info` after that dependency closes; closed native
prerequisites do not provide source capability. #91/#90 remain CLOSED and #70
remains OPEN `needs-info`. The next blocker is an exact complete-current Belgian
schedule contract, including status/replacement coverage and automatic identity
persistence. No implementation readiness is inferred from the useful JSON sample.

# Pro League raw calendar qualification

Research date: 2026-10-10. Belgium-only continuation of
[#91](https://github.com/Awisalas/match-vet/issues/91), for
[#92](https://github.com/Awisalas/match-vet/issues/92).
The [initial review](pro-league-source-contract-2026-10-10.md) retains the
seven-league table; no other league was researched in this continuation.

## Decision

**B: TECHNICALLY INSUFFICIENT for the exact initial calendar representation.**
The ordinary public response from the
[official calendar](https://www.proleague.be/jpl-kalender!) contains structured fixture data,
including exact UTC timestamps and ordered team objects. It contains fixtures
only for matchday 8. Its catalogue of 34 matchdays contains no fixtures for the
other partitions and no complete current date-window protocol. This response
cannot supply #92's general requested-window coverage, including fixtures moved
into that window from other matchdays.

This is a demonstrated limit of the inspected response, not a claim that every
Pro League representation lacks the required capability. No further origin
request was made after inspection. #91's alternative close criterion is met by
this specific missing capability and the replacement decision below. #92 remains
OPEN `needs-info`; closing its dependencies does not qualify the missing source.

## Exact response and retention

The publisher/operator remains Pro League NV, as identified in the retained
[operator review](pro-league-source-contract-2026-10-10.md#exact-candidate-and-known-publication-facts).
External fixture-data permission and exact current upstream ancestry remain
UNKNOWN. [ADR 0006](../adr/0006-research-only-public-source-automation-risk.md)
records internal risk acceptance, not a grant or operational authorization.

| Capture fact | Exact retained value |
| --- | --- |
| Requested / final validated URL | `https://www.proleague.be/jpl-kalender!` |
| Request started UTC | `2026-10-10T15:12:46.841655+00:00` |
| Headers received UTC | `2026-10-10T15:12:48.394897+00:00` |
| Retrieval completed UTC | `2026-10-10T15:12:49.042098+00:00` |
| Status / content type | `200`; `text/html; charset=utf-8` |
| Complete body bytes | `253848` |
| Body SHA-256 | `9813e53c40d2228195078dcac501b52f58a26b86d5da3e1a777212428dc2ccf3` |
| Redirect chain / retries | Empty / zero |
| HTTP dispatch attempts | One, without credentials, cookies or browser execution |
| Public pinned address | `150.171.109.84`; verified HTTPS for `www.proleague.be` |
| Server Date | `Sat, 10 Oct 2026 15:12:48 GMT` |
| ETag / Cache-Control | `"8xlbhsqtjf5fui"`; `public, max-age=300` |
| Elapsed probe time | `3.356812` seconds, including import and DNS |

The probe allowed one request, 1 MiB total body bytes, five-second DNS resolution,
ten-second request timeout, fifteen-second total budget, two-second pacing,
zero redirects/retries and zero backoff. It reused #90's public-IP validator,
pinned verified HTTPS transport and refusal classifier. It did not invoke an
operational downloader, instantiate a Store or provision synthetic source authority.

Scratch write/read and durable ledger writes were checked before contact.
Python's resolver then timed out before HTTP. That failure was retained with
zero dispatch attempts. A bounded native `drill` A lookup using the existing
configured resolvers succeeded; its returned address was validated before the
single HTTPS request. This changed the local DNS mechanism, not the source URL,
identity or route after a source refusal. No production transport code changed.

Private exact bytes and ledgers are retained locally in
`.audit/issue-91-belgium-raw-2026-10-10/`, with directory mode 0700 and files 0600.
They are not included in the Git commit or redistributed as a runtime fixture.
`retained-digests.json` records the exact artifacts. The successful probe ledger
SHA-256 is `1e5c0557ea06531e4db1f532f7996107479fde18de66aebee8ffd17159346ce8`.
The minimum derived representative observations have SHA-256
`71558a3a3b6e39aacce97761d7ad7443f643ade7060ffe28dede01970117f8fc`.
They retain three fixture fragments and the 18 identity observations, not a
season archive or an approved automatic mapping.

## Structured representation

The HTML explicitly delivers `script#__NEXT_DATA__[type="application/json"]`.
No endpoint guess or JavaScript execution is needed to read it. JSON-LD contains
`SportsTeam` and `WebSite` metadata, not a fixture schedule.

Define `M` as the exact JSON pointer
`/props/pageProps/data/page/grids/0/areas/0/modules/0`.
The module type is `football_list`, subtype `football_competition_match`.
Page/list metadata declares `accessControl.status=public` and
`exclusiveContent=false`. This supports public delivery of this response, not
permission to call a different backend.

| Field / pointer relative to M | Observed semantics |
| --- | --- |
| `/data/matches/*/id` | Nine distinct fixture UUIDs; persistence across future revisions unproven |
| `/data/matches/*/homeTeam`, `/awayTeam` | Explicit ordered objects with UUID `id`, exact `name`, display abbreviation and `slug` |
| `/data/matches/*/competition/id` | `18d6fee0-d3bb-4624-b4d2-ac5b16ab498c`, Jupiler Pro League |
| `/data/matches/*/season/id` | `bd52b2d5-437b-46de-a088-1678e062fff1`, season 2026/2027 |
| `/data/editionId` | `6582729e-c371-4573-8d59-50674807d96c`; all sample fixture editions agree |
| `/data/roundId` | `c36a5f14-de03-4ec9-93fe-07e9065a8b57`, regular season |
| `/data/gameweek/id` | `1884acf3-b5e8-456e-875d-994dbe84e918`, week 8; all nine fixtures agree |
| `/data/matches/*/time` | ISO-8601 timestamps with explicit `Z`; exact UTC basis supplied |
| `/data/matches/*/date` | Date string alongside the instant; must not replace `time` or imply DATE-only precision |
| `/data/matches/*/period/type` | Observed `FullTime`, `SecondHalf`, `PreMatch`; full status vocabulary unqualified |
| `/data/gameweeks`, `/data/rounds` | Matchday catalogue, not fixture membership for other matchdays |

One exact representative fixture has ID
`0bd9e335-ca2c-4a2f-b587-3e17f25fb35e`, home SK Beveren, away Lommel SK,
`time=2026-10-09T18:45:00Z`, and `period.type=FullTime`.
All nine sample timestamps explicitly use UTC. The independently delivered
`/props/pageProps/settings/general/date/timeZone` is `Europe/Brussels`.
Conversion therefore uses the supplied UTC instant; the site timezone is a
source configuration fact, not an assumption based on Belgium's geography.
It does not establish semantics for an uninspected replacement feed.

`/props/runtimeConfig/apiBaseUrl` identifies a cross-origin Maker service under
`apim-maker.llt-services.com`, not a same-origin public fixture endpoint.
Its access mode, schema and authorization requirements are UNKNOWN. It was not
contacted. A public base URL in configuration does not qualify its endpoints.
Same-origin JavaScript assets are explicitly linked, but no exact public
same-origin structured fixture endpoint or export is exposed in the retained
HTML/JSON. No asset was fetched to discover or guess backend calls.

## Partition, exhaustion and affirmative empty

The delivered match list has nine distinct fixture IDs, 18 distinct team IDs,
and exactly one selected gameweek. The catalogue has 34 distinct gameweek IDs,
with previous/current/next entries. Those entries do not include the remaining
fixtures, their changed dates or a protocol selecting all partitions relevant
to a requested half-open UTC window. The page route query contains only
`params=["jpl-kalender!"]`; no requested UTC bounds were supplied or acknowledged.

There is no source total, pagination/terminal assertion, covered-bound assertion
or complete-response declaration in this module. Its empty-state configuration
has null display messages and buttons, not an affirmative no-fixtures declaration.
The known 18-club format makes nine pairings a useful consistency check. It does
not establish exhaustion or absence of omitted/cancelled/moved fixtures.

[F01](../../src/matchvet/fixture_coverage.py) does not mandate a native pagination
counter or a particular field name. A genuine versioned complete-response contract
could establish enumeration and empty semantics. None is supplied by this
inspected representation. Recasting a catalogue as 34 fetched partitions would
fabricate accounted coverage. F06's seven-scope requirement is unchanged.

## Revision and currentness

Structured fixture IDs and UTC values would permit comparison if later
authoritative snapshots preserve the identity. This one response does not prove
that preservation, omission/replacement rules, moved-in/moved-out enumeration,
postponed/cancelled status meanings or complete correction coverage.

The page/list `publishedAt` is `2023-06-22T11:07:45Z`. It is not an as-of time for
2026 fixtures. Server Date and retrieval time establish serving/retrieval facts;
the ETag identifies the HTML representation. Cache-Control describes HTTP caching.
None of them is a fixture publication/update timestamp or proves the currentness
of every fixture. The Next.js build ID identifies application output, not fixture
revision authority. Fixture publication/update time remains UNKNOWN.

The existing official update articles retain evidence that scheduling changes
occur. They do not supply the missing complete revision stream. A native revision
timestamp is not itself mandatory: a proved complete current snapshot contract
plus stable identities could suffice. That contract remains unqualified here.

## Identity observations

The structured UUIDs below replace speculation about numeric slug suffixes.
They are unique within this capture and identify the exact home/away objects.
Their lifetime stability, upstream namespace and cross-representation identity
contract remain UNKNOWN. `competition.source=client` is a source field value;
it does not identify an independent upstream publisher.

These are reviewed target observations, not a new automatic mapping revision.
Canonical targets come from the existing
[registry and audit](pro-league-source-contract-2026-10-10.md#identity-mapping).
The LF05 digest remains
`sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`.
Its manual-only lineage was not reused as automatic authority. No teams were
created, and an ambiguous or missing target still fails closed as UNKNOWN.

| Exact structured source name | Source UUID | Existing canonical target |
| --- | --- | --- |
| Cercle Brugge | `4c804f0f-414d-4c53-8b84-b2bbb9cc9b1a` | Cercle Brugge |
| Club Brugge | `5fc3087b-6962-4d05-815a-8ef2f3f0d26a` | Club Brugge |
| KAA Gent | `eba93b1d-898c-45af-a409-6337ea9bdd0d` | Gent |
| KRC Genk | `e79bacb9-c33a-44ac-a450-f18396b6b4ff` | Genk |
| KV Kortrijk | `16b7d834-4446-4a79-8fb6-d73c65ea6504` | Kortrijk |
| KV Mechelen | `afe133f7-22d8-4d0f-ace3-7bbd4d0f7ba5` | Mechelen |
| KVC Westerlo | `fb0037bb-e6f4-474f-8fb2-ab873e7df147` | Westerlo |
| Lommel SK | `09120bf9-6534-459f-b32a-615c6c366e7d` | Lommel SK |
| OH Leuven | `0623a7ea-b0ab-4f8e-81d1-d0c8c4321205` | Oud-Heverlee Leuven |
| RAAL La Louvière | `3dcdb287-a7ca-400f-b697-c1f9161864e8` | RAAL La Louviere |
| RSC Anderlecht | `236c1af7-96bd-4e21-ae91-dd641556cc24` | Anderlecht |
| Royal Antwerp FC | `ab0c5675-38b2-4b78-8f47-c48cc209d205` | Antwerp |
| Royale Union Saint-Gilloise | `0a440e2a-ef6c-48df-9ac8-428c6902fd7a` | St. Gilloise |
| SK Beveren | `2b991075-4bde-4641-8c4f-3dd6e10ebbf3` | Beveren |
| Sporting Charleroi | `304d6c29-ca06-46c1-805e-ef07a1005ad6` | Charleroi |
| Standard de Liège | `13ceba74-ed6b-4027-bfcc-c8e45337ef98` | Standard |
| STVV | `1a0d789b-c8f3-47e1-84f4-55f89fa52760` | St Truiden |
| SV Zulte Waregem | `2fc41f83-c2fd-4bfd-a39f-1c5566e06ee0` | Waregem |

The private observation record binds all 18 exact source UUID/name/slug tuples
to the already recorded canonical UUID targets and this capture digest.
It supplies no approved automatic-source mapping digest. A later mapping must
bind a proved source namespace, scope, stability contract and reviewed evidence.

## Refusal classification

The unchanged #90 body classifier returns `TECHNICAL_REFUSAL` because the HTML
contains a hidden `g-recaptcha` element and public reCAPTCHA site configuration.
The retained page also contains the calendar and its fixture payload. This
observation does not prove that a CAPTCHA challenge or WAF refusal was presented.
No challenge was solved, and no account/IP/header identity was changed.

The classifier result is retained exactly. It stopped further live inspection;
it was not overridden to enable a second request. This is also a current
operational transport compatibility gap. Any future classifier review belongs
in separate transport work and must preserve real refusal handling. This ticket
changes no #90 code, policy or authorization behavior.

## Smallest replacement decision and issue disposition

Replace the unparameterized default-matchday response as the proposed completeness
source. The next representation to qualify is a **Pro League-published public
competition/edition fixture payload or supported export** with an explicitly
selected matchday or date window, complete partition membership, cross-round
rescheduling/replacement behavior and authoritative current-snapshot semantics.
Require exact UTC and source-scoped stable IDs at that same boundary. Its exact
public locator remains UNKNOWN until officially exposed or documented. Do not
guess a Maker API path or derive a Next.js data URL from a build ID.

The already linked official match detail and team fixture pages can corroborate
one object's schema/identity. They are not a competition-window replacement;
do not crawl 18 teams or 34 rounds to manufacture exhaustion. No unofficial
aggregator, paid feed or new provider is selected by this decision.

#91 closes under criterion B for this exact representation and replacement
decision. #92 stays OPEN `needs-info`, without `ready-for-agent`, until a replacement
contract is qualified. Closed native dependencies do not waive that requirement.
The six other league findings remain untouched. No adapter, authority, production
Store, provider activation or live acquisition capability was added.

## Checks

Offline checks verify retained artifact bytes/digests and locator/timing/budget
metadata, embedded JSON extraction, nine unique fixtures, 34 unique catalogue
entries, UTC offsets, 18 unique identity/target observations and the unchanged
LF05 digest. Document links, table/fence structure, issue states/native dependencies
and `git diff --check` are checked before delivery. Origin currentness is evidenced
only for the exact retained response above; older publication links were not
refetched after the refusal classification. No runtime test suite was needed for
these research/status-only changes.

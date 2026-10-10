# Football Charts free Belgian fixture contract

Research date: 2026-10-10. Belgium-only
[#97](https://github.com/Awisalas/match-vet/issues/97), for
[#92](https://github.com/Awisalas/match-vet/issues/92). This follows the retained
[#95 replacement-source](pro-league-replacement-fixture-source-2026-10-10.md) and
[#96 date-window](pro-league-date-window-calendar-qualification-2026-10-10.md)
qualification results and the earlier
[upcoming-fixture audit](upcoming-fixture-coverage-source-audit-2026-09-27.md).

## Decision before fixture contact

**B: DOCUMENTATION ALREADY INSUFFICIENT.** The inspected primary material does
not establish a complete-current real-world Belgian Matchweek contract.
The advertised short upcoming horizon has no exact coverage bounds. No source
statement binds every fixture in a Friday–Tuesday window to the returned set,
including postponed or moved fixtures. The required alternative of a documented
complete-current snapshot is also absent. Two example responses could establish
rows and schema; they could not repair these missing coverage assertions.

No fixture, result, team, match-detail or league-index data API was requested.
The API root was inspected only as the developers page's explicitly linked
self-description. No credential was requested, extracted or reused. No odds or
history acquisition occurred. #97 closes completed under B; #92 remains OPEN
`needs-info`. No automatic mapping, adapter or operational source authority is
approved. Default live acquisition remains disabled.

This result does not depend on extending paid-product warranty terms to free
access. Free-tier disclaimer applicability remains UNKNOWN, as explained below.
Nor does it claim a proved numerical truncation or that every possible Belgian
record is absent. It records that the exact F01 contract is unproved.

## Current primary evidence

The [developers page](https://www.football-charts.com/developers) advertises
keyless REST, 300 requests/day/IP, and identical data with a free key at a larger
quota. Free access covers all listed leagues and each league's current/previous
season. It describes daily overnight refresh around 06:00 UTC and fixtures
"a few days ahead". That phrase supplies no minimum horizon. Its fixture endpoint
has no documented date bounds, season or pagination parameters. Attribution,
research/personal use and no resale are explicit. No free result-size limit or
preview-only tier is stated; full real-world membership is not promised either.

The [Belgian competition page](https://www.football-charts.com/leagues/belgium/jupiler-pro-league)
labels Jupiler Pro League 2026-2027. Its
[season table](https://www.football-charts.com/rankings/belgium/jupiler-pro-league/2026-2027/classic)
lists 18 teams. This corroborates advertised competition/season coverage, not an
exact API league key, complete schedule partition, free fixture entitlement
response, or source-ID mapping. The hub's projection update and future-schedule
counts concern the model and cannot supply a schedule snapshot contract.

The explicitly linked [API self-description](https://footballcharts-backend.onrender.com/api/v1/)
identifies developer API version 1. It describes keyless 300/day, 20/minute;
free current/previous seasons per league; and all leagues. It lists GET
`/api/v1/leagues/{league}/fixtures/` without window, season or page parameters.
Every data answer is described as carrying `source_url` to the corresponding
Football Charts page. That is publisher-page provenance, not identified upstream
fixture authority or coverage certification. The root supplies no fixture
revision, exhaustive membership, empty-window or timezone contract.

### Pinned publisher code

The public MCP repository was read at commit
[`f3291dd2d7ecb185f756221298e35c7016173a43`](https://github.com/ddevetak/footballcharts-mcp/tree/f3291dd2d7ecb185f756221298e35c7016173a43).
Pinned current contents and current publisher documentation control this
assessment; no older README is used as the current contract.

[`src/tools.js`](https://github.com/ddevetak/footballcharts-mcp/blob/f3291dd2d7ecb185f756221298e35c7016173a43/src/tools.js)
defines `get_fixtures` with only `league`; its GET has no additional selectors.
The fixture shape names `slug`, `home_team`, `away_team`, `match_date`, `time`,
`status`. Schemas are permissive and do not enumerate all API fields. This is
schema documentation, not observed fixture bytes or UTC/stability proof.
`get_match` removes storage fields including creation/update times and upstream
fixture/team IDs. Those names suggest integrations, without proving their
actual Belgian lineage or persistence. Model `computed_at`/`data_through` describe
model computation. They are not schedule publication times. Its orientation text
mentions updates after full time and a few times a day before matches, which differs
from the developers page's overnight cadence. Neither establishes guaranteed
current schedule coverage.

[`src/fc.js`](https://github.com/ddevetak/footballcharts-mcp/blob/f3291dd2d7ecb185f756221298e35c7016173a43/src/fc.js)
constructs GET requests against the published REST base. Keyless requests omit
Authorization. It documents `season_gated` for seasons outside the free window.
No response pagination loop or complete-window verification is present.
The [publisher's REST guide](https://github.com/ddevetak/footballcharts-mcp/blob/f3291dd2d7ecb185f756221298e35c7016173a43/skills/football-data/SKILL.md)
also lists fixtures without date-window selectors. These public client
observations do not prove undocumented backend behavior. No client was installed
or executed against the API.

## F01 qualification matrix

The unchanged [F01 schedule contract](../../src/matchvet/fixture_coverage.py) requires proof of
the requested real-world scope. Returned rows, exhausted known records and
successful HTTP transport do not establish it.

| Requirement | Verdict for the inspected free contract |
| --- | --- |
| Competition/season | Belgian 2026-2027 advertised; exact API key/fixture selector binding UNKNOWN |
| Full Friday–Tuesday membership | UNKNOWN; no minimum horizon or all-status window coverage statement |
| Explicit window bounds | Undocumented; no inclusive/exclusive semantics |
| Pagination/exhaustion | Undocumented; no terminal/full-result scope proof |
| Affirmative empty | UNKNOWN; no complete covered-window declaration |
| Fixtures moved into/out of window | UNKNOWN; no current-date inclusion or removal/replacement contract |
| Current authoritative snapshot or revisions | UNKNOWN; refresh cadence alone is insufficient |
| Stable fixture/team identities | UNKNOWN; documented slug/names do not prove persistence or source namespace |
| Ordered home/away | Documented field names; no retained fixture response |
| Kickoff UTC/offset | UNKNOWN; date/time field names and ISO dates alone supply no timezone basis |
| Status vocabulary | Match detail documents `scheduled`/`ft`; fixture status is otherwise generic, with postponed/cancelled/rescheduled behavior unproved |

The missing requirements remain UNKNOWN. No empty set becomes CONFIRMED_EMPTY,
no missing fixture becomes ABSENT, and no retrieval time, HTTP Date, cache header
or model timestamp becomes fixture publication time. This research neither
weakens completeness nor changes the source-authorization semantics governed by
[ADR 0006](../adr/0006-research-only-public-source-automation-risk.md).

## Terms applicable to free access

[Terms of Sale](https://www.football-charts.com/terms), updated 27 September 2026,
identify Damir Devetak, sole proprietor in Serbia, and expressly scope the terms
to paid products/paid API. They separately say the free API remains free.
Paid terms license internal uses and prohibit raw/substantial redistribution;
they disclaim completeness. Applying those paid clauses to free data without an
additional basis would overstate the evidence. The general public-report/provider
compilation description does not establish exact Belgian fixture ancestry.

The current [MCP README terms and licence](https://github.com/ddevetak/footballcharts-mcp/blob/f3291dd2d7ecb185f756221298e35c7016173a43/README.md)
permit free personal/research use with attribution and forbid resale. MIT covers
server code only; served data remains separately governed. Neither statement is
an upstream clearance claim.

| Free-tier operation | Exact assessment |
| --- | --- |
| Access | Explicit free/keyless invitation; no authority provisioned |
| Attribution | Required, `Data by football-charts.com` |
| Internal RESEARCH_ONLY use | Research use explicitly invited |
| Raw response retention | Duration/survival permissions not explicit; UNKNOWN |
| Normalized retention | Exact retained fact/identity operations not explicit; UNKNOWN |
| Private backup/restore/replay | Not explicitly addressed; UNKNOWN |
| Derived statistical use | Research invitation supports purpose; separate enduring derived-use grant UNKNOWN |
| Redistribution | Resale forbidden for free data; wider publication/redistribution scope UNKNOWN |
| Availability/completeness disclaimer | Paid clause exists; free applicability UNKNOWN |

Under ADR 0006, owner risk acceptance can address legal uncertainty. It cannot
supply missing technical scope or currentness. This task supplies no owner risk
authorization and no external contact.

## Identity mapping and next decision

The [retained official identity observations](pro-league-calendar-raw-qualification-2026-10-10.md#identity-observations)
remain the baseline for all 18 existing Belgian canonical teams. Football Charts'
18 display names do not establish persistent IDs or an automatic namespace.
No all-18 automatic mapping revision or digest can be approved from this evidence.
The existing LF05 manual registry retains its lineage and digest
`sha256:af6349f30e0565f92fb2af4fde34b1c1707acf6121003b230b901e580b2de213`.
Offline checks confirm all 18 existing targets remain distinct and consistent.
No team is created and no fuzzy fallback is proposed.

The smallest next source decision is to require a concrete complete-current
Belgian schedule contract from a publisher/provider before more fixture probes.
It must state full selected-window membership, status/moved-fixture treatment,
empty semantics, identities and exact kickoff conversion. A provider clarification
is an option for a separately authorized task, not outreach performed here.
Do not retry OpenFootAPI/API-Football under unchanged primary terms. Further
Pro League official probing already stopped at #96.

Recommend a contract-first source decision in #92, with no more row probes
until a publisher can establish those exact capabilities. Keep manual Belgium
as the existing temporary path while this decision is unresolved. It does not
satisfy the fully automated architecture. No reviewed free Belgian source is
qualified; changing the zero-cost requirement would require a separate product
decision and is not selected here. #92 remains blocked on the exact source contract.
Closing #97 removes its open native dependency, not that substantive readiness gate.

## Inspection and checks

This was documentation-only research: current primary developer/terms/Belgium
pages, the explicitly linked API root self-description, and pinned publisher
repository contents. No fixture probe was justified or made. Documentation-reader
observations are not byte-perfect HTTP captures; no exact response status, bytes,
redirect chain or retrieval timestamp is invented for them. A fixture probe
ledger therefore has zero requests and zero fixture bytes.

Private documentation artifacts are in
`.audit/issue-97-football-charts-2026-10-10/`, directory 0700/files 0600.
Four pinned repository files retain 42,604 decoded bytes, exact locators,
request/completion UTC times, SHA-256 and Git blob identities. The public
repository contents API did not expose raw HTTP status/redirect history to the
retention method; neither is invented. These are documentation/code files,
not fixture captures. The parsed primary-page observations likewise retain
review locators and explicit unknown transport metadata.

The observation file has SHA-256
`6b4f00b0fbaf7fa44be175e05be8d16982bf38c764befbc80ac679456a26d8a9`.
The retained-file manifest has SHA-256
`1ec4f62704f46d5e6bc5c01f0fd539d24d92baccc61230ccc1afcd0e6108f429`.
Offline checks reject altered bytes and confirm the pinned code locators,
fixture selectors/status schema, zero fixture requests/bytes, paid/free scope
distinction, protected modes and all 18 unchanged canonical targets/manual
registry digest. No raw documentation is published as reusable source data.

Primary-source freshness/links, issue dependency/state consistency,
documentation relative links/anchors/tables/fences and `git diff --check` pass.
No production module, schema, format, source policy or contract was changed.
#97 closes completed under B after delivery; #92 stays OPEN `needs-info` even
when every native dependency is closed. Its remaining source-contract gate is
explicit in the issue body. #90/#91/#95/#96 remain CLOSED; #70 OPEN `needs-info`.
No new issue, source/causal authority, live acquisition or provider activation
was created. No other league, #93/#94, #86 collection, fitting, F17/F18/F20,
PLAY or Product Promotion was worked.

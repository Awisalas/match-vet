# Issue 79 grounding

Grounded against main `50dd61b` on 2026-10-08. This record reads repository source,
documents, git history and GitHub issues only. It does not open a SQLite store,
acquire fixtures, invoke production writer APIs, or send a timestamp request.

## Overview

MatchweekResearchRepository is the deep owner of prospective admission,
selection, completion authority and selected replay. F11–F16 call its shared
candidate gates. Store owns atomic catalog assignment and private operation
lifetime. ArtifactStore owns content verification, durable object files and
reserved-role publication. This separation is the right starting point for a
causal witness. A remote witness belongs after Store's confirmed fresh commit,
inside the same owner-controlled live operation. It cannot be supplied as a new
TrustedUTCClock implementation.

The founder boundary comes from a complete all-seven-scope Friday–Monday F06
freeze. Corrected F07 derives common T from the earliest exact INCLUDED kickoff
minus explicit 21600 seconds. F06 creation is metadata. ADR 0001 requires all
F11/F13/F14/F16 research and decisions to finish before T. ADR 0002 accepts the
impossibility of an actual-at-function-return bound under arbitrary suspension
and explicitly leaves causal-event adoption to a separately authorized design.
The present user request provides that design authorization; no production
implementation is authorized.

Sources: `docs/adr/0001-matchweek-wide-evidence-cutoff.md`,
`docs/adr/0002-production-trusted-utc.md`, `GLOSSARY.md`,
[issue 79](https://github.com/Awisalas/match-vet/issues/79).

## Existing runtime chain

1. F15 start/resume validates exact F06/F07/profile/policy/run identity and calls
   `require_candidate_contract` before coordinating a missing phase. Once selected,
   it returns inspection of the already retained exact run.
   `src/matchvet/f15.py:120`, `src/matchvet/f15.py:175`.
2. F16 phases call the shared contract and artifact gates. Evidence acquisition
   delegates to F11; frozen-evidence phase delegates to F13; preference vetting
   constructs F14 results, per-match F16 children and the whole-slate F16 manifest.
   `src/matchvet/f16.py:168`, `src/matchvet/f16.py:178`,
   `src/matchvet/f16.py:442`.
3. F11 acquires responses through `_AcquisitionClient` with guards surrounding
   acquisition. It retains exact response, request, history, contextual-attempt
   and evidence artifacts. Its final evidence bytes are validated before
   `publish_artifact`. Selected replay names the F16-selected evidence digest and
   rejects changed request bytes, location or rules.
   `src/matchvet/f11.py:186`, `src/matchvet/f11.py:295`,
   `src/matchvet/f11.py:398`, `src/matchvet/f11.py:550`.
4. F12 preserves response/attempt/health provenance. A selected attempt must be an
   exact selected reference and match selected F11 acquisition bytes. First-attempt
   and exact-request conflicts refuse. `src/matchvet/f12.py:237`,
   `src/matchvet/f12.py:279`, `src/matchvet/f12.py:410`.
5. F13 binds evidence to exact cutoff/membership/revision. It serializes retained
   history and calibration into immutable inputs, evaluates them, then publishes
   model result bytes. First-result conflict guards remain separate from timing.
   Selected replay chooses the model named by F16, rather than discovering later
   mutable history. `src/matchvet/f13.py:178`, `src/matchvet/f13.py:293`,
   `src/matchvet/f13.py:352`, `src/matchvet/f13.py:813`.
6. F14 binds profile, F11, cutoff, model and policy. It rejects changed partial
   Matchweek contracts and repeated conflicting inputs. It publishes canonical
   input/result bytes only after evaluation. Replay recomputes the deterministic
   result from retained inputs and checks exact bytes.
   `src/matchvet/f14.py:352`, `src/matchvet/f14.py:401`,
   `src/matchvet/f14.py:454`.
7. F16's manifest names every included membership's exact evidence, model,
   decision and child result. The child publication follows computation; final
   F16 publication follows all children. Its reader validates F06/F07 and child
   lineage. `src/matchvet/f16.py:317`, `src/matchvet/f16.py:442`.
8. `_admit` replays that whole graph while capturing every verified artifact digest.
   It requires corrected policy, one common T, complete cutoff coverage and one
   F11 digest, then builds the exact protected selection closure.
   `src/matchvet/matchweek_research.py:159`.
9. `seal_completed` checks the stable logical slot. Existing winners replay; alternate
   proposals refuse. For a fresh proposal it opens private Store authority,
   publishes/synchronizes selection and graph, atomically commits selection, then
   observes a trusted local bound and acknowledges it before one receipt attempt.
   `src/matchvet/matchweek_research.py:257`.
10. Replay reconstructs exact expected selection and receipt, requires indexed
    canonical role slots and strict receipt bound before T, and returns only this
    selected state. Missing indexed receipt is permanent refusal.
    `src/matchvet/matchweek_research.py:552`.

## Where authority and durability live

`src/matchvet/store.py:4362` uses `BEGIN IMMEDIATE`, commit on success and rollback
on exception. `_research_operation` requires fresh WAL/FULL, no nested operation,
and invalidates authority on scope exit. `_ResearchOperation` restricts Store,
PID and thread lifetime, disallows copying/serialization, consumes role authority
before publication, and checks an exact fresh protected insertion.
`src/matchvet/store.py:4377`, `src/matchvet/store.py:4660`.

`ArtifactStore._publish_research_manifest` consumes the private role attempt.
`_publish_manifest` refuses idempotent reserved assignments, stages/verifies exact
bytes, synchronizes selection and every graph object and containing directory,
then inserts the protected snapshot in a bounded transaction. `_committed` runs
only after transaction return and fresh insertion. `src/matchvet/artifacts.py:615`,
`src/matchvet/artifacts.py:662`, `src/matchvet/artifacts.py:705`,
`src/matchvet/artifacts.py:781`, `src/matchvet/artifacts.py:928`.

The same operation may acknowledge only phase `selection_committed`. v1 receipt
binding requires exactly one artifact digest, the selection digest, and
`created_at_utc` equal to the bound. It cannot retain a confidence/witness closure
without a new exact private binding and domain version.
`src/matchvet/store.py:4698`, `src/matchvet/store.py:4759`,
`src/matchvet/store.py:4771`.

Ordinary ArtifactStore publication and structured StoreTransaction insertion guard
reserved slots before generic idempotent publication. Raw SQL/private repository
code remain trusted. `src/matchvet/artifacts.py:599`,
`src/matchvet/store.py:4894`.

Logical identity uses season and canonical Friday. Selection/completion slots are
stable UUIDs derived from that identity and do not vary with policy/profile/reader
version. Preserve those exact uniqueness keys for a successor protocol.
`src/matchvet/research_identity.py:6`.

## Every affected writer gate

| Existing boundary | Current authority | Required causal-successor treatment |
| --- | --- | --- |
| Shared `require_preselection_open` | No occupied slot; exact corrected policy, common cutoff, candidate identity; trusted bound before and after identity checks | Keep slot/identity/complete-boundary checks; remove local time as qualification authority only in explicitly versioned prospective mode |
| `candidate_artifacts` guard | Rechecks slot, trusted time, candidate/contract identity, first-result state before/after publication | Keep repeated immutable-state checks; candidate artifacts remain unqualified pending final witness |
| F11 direct and retained-request entry | Shared gate before catalog discovery or work; one request and selected replay | Preserve all request/lineage conflict checks; permit no change to selected closure |
| F11 acquisition wrapper | Guards actual weather retrieval before/after fetch | Successor causal ordering must require response collection before immutable F11 result; advisory deadline can stop waste but cannot qualify |
| Weather health recorder | `health_clock` returns gate timestamp used as F09 checked time; second clock call before persistence | Split metadata timestamp from gate result explicitly; a local string must not be relabeled trusted UTC |
| F12 direct publish | Shared gate plus acquisition/retrieval timestamp checks; first attempt | Preserve provenance consistency; early timestamp never admits late acquisition; only selected closure and causal witness establish cutoff qualification |
| F13 direct build/discovery | Shared gate plus first-model guard; immutable history and calibration | Preserve exact selected inputs, chronology and same-Matchweek outcome exclusion; computation must finish before model artifact admitted into witnessed graph |
| F14 direct build/replay | Shared contract/first-input/first-result guards | Preserve unique input/model/profile/policy and deterministic replay; no new decision joins occupied slot |
| F15 start/resume | Shared contract before missing phases; selected run inspection | Missing work remains unqualified; no restart can regain witness authority from persisted selection |
| F16 every writer phase | Shared contract/artifact gates; full members and exact F11/F13/F14 | Complete immutable graph before selection; selected output or occupied unqualified slot never allows alternate construction to replace it |
| Selection before/after commit | Trusted precommit and postcommit return bounds | Replace qualification with post-fresh-commit request and verified remote event U < T; local prechecks are advisory |
| Receipt persistence | Exact same-operation one-use capability; may complete after T | Extend exact private binding to witness/provenance closure, preserve one attempt and read-only ambiguous-return recovery |

Exact locations for shared gates: `src/matchvet/matchweek_research.py:312`,
`:450`, `:504`. Artifact guards execute before staging, before/in catalog
transaction and after commit return, `src/matchvet/artifacts.py:542`.
Weather timestamp coupling is `src/matchvet/weather_provider_health.py:135`,
`:313`; F12 time comparison is `src/matchvet/f12.py:269`.

The causal design changes the historical statement that no unselected candidate
work can execute after real T. Under unrestricted suspension and advisory local
time, that statement cannot be enforced as a hard local fact. The founder invariant
still holds if late work can never qualify and can never alter an occupied selected
graph. State this prospective change openly; keep v1 enforcement/tests intact.

## Causal proof and its premises

For each selected artifact A, trusted repository execution must establish its
actual acquisition/computation before immutable byte publication, and publication
before exact complete graph verification and fresh durable selection commit C.
Only after confirmed C may the live owner generate fresh unpredictable request
binding B to selection digest, logical Matchweek, cutoff/policy, supported protocol
and graph identity. A qualified honest remote authority processes B at event E
and authenticates an upper endpoint U with E <= U < T. Then acquisition/computation
< A <= C < request <= E <= U < T. Suspension after E or during delivery changes
neither the causal relation nor selected bytes. Suspension before request can
only move E later and cause refusal when U >= T.

Remote cryptography alone proves a digest commitment existed by E. It does not
prove F11 was actually collected, F13/F14 actually computed, or SQLite committed.
Those conclusions depend on trusted local code/kernel/process, integrity of
artifact bytes and graph validation, fresh commit acknowledgement, collision and
preimage resistance, durable WAL/FULL/fsync/VFS/locking, and one authoritative
catalog history. Artifact strings carrying early timestamps provide none of
those execution premises. A malicious local operator can precompute a digest,
forge collection metadata or directly edit private persistence; this task does
not add remote execution attestation.

All selected artifacts exist before C. The protected selection closure and scoped
catalog replay forbid a post-witness artifact entering the selected graph.
`src/matchvet/matchweek_research.py:175`, `:201`, `:478`,
`src/matchvet/store.py:4339`, `:4397`.

## CB01 is a different witness

Corrected CB01 preparation first requires the exact qualified selected F16/common
T. Its retained RFC3161 request/response bind the batch digest and nonce, verify
pinned algorithms/policy/chain and signer validity at signed genTime, and enforce
strict T < genTime < that fixture's controlling kickoff.
`src/matchvet/cb01_sources.py:105`, `src/matchvet/cb01_trust.py:738`,
`:750`, `:828`, `:844`.

CB01 retains parsed accuracy as evidence but its existing time-window comparison
uses genTime directly. That implementation is not a production UTC hard-upper-bound
verifier. Reusing its transport/parsers requires an independently versioned
selection-witness accuracy/trust profile, not reuse of its acceptance semantics.
Keep CB01's post-T enrollment role and existing acceptance unchanged.

Historical CB01 software identity hashes `cb01.py` bytes. Changing that module or
trust module can invalidate reconstructed historical commitments. Prefer a
separate new witness verifier/owner adapter; prove dispatch if modifying historical
core becomes necessary. `src/matchvet/cb01_sources.py:727`.

## Compatibility and storage facts

Generic SnapshotManifest schema is 1, accepts a set of artifact references and
version identities, and requires exact catalog reconstruction. The SQL snapshot
index has UNIQUE(snapshot_id), with artifact/reference/version tables. Existing
generic shape can represent a new protocol's witness, request, response, trust
profile and verification provenance as protected content-addressed artifacts.
`src/matchvet/artifacts.py:30`, `:188`, `:823`,
`src/matchvet/store.py:356`.

This source-level sufficiency is not a completed new-protocol storage proof.
Successor implementation must run isolated exact-reader/private-binding tests.
No schema migration is justified by source inspection. Domain completion v2 must
retain exact evidence references, supported version and upper-bound meaning;
v1 bytes/readers/created-time meaning remain unchanged. An occupied v1 selection
can never be upgraded or reopened as v2.

## Historical rationale and proof limits

- `5c8d56aceb255aec7f5592da85ac069142261efa` implements #75's fresh postcommit local
  acknowledgement, one-use receipt, protected slots and graph durability. Its
  comments explicitly say deterministic clocks establish behavior while production
  UTC confidence remains unavailable.
- `53bb02c6d60897ebd9510594ee9c55a5a73a49a9` implements #76 writer gates and legacy
  replay. #76 acceptance assumes a genuine actual-at-return trusted upper bound.
- `f528e31425d54df6ca6ee12d2480f7031838f604` implements #77 selected lineage,
  CB01 denominator and separate chronology; unchanged CB01 core software bytes.
- `204ce627ec30049d1b77626366fb8495d958daa1` proves #78's isolated integrated chain.
- `55a3a1b` records ADR 0002's production refusal and return-time impossibility.

GitHub #73–#78 are CLOSED. Their historical deterministic acceptance is valid
under its explicit premise. A causal successor invalidates using those tests as
proof of new prospective timing semantics, not their historical results. Add
successor cases for before-request suspension, delayed delivery, remote upper
bound equality, request-before-commit prohibition and no restart/backfill. Preserve
existing v1 tests. Examples requiring version-separated expectations include
`tests/test_matchweek_research.py:164`, `:183`, `:201` and
`tests/test_issue76.py:175`, `:196`, `:233`, `:509`, `:551`, `:622`.

Sources: GitHub issue bodies and completion comments for
[73](https://github.com/Awisalas/match-vet/issues/73),
[74](https://github.com/Awisalas/match-vet/issues/74),
[75](https://github.com/Awisalas/match-vet/issues/75),
[76](https://github.com/Awisalas/match-vet/issues/76),
[77](https://github.com/Awisalas/match-vet/issues/77),
[78](https://github.com/Awisalas/match-vet/issues/78); git log, show and blame.

## Evidence coverage and limits

Source-control evidence used local git history/blame and issue-linked commit
records. Issue evidence used canonical `gh issue view`, as repository instructions
require. Long-form rationale used the repo's ADR/design/research files and glossary,
which are the named authoritative design records. Available external Notion,
Google and Canva apps have no identified MatchVet record in this task and searching
unrelated private documents would not add evidence to the named repository record.
Real-time team chat, external error tracking and product analytics have no identified
MatchVet evidence source in the available tool map. Vercel/Netlify observability
tools are for unrelated hosting platforms and do not observe this Android/Termux
local application. No relevant external runtime observation was queried.

Grounding was performed directly inside the parent's parallel work because the
shared four-agent limit was occupied. No further how/why explorers or synthesis
agent could be spawned in this slice. Protocol/operator qualification belongs to
the parallel primary-source research and is deliberately not inferred here.

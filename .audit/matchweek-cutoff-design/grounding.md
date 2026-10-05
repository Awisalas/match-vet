# Cutoff correction grounding

Design only. No live store access, acquisition, F06/F07/F11/F13/F14/F16/CB01 artifact creation, timestamp requests, or implementation is authorized.

## Founder semantics

All seven Target Leagues form one Friday-through-Monday Matchweek. Research and collection finish and freeze at one Matchweek Research Cutoff before earliest eligible kickoff. Later information never changes a recommendation, including UNKNOWN states and rejection reasons. Settlement and permitted audit/evaluation remain separate.

## Observed runtime flow

F01 exact coverage and F05 health -> F06 assessment-specific membership/revision freeze -> F07 policy and per-membership cutoff -> F11 evidence -> F13 input/history/model -> F14 decision -> F15 processing inputs and F16 whole-freeze manifest -> CB01 fixture-by-preference enrollment and RFC3161 witness -> F19 settlement and chronological evaluation.

- F06 carries all seven scopes and exact controlling revisions. INCLUDED can have date-only kickoff. Its creation time is metadata, not research cutoff. `matchweek_membership.py:257-356`.
- F07 schema 1 includes whole freeze/digest, member/digest, revision/digest, policy/digest, boundary. Rule only KICKOFF_MINUS_LEAD_TIME; `_cutoff` subtracts own kickoff; replay recomputes. `match_evidence_cutoff.py:35-70,129-164,243-272`.
- F11 snapshots all-match evidence but idempotency is request_digest including context, locations, rules. Multiple variants same freeze/policy remain possible. `f11.py:175-197,199-278`; legacy tests `test_f11.py:438-496`.
- F13 freezes chosen history/calibration in input artifacts, but first assembly enumerates mutable retained history catalog. `f13.py:290-389`. Its adapter identity is recomputed during replay at `:223,771`.
- F14 exact lineage already includes cutoff, evidence, model. Late weather UNKNOWN/attempt metadata can change derived mandatory research state. `weather.py:514-529`; `f14.py:440-459,574`.
- F15/F16 verify exact F06/F07 coverage but do not explicitly require uniform common boundary. `f15.py:154-209`; `f16.py:107-159,303,486`.
- CB01 has full INCLUDED membership x enabled preference denominator, exact lineage, and strict cutoff < signed genTime < own kickoff. This witnesses existence by genTime, not pre-cutoff collection. `cb01_trust.py:846`; design contract chronology section.
- CB01 sources hash current cb01.py bytes into PreEnrollment software identity; reconstruction requires byte equality. Editing cb01.py risks old replay. `cb01_sources.py:484,702-709`; `cb01.py:1125-1132`.
- CB01 denominator selection/failure indexing does not enforce uniform cutoff policy. `cb01.py:392-427,1941-1953`.
- F19 retains exact manifest/match/decision and append-only result corrections. `f19.py:102,275`.

## Direct history and product authority

- Original glossary 207cdf9 defines one Matchweek cutoff initially six hours. T05 448b930 implemented 21600 and never recalculates old cutoffs.
- Current issue #1 and owner resolution #13 explicitly settle six hours before earliest INCLUDED kickoff. #23 implements it; open #37 still requires real six-hour chronological evaluation. https://github.com/Awisalas/match-vet/issues/13#issuecomment-5646165350
- V2 direction 7c0635b explicitly replaces shared cutoff and says timing undecided; architecture 3b897e3 propagates this. #58 deliberately requires independent Friday/Monday deadlines and no implicit numeric default. #62 propagates these deadlines into F11.
- #70 version 0.1.0 explicitly applies the old V2 per-match cutoff. Preserve its released evidence; new corrected chronology needs an explicit successor/addendum.
- #16 historical FR-1 permits later retrieval with trustworthy earlier publication; current founder instruction supersedes that exception for corrected recommendation inputs. https://github.com/Awisalas/match-vet/issues/16#issuecomment-5646458780
- #17 prohibits later research, recalculation, and refresh. https://github.com/Awisalas/match-vet/issues/17#issuecomment-5646569039
- No issue explicitly reopens/revokes the owner six-hour resolution or chooses another number. Distinguish explicit 21600 configuration from an implicit code default; reconcile competing V1/V2 records in final synthesis.

## Evidence coverage

Git source history and GitHub issues consulted. Google Drive narrow MatchVet/match-vet/Match Vet searches succeeded with no results. Notion project and active DEC-2 confirm pre-lineup no-refresh/replay rationale, without six-hour or slate-versus-match timing. No realtime chat or error-tracking MCP exists. Vercel/Netlify/Sites runtime observability is irrelevant to this local SQLite/Termux contract; Metricool is social analytics, not MatchVet evaluation.

Notion references: [MatchVet project](https://app.notion.com/p/3ead1dd61530813a81f9e67bef460817), [DEC-2](https://app.notion.com/p/3ead1dd6153081e0a9c8d6e2197e4c4d), and [cutoff task](https://app.notion.com/p/3ead1dd61530815a9c02ef12eefc7c74). Their generic pre-lineup timing does not settle a number or supersede the current founder rule.

## Live consequence

Founder retains A authoritative, B unmerged. Existing recovery assessment confirms unsupported exact transfer and fresh F01/F05/F06 route; no downstream identities exist there as of its retained inspection. These are historical observations, not a new live inventory. Schedule/cutoff must be revalidated after implementation. No replayed B schedule proves A's future boundary.

## Candidate questions

Compare policy-rule-only F07 + existing input snapshots against an explicit shared Matchweek boundary/input-selection artifact. Avoid SQLite migration. Preserve legacy rules and reader bytes. Protect every writer, not just CLI. Fail closed on nonexact INCLUDED kickoff, undefined earliest/common boundary, incomplete seven-scope eligibility, changed after-freeze inputs, late evidence, or mixed downstream policy/boundary. CB01 batching can remain per fixture, but corrected cohorts cannot hide omitted earlier fixtures or use their late kickoff to refresh evidence. Establish whether witness deadline must additionally be before slate earliest kickoff without silently changing historical witness interpretation.

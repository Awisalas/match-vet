## Parent

Part of #80.

## What to build

Downstream consumers explicitly accept qualified selection-v2 lineage while preserving every denominator row, CB01's independent post-T enrollment proof, exact F19 settlement lineage and historical replay.

## Exact scope

Selected-state CLI/report/evaluation consumers; CB01 selected-state adapter; denominator and chronological cohort dispatch; F19 settlement/correction/cache lineage and read-only legacy/v1 compatibility. Consume the preceding children's owner and supported stage readers; do not add another qualification owner.

## Acceptance criteria

- [ ] Dispatch by stored selection/completion, candidate and engine identities. Only exact supported qualified owner state can supply recommendations; generic COMPLETE, candidate F16, missing receipt or nonselected alternate graph never qualifies. Unsupported versions fail closed before timestamp comparisons. Inspection of terminal/unqualified or withdrawn state cannot masquerade as present qualification.
- [ ] CB01 explicitly resolves selection-v2 and its exact F16/F07/decision lineage without changing released CB01 core/software commitment identities, canonical bytes or old token readers. Keep T<signed genTime<controlling kickoff. Selection witness and CB01 token cannot substitute for each other's purpose, imprint or chronology.
- [ ] Full INCLUDED membership × enabled-preference denominator survives unavailable F16/receipt/lineage, failed or missing witnesses and unattempted cases. Preserve failure/attempt history and UNKNOWN/unavailable rows. Do not filter the cohort to qualified/enrolled successes.
- [ ] F19 settlement and append-only corrections require exact selected F16/decision origin. Cached or alternate valid artifacts cannot bypass receipt/selection checks. Later outcomes/post-cutoff evidence never join frozen recommendation inputs.
- [ ] Reports/evaluation distinguish causal, historical v1 and legacy contracts and assurance, preserving existing cohort/chronology meanings and #70 released method bytes. Do not pool incompatible versions implicitly or treat advisory timestamps as qualification. Trust withdrawal refuses present qualification while original historical inspection remains available.
- [ ] Existing v1/legacy canonical artifacts and historical engines/CB01 software reconstruct byte-for-byte. Old domain readers reject successor selection/completion semantics; unchanged source primitives/F06/F07 retain their old interpretation. No historical candidate is upgraded/requalified.

## Explicit non-scope

Writer/schema contract authoring, witness protocol implementation, source activation, numerical derivation or fitting, PLAY promotion, integration harness. No changed CB01 time window, core commitment identity or historical acceptance.

## Focused tests

Qualified-v2 versus candidate/missing/withdrawn/alternate selection consumers; full denominator with failed/unattempted/missing lineage; CB01 separate strict boundaries and wrong-role token rejection; F19 exact origin and cache/correction isolation; report/evaluation version dispatch; retained CB01 wire/software commitment bytes and v1/legacy reader/engine reconstruction. Run directly affected #77 regressions only, reusing preceding child proofs rather than rerunning all writer/crypto cases.

## Recommendation

GPT-6.1 Sol with high reasoning; blast-radius for denominator loss, released CB01 identity and F19 cached lineage.

## Blocked by

- #82, the preceding ownership boundary must pass before implementation starts.

## Contract and restrictions

Implement ADR 0003 and the accepted causal Matchweek selection design linked by #80. Architecture is settled. Preserve the founder's common T = earliest INCLUDED kickoff minus explicit 21600 seconds, one stable logical Matchweek selection/completion slot across versions, and historical completion of #73–#78. Old v1/legacy meanings, canonical bytes, engine/software identities and readers remain intact. Unsupported successor semantics fail closed. Production refusal remains until every child and the entire #80 acceptance proof pass; child completion never authorizes source activation or partial production qualification.

Use isolated temporary stores, deterministic synthetic graphs and retained offline wire fixtures only. No live-store access, network activation, live fixture acquisition, live TSA/TUF requests, operational artifact publication, SQL migration, #70 fitting or PLAY promotion. Approved configuration in tests is isolated synthetic approval, never live activation. No historical artifact, migration, issue or audit rewrite. Run focused real-code tests and retained-wire checks for this boundary, directly affected v1 regressions, Ruff and mypy for changed Python, and git diff --check. Batch tests for Termux; do not run the full suite.

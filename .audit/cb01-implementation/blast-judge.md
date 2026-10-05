# CB01 blast-radius cross-judge

Scope: candidate A and candidate B were judged against the frozen `docs/design/cb01-enrollment-contract.md` and the current CB01 source. The implementation changed during the audit. This report separates defects present in the candidates' source snapshot from their status after the in-flight fixes.

## Verdict

Both reports found real faults. Candidate A found the most immediate blocker, the fresh TUF refresh failure. Candidate B found the broader attachment publication problem and the CandidateInput provenance error. Candidate B's rollback concern was also valid, but its proposed offline replay proof targeted the wrong lifecycle seam.

| Finding | Judgment on reported snapshot | Evidence and qualification | Current-source status |
| --- | --- | --- | --- |
| A1: fresh trust refresh rejects expired intermediate roots | **Confirmed, release blocker.** | The old loop checked every sequential root at the current time. A deterministic refresh over retained roots 11 through 15 failed on expired root 11 before it could reach valid root 15. The public enrollment path turns that exception into `SIGSTORE_TUF_REFRESH_FAILED`, so every normal live batch would remain incomplete. | **Fixed.** `refresh_trust` now verifies each rotation and checks expiry only on the final root in `src/matchvet/cb01_trust.py:281-318`. The focused regression now passes and also rejects an expired final root. |
| A2: a caller-selected F19 subset can erase an equal-authority conflict | **Confirmed, high assessment impact.** | The reported code resolved only the selected subset and replay reproduced it. The public seam test built two equal-authority, contradictory final scores and did not raise when one digest was selected. That permits `CONFLICTING` to become `AVAILABLE`, contrary to contract line 123. | **Fixed.** `_outcome_evidence_items` always retains the complete F19 snapshot and rejects a nonempty partial F19 selection in `src/matchvet/cb01.py:577-611`; replay requires every F19 evidence digest in `src/matchvet/cb01.py:1866-1882`. |
| A3/B2: supplemental exact T10 evidence cannot be attached | **Confirmed.** | The old API rejected every digest outside the selected F19 settlement even though contract line 114 permits exact same-fixture T10 supplements. This blocks diagnostics for a family whose counts were absent from the evidence used to grade another preference. | **Fixed.** The repository now loads requested same-fixture evidence from the protected T10 evidence store, keeps the complete F19 snapshot, and replays the same selection in `src/matchvet/cb01.py:577-611` and `src/matchvet/cb01.py:1878-1907`. |
| B1: rejected competing outcome facts remain cataloged and replayable | **Confirmed, with likelihood downgraded from high to medium.** | In the reported code, the fact artifact was published before the one-successor check. A changed second call could therefore raise while leaving its fact projection cataloged, and replay accepted a fact without its OutcomeAttachment. An identical retry was safe because it reproduced the same digests, so "ordinary duplicate calls" overstated the likelihood. Impact remained high because the orphan exposed an alternate fact view outside the accepted correction chain. | **Fixed.** A competing successor is checked before fact publication in `src/matchvet/cb01.py:552-575`. A crash can still leave the fact-first artifact, but replay now requires each selected fact to be named by a selected exact OutcomeAttachment in `src/matchvet/cb01.py:357-382`; an identical retry reuses the orphan and completes the pair. |
| B3: `Support.candidate_input` points to the F14 decision artifact | **Confirmed.** | F14 protects the decision input bundle and decision under distinct media types. The reported `_support` call passed `f14_digest`, so a PRESENT CandidateInput reference resolved to the decision output rather than the artifact containing `candidate_inputs`. Contract lines 28, 30, 53, and 57 require the exact available support reference. | **Fixed.** Source preparation now retains `decision_value["input_bundle_digest"]` and passes that digest to `_support`, which uses it for the CandidateInput reference in `src/matchvet/cb01_sources.py:200-203` and `src/matchvet/cb01_sources.py:486-505`. |
| B4: fresh TUF metadata can roll back | **Confirmed risk on the reported fresh-enrollment path.** | The old refresh authenticated signatures, references, expiry, and the pinned target, but had no floor for timestamp, snapshot, or targets versions and no comparison with locally retained newer versions. A still-valid older signed chain could therefore mask a later removal of the TSA entry. Candidate B's proposed `replay_trust_state` proof is the wrong proof: contract line 105 deliberately replays an original enrollment under its retained trust state. The correct proof is a fresh enrollment refresh below the reviewed or locally retained version floor. | **Fixed.** Trust validation enforces the reviewed root/timestamp/snapshot/targets version and digest floors, and repository retention rejects versions below already protected metadata in `src/matchvet/cb01_trust.py:643-677` and `src/matchvet/cb01.py:1396-1482`. Offline replay of the original retained state remains immutable as required. |

## Cleared claims

- Chronology and RFC3161 verification fail closed at the inspected boundaries. The verifier checks granted status, imprint, nonce, token policy, CMS algorithms and ESS binding, signer identity, EKU, chain, certificate time at signed `genTime`, and strict `cutoff < genTime < kickoff`. The captured Sigstore fixture exercises the real crypto verifier. Denominator and lineage checks are added by the repository before VERIFIED publication.
- Receipt-last visibility is supported by the source. Enrollment records are published before the complete receipt, while `inspect_denominator` accepts only explicitly selected complete receipts. Interrupted record publication remains staged. The repository recovery test is the right proof because ArtifactStore has no multi-object transaction.
- Exact upstream replay is present. CB01 reaches F16 replay, which reaches F14 and F13 replay; the preparation path does not call their acquisition or build APIs.
- CB01 keeps all methodology eligibility dimensions `NOT_ASSESSED`, and schema validation rejects any promotion. No F17, F18, F20, or F21 behavior is introduced here.
- The CB01 implementation adds new source modules and package data. It does not modify Store, ArtifactStore, F13, F14, F16, F19, or the production CLI. The separate `CONTEXT.md` working-tree edit should still be reviewed on its own rather than treated as part of CB01 by default.

## Runtime evidence

The strongest reproduced facts were:

1. On the reported snapshot, the retained-root refresh and partial-conflict selection tests both failed exactly at the claimed behavior: `2 failed in 249.72s`. The trust failure raised `CB01TrustError: Sigstore TUF metadata is expired at refresh time` on root 11. The outcome test reported `Failed: DID NOT RAISE CB01Error` when only one side of an equal-authority conflict was selected.
2. After the trust fix, the exact retained chain test passed in 7.51 seconds. It accepts expired intermediate roots and rejects an expired final root.
3. The reviewed-floor check passes against the captured trust state and rejects timestamp version 798 below the frozen version 799 floor.
4. On the stable corrected source, the public outcome seam passed: `1 passed in 620.01s`. It used a real Store and covered an interruption after fact publication, rejection of standalone orphan replay, identical retry, complete F19 conflict preservation, protected same-fixture T10 supplements, the correction chain, and paired fact/outcome replay.
5. The full CB01 suite passed on the stable source: `31 passed in 1276.18s`.
6. The affected F13/F14/F16/F19 suite passed: `28 passed in 771.87s`.
7. Project-wide `uv run mypy` passed across 102 source files.
8. `uv run ruff check src tests` and `uv run ruff format --check src tests` passed across 102 Python files.
9. Diff checks passed.

## Final gate

The completed public outcome seam proves the attachment invariant that both candidate reports depend on. A crash after fact publication cannot expose the orphan through replay; retry completes the identical pair; partial F19 selection cannot erase a conflict; supplemental same-fixture T10 facts remain exact; and facts replay only with their selected OutcomeAttachment.

No-argument Ruff and format walks are outside this source-and-test gate. They report existing violations in unrelated untracked `.audit` scripts and older Markdown documents; the scoped `src tests` checks above are clean.

# Independent design review and arena cross-judgment

Scope: #79 design, research and offline proof only. I read the assigned artifacts, both candidates, ADR 0002 and the relevant writer/Store paths. I did not run production code or inspect another review. The causal argument is sound **under its stated premises**: honest local execution and durable selection precede a fresh request, and an honest qualified TSA bounds its subsequent event by `U < T`. The retained CB01 token and generic storage experiment do not verify a new production runtime; the documents mostly say this clearly.

## Findings

### 1. Warning: the versioned candidate contract has no defined route through direct writers

Location: `docs/design/causal-matchweek-selection-witness.md:30-55`, `:214-233`, `:250-265`; current paths `src/matchvet/f11.py:186`, `:264`, `src/matchvet/f12.py:237`, `src/matchvet/matchweek_research.py:450`, `:504`.

The sketch changes `require_candidate_write` to accept `CausalCandidateContract`, but direct F11/F12/F13/F14 entry points currently receive only existing freeze/cutoff or artifact inputs. The F07 policy is deliberately unchanged, so those inputs cannot identify v1 versus v2. Today `require_candidate_write(freeze_id, policy_digest)` dispatches corrected work to the v1 trusted-clock path. F11's `build_or_replay_for_freeze` can also discover a retained result before F15 supplies any contract. Without an explicit propagation and fail-closed rule, a successor could leave direct writers on v1, accept a missing version as v2, or reuse a v1 result as prospective evidence. This is the main implementation-readiness gap.

Specify where the prospective contract is supplied to each direct entry, how it is checked against retained F15/F11/F12/F13/F14/F16 identity, and that a missing or conflicting version refuses. The shared research owner should make the dispatch decision once; callers should not independently infer it from the unchanged F07 policy or media type. Exercise direct calls as well as F15 resumes in successor tests.

### 2. Warning: first-result conflicts must span old and new candidate media types

Location: `docs/design/causal-matchweek-selection-witness.md:217-231`, `:250-262`; current paths `src/matchvet/matchweek_research.py:340-368`, `:382-405`, `:427-447`, `src/matchvet/f11.py:307-343`, `src/matchvet/f14.py:369-392`.

The design correctly requires new timing-bearing artifact identities and says the first-result/identity rules survive. Existing guards scan only the current F11/F12/F14 media types and the one F15 canonical contract. If successor code only scans its new media types, an old unselected candidate for the same logical Matchweek can disappear from conflict checks while the stable selection slot is still vacant. The implementation could then create a second F11 request, F12 attempt, or F14 input under v2. Refusing to *adopt* v1 bytes is not sufficient to preserve the first-result rule.

Define one cross-version logical candidate occupancy/conflict predicate over all supported historical and prospective identities. It should reject an incompatible old candidate before new publication, while the v2 graph reader still rejects old artifacts as timing evidence. Test a vacant selection slot with a retained v1 F11/F12/F14/F15 candidate followed by a conflicting v2 direct write.

### 3. Warning: known later signer compromise needs a replay qualification rule

Location: `docs/design/causal-matchweek-selection-witness.md:184-194`, `:264-279`; `docs/adr/0003-causal-matchweek-selection-witness.md:18-34`, `:88-96`.

The design candidly says historical TUF metadata cannot detect a newer undisclosed revocation. It also says later trust reassessment is append-only, but does not say whether a known compromise makes `replay_for_matchweek` refuse qualification. A compromised TSA key can sign a backdated token with the exact nonce and imprint; checking certificate and metadata validity against that token's own interval cannot distinguish it. Sigstore's pinned [policy, section 8](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#8-security-considerations) explicitly calls for rechecking current revocation status and says compromise can invalidate old tokens. This is separate from the accepted inability to learn undisclosed changes while offline.

Keep the receipt and selected graph immutable, but specify how a *known* key compromise, revocation or withdrawn authority approval changes the qualification result for later readers and consumers. Define what happens when current status is unavailable; do not silently describe a pinned historical trust state as current assurance. This can be a separate trust-status record and versioned reader rule, without backfilling or replacing the selection.

### 4. Warning: source association remains an activation prerequisite

Location: `docs/design/causal-matchweek-selection-witness.md:157-181`; `docs/research/causal-matchweek-witness-2026-10-08.md:35-55`.

The research accurately notes that the inspected handler copies the requested policy OID and fixes `Accuracy=1s`, while its monitor does not itself stop issuance. The [policy](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md) and [handler](https://github.com/sigstore/timestamp-authority/blob/3593e847b84fa501e2a0729eaea2c6ac982c4ab3/pkg/api/timestamp.go) support an explicit operator-honesty premise, not independent assurance about the deployed instance. The design says to approve an endpoint, signing identity, target hashes and metadata floors, but no concrete v2 approved profile with those identities exists yet. I do not treat that as a defect in this design-only issue because activation is expressly deferred. The corrective issue should make that exact approval a prerequisite and retain its evidence before enabling the provider. A matching OID or old CB01 certificate alone must not complete it.

## Proof and red-flag assessment

`proof.py` checks a synthetic order relation, a retained CB01 RFC3161 response, and a generic four-reference SnapshotManifest round trip. Its 5,120 pause/error schedules assume the honest remote upper bound and the prerequisite event chain; they do not exercise a v2 writer, protected receipt, full multi-match closure or TSA availability. `proof-result.json` and the design disclose these limits. The [RFC3161 accuracy rule](https://www.rfc-editor.org/rfc/rfc3161.html#section-2.4.2) supports `U = genTime + signed accuracy`; the proof correctly rejects equality and shows that a generic OpenSSL verification can accept a request without the application-required nonce. I found no claim that the generic storage experiment establishes protected v2 publication.

Candidate A has a deep owner interface: the repository hides graph admission, fresh commit, request and receipt, and the private adapter owns wire/trust rules. No shallow public stage API, pass-through coordinator or transport re-export is proposed. Its remaining interface leak is the unresolved candidate-version route in finding 1. Candidate B's public interface is also small, but local and remote graph validators share canonical policy knowledge and two durable slot histories. That duplication is a concrete information-leak and ownership cost, not a reason to add the registry for #79.

## Candidate scores

Scores apply to the candidate sketches as written, before the later research and final design filled gaps. Each criterion is 0-2 in the order of `.audit/issue-79/rubric.md`.

| Criterion | A: local selection + RFC3161 | B: remote registry |
| --- | ---: | ---: |
| Exact graph, durable unique selection, causal bounded event | 2 | 1 |
| Primary-source accuracy, leap, binding, trust, availability | 1 | 0 |
| Every versioned direct/resumed writer path | 1 | 1 |
| One operation, ambiguous receipt, terminal failure, replay | 2 | 2 |
| Small owner API, historical slots/bytes, demonstrated schema fit | 2 | 1 |
| **Total** | **8/10** | **5/10** |

Candidate A is the architecture base. Its trust and writer scores are partial because its sketch leaves source qualification and direct-entry propagation open; the final research/design improves source honesty and writer enumeration but does not close findings 1-3. Candidate B's event source is a proposed service using ClockBound, without a deployed signed registry or qualified UTC sample guarantee. Its two-store protocol adds a remote schema, backups, replica uniqueness and operator duties to prove a property the local fresh-commit plus TSA chain already proves under the stated local-storage premise. Neither candidate verifies a new runtime.

## Final architecture recheck, 2026-10-08

The original findings above record the first review and remain unchanged. This recheck covers the later additions to `docs/design/causal-matchweek-selection-witness.md` and the corrective implementation issue. It is a design-contract recheck, not evidence of a working v2 runtime.

- **Finding 1 resolved for design-to-ready.** The new direct-entry section at design lines 293-319 requires a canonical candidate descriptor before v2 work, passes its digest through F15 and every direct F11/F12/F13/F14/F16 constructor, resolves protocol only in the research owner, and refuses missing causal context before discovery or acquisition. It also requires retained results and dependencies to carry the same descriptor. The implementation issue repeats these conditions as acceptance criteria. The actual API changes and negative tests remain successor work.
- **Finding 2 resolved for design-to-ready.** Design lines 321-337 require one research-owner conflict predicate across all registered old/new F11/F12/F14/F15 candidate identities. An old timing-bearing candidate blocks a new v2 chain even with a vacant selection slot. The first guarded candidate publication pins the contract inside the catalog transaction, and tests must cover old partial state and competing descriptors. This is a concrete cross-version rule rather than media-type exclusion alone. Whether every physical publication path obeys it awaits implementation tests.
- **Finding 3 resolved for design-to-ready with an explicit trust limit.** Design lines 221-246 and ADR 0003 now distinguish historical verification from current revocation assurance. Known authenticated compromise or withdrawal invalidating the event requires present qualification refusal while the exact graph, receipt and occupied slot remain available for historical inspection. Missing current status cannot be reported as checked; consumers requiring current assurance must refuse until separately authenticated status exists. This does not claim that offline replay can discover an undisclosed revocation.
- **Finding 4 is a successor activation prerequisite.** The design now records exact initial signer/anchor DER hashes, bootstrap root hash, metadata floors, TrustedRoot hash and algorithm family at lines 171-183. I checked the signer, anchor and bootstrap hashes against the retained local bytes; they match. The approved source-policy association remains an explicit operator-compliance premise, with no claim of independently measured accuracy. The corrective issue requires a concrete retained runtime profile with exact authenticated target/chain material and tests before enablement. That byte artifact is intentionally not a deliverable of this design-only issue.

I find no unresolved blocker to opening the corrective implementation issue from this design. Production qualification remains disabled until that issue proves the protected v2 path, direct/resumed writers, strict witness verification, trust profile and consumer dispatch with isolated tests. The original candidate scores remain scores of the earlier sketches, not of this revised architecture.

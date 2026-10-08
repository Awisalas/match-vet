# Independent review C

Reviewed on 2026-10-08 as the available highest-capability substitute for an
unavailable default Claude/Grok reviewer. No other reviewer output was read.
This review covers the ADR, architecture, research, grounding, both candidates,
rubric, proof script/result, ADR 0002 and relevant existing writer/storage source.

Recommend candidate A as the architecture base. The causal argument is valid
under its explicit honest local execution/storage and honest remote-authority
premises. No critical finding. The one warning below was resolved during review
by an explicit trust-lifecycle rule in the final architecture and research.

1. **Warning: distinguish historical witness replay from current Sigstore policy assurance.**

   Location: `docs/design/causal-matchweek-selection-witness.md:184`, especially
   the historical validity and later reassessment rules at lines 189-194;
   `docs/research/causal-matchweek-witness-2026-10-08.md:64`; candidate A at line 149.

   The selected profile relies on Sigstore's pinned policy, but the research
   omits its relying-party requirements. Section 8 requires current revocation
   checks during the signing certificate's lifetime and says a compromised TSA
   key invalidates its tokens. Annex A makes long-term verification conditional
   on the key remaining uncompromised when verification occurs.
   [Pinned Sigstore policy, section 8 and Annex A](https://github.com/sigstore/timestamp-authority/blob/3a83b1f015affed68763ef73f7729aa478c650e1/docs/tsa-policy.md#8-security-considerations)

   The proposed path verifies a token against retained historical trust at the
   token's own interval and returns qualified selected state. Later reassessment
   only appends a separate record. The document admits that offline verification
   cannot discover a newer revocation, which is correct, but never says how an
   already known authenticated withdrawal changes the qualification result.
   A client could therefore continue treating the receipt as qualified using its
   retained profile after an authenticated notice invalidates that event. This
   is a gap in the specified trust decision, not a failure of `C < E <= U < T`.

   Specify that retained verification establishes a conditional historical
   result, and expressly identify the difference from current policy-compliant
   revocation assurance. Define how known authenticated compromise or withdrawal
   affecting the event makes current qualification refuse. Preserve the exact
   receipt and selected graph, keep the stable slot occupied, and permit no new
   witness or replacement selection. Add successor cases for a valid retained
   receipt followed by an applicable withdrawal and for offline replay with no
   claim of fresh revocation knowledge. The lead's proposed clarification covers
   this warning. I checked the resulting architecture section, "Historical
   verification and current trust", and the research's section-8 discussion.
   They distinguish the historical result, require refusal for known applicable
   invalidation, preserve exact immutable inspection and make no current-status
   guarantee. Status: resolved in the synthesized design.

The numeric accuracy treatment is otherwise honest. It distinguishes an
operator's signed assertion from independent accuracy measurement, requires the
complete signed allowance, preserves strict equality refusal and rejects
unsupported leap intervals. The request is built only after confirmed fresh
selection commit. Precomputed commitments, idempotent selection lookup and a
persisted selection cannot grant request authority. Receipt loss before indexing
remains terminal even when the remote event was timely.

The writer plan handles the significant semantic change directly. New candidate
work is unqualified until the complete graph's witness passes. It preserves
vacancy and first-result guards, identifies the weather health-clock coupling,
requires new artifact/run/engine identities and separates old readers. Nothing
in the logical model or generic storage experiment verifies those successor
implementations, and the documents say so. Existing source confirms the private
receipt binding currently accepts only the selection reference, so its new exact
evidence-set rule remains required implementation work.

Candidate scores use the five criteria in `rubric.md`, with the shared grounding
and research as context. Each score is 0-2. These score the original candidate
packages; the final synthesis resolves A's trust-policy warning.

| Criterion | A | B | Reason |
| --- | --- | --- | --- |
| 1. Complete graph, durable unique selection, causal event and unchanged T | 2 | 2 | Both order full local durability before a fresh bound event. B also orders a remote durable commit. |
| 2. Primary-source accuracy, leap, binding, trust and availability | 1 | 1 | A has a concrete protocol and retained wire evidence but needs the revocation clarification above. B still needs qualification of its hosted interval signer and deployment. |
| 3. Every direct/resumed writer, prospective versions and no metadata authority | 2 | 1 | A adopts the grounded shared-owner contract and explicit versioned writer semantics. B states the rule but leaves the detailed writer/identity mapping to later design. |
| 4. Live operation, crashes, receipt ambiguity, no backfill and exact replay | 2 | 2 | Both define terminal loss and stable slots. B applies the same loss rules to both hosts. |
| 5. Small owner API, historical identity protection and demonstrated storage fit | 2 | 1 | A extends existing owners and the generic representation already fits. B adds another catalog, durable uniqueness system, authentication and backup-history obligations. |
| Total | 9 | 7 | A is the smaller correction for the stated requirement. |

Neither candidate exposes public transport stages or pass-through methods. A
keeps wire/trust knowledge in a private adapter and selection policy in the
existing repository. B's local and remote owners each hide real work, but duplicate
graph validation and enduring slot ownership add substantial operational cost
without removing the honest-local-execution premise. Do not graft the remote
registry into A unless remote possession becomes a separate requirement.

I reran `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python
.audit/issue-79/proof.py`. It passed with the recorded 5040 predecessor
permutations, 5120 synthetic schedules, 320 qualified cases, exact retained-token
verification and four-reference schema-1 round trip. The rerun used temporary
storage and the retained diagnostic token. It made no network request. Primary
source inspection used read-only web access separately. No live store, live
fixture, GitHub state or shared implementation/document was changed.

These results establish the stated logical implication, diagnostic wire checks
and generic representation. They do not establish a new protected v2 receipt,
prospective writer integration, current revocation knowledge or measured public
TSA accuracy. Keep activation blocked on the successor implementation and tests.

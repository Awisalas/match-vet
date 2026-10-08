# Review B: causal Matchweek selection witness

## Verdict

Use Candidate A as the architecture base. Its causal argument is valid under the
stated honest-local-execution and honest-approved-TSA premises, and it keeps the
remote service out of graph ownership. Candidate B proves a stronger fact, remote
possession of the graph, but that fact is not required by #79 and costs a second
durability, uniqueness, backup, authorization and trust system.

The records do not verify a running causal-v2 path. I reran
`PYTHONPATH=src:tests python .audit/issue-79/proof.py`; it reproduced
`proof-result.json`. That establishes the stated arithmetic model, retained-token
checks and generic schema-1 representation. The result itself correctly says
`protected_v2_publication: not implemented`. Production refusal therefore remains
the only supported runtime result.

## Findings

### 1. Critical: the prospective contract cannot yet reach every direct writer

Location: `docs/design/causal-matchweek-selection-witness.md:28-61`,
`:210-264`; `.audit/issue-79/implementation-issue.md:21-25`, `:62-70`;
`src/matchvet/matchweek_research.py:412-538`; direct callers in
`src/matchvet/f11.py:180-206`, `src/matchvet/f12.py:231-294`,
`src/matchvet/f13.py:156-320`, `src/matchvet/f14.py:349-450`,
`src/matchvet/f15.py:117-208`, and `src/matchvet/f16.py:104-176`.

Evidence: the design sketches `require_candidate_write(contract:
CausalCandidateContract)`, but the shipped direct APIs and the implementation issue
do not define how that contract reaches each writer. Today all shared dispatch is
derived from only `freeze_id` and `policy_digest`, and
`require_candidate_write()` chooses behavior through `is_corrected(policy_digest)`.
The causal design deliberately keeps the same corrected F07 rule, policy and T, so
that branch cannot distinguish historical v1 timing from causal-v2 timing. F12 is
the sharpest example: `publish(attempt)` derives an F07 cutoff from the existing
attempt and has no prospective contract, witness profile or timing version input.
F11 and F13 have the same problem in their direct build paths. F15 can add a run
identity, but direct callers bypass F15 by design.

This is not a naming omission. An implementer must otherwise choose an ambient
repository mode, infer v2 from unchanged F07 data, or change the corrected path for
every caller. Each choice can reinterpret v1 candidate bytes or let a v1 artifact
enter a v2 graph, contrary to ADR 0003.

Suggestion: make one immutable `CausalCandidateContract` or
`CandidateWriteContext` the required input to every prospective F11, F12, F13,
F14, F15 and F16 write entry. Let it own the guarded ArtifactStore and the separate
advisory metadata clock. Persist its digest in each new artifact/run identity and
filter discovery by that exact digest before reuse. Keep the old signatures on the
v1/legacy path or make them refuse prospective corrected writes. Do not infer the
timing protocol from F07 policy, media type alone, or a constructor default. Add a
short call-flow sketch showing F15 and each direct entry creating or loading the
same contract and passing it down to F12 and the weather-health recorder.

### 2. Warning: the TUF/current-revocation rule mixes a pinned trust premise with a circular freshness check

Location: `docs/design/causal-matchweek-selection-witness.md:157-209`,
`docs/research/causal-matchweek-witness-2026-10-08.md:59-82`,
`.audit/issue-79/implementation-issue.md:47-61`.

Evidence: the documents correctly disclose that the retained TUF state does not
prove current revocation status and that the public instance's one-second behavior
is an operator premise. The proposed verifier nevertheless authenticates TUF
rotations and expiry "without local wall time," then uses the witnessed interval to
check the certificate and final metadata that authorize that same witness. TUF's
update workflow checks expiry against a fixed update-start time. The TSA token
cannot safely provide that independent start time when evaluating compromise: a
compromised still-pinned TSA key can mint a matching-nonce token after T with a
backdated `genTime`, while an attacker replays metadata that was valid at that
claimed time. Version floors prevent rollback below retained state; they do not
prove that retained state is latest.

The causal proof survives because it already assumes an honest, uncompromised
approved authority. The TUF language should not imply an extra currentness guarantee
that the protocol does not have.

Suggestion: choose one explicit trust rule. The smaller rule is an immutable
MatchVet profile that pins the exact policy digest, endpoint, TSA leaf/anchor DER,
algorithms and approval interval; TUF records how those pins were obtained, while
profile activation and known compromise withdrawal are separate authenticated local
state. Missing activation state, lost rollback floors or uncertain restore history
must refuse after reboot. If current revocation at issuance is required, add an
independent fresh authority or online signed mechanism whose freshness does not
come from the token being checked. In either case, remove runtime wording that
suggests TUF plus the token establishes latest status.

### 3. Warning: postcommit request issuance is specified by comments rather than the private operation type

Location: `.audit/issue-79/candidate-a.md:79-103`,
`docs/design/causal-matchweek-selection-witness.md:55-60`, `:78-100`, and the
existing state machine in `src/matchvet/store.py:4652-4778`.

Evidence: Candidate A exposes a constructible `_WitnessBinding` to
`_RFC3161Witness.request_and_verify()`. The sequence comments say that binding,
nonce and transport follow confirmed fresh commit, but the type sketch does not
make request issuance a transition of `_ResearchOperation`. That order is the
load-bearing fact. RFC3161 proves that the committed digest existed by the remote
event only if the exact request was first issued after C. A request sent before C
and retained until after C can produce a perfectly valid nonce/imprint token without
proving `C < E`. A test can catch one implementation mistake, but the existing v1
owner already has a cleaner structural seam for preventing it.

Suggestion: extend `_ResearchOperation` with a transition available only in
`selection_committed`, for example `_begin_witness(selection_digest, graph_digest,
profile) -> _WitnessAttempt`. Generate the nonce and canonical request inside that
transition, consume the request attempt before transport, and bind the returned
verified event to that exact attempt before enabling the one receipt attempt. The
RFC3161 adapter should receive the operation-produced request and return parsed
evidence; it should not accept an independently caller-built binding. Any transport
exception, invalid token or ambiguous attempt leaves the operation consumed and the
slot terminal. This keeps precommit issuance impossible in the same place that
already prevents receipt backfill.

## Cross-judge scores

Scores use `.audit/issue-79/rubric.md`, from 0 to 2.

| Criterion | Candidate A | Candidate B | Judgment |
| --- | ---: | ---: | --- |
| 1. Whole graph and unique selection causally precede bounded event before T | 2 | 2 | Both state the required chain. A relies on the existing local graph owner; B also proves remote possession. |
| 2. Primary-source accuracy, leap, binding, trust and availability | 1 | 0 | A uses the right RFC3161 bound and states the Sigstore operator premise without inventing a margin, but current trust freshness remains deliberately unproved. B names ClockBound as a component of a service that does not exist and has no qualified signer/profile. |
| 3. Versioned unqualified candidates on every direct/resume path | 1 | 1 | Both identify the semantic change. Neither candidate closes the contract flow through the actual direct writer signatures; A's final design gets closer with the writer table. |
| 4. One operation, crash ambiguity, terminal loss and immutable replay | 2 | 2 | Both have clear one-attempt, no-backfill, occupied-slot and ambiguous-commit rules. |
| 5. Small owner API, private protocol, historical bytes, stable slots and demonstrated storage impact | 1 | 0 | A has the right deep owner and proves generic representation, but protected v2 binding is unimplemented. B adds an unproved remote catalog, global uniqueness and backup regime. |
| Total | 7/10 | 5/10 | Candidate A is the clear base. |

## Design red-flag screen

Candidate A avoids a public staged workflow and keeps RFC3161 details behind a
substantive private adapter. Its public owner is deep, and the stable role slots
stay with the existing catalog owner. The remaining information-leak risk is the
causal contract: if callers independently reconstruct its fields, version policy
will spread across F11 through F16. Passing one digest-bound context fixes that.
The request-order finding is also a structure problem. The private operation should
own the transition instead of relying on method order documented in comments.

Candidate B has a small client API, but it duplicates graph validation, unique-slot
policy and permanent history across local and remote stores. That is information
leakage with distributed failure modes. The registry adapter is not a pass-through,
but the added module is deeper only because it owns an entire new service. Nothing
in #79 needs that service's extra remote-possession fact.

## Evidence checked

- Read both candidates, the ADR, design, research, grounding, corrective issue,
  ADR 0002, the current selection/store/artifact owner and every named writer and
  downstream consumer path.
- Reran the isolated proof successfully and verified every retained bundle hash
  with `sha256sum -c SHA256SUMS` from the bundle directory.
- Confirmed from the pinned handler that it reads the request before `time.Now()`,
  signs `Accuracy=1s`, copies the nonce and accepts configured request policy OIDs.
  The OID is therefore a consistency check, while profile approval supplies the
  operator-policy trust decision.
- Confirmed that no causal-v2 writer, protected receipt binding or reader dispatch
  exists in the runtime. Existing v1 tests and owners are supporting evidence, not
  verification of the successor.

## Resolution audit against the final synthesis

The final prospective design resolves all three original findings. The findings
above remain the record of the candidate package that I reviewed; this disposition
does not turn the unimplemented design into runtime evidence.

1. **Finding 1 is resolved.** The direct-entry section now requires one canonical
   candidate descriptor, carries its digest through F15 and every direct
   F11/F12/F13/F14/F16 constructor, validates it before discovery or external work,
   and binds every dependency and output to it. The shared owner chooses protocol
   semantics, and missing context cannot default to v2. Its cross-version predicate
   also scans old and new timing-bearing candidate associations and transactionally
   pins the first actual state. See
   `docs/design/causal-matchweek-selection-witness.md:336-382` and
   `.audit/issue-79/implementation-issue.md:80-91`.
2. **Finding 2 is resolved.** Authority activation now comes from an immutable
   repository-approved profile plus authenticated activation/withdrawal state.
   TUF authenticates the approved pins and historical constraints only. The design
   expressly refuses missing activation, rollback floors, or ambiguous restored
   history and does not derive current update-start time or latest revocation state
   from the token under review. Known authenticated compromise or withdrawal makes
   present qualification refuse while preserving the occupied historical record.
   See `docs/design/causal-matchweek-selection-witness.md:229-252` and `:264-288`.
3. **Finding 3 is resolved.** `_ResearchOperation._begin_witness` is available only
   after a confirmed fresh `selection_committed` transition and constructs and
   consumes the sole operation-bound request attempt. The private transport accepts
   only that attempt. `_accept_witness` matches the exact attempt, winning graph,
   query, nonce, profile, and evidence before enabling one receipt attempt. See
   `docs/design/causal-matchweek-selection-witness.md:108-138` and
   `.audit/issue-79/implementation-issue.md:42-47`.

### Remaining warning: a token cannot reveal whether its source clock was smeared

Location: `docs/design/causal-matchweek-selection-witness.md:254-262` and
`.audit/issue-79/implementation-issue.md:59-62`.

The final text says to reject smeared representations. RFC3161 `GeneralizedTime`
has no field that identifies the server's clock discipline. A server using a leap
smear can encode an ordinary UTC-looking `Z` value, so a verifier cannot distinguish
that value from unsmeared UTC by parsing TSTInfo. The design already has the premise
needed for its proof: the approved operator complies with the pinned accuracy and
UTC/leap policy. It should describe absence of smear as part of that explicit source
premise, not as a syntactic condition the verifier can independently test.

Keep the enforceable parser rules: refuse non-UTC syntax, `:60`, unsupported or
ambiguous leap encodings, and intervals crossing a UTC day boundary. If detecting
smear independently is required, this authority profile is insufficient and must
refuse rather than claim detection. This warning does not reopen the causal proof
under its stated honest-approved-authority premise.

With those dispositions, I find no remaining architecture blocker. Candidate A
remains the correct base and Candidate B's remote registry remains unnecessary.
The scores above are the historical scores of the candidate submissions; the final
synthesis adds the missing direct-context, trust-lifecycle, and private-transition
contracts. Production refusal remains required until the protected v2 owner and all
successor writer/reader tests exist.

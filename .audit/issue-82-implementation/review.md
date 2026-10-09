# Issue #82 review

The review compares the worktree with `a65c033160dd1b6e50a5bf69e9c7e0aecb4e8bf0`.
Its scope is the immutable causal candidate, every F11–F16 writer, cross-version
occupancy, and real graph admission by the existing #81 owner.

## Interrogate

Four reviewers examined the same scope using the interrogate rubric:

- A: `gpt-6.1-sol`, max reasoning. Completed review and final standards review.
- B: `gpt-5.6-sol`, max reasoning. Reported a coordinator publication gap before
  its usage limit prevented completion. This review is partial.
- C: `gpt-6-sol`, xhigh reasoning. Completed review.
- D: `gpt-6-astra`, max reasoning. Completed review and final spec review.

The harness could not resolve the skill's default model names. Available models
provided the independent reviews. Changing unrelated skill configuration is
outside this issue.

### Acted on

- A/B: Guard historical F11 publication and all run metadata, staging cleanup,
  and completion artifacts against a competing candidate and occupied selection.
- A: Compute and compare the complete F13 input binding before its publication,
  preserving exact partial-input retries.
- A/C: Dispatch F11 evidence and history by exact media/schema pairs.
- A/D: Replace F16's writable coordinator construction with reader-safe F15
  identity validation. Read-only graph replay cannot obtain writer authority.
- A: Require an explicit owner for direct causal weather acquisition, including
  the public helper and builders without a health repository.
- C: Preserve observed weather when a known pre-T publication has an advisory
  retrieval timestamp after T. Unknown publication remains UNKNOWN.
- D: Replace the large OR-based exact-history query with `json_each`, avoiding
  SQLite expression-depth limits while excluding later catalog discovery.
- D: Distinguish F16 decision-policy references from F07 policy associations in
  the shared occupancy predicate.
- D: Validate and compute successor F14 dependencies before publishing its input.
- A: Extract F11/F13 contract codecs and immutable run input validation to keep
  stage modules within their existing size boundary.

The final reviews found no remaining correctness or spec blockers. A noted,
nonblocking standards concern is the repeated contract classification in the
occupancy predicate. Its supported versions are explicit and unsupported versions
refuse; consolidating that table is not required for this delivery.

## Code review: standards

No hard documented standards breaches were found. The implementation uses the
glossary and ADR0003's explicit unqualified candidate model. The final standards
review confirmed that caches contain immutable decoded identities and associations.
Every admission still queries mutable run rows, the artifact catalog, and the
selection slot.

## Code review: spec

No remaining missing, partial, or incorrect #82 requirements were identified.
Exact health preimages cover the SQL-backed F05/F09 references in the actual graph.
CLI run/resume dispatch carries explicit candidate identity. Reader reconstruction
does not construct a coordinator. No #83 consumer or #84 integrated proof is added.

## Diagnosing the historical interruption regression

The first historical batch passed 11 cases, then the existing
`test_f15_partial_resume_cannot_execute_a_missing_writer_after_t` raised its
intentional KeyboardInterrupt outside the coordinator's interruption handler.
The new metadata guard observed the historical stage clock inside run creation.

The owner now supplies `candidate_run_guard`. Causal metadata retains the full
causal admission guard. Historical metadata checks occupancy, vacancy, and pinned
boundary/profile/policy without invoking a stage clock. F15 entry and actual F16
stage/publication timing checks remain in place. D reviewed this fix and found
no admission or occupancy gap. The fresh historical batch rechecks that regression.

The targeted historical F11 retry case also caught replacement of the repository's
legacy publication hook. Legacy F11 now attaches the owner's guard to that same
ArtifactStore instance. The retry test keeps its original hook, and the transaction
still rechecks vacancy and cross-version occupancy.

The final writer matrix also exposed two incorrect test expectations: exact F14
input replay returns the existing decision without new computation, and a missing
F12 constructor context raises its own F12Error. Targeted reruns check the corrected
assertions. F11's media/schema rejection previously wrapped its own domain error
as a generic malformed-contract error; it now preserves that precise rejection.
The malformed-media test tried to update protected metadata and correctly hit
the store's immutability trigger. It now publishes incompatible versions with
distinct digests, exercising reader refusal through the real publication API.

The consumer caller trace found one additional missing-context shortcut:
`selected_for_boundary` let a default historical owner resolve a causal selection.
That writer lookup now requires an explicit candidate digest for a causal slot.
Named read-only replay and inspection remain available. A confirmed this fix also
keeps the existing CB01/F19 consumers refusing until #83 without changing them.
The test rejects before graph replay, and both real selected-state cases recheck
the same boundary.

The complete matrix found one further reader/writer coupling: retained-history
loading constructed `WorkloadScheduleRecorder` merely to query schedule events.
Its writable-store check rejected real graph replay through a query-only store.
The minimized public-reader test failed before the fix. The existing SELECT,
ordering, exact-revision filter, and row decoding now live in a query-only helper.
The recorder delegates reads and retains its writable constructor and transaction
guards. A and D reviewed this final delta and found no authority or historical
compatibility blocker. The focused regression also retains a cup schedule event
and checks that read-only history equals the healthy-store history.

## Blast radius

The safety facts are executable tests, not caller inventories:

- Only the first guarded timing-bearing publication pins a candidate. Tests
  exercise descriptor-only publication, competing descriptors, dormant historical
  guards, and a mismatch detected inside the actual SQLite transaction.
- Vacancy and first-state checks remain live at each mutation boundary. Direct,
  reentrant, partial-resume, selected, and terminal-unqualified cases check that
  acquisition or alternate artifacts cannot pass these boundaries.
- Stored reader context grants no writer authority. Tests exercise catalog scope
  refusal and real graph replay through a query-only connection.
- The #81 owner binds the complete actual F15/F16 graph, including F12 weather
  attempts and protected canonical health preimages. Incomplete and mixed graphs
  refuse. Synthetic witness transport is used only at the existing test seam.
- `compatibility-proof.py` executes the pre-#82 source and current historical
  writers against copies of the same offline store. It compares every canonical
  artifact byte, the manifest, F15 input identity, and F13 engine identity.
- The #81 witness, trust, selection protocol, Store, and ArtifactStore source files
  are unchanged from the base. Focused protocol seam tests retain their existing
  protected-receipt and terminal semantics.

All execution uses isolated temporary stores and offline fixtures. There is no
running production application proof, live store access, or production activation.

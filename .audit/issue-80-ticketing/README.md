# Issue 80 decomposition record

Date: 2026-10-08. This delivery creates implementation tickets and repository
tracking only. No application code or tests are implemented.

[The child plan](../../docs/design/causal-matchweek-implementation-tickets.md)
maps all 18 original acceptance criteria. The parent remains OPEN. Four native
sub-issues form #81 → #82 → #83 → #84, with #80 blocked by #84. Its existing closed
#79 prerequisite is preserved. Only #81 receives `ready-for-agent`; the parent
readiness label is removed.

The user's explicit four-part breakdown and instruction to create children provide
authorization to publish without the skill's optional breakdown approval loop.
The instruction to update #80 overrides to-tickets' default prohibition on changing
a parent. Scope remains the accepted architecture; no redesign or activation is
performed.

## Retained tracker records

- `parent-before.json` preserves the original title, body and OPEN state.
- `child-01.md` through `child-04.md` contain the published child bodies.
- `children.json` records issue numbers, titles, URLs and blocking order.
- `parent-after.md` retains original acceptance/restrictions and appends the plan.
- `tracker-verification.json` records final native links, gates, labels and states.

Read #80 and its empty comments, ADR 0003, the full causal design, glossary,
tracker/triage/domain instructions, and #75–#78 bodies and completion comments.
Inspected research identity/admission/private Store operations, F13 dispatch,
#76 direct/resume tests, #77 compatibility/denominator/F19 tests and #78 integration.
Historical implementation commits are 5c8d56a, 53bb02c, f528e31 and 204ce62.

## Blast-radius findings and proof limits

The safety fact for this delivery is that no implementation changes. Every tracked
source and test file was compared byte-for-byte to HEAD by a script; all matched.
A script imported the real logical_matchweek_id, selection_slot and completion_slot
functions, checked that no signature accepts protocol version, verified deterministic
logical identity, and verified distinct selection/completion slots. Both checks
passed. This reaches executed real-code evidence for the current identity boundary,
not proof of unimplemented cross-version transactions.

The boundary must remain stable because selection/completion uniqueness is keyed
by these functions in `src/matchvet/research_identity.py:6`, not by protocol. Owner
admission currently calls F16 replay in `src/matchvet/matchweek_research.py:180`;
#81 owns protocol admission, while #82 supplies real successor stage dispatch.
Unsupported intermediate stage graphs must refuse. No synthetic fixture bridge can
become a production graph bypass.

F13's engine contract and identity are generated in `src/matchvet/f13.py:76` and
`:118`. Global mutation can invalidate historical hashes, so #82 freezes historical
identity and adds explicit successor dispatch. Existing F13 schema 2 cannot be
reused as the causal successor identity. Transactional candidate occupancy is
another real boundary: excluding old media types would bypass old partial chains.
#82 therefore owns all old/new F11/F12/F14/F15 associations and direct/resume gates.
These successor safety claims remain unproven until their child tests execute.

CB01 core/software commitment identity and full denominator are downstream facts
that must survive. Ran the existing real-code checks:

```sh
.venv/bin/python -m pytest -q \
  tests/test_issue77_history.py::test_released_cb01_software_and_method_010_remain_byte_identical \
  tests/test_issue77.py::test_corrected_denominator_exists_without_f16_selection_or_attempts
```

Result: `4 passed in 17.56s`. The identity test covers CB01 core, trust verifier and
released methodology bytes. The denominator test verifies availability without
F16 selection/attempts. These baseline properties are cleared for this tracking
change; v2 compatibility and F19 lineage still require #83/#84 successor proof.

An earlier batch also selected alternate-proposal stable-slot and protected generic
publication tests. It was interrupted after 338.11 seconds during fixture setup in
provider_health.py; no tests ran and no passing claim is made for that batch. This
is why the child tickets require focused Termux-safe batches and why cross-version
slot/publication proof is left explicitly to #81/#84 rather than inferred here.

No future signed-event, trust/nonce/imprint, crash/no-backfill or v2 integrated safety
fact is marked complete by decomposition. #84 must replace planned coverage with
exact runnable evidence. No live store, fixture or TSA/TUF request was used.

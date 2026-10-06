# Adversarial review

Scope: the postcommit completion protocol, its temporary-store proof and proposed #75
acceptance wording. This review does not accept production #75 implementation.
All reviewers received the same intent and evidence pointers in `review-prompt.md`.
The initial usage-limit failures produced no review findings; subsequent completed
reviews are the ones recorded here.

## Independent reviewers

| Reviewer | Result before final refinement |
| --- | --- |
| gpt-6-astra | No findings within the stated design/proof scope. Explicitly retained synthetic graph, modeled guard, hardware and UTC accuracy limitations. |
| gpt-6-sol | No findings within the stated design/proof scope. |
| gpt-6.1-sol | No findings within the stated design/proof scope; noted absence of injected commit I/O errors and the prototype's extra postcommit sync barrier. |
| gpt-5.6-sol | Four warning-level proof gaps, below. |

## Act on

Root accepted all four warnings and authorized changes only in the throwaway proof:

1. Ambient `_authorized` allowed callbacks to borrow publication authority. Replace it
   with Store-scoped nonreentrant operation ownership and exact-role private publication;
   ordinary publication must always guard the reserved mappings.
2. Commit exceptions were not injected. Exercise exceptions before and after selection
   and receipt commits. Uncertain selection return gets no authority. A receipt error
   permits only read-only verification of an already committed receipt, never retry.
3. Orphan selection retry and precommit reuse synchronization were not demonstrated.
   Sync fresh/reused object files and ancestors before the catalog transaction. Retry
   the unindexed selection object in a new pre-T operation, without adopting any receipt.
4. The fixed synthetic slot guard was stronger than the accepted UUIDv5 mapping guard.
   Use the documented derivations. Demonstrate that a forged different Matchweek can
   poison a slot but cannot qualify it; this deliberate false refusal is permitted.

The protocol ordering argument survives these findings. The original proof did not
establish these four implementation behaviors; its outputs remain preserved as earlier
checkpoints. Final verification is recorded after the refined executable completes.

## Retained limits

- Synthetic dependency admission is not full F16/F06/F07/F11/F13/F14 integration.
- Modeled publication guards are not production ArtifactStore/StoreTransaction guards.
- Process exits and injected exceptions do not simulate hardware power loss.
- Deterministic clocks do not establish a live UTC uncertainty bound.
- Raw SQL, reflective Python, hostile storage writers and restored process memory remain
  outside the application trust boundary.

No warning was dismissed or silently treated as verified. The final design makes
nonreentrancy, commit-error reconciliation, sync ordering and the guard's availability
tradeoff explicit.

## Targeted design refresh

gpt-6-astra reviewed the revised nonreentrancy, ambiguous-commit rules, clock-bound
impossibility and authoritative-history premise. No substantive gap was found in the
conditional protocol. Existing open/recovery preserves the catalog and opens failures
read-only. Backup restoration refuses an existing destination but can create a writable
separate copy. Not promoting that copy as replacement authority is an explicit trusted
operator requirement; current restoration APIs do not enforce a global history ledger.
This refresh did not execute the still-pending refined prototype.

## Warning closure after refinement

gpt-5.6-sol returned the final 47-case proof and a targeted readback closing all four
warnings in the throwaway model:

- The Store-attached operation tuple binds the exact ArtifactStore instance, lexical
  cookie, PID and Store lifetime. Public publication always guards derived role slots;
  the private publisher validates operation and role, rejects nesting, and calls the
  base publisher directly. The reentrant callback refuses both nested seal and public
  reserved publication while the outer operation qualifies.
- Commit errors are injected before/after `super().commit()` for selection and receipt,
  including a receipt error after its post-T commit. Selection errors mint no authority;
  receipt errors cause one read-only replay and no second publication. Attempt counts
  prove one selection and at most one receipt attempt.
- Fresh and reused protocol files and all containing directories through the private
  boundary are synchronized before the catalog transaction. The commit hook asserts
  that ordering. A saved unindexed selection object can qualify through a fresh pre-T
  operation; orphan receipts remain inadmissible. The postcommit extra sync was removed.
- Logical and role slots use the documented UUIDv5 formulas. A generic wrong-Matchweek
  receipt may poison the real slot, but strict domain replay refuses it permanently.

Two additional named cases refuse a never-selected candidate exactly at T and an orphan
selection retry after T, with zero publication attempts and no occupied role indices.
Root independently reruns this exact final script and records that outcome separately.
This closure covers the modeled behaviors, not production API enforcement.

## Non-green refinement history

The first orphan retry ran in the parent without the deterministic publication-clock
patch. Its new digest differed from the saved stamp-90 object, so the reuse assertion
failed. After clock correction, the parent still used the stock SQLite connection;
commit counters stayed zero and the ordering hook was not exercised. Moving the retry
through the normal child subprocess supplied both the deterministic clock and patched
connection. The subsequent 45-case checkpoint passed, then the two explicit initial
cutoff-gate cases produced the final 47-case proof. These were instrumentation failures;
none is counted as a passing proof run.

## Independent final refresh

gpt-6.1-sol reviewed the final specification, refined script, 47-case report and warning
closure without executing stores or changing files. No substantive findings were found
within the stated synthetic scope. Publication guards, full F16 admission and a trusted
live clock remain future production work. Root's independent run passed all 47 cases,
with 8 reducer walkthroughs, Ruff check/format and diff checks; see `checks-final.json`.

# LF14 Standards review

Baseline: `285054c5eeb3e04b0c5cd237783534161b160905`; reviewed `git diff HEAD` for LF14 files plus the untracked integrity module, regression tests, and design document. Existing unrelated `CONTEXT.md` edits are excluded. Sources: `AGENTS.md`, `docs/agents/domain.md`, `CONTEXT.md`, issue-tracker/triage conventions, and the code-review skill smell baseline. Tool-enforced checks are excluded.

**Documented-standard breaches: none found.** The implementation uses Fixture Revision, Fixture Scope, Fixture Coverage Assessment, and membership freeze vocabulary consistently with `CONTEXT.md`. Optional versioned integrity facts preserve the documented append-only history contract. No ADR conflict was found.

**Judgement calls, nonblocking:**

1. **Possible Duplicated Code.** `src/matchvet/matchweek_membership_repository.py:1431–1475` and `:1479–1551` both construct assertion support/semantic maps, select the maximum authority/time pair, then run identical semantic conflict comparison. The new comprehension beginning `semantic_values = { ... }` and the new `semantic_values_conflict(...)` branch occur twice. A shared helper returning controlling conflicting predicates/IDs would reduce the risk of creation diagnostics and replay validation acquiring different semantics.

2. **Possible Primitive Obsession / Mysterious Name.** `src/matchvet/matchweek_membership_integrity.py:142–175` stores eleven revision/fixture fields in `fixture`, then indexes them throughout the validator. Mapping checks at `:211–217` use `mappings[0][5]` and `[6]`. Named records or explicitly aliased row dictionaries would make semantic evidence checks easier to inspect and less coupled to SQLite column order. This follows existing repository style, so it is a maintainability suggestion, not a violation.

**Documentation accuracy:** `docs/design/lf14-f06-semantic-integrity.md:23` names `compatible_revision_facts(left, right)`, which does not exist, and sketches `project_conflicts(..., snapshots)` although the actual seam takes assertion IDs and semantic values. Update the sketch to the implemented interface before committing.

Count: 0 hard breaches; 2 nonblocking smell findings; 1 documentation correction. No standards finding requires a behavioral change.

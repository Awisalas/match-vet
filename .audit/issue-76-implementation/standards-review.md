# Standards review

Reviewed the working diff against `6470abf2d1f8df4ebe01d2b9f110c5ad01e2e483` with `git diff 6470abf -- src tests docs`. No commits exist beyond the fixed base. Read AGENTS.md, docs/agents, GLOSSARY.md, ADR 0001, pyproject.toml and the applicable review/writing skills. No tests or production files were changed for this review.

No documented coding-standard breach found. Tooling-enforced rules were excluded.

One resolved finding and one optional judgement finding:

1. **Resolved: request-specific mutable state.** The earlier F11 hunk replaced `self.artifacts` only for corrected builds, which could leave its cutoff guard installed for a later legacy build on the same instance. The revised `src/matchvet/f11.py:344` captures `artifacts = self.artifacts` and replaces only that local variable for corrected work. All three build publications use the local publisher. F13 and F14 likewise keep guarded publishers local; F13 passes its publisher through evaluation and retention. Static re-review closes the finding. This reviewer did not execute a test.

2. **Possible Duplicated Code / Feature Envy.** F11 (`f11.py:194` and `:288`), F13 (`f13.py:362`) and F14 (`f14.py:397`) repeat `selected_for_boundary`, local import of F16, `F16MatchweekProcessor(...).replay_manifest(selected.f16_manifest_digest)`, and selected-row navigation. The shared authority already replays that F16 graph to qualify the selection. Returning exact selected references from that owner would remove downstream-to-orchestrator imports and put selection traversal in one place. This is a maintainability suggestion, not a required architecture change.

The cutoff comparison and trusted-clock validation remain owned by MatchweekResearchRepository. Writer modules call that owner rather than reimplementing the deadline. Their additional timestamp comparisons validate source eligibility, which is a separate concern.

Summary: zero documented breaches; zero blocking findings. The concrete F11 finding is resolved statically. The optional selected-reference traversal suggestion is acknowledged and can remain outside this issue's settled architecture.

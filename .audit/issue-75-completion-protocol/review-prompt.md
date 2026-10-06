# Adversarial review intent

Prove exact complete logical-Matchweek selection and reference graph are durably assigned
before T, with a repository-owned postcommit UTC upper bound strictly before T. Permit
only that same operation's one-use ephemeral authority to persist a later receipt. Restart
must never backfill or reselect; ambiguous indexed selection without valid receipt loses
the Matchweek forever. Use existing protected SnapshotManifest/index schema, with explicit
future guarded publication APIs. No production implementation or #76 work in this task.

Read docs/design/matchweek-selection-completion-protocol.md,
docs/design/matchweek-wide-evidence-cutoff.md and docs/adr/0001-matchweek-wide-evidence-cutoff.md.
Read .audit/issue-75-completion-protocol/prototype_protocol.py, proof-results.json,
synthesis.md, grounding.md and docs/research/matchweek-selection-completion-protocol-2026-10-06.md.
Prior proof directory is READ ONLY and not overwritten. Scope is protocol+proof, not
implemented full F16 admission or live clock provider. No live stores/network/TSA.

Apply the SAME review rubric and code-quality lens from:
/data/data/com.termux/files/home/.agents/skills/interrogate/references/rubric.md
/data/data/com.termux/files/home/.agents/skills/interrogate/references/code-quality-review.md
Use reviewer-prompt.md in that same directory as template. Severity critical/warning/nit,
concrete location, trace/evidence and optional fix. Challenge every stated crash/clock/
capability/reopen/backfill/concurrency/durability/graph/cutoff/alternate-proposal case.
Return only real findings; zero findings valid. Do not auto-apply or edit anything.
Call out scope-limited proofs; do not demand production implementation in this design run.

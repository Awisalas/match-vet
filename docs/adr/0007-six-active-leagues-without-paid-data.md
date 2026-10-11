# Six active leagues without required paid data

Date: 2026-10-11.
Status: accepted product decision; #98 scope and F01/F02/F03 are implemented offline.
F06/F07 policy3 is implemented offline in #99; end-to-end successor operation remains pending.

MatchVet's active recommendation scope is exactly ENG Premier League, ITA Serie A,
ESP LaLiga, GER Bundesliga, FRA Ligue 1, and POR Primeira Liga, in that order.
Belgian Pro League leaves active scope because the bounded official and free-source
qualification work found no qualified complete-current automated contract. There
is no replacement league, dynamic scope, or Belgian UNKNOWN placeholder in new runs.

Runtime must remain completely operable without a paid football/data provider or
paid API subscription. This constraint concerns required data dependencies. It
does not ban ordinary hosting, device, or network costs. Free access must still
satisfy the exact evidence contract; risk acceptance does not supply completeness.

This explicitly supersedes the active seven-league premise in the original
2026/27 product specification, glossary, and ADR 0001. Historical seven-league
versions keep their identities, bytes, digests, denominator membership, readers,
and replay semantics. Belgian canonical teams, mappings, captures, and research
remain retained. The common Matchweek window, explicit 21600-second cutoff rule,
UNKNOWN, F01/F06 evidence rules, and ADR 0003 occupied-week semantics do not change.
ADR 0006 remains byte-for-byte unchanged with its separately pinned risk policy.

Use an explicit successor active-scope contract for new six-league work. Preserve
the legacy seven identity catalog and dispatch by retained contract versions.
Changing the shared catalog in place breaks old F01 replay. The smallest proposed
storage design uses a new F01 version and F06 membership policy3 within the existing
freeze envelope. Offline storage evidence supports no migration for that design;
F01 successor admission and persistence use that representation without migration.
F06/F07 policy3 uses the same representation without migration. Prospective
capture/cohort integration and release qualification remain pending in #100/#101.

See the [blast-radius audit](../research/six-scope-blast-radius-2026-10-11.md)
for exact contracts, proof limits, implementation tickets, and activation blockers.
This decision grants no live acquisition, source or causal authority, fitting,
PLAY, or Product Promotion.

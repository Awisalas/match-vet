# Product V2 direction

MatchVet researches each eligible match before making a betting decision. It evaluates every enabled Betting Preference and returns exactly one strongest justified Primary Recommendation, or AVOID MATCH when none is justified. AVOID MATCH is a first-class outcome. MatchVet never manufactures a recommendation. Research exists to support the decision, not just to display statistics.

## Preferences and recommendations

Keep the founder's current allowed preferences. Exclude Unders, cards, Over 0.5, Under 0.5, and trivial or "baby" selections. Keep the future user Preference Profile separate from the engine's long-term market capability. Do not add markets now.

Odds do not drive ranking or recommendations. MatchVet may retain odds later as evaluation benchmarks only. Recommendations remain pre-lineup.

## Research and evidence

Product V2 uses a Matchweek Membership Freeze to define eligible fixtures and a per-match Match Evidence Cutoff to bound each match's research. This replaces the planned V1 single Matchweek Research Cutoff architecture. The numeric lead time for either freeze or cutoff is undecided.

Missing evidence remains UNKNOWN. MatchVet never infers ABSENT from missing data. Preserve evidence provenance, immutability, auditability, uncertainty, recovery, and RESEARCH_ONLY safeguards. Keep historical V1 artifacts valid under their original versions.

## Delivery constraints

The project has no budget. Product V2 must require no paid football data or infrastructure. Use free, open, and official sources now, with replaceable provider boundaries for later.

Fix the live workflow before adding major features. Upcoming fixture acquisition is unreliable, and `matchvet run` completes lifecycle phases without running the full analysis pipeline. Later features include Trend Intelligence, Comparable Match Intelligence, Regime Intelligence, Failure Pattern Intelligence, automatic settlement, source health, and a transparent historical MatchVet record.

The eventual product is an Android, iOS, and web subscription app. Termux and the CLI remain the engineering and operator interface. Do not build subscriptions yet. Do not start T20 Production Promotion until Product V2 has a working live pipeline and sufficient genuine chronological evidence.

## Build order

1. Live workflow
2. Architecture cleanup
3. Intelligence features
4. Genuine chronological evidence and revalidation
5. App/service layer
6. Beta
7. Production Promotion
8. Subscriptions and launch

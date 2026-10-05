# Match vetting

MatchVet evaluates upcoming football matches in configured domestic top-flight leagues against every Betting Preference in the active Preference Set. It returns one Primary Recommendation only when the candidate with the highest Selection Strength passes the Selection Policy; otherwise it returns AVOID MATCH.

## Scope

**Target League**:
A configured domestic top-flight competition and season whose upcoming fixtures are eligible for recommendations. Cups, continental competitions, friendlies, and lower divisions are excluded unless separately configured.

**2026/27 Target League Set**:
The fixed recommendation scope for the 2026/27 season: Premier League, Serie A, La Liga, Bundesliga, Ligue 1, Liga Portugal, and Belgian Pro League. The set is based on the UEFA five-year association ranking and does not change during the configured season.

**Matchweek**:
The user-facing Friday-through-Monday calendar slate containing every eligible Target Match in the seven configured Target Leagues whose scheduled kickoff falls within that window. Official league round numbers do not control membership; a rescheduled fixture outside the window belongs to another Matchweek.

**Fixture Scope**:
One configured Target League, season, and requested Matchweek window.

**Provider Attempt**:
One attempt to acquire schedule data for a Fixture Scope, retaining its provider, capability, retrieval time, outcome, and any source capture identity and digest. A captured response does not by itself establish complete scope coverage.

**Provider Coverage Evidence**:
A source-backed claim about which part of a Fixture Scope a captured provider response covers, including the basis and any required partitions or pagination details.

**Scope Coverage State**:
The F01 assessment state for one Fixture Scope: COMPLETE, CONFIRMED_EMPTY, PARTIAL, UNKNOWN, or STALE. F01 defines the evidence required for each state; persistence and later consumers preserve that state.

**Fixture Identity Resolution**:
The F01 result that records whether a source candidate is linked to a canonical Fixture Revision or remains unresolved, together with its source and revision references.

**Coverage Freshness Result**:
The result of applying a versioned freshness policy to identified Provider Coverage Evidence. The policy identity and result are retained; F01 chooses no numeric freshness threshold.

**Fixture Coverage Assessment**:
The immutable, versioned F01 result for all seven Fixture Scopes in one season and Matchweek. It retains scope states, provider attempts and coverage evidence, Fixture Revision references, fixture identity results, freshness results, aggregate Matchweek Schedule State, and a stable digest.

**Matchweek Schedule State**:
The F01 aggregate coverage state for the seven Fixture Scopes: COMPLETE, CONFIRMED_EMPTY, PARTIAL, UNKNOWN, or STALE.

**Fixture Revision**:
An append-only, source-backed statement of a fixture's canonical identity, teams, competition, venue, kickoff, and status as known at a particular time. A later revision may supersede the current view but never overwrites an earlier revision.

**Frozen Matchweek Membership**:
The V1 T05 immutable set of Target Matches established at the Matchweek Research Cutoff from each fixture's highest-authority, latest cutoff-valid Fixture Revision. It retains the controlling revision ID and digest and never changes when later schedule information arrives.

**V2 Matchweek Membership Freeze**:
An immutable, assessment-specific record of the fixtures assigned to one Friday-through-Monday Matchweek from its seven Fixture Scopes. It names the exact Fixture Coverage Assessment, versioned membership policy, and controlling Fixture Revision for each resolved candidate. Later observations and later freezes do not change it. Its creation time is not a Match Evidence Cutoff.

**V2 Matchweek Membership Observation**:
An append-only link from a V2 Matchweek Membership Freeze to a later exact Fixture Coverage Assessment, retaining later fixture facts and any determinable changes without changing original membership.

**Indeterminate Fixture Membership**:
The audited state used when MatchVet cannot resolve a fixture's canonical identity confidently at the Matchweek Research Cutoff. It is not a Target Match, receives no match decision, and does not count in normal recommendation-coverage metrics.

**Post-cutoff Fixture Appendix**:
The append-only audit timeline for fixtures first added to the Matchweek window and for Fixture Revisions learned after the Matchweek Research Cutoff. It can support evaluation or Research-only analysis but cannot alter Frozen Matchweek Membership or create a retroactive recommendation.

**Target Match**:
An upcoming fixture in a Target League and Matchweek that is eligible for a PLAY or AVOID MATCH outcome.

**Research Context**:
Relevant matches and events outside the recommendation scope that may inform fatigue, congestion, rotation, injuries, form, or tactical change. Research Context can affect Vetting but cannot receive a recommendation unless it is also a Target Match.

**Historical Match**:
A completed match used for research, backtesting, calibration, or evaluation rather than a current recommendation.

**Pre-lineup Recommendation**:
A recommendation finalized from evidence available at the Matchweek Research Cutoff, before confirmed starting lineups are released, and never refreshed or revised afterward. Expected lineups and unresolved player availability remain part of its uncertainty.

**Matchweek Research Cutoff**:
The single point at which all research and evidence collection for an entire Matchweek must be completed and its information state frozen, initially six hours before its earliest eligible kickoff. Every Target Match uses that same frozen state. No later collection, refresh, replacement, or research can change a frozen recommendation. The lead time is an explicit, versioned policy parameter; later Target Matches receive greater Evidence Freshness and Probability Uncertainty penalties where time-sensitive evidence ages.

**Match Evidence Cutoff**:
A match's immutable reference to the common Matchweek Research Cutoff, tied to its exact frozen membership, controlling Fixture Revision, and Match Evidence Cutoff Policy. Every included match in the same frozen Matchweek has the same evidence boundary. The boundary is separate from Matchweek Membership Freeze and its creation time.

**Match Evidence Cutoff Policy**:
A versioned timing rule and explicit lead time that determine the common Matchweek Research Cutoff from the earliest exact eligible kickoff in the frozen Matchweek. A changed configuration creates separate cutoff state and never changes a retained cutoff or permits a frozen recommendation to be refreshed.

**Post-cutoff Evidence**:
Material information published or collected after the Matchweek Research Cutoff. It cannot alter the frozen recommendation but is recorded during Historical Evaluation to measure whether the cutoff policy systematically causes avoidable failures. Earlier publication does not make later collection eligible for the frozen recommendation.

**Canonical Timestamp**:
The UTC time retained for every fixture, cutoff, and item of evidence. User-facing Matchweek boundaries and times use Africa/Lagos, while a fixture's official local kickoff timezone is also retained when available.

## Preferences

**Preference Set**:
The fixed, versioned collection of every enabled market selection and, where applicable, its side and exact line, that MatchVet vets against every Target Match. Items change only through an explicit Preference Set version change.

**Preference Profile**:
The immutable V2 snapshot of the founder's enabled Betting Preferences, selected from the approved T10 catalog and identified independently from engine market capability.

**Engine Market Capability**:
The versioned set of market contracts the engine can represent and evaluate. Capability does not imply that a Betting Preference is enabled in a Preference Profile.

**Initial Preference Set**:
The first Preference Set contains Home Win, Draw, Away Win; Match Goals Over 1.5, 2.5, and 3.5; Home Team Goals Over 1.5 and 2.5; Away Team Goals Over 1.5 and 2.5; First-Half Over 1.5; Second-Half Over 1.5; Double Chance 1X, X2, and 12; and Asian Handicaps Home or Away 0.0, +1.0, +1.5, -1.0, and -1.5. Its corner preferences are Full-Match Total Corners Over 8.5, 9.5, and 10.5; Corner Match Winner Home, Draw, and Away; and Home Team or Away Team Corners Over 3.5, 4.5, and 5.5.

**Prohibited Preference**:
A market or exact line that cannot belong to any Preference Set or appear as a Primary Recommendation, Correlated Secondary Fit, or fallback. Every Under market, every Over 0.5 line, and Under 0.5 are prohibited across all Preference Families.

**Trivial Preference**:
A structurally easy market or line whose Historical Baseline makes success near-automatic, rather than a candidate whose high confidence comes from unusual match-specific strength. Total Corners Over 2.5 is an example.

**Preference Family**:
A supported category of betting market: Match Winner, Match Goal Overs, Full-Match Total Corners Over, Corner Match Winner, Home Team Corners Over, Away Team Corners Over, First-Half Overs, Second-Half Overs, Asian Handicaps, Double Chance, Home Team Goal Overs, or Away Team Goal Overs.

**Betting Preference**:
A market selection in the active Preference Set, including its side and exact Supported Line where applicable, that MatchVet vets independently against every Target Match. Global acceptance rules do not belong to a Betting Preference, and no opposite side or unsupported market is implied.
_Avoid_: Bet type, pick

**Supported Line**:
A specific selection or threshold within a Preference Family that MatchVet recognizes as a Betting Preference.

**Asian Handicap Preference**:
A Betting Preference named by its backed side and signed line, such as Home -1.0 or Away +1.0. The Initial Preference Set excludes duplicate ±0.5 lines and every ±2.0 or wider line; a 0.0 line produces PUSH on a draw, while +1.0, +1.5, -1.0, and -1.5 remain subject to the Non-Triviality Gate.

**Duplicate Preference**:
A Betting Preference whose settlement outcomes reproduce another enabled preference under a different name. The initial Asian Handicap ±0.5 lines are excluded because -0.5 duplicates Match Winner and +0.5 duplicates Double Chance.

**Full-Match Total Corners Over**:
A corner preference predicting that the combined corners won by both teams will exceed an explicitly versioned Supported Line during regulation time plus stoppage time. Extra time and penalty shootouts are excluded.

**Corner Match Winner**:
A corner preference predicting whether Home, Draw, or Away will have the greater corner count during regulation time plus stoppage time, based on the teams' expected corner distributions and matchup. It is independent of general Match Winner probability; extra time and penalty shootouts are excluded.

**Team Corners Over**:
A Home Team or Away Team corner preference predicting that the named team's corners will exceed an explicitly versioned Supported Line during regulation time plus stoppage time. Home and away distributions are calibrated separately where Sufficient Samples exist; its predictive drivers remain separate from Full-Match Total Corners Over.

**Corner Grading Source Hierarchy**:
The deterministic source order for corner Settlement Results: final official competition or league event record, a suitable official federation or club match record, then one predesignated reliable statistical provider. MatchVet never switches sources based on which result favors its prediction and preserves the chosen source plus official correction history.

**Corner Triviality Baseline**:
The hierarchical Historical Baseline used by the Non-Triviality Gate for corner preferences, beginning with Corner Preference Family and exact line, then home or away role, Target League, and a relevant matchup subgroup only when each narrower level has a Sufficient Sample. Sparse subgroups inherit shared evidence, and broad averages cannot hide a near-automatic narrower context.

**Excluded Corner Preference**:
A corner market outside the active Preference Set. Corner Unders and Over 0.5 are prohibited, while corner handicaps, half-corner markets, and corner double chance require an explicit future Preference Set version.

**Correlated Preferences**:
Betting Preferences whose outcomes or supporting evidence materially overlap. Their agreement is not independent confirmation.

## Evaluation

**Vetting**:
The independent evaluation of every supported Betting Preference against a Target Match, including an active search for evidence that could make each preference fail.

**Preference Fit**:
The strength of the weighted predictive case that a Betting Preference will succeed in a Target Match, assessed independently of the Selection Policy. Supporting and opposing signals contribute according to their Signal Weight rather than by simple count.

**Historical Baseline**:
The out-of-sample success profile normally achieved by the actual Preference Family, Supported Line, and Settlement Result structure under evaluation. MatchVet never pools fundamentally different markets as though they shared one base rate; it specializes shared family and line evidence by Target League and exact line only when a Sufficient Sample exists, while older evidence loses influence when recency or a Structural Change reduces its relevance.

**Selection Strength**:
The market-normalized strength of a candidate based on its complete Settlement Distribution, Conservative Probability, improvement over its Historical Baseline, Data Quality, Probability Uncertainty, Model Agreement, Failure/Risk Assessment, and historical predictive reliability. It ranks only candidates that survive their settlement-appropriate mandatory Selection Policy gates and cannot compensate for a critical failure.

**Selection Policy Version**:
A frozen set of thresholds, gates, baselines, and ranking rules derived from historical development data and judged on future unseen matches. Any change creates a new version for later out-of-sample evaluation and cannot use results from the period judging the prior version.

**Production Promotion**:
Authorization for a frozen Selection Policy Version to issue PLAY after it demonstrates probability calibration, acceptable Brier score and log loss, controlled false positives, reliable uncertainty, subgroup robustness, stable mandatory gates, effective Non-Triviality Gate behavior, cutoff-policy performance, and reliable cross-family ranking on unseen chronological Matchweeks. Profitability and bookmaker-value metrics are excluded.

**Selection Policy**:
The shared acceptance principles for probability, uncertainty, Data Quality, Model Agreement, Failure/Risk Assessment, Research Sufficiency, Non-Triviality Gate, and veto conditions that a Preference Fit must pass before it can become a PLAY. Failure at any mandatory gate rejects the candidate; league-, market-, or line-specific calibration belongs in the policy only when sufficient historical out-of-sample evidence shows that it improves Prediction Quality.

**Non-Triviality Gate**:
The mandatory rejection of any Trivial Preference before Selection Strength ranking. It uses historical market and line base rates plus calibration, never bookmaker odds alone, and does not reject high confidence produced by unusual match-specific evidence.

**Primary Recommendation**:
The Betting Preference with the highest Selection Strength among those that pass the Selection Policy for a Target Match. Each PLAY has exactly one Primary Recommendation.
_Avoid_: Primary pick, tip

**Correlated Secondary Fit**:
A genuinely strong, non-primary Betting Preference that independently passes every Selection Policy gate and adds useful explanation of an overlapping view of the match. It is not an additional recommendation, cannot increase confidence through double counting, and cannot be a near-miss.

**Statistical Tie**:
The state in which a Selection Strength difference is not meaningful relative to the candidates' uncertainty. MatchVet breaks a Statistical Tie by lower uncertainty, then stronger Data Quality, lower Failure/Risk Assessment, and stronger historical reliability; user preference order applies only if they remain indistinguishable.

## Outcomes

**PLAY**:
The production match-level outcome used when at least one Preference Fit passes a Selection Policy Version with validated thresholds. PLAY depends on predicted success, not bookmaker price or expected profit; each PLAY qualifies independently, with no required or arbitrary maximum count per Matchweek.

**Research-only Candidate Ranking**:
A development output that orders candidates before validated Selection Policy thresholds exist. It cannot be labeled or counted as a production PLAY recommendation.

**AVOID MATCH**:
The valid match-level outcome used when no Betting Preference clears the Selection Policy. It has one primary AVOID Reason, may have supporting reasons and free-text explanation, and remains valid for every Target Match in a Matchweek, including when the whole Matchweek has zero PLAY outcomes.
_Avoid_: AVOID, no pick, skip

**AVOID Reason**:
A standardized explanation category for AVOID MATCH: insufficient probability, excessive uncertainty, insufficient Data Quality, incomplete research, Material Conflict, adversarial veto, Non-Triviality Gate failure, model disagreement, or no preference passed absolute gates.

**Withdrawn Recommendation**:
A frozen recommendation removed because its Target Match was postponed or cancelled after the Matchweek Research Cutoff. It receives a VOID Settlement Result rather than AVOID MATCH, while the original analysis remains available for audit and evaluation.

**REJECT**:
The preference-level outcome used when a Preference Fit does not pass the Selection Policy. A Target Match becomes AVOID MATCH only when every Betting Preference is rejected.

**Settlement Result**:
The result assigned to a completed recommendation under the exact rules of its Supported Line: WIN, LOSS, PUSH, VOID, and, when quarter lines are supported, HALF_WIN or HALF_LOSS. PUSH and VOID do not count as wins or losses in calibration.

**Corner Settlement Result**:
An abandoned match or missing complete authoritative corner record produces VOID unless the Supported Line's explicit settlement contract says otherwise. MatchVet never infers missing corners; later official corrections may change grading but cannot alter the evidence state at the Matchweek Research Cutoff.

**Settlement Distribution**:
The predicted probabilities across every possible Settlement Result for a Betting Preference. The Initial Preference Set supports WIN, LOSS, and PUSH where applicable; PUSH remains neutral and separate, and a PUSH-capable handicap must have sufficient Conservative Probability of WIN plus acceptable probability of LOSS rather than passing on WIN plus PUSH.

## Reporting and audit

**Preference Vetting Result**:
The retained pass or rejection status and reasons for one exact Betting Preference tested against one Target Match.

**Vetting Matrix**:
The complete set of Preference Vetting Results for every exact line in the active Preference Set against every Target Match. It remains in the audit record even when the user-facing report does not display it.

**Matchweek Audit**:
The complete record of every Target Match in a Matchweek, including PLAY, AVOID MATCH, and Withdrawn Recommendation outcomes, plus the full Vetting Matrix needed for evaluation.

**Matchweek Report**:
The concise user-facing view of a Matchweek Audit. It prioritizes Primary Recommendations, useful Correlated Secondary Fits, and major rejected alternatives without displaying the full Vetting Matrix unless requested.

**Recommendation Evidence Record**:
The retained basis for a Primary Recommendation: its exact Betting Preference and Supported Line, Estimated Probability, Conservative Probability, Selection Strength, Historical Baseline, Data Quality, Model Agreement, Failure/Risk Assessment, Supporting Case, Failure Case, important trends and matchup insights, material Evidence Provenance, major uncertainty or missing evidence, and why it outranked other qualifying candidates.

**Reproducibility Record**:
The identity of the frozen Matchweek analysis: Matchweek identifier and date window; Target League Set, Preference Set, Selection Policy, model or ensemble, and feature or research-rule versions; data snapshot or retrieval-cutoff identifiers; Matchweek Research Cutoff; Canonical Timestamps and Africa/Lagos display rules; and the software or Git commit identifier when available.

## Evidence

**Source Hierarchy**:
The evidence-type-specific ordering of source authority. Official competition and club sources lead for official facts, reliable structured data sources lead for statistics and events, and reputable specialist reporting supports injuries, availability, tactics, and team news.

**Evidence Provenance**:
The source, publication or observation time, and underlying origin of material evidence. MatchVet preserves provenance so authority, independence, and cutoff eligibility remain explicit.

**Independent Source**:
A source with a genuinely separate origin for a claim. Syndicated reports and sites repeating one underlying report count as one source.

**Signal Weight**:
The influence of an evidence signal based on its source reliability, freshness, match relevance, causal plausibility, independence, and historically validated predictive usefulness for the relevant Preference Family or Supported Line.

**Correlated Evidence**:
Signals that share underlying matches, events, player absences, reports, or a statistical derivation chain. MatchVet preserves their useful detail but discounts duplicate influence rather than treating them as independent confirmation.

**Qualitative Evidence**:
Sourced evidence about tactics, managerial decisions, expected roles, injuries, rotation, or similar context that is not primarily numeric. It may reshape, downgrade, or veto a Preference Fit, but cannot create PLAY alone unless its type has demonstrated predictive value and has sufficient quantitative or independent corroboration.

**Narrative Speculation**:
An interpretation that lacks adequate evidence, provenance, or demonstrated predictive relevance. It does not contribute to a Preference Fit.

**UNKNOWN**:
The evidence state used when MatchVet cannot establish a fact from suitable sources. Failure to find evidence never changes UNKNOWN into ABSENT.

**ABSENT**:
The evidence state used when reliable evidence affirmatively establishes that a condition is not present.

**Critical Evidence**:
Evidence whose absence or staleness could materially change a Preference Fit. Criticality is defined by Preference Family and, where justified, Supported Line using domain reasoning and sufficient historical out-of-sample evidence; insufficient coverage of any Critical Evidence blocks PLAY regardless of overall Data Quality.

**Mandatory Research**:
The shared investigation that every Betting Preference must receive, whether or not each fact is ultimately found. Failure to perform it makes Research Sufficiency incomplete, while an unsuccessful search blocks PLAY only when the missing fact is Critical Evidence or could materially change the decision.

**Research Requirement**:
A versioned statement that specified evidence research must be attempted for one or more Preference Families. It records the evidence sought and permitted information states; it does not assert that evidence exists or that the research was performed. Missing or unavailable sourcing remains UNKNOWN or UNPERFORMED, never ABSENT.

**Optional Evidence**:
Evidence that can improve an evaluation without deciding it alone. It has either Important or Context influence; missing Optional Evidence lowers confidence and Data Quality rather than automatically blocking PLAY.

**Important Evidence**:
Optional Evidence that can materially affect Data Quality, Probability Uncertainty, Failure/Risk Assessment, or interpretation without automatically blocking PLAY.

**Context Evidence**:
Optional Evidence researched and retained when useful, with lower default influence than Important Evidence.

**Evidence Freshness**:
Whether evidence is recent enough for its type at the Matchweek Research Cutoff. Fast-changing team news requires tighter limits than tactical tendencies, underlying performance, historical matchups, or long-term team strength.

**Material Conflict**:
An explicit contradiction between relevant evidence that could change the recommendation. MatchVet resolves it only when authority, directness, freshness, or relevance clearly favors one side and records why; otherwise the conflict remains explicit, increases uncertainty and Data Quality penalties, and may veto PLAY.

**Adversarial Veto**:
The rejection of a candidate when its Failure Case is evidence-backed, materially plausible, and either invalidates a key assumption or pushes Conservative Probability below the acceptance gate. Generic caution and Narrative Speculation cannot create an Adversarial Veto.

**Pre-lineup Risk**:
Uncertainty from expected starting elevens, doubtful players, rotation, injuries, suspensions, role importance, and related factors unresolved at the Matchweek Research Cutoff. MatchVet assesses reasonably plausible personnel scenarios and rejects or downgrades a Preference Fit when those scenarios materially weaken it or push its Conservative Probability below the acceptance threshold.

**Supporting Case**:
The strongest weighted evidence that a Betting Preference will succeed in a Target Match.

**Failure Case**:
The strongest credible explanation of how a Betting Preference could fail, including its supporting evidence, estimated materiality, representation in Estimated Probability and Probability Uncertainty, and whether it should downgrade or veto the candidate.

**Adversarial Review**:
The required challenge of every candidate approaching PLAY. It records both the Supporting Case and Failure Case and checks whether the identified risk is already represented in the candidate's probability and uncertainty.

**Research Sufficiency**:
The point at which Critical Evidence is sufficiently covered, relevant Optional Evidence has reached diminishing returns, Material Conflicts are resolved or represented in uncertainty, Adversarial Review is complete, and realistically obtainable missing evidence is unlikely to change PLAY to AVOID MATCH.

## Statistical context

**Form Horizon**:
One of several recency-weighted views of team strength, including short-term, medium-term, season, and longer-term evidence where relevant. MatchVet detects trend direction and Structural Change rather than treating a fixed last-five sample as authoritative, and weights each horizon by validated usefulness for the relevant Preference Family.

**Opponent Adjustment**:
The correction of results, goals, expected goals, corners, shots, and related measurements for opponent quality and schedule difficulty. Raw performance against unlike opposition is not directly comparable.

**Venue Effect**:
The difference between relevant home and away performance. MatchVet preserves it while borrowing hierarchical or shared evidence when venue-specific samples are too small.

**Match-State Distortion**:
The effect of leading or trailing, red cards, early penalties, extreme score states, prolonged numerical imbalance, or reliably known unusual weather or pitch conditions on observed statistics. Distorted statistics do not represent normal team strength without adjustment or explicit context.

**Cross-Competition Evidence**:
Evidence from cup or continental matches used directly for workload, fatigue, rest, rotation, injury, availability, tactical change, and current team state. Performance statistics from those matches influence Target Match Vetting only after adjustment for competition strength, opponent quality, lineup strength, and match context.

**Head-to-Head Evidence**:
Evidence from previous meetings with low default Signal Weight and rapid age decay. Recent meetings gain limited influence only when managers, tactical structures, core personnel, venue context, and relevant matchup characteristics remain comparable, and they can never independently create PLAY.

## Prediction quality

**Prediction Quality**:
The reliability of MatchVet's success probabilities on unseen matches, with preference for calibrated, low-uncertainty predictions and fewer false-positive selections over greater selection volume.

**Estimated Probability**:
MatchVet's explicit estimate of how likely a Betting Preference is to succeed in a Target Match.

**Probability Uncertainty**:
The degree of uncertainty around an Estimated Probability. Its intervals must achieve their intended empirical coverage on unseen matches, and greater stated uncertainty must correspond to greater observed prediction error; systematic overconfidence fails validation.

**Probability Interval Coverage**:
The frequency with which a probability interval contains the true conditional probability under its declared validation assumptions. One observed Settlement Result does not reveal that probability.

**Predictive Coverage**:
The frequency with which observed match outcomes fall inside a predicted outcome region. Predictive Coverage and Probability Interval Coverage measure different objects and cannot certify each other.

**Conservative Probability**:
An uncertainty-adjusted probability or lower confidence bound used as the Selection Policy's hard probability gate. A high Estimated Probability cannot pass when its Conservative Probability remains below the required threshold.

**Data Quality**:
The completeness, freshness, provenance, and reliability of the evidence used in Vetting. PLAY requires both sufficient Critical Evidence coverage and a minimum overall Data Quality threshold, so a strong average cannot conceal a material missing fact.

**Model Agreement**:
The extent to which predictive assessments with meaningfully different assumptions, information pathways, or historical error patterns support or contradict the same Preference Fit. Assessments derived from the same statistical chain receive correlated weight rather than separate votes.

**Model Disagreement**:
The extent to which meaningfully independent predictive assessments diverge. MatchVet rejects the candidate when their ranges cross opposing sides of the acceptance boundary or support materially conflicting outcomes; smaller disagreement widens Probability Uncertainty and reduces Selection Strength.

**Failure/Risk Assessment**:
The explicit case for how and why a Betting Preference could fail, including identified vetoes and unresolved uncertainty.

**Confidence Label**:
A presentation-only summary such as `HIGH` derived from Estimated Probability, Probability Uncertainty, Data Quality, Model Agreement, and Failure/Risk Assessment. It never replaces those separate measures and appears only alongside at least Estimated Probability, Conservative Probability, Data Quality, Model Agreement, and a Failure/Risk summary.

**Historical Evaluation**:
An assessment of past recommendations that reproduces the information state genuinely available and collected at the original Matchweek Research Cutoff. Confirmed lineups, later news, final results, and retrospective corrections unavailable at that cutoff are excluded from the prediction input; materially relevant Post-cutoff Evidence is recorded separately without rewriting the original prediction. Historical artifacts retain their original timing policy and cannot be relabeled as using a different cutoff.

**Development Period**:
A chronological span of Historical Matches used for model fitting and feature, research-rule, or candidate development.

**Validation Period**:
A chronological span after the Development Period used to select and freeze calibration, thresholds, gates, and ranking rules.

**Final Evaluation Period**:
An untouched chronological span after the Validation Period used to judge a frozen Selection Policy Version. Once its results influence any change, it becomes historical development evidence and is no longer unseen.

**Out-of-Sample Evidence**:
Evidence from later chronological Matchweeks never used for model fitting, feature or rule selection, calibration, threshold setting, or policy changes. Random match splits do not qualify when future team or season information can leak backward.

**Structural Change**:
A change that weakens the relevance of older evidence, such as promotion, a manager change, major squad turnover, a tactical shift, a competition rule change, or a persistent league-level shift. Shared team identity alone does not establish continuity across the change.

**Frozen Evaluation Window**:
The live period during which a Selection Policy Version cannot change. A failed version returns to research-only status after the window closes, and any model, threshold, feature, gate, or ranking revision creates a new version for later unseen Matchweeks.

**Calibration**:
Agreement between Estimated Probabilities and observed success frequencies over sufficient samples. MatchVet evaluates WIN, LOSS, and PUSH where applicable with settlement-aware probability metrics, calibration curves or bins, Brier score, and log loss; VOID is excluded, and future quarter lines add HALF_WIN and HALF_LOSS as distinct classes.

**False Positive**:
A recommendation classified as PLAY that later receives a LOSS Settlement Result. False-positive rates are assessed across groups; one loss does not by itself show that the underlying probability was unsound.

**Partial Failure**:
A future HALF_LOSS Settlement Result tracked separately from full LOSS if quarter-goal Asian Handicaps enter a later Preference Set. MatchVet reports both full-failure and combined negative-settlement rates without treating HALF_LOSS as a full False Positive.

**Evaluation Unit**:
The level at which Prediction Quality is assessed. MatchVet retains both match-level and preference-level evaluation, clusters correlated observations by Target Match, and prevents overlapping markets or lines from inflating effective sample size or confidence.

**Evaluation Subgroup**:
A sufficiently large group of comparable recommendations, such as a Target League, Preference Family, Supported Line, Confidence Label, or Probability Uncertainty band, used to detect persistent weaknesses hidden by aggregate results.

**Sufficient Sample**:
Enough out-of-sample evidence under predeclared Preference Family or Supported Line requirements, with acceptable metric uncertainty, to support a subgroup-specific conclusion without reacting to small-sample noise. Until then, sparse league and line groups borrow shared or hierarchical evidence and are not restricted solely for weak local results.

**Odds Context**:
Optional bookmaker price data retained for research or benchmarking with its source and observation time. Odds never determine PLAY or AVOID MATCH, and missing odds never block a recommendation.

**Match Decision Result**:
The immutable V2 result of vetting each enabled Betting Preference against one exact Target Match, with one Primary Recommendation or AVOID MATCH and its exact profile, evidence, policy, model, uncertainty, and vetting lineage.

**V2 Settlement Version**:
An immutable result-evidence record for one exact F16 match result, F14 decision, and enabled preference. It retains pending or conflicting evidence, or a T10 WIN, LOSS, PUSH, or VOID result; later corrections are successor versions.

## Provider health

**Intended Use**:
The specific MatchVet operation or distribution context for which a provider observation is assessed. Permission is evaluated for that use under a versioned source-rights policy.

**Provider Health Record**:
An immutable F04 observation for one provider or feed, one capability, one exact requested query scope, one intended use, and one check time. It records each health dimension separately and has a deterministic versioned digest.

**Provider Capability**:
A stable identifier for one operation or dataset, such as scheduled fixtures or season results. Evidence for one capability does not establish health for another.

**Source Lineage**:
The shared upstream data ancestry for one or more provider feeds. Distinct feeds can share a lineage, as OpenFootball JSON and Football.TXT do; lineage does not establish independent corroboration.

**Requested Query Scope**:
The exact competition, season, date or time range, subjects, and named filters requested for one provider capability. Every applicable facet retains an explicit state and participates in record identity.

**Scope Facet State**:
One of KNOWN, UNBOUNDED, NOT_APPLICABLE, or UNKNOWN. UNKNOWN means the requested bound is not established and is never treated as unbounded.

**Provider Health Dimensions**:
Separate permission, reachability, capability availability, structural validity, freshness, coverage, and failure assessments. No combined provider-wide health verdict replaces these dimensions.

**Provider Health Record Identity**:
The pair of exact Fixture Coverage Assessment digest and Provider Attempt ID. F05 persists one record per pair. Replaying the same pair is idempotent; reusing an attempt in another assessment creates another immutable record because its assessment reference changes the provenance and F04 digest.

## Model lineage

**V2 Model Input Contract**:
The exact frozen evidence, cutoff-valid historical inputs, and model versions used to estimate one Target Match. Its identity changes when any retained input or version changes.

**V2 Model Family Result**:
A prediction and its availability and uncertainty for one model family, bound to the exact V2 Model Input Contract and calibration lineage. An unavailable model or calibration retains that state explicitly.

**Calibration Case**:
An exact earlier prediction paired with cutoff-valid observed counts for the same fixture, teams, and kickoff. Unknown outcomes cannot supply calibration facts.

# Prediction and uncertainty methods for MatchVet

This note compares candidates for the Initial Preference Set. It does not select the final model stack. [Issue 12](https://github.com/Awisalas/match-vet/issues/12) owns that decision.

## Constraints that matter

The source portfolio supplies full-time and half-time goals, results, aggregate shots and shots on target, corners, cards, and all-seven-league history from 2017/18 through Football-Data.co.uk. It does not supply a transparent, deep, current xG series, shot-level chances, complete player statistics, complete all-league injury and likely-lineup histories, or historical pre-cutoff news states. Those gaps make goals, results, and corners the stable statistical base. Advanced xG, player, referee, availability, and tactical features must remain optional until a cutoff-valid history exists.

The chosen runtime is CPython 3.14 with Termux-built NumPy and SciPy. The normal limits are 1 GiB RAM, one CPU-heavy worker, no normal reliance on swap, a two-hour Matchweek target, and a four-hour hard limit. Model fitting must therefore use compact arrays, bounded optimization, and checkpoints. The current project environment does not yet have NumPy or SciPy installed, so this note establishes feasibility from the selected Termux packages and official APIs rather than claiming an on-device fit was run.

## Preference coverage

| Predictive object | Preferences obtained from it | Important condition |
| --- | --- | --- |
| Joint home and away full-time goal counts | Match Winner, Match Goals Overs, Home and Away Team Goals Overs, Double Chance, every initial Asian Handicap | Preserve the score-difference tail and PUSH mass. Dixon-Coles changes only low score cells, so high-score and tail checks still matter. |
| Separate first-half and second-half goal counts | First-Half Over 1.5 and Second-Half Over 1.5 | Do not infer the two periods from one full-time rate without validating the time split and dependence. |
| Joint home and away corner counts | Full-Match Total Corners Overs, Corner Match Winner, Home and Away Team Corners Overs | Model home and away corner processes separately. A total-only model cannot recover Corner Match Winner or team totals. |
| Direct categorical outcome probabilities | One exact binary preference, 1X2, or one WIN/LOSS/PUSH handicap | Separate per-line fits can contradict each other across nested lines, so coherence must be tested. |

## Method comparison

### Poisson and Dixon-Coles goal models

- Preferences and evidence. A joint score grid covers every full-time goal-derived preference. Separate period-specific fits cover the two half-total preferences. The minimum evidence is fixture identity, home and away goals, match time, league, venue role, and team identity. Shots, rest, and cutoff-valid context can enter as validated covariates.
- Assumptions and failure modes. Independent Poisson fixes count variance to its mean and assumes conditional independence. Maher found a reasonably accurate football score fit but also found improvement from correlated bivariate Poisson scores. Dixon-Coles adds time weighting and a low-score dependence correction, but it does not repair high-score tails, overdispersion, red-card distortions, or structural breaks. [Maher 1982](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9574.1982.tb00782.x), [Dixon and Coles 1997](https://doi.org/10.1111/1467-9876.00065), [Karlis and Ntzoufras 2003](https://www2.stat-athens.aueb.gr/~jbn/papers2/08_Karlis_Ntzoufras_2003_RSSD.pdf)
- Calibration and small samples. Attack, defence, home advantage, recency, and dependence parameters are identifiable with multi-season match results, but newly promoted teams and recent regime changes need shrinkage. A plain maximum-likelihood fit can overreact to small current-team samples.
- Audit and cost. The fitted rates, team effects, time weights, score matrix, and settlement mapping are easy to retain and explain. A few hundred parameters and tens of thousands of matches fit comfortably in NumPy arrays. SciPy supplies bounded local optimization and Poisson probability functions. [SciPy optimization](https://docs.scipy.org/doc/scipy/reference/optimize.html), [SciPy Poisson distribution](https://docs.scipy.org/doc/scipy/tutorial/stats/discrete_poisson.html)
- Settlement and missing advanced data. The score grid produces normalized WIN/LOSS/PUSH distributions and exact PUSH mass for whole-goal handicaps. It remains useful when xG and player data are UNKNOWN because goals and schedule data are Core. Missing material personnel evidence must widen uncertainty or block PLAY outside the count likelihood. It must not be imputed as "no absence."

Verdict: strong goal-family candidate, with Dixon-Coles and bivariate forms tested against an independent Poisson baseline. A plain independent Poisson model is too restrictive to be the only candidate.

### Hierarchical team-strength models

- Preferences and evidence. Hierarchical attack, defence, home, away, league, and season effects can sit inside goal or corner count likelihoods. They support whatever Settlement Distribution the underlying likelihood supports.
- Assumptions and failure modes. Partial pooling stabilizes promoted teams, sparse league-line groups, and early-season fits. Bad pooling can erase real league or team differences. Baio and Blangiardo explicitly report overshrinkage in a hierarchical football model and use a mixture extension to improve fit. Dynamic team strengths also need controlled recency or state evolution rather than treating years-old team identity as current strength. [Baio and Blangiardo 2010](https://discovery.ucl.ac.uk/16040/1/16040.pdf), [Rue and Salvesen 2000](https://citeseerx.ist.psu.edu/document?doi=d260ef5bd7eedc2dd269453fab3507b5752536f1&repid=rep1&type=pdf)
- Calibration and small samples. This is the best candidate structure for the product's shared-to-league hierarchy, but pooling strength and structural-change handling must be selected chronologically. Sparse local estimates should fall back to shared family or league evidence.
- Audit and cost. Penalized likelihood or empirical-Bayes MAP with a Laplace approximation is feasible with SciPy. Full MCMC or HMC adds a large runtime and dependency burden and is not a practical initial Termux candidate. Every group effect, prior or penalty, and version can be audited.
- Settlement and missing advanced data. A hierarchy cannot invent unavailable player or xG data. It can shrink unknown teams toward a defensible population and propagate wider parameter uncertainty, while evidence-policy uncertainty remains separate.

Verdict: strong structural candidate for count models and baselines. Compare shallow penalized or empirical-Bayes forms before considering richer mixtures or time-varying latent states.

### Regularized logistic and multinomial regression

- Preferences and evidence. Binary logit can predict each Over, Double Chance, and half-goal preference. Multinomial softmax can predict Match Winner and WIN/LOSS/PUSH outcomes. Inputs can include Elo differences, rolling opponent-adjusted goals, shots, corners, rest, venue, league, and explicit missingness states.
- Assumptions and failure modes. The log-odds are linear in the features unless interactions are declared. One model per exact line wastes data and may violate nesting, such as assigning a higher probability to Over 3.5 than Over 2.5. Unregularized sparse fits can separate, overfit, and become overconfident.
- Calibration and small samples. L2-regularized low-dimensional models are credible discriminative checks. Shared coefficients with carefully limited league or line interactions are safer than dozens of isolated fits. Calibration still needs a later chronological set.
- Audit and cost. Coefficients and feature definitions are inspectable. Stable binary and softmax likelihoods can use `scipy.special.expit` and `logsumexp`, with `scipy.optimize.minimize` for fitting. The data scale fits in memory without pandas or scikit-learn. [SciPy expit](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.expit.html), [SciPy logsumexp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.logsumexp.html), [SciPy minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- Settlement and missing advanced data. Multinomial output directly preserves WIN/LOSS/PUSH. Separate binary models do not create a joint score or corner distribution. Models must use explicit missingness and omit unvalidated advanced features rather than turn UNKNOWN into zero.

Verdict: strong independent check and possible direct model for specific families. It should not replace coherent count distributions across all related lines unless cross-line constraints are solved and validated.

### Elo-style ratings

- Preferences and evidence. Elo needs ordered results, venue, opponent, and a frozen update rule. Football research has used Elo ratings as covariates in ordered-logit match-result models. [Hvattum and Arntzen 2010](https://doi.org/10.1016/j.ijforecast.2009.10.002)
- Assumptions and failure modes. One scalar rating compresses attack, defence, score margin, and style. Update speed, season carry-over, promoted-team initialization, and home advantage can dominate results if tuned on too little data.
- Calibration and small samples. Ratings update cheaply and adjust for opponent strength, which makes them useful early and when advanced evidence is UNKNOWN. The rating-to-probability map still needs chronological calibration and shrinkage.
- Audit and cost. Cost is linear in matches with trivial memory. Every update can be replayed. Elo alone does not yield score, corner, or PUSH distributions.

Verdict: strong low-cost feature and genuinely different baseline. Reject Elo as the sole probability engine for MatchVet's full Preference Set.

### Empirical and hierarchical baselines

- Preferences and evidence. Family, exact line, settlement type, role, league, and sufficiently large matchup groups can use observed chronological frequencies. Beta-binomial shrinkage suits binary outcomes. Dirichlet-multinomial shrinkage suits WIN/LOSS/PUSH. SciPy directly supports beta-binomial and Dirichlet distributions. [SciPy beta-binomial](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.betabinom.html), [SciPy Dirichlet](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.dirichlet.html)
- Assumptions and failure modes. Results inside a pooled group must be exchangeable enough for the baseline to mean anything. Broad groups hide local triviality; narrow groups become noisy. Recency and structural changes must reduce the relevance of stale history.
- Calibration and small samples. Partial pooling is exactly the right behavior for the Non-Triviality Gate and Historical Baseline. It is deliberately conservative in sparse cells.
- Audit and cost. Counts, group definitions, priors, posterior means, and intervals are compact and easy to reproduce. Baselines yield full categorical settlement probabilities, but little match-specific discrimination.

Verdict: mandatory benchmark and baseline candidate, not a sufficient match predictor by itself.

### Simulation from fitted distributions

- Preferences and evidence. Sampling a fitted joint goal or corner distribution can map score or count outcomes to every exact settlement rule. Parameter draws can also propagate estimation uncertainty.
- Assumptions and failure modes. Simulation inherits every error in the fitted model. Truncated count ranges and too few draws can distort tail markets and PUSH mass. It adds Monte Carlo error where exact grid summation is available.
- Calibration and small samples. Simulation does not calibrate a model. It only approximates the fitted predictive distribution.
- Audit and cost. NumPy has reproducible generators and count samplers. Seeds, generator identity, draw count, truncation, and Monte Carlo error must be retained. [NumPy random sampling](https://numpy.org/doc/stable/reference/random/index.html)

Verdict: useful for parameter uncertainty, scenarios, and settlement rules that resist closed-form aggregation. Prefer exact enumeration for the small full-time goal and corner grids when it is practical. Simulation is not an independent model vote.

### Corner-specific count models

- Preferences and evidence. Separate home and away corner intensities support team Overs, total Overs, and Corner Match Winner. Core inputs include prior corners for and against, opponent strength, venue role, shots, match recency, and league. Historical results do not reveal the pre-match state that produced each corner, so match-state features are limited.
- Assumptions and failure modes. Plain Poisson may be under-dispersed because corners arrive in clusters. A compound Poisson study models this clustering and compares Poisson, negative-binomial, and geometric-Poisson regressions. Its data and some predictors include market information that MatchVet cannot use, so the result motivates candidate distributions rather than validating them for MatchVet. [Yip et al. 2021](https://arxiv.org/abs/2112.13001)
- Calibration and small samples. Poisson is the baseline. Negative-binomial or geometric/compound Poisson should advance only if chronological dispersion and tail checks improve. A bivariate construction or shared match effect is needed if home and away corner dependence matters.
- Audit and cost. Poisson and negative-binomial likelihoods are compact and available in SciPy's distribution set. The compound variants need a small custom likelihood but no new framework. [SciPy statistical distributions](https://docs.scipy.org/doc/scipy/reference/stats.html)
- Settlement and missing advanced data. A joint home-away count surface gives full binary and three-way corner settlement probabilities. Missing player and xG data is tolerable because the Core corner history exists. Missing lineup or tactical evidence still affects the separate evidence risk assessment when material.

Verdict: strong corner-family candidates are a joint Poisson baseline and an over-dispersed joint or shared-effect alternative. Reject a total-corners-only model because it cannot support the other corner preferences.

### Calibration methods

- Parametric binary calibration. Logistic or Platt scaling is cheap and stable. Beta calibration adds flexible shapes and includes the identity map, while remaining a small logistic fit. [Kull, Silva Filho, and Flach 2017](https://proceedings.mlr.press/v54/kull17a.html)
- Non-parametric binary calibration. Isotonic regression can correct arbitrary monotone distortion, and SciPy has a pool-adjacent-violators implementation. It overfits smaller calibration sets, so it needs a declared sample floor and later chronological data. [Niculescu-Mizil and Caruana 2005](https://icml.cc/Conferences/2005/proceedings/papers/079_GoodProbabilities_NiculescuMizilCaruana.pdf), [SciPy isotonic regression](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.isotonic_regression.html)
- Multiclass calibration. Temperature scaling is the lowest-parameter candidate. Dirichlet calibration preserves a probability simplex and generalizes binary beta calibration, but its larger parameter count needs regularization and more validation data. [Guo et al. 2017](https://proceedings.mlr.press/v70/guo17a), [Kull et al. 2019](https://papers.nips.cc/paper_files/paper/2019/hash/8ca01ea920679a0fe3728441494041b9-Abstract.html)
- Evaluation. Fit calibration only on a later chronological calibration or validation period. Check full multiclass calibration, not only confidence in the most likely class. Reliability diagrams and scalar errors can miss different kinds of multiclass miscalibration. [Vaicenavicius et al. 2019](https://proceedings.mlr.press/v89/vaicenavicius19a.html)

Verdict: compare identity or no recalibration, low-parameter logistic or beta calibration, and temperature scaling first. Allow isotonic or Dirichlet calibration only after their extra flexibility has enough unseen data.

### Probability uncertainty

MatchVet needs two distinct objects. The Settlement Distribution represents match randomness. Probability Uncertainty represents how uncertain MatchVet is about that distribution.

Candidate methods are:

- Inverse-Hessian or Laplace covariance around a penalized optimum. It is cheap and auditable, but can understate uncertainty for sparse groups, boundary parameters, multimodality, and model misspecification.
- Parametric bootstrap refits. This propagates fitted-model parameter uncertainty and yields lower probability quantiles. It inherits the model's assumptions and can consume substantial CPU when many refits are used.
- Chronological moving-block or Matchweek-cluster bootstrap as a sensitivity analysis. Resampling individual preference rows is invalid because outcomes within one match overlap. Blocks must not leak future data into fitting or threshold selection.
- Hierarchical posterior draws from a MAP and Laplace approximation. This gives coherent partial-pooling uncertainty without requiring full MCMC.
- Evidence-backed availability and tactical scenarios. These can widen the probability range or trigger the settled policy veto. Scenario weights cannot masquerade as learned probabilities until forward cutoff-state archives support them.
- Ensemble spread. It is useful Model Agreement evidence but cannot replace a calibrated uncertainty interval.

SciPy supplies confidence-interval bootstrap machinery, but MatchVet needs its own match or Matchweek resampling unit and checkpoints. [SciPy bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) Whatever method advances must demonstrate interval coverage and rising error with rising stated uncertainty on later chronological Matchweeks. Recalibration can target empirical interval coverage, but calibration without sharpness can produce uselessly wide intervals. [Kuleshov, Fenner, and Ermon 2018](https://proceedings.mlr.press/v80/kuleshov18a/kuleshov18a.pdf)

Verdict: strongest low-cost candidates are Laplace uncertainty plus checkpointed block or parametric bootstrap checks. Full Bayesian MCMC is not justified on the initial phone toolchain.

### Ensembles and Model Agreement

- Candidate shape. Combine a small number of components only when their assumptions, information paths, or historical errors differ. A count model, a regularized direct model, and an Elo or empirical baseline are plausibly different. Two minor variations of the same score model are correlated evidence.
- Full distributions. Pool normalized settlement probabilities, then recalibrate the pooled output on later chronological data. Linear pools tend to become over-dispersed and can lose calibration even when components are calibrated. [Gneiting and Ranjan 2013](https://arxiv.org/abs/1106.1638)
- Cost and audit. A two- or three-component pool is cheap. Retain every component distribution, weight, dependency group, disagreement measure, and pooled distribution. Learn weights with regularization or use frozen equal weights as a baseline. Never tune them on the evaluation window.
- Failure mode. More components do not create more evidence when they share data and errors. Hard voting discards the probability and PUSH structure and is unsuitable.

Verdict: a small dependency-aware probability ensemble is a strong candidate. Large stacks, uncalibrated averaging, and vote counting are rejected.

## Candidate shortlist for issue 12

The strongest methods worth taking into final selection are:

1. A regularized, recency-aware Poisson score model with independent, Dixon-Coles, and bivariate dependence variants compared chronologically.
2. Hierarchical or empirical-Bayes team and league effects inside goal and corner models, implemented as penalized likelihood or MAP rather than phone-based MCMC.
3. A separate corner count model that compares joint Poisson with an over-dispersed negative-binomial or compound-Poisson alternative.
4. Low-dimensional L2 logistic or multinomial models as independent discriminative checks, with Elo and opponent-adjusted rolling statistics as inputs.
5. Hierarchical empirical settlement baselines for calibration reference, subgroup borrowing, and the Non-Triviality Gate.
6. Low-parameter post-hoc calibration, with beta or logistic methods for binary outputs and temperature scaling for multiclass output. More flexible isotonic or Dirichlet calibration must earn their place on sufficient later data.
7. Laplace probability uncertainty checked by checkpointed parametric and chronological block refits. Evidence scenarios and Model Agreement stay separate.
8. A small probability-distribution ensemble only if chronological errors show meaningful component diversity.

This is a shortlist, not a stack decision.

## Rejected approaches for the initial product

- Full MCMC or HMC hierarchical fitting on the phone. It adds runtime, memory, convergence, and dependency costs that the selected toolchain avoids.
- Deep neural networks, gradient boosting, random forests, and high-dimensional player or event models. The chosen toolchain excludes their frameworks and the source portfolio lacks a stable all-seven feature history.
- A model that requires xG, shot-level chances, player ratings, referee history, or predicted lineups. These fields are incomplete or opaque at zero cost.
- Independent unpooled models for every exact line. They waste shared information and can issue incoherent nested probabilities.
- Plain independent Poisson as the only goal or corner model. It cannot represent relevant dependence and may miss over-dispersed tails.
- Elo or an empirical base rate as the only engine. Neither covers the complete settlement structure with enough match-specific detail.
- Simulation treated as a predictor or ensemble member. It is a calculation method over another model.
- Isotonic calibration in sparse league-line cells, unconstrained multiclass one-versus-rest calibration, uncalibrated probability averaging, and hard voting.
- Any model or feature derived from bookmaker odds. MatchVet does not optimize price or expected profit.

## Evidence limits that remain decisive

1. Historical result, goal, half-goal, shot, and corner data can support low-dimensional team and league models. It cannot support reliable player-level or event-quality models across all seven leagues.
2. The lack of historical cutoff-state injury, availability, lineup, tactical, and referee archives prevents honest retrospective training or validation of those features. Forward collection is needed before they can become learned model inputs.
3. Football-Data.co.uk xG fields have undocumented origin and continuity. They may be a sensitivity input, never a required or independently confirming feature.
4. Corner history has match totals but not event sequence or game-state attribution. Overdispersion and home-away dependence must be learned from aggregate counts without pretending to know the causal path.
5. Belgian data has no open structured fallback. Source failure raises Data Quality and may block research sufficiency sooner than in the other six leagues.
6. Promoted teams, manager changes, squad turnover, red cards, and abnormal match states create regime breaks that a stable historical model will miss unless recency, shrinkage, exclusions, or explicit context handle them.
7. A complete statistical model does not satisfy the product's Evidence Research seam by itself. Material UNKNOWN or conflicting pre-lineup evidence still widens uncertainty, lowers Data Quality, or blocks PLAY under the frozen Selection Policy.

## Research conclusion

The practical dividing line is simple. Count distributions should carry the coherent goal and corner settlement math. Low-dimensional direct models and ratings should challenge them. Hierarchical baselines should stop sparse groups from pretending to be certain. Calibration, uncertainty, and ensemble agreement then need separate chronological tests. The available data and phone can support that research program without a new numerical framework, but they cannot support an honest player-level or xG-dependent engine yet.

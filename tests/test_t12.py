from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from matchvet.t09 import FrozenEvidenceState, HistoricalMatch, TargetMatch


def _target() -> TargetMatch:
    from matchvet.t09 import TargetMatch

    return TargetMatch(
        matchweek_id="mw-t12",
        cutoff_id="cutoff-t12",
        fixture_id="fixture-t12",
        cutoff_utc="2026-10-01T12:00:00+00:00",
        kickoff_utc="2026-10-01T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
        venue_id="venue-t12",
        venue_name="T12 Stadium",
        source_assertion_ids=("target-t12",),
    )


def _history() -> tuple[HistoricalMatch, ...]:
    from matchvet.t09 import HistoricalMatch

    teams = ("team-home", "team-away", "team-red", "team-blue", "team-green")
    rows: list[HistoricalMatch] = []
    for index in range(18):
        kickoff = (date(2026, 9, 25) - timedelta(days=index * 3)).isoformat()
        home = teams[index % len(teams)]
        away = teams[(index + 2) % len(teams)]
        if home == away:
            away = teams[(index + 3) % len(teams)]
        full_home = (index * 3 + 1) % 4
        full_away = (index + 2) % 3
        half_home = min(full_home, index % 2)
        half_away = min(full_away, (index + 1) % 2)
        rows.append(
            HistoricalMatch(
                fixture_id=f"history-t12-{index:02d}",
                home_team_id=home,
                away_team_id=away,
                kickoff_utc=f"{kickoff}T20:00:00+00:00",
                full_time_home_goals=full_home,
                full_time_away_goals=full_away,
                half_time_home_goals=half_home,
                half_time_away_goals=half_away,
                source_assertion_ids=(f"assertion-t12-{index:02d}",),
                source_digest=f"{index + 1:064x}",
                source_key="football-data",
                origin_id="origin-football-data",
                competition_key="premier_league",
                regime_id="stable",
            )
        )
    return tuple(rows)


def _state(history: tuple[HistoricalMatch, ...]) -> FrozenEvidenceState:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput

    return EvidenceResearcher().build(EvidenceResearchInput(target=_target(), history=history))


def _state_for_target(
    history: tuple[HistoricalMatch, ...], target: TargetMatch
) -> FrozenEvidenceState:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput

    return EvidenceResearcher().build(EvidenceResearchInput(target=target, history=history))


def _state_with_feature(
    history: tuple[HistoricalMatch, ...], name: str, value: object, input_id: str
) -> FrozenEvidenceState:
    from matchvet.evidence import EvidenceState
    from matchvet.t09 import DerivedFeature

    state = _state(history)
    feature = next(item for item in state.derived_features if item.name == name)
    updated = replace(
        feature,
        state=EvidenceState.OBSERVED,
        value=value,
        input_ids=(input_id,),
        input_digests=(input_id.encode().hex().ljust(64, "0")[:64],),
        reason=None,
        digest="",
    )
    assert isinstance(updated, DerivedFeature)
    return replace(
        state,
        derived_features=tuple(
            updated if item.feature_id == feature.feature_id else item
            for item in state.derived_features
        ),
        state_digest="",
    )


def _state_with_regime(history: tuple[HistoricalMatch, ...], regime_id: str) -> FrozenEvidenceState:
    return _state_with_feature(
        history,
        "E-TACTICAL-REGIME",
        {"regime_id": regime_id},
        f"regime-{regime_id}",
    )


def test_t12_derives_first_and_second_half_history_without_a_fixed_split() -> None:
    from matchvet.t12 import derive_first_half_history, derive_second_half_history

    history = _history()
    first = derive_first_half_history(history)
    second = derive_second_half_history(history)

    assert first[0].home_goals == history[0].half_time_home_goals
    assert first[0].away_goals == history[0].half_time_away_goals
    first_match = history[0]
    assert first_match.full_time_home_goals is not None
    assert first_match.full_time_away_goals is not None
    assert first_match.half_time_home_goals is not None
    assert first_match.half_time_away_goals is not None
    assert (
        second[0].home_goals == first_match.full_time_home_goals - first_match.half_time_home_goals
    )
    assert (
        second[0].away_goals == first_match.full_time_away_goals - first_match.half_time_away_goals
    )
    assert any(
        first_row.home_goals + first_row.away_goals != second_row.home_goals + second_row.away_goals
        for first_row, second_row in zip(first, second, strict=True)
    )

    inconsistent = replace(history[0], full_time_home_goals=-1)
    assert derive_second_half_history((inconsistent, *history[1:])) == second[1:]


def test_t12_missing_half_time_history_is_model_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import fit_half_goal_models

    history = tuple(
        replace(match, half_time_home_goals=None, half_time_away_goals=None) for match in _history()
    )
    models = fit_half_goal_models(history, _state(history))

    assert models.first_half.status is ModelStatus.MODEL_UNAVAILABLE
    assert models.second_half.status is ModelStatus.MODEL_UNAVAILABLE


def test_t12_phase_distributions_are_normalized_and_derive_over_1_5() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import (
        FIRST_HALF_OVER_1_5,
        SECOND_HALF_OVER_1_5,
        fit_half_goal_models,
    )

    history = _history()
    models = fit_half_goal_models(history, _state(history))
    assert models.first_half.status is ModelStatus.AVAILABLE
    assert models.second_half.status is ModelStatus.AVAILABLE

    for phase, preference_id in (
        (models.first_half, FIRST_HALF_OVER_1_5),
        (models.second_half, SECOND_HALF_OVER_1_5),
    ):
        distribution = phase.predict()
        score = np.asarray(distribution.score_distribution)
        total = np.asarray(distribution.goal_distribution)
        assert np.all(np.isfinite(score))
        assert np.all(score >= 0.0)
        assert np.isclose(score.sum(), 1.0, atol=1e-12)
        assert np.all(np.isfinite(total))
        assert np.all(total >= 0.0)
        assert np.isclose(total.sum(), 1.0, atol=1e-12)
        assert set(distribution.settlement_distributions) == {preference_id}
        expected_win = sum(total[goals] for goals in range(2, len(total)))
        assert np.isclose(distribution.settlement_distributions[preference_id].win, expected_win)
        assert np.isclose(
            distribution.settlement_distributions[preference_id].win
            + distribution.settlement_distributions[preference_id].loss,
            1.0,
        )
        over_2_5 = sum(total[goals] for goals in range(3, len(total)))
        over_3_5 = sum(total[goals] for goals in range(4, len(total)))
        assert expected_win >= over_2_5 >= over_3_5


def test_t12_phase_fits_have_separate_coefficients_and_keep_schedule_history() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import fit_half_goal_models

    history = _history()
    missing_score = replace(
        history[0],
        full_time_home_goals=None,
        full_time_away_goals=None,
        half_time_home_goals=None,
        half_time_away_goals=None,
    )
    history_with_missing_score = (missing_score, *history[1:])
    models = fit_half_goal_models(history_with_missing_score, _state(history_with_missing_score))

    assert models.first_half.status is ModelStatus.AVAILABLE
    assert models.second_half.status is ModelStatus.AVAILABLE
    first_coefficients = models.first_half.parameters["feature_coefficients"]
    second_coefficients = models.second_half.parameters["feature_coefficients"]
    assert isinstance(first_coefficients, Mapping)
    assert isinstance(second_coefficients, Mapping)
    assert dict(first_coefficients) != dict(second_coefficients)

    target_covariates = models.first_half.parameters["target_model_covariates"]
    assert isinstance(target_covariates, Mapping)
    home_covariates = target_covariates["home"]
    assert isinstance(home_covariates, Mapping)
    schedule_covariate = home_covariates["schedule"]
    assert isinstance(schedule_covariate, (int, float))
    assert schedule_covariate < 0


def test_t12_fitted_probability_golden_case_is_stable() -> None:
    from matchvet.t12 import fit_half_goal_models

    models = fit_half_goal_models(_history(), _state(_history()))

    assert np.isclose(
        models.first_half.predict().settlement_distributions["first_half_over_1_5"].win,
        0.0852391713284046,
        atol=1e-12,
    )
    assert np.isclose(
        models.second_half.predict().settlement_distributions["second_half_over_1_5"].win,
        0.607826547048007,
        atol=1e-12,
    )


def test_t12_fitting_and_prediction_are_deterministic_for_frozen_inputs() -> None:
    from matchvet.t12 import fit_half_goal_models

    history = _history()
    state = _state(history)
    first = fit_half_goal_models(history, state)
    second = fit_half_goal_models(tuple(reversed(history)), state)
    assert first.first_half.to_bytes() == second.first_half.to_bytes()
    assert first.second_half.to_bytes() == second.second_half.to_bytes()
    assert first.first_half.predict(state).to_bytes() == second.first_half.predict(state).to_bytes()
    assert (
        first.second_half.predict(state).to_bytes() == second.second_half.predict(state).to_bytes()
    )


def test_t12_sparse_teams_borrow_phase_and_full_time_hierarchical_evidence() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import fit_half_goal_models

    history = _history()
    target = replace(
        _target(),
        fixture_id="fixture-promoted-t12",
        matchweek_id="mw-promoted-t12",
        cutoff_id="cutoff-promoted-t12",
        home_team_id="promoted-home",
        away_team_id="promoted-away",
    )
    models = fit_half_goal_models(history, _state_for_target(history, target))
    assert models.first_half.status is ModelStatus.AVAILABLE
    assert models.second_half.status is ModelStatus.AVAILABLE
    for fit in (models.first_half, models.second_half):
        teams = fit.uncertainty["teams"]
        assert isinstance(teams, Mapping)
        assert teams["promoted-home"]["pooling"] == "SHARED_LEAGUE_PRIOR"
        assert teams["promoted-home"]["borrowed_evidence"] is True
        assert teams["promoted-home"]["uncertainty_multiplier"] > 1.0
        assert fit.parameters["full_time_strength_source"] == "T11_FULL_TIME_GOAL_CAPABILITY"


def test_t12_recency_regime_opponent_venue_and_schedule_inputs_change_the_fit() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import T12ModelConfig, fit_first_half_goal_model

    history = _history()
    state = _state(history)
    short = fit_first_half_goal_model(
        history,
        state,
        config=T12ModelConfig(recency_half_life_days=20.0),
    )
    long = fit_first_half_goal_model(
        history,
        state,
        config=T12ModelConfig(recency_half_life_days=1_000.0),
    )
    assert short.status is ModelStatus.AVAILABLE
    assert long.status is ModelStatus.AVAILABLE
    short_effective = short.diagnostics["training_effective_matches"]
    long_effective = long.diagnostics["training_effective_matches"]
    assert isinstance(short_effective, (int, float))
    assert isinstance(long_effective, (int, float))
    assert float(short_effective) < float(long_effective)

    opponent_history = tuple(
        replace(match, full_time_home_goals=3) if match.fixture_id == "history-t12-01" else match
        for match in history
    )
    opponent_state = _state(opponent_history)
    opponent_fit = fit_first_half_goal_model(opponent_history, opponent_state)
    assert opponent_fit.status is ModelStatus.AVAILABLE
    assert (
        opponent_fit.predict(opponent_state).home_expected_goals
        != short.predict().home_expected_goals
    )

    venue_fit = fit_first_half_goal_model(
        history,
        state,
        config=T12ModelConfig(home_advantage_prior_scale=0.05),
    )
    assert venue_fit.status is ModelStatus.AVAILABLE
    assert venue_fit.predict(state).home_expected_goals != short.predict().home_expected_goals

    workload_history = tuple(
        replace(match, kickoff_utc="2026-09-29T20:00:00+00:00")
        if match.fixture_id == "history-t12-00"
        else match
        for match in history
    )
    workload_state = _state(workload_history)
    workload_fit = fit_first_half_goal_model(workload_history, workload_state)
    assert workload_fit.status is ModelStatus.AVAILABLE
    assert (
        workload_fit.predict(workload_state).home_expected_goals
        != short.predict().home_expected_goals
    )

    stable = fit_first_half_goal_model(history, _state_with_regime(history, "stable"))
    changed_regime = fit_first_half_goal_model(history, _state_with_regime(history, "changed"))
    assert stable.status is ModelStatus.AVAILABLE
    assert changed_regime.status is ModelStatus.AVAILABLE
    stable_effective = stable.diagnostics["training_effective_matches"]
    changed_effective = changed_regime.diagnostics["training_effective_matches"]
    assert isinstance(stable_effective, (int, float))
    assert isinstance(changed_effective, (int, float))
    assert float(stable_effective) > float(changed_effective)
    assert stable.to_bytes() != changed_regime.to_bytes()


def test_t12_second_half_uses_its_own_fitted_covariates() -> None:
    from matchvet.t12 import T12ModelConfig, fit_second_half_goal_model

    history = _history()
    state = _state(history)
    baseline = fit_second_half_goal_model(history, state)
    short_recency = fit_second_half_goal_model(
        history,
        state,
        config=T12ModelConfig(recency_half_life_days=20.0),
    )
    venue_prior = fit_second_half_goal_model(
        history,
        state,
        config=T12ModelConfig(home_advantage_prior_scale=0.05),
    )
    stable_state = _state_with_regime(history, "stable")
    changed_regime_state = _state_with_regime(history, "changed")
    stable_regime = fit_second_half_goal_model(history, stable_state)
    changed_regime = fit_second_half_goal_model(history, changed_regime_state)
    opponent_history = tuple(
        replace(match, full_time_home_goals=3) if match.fixture_id == "history-t12-01" else match
        for match in history
    )
    opponent_state = _state(opponent_history)
    changed_opponent = fit_second_half_goal_model(opponent_history, opponent_state)
    schedule_history = tuple(
        replace(match, kickoff_utc="2026-09-29T20:00:00+00:00")
        if match.fixture_id == "history-t12-00"
        else match
        for match in history
    )
    schedule_state = _state(schedule_history)
    changed_schedule = fit_second_half_goal_model(schedule_history, schedule_state)

    assert baseline.status.value == "AVAILABLE"
    assert short_recency.status.value == "AVAILABLE"
    assert venue_prior.status.value == "AVAILABLE"
    assert stable_regime.status.value == "AVAILABLE"
    assert changed_regime.status.value == "AVAILABLE"
    assert changed_opponent.status.value == "AVAILABLE"
    assert changed_schedule.status.value == "AVAILABLE"
    assert baseline.predict().home_expected_goals != short_recency.predict().home_expected_goals
    assert baseline.predict().home_expected_goals != venue_prior.predict().home_expected_goals
    baseline_coefficients = baseline.parameters["feature_coefficients"]
    venue_coefficients = venue_prior.parameters["feature_coefficients"]
    stable_coefficients = stable_regime.parameters["feature_coefficients"]
    changed_coefficients = changed_regime.parameters["feature_coefficients"]
    assert isinstance(baseline_coefficients, Mapping)
    assert isinstance(venue_coefficients, Mapping)
    assert isinstance(stable_coefficients, Mapping)
    assert isinstance(changed_coefficients, Mapping)
    assert baseline_coefficients["venue"] != venue_coefficients["venue"]
    assert stable_coefficients["regime"] != changed_coefficients["regime"]
    assert (
        baseline.predict().home_expected_goals
        != changed_opponent.predict(opponent_state).home_expected_goals
    )
    assert (
        baseline.predict().home_expected_goals
        != changed_schedule.predict(schedule_state).home_expected_goals
    )
    assert (
        stable_regime.predict(stable_state).home_expected_goals
        != changed_regime.predict(changed_regime_state).home_expected_goals
    )


def test_t12_missing_or_mismatched_frozen_half_inputs_are_unavailable() -> None:
    from matchvet.t12 import fit_second_half_goal_model

    history = _history()
    state = _state(history)
    missing = fit_second_half_goal_model(history[:-1], state)
    assert missing.status.value == "MODEL_UNAVAILABLE"
    assert missing.reason == "FROZEN_HISTORY_INPUTS_INCOMPLETE"
    assert missing.diagnostics["missing_fixture_ids"] == ("history-t12-17",)

    changed = replace(history[0], half_time_home_goals=1)
    mismatch = fit_second_half_goal_model((changed, *history[1:]), state)
    assert mismatch.status.value == "MODEL_UNAVAILABLE"
    assert mismatch.reason == "FROZEN_HISTORY_INPUTS_MISMATCH"
    assert mismatch.diagnostics["mismatched_fixture_ids"] == ("history-t12-00",)


def test_t12_unresolved_score_conflict_is_model_unavailable() -> None:
    from matchvet.t09 import MaterialConflict
    from matchvet.t12 import fit_second_half_goal_model

    history = _history()
    state = _state(history)
    conflict = MaterialConflict(
        conflict_id="conflict-t12-score",
        subject_id="history-t12-00",
        evidence_type="MATCH_STATISTIC",
        predicate="half_time_home_goals",
        assertion_ids=("assertion-a", "assertion-b"),
        values=(0, 1),
    )
    conflicted_state = replace(state, conflicts=(conflict,), state_digest="")

    fit = fit_second_half_goal_model(history, conflicted_state)

    assert fit.status.value == "MODEL_UNAVAILABLE"
    assert fit.reason == "UNRESOLVED_MATERIAL_CONFLICT"
    assert fit.diagnostics["unresolved_material_conflict_ids"] == ("conflict-t12-score",)


def test_t12_requires_an_available_full_time_model() -> None:
    from matchvet.t11 import T11ModelConfig, fit_full_time_goal_model
    from matchvet.t12 import fit_first_half_goal_model

    history = _history()
    state = _state(history)
    full_time_fit = fit_full_time_goal_model(
        history,
        state,
        config=T11ModelConfig(optimizer_max_iterations=1),
    )
    assert full_time_fit.status.value == "MODEL_UNAVAILABLE"

    phase_fit = fit_first_half_goal_model(history, state, full_time_fit=full_time_fit)
    assert phase_fit.status.value == "MODEL_UNAVAILABLE"
    assert phase_fit.reason == "FULL_TIME_MODEL_UNAVAILABLE"


def test_t12_round_trips_metadata_and_rejects_tampered_settlement() -> None:
    from matchvet.t12 import (
        HalfGoalDistribution,
        HalfGoalModelFit,
        T12IntegrityError,
        fit_second_half_goal_model,
    )

    history = _history()
    state = _state(history)
    fit = fit_second_half_goal_model(history, state)
    restored_fit = HalfGoalModelFit.from_dict(json.loads(fit.to_bytes()))
    distribution = fit.predict(state)
    restored_distribution = HalfGoalDistribution.from_dict(json.loads(distribution.to_bytes()))
    assert restored_fit.to_bytes() == fit.to_bytes()
    assert restored_distribution.to_bytes() == distribution.to_bytes()
    assert fit.model_version == "t12-second-half-goals-v2"
    assert fit.training_input_fixture_ids
    assert fit.training_input_digests
    assert fit.reproducibility["randomness"] == "none"
    assert fit.reproducibility["history_order"] == "fixture_id_ascending"
    assert fit.reproducibility["preference_ids"] == ("second_half_over_1_5",)
    provenance = fit.diagnostics["training_input_provenance"]
    assert isinstance(provenance, Mapping)
    fixture_provenance = provenance["history-t12-00"]
    assert isinstance(fixture_provenance, Mapping)
    metric_provenance = fixture_provenance["half_time_home_goals"]
    assert isinstance(metric_provenance, Mapping)
    assert metric_provenance["source_assertion_ids"]
    assert metric_provenance["source_digests"]

    multi_source_state = _state(history)
    multi_source_facts = tuple(
        replace(
            fact,
            source_digest=("a" * 64)
            if fact.subject_id == "history-t12-00" and fact.predicate.startswith("half_time_")
            else ("b" * 64)
            if fact.subject_id == "history-t12-00" and fact.predicate.startswith("full_time_")
            else fact.source_digest,
        )
        for fact in multi_source_state.source_assertions
    )
    multi_source_state = replace(
        multi_source_state,
        source_assertions=multi_source_facts,
        state_digest="",
    )
    multi_source_fit = fit_second_half_goal_model(history, multi_source_state)
    assert multi_source_fit.status.value == "MODEL_UNAVAILABLE"
    assert multi_source_fit.reason == "FROZEN_HISTORY_INPUTS_MISMATCH"
    tampered = json.loads(distribution.to_bytes())
    settlement = tampered["settlement_distributions"]["second_half_over_1_5"]
    assert isinstance(settlement, dict)
    settlement["WIN"] += 0.01
    settlement["LOSS"] -= 0.01
    with pytest.raises(T12IntegrityError):
        HalfGoalDistribution.from_dict(tampered)


def test_t12_extreme_phase_scores_are_finite_or_explicitly_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t12 import fit_second_half_goal_model

    history = tuple(
        replace(
            match,
            full_time_home_goals=50 if index == 0 else match.full_time_home_goals,
            full_time_away_goals=40 if index == 0 else match.full_time_away_goals,
            half_time_home_goals=20 if index == 0 else match.half_time_home_goals,
            half_time_away_goals=20 if index == 0 else match.half_time_away_goals,
        )
        for index, match in enumerate(_history())
    )
    state = _state(history)
    fit = fit_second_half_goal_model(history, state)
    prediction = fit.predict(state)
    if fit.status is ModelStatus.AVAILABLE:
        total = np.asarray(prediction.goal_distribution)
        assert np.all(np.isfinite(total))
        assert np.all(total >= 0.0)
        assert np.isclose(total.sum(), 1.0, atol=1e-12)
    else:
        assert prediction.status is ModelStatus.MODEL_UNAVAILABLE

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from matchvet.t09 import FrozenEvidenceState, HistoricalMatch, TargetMatch


def _target() -> TargetMatch:
    from matchvet.t09 import TargetMatch

    return TargetMatch(
        matchweek_id="mw-t11",
        cutoff_id="cutoff-t11",
        fixture_id="fixture-t11",
        cutoff_utc="2026-09-18T12:00:00+00:00",
        kickoff_utc="2026-09-18T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
        venue_id="venue-t11",
        venue_name="T11 Stadium",
        source_assertion_ids=("target-t11",),
    )


def _history() -> tuple[HistoricalMatch, ...]:
    from matchvet.t09 import HistoricalMatch

    rows = []
    teams = ("team-home", "team-away", "team-red", "team-blue", "team-green")
    for index in range(16):
        kickoff = (date(2026, 9, 10) - timedelta(days=index * 4)).isoformat()
        home = teams[index % len(teams)]
        away = teams[(index + 2) % len(teams)]
        if home == away:
            away = teams[(index + 3) % len(teams)]
        rows.append(
            HistoricalMatch(
                fixture_id=f"history-t11-{index:02d}",
                home_team_id=home,
                away_team_id=away,
                kickoff_utc=f"{kickoff}T20:00:00+00:00",
                full_time_home_goals=(index * 3 + 1) % 4,
                full_time_away_goals=(index + 2) % 3,
                source_assertion_ids=(f"assertion-t11-{index:02d}",),
                source_digest=(f"{index + 1:064x}"),
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


def _state_with_regime(history: tuple[HistoricalMatch, ...], regime_id: str) -> FrozenEvidenceState:
    from matchvet.evidence import EvidenceState
    from matchvet.t09 import DerivedFeature

    state = _state(history)
    regime = next(
        feature for feature in state.derived_features if feature.name == "E-TACTICAL-REGIME"
    )
    updated = replace(
        regime,
        state=EvidenceState.OBSERVED,
        value={"regime_id": regime_id},
        input_ids=(f"regime-{regime_id}",),
        input_digests=(f"{regime_id.encode().hex():0<64}"[:64],),
        reason=None,
        digest="",
    )
    assert isinstance(updated, DerivedFeature)
    return replace(
        state,
        derived_features=tuple(
            updated if feature.name == regime.name else feature
            for feature in state.derived_features
        ),
        state_digest="",
    )


def test_t11_fit_returns_one_normalized_score_grid_and_all_goal_markets() -> None:
    from matchvet.t11 import ModelStatus, fit_full_time_goal_model

    history = _history()
    fit = fit_full_time_goal_model(history, _state(history))
    assert fit.status is ModelStatus.AVAILABLE

    prediction = fit.predict(_state(history))
    assert prediction.status is ModelStatus.AVAILABLE
    score = np.asarray(prediction.score_distribution)
    assert score.ndim == 2
    assert score.shape[0] == score.shape[1]
    assert np.all(np.isfinite(score))
    assert np.all(score >= 0.0)
    assert np.isclose(score.sum(), 1.0, atol=1e-12)
    assert set(prediction.settlement_distributions) == {
        "match_winner_home",
        "match_winner_draw",
        "match_winner_away",
        "double_chance_1x",
        "double_chance_x2",
        "double_chance_12",
        "match_goals_over_1_5",
        "match_goals_over_2_5",
        "match_goals_over_3_5",
        "home_team_goals_over_1_5",
        "home_team_goals_over_2_5",
        "away_team_goals_over_1_5",
        "away_team_goals_over_2_5",
        "asian_handicap_home_0_0",
        "asian_handicap_home_plus_1_0",
        "asian_handicap_home_plus_1_5",
        "asian_handicap_home_minus_1_0",
        "asian_handicap_home_minus_1_5",
        "asian_handicap_away_0_0",
        "asian_handicap_away_plus_1_0",
        "asian_handicap_away_plus_1_5",
        "asian_handicap_away_minus_1_0",
        "asian_handicap_away_minus_1_5",
    }


def test_t11_fit_is_deterministic_for_identical_frozen_inputs() -> None:
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    state = _state(history)
    first = fit_full_time_goal_model(history, state)
    second = fit_full_time_goal_model(tuple(reversed(history)), state)
    assert first.to_bytes() == second.to_bytes()
    assert first.predict(state).to_bytes() == second.predict(state).to_bytes()


def test_t11_settlement_mappings_are_marginals_of_the_same_score_surface() -> None:
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    prediction = fit_full_time_goal_model(history, _state(history)).predict(_state(history))
    score = np.asarray(prediction.score_distribution)
    home = sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h > a)
    draw = sum(score[h, h] for h in range(len(score)))
    away = sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h < a)
    markets = prediction.settlement_distributions
    assert np.isclose(markets["match_winner_home"].win, home)
    assert np.isclose(markets["match_winner_draw"].win, draw)
    assert np.isclose(markets["match_winner_away"].win, away)
    assert np.isclose(markets["double_chance_1x"].win, home + draw)
    assert np.isclose(markets["double_chance_x2"].win, away + draw)
    assert np.isclose(markets["double_chance_12"].win, home + away)
    assert np.isclose(home + draw + away, 1.0, atol=1e-12)


def test_t11_goal_markets_are_monotone_and_have_no_hidden_push_mass() -> None:
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    prediction = fit_full_time_goal_model(history, _state(history)).predict(_state(history))
    score = np.asarray(prediction.score_distribution)
    markets = prediction.settlement_distributions
    assert (
        markets["match_goals_over_1_5"].win
        >= markets["match_goals_over_2_5"].win
        >= markets["match_goals_over_3_5"].win
    )
    assert markets["home_team_goals_over_1_5"].win >= markets["home_team_goals_over_2_5"].win
    assert markets["away_team_goals_over_1_5"].win >= markets["away_team_goals_over_2_5"].win
    assert np.isclose(
        markets["match_goals_over_1_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h + a > 1.5),
    )
    assert np.isclose(
        markets["match_goals_over_2_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h + a > 2.5),
    )
    assert np.isclose(
        markets["match_goals_over_3_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h + a > 3.5),
    )
    assert np.isclose(
        markets["home_team_goals_over_1_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h > 1.5),
    )
    assert np.isclose(
        markets["home_team_goals_over_2_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if h > 2.5),
    )
    assert np.isclose(
        markets["away_team_goals_over_1_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if a > 1.5),
    )
    assert np.isclose(
        markets["away_team_goals_over_2_5"].win,
        sum(score[h, a] for h in range(len(score)) for a in range(len(score)) if a > 2.5),
    )
    for probability in markets.values():
        assert np.isclose(probability.win + probability.loss + probability.push, 1.0)


def test_t11_asian_handicap_preserves_win_push_loss_rules() -> None:
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    prediction = fit_full_time_goal_model(history, _state(history)).predict(_state(history))
    score = np.asarray(prediction.score_distribution)
    markets = prediction.settlement_distributions
    for side in ("home", "away"):
        assert markets[f"asian_handicap_{side}_0_0"].push > 0.0
        assert markets[f"asian_handicap_{side}_plus_1_0"].push > 0.0
        assert markets[f"asian_handicap_{side}_minus_1_0"].push > 0.0
        assert markets[f"asian_handicap_{side}_plus_1_5"].push == 0.0
        assert markets[f"asian_handicap_{side}_minus_1_5"].push == 0.0
    assert np.isclose(
        markets["asian_handicap_home_0_0"].win,
        markets["asian_handicap_away_0_0"].loss,
    )
    assert np.isclose(
        markets["asian_handicap_home_0_0"].push,
        markets["asian_handicap_away_0_0"].push,
    )
    line_names = {
        0.0: "0_0",
        1.0: "plus_1_0",
        1.5: "plus_1_5",
        -1.0: "minus_1_0",
        -1.5: "minus_1_5",
    }
    for side in ("home", "away"):
        for line, line_name in line_names.items():
            expected = {"WIN": 0.0, "PUSH": 0.0, "LOSS": 0.0}
            for home_goals, row in enumerate(score):
                for away_goals, probability in enumerate(row):
                    difference = (
                        home_goals - away_goals if side == "home" else away_goals - home_goals
                    )
                    result = (
                        "WIN"
                        if 2 * difference + 2 * line > 0
                        else "LOSS"
                        if 2 * difference + 2 * line < 0
                        else "PUSH"
                    )
                    expected[result] += float(probability)
            actual = markets[f"asian_handicap_{side}_{line_name}"]
            assert np.isclose(actual.win, expected["WIN"])
            assert np.isclose(actual.push, expected["PUSH"])
            assert np.isclose(actual.loss, expected["LOSS"])


def test_t11_sparse_promoted_teams_borrow_shared_evidence_and_widen_uncertainty() -> None:
    from matchvet.t11 import ModelStatus, fit_full_time_goal_model

    history = _history()
    target = replace(
        _target(),
        fixture_id="fixture-promoted-t11",
        matchweek_id="mw-promoted-t11",
        cutoff_id="cutoff-promoted-t11",
        home_team_id="promoted-home",
        away_team_id="promoted-away",
    )
    state = _state_for_target(history, target)
    fit = fit_full_time_goal_model(history, state)
    assert fit.status is ModelStatus.AVAILABLE
    teams = fit.uncertainty["teams"]
    assert isinstance(teams, Mapping)
    assert teams["promoted-home"]["pooling"] == "SHARED_LEAGUE_PRIOR"
    assert teams["promoted-home"]["borrowed_evidence"] is True
    assert teams["promoted-home"]["uncertainty_multiplier"] > 1.0
    assert fit.predict(state).status is ModelStatus.AVAILABLE


def test_t11_recency_and_regime_controls_change_the_fit_deterministically() -> None:
    from matchvet.t11 import T11ModelConfig, fit_full_time_goal_model

    history = _history()
    state = _state(history)
    short = fit_full_time_goal_model(
        history, state, config=T11ModelConfig(recency_half_life_days=20.0)
    )
    long = fit_full_time_goal_model(
        history, state, config=T11ModelConfig(recency_half_life_days=1_000.0)
    )
    short_effective = short.diagnostics["training_effective_matches"]
    long_effective = long.diagnostics["training_effective_matches"]
    assert isinstance(short_effective, (int, float))
    assert isinstance(long_effective, (int, float))
    assert short_effective < long_effective
    stable = fit_full_time_goal_model(history, _state_with_regime(history, "stable"))
    changed = fit_full_time_goal_model(history, _state_with_regime(history, "changed"))
    stable_effective = stable.diagnostics["training_effective_matches"]
    changed_effective = changed.diagnostics["training_effective_matches"]
    assert isinstance(stable_effective, (int, float))
    assert isinstance(changed_effective, (int, float))
    assert stable_effective > changed_effective
    assert stable.to_bytes() != changed.to_bytes()


def test_t11_opponent_and_home_away_identity_affect_predictions() -> None:
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    forward_state = _state(history)
    reverse_target = replace(
        _target(),
        fixture_id="fixture-t11-reverse",
        matchweek_id="mw-t11-reverse",
        cutoff_id="cutoff-t11-reverse",
        home_team_id="team-away",
        away_team_id="team-home",
    )
    reverse_state = _state_for_target(history, reverse_target)
    forward = fit_full_time_goal_model(history, forward_state).predict(forward_state)
    reverse = fit_full_time_goal_model(history, reverse_state).predict(reverse_state)
    assert forward.status.value == "AVAILABLE"
    assert reverse.status.value == "AVAILABLE"
    assert forward.home_expected_goals is not None
    assert reverse.home_expected_goals is not None
    assert not np.isclose(forward.home_expected_goals, reverse.home_expected_goals)


def test_t11_consumes_frozen_schedule_and_cross_competition_features() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput
    from matchvet.t11 import fit_full_time_goal_model

    history = _history()
    target = _target()
    state = EvidenceResearcher().build(
        EvidenceResearchInput(
            target=target,
            history=history,
            workload={
                "workload_evidence_id": "workload-t11",
                "evidence_state": "OBSERVED",
                "evidence_digest": "a" * 64,
                "cutoff_utc": target.cutoff_utc,
                "home": {
                    "rest_days": 3,
                    "congestion_windows": ["short-rest"],
                    "cross_competition_fixture_ids": ["cup-1", "cup-2"],
                },
                "away": {
                    "rest_days": 7,
                    "congestion_windows": [],
                    "cross_competition_fixture_ids": [],
                },
            },
        )
    )
    fit = fit_full_time_goal_model(history, state)
    offsets = fit.parameters["target_feature_offsets"]
    assert isinstance(offsets, Mapping)
    components = offsets["components"]
    assert isinstance(components, Mapping)
    schedule = components["schedule"]
    assert isinstance(schedule, Mapping)
    assert schedule["home"] < schedule["away"]
    assert "workload-t11" in fit.feature_input_ids


def test_t11_rejects_history_that_does_not_match_frozen_evidence_inputs() -> None:
    from matchvet.t11 import MODEL_UNAVAILABLE, fit_full_time_goal_model

    history = _history()
    fit = fit_full_time_goal_model(history[:-1], _state(history))
    assert fit.status is MODEL_UNAVAILABLE
    assert fit.reason == "FROZEN_HISTORY_INPUTS_INCOMPLETE"
    assert fit.diagnostics["missing_fixture_ids"] == ("history-t11-15",)

    original_home_goals = history[0].full_time_home_goals
    assert original_home_goals is not None
    changed: tuple[HistoricalMatch, ...] = (
        replace(history[0], full_time_home_goals=original_home_goals + 1),
        *history[1:],
    )
    changed_fit = fit_full_time_goal_model(changed, _state(history))
    assert changed_fit.status is MODEL_UNAVAILABLE
    assert changed_fit.reason == "FROZEN_HISTORY_INPUTS_MISMATCH"
    assert changed_fit.diagnostics["mismatched_fixture_ids"] == ("history-t11-00",)


def test_t11_prediction_rejects_a_different_frozen_evidence_digest() -> None:
    from matchvet.t11 import T11IntegrityError, fit_full_time_goal_model

    history = _history()
    state = _state(history)
    fit = fit_full_time_goal_model(history, state)
    changed_state = _state_with_regime(history, "stable")
    with pytest.raises(T11IntegrityError):
        fit.predict(changed_state)


def test_t11_returns_model_unavailable_without_minimum_goal_history() -> None:
    from matchvet.t11 import MODEL_UNAVAILABLE, fit_full_time_goal_model

    state = _state(())
    fit = fit_full_time_goal_model((), state)
    assert fit.status is MODEL_UNAVAILABLE
    assert fit.reason == "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"
    prediction = fit.predict(state)
    assert prediction.status is MODEL_UNAVAILABLE
    assert prediction.score_distribution == ()
    assert prediction.settlement_distributions == {}


def test_t11_missing_core_history_is_model_unavailable() -> None:
    from matchvet.t11 import MODEL_UNAVAILABLE, fit_full_time_goal_model

    missing = tuple(
        replace(
            match,
            full_time_home_goals=None,
            full_time_away_goals=None,
        )
        for match in _history()
    )
    state = _state(missing)
    fit = fit_full_time_goal_model(missing, state)
    assert fit.status is MODEL_UNAVAILABLE
    assert fit.reason == "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"


def test_t11_optimizer_failure_returns_model_unavailable() -> None:
    from matchvet.t11 import (
        MODEL_UNAVAILABLE,
        T11ModelConfig,
        fit_full_time_goal_model,
    )

    history = _history()
    fit = fit_full_time_goal_model(
        history,
        _state(history),
        config=T11ModelConfig(optimizer_max_iterations=1),
    )
    assert fit.status is MODEL_UNAVAILABLE
    assert fit.reason == "FIT_FAILED"
    assert "optimizer failed" in str(fit.diagnostics["fit_error"])


def test_t11_excessive_score_tail_returns_model_unavailable() -> None:
    from matchvet.t11 import MODEL_UNAVAILABLE, T11ModelConfig, fit_full_time_goal_model

    history = _history()
    config = T11ModelConfig(
        maximum_expected_goals=100.0,
        dixon_coles_rho_bound=1e-6,
        target_feature_scale=100.0,
    )
    fit = fit_full_time_goal_model(history, _state(history), config=config)
    assert fit.status is MODEL_UNAVAILABLE
    assert fit.reason == "FIT_FAILED"
    assert "tail mass" in str(fit.diagnostics["fit_error"])


def test_t11_extreme_goal_inputs_remain_finite_or_explicitly_unavailable() -> None:
    from matchvet.t11 import ModelStatus, fit_full_time_goal_model

    history = tuple(
        replace(
            match,
            full_time_home_goals=50 if index == 0 else match.full_time_home_goals,
            full_time_away_goals=40 if index == 0 else match.full_time_away_goals,
        )
        for index, match in enumerate(_history())
    )
    state = _state(history)
    fit = fit_full_time_goal_model(history, state)
    prediction = fit.predict(state)
    if fit.status is ModelStatus.AVAILABLE:
        score = np.asarray(prediction.score_distribution)
        assert prediction.status is ModelStatus.AVAILABLE
        assert np.all(np.isfinite(score))
        assert np.isclose(score.sum(), 1.0, atol=1e-12)
    else:
        assert prediction.status is ModelStatus.MODEL_UNAVAILABLE


def test_t11_fit_and_distribution_round_trip_with_reproducibility_metadata() -> None:
    import json

    from matchvet.t11 import (
        FULL_TIME_GOAL_PREFERENCE_IDS,
        FullTimeGoalDistribution,
        FullTimeGoalModelFit,
        T11IntegrityError,
        fit_full_time_goal_model,
    )

    history = _history()
    state = _state(history)
    fit = fit_full_time_goal_model(history, state)
    restored = FullTimeGoalModelFit.from_dict(json.loads(fit.to_bytes()))
    assert restored.to_bytes() == fit.to_bytes()
    distribution = fit.predict(state)
    restored_distribution = FullTimeGoalDistribution.from_dict(json.loads(distribution.to_bytes()))
    assert restored_distribution.to_bytes() == distribution.to_bytes()
    tampered = json.loads(distribution.to_bytes())
    settlement = tampered["settlement_distributions"]["match_winner_home"]
    assert isinstance(settlement, dict)
    settlement["WIN"] += 0.01
    settlement["LOSS"] -= 0.01
    with pytest.raises(T11IntegrityError):
        FullTimeGoalDistribution.from_dict(tampered)
    assert fit.frozen_evidence_digest == state.digest
    assert fit.training_input_fixture_ids
    assert fit.training_input_digests
    assert fit.reproducibility["randomness"] == "none"
    assert fit.reproducibility["history_order"] == "fixture_id_ascending"
    assert fit.reproducibility["preference_ids"] == FULL_TIME_GOAL_PREFERENCE_IDS


def test_t11_artifacts_publish_and_reload_through_the_private_store(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.t11 import T11ArtifactRecorder, fit_full_time_goal_model

    private_root = tmp_path / "private"
    private_root.mkdir()
    history = _history()
    state = _state(history)
    fit = fit_full_time_goal_model(history, state)
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = T11ArtifactRecorder(store)
        published = recorder.publish(fit)
        loaded_fit = recorder.load_fit(published.fit_artifact_digest)
        loaded_distribution = recorder.load_distribution(published.distribution_artifact_digest)
    assert published.fit.digest == fit.digest
    assert loaded_fit.to_bytes() == fit.to_bytes()
    assert loaded_distribution.to_bytes() == published.distribution.to_bytes()

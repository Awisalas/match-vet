from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from matchvet.t09 import FrozenEvidenceState, HistoricalMatch, TargetMatch
    from matchvet.t13 import CornerModelFit


def _target() -> TargetMatch:
    from matchvet.t09 import TargetMatch

    return TargetMatch(
        matchweek_id="mw-t13",
        cutoff_id="cutoff-t13",
        fixture_id="fixture-t13",
        cutoff_utc="2026-10-01T12:00:00+00:00",
        kickoff_utc="2026-10-01T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
        venue_id="venue-t13",
        venue_name="T13 Stadium",
        source_assertion_ids=("target-t13",),
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
        rows.append(
            HistoricalMatch(
                fixture_id=f"history-t13-{index:02d}",
                home_team_id=home,
                away_team_id=away,
                kickoff_utc=f"{kickoff}T20:00:00+00:00",
                full_time_home_goals=(index * 3 + 1) % 4,
                full_time_away_goals=(index + 2) % 3,
                corners_home=3 + (index * 3) % 7,
                corners_away=2 + (index * 5) % 8,
                source_assertion_ids=(f"assertion-t13-{index:02d}",),
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


@pytest.fixture(scope="module")
def fitted_case() -> tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit]:
    from matchvet.t13 import CornerModelFit, fit_joint_corner_model

    history = _history()
    state = _state(history)
    fit = fit_joint_corner_model(history, state)
    assert isinstance(fit, CornerModelFit)
    return history, state, fit


def test_t13_fit_returns_one_normalized_joint_corner_surface_and_all_markets(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t11 import ModelStatus

    _, state, fit = fitted_case
    assert fit.status is ModelStatus.AVAILABLE

    prediction = fit.predict(state)
    assert prediction.status is ModelStatus.AVAILABLE
    joint = np.asarray(prediction.joint_corner_distribution)
    assert joint.ndim == 2
    assert joint.shape[0] == joint.shape[1]
    assert np.all(np.isfinite(joint))
    assert np.all(joint >= 0.0)
    assert np.isclose(joint.sum(), 1.0, atol=1e-12)
    assert set(prediction.settlement_distributions) == {
        "corner_winner_home",
        "corner_winner_draw",
        "corner_winner_away",
        "total_corners_over_8_5",
        "total_corners_over_9_5",
        "total_corners_over_10_5",
        "home_corners_over_3_5",
        "home_corners_over_4_5",
        "home_corners_over_5_5",
        "away_corners_over_3_5",
        "away_corners_over_4_5",
        "away_corners_over_5_5",
    }


def test_t13_fit_and_prediction_are_deterministic_for_frozen_inputs(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t13 import fit_joint_corner_model

    history, state, first = fitted_case
    second = fit_joint_corner_model(tuple(reversed(history)), state)
    assert first.to_bytes() == second.to_bytes()
    assert first.predict(state).to_bytes() == second.predict(state).to_bytes()


def test_t13_joint_surface_has_positive_dependence_and_overdispersion(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    _, state, fit = fitted_case
    prediction = fit.predict(state)

    assert prediction.shared_pace_dispersion is not None
    assert prediction.shared_pace_dispersion > 0.0
    assert prediction.corner_covariance is not None
    assert prediction.corner_covariance > 0.0
    assert prediction.corner_correlation is not None
    assert prediction.corner_correlation > 0.0
    assert prediction.home_expected_corners is not None
    assert prediction.away_expected_corners is not None
    assert prediction.home_corner_variance is not None
    assert prediction.away_corner_variance is not None
    assert prediction.home_corner_variance > prediction.home_expected_corners
    assert prediction.away_corner_variance > prediction.away_expected_corners


def test_t13_corner_winner_markets_are_marginals_of_the_joint_surface(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    _, state, fit = fitted_case
    prediction = fit.predict(state)
    joint = np.asarray(prediction.joint_distribution)
    home = sum(joint[h, a] for h in range(len(joint)) for a in range(len(joint)) if h > a)
    draw = sum(joint[h, h] for h in range(len(joint)))
    away = sum(joint[h, a] for h in range(len(joint)) for a in range(len(joint)) if h < a)
    markets = prediction.settlement_distributions

    assert np.isclose(markets["corner_winner_home"].win, home)
    assert np.isclose(markets["corner_winner_draw"].win, draw)
    assert np.isclose(markets["corner_winner_away"].win, away)
    assert np.isclose(home + draw + away, 1.0, atol=1e-12)


def test_t13_total_and_team_over_markets_are_monotone_and_have_no_push_mass(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    _, state, fit = fitted_case
    markets = fit.predict(state).settlement_distributions

    assert (
        markets["total_corners_over_8_5"].win
        >= markets["total_corners_over_9_5"].win
        >= markets["total_corners_over_10_5"].win
    )
    assert (
        markets["home_corners_over_3_5"].win
        >= markets["home_corners_over_4_5"].win
        >= markets["home_corners_over_5_5"].win
    )
    assert (
        markets["away_corners_over_3_5"].win
        >= markets["away_corners_over_4_5"].win
        >= markets["away_corners_over_5_5"].win
    )
    assert all(value.push == 0.0 for value in markets.values())
    assert all(np.isclose(value.win + value.loss + value.push, 1.0) for value in markets.values())


def test_t13_sparse_teams_borrow_league_and_hierarchical_evidence(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    history, _, _ = fitted_case
    target = replace(
        _target(),
        home_team_id="team-new-home",
        away_team_id="team-new-away",
    )
    state = _state_for_target(history, target)
    fit = fit_joint_corner_model(history, state)

    assert fit.status is ModelStatus.AVAILABLE
    team_for = fit.parameters["team_corner_for"]
    assert isinstance(team_for, Mapping)
    assert "team-new-home" in team_for
    assert "team-new-away" in team_for
    teams = fit.uncertainty["teams"]
    assert isinstance(teams, Mapping)
    assert teams["team-new-home"]["pooling"] == "SHARED_LEAGUE_PRIOR"
    assert teams["team-new-away"]["borrowed_evidence"] is True
    assert fit.predict(state).is_available


def test_t13_multi_league_fit_retains_league_specific_venue_effects() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    base_history = _history()
    history = tuple(
        replace(
            row,
            competition_key="championship" if index < 9 else "premier_league",
        )
        for index, row in enumerate(base_history)
    )
    state = _state(history)
    fit = fit_joint_corner_model(history, state)

    assert fit.status is ModelStatus.AVAILABLE
    intercepts = fit.parameters["league_season_intercepts"]
    venues = fit.parameters["home_venue_effects"]
    dispersions = fit.parameters["league_season_dispersions"]
    assert isinstance(intercepts, Mapping)
    assert isinstance(venues, Mapping)
    assert isinstance(dispersions, Mapping)
    assert set(intercepts) == {"championship:2026-27", "premier_league:2026-27"}
    assert set(venues) == set(intercepts)
    assert set(dispersions) == set(intercepts)


def test_t13_excludes_target_fixture_and_non_target_competition_from_training() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    base_history = _history()
    target_fixture = replace(base_history[0], fixture_id=_target().fixture_id)
    cup_fixture = replace(base_history[1], competition_type="DOMESTIC_CUP")
    history = (target_fixture, cup_fixture, *base_history[2:])
    state = _state(history)
    fit = fit_joint_corner_model(history, state)

    assert fit.status is ModelStatus.AVAILABLE
    assert _target().fixture_id not in fit.training_input_fixture_ids
    assert cup_fixture.fixture_id not in fit.training_input_fixture_ids
    invalid_reasons = fit.diagnostics["invalid_history_reasons"]
    assert isinstance(invalid_reasons, Mapping)
    assert invalid_reasons[cup_fixture.fixture_id] == "NON_TARGET_COMPETITION_EXCLUDED"


def test_t13_opponent_venue_and_recency_features_change_target_rates(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t13 import fit_joint_corner_model

    history, base_state, _ = fitted_case
    base = fit_joint_corner_model(history, base_state).predict(base_state)
    opponent_state = _state_with_feature(
        history,
        "D-OPPONENT-STRENGTH",
        {
            "team-home": {"corners": {"opponent_adjusted": {"mean_difference": 6.0}}},
            "team-away": {"corners": {"opponent_adjusted": {"mean_difference": 0.0}}},
        },
        "opponent-t13",
    )
    venue_state = _state_with_feature(
        history,
        "D-VENUE-EFFECT",
        {
            "team-home": {"corners": {"venue_effect": 6.0}},
            "team-away": {"corners": {"venue_effect": 0.0}},
        },
        "venue-t13-feature",
    )
    recency_state = _state_with_feature(
        history,
        "D-RECENCY-STRENGTH",
        {
            "team-home": {"corners": {"weighted_mean": 12.0}},
            "team-away": {"corners": {"weighted_mean": 0.0}},
        },
        "recency-t13",
    )

    opponent = fit_joint_corner_model(history, opponent_state).predict(opponent_state)
    venue = fit_joint_corner_model(history, venue_state).predict(venue_state)
    recency = fit_joint_corner_model(history, recency_state).predict(recency_state)
    assert base.home_expected_corners is not None
    assert opponent.home_expected_corners is not None
    assert venue.home_expected_corners is not None
    assert recency.home_expected_corners is not None
    assert opponent.home_expected_corners > base.home_expected_corners
    assert venue.home_expected_corners > base.home_expected_corners
    assert recency.home_expected_corners > base.home_expected_corners


def test_t13_rest_congestion_and_regime_inputs_are_retained_and_used(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t13 import fit_joint_corner_model

    history, base_state, _ = fitted_case
    schedule_state = _state_with_feature(
        history,
        "D-REST",
        {"home": 14.0, "away": 3.0},
        "rest-t13",
    )
    schedule_state = replace(
        schedule_state,
        derived_features=tuple(
            replace(
                feature,
                state=(feature.state if feature.name != "D-CONGESTION" else "OBSERVED"),
                value=(
                    feature.value
                    if feature.name != "D-CONGESTION"
                    else {"home": {"count": 0}, "away": {"count": 5}}
                ),
                input_ids=("congestion-t13",)
                if feature.name == "D-CONGESTION"
                else feature.input_ids,
                input_digests=("c" * 64,)
                if feature.name == "D-CONGESTION"
                else feature.input_digests,
                digest="",
            )
            for feature in schedule_state.derived_features
        ),
        state_digest="",
    )
    schedule_fit = fit_joint_corner_model(history, schedule_state)
    base_fit = fit_joint_corner_model(history, base_state)
    schedule_prediction = schedule_fit.predict(schedule_state)
    base_prediction = base_fit.predict(base_state)
    assert schedule_prediction.home_expected_corners is not None
    assert base_prediction.home_expected_corners is not None
    assert schedule_prediction.home_expected_corners > base_prediction.home_expected_corners
    offsets = schedule_fit.parameters["target_feature_offsets"]
    assert isinstance(offsets, Mapping)
    feature_names = offsets["feature_names"]
    assert isinstance(feature_names, tuple)
    assert "D-REST" in feature_names
    assert "D-CONGESTION" in feature_names
    components = offsets["components"]
    assert isinstance(components, Mapping)
    schedule_components = components["schedule"]
    assert isinstance(schedule_components, Mapping)
    away_schedule = schedule_components["away"]
    assert isinstance(away_schedule, float)
    assert away_schedule < -0.02
    congestion_feature = next(
        feature for feature in schedule_state.derived_features if feature.name == "D-CONGESTION"
    )
    assert congestion_feature.feature_id in schedule_fit.feature_input_ids

    regime_history = tuple(
        replace(row, regime_id="high-pace" if index < 9 else "stable")
        for index, row in enumerate(history)
    )
    regime_state = _state_with_feature(
        regime_history,
        "E-TACTICAL-REGIME",
        {"regime_id": "high-pace"},
        "regime-t13",
    )
    regime_fit = fit_joint_corner_model(regime_history, regime_state)
    assert regime_fit.diagnostics["regime_match_weight"] == 1.0
    assert regime_fit.parameters["target_regime_id"] == "high-pace"
    regime_effective = regime_fit.diagnostics["training_effective_matches"]
    base_effective = base_fit.diagnostics["training_effective_matches"]
    assert isinstance(regime_effective, float)
    assert isinstance(base_effective, float)
    assert regime_effective < base_effective


def test_t13_missing_corner_history_is_not_imputed_and_can_be_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import derive_corner_history, fit_joint_corner_model

    history = _history()
    incomplete = tuple(
        replace(row, corners_home=None, corners_away=None) if index < 16 else row
        for index, row in enumerate(history)
    )
    assert len(derive_corner_history(incomplete)) == 2
    fit = fit_joint_corner_model(incomplete, _state(incomplete))
    assert fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert fit.reason == "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"
    assert fit.predict().settlement_distributions == {}


def test_t13_unresolved_corner_conflict_is_model_unavailable() -> None:
    from matchvet.t09 import MaterialConflict
    from matchvet.t10 import CORNER_FACTS
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    history = _history()
    state = _state(history)
    conflict = MaterialConflict(
        conflict_id="conflict-t13-corners",
        subject_id=history[0].fixture_id,
        evidence_type="MATCH_STATISTIC",
        predicate=CORNER_FACTS[0],
        assertion_ids=("corner-a", "corner-b"),
        values=(history[0].corners_home, 99),
    )
    conflicted = replace(state, conflicts=(*state.conflicts, conflict), state_digest="")
    fit = fit_joint_corner_model(history, conflicted)
    assert fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert fit.reason == "UNRESOLVED_MATERIAL_CONFLICT"


def test_t13_frozen_history_digest_mismatch_is_model_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    history = _history()
    state = _state(history)
    assert history[0].corners_home is not None
    changed = replace(history[0], corners_home=history[0].corners_home + 1)
    fit = fit_joint_corner_model((changed, *history[1:]), state)
    assert fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert fit.reason == "FROZEN_HISTORY_INPUTS_MISMATCH"


def test_t13_frozen_history_metadata_mismatch_is_model_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    history = _history()
    state = _state(history)
    first = history[0]
    reproducibility = dict(state.reproducibility)
    reproducibility["input_history_metadata"] = {
        first.fixture_id: {
            "home_team_id": first.home_team_id,
            "away_team_id": first.away_team_id,
            "competition_key": first.competition_key,
            "kickoff_utc": first.kickoff_utc,
            "regime_id": first.regime_id,
        }
    }
    frozen = replace(state, reproducibility=reproducibility, state_digest="")
    changed = replace(first, home_team_id="team-metadata-mismatch")
    fit = fit_joint_corner_model((changed, *history[1:]), frozen)

    assert fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert fit.reason == "FROZEN_HISTORY_INPUTS_MISMATCH"


def test_t13_conflicting_duplicate_corner_rows_are_model_unavailable() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import fit_joint_corner_model

    history = _history()
    state = _state(history)
    first = history[0]
    assert first.corners_home is not None
    conflicting = replace(first, corners_home=first.corners_home + 1)
    fit = fit_joint_corner_model((first, conflicting, *history[1:]), state)

    assert fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert fit.reason == "CONFLICTING_CORNER_HISTORY"


def test_t13_numerical_stability_and_invalid_fit_are_explicit() -> None:
    from matchvet.t11 import ModelStatus
    from matchvet.t13 import T13ModelConfig, T13ValidationError, fit_joint_corner_model

    history = _history()
    state = _state(history)
    stable_config = T13ModelConfig(
        shared_pace_dispersion=0.4,
        maximum_expected_corners=25.0,
        maximum_corner_count=96,
    )
    stable_fit = fit_joint_corner_model(history, state, config=stable_config)
    stable_prediction = stable_fit.predict(state)
    assert stable_fit.status is ModelStatus.AVAILABLE
    assert np.all(np.isfinite(np.asarray(stable_prediction.joint_distribution)))
    assert np.isclose(np.asarray(stable_prediction.joint_distribution).sum(), 1.0)

    failed_fit = fit_joint_corner_model(
        history, state, config=T13ModelConfig(optimizer_max_iterations=1)
    )
    assert failed_fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert failed_fit.reason == "FIT_FAILED"
    tail_fit = fit_joint_corner_model(history, state, config=T13ModelConfig(maximum_corner_count=2))
    assert tail_fit.status is ModelStatus.MODEL_UNAVAILABLE
    assert tail_fit.reason == "FIT_FAILED"
    with pytest.raises(T13ValidationError):
        T13ModelConfig(shared_pace_dispersion=0.0)


def test_t13_fit_and_distribution_round_trip_preserve_frozen_metadata(
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.t13 import CORNER_PREFERENCE_IDS, CornerDistribution, CornerModelFit

    _, state, fit = fitted_case
    distribution = fit.predict(state)
    restored_fit = CornerModelFit.from_dict(json.loads(fit.to_bytes()))
    restored_distribution = CornerDistribution.from_dict(json.loads(distribution.to_bytes()))
    assert restored_fit.to_bytes() == fit.to_bytes()
    assert restored_distribution.to_bytes() == distribution.to_bytes()
    assert fit.frozen_evidence_digest == state.digest
    assert fit.training_input_fixture_ids
    assert fit.training_input_digests
    assert fit.reproducibility["randomness"] == "none"
    assert fit.reproducibility["history_order"] == "fixture_id_ascending"
    assert fit.reproducibility["preference_ids"] == CORNER_PREFERENCE_IDS


def test_t13_artifacts_publish_and_reload_through_the_private_store(
    tmp_path: Path,
    fitted_case: tuple[tuple[HistoricalMatch, ...], FrozenEvidenceState, CornerModelFit],
) -> None:
    from matchvet.store import open_store
    from matchvet.t13 import T13ArtifactRecorder

    _, state, fit = fitted_case
    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        recorder = T13ArtifactRecorder(store)
        published = recorder.publish(fit, fit.predict(state))
        loaded_fit = recorder.load_fit(published.fit_artifact_digest)
        loaded_distribution = recorder.load_distribution(published.distribution_artifact_digest)
    assert published.fit.digest == fit.digest
    assert loaded_fit.to_bytes() == fit.to_bytes()
    assert loaded_distribution.to_bytes() == published.distribution.to_bytes()

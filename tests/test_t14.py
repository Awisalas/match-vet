from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from matchvet.t09 import FrozenEvidenceState
from matchvet.t11 import SettlementProbabilities
from matchvet.t14 import (
    CalibrationFit,
    CalibrationObservation,
    DistributionInput,
    ModelFamily,
    ReferenceModel,
    ReferenceModelKind,
    T14Config,
    T14Status,
    calibrate_distribution,
    calibrate_model_families,
    compute_model_agreement,
    fit_calibration,
    laplace_parameter_draws,
)


def _surface() -> tuple[tuple[float, ...], ...]:
    return (
        (0.20, 0.12, 0.05),
        (0.16, 0.14, 0.08),
        (0.08, 0.10, 0.07),
    )


def _distribution(
    family: ModelFamily = ModelFamily.FULL_TIME_GOALS,
    *,
    model_version: str = "t11-test-v1",
    uncertainty: dict[str, object] | None = None,
) -> DistributionInput:
    return DistributionInput(
        family=family,
        target_fixture_id="fixture-t14",
        matchweek_id="mw-t14",
        model_version=model_version,
        model_digest="model-digest-t14",
        surface=_surface(),
        uncertainty=uncertainty or {},
    )


def _observations(
    family: ModelFamily = ModelFamily.FULL_TIME_GOALS,
    distribution: DistributionInput | None = None,
) -> tuple[CalibrationObservation, ...]:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    values = ((2, 1), (1, 0), (3, 2), (0, 1), (2, 2), (1, 3))
    selected_distribution = distribution or _distribution(family)
    return tuple(
        CalibrationObservation(
            fixture_id=f"cal-{index}",
            family=family,
            kickoff_utc=(start + timedelta(days=index)).isoformat(),
            distribution=selected_distribution,
            observed_home_count=home,
            observed_away_count=away,
            observed_total_count=home + away,
            prediction_cutoff_utc=(start + timedelta(days=index) - timedelta(hours=6)).isoformat(),
            model_training_fixture_ids=(f"history-{index}",),
        )
        for index, (home, away) in enumerate(values)
    )


def _fit(
    family: ModelFamily = ModelFamily.FULL_TIME_GOALS,
    distribution: DistributionInput | None = None,
    *,
    config: T14Config | None = None,
) -> CalibrationFit:
    return fit_calibration(
        _observations(family, distribution),
        family=family,
        calibration_end_utc="2026-09-06T23:59:59+00:00",
        config=config or T14Config(minimum_calibration_matches=3, parameter_draws=8),
    )


def _frozen_state(*, structural_change: bool = False) -> FrozenEvidenceState:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput, TargetMatch

    target = TargetMatch(
        matchweek_id="mw-t14",
        cutoff_id="cutoff-t14",
        fixture_id="fixture-t14",
        cutoff_utc="2026-10-01T12:00:00+00:00",
        kickoff_utc="2026-10-01T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
    )
    state = EvidenceResearcher().build(EvidenceResearchInput(target=target))
    if not structural_change:
        return state
    feature = next(item for item in state.derived_features if item.name == "E-TACTICAL-REGIME")
    changed = replace(
        feature,
        state="OBSERVED",
        value={"structural_change": True, "active_regime": "manager-change"},
        input_ids=("regime-t14",),
        input_digests=("r" * 64,),
        digest="",
    )
    return replace(
        state,
        derived_features=tuple(
            changed if item.feature_id == feature.feature_id else item
            for item in state.derived_features
        ),
        state_digest="",
    )


def test_t14_fits_affine_calibration_only_from_chronological_development_evidence() -> None:
    observations = _observations()
    future = CalibrationObservation(
        fixture_id="cal-future",
        family=ModelFamily.FULL_TIME_GOALS,
        kickoff_utc="2026-10-01T20:00:00+00:00",
        distribution=_distribution(),
        observed_home_count=20,
        observed_away_count=20,
        prediction_cutoff_utc="2026-10-01T14:00:00+00:00",
        model_training_fixture_ids=("history-future",),
    )
    fit = fit_calibration(
        (*observations, future),
        family=ModelFamily.FULL_TIME_GOALS,
        calibration_end_utc="2026-09-06T23:59:59+00:00",
        config=T14Config(minimum_calibration_matches=3),
    )

    assert fit.status is T14Status.AVAILABLE
    assert fit.used_fixture_ids == tuple(item.fixture_id for item in observations)
    assert "cal-future" in cast(tuple[str, ...], fit.diagnostics["future_excluded_fixture_ids"])
    assert fit.provenance["chronology_enforced"] is True
    assert fit.parameters["home"].slope != 1.0 or fit.parameters["home"].intercept != 0.0


def test_t14_calibrates_surface_before_settlement_and_preserves_coherence() -> None:
    fit = fit_calibration(
        _observations(),
        family=ModelFamily.FULL_TIME_GOALS,
        calibration_end_utc="2026-09-06T23:59:59+00:00",
        config=T14Config(minimum_calibration_matches=3),
    )
    result = calibrate_distribution(_distribution(), calibration_fit=fit, seed=7)

    assert result.status is T14Status.AVAILABLE
    assert result.surface != _surface()
    assert sum(sum(row) for row in result.surface) == pytest.approx(1.0)
    assert result.settlement_distributions["match_goals_over_1_5"].win >= (
        result.settlement_distributions["match_goals_over_2_5"].win
    )
    assert result.settlement_distributions["match_goals_over_2_5"].win >= (
        result.settlement_distributions["match_goals_over_3_5"].win
    )
    assert result.settlement_distributions["double_chance_1x"].win == pytest.approx(
        result.settlement_distributions["match_winner_home"].win
        + result.settlement_distributions["match_winner_draw"].win
    )
    assert result.provenance["calibration_fit_digest"] == fit.digest
    assert result.diagnostics["calibration_method"] == "affine_mean_exponential_tilt_v1"


def test_t14_uncertainty_is_laplace_settlement_aware_and_conservative() -> None:
    fit = _fit()
    result = calibrate_distribution(_distribution(), calibration_fit=fit, seed=11)

    assert result.status is T14Status.AVAILABLE
    assert result.model_agreement is not None
    laplace = cast(dict[str, object], result.uncertainty["laplace"])
    assert laplace["method"] == "laplace-penalized-map-diagonal-v1"
    handicap = result.probability_intervals["asian_handicap_home_0_0"]
    assert set(handicap) == {"WIN", "LOSS", "PUSH"}
    assert handicap["LOSS"].upper >= handicap["LOSS"].estimated
    assert handicap["PUSH"].upper >= handicap["PUSH"].estimated
    assert result.loss_probability_upper["asian_handicap_home_0_0"] >= (
        result.settlement_distributions["asian_handicap_home_0_0"].loss
    )
    assert all(
        result.conservative_probabilities[key] <= result.estimated_probabilities[key] + 1e-12
        for key in result.estimated_probabilities
    )


def test_t14_more_parameter_uncertainty_widens_and_lowers_conservative_probability() -> None:
    fit = _fit()
    base = calibrate_distribution(
        _distribution(),
        calibration_fit=fit,
        model_fit=SimpleNamespace(
            uncertainty={"effective_sample_size": 1000.0},
            diagnostics={},
        ),
        seed=17,
    )
    uncertain = calibrate_distribution(
        _distribution(),
        calibration_fit=fit,
        model_fit=SimpleNamespace(
            uncertainty={
                "effective_sample_size": 1.0,
                "prediction_uncertainty_multiplier": 3.0,
                "teams": {"home": {"borrowed_evidence": True, "uncertainty_multiplier": 2.0}},
            },
            diagnostics={},
        ),
        seed=17,
    )

    preference = "match_goals_over_2_5"
    assert cast(float, uncertain.uncertainty["total_multiplier"]) > cast(
        float, base.uncertainty["total_multiplier"]
    )
    assert uncertain.conservative_probabilities[preference] <= (
        base.conservative_probabilities[preference] + 1e-12
    )
    assert uncertain.probability_intervals[preference]["WIN"].standard_deviation >= (
        base.probability_intervals[preference]["WIN"].standard_deviation
    )


def test_t14_laplace_draws_are_deterministic_and_include_penalized_curvature() -> None:
    first = laplace_parameter_draws(
        ModelFamily.CORNERS,
        {"home": 5.0, "away": 4.0},
        config=T14Config(parameter_draws=12),
        seed=23,
    )
    second = laplace_parameter_draws(
        ModelFamily.CORNERS,
        {"home": 5.0, "away": 4.0},
        config=T14Config(parameter_draws=12),
        seed=23,
    )

    assert first.to_dict() == second.to_dict()
    assert first.hessian[0][0] > first.penalty_precision[0]
    assert len(first.draws) == 12
    assert all(len(draw) == 2 for draw in first.draws)


def test_t14_references_measure_meaningful_sensitivity_once_per_dependency_group() -> None:
    fit = _fit()
    primary = calibrate_distribution(_distribution(), calibration_fit=fit, seed=5)
    correlated_a = ReferenceModel(
        name="reduced-a",
        kind=ReferenceModelKind.REDUCED,
        dependency_group="same-count-chain",
        settlement_distributions=primary.settlement_distributions,
        correlated=True,
    )
    correlated_b = ReferenceModel(
        name="bivariate-b",
        kind=ReferenceModelKind.BIVARIATE,
        dependency_group="same-count-chain",
        settlement_distributions={
            key: SettlementProbabilities(
                win_probability=min(1.0 - value.push, value.win + 0.08),
                push_probability=value.push,
                loss_probability=max(
                    0.0, 1.0 - min(1.0 - value.push, value.win + 0.08) - value.push
                ),
            )
            for key, value in primary.settlement_distributions.items()
        },
        correlated=True,
    )
    independent = ReferenceModel(
        name="empirical-independent",
        kind=ReferenceModelKind.EMPIRICAL,
        dependency_group="empirical-chain",
        settlement_distributions=correlated_b.settlement_distributions,
    )
    sensitivity = compute_model_agreement(
        primary.settlement_distributions,
        (correlated_a, correlated_b, independent),
    )

    assert sensitivity.agreement < 1.0
    assert sensitivity.effective_dependency_groups == (
        "empirical-chain",
        "same-count-chain",
    )
    assert sensitivity.correlated_reference_groups == ("same-count-chain",)
    assert sensitivity.meaningful_reference_names
    assert sensitivity.uncertainty_multiplier > 1.0


def test_t14_calibrates_all_model_families_without_cross_family_mixing() -> None:
    full = _distribution(ModelFamily.FULL_TIME_GOALS, model_version="t11-v1")
    first = _distribution(ModelFamily.FIRST_HALF_GOALS, model_version="t12-first-v1")
    second = _distribution(ModelFamily.SECOND_HALF_GOALS, model_version="t12-second-v1")
    corners = _distribution(ModelFamily.CORNERS, model_version="t13-v1")
    observations = (
        *_observations(ModelFamily.FULL_TIME_GOALS, full),
        *_observations(ModelFamily.FIRST_HALF_GOALS, first),
        *_observations(ModelFamily.SECOND_HALF_GOALS, second),
        *_observations(ModelFamily.CORNERS, corners),
    )
    bundle = calibrate_model_families(
        {
            "full_time": full,
            "first_half": first,
            "second_half": second,
            "corners": corners,
        },
        calibration_records=observations,
        calibration_end_utc="2026-09-06T23:59:59+00:00",
        config=T14Config(minimum_calibration_matches=3, parameter_draws=16),
        seed=31,
    )

    assert bundle.status is T14Status.AVAILABLE
    assert set(bundle.predictions) == {
        "FULL_TIME_GOALS",
        "FIRST_HALF_GOALS",
        "SECOND_HALF_GOALS",
        "CORNERS",
    }
    assert all(item.is_available for item in bundle.predictions.values())
    assert all(
        cast(dict[str, object], item.uncertainty["laplace"])["family"]
        for item in bundle.predictions.values()
    )


def test_t14_from_prediction_derives_second_half_outcome_and_keeps_input_lineage() -> None:
    distribution = replace(
        _distribution(ModelFamily.SECOND_HALF_GOALS),
        artifact_digest="artifact-t14",
        distribution_digest="",
    )
    outcome = SimpleNamespace(
        full_time_home_goals=3,
        full_time_away_goals=1,
        half_time_home_goals=1,
        half_time_away_goals=0,
    )
    record = CalibrationObservation.from_prediction(
        fixture_id="second-half-outcome",
        kickoff_utc="2026-09-10T20:00:00+00:00",
        distribution=distribution,
        outcome=outcome,
        family=ModelFamily.SECOND_HALF_GOALS,
        prediction_cutoff_utc="2026-09-10T14:00:00+00:00",
    )

    assert record.observed_total_count == 3
    fit = _fit(ModelFamily.SECOND_HALF_GOALS, distribution)
    result = calibrate_distribution(distribution, calibration_fit=fit, seed=47)

    assert result.provenance["distribution_input_digest"] == distribution.digest
    assert result.provenance["artifact_digest"] == "artifact-t14"
    calibration_provenance = cast(dict[str, object], result.provenance["calibration_provenance"])
    assert "calibration_training_fixture_ids" in calibration_provenance


def test_t14_half_and_corner_calibration_preserve_related_market_ordering() -> None:
    first_distribution = _distribution(ModelFamily.FIRST_HALF_GOALS)
    first = calibrate_distribution(
        first_distribution,
        calibration_fit=_fit(ModelFamily.FIRST_HALF_GOALS, first_distribution),
        config=T14Config(parameter_draws=8),
        seed=41,
    )
    corner_distribution = _distribution(ModelFamily.CORNERS)
    corners = calibrate_distribution(
        corner_distribution,
        calibration_fit=_fit(ModelFamily.CORNERS, corner_distribution),
        config=T14Config(parameter_draws=8),
        seed=41,
    )

    assert first.is_available
    assert first.settlement_distributions["first_half_over_1_5"].win >= 0.0
    assert corners.is_available
    assert (
        corners.estimated_probabilities["total_corners_over_8_5"]
        >= corners.estimated_probabilities["total_corners_over_9_5"]
        >= corners.estimated_probabilities["total_corners_over_10_5"]
    )
    assert (
        corners.estimated_probabilities["home_corners_over_3_5"]
        >= corners.estimated_probabilities["home_corners_over_4_5"]
        >= corners.estimated_probabilities["home_corners_over_5_5"]
    )
    assert (
        corners.estimated_probabilities["away_corners_over_3_5"]
        >= corners.estimated_probabilities["away_corners_over_4_5"]
        >= corners.estimated_probabilities["away_corners_over_5_5"]
    )


def test_t14_frozen_evidence_and_structural_change_are_explicit_uncertainty_components() -> None:
    fit = _fit()
    routine = calibrate_distribution(
        _distribution(),
        calibration_fit=fit,
        frozen_evidence_state=_frozen_state(),
        config=T14Config(parameter_draws=8),
        seed=43,
    )
    changed = calibrate_distribution(
        _distribution(),
        calibration_fit=fit,
        frozen_evidence_state=_frozen_state(structural_change=True),
        config=T14Config(parameter_draws=8),
        seed=43,
    )

    components = cast(dict[str, object], changed.uncertainty["components"])
    evidence = cast(dict[str, object], components["evidence"])
    structural = cast(dict[str, object], components["structural_change"])
    assert evidence["state_digest"]
    assert structural["detected"] is True
    assert cast(float, changed.uncertainty["total_multiplier"]) > cast(
        float, routine.uncertainty["total_multiplier"]
    )
    assert changed.conservative_probabilities["match_goals_over_2_5"] <= (
        routine.conservative_probabilities["match_goals_over_2_5"] + 1e-12
    )


def test_t14_stale_frozen_evidence_is_a_separate_uncertainty_component() -> None:
    from matchvet.t09 import SourceFact

    fit = _fit()
    routine_state = _frozen_state()
    stale_fact = SourceFact(
        fact_id="stale-t14",
        subject_id="fixture-t14",
        evidence_type="FORM",
        predicate="state",
        state="OBSERVED",
        value="STALE",
        source_key="recorded-t14",
        origin_id="origin-t14",
        source_digest="s" * 64,
        cutoff_eligibility="CUTOFF_VALID",
        freshness="STALE",
    )
    stale_state = replace(
        routine_state,
        source_assertions=(stale_fact,),
        state_digest="",
    )
    routine = calibrate_distribution(
        _distribution(), calibration_fit=fit, frozen_evidence_state=routine_state, seed=61
    )
    stale = calibrate_distribution(
        _distribution(), calibration_fit=fit, frozen_evidence_state=stale_state, seed=61
    )

    components = cast(dict[str, object], stale.uncertainty["components"])
    freshness = cast(dict[str, object], components["evidence_freshness"])
    assert freshness["stale_count"] == 1
    assert cast(float, stale.uncertainty["total_multiplier"]) > cast(
        float, routine.uncertainty["total_multiplier"]
    )


def test_t14_identical_frozen_inputs_versions_and_seed_are_byte_reproducible() -> None:
    distribution = _distribution()
    fit = _fit()
    config = T14Config(parameter_draws=8, seed=53)
    first = calibrate_distribution(distribution, calibration_fit=fit, config=config)
    second = calibrate_distribution(
        DistributionInput.from_model_output(distribution),
        calibration_fit=CalibrationFit.from_dict(fit.to_dict()),
        config=config,
    )

    assert first.to_bytes() == second.to_bytes()
    assert first.digest == second.digest
    assert first.provenance["config_digest"] == config.digest
    assert cast(dict[str, object], first.provenance["randomness"])["seed"] == 53


def test_t14_malformed_or_insufficient_calibration_is_model_unavailable() -> None:
    insufficient = fit_calibration(
        [
            {
                "fixture_id": "bad",
                "family": "FULL_TIME_GOALS",
                "kickoff_utc": "2026-09-01T20:00:00+00:00",
            }
        ],
        family=ModelFamily.FULL_TIME_GOALS,
        calibration_end_utc="2026-09-02T00:00:00+00:00",
    )
    result = calibrate_distribution(_distribution(), calibration_fit=insufficient)

    assert insufficient.status is T14Status.MODEL_UNAVAILABLE
    assert result.status is T14Status.MODEL_UNAVAILABLE
    assert "CALIBRATION" in (result.reason or "")


def test_t14_outcome_leakage_is_rejected_even_inside_the_chronological_window() -> None:
    observations = list(_observations())
    observations[0] = replace(
        observations[0],
        model_training_fixture_ids=(observations[0].fixture_id,),
        record_digest="",
    )
    fit = fit_calibration(
        observations,
        family=ModelFamily.FULL_TIME_GOALS,
        calibration_end_utc="2026-09-06T23:59:59+00:00",
        config=T14Config(minimum_calibration_matches=3),
    )

    assert fit.status is T14Status.MODEL_UNAVAILABLE
    assert fit.reason == "OUTCOME_LEAKAGE_DETECTED"


def test_t14_rejects_a_known_future_training_fixture() -> None:
    observations = list(_observations())
    future = replace(
        observations[-1],
        fixture_id="cal-future-training",
        kickoff_utc="2026-09-10T20:00:00+00:00",
        prediction_cutoff_utc="2026-09-10T14:00:00+00:00",
        record_digest="",
    )
    observations[0] = replace(
        observations[0],
        model_training_fixture_ids=(future.fixture_id,),
        record_digest="",
    )

    fit = fit_calibration(
        (*observations[:-1], future),
        family=ModelFamily.FULL_TIME_GOALS,
        calibration_end_utc="2026-09-11T00:00:00+00:00",
        config=T14Config(minimum_calibration_matches=3),
    )

    assert fit.status is T14Status.MODEL_UNAVAILABLE
    assert fit.reason == "OUTCOME_LEAKAGE_DETECTED"
    leakage = cast(dict[str, object], fit.diagnostics["leakage_training_fixture_ids"])
    assert "cal-0" in leakage
    assert "cal-future-training" in cast(tuple[str, ...], leakage["cal-0"])


def test_t14_extreme_count_masses_remain_finite_and_calibratable() -> None:
    fit = _fit()
    extreme = DistributionInput(
        family=ModelFamily.FULL_TIME_GOALS,
        target_fixture_id="fixture-t14-extreme",
        matchweek_id="mw-t14-extreme",
        model_version="t11-test-v1",
        model_digest="model-digest-extreme",
        surface=(
            (1e-300, 0.0, 0.0),
            (0.0, 1e300, 1e-300),
            (0.0, 0.0, 1e-300),
        ),
    )

    result = calibrate_distribution(extreme, calibration_fit=fit, seed=83)

    assert result.status is T14Status.AVAILABLE
    assert all(math.isfinite(cell) for row in result.surface for cell in row)
    assert all(math.isfinite(value) for value in result.estimated_probabilities.values())

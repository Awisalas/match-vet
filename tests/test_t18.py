from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import matchvet.t18 as t18_module
from matchvet.t18 import (
    CandidatePolicy,
    ChronologicalPeriod,
    EvaluationArtifact,
    EvaluationConfig,
    EvaluationCriterion,
    EvaluationError,
    EvaluationRunner,
    HistoricalEvaluation,
    evaluate_observations,
    evaluate_policies,
    generate_rolling_origin_folds,
    read_evaluation_checkpoint,
    validate_evaluation_contract,
)


def _observation(
    *,
    match_id: str = "match-1",
    matchweek_id: str = "mw-1",
    matchweek_start_utc: str = "2026-08-07T00:00:00+00:00",
    kickoff_at_utc: str = "2026-08-08T14:00:00+00:00",
    research_cutoff_at_utc: str = "2026-08-08T08:00:00+00:00",
    outcome_known_at_utc: str = "2026-08-08T18:00:00+00:00",
    policy_digest: str = "a" * 64,
    outcome_use: str = "UNSEEN",
    input_observed_at_utc: dict[str, str] | None = None,
) -> HistoricalEvaluation:
    fixture_revision = {"kickoff_at_utc": kickoff_at_utc, "match_id": match_id}
    fixture_revision_digest = hashlib.sha256(
        json.dumps(fixture_revision, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    membership_manifest = {
        "fixture_revision_digests": [fixture_revision_digest],
        "matchweek_id": matchweek_id,
    }
    membership_manifest_digest = hashlib.sha256(
        json.dumps(membership_manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return HistoricalEvaluation(
        match_id=match_id,
        matchweek_id=matchweek_id,
        matchweek_start_utc=matchweek_start_utc,
        kickoff_at_utc=kickoff_at_utc,
        research_cutoff_at_utc=research_cutoff_at_utc,
        prediction_created_at_utc=research_cutoff_at_utc,
        outcome_known_at_utc=outcome_known_at_utc,
        league="Premier League",
        preference_id="match_winner_home",
        preference_family="Match Winner",
        exact_line="Home",
        policy_version="policy-a",
        policy_digest=policy_digest,
        model_version="model-1",
        model_digest="b" * 64,
        evidence_digest="c" * 64,
        input_digest="d" * 64,
        membership_manifest=membership_manifest,
        membership_manifest_digest=membership_manifest_digest,
        fixture_revision=fixture_revision,
        fixture_revision_digest=fixture_revision_digest,
        estimated_probability=0.7,
        conservative_probability=0.6,
        uncertainty_lower=0.55,
        uncertainty_upper=0.8,
        settlement="WIN",
        recommendation="CANDIDATE",
        correlation_group="match-result",
        input_observed_at_utc=input_observed_at_utc
        or {
            "fixture_revision": "2026-08-07T20:00:00+00:00",
            "membership_manifest": "2026-08-07T20:00:00+00:00",
        },
        training_data_end_utc=matchweek_start_utc,
        model_fitted_at_utc=matchweek_start_utc,
        calibration_digest="e" * 64,
        baseline_digest="f" * 64,
        outcome_use=outcome_use,
    )


def _candidate(
    *,
    version: str = "policy-a",
    digest: str = "a" * 64,
    development_data_end_utc: str = "2026-08-21T00:00:00+00:00",
    frozen_at_utc: str = "2026-08-28T00:00:00+00:00",
    parameters: dict[str, object] | None = None,
    inspected_evaluation_digests: tuple[str, ...] = (),
) -> CandidatePolicy:
    return CandidatePolicy(
        version=version,
        digest=digest,
        development_data_end_utc=development_data_end_utc,
        frozen_at_utc=frozen_at_utc,
        parameters=parameters or {"conservative_probability_min": 0.6},
        inspected_evaluation_digests=inspected_evaluation_digests,
    )


def _replace_observation(
    observation: HistoricalEvaluation, **changes: object
) -> HistoricalEvaluation:
    match_id = str(changes.get("match_id", observation.match_id))
    matchweek_id = str(changes.get("matchweek_id", observation.matchweek_id))
    kickoff = str(changes.get("kickoff_at_utc", observation.kickoff_at_utc))
    fixture_revision = {"kickoff_at_utc": kickoff, "match_id": match_id}
    fixture_revision_digest = hashlib.sha256(
        json.dumps(fixture_revision, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    membership_manifest = {
        "fixture_revision_digests": [fixture_revision_digest],
        "matchweek_id": matchweek_id,
    }
    membership_manifest_digest = hashlib.sha256(
        json.dumps(membership_manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return replace(
        observation,
        **changes,  # type: ignore[arg-type]
        fixture_revision=fixture_revision,
        fixture_revision_digest=fixture_revision_digest,
        membership_manifest=membership_manifest,
        membership_manifest_digest=membership_manifest_digest,
    )


def _share_membership(
    observations: tuple[HistoricalEvaluation, ...],
) -> tuple[HistoricalEvaluation, ...]:
    manifest = {
        "fixture_revision_digests": sorted(item.fixture_revision_digest for item in observations),
        "matchweek_id": observations[0].matchweek_id,
    }
    digest = hashlib.sha256(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return tuple(
        replace(
            item,
            membership_manifest=manifest,
            membership_manifest_digest=digest,
        )
        for item in observations
    )


def _config() -> EvaluationConfig:
    return EvaluationConfig(
        development=ChronologicalPeriod(
            "DEVELOPMENT",
            "2026-08-07T00:00:00+00:00",
            "2026-08-21T00:00:00+00:00",
        ),
        validation=ChronologicalPeriod(
            "VALIDATION",
            "2026-08-21T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
        ),
        evaluation=ChronologicalPeriod(
            "EVALUATION",
            "2026-08-28T00:00:00+00:00",
            "2026-09-11T00:00:00+00:00",
        ),
        minimum_development_matchweeks=1,
        rolling_validation_matchweeks=1,
        rolling_step_matchweeks=1,
        seed=17,
    )


def _policy_observation(
    *,
    candidate: CandidatePolicy,
    period: str,
    settlement: str,
    estimated_probability: float,
) -> HistoricalEvaluation:
    if period == "VALIDATION":
        base = _observation(
            match_id="validation-match",
            matchweek_id="mw-validation",
            matchweek_start_utc="2026-08-21T00:00:00+00:00",
            kickoff_at_utc="2026-08-22T14:00:00+00:00",
            research_cutoff_at_utc="2026-08-22T08:00:00+00:00",
            outcome_known_at_utc="2026-08-22T18:00:00+00:00",
        )
    elif period == "EVALUATION":
        base = _observation(
            match_id="evaluation-match",
            matchweek_id="mw-evaluation",
            matchweek_start_utc="2026-08-28T00:00:00+00:00",
            kickoff_at_utc="2026-08-29T14:00:00+00:00",
            research_cutoff_at_utc="2026-08-29T08:00:00+00:00",
            outcome_known_at_utc="2026-08-29T18:00:00+00:00",
        )
    else:
        base = _observation(
            match_id="development-match",
            matchweek_id="mw-development",
            matchweek_start_utc="2026-08-07T00:00:00+00:00",
            kickoff_at_utc="2026-08-08T14:00:00+00:00",
            research_cutoff_at_utc="2026-08-08T08:00:00+00:00",
            outcome_known_at_utc="2026-08-08T18:00:00+00:00",
        )
    return replace(
        base,
        policy_version=candidate.version,
        policy_digest=candidate.digest,
        estimated_probability=estimated_probability,
        conservative_probability=max(0.0, estimated_probability - 0.1),
        uncertainty_lower=max(0.0, estimated_probability - 0.2),
        uncertainty_upper=min(1.0, estimated_probability + 0.1),
        settlement=settlement,
    )


def test_historical_evaluation_rejects_non_utc_timestamp() -> None:
    with pytest.raises(EvaluationError, match="UTC offset"):
        _observation(kickoff_at_utc="2026-08-08T14:00:00")


def test_historical_evaluation_rejects_non_string_timestamp_cleanly() -> None:
    with pytest.raises(EvaluationError, match="ISO-8601"):
        replace(_observation(), kickoff_at_utc=None)  # type: ignore[arg-type]


def test_historical_evaluation_rejects_future_input_at_cutoff() -> None:
    with pytest.raises(EvaluationError, match="after the Research Cutoff"):
        _observation(input_observed_at_utc={"confirmed_lineup": "2026-08-08T13:00:00+00:00"})


def test_historical_evaluation_rejects_tampered_membership_manifest() -> None:
    with pytest.raises(EvaluationError, match="Membership Manifest digest"):
        replace(
            _observation(),
            membership_manifest={
                "fixture_revision_digests": ["0" * 64],
                "matchweek_id": "mw-1",
            },
        )


def test_historical_evaluation_rejects_substituted_fixture_revision() -> None:
    row = _observation()
    substituted = {"kickoff_at_utc": row.kickoff_at_utc, "match_id": "other-match"}
    substituted_digest = hashlib.sha256(
        json.dumps(substituted, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(EvaluationError, match="identity or kickoff"):
        replace(
            row,
            fixture_revision=substituted,
            fixture_revision_digest=substituted_digest,
        )


def test_historical_evaluation_rejects_prediction_after_kickoff() -> None:
    with pytest.raises(EvaluationError, match="before kickoff"):
        replace(
            _observation(),
            prediction_created_at_utc="2026-08-08T14:01:00+00:00",
        )


@pytest.mark.parametrize(
    "distribution",
    [
        {"WIN": 0.7, "LOSS": 0.3},
        {"WIN": 0.7, "PUSH": 0.2, "LOSS": 0.2},
        {"WIN": 0.6, "PUSH": 0.1, "LOSS": 0.3},
    ],
)
def test_settlement_distribution_must_be_complete_coherent_and_match_win(
    distribution: dict[str, float],
) -> None:
    with pytest.raises(EvaluationError, match="Settlement Distribution"):
        replace(_observation(), settlement_distribution=distribution)


def test_push_capable_preference_requires_frozen_settlement_distribution() -> None:
    with pytest.raises(EvaluationError, match="PUSH-capable"):
        replace(
            _observation(),
            preference_id="asian_handicap_home_0_0",
            preference_family="Asian Handicap",
            exact_line="Home 0.0",
        )


def test_binary_preference_rejects_push_settlement() -> None:
    with pytest.raises(EvaluationError, match="cannot settle PUSH"):
        replace(_observation(), settlement="PUSH")


def test_config_rejects_random_split() -> None:
    with pytest.raises(EvaluationError, match="chronological"):
        replace(_config(), split_method="RANDOM")


def test_periods_must_be_ordered_and_non_overlapping() -> None:
    config = replace(
        _config(),
        validation=ChronologicalPeriod(
            "VALIDATION",
            "2026-08-20T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
        ),
    )
    with pytest.raises(EvaluationError, match="overlap"):
        validate_evaluation_contract((_observation(),), (_candidate(),), config)


def test_explicit_gaps_are_allowed_without_reassigning_rows() -> None:
    config = replace(
        _config(),
        validation=ChronologicalPeriod(
            "VALIDATION",
            "2026-08-22T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
        ),
    )
    contract = validate_evaluation_contract((_observation(),), (_candidate(),), config)
    assert contract.excluded_match_ids == ()
    assert contract.period_for(_observation()) == "DEVELOPMENT"


def test_candidate_may_not_derive_parameters_from_validation_outcomes() -> None:
    candidate = _candidate(development_data_end_utc="2026-08-22T00:00:00+00:00")
    with pytest.raises(EvaluationError, match="Development Period"):
        validate_evaluation_contract((_observation(),), (candidate,), _config())


def test_candidate_must_be_frozen_before_evaluation_starts() -> None:
    candidate = _candidate(frozen_at_utc="2026-08-28T00:00:01+00:00")
    with pytest.raises(EvaluationError, match="before Final Evaluation"):
        validate_evaluation_contract((_observation(),), (candidate,), _config())


def test_candidate_cannot_freeze_before_validation_period_ends() -> None:
    candidate = _candidate(frozen_at_utc="2026-08-27T23:59:59+00:00")
    with pytest.raises(EvaluationError, match="before Validation ended"):
        validate_evaluation_contract((_observation(),), (candidate,), _config())


def test_development_outcome_must_be_known_by_candidate_data_cutoff() -> None:
    observation = replace(
        _observation(),
        outcome_known_at_utc="2026-08-21T00:00:01+00:00",
    )
    with pytest.raises(EvaluationError, match="Development outcome"):
        validate_evaluation_contract((observation,), (_candidate(),), _config())


def test_observation_policy_version_must_match_digest_identity() -> None:
    observation = replace(_observation(), policy_version="different-version")
    with pytest.raises(EvaluationError, match="version does not match"):
        validate_evaluation_contract((observation,), (_candidate(),), _config())


def test_validation_correction_known_after_policy_freeze_is_rejected() -> None:
    observation = _policy_observation(
        candidate=_candidate(),
        period="VALIDATION",
        settlement="WIN",
        estimated_probability=0.8,
    )
    corrected_later = replace(
        observation,
        outcome_known_at_utc="2026-08-28T00:00:01+00:00",
    )
    with pytest.raises(EvaluationError, match="Validation outcome"):
        validate_evaluation_contract((corrected_later,), (_candidate(),), _config())


@pytest.mark.parametrize("outcome_use", ["DEVELOPMENT", "VALIDATION", "INSPECTED"])
def test_non_unseen_evaluation_row_cannot_be_reused_as_unseen(outcome_use: str) -> None:
    observation = _observation(
        match_id="evaluation-match",
        matchweek_id="mw-4",
        matchweek_start_utc="2026-08-28T00:00:00+00:00",
        kickoff_at_utc="2026-08-29T14:00:00+00:00",
        research_cutoff_at_utc="2026-08-29T08:00:00+00:00",
        outcome_known_at_utc="2026-08-29T18:00:00+00:00",
        outcome_use=outcome_use,
    )
    with pytest.raises(EvaluationError, match="no longer unseen"):
        validate_evaluation_contract((observation,), (_candidate(),), _config())


def test_inspected_evaluation_period_stays_seen_if_corpus_digest_changes() -> None:
    observation = _observation(
        match_id="evaluation-match",
        matchweek_id="mw-evaluation",
        matchweek_start_utc="2026-08-28T00:00:00+00:00",
        kickoff_at_utc="2026-08-29T14:00:00+00:00",
        research_cutoff_at_utc="2026-08-29T08:00:00+00:00",
        outcome_known_at_utc="2026-08-29T18:00:00+00:00",
    )
    inspected_digest = validate_evaluation_contract(
        (observation,), (_candidate(),), _config()
    ).evaluation_window_digest
    changed_corpus = replace(observation, input_digest="f" * 64)
    candidate = _candidate(inspected_evaluation_digests=(inspected_digest,))

    with pytest.raises(EvaluationError, match="already inspected"):
        validate_evaluation_contract((changed_corpus,), (candidate,), _config())


@pytest.mark.parametrize(
    "parameters",
    [
        {"bookmaker_odds": 1.5},
        {"expected_profit": 2.0},
        {"stake_size": 10},
        {"target_selection_volume": 25},
    ],
)
def test_candidate_rejects_prohibited_policy_inputs(parameters: dict[str, object]) -> None:
    with pytest.raises(EvaluationError, match="prohibited"):
        _candidate(parameters=parameters)


def test_rolling_origin_folds_are_deterministic_and_matchweek_bound() -> None:
    observations = tuple(
        _observation(
            match_id=f"match-{index}",
            matchweek_id=f"mw-{index}",
            matchweek_start_utc=f"2026-08-{7 + 7 * (index - 1):02d}T00:00:00+00:00",
            kickoff_at_utc=f"2026-08-{8 + 7 * (index - 1):02d}T14:00:00+00:00",
            research_cutoff_at_utc=f"2026-08-{8 + 7 * (index - 1):02d}T08:00:00+00:00",
            outcome_known_at_utc=f"2026-08-{8 + 7 * (index - 1):02d}T18:00:00+00:00",
        )
        for index in range(1, 3)
    )
    first = generate_rolling_origin_folds(observations, _config())
    second = generate_rolling_origin_folds(tuple(reversed(observations)), _config())

    assert first == second
    assert len(first) == 1
    assert first[0].development_matchweek_ids == ("mw-1",)
    assert first[0].validation_matchweek_ids == ("mw-2",)
    assert first[0].evaluation_matchweek_ids == ()
    assert first[0].development_end_utc <= first[0].validation_start_utc


def test_same_matchweek_cannot_have_two_start_boundaries() -> None:
    observations = (
        _observation(),
        _observation(
            match_id="match-2",
            matchweek_start_utc="2026-08-08T00:00:00+00:00",
        ),
    )
    with pytest.raises(EvaluationError, match="Matchweek boundary"):
        generate_rolling_origin_folds(observations, _config())


def test_same_matchweek_cannot_have_two_research_cutoffs() -> None:
    observations = (
        _observation(),
        _observation(
            match_id="match-2",
            research_cutoff_at_utc="2026-08-08T09:00:00+00:00",
        ),
    )
    with pytest.raises(EvaluationError, match="Research Cutoff differs"):
        validate_evaluation_contract(observations, (_candidate(),), _config())


def test_probability_metrics_are_hand_computable_and_match_clustered() -> None:
    match_one_win = replace(
        _observation(),
        estimated_probability=0.8,
        conservative_probability=0.7,
        uncertainty_lower=0.6,
        uncertainty_upper=0.9,
    )
    match_one_loss = replace(
        match_one_win,
        preference_id="double_chance_12",
        preference_family="Double Chance",
        exact_line="12",
        estimated_probability=0.6,
        conservative_probability=0.5,
        uncertainty_lower=0.4,
        uncertainty_upper=0.8,
        settlement="LOSS",
    )
    match_two_loss = _replace_observation(
        match_one_win,
        match_id="match-2",
        matchweek_id="mw-2",
        preference_id="match_winner_away",
        exact_line="Away",
        estimated_probability=0.2,
        conservative_probability=0.1,
        uncertainty_lower=0.1,
        uncertainty_upper=0.3,
        settlement="LOSS",
    )
    push = _replace_observation(
        match_one_win,
        match_id="match-3",
        matchweek_id="mw-3",
        preference_id="asian_handicap_home_0_0",
        preference_family="Asian Handicap",
        exact_line="Home 0.0",
        estimated_probability=0.5,
        conservative_probability=0.4,
        uncertainty_lower=0.3,
        uncertainty_upper=0.7,
        settlement_distribution={"WIN": 0.5, "PUSH": 0.25, "LOSS": 0.25},
        settlement="PUSH",
    )
    void = _replace_observation(
        match_one_win,
        match_id="match-4",
        matchweek_id="mw-4",
        estimated_probability=0.9,
        conservative_probability=0.8,
        uncertainty_lower=0.7,
        uncertainty_upper=0.95,
        settlement="VOID",
    )

    report = evaluate_observations(
        (match_one_win, match_one_loss, match_two_loss, push, void),
        calibration_bin_edges=(0.0, 0.5, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.probability_quality["brier_score"] == pytest.approx(0.2258333333)
    assert report.probability_quality["log_loss"] == pytest.approx(0.726385018)
    assert report.probability_quality["preference_level_brier_score"] == pytest.approx(0.219375)
    assert report.probability_quality["preference_level_log_loss"] == pytest.approx(0.6872180489)
    assert report.probability_quality["mean_predicted_probability"] == pytest.approx(7 / 15)
    assert report.probability_quality["observed_success_rate"] == pytest.approx(1 / 6)
    assert report.probability_quality["calibration_gap"] == pytest.approx(0.3)
    assert report.effective_samples == {
        "binary_recommendation_match_clusters": 2,
        "binary_match_clusters": 2,
        "correlation_clusters": 4,
        "match_clusters": 4,
        "preference_rows": 5,
        "recommendation_match_clusters": 4,
        "scored_recommendation_match_clusters": 3,
        "scored_match_clusters": 3,
    }


def test_probability_metrics_score_push_distribution_and_exclude_void() -> None:
    push = replace(
        _observation(),
        preference_id="asian_handicap_home_0_0",
        preference_family="Asian Handicap",
        exact_line="Home 0.0",
        estimated_probability=0.5,
        conservative_probability=0.4,
        uncertainty_lower=0.3,
        uncertainty_upper=0.7,
        settlement_distribution={"WIN": 0.5, "PUSH": 0.25, "LOSS": 0.25},
        settlement="PUSH",
    )
    void = replace(
        _observation(match_id="match-2", matchweek_id="mw-2"),
        settlement="VOID",
    )

    report = evaluate_observations(
        (push, void),
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.probability_quality["brier_score"] == pytest.approx(0.4375)
    assert report.probability_quality["log_loss"] == pytest.approx(-math.log(0.25))
    assert report.probability_quality["scored_preference_rows"] == 1
    assert report.probability_quality["void_rows_excluded"] == 1
    assert report.probability_quality["observed_vs_predicted"] == {
        "LOSS": {"observed_rate": 0.0, "predicted_probability": 0.25},
        "PUSH": {"observed_rate": 1.0, "predicted_probability": 0.25},
        "WIN": {"observed_rate": 0.0, "predicted_probability": 0.5},
    }


def test_uncertainty_coverage_uses_reliability_bins_without_aggregate_cancellation() -> None:
    high_wrong = replace(
        _observation(),
        estimated_probability=0.9,
        conservative_probability=0.8,
        uncertainty_lower=0.85,
        uncertainty_upper=0.95,
        settlement="LOSS",
    )
    low_wrong = _replace_observation(
        _observation(),
        match_id="match-2",
        matchweek_id="mw-2",
        estimated_probability=0.1,
        conservative_probability=0.05,
        uncertainty_lower=0.05,
        uncertainty_upper=0.15,
        settlement="WIN",
    )

    report = evaluate_observations(
        (high_wrong, low_wrong),
        calibration_bin_edges=(0.0, 0.5, 1.0),
        subgroup_minimum_effective_samples={},
        uncertainty_nominal_coverage=0.8,
    )

    aggregate_alignment = cast(
        Mapping[str, object], report.probability_quality["aggregate_uncertainty_alignment"]
    )
    assert aggregate_alignment["covered"] is True
    assert report.probability_quality["uncertainty_interval_coverage"] == {
        "bins": (
            {
                "covered": False,
                "end": 0.5,
                "interval_lower": 0.05,
                "interval_upper": 0.15,
                "match_clusters": 1,
                "observed_success_rate": 1.0,
                "start": 0.0,
            },
            {
                "covered": False,
                "end": 1.0,
                "interval_lower": 0.85,
                "interval_upper": 0.95,
                "match_clusters": 1,
                "observed_success_rate": 0.0,
                "start": 0.5,
            },
        ),
        "coverage_rate": 0.0,
        "covered_bin_count": 0,
        "eligible_bin_count": 2,
        "nominal_coverage": 0.8,
        "status": "AVAILABLE",
    }


def test_calibration_and_probability_coverage_include_push_and_exclude_void() -> None:
    rows = (
        replace(
            _observation(),
            estimated_probability=0.8,
            conservative_probability=0.6,
            uncertainty_lower=0.4,
            uncertainty_upper=0.9,
        ),
        replace(
            _observation(match_id="match-2", matchweek_id="mw-2"),
            estimated_probability=0.2,
            conservative_probability=0.1,
            uncertainty_lower=0.1,
            uncertainty_upper=0.4,
            settlement="LOSS",
        ),
        replace(
            _observation(match_id="match-3", matchweek_id="mw-3"),
            preference_id="asian_handicap_home_0_0",
            preference_family="Asian Handicap",
            exact_line="Home 0.0",
            estimated_probability=0.4,
            conservative_probability=0.3,
            uncertainty_lower=0.2,
            uncertainty_upper=0.6,
            settlement_distribution={"WIN": 0.4, "PUSH": 0.2, "LOSS": 0.4},
            settlement="PUSH",
        ),
        replace(
            _observation(match_id="match-4", matchweek_id="mw-4"),
            settlement="VOID",
        ),
    )

    report = evaluate_observations(
        rows,
        calibration_bin_edges=(0.0, 0.5, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.calibration_bins == (
        {
            "end": 0.5,
            "match_clusters": 2,
            "mean_predicted_probability": pytest.approx(0.3),
            "observed_success_rate": 0.0,
            "preference_rows": 2,
            "start": 0.0,
        },
        {
            "end": 1.0,
            "match_clusters": 1,
            "mean_predicted_probability": 0.8,
            "observed_success_rate": 1.0,
            "preference_rows": 1,
            "start": 0.5,
        },
    )
    assert report.probability_quality["conservative_probability_coverage"] == {
        "covered": True,
        "margin": pytest.approx(0.0),
        "mean_conservative_probability": pytest.approx(1 / 3),
        "observed_success_rate": pytest.approx(1 / 3),
    }
    assert report.probability_quality["aggregate_uncertainty_alignment"] == {
        "covered": True,
        "interval_lower": pytest.approx(7 / 30),
        "interval_upper": pytest.approx(19 / 30),
        "observed_success_rate": pytest.approx(1 / 3),
    }
    interval_coverage = cast(
        Mapping[str, object], report.probability_quality["uncertainty_interval_coverage"]
    )
    assert interval_coverage["status"] == "INCONCLUSIVE"


def test_settlement_metrics_keep_push_and_void_neutral() -> None:
    rows = (
        _observation(),
        replace(_observation(match_id="match-2", matchweek_id="mw-2"), settlement="LOSS"),
        replace(
            _observation(match_id="match-3", matchweek_id="mw-3"),
            preference_id="asian_handicap_home_0_0",
            preference_family="Asian Handicap",
            exact_line="Home 0.0",
            settlement_distribution={"WIN": 0.7, "PUSH": 0.1, "LOSS": 0.2},
            settlement="PUSH",
        ),
        replace(_observation(match_id="match-4", matchweek_id="mw-4"), settlement="VOID"),
        replace(
            _observation(match_id="match-5", matchweek_id="mw-5"),
            recommendation="AVOID",
            settlement="LOSS",
        ),
    )

    report = evaluate_observations(
        rows,
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.settlement_metrics == {
        "avoid_match_count": 1,
        "avoid_rate": pytest.approx(0.2),
        "avoid_settlement_counts": {"LOSS": 1, "PUSH": 0, "VOID": 0, "WIN": 0},
        "avoid_settlements_credited_as_success": False,
        "false_positive_count": 1,
        "false_positive_rate": pytest.approx(0.5),
        "loss_count": 1,
        "negative_settlement_rate": pytest.approx(0.5),
        "push_count": 1,
        "recommendation_count": 4,
        "recommendation_match_count": 4,
        "recommendation_rate": pytest.approx(0.8),
        "void_count": 1,
        "win_count": 1,
    }


def test_sparse_subgroups_borrow_parent_metrics_and_stay_inconclusive() -> None:
    rows = (
        _observation(),
        replace(
            _observation(match_id="match-2", matchweek_id="mw-2"),
            preference_id="match_winner_away",
            exact_line="Away",
            settlement="LOSS",
        ),
    )

    report = evaluate_observations(
        rows,
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={
            "exact_line": 2,
            "league": 2,
            "preference_family": 3,
        },
    )
    subgroups = {(item["dimension"], item["value"]): item for item in report.subgroup_metrics}

    assert subgroups[("league", "Premier League")]["sample_status"] == "SUFFICIENT"
    family = subgroups[("preference_family", "Match Winner")]
    assert family["sample_status"] == "INCONCLUSIVE"
    assert family["borrowed_from"] == "aggregate"
    home = subgroups[("exact_line", "Match Winner | Home")]
    assert home["effective_sample"] == 1
    assert home["sample_status"] == "INCONCLUSIVE"
    assert home["borrowed_from"] == "preference_family:Match Winner"
    assert home["borrowed_probability_quality"] == family["probability_quality"]


def test_non_triviality_reports_baseline_lift_and_easy_line_gate_behavior() -> None:
    easy_selected = replace(
        _observation(),
        estimated_probability=0.92,
        conservative_probability=0.88,
        uncertainty_lower=0.85,
        uncertainty_upper=0.96,
        baseline_probability=0.9,
        baseline_structural_trivial=True,
        gates={"G4": "PASS"},
    )
    discriminating_loss = replace(
        _observation(match_id="match-2", matchweek_id="mw-2"),
        estimated_probability=0.7,
        conservative_probability=0.6,
        uncertainty_lower=0.55,
        uncertainty_upper=0.8,
        baseline_probability=0.4,
        baseline_structural_trivial=False,
        settlement="LOSS",
        gates={"G4": "PASS"},
    )
    easy_rejected = replace(
        _observation(match_id="match-3", matchweek_id="mw-3"),
        baseline_probability=0.85,
        baseline_structural_trivial=True,
        recommendation="REJECT",
        gates={"G4": "FAIL"},
    )

    report = evaluate_observations(
        (easy_selected, discriminating_loss, easy_rejected),
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.non_triviality == {
        "baseline_success_rate": pytest.approx(0.65),
        "base_rate_dominated_win_count": 1,
        "g4_rejected_structurally_trivial_count": 1,
        "observed_lift_over_baseline": pytest.approx(-0.15),
        "selected_structurally_trivial_count": 1,
        "selected_success_rate": pytest.approx(0.5),
        "selection_count_with_baseline": 2,
    }


def test_selection_strength_ranking_is_scored_only_among_gate_survivors() -> None:
    higher_winner = replace(
        _observation(),
        selection_strength=0.9,
        gates={"G0": "PASS", "G4": "PASS", "G8": "PASS"},
    )
    lower_loser = replace(
        higher_winner,
        preference_id="match_goals_over_2_5",
        preference_family="Match Goals Over",
        exact_line="2.5",
        selection_strength=0.7,
        settlement="LOSS",
    )
    rejected = replace(
        higher_winner,
        preference_id="match_goals_over_3_5",
        preference_family="Match Goals Over",
        exact_line="3.5",
        selection_strength=0.95,
        settlement="LOSS",
        recommendation="REJECT",
        gates={"G4": "FAIL"},
    )

    report = evaluate_observations(
        (higher_winner, lower_loser, rejected),
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.ranking_diagnostics == {
        "concordance_rate": 1.0,
        "concordant_pairs": 1,
        "discordant_pairs": 0,
        "eligible_match_count": 1,
        "pair_count": 1,
    }


def test_gate_and_stability_diagnostics_expose_leaks_and_chronological_drift() -> None:
    first_win = replace(
        _observation(),
        gates={"G0": "PASS", "G4": "PASS"},
        selection_components={"probability": 0.8, "uncertainty": 0.7},
        model_agreement=0.9,
        uncertainty_width=0.1,
    )
    first_leaked_loss = replace(
        first_win,
        preference_id="match_goals_over_2_5",
        preference_family="Match Goals Over",
        exact_line="2.5",
        settlement="LOSS",
        gates={"G0": "PASS", "G4": "FAIL"},
        selection_components={"probability": 0.5, "uncertainty": 0.3},
        model_agreement=0.4,
        uncertainty_width=0.4,
    )
    second_avoid = replace(
        _observation(match_id="match-2", matchweek_id="mw-2"),
        recommendation="AVOID",
        settlement="LOSS",
        gates={"G0": "PASS", "G4": "FAIL"},
        model_agreement=0.5,
        uncertainty_width=0.3,
    )

    report = evaluate_observations(
        (first_win, first_leaked_loss, second_avoid),
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={},
    )

    assert report.gate_diagnostics["mandatory_gate_rejections"] == {"G4": 2}
    assert report.gate_diagnostics["selected_failed_mandatory_gate_count"] == 1
    assert report.stability_diagnostics["recommendation_rate_by_matchweek"] == {
        "mw-1": 1.0,
        "mw-2": 0.0,
    }
    assert report.stability_diagnostics["recommendation_rate_range"] == 1.0
    assert report.stability_diagnostics["false_positive_rate_by_matchweek"] == {
        "mw-1": 0.5,
        "mw-2": None,
    }
    assert report.stability_diagnostics["mandatory_gate_rejection_rate_by_matchweek"] == {
        "mw-1": 0.5,
        "mw-2": 1.0,
    }
    assert report.stability_diagnostics["mandatory_gate_rejection_rate_range"] == 0.5
    assert report.stability_diagnostics["selection_component_ranges"] == {
        "probability": pytest.approx(0.3),
        "uncertainty": pytest.approx(0.4),
    }
    assert report.stability_diagnostics["model_agreement_by_settlement"] == {
        "LOSS": pytest.approx(0.4),
        "WIN": pytest.approx(0.9),
    }
    assert report.stability_diagnostics["uncertainty_error_correlation"] == pytest.approx(1.0)


def test_validation_selects_policy_before_evaluation_outcomes_are_scored() -> None:
    candidate_a = _candidate()
    candidate_b = _candidate(version="policy-b", digest="e" * 64)
    observations = (
        _policy_observation(
            candidate=candidate_a,
            period="DEVELOPMENT",
            settlement="WIN",
            estimated_probability=0.7,
        ),
        _policy_observation(
            candidate=candidate_b,
            period="DEVELOPMENT",
            settlement="WIN",
            estimated_probability=0.7,
        ),
        _policy_observation(
            candidate=candidate_a,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate_b,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.6,
        ),
        _policy_observation(
            candidate=candidate_a,
            period="EVALUATION",
            settlement="LOSS",
            estimated_probability=0.8,
        ),
    )
    config = replace(
        _config(),
        calibration_bin_edges=(0.0, 0.5, 1.0),
        selection_metric="probability_quality.brier_score",
        selection_direction="MINIMIZE",
        evaluation_minimum_recommendations=1,
        criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.7),),
    )

    first = evaluate_policies(observations, (candidate_a, candidate_b), config)
    changed_evaluation = tuple(
        replace(item, settlement="WIN") if item.matchweek_id == "mw-evaluation" else item
        for item in observations
    )
    second = evaluate_policies(changed_evaluation, (candidate_a, candidate_b), config)

    assert first.frozen_policy_identity == {
        "digest": candidate_a.digest,
        "status": "RESEARCH_ONLY",
        "version": candidate_a.version,
    }
    assert second.frozen_policy_identity == first.frozen_policy_identity
    assert first.validation_candidates[0]["policy_digest"] == candidate_a.digest
    first_quality = first.evaluation_metrics["probability_quality"]
    second_quality = second.evaluation_metrics["probability_quality"]
    assert isinstance(first_quality, Mapping)
    assert isinstance(second_quality, Mapping)
    assert first_quality["brier_score"] == pytest.approx(0.64)
    assert second_quality["brier_score"] == pytest.approx(0.04)


def test_final_evaluation_rejects_rows_for_non_frozen_candidate() -> None:
    candidate_a = _candidate()
    candidate_b = _candidate(version="policy-b", digest="e" * 64)
    observations = (
        _policy_observation(
            candidate=candidate_a,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate_b,
            period="VALIDATION",
            settlement="LOSS",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate_a,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate_b,
            period="EVALUATION",
            settlement="LOSS",
            estimated_probability=0.1,
        ),
    )
    config = replace(
        _config(),
        selection_metric="probability_quality.brier_score",
        selection_direction="MINIMIZE",
    )

    with pytest.raises(EvaluationError, match="non-frozen Candidate Policy"):
        evaluate_policies(observations, (candidate_a, candidate_b), config)


def test_declared_criteria_control_pass_fail_and_insufficient_evidence() -> None:
    candidate = _candidate()
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="LOSS",
            estimated_probability=0.8,
        ),
    )
    base = replace(
        _config(),
        evaluation_minimum_recommendations=1,
        criteria=(
            EvaluationCriterion("probability_quality.brier_score", "<=", 0.7),
            EvaluationCriterion("settlement_metrics.false_positive_rate", "<=", 1.0),
        ),
    )

    passing = evaluate_policies(observations, (candidate,), base)
    failing = evaluate_policies(
        observations,
        (candidate,),
        replace(
            base,
            criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.5),),
        ),
    )
    insufficient = evaluate_policies(
        observations,
        (candidate,),
        replace(base, evaluation_minimum_recommendations=2),
    )
    undeclared = evaluate_policies(
        observations,
        (candidate,),
        replace(base, evaluation_minimum_recommendations=None, criteria=()),
    )

    assert passing.status == "PASS"
    assert {item["status"] for item in passing.findings} == {"PASS"}
    assert failing.status == "FAIL"
    assert failing.findings[0]["status"] == "FAIL"
    assert insufficient.status == "INCONCLUSIVE"
    assert insufficient.findings[0]["status"] == "INCONCLUSIVE"
    assert undeclared.status == "INCONCLUSIVE"
    assert undeclared.findings == (
        {
            "criterion": "evaluation_evidence",
            "reason": "NO_PREDECLARED_ACCEPTANCE_CRITERIA_OR_MINIMUM_SAMPLE",
            "status": "INCONCLUSIVE",
        },
    )


def test_void_recommendations_do_not_satisfy_effective_sample_minimum() -> None:
    candidate = _candidate()
    evaluation_win = _policy_observation(
        candidate=candidate,
        period="EVALUATION",
        settlement="WIN",
        estimated_probability=0.8,
    )
    evaluation_void = _replace_observation(
        evaluation_win,
        match_id="evaluation-void",
        settlement="VOID",
    )
    evaluation_win, evaluation_void = _share_membership((evaluation_win, evaluation_void))
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        evaluation_win,
        evaluation_void,
    )
    config = replace(
        _config(),
        evaluation_minimum_recommendations=2,
        criteria=(
            EvaluationCriterion(
                "probability_quality.brier_score",
                "<=",
                0.1,
                minimum_effective_sample=2,
            ),
        ),
    )

    artifact = evaluate_policies(observations, (candidate,), config)

    assert artifact.status == "INCONCLUSIVE"
    assert artifact.findings[0]["effective_sample"] == 1
    assert artifact.findings[1]["effective_sample"] == 1


def test_void_only_matches_do_not_make_subgroup_sufficient() -> None:
    win = _observation()
    void = _replace_observation(win, match_id="void-match", settlement="VOID")
    win, void = _share_membership((win, void))

    report = evaluate_observations(
        (win, void),
        calibration_bin_edges=(0.0, 1.0),
        subgroup_minimum_effective_samples={"league": 2},
    )
    league = next(
        item
        for item in report.subgroup_metrics
        if item["dimension"] == "league" and item["value"] == "Premier League"
    )

    assert league["effective_sample"] == 1
    assert league["sample_status"] == "INCONCLUSIVE"


def test_evaluation_artifact_is_deterministic_immutable_and_research_only() -> None:
    candidate = _candidate()
    original_parameters = dict(candidate.parameters)
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )
    config = replace(
        _config(),
        evaluation_minimum_recommendations=1,
        criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.1),),
    )

    first = evaluate_policies(observations, (candidate,), config)
    second = evaluate_policies(tuple(reversed(observations)), (candidate,), config)
    reparsed = EvaluationArtifact.from_bytes(first.to_bytes())

    assert first.digest == second.digest == reparsed.digest
    assert first.to_bytes() == second.to_bytes() == reparsed.to_bytes()
    assert first.lifecycle_effect == "EVALUATED_RESEARCH_ONLY"
    assert first.cutoff_fidelity["checked_input_count"] == 4
    assert first.cutoff_fidelity["status"] == "PASS"
    assert len(cast(tuple[object, ...], first.cutoff_fidelity["fixture_revision_digests"])) == 2
    assert len(cast(tuple[object, ...], first.cutoff_fidelity["membership_manifest_digests"])) == 2
    assert candidate.parameters == original_parameters
    assert first.reproducibility["seed"] == 17
    assert first.reproducibility["corpus_digest"]
    assert first.reproducibility["config_digest"]
    assert tuple(
        (item["match_id"], item["preference_id"], item["settlement"])
        for item in first.observation_audit
    ) == (
        ("validation-match", "match_winner_home", "WIN"),
        ("evaluation-match", "match_winner_home", "WIN"),
    )
    assert first.folds[-1]["evaluation_range"] == {
        "end_utc": "2026-09-11T00:00:00+00:00",
        "start_utc": "2026-08-28T00:00:00+00:00",
    }

    tampered = json.loads(first.to_bytes())
    tampered["status"] = "FAIL"
    with pytest.raises(EvaluationError, match="digest"):
        EvaluationArtifact.from_bytes(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
        )


def test_interrupted_evaluation_resumes_only_with_identical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _candidate()
    first_development = _policy_observation(
        candidate=candidate,
        period="DEVELOPMENT",
        settlement="WIN",
        estimated_probability=0.7,
    )
    second_development = _replace_observation(
        first_development,
        match_id="development-match-2",
        matchweek_id="mw-development-2",
        matchweek_start_utc="2026-08-14T00:00:00+00:00",
        kickoff_at_utc="2026-08-15T14:00:00+00:00",
        research_cutoff_at_utc="2026-08-15T08:00:00+00:00",
        prediction_created_at_utc="2026-08-15T08:00:00+00:00",
        training_data_end_utc="2026-08-14T00:00:00+00:00",
        model_fitted_at_utc="2026-08-14T00:00:00+00:00",
        outcome_known_at_utc="2026-08-15T18:00:00+00:00",
    )
    observations = (
        first_development,
        second_development,
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )
    config = replace(
        _config(),
        evaluation_minimum_recommendations=1,
        criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.1),),
    )
    checkpoint_path = tmp_path / "evaluation-checkpoint.json"

    def interrupt_after_first_fold(completed_folds: int) -> None:
        if completed_folds == 1:
            raise KeyboardInterrupt

    interrupted_runner = EvaluationRunner(
        checkpoint_path,
        checkpoint_observer=interrupt_after_first_fold,
    )
    with pytest.raises(KeyboardInterrupt):
        interrupted_runner.run(observations, (candidate,), config)

    checkpoint = read_evaluation_checkpoint(checkpoint_path)
    assert checkpoint.state == "IN_PROGRESS"
    assert len(checkpoint.completed_fold_ids) == 1
    assert checkpoint.artifact_digest is None
    assert not (tmp_path / "evaluation-checkpoint.json.partial").exists()

    original_nested_evaluator = t18_module._nested_candidate_results

    def completed_fold_must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("completed nested fold was recomputed")

    monkeypatch.setattr(t18_module, "_nested_candidate_results", completed_fold_must_not_run)

    resumed = EvaluationRunner(checkpoint_path).run(
        observations,
        (candidate,),
        config,
        resume=True,
    )
    monkeypatch.setattr(t18_module, "_nested_candidate_results", original_nested_evaluator)
    fresh = evaluate_policies(observations, (candidate,), config)
    completed = read_evaluation_checkpoint(checkpoint_path)

    assert resumed.digest == fresh.digest
    assert completed.state == "COMPLETE"
    assert completed.artifact_digest == resumed.digest
    assert completed.completed_fold_ids[-1].startswith("final-")
    nested = fresh.folds[0]
    candidate_validation_results = cast(
        tuple[Mapping[str, object], ...], nested["candidate_validation_results"]
    )
    assert candidate_validation_results == (
        {
            "metrics": candidate_validation_results[0]["metrics"],
            "policy_digest": candidate.digest,
            "policy_version": candidate.version,
            "selection_metric": "probability_quality.brier_score",
            "selection_metric_value": pytest.approx(0.09),
        },
    )
    assert nested["model_digests"] == ("b" * 64,)
    assert nested["evidence_digests"] == ("c" * 64,)
    assert nested["policy_versions"] == (candidate.version,)
    development_counts = cast(Mapping[str, object], nested["development_counts"])
    assert development_counts["effective_samples"] == {
        "binary_recommendation_match_clusters": 1,
        "binary_match_clusters": 1,
        "correlation_clusters": 1,
        "match_clusters": 1,
        "preference_rows": 1,
        "recommendation_match_clusters": 1,
        "scored_recommendation_match_clusters": 1,
        "scored_match_clusters": 1,
    }

    tampered = tuple(
        replace(item, input_digest="f" * 64) if item.match_id == "development-match-2" else item
        for item in observations
    )
    with pytest.raises(EvaluationError, match="checkpoint input digest"):
        EvaluationRunner(checkpoint_path).run(
            tampered,
            (candidate,),
            config,
            resume=True,
        )


def test_nested_fold_rejects_outcome_unavailable_at_fold_training_boundary() -> None:
    candidate = _candidate()
    first_development = replace(
        _policy_observation(
            candidate=candidate,
            period="DEVELOPMENT",
            settlement="WIN",
            estimated_probability=0.7,
        ),
        outcome_known_at_utc="2026-08-20T18:00:00+00:00",
    )
    second_development = _replace_observation(
        first_development,
        match_id="development-match-2",
        matchweek_id="mw-development-2",
        matchweek_start_utc="2026-08-14T00:00:00+00:00",
        kickoff_at_utc="2026-08-15T14:00:00+00:00",
        research_cutoff_at_utc="2026-08-15T08:00:00+00:00",
        prediction_created_at_utc="2026-08-15T08:00:00+00:00",
        training_data_end_utc="2026-08-14T00:00:00+00:00",
        model_fitted_at_utc="2026-08-14T00:00:00+00:00",
        outcome_known_at_utc="2026-08-15T18:00:00+00:00",
    )
    observations = (
        replace(first_development, outcome_known_at_utc="2026-08-20T18:00:00+00:00"),
        second_development,
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )

    with pytest.raises(EvaluationError, match="Nested fold training"):
        evaluate_policies(observations, (candidate,), _config())


def test_checkpoint_digest_tamper_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "evaluation-checkpoint.json"
    path.write_text(
        json.dumps(
            {
                "artifact_digest": None,
                "checkpoint_digest": "0" * 64,
                "completed_fold_ids": [],
                "fold_records": [],
                "run_digest": "1" * 64,
                "schema_version": "matchvet.policy-evaluation-checkpoint.v1",
                "state": "IN_PROGRESS",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationError, match="checkpoint digest"):
        read_evaluation_checkpoint(path)


def test_final_only_evaluation_checkpoints_before_metrics(tmp_path: Path) -> None:
    candidate = _candidate()
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )
    checkpoint_path = tmp_path / "final-only-checkpoint.json"

    def interrupt_before_metrics(completed_folds: int) -> None:
        if completed_folds == 0:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        EvaluationRunner(
            checkpoint_path,
            checkpoint_observer=interrupt_before_metrics,
        ).run(observations, (candidate,), _config())

    checkpoint = read_evaluation_checkpoint(checkpoint_path)
    assert checkpoint.state == "IN_PROGRESS"
    assert checkpoint.completed_fold_ids == ()
    assert checkpoint.fold_records == ()


def test_checkpoint_writer_does_not_reuse_unrelated_partial(tmp_path: Path) -> None:
    candidate = _candidate()
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    unrelated_partial = tmp_path / "checkpoint.json.partial"
    unrelated_partial.write_bytes(b"unrelated")

    EvaluationRunner(checkpoint_path).run(observations, (candidate,), _config())

    assert unrelated_partial.read_bytes() == b"unrelated"
    assert not tuple(tmp_path.glob(".checkpoint.json.*.partial"))


def test_artifact_records_exclusion_reasons_for_rows_between_periods() -> None:
    candidate = _candidate()
    validation = _replace_observation(
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        matchweek_start_utc="2026-08-22T00:00:00+00:00",
        kickoff_at_utc="2026-08-23T14:00:00+00:00",
        research_cutoff_at_utc="2026-08-23T08:00:00+00:00",
        prediction_created_at_utc="2026-08-23T08:00:00+00:00",
        outcome_known_at_utc="2026-08-23T18:00:00+00:00",
    )
    gap_row = _replace_observation(
        validation,
        match_id="gap-match",
        matchweek_id="mw-gap",
        matchweek_start_utc="2026-08-21T00:00:00+00:00",
    )
    evaluation = _policy_observation(
        candidate=candidate,
        period="EVALUATION",
        settlement="WIN",
        estimated_probability=0.8,
    )
    config = replace(
        _config(),
        validation=ChronologicalPeriod(
            "VALIDATION",
            "2026-08-22T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
        ),
        evaluation_minimum_recommendations=1,
        criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.1),),
    )

    artifact = evaluate_policies((gap_row, validation, evaluation), (candidate,), config)

    assert artifact.folds[-1]["exclusions"] == (
        {
            "match_id": "gap-match",
            "matchweek_id": "mw-gap",
            "reason": "OUTSIDE_DECLARED_PERIODS",
        },
    )


def test_policy_stability_reports_fold_threshold_and_weight_ranges() -> None:
    candidate = replace(
        _candidate(),
        fold_parameters={
            "fold-1": {
                "selection_strength": {"weights": {"probability": 0.6}},
                "thresholds": {"conservative_probability_min": 0.58},
            },
            "fold-2": {
                "selection_strength": {"weights": {"probability": 0.5}},
                "thresholds": {"conservative_probability_min": 0.62},
            },
        },
    )
    observations = (
        _policy_observation(
            candidate=candidate,
            period="VALIDATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
        _policy_observation(
            candidate=candidate,
            period="EVALUATION",
            settlement="WIN",
            estimated_probability=0.8,
        ),
    )
    artifact = evaluate_policies(
        observations,
        (candidate,),
        replace(
            _config(),
            evaluation_minimum_recommendations=1,
            criteria=(EvaluationCriterion("probability_quality.brier_score", "<=", 0.1),),
        ),
    )

    assert artifact.policy_stability["fold_parameter_status"] == "AVAILABLE"
    assert artifact.policy_stability["threshold_ranges"] == {
        "thresholds.conservative_probability_min": pytest.approx(0.04)
    }
    assert artifact.policy_stability["selection_strength_weight_ranges"] == {
        "selection_strength.weights.probability": pytest.approx(0.1)
    }

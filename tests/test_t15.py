from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
from typing import cast

import pytest

from matchvet.t09 import CriticalEvidenceCoverage, ResearchStatus, ResearchSufficiency, TargetMatch
from matchvet.t10 import (
    DEFAULT_PREFERENCE_CATALOG,
    PreferenceCatalog,
    PreferenceFamily,
)
from matchvet.t15 import (
    MatchVettingResult,
    NormalizationSpec,
    PolicyVersion,
    PreferenceVettingResult,
    SelectionStrengthConfig,
)


def _family_key(preference_family: PreferenceFamily) -> str:
    if preference_family is PreferenceFamily.FIRST_HALF_OVER:
        return "FIRST_HALF_GOALS"
    if preference_family is PreferenceFamily.SECOND_HALF_OVER:
        return "SECOND_HALF_GOALS"
    if preference_family in {
        PreferenceFamily.CORNER_WINNER,
        PreferenceFamily.TOTAL_CORNERS_OVER,
        PreferenceFamily.HOME_CORNERS_OVER,
        PreferenceFamily.AWAY_CORNERS_OVER,
    }:
        return "CORNERS"
    return "FULL_TIME_GOALS"


def _evidence_family_key(preference_family: PreferenceFamily) -> str:
    if preference_family is PreferenceFamily.ASIAN_HANDICAP:
        return "Asian Handicaps"
    return preference_family.value


def _target() -> TargetMatch:
    return TargetMatch(
        matchweek_id="mw-t15",
        cutoff_id="cutoff-t15",
        fixture_id="fixture-t15",
        cutoff_utc="2026-10-01T12:00:00+00:00",
        kickoff_utc="2026-10-01T20:00:00+00:00",
        home_team_id="team-home",
        away_team_id="team-away",
        competition_key="premier_league",
        competition_name="Premier League",
        season="2026-27",
    )


def _evidence_state() -> SimpleNamespace:
    coverage = {}
    sufficiency = {}
    for preference in DEFAULT_PREFERENCE_CATALOG:
        family = _evidence_family_key(preference.family)
        coverage[family] = CriticalEvidenceCoverage(
            family=family,
            required_requirement_ids=("critical",),
            covered_requirement_ids=("critical",),
            missing_requirement_ids=(),
            coverage_ratio=1.0,
            complete=True,
        )
        sufficiency[family] = ResearchSufficiency(
            family=family,
            status=ResearchStatus.SUFFICIENT,
            mandatory_research_complete=True,
            critical_evidence_complete=True,
            optional_research_complete=True,
            diminishing_returns_reached=True,
            model_unavailable=False,
            unresolved_material_conflicts=0,
        )
    return SimpleNamespace(
        target=_target(),
        research_sufficiency=sufficiency,
        critical_evidence_coverage=coverage,
        conflicts=(),
        gaps=(),
        state_digest="evidence-digest",
    )


def _predictions() -> dict[str, dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for preference in DEFAULT_PREFERENCE_CATALOG:
        grouped.setdefault(_family_key(preference.family), []).append(preference.preference_id)
    predictions: dict[str, dict[str, object]] = {}
    for family, preference_ids in grouped.items():
        settlements: dict[str, dict[str, float]] = {}
        estimated: dict[str, float] = {}
        conservative: dict[str, float] = {}
        loss_upper: dict[str, float] = {}
        intervals: dict[str, dict[str, dict[str, float]]] = {}
        for preference_id in preference_ids:
            preference = DEFAULT_PREFERENCE_CATALOG.get(preference_id)
            push = (
                0.1 if "PUSH" in {str(item.value) for item in preference.possible_results} else 0.0
            )
            loss = 0.2 if push else 0.28
            win = 1.0 - push - loss
            settlements[preference_id] = {"WIN": win, "LOSS": loss, "PUSH": push}
            estimated[preference_id] = win
            conservative[preference_id] = win - 0.05
            loss_upper[preference_id] = loss + 0.02
            intervals[preference_id] = {
                "WIN": {
                    "estimated": win,
                    "lower": win - 0.05,
                    "upper": win - 0.01,
                    "standard_deviation": 0.01,
                }
            }
        predictions[family] = {
            "status": "AVAILABLE",
            "family": family,
            "target_fixture_id": "fixture-t15",
            "matchweek_id": "mw-t15",
            "model_version": "model-t15-v1",
            "model_digest": f"model-digest-{family.lower()}",
            "calibration_version": "calibration-t15-v1",
            "prediction_digest": f"prediction-digest-{family.lower()}",
            "settlement_distributions": settlements,
            "estimated_probabilities": estimated,
            "conservative_probabilities": conservative,
            "loss_probability_upper": loss_upper,
            "probability_intervals": intervals,
            "uncertainty": {
                "tail_risk": 0.05,
                "empirical_coverage_validated": True,
            },
            "model_agreement": 0.9,
            "reference_sensitivity": {
                "sensitivity_by_preference": {
                    preference_id: 0.1 for preference_id in preference_ids
                }
            },
        }
    return predictions


def _candidate_inputs() -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for preference in DEFAULT_PREFERENCE_CATALOG:
        push = "PUSH" in {str(item.value) for item in preference.possible_results}
        values[preference.preference_id] = {
            "data_quality": {"overall": 0.9, "dimensions": {"freshness": 0.9}},
            "baseline": {
                "win": 0.5,
                "loss": 0.4 if push else 0.5,
                "push": 0.1 if push else 0.0,
                "hierarchical_key": f"{preference.family.value}:{preference.preference_id}",
                "contract": preference.to_dict(),
                "structural_trivial": False,
                "match_specific_lift": 0.2,
            },
            "historical_reliability": {
                "overall": 0.9,
                "dimensions": {"calibration": 0.9, "uncertainty": 0.9},
                "effective_sample": 100,
            },
            "adversarial_review": {
                "failure_case": "The strongest plausible failure is a late tactical change.",
                "evidence_ids": (f"failure-{preference.preference_id}",),
                "materiality": 0.2,
                "represented_in_uncertainty": True,
            },
            "supporting_case": "The frozen evidence and calibrated distribution support the line.",
            "uncertainty_reliable": True,
        }
    return values


def _selection_config() -> SelectionStrengthConfig:
    identity = {
        component: "identity"
        for component in (
            "conservative_probability",
            "win_lift",
            "loss_risk_improvement",
            "data_quality",
            "model_agreement",
            "adversarial_safety",
            "historical_reliability",
        )
    }
    normalizers: dict[str, NormalizationSpec | str] = {
        **identity,
        "uncertainty_quality": NormalizationSpec(method="inverse_min_max", lower=0.0, upper=0.5),
    }
    return SelectionStrengthConfig(
        version="strength-t15-test-v1",
        weights={
            component: 0.125
            for component in (
                "conservative_probability",
                "win_lift",
                "loss_risk_improvement",
                "data_quality",
                "uncertainty_quality",
                "model_agreement",
                "adversarial_safety",
                "historical_reliability",
            )
        },
        transforms={component: "identity" for component in normalizers},
        normalizers=normalizers,
    )


def _policy(
    *, production: bool = False, thresholds: Mapping[str, object] | None = None
) -> PolicyVersion:
    from matchvet.t15 import PolicyStatus

    selected = {
        "data_quality_min": 0.7,
        "data_quality_dimension_min": {"freshness": 0.7},
        "historical_reliability_min": 0.7,
        "non_triviality_baseline_win_max": 0.9,
        "non_triviality_min_lift": 0.05,
        "conservative_probability_min": 0.6,
        "loss_risk_max": 0.35,
        "uncertainty_width_max": 0.2,
        "uncertainty_tail_risk_max": 0.1,
        "model_agreement_min": 0.7,
        "model_sensitivity_max": 0.3,
        "statistical_tie_tolerance": 0.001,
    }
    selected.update(thresholds or {})
    return PolicyVersion(
        version="policy-t15-production-v1" if production else "policy-t15-research-v1",
        status=PolicyStatus.PRODUCTION_PROMOTED if production else PolicyStatus.RESEARCH_ONLY,
        thresholds=selected,
        selection_strength=_selection_config(),
        correlation_groups={
            "match_goals_over_1_5": "match-goals",
            "match_goals_over_2_5": "match-goals",
            "match_goals_over_3_5": "match-goals",
        },
        promotion_evidence={"explicitly_promoted": production},
    )


def _row(result: MatchVettingResult, preference_id: str) -> PreferenceVettingResult:
    return next(
        item for item in result.preference_results if item.preference.preference_id == preference_id
    )


def _candidate_inputs_with(preference_id: str, **updates: object) -> dict[str, dict[str, object]]:
    values = _candidate_inputs()
    values[preference_id] = {**values[preference_id], **updates}
    return values


def _candidate_inputs_nested(
    preference_id: str, field: str, **updates: object
) -> dict[str, dict[str, object]]:
    values = _candidate_inputs()
    original = values[preference_id][field]
    assert isinstance(original, dict)
    values[preference_id] = {
        **values[preference_id],
        field: {**original, **updates},
    }
    return values


def _predictions_with(preference_id: str, **updates: object) -> dict[str, dict[str, object]]:
    values = _predictions()
    family = _family_key(DEFAULT_PREFERENCE_CATALOG.get(preference_id).family)
    values[family] = {**values[family], **updates}
    return values


def _state_with(**updates: object) -> SimpleNamespace:
    state = _evidence_state()
    return SimpleNamespace(**{**state.__dict__, **updates})


def _component_values(value: float) -> dict[str, float]:
    values = {
        component: value
        for component in (
            "conservative_probability",
            "win_lift",
            "loss_risk_improvement",
            "data_quality",
            "uncertainty_quality",
            "model_agreement",
            "adversarial_safety",
            "historical_reliability",
        )
    }
    values["uncertainty_quality"] = min(value, 0.2)
    return values


def test_t15_public_seam_evaluates_every_enabled_preference() -> None:
    from matchvet.t15 import PolicyVersion, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        predictions={},
        policy=PolicyVersion(version="t15-test-v1"),
    )

    assert len(result.preference_results) == 37
    assert {item.preference.preference_id for item in result.preference_results} == {
        item.preference_id for item in DEFAULT_PREFERENCE_CATALOG
    }


def test_research_only_retains_diagnostic_primary_without_production_labels() -> None:
    from matchvet.t15 import CandidateRole, CandidateStatus, MatchDecision, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )

    assert result.decision is MatchDecision.RESEARCH_ONLY
    assert result.primary_recommendation is None
    assert result.research_primary_candidate is not None
    assert result.research_primary_candidate.role is CandidateRole.RESEARCH_PRIMARY_CANDIDATE
    assert result.research_primary_candidate.status is CandidateStatus.RESEARCH_CANDIDATE
    assert result.secondary_fits == ()
    assert result.research_primary_candidate.selection_strength is not None
    assert "PLAY" not in str(result.to_dict())


def test_research_only_without_strength_config_keeps_candidates_but_no_ranked_primary() -> None:
    from matchvet.t15 import CandidateStatus, MatchDecision, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        replace(_policy(), selection_strength=None),
        candidate_inputs=_candidate_inputs(),
    )

    assert result.decision is MatchDecision.RESEARCH_ONLY
    assert result.avoid_reason == "RESEARCH_SELECTION_STRENGTH_UNAVAILABLE"
    assert result.research_primary_candidate is None
    assert all(
        item.status is CandidateStatus.RESEARCH_CANDIDATE for item in result.preference_results
    )
    assert all(item.selection_strength is None for item in result.preference_results)


def test_each_preference_has_explicit_g0_to_g8_audit_rows() -> None:
    from matchvet.t15 import GateId, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )

    assert result.audit_complete
    for item in result.preference_results:
        assert tuple(gate.gate_id for gate in item.gates) == tuple(GateId)
        assert len(item.rejection_reasons) == 0
        assert set(item.selection_components) == {
            "conservative_probability",
            "win_lift",
            "loss_risk_improvement",
            "data_quality",
            "uncertainty_quality",
            "model_agreement",
            "adversarial_safety",
            "historical_reliability",
        }


def test_missing_model_distribution_fails_g0_and_cannot_receive_strength() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        {},
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")

    g0 = next(gate for gate in row.gates if gate.gate_id is GateId.G0)
    assert g0.status is GateStatus.FAIL
    assert "MODEL_UNAVAILABLE" in g0.reason_codes
    assert row.selection_strength is None


def test_evidence_state_digest_mismatch_fails_g0() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    state = _state_with(state_digest="wrong-evidence-digest", digest="actual-evidence-digest")
    result = vet_target_match(
        state,
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G0)

    assert gate.status is GateStatus.FAIL
    assert "EVIDENCE_STATE_DIGEST_MISMATCH" in gate.reason_codes
    assert row.selection_strength is None


def test_prediction_digest_mismatch_fails_g0() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    predictions = _predictions()
    predictions["FULL_TIME_GOALS"] = {
        **predictions["FULL_TIME_GOALS"],
        "digest": "different-prediction-digest",
    }
    result = vet_target_match(
        _evidence_state(),
        predictions,
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G0)

    assert gate.status is GateStatus.FAIL
    assert "PREDICTION_DIGEST_MISMATCH" in gate.reason_codes
    assert row.selection_strength is None


def test_research_sufficiency_gate_is_non_compensable() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    sufficiency = dict(_evidence_state().research_sufficiency)
    sufficiency["Match Winner"] = ResearchSufficiency(
        family="Match Winner",
        status=ResearchStatus.INSUFFICIENT,
        mandatory_research_complete=False,
        critical_evidence_complete=False,
        optional_research_complete=False,
        diminishing_returns_reached=False,
        model_unavailable=False,
        unresolved_material_conflicts=0,
    )
    state = _state_with(research_sufficiency=sufficiency)
    inputs = _candidate_inputs_with(
        "match_winner_home",
        selection_components={
            component: 1.0
            for component in (
                "conservative_probability",
                "win_lift",
                "loss_risk_improvement",
                "data_quality",
                "uncertainty_quality",
                "model_agreement",
                "adversarial_safety",
                "historical_reliability",
            )
        },
    )
    result = vet_target_match(state, _predictions(), _policy(), candidate_inputs=inputs)
    row = _row(result, "match_winner_home")
    gate = next(gate for gate in row.gates if gate.gate_id is GateId.G1)

    assert gate.status is GateStatus.FAIL
    assert row.selection_strength is None
    assert "RESEARCH_SUFFICIENCY_INSUFFICIENT" in row.rejection_reasons


def test_missing_critical_evidence_fails_g2() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    coverage = dict(_evidence_state().critical_evidence_coverage)
    coverage["Match Winner"] = replace(
        coverage["Match Winner"],
        covered_requirement_ids=(),
        missing_requirement_ids=("critical",),
        coverage_ratio=0.0,
        complete=False,
    )
    result = vet_target_match(
        _state_with(critical_evidence_coverage=coverage),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(gate for gate in row.gates if gate.gate_id is GateId.G2)

    assert gate.status is GateStatus.FAIL
    assert "CRITICAL_EVIDENCE_MISSING" in gate.reason_codes
    assert row.selection_strength is None


@pytest.mark.parametrize(
    ("gate_id", "inputs"),
    (
        (
            "G3",
            _candidate_inputs_nested(
                "match_winner_home",
                "historical_reliability",
                overall=0.2,
            ),
        ),
        (
            "G4",
            _candidate_inputs_nested(
                "match_winner_home",
                "baseline",
                structural_trivial=True,
            ),
        ),
        (
            "G8",
            _candidate_inputs_nested(
                "match_winner_home",
                "adversarial_review",
                veto=True,
            ),
        ),
    ),
)
def test_failed_hard_gates_never_receive_selection_strength(
    gate_id: str, inputs: dict[str, dict[str, object]]
) -> None:
    from matchvet.t15 import GateStatus, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=inputs,
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id.value == gate_id)

    assert gate.status is GateStatus.FAIL
    assert row.selection_strength is None
    assert row.status.value == "REJECT"
    assert row.rejection_reasons


def test_non_triviality_requires_exact_t10_baseline_contract() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    inputs = _candidate_inputs_nested("match_winner_home", "baseline", contract={})
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=inputs,
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G4)

    assert gate.status is GateStatus.FAIL
    assert "HISTORICAL_BASELINE_CONTRACT_MISSING" in gate.reason_codes
    assert row.selection_strength is None


def test_conservative_probability_and_loss_risk_gate() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions_with(
            "match_winner_home",
            conservative_probabilities={"match_winner_home": 0.5},
            loss_probability_upper={"match_winner_home": 0.8},
        ),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G5)

    assert gate.status is GateStatus.FAIL
    assert "CONSERVATIVE_PROBABILITY_BELOW_THRESHOLD" in gate.reason_codes
    assert "LOSS_RISK_ABOVE_THRESHOLD" in gate.reason_codes
    assert row.selection_strength is None


def test_missing_calibrated_loss_risk_cannot_fallback_to_settlement_point_mass() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    predictions = _predictions()
    predictions["FULL_TIME_GOALS"] = {
        **predictions["FULL_TIME_GOALS"],
        "loss_probability_upper": {
            key: value
            for key, value in cast(
                Mapping[str, float],
                predictions["FULL_TIME_GOALS"]["loss_probability_upper"],
            ).items()
            if key != "match_winner_home"
        },
    }
    result = vet_target_match(
        _evidence_state(),
        predictions,
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G5)

    assert gate.status is GateStatus.FAIL
    assert "LOSS_RISK_MISSING" in gate.reason_codes
    assert row.selection_strength is None


def test_uncertainty_gate_and_model_sensitivity_gate() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    inputs = _candidate_inputs_with(
        "match_winner_home",
        uncertainty_width=0.4,
        model_agreement=0.5,
        model_sensitivity=0.4,
    )
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=inputs,
    )
    row = _row(result, "match_winner_home")
    g6 = next(item for item in row.gates if item.gate_id is GateId.G6)
    g7 = next(item for item in row.gates if item.gate_id is GateId.G7)

    assert g6.status is GateStatus.FAIL
    assert "PROBABILITY_UNCERTAINTY_ABOVE_THRESHOLD" in g6.reason_codes
    assert g7.status is GateStatus.FAIL
    assert "MODEL_AGREEMENT_BELOW_THRESHOLD" in g7.reason_codes
    assert "MODEL_SENSITIVITY_ABOVE_THRESHOLD" in g7.reason_codes
    assert row.selection_strength is None


def test_t14_uncertainty_without_validated_tail_metadata_is_rejected_safely() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    predictions = _predictions()
    predictions["FULL_TIME_GOALS"] = {
        **predictions["FULL_TIME_GOALS"],
        "uncertainty": {
            "total_multiplier": 1.1,
            "effective_sample_size": 20.0,
        },
    }
    result = vet_target_match(
        _evidence_state(),
        predictions,
        _policy(),
        candidate_inputs=_candidate_inputs_with("match_winner_home", uncertainty_reliable=None),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G6)

    assert gate.status is GateStatus.FAIL
    assert "UNCERTAINTY_TAIL_RISK_MISSING" in gate.reason_codes
    assert "UNCERTAINTY_METHOD_NOT_EMPIRICALLY_RELIABLE" in gate.reason_codes
    assert row.selection_strength is None


def test_adversarial_veto_contains_failure_case_and_materiality_audit() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs_nested(
            "match_winner_home",
            "adversarial_review",
            veto=True,
            materiality=0.9,
            represented_in_uncertainty=False,
        ),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G8)

    assert gate.status is GateStatus.FAIL
    assert "ADVERSARIAL_VETO" in gate.reason_codes
    assert gate.details["failure_case"]
    assert gate.details["supporting_evidence_ids"]
    assert gate.details["materiality"] == 0.9
    assert row.selection_strength is None


def test_adversarial_downgrade_is_retained_without_becoming_a_veto() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs_nested(
            "match_winner_home",
            "adversarial_review",
            downgrade=True,
        ),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G8)

    assert gate.status is GateStatus.PASS
    assert gate.details["downgrade"] is True
    assert row.adversarial_review is not None
    assert row.adversarial_review.downgrade is True
    assert row.adversarial_review.outcome == "DOWNGRADE"
    review = cast(dict[str, object], row.to_dict()["adversarial_review"])
    assert review["downgrade"] is True
    assert review["outcome"] == "DOWNGRADE"


def test_production_policy_selects_one_primary_and_correlated_secondary_fits() -> None:
    from matchvet.t15 import (
        CandidateRole,
        CandidateStatus,
        MatchDecision,
        vet_target_match,
    )

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_goals_over_1_5"] = {
        **inputs["match_goals_over_1_5"],
        "selection_components": _component_values(0.95),
    }
    inputs["match_goals_over_2_5"] = {
        **inputs["match_goals_over_2_5"],
        "selection_components": _component_values(0.8),
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(production=True),
        candidate_inputs=inputs,
    )

    assert result.decision is MatchDecision.PLAY
    assert result.primary_recommendation is not None
    assert result.primary_recommendation.preference.preference_id == "match_goals_over_1_5"
    assert result.primary_recommendation.status is CandidateStatus.PRIMARY_RECOMMENDATION
    assert result.primary_recommendation.role is CandidateRole.PRIMARY_RECOMMENDATION
    assert len(result.secondary_fits) == 2
    assert {item.preference.preference_id for item in result.secondary_fits} == {
        "match_goals_over_2_5",
        "match_goals_over_3_5",
    }
    assert all(
        item.status is CandidateStatus.CORRELATED_SECONDARY_FIT for item in result.secondary_fits
    )
    assert (
        sum(item.role is CandidateRole.PRIMARY_RECOMMENDATION for item in result.preference_results)
        == 1
    )


def test_correlation_does_not_inflate_probability_or_selection_strength() -> None:
    from matchvet.t15 import vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_goals_over_1_5"] = {
        **inputs["match_goals_over_1_5"],
        "selection_components": _component_values(0.9),
    }
    with_groups = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(production=True),
        candidate_inputs=inputs,
    )
    without_groups = vet_target_match(
        _evidence_state(),
        _predictions(),
        replace(_policy(production=True), correlation_groups={}),
        candidate_inputs=inputs,
    )
    left = _row(with_groups, "match_goals_over_1_5")
    right = _row(without_groups, "match_goals_over_1_5")

    assert left.conservative_probability == right.conservative_probability
    assert left.selection_strength == right.selection_strength
    assert len(with_groups.secondary_fits) == 2
    assert without_groups.secondary_fits == ()


def test_correlated_secondary_fit_must_remain_explanatory() -> None:
    from matchvet.t15 import CandidateRole, vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_goals_over_1_5"] = {
        **inputs["match_goals_over_1_5"],
        "selection_components": _component_values(0.95),
    }
    inputs["match_goals_over_2_5"] = {
        **inputs["match_goals_over_2_5"],
        "selection_components": _component_values(0.85),
        "explanatory": False,
    }
    inputs["match_goals_over_3_5"] = {
        **inputs["match_goals_over_3_5"],
        "selection_components": _component_values(0.8),
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(production=True),
        candidate_inputs=inputs,
    )

    assert {item.preference.preference_id for item in result.secondary_fits} == {
        "match_goals_over_3_5"
    }
    assert _row(result, "match_goals_over_2_5").role is CandidateRole.NONE


def test_all_rejected_production_match_is_avoid_with_complete_audit() -> None:
    from matchvet.t15 import CandidateStatus, MatchDecision, vet_target_match

    inputs = {
        preference_id: {**value, "non_trivial": False}
        for preference_id, value in _candidate_inputs().items()
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(production=True),
        candidate_inputs=inputs,
    )

    assert result.decision is MatchDecision.AVOID_MATCH
    assert result.avoid_reason == "NO_PREFERENCE_PASSED_ABSOLUTE_GATES"
    assert result.primary_recommendation is None
    assert result.secondary_fits == ()
    assert result.all_rejected
    assert len(result.preference_results) == 37
    assert all(item.status is CandidateStatus.REJECT for item in result.preference_results)
    assert all(item.selection_strength is None for item in result.preference_results)
    assert all(item.rejection_reasons for item in result.preference_results)


def test_research_all_rejected_is_research_avoid_not_production_avoid() -> None:
    from matchvet.t15 import MatchDecision, vet_target_match

    inputs = {
        preference_id: {**value, "non_trivial": False}
        for preference_id, value in _candidate_inputs().items()
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=inputs,
    )

    assert result.decision is MatchDecision.RESEARCH_AVOID
    assert result.primary_recommendation is None
    assert result.secondary_fits == ()
    assert result.research_primary_candidate is None


def test_market_normalized_component_controls_ranking_over_raw_probability() -> None:
    from matchvet.t15 import vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_winner_home"] = {
        **inputs["match_winner_home"],
        "selection_components": {
            **_component_values(0.5),
            "conservative_probability": 0.2,
        },
    }
    inputs["match_goals_over_1_5"] = {
        **inputs["match_goals_over_1_5"],
        "selection_components": {
            **_component_values(0.5),
            "conservative_probability": 0.8,
        },
    }
    predictions = _predictions()
    predictions["FULL_TIME_GOALS"] = {
        **predictions["FULL_TIME_GOALS"],
        "conservative_probabilities": {
            **cast(
                Mapping[str, float],
                predictions["FULL_TIME_GOALS"]["conservative_probabilities"],
            ),
            "match_winner_home": 0.99,
        },
    }
    result = vet_target_match(
        _evidence_state(),
        predictions,
        _policy(production=True),
        candidate_inputs=inputs,
    )

    assert result.primary_recommendation is not None
    assert result.primary_recommendation.preference.preference_id == "match_goals_over_1_5"
    assert _row(result, "match_winner_home").conservative_probability == 0.99


def test_statistical_tie_uses_uncertainty_then_data_quality_failure_and_reliability() -> None:
    from matchvet.t15 import vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_winner_home"] = {
        **inputs["match_winner_home"],
        "uncertainty_width": 0.08,
    }
    inputs["match_winner_draw"] = {
        **inputs["match_winner_draw"],
        "uncertainty_width": 0.02,
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(production=True),
        candidate_inputs=inputs,
    )
    home = _row(result, "match_winner_home")
    draw = _row(result, "match_winner_draw")

    assert home.selection_strength == draw.selection_strength
    assert draw.rank is not None and home.rank is not None
    assert draw.rank < home.rank


def test_user_preference_order_breaks_only_a_remaining_exact_tie() -> None:
    from matchvet.t15 import vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    policy = replace(
        _policy(production=True),
        user_preference_order=("match_winner_draw", "match_winner_home"),
    )
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        policy,
        candidate_inputs=inputs,
    )

    assert result.primary_recommendation is not None
    assert result.primary_recommendation.preference.preference_id == "match_winner_draw"


def test_banned_under_and_over_half_markets_can_only_be_rejected() -> None:
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    banned = replace(
        DEFAULT_PREFERENCE_CATALOG.get("match_goals_over_1_5"),
        line=Fraction(1, 2),
        label="Match Goals Over 0.5",
    )
    catalog = PreferenceCatalog((banned,))
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
        catalog=catalog,
    )
    row = result.preference_results[0]
    gate = next(item for item in row.gates if item.gate_id is GateId.G0)

    assert gate.status is GateStatus.FAIL
    assert "BANNED_OVER_0_5" in gate.reason_codes
    assert row.selection_strength is None
    assert result.research_primary_candidate is None


def test_research_policy_cannot_emit_production_play_or_labels() -> None:
    from matchvet.t15 import MatchDecision, PolicyStatus, vet_target_match

    inputs = _candidate_inputs()
    for preference_id in inputs:
        inputs[preference_id] = {
            **inputs[preference_id],
            "selection_components": _component_values(0.5),
        }
    inputs["match_goals_over_1_5"] = {
        **inputs["match_goals_over_1_5"],
        "selection_components": _component_values(0.9),
    }
    result = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=inputs,
    )

    assert result.policy_status is PolicyStatus.RESEARCH_ONLY
    assert result.decision is MatchDecision.RESEARCH_ONLY
    assert result.primary_recommendation is None
    assert result.secondary_fits == ()
    assert result.research_primary_candidate is not None
    assert result.research_secondary_candidates
    assert all(
        "Primary Recommendation" not in item.role.value for item in result.preference_results
    )
    assert all(
        "Correlated Secondary Fit" not in item.role.value for item in result.preference_results
    )
    assert "PLAY" not in str(result.to_dict())


def test_production_policy_requires_explicit_promotion_and_frozen_numeric_contract() -> None:
    from matchvet.t15 import (
        PolicyStatus,
        PolicyValidationError,
        PolicyVersion,
        TransformSpec,
    )

    with pytest.raises(PolicyValidationError):
        PolicyVersion(
            version="unpromoted-production-policy",
            status=PolicyStatus.PRODUCTION_PROMOTED,
            thresholds={},
            selection_strength=_selection_config(),
            promotion_evidence={"explicitly_promoted": False},
        ).validate_for_production()

    with pytest.raises(PolicyValidationError):
        PolicyVersion(version="policy-with-odds", thresholds={"odds": 2.0})

    with pytest.raises(ValueError):
        TransformSpec(kind="linear")


def test_candidate_bookmaker_odds_are_not_a_vetting_input_or_output() -> None:
    from matchvet.t15 import vet_target_match

    with_odds = _candidate_inputs_with("match_winner_home", odds=1.01)
    without_odds = _candidate_inputs()
    left = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=with_odds,
    )
    right = vet_target_match(
        _evidence_state(),
        _predictions(),
        _policy(),
        candidate_inputs=without_odds,
    )

    assert (
        _row(left, "match_winner_home").selection_strength
        == _row(right, "match_winner_home").selection_strength
    )
    assert "odds" not in str(left.to_dict()).lower()


def test_vet_matchweek_is_deterministic_and_orders_fixtures_by_id() -> None:
    from matchvet.t15 import vet_matchweek

    first_state = _state_with(target=replace(_target(), fixture_id="fixture-t15-a"))
    second_target = replace(_target(), fixture_id="fixture-t15-b")
    second_state = _state_with(target=second_target)
    states = {"fixture-t15-b": second_state, "fixture-t15-a": first_state}
    predictions = {
        "fixture-t15-a": _predictions(),
        "fixture-t15-b": _predictions(),
    }
    inputs = {
        "fixture-t15-a": _candidate_inputs(),
        "fixture-t15-b": _candidate_inputs(),
    }
    policy = _policy()

    first = vet_matchweek(states, predictions, policy, candidate_inputs=inputs)
    second = vet_matchweek(
        {"fixture-t15-a": first_state, "fixture-t15-b": second_state},
        {
            "fixture-t15-b": predictions["fixture-t15-b"],
            "fixture-t15-a": predictions["fixture-t15-a"],
        },
        policy,
        candidate_inputs={
            "fixture-t15-b": inputs["fixture-t15-b"],
            "fixture-t15-a": inputs["fixture-t15-a"],
        },
    )

    assert [cast(TargetMatch, item.target).fixture_id for item in first.matches] == [
        "fixture-t15-a",
        "fixture-t15-b",
    ]
    assert first.audit_digest == second.audit_digest
    assert first.to_dict() == second.to_dict()


def test_t14_reference_sensitivity_object_is_consumed_for_g7() -> None:
    from matchvet.t14 import ReferenceSensitivity
    from matchvet.t15 import GateId, GateStatus, vet_target_match

    preference_ids = tuple(
        preference.preference_id
        for preference in DEFAULT_PREFERENCE_CATALOG
        if _family_key(preference.family) == "FULL_TIME_GOALS"
    )
    sensitivity = ReferenceSensitivity(
        agreement=0.9,
        uncertainty_multiplier=1.0,
        sensitivity_by_preference={preference_id: 0.1 for preference_id in preference_ids},
        group_sensitivity={},
        effective_dependency_groups=(),
        correlated_reference_groups=(),
        meaningful_reference_names=("reference-model",),
        reference_digests=("reference-digest",),
    )
    predictions = _predictions()
    predictions["FULL_TIME_GOALS"] = {
        **predictions["FULL_TIME_GOALS"],
        "reference_sensitivity": sensitivity,
        "model_agreement": None,
    }
    result = vet_target_match(
        _evidence_state(),
        predictions,
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "match_winner_home")
    gate = next(item for item in row.gates if item.gate_id is GateId.G7)

    assert gate.status is GateStatus.PASS
    assert row.model_agreement == 0.9
    assert row.model_sensitivity == 0.1


def test_real_t09_frozen_state_family_contract_is_consumed() -> None:
    from matchvet.t09 import EvidenceResearcher, EvidenceResearchInput
    from matchvet.t15 import GateId, vet_target_match

    state = EvidenceResearcher().build(EvidenceResearchInput(target=_target()))
    result = vet_target_match(
        state,
        _predictions(),
        _policy(),
        candidate_inputs=_candidate_inputs(),
    )
    row = _row(result, "asian_handicap_home_0_0")
    g1 = next(item for item in row.gates if item.gate_id is GateId.G1)
    g2 = next(item for item in row.gates if item.gate_id is GateId.G2)

    assert "RESEARCH_SUFFICIENCY_MISSING" not in g1.reason_codes
    assert "CRITICAL_EVIDENCE_COVERAGE_MISSING" not in g2.reason_codes

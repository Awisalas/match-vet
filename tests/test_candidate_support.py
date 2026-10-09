from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from itertools import permutations
from pathlib import Path
from typing import cast

import pytest

from matchvet.candidate_support import (
    G6_U1_EVENT_RESULT_MEDIA_TYPE,
    CandidatePreferenceSupport,
    CandidateSupportManifest,
    ComparisonState,
    ComponentSupportReference,
    F13UncertaintyIdentity,
    FinalistCandidate,
    G6U1EventResult,
    GateSupportStatus,
    JointUncertaintySupport,
    PairDifferenceSupport,
    PreferenceSupportContext,
    SupportState,
    T15ComparisonResult,
    compare_finalists,
    comparison_rule_digest,
    evaluate_candidate_support,
    group_resolver_rule_digest,
    resolve_component_support,
)
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG
from matchvet.t15 import (
    SELECTION_COMPONENTS,
    CandidateRole,
    CandidateStatus,
    NormalizationSpec,
    PolicyVersion,
    PreferenceVettingResult,
    SelectionStrengthConfig,
    TransformSpec,
    _compare_results,
)


def _proof_record(kind: str, payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    from matchvet.candidate_support import _digest

    record = {**payload, "kind": kind, "schema_version": 1}
    return record, _digest(record)


def _u2_with_record(value: Mapping[str, object]) -> dict[str, object]:
    payload = {
        field: value[field]
        for field in (
            "claim",
            "evidence_basis",
            "preference_contract_digest",
            "cutoff_id",
            "cutoff_digest",
            "policy_digest",
            "population_digest",
            "chronology_digest",
            "groups_digest",
            "group_keys",
            "assumptions_digest",
            "diagnostics_digest",
            "method",
            "settlement_topology",
        )
    }
    record, digest = _proof_record("G6_U2_VALIDATION", payload)
    return {**value, "validation_record": record, "validation_artifact_digest": digest}


def test_component_support_falls_back_only_with_matching_estimand_and_topology() -> None:
    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(
        preference=preference,
        league="premier_league",
        supported_contexts=("home-favourite",),
        component_estimands={"win_lift": "win-lift-v1"},
    )
    compatible = ComponentSupportReference(
        component="win_lift",
        scope="FAMILY_LINE",
        group_key="Match Winner|NONE",
        estimand_id="win-lift-v1",
        settlement_topology=("WIN", "LOSS"),
        normalizer={"method": "min_max", "lower": 0.0, "upper": 1.0},
        source_artifact_digests=("a" * 64,),
    )
    incompatible = ComponentSupportReference(
        component="win_lift",
        scope="ROLE",
        group_key="Home",
        estimand_id="win-lift-v1",
        settlement_topology=("WIN", "PUSH", "LOSS"),
        normalizer={"method": "min_max", "lower": 0.0, "upper": 1.0},
        source_artifact_digests=("b" * 64,),
    )

    resolved = resolve_component_support(context, "win_lift", (incompatible, compatible))

    assert resolved.state is SupportState.SUPPORTED
    assert resolved.reference_digest == compatible.digest
    assert resolved.fallback_reason == "FALLBACK_FAMILY_LINE"
    assert resolved.ancestors_considered == (
        "EXACT:match_winner_home",
        "FAMILY_LINE:Match Winner|NONE",
    )


def test_component_support_is_unknown_when_only_topology_incompatible_fallback_exists() -> None:
    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(
        preference=preference,
        league="premier_league",
        supported_contexts=(),
        component_estimands={"win_lift": "win-lift-v1"},
    )
    incompatible = ComponentSupportReference(
        component="win_lift",
        scope="ROLE",
        group_key="Home",
        estimand_id="win-lift-v1",
        settlement_topology=("WIN", "PUSH", "LOSS"),
        normalizer={"method": "min_max", "lower": 0.0, "upper": 1.0},
        source_artifact_digests=("c" * 64,),
    )

    resolved = resolve_component_support(context, "win_lift", (incompatible,))

    assert resolved.state is SupportState.UNKNOWN
    assert resolved.reference_digest is None
    assert resolved.normalizer is None
    assert resolved.fallback_reason == "NO_COMPATIBLE_SUPPORTED_REFERENCE"


def test_g6_g7_g8_missing_support_and_legacy_boolean_remain_unknown() -> None:
    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(
        preference=preference,
        league="premier_league",
        supported_contexts=(),
        component_estimands={},
    )
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest="a" * 64,
        f13_prediction_digest="b" * 64,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g6={"uncertainty_reliable": True, "uncertainty_tail_risk": 0.0},
    )

    result = evaluate_candidate_support(
        context,
        support,
        PolicyVersion("research-v2"),
        cutoff_id="cutoff-exact",
        cutoff_digest="c" * 64,
        f13_result_digest="d" * 64,
    )

    assert result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert result.gates["G7"].status is GateSupportStatus.UNKNOWN
    assert result.gates["G8"].status is GateSupportStatus.UNKNOWN
    assert result.status is GateSupportStatus.UNKNOWN


@pytest.mark.parametrize(
    ("availability_state", "eligibility_state"),
    (("UNAVAILABLE", "ELIGIBLE"), ("AVAILABLE", "INELIGIBLE")),
)
def test_g7_unavailable_or_ineligible_required_reference_stays_unknown(
    availability_state: str, eligibility_state: str
) -> None:
    from matchvet.candidate_support import _digest

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(preference, "premier_league", (), {})
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest="a" * 64,
        f13_prediction_digest="b" * 64,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g7={
            "state": "SUPPORTED",
            "preference_contract_digest": _digest(preference.to_dict()),
            "cutoff_id": "cutoff-exact",
            "cutoff_digest": "c" * 64,
            "candidate_prediction_digest": "b" * 64,
            "evaluation_artifact_digest": "e" * 64,
            "model_agreement": 1.0,
            "model_sensitivity": 0.0,
            "references": [
                {
                    "reference_id": "reference-one",
                    "availability_state": availability_state,
                    "eligibility_state": eligibility_state,
                }
            ],
        },
    )
    policy = PolicyVersion(
        "research-v2",
        thresholds={"model_agreement_min": 0.5, "model_sensitivity_max": 0.5},
        dependencies={
            f"candidate_input.g7_references:{preference.preference_id}": '["reference-one"]'
        },
    )

    result = evaluate_candidate_support(
        context,
        support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest="c" * 64,
        f13_result_digest="d" * 64,
    )

    assert result.gates["G7"].status is GateSupportStatus.UNKNOWN
    assert "G7_REFERENCE_UNAVAILABLE_OR_INELIGIBLE" in result.gates["G7"].reason_codes


def test_g7_evaluation_metrics_are_bound_to_exact_eligible_reference_records(
    tmp_path: Path,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.candidate_support import (
        G7_EVALUATION_MEDIA_TYPE,
        G7_REFERENCE_MEDIA_TYPE,
        CandidateInputSupportRepository,
        _digest,
    )
    from matchvet.matchweek_membership import canonical_json
    from matchvet.store import open_store

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    preference_digest = _digest(preference.to_dict())
    context = PreferenceSupportContext(preference, "premier_league", (), {})
    topology = tuple(item.value for item in preference.possible_results)
    reference_payload = {
        "reference_id": "reference-one",
        "availability_state": "AVAILABLE",
        "eligibility_state": "ELIGIBLE",
        "preference_contract_digest": preference_digest,
        "cutoff_id": "cutoff-exact",
        "cutoff_digest": "c" * 64,
        "settlement_topology": topology,
        "settlement_distribution": {"WIN": 0.6, "LOSS": 0.4},
        "settlement_ranges": {
            "WIN": {"lower": 0.5, "upper": 0.7},
            "LOSS": {"lower": 0.3, "upper": 0.5},
        },
        "dependency_group": "model-family-one",
        "provenance_digest": "1" * 64,
        "model_digest": "2" * 64,
        "calibration_digest": "3" * 64,
        "validation_digest": "4" * 64,
        "assumptions_digest": "5" * 64,
        "information_path_digest": "6" * 64,
        "historical_error_digest": "7" * 64,
        "source_artifact_digests": ("8" * 64,),
    }
    reference_record, reference_digest = _proof_record("G7_REFERENCE", reference_payload)
    reference = {
        **reference_payload,
        "reference_record": reference_record,
        "reference_artifact_digest": reference_digest,
    }
    policy = PolicyVersion(
        "research-v2",
        thresholds={"model_agreement_min": 0.5, "model_sensitivity_max": 0.5},
        dependencies={
            f"candidate_input.g7_references:{preference.preference_id}": '["reference-one"]'
        },
    )
    evaluation_payload = {
        "preference_contract_digest": preference_digest,
        "cutoff_id": "cutoff-exact",
        "cutoff_digest": "c" * 64,
        "policy_digest": policy.digest,
        "candidate_prediction_digest": "b" * 64,
        "reference_artifact_digests": (reference_digest,),
        "model_agreement": 0.9,
        "model_sensitivity": 0.1,
    }
    evaluation_record, evaluation_digest = _proof_record("G7_EVALUATION", evaluation_payload)
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest=preference_digest,
        f13_prediction_digest="b" * 64,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g7={
            "state": "SUPPORTED",
            "preference_contract_digest": preference_digest,
            "cutoff_id": "cutoff-exact",
            "cutoff_digest": "c" * 64,
            "candidate_prediction_digest": "b" * 64,
            "evaluation_artifact_digest": evaluation_digest,
            "evaluation_record": evaluation_record,
            "model_agreement": 0.9,
            "model_sensitivity": 0.1,
            "references": [reference],
        },
    )

    result = evaluate_candidate_support(
        context,
        support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest="c" * 64,
        f13_result_digest="d" * 64,
    )
    assert result.gates["G7"].status is GateSupportStatus.PASS

    with open_store(tmp_path / "g7-proofs.sqlite3", private_root=tmp_path) as store:
        artifacts = ArtifactStore(store)
        assert (
            artifacts.publish_artifact(
                canonical_json(reference_record).encode("utf-8"), G7_REFERENCE_MEDIA_TYPE
            ).digest
            == reference_digest
        )
        assert (
            artifacts.publish_artifact(
                canonical_json(evaluation_record).encode("utf-8"), G7_EVALUATION_MEDIA_TYPE
            ).digest
            == evaluation_digest
        )
        repository = CandidateInputSupportRepository(store)
        assert repository._gate_proof_records_match("g7", support.g7 or {})
        unrelated = artifacts.publish_artifact(b'{"unrelated":true}', G7_REFERENCE_MEDIA_TYPE)
        unrelated_reference = {
            **reference,
            "reference_artifact_digest": unrelated.digest,
        }
        assert not repository._gate_proof_records_match(
            "g7", {**(support.g7 or {}), "references": [unrelated_reference]}
        )

    forged = replace(
        support,
        g7={**(support.g7 or {}), "model_agreement": 1.0},
    )
    refused = evaluate_candidate_support(
        context,
        forged,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest="c" * 64,
        f13_result_digest="d" * 64,
    )
    assert refused.gates["G7"].status is GateSupportStatus.UNKNOWN
    assert "G7_EVALUATION_UNKNOWN" in refused.gates["G7"].reason_codes


def test_g6_requires_protected_u1_and_claim_specific_u2() -> None:
    from matchvet.candidate_support import _digest

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    preference_contract_digest = _digest(preference.to_dict())
    context = PreferenceSupportContext(preference, "premier_league", (), {})
    cutoff_digest = "c" * 64
    f13_digest = "d" * 64
    f13_uncertainty = F13UncertaintyIdentity(
        prediction_digest=f13_digest,
        uncertainty_law_digest="1" * 64,
        source_draws_digest="2" * 64,
    )
    policy = PolicyVersion(
        "research-v2",
        thresholds={
            "conservative_probability_min": 0.5,
            "loss_risk_max": 0.4,
            "uncertainty_width_max": 0.5,
            "uncertainty_tail_risk_max": 0.2,
        },
        dependencies={
            f"candidate_input.u2_claim:{preference.preference_id}": "PREDICTIVE_COVERAGE"
        },
    )
    g5_constraints = _digest(
        {
            "conservative_probability_min": 0.5,
            "loss_risk_max": 0.4,
            "policy_digest": policy.digest,
            "preference_id": preference.preference_id,
        }
    )
    common = {
        "state": "SUPPORTED",
        "cutoff_id": "cutoff-exact",
        "cutoff_digest": cutoff_digest,
        "settlement_topology": ("WIN", "LOSS"),
        "preference_contract_digest": preference_contract_digest,
    }
    target_groups = (
        f"LEAGUE:{context.league}",
        f"PREFERENCE:{preference.preference_id}",
    )
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest="a" * 64,
        f13_prediction_digest=f13_digest,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g6={
            "uncertainty_width": 0.3,
            "u1": {
                **common,
                "probability_mass": 0.1,
                "event_result_digest": "f" * 64,
                "artifact_digest": "f" * 64,
                "schema_version": 1,
                "f13_prediction_digest": f13_uncertainty.prediction_digest,
                "policy_digest": policy.digest,
                "uncertainty_law_digest": f13_uncertainty.uncertainty_law_digest,
                "g5_constraints_digest": g5_constraints,
                "source_draws_digest": f13_uncertainty.source_draws_digest,
                "f13_result_digest": f13_digest,
            },
            "u2": _u2_with_record(
                {
                    **common,
                    "claim": "PREDICTIVE_COVERAGE",
                    "evidence_basis": "LATER_OUTCOME_VALIDATION",
                    "policy_digest": policy.digest,
                    "method": "held-out-chronology-v1",
                    "population_digest": "4" * 64,
                    "chronology_digest": "5" * 64,
                    "group_keys": target_groups,
                    "groups_digest": _digest({"group_keys": tuple(sorted(target_groups))}),
                    "assumptions_digest": "7" * 64,
                    "diagnostics_digest": "8" * 64,
                }
            ),
        },
    )

    result = evaluate_candidate_support(
        context,
        support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )

    assert result.gates["G6"].status is GateSupportStatus.PASS

    g6 = dict(support.g6 or {})
    u2 = g6.get("u2")
    u1 = g6.get("u1")
    assert isinstance(u2, Mapping)
    assert isinstance(u1, Mapping)
    forged_u2 = replace(
        support,
        g6={**g6, "u2": {**u2, "method": "unrelated-validation"}},
    )
    forged_u2_result = evaluate_candidate_support(
        context,
        forged_u2,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert forged_u2_result.gates["G6"].status is GateSupportStatus.UNKNOWN

    other_group_keys = ("LEAGUE:other-league",)
    wrong_group_support = replace(
        support,
        g6={
            **g6,
            "u2": _u2_with_record(
                {
                    **u2,
                    "group_keys": other_group_keys,
                    "groups_digest": _digest({"group_keys": other_group_keys}),
                }
            ),
        },
    )
    wrong_group_result = evaluate_candidate_support(
        context,
        wrong_group_support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert wrong_group_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_UNSUPPORTED_VALIDATION_GROUP" in wrong_group_result.gates["G6"].reason_codes

    unrelated_f13_uncertainty = F13UncertaintyIdentity(
        prediction_digest=f13_digest,
        uncertainty_law_digest="9" * 64,
        source_draws_digest=f13_uncertainty.source_draws_digest,
    )
    unrelated_result = evaluate_candidate_support(
        context,
        support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=unrelated_f13_uncertainty,
    )
    assert unrelated_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_U1_F13_LINK_UNKNOWN" in unrelated_result.gates["G6"].reason_codes

    bad_event_identity = replace(
        support,
        g6={**g6, "u1": {**u1, "event_result_digest": "e" * 64}},
    )
    bad_event_result = evaluate_candidate_support(
        context,
        bad_event_identity,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert bad_event_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_U1_F13_LINK_UNKNOWN" in bad_event_result.gates["G6"].reason_codes

    mismatched_claim = replace(
        support,
        g6={**g6, "u2": _u2_with_record({**u2, "claim": "CALIBRATION"})},
    )
    mismatch_result = evaluate_candidate_support(
        context,
        mismatched_claim,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )

    assert mismatch_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_REQUIRED_SUPPORT_UNKNOWN" in mismatch_result.gates["G6"].reason_codes

    invented_policy = PolicyVersion(
        "research-v2",
        thresholds=policy.thresholds,
        dependencies={f"candidate_input.u2_claim:{preference.preference_id}": "MADE_UP_CLAIM"},
    )
    invented_g5_constraints = _digest(
        {
            "conservative_probability_min": 0.5,
            "loss_risk_max": 0.4,
            "policy_digest": invented_policy.digest,
            "preference_id": preference.preference_id,
        }
    )
    invented_support = replace(
        support,
        g6={
            **g6,
            "u1": {
                **u1,
                "g5_constraints_digest": invented_g5_constraints,
                "policy_digest": invented_policy.digest,
            },
            "u2": _u2_with_record(
                {**u2, "claim": "MADE_UP_CLAIM", "policy_digest": invented_policy.digest}
            ),
        },
    )
    invented_result = evaluate_candidate_support(
        context,
        invented_support,
        invented_policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert invented_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_REQUIRED_SUPPORT_UNKNOWN" in invented_result.gates["G6"].reason_codes

    latent_policy = PolicyVersion(
        "research-v2",
        thresholds=policy.thresholds,
        dependencies={
            f"candidate_input.u2_claim:{preference.preference_id}": (
                "LATENT_PROBABILITY_INTERVAL_COVERAGE"
            )
        },
    )
    latent_g5_constraints = _digest(
        {
            "conservative_probability_min": 0.5,
            "loss_risk_max": 0.4,
            "policy_digest": latent_policy.digest,
            "preference_id": preference.preference_id,
        }
    )
    latent_valid_support = replace(
        support,
        g6={
            **g6,
            "u1": {
                **u1,
                "g5_constraints_digest": latent_g5_constraints,
                "policy_digest": latent_policy.digest,
            },
            "u2": _u2_with_record(
                {
                    **u2,
                    "claim": "LATENT_PROBABILITY_INTERVAL_COVERAGE",
                    "evidence_basis": "KNOWN_TRUTH_SIMULATION",
                    "policy_digest": latent_policy.digest,
                }
            ),
        },
    )
    latent_valid_result = evaluate_candidate_support(
        context,
        latent_valid_support,
        latent_policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert latent_valid_result.gates["G6"].status is GateSupportStatus.PASS

    latent_support = replace(
        support,
        g6={
            **g6,
            "u1": {
                **u1,
                "g5_constraints_digest": latent_g5_constraints,
                "policy_digest": latent_policy.digest,
            },
            "u2": _u2_with_record(
                {
                    **u2,
                    "claim": "LATENT_PROBABILITY_INTERVAL_COVERAGE",
                    "evidence_basis": "LATER_OUTCOME_VALIDATION",
                    "policy_digest": latent_policy.digest,
                }
            ),
        },
    )
    latent_result = evaluate_candidate_support(
        context,
        latent_support,
        latent_policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert latent_result.gates["G6"].status is GateSupportStatus.UNKNOWN
    assert "G6_REQUIRED_SUPPORT_UNKNOWN" in latent_result.gates["G6"].reason_codes

    calibration_policy = PolicyVersion(
        "research-v2",
        thresholds=policy.thresholds,
        dependencies={f"candidate_input.u2_claim:{preference.preference_id}": "CALIBRATION"},
    )
    calibration_g5_constraints = _digest(
        {
            "conservative_probability_min": 0.5,
            "loss_risk_max": 0.4,
            "policy_digest": calibration_policy.digest,
            "preference_id": preference.preference_id,
        }
    )
    calibration_support = replace(
        support,
        g6={
            **g6,
            "u1": {
                **u1,
                "g5_constraints_digest": calibration_g5_constraints,
                "policy_digest": calibration_policy.digest,
            },
            "u2": _u2_with_record(
                {**u2, "claim": "CALIBRATION", "policy_digest": calibration_policy.digest}
            ),
        },
    )
    calibration_result = evaluate_candidate_support(
        context,
        calibration_support,
        calibration_policy,
        cutoff_id="cutoff-exact",
        cutoff_digest=cutoff_digest,
        f13_result_digest=f13_digest,
        f13_uncertainty=f13_uncertainty,
    )
    assert calibration_result.gates["G6"].status is GateSupportStatus.PASS


def test_g6_requires_typed_protected_u1_artifact_bound_to_f13_uncertainty(
    tmp_path: Path,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.candidate_support import CandidateInputSupportRepository, _digest
    from matchvet.matchweek_membership import canonical_json
    from matchvet.store import open_store

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    preference_digest = _digest(preference.to_dict())
    record = G6U1EventResult(
        cutoff_id="cutoff-exact",
        cutoff_digest="a" * 64,
        preference_contract_digest=preference_digest,
        f13_result_digest="b" * 64,
        f13_prediction_digest="c" * 64,
        policy_digest="d" * 64,
        g5_constraints_digest="e" * 64,
        uncertainty_law_digest="f" * 64,
        source_draws_digest="1" * 64,
        settlement_topology=tuple(item.value for item in preference.possible_results),
        probability_mass=0.1,
    )
    uncertainty = F13UncertaintyIdentity(
        prediction_digest=record.f13_prediction_digest,
        uncertainty_law_digest=record.uncertainty_law_digest,
        source_draws_digest=record.source_draws_digest,
    )
    with open_store(tmp_path / "u1-support.sqlite3", private_root=tmp_path) as store:
        artifacts = ArtifactStore(store)
        artifact = artifacts.publish_artifact(
            canonical_json(record.to_dict()).encode("utf-8"), G6_U1_EVENT_RESULT_MEDIA_TYPE
        )
        support = CandidatePreferenceSupport(
            preference_id=preference.preference_id,
            preference_contract_digest=preference_digest,
            f13_prediction_digest=record.f13_prediction_digest,
            component_estimands={},
            supported_contexts=(),
            component_references=(),
            g6={
                "u1": {
                    **record.to_dict(),
                    "state": "SUPPORTED",
                    "event_result_digest": artifact.digest,
                    "artifact_digest": artifact.digest,
                }
            },
        )
        repository = CandidateInputSupportRepository(store)
        accepted = repository._safe_preference_support(
            support,
            f13_uncertainty=uncertainty,
            f13_result_digest=record.f13_result_digest,
        )
        assert accepted is not None
        assert accepted.g6 == support.g6

        wrong_f13_link = F13UncertaintyIdentity(
            prediction_digest=uncertainty.prediction_digest,
            uncertainty_law_digest="2" * 64,
            source_draws_digest=uncertainty.source_draws_digest,
        )
        refused = repository._safe_preference_support(
            support,
            f13_uncertainty=wrong_f13_link,
            f13_result_digest=record.f13_result_digest,
        )
        assert refused is not None
        assert refused.g6 == {"state": "UNKNOWN"}


def test_f13_uncertainty_identity_uses_exact_candidate_prediction_law_and_draws() -> None:
    from matchvet.candidate_support import _digest, _f13_uncertainty_identity

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    calibrated_uncertainty = {
        "components": {"parameter": {"draws_digest": "a" * 64}},
        "method": "fixture-law-v1",
    }
    f13_model = {
        "results": {
            "FULL_TIME_GOALS": {
                "prediction_digest": "b" * 64,
                "uncertainty": {"calibrated": calibrated_uncertainty},
            }
        }
    }

    identity = _f13_uncertainty_identity(preference, f13_model)

    assert identity == F13UncertaintyIdentity(
        prediction_digest="b" * 64,
        uncertainty_law_digest=_digest(calibrated_uncertainty),
        source_draws_digest="a" * 64,
    )


def test_g8_missing_exact_representation_proof_stays_unknown() -> None:
    from matchvet.candidate_support import _digest

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(preference, "premier_league", (), {})
    preference_digest = _digest(preference.to_dict())
    policy = PolicyVersion(
        "research-v2", thresholds={"adversarial_unrepresented_materiality_max": 0.5}
    )
    evidence_digests = ("d" * 64,)
    assertion_payload = {
        "case_id": "failure-one",
        "preference_contract_digest": preference_digest,
        "f13_result_digest": "b" * 64,
        "consequence": "NO_VETO",
        "supporting_evidence_digests": evidence_digests,
        "policy_digest": policy.digest,
    }
    assertion_record, assertion_digest = _proof_record("G8_FAILURE_ASSERTION", assertion_payload)
    materiality_payload = {
        "case_id": "failure-one",
        "preference_contract_digest": preference_digest,
        "f13_result_digest": "b" * 64,
        "policy_digest": policy.digest,
        "source_assertion_digest": assertion_digest,
        "supporting_evidence_digests": evidence_digests,
        "value": 0.2,
        "effect_unit": "probability-mass",
    }
    materiality_record, materiality_digest = _proof_record("G8_MATERIALITY", materiality_payload)
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest="a" * 64,
        f13_prediction_digest="b" * 64,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g6={"u1": {"uncertainty_law_digest": "e" * 64}},
        g8={
            "state": "SUPPORTED",
            "preference_contract_digest": preference_digest,
            "f13_result_digest": "b" * 64,
            "failure_cases": [
                {
                    "case_id": "failure-one",
                    "source_assertion_digest": assertion_digest,
                    "assertion_record": assertion_record,
                    "supporting_evidence_digests": evidence_digests,
                    "consequence": "NO_VETO",
                    "materiality": {
                        "state": "SUPPORTED",
                        "value": 0.2,
                        "effect_unit": "probability-mass",
                        "support_digest": materiality_digest,
                        "support_artifact_digest": materiality_digest,
                        "support_record": materiality_record,
                    },
                    "uncertainty_representation": {
                        "state": "NOT_REPRESENTED",
                        "f13_result_digest": "b" * 64,
                        "uncertainty_law_digest": "e" * 64,
                    },
                }
            ],
        },
    )
    result = evaluate_candidate_support(
        context,
        support,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest="f" * 64,
        f13_result_digest="b" * 64,
    )

    assert result.gates["G8"].status is GateSupportStatus.UNKNOWN
    assert "G8_UNCERTAINTY_REPRESENTATION_UNKNOWN" in result.gates["G8"].reason_codes

    g8 = support.g8 or {}
    cases = cast(list[Mapping[str, object]], g8["failure_cases"])
    case = cases[0]
    forged_materiality = replace(
        support,
        g8={
            **g8,
            "failure_cases": [
                {
                    **case,
                    "materiality": {
                        **cast(Mapping[str, object], case["materiality"]),
                        "value": 0.4,
                    },
                }
            ],
        },
    )
    forged_result = evaluate_candidate_support(
        context,
        forged_materiality,
        policy,
        cutoff_id="cutoff-exact",
        cutoff_digest="f" * 64,
        f13_result_digest="b" * 64,
    )
    assert forged_result.gates["G8"].status is GateSupportStatus.UNKNOWN
    assert "G8_MATERIALITY_OR_EVIDENCE_UNKNOWN" in forged_result.gates["G8"].reason_codes

    duplicate_evidence = replace(
        support,
        g8={
            **g8,
            "failure_cases": [{**case, "supporting_evidence_digests": ["d" * 64, "d" * 64]}],
        },
    )
    reused_assertion = replace(
        support,
        g8={
            **g8,
            "failure_cases": [
                {
                    **case,
                    "supporting_evidence_digests": ["c" * 64],
                }
            ],
        },
    )
    for malformed in (duplicate_evidence, reused_assertion):
        malformed_result = evaluate_candidate_support(
            context,
            malformed,
            policy,
            cutoff_id="cutoff-exact",
            cutoff_digest="f" * 64,
            f13_result_digest="b" * 64,
        )
        assert malformed_result.gates["G8"].status is GateSupportStatus.UNKNOWN
        assert "G8_MATERIALITY_OR_EVIDENCE_UNKNOWN" in malformed_result.gates["G8"].reason_codes


def test_g8_supporting_evidence_is_collected_for_exact_artifact_verification() -> None:
    from matchvet.candidate_support import _artifact_digests

    evidence_digest = "a" * 64
    assert _artifact_digests({"supporting_evidence_digests": [evidence_digest]}) == (
        evidence_digest,
    )


def test_g8_missing_materiality_artifact_fails_closed() -> None:
    from matchvet.candidate_support import _digest

    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    context = PreferenceSupportContext(preference, "premier_league", (), {})
    support = CandidatePreferenceSupport(
        preference_id=preference.preference_id,
        preference_contract_digest=_digest(preference.to_dict()),
        f13_prediction_digest="b" * 64,
        component_estimands={},
        supported_contexts=(),
        component_references=(),
        g8={
            "state": "SUPPORTED",
            "preference_contract_digest": _digest(preference.to_dict()),
            "f13_result_digest": "b" * 64,
            "failure_cases": [
                {
                    "case_id": "failure-one",
                    "source_assertion_digest": "c" * 64,
                    "supporting_evidence_digests": ["d" * 64],
                    "consequence": "NO_VETO",
                    "materiality": {
                        "state": "SUPPORTED",
                        "value": 0.2,
                        "effect_unit": "probability-mass",
                        "support_digest": "e" * 64,
                    },
                    "uncertainty_representation": {
                        "state": "NOT_REPRESENTED",
                        "absence_evidence_digest": "f" * 64,
                        "absence_evidence_artifact_digest": "f" * 64,
                    },
                }
            ],
        },
    )

    result = evaluate_candidate_support(
        context,
        support,
        PolicyVersion("research-v2", thresholds={"adversarial_unrepresented_materiality_max": 0.5}),
        cutoff_id="cutoff-exact",
        cutoff_digest="a" * 64,
        f13_result_digest="b" * 64,
    )

    assert result.gates["G8"].status is GateSupportStatus.UNKNOWN
    assert "G8_MATERIALITY_OR_EVIDENCE_UNKNOWN" in result.gates["G8"].reason_codes


def test_methodology_010_and_chronology_020_history_remain_byte_stable() -> None:
    import hashlib

    repository_root = Path(__file__).resolve().parents[1]
    legacy_method = repository_root / "docs/product-v2/CANDIDATE-INPUT-METHODOLOGY.md"
    chronology = repository_root / "docs/product-v2/CANDIDATE-INPUT-CHRONOLOGY-0.2.0.md"

    assert hashlib.sha256(legacy_method.read_bytes()).hexdigest() == (
        "1ebeb80f33190f18440d2dcfa5b2526d3907223471f4b2711b7445b0ece8e200"
    )
    assert hashlib.sha256(chronology.read_bytes()).hexdigest() == (
        "defa2568e3617c49abbde2f037826d27c56bebeb286347ad2c6c74b5dfa43029"
    )


def test_f14_unresolved_primary_is_persisted_and_replayed_from_exact_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    from test_match_evidence_cutoff import _freeze

    from matchvet.artifacts import ArtifactStore
    from matchvet.candidate_support import (
        F13_SUPPORT_MEDIA_TYPE,
        F14_SUPPORT_INPUT_MEDIA_TYPE,
        F14_SUPPORT_RESULT_MEDIA_TYPE,
        T15_COMPARISON_MEDIA_TYPE,
        T15_COMPARISON_RESULT_MEDIA_TYPE,
        CandidateInputSupportRepository,
    )
    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f13 import ModelContractRepository
    from matchvet.f14 import (
        DECISION_INPUT_MEDIA_TYPE,
        DECISION_MEDIA_TYPE,
        DecisionResult,
        PreferenceProfileRepository,
    )
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership import canonical_json
    from matchvet.store import open_store

    def encode(value: object) -> bytes:
        return canonical_json(value).encode("utf-8")

    with open_store(tmp_path / "candidate-support.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy_digest = cutoffs.persist_policy(CutoffPolicy("candidate-input", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze, cutoff_policy_digest)[0]
        evidence = F11EvidenceRepository(store).build(
            freeze, cutoff_policy_digest, weather_client=None
        )
        model = ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=())
        profiles = PreferenceProfileRepository(store)
        profile = profiles.build_profile(("match_winner_home",), profile_version="support-test")
        policy = PolicyVersion("candidate-input-research")
        from matchvet.f14 import DecisionInputBundle

        base_input = DecisionInputBundle(
            profile_digest=profile.digest,
            evidence_digest=evidence.digest,
            cutoff_id=cutoff.cutoff_id,
            model_result_digest=model.digest,
            policy=policy.to_dict(),
            candidate_inputs={},
        )
        artifacts = ArtifactStore(store)
        base_input_record = artifacts.publish_artifact(
            encode(base_input.to_dict()), DECISION_INPUT_MEDIA_TYPE
        )
        model_value = model.to_dict()
        preference = profile.enabled_preferences[0]
        base_vetting = {
            "preference": preference.to_dict(),
            "gates": [
                {"gate_id": f"G{index}", "status": "PASS", "reason_codes": ()} for index in range(9)
            ],
            "uncertainty_width": 0.2,
            "data_quality": 0.8,
            "failure_risk": 0.2,
            "historical_reliability": 0.7,
            "adversarial_review": {"materiality": 0.2},
        }
        base_lineage = {
            "cutoff_id": cutoff.cutoff_id,
            "evidence_digest": evidence.digest,
            "f13_model_result_digest": model.digest,
            "f13_models": {
                family: {
                    "calibration_artifact_digest": row["calibration_artifact_digest"],
                    "calibration_digest": row["calibration_digest"],
                    "calibration_version": row["calibration_version"],
                    "model_artifact_digest": row["model_artifact_digest"],
                    "model_fit_digest": row["model_fit_digest"],
                    "model_version": row["model_version"],
                    "prediction_artifact_digest": row["prediction_artifact_digest"],
                    "prediction_digest": row["prediction_digest"],
                    "uncertainty_engine": row["uncertainty_engine"],
                }
                for family, row in model_value["results"].items()
            },
            "profile_digest": profile.digest,
            "t10_preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
            "t15_policy_digest": policy.digest,
            "t15_policy_version": policy.version,
        }
        base_value = {
            "fixture_id": model_value["inputs"]["fixture_id"],
            "input_bundle_digest": base_input_record.digest,
            "lineage": base_lineage,
            "outcome": "AVOID MATCH",
            "primary_preference_id": None,
            "preference_results": [
                {"terminal_result": "SURVIVES_NOT_SELECTED", "vetting": base_vetting}
            ],
            "schema_version": 2,
            "status": "RESEARCH_ONLY",
        }
        base_decision = DecisionResult(encode(base_value))
        base_record = artifacts.publish_artifact(base_decision.to_bytes(), DECISION_MEDIA_TYPE)
        from matchvet.f14 import DecisionRepository

        real_replay = DecisionRepository.replay

        def replay_base(repository: DecisionRepository, digest: str) -> DecisionResult:
            if digest == base_record.digest:
                return base_decision
            return real_replay(repository, digest)

        monkeypatch.setattr(DecisionRepository, "replay", replay_base)
        target = model_value["inputs"]["target"]
        manifest = CandidateSupportManifest(
            cutoff_id=cutoff.cutoff_id,
            cutoff_digest=cutoff.digest,
            t10_profile_digest=profile.digest,
            t10_catalog_digest=DEFAULT_PREFERENCE_CATALOG.digest,
            f13_result_digest=model.digest,
            policy_digest=policy.digest,
            league=target["competition_key"],
            preference_supports=(),
            source_artifact_digests=(model.digest,),
            resolver_rule_digest=group_resolver_rule_digest(),
            comparison_rule_digest=comparison_rule_digest(),
        )
        joint = JointUncertaintySupport(
            cutoff_id=cutoff.cutoff_id,
            cutoff_digest=cutoff.digest,
            t10_profile_digest=profile.digest,
            t10_catalog_digest=DEFAULT_PREFERENCE_CATALOG.digest,
            f13_result_digest=model.digest,
            policy_digest=policy.digest,
            finalist_ids=(),
            draw_ids=(),
            raw_component_draws={},
            paired_regions=(),
            region_rule_digest="f" * 64,
            source_artifact_digests=(model.digest,),
            state=SupportState.UNKNOWN,
        )
        repository = CandidateInputSupportRepository(store)
        manifest_digest = repository.publish_support_manifest(manifest)
        joint_digest = repository.publish_joint_uncertainty(joint)

        result = repository.build_decision(base_record.digest, manifest_digest, joint_digest)
        result_value = result.to_dict()

        assert result_value["outcome"] == "AVOID MATCH"
        assert result_value["decision_reason"] == "PRIMARY_SELECTION_UNRESOLVED"
        assert result_value["unresolved_preference_ids"] == [preference.preference_id]
        lineage = cast(Mapping[str, object], result_value["lineage"])
        assert lineage["base_f14_result_digest"] == base_record.digest
        assert lineage["base_f14_input_digest"] == base_input_record.digest
        assert lineage["cutoff_id"] == cutoff.cutoff_id
        assert lineage["cutoff_digest"] == cutoff.digest
        assert lineage["f13_result_digest"] == model.digest
        assert lineage["profile_digest"] == profile.digest
        preference_digests = cast(Mapping[str, str], lineage["t10_preference_contract_digests"])
        assert (
            preference_digests[preference.preference_id]
            == hashlib.sha256(encode(preference.to_dict())).hexdigest()
        )
        result_meta = store.artifact_metadata(result.digest)
        assert result_meta is not None and result_meta.media_type == F14_SUPPORT_RESULT_MEDIA_TYPE
        result_input_digest = cast(str, result_value["input_bundle_digest"])
        input_meta = store.artifact_metadata(result_input_digest)
        assert input_meta is not None and input_meta.media_type == F14_SUPPORT_INPUT_MEDIA_TYPE
        input_value = json.loads(artifacts.read_artifact(result_input_digest))
        assert input_value["support_manifest_digest"] == manifest_digest
        assert input_value["joint_uncertainty_digest"] == joint_digest
        comparison_digest = cast(str, lineage["comparison_result_digest"])
        comparison_meta = store.artifact_metadata(comparison_digest)
        assert comparison_meta is not None
        assert comparison_meta.media_type == T15_COMPARISON_RESULT_MEDIA_TYPE
        manifest_meta = store.artifact_metadata(manifest_digest)
        joint_meta = store.artifact_metadata(joint_digest)
        assert manifest_meta is not None and manifest_meta.media_type == F13_SUPPORT_MEDIA_TYPE
        assert joint_meta is not None and joint_meta.media_type == T15_COMPARISON_MEDIA_TYPE

        decoy_manifest = replace(manifest, league=f"{target['competition_key']}-other")
        repository.publish_support_manifest(decoy_manifest)

        assert repository.replay(result.digest) == result


def _comparison_fixture(
    scores: dict[str, float],
    tie_metrics: dict[str, tuple[float, float, float, float]],
) -> tuple[
    tuple[FinalistCandidate, ...], JointUncertaintySupport, CandidateSupportManifest, PolicyVersion
]:
    weights = {component: 1.0 / len(SELECTION_COMPONENTS) for component in SELECTION_COMPONENTS}
    transforms = {component: TransformSpec("identity") for component in SELECTION_COMPONENTS}
    normalizers = {component: NormalizationSpec("identity") for component in SELECTION_COMPONENTS}
    config = SelectionStrengthConfig(weights, transforms, normalizers, version="unchanged-t15")
    policy = PolicyVersion("candidate-input-v2", selection_strength=config)
    finalists = tuple(
        FinalistCandidate(
            preference_id=preference_id,
            gate_status=GateSupportStatus.PASS,
            normalizers={
                component: NormalizationSpec("identity") for component in SELECTION_COMPONENTS
            },
            normalizer_reference_digests={
                component: "e" * 64 for component in SELECTION_COMPONENTS
            },
            uncertainty_width=tie_metrics[preference_id][0],
            data_quality=tie_metrics[preference_id][1],
            failure_risk=tie_metrics[preference_id][2],
            adversarial_materiality=None,
            historical_reliability=tie_metrics[preference_id][3],
        )
        for preference_id in scores
    )
    manifest = CandidateSupportManifest(
        cutoff_id="cutoff-exact",
        cutoff_digest="a" * 64,
        t10_profile_digest="b" * 64,
        t10_catalog_digest=DEFAULT_PREFERENCE_CATALOG.digest,
        f13_result_digest="c" * 64,
        policy_digest=policy.digest,
        league="premier_league",
        preference_supports=(),
        resolver_rule_digest=group_resolver_rule_digest(),
        comparison_rule_digest=comparison_rule_digest(),
    )
    region_rule_digest = "d" * 64
    finalists_by_id = {item.preference_id for item in finalists}
    ordered_ids = tuple(sorted(finalists_by_id))
    paired_regions = tuple(
        PairDifferenceSupport(
            left_preference_id=left,
            right_preference_id=right,
            lower=scores[left] - scores[right] - (0.01 if scores[left] == scores[right] else 0.0),
            upper=scores[left] - scores[right] + (0.01 if scores[left] == scores[right] else 0.0),
            state=SupportState.SUPPORTED,
            region_rule_digest=region_rule_digest,
        )
        for index, left in enumerate(ordered_ids)
        for right in ordered_ids[index + 1 :]
    )
    raw_draws = {
        preference_id: {"draw-1": {component: score for component in SELECTION_COMPONENTS}}
        for preference_id, score in scores.items()
    }
    joint = JointUncertaintySupport(
        cutoff_id=manifest.cutoff_id,
        cutoff_digest=manifest.cutoff_digest,
        t10_profile_digest=manifest.t10_profile_digest,
        t10_catalog_digest=manifest.t10_catalog_digest,
        f13_result_digest=manifest.f13_result_digest,
        policy_digest=manifest.policy_digest,
        finalist_ids=ordered_ids,
        draw_ids=("draw-1",),
        raw_component_draws=raw_draws,
        paired_regions=paired_regions,
        region_rule_digest=region_rule_digest,
        source_artifact_digests=("f" * 64,),
    )
    return finalists, joint, manifest, policy


def _legacy_result(
    preference_id: str,
    score: float,
    interval: tuple[float, float],
    uncertainty: float,
) -> PreferenceVettingResult:
    return PreferenceVettingResult(
        target_fixture_id="fixture-cycle",
        preference=DEFAULT_PREFERENCE_CATALOG.get(preference_id),
        status=CandidateStatus.RESEARCH_CANDIDATE,
        role=CandidateRole.NONE,
        gates=(),
        selection_strength=score,
        selection_strength_interval=interval,
        uncertainty_width=uncertainty,
        data_quality=1.0,
        failure_risk=0.0,
        historical_reliability=1.0,
    )


def test_joint_comparison_breaks_the_reproduced_three_finalist_comparator_cycle() -> None:
    policy = PolicyVersion(
        "legacy-cycle",
        user_preference_order=("match_winner_home", "match_winner_draw", "match_winner_away"),
    )
    home = _legacy_result("match_winner_home", 0.75, (0.5, 0.8), 3.0)
    draw = _legacy_result("match_winner_draw", 0.5, (0.3, 0.6), 2.0)
    away = _legacy_result("match_winner_away", 0.25, (0.1, 0.4), 1.0)

    assert _compare_results(home, draw, policy) > 0
    assert _compare_results(draw, away, policy) > 0
    assert _compare_results(away, home, policy) > 0

    finalists, joint, manifest, joint_policy = _comparison_fixture(
        {
            "match_winner_home": 0.75,
            "match_winner_draw": 0.5,
            "match_winner_away": 0.25,
        },
        {
            "match_winner_home": (3.0, 1.0, 0.0, 1.0),
            "match_winner_draw": (2.0, 1.0, 0.0, 1.0),
            "match_winner_away": (1.0, 1.0, 0.0, 1.0),
        },
    )
    comparison = compare_finalists(finalists, joint, manifest, joint_policy)

    assert comparison.state is ComparisonState.SUPPORTED
    assert comparison.maximal_set == ("match_winner_home",)
    assert comparison.primary_preference_id == "match_winner_home"


def test_joint_comparison_is_input_order_independent() -> None:
    scores = {
        "match_winner_home": 0.8,
        "match_winner_draw": 0.8,
        "match_winner_away": 0.3,
    }
    tie_metrics = {
        "match_winner_home": (0.3, 0.8, 0.2, 0.7),
        "match_winner_draw": (0.2, 0.8, 0.2, 0.7),
        "match_winner_away": (0.4, 0.7, 0.3, 0.6),
    }
    finalists, joint, manifest, policy = _comparison_fixture(scores, tie_metrics)
    expected = compare_finalists(finalists, joint, manifest, policy).to_dict()
    assert T15ComparisonResult.from_dict(expected).to_dict() == expected

    for candidate_order in permutations(finalists):
        result = compare_finalists(candidate_order, joint, manifest, policy)
        assert result.to_dict() == expected
    assert expected["primary_preference_id"] == "match_winner_draw"


def test_three_plus_finalists_use_maximal_set_before_existing_tie_breaks() -> None:
    scores = {
        "match_winner_home": 0.8,
        "match_winner_draw": 0.8,
        "match_winner_away": 0.7,
        "total_goals_over_1_5": 0.6,
    }
    tie_metrics = {
        "match_winner_home": (0.4, 0.9, 0.1, 0.8),
        "match_winner_draw": (0.2, 0.9, 0.1, 0.8),
        "match_winner_away": (0.1, 0.9, 0.1, 0.8),
        "total_goals_over_1_5": (0.1, 0.9, 0.1, 0.8),
    }
    finalists, joint, manifest, policy = _comparison_fixture(scores, tie_metrics)

    result = compare_finalists(finalists, joint, manifest, policy)

    assert result.state is ComparisonState.SUPPORTED
    assert result.maximal_set == ("match_winner_draw", "match_winner_home")
    assert result.primary_preference_id == "match_winner_draw"

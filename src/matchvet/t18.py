"""T18 offline chronological policy evaluation.

This module evaluates research-only Selection Policy candidates against frozen
historical information states.  It does not promote policies or alter Matchweek
vetting output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import cast

from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SettlementResult

T18_SCHEMA_VERSION = "matchvet.policy-evaluation.v1"
CHRONOLOGICAL_SPLIT = "CHRONOLOGICAL"
_PUSH_CAPABLE_PREFERENCE_IDS = frozenset(
    preference.preference_id
    for preference in DEFAULT_PREFERENCE_CATALOG.preferences
    if SettlementResult.PUSH in preference.possible_results
)
_PREFERENCE_RESULTS = {
    preference.preference_id: frozenset(result.value for result in preference.possible_results)
    for preference in DEFAULT_PREFERENCE_CATALOG.preferences
}


class EvaluationError(ValueError):
    """A T18 input violates chronology, cutoff fidelity, or schema rules."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{label} must be a non-empty string.")
    return value.strip()


def _utc(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{label} must be an ISO-8601 timestamp with a UTC offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise EvaluationError(
            f"{label} must be an ISO-8601 timestamp with a UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise EvaluationError(f"{label} must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _digest(value: str, label: str) -> str:
    selected = _text(value, label)
    if len(selected) != 64 or any(character not in "0123456789abcdef" for character in selected):
        raise EvaluationError(f"{label} must be a lowercase SHA-256 digest.")
    return selected


def _probability(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{label} must be a finite probability.")
    selected = float(value)
    if not math.isfinite(selected) or not 0.0 <= selected <= 1.0:
        raise EvaluationError(f"{label} must be between zero and one.")
    return selected


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items())})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


_PROHIBITED_POLICY_TOKENS = (
    "bookmaker",
    "odds",
    "profit",
    "stake",
    "staking",
    "target_selection_volume",
    "minimum_selection_volume",
    "maximum_selection_volume",
)


def _prohibited_paths(value: object, prefix: str = "") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            token = name.lower().replace("-", "_").replace(" ", "_")
            if any(prohibited in token for prohibited in _PROHIBITED_POLICY_TOKENS):
                found.append(path)
            found.extend(_prohibited_paths(item, path))
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            found.extend(_prohibited_paths(item, f"{prefix}[{index}]"))
    return tuple(sorted(set(found)))


@dataclass(frozen=True)
class ChronologicalPeriod:
    """A half-open UTC interval with an explicit evaluation purpose."""

    name: str
    start_utc: str
    end_utc: str

    def __post_init__(self) -> None:
        name = _text(self.name, "Period name").upper()
        start = _utc(self.start_utc, f"{name} start")
        end = _utc(self.end_utc, f"{name} end")
        if _instant(start) >= _instant(end):
            raise EvaluationError(f"{name} start must be before its end.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)

    def contains(self, timestamp: str) -> bool:
        selected = _instant(timestamp)
        return _instant(self.start_utc) <= selected < _instant(self.end_utc)

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "start_utc": self.start_utc, "end_utc": self.end_utc}


@dataclass(frozen=True)
class HistoricalEvaluation:
    """One frozen preference-level prediction and its later settlement."""

    match_id: str
    matchweek_id: str
    matchweek_start_utc: str
    kickoff_at_utc: str
    research_cutoff_at_utc: str
    prediction_created_at_utc: str
    outcome_known_at_utc: str
    league: str
    preference_id: str
    preference_family: str
    exact_line: str
    policy_version: str
    policy_digest: str
    model_version: str
    model_digest: str
    evidence_digest: str
    input_digest: str
    estimated_probability: float
    conservative_probability: float
    uncertainty_lower: float
    uncertainty_upper: float
    settlement: str
    recommendation: str
    correlation_group: str
    input_observed_at_utc: Mapping[str, str]
    membership_manifest: Mapping[str, object]
    membership_manifest_digest: str
    fixture_revision: Mapping[str, object]
    fixture_revision_digest: str
    training_data_end_utc: str
    model_fitted_at_utc: str
    calibration_digest: str
    baseline_digest: str
    outcome_use: str = "UNSEEN"
    selection_strength: float | None = None
    baseline_probability: float | None = None
    baseline_structural_trivial: bool | None = None
    gates: Mapping[str, str] = field(default_factory=dict)
    selection_components: Mapping[str, float] = field(default_factory=dict)
    structural_conditions: tuple[str, ...] = ()
    model_agreement: float | None = None
    uncertainty_width: float | None = None
    settlement_distribution: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "match_id",
            "matchweek_id",
            "league",
            "preference_id",
            "preference_family",
            "exact_line",
            "policy_version",
            "model_version",
            "correlation_group",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in (
            "policy_digest",
            "model_digest",
            "evidence_digest",
            "input_digest",
            "calibration_digest",
            "baseline_digest",
            "membership_manifest_digest",
            "fixture_revision_digest",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        for field_name in (
            "matchweek_start_utc",
            "kickoff_at_utc",
            "research_cutoff_at_utc",
            "prediction_created_at_utc",
            "outcome_known_at_utc",
            "training_data_end_utc",
            "model_fitted_at_utc",
        ):
            object.__setattr__(self, field_name, _utc(getattr(self, field_name), field_name))
        matchweek_start = _instant(self.matchweek_start_utc)
        cutoff = _instant(self.research_cutoff_at_utc)
        prediction = _instant(self.prediction_created_at_utc)
        kickoff = _instant(self.kickoff_at_utc)
        outcome_known = _instant(self.outcome_known_at_utc)
        training_data_end = _instant(self.training_data_end_utc)
        model_fitted = _instant(self.model_fitted_at_utc)
        if not matchweek_start <= cutoff < kickoff:
            raise EvaluationError(
                "Research Cutoff must follow the Matchweek start and precede kickoff."
            )
        if not cutoff <= prediction < kickoff:
            raise EvaluationError(
                "The frozen prediction must be created at cutoff and before kickoff."
            )
        if outcome_known < kickoff:
            raise EvaluationError("The settlement outcome cannot be known before kickoff.")
        if not training_data_end <= model_fitted <= prediction:
            raise EvaluationError(
                "Model fitting must follow its training-data boundary and precede prediction."
            )
        observed: dict[str, str] = {}
        for name, timestamp in self.input_observed_at_utc.items():
            input_name = _text(name, "Historical input name")
            canonical = _utc(timestamp, f"Historical input {input_name}")
            if _instant(canonical) > cutoff:
                raise EvaluationError(
                    f"Historical input {input_name} was observed after the Research Cutoff."
                )
            observed[input_name] = canonical
        if not observed:
            raise EvaluationError("Historical replay requires at least one cutoff-valid input.")
        if not {"membership_manifest", "fixture_revision"}.issubset(observed):
            raise EvaluationError(
                "Cutoff fidelity requires observed membership_manifest and fixture_revision inputs."
            )
        object.__setattr__(
            self, "input_observed_at_utc", MappingProxyType(dict(sorted(observed.items())))
        )
        membership_manifest = cast(Mapping[str, object], _freeze(self.membership_manifest))
        fixture_revision = cast(Mapping[str, object], _freeze(self.fixture_revision))
        if _sha256(membership_manifest) != self.membership_manifest_digest:
            raise EvaluationError("Membership Manifest digest does not match its frozen content.")
        if _sha256(fixture_revision) != self.fixture_revision_digest:
            raise EvaluationError("Fixture Revision digest does not match its frozen content.")
        if (
            fixture_revision.get("match_id") != self.match_id
            or fixture_revision.get("kickoff_at_utc") != self.kickoff_at_utc
        ):
            raise EvaluationError(
                "Fixture Revision identity or kickoff does not match the historical row."
            )
        revision_digests = membership_manifest.get("fixture_revision_digests")
        if (
            membership_manifest.get("matchweek_id") != self.matchweek_id
            or not isinstance(revision_digests, (tuple, list))
            or self.fixture_revision_digest not in revision_digests
        ):
            raise EvaluationError(
                "Membership Manifest does not control this Matchweek Fixture Revision."
            )
        object.__setattr__(self, "membership_manifest", membership_manifest)
        object.__setattr__(self, "fixture_revision", fixture_revision)
        estimated = _probability(self.estimated_probability, "Estimated Probability")
        conservative = _probability(self.conservative_probability, "Conservative Probability")
        lower = _probability(self.uncertainty_lower, "Uncertainty lower bound")
        upper = _probability(self.uncertainty_upper, "Uncertainty upper bound")
        if conservative > estimated:
            raise EvaluationError("Conservative Probability cannot exceed Estimated Probability.")
        if not lower <= estimated <= upper:
            raise EvaluationError("Probability uncertainty must contain Estimated Probability.")
        object.__setattr__(self, "estimated_probability", estimated)
        object.__setattr__(self, "conservative_probability", conservative)
        object.__setattr__(self, "uncertainty_lower", lower)
        object.__setattr__(self, "uncertainty_upper", upper)
        settlement = str(self.settlement).upper()
        if settlement not in {"WIN", "LOSS", "PUSH", "VOID"}:
            raise EvaluationError("Settlement must be WIN, LOSS, PUSH, or VOID.")
        possible_results = _PREFERENCE_RESULTS.get(self.preference_id)
        if possible_results is None:
            raise EvaluationError("Historical Evaluation references an unknown Betting Preference.")
        if settlement != "VOID" and settlement not in possible_results:
            raise EvaluationError(
                f"Betting Preference {self.preference_id} cannot settle {settlement}."
            )
        recommendation = str(self.recommendation).upper()
        if recommendation not in {"CANDIDATE", "PLAY", "REJECT", "AVOID"}:
            raise EvaluationError("Recommendation must be CANDIDATE, PLAY, REJECT, or AVOID.")
        outcome_use = str(self.outcome_use).upper()
        if outcome_use not in {"UNSEEN", "DEVELOPMENT", "VALIDATION", "INSPECTED"}:
            raise EvaluationError("Outcome use must describe its chronological inspection state.")
        object.__setattr__(self, "settlement", settlement)
        object.__setattr__(self, "recommendation", recommendation)
        object.__setattr__(self, "outcome_use", outcome_use)
        if (
            self.preference_id in _PUSH_CAPABLE_PREFERENCE_IDS
            and self.settlement_distribution is None
        ):
            raise EvaluationError(
                "A PUSH-capable preference requires its frozen Settlement Distribution."
            )
        if self.settlement_distribution is not None:
            raw_distribution = self.settlement_distribution
            if set(raw_distribution) != {"WIN", "PUSH", "LOSS"}:
                raise EvaluationError(
                    "Settlement Distribution must contain exactly WIN, PUSH, and LOSS."
                )
            distribution = {
                result: _probability(raw_distribution[result], f"{result} probability")
                for result in ("LOSS", "PUSH", "WIN")
            }
            if not math.isclose(sum(distribution.values()), 1.0, abs_tol=1e-12):
                raise EvaluationError("Settlement Distribution probabilities must sum to one.")
            if not math.isclose(distribution["WIN"], estimated, abs_tol=1e-12):
                raise EvaluationError(
                    "Estimated Probability must equal Settlement Distribution WIN."
                )
            object.__setattr__(
                self,
                "settlement_distribution",
                MappingProxyType(distribution),
            )
        if self.selection_strength is not None:
            strength = float(self.selection_strength)
            if not math.isfinite(strength):
                raise EvaluationError("Selection Strength must be finite.")
            object.__setattr__(self, "selection_strength", strength)
        if self.baseline_probability is not None:
            object.__setattr__(
                self,
                "baseline_probability",
                _probability(self.baseline_probability, "Historical Baseline"),
            )
        if self.baseline_structural_trivial is not None and not isinstance(
            self.baseline_structural_trivial, bool
        ):
            raise EvaluationError("Structural triviality must be boolean or null.")
        for field_name in ("model_agreement", "uncertainty_width"):
            value = getattr(self, field_name)
            if value is not None:
                selected = float(value)
                if not math.isfinite(selected) or selected < 0.0:
                    raise EvaluationError(f"{field_name} must be a finite non-negative number.")
                object.__setattr__(self, field_name, selected)
        object.__setattr__(self, "gates", cast(Mapping[str, str], _freeze(self.gates)))
        object.__setattr__(
            self,
            "selection_components",
            cast(Mapping[str, float], _freeze(self.selection_components)),
        )
        object.__setattr__(self, "structural_conditions", tuple(sorted(self.structural_conditions)))


@dataclass(frozen=True)
class CandidatePolicy:
    """A research-only candidate whose lifecycle times are independently auditable."""

    version: str
    digest: str
    development_data_end_utc: str
    frozen_at_utc: str
    parameters: Mapping[str, object]
    fold_parameters: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    inspected_evaluation_digests: tuple[str, ...] = ()
    status: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, "Candidate policy version"))
        object.__setattr__(self, "digest", _digest(self.digest, "Candidate policy digest"))
        object.__setattr__(
            self,
            "development_data_end_utc",
            _utc(self.development_data_end_utc, "Candidate development-data end"),
        )
        object.__setattr__(self, "frozen_at_utc", _utc(self.frozen_at_utc, "Candidate freeze time"))
        prohibited = _prohibited_paths(self.parameters)
        if prohibited:
            raise EvaluationError(
                "Candidate policy contains prohibited odds/profit/staking/volume inputs: "
                + ", ".join(prohibited)
            )
        object.__setattr__(self, "parameters", cast(Mapping[str, object], _freeze(self.parameters)))
        fold_parameters: dict[str, Mapping[str, object]] = {}
        for fold_id, parameters in self.fold_parameters.items():
            selected_fold_id = _text(fold_id, "Candidate fold ID")
            prohibited_fold = _prohibited_paths(parameters)
            if prohibited_fold:
                raise EvaluationError(
                    "Candidate fold parameters contain prohibited inputs: "
                    + ", ".join(prohibited_fold)
                )
            fold_parameters[selected_fold_id] = cast(Mapping[str, object], _freeze(parameters))
        object.__setattr__(
            self,
            "fold_parameters",
            MappingProxyType(dict(sorted(fold_parameters.items()))),
        )
        if str(self.status).upper() != "RESEARCH_ONLY":
            raise EvaluationError("T18 evaluates RESEARCH_ONLY Candidate Policies only.")
        object.__setattr__(self, "status", "RESEARCH_ONLY")
        inspected = tuple(
            sorted(
                _digest(item, "Inspected evaluation digest")
                for item in self.inspected_evaluation_digests
            )
        )
        object.__setattr__(self, "inspected_evaluation_digests", inspected)

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            _jsonable(
                {
                    "development_data_end_utc": self.development_data_end_utc,
                    "digest": self.digest,
                    "frozen_at_utc": self.frozen_at_utc,
                    "fold_parameters": self.fold_parameters,
                    "inspected_evaluation_digests": self.inspected_evaluation_digests,
                    "parameters": self.parameters,
                    "status": self.status,
                    "version": self.version,
                }
            ),
        )


@dataclass(frozen=True)
class EvaluationCriterion:
    """One predeclared acceptance comparison; T18 supplies no defaults."""

    metric: str
    operator: str
    threshold: float
    minimum_effective_sample: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", _text(self.metric, "Criterion metric"))
        if self.operator not in {"<", "<=", ">", ">=", "=="}:
            raise EvaluationError("Criterion operator must be <, <=, >, >=, or ==.")
        threshold = float(self.threshold)
        if not math.isfinite(threshold):
            raise EvaluationError("Criterion threshold must be finite.")
        object.__setattr__(self, "threshold", threshold)
        if self.minimum_effective_sample is not None and (
            isinstance(self.minimum_effective_sample, bool)
            or not isinstance(self.minimum_effective_sample, int)
            or self.minimum_effective_sample < 1
        ):
            raise EvaluationError("Criterion minimum effective sample must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "minimum_effective_sample": self.minimum_effective_sample,
            "operator": self.operator,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class EvaluationConfig:
    """Predeclared split and deterministic rolling-origin controls."""

    development: ChronologicalPeriod
    validation: ChronologicalPeriod
    evaluation: ChronologicalPeriod
    minimum_development_matchweeks: int
    rolling_validation_matchweeks: int
    rolling_step_matchweeks: int
    seed: int
    split_method: str = CHRONOLOGICAL_SPLIT
    calibration_bin_edges: tuple[float, ...] = (0.0, 1.0)
    subgroup_minimum_effective_samples: Mapping[str, int] = field(default_factory=dict)
    selection_metric: str = "probability_quality.brier_score"
    selection_direction: str = "MINIMIZE"
    evaluation_minimum_recommendations: int | None = None
    uncertainty_nominal_coverage: float | None = None
    criteria: tuple[EvaluationCriterion, ...] = ()

    def __post_init__(self) -> None:
        if str(self.split_method).upper() != CHRONOLOGICAL_SPLIT:
            raise EvaluationError(
                "T18 accepts chronological splitting only; random splits are invalid."
            )
        object.__setattr__(self, "split_method", CHRONOLOGICAL_SPLIT)
        for field_name in (
            "minimum_development_matchweeks",
            "rolling_validation_matchweeks",
            "rolling_step_matchweeks",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvaluationError(f"{field_name} must be a positive integer.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise EvaluationError("Evaluation seed must be a non-negative integer.")
        edges = _validate_calibration_edges(self.calibration_bin_edges)
        object.__setattr__(self, "calibration_bin_edges", edges)
        minimums = dict(sorted(self.subgroup_minimum_effective_samples.items()))
        for name, value in minimums.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvaluationError(
                    f"Subgroup minimum effective sample {name!r} must be positive."
                )
        object.__setattr__(self, "subgroup_minimum_effective_samples", MappingProxyType(minimums))
        object.__setattr__(
            self, "selection_metric", _text(self.selection_metric, "Selection metric")
        )
        direction = str(self.selection_direction).upper()
        if direction not in {"MINIMIZE", "MAXIMIZE"}:
            raise EvaluationError("Selection direction must be MINIMIZE or MAXIMIZE.")
        object.__setattr__(self, "selection_direction", direction)
        minimum = self.evaluation_minimum_recommendations
        if minimum is not None and (
            isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1
        ):
            raise EvaluationError("Evaluation minimum recommendations must be positive or null.")
        object.__setattr__(self, "criteria", tuple(self.criteria))
        if self.uncertainty_nominal_coverage is not None:
            object.__setattr__(
                self,
                "uncertainty_nominal_coverage",
                _probability(
                    self.uncertainty_nominal_coverage,
                    "Uncertainty nominal coverage",
                ),
            )

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            _jsonable(
                {
                    "calibration_bin_edges": self.calibration_bin_edges,
                    "criteria": tuple(item.to_dict() for item in self.criteria),
                    "development": self.development.to_dict(),
                    "evaluation": self.evaluation.to_dict(),
                    "evaluation_minimum_recommendations": (self.evaluation_minimum_recommendations),
                    "minimum_development_matchweeks": self.minimum_development_matchweeks,
                    "rolling_step_matchweeks": self.rolling_step_matchweeks,
                    "rolling_validation_matchweeks": self.rolling_validation_matchweeks,
                    "seed": self.seed,
                    "selection_direction": self.selection_direction,
                    "selection_metric": self.selection_metric,
                    "split_method": self.split_method,
                    "subgroup_minimum_effective_samples": (self.subgroup_minimum_effective_samples),
                    "uncertainty_nominal_coverage": self.uncertainty_nominal_coverage,
                    "validation": self.validation.to_dict(),
                }
            ),
        )

    @property
    def digest(self) -> str:
        return _sha256(self.to_dict())


@dataclass(frozen=True)
class ChronologicalFold:
    """One deterministic expanding-window fold over complete Matchweeks."""

    fold_id: str
    development_start_utc: str
    development_end_utc: str
    validation_start_utc: str
    validation_end_utc: str
    evaluation_start_utc: str | None
    evaluation_end_utc: str | None
    development_matchweek_ids: tuple[str, ...]
    validation_matchweek_ids: tuple[str, ...]
    evaluation_matchweek_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationContract:
    """Validated split assignment with explicit rows outside declared periods."""

    config: EvaluationConfig
    excluded_match_ids: tuple[str, ...]
    exclusions: tuple[Mapping[str, str], ...]
    evaluation_window_digest: str

    def period_for(self, observation: HistoricalEvaluation) -> str | None:
        timestamp = observation.matchweek_start_utc
        for period in (self.config.development, self.config.validation, self.config.evaluation):
            if period.contains(timestamp):
                return period.name
        return None


@dataclass(frozen=True)
class EvaluationMetrics:
    """Schema-stable metrics for one policy and chronological slice."""

    match_count: int
    target_count: int
    recommendation_count: int
    effective_samples: Mapping[str, int]
    probability_quality: Mapping[str, object]
    calibration_bins: tuple[Mapping[str, object], ...]
    settlement_metrics: Mapping[str, object]
    subgroup_metrics: tuple[Mapping[str, object], ...]
    non_triviality: Mapping[str, object]
    ranking_diagnostics: Mapping[str, object]
    gate_diagnostics: Mapping[str, object]
    stability_diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        for field_name in (
            "effective_samples",
            "probability_quality",
            "settlement_metrics",
            "non_triviality",
            "ranking_diagnostics",
            "gate_diagnostics",
            "stability_diagnostics",
        ):
            object.__setattr__(
                self, field_name, cast(Mapping[str, object], _freeze(getattr(self, field_name)))
            )
        object.__setattr__(
            self,
            "calibration_bins",
            tuple(cast(Mapping[str, object], _freeze(item)) for item in self.calibration_bins),
        )
        object.__setattr__(
            self,
            "subgroup_metrics",
            tuple(cast(Mapping[str, object], _freeze(item)) for item in self.subgroup_metrics),
        )

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            _jsonable(
                {
                    "calibration_bins": self.calibration_bins,
                    "effective_samples": self.effective_samples,
                    "gate_diagnostics": self.gate_diagnostics,
                    "match_count": self.match_count,
                    "non_triviality": self.non_triviality,
                    "probability_quality": self.probability_quality,
                    "ranking_diagnostics": self.ranking_diagnostics,
                    "recommendation_count": self.recommendation_count,
                    "settlement_metrics": self.settlement_metrics,
                    "stability_diagnostics": self.stability_diagnostics,
                    "subgroup_metrics": self.subgroup_metrics,
                    "target_count": self.target_count,
                }
            ),
        )


def _validate_period_order(config: EvaluationConfig) -> None:
    development_end = _instant(config.development.end_utc)
    validation_start = _instant(config.validation.start_utc)
    validation_end = _instant(config.validation.end_utc)
    evaluation_start = _instant(config.evaluation.start_utc)
    if development_end > validation_start or validation_end > evaluation_start:
        raise EvaluationError(
            "Development, Validation, and Final Evaluation periods must not overlap."
        )


def _evaluation_window_digest(
    observations: Sequence[HistoricalEvaluation], config: EvaluationConfig
) -> str:
    del observations
    return _sha256(
        {
            "purpose": "UNTOUCHED_FINAL_EVALUATION_WINDOW",
            "period": config.evaluation.to_dict(),
        }
    )


def _validate_matchweek_boundaries(
    observations: Sequence[HistoricalEvaluation],
) -> None:
    boundaries: dict[str, tuple[str, str, str]] = {}
    for observation in observations:
        current = (
            observation.matchweek_start_utc,
            observation.research_cutoff_at_utc,
            observation.membership_manifest_digest,
        )
        previous = boundaries.setdefault(observation.matchweek_id, current)
        if previous[0] != current[0]:
            raise EvaluationError(
                f"Matchweek boundary differs across rows for {observation.matchweek_id}."
            )
        if previous[1] != current[1]:
            raise EvaluationError(
                f"Research Cutoff differs across rows for {observation.matchweek_id}."
            )
        if previous[2] != current[2]:
            raise EvaluationError(
                f"Membership Manifest differs across rows for {observation.matchweek_id}."
            )


def validate_evaluation_contract(
    observations: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
) -> EvaluationContract:
    """Fail closed when a historical split is not genuinely chronological."""

    _validate_period_order(config)
    _validate_matchweek_boundaries(observations)
    if not candidates:
        raise EvaluationError("At least one Candidate Policy is required.")
    candidate_digests = {candidate.digest for candidate in candidates}
    if len(candidate_digests) != len(candidates):
        raise EvaluationError("Candidate Policy digests must be unique.")
    for candidate in candidates:
        if _instant(candidate.development_data_end_utc) > _instant(config.development.end_utc):
            raise EvaluationError(
                f"Candidate {candidate.version} uses outcomes beyond the Development Period."
            )
        if _instant(candidate.frozen_at_utc) > _instant(config.evaluation.start_utc):
            raise EvaluationError(
                f"Candidate {candidate.version} was not frozen before Final Evaluation."
            )
        if _instant(candidate.frozen_at_utc) < _instant(config.validation.end_utc):
            raise EvaluationError(f"Candidate {candidate.version} froze before Validation ended.")
    candidate_by_digest = {candidate.digest: candidate for candidate in candidates}
    window_digest = _evaluation_window_digest(observations, config)
    if any(window_digest in candidate.inspected_evaluation_digests for candidate in candidates):
        raise EvaluationError(
            "The Final Evaluation window was already inspected and is no longer unseen."
        )
    exclusions: dict[tuple[str, str], dict[str, str]] = {}
    for observation in observations:
        periods = tuple(
            period
            for period in (config.development, config.validation, config.evaluation)
            if period.contains(observation.matchweek_start_utc)
        )
        if not periods:
            exclusions[(observation.match_id, observation.matchweek_id)] = {
                "match_id": observation.match_id,
                "matchweek_id": observation.matchweek_id,
                "reason": "OUTSIDE_DECLARED_PERIODS",
            }
            continue
        if len(periods) != 1:
            raise EvaluationError("A Historical Evaluation belongs to overlapping periods.")
        if observation.policy_digest not in candidate_digests:
            raise EvaluationError(
                "Historical Evaluation references an undeclared Candidate Policy."
            )
        candidate = candidate_by_digest[observation.policy_digest]
        if observation.policy_version != candidate.version:
            raise EvaluationError(
                "Historical Evaluation policy version does not match its Candidate Policy digest."
            )
        if periods[0].name == config.development.name and _instant(
            observation.outcome_known_at_utc
        ) > _instant(candidate.development_data_end_utc):
            raise EvaluationError(
                "A Development outcome was unavailable at the Candidate Policy data cutoff."
            )
        if periods[0].name == config.validation.name and _instant(
            observation.outcome_known_at_utc
        ) > _instant(candidate.frozen_at_utc):
            raise EvaluationError(
                "A Validation outcome was unavailable when the Candidate Policy was frozen."
            )
        if periods[0].name == config.evaluation.name and observation.outcome_use != "UNSEEN":
            raise EvaluationError("An inspected Final Evaluation row is no longer unseen.")
    ordered_exclusions = tuple(exclusions[key] for key in sorted(exclusions))
    return EvaluationContract(
        config,
        tuple(item["match_id"] for item in ordered_exclusions),
        ordered_exclusions,
        window_digest,
    )


def generate_rolling_origin_folds(
    observations: Sequence[HistoricalEvaluation], config: EvaluationConfig
) -> tuple[ChronologicalFold, ...]:
    """Build expanding-window folds from complete Development Matchweeks."""

    _validate_period_order(config)
    _validate_matchweek_boundaries(observations)
    starts_by_matchweek = {
        observation.matchweek_id: observation.matchweek_start_utc for observation in observations
    }
    development_matchweeks = sorted(
        (
            (start, matchweek_id)
            for matchweek_id, start in starts_by_matchweek.items()
            if config.development.contains(start)
        ),
        key=lambda item: (item[0], item[1]),
    )
    folds: list[ChronologicalFold] = []
    development_count = config.minimum_development_matchweeks
    validation_count = config.rolling_validation_matchweeks
    while development_count + validation_count <= len(development_matchweeks):
        development_rows = development_matchweeks[:development_count]
        validation_rows = development_matchweeks[
            development_count : development_count + validation_count
        ]
        development_start = development_rows[0][0]
        validation_start = validation_rows[0][0]
        validation_end_index = development_count + validation_count
        validation_end = (
            development_matchweeks[validation_end_index][0]
            if validation_end_index < len(development_matchweeks)
            else config.development.end_utc
        )
        payload = {
            "development": tuple(row[1] for row in development_rows),
            "validation": tuple(row[1] for row in validation_rows),
            "seed": config.seed,
        }
        folds.append(
            ChronologicalFold(
                fold_id=f"fold-{len(folds) + 1:03d}-{_sha256(payload)[:12]}",
                development_start_utc=development_start,
                development_end_utc=validation_start,
                validation_start_utc=validation_start,
                validation_end_utc=validation_end,
                evaluation_start_utc=None,
                evaluation_end_utc=None,
                development_matchweek_ids=tuple(row[1] for row in development_rows),
                validation_matchweek_ids=tuple(row[1] for row in validation_rows),
            )
        )
        development_count += config.rolling_step_matchweeks
    return tuple(folds)


def _binary_rows(
    observations: Sequence[HistoricalEvaluation],
) -> tuple[HistoricalEvaluation, ...]:
    return tuple(item for item in observations if item.settlement in {"WIN", "LOSS"})


def _scored_rows(
    observations: Sequence[HistoricalEvaluation],
) -> tuple[HistoricalEvaluation, ...]:
    return tuple(item for item in observations if item.settlement != "VOID")


def _settlement_probabilities(observation: HistoricalEvaluation) -> dict[str, float]:
    if observation.settlement_distribution is not None:
        return dict(observation.settlement_distribution)
    return {
        "LOSS": 1.0 - observation.estimated_probability,
        "PUSH": 0.0,
        "WIN": observation.estimated_probability,
    }


def _selected_rows(
    observations: Sequence[HistoricalEvaluation],
) -> tuple[HistoricalEvaluation, ...]:
    return tuple(item for item in observations if item.recommendation in {"PLAY", "CANDIDATE"})


def _outcome(observation: HistoricalEvaluation) -> float:
    return 1.0 if observation.settlement == "WIN" else 0.0


def _class_outcome(observation: HistoricalEvaluation, result: str) -> float:
    return 1.0 if observation.settlement == result else 0.0


def _class_outcome_value(
    result: str,
) -> Callable[[HistoricalEvaluation], float]:
    return lambda observation: _class_outcome(observation, result)


def _class_probability_value(
    result: str,
) -> Callable[[HistoricalEvaluation], float]:
    return lambda observation: _settlement_probabilities(observation)[result]


def _settlement_brier(observation: HistoricalEvaluation) -> float:
    probabilities = _settlement_probabilities(observation)
    return (
        sum(
            (probabilities[result] - _class_outcome(observation, result)) ** 2
            for result in ("LOSS", "PUSH", "WIN")
        )
        / 2.0
    )


def _settlement_log_loss(observation: HistoricalEvaluation) -> float:
    epsilon = 1e-15
    return -math.log(max(epsilon, _settlement_probabilities(observation)[observation.settlement]))


def _match_cluster_mean(
    observations: Sequence[HistoricalEvaluation],
    value: Callable[[HistoricalEvaluation], float | None],
) -> float | None:
    by_match: dict[str, list[float]] = {}
    for observation in observations:
        selected = value(observation)
        if selected is None:
            continue
        by_match.setdefault(observation.match_id, []).append(float(selected))
    if not by_match:
        return None
    match_means = [sum(values) / len(values) for values in by_match.values()]
    return sum(match_means) / len(match_means)


def _uncertainty_coverage(
    observations: Sequence[HistoricalEvaluation],
    edges: Sequence[float],
    nominal_coverage: float | None,
) -> dict[str, object]:
    if nominal_coverage is None:
        return {
            "bins": (),
            "coverage_rate": None,
            "covered_bin_count": 0,
            "eligible_bin_count": 0,
            "nominal_coverage": None,
            "status": "INCONCLUSIVE",
        }
    nominal = _probability(nominal_coverage, "Uncertainty nominal coverage")
    scored = _scored_rows(observations)
    bins: list[dict[str, object]] = []
    for index, (start, end) in enumerate(pairwise(edges)):
        is_last = index == len(edges) - 2
        rows = tuple(
            item
            for item in scored
            if start <= item.estimated_probability
            and (item.estimated_probability <= end if is_last else item.estimated_probability < end)
        )
        if not rows:
            continue
        observed = _match_cluster_mean(rows, _outcome)
        lower = _match_cluster_mean(rows, lambda item: item.uncertainty_lower)
        upper = _match_cluster_mean(rows, lambda item: item.uncertainty_upper)
        assert observed is not None and lower is not None and upper is not None
        bins.append(
            {
                "covered": lower <= observed <= upper,
                "end": end,
                "interval_lower": lower,
                "interval_upper": upper,
                "match_clusters": len({item.match_id for item in rows}),
                "observed_success_rate": observed,
                "start": start,
            }
        )
    covered = sum(item["covered"] is True for item in bins)
    return {
        "bins": tuple(bins),
        "coverage_rate": covered / len(bins) if bins else None,
        "covered_bin_count": covered,
        "eligible_bin_count": len(bins),
        "nominal_coverage": nominal,
        "status": "AVAILABLE" if bins else "INCONCLUSIVE",
    }


def _probability_quality(
    observations: Sequence[HistoricalEvaluation],
    edges: Sequence[float] = (0.0, 1.0),
    nominal_coverage: float | None = None,
) -> dict[str, object]:
    scored = _scored_rows(observations)
    binary = _binary_rows(observations)
    void_count = sum(item.settlement == "VOID" for item in observations)
    if not scored:
        return {
            "binary_preference_rows": 0,
            "brier_score": None,
            "calibration_gap": None,
            "conservative_probability_coverage": {
                "covered": None,
                "margin": None,
                "mean_conservative_probability": None,
                "observed_success_rate": None,
            },
            "log_loss": None,
            "mean_predicted_probability": None,
            "observed_vs_predicted": {
                result: {"observed_rate": None, "predicted_probability": None}
                for result in ("LOSS", "PUSH", "WIN")
            },
            "observed_success_rate": None,
            "preference_level_brier_score": None,
            "preference_level_log_loss": None,
            "scored_preference_rows": 0,
            "aggregate_uncertainty_alignment": {
                "covered": None,
                "interval_lower": None,
                "interval_upper": None,
                "observed_success_rate": None,
            },
            "uncertainty_interval_coverage": _uncertainty_coverage(
                observations, edges, nominal_coverage
            ),
            "void_rows_excluded": void_count,
        }
    predicted = _match_cluster_mean(scored, lambda item: item.estimated_probability)
    observed = _match_cluster_mean(scored, _outcome)
    brier = _match_cluster_mean(scored, _settlement_brier)
    log_loss = _match_cluster_mean(scored, _settlement_log_loss)
    conservative = _match_cluster_mean(scored, lambda item: item.conservative_probability)
    interval_lower = _match_cluster_mean(scored, lambda item: item.uncertainty_lower)
    interval_upper = _match_cluster_mean(scored, lambda item: item.uncertainty_upper)
    assert predicted is not None
    assert observed is not None
    assert conservative is not None
    assert interval_lower is not None
    assert interval_upper is not None
    observed_vs_predicted: dict[str, dict[str, float | None]] = {}
    for result in ("LOSS", "PUSH", "WIN"):
        observed_vs_predicted[result] = {
            "observed_rate": _match_cluster_mean(scored, _class_outcome_value(result)),
            "predicted_probability": _match_cluster_mean(scored, _class_probability_value(result)),
        }
    return {
        "binary_preference_rows": len(binary),
        "brier_score": brier,
        "calibration_gap": abs(predicted - observed),
        "conservative_probability_coverage": {
            "covered": observed >= conservative,
            "margin": observed - conservative,
            "mean_conservative_probability": conservative,
            "observed_success_rate": observed,
        },
        "log_loss": log_loss,
        "mean_predicted_probability": predicted,
        "observed_vs_predicted": observed_vs_predicted,
        "observed_success_rate": observed,
        "preference_level_brier_score": sum(_settlement_brier(item) for item in scored)
        / len(scored),
        "preference_level_log_loss": sum(_settlement_log_loss(item) for item in scored)
        / len(scored),
        "scored_preference_rows": len(scored),
        "aggregate_uncertainty_alignment": {
            "covered": interval_lower <= observed <= interval_upper,
            "interval_lower": interval_lower,
            "interval_upper": interval_upper,
            "observed_success_rate": observed,
        },
        "uncertainty_interval_coverage": _uncertainty_coverage(
            observations, edges, nominal_coverage
        ),
        "void_rows_excluded": void_count,
    }


def _validate_calibration_edges(edges: Sequence[float]) -> tuple[float, ...]:
    selected = tuple(float(item) for item in edges)
    if (
        len(selected) < 2
        or selected[0] != 0.0
        or selected[-1] != 1.0
        or any(not math.isfinite(item) for item in selected)
        or any(left >= right for left, right in pairwise(selected))
    ):
        raise EvaluationError("Calibration bin edges must increase strictly from zero through one.")
    return selected


def _calibration_bins(
    observations: Sequence[HistoricalEvaluation], edges: Sequence[float]
) -> tuple[dict[str, object], ...]:
    scored = _scored_rows(observations)
    bins: list[dict[str, object]] = []
    for index, (start, end) in enumerate(pairwise(edges)):
        is_last = index == len(edges) - 2
        rows = tuple(
            item
            for item in scored
            if start <= item.estimated_probability
            and (item.estimated_probability <= end if is_last else item.estimated_probability < end)
        )
        if not rows:
            continue
        bins.append(
            {
                "end": end,
                "match_clusters": len({item.match_id for item in rows}),
                "mean_predicted_probability": _match_cluster_mean(
                    rows, lambda item: item.estimated_probability
                ),
                "observed_success_rate": _match_cluster_mean(rows, _outcome),
                "preference_rows": len(rows),
                "start": start,
            }
        )
    return tuple(bins)


def _settlement_metrics(
    observations: Sequence[HistoricalEvaluation],
) -> dict[str, object]:
    selected = _selected_rows(observations)
    selected_matches = {item.match_id for item in selected}
    all_matches = {item.match_id for item in observations}
    terminal = tuple(item for item in selected if item.settlement in {"WIN", "LOSS"})
    losses = tuple(item for item in terminal if item.settlement == "LOSS")
    false_positive_rate = _match_cluster_mean(
        terminal, lambda item: 1.0 if item.settlement == "LOSS" else 0.0
    )
    avoided_matches = {
        item.match_id
        for item in observations
        if item.recommendation == "AVOID" and item.match_id not in selected_matches
    }
    avoided_rows = tuple(item for item in observations if item.recommendation == "AVOID")
    match_count = len(all_matches)
    return {
        "avoid_match_count": len(avoided_matches),
        "avoid_rate": len(avoided_matches) / match_count if match_count else None,
        "avoid_settlement_counts": {
            result: sum(item.settlement == result for item in avoided_rows)
            for result in ("LOSS", "PUSH", "VOID", "WIN")
        },
        "avoid_settlements_credited_as_success": False,
        "false_positive_count": len(losses),
        "false_positive_rate": false_positive_rate,
        "loss_count": len(losses),
        "negative_settlement_rate": false_positive_rate,
        "push_count": sum(item.settlement == "PUSH" for item in selected),
        "recommendation_count": len(selected),
        "recommendation_match_count": len(selected_matches),
        "recommendation_rate": len(selected_matches) / match_count if match_count else None,
        "void_count": sum(item.settlement == "VOID" for item in selected),
        "win_count": sum(item.settlement == "WIN" for item in selected),
    }


def _subgroup_rows(
    observations: Sequence[HistoricalEvaluation],
) -> dict[tuple[str, str], tuple[HistoricalEvaluation, ...]]:
    grouped: dict[tuple[str, str], list[HistoricalEvaluation]] = {}
    for observation in observations:
        values = (
            ("league", observation.league),
            ("preference_family", observation.preference_family),
            ("exact_line", f"{observation.preference_family} | {observation.exact_line}"),
            ("time_period", observation.matchweek_id),
        )
        for key in values:
            grouped.setdefault(key, []).append(observation)
        for condition in observation.structural_conditions:
            grouped.setdefault(("structural_condition", condition), []).append(observation)
    return {key: tuple(value) for key, value in grouped.items()}


def _subgroup_metrics(
    observations: Sequence[HistoricalEvaluation],
    minimums: Mapping[str, int],
    edges: Sequence[float],
    nominal_coverage: float | None,
) -> tuple[dict[str, object], ...]:
    for dimension, minimum_value in minimums.items():
        if dimension not in {
            "league",
            "preference_family",
            "exact_line",
            "time_period",
            "structural_condition",
        }:
            raise EvaluationError(f"Unknown subgroup sample rule {dimension!r}.")
        if (
            isinstance(minimum_value, bool)
            or not isinstance(minimum_value, int)
            or minimum_value < 1
        ):
            raise EvaluationError("Subgroup minimum effective samples must be positive integers.")
    grouped = _subgroup_rows(observations)
    aggregate_quality = _probability_quality(observations, edges, nominal_coverage)
    family_quality = {
        subgroup_value: _probability_quality(rows, edges, nominal_coverage)
        for (dimension, subgroup_value), rows in grouped.items()
        if dimension == "preference_family"
    }
    results: list[dict[str, object]] = []
    for (dimension, subgroup_value), rows in sorted(grouped.items()):
        effective_sample = len({item.match_id for item in _scored_rows(rows)})
        minimum = minimums.get(dimension)
        sufficient = minimum is not None and effective_sample >= minimum
        borrowed_from: str | None = None
        borrowed_quality: dict[str, object] | None = None
        if not sufficient:
            if dimension == "exact_line":
                family = rows[0].preference_family
                borrowed_from = f"preference_family:{family}"
                borrowed_quality = family_quality[family]
            else:
                borrowed_from = "aggregate"
                borrowed_quality = aggregate_quality
        results.append(
            {
                "borrowed_from": borrowed_from,
                "borrowed_probability_quality": borrowed_quality,
                "dimension": dimension,
                "effective_sample": effective_sample,
                "minimum_effective_sample": minimum,
                "probability_quality": _probability_quality(rows, edges, nominal_coverage),
                "sample_status": "SUFFICIENT" if sufficient else "INCONCLUSIVE",
                "settlement_metrics": _settlement_metrics(rows),
                "value": subgroup_value,
            }
        )
    return tuple(results)


def _non_triviality(
    observations: Sequence[HistoricalEvaluation],
) -> dict[str, object]:
    selected = tuple(
        item
        for item in _selected_rows(observations)
        if item.baseline_probability is not None and item.settlement in {"WIN", "LOSS"}
    )
    baseline = _match_cluster_mean(selected, lambda item: item.baseline_probability)
    observed = _match_cluster_mean(selected, _outcome)
    return {
        "baseline_success_rate": baseline,
        "base_rate_dominated_win_count": sum(
            item.settlement == "WIN" and item.baseline_structural_trivial is True
            for item in selected
        ),
        "g4_rejected_structurally_trivial_count": sum(
            item.baseline_structural_trivial is True
            and str(item.gates.get("G4", "")).upper() == "FAIL"
            for item in observations
        ),
        "observed_lift_over_baseline": (
            observed - baseline if observed is not None and baseline is not None else None
        ),
        "selected_structurally_trivial_count": sum(
            item.baseline_structural_trivial is True for item in selected
        ),
        "selected_success_rate": observed,
        "selection_count_with_baseline": len(selected),
    }


def _gate_survivor(observation: HistoricalEvaluation) -> bool:
    return bool(observation.gates) and all(
        str(status).upper() == "PASS" for status in observation.gates.values()
    )


def _ranking_diagnostics(
    observations: Sequence[HistoricalEvaluation],
) -> dict[str, object]:
    by_match: dict[str, list[HistoricalEvaluation]] = {}
    for observation in observations:
        if (
            _gate_survivor(observation)
            and observation.selection_strength is not None
            and observation.settlement in {"WIN", "LOSS"}
        ):
            by_match.setdefault(observation.match_id, []).append(observation)
    concordant = 0
    discordant = 0
    eligible_matches = 0
    for rows in by_match.values():
        if len(rows) < 2:
            continue
        match_had_pair = False
        for left_index, left in enumerate(rows):
            for right in rows[left_index + 1 :]:
                if (
                    left.selection_strength == right.selection_strength
                    or left.settlement == right.settlement
                ):
                    continue
                match_had_pair = True
                higher = (
                    left
                    if cast(float, left.selection_strength) > cast(float, right.selection_strength)
                    else right
                )
                if higher.settlement == "WIN":
                    concordant += 1
                else:
                    discordant += 1
        eligible_matches += int(match_had_pair)
    pairs = concordant + discordant
    return {
        "concordance_rate": concordant / pairs if pairs else None,
        "concordant_pairs": concordant,
        "discordant_pairs": discordant,
        "eligible_match_count": eligible_matches,
        "pair_count": pairs,
    }


def _gate_diagnostics(
    observations: Sequence[HistoricalEvaluation],
) -> dict[str, object]:
    rejections: dict[str, int] = {}
    selected_failed = 0
    for observation in observations:
        failed = tuple(
            gate for gate, status in observation.gates.items() if str(status).upper() == "FAIL"
        )
        for gate in failed:
            rejections[gate] = rejections.get(gate, 0) + 1
        if observation.recommendation in {"PLAY", "CANDIDATE"} and failed:
            selected_failed += 1
    return {
        "mandatory_gate_rejections": dict(sorted(rejections.items())),
        "selected_failed_mandatory_gate_count": selected_failed,
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_item - left_mean) * (right_item - right_mean)
        for left_item, right_item in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((item - left_mean) ** 2 for item in left))
    right_scale = math.sqrt(sum((item - right_mean) ** 2 for item in right))
    if left_scale == 0.0 or right_scale == 0.0:
        return None
    return numerator / (left_scale * right_scale)


def _stability_diagnostics(
    observations: Sequence[HistoricalEvaluation],
) -> dict[str, object]:
    matchweeks = sorted({item.matchweek_id for item in observations})
    recommendation_rates: dict[str, float | None] = {}
    false_positive_rates: dict[str, float | None] = {}
    gate_rejection_rates: dict[str, float | None] = {}
    for matchweek in matchweeks:
        rows = tuple(item for item in observations if item.matchweek_id == matchweek)
        settlement = _settlement_metrics(rows)
        recommendation_rates[matchweek] = cast(float | None, settlement["recommendation_rate"])
        false_positive_rates[matchweek] = cast(float | None, settlement["false_positive_rate"])
        gate_rejection_rates[matchweek] = _match_cluster_mean(
            rows,
            lambda item: (
                1.0 if any(str(status).upper() == "FAIL" for status in item.gates.values()) else 0.0
            ),
        )
    recommendation_values = tuple(
        value for value in recommendation_rates.values() if value is not None
    )
    false_positive_values = tuple(
        value for value in false_positive_rates.values() if value is not None
    )
    gate_rejection_values = tuple(
        value for value in gate_rejection_rates.values() if value is not None
    )
    selected = _selected_rows(observations)
    components: dict[str, list[float]] = {}
    for observation in selected:
        for name, value in observation.selection_components.items():
            components.setdefault(name, []).append(float(value))
    component_ranges = {
        name: max(values) - min(values) for name, values in sorted(components.items())
    }
    agreement: dict[str, list[float]] = {}
    widths: list[float] = []
    errors: list[float] = []
    for observation in selected:
        if observation.model_agreement is not None and observation.settlement in {"WIN", "LOSS"}:
            agreement.setdefault(observation.settlement, []).append(observation.model_agreement)
        if observation.uncertainty_width is not None and observation.settlement in {"WIN", "LOSS"}:
            widths.append(observation.uncertainty_width)
            errors.append(abs(observation.estimated_probability - _outcome(observation)))
    return {
        "false_positive_rate_by_matchweek": false_positive_rates,
        "false_positive_rate_range": (
            max(false_positive_values) - min(false_positive_values)
            if false_positive_values
            else None
        ),
        "model_agreement_by_settlement": {
            settlement: sum(values) / len(values)
            for settlement, values in sorted(agreement.items())
        },
        "mandatory_gate_rejection_rate_by_matchweek": gate_rejection_rates,
        "mandatory_gate_rejection_rate_range": (
            max(gate_rejection_values) - min(gate_rejection_values)
            if gate_rejection_values
            else None
        ),
        "recommendation_rate_by_matchweek": recommendation_rates,
        "recommendation_rate_range": (
            max(recommendation_values) - min(recommendation_values)
            if recommendation_values
            else None
        ),
        "selection_component_ranges": component_ranges,
        "uncertainty_error_correlation": _pearson(widths, errors),
    }


def evaluate_observations(
    observations: Sequence[HistoricalEvaluation],
    *,
    calibration_bin_edges: Sequence[float],
    subgroup_minimum_effective_samples: Mapping[str, int],
    uncertainty_nominal_coverage: float | None = None,
) -> EvaluationMetrics:
    """Compute settlement-aware metrics without inferring acceptance rules."""

    rows = tuple(observations)
    if not rows:
        raise EvaluationError("T18 requires at least one Historical Evaluation.")
    edges = _validate_calibration_edges(calibration_bin_edges)
    selected = _selected_rows(rows)
    binary = _binary_rows(rows)
    scored = _scored_rows(rows)
    return EvaluationMetrics(
        match_count=len({item.match_id for item in rows}),
        target_count=len(rows),
        recommendation_count=len(selected),
        effective_samples={
            "binary_recommendation_match_clusters": len(
                {item.match_id for item in selected if item.settlement in {"WIN", "LOSS"}}
            ),
            "binary_match_clusters": len({item.match_id for item in binary}),
            "correlation_clusters": len({(item.match_id, item.correlation_group) for item in rows}),
            "match_clusters": len({item.match_id for item in rows}),
            "preference_rows": len(rows),
            "recommendation_match_clusters": len({item.match_id for item in selected}),
            "scored_recommendation_match_clusters": len(
                {item.match_id for item in selected if item.settlement != "VOID"}
            ),
            "scored_match_clusters": len({item.match_id for item in scored}),
        },
        probability_quality=_probability_quality(rows, edges, uncertainty_nominal_coverage),
        calibration_bins=_calibration_bins(rows, edges),
        settlement_metrics=_settlement_metrics(rows),
        subgroup_metrics=_subgroup_metrics(
            rows,
            subgroup_minimum_effective_samples,
            edges,
            uncertainty_nominal_coverage,
        ),
        non_triviality=_non_triviality(rows),
        ranking_diagnostics=_ranking_diagnostics(rows),
        gate_diagnostics=_gate_diagnostics(rows),
        stability_diagnostics=_stability_diagnostics(rows),
    )


def _historical_payload(observation: HistoricalEvaluation) -> dict[str, object]:
    return cast(
        dict[str, object],
        _jsonable(
            {
                "baseline_probability": observation.baseline_probability,
                "baseline_digest": observation.baseline_digest,
                "baseline_structural_trivial": observation.baseline_structural_trivial,
                "conservative_probability": observation.conservative_probability,
                "calibration_digest": observation.calibration_digest,
                "correlation_group": observation.correlation_group,
                "estimated_probability": observation.estimated_probability,
                "evidence_digest": observation.evidence_digest,
                "exact_line": observation.exact_line,
                "fixture_revision": observation.fixture_revision,
                "fixture_revision_digest": observation.fixture_revision_digest,
                "gates": observation.gates,
                "input_digest": observation.input_digest,
                "input_observed_at_utc": observation.input_observed_at_utc,
                "kickoff_at_utc": observation.kickoff_at_utc,
                "league": observation.league,
                "match_id": observation.match_id,
                "matchweek_id": observation.matchweek_id,
                "matchweek_start_utc": observation.matchweek_start_utc,
                "membership_manifest": observation.membership_manifest,
                "membership_manifest_digest": observation.membership_manifest_digest,
                "model_agreement": observation.model_agreement,
                "model_digest": observation.model_digest,
                "model_fitted_at_utc": observation.model_fitted_at_utc,
                "model_version": observation.model_version,
                "outcome_known_at_utc": observation.outcome_known_at_utc,
                "outcome_use": observation.outcome_use,
                "policy_digest": observation.policy_digest,
                "policy_version": observation.policy_version,
                "prediction_created_at_utc": observation.prediction_created_at_utc,
                "preference_family": observation.preference_family,
                "preference_id": observation.preference_id,
                "recommendation": observation.recommendation,
                "research_cutoff_at_utc": observation.research_cutoff_at_utc,
                "selection_components": observation.selection_components,
                "selection_strength": observation.selection_strength,
                "settlement": observation.settlement,
                "settlement_distribution": _settlement_probabilities(observation),
                "structural_conditions": observation.structural_conditions,
                "training_data_end_utc": observation.training_data_end_utc,
                "uncertainty_lower": observation.uncertainty_lower,
                "uncertainty_upper": observation.uncertainty_upper,
                "uncertainty_width": observation.uncertainty_width,
            }
        ),
    )


def _observation_sort_key(observation: HistoricalEvaluation) -> tuple[str, ...]:
    return (
        observation.matchweek_start_utc,
        observation.kickoff_at_utc,
        observation.match_id,
        observation.policy_digest,
        observation.preference_id,
        observation.input_digest,
    )


def _metric_value(payload: Mapping[str, object], path: str) -> float | None:
    selected: object = payload
    for part in path.split("."):
        if not isinstance(selected, Mapping) or part not in selected:
            return None
        selected = selected[part]
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        return None
    value = float(selected)
    return value if math.isfinite(value) else None


def _fold_counts(observations: Sequence[HistoricalEvaluation]) -> dict[str, object]:
    rows = tuple(observations)
    selected = _selected_rows(rows)
    binary = _binary_rows(rows)
    scored = _scored_rows(rows)
    return {
        "effective_samples": {
            "binary_recommendation_match_clusters": len(
                {item.match_id for item in selected if item.settlement in {"WIN", "LOSS"}}
            ),
            "binary_match_clusters": len({item.match_id for item in binary}),
            "correlation_clusters": len({(item.match_id, item.correlation_group) for item in rows}),
            "match_clusters": len({item.match_id for item in rows}),
            "preference_rows": len(rows),
            "recommendation_match_clusters": len({item.match_id for item in selected}),
            "scored_recommendation_match_clusters": len(
                {item.match_id for item in selected if item.settlement != "VOID"}
            ),
            "scored_match_clusters": len({item.match_id for item in scored}),
        },
        "match_count": len({item.match_id for item in rows}),
        "recommendation_count": len(selected),
        "target_count": len(rows),
    }


def _nested_candidate_results(
    development_rows: Sequence[HistoricalEvaluation],
    validation_rows: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
    fold: ChronologicalFold,
) -> tuple[dict[str, object], ...]:
    results: list[dict[str, object]] = []
    for candidate in sorted(candidates, key=lambda item: (item.version, item.digest)):
        rows = tuple(item for item in validation_rows if item.policy_digest == candidate.digest)
        if not rows:
            results.append(
                {
                    "metrics": None,
                    "policy_digest": candidate.digest,
                    "policy_version": candidate.version,
                    "selection_metric": config.selection_metric,
                    "selection_metric_value": None,
                }
            )
            continue
        for row in rows:
            training_end = _instant(row.training_data_end_utc)
            if training_end > _instant(fold.development_end_utc) or _instant(
                row.model_fitted_at_utc
            ) > _instant(fold.validation_start_utc):
                raise EvaluationError(
                    "Nested fold training, calibration, and baseline fitting must use only "
                    "earlier Matchweeks."
                )
            if any(
                item.policy_digest == candidate.digest
                and _instant(item.outcome_known_at_utc) > training_end
                for item in development_rows
            ):
                raise EvaluationError(
                    "Nested fold training includes an outcome unavailable at its training boundary."
                )
        metrics = evaluate_observations(
            rows,
            calibration_bin_edges=config.calibration_bin_edges,
            subgroup_minimum_effective_samples=config.subgroup_minimum_effective_samples,
            uncertainty_nominal_coverage=config.uncertainty_nominal_coverage,
        )
        results.append(
            {
                "metrics": metrics.to_dict(),
                "policy_digest": candidate.digest,
                "policy_version": candidate.version,
                "selection_metric": config.selection_metric,
                "selection_metric_value": _metric_value(metrics.to_dict(), config.selection_metric),
            }
        )
    return tuple(results)


def _fold_identity_metadata(
    observations: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
) -> dict[str, object]:
    return {
        "config_digest": config.digest,
        "baseline_digests": tuple(sorted({item.baseline_digest for item in observations})),
        "calibration_digests": tuple(sorted({item.calibration_digest for item in observations})),
        "evidence_digests": tuple(sorted({item.evidence_digest for item in observations})),
        "fixture_revision_digests": tuple(
            sorted({item.fixture_revision_digest for item in observations})
        ),
        "input_digests": tuple(sorted({item.input_digest for item in observations})),
        "model_digests": tuple(sorted({item.model_digest for item in observations})),
        "model_versions": tuple(sorted({item.model_version for item in observations})),
        "membership_manifest_digests": tuple(
            sorted({item.membership_manifest_digest for item in observations})
        ),
        "policy_digests": tuple(sorted(candidate.digest for candidate in candidates)),
        "policy_versions": tuple(sorted(candidate.version for candidate in candidates)),
        "seed": config.seed,
    }


def _nested_fold_record(
    rows: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
    exclusions: Sequence[Mapping[str, str]],
    fold: ChronologicalFold,
) -> dict[str, object]:
    development_rows = tuple(
        item for item in rows if item.matchweek_id in fold.development_matchweek_ids
    )
    validation_rows = tuple(
        item for item in rows if item.matchweek_id in fold.validation_matchweek_ids
    )
    return {
        **_fold_identity_metadata((*development_rows, *validation_rows), candidates, config),
        "candidate_validation_results": _nested_candidate_results(
            development_rows, validation_rows, candidates, config, fold
        ),
        "development_counts": _fold_counts(development_rows),
        "development_matchweek_ids": fold.development_matchweek_ids,
        "development_range": {
            "end_utc": fold.development_end_utc,
            "start_utc": fold.development_start_utc,
        },
        "evaluation_counts": None,
        "evaluation_matchweek_ids": (),
        "evaluation_range": None,
        "exclusions": tuple(exclusions),
        "fold_id": fold.fold_id,
        "fold_type": "NESTED_DEVELOPMENT",
        "validation_counts": _fold_counts(validation_rows),
        "validation_matchweek_ids": fold.validation_matchweek_ids,
        "validation_range": {
            "end_utc": fold.validation_end_utc,
            "start_utc": fold.validation_start_utc,
        },
    }


def _fold_records(
    observations: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
    selected_digest: str,
    exclusions: Sequence[Mapping[str, str]],
    nested_records: Sequence[Mapping[str, object]] | None = None,
) -> tuple[dict[str, object], ...]:
    rows = tuple(observations)
    records = (
        [cast(dict[str, object], _jsonable(item)) for item in nested_records]
        if nested_records is not None
        else [
            _nested_fold_record(rows, candidates, config, exclusions, fold)
            for fold in generate_rolling_origin_folds(rows, config)
        ]
    )
    development_rows = tuple(
        item
        for item in rows
        if item.policy_digest == selected_digest
        and config.development.contains(item.matchweek_start_utc)
    )
    validation_rows = tuple(
        item
        for item in rows
        if item.policy_digest == selected_digest
        and config.validation.contains(item.matchweek_start_utc)
    )
    evaluation_rows = tuple(
        item
        for item in rows
        if item.policy_digest == selected_digest
        and config.evaluation.contains(item.matchweek_start_utc)
    )
    outer_payload = {
        "config_digest": config.digest,
        "policy_digest": selected_digest,
        "window": config.evaluation.to_dict(),
    }
    records.append(
        {
            **_fold_identity_metadata(
                (*development_rows, *validation_rows, *evaluation_rows),
                tuple(candidate for candidate in candidates if candidate.digest == selected_digest),
                config,
            ),
            "candidate_validation_results": None,
            "development_counts": _fold_counts(development_rows),
            "development_matchweek_ids": tuple(
                sorted({item.matchweek_id for item in development_rows})
            ),
            "development_range": {
                "end_utc": config.development.end_utc,
                "start_utc": config.development.start_utc,
            },
            "evaluation_counts": _fold_counts(evaluation_rows),
            "evaluation_matchweek_ids": tuple(
                sorted({item.matchweek_id for item in evaluation_rows})
            ),
            "evaluation_range": {
                "end_utc": config.evaluation.end_utc,
                "start_utc": config.evaluation.start_utc,
            },
            "exclusions": tuple(exclusions),
            "fold_id": f"final-{_sha256(outer_payload)[:12]}",
            "fold_type": "OUTER_FINAL_EVALUATION",
            "validation_counts": _fold_counts(validation_rows),
            "validation_matchweek_ids": tuple(
                sorted({item.matchweek_id for item in validation_rows})
            ),
            "validation_range": {
                "end_utc": config.validation.end_utc,
                "start_utc": config.validation.start_utc,
            },
        }
    )
    return tuple(records)


def _criterion_passes(value: float, criterion: EvaluationCriterion) -> bool:
    if criterion.operator == "<":
        return value < criterion.threshold
    if criterion.operator == "<=":
        return value <= criterion.threshold
    if criterion.operator == ">":
        return value > criterion.threshold
    if criterion.operator == ">=":
        return value >= criterion.threshold
    return math.isclose(value, criterion.threshold, abs_tol=1e-12)


def _criterion_effective_sample(metrics: EvaluationMetrics, metric: str) -> int:
    if metric.startswith(("probability_quality.", "calibration_bins.")):
        return int(metrics.effective_samples["scored_match_clusters"])
    if metric.startswith("ranking_diagnostics."):
        return cast(int, metrics.ranking_diagnostics["eligible_match_count"])
    if metric.startswith("settlement_metrics.false_positive") or metric.startswith(
        "settlement_metrics.negative_settlement"
    ):
        return int(metrics.effective_samples["binary_recommendation_match_clusters"])
    return int(metrics.effective_samples["scored_recommendation_match_clusters"])


def _evaluation_findings(
    metrics: EvaluationMetrics, config: EvaluationConfig
) -> tuple[str, tuple[dict[str, object], ...]]:
    recommendation_effective_sample = int(
        metrics.effective_samples["scored_recommendation_match_clusters"]
    )
    minimum = config.evaluation_minimum_recommendations
    if minimum is None and not config.criteria:
        return (
            "INCONCLUSIVE",
            (
                {
                    "criterion": "evaluation_evidence",
                    "reason": "NO_PREDECLARED_ACCEPTANCE_CRITERIA_OR_MINIMUM_SAMPLE",
                    "status": "INCONCLUSIVE",
                },
            ),
        )
    findings: list[dict[str, object]] = []
    insufficient = minimum is None or recommendation_effective_sample < minimum
    if insufficient:
        findings.append(
            {
                "criterion": "evaluation_evidence",
                "effective_sample": recommendation_effective_sample,
                "minimum_effective_sample": minimum,
                "reason": (
                    "MINIMUM_SAMPLE_NOT_PREDECLARED"
                    if minimum is None
                    else "TOO_FEW_RECOMMENDATIONS"
                ),
                "status": "INCONCLUSIVE",
            }
        )
    payload = metrics.to_dict()
    for criterion in config.criteria:
        value = _metric_value(payload, criterion.metric)
        criterion_minimum = criterion.minimum_effective_sample
        criterion_effective_sample = _criterion_effective_sample(metrics, criterion.metric)
        if value is None or (
            criterion_minimum is not None and criterion_effective_sample < criterion_minimum
        ):
            findings.append(
                {
                    "criterion": criterion.metric,
                    "effective_sample": criterion_effective_sample,
                    "minimum_effective_sample": criterion_minimum,
                    "operator": criterion.operator,
                    "reason": "METRIC_OR_SAMPLE_UNAVAILABLE",
                    "status": "INCONCLUSIVE",
                    "threshold": criterion.threshold,
                    "value": value,
                }
            )
            continue
        findings.append(
            {
                "criterion": criterion.metric,
                "effective_sample": criterion_effective_sample,
                "minimum_effective_sample": criterion_minimum,
                "operator": criterion.operator,
                "status": "PASS" if _criterion_passes(value, criterion) else "FAIL",
                "threshold": criterion.threshold,
                "value": value,
            }
        )
    statuses = {str(item["status"]) for item in findings}
    if insufficient or "INCONCLUSIVE" in statuses:
        return "INCONCLUSIVE", tuple(findings)
    if "FAIL" in statuses:
        return "FAIL", tuple(findings)
    if findings and statuses == {"PASS"}:
        return "PASS", tuple(findings)
    return "INCONCLUSIVE", tuple(findings)


@dataclass(frozen=True)
class EvaluationArtifact:
    """Canonical, digest-bound output of one complete T18 evaluation."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = cast(dict[str, object], _jsonable(self.payload))
        if normalized.get("schema_version") != T18_SCHEMA_VERSION:
            raise EvaluationError("Unsupported T18 evaluation artifact schema version.")
        supplied = normalized.get("artifact_digest")
        if not isinstance(supplied, str):
            raise EvaluationError("Evaluation artifact digest is required.")
        core = {key: value for key, value in normalized.items() if key != "artifact_digest"}
        if supplied != _sha256(core):
            raise EvaluationError("Evaluation artifact digest does not match its content.")
        object.__setattr__(self, "payload", cast(Mapping[str, object], _freeze(normalized)))

    @property
    def digest(self) -> str:
        return str(self.payload["artifact_digest"])

    @property
    def status(self) -> str:
        return str(self.payload["status"])

    @property
    def lifecycle_effect(self) -> str:
        return str(self.payload["lifecycle_effect"])

    @property
    def frozen_policy_identity(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], self.payload["frozen_policy_identity"])

    @property
    def validation_candidates(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], self.payload["validation_candidates"])

    @property
    def evaluation_metrics(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], self.payload["evaluation_metrics"])

    @property
    def findings(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], self.payload["findings"])

    @property
    def cutoff_fidelity(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], self.payload["cutoff_fidelity"])

    @property
    def reproducibility(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], self.payload["reproducibility"])

    @property
    def folds(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], self.payload["folds"])

    @property
    def policy_stability(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], self.payload["policy_stability"])

    @property
    def observation_audit(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], self.payload["observation_audit"])

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(self.payload))

    def to_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    @classmethod
    def from_bytes(cls, value: bytes) -> EvaluationArtifact:
        try:
            payload = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvaluationError("Evaluation artifact must be valid UTF-8 JSON.") from error
        if not isinstance(payload, Mapping):
            raise EvaluationError("Evaluation artifact must be a JSON object.")
        return cls(cast(Mapping[str, object], payload))


def _numeric_paths(value: Mapping[str, object], prefix: str = "") -> dict[str, float]:
    selected: dict[str, float] = {}
    for name, item in value.items():
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(item, Mapping):
            selected.update(_numeric_paths(cast(Mapping[str, object], item), path))
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            number = float(item)
            if math.isfinite(number):
                selected[path] = number
    return selected


def _policy_stability(
    validation_candidates: Sequence[Mapping[str, object]],
    candidates: Sequence[CandidatePolicy],
) -> dict[str, object]:
    scores: list[float] = []
    for item in validation_candidates:
        score = item.get("selection_metric_value")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            scores.append(float(score))
    parameter_digests = {
        candidate.digest: _sha256(candidate.parameters) for candidate in candidates
    }
    fold_values: dict[str, list[float]] = {}
    for candidate in candidates:
        for parameters in candidate.fold_parameters.values():
            for path, value in _numeric_paths(parameters).items():
                fold_values.setdefault(path, []).append(value)
    threshold_ranges = {
        path: max(values) - min(values)
        for path, values in sorted(fold_values.items())
        if path.startswith("thresholds.") and len(values) >= 2
    }
    weight_ranges = {
        path: max(values) - min(values)
        for path, values in sorted(fold_values.items())
        if path.startswith("selection_strength.weights.") and len(values) >= 2
    }
    return {
        "candidate_parameter_digests": parameter_digests,
        "candidate_selection_metric_range": max(scores) - min(scores) if scores else None,
        "candidate_count": len(candidates),
        "fold_parameter_status": "AVAILABLE" if fold_values else "INCONCLUSIVE",
        "selection_strength_weight_ranges": weight_ranges,
        "threshold_ranges": threshold_ranges,
    }


def evaluate_policies(
    observations: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
    *,
    _nested_records: Sequence[Mapping[str, object]] | None = None,
) -> EvaluationArtifact:
    """Select on Validation and judge only the frozen winner on Final Evaluation."""

    rows = tuple(sorted(observations, key=_observation_sort_key))
    candidate_rows = tuple(sorted(candidates, key=lambda item: (item.version, item.digest)))
    contract = validate_evaluation_contract(rows, candidate_rows, config)
    validation_candidates: list[dict[str, object]] = []
    for candidate in candidate_rows:
        validation_rows = tuple(
            item
            for item in rows
            if item.policy_digest == candidate.digest
            and config.validation.contains(item.matchweek_start_utc)
        )
        if not validation_rows:
            raise EvaluationError(
                f"Candidate {candidate.version} has no observations in the Validation Period."
            )
        metrics = evaluate_observations(
            validation_rows,
            calibration_bin_edges=config.calibration_bin_edges,
            subgroup_minimum_effective_samples=config.subgroup_minimum_effective_samples,
            uncertainty_nominal_coverage=config.uncertainty_nominal_coverage,
        )
        metric_value = _metric_value(metrics.to_dict(), config.selection_metric)
        if metric_value is None:
            raise EvaluationError(
                f"Selection metric {config.selection_metric!r} is unavailable for "
                f"Candidate {candidate.version}."
            )
        validation_candidates.append(
            {
                "metrics": metrics.to_dict(),
                "policy_digest": candidate.digest,
                "policy_version": candidate.version,
                "selection_metric": config.selection_metric,
                "selection_metric_value": metric_value,
            }
        )
    reverse = config.selection_direction == "MAXIMIZE"

    def selection_key(item: Mapping[str, object]) -> tuple[float, str]:
        raw_score = item["selection_metric_value"]
        assert isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        score = float(raw_score)
        return (-score if reverse else score, str(item["policy_digest"]))

    validation_candidates.sort(key=selection_key)
    selected_digest = str(validation_candidates[0]["policy_digest"])
    selected = next(item for item in candidate_rows if item.digest == selected_digest)
    evaluation_rows = tuple(
        item for item in rows if config.evaluation.contains(item.matchweek_start_utc)
    )
    unexpected = tuple(
        sorted(
            {
                item.policy_digest
                for item in evaluation_rows
                if item.policy_digest != selected_digest
            }
        )
    )
    if unexpected:
        raise EvaluationError(
            "Final Evaluation contains outcomes for a non-frozen Candidate Policy: "
            + ", ".join(unexpected)
        )
    if not evaluation_rows:
        raise EvaluationError("The frozen Candidate Policy has no Final Evaluation observations.")
    metrics = evaluate_observations(
        evaluation_rows,
        calibration_bin_edges=config.calibration_bin_edges,
        subgroup_minimum_effective_samples=config.subgroup_minimum_effective_samples,
        uncertainty_nominal_coverage=config.uncertainty_nominal_coverage,
    )
    status, findings = _evaluation_findings(metrics, config)
    folds = _fold_records(
        rows,
        candidate_rows,
        config,
        selected.digest,
        contract.exclusions,
        _nested_records,
    )
    corpus_payload = tuple(_historical_payload(item) for item in rows)
    core: dict[str, object] = {
        "cutoff_fidelity": {
            "checked_input_count": sum(len(item.input_observed_at_utc) for item in rows),
            "fixture_revision_digests": tuple(
                sorted({item.fixture_revision_digest for item in rows})
            ),
            "membership_manifest_digests": tuple(
                sorted({item.membership_manifest_digest for item in rows})
            ),
            "status": "PASS",
        },
        "evaluation_metrics": metrics.to_dict(),
        "findings": findings,
        "folds": folds,
        "frozen_policy_identity": {
            "digest": selected.digest,
            "status": selected.status,
            "version": selected.version,
        },
        "lifecycle_effect": "EVALUATED_RESEARCH_ONLY",
        "observation_audit": corpus_payload,
        "policy_stability": _policy_stability(validation_candidates, candidate_rows),
        "reproducibility": {
            "algorithm_version": "t18-chronological-evaluation-v1",
            "candidate_policy_digests": tuple(item.digest for item in candidate_rows),
            "config_digest": config.digest,
            "corpus_digest": _sha256(corpus_payload),
            "environment": {
                "machine": platform.machine(),
                "python": platform.python_version(),
                "system": platform.system(),
            },
            "evaluation_window_digest": contract.evaluation_window_digest,
            "fold_digest": _sha256(folds),
            "input_digests": tuple(sorted({item.input_digest for item in rows})),
            "membership_manifest_digests": tuple(
                sorted({item.membership_manifest_digest for item in rows})
            ),
            "fixture_revision_digests": tuple(
                sorted({item.fixture_revision_digest for item in rows})
            ),
            "model_digests": tuple(sorted({item.model_digest for item in rows})),
            "seed": config.seed,
        },
        "schema_version": T18_SCHEMA_VERSION,
        "status": status,
        "validation_candidates": tuple(validation_candidates),
    }
    return EvaluationArtifact({**core, "artifact_digest": _sha256(core)})


T18_CHECKPOINT_SCHEMA_VERSION = "matchvet.policy-evaluation-checkpoint.v1"


@dataclass(frozen=True)
class EvaluationCheckpoint:
    """Digest-bound progress for resumable nested-fold evaluation."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = cast(dict[str, object], _jsonable(self.payload))
        if normalized.get("schema_version") != T18_CHECKPOINT_SCHEMA_VERSION:
            raise EvaluationError("Unsupported evaluation checkpoint schema version.")
        supplied = normalized.get("checkpoint_digest")
        if not isinstance(supplied, str):
            raise EvaluationError("Evaluation checkpoint digest is required.")
        core = {key: value for key, value in normalized.items() if key != "checkpoint_digest"}
        if supplied != _sha256(core):
            raise EvaluationError("Evaluation checkpoint digest does not match its content.")
        if normalized.get("state") not in {"IN_PROGRESS", "COMPLETE"}:
            raise EvaluationError("Evaluation checkpoint state is invalid.")
        _digest(str(normalized.get("run_digest", "")), "Evaluation checkpoint run digest")
        artifact_digest = normalized.get("artifact_digest")
        if artifact_digest is not None:
            _digest(str(artifact_digest), "Evaluation checkpoint artifact digest")
        completed = normalized.get("completed_fold_ids")
        records = normalized.get("fold_records")
        if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
            raise EvaluationError("Evaluation checkpoint fold IDs must be a JSON array.")
        if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records):
            raise EvaluationError("Evaluation checkpoint fold records must be a JSON array.")
        object.__setattr__(self, "payload", cast(Mapping[str, object], _freeze(normalized)))

    @property
    def state(self) -> str:
        return str(self.payload["state"])

    @property
    def run_digest(self) -> str:
        return str(self.payload["run_digest"])

    @property
    def artifact_digest(self) -> str | None:
        selected = self.payload["artifact_digest"]
        return None if selected is None else str(selected)

    @property
    def completed_fold_ids(self) -> tuple[str, ...]:
        return cast(tuple[str, ...], self.payload["completed_fold_ids"])

    @property
    def fold_records(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], self.payload["fold_records"])

    def to_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    @classmethod
    def build(
        cls,
        *,
        state: str,
        run_digest: str,
        completed_fold_ids: Sequence[str],
        fold_records: Sequence[Mapping[str, object]],
        artifact_digest: str | None,
    ) -> EvaluationCheckpoint:
        core: dict[str, object] = {
            "artifact_digest": artifact_digest,
            "completed_fold_ids": tuple(completed_fold_ids),
            "fold_records": tuple(fold_records),
            "run_digest": run_digest,
            "schema_version": T18_CHECKPOINT_SCHEMA_VERSION,
            "state": state,
        }
        return cls({**core, "checkpoint_digest": _sha256(core)})


def read_evaluation_checkpoint(path: Path) -> EvaluationCheckpoint:
    """Read and verify a T18 progress checkpoint."""

    try:
        content = path.read_bytes()
    except OSError as error:
        raise EvaluationError(f"Evaluation checkpoint could not be read: {path}") from error
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Evaluation checkpoint must be valid UTF-8 JSON.") from error
    if not isinstance(payload, Mapping):
        raise EvaluationError("Evaluation checkpoint must be a JSON object.")
    return EvaluationCheckpoint(cast(Mapping[str, object], payload))


def _write_evaluation_checkpoint(path: Path, checkpoint: EvaluationCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    partial = Path(partial_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(checkpoint.to_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
        _fsync_directory(path.parent)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _evaluation_run_digest(
    observations: Sequence[HistoricalEvaluation],
    candidates: Sequence[CandidatePolicy],
    config: EvaluationConfig,
) -> str:
    return _sha256(
        {
            "candidates": tuple(
                item.to_dict() for item in sorted(candidates, key=lambda item: item.digest)
            ),
            "config": config.to_dict(),
            "corpus": tuple(
                _historical_payload(item)
                for item in sorted(observations, key=_observation_sort_key)
            ),
        }
    )


class EvaluationRunner:
    """Checkpoint nested folds and resume only the exact same evaluation run."""

    def __init__(
        self,
        checkpoint_path: Path,
        *,
        checkpoint_observer: Callable[[int], None] | None = None,
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.checkpoint_observer = checkpoint_observer

    def run(
        self,
        observations: Sequence[HistoricalEvaluation],
        candidates: Sequence[CandidatePolicy],
        config: EvaluationConfig,
        *,
        resume: bool = False,
    ) -> EvaluationArtifact:
        rows = tuple(sorted(observations, key=_observation_sort_key))
        candidate_rows = tuple(sorted(candidates, key=lambda item: item.digest))
        run_digest = _evaluation_run_digest(rows, candidate_rows, config)
        completed_ids: list[str] = []
        completed_records: list[Mapping[str, object]] = []
        if resume:
            checkpoint = read_evaluation_checkpoint(self.checkpoint_path)
            if checkpoint.run_digest != run_digest:
                raise EvaluationError(
                    "Evaluation checkpoint input digest does not match this corpus/config."
                )
            completed_ids.extend(checkpoint.completed_fold_ids)
            completed_records.extend(checkpoint.fold_records)
        elif self.checkpoint_path.exists():
            raise EvaluationError(
                "Evaluation checkpoint already exists; use resume or a new checkpoint path."
            )
        contract = validate_evaluation_contract(rows, candidate_rows, config)
        if not resume:
            initial = EvaluationCheckpoint.build(
                state="IN_PROGRESS",
                run_digest=run_digest,
                completed_fold_ids=(),
                fold_records=(),
                artifact_digest=None,
            )
            _write_evaluation_checkpoint(self.checkpoint_path, initial)
            if self.checkpoint_observer is not None:
                self.checkpoint_observer(0)
        nested_folds = generate_rolling_origin_folds(rows, config)
        expected_fold_ids = tuple(fold.fold_id for fold in nested_folds)
        saved_nested_count = min(len(expected_fold_ids), len(completed_ids))
        completed_ids = completed_ids[:saved_nested_count]
        completed_records = completed_records[:saved_nested_count]
        if (
            tuple(completed_ids) != expected_fold_ids[:saved_nested_count]
            or tuple(str(item.get("fold_id")) for item in completed_records)
            != expected_fold_ids[:saved_nested_count]
        ):
            raise EvaluationError(
                "Evaluation checkpoint folds do not match this chronological run."
            )
        for fold in nested_folds[saved_nested_count:]:
            record = _nested_fold_record(
                rows,
                candidate_rows,
                config,
                contract.exclusions,
                fold,
            )
            fold_id = fold.fold_id
            if fold_id in completed_ids:
                continue
            completed_ids.append(fold_id)
            completed_records.append(record)
            checkpoint = EvaluationCheckpoint.build(
                state="IN_PROGRESS",
                run_digest=run_digest,
                completed_fold_ids=completed_ids,
                fold_records=completed_records,
                artifact_digest=None,
            )
            _write_evaluation_checkpoint(self.checkpoint_path, checkpoint)
            if self.checkpoint_observer is not None:
                self.checkpoint_observer(len(completed_ids))
        artifact = evaluate_policies(
            rows,
            candidate_rows,
            config,
            _nested_records=completed_records,
        )
        final_id = str(artifact.folds[-1]["fold_id"])
        completed_ids = [
            *(str(item["fold_id"]) for item in artifact.folds[:-1]),
            final_id,
        ]
        completed = EvaluationCheckpoint.build(
            state="COMPLETE",
            run_digest=run_digest,
            completed_fold_ids=completed_ids,
            fold_records=artifact.folds,
            artifact_digest=artifact.digest,
        )
        _write_evaluation_checkpoint(self.checkpoint_path, completed)
        return artifact


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{label} must be a JSON object.")
    return cast(Mapping[str, object], value)


def _optional_float_from_mapping(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{label} must be a finite number or null.")
    selected = float(value)
    if not math.isfinite(selected):
        raise EvaluationError(f"{label} must be a finite number or null.")
    return selected


def historical_evaluation_from_mapping(value: Mapping[str, object]) -> HistoricalEvaluation:
    """Construct one strict historical row from external JSON."""

    inputs = _required_mapping(value.get("input_observed_at_utc"), "input_observed_at_utc")
    membership_manifest = _required_mapping(value.get("membership_manifest"), "membership_manifest")
    fixture_revision = _required_mapping(value.get("fixture_revision"), "fixture_revision")
    gates = _required_mapping(value.get("gates", {}), "gates")
    components = _required_mapping(value.get("selection_components", {}), "selection_components")
    structural = value.get("structural_conditions", ())
    if not isinstance(structural, (tuple, list)) or not all(
        isinstance(item, str) for item in structural
    ):
        raise EvaluationError("structural_conditions must be an array of strings.")
    trivial = value.get("baseline_structural_trivial")
    if trivial is not None and not isinstance(trivial, bool):
        raise EvaluationError("baseline_structural_trivial must be boolean or null.")
    raw_distribution = value.get("settlement_distribution")
    distribution = (
        None
        if raw_distribution is None
        else _required_mapping(raw_distribution, "settlement_distribution")
    )
    return HistoricalEvaluation(
        match_id=cast(str, value.get("match_id")),
        matchweek_id=cast(str, value.get("matchweek_id")),
        matchweek_start_utc=cast(str, value.get("matchweek_start_utc")),
        kickoff_at_utc=cast(str, value.get("kickoff_at_utc")),
        research_cutoff_at_utc=cast(str, value.get("research_cutoff_at_utc")),
        prediction_created_at_utc=cast(str, value.get("prediction_created_at_utc")),
        outcome_known_at_utc=cast(str, value.get("outcome_known_at_utc")),
        league=cast(str, value.get("league")),
        preference_id=cast(str, value.get("preference_id")),
        preference_family=cast(str, value.get("preference_family")),
        exact_line=cast(str, value.get("exact_line")),
        policy_version=cast(str, value.get("policy_version")),
        policy_digest=cast(str, value.get("policy_digest")),
        model_version=cast(str, value.get("model_version")),
        model_digest=cast(str, value.get("model_digest")),
        evidence_digest=cast(str, value.get("evidence_digest")),
        input_digest=cast(str, value.get("input_digest")),
        estimated_probability=cast(float, value.get("estimated_probability")),
        conservative_probability=cast(float, value.get("conservative_probability")),
        uncertainty_lower=cast(float, value.get("uncertainty_lower")),
        uncertainty_upper=cast(float, value.get("uncertainty_upper")),
        settlement=cast(str, value.get("settlement")),
        recommendation=cast(str, value.get("recommendation")),
        correlation_group=cast(str, value.get("correlation_group")),
        input_observed_at_utc=cast(Mapping[str, str], inputs),
        membership_manifest=membership_manifest,
        membership_manifest_digest=cast(str, value.get("membership_manifest_digest")),
        fixture_revision=fixture_revision,
        fixture_revision_digest=cast(str, value.get("fixture_revision_digest")),
        training_data_end_utc=cast(str, value.get("training_data_end_utc")),
        model_fitted_at_utc=cast(str, value.get("model_fitted_at_utc")),
        calibration_digest=cast(str, value.get("calibration_digest")),
        baseline_digest=cast(str, value.get("baseline_digest")),
        outcome_use=cast(str, value.get("outcome_use", "UNSEEN")),
        selection_strength=_optional_float_from_mapping(
            value.get("selection_strength"), "selection_strength"
        ),
        baseline_probability=_optional_float_from_mapping(
            value.get("baseline_probability"), "baseline_probability"
        ),
        baseline_structural_trivial=trivial,
        gates=cast(Mapping[str, str], gates),
        selection_components=cast(Mapping[str, float], components),
        structural_conditions=tuple(cast(Sequence[str], structural)),
        model_agreement=_optional_float_from_mapping(
            value.get("model_agreement"), "model_agreement"
        ),
        uncertainty_width=_optional_float_from_mapping(
            value.get("uncertainty_width"), "uncertainty_width"
        ),
        settlement_distribution=cast(Mapping[str, float] | None, distribution),
    )


def candidate_policy_from_mapping(value: Mapping[str, object]) -> CandidatePolicy:
    """Construct a strict research-only candidate from external JSON."""

    parameters = _required_mapping(value.get("parameters"), "Candidate parameters")
    raw_folds = _required_mapping(value.get("fold_parameters", {}), "fold_parameters")
    folds = {
        str(fold_id): _required_mapping(parameters_value, f"fold_parameters.{fold_id}")
        for fold_id, parameters_value in raw_folds.items()
    }
    inspected = value.get("inspected_evaluation_digests", ())
    if not isinstance(inspected, (tuple, list)) or not all(
        isinstance(item, str) for item in inspected
    ):
        raise EvaluationError("inspected_evaluation_digests must be an array of digests.")
    return CandidatePolicy(
        version=cast(str, value.get("version")),
        digest=cast(str, value.get("digest")),
        development_data_end_utc=cast(str, value.get("development_data_end_utc")),
        frozen_at_utc=cast(str, value.get("frozen_at_utc")),
        parameters=parameters,
        fold_parameters=folds,
        inspected_evaluation_digests=tuple(cast(Sequence[str], inspected)),
        status=cast(str, value.get("status", "RESEARCH_ONLY")),
    )


def _period_from_mapping(value: object, label: str) -> ChronologicalPeriod:
    selected = _required_mapping(value, label)
    return ChronologicalPeriod(
        cast(str, selected.get("name")),
        cast(str, selected.get("start_utc")),
        cast(str, selected.get("end_utc")),
    )


def evaluation_config_from_mapping(value: Mapping[str, object]) -> EvaluationConfig:
    """Construct declared chronological controls without filling statistical defaults."""

    raw_criteria = value.get("criteria", ())
    if not isinstance(raw_criteria, (tuple, list)):
        raise EvaluationError("criteria must be an array.")
    criteria: list[EvaluationCriterion] = []
    for index, item in enumerate(raw_criteria):
        selected = _required_mapping(item, f"criteria[{index}]")
        criteria.append(
            EvaluationCriterion(
                metric=cast(str, selected.get("metric")),
                operator=cast(str, selected.get("operator")),
                threshold=cast(float, selected.get("threshold")),
                minimum_effective_sample=cast(int | None, selected.get("minimum_effective_sample")),
            )
        )
    raw_edges = value.get("calibration_bin_edges", (0.0, 1.0))
    if not isinstance(raw_edges, (tuple, list)):
        raise EvaluationError("calibration_bin_edges must be an array.")
    raw_minimums = _required_mapping(
        value.get("subgroup_minimum_effective_samples", {}),
        "subgroup_minimum_effective_samples",
    )
    return EvaluationConfig(
        development=_period_from_mapping(value.get("development"), "development"),
        validation=_period_from_mapping(value.get("validation"), "validation"),
        evaluation=_period_from_mapping(value.get("evaluation"), "evaluation"),
        minimum_development_matchweeks=cast(int, value.get("minimum_development_matchweeks")),
        rolling_validation_matchweeks=cast(int, value.get("rolling_validation_matchweeks")),
        rolling_step_matchweeks=cast(int, value.get("rolling_step_matchweeks")),
        seed=cast(int, value.get("seed")),
        split_method=cast(str, value.get("split_method", CHRONOLOGICAL_SPLIT)),
        calibration_bin_edges=tuple(cast(Sequence[float], raw_edges)),
        subgroup_minimum_effective_samples=cast(Mapping[str, int], raw_minimums),
        selection_metric=cast(
            str, value.get("selection_metric", "probability_quality.brier_score")
        ),
        selection_direction=cast(str, value.get("selection_direction", "MINIMIZE")),
        evaluation_minimum_recommendations=cast(
            int | None, value.get("evaluation_minimum_recommendations")
        ),
        uncertainty_nominal_coverage=cast(float | None, value.get("uncertainty_nominal_coverage")),
        criteria=tuple(criteria),
    )


__all__ = [
    "CHRONOLOGICAL_SPLIT",
    "T18_SCHEMA_VERSION",
    "CandidatePolicy",
    "ChronologicalFold",
    "ChronologicalPeriod",
    "EvaluationArtifact",
    "EvaluationCheckpoint",
    "EvaluationConfig",
    "EvaluationContract",
    "EvaluationCriterion",
    "EvaluationError",
    "EvaluationMetrics",
    "EvaluationRunner",
    "HistoricalEvaluation",
    "candidate_policy_from_mapping",
    "evaluate_observations",
    "evaluate_policies",
    "evaluation_config_from_mapping",
    "generate_rolling_origin_folds",
    "historical_evaluation_from_mapping",
    "read_evaluation_checkpoint",
    "validate_evaluation_contract",
]

"""T14 calibration and probability-uncertainty layer.

T14 consumes the coherent count distributions produced by T11--T13.  It
calibrates the underlying count surface with a small affine mean map and an
exponential tilt, then derives every settlement market again from that one
surface.  This keeps nesting, marginals, and PUSH mass coherent while making
calibration and uncertainty auditable.

The module deliberately stops at calibrated probabilities.  It does not
implement Selection Strength, policy gates, PLAY/AVOID, or reports.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from matchvet.t09 import FrozenEvidenceState
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, BettingPreference, PreferenceFamily
from matchvet.t11 import ModelStatus, SettlementProbabilities

T14_MODEL_NAME = "matchvet-calibration-uncertainty-layer"
T14_MODEL_VERSION = "t14-calibration-uncertainty-v1"
T14_CALIBRATION_VERSION = "t14-affine-distribution-calibration-v1"
T14_ALGORITHM_VERSION = "affine-mean-exponential-tilt-laplace-sensitivity-v1"
T14_FEATURE_VERSION = "t14-frozen-t09-uncertainty-v1"
T14_MEDIA_TYPE = "application/vnd.matchvet.t14-calibration-uncertainty+json"


class T14Error(Exception):
    """Base class for T14 calibration and uncertainty errors."""


class T14ValidationError(T14Error, ValueError):
    """A T14 input is malformed or cannot satisfy the frozen-input contract."""


class T14IntegrityError(T14Error):
    """A T14 digest or immutable provenance value does not match its content."""


class T14Status(StrEnum):
    AVAILABLE = "AVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    REJECT = "REJECT"


MODEL_UNAVAILABLE = T14Status.MODEL_UNAVAILABLE
REJECT = T14Status.REJECT


class ModelFamily(StrEnum):
    FULL_TIME_GOALS = "FULL_TIME_GOALS"
    FIRST_HALF_GOALS = "FIRST_HALF_GOALS"
    SECOND_HALF_GOALS = "SECOND_HALF_GOALS"
    CORNERS = "CORNERS"


class ReferenceModelKind(StrEnum):
    REDUCED = "REDUCED"
    EMPIRICAL = "EMPIRICAL"
    BIVARIATE = "BIVARIATE"
    ELO = "ELO"


FULL_TIME_GOALS = ModelFamily.FULL_TIME_GOALS
FIRST_HALF_GOALS = ModelFamily.FIRST_HALF_GOALS
SECOND_HALF_GOALS = ModelFamily.SECOND_HALF_GOALS
CORNERS = ModelFamily.CORNERS


def _enum_value(value: object) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted((_jsonable(item) for item in value), key=str)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if isinstance(value, float):
        if not math.isfinite(value):
            raise T14ValidationError("T14 JSON values must be finite.")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T14ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _number(value: object, label: str = "T14 number") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise T14ValidationError(f"{label} must be a finite number.")
    selected = float(value)
    if not math.isfinite(selected):
        raise T14ValidationError(f"{label} must be a finite number.")
    return selected


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _non_negative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise T14ValidationError(f"{label} must be a non-negative integer or null.")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise T14ValidationError(f"{label} must be an object.")
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


def _strings(value: Iterable[object]) -> tuple[str, ...]:
    selected: set[str] = set()
    for item in value:
        selected.add(_text(item, "T14 identifier"))
    return tuple(sorted(selected))


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise T14ValidationError("T14 timestamps must be ISO-8601 values.") from error
    if parsed.tzinfo is None:
        raise T14ValidationError("T14 timestamps must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _freeze_map(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): value[key] for key in value})


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalise_family(value: ModelFamily | str | None) -> ModelFamily:
    if isinstance(value, ModelFamily):
        return value
    if value is None:
        raise T14ValidationError("T14 model family is required.")
    token = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "FULL_TIME": ModelFamily.FULL_TIME_GOALS,
        "FULL_TIME_GOAL": ModelFamily.FULL_TIME_GOALS,
        "FULL_TIME_GOALS": ModelFamily.FULL_TIME_GOALS,
        "GOALS": ModelFamily.FULL_TIME_GOALS,
        "FIRST_HALF": ModelFamily.FIRST_HALF_GOALS,
        "FIRST_HALF_GOAL": ModelFamily.FIRST_HALF_GOALS,
        "FIRST_HALF_GOALS": ModelFamily.FIRST_HALF_GOALS,
        "SECOND_HALF": ModelFamily.SECOND_HALF_GOALS,
        "SECOND_HALF_GOAL": ModelFamily.SECOND_HALF_GOALS,
        "SECOND_HALF_GOALS": ModelFamily.SECOND_HALF_GOALS,
        "CORNER": ModelFamily.CORNERS,
        "CORNERS": ModelFamily.CORNERS,
        "JOINT_CORNERS": ModelFamily.CORNERS,
    }
    try:
        return aliases[token]
    except KeyError as error:
        raise T14ValidationError(f"Unsupported T14 model family {value!r}.") from error


def _normalise_reference_kind(value: ReferenceModelKind | str) -> ReferenceModelKind:
    if isinstance(value, ReferenceModelKind):
        return value
    token = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "REDUCED_POISSON": ReferenceModelKind.REDUCED,
        "EMPIRICAL_BASELINE": ReferenceModelKind.EMPIRICAL,
        "BIVARIATE_COUNT": ReferenceModelKind.BIVARIATE,
        "ELO_STYLE": ReferenceModelKind.ELO,
    }
    try:
        return aliases.get(token, ReferenceModelKind(token))
    except ValueError as error:
        raise T14ValidationError(f"Unsupported T14 reference model {value!r}.") from error


def _status(value: object) -> T14Status:
    if isinstance(value, T14Status):
        return value
    token = _enum_value(value).upper()
    if token == ModelStatus.AVAILABLE.value:
        return T14Status.AVAILABLE
    if token == ModelStatus.MODEL_UNAVAILABLE.value:
        return T14Status.MODEL_UNAVAILABLE
    try:
        return T14Status(token)
    except ValueError as error:
        raise T14ValidationError(f"Unsupported T14 status {value!r}.") from error


@dataclass(frozen=True)
class T14Config:
    """Versioned calibration, uncertainty, and sensitivity controls."""

    name: str = T14_MODEL_NAME
    version: str = T14_MODEL_VERSION
    calibration_version: str = T14_CALIBRATION_VERSION
    algorithm_version: str = T14_ALGORITHM_VERSION
    feature_version: str = T14_FEATURE_VERSION
    minimum_calibration_matches: int = 3
    ridge: float = 0.25
    minimum_slope: float = 0.25
    maximum_slope: float = 2.5
    maximum_count_mean: float = 32.0
    parameter_draws: int = 32
    lower_quantile: float = 0.05
    upper_quantile: float = 0.95
    seed: int = 0
    meaningful_sensitivity: float = 0.025
    sensitivity_scale: float = 0.10
    evidence_uncertainty_scale: float = 0.20
    freshness_uncertainty_scale: float = 0.15
    structural_uncertainty_scale: float = 0.35
    sparse_uncertainty_scale: float = 0.25
    reference_uncertainty_scale: float = 0.35

    def __post_init__(self) -> None:
        for label, string_value in (
            ("T14 name", self.name),
            ("T14 version", self.version),
            ("T14 calibration version", self.calibration_version),
            ("T14 algorithm version", self.algorithm_version),
            ("T14 feature version", self.feature_version),
        ):
            _text(string_value, label)
        for label, numeric_value in (
            ("T14 ridge", self.ridge),
            ("T14 maximum count mean", self.maximum_count_mean),
            ("T14 meaningful sensitivity", self.meaningful_sensitivity),
            ("T14 sensitivity scale", self.sensitivity_scale),
            ("T14 evidence uncertainty scale", self.evidence_uncertainty_scale),
            ("T14 freshness uncertainty scale", self.freshness_uncertainty_scale),
            ("T14 structural uncertainty scale", self.structural_uncertainty_scale),
            ("T14 sparse uncertainty scale", self.sparse_uncertainty_scale),
            ("T14 reference uncertainty scale", self.reference_uncertainty_scale),
        ):
            if not math.isfinite(float(numeric_value)) or float(numeric_value) <= 0:
                raise T14ValidationError(f"{label} must be positive and finite.")
        if not 0 < self.minimum_slope <= self.maximum_slope:
            raise T14ValidationError("T14 calibration slope bounds are invalid.")
        if (
            isinstance(self.minimum_calibration_matches, bool)
            or self.minimum_calibration_matches < 1
            or isinstance(self.parameter_draws, bool)
            or self.parameter_draws < 1
        ):
            raise T14ValidationError("T14 calibration sample and draw counts must be positive.")
        if not 0.0 <= self.lower_quantile < self.upper_quantile <= 1.0:
            raise T14ValidationError("T14 probability interval quantiles are invalid.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise T14ValidationError("T14 seed must be an integer.")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "calibration_version": self.calibration_version,
            "evidence_uncertainty_scale": self.evidence_uncertainty_scale,
            "feature_version": self.feature_version,
            "freshness_uncertainty_scale": self.freshness_uncertainty_scale,
            "lower_quantile": self.lower_quantile,
            "maximum_count_mean": self.maximum_count_mean,
            "maximum_slope": self.maximum_slope,
            "meaningful_sensitivity": self.meaningful_sensitivity,
            "minimum_calibration_matches": self.minimum_calibration_matches,
            "minimum_slope": self.minimum_slope,
            "name": self.name,
            "parameter_draws": self.parameter_draws,
            "reference_uncertainty_scale": self.reference_uncertainty_scale,
            "ridge": self.ridge,
            "seed": self.seed,
            "sensitivity_scale": self.sensitivity_scale,
            "sparse_uncertainty_scale": self.sparse_uncertainty_scale,
            "structural_uncertainty_scale": self.structural_uncertainty_scale,
            "upper_quantile": self.upper_quantile,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


def _surface(
    value: object, label: str = "T14 distribution surface"
) -> tuple[tuple[float, ...], ...]:
    rows = _sequence(value)
    if not rows:
        raise T14ValidationError(f"{label} must be a non-empty square array.")
    selected: list[tuple[float, ...]] = []
    for row in rows:
        cells = _sequence(row)
        if not cells:
            raise T14ValidationError(f"{label} rows must be non-empty arrays.")
        selected.append(tuple(_number(cell, f"{label} value") for cell in cells))
    if any(len(row) != len(selected) for row in selected):
        raise T14ValidationError(f"{label} must be square.")
    if any(value < 0 for row in selected for value in row):
        raise T14ValidationError(f"{label} cannot contain negative values.")
    total = sum(sum(row) for row in selected)
    if not math.isfinite(total) or total <= 0:
        raise T14ValidationError(f"{label} must have positive finite mass.")
    return tuple(selected)


def _normalise_surface(value: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    rows = _surface(value)
    total = sum(sum(row) for row in rows)
    normalised = tuple(tuple(max(0.0, float(cell) / total) for cell in row) for row in rows)
    final_total = sum(sum(row) for row in normalised)
    if not math.isfinite(final_total) or final_total <= 0:
        raise T14ValidationError("T14 normalized surface has invalid mass.")
    return tuple(tuple(cell / final_total for cell in row) for row in normalised)


@dataclass(frozen=True)
class DistributionInput:
    """Small public adapter for a T11/T12/T13-like count distribution."""

    family: ModelFamily | str
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    surface: tuple[tuple[float, ...], ...]
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    feature_inputs: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    artifact_digest: str | None = None
    distribution_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _normalise_family(self.family))
        _text(self.target_fixture_id, "T14 target fixture ID")
        _text(self.matchweek_id, "T14 matchweek ID")
        _text(self.model_version, "T14 model version")
        _text(self.model_digest, "T14 model digest")
        object.__setattr__(self, "surface", _normalise_surface(self.surface))
        object.__setattr__(self, "uncertainty", _freeze_map(self.uncertainty))
        object.__setattr__(self, "feature_inputs", _freeze_map(self.feature_inputs))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        if self.artifact_digest is not None:
            _text(self.artifact_digest, "T14 artifact digest")
        expected = _digest(self._core_dict(include_digest=False))
        if self.distribution_digest and self.distribution_digest != expected:
            raise T14IntegrityError("T14 distribution input digest does not match its content.")
        object.__setattr__(self, "distribution_digest", expected)

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "artifact_digest": self.artifact_digest,
            "diagnostics": dict(self.diagnostics),
            "family": _enum_value(self.family),
            "feature_inputs": dict(self.feature_inputs),
            "matchweek_id": self.matchweek_id,
            "model_digest": self.model_digest,
            "model_version": self.model_version,
            "surface": self.surface,
            "target_fixture_id": self.target_fixture_id,
            "uncertainty": dict(self.uncertainty),
        }
        if include_digest:
            payload["distribution_digest"] = self.distribution_digest
        return payload

    @property
    def digest(self) -> str:
        return self.distribution_digest

    def to_dict(self) -> dict[str, object]:
        return self._core_dict()

    @classmethod
    def from_model_output(
        cls, value: object, *, family: ModelFamily | str | None = None
    ) -> DistributionInput:
        parts = _coerce_distribution(value, family=family)
        if parts.status is not T14Status.AVAILABLE:
            raise T14ValidationError(parts.reason or "T14 model distribution unavailable.")
        return cls(
            family=parts.family,
            target_fixture_id=parts.target_fixture_id,
            matchweek_id=parts.matchweek_id,
            model_version=parts.model_version,
            model_digest=parts.model_digest,
            surface=parts.surface,
            uncertainty=parts.uncertainty,
            feature_inputs=parts.feature_inputs,
            diagnostics=parts.diagnostics,
            artifact_digest=parts.artifact_digest,
        )


@dataclass(frozen=True)
class CalibrationObservation:
    """One chronological, cutoff-replayable calibration observation."""

    fixture_id: str
    family: ModelFamily | str
    kickoff_utc: str
    distribution: object | None = None
    observed_home_count: int | None = None
    observed_away_count: int | None = None
    observed_total_count: int | None = None
    prediction_cutoff_utc: str | None = None
    outcome_utc: str | None = None
    model_training_fixture_ids: tuple[str, ...] = ()
    model_training_input_ids: tuple[str, ...] = ()
    model_version: str | None = None
    model_digest: str | None = None
    evidence_state_digest: str | None = None
    source_input_ids: tuple[str, ...] = ()
    source_input_digests: tuple[str, ...] = ()
    settlement_results: Mapping[str, str] = field(default_factory=dict)
    predicted_home_mean: float | None = None
    predicted_away_mean: float | None = None
    predicted_total_mean: float | None = None
    observed_home_goals: int | None = None
    observed_away_goals: int | None = None
    observed_total_goals: int | None = None
    actual_home_count: int | None = None
    actual_away_count: int | None = None
    actual_total_count: int | None = None
    record_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.fixture_id, "T14 calibration fixture ID")
        object.__setattr__(self, "family", _normalise_family(self.family))
        object.__setattr__(self, "kickoff_utc", _canonical_utc(self.kickoff_utc))
        if self.prediction_cutoff_utc is not None:
            object.__setattr__(
                self, "prediction_cutoff_utc", _canonical_utc(self.prediction_cutoff_utc)
            )
        if self.outcome_utc is not None:
            object.__setattr__(self, "outcome_utc", _canonical_utc(self.outcome_utc))
        for name in (
            "observed_home_count",
            "observed_away_count",
            "observed_total_count",
            "observed_home_goals",
            "observed_away_goals",
            "observed_total_goals",
            "actual_home_count",
            "actual_away_count",
            "actual_total_count",
        ):
            object.__setattr__(
                self,
                name,
                _non_negative_int(getattr(self, name), f"T14 {name}"),
            )
        for name in (
            "predicted_home_mean",
            "predicted_away_mean",
            "predicted_total_mean",
        ):
            raw = getattr(self, name)
            object.__setattr__(self, name, _optional_number(raw))
            if raw is not None and getattr(self, name) is None:
                raise T14ValidationError(f"T14 {name} must be finite.")
        for name in (
            "model_training_fixture_ids",
            "model_training_input_ids",
            "source_input_ids",
            "source_input_digests",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name)))
        if self.model_version is not None:
            object.__setattr__(
                self, "model_version", _text(self.model_version, "T14 model version")
            )
        if self.model_digest is not None:
            object.__setattr__(self, "model_digest", _text(self.model_digest, "T14 model digest"))
        if self.evidence_state_digest is not None:
            object.__setattr__(
                self,
                "evidence_state_digest",
                _text(self.evidence_state_digest, "T14 evidence digest"),
            )
        normalized_results = {
            str(key): _enum_value(value).upper() for key, value in self.settlement_results.items()
        }
        if any(
            value not in {"WIN", "LOSS", "PUSH", "VOID"} for value in normalized_results.values()
        ):
            raise T14ValidationError("T14 settlement results must be WIN, LOSS, PUSH, or VOID.")
        object.__setattr__(self, "settlement_results", MappingProxyType(normalized_results))
        if self.observed_total_count is None and self.observed_total_goals is not None:
            object.__setattr__(self, "observed_total_count", self.observed_total_goals)
        if self.observed_home_count is None and self.observed_home_goals is not None:
            object.__setattr__(self, "observed_home_count", self.observed_home_goals)
        if self.observed_away_count is None and self.observed_away_goals is not None:
            object.__setattr__(self, "observed_away_count", self.observed_away_goals)
        if self.observed_total_count is None and (
            self.observed_home_count is not None and self.observed_away_count is not None
        ):
            object.__setattr__(
                self,
                "observed_total_count",
                self.observed_home_count + self.observed_away_count,
            )
        if self.actual_home_count is None and self.observed_home_count is not None:
            object.__setattr__(self, "actual_home_count", self.observed_home_count)
        if self.actual_away_count is None and self.observed_away_count is not None:
            object.__setattr__(self, "actual_away_count", self.observed_away_count)
        if self.actual_total_count is None:
            if self.observed_total_count is not None:
                object.__setattr__(self, "actual_total_count", self.observed_total_count)
            elif self.actual_home_count is not None and self.actual_away_count is not None:
                object.__setattr__(
                    self,
                    "actual_total_count",
                    self.actual_home_count + self.actual_away_count,
                )
        expected = _digest(self._payload(include_digest=False))
        if self.record_digest and self.record_digest != expected:
            raise T14IntegrityError(
                "T14 calibration observation digest does not match its content."
            )
        object.__setattr__(self, "record_digest", expected)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "actual_away_count": self.actual_away_count,
            "actual_home_count": self.actual_home_count,
            "actual_total_count": self.actual_total_count,
            "evidence_state_digest": self.evidence_state_digest,
            "fixture_id": self.fixture_id,
            "family": _enum_value(self.family),
            "kickoff_utc": self.kickoff_utc,
            "model_digest": self.model_digest,
            "model_training_fixture_ids": self.model_training_fixture_ids,
            "model_training_input_ids": self.model_training_input_ids,
            "model_version": self.model_version,
            "observed_away_count": self.observed_away_count,
            "observed_home_count": self.observed_home_count,
            "observed_total_count": self.observed_total_count,
            "outcome_utc": self.outcome_utc,
            "predicted_away_mean": self.predicted_away_mean,
            "predicted_home_mean": self.predicted_home_mean,
            "predicted_total_mean": self.predicted_total_mean,
            "prediction_cutoff_utc": self.prediction_cutoff_utc,
            "settlement_results": dict(self.settlement_results),
            "source_input_digests": self.source_input_digests,
            "source_input_ids": self.source_input_ids,
        }
        if include_digest:
            payload["record_digest"] = self.record_digest
        return payload

    @property
    def digest(self) -> str:
        return self.record_digest

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CalibrationObservation:
        distribution = value.get("distribution", value.get("prediction"))
        if distribution is None:
            distribution = value.get("predicted_distribution", value.get("model_output"))

        def first(*keys: str) -> object | None:
            for key in keys:
                if key in value:
                    return value[key]
            return None

        results = first("settlement_results", "outcomes", "settlements")
        return cls(
            fixture_id=_text(value.get("fixture_id", value.get("match_id")), "T14 fixture ID"),
            family=_normalise_family(
                cast(ModelFamily | str | None, first("family", "model_family"))
            ),
            kickoff_utc=_text(
                value.get("kickoff_utc", value.get("prediction_time_utc")),
                "T14 kickoff timestamp",
            ),
            distribution=distribution,
            observed_home_count=cast(int | None, first("observed_home_count", "home_count")),
            observed_away_count=cast(int | None, first("observed_away_count", "away_count")),
            observed_total_count=cast(int | None, first("observed_total_count", "total_count")),
            prediction_cutoff_utc=cast(str | None, first("prediction_cutoff_utc", "cutoff_utc")),
            outcome_utc=cast(str | None, first("outcome_utc", "settled_at_utc")),
            model_training_fixture_ids=tuple(
                item
                for item in _sequence(
                    first("model_training_fixture_ids", "training_input_fixture_ids")
                )
                if isinstance(item, str)
            ),
            model_training_input_ids=tuple(
                item
                for item in _sequence(first("model_training_input_ids", "training_input_ids"))
                if isinstance(item, str)
            ),
            model_version=cast(str | None, first("model_version")),
            model_digest=cast(str | None, first("model_digest", "distribution_digest")),
            evidence_state_digest=cast(
                str | None, first("evidence_state_digest", "frozen_evidence_digest")
            ),
            source_input_ids=tuple(
                item
                for item in _sequence(first("source_input_ids", "input_ids"))
                if isinstance(item, str)
            ),
            source_input_digests=tuple(
                item
                for item in _sequence(first("source_input_digests", "input_digests"))
                if isinstance(item, str)
            ),
            settlement_results=(
                cast(Mapping[str, str], results) if isinstance(results, Mapping) else {}
            ),
            predicted_home_mean=_optional_number(
                first("predicted_home_mean", "home_expected_goals", "home_expected_corners")
            ),
            predicted_away_mean=_optional_number(
                first("predicted_away_mean", "away_expected_goals", "away_expected_corners")
            ),
            predicted_total_mean=_optional_number(
                first(
                    "predicted_total_mean", "expected_goals", "expected_corners", "predicted_mean"
                )
            ),
            observed_home_goals=cast(int | None, first("observed_home_goals", "actual_home_goals")),
            observed_away_goals=cast(int | None, first("observed_away_goals", "actual_away_goals")),
            observed_total_goals=cast(
                int | None, first("observed_total_goals", "actual_total_goals")
            ),
            actual_home_count=cast(int | None, first("actual_home_count")),
            actual_away_count=cast(int | None, first("actual_away_count")),
            actual_total_count=cast(int | None, first("actual_total_count")),
        )

    @classmethod
    def from_prediction(
        cls,
        fixture_id: str,
        kickoff_utc: str,
        distribution: object,
        outcome: object,
        *,
        family: ModelFamily | str | None = None,
        prediction_cutoff_utc: str | None = None,
        model_training_fixture_ids: Iterable[str] = (),
        model_training_input_ids: Iterable[str] = (),
        evidence_state_digest: str | None = None,
    ) -> CalibrationObservation:
        selected_family = (
            _normalise_family(family)
            if family is not None
            else _coerce_distribution(distribution).family
        )
        home, away, total = _outcome_counts(outcome, selected_family)
        parts = _coerce_distribution(distribution, family=selected_family)
        return cls(
            fixture_id=fixture_id,
            family=selected_family,
            kickoff_utc=kickoff_utc,
            distribution=distribution,
            observed_home_count=home,
            observed_away_count=away,
            observed_total_count=total,
            prediction_cutoff_utc=prediction_cutoff_utc,
            model_training_fixture_ids=tuple(model_training_fixture_ids),
            model_training_input_ids=tuple(model_training_input_ids),
            model_version=parts.model_version,
            model_digest=parts.model_digest,
            evidence_state_digest=evidence_state_digest,
            predicted_home_mean=parts.home_mean,
            predicted_away_mean=parts.away_mean,
            predicted_total_mean=parts.total_mean,
        )

    def to_dict(self) -> dict[str, object]:
        return self._payload()


@dataclass(frozen=True)
class AffineCalibrationParameter:
    """One low-parameter affine map from predicted to observed count mean."""

    intercept: float
    slope: float
    sample_count: int
    residual_scale: float
    intercept_standard_error: float
    slope_standard_error: float

    def __post_init__(self) -> None:
        for label, value in (
            ("intercept", self.intercept),
            ("slope", self.slope),
            ("residual scale", self.residual_scale),
            ("intercept standard error", self.intercept_standard_error),
            ("slope standard error", self.slope_standard_error),
        ):
            if not math.isfinite(float(value)):
                raise T14ValidationError(f"T14 {label} must be finite.")
        if self.slope <= 0 or self.sample_count < 1:
            raise T14ValidationError("T14 affine calibration parameter is invalid.")

    def apply(self, mean: float, maximum: float) -> float:
        return _bounded(self.intercept + self.slope * mean, 0.0, maximum)

    def to_dict(self) -> dict[str, object]:
        return {
            "intercept": self.intercept,
            "intercept_standard_error": self.intercept_standard_error,
            "residual_scale": self.residual_scale,
            "sample_count": self.sample_count,
            "slope": self.slope,
            "slope_standard_error": self.slope_standard_error,
        }


def _unavailable_calibration(
    family: ModelFamily,
    config: T14Config,
    reason: str,
    *,
    diagnostics: Mapping[str, object] | None = None,
    records: Sequence[CalibrationObservation] = (),
) -> CalibrationFit:
    selected_diagnostics = dict(diagnostics or {})
    selected_diagnostics.setdefault("model_status_reason", reason)
    return CalibrationFit(
        status=T14Status.MODEL_UNAVAILABLE,
        family=family,
        calibration_version=config.calibration_version,
        fit_as_of_utc=None,
        development_end_utc=None,
        calibration_start_utc=None,
        calibration_end_utc=None,
        parameters={},
        used_fixture_ids=(),
        used_record_digests=(),
        training_input_ids=tuple(
            sorted({item for record in records for item in record.model_training_input_ids})
        ),
        training_input_digests=tuple(
            sorted({item for record in records for item in record.source_input_digests})
        ),
        diagnostics=selected_diagnostics,
        provenance={
            "calibration_training_fixture_ids": tuple(
                sorted({item for record in records for item in record.model_training_fixture_ids})
            ),
            "calibration_training_input_ids": tuple(
                sorted({item for record in records for item in record.model_training_input_ids})
            ),
            "config_digest": config.digest,
            "chronology_enforced": True,
            "source_input_ids": tuple(
                sorted({item for record in records for item in record.source_input_ids})
            ),
        },
        reason=reason,
    )


@dataclass(frozen=True)
class CalibrationFit:
    """An immutable chronological affine calibration fit."""

    status: T14Status
    family: ModelFamily | str
    calibration_version: str
    fit_as_of_utc: str | None
    development_end_utc: str | None
    calibration_start_utc: str | None
    calibration_end_utc: str | None
    parameters: Mapping[str, AffineCalibrationParameter]
    used_fixture_ids: tuple[str, ...] = ()
    used_record_digests: tuple[str, ...] = ()
    training_input_ids: tuple[str, ...] = ()
    training_input_digests: tuple[str, ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    provenance: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    fit_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _normalise_family(self.family))
        _text(self.calibration_version, "T14 calibration version")
        for name in (
            "fit_as_of_utc",
            "development_end_utc",
            "calibration_start_utc",
            "calibration_end_utc",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _canonical_utc(value))
        if not all(
            isinstance(value, AffineCalibrationParameter) for value in self.parameters.values()
        ):
            raise T14ValidationError("T14 calibration parameters must be typed affine parameters.")
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(sorted(self.parameters.items())))
        )
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        object.__setattr__(self, "provenance", _freeze_map(self.provenance))
        object.__setattr__(self, "used_fixture_ids", _strings(self.used_fixture_ids))
        object.__setattr__(self, "used_record_digests", _strings(self.used_record_digests))
        object.__setattr__(self, "training_input_ids", _strings(self.training_input_ids))
        object.__setattr__(self, "training_input_digests", _strings(self.training_input_digests))
        expected = _digest(self._core_dict(include_digest=False))
        if self.fit_digest and self.fit_digest != expected:
            raise T14IntegrityError("T14 calibration fit digest does not match its content.")
        object.__setattr__(self, "fit_digest", expected)

    @property
    def digest(self) -> str:
        return self.fit_digest

    @property
    def is_available(self) -> bool:
        return self.status is T14Status.AVAILABLE

    @property
    def model_unavailable(self) -> bool:
        return self.status is not T14Status.AVAILABLE

    @property
    def used_input_fixture_ids(self) -> tuple[str, ...]:
        return self.used_fixture_ids

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "calibration_end_utc": self.calibration_end_utc,
            "calibration_start_utc": self.calibration_start_utc,
            "calibration_version": self.calibration_version,
            "development_end_utc": self.development_end_utc,
            "diagnostics": dict(self.diagnostics),
            "family": _enum_value(self.family),
            "fit_as_of_utc": self.fit_as_of_utc,
            "parameters": {key: value.to_dict() for key, value in self.parameters.items()},
            "provenance": dict(self.provenance),
            "reason": self.reason,
            "status": self.status.value,
            "training_input_digests": self.training_input_digests,
            "training_input_ids": self.training_input_ids,
            "used_fixture_ids": self.used_fixture_ids,
            "used_record_digests": self.used_record_digests,
        }
        if include_digest:
            payload["fit_digest"] = self.fit_digest
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._core_dict()

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CalibrationFit:
        raw_parameters = value.get("parameters", {})
        if not isinstance(raw_parameters, Mapping):
            raise T14ValidationError("T14 calibration parameters are malformed.")
        parameters: dict[str, AffineCalibrationParameter] = {}
        for key, raw in raw_parameters.items():
            mapped = _mapping(raw, "T14 calibration parameter")
            sample_count = _non_negative_int(
                mapped.get("sample_count", 0), "T14 calibration sample count"
            )
            if sample_count is None:
                raise T14ValidationError("T14 calibration sample count is required.")
            parameters[str(key)] = AffineCalibrationParameter(
                intercept=_number(mapped.get("intercept"), "T14 intercept"),
                slope=_number(mapped.get("slope"), "T14 slope"),
                sample_count=sample_count,
                residual_scale=_number(mapped.get("residual_scale", 0.0)),
                intercept_standard_error=_number(mapped.get("intercept_standard_error", 0.0)),
                slope_standard_error=_number(mapped.get("slope_standard_error", 0.0)),
            )
        reason_value = value.get("reason")
        return cls(
            status=_status(value.get("status", T14Status.MODEL_UNAVAILABLE.value)),
            family=cast(ModelFamily | str, value.get("family")),
            calibration_version=_text(value.get("calibration_version"), "T14 calibration version"),
            fit_as_of_utc=cast(str | None, value.get("fit_as_of_utc")),
            development_end_utc=cast(str | None, value.get("development_end_utc")),
            calibration_start_utc=cast(str | None, value.get("calibration_start_utc")),
            calibration_end_utc=cast(str | None, value.get("calibration_end_utc")),
            parameters=parameters,
            used_fixture_ids=tuple(
                item for item in _sequence(value.get("used_fixture_ids")) if isinstance(item, str)
            ),
            used_record_digests=tuple(
                item
                for item in _sequence(value.get("used_record_digests"))
                if isinstance(item, str)
            ),
            training_input_ids=tuple(
                item for item in _sequence(value.get("training_input_ids")) if isinstance(item, str)
            ),
            training_input_digests=tuple(
                item
                for item in _sequence(value.get("training_input_digests"))
                if isinstance(item, str)
            ),
            diagnostics=_mapping(value.get("diagnostics", {}), "T14 calibration diagnostics"),
            provenance=_mapping(value.get("provenance", {}), "T14 calibration provenance"),
            reason=reason_value if isinstance(reason_value, str) else None,
            fit_digest=str(value.get("fit_digest", "")),
        )


def _coerce_observation(
    value: CalibrationObservation | Mapping[str, object],
) -> CalibrationObservation:
    if isinstance(value, CalibrationObservation):
        return value
    if isinstance(value, Mapping):
        return CalibrationObservation.from_mapping(value)
    raise T14ValidationError("T14 calibration observations must be typed records or objects.")


def _record_features(
    record: CalibrationObservation,
) -> tuple[Mapping[str, float], Mapping[str, int]] | None:
    try:
        parts = _coerce_distribution(record.distribution, family=record.family)
    except T14Error:
        parts = _DistributionParts(
            status=T14Status.AVAILABLE,
            family=_normalise_family(record.family),
            target_fixture_id=record.fixture_id,
            matchweek_id="calibration",
            model_version=record.model_version or "unknown",
            model_digest=record.model_digest or "unknown",
            surface=(),
            home_mean=record.predicted_home_mean,
            away_mean=record.predicted_away_mean,
            total_mean=record.predicted_total_mean,
            uncertainty={},
            feature_inputs={},
            diagnostics={},
            artifact_digest=None,
            reason=None,
        )
    predicted: dict[str, float] = {}
    observed: dict[str, int] = {}
    if record.predicted_home_mean is not None:
        predicted["home"] = record.predicted_home_mean
    elif parts.home_mean is not None:
        predicted["home"] = parts.home_mean
    if record.predicted_away_mean is not None:
        predicted["away"] = record.predicted_away_mean
    elif parts.away_mean is not None:
        predicted["away"] = parts.away_mean
    if record.predicted_total_mean is not None:
        predicted["total"] = record.predicted_total_mean
    elif parts.total_mean is not None:
        predicted["total"] = parts.total_mean

    home = record.actual_home_count
    if home is None:
        home = record.observed_home_count
    away = record.actual_away_count
    if away is None:
        away = record.observed_away_count
    total = record.actual_total_count
    if total is None:
        total = record.observed_total_count
    if total is None and home is not None and away is not None:
        total = home + away
    if home is not None:
        observed["home"] = home
    if away is not None:
        observed["away"] = away
    if total is not None:
        observed["total"] = total
    if (
        record.family is ModelFamily.FIRST_HALF_GOALS
        or record.family is ModelFamily.SECOND_HALF_GOALS
    ):
        if "total" not in predicted or "total" not in observed:
            return None
        return {"total": predicted["total"]}, {"total": observed["total"]}
    if record.family in {ModelFamily.FULL_TIME_GOALS, ModelFamily.CORNERS}:
        if not {"home", "away"}.issubset(predicted) or not {"home", "away"}.issubset(observed):
            return None
        return (
            {"home": predicted["home"], "away": predicted["away"]},
            {"home": observed["home"], "away": observed["away"]},
        )
    return None


def _fit_affine(
    pairs: Sequence[tuple[float, int]], config: T14Config
) -> AffineCalibrationParameter | None:
    if len(pairs) < config.minimum_calibration_matches:
        return None
    x_values = [float(item[0]) for item in pairs]
    y_values = [float(item[1]) for item in pairs]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    centered = sum((value - x_mean) ** 2 for value in x_values)
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=True))
    slope = covariance / (centered + config.ridge)
    slope = _bounded(slope, config.minimum_slope, config.maximum_slope)
    intercept = _bounded(
        y_mean - slope * x_mean, -config.maximum_count_mean, config.maximum_count_mean
    )
    residuals = [y - (intercept + slope * x) for x, y in zip(x_values, y_values, strict=True)]
    residual_scale = math.sqrt(
        sum(value * value for value in residuals) / max(1, len(residuals) - 2)
    )
    residual_scale = max(1e-6, residual_scale)
    slope_standard_error = residual_scale / math.sqrt(centered + config.ridge)
    intercept_standard_error = residual_scale * math.sqrt(
        1.0 / len(pairs) + (x_mean * x_mean) / (centered + config.ridge)
    )
    values = (
        intercept,
        slope,
        residual_scale,
        slope_standard_error,
        intercept_standard_error,
    )
    if any(not math.isfinite(value) for value in values):
        return None
    return AffineCalibrationParameter(
        intercept=intercept,
        slope=slope,
        sample_count=len(pairs),
        residual_scale=residual_scale,
        intercept_standard_error=intercept_standard_error,
        slope_standard_error=slope_standard_error,
    )


def _uncertainty_checks(
    used: Sequence[CalibrationObservation],
    pairs_by_dimension: Mapping[str, Sequence[tuple[float, int]]],
    parameters: Mapping[str, AffineCalibrationParameter],
    config: T14Config,
) -> Mapping[str, object]:
    """Run bounded chronological checks without resampling future rows."""

    if len(used) < 4:
        return {
            "rolling_origin": {"status": "INSUFFICIENT"},
            "parametric_bootstrap": {"status": "INSUFFICIENT"},
            "chronological_block": {"status": "INSUFFICIENT"},
            "widening_multiplier": 1.0,
        }
    rolling_values: list[float] = []
    for dimension, parameter in parameters.items():
        pairs = pairs_by_dimension.get(dimension, ())
        split = len(pairs) // 2
        if split < 1 or split >= len(pairs):
            continue
        early = sum(y for _, y in pairs[:split]) / split
        late = sum(y for _, y in pairs[split:]) / (len(pairs) - split)
        rolling_values.append(abs(late - early) / max(1.0, early, late))
        residuals = [float(y) - (parameter.intercept + parameter.slope * x) for x, y in pairs]
        rolling_values.append(
            (sum(value * value for value in residuals) / max(1, len(residuals))) ** 0.5
            / max(1.0, late)
        )
    rolling_signal = min(0.75, max(rolling_values, default=0.0))

    bootstrap_signals: list[float] = []
    rng = random.Random(config.seed + len(used))
    for dimension, pairs in pairs_by_dimension.items():
        bootstrap_parameter = parameters.get(dimension)
        if len(pairs) < 3 or bootstrap_parameter is None:
            continue
        slopes: list[float] = []
        for _ in range(12):
            sample = []
            for x, _ in pairs:
                fitted_mean = max(
                    0.0,
                    bootstrap_parameter.intercept + bootstrap_parameter.slope * x,
                )
                scale = max(
                    1e-6,
                    math.sqrt(fitted_mean + bootstrap_parameter.residual_scale**2),
                )
                simulated = max(0, round(rng.gauss(fitted_mean, scale)))
                sample.append((x, simulated))
            x_mean = sum(x for x, _ in sample) / len(sample)
            y_mean = sum(y for _, y in sample) / len(sample)
            denominator = sum((x - x_mean) ** 2 for x, _ in sample) + config.ridge
            slopes.append(sum((x - x_mean) * (y - y_mean) for x, y in sample) / denominator)
        bootstrap_signals.append(min(0.75, _std(slopes)))
    bootstrap_signal = max(bootstrap_signals, default=0.0)

    block_size = max(1, len(used) // 3)
    block_means: list[float] = []
    for start in range(0, len(used), block_size):
        block = used[start : start + block_size]
        values = [
            float(item.observed_total_count)
            for item in block
            if item.observed_total_count is not None
        ]
        if values:
            block_means.append(sum(values) / len(values))
    block_signal = min(
        0.75, _std(block_means) / max(1.0, sum(block_means) / max(1, len(block_means)))
    )
    widening = 1.0 + max(rolling_signal, bootstrap_signal, block_signal)
    return {
        "rolling_origin": {
            "status": "CHECKED",
            "relative_error_signal": rolling_signal,
            "chronological_order": tuple(item.fixture_id for item in used),
        },
        "parametric_bootstrap": {
            "status": "CHECKED",
            "relative_slope_signal": bootstrap_signal,
            "seed": config.seed + len(used),
            "draws": 12,
            "method": "parametric-affine-count-gaussian-v1",
        },
        "chronological_block": {
            "status": "CHECKED",
            "block_size": block_size,
            "relative_mean_signal": block_signal,
        },
        "widening_multiplier": widening,
    }


def fit_calibration(
    observations: Iterable[CalibrationObservation | Mapping[str, object]],
    *,
    family: ModelFamily | str | None = None,
    calibration_end_utc: str | None = None,
    fit_as_of_utc: str | None = None,
    as_of_utc: str | None = None,
    development_end_utc: str | None = None,
    config: T14Config | None = None,
    expected_model_version: str | None = None,
) -> CalibrationFit:
    """Fit calibration from only later chronological observations.

    Rows after ``calibration_end_utc`` or whose outcome is not known by that
    boundary are excluded.  A row whose model training inputs include its own
    fixture is excluded as outcome leakage.  The returned fit retains both
    included and excluded identities for audit.
    """

    selected_config = config or T14Config()
    if fit_as_of_utc is not None and as_of_utc is not None:
        raise T14ValidationError("T14 received two aliases for the fit cutoff.")
    if calibration_end_utc is not None and (fit_as_of_utc is not None or as_of_utc is not None):
        raise T14ValidationError("T14 received two aliases for the calibration cutoff.")
    boundary_text = calibration_end_utc or fit_as_of_utc or as_of_utc
    records: list[CalibrationObservation] = []
    malformed = False
    for raw in observations:
        try:
            records.append(_coerce_observation(raw))
        except T14Error, TypeError, ValueError:
            malformed = True
    if family is None:
        if not records:
            return _unavailable_calibration(
                ModelFamily.FULL_TIME_GOALS,
                selected_config,
                "MALFORMED_OR_EMPTY_CALIBRATION_DATA",
            )
        families = {_normalise_family(record.family) for record in records}
        if len(families) != 1:
            return _unavailable_calibration(
                ModelFamily.FULL_TIME_GOALS,
                selected_config,
                "CALIBRATION_FAMILY_REQUIRED_FOR_MIXED_DATA",
                records=records,
            )
        selected_family = next(iter(families))
    else:
        selected_family = _normalise_family(family)
    records = [record for record in records if _normalise_family(record.family) is selected_family]
    if not records or malformed:
        return _unavailable_calibration(
            selected_family,
            selected_config,
            "MALFORMED_OR_EMPTY_CALIBRATION_DATA",
            records=records,
        )
    if expected_model_version is not None:
        _text(expected_model_version, "T14 expected model version")
    if boundary_text is None:
        boundary = max(_parse_utc(record.kickoff_utc) for record in records)
        boundary_text = boundary.isoformat()
    boundary = _parse_utc(boundary_text)
    development_end = _parse_utc(development_end_utc) if development_end_utc else None
    if development_end is not None and development_end >= boundary:
        return _unavailable_calibration(
            selected_family,
            selected_config,
            "CALIBRATION_PERIOD_AFTER_BOUNDARY_IS_EMPTY",
            records=records,
        )

    ordered = sorted(records, key=lambda item: (item.kickoff_utc, item.fixture_id))
    used: list[CalibrationObservation] = []
    future_ids: list[str] = []
    leakage_ids: list[str] = []
    leakage_training_fixture_ids: dict[str, tuple[str, ...]] = {}
    post_development_ids: list[str] = []
    invalid_ids: list[str] = []
    known_kickoffs = {record.fixture_id: _parse_utc(record.kickoff_utc) for record in ordered}
    for record in ordered:
        kickoff = _parse_utc(record.kickoff_utc)
        if (
            record.prediction_cutoff_utc is not None
            and _parse_utc(record.prediction_cutoff_utc) >= kickoff
        ):
            invalid_ids.append(record.fixture_id)
            continue
        if record.outcome_utc is not None and _parse_utc(record.outcome_utc) < kickoff:
            invalid_ids.append(record.fixture_id)
            continue
        if (
            record.outcome_utc is not None
            and record.prediction_cutoff_utc is not None
            and _parse_utc(record.prediction_cutoff_utc) >= _parse_utc(record.outcome_utc)
        ):
            leakage_ids.append(record.fixture_id)
            leakage_training_fixture_ids[record.fixture_id] = ("OUTCOME_AT_PREDICTION_CUTOFF",)
            continue
        if kickoff > boundary or (
            record.outcome_utc is not None and _parse_utc(record.outcome_utc) > boundary
        ):
            future_ids.append(record.fixture_id)
            continue
        if (
            record.prediction_cutoff_utc is not None
            and _parse_utc(record.prediction_cutoff_utc) > boundary
        ):
            future_ids.append(record.fixture_id)
            continue
        if development_end is not None and kickoff <= development_end:
            post_development_ids.append(record.fixture_id)
            continue
        future_training_ids = tuple(
            sorted(
                training_id
                for training_id in record.model_training_fixture_ids
                if training_id in known_kickoffs and known_kickoffs[training_id] >= kickoff
            )
        )
        if record.fixture_id in set(record.model_training_fixture_ids):
            future_training_ids = tuple(sorted(set(future_training_ids) | {record.fixture_id}))
        if future_training_ids:
            leakage_ids.append(record.fixture_id)
            leakage_training_fixture_ids[record.fixture_id] = future_training_ids
            continue
        if expected_model_version is not None and record.model_version not in {
            None,
            expected_model_version,
        }:
            invalid_ids.append(record.fixture_id)
            continue
        if _record_features(record) is None:
            invalid_ids.append(record.fixture_id)
            continue
        used.append(record)
    if leakage_ids:
        return _unavailable_calibration(
            selected_family,
            selected_config,
            "OUTCOME_LEAKAGE_DETECTED",
            diagnostics={
                "leakage_fixture_ids": tuple(sorted(leakage_ids)),
                "leakage_training_fixture_ids": leakage_training_fixture_ids,
                "future_excluded_fixture_ids": tuple(sorted(future_ids)),
            },
            records=records,
        )
    if not used:
        return _unavailable_calibration(
            selected_family,
            selected_config,
            "NO_CHRONOLOGICAL_CALIBRATION_ROWS",
            diagnostics={
                "future_excluded_fixture_ids": tuple(sorted(future_ids)),
                "post_development_fixture_ids": tuple(sorted(post_development_ids)),
                "invalid_fixture_ids": tuple(sorted(invalid_ids)),
                "leakage_training_fixture_ids": leakage_training_fixture_ids,
            },
            records=records,
        )
    pairs_by_dimension: dict[str, list[tuple[float, int]]] = {}
    for record in used:
        features = _record_features(record)
        if features is None:
            continue
        predicted, observed = features
        for dimension in predicted:
            if dimension in observed:
                pairs_by_dimension.setdefault(dimension, []).append(
                    (predicted[dimension], observed[dimension])
                )
    parameters: dict[str, AffineCalibrationParameter] = {}
    missing_dimensions: list[str] = []
    required = (
        ("total",)
        if selected_family
        in {
            ModelFamily.FIRST_HALF_GOALS,
            ModelFamily.SECOND_HALF_GOALS,
        }
        else ("home", "away")
    )
    for dimension in required:
        parameter = _fit_affine(pairs_by_dimension.get(dimension, ()), selected_config)
        if parameter is None:
            missing_dimensions.append(dimension)
        else:
            parameters[dimension] = parameter
    if missing_dimensions:
        return _unavailable_calibration(
            selected_family,
            selected_config,
            "INSUFFICIENT_CALIBRATION_DATA",
            diagnostics={
                "future_excluded_fixture_ids": tuple(sorted(future_ids)),
                "post_development_fixture_ids": tuple(sorted(post_development_ids)),
                "invalid_fixture_ids": tuple(sorted(invalid_ids)),
                "used_fixture_ids": tuple(record.fixture_id for record in used),
                "missing_dimensions": tuple(missing_dimensions),
                "sample_counts": {key: len(value) for key, value in pairs_by_dimension.items()},
            },
            records=records,
        )
    first_used = used[0].kickoff_utc
    versions = tuple(
        sorted({record.model_version for record in used if record.model_version is not None})
    )
    digests = tuple(
        sorted({record.model_digest for record in used if record.model_digest is not None})
    )
    input_ids = tuple(sorted({item for record in used for item in record.model_training_input_ids}))
    training_fixture_ids = tuple(
        sorted({item for record in used for item in record.model_training_fixture_ids})
    )
    input_digests = tuple(sorted({item for record in used for item in record.source_input_digests}))
    diagnostics: dict[str, object] = {
        "chronological_order": tuple(record.fixture_id for record in used),
        "future_excluded_fixture_ids": tuple(sorted(future_ids)),
        "invalid_fixture_ids": tuple(sorted(invalid_ids)),
        "leakage_fixture_ids": tuple(sorted(leakage_ids)),
        "post_development_fixture_ids": tuple(sorted(post_development_ids)),
        "sample_counts": {key: len(value) for key, value in pairs_by_dimension.items()},
        "calibration_method": "affine_mean_exponential_tilt_v1",
        "outcome_fields_used": required,
        "uncertainty_checks": _uncertainty_checks(
            used,
            pairs_by_dimension,
            parameters,
            selected_config,
        ),
    }
    provenance = {
        "calibration_data_record_digests": tuple(record.digest for record in used),
        "calibration_model_digests": digests,
        "calibration_model_versions": versions,
        "calibration_training_fixture_ids": training_fixture_ids,
        "calibration_training_input_ids": input_ids,
        "chronology_enforced": True,
        "config_digest": selected_config.digest,
        "future_rows_excluded": tuple(sorted(future_ids)),
        "outcome_leakage_policy": "exclude_training_fixture_and_post_boundary_outcome",
        "source_input_ids": tuple(
            sorted({item for record in used for item in record.source_input_ids})
        ),
        "source_input_digests": input_digests,
    }
    return CalibrationFit(
        status=T14Status.AVAILABLE,
        family=selected_family,
        calibration_version=selected_config.calibration_version,
        fit_as_of_utc=boundary.isoformat(),
        development_end_utc=development_end.isoformat() if development_end else None,
        calibration_start_utc=(
            (development_end + _seconds(1)).isoformat() if development_end else first_used
        ),
        calibration_end_utc=boundary.isoformat(),
        parameters=parameters,
        used_fixture_ids=tuple(record.fixture_id for record in used),
        used_record_digests=tuple(record.digest for record in used),
        training_input_ids=input_ids,
        training_input_digests=input_digests,
        diagnostics=diagnostics,
        provenance=provenance,
    )


def _seconds(value: int) -> timedelta:
    return timedelta(seconds=value)


@dataclass(frozen=True)
class _DistributionParts:
    status: T14Status
    family: ModelFamily
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    surface: tuple[tuple[float, ...], ...]
    home_mean: float | None
    away_mean: float | None
    total_mean: float | None
    uncertainty: Mapping[str, object]
    feature_inputs: Mapping[str, object]
    diagnostics: Mapping[str, object]
    artifact_digest: str | None
    reason: str | None


def _get(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _available(value: object) -> bool:
    selected = _get(value, "is_available", None)
    if isinstance(selected, bool):
        return selected
    selected_status = _get(value, "status", T14Status.AVAILABLE)
    try:
        return _status(selected_status) is T14Status.AVAILABLE
    except T14Error:
        return False


def _coerce_distribution(
    value: object, *, family: ModelFamily | str | None = None
) -> _DistributionParts:
    if isinstance(value, DistributionInput):
        return _DistributionParts(
            status=T14Status.AVAILABLE,
            family=_normalise_family(value.family),
            target_fixture_id=value.target_fixture_id,
            matchweek_id=value.matchweek_id,
            model_version=value.model_version,
            model_digest=value.model_digest,
            surface=value.surface,
            home_mean=_surface_mean(value.surface, "home"),
            away_mean=_surface_mean(value.surface, "away"),
            total_mean=_surface_mean(value.surface, "total"),
            uncertainty=value.uncertainty,
            feature_inputs=value.feature_inputs,
            diagnostics=value.diagnostics,
            artifact_digest=value.artifact_digest,
            reason=None,
        )
    selected_family = _normalise_family(family) if family is not None else None
    if selected_family is None:
        phase = _get(value, "phase", None)
        if phase is not None:
            phase_token = _enum_value(phase).upper()
            selected_family = (
                ModelFamily.FIRST_HALF_GOALS
                if "FIRST" in phase_token
                else ModelFamily.SECOND_HALF_GOALS
            )
        elif _get(value, "joint_corner_distribution", None) is not None:
            selected_family = ModelFamily.CORNERS
        else:
            selected_family = ModelFamily.FULL_TIME_GOALS
    target_fixture_id = str(
        _get(value, "target_fixture_id", _get(value, "fixture_id", "unknown-fixture"))
    )
    matchweek_id = str(_get(value, "matchweek_id", "unknown-matchweek"))
    model_version = str(_get(value, "model_version", "unknown-model-version"))
    model_digest = str(
        _get(
            value,
            "model_digest",
            _get(value, "distribution_digest", _get(value, "digest", "unknown-model-digest")),
        )
    )
    raw_surface = _get(value, "surface", None)
    if raw_surface is None:
        raw_surface = _get(value, "joint_corner_distribution", None)
    if raw_surface is None:
        raw_surface = _get(value, "score_distribution", None)
    if raw_surface is None:
        raw_surface = _get(value, "joint_distribution", None)
    if raw_surface is None:
        raw_surface = _get(value, "corner_distribution", None)
    try:
        selected_surface = _normalise_surface(cast(Sequence[Sequence[float]], raw_surface))
    except (T14Error, TypeError, ValueError) as error:
        return _DistributionParts(
            status=T14Status.MODEL_UNAVAILABLE,
            family=selected_family,
            target_fixture_id=target_fixture_id,
            matchweek_id=matchweek_id,
            model_version=model_version,
            model_digest=model_digest,
            surface=(),
            home_mean=None,
            away_mean=None,
            total_mean=None,
            uncertainty=_mapping(_get(value, "uncertainty", {}), "T14 model uncertainty"),
            feature_inputs=_mapping(_get(value, "feature_inputs", {}), "T14 feature inputs"),
            diagnostics=_mapping(_get(value, "diagnostics", {}), "T14 model diagnostics"),
            artifact_digest=(
                str(_get(value, "artifact_digest"))
                if _get(value, "artifact_digest") is not None
                else None
            ),
            reason=f"INVALID_MODEL_DISTRIBUTION:{error}",
        )
    if not _available(value):
        return _DistributionParts(
            status=T14Status.MODEL_UNAVAILABLE,
            family=selected_family,
            target_fixture_id=target_fixture_id,
            matchweek_id=matchweek_id,
            model_version=model_version,
            model_digest=model_digest,
            surface=(),
            home_mean=None,
            away_mean=None,
            total_mean=None,
            uncertainty=_mapping(_get(value, "uncertainty", {}), "T14 model uncertainty"),
            feature_inputs=_mapping(_get(value, "feature_inputs", {}), "T14 feature inputs"),
            diagnostics=_mapping(_get(value, "diagnostics", {}), "T14 model diagnostics"),
            artifact_digest=None,
            reason=str(_get(value, "reason", "MODEL_UNAVAILABLE")),
        )
    return _DistributionParts(
        status=T14Status.AVAILABLE,
        family=selected_family,
        target_fixture_id=target_fixture_id,
        matchweek_id=matchweek_id,
        model_version=model_version,
        model_digest=model_digest,
        surface=selected_surface,
        home_mean=_surface_mean(selected_surface, "home"),
        away_mean=_surface_mean(selected_surface, "away"),
        total_mean=_surface_mean(selected_surface, "total"),
        uncertainty=_mapping(_get(value, "uncertainty", {}), "T14 model uncertainty"),
        feature_inputs=_mapping(_get(value, "feature_inputs", {}), "T14 feature inputs"),
        diagnostics=_mapping(_get(value, "diagnostics", {}), "T14 model diagnostics"),
        artifact_digest=(
            str(_get(value, "artifact_digest"))
            if _get(value, "artifact_digest") is not None
            else None
        ),
        reason=None,
    )


def _surface_mean(surface: Sequence[Sequence[float]], dimension: str) -> float:
    if not surface:
        return 0.0
    result = 0.0
    for home, row in enumerate(surface):
        for away, probability in enumerate(row):
            value = home if dimension == "home" else away if dimension == "away" else home + away
            result += value * probability
    return result


def _outcome_counts(
    value: object, family: ModelFamily
) -> tuple[int | None, int | None, int | None]:
    if isinstance(value, Mapping):

        def raw(*keys: str) -> object | None:
            for key in keys:
                if key in value:
                    return cast(object, value[key])
            return None

        home = raw(
            "observed_home_count",
            "home_count",
            "home_goals",
            "full_time_home_goals",
            "half_time_home_goals",
            "corners_home",
        )
        away = raw(
            "observed_away_count",
            "away_count",
            "away_goals",
            "full_time_away_goals",
            "half_time_away_goals",
            "corners_away",
        )
        total = raw(
            "observed_total_count",
            "total_count",
            "total_goals",
            "half_time_total_goals",
            "total_corners",
        )
    else:
        home = _get(
            value,
            "observed_home_count",
            _get(
                value,
                "home_goals",
                _get(
                    value,
                    "full_time_home_goals",
                    _get(value, "half_time_home_goals", _get(value, "corners_home", None)),
                ),
            ),
        )
        away = _get(
            value,
            "observed_away_count",
            _get(
                value,
                "away_goals",
                _get(
                    value,
                    "full_time_away_goals",
                    _get(value, "half_time_away_goals", _get(value, "corners_away", None)),
                ),
            ),
        )
        total = _get(
            value,
            "observed_total_count",
            _get(
                value,
                "total_goals",
                _get(value, "half_time_total_goals", _get(value, "total_corners", None)),
            ),
        )
    if family is ModelFamily.SECOND_HALF_GOALS:

        def raw(*keys: str) -> object | None:
            if isinstance(value, Mapping):
                for key in keys:
                    if key in value:
                        return cast(object, value[key])
                return None
            for key in keys:
                selected = _get(value, key, None)
                if selected is not None:
                    return selected
            return None

        explicit_home = raw("second_half_home_count", "second_half_home_goals")
        explicit_away = raw("second_half_away_count", "second_half_away_goals")
        explicit_total = raw(
            "observed_total_count",
            "total_count",
            "second_half_total_count",
            "second_half_total_goals",
        )
        if explicit_home is not None and explicit_away is not None:
            home = explicit_home
            away = explicit_away
        else:
            full_home = raw("full_time_home_goals", "full_time_home_count")
            full_away = raw("full_time_away_goals", "full_time_away_count")
            half_home = raw("half_time_home_goals", "half_time_home_count")
            half_away = raw("half_time_away_goals", "half_time_away_count")
            if (
                full_home is not None
                and full_away is not None
                and half_home is not None
                and half_away is not None
            ):
                full_home_count = _non_negative_int(full_home, "T14 full-time home outcome")
                full_away_count = _non_negative_int(full_away, "T14 full-time away outcome")
                half_home_count = _non_negative_int(half_home, "T14 half-time home outcome")
                half_away_count = _non_negative_int(half_away, "T14 half-time away outcome")
                if (
                    full_home_count is not None
                    and full_away_count is not None
                    and half_home_count is not None
                    and half_away_count is not None
                ):
                    home = full_home_count - half_home_count
                    away = full_away_count - half_away_count
        if explicit_total is not None:
            total = explicit_total
    home_count = _non_negative_int(home, "T14 outcome home count")
    away_count = _non_negative_int(away, "T14 outcome away count")
    total_count = _non_negative_int(total, "T14 outcome total count")
    if total_count is None and home_count is not None and away_count is not None:
        total_count = home_count + away_count
    if family in {ModelFamily.FIRST_HALF_GOALS, ModelFamily.SECOND_HALF_GOALS}:
        return None, None, total_count
    return home_count, away_count, total_count


def _solve_tilt_vector(base: Sequence[float], target_mean: float) -> tuple[float, ...]:
    selected = tuple(max(0.0, float(value)) for value in base)
    total = sum(selected)
    if total <= 0 or not math.isfinite(total):
        raise T14ValidationError("T14 cannot tilt a zero-mass count distribution.")
    selected = tuple(value / total for value in selected)
    support = tuple(index for index, value in enumerate(selected) if value > 0)
    if not support:
        raise T14ValidationError("T14 count distribution has no support.")
    target = _bounded(float(target_mean), float(min(support)), float(max(support)))
    if abs(target - min(support)) <= 1e-12:
        output = [0.0] * len(selected)
        output[min(support)] = 1.0
        return tuple(output)
    if abs(target - max(support)) <= 1e-12:
        output = [0.0] * len(selected)
        output[max(support)] = 1.0
        return tuple(output)

    def weighted(theta: float) -> tuple[tuple[float, ...], float]:
        logs = [
            math.log(value) + theta * index if value > 0 else -math.inf
            for index, value in enumerate(selected)
        ]
        maximum = max(logs)
        weights = [math.exp(value - maximum) if math.isfinite(value) else 0.0 for value in logs]
        mass = sum(weights)
        if mass <= 0 or not math.isfinite(mass):
            raise T14ValidationError("T14 exponential tilt became numerically unstable.")
        probabilities = tuple(value / mass for value in weights)
        mean = sum(index * value for index, value in enumerate(probabilities))
        return probabilities, mean

    low, high = -40.0, 40.0
    for _ in range(48):
        midpoint = (low + high) / 2.0
        _, mean = weighted(midpoint)
        if mean < target:
            low = midpoint
        else:
            high = midpoint
    return weighted((low + high) / 2.0)[0]


def _tilt_surface(
    base: Sequence[Sequence[float]], family: ModelFamily, target_means: Mapping[str, float]
) -> tuple[tuple[float, ...], ...]:
    selected = _normalise_surface(base)
    if family in {ModelFamily.FIRST_HALF_GOALS, ModelFamily.SECOND_HALF_GOALS}:
        target = target_means["total"]
        current_total = _surface_mean(selected, "total")
        if abs(current_total - target) <= 1e-12:
            return selected
        # The total is a one-dimensional sufficient statistic.  The same
        # scalar tilt on both axes preserves the home/away conditional shape.
        low, high = -40.0, 40.0

        def weighted(theta: float) -> tuple[tuple[tuple[float, ...], ...], float]:
            raw: list[list[float]] = []
            maximum = max(
                math.log(value) + theta * (home + away)
                for home, row in enumerate(selected)
                for away, value in enumerate(row)
                if value > 0
            )
            mass = 0.0
            for home, row in enumerate(selected):
                output_row: list[float] = []
                for away, value in enumerate(row):
                    selected_value = (
                        math.exp(math.log(value) + theta * (home + away) - maximum)
                        if value > 0
                        else 0.0
                    )
                    output_row.append(selected_value)
                    mass += selected_value
                raw.append(output_row)
            probabilities = tuple(tuple(value / mass for value in row) for row in raw)
            return probabilities, _surface_mean(probabilities, "total")

        min_total = min(
            home + away
            for home, row in enumerate(selected)
            for away, value in enumerate(row)
            if value > 0
        )
        max_total = max(
            home + away
            for home, row in enumerate(selected)
            for away, value in enumerate(row)
            if value > 0
        )
        target = _bounded(target, float(min_total), float(max_total))
        for _ in range(48):
            midpoint = (low + high) / 2.0
            _, mean = weighted(midpoint)
            if mean < target:
                low = midpoint
            else:
                high = midpoint
        return weighted((low + high) / 2.0)[0]

    targets = {"home": target_means["home"], "away": target_means["away"]}
    current = selected
    for _ in range(8):
        home_marginal = [sum(row) for row in current]
        tilted_home = _solve_tilt_vector(home_marginal, targets["home"])
        home_scale = [
            tilted_home[home] / home_marginal[home] if home_marginal[home] > 0 else 0.0
            for home in range(len(current))
        ]
        current = tuple(
            tuple(row[away] * home_scale[home] for away in range(len(row)))
            for home, row in enumerate(current)
        )
        current = _normalise_surface(current)
        away_marginal = [
            sum(current[home][away] for home in range(len(current))) for away in range(len(current))
        ]
        tilted_away = _solve_tilt_vector(away_marginal, targets["away"])
        away_scale = [
            tilted_away[away] / away_marginal[away] if away_marginal[away] > 0 else 0.0
            for away in range(len(current))
        ]
        current = tuple(
            tuple(row[away] * away_scale[away] for away in range(len(row))) for row in current
        )
        current = _normalise_surface(current)
        if (
            abs(_surface_mean(current, "home") - targets["home"]) < 1e-10
            and abs(_surface_mean(current, "away") - targets["away"]) < 1e-10
        ):
            break
    return current


def _preference_set(family: ModelFamily) -> tuple[BettingPreference, ...]:
    if family is ModelFamily.FULL_TIME_GOALS:
        allowed = {
            PreferenceFamily.MATCH_WINNER,
            PreferenceFamily.DOUBLE_CHANCE,
            PreferenceFamily.MATCH_GOALS_OVER,
            PreferenceFamily.HOME_TEAM_GOALS_OVER,
            PreferenceFamily.AWAY_TEAM_GOALS_OVER,
            PreferenceFamily.ASIAN_HANDICAP,
        }
        return tuple(item for item in DEFAULT_PREFERENCE_CATALOG if item.family in allowed)
    if family is ModelFamily.CORNERS:
        allowed = {
            PreferenceFamily.CORNER_WINNER,
            PreferenceFamily.TOTAL_CORNERS_OVER,
            PreferenceFamily.HOME_CORNERS_OVER,
            PreferenceFamily.AWAY_CORNERS_OVER,
        }
        return tuple(item for item in DEFAULT_PREFERENCE_CATALOG if item.family in allowed)
    preference_id = (
        "first_half_over_1_5" if family is ModelFamily.FIRST_HALF_GOALS else "second_half_over_1_5"
    )
    return tuple(item for item in DEFAULT_PREFERENCE_CATALOG if item.preference_id == preference_id)


def _settle_surface(
    preference: BettingPreference, surface: Sequence[Sequence[float]]
) -> SettlementProbabilities:
    win = 0.0
    loss = 0.0
    push = 0.0
    for home, row in enumerate(surface):
        for away, probability in enumerate(row):
            value = float(probability)
            selected = False
            if preference.family is PreferenceFamily.MATCH_WINNER:
                selected = (
                    home > away
                    if preference.selection == "Home"
                    else away > home
                    if preference.selection == "Away"
                    else home == away
                )
            elif preference.family is PreferenceFamily.DOUBLE_CHANCE:
                selected = (
                    home >= away
                    if preference.selection == "1X"
                    else away >= home
                    if preference.selection == "X2"
                    else home != away
                )
            elif preference.family in {
                PreferenceFamily.MATCH_GOALS_OVER,
                PreferenceFamily.FIRST_HALF_OVER,
                PreferenceFamily.SECOND_HALF_OVER,
            }:
                assert preference.line is not None
                selected = home + away > preference.line
            elif preference.family is PreferenceFamily.HOME_TEAM_GOALS_OVER:
                assert preference.line is not None
                selected = home > preference.line
            elif preference.family is PreferenceFamily.AWAY_TEAM_GOALS_OVER:
                assert preference.line is not None
                selected = away > preference.line
            elif preference.family is PreferenceFamily.CORNER_WINNER:
                selected = (
                    home > away
                    if preference.selection == "Home"
                    else away > home
                    if preference.selection == "Away"
                    else home == away
                )
            elif preference.family is PreferenceFamily.TOTAL_CORNERS_OVER:
                assert preference.line is not None
                selected = home + away > preference.line
            elif preference.family is PreferenceFamily.HOME_CORNERS_OVER:
                assert preference.line is not None
                selected = home > preference.line
            elif preference.family is PreferenceFamily.AWAY_CORNERS_OVER:
                assert preference.line is not None
                selected = away > preference.line
            elif preference.family is PreferenceFamily.ASIAN_HANDICAP:
                assert preference.line is not None
                difference = home - away if preference.selection == "Home" else away - home
                adjusted = 2.0 * difference + 2.0 * preference.line
                if adjusted > 0:
                    win += value
                elif adjusted < 0:
                    loss += value
                else:
                    push += value
                continue
            if selected:
                win += value
            else:
                loss += value
    total = win + loss + push
    if not math.isfinite(total) or total <= 0:
        raise T14ValidationError("T14 settlement mass is invalid.")
    win /= total
    push /= total
    loss = max(0.0, 1.0 - win - push)
    return SettlementProbabilities(win, loss, push)


def _settlement_distributions(
    family: ModelFamily, surface: Sequence[Sequence[float]]
) -> Mapping[str, SettlementProbabilities]:
    return MappingProxyType(
        {
            preference.preference_id: _settle_surface(preference, surface)
            for preference in _preference_set(family)
        }
    )


@dataclass(frozen=True)
class ProbabilityInterval:
    """Settlement-aware interval for one probability class."""

    estimated: float
    lower: float
    upper: float
    standard_deviation: float
    lower_quantile: float
    upper_quantile: float

    def __post_init__(self) -> None:
        values = (
            self.estimated,
            self.lower,
            self.upper,
            self.standard_deviation,
            self.lower_quantile,
            self.upper_quantile,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise T14ValidationError("T14 probability intervals must be finite.")
        if not 0 <= self.lower <= 1 or not 0 <= self.estimated <= 1 or not 0 <= self.upper <= 1:
            raise T14ValidationError("T14 probability interval bounds are invalid.")
        if self.lower > self.estimated + 1e-9 or self.upper < self.estimated - 1e-9:
            raise T14ValidationError("T14 probability interval ordering is invalid.")
        if self.standard_deviation < 0:
            raise T14ValidationError("T14 probability interval spread cannot be negative.")

    def to_dict(self) -> dict[str, float]:
        return {
            "estimated": self.estimated,
            "lower": self.lower,
            "lower_quantile": self.lower_quantile,
            "standard_deviation": self.standard_deviation,
            "upper": self.upper,
            "upper_quantile": self.upper_quantile,
        }


@dataclass(frozen=True)
class LaplaceParameterUncertainty:
    """Diagonal Laplace approximation around a penalized MAP prediction."""

    family: ModelFamily | str
    parameter_names: tuple[str, ...]
    mean: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    hessian: tuple[tuple[float, ...], ...]
    penalty_precision: tuple[float, ...]
    effective_sample_size: float
    sparse_multiplier: float
    seed: int
    draw_count: int
    method: str = "laplace-penalized-map-diagonal-v1"
    draws_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _normalise_family(self.family))
        if len(self.parameter_names) != len(self.mean) or len(self.mean) != len(self.covariance):
            raise T14ValidationError("T14 Laplace parameter dimensions do not match.")
        if any(len(row) != len(self.mean) for row in self.covariance):
            raise T14ValidationError("T14 Laplace covariance must be square.")
        if len(self.penalty_precision) != len(self.mean):
            raise T14ValidationError("T14 Laplace penalty dimensions do not match.")
        if self.effective_sample_size <= 0 or self.sparse_multiplier < 1 or self.draw_count < 1:
            raise T14ValidationError("T14 Laplace uncertainty metadata is invalid.")
        expected = _digest(self._payload(include_digest=False))
        if self.draws_digest and self.draws_digest != expected:
            raise T14IntegrityError("T14 Laplace uncertainty digest does not match its content.")
        object.__setattr__(self, "draws_digest", expected)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "covariance": self.covariance,
            "draw_count": self.draw_count,
            "effective_sample_size": self.effective_sample_size,
            "family": _enum_value(self.family),
            "hessian": self.hessian,
            "mean": self.mean,
            "method": self.method,
            "parameter_names": self.parameter_names,
            "penalty_precision": self.penalty_precision,
            "seed": self.seed,
            "sparse_multiplier": self.sparse_multiplier,
        }
        if include_digest:
            payload["draws_digest"] = self.draws_digest
        return payload

    @property
    def digest(self) -> str:
        return self.draws_digest

    def parameter_draws(self) -> tuple[tuple[float, ...], ...]:
        rng = random.Random(self.seed)
        selected: list[tuple[float, ...]] = []
        standard_deviations = tuple(
            math.sqrt(max(0.0, self.covariance[index][index])) for index in range(len(self.mean))
        )
        for _ in range(self.draw_count):
            selected.append(
                tuple(
                    max(0.0, mean + rng.gauss(0.0, standard_deviations[index]))
                    for index, mean in enumerate(self.mean)
                )
            )
        return tuple(selected)

    @property
    def draws(self) -> tuple[tuple[float, ...], ...]:
        return self.parameter_draws()

    def to_dict(self) -> dict[str, object]:
        return self._payload()


def _numeric_uncertainty(value: object, keys: Sequence[str]) -> float | None:
    if isinstance(value, Mapping):
        for key in keys:
            selected = _optional_number(value.get(key))
            if selected is not None:
                return selected
    return None


def _sparse_multiplier(value: Mapping[str, object]) -> float:
    selected = _numeric_uncertainty(
        value,
        ("prediction_uncertainty_multiplier", "uncertainty_multiplier", "sparse_multiplier"),
    )
    teams = value.get("teams")
    team_multiplier = 1.0
    if isinstance(teams, Mapping):
        for team in teams.values():
            if isinstance(team, Mapping):
                candidate = _numeric_uncertainty(
                    team, ("uncertainty_multiplier", "sparse_multiplier")
                )
                if candidate is not None:
                    team_multiplier = max(team_multiplier, candidate)
                if team.get("borrowed_evidence") is True:
                    team_multiplier = max(team_multiplier, 1.25)
    return max(1.0, selected or 1.0, team_multiplier)


def build_laplace_uncertainty(
    family: ModelFamily | str,
    means: Mapping[str, float],
    *,
    model_fit: object | None = None,
    distribution_uncertainty: Mapping[str, object] | None = None,
    calibration_fit: CalibrationFit | None = None,
    config: T14Config | None = None,
    seed: int | None = None,
) -> LaplaceParameterUncertainty:
    """Build deterministic Laplace covariance from a penalized MAP fit.

    T11--T13 expose effective sample sizes, pooling multipliers, and penalty
    configuration in their immutable fit metadata.  T14 uses those values to
    form a conservative diagonal inverse-Hessian approximation for the
    predictive count means; calibration residual uncertainty is added to the
    same local Hessian rather than treated as independent model votes.
    """

    selected_config = config or T14Config()
    selected_family = _normalise_family(family)
    fit_uncertainty = _get(model_fit, "uncertainty", {}) if model_fit is not None else {}
    if not isinstance(fit_uncertainty, Mapping):
        fit_uncertainty = {}
    merged_uncertainty = dict(distribution_uncertainty or {})
    merged_uncertainty.update(fit_uncertainty)
    effective = _numeric_uncertainty(
        merged_uncertainty,
        (
            "training_effective_matches",
            "effective_training_matches",
            "effective_sample_size",
            "effective_history_matches",
        ),
    )
    if effective is None:
        diagnostics = _get(model_fit, "diagnostics", {}) if model_fit is not None else {}
        if isinstance(diagnostics, Mapping):
            effective = _numeric_uncertainty(
                diagnostics,
                ("training_effective_matches", "effective_sample_size"),
            )
    effective = max(1.0, effective or float(selected_config.minimum_calibration_matches))
    sparse = _sparse_multiplier(merged_uncertainty)
    parameter_names = tuple(sorted(means))
    if not parameter_names:
        raise T14ValidationError("T14 Laplace uncertainty requires predictive parameters.")
    calibration_residual = 0.0
    if calibration_fit is not None:
        calibration_residual = max(
            (parameter.residual_scale for parameter in calibration_fit.parameters.values()),
            default=0.0,
        )
    values = tuple(max(0.0, _number(means[name], f"T14 {name} mean")) for name in parameter_names)
    covariance_rows: list[list[float]] = []
    hessian_rows: list[list[float]] = []
    penalty_values: list[float] = []
    model_config = _get(model_fit, "config", None) if model_fit is not None else None
    prior_scales = tuple(
        candidate
        for key in (
            "team_prior_scale",
            "home_advantage_prior_scale",
            "dispersion_prior_scale",
            "league_season_prior_scale",
        )
        if (candidate := _optional_number(_get(model_config, key))) is not None and candidate > 0
    )
    model_penalty_precision = 1.0 / max(min(prior_scales) ** 2, 1e-6) if prior_scales else 0.0
    calibration_penalty_precision = 1.0 / max(selected_config.ridge, 1e-6)
    for value in values:
        # The Poisson curvature is informative near zero; the ridge term and
        # the MAP's pooling penalty stop the inverse Hessian from exploding.
        likelihood_precision = effective / max(1.0, value + 0.75)
        penalty = calibration_penalty_precision + model_penalty_precision
        residual_precision = 1.0 / max(1.0, calibration_residual * calibration_residual)
        hessian = likelihood_precision + penalty + residual_precision
        variance = sparse * sparse / max(hessian, 1e-9)
        covariance_rows.append(
            [variance if index == len(covariance_rows) else 0.0 for index in range(len(values))]
        )
        hessian_rows.append(
            [hessian if index == len(hessian_rows) else 0.0 for index in range(len(values))]
        )
        penalty_values.append(penalty)
    selected_seed = seed if seed is not None else selected_config.seed
    if isinstance(selected_seed, bool) or not isinstance(selected_seed, int):
        raise T14ValidationError("T14 Laplace seed must be an integer.")
    return LaplaceParameterUncertainty(
        family=selected_family,
        parameter_names=parameter_names,
        mean=values,
        covariance=tuple(tuple(row) for row in covariance_rows),
        hessian=tuple(tuple(row) for row in hessian_rows),
        penalty_precision=tuple(penalty_values),
        effective_sample_size=effective,
        sparse_multiplier=sparse,
        seed=selected_seed,
        draw_count=selected_config.parameter_draws,
    )


def laplace_parameter_draws(
    model_fit_or_family: object,
    means: Mapping[str, float] | None = None,
    *,
    model_fit: object | None = None,
    distribution_uncertainty: Mapping[str, object] | None = None,
    calibration_fit: CalibrationFit | None = None,
    config: T14Config | None = None,
    seed: int | None = None,
) -> LaplaceParameterUncertainty:
    """Public helper returning the Laplace approximation and deterministic draws."""

    if isinstance(model_fit_or_family, (ModelFamily, str)) and means is not None:
        family = _normalise_family(model_fit_or_family)
        fit = model_fit
    else:
        fit = model_fit_or_family
        family = _normalise_family(
            cast(ModelFamily | str, _get(fit, "family", ModelFamily.FULL_TIME_GOALS))
        )
        if means is None:
            raise T14ValidationError("T14 means are required for a model-fit draw request.")
    return build_laplace_uncertainty(
        family,
        means,
        model_fit=fit,
        distribution_uncertainty=distribution_uncertainty,
        calibration_fit=calibration_fit,
        config=config,
        seed=seed,
    )


@dataclass(frozen=True)
class ReferenceModel:
    """One approved reference assessment with an explicit dependency group."""

    name: str
    kind: ReferenceModelKind | str
    dependency_group: str
    settlement_distributions: Mapping[str, SettlementProbabilities]
    correlated: bool = False
    source_model_digest: str | None = None
    source_input_ids: tuple[str, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=dict)
    reference_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.name, "T14 reference model name")
        object.__setattr__(self, "kind", _normalise_reference_kind(self.kind))
        _text(self.dependency_group, "T14 reference dependency group")
        selected: dict[str, SettlementProbabilities] = {}
        for key, value in self.settlement_distributions.items():
            if isinstance(value, SettlementProbabilities):
                selected[str(key)] = value
            elif isinstance(value, Mapping):
                selected[str(key)] = SettlementProbabilities(
                    win_probability=_number(
                        value.get("WIN", value.get("win", value.get("win_probability", 0.0)))
                    ),
                    loss_probability=_number(
                        value.get("LOSS", value.get("loss", value.get("loss_probability", 0.0)))
                    ),
                    push_probability=_number(
                        value.get("PUSH", value.get("push", value.get("push_probability", 0.0)))
                    ),
                )
            else:
                raise T14ValidationError("T14 reference settlements must be typed probabilities.")
        object.__setattr__(
            self, "settlement_distributions", MappingProxyType(dict(sorted(selected.items())))
        )
        object.__setattr__(self, "source_input_ids", _strings(self.source_input_ids))
        object.__setattr__(self, "provenance", _freeze_map(self.provenance))
        expected = _digest(self._payload(include_digest=False))
        if self.reference_digest and self.reference_digest != expected:
            raise T14IntegrityError("T14 reference digest does not match its content.")
        object.__setattr__(self, "reference_digest", expected)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "correlated": self.correlated,
            "dependency_group": self.dependency_group,
            "kind": _enum_value(self.kind),
            "name": self.name,
            "provenance": dict(self.provenance),
            "settlement_distributions": {
                key: value.to_dict() for key, value in self.settlement_distributions.items()
            },
            "source_input_ids": self.source_input_ids,
            "source_model_digest": self.source_model_digest,
        }
        if include_digest:
            payload["reference_digest"] = self.reference_digest
        return payload

    @property
    def digest(self) -> str:
        return self.reference_digest

    def to_dict(self) -> dict[str, object]:
        return self._payload()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ReferenceModel:
        settlements = value.get("settlement_distributions", value.get("settlements", {}))
        return cls(
            name=_text(value.get("name", value.get("model_name")), "T14 reference name"),
            kind=cast(
                ReferenceModelKind | str,
                value.get("kind", value.get("reference_kind", "REDUCED")),
            ),
            dependency_group=_text(
                value.get("dependency_group", value.get("correlation_group", "reference")),
                "T14 reference dependency group",
            ),
            settlement_distributions=cast(
                Mapping[str, SettlementProbabilities],
                _mapping(settlements, "T14 reference settlements"),
            ),
            correlated=bool(value.get("correlated", False)),
            source_model_digest=(
                str(value["source_model_digest"])
                if value.get("source_model_digest") is not None
                else None
            ),
            source_input_ids=tuple(
                item for item in _sequence(value.get("source_input_ids")) if isinstance(item, str)
            ),
            provenance=_mapping(value.get("provenance", {}), "T14 reference provenance"),
            reference_digest=str(value.get("reference_digest", "")),
        )


@dataclass(frozen=True)
class ReferenceSensitivity:
    """Continuous dependency-aware sensitivity, never a vote count."""

    agreement: float
    uncertainty_multiplier: float
    sensitivity_by_preference: Mapping[str, float]
    group_sensitivity: Mapping[str, float]
    effective_dependency_groups: tuple[str, ...]
    correlated_reference_groups: tuple[str, ...]
    meaningful_reference_names: tuple[str, ...]
    reference_digests: tuple[str, ...]
    method: str = "dependency-aware-meaningful-sensitivity-v1"
    sensitivity_digest: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.agreement <= 1 or self.uncertainty_multiplier < 1:
            raise T14ValidationError("T14 reference sensitivity values are invalid.")
        object.__setattr__(
            self, "sensitivity_by_preference", _freeze_map(self.sensitivity_by_preference)
        )
        object.__setattr__(self, "group_sensitivity", _freeze_map(self.group_sensitivity))
        object.__setattr__(
            self, "effective_dependency_groups", _strings(self.effective_dependency_groups)
        )
        object.__setattr__(
            self, "correlated_reference_groups", _strings(self.correlated_reference_groups)
        )
        object.__setattr__(
            self, "meaningful_reference_names", _strings(self.meaningful_reference_names)
        )
        object.__setattr__(self, "reference_digests", _strings(self.reference_digests))
        expected = _digest(self._payload(include_digest=False))
        if self.sensitivity_digest and self.sensitivity_digest != expected:
            raise T14IntegrityError("T14 reference sensitivity digest does not match its content.")
        object.__setattr__(self, "sensitivity_digest", expected)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "agreement": self.agreement,
            "correlated_reference_groups": self.correlated_reference_groups,
            "effective_dependency_groups": self.effective_dependency_groups,
            "group_sensitivity": dict(self.group_sensitivity),
            "meaningful_reference_names": self.meaningful_reference_names,
            "method": self.method,
            "reference_digests": self.reference_digests,
            "sensitivity_by_preference": dict(self.sensitivity_by_preference),
            "uncertainty_multiplier": self.uncertainty_multiplier,
        }
        if include_digest:
            payload["sensitivity_digest"] = self.sensitivity_digest
        return payload

    @property
    def digest(self) -> str:
        return self.sensitivity_digest

    @property
    def model_agreement(self) -> float:
        return self.agreement

    def to_dict(self) -> dict[str, object]:
        return self._payload()


ModelAgreement = ReferenceSensitivity
CalibrationRecord = CalibrationObservation


def _coerce_reference(value: ReferenceModel | Mapping[str, object]) -> ReferenceModel:
    if isinstance(value, ReferenceModel):
        return value
    if isinstance(value, Mapping):
        return ReferenceModel.from_mapping(value)
    raise T14ValidationError("T14 references must be typed reference models or objects.")


def compute_model_agreement(
    primary_settlements: Mapping[str, SettlementProbabilities],
    references: Iterable[ReferenceModel | Mapping[str, object]],
    *,
    config: T14Config | None = None,
) -> ReferenceSensitivity:
    """Measure meaningful distribution sensitivity once per dependency group."""

    selected_config = config or T14Config()
    selected = [_coerce_reference(value) for value in references]
    groups: dict[str, list[ReferenceModel]] = {}
    for reference in selected:
        groups.setdefault(reference.dependency_group, []).append(reference)
    group_sensitivity_values: dict[str, dict[str, float]] = {}
    correlated_groups: set[str] = set()
    for group, values in sorted(groups.items()):
        if len(values) > 1 or any(item.correlated for item in values):
            correlated_groups.add(group)
        # A dependency group contributes one continuous assessment.  Its
        # largest deviation is retained as sensitivity; references never vote,
        # average into, or replace the primary calibrated probability.
        keys = sorted({key for item in values for key in item.settlement_distributions})
        group_sensitivity_values[group] = {
            key: max(
                (
                    abs(item.settlement_distributions[key].win - primary_settlements[key].win)
                    for item in values
                    if key in item.settlement_distributions and key in primary_settlements
                ),
                default=0.0,
            )
            for key in keys
        }
    sensitivity: dict[str, float] = {}
    meaningful_names: set[str] = set()
    for preference_id, primary in sorted(primary_settlements.items()):
        deviations = [
            values[preference_id]
            for values in group_sensitivity_values.values()
            if preference_id in values
        ]
        meaningful = [
            max(0.0, value - selected_config.meaningful_sensitivity) for value in deviations
        ]
        selected_value = max(meaningful, default=0.0)
        sensitivity[preference_id] = selected_value
        if any(value > 0 for value in meaningful):
            for reference in selected:
                if (
                    preference_id in reference.settlement_distributions
                    and abs(reference.settlement_distributions[preference_id].win - primary.win)
                    > selected_config.meaningful_sensitivity
                ):
                    meaningful_names.add(reference.name)
    group_sensitivity = {
        group: max(
            (
                max(0.0, value - selected_config.meaningful_sensitivity)
                for key, value in values.items()
                if key in primary_settlements
            ),
            default=0.0,
        )
        for group, values in group_sensitivity_values.items()
    }
    average_sensitivity = sum(sensitivity.values()) / max(1, len(sensitivity))
    denominator = max(
        selected_config.sensitivity_scale - selected_config.meaningful_sensitivity, 1e-9
    )
    agreement = _bounded(1.0 - average_sensitivity / denominator, 0.0, 1.0)
    uncertainty_multiplier = 1.0 + selected_config.reference_uncertainty_scale * _bounded(
        average_sensitivity / denominator, 0.0, 2.0
    )
    return ReferenceSensitivity(
        agreement=agreement,
        uncertainty_multiplier=uncertainty_multiplier,
        sensitivity_by_preference=sensitivity,
        group_sensitivity=group_sensitivity,
        effective_dependency_groups=tuple(sorted(group_sensitivity_values)),
        correlated_reference_groups=tuple(sorted(correlated_groups)),
        meaningful_reference_names=tuple(sorted(meaningful_names)),
        reference_digests=tuple(item.digest for item in selected),
    )


def _marginal_surface_reference(
    family: ModelFamily,
    surface: Sequence[Sequence[float]],
    name: str,
    kind: ReferenceModelKind,
    *,
    dependency_group: str = "reduced-count-surface",
) -> ReferenceModel:
    home = [sum(row) for row in surface]
    away = [
        sum(surface[home_index][away_index] for home_index in range(len(surface)))
        for away_index in range(len(surface))
    ]
    independent = _normalise_surface(
        tuple(
            tuple(home[home_index] * away[away_index] for away_index in range(len(away)))
            for home_index in range(len(home))
        )
    )
    return ReferenceModel(
        name=name,
        kind=kind,
        dependency_group=dependency_group,
        settlement_distributions=_settlement_distributions(family, independent),
        correlated=True,
        provenance={"surface_method": "independent-marginal-product"},
    )


def _empirical_reference(
    family: ModelFamily,
    observations: Sequence[CalibrationObservation],
    name: str = "empirical-baseline",
) -> ReferenceModel | None:
    counts: dict[str, list[int]] = {}
    for record in observations:
        results = record.settlement_results
        for key, result in results.items():
            if result in {"WIN", "LOSS", "PUSH"}:
                counts.setdefault(key, [0, 0, 0])[{"WIN": 0, "LOSS": 1, "PUSH": 2}[result]] += 1
    if not counts:
        return None
    settlements = {
        key: SettlementProbabilities(
            (values[0] + 1.0) / (sum(values) + 3.0),
            (values[1] + 1.0) / (sum(values) + 3.0),
            (values[2] + 1.0) / (sum(values) + 3.0),
        )
        for key, values in counts.items()
    }
    return ReferenceModel(
        name=name,
        kind=ReferenceModelKind.EMPIRICAL,
        dependency_group="empirical-settlement-baseline",
        settlement_distributions=settlements,
        provenance={"dirichlet_prior": (1.0, 1.0, 1.0), "observation_count": len(observations)},
    )


def build_reference_models(
    distribution: object,
    *,
    observations: Iterable[CalibrationObservation | Mapping[str, object]] = (),
    elo_ratings: Mapping[str, float] | None = None,
) -> tuple[ReferenceModel, ...]:
    """Build only approved reduced/empirical/bivariate/Elo-style references."""

    parts = _coerce_distribution(distribution)
    if parts.status is not T14Status.AVAILABLE:
        return ()
    references: list[ReferenceModel] = [
        _marginal_surface_reference(
            parts.family,
            parts.surface,
            "reduced-independent-count",
            ReferenceModelKind.REDUCED,
            dependency_group="primary-count-surface-chain",
        ),
        ReferenceModel(
            name="bivariate-primary-surface",
            kind=ReferenceModelKind.BIVARIATE,
            dependency_group="primary-count-surface-chain",
            settlement_distributions=_settlement_distributions(parts.family, parts.surface),
            correlated=True,
            source_model_digest=parts.model_digest,
            provenance={"source": "T11-T13-primary-surface"},
        ),
    ]
    selected_observations: list[CalibrationObservation] = []
    for item in observations:
        try:
            selected_observations.append(_coerce_observation(item))
        except T14Error:
            continue
    empirical = _empirical_reference(parts.family, selected_observations)
    if empirical is not None:
        references.append(empirical)
    if elo_ratings is not None:
        target = _get(distribution, "target", None)
        home_team = _get(target, "home_team_id", _get(distribution, "home_team_id", None))
        away_team = _get(target, "away_team_id", _get(distribution, "away_team_id", None))
        if isinstance(home_team, str) and isinstance(away_team, str):
            home_rating = _optional_number(elo_ratings.get(home_team))
            away_rating = _optional_number(elo_ratings.get(away_team))
            if home_rating is not None and away_rating is not None:
                home_probability = 1.0 / (1.0 + 10.0 ** (-(home_rating - away_rating) / 400.0))
                draw_probability = 0.22
                winner: dict[str, SettlementProbabilities] = {}
                for preference in _preference_set(parts.family):
                    if preference.family is PreferenceFamily.MATCH_WINNER:
                        if preference.selection == "Home":
                            win = home_probability * (1.0 - draw_probability)
                        elif preference.selection == "Away":
                            win = (1.0 - home_probability) * (1.0 - draw_probability)
                        else:
                            win = draw_probability
                        winner[preference.preference_id] = SettlementProbabilities(
                            win, 1.0 - win, 0.0
                        )
                if winner:
                    references.append(
                        ReferenceModel(
                            name="elo-style-match-winner",
                            kind=ReferenceModelKind.ELO,
                            dependency_group="elo-rating-path",
                            settlement_distributions=winner,
                            provenance={
                                "rating_scale": 400.0,
                                "draw_probability": draw_probability,
                            },
                        )
                    )
    return tuple(references)


def _feature_number(value: object, keys: Sequence[str]) -> float | None:
    if isinstance(value, Mapping):
        for key in keys:
            selected = _optional_number(value.get(key))
            if selected is not None:
                return selected
    return None


def _state_for_uncertainty(value: object | None) -> FrozenEvidenceState | None:
    if value is None:
        return None
    if isinstance(value, FrozenEvidenceState):
        return value
    if isinstance(value, Mapping):
        return FrozenEvidenceState.from_dict(value)
    raise T14ValidationError("T14 evidence uncertainty requires a FrozenEvidenceState.")


def _evidence_family_tokens(family: ModelFamily) -> tuple[str, ...]:
    return {
        ModelFamily.FULL_TIME_GOALS: (
            "Match Winner",
            "Match Goals Over",
            "Double Chance",
            "Asian Handicap",
        ),
        ModelFamily.FIRST_HALF_GOALS: ("First-Half Over",),
        ModelFamily.SECOND_HALF_GOALS: ("Second-Half Over",),
        ModelFamily.CORNERS: ("Corner",),
    }[family]


def _evidence_uncertainty(
    state: FrozenEvidenceState | None, family: ModelFamily
) -> tuple[float, float, Mapping[str, object]]:
    if state is None:
        return 0.0, 0.0, {"available": False, "reasons": ()}
    family_tokens = _evidence_family_tokens(family)
    sufficiency_values = [
        item
        for key, item in state.research_sufficiency.items()
        if any(token.lower() in str(key).lower() for token in family_tokens)
    ]
    if not sufficiency_values:
        sufficiency_values = list(state.research_sufficiency.values())
    score = 0.0
    reasons: list[str] = []
    missing_important = 0
    unresolved = 0
    for item in sufficiency_values:
        missing = len(getattr(item, "missing_important_requirement_ids", ()))
        missing_important += missing
        unresolved += int(getattr(item, "unresolved_material_conflicts", 0))
        if missing:
            reasons.append("MISSING_IMPORTANT_EVIDENCE")
        if unresolved:
            reasons.append("UNRESOLVED_MATERIAL_CONFLICT")
        if not bool(getattr(item, "critical_evidence_complete", True)):
            score += 0.35
            reasons.append("CRITICAL_EVIDENCE_INCOMPLETE")
    score += min(0.5, 0.10 * missing_important)
    score += min(0.6, 0.20 * unresolved)
    unknown_features = 0
    for feature in state.derived_features:
        feature_state = _enum_value(getattr(feature, "state", "UNKNOWN")).upper()
        if feature_state in {"UNKNOWN", "ABSENT"} and getattr(feature, "name", "").startswith(
            ("E-", "D-")
        ):
            unknown_features += 1
    if unknown_features:
        score += min(0.45, 0.04 * unknown_features)
        reasons.append("FROZEN_FEATURE_UNKNOWN")
    if state.material_scenarios:
        active = [item for item in state.material_scenarios if item.could_change_acceptance]
        if active:
            score += min(0.6, 0.12 * len(active))
            reasons.append("MATERIAL_SCENARIO")
    return (
        score,
        min(1.5, score),
        {
            "available": True,
            "unknown_feature_count": unknown_features,
            "missing_important_count": missing_important,
            "unresolved_conflict_count": unresolved,
            "reasons": tuple(sorted(set(reasons))),
            "state_digest": state.digest,
        },
    )


def _freshness_uncertainty(
    state: FrozenEvidenceState | None,
) -> tuple[float, Mapping[str, object]]:
    """Keep stale/unknown evidence freshness separate from missing evidence."""

    if state is None:
        return 0.0, {"available": False, "stale_count": 0, "unknown_count": 0}
    source_freshness = [_enum_value(item.freshness).upper() for item in state.source_assertions]
    if source_freshness:
        considered = source_freshness
    else:
        considered = [
            _enum_value(item.freshness).upper()
            for item in state.requirement_evaluations
            if _enum_value(item.status).upper() in {"COVERED", "STALE", "CONFLICT"}
        ]
    total = max(1, len(considered))
    stale_count = sum(item == "STALE" for item in considered)
    unknown_count = sum(item == "UNKNOWN" for item in considered)
    post_cutoff_count = sum(item == "POST_CUTOFF" for item in considered)
    score = min(
        1.5,
        0.9 * stale_count / total + 0.45 * unknown_count / total + 1.2 * post_cutoff_count / total,
    )
    return score, {
        "available": True,
        "considered_count": len(considered),
        "stale_count": stale_count,
        "unknown_count": unknown_count,
        "post_cutoff_count": post_cutoff_count,
        "state_digest": state.digest,
    }


def _structural_uncertainty(
    state: FrozenEvidenceState | None,
) -> tuple[float, Mapping[str, object]]:
    if state is None:
        return 0.0, {"available": False, "detected": False}
    detected = False
    evidence: list[str] = []
    for feature in state.derived_features:
        name = str(getattr(feature, "name", "")).upper()
        value = getattr(feature, "value", None)
        feature_uncertainty = getattr(feature, "uncertainty", {})
        if "REGIME" in name or "STRUCTURAL" in name or "MANAGER" in name:
            candidate = _feature_number(
                feature_uncertainty,
                ("structural_change", "structural_change_probability", "regime_change_probability"),
            )
            if candidate is not None and candidate > 0:
                detected = True
                evidence.append(f"{name}:probability")
            if isinstance(value, Mapping):
                bool_keys = ("structural_change", "regime_change", "manager_change", "changed")
                if any(value.get(key) is True for key in bool_keys):
                    detected = True
                    evidence.append(name)
                if any("change" in str(key).lower() for key in value):
                    detected = True
                    evidence.append(name)
    for scenario in state.material_scenarios:
        description = str(scenario.description).lower()
        requirement = str(scenario.requirement_id).lower()
        if scenario.could_change_acceptance and any(
            token in description or token in requirement
            for token in ("structural", "regime", "manager")
        ):
            detected = True
            evidence.append(scenario.scenario_id)
    score = 0.45 if detected else 0.0
    return score, {
        "available": True,
        "detected": detected,
        "evidence_ids": tuple(sorted(set(evidence))),
        "state_digest": state.digest,
    }


def _fit_uncertainty(value: object | None) -> Mapping[str, object]:
    selected = _get(value, "uncertainty", {}) if value is not None else {}
    return selected if isinstance(selected, Mapping) else {}


def _fit_provenance(value: object | None) -> Mapping[str, object]:
    if value is None:
        return {}
    result: dict[str, object] = {}
    for key in (
        "digest",
        "fit_digest",
        "model_digest",
        "model_version",
        "artifact_digest",
        "config_digest",
        "algorithm_version",
        "feature_version",
        "training_input_fixture_ids",
        "training_input_digests",
        "training_input_ids",
        "frozen_evidence_digest",
        "frozen_artifact_digest",
        "frozen_manifest_digest",
    ):
        item = _get(value, key, None)
        if item is not None:
            result[key] = item
    config_digest = _get(_get(value, "config", None), "digest", None)
    if config_digest is not None:
        result["model_config_digest"] = config_digest
    return result


def _quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise T14ValidationError("T14 quantile requires values.")
    ordered = sorted(float(value) for value in values)
    position = _bounded(quantile, 0.0, 1.0) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _unavailable_prediction(
    parts: _DistributionParts,
    reason: str,
    *,
    calibration_fit: CalibrationFit | None = None,
    diagnostics: Mapping[str, object] | None = None,
    provenance: Mapping[str, object] | None = None,
) -> CalibratedDistribution:
    return CalibratedDistribution(
        status=T14Status.MODEL_UNAVAILABLE,
        family=parts.family,
        target_fixture_id=parts.target_fixture_id,
        matchweek_id=parts.matchweek_id,
        model_version=parts.model_version,
        model_digest=parts.model_digest,
        calibration_version=calibration_fit.calibration_version
        if calibration_fit
        else T14_CALIBRATION_VERSION,
        calibration_digest=calibration_fit.digest if calibration_fit else None,
        reason=reason,
        diagnostics=dict(diagnostics or {}),
        provenance=dict(provenance or {}),
    )


@dataclass(frozen=True)
class CalibratedDistribution:
    """Calibrated probabilities and settlement-aware uncertainty for one family."""

    status: T14Status
    family: ModelFamily | str
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    calibration_version: str
    calibration_digest: str | None = None
    surface: tuple[tuple[float, ...], ...] = ()
    settlement_distributions: Mapping[str, SettlementProbabilities] = field(default_factory=dict)
    estimated_probabilities: Mapping[str, float] = field(default_factory=dict)
    conservative_probabilities: Mapping[str, float] = field(default_factory=dict)
    loss_probability_upper: Mapping[str, float] = field(default_factory=dict)
    probability_intervals: Mapping[str, Mapping[str, ProbabilityInterval]] = field(
        default_factory=dict
    )
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    model_agreement: float | None = None
    reference_sensitivity: ReferenceSensitivity | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    prediction_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _normalise_family(self.family))
        _text(self.target_fixture_id, "T14 target fixture ID")
        _text(self.matchweek_id, "T14 matchweek ID")
        _text(self.model_version, "T14 model version")
        _text(self.model_digest, "T14 model digest")
        _text(self.calibration_version, "T14 calibration version")
        if not isinstance(self.status, T14Status):
            object.__setattr__(self, "status", _status(self.status))
        settlements: dict[str, SettlementProbabilities] = {}
        for key, value in self.settlement_distributions.items():
            if not isinstance(value, SettlementProbabilities):
                raise T14ValidationError(
                    "T14 settlement distributions require typed probabilities."
                )
            settlements[str(key)] = value
        object.__setattr__(
            self, "settlement_distributions", MappingProxyType(dict(sorted(settlements.items())))
        )
        object.__setattr__(
            self, "estimated_probabilities", _freeze_map(self.estimated_probabilities)
        )
        object.__setattr__(
            self, "conservative_probabilities", _freeze_map(self.conservative_probabilities)
        )
        object.__setattr__(self, "loss_probability_upper", _freeze_map(self.loss_probability_upper))
        object.__setattr__(self, "probability_intervals", _freeze_map(self.probability_intervals))
        object.__setattr__(self, "uncertainty", _freeze_map(self.uncertainty))
        object.__setattr__(self, "provenance", _freeze_map(self.provenance))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        if self.status is T14Status.AVAILABLE:
            selected_surface = _normalise_surface(self.surface)
            if not self.settlement_distributions:
                raise T14ValidationError("Available T14 output requires settlement distributions.")
            expected_settlements = _settlement_distributions(
                _normalise_family(self.family), selected_surface
            )
            if set(expected_settlements) != set(self.settlement_distributions):
                raise T14IntegrityError(
                    "T14 settlement distributions do not cover the calibrated family."
                )
            for key, expected_settlement in expected_settlements.items():
                actual_settlement = self.settlement_distributions[key]
                if any(
                    abs(
                        getattr(actual_settlement, field_name)
                        - getattr(expected_settlement, field_name)
                    )
                    > 1e-8
                    for field_name in ("win", "loss", "push")
                ):
                    raise T14IntegrityError(
                        "T14 settlement distributions do not match the calibrated surface."
                    )
            if set(self.estimated_probabilities) != set(self.settlement_distributions):
                raise T14ValidationError(
                    "Available T14 output requires one Estimated Probability per market."
                )
            if any(
                key not in self.settlement_distributions or value < -1e-12 or value > 1.0 + 1e-12
                for key, value in self.estimated_probabilities.items()
            ):
                raise T14ValidationError("T14 estimated probabilities are invalid.")
            for key, settlement in self.settlement_distributions.items():
                if (
                    key in self.estimated_probabilities
                    and abs(settlement.win - self.estimated_probabilities[key]) > 1e-8
                ):
                    raise T14IntegrityError("T14 estimated probability does not match WIN mass.")
                if key in self.conservative_probabilities and (
                    self.conservative_probabilities[key] > settlement.win + 1e-10
                ):
                    raise T14ValidationError(
                        "T14 Conservative Probability exceeds Estimated Probability."
                    )
            object.__setattr__(self, "surface", selected_surface)
        elif self.surface or self.settlement_distributions:
            raise T14ValidationError("Unavailable T14 output cannot contain probability output.")
        expected = _digest(self._core_dict(include_digest=False))
        if self.prediction_digest and self.prediction_digest != expected:
            raise T14IntegrityError("T14 calibrated prediction digest does not match its content.")
        object.__setattr__(self, "prediction_digest", expected)

    @property
    def digest(self) -> str:
        return self.prediction_digest

    @property
    def is_available(self) -> bool:
        return self.status is T14Status.AVAILABLE

    @property
    def model_unavailable(self) -> bool:
        return self.status is not T14Status.AVAILABLE

    @property
    def calibrated_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.surface

    @property
    def score_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.surface

    @property
    def joint_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.surface

    @property
    def settlement_probabilities(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def settlements(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    def estimated_probability(self, preference_id: str) -> float:
        return self.estimated_probabilities[preference_id]

    def conservative_probability(self, preference_id: str) -> float:
        return self.conservative_probabilities[preference_id]

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "calibration_digest": self.calibration_digest,
            "calibration_version": self.calibration_version,
            "conservative_probabilities": dict(self.conservative_probabilities),
            "diagnostics": dict(self.diagnostics),
            "estimated_probabilities": dict(self.estimated_probabilities),
            "family": _enum_value(self.family),
            "loss_probability_upper": dict(self.loss_probability_upper),
            "matchweek_id": self.matchweek_id,
            "model_agreement": self.model_agreement,
            "model_digest": self.model_digest,
            "model_version": self.model_version,
            "prediction_digest": self.prediction_digest,
            "probability_intervals": {
                key: {name: interval.to_dict() for name, interval in values.items()}
                for key, values in self.probability_intervals.items()
            },
            "provenance": dict(self.provenance),
            "reason": self.reason,
            "reference_sensitivity": (
                self.reference_sensitivity.to_dict() if self.reference_sensitivity else None
            ),
            "settlement_distributions": {
                key: value.to_dict() for key, value in self.settlement_distributions.items()
            },
            "status": self.status.value,
            "surface": self.surface,
            "target_fixture_id": self.target_fixture_id,
            "uncertainty": dict(self.uncertainty),
        }
        if include_digest:
            payload["prediction_digest"] = self.prediction_digest
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._core_dict()

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


CalibratedPrediction = CalibratedDistribution


def _uncertainty_payload(
    laplace: LaplaceParameterUncertainty,
    *,
    evidence_multiplier: float,
    freshness_multiplier: float,
    structural_multiplier: float,
    sparse_multiplier: float,
    reference_multiplier: float,
    chronological_multiplier: float,
    evidence_detail: Mapping[str, object],
    freshness_detail: Mapping[str, object],
    structural_detail: Mapping[str, object],
    reference_detail: Mapping[str, object],
) -> tuple[float, Mapping[str, object]]:
    total = max(
        1.0,
        (1.0 + evidence_multiplier)
        * (1.0 + freshness_multiplier)
        * (1.0 + structural_multiplier)
        * sparse_multiplier
        * reference_multiplier
        * chronological_multiplier,
    )
    return total, {
        "components": {
            "parameter": {"method": laplace.method, "draws_digest": laplace.digest},
            "evidence": {"multiplier": 1.0 + evidence_multiplier, **dict(evidence_detail)},
            "evidence_freshness": {
                "multiplier": 1.0 + freshness_multiplier,
                **dict(freshness_detail),
            },
            "structural_change": {
                "multiplier": 1.0 + structural_multiplier,
                **dict(structural_detail),
            },
            "sparse_team": {"multiplier": sparse_multiplier},
            "reference_sensitivity": {
                "multiplier": reference_multiplier,
                **dict(reference_detail),
            },
            "chronological_checks": {"multiplier": chronological_multiplier},
        },
        "effective_sample_size": laplace.effective_sample_size,
        "laplace": laplace.to_dict(),
        "total_multiplier": total,
    }


def calibrate_distribution(
    distribution: object,
    calibration_fit: CalibrationFit | None = None,
    *,
    calibration: CalibrationFit | None = None,
    model_fit: object | None = None,
    frozen_evidence_state: object | None = None,
    evidence_state: object | None = None,
    reference_models: Iterable[ReferenceModel | Mapping[str, object]] | None = None,
    calibration_records: Iterable[CalibrationObservation | Mapping[str, object]] = (),
    calibration_end_utc: str | None = None,
    development_end_utc: str | None = None,
    config: T14Config | None = None,
    seed: int | None = None,
) -> CalibratedDistribution:
    """Calibrate one T11/T12/T13 distribution and quantify its uncertainty."""

    selected_config = config or T14Config()
    if calibration_fit is not None and calibration is not None:
        raise T14ValidationError("T14 received two calibration-fit aliases.")
    selected_fit = calibration_fit or calibration
    if frozen_evidence_state is not None and evidence_state is not None:
        raise T14ValidationError("T14 received two FrozenEvidenceState aliases.")
    selected_state_raw = (
        frozen_evidence_state if frozen_evidence_state is not None else evidence_state
    )
    try:
        parts = _coerce_distribution(distribution)
    except (T14Error, TypeError, ValueError) as error:
        parts = _DistributionParts(
            status=T14Status.MODEL_UNAVAILABLE,
            family=ModelFamily.FULL_TIME_GOALS,
            target_fixture_id="unknown-fixture",
            matchweek_id="unknown-matchweek",
            model_version="unknown-model-version",
            model_digest="unknown-model-digest",
            surface=(),
            home_mean=None,
            away_mean=None,
            total_mean=None,
            uncertainty={},
            feature_inputs={},
            diagnostics={},
            artifact_digest=None,
            reason=f"MALFORMED_MODEL_DISTRIBUTION:{error}",
        )
    if parts.status is not T14Status.AVAILABLE:
        return _unavailable_prediction(
            parts, parts.reason or "MODEL_UNAVAILABLE", calibration_fit=selected_fit
        )
    if model_fit is not None and not _available(model_fit):
        return _unavailable_prediction(
            parts, "PRIMARY_MODEL_UNAVAILABLE", calibration_fit=selected_fit
        )
    if selected_fit is None and calibration_records:
        selected_fit = fit_calibration(
            calibration_records,
            family=parts.family,
            calibration_end_utc=calibration_end_utc,
            development_end_utc=development_end_utc,
            config=selected_config,
            expected_model_version=parts.model_version,
        )
    if selected_fit is None:
        return _unavailable_prediction(parts, "CALIBRATION_FIT_REQUIRED")
    if not selected_fit.is_available:
        return _unavailable_prediction(
            parts,
            selected_fit.reason or "CALIBRATION_MODEL_UNAVAILABLE",
            calibration_fit=selected_fit,
        )
    if selected_fit.family is not parts.family:
        return _unavailable_prediction(
            parts, "CALIBRATION_FAMILY_MISMATCH", calibration_fit=selected_fit
        )
    try:
        state = _state_for_uncertainty(selected_state_raw)
        params = selected_fit.parameters
        if parts.family in {ModelFamily.FIRST_HALF_GOALS, ModelFamily.SECOND_HALF_GOALS}:
            base_mean = parts.total_mean or 0.0
            target_means = {
                "total": params["total"].apply(base_mean, selected_config.maximum_count_mean)
            }
        else:
            target_means = {
                "home": params["home"].apply(
                    parts.home_mean or 0.0, selected_config.maximum_count_mean
                ),
                "away": params["away"].apply(
                    parts.away_mean or 0.0, selected_config.maximum_count_mean
                ),
            }
        calibrated_surface = _tilt_surface(parts.surface, parts.family, target_means)
        settlements = _settlement_distributions(parts.family, calibrated_surface)
        evidence_score, _, evidence_detail = _evidence_uncertainty(state, parts.family)
        freshness_score, freshness_detail = _freshness_uncertainty(state)
        structural_score, structural_detail = _structural_uncertainty(state)
        sparse = max(
            _sparse_multiplier(parts.uncertainty),
            _sparse_multiplier(_fit_uncertainty(model_fit)),
        )
        uncertainty_checks = selected_fit.diagnostics.get("uncertainty_checks", {})
        chronological_multiplier = (
            _optional_number(
                uncertainty_checks.get("widening_multiplier")
                if isinstance(uncertainty_checks, Mapping)
                else None
            )
            or 1.0
        )
        if reference_models is None:
            references = build_reference_models(
                DistributionInput(
                    family=parts.family,
                    target_fixture_id=parts.target_fixture_id,
                    matchweek_id=parts.matchweek_id,
                    model_version=parts.model_version,
                    model_digest=parts.model_digest,
                    surface=calibrated_surface,
                )
            )
        else:
            references = tuple(_coerce_reference(item) for item in reference_models)
        sensitivity = compute_model_agreement(settlements, references, config=selected_config)
        reference_multiplier = sensitivity.uncertainty_multiplier
        uncertainty_factor, uncertainty_details = _uncertainty_payload(
            build_laplace_uncertainty(
                parts.family,
                target_means,
                model_fit=model_fit,
                distribution_uncertainty=parts.uncertainty,
                calibration_fit=selected_fit,
                config=selected_config,
                seed=seed,
            ),
            evidence_multiplier=selected_config.evidence_uncertainty_scale * evidence_score,
            freshness_multiplier=selected_config.freshness_uncertainty_scale * freshness_score,
            structural_multiplier=selected_config.structural_uncertainty_scale * structural_score,
            sparse_multiplier=max(
                1.0, 1.0 + selected_config.sparse_uncertainty_scale * (sparse - 1.0)
            ),
            reference_multiplier=reference_multiplier,
            chronological_multiplier=max(1.0, chronological_multiplier),
            evidence_detail=evidence_detail,
            freshness_detail=freshness_detail,
            structural_detail=structural_detail,
            reference_detail={
                "agreement": sensitivity.agreement,
                "sensitivity_digest": sensitivity.digest,
                "effective_dependency_groups": sensitivity.effective_dependency_groups,
            },
        )
        laplace = build_laplace_uncertainty(
            parts.family,
            target_means,
            model_fit=model_fit,
            distribution_uncertainty=parts.uncertainty,
            calibration_fit=selected_fit,
            config=selected_config,
            seed=seed,
        )
        raw_draws = laplace.parameter_draws()
        scaled_draws = tuple(
            tuple(
                _bounded(
                    max(
                        0.0,
                        target_means[name]
                        + (draw[index] - target_means[name]) * uncertainty_factor,
                    ),
                    0.0,
                    selected_config.maximum_count_mean,
                )
                for index, name in enumerate(laplace.parameter_names)
            )
            for draw in raw_draws
        )
        settlement_samples: dict[str, dict[str, list[float]]] = {
            key: {"WIN": [], "LOSS": [], "PUSH": []} for key in settlements
        }
        for draw in scaled_draws:
            draw_means = {name: draw[index] for index, name in enumerate(laplace.parameter_names)}
            draw_surface = _tilt_surface(calibrated_surface, parts.family, draw_means)
            draw_settlements = _settlement_distributions(parts.family, draw_surface)
            for key, value in draw_settlements.items():
                settlement_samples[key]["WIN"].append(value.win)
                settlement_samples[key]["LOSS"].append(value.loss)
                settlement_samples[key]["PUSH"].append(value.push)
        estimated = {key: value.win for key, value in settlements.items()}
        conservatives: dict[str, float] = {}
        loss_upper: dict[str, float] = {}
        intervals: dict[str, Mapping[str, ProbabilityInterval]] = {}
        for key, settlement in settlements.items():
            classes: dict[str, ProbabilityInterval] = {}
            for outcome in ("WIN", "LOSS", "PUSH"):
                samples = settlement_samples[key][outcome]
                estimate = getattr(settlement, outcome.lower())
                raw_lower = _quantile(samples, selected_config.lower_quantile)
                raw_upper = _quantile(samples, selected_config.upper_quantile)
                spread = _std(samples)
                lower = _bounded(min(estimate, raw_lower), 0.0, 1.0)
                upper = _bounded(max(estimate, raw_upper), 0.0, 1.0)
                classes[outcome] = ProbabilityInterval(
                    estimated=estimate,
                    lower=lower,
                    upper=upper,
                    standard_deviation=spread,
                    lower_quantile=selected_config.lower_quantile,
                    upper_quantile=selected_config.upper_quantile,
                )
            intervals[key] = MappingProxyType(classes)
            base_lower = classes["WIN"].lower
            extra_penalty = max(0.0, uncertainty_factor - 1.0) * max(
                classes["WIN"].standard_deviation,
                0.01 * max(estimated[key], 0.1),
            )
            conservatives[key] = _bounded(min(estimated[key], base_lower - extra_penalty), 0.0, 1.0)
            loss_upper[key] = _bounded(
                max(classes["LOSS"].upper, settlement.loss + extra_penalty), 0.0, 1.0
            )
        raw_distribution_digest = _get(
            distribution,
            "distribution_digest",
            _get(distribution, "digest", None),
        )
        distribution_input_digest = (
            raw_distribution_digest if isinstance(raw_distribution_digest, str) else None
        )
        provenance: dict[str, object] = {
            "artifact_digest": parts.artifact_digest,
            "calibration_fit_digest": selected_fit.digest,
            "calibration_period": {
                "start_utc": selected_fit.calibration_start_utc,
                "end_utc": selected_fit.calibration_end_utc,
                "fit_as_of_utc": selected_fit.fit_as_of_utc,
                "used_fixture_ids": selected_fit.used_fixture_ids,
                "used_record_digests": selected_fit.used_record_digests,
                "training_input_ids": selected_fit.training_input_ids,
                "training_input_digests": selected_fit.training_input_digests,
            },
            "calibration_provenance": dict(selected_fit.provenance),
            "config_digest": selected_config.digest,
            "distribution_digest": parts.model_digest,
            "distribution_input_digest": distribution_input_digest,
            "feature_inputs": dict(parts.feature_inputs),
            "model_diagnostics": dict(parts.diagnostics),
            "model": _fit_provenance(model_fit),
            "model_digest": parts.model_digest,
            "model_version": parts.model_version,
            "model_uncertainty": dict(parts.uncertainty),
            "randomness": {
                "seed": seed if seed is not None else selected_config.seed,
                "laplace_draws": len(scaled_draws),
                "draws_digest": laplace.digest,
            },
            "reference_digests": sensitivity.reference_digests,
            "t14_version": selected_config.version,
            "frozen_evidence_digest": state.digest if state is not None else None,
        }
        diagnostics = dict(parts.diagnostics)
        diagnostics.update(
            {
                "calibration_method": "affine_mean_exponential_tilt_v1",
                "calibrated_means": target_means,
                "calibrated_surface_normalized": math.isclose(
                    sum(sum(row) for row in calibrated_surface), 1.0, abs_tol=1e-12
                ),
                "laplace_method": laplace.method,
                "reference_sensitivity_method": sensitivity.method,
                "settlement_classes": ("WIN", "LOSS", "PUSH"),
            }
        )
        uncertainty_details = dict(uncertainty_details)
        uncertainty_details["calibration_parameter_uncertainty"] = {
            key: value.to_dict() for key, value in selected_fit.parameters.items()
        }
        return CalibratedDistribution(
            status=T14Status.AVAILABLE,
            family=parts.family,
            target_fixture_id=parts.target_fixture_id,
            matchweek_id=parts.matchweek_id,
            model_version=parts.model_version,
            model_digest=parts.model_digest,
            calibration_version=selected_fit.calibration_version,
            calibration_digest=selected_fit.digest,
            surface=calibrated_surface,
            settlement_distributions=settlements,
            estimated_probabilities=estimated,
            conservative_probabilities=conservatives,
            loss_probability_upper=loss_upper,
            probability_intervals=intervals,
            uncertainty=uncertainty_details,
            model_agreement=sensitivity.agreement,
            reference_sensitivity=sensitivity,
            provenance=provenance,
            diagnostics=diagnostics,
        )
    except (T14Error, TypeError, ValueError, OverflowError, ZeroDivisionError) as error:
        return _unavailable_prediction(
            parts,
            f"CALIBRATION_OR_UNCERTAINTY_FAILED:{error}",
            calibration_fit=selected_fit,
        )


@dataclass(frozen=True)
class CalibrationBundle:
    """T14 output for the available full-time, half-time, and corner families."""

    status: T14Status
    predictions: Mapping[str, CalibratedDistribution]
    calibration_fits: Mapping[str, CalibrationFit]
    provenance: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    bundle_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "predictions", MappingProxyType(dict(sorted(self.predictions.items())))
        )
        object.__setattr__(
            self, "calibration_fits", MappingProxyType(dict(sorted(self.calibration_fits.items())))
        )
        object.__setattr__(self, "provenance", _freeze_map(self.provenance))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        expected = _digest(self._payload(include_digest=False))
        if self.bundle_digest and self.bundle_digest != expected:
            raise T14IntegrityError("T14 calibration bundle digest does not match its content.")
        object.__setattr__(self, "bundle_digest", expected)

    @property
    def digest(self) -> str:
        return self.bundle_digest

    @property
    def is_available(self) -> bool:
        return self.status is T14Status.AVAILABLE

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "calibration_fits": {
                key: value.to_dict() for key, value in self.calibration_fits.items()
            },
            "diagnostics": dict(self.diagnostics),
            "predictions": {key: value.to_dict() for key, value in self.predictions.items()},
            "provenance": dict(self.provenance),
            "reason": self.reason,
            "status": self.status.value,
        }
        if include_digest:
            payload["bundle_digest"] = self.bundle_digest
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._payload()


def _family_key(value: object) -> str:
    return _normalise_family(cast(ModelFamily | str, value)).value


def calibrate_model_families(
    distributions: Mapping[str, object] | None = None,
    *,
    full_time: object | None = None,
    first_half: object | None = None,
    second_half: object | None = None,
    corners: object | None = None,
    full_time_distribution: object | None = None,
    first_half_distribution: object | None = None,
    second_half_distribution: object | None = None,
    corner_distribution: object | None = None,
    calibration_records: Iterable[CalibrationObservation | Mapping[str, object]] = (),
    records: Iterable[CalibrationObservation | Mapping[str, object]] | None = None,
    calibration_fits: Mapping[str, CalibrationFit] | None = None,
    model_fits: Mapping[str, object] | None = None,
    frozen_evidence_state: object | None = None,
    evidence_state: object | None = None,
    reference_models: Mapping[str, Iterable[ReferenceModel | Mapping[str, object]]] | None = None,
    calibration_end_utc: str | None = None,
    development_end_utc: str | None = None,
    config: T14Config | None = None,
    seed: int | None = None,
) -> CalibrationBundle:
    """Calibrate every supplied T11/T12/T13 family in one deterministic pass."""

    selected_config = config or T14Config()
    if records is not None:
        calibration_records = records
    if frozen_evidence_state is not None and evidence_state is not None:
        raise T14ValidationError("T14 received two FrozenEvidenceState aliases.")
    selected_distributions: dict[str, object] = {}
    if distributions is not None:
        selected_distributions.update({str(key): value for key, value in distributions.items()})
    aliases = {
        "full_time": full_time_distribution if full_time_distribution is not None else full_time,
        "first_half": first_half_distribution
        if first_half_distribution is not None
        else first_half,
        "second_half": second_half_distribution
        if second_half_distribution is not None
        else second_half,
        "corners": corner_distribution if corner_distribution is not None else corners,
    }
    selected_distributions.update(
        {key: value for key, value in aliases.items() if value is not None}
    )
    selected_records: list[CalibrationObservation] = []
    for raw in calibration_records:
        try:
            selected_records.append(_coerce_observation(raw))
        except T14Error:
            continue
    fits: dict[str, CalibrationFit] = {}
    if calibration_fits is not None:
        fits.update({_family_key(key): value for key, value in calibration_fits.items()})
    predictions: dict[str, CalibratedDistribution] = {}
    for key, distribution in sorted(selected_distributions.items()):
        try:
            parts = _coerce_distribution(distribution)
        except T14Error:
            continue
        family_key = _enum_value(parts.family)
        fit = fits.get(family_key)
        if fit is None:
            fit = fit_calibration(
                selected_records,
                family=parts.family,
                calibration_end_utc=calibration_end_utc,
                development_end_utc=development_end_utc,
                config=selected_config,
                expected_model_version=parts.model_version,
            )
            fits[family_key] = fit
        selected_references = (
            None
            if reference_models is None
            else reference_models.get(key, reference_models.get(family_key, ()))
        )
        selected_fit = model_fits.get(key, model_fits.get(family_key)) if model_fits else None
        predictions[family_key] = calibrate_distribution(
            distribution,
            calibration_fit=fit,
            model_fit=selected_fit,
            frozen_evidence_state=frozen_evidence_state
            if frozen_evidence_state is not None
            else evidence_state,
            reference_models=selected_references,
            config=selected_config,
            seed=seed,
        )
    available = bool(predictions) and all(item.is_available for item in predictions.values())
    status = T14Status.AVAILABLE if available else T14Status.MODEL_UNAVAILABLE
    provenance = {
        "calibration_fit_digests": {key: value.digest for key, value in fits.items()},
        "config_digest": selected_config.digest,
        "prediction_digests": {key: value.digest for key, value in predictions.items()},
        "seed": seed if seed is not None else selected_config.seed,
        "t14_version": selected_config.version,
    }
    diagnostics = {
        "available_families": tuple(
            key for key, value in predictions.items() if value.is_available
        ),
        "unavailable_families": tuple(
            key for key, value in predictions.items() if not value.is_available
        ),
        "family_count": len(predictions),
    }
    return CalibrationBundle(
        status=status,
        predictions=predictions,
        calibration_fits=fits,
        provenance=provenance,
        diagnostics=diagnostics,
        reason=None if available else "ONE_OR_MORE_FAMILIES_MODEL_UNAVAILABLE",
    )


def quantify_uncertainty(
    distribution: object,
    calibration_fit: CalibrationFit,
    **kwargs: Any,
) -> CalibratedDistribution:
    """Compatibility seam for callers that name the T14 operation explicitly."""

    return calibrate_distribution(distribution, calibration_fit=calibration_fit, **kwargs)


fit_calibrator = fit_calibration
calibrate_probabilities = calibrate_model_families
calibrate_model_output = calibrate_distribution
calibrate_distribution_level = calibrate_distribution


__all__ = [
    "CALIBRATION_VERSION",
    "CORNERS",
    "FIRST_HALF_GOALS",
    "FULL_TIME_GOALS",
    "MODEL_UNAVAILABLE",
    "REJECT",
    "SECOND_HALF_GOALS",
    "T14_ALGORITHM_VERSION",
    "T14_CALIBRATION_VERSION",
    "T14_FEATURE_VERSION",
    "T14_MEDIA_TYPE",
    "T14_MODEL_NAME",
    "T14_MODEL_VERSION",
    "AffineCalibrationParameter",
    "CalibratedDistribution",
    "CalibratedPrediction",
    "CalibrationBundle",
    "CalibrationFit",
    "CalibrationObservation",
    "CalibrationRecord",
    "DistributionInput",
    "LaplaceParameterUncertainty",
    "ModelAgreement",
    "ModelFamily",
    "ProbabilityInterval",
    "ReferenceModel",
    "ReferenceModelKind",
    "ReferenceSensitivity",
    "T14Config",
    "T14Error",
    "T14IntegrityError",
    "T14Status",
    "T14ValidationError",
    "build_laplace_uncertainty",
    "build_reference_models",
    "calibrate_distribution",
    "calibrate_distribution_level",
    "calibrate_model_families",
    "calibrate_model_output",
    "calibrate_probabilities",
    "compute_model_agreement",
    "fit_calibration",
    "fit_calibrator",
    "laplace_parameter_draws",
    "quantify_uncertainty",
]

# Kept as a named alias for callers that used the issue vocabulary.
CALIBRATION_VERSION = T14_CALIBRATION_VERSION

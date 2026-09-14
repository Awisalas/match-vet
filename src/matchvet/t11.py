"""T11 full-time goal Settlement Distributions.

T11 is the first probability-producing seam in MatchVet.  It fits one
recency-weighted, partially pooled Dixon-Coles score model from cutoff-valid
structured history and maps that one joint score surface to every supported
full-time goal preference.  Calibration, half-goal, corner, recommendation,
and policy logic deliberately remain outside this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from matchvet.artifacts import ArtifactStore
from matchvet.evidence import EvidenceState
from matchvet.store import Store
from matchvet.t09 import FrozenEvidenceState, HistoricalMatch, TargetMatch
from matchvet.t10 import (
    DEFAULT_PREFERENCE_CATALOG,
    BettingPreference,
    PreferenceFamily,
    SettlementResult,
)

T11_MODEL_NAME = "matchvet-full-time-goal-model"
T11_MODEL_VERSION = "t11-full-time-goals-v1"
T11_ALGORITHM_VERSION = "hierarchical-recency-dixon-coles-map-v1"
T11_FEATURE_VERSION = "t11-frozen-t09-features-v1"
T11_MEDIA_TYPE = "application/vnd.matchvet.t11-full-time-goal-model+json"
T11_DISTRIBUTION_MEDIA_TYPE = "application/vnd.matchvet.t11-full-time-settlement-distribution+json"
MODEL_MEDIA_TYPE = T11_MEDIA_TYPE
FULL_TIME_GOAL_MODEL_VERSION = T11_MODEL_VERSION


class T11Error(Exception):
    """Base class for T11 fitting, prediction, and artifact errors."""


class T11ValidationError(T11Error, ValueError):
    """A T11 input is malformed or violates its frozen-input contract."""


class T11IntegrityError(T11Error):
    """An immutable T11 identity or artifact was reused with different content."""


class ModelStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


MODEL_UNAVAILABLE = ModelStatus.MODEL_UNAVAILABLE


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


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise T11ValidationError("T11 JSON values must be finite.")
        return value
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T11ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise T11ValidationError(f"{label} must be a finite number.")
    selected = float(value)
    if not math.isfinite(selected):
        raise T11ValidationError(f"{label} must be a finite number.")
    return selected


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise T11ValidationError("T11 timestamps must be ISO-8601 values.") from error
    if parsed.tzinfo is None:
        raise T11ValidationError("T11 timestamps must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _strings(values: Iterable[object]) -> tuple[str, ...]:
    selected = tuple(_text(item, "T11 identity") for item in values)
    return tuple(sorted(set(selected)))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise T11ValidationError(f"{label} must be an object.")
    return cast(Mapping[str, object], value)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


@dataclass(frozen=True)
class T11ModelConfig:
    """Versioned numerical and pooling controls for the T11 MAP fit."""

    name: str = T11_MODEL_NAME
    version: str = T11_MODEL_VERSION
    algorithm_version: str = T11_ALGORITHM_VERSION
    feature_version: str = T11_FEATURE_VERSION
    recency_half_life_days: float = 180.0
    regime_match_weight: float = 1.0
    regime_mismatch_weight: float = 0.35
    unknown_regime_weight: float = 0.75
    minimum_history_matches: int = 3
    minimum_effective_history_matches: float = 3.0
    minimum_shared_team_matches: int = 3
    maximum_expected_goals: float = 8.0
    maximum_score_goals: int = 40
    tail_tolerance: float = 1e-10
    dixon_coles_rho_bound: float = 0.01
    team_prior_scale: float = 0.45
    league_season_prior_scale: float = 0.35
    regime_prior_scale: float = 0.3
    home_advantage_prior_scale: float = 0.5
    rho_prior_scale: float = 1.0
    target_feature_scale: float = 0.05
    schedule_feature_scale: float = 0.02
    regime_feature_scale: float = 0.05
    optimizer_max_iterations: int = 500
    optimizer_ftol: float = 1e-11

    def __post_init__(self) -> None:
        _text(self.name, "T11 model name")
        _text(self.version, "T11 model version")
        _text(self.algorithm_version, "T11 algorithm version")
        _text(self.feature_version, "T11 feature version")
        for label, value in (
            ("recency half-life", self.recency_half_life_days),
            ("regime match weight", self.regime_match_weight),
            ("regime mismatch weight", self.regime_mismatch_weight),
            ("unknown regime weight", self.unknown_regime_weight),
            ("minimum effective history", self.minimum_effective_history_matches),
            ("maximum expected goals", self.maximum_expected_goals),
            ("tail tolerance", self.tail_tolerance),
            ("Dixon-Coles rho bound", self.dixon_coles_rho_bound),
            ("team prior scale", self.team_prior_scale),
            ("league-season prior scale", self.league_season_prior_scale),
            ("regime prior scale", self.regime_prior_scale),
            ("home advantage prior scale", self.home_advantage_prior_scale),
            ("rho prior scale", self.rho_prior_scale),
            ("target feature scale", self.target_feature_scale),
            ("schedule feature scale", self.schedule_feature_scale),
            ("regime feature scale", self.regime_feature_scale),
            ("optimizer ftol", self.optimizer_ftol),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise T11ValidationError(f"T11 {label} must be positive and finite.")
        if self.regime_match_weight > 1 or self.regime_mismatch_weight > 1:
            raise T11ValidationError("T11 regime weights cannot exceed one.")
        if self.minimum_history_matches < 1 or self.minimum_shared_team_matches < 1:
            raise T11ValidationError("T11 history minimums must be positive.")
        if self.maximum_score_goals < 2:
            raise T11ValidationError(
                "T11 score grids must include at least goals zero through two."
            )
        if self.tail_tolerance >= 1:
            raise T11ValidationError("T11 tail tolerance must be below one.")
        if self.dixon_coles_rho_bound * self.maximum_expected_goals**2 >= 1:
            raise T11ValidationError(
                "T11 Dixon-Coles correction can become negative at the configured goal cap."
            )
        if self.optimizer_max_iterations < 1:
            raise T11ValidationError("T11 optimizer iterations must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "dixon_coles_rho_bound": self.dixon_coles_rho_bound,
            "feature_version": self.feature_version,
            "home_advantage_prior_scale": self.home_advantage_prior_scale,
            "league_season_prior_scale": self.league_season_prior_scale,
            "maximum_expected_goals": self.maximum_expected_goals,
            "maximum_score_goals": self.maximum_score_goals,
            "minimum_effective_history_matches": self.minimum_effective_history_matches,
            "minimum_history_matches": self.minimum_history_matches,
            "minimum_shared_team_matches": self.minimum_shared_team_matches,
            "name": self.name,
            "optimizer_ftol": self.optimizer_ftol,
            "optimizer_max_iterations": self.optimizer_max_iterations,
            "recency_half_life_days": self.recency_half_life_days,
            "regime_match_weight": self.regime_match_weight,
            "regime_mismatch_weight": self.regime_mismatch_weight,
            "regime_prior_scale": self.regime_prior_scale,
            "rho_prior_scale": self.rho_prior_scale,
            "schedule_feature_scale": self.schedule_feature_scale,
            "tail_tolerance": self.tail_tolerance,
            "target_feature_scale": self.target_feature_scale,
            "regime_feature_scale": self.regime_feature_scale,
            "team_prior_scale": self.team_prior_scale,
            "unknown_regime_weight": self.unknown_regime_weight,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class SettlementProbabilities(Mapping[str, float]):
    """One complete WIN/PUSH/LOSS distribution for a preference."""

    win_probability: float
    loss_probability: float
    push_probability: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.win_probability,
            self.loss_probability,
            self.push_probability,
        )
        if any(not math.isfinite(float(value)) or float(value) < -1e-12 for value in values):
            raise T11ValidationError("Settlement probabilities must be finite and non-negative.")
        total = sum(float(value) for value in values)
        if abs(total - 1.0) > 1e-9:
            raise T11ValidationError("Settlement probabilities must sum to one.")
        object.__setattr__(
            self,
            "win_probability",
            max(0.0, min(1.0, float(self.win_probability))),
        )
        object.__setattr__(
            self,
            "loss_probability",
            max(0.0, min(1.0, float(self.loss_probability))),
        )
        object.__setattr__(
            self,
            "push_probability",
            max(0.0, min(1.0, float(self.push_probability))),
        )

    @property
    def win(self) -> float:
        return self.win_probability

    @property
    def loss(self) -> float:
        return self.loss_probability

    @property
    def push(self) -> float:
        return self.push_probability

    def to_dict(self) -> dict[str, float]:
        return {
            SettlementResult.LOSS.value: self.loss_probability,
            SettlementResult.PUSH.value: self.push_probability,
            SettlementResult.WIN.value: self.win_probability,
        }

    def __getitem__(self, key: str) -> float:
        try:
            return self.to_dict()[key.upper()]
        except KeyError as error:
            raise KeyError(key) from error

    def __iter__(self) -> Iterator[str]:
        return iter(
            (SettlementResult.LOSS.value, SettlementResult.PUSH.value, SettlementResult.WIN.value)
        )

    def __len__(self) -> int:
        return 3


_GOAL_FAMILIES = frozenset(
    {
        PreferenceFamily.MATCH_WINNER,
        PreferenceFamily.DOUBLE_CHANCE,
        PreferenceFamily.MATCH_GOALS_OVER,
        PreferenceFamily.HOME_TEAM_GOALS_OVER,
        PreferenceFamily.AWAY_TEAM_GOALS_OVER,
        PreferenceFamily.ASIAN_HANDICAP,
    }
)


def _goal_preferences() -> tuple[BettingPreference, ...]:
    return tuple(item for item in DEFAULT_PREFERENCE_CATALOG if item.family in _GOAL_FAMILIES)


FULL_TIME_GOAL_PREFERENCES = _goal_preferences()
FULL_TIME_GOAL_PREFERENCE_IDS = tuple(item.preference_id for item in FULL_TIME_GOAL_PREFERENCES)


def _freeze_map(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): value[key] for key in value})


@dataclass(frozen=True)
class FullTimeGoalDistribution:
    """The coherent T11 score grid and all 23 derived goal markets."""

    status: ModelStatus
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    score_distribution: tuple[tuple[float, ...], ...] = ()
    home_expected_goals: float | None = None
    away_expected_goals: float | None = None
    maximum_goals: int | None = None
    tail_mass: float | None = None
    settlement_distributions: Mapping[str, SettlementProbabilities] = field(default_factory=dict)
    feature_inputs: Mapping[str, object] = field(default_factory=dict)
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    artifact_digest: str | None = None
    distribution_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.target_fixture_id, "T11 target fixture ID")
        _text(self.matchweek_id, "T11 matchweek ID")
        _text(self.model_version, "T11 model version")
        _text(self.model_digest, "T11 model digest")
        if not isinstance(self.status, ModelStatus):
            object.__setattr__(self, "status", ModelStatus(str(self.status)))
        selected = {str(key): value for key, value in self.settlement_distributions.items()}
        if not all(isinstance(value, SettlementProbabilities) for value in selected.values()):
            raise T11ValidationError("T11 settlement distributions require typed probabilities.")
        object.__setattr__(self, "settlement_distributions", MappingProxyType(selected))
        object.__setattr__(self, "feature_inputs", _freeze_map(self.feature_inputs))
        object.__setattr__(self, "uncertainty", _freeze_map(self.uncertainty))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        if self.status is ModelStatus.AVAILABLE:
            if not self.score_distribution:
                raise T11ValidationError("An available T11 distribution requires a score grid.")
            rows = tuple(tuple(float(cell) for cell in row) for row in self.score_distribution)
            if not rows or any(len(row) != len(rows) for row in rows):
                raise T11ValidationError("T11 score grids must be square.")
            if any(not math.isfinite(cell) or cell < -1e-12 for row in rows for cell in row):
                raise T11ValidationError("T11 score grids must be finite and non-negative.")
            if abs(sum(sum(row) for row in rows) - 1.0) > 1e-9:
                raise T11ValidationError("T11 score grids must be normalized.")
            if self.home_expected_goals is None or self.away_expected_goals is None:
                raise T11ValidationError("Available T11 distributions require expected goals.")
            for label, value in (
                ("home expected goals", self.home_expected_goals),
                ("away expected goals", self.away_expected_goals),
            ):
                if not math.isfinite(float(value)) or float(value) < 0:
                    raise T11ValidationError(f"T11 {label} must be finite and non-negative.")
            if self.tail_mass is not None and (
                not math.isfinite(float(self.tail_mass)) or not 0.0 <= float(self.tail_mass) <= 1.0
            ):
                raise T11ValidationError("T11 score-grid tail mass must be between zero and one.")
            if not self.settlement_distributions:
                raise T11ValidationError("Available T11 distributions require market mappings.")
            if set(selected) != set(FULL_TIME_GOAL_PREFERENCE_IDS):
                raise T11ValidationError(
                    "Available T11 distributions must contain exactly the v1 "
                    "full-time goal markets."
                )
            object.__setattr__(self, "score_distribution", rows)
        else:
            if self.score_distribution or self.settlement_distributions:
                raise T11ValidationError(
                    "MODEL_UNAVAILABLE distributions cannot contain probability output."
                )
        expected = _digest(self._core_dict(include_digest=False))
        if self.distribution_digest and self.distribution_digest != expected:
            raise T11IntegrityError("T11 distribution digest does not match its content.")
        object.__setattr__(self, "distribution_digest", expected)

    @property
    def digest(self) -> str:
        return self.distribution_digest

    @property
    def score_grid(self) -> tuple[tuple[float, ...], ...]:
        return self.score_distribution

    @property
    def joint_score_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.score_distribution

    @property
    def market_distributions(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def preference_distributions(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def settlement_probabilities(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def is_available(self) -> bool:
        return self.status is ModelStatus.AVAILABLE

    @property
    def model_unavailable(self) -> bool:
        return self.status is ModelStatus.MODEL_UNAVAILABLE

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "away_expected_goals": self.away_expected_goals,
            "diagnostics": dict(self.diagnostics),
            "feature_inputs": dict(self.feature_inputs),
            "home_expected_goals": self.home_expected_goals,
            "matchweek_id": self.matchweek_id,
            "maximum_goals": self.maximum_goals,
            "model_digest": self.model_digest,
            "model_version": self.model_version,
            "reason": self.reason,
            "score_distribution": self.score_distribution,
            "settlement_distributions": {
                key: value.to_dict() for key, value in sorted(self.settlement_distributions.items())
            },
            "status": self.status.value,
            "tail_mass": self.tail_mass,
            "target_fixture_id": self.target_fixture_id,
            "uncertainty": dict(self.uncertainty),
        }
        if include_digest:
            payload["distribution_digest"] = self.distribution_digest
        return payload

    def to_dict(self, *, include_publication: bool = True) -> dict[str, object]:
        payload = self._core_dict()
        if include_publication:
            payload["artifact_digest"] = self.artifact_digest
        return payload

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict(include_publication=False))

    def with_artifact(self, artifact_digest: str) -> FullTimeGoalDistribution:
        return replace(self, artifact_digest=_text(artifact_digest, "T11 artifact digest"))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FullTimeGoalDistribution:
        status = ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value)))
        settlements: dict[str, SettlementProbabilities] = {}
        settlement_raw = value.get("settlement_distributions", {})
        if isinstance(settlement_raw, Mapping):
            for key, item in settlement_raw.items():
                mapped = _mapping(item, "T11 settlement distribution")
                settlements[str(key)] = SettlementProbabilities(
                    win_probability=_finite(mapped.get(SettlementResult.WIN.value), "T11 WIN"),
                    loss_probability=_finite(mapped.get(SettlementResult.LOSS.value), "T11 LOSS"),
                    push_probability=_finite(
                        mapped.get(SettlementResult.PUSH.value, 0.0), "T11 PUSH"
                    ),
                )
        score = tuple(
            tuple(float(cell) for cell in row)
            for row in _as_sequence(value.get("score_distribution", ()))
            if isinstance(row, (tuple, list))
        )
        maximum_value = value.get("maximum_goals")
        maximum_goals = (
            int(maximum_value)
            if isinstance(maximum_value, int) and not isinstance(maximum_value, bool)
            else None
        )
        reason_value = value.get("reason")
        if status is ModelStatus.AVAILABLE:
            expected_settlements = _settlement_distributions(score)
            if set(expected_settlements) != set(settlements) or any(
                any(
                    abs(
                        getattr(expected_settlements[key], field_name)
                        - getattr(settlements[key], field_name)
                    )
                    > 1e-9
                    for field_name in ("win", "loss", "push")
                )
                for key in expected_settlements
                if key in settlements
            ):
                raise T11IntegrityError(
                    "T11 settlement distributions do not match the stored score grid."
                )
        return cls(
            status=status,
            target_fixture_id=_text(value.get("target_fixture_id"), "T11 fixture ID"),
            matchweek_id=_text(value.get("matchweek_id"), "T11 matchweek ID"),
            model_version=_text(value.get("model_version"), "T11 model version"),
            model_digest=_text(value.get("model_digest"), "T11 model digest"),
            score_distribution=score,
            home_expected_goals=(
                _number(value.get("home_expected_goals"))
                if value.get("home_expected_goals") is not None
                else None
            ),
            away_expected_goals=(
                _number(value.get("away_expected_goals"))
                if value.get("away_expected_goals") is not None
                else None
            ),
            maximum_goals=maximum_goals,
            tail_mass=(
                _number(value.get("tail_mass")) if value.get("tail_mass") is not None else None
            ),
            settlement_distributions=settlements,
            feature_inputs=_mapping(value.get("feature_inputs", {}), "T11 feature inputs"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T11 uncertainty"),
            diagnostics=_mapping(value.get("diagnostics", {}), "T11 diagnostics"),
            reason=reason_value if isinstance(reason_value, str) else None,
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            distribution_digest=str(value.get("distribution_digest", "")),
        )


@dataclass(frozen=True)
class FullTimeGoalModelFit:
    """A deterministic fitted T11 model with auditable input identity."""

    status: ModelStatus
    model_name: str
    model_version: str
    algorithm_version: str
    feature_version: str
    target: TargetMatch
    config: T11ModelConfig
    parameters: Mapping[str, object] = field(default_factory=dict)
    training_input_fixture_ids: tuple[str, ...] = ()
    training_input_digests: tuple[str, ...] = ()
    training_input_ids: tuple[str, ...] = ()
    frozen_evidence_digest: str = ""
    frozen_artifact_digest: str | None = None
    frozen_manifest_digest: str | None = None
    feature_input_ids: tuple[str, ...] = ()
    feature_input_digests: tuple[str, ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    reproducibility: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    artifact_digest: str | None = None
    fit_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ModelStatus):
            object.__setattr__(self, "status", ModelStatus(str(self.status)))
        _text(self.model_name, "T11 model name")
        _text(self.model_version, "T11 model version")
        _text(self.algorithm_version, "T11 algorithm version")
        _text(self.feature_version, "T11 feature version")
        if not isinstance(self.target, TargetMatch):
            raise T11ValidationError("T11 fits require a TargetMatch.")
        if not isinstance(self.config, T11ModelConfig):
            raise T11ValidationError("T11 fits require a T11ModelConfig.")
        for name in (
            "parameters",
            "diagnostics",
            "uncertainty",
            "reproducibility",
        ):
            object.__setattr__(self, name, _freeze_map(getattr(self, name)))
        for name in (
            "training_input_fixture_ids",
            "training_input_digests",
            "training_input_ids",
            "feature_input_ids",
            "feature_input_digests",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name)))
        if self.status is ModelStatus.AVAILABLE and not self.parameters:
            raise T11ValidationError("Available T11 fits require fitted parameters.")
        expected = _digest(self._core_dict(include_digest=False))
        if self.fit_digest and self.fit_digest != expected:
            raise T11IntegrityError("T11 fit digest does not match its content.")
        object.__setattr__(self, "fit_digest", expected)

    @property
    def digest(self) -> str:
        return self.fit_digest

    @property
    def model_digest(self) -> str:
        return self.fit_digest

    @property
    def model_parameters(self) -> Mapping[str, object]:
        return self.parameters

    @property
    def target_fixture_id(self) -> str:
        return self.target.fixture_id

    @property
    def matchweek_id(self) -> str:
        return self.target.matchweek_id

    @property
    def is_available(self) -> bool:
        return self.status is ModelStatus.AVAILABLE

    @property
    def model_unavailable(self) -> bool:
        return self.status is ModelStatus.MODEL_UNAVAILABLE

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "algorithm_version": self.algorithm_version,
            "config": self.config.to_dict(),
            "diagnostics": dict(self.diagnostics),
            "feature_input_digests": self.feature_input_digests,
            "feature_input_ids": self.feature_input_ids,
            "feature_version": self.feature_version,
            "frozen_artifact_digest": self.frozen_artifact_digest,
            "frozen_evidence_digest": self.frozen_evidence_digest,
            "frozen_manifest_digest": self.frozen_manifest_digest,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "reproducibility": dict(self.reproducibility),
            "status": self.status.value,
            "target": self.target.to_dict(),
            "training_input_digests": self.training_input_digests,
            "training_input_fixture_ids": self.training_input_fixture_ids,
            "training_input_ids": self.training_input_ids,
            "uncertainty": dict(self.uncertainty),
        }
        if include_digest:
            payload["fit_digest"] = self.fit_digest
        return payload

    def to_dict(self, *, include_publication: bool = True) -> dict[str, object]:
        payload = self._core_dict()
        if include_publication:
            payload["artifact_digest"] = self.artifact_digest
        return payload

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict(include_publication=False))

    def with_artifact(self, artifact_digest: str) -> FullTimeGoalModelFit:
        return replace(self, artifact_digest=_text(artifact_digest, "T11 artifact digest"))

    def predict(
        self,
        frozen_evidence_state: FrozenEvidenceState | None = None,
    ) -> FullTimeGoalDistribution:
        """Derive one coherent full-time distribution from this fitted model."""
        return predict_full_time_goal_distribution(self, frozen_evidence_state)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FullTimeGoalModelFit:
        target_value = _mapping(value.get("target"), "T11 fit target")
        config_value = _mapping(value.get("config"), "T11 fit config")
        config_fields = {
            key: config_value[key]
            for key in T11ModelConfig.__dataclass_fields__
            if key in config_value
        }
        return cls(
            status=ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value))),
            model_name=_text(value.get("model_name"), "T11 model name"),
            model_version=_text(value.get("model_version"), "T11 model version"),
            algorithm_version=_text(value.get("algorithm_version"), "T11 algorithm version"),
            feature_version=_text(value.get("feature_version"), "T11 feature version"),
            target=TargetMatch(**cast(dict[str, Any], dict(target_value))),
            config=T11ModelConfig(**cast(dict[str, Any], config_fields)),
            parameters=_mapping(value.get("parameters", {}), "T11 parameters"),
            training_input_fixture_ids=tuple(
                item
                for item in _as_sequence(value.get("training_input_fixture_ids", ()))
                if isinstance(item, str)
            ),
            training_input_digests=tuple(
                item
                for item in _as_sequence(value.get("training_input_digests", ()))
                if isinstance(item, str)
            ),
            training_input_ids=tuple(
                item
                for item in _as_sequence(value.get("training_input_ids", ()))
                if isinstance(item, str)
            ),
            frozen_evidence_digest=str(value.get("frozen_evidence_digest", "")),
            frozen_artifact_digest=(
                str(value["frozen_artifact_digest"])
                if value.get("frozen_artifact_digest") is not None
                else None
            ),
            frozen_manifest_digest=(
                str(value["frozen_manifest_digest"])
                if value.get("frozen_manifest_digest") is not None
                else None
            ),
            feature_input_ids=tuple(
                item
                for item in _as_sequence(value.get("feature_input_ids", ()))
                if isinstance(item, str)
            ),
            feature_input_digests=tuple(
                item
                for item in _as_sequence(value.get("feature_input_digests", ()))
                if isinstance(item, str)
            ),
            diagnostics=_mapping(value.get("diagnostics", {}), "T11 diagnostics"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T11 uncertainty"),
            reproducibility=_mapping(value.get("reproducibility", {}), "T11 reproducibility"),
            reason=(cast(str, value["reason"]) if isinstance(value.get("reason"), str) else None),
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            fit_digest=str(value.get("fit_digest", "")),
        )


@dataclass(frozen=True)
class _TrainingMatch:
    """The small immutable row used by the numerical fitter."""

    fixture_id: str
    home_team_id: str
    away_team_id: str
    league_key: str
    kickoff_utc: str
    home_goals: int
    away_goals: int
    recency_weight: float
    regime_weight: float
    regime_id: str | None

    @property
    def weight_without_regime(self) -> float:
        return self.recency_weight

    @property
    def weight(self) -> float:
        return self.recency_weight * self.regime_weight


class _T11FitFailure(T11Error):
    """Internal signal for a failed numerical fit that must become unavailable."""


def _numeric_modules() -> tuple[Any, Callable[..., Any], Callable[..., Any]]:
    """Load the native numerical stack only when a fit or prediction is requested."""
    try:
        import numpy as np
        from scipy.optimize import minimize  # type: ignore[import-untyped]
        from scipy.special import gammaln  # type: ignore[import-untyped]
    except ImportError as error:
        raise _T11FitFailure(
            "T11 requires the native NumPy/SciPy runtime for deterministic MAP fitting."
        ) from error
    return np, minimize, gammaln


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _feature_map(state: FrozenEvidenceState) -> Mapping[str, object]:
    return {feature.name: feature for feature in state.derived_features}


def _feature_is_observed(value: object) -> bool:
    selected = getattr(value, "state", None)
    return selected is EvidenceState.OBSERVED or str(selected) == EvidenceState.OBSERVED.value


def _feature_value(state: FrozenEvidenceState, name: str) -> object | None:
    feature = _feature_map(state).get(name)
    if feature is None or not _feature_is_observed(feature):
        return None
    return getattr(feature, "value", None)


def _feature_lineage(
    state: FrozenEvidenceState, names: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected_names = set(names)
    input_ids: set[str] = set()
    input_digests: set[str] = set()
    for feature in state.derived_features:
        if feature.name not in selected_names or not _feature_is_observed(feature):
            continue
        input_ids.update(feature.input_ids)
        input_digests.update(feature.input_digests)
        input_ids.add(feature.feature_id)
        input_digests.add(feature.digest)
    return tuple(sorted(input_ids)), tuple(sorted(input_digests))


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _team_feature_value(value: object, team_id: str) -> Mapping[str, object]:
    mapped = _mapping_or_empty(value)
    selected = mapped.get(team_id)
    return selected if isinstance(selected, Mapping) else {}


def _side_feature_value(value: object, side: str, team_id: str) -> Mapping[str, object]:
    mapped = _mapping_or_empty(value)
    selected = mapped.get(side)
    if isinstance(selected, Mapping):
        return selected
    selected = mapped.get(team_id)
    return selected if isinstance(selected, Mapping) else {}


def _side_feature_raw(value: object, side: str, team_id: str) -> object | None:
    mapped = _mapping_or_empty(value)
    if side in mapped:
        return mapped[side]
    return mapped.get(team_id)


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _regime_token(value: object, depth: int = 0) -> str | None:
    if depth > 4:
        return None
    if isinstance(value, str):
        selected = value.strip()
        if selected and selected.upper() not in {"UNKNOWN", "NONE", "NULL", "REGIME_NOT_RECORDED"}:
            return selected
        return None
    if isinstance(value, Mapping):
        for key in (
            "regime_id",
            "active_regime",
            "regime",
            "regime_key",
            "label",
            "name",
            "id",
            "value",
        ):
            if key in value:
                candidate = _regime_token(value[key], depth + 1)
                if candidate is not None:
                    return candidate
    return None


def _target_regime(state: FrozenEvidenceState) -> str | None:
    return _regime_token(_feature_value(state, "E-TACTICAL-REGIME"))


def _state_history_ids(state: FrozenEvidenceState) -> tuple[str, ...]:
    raw = state.reproducibility.get("input_history_fixture_ids", ())
    return tuple(sorted(item for item in _as_sequence(raw) if isinstance(item, str)))


def _history_digest(match: HistoricalMatch) -> str:
    return (
        match.source_digest
        if isinstance(match.source_digest, str) and match.source_digest
        else _digest(match.to_dict())
    )


def _frozen_history_input_mismatches(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> tuple[str, ...]:
    """Compare model-used goal facts with the history embedded in frozen T09 inputs."""
    expected_ids = set(_state_history_ids(state))
    if not expected_ids:
        return ()
    frozen: dict[str, dict[str, object]] = {}
    for fact in state.source_assertions:
        if (
            fact.evidence_type != "MATCH_STATISTIC"
            or fact.subject_id not in expected_ids
            or fact.predicate not in {"full_time_home_goals", "full_time_away_goals"}
        ):
            continue
        entry = frozen.setdefault(fact.subject_id, {})
        entry[fact.predicate] = fact.value
        if fact.source_digest is not None:
            entry["source_digest"] = fact.source_digest

    by_fixture = {match.fixture_id: match for match in history}
    mismatches: list[str] = []
    for fixture_id, inputs in sorted(frozen.items()):
        match = by_fixture.get(fixture_id)
        if match is None:
            continue
        if (
            "full_time_home_goals" in inputs
            and match.full_time_home_goals != inputs["full_time_home_goals"]
        ) or (
            "full_time_away_goals" in inputs
            and match.full_time_away_goals != inputs["full_time_away_goals"]
        ):
            mismatches.append(fixture_id)
            continue
        frozen_digest = inputs.get("source_digest")
        if isinstance(frozen_digest, str) and _history_digest(match) != frozen_digest:
            mismatches.append(fixture_id)
    return tuple(mismatches)


def _cutoff_valid_history_match(match: HistoricalMatch, cutoff: datetime) -> bool:
    if match.fixture_status.upper() not in {"COMPLETED", "FINAL", "FINISHED"}:
        return False
    if match.final_state is not EvidenceState.OBSERVED:
        return False
    timestamps = (match.kickoff_utc, match.observed_at_utc, match.published_at_utc)
    return not any(value is not None and _parse_utc(value) > cutoff for value in timestamps)


def _coerce_history(
    value: Iterable[HistoricalMatch | Mapping[str, object]],
) -> tuple[HistoricalMatch, ...]:
    selected: list[HistoricalMatch] = []
    for item in value:
        if isinstance(item, HistoricalMatch):
            selected.append(item)
        elif isinstance(item, Mapping):
            selected.append(HistoricalMatch.from_mapping(item))
        else:
            raise T11ValidationError("T11 history must contain HistoricalMatch records.")
    return tuple(selected)


def _league_season_key(competition_key: str, season: str) -> str:
    return f"{competition_key}:{season}"


def _training_rows(
    history: Iterable[HistoricalMatch | Mapping[str, object]],
    state: FrozenEvidenceState,
    config: T11ModelConfig,
) -> tuple[tuple[_TrainingMatch, ...], tuple[HistoricalMatch, ...]]:
    target = state.target
    cutoff = _parse_utc(target.cutoff_utc)
    expected_ids = set(_state_history_ids(state))
    by_fixture: dict[str, HistoricalMatch] = {}
    for match in _coerce_history(history):
        if expected_ids and match.fixture_id not in expected_ids:
            continue
        if not _cutoff_valid_history_match(match, cutoff):
            continue
        if match.full_time_home_goals is None or match.full_time_away_goals is None:
            continue
        if (
            match.metric_state("full_time_home_goals") is not EvidenceState.OBSERVED
            or match.metric_state("full_time_away_goals") is not EvidenceState.OBSERVED
        ):
            continue
        home_goals = match.full_time_home_goals
        away_goals = match.full_time_away_goals
        assert home_goals is not None and away_goals is not None
        for label, value in (("home goals", home_goals), ("away goals", away_goals)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise T11ValidationError(f"T11 {label} must be a non-negative integer.")
            if value > 100_000:
                raise T11ValidationError(f"T11 {label} is outside the supported numerical range.")
        previous = by_fixture.get(match.fixture_id)
        if previous is not None and previous.to_dict() != match.to_dict():
            raise T11IntegrityError(
                f"Historical Match {match.fixture_id} was supplied with conflicting content."
            )
        by_fixture[match.fixture_id] = match

    ordered = tuple(sorted(by_fixture.values(), key=lambda item: item.fixture_id))
    target_regime = _target_regime(state)
    rows: list[_TrainingMatch] = []
    for match in ordered:
        row_home_goals = match.full_time_home_goals
        row_away_goals = match.full_time_away_goals
        assert row_home_goals is not None and row_away_goals is not None
        age_days = max(
            0.0,
            (cutoff - _parse_utc(match.kickoff_utc)).total_seconds() / 86_400.0,
        )
        recency_weight = 2.0 ** (-age_days / config.recency_half_life_days)
        if target_regime is None:
            regime_weight = 1.0
        elif match.regime_id is None:
            regime_weight = config.unknown_regime_weight
        elif match.regime_id == target_regime:
            regime_weight = config.regime_match_weight
        else:
            regime_weight = config.regime_mismatch_weight
        rows.append(
            _TrainingMatch(
                fixture_id=match.fixture_id,
                home_team_id=match.home_team_id,
                away_team_id=match.away_team_id,
                league_key=_league_season_key(
                    match.competition_key or target.competition_key, target.season
                ),
                kickoff_utc=match.kickoff_utc,
                home_goals=row_home_goals,
                away_goals=row_away_goals,
                recency_weight=recency_weight,
                regime_weight=regime_weight,
                regime_id=match.regime_id,
            )
        )
    return tuple(rows), ordered


def _minimum_evidence_reason(
    rows: Sequence[_TrainingMatch], target: TargetMatch, config: T11ModelConfig
) -> str | None:
    if len(rows) < config.minimum_history_matches:
        return "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"
    effective = sum(row.weight for row in rows)
    if effective < config.minimum_effective_history_matches:
        return "MINIMUM_EFFECTIVE_HISTORY_NOT_SATISFIED"
    teams = {team for row in rows for team in (row.home_team_id, row.away_team_id)}
    if len(teams) < 2:
        return "MINIMUM_SHARED_TEAM_EVIDENCE_NOT_SATISFIED"
    target_counts = {
        team_id: sum(team_id in (row.home_team_id, row.away_team_id) for row in rows)
        for team_id in target.team_ids
    }
    shared = len(rows)
    if any(
        count < 1 and shared < config.minimum_shared_team_matches
        for count in target_counts.values()
    ):
        return "MINIMUM_DIRECT_AND_SHARED_HISTORY_NOT_SATISFIED"
    return None


_T11_FEATURE_NAMES = (
    "D-OPPONENT-STRENGTH",
    "D-VENUE-EFFECT",
    "D-RECENCY-STRENGTH",
    "D-FORM-HORIZONS",
    "D-TREND-DIRECTION",
    "D-REST",
    "D-CONGESTION",
    "D-CROSS-COMP-WORKLOAD",
    "E-TACTICAL-REGIME",
)


def _feature_offsets(
    state: FrozenEvidenceState | None,
    target: TargetMatch,
    config: T11ModelConfig,
    *,
    baseline_goal_rate: float,
    regime_effects: Mapping[str, object] | None = None,
    stored: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    if state is None:
        if stored is not None:
            return stored
        return {"home": 0.0, "away": 0.0, "components": {}}

    opponent = _feature_value(state, "D-OPPONENT-STRENGTH")
    venue = _feature_value(state, "D-VENUE-EFFECT")
    recency = _feature_value(state, "D-RECENCY-STRENGTH")
    horizons = _feature_value(state, "D-FORM-HORIZONS")
    trends = _feature_value(state, "D-TREND-DIRECTION")
    rest = _feature_value(state, "D-REST")
    congestion = _feature_value(state, "D-CONGESTION")
    cross_competition = _feature_value(state, "D-CROSS-COMP-WORKLOAD")
    regime_id = _target_regime(state)
    scale = config.target_feature_scale
    components: dict[str, dict[str, float]] = {
        "opponent": {"home": 0.0, "away": 0.0},
        "venue": {"home": 0.0, "away": 0.0},
        "recency": {"home": 0.0, "away": 0.0},
        "form": {"home": 0.0, "away": 0.0},
        "schedule": {"home": 0.0, "away": 0.0},
        "regime": {"home": 0.0, "away": 0.0},
    }

    for side, team_id in (("home", target.home_team_id), ("away", target.away_team_id)):
        team_opponent = _team_feature_value(opponent, team_id)
        opponent_adjusted = _mapping_or_empty(team_opponent.get("opponent_adjusted"))
        opponent_difference = _number(opponent_adjusted.get("mean_difference"))
        if opponent_difference is not None:
            components["opponent"][side] = scale * _bounded(opponent_difference, -4.0, 4.0)

        team_venue = _team_feature_value(venue, team_id)
        venue_effect = _number(team_venue.get("venue_effect"))
        if venue_effect is not None:
            venue_direction = 1.0 if side == "home" else -1.0
            components["venue"][side] = venue_direction * scale * _bounded(venue_effect, -4.0, 4.0)

        team_recency = _team_feature_value(recency, team_id)
        weighted_mean = _number(team_recency.get("weighted_mean"))
        if weighted_mean is not None and baseline_goal_rate > 0:
            components["recency"][side] = scale * _bounded(
                weighted_mean - baseline_goal_rate, -3.0, 3.0
            )

        team_horizon = _team_feature_value(horizons, team_id)
        recent = _number(_mapping_or_empty(team_horizon.get("recent")).get("mean"))
        medium = _number(_mapping_or_empty(team_horizon.get("medium")).get("mean"))
        if recent is not None and medium is not None:
            components["form"][side] = 0.5 * scale * _bounded(recent - medium, -3.0, 3.0)
        else:
            team_trend = _team_feature_value(trends, team_id)
            trend_direction = str(team_trend.get("direction", "")).upper()
            if trend_direction == "INCREASING":
                components["form"][side] = 0.25 * scale
            elif trend_direction == "DECREASING":
                components["form"][side] = -0.25 * scale

        rest_raw = _side_feature_raw(rest, side, team_id)
        rest_map = _mapping_or_empty(rest_raw)
        rest_value = _number(rest_map.get("rest_days") if rest_map else rest_raw)
        congestion_map = _side_feature_value(congestion, side, team_id)
        congestion_count = _number(congestion_map.get("count"))
        if rest_value is not None:
            components["schedule"][side] += config.schedule_feature_scale * _bounded(
                (rest_value - 7.0) / 7.0, -1.0, 1.0
            )
        if congestion_count is not None:
            components["schedule"][side] -= config.schedule_feature_scale * _bounded(
                congestion_count / 5.0, 0.0, 1.0
            )
        cross_competition_raw = _side_feature_raw(cross_competition, side, team_id)
        cross_competition_count: float | None
        if isinstance(cross_competition_raw, (tuple, list)):
            cross_competition_count = float(len(cross_competition_raw))
        elif isinstance(cross_competition_raw, Mapping):
            cross_competition_count = _number(cross_competition_raw.get("count"))
        else:
            cross_competition_count = None
        if cross_competition_count is not None:
            components["schedule"][side] -= (
                config.schedule_feature_scale
                * 0.25
                * _bounded(cross_competition_count / 3.0, 0.0, 1.0)
            )

    selected_regime_effects = regime_effects or {}
    regime_value = (
        _number(selected_regime_effects.get(regime_id)) if regime_id is not None else None
    )
    if regime_value is not None:
        regime_offset = config.regime_feature_scale * _bounded(regime_value, -2.0, 2.0)
        components["regime"]["home"] = regime_offset
        components["regime"]["away"] = regime_offset

    home_offset = sum(item["home"] for item in components.values())
    away_offset = sum(item["away"] for item in components.values())
    return {
        "home": home_offset,
        "away": away_offset,
        "components": components,
        "regime_id": regime_id,
        "feature_names": _T11_FEATURE_NAMES,
    }


def _parameter_layout(team_count: int, league_count: int) -> tuple[int, int, int, int, int]:
    league_start = 0
    home_index = league_count
    rho_index = league_count + 1
    attack_start = league_count + 2
    defense_start = attack_start + team_count
    return league_start, home_index, rho_index, attack_start, defense_start


def _fit_numerical_parameters(
    rows: Sequence[_TrainingMatch],
    target: TargetMatch,
    config: T11ModelConfig,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    np, minimize, gammaln = _numeric_modules()
    team_ids = tuple(
        sorted(
            {
                *target.team_ids,
                *(team_id for row in rows for team_id in (row.home_team_id, row.away_team_id)),
            }
        )
    )
    target_league_key = _league_season_key(target.competition_key, target.season)
    league_keys = tuple(sorted({row.league_key for row in rows} | {target_league_key}))
    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    league_index = {league: index for index, league in enumerate(league_keys)}
    team_count = len(team_ids)
    league_count = len(league_keys)
    _, home_index, rho_index, attack_start, defense_start = _parameter_layout(
        team_count, league_count
    )

    home_goals = np.asarray([row.home_goals for row in rows], dtype=np.float64)
    away_goals = np.asarray([row.away_goals for row in rows], dtype=np.float64)
    home_indices = np.asarray([team_index[row.home_team_id] for row in rows], dtype=np.int64)
    away_indices = np.asarray([team_index[row.away_team_id] for row in rows], dtype=np.int64)
    league_indices = np.asarray([league_index[row.league_key] for row in rows], dtype=np.int64)
    weights = np.asarray([row.weight for row in rows], dtype=np.float64)
    if not np.all(np.isfinite(weights)) or float(np.sum(weights)) <= 0:
        raise _T11FitFailure("T11 training weights are not finite and positive.")

    total_weight = float(np.sum(weights))
    overall_home = float(np.sum(weights * home_goals) / total_weight)
    overall_away = float(np.sum(weights * away_goals) / total_weight)
    baseline_goal_rate = max((overall_home + overall_away) / 2.0, 0.05)
    maximum_expected = max(config.maximum_expected_goals, 0.05)
    log_max = math.log(maximum_expected)
    log_min = min(-8.0, log_max - 4.0)

    league_initial = np.full(league_count, math.log(baseline_goal_rate), dtype=np.float64)
    for _key, index in league_index.items():
        selected = league_indices == index
        selected_weight = float(np.sum(weights[selected]))
        if selected_weight > 0:
            league_rate = float(
                np.sum(weights[selected] * (home_goals[selected] + away_goals[selected]) / 2.0)
                / selected_weight
            )
            league_initial[index] = math.log(_bounded(league_rate, 0.05, maximum_expected))
    home_initial = math.log(
        _bounded(
            max(overall_home, 0.05) / max(overall_away, 0.05),
            math.exp(-2.5),
            math.exp(2.5),
        )
    )
    initial = np.concatenate(
        (
            league_initial,
            np.asarray([home_initial, 0.0], dtype=np.float64),
            np.zeros(team_count, dtype=np.float64),
            np.zeros(team_count, dtype=np.float64),
        )
    )

    def unpack(vector: Any) -> tuple[Any, ...]:
        league = vector[:league_count]
        home_advantage = vector[home_index]
        rho_raw = vector[rho_index]
        attack = vector[attack_start:defense_start]
        defense = vector[defense_start:]
        attack_centered = attack - np.mean(attack)
        defense_centered = defense - np.mean(defense)
        eta_home_raw = (
            league[league_indices]
            + home_advantage
            + attack_centered[home_indices]
            - defense_centered[away_indices]
        )
        eta_away_raw = (
            league[league_indices] + attack_centered[away_indices] - defense_centered[home_indices]
        )
        eta_home = np.clip(eta_home_raw, log_min, log_max)
        eta_away = np.clip(eta_away_raw, log_min, log_max)
        lambda_home = np.exp(eta_home)
        lambda_away = np.exp(eta_away)
        rho = config.dixon_coles_rho_bound * np.tanh(rho_raw)
        return (
            league,
            home_advantage,
            rho_raw,
            attack,
            defense,
            eta_home_raw,
            eta_away_raw,
            lambda_home,
            lambda_away,
            rho,
        )

    def value_and_gradient(vector: Any) -> tuple[float, Any]:
        (
            league,
            home_advantage,
            rho_raw,
            attack,
            defense,
            eta_home_raw,
            eta_away_raw,
            lambda_home,
            lambda_away,
            rho,
        ) = unpack(vector)
        del league, home_advantage, attack, defense
        eta_home = np.clip(eta_home_raw, log_min, log_max)
        eta_away = np.clip(eta_away_raw, log_min, log_max)
        tau = np.ones(len(rows), dtype=np.float64)
        zero_zero = (home_goals == 0) & (away_goals == 0)
        zero_one = (home_goals == 0) & (away_goals == 1)
        one_zero = (home_goals == 1) & (away_goals == 0)
        one_one = (home_goals == 1) & (away_goals == 1)
        tau[zero_zero] = 1.0 - lambda_home[zero_zero] * lambda_away[zero_zero] * rho
        tau[zero_one] = 1.0 + lambda_home[zero_one] * rho
        tau[one_zero] = 1.0 + lambda_away[one_zero] * rho
        tau[one_one] = 1.0 - rho
        if not np.all(np.isfinite(tau)) or np.any(tau <= 0):
            return math.inf, np.full_like(vector, math.nan, dtype=np.float64)
        log_likelihood = np.sum(
            weights
            * (
                home_goals * eta_home
                - lambda_home
                - gammaln(home_goals + 1.0)
                + away_goals * eta_away
                - lambda_away
                - gammaln(away_goals + 1.0)
                + np.log(tau)
            )
        )
        g_home_eta = home_goals - lambda_home
        g_away_eta = away_goals - lambda_away
        correction_home = np.zeros(len(rows), dtype=np.float64)
        correction_away = np.zeros(len(rows), dtype=np.float64)
        correction_home[zero_zero] = (
            -lambda_home[zero_zero] * lambda_away[zero_zero] * rho / tau[zero_zero]
        )
        correction_home[zero_one] = lambda_home[zero_one] * rho / tau[zero_one]
        correction_away[zero_zero] = (
            -lambda_home[zero_zero] * lambda_away[zero_zero] * rho / tau[zero_zero]
        )
        correction_away[one_zero] = lambda_away[one_zero] * rho / tau[one_zero]
        g_home_eta += correction_home
        g_away_eta += correction_away
        tau_rho = np.zeros(len(rows), dtype=np.float64)
        tau_rho[zero_zero] = -lambda_home[zero_zero] * lambda_away[zero_zero]
        tau_rho[zero_one] = lambda_home[zero_one]
        tau_rho[one_zero] = lambda_away[one_zero]
        tau_rho[one_one] = -1.0
        rho_gradient = float(
            np.sum(weights * tau_rho / tau)
            * config.dixon_coles_rho_bound
            * (1.0 - np.tanh(float(rho_raw)) ** 2)
        )

        active_home = ((eta_home_raw > log_min) & (eta_home_raw < log_max)).astype(np.float64)
        active_away = ((eta_away_raw > log_min) & (eta_away_raw < log_max)).astype(np.float64)
        g_home_eta *= active_home
        g_away_eta *= active_away
        weighted_home = weights * g_home_eta
        weighted_away = weights * g_away_eta
        gradient = np.zeros_like(vector, dtype=np.float64)
        gradient[:league_count] = np.bincount(
            league_indices, weights=weighted_home + weighted_away, minlength=league_count
        )
        gradient[home_index] = float(np.sum(weighted_home))
        gradient[rho_index] = rho_gradient
        attack_direct = np.bincount(
            home_indices, weights=weighted_home, minlength=team_count
        ) + np.bincount(away_indices, weights=weighted_away, minlength=team_count)
        defense_direct = np.bincount(
            away_indices, weights=-weighted_home, minlength=team_count
        ) + np.bincount(home_indices, weights=-weighted_away, minlength=team_count)
        gradient[attack_start:defense_start] = attack_direct - np.mean(attack_direct)
        gradient[defense_start:] = defense_direct - np.mean(defense_direct)

        prior = 0.0
        prior_gradient = np.zeros_like(vector, dtype=np.float64)
        league_prior = math.log(baseline_goal_rate)
        league_delta = vector[:league_count] - league_prior
        prior += 0.5 * float(np.sum(league_delta**2)) / config.league_season_prior_scale**2
        prior_gradient[:league_count] += league_delta / config.league_season_prior_scale**2
        home_delta = float(vector[home_index] - home_initial)
        prior += 0.5 * home_delta**2 / config.home_advantage_prior_scale**2
        prior_gradient[home_index] += home_delta / config.home_advantage_prior_scale**2
        prior += 0.5 * float(rho_raw**2) / config.rho_prior_scale**2
        prior_gradient[rho_index] += float(rho_raw) / config.rho_prior_scale**2
        prior += (
            0.5
            * float(np.sum(vector[attack_start:defense_start] ** 2))
            / config.team_prior_scale**2
        )
        prior_gradient[attack_start:defense_start] += (
            vector[attack_start:defense_start] / config.team_prior_scale**2
        )
        prior += 0.5 * float(np.sum(vector[defense_start:] ** 2)) / config.team_prior_scale**2
        prior_gradient[defense_start:] += vector[defense_start:] / config.team_prior_scale**2
        objective = float(-log_likelihood + prior)
        full_gradient = -gradient + prior_gradient
        if not math.isfinite(objective) or not np.all(np.isfinite(full_gradient)):
            return math.inf, np.full_like(vector, math.nan, dtype=np.float64)
        return objective, full_gradient

    bounds: list[tuple[float, float]] = [(log_min, log_max)] * league_count
    bounds.extend(((-2.5, 2.5), (-8.0, 8.0)))
    bounds.extend([(-4.0, 4.0)] * (team_count * 2))
    result = minimize(
        lambda vector: value_and_gradient(vector)[0],
        initial,
        jac=lambda vector: value_and_gradient(vector)[1],
        method="L-BFGS-B",
        bounds=bounds,
        options={
            "ftol": config.optimizer_ftol,
            "gtol": 1e-8,
            "maxiter": config.optimizer_max_iterations,
            "maxls": 50,
        },
    )
    vector = np.asarray(result.x, dtype=np.float64)
    if not bool(result.success) or not np.all(np.isfinite(vector)):
        raise _T11FitFailure(f"T11 optimizer failed: {result.message}")
    league = vector[:league_count]
    attack = vector[attack_start:defense_start]
    defense = vector[defense_start:]
    attack -= np.mean(attack)
    defense -= np.mean(defense)
    rho = config.dixon_coles_rho_bound * math.tanh(float(vector[rho_index]))
    parameters: Mapping[str, object] = {
        "league_season_intercepts": {
            key: float(league[index]) for key, index in sorted(league_index.items())
        },
        "team_attack": {key: float(attack[index]) for key, index in sorted(team_index.items())},
        "team_defense": {key: float(defense[index]) for key, index in sorted(team_index.items())},
        "home_advantage": float(vector[home_index]),
        "dixon_coles_rho": float(rho),
        "dixon_coles_rho_raw": float(vector[rho_index]),
        "baseline_goal_rate": float(baseline_goal_rate),
        "league_keys": league_keys,
        "team_ids": team_ids,
    }
    diagnostics: Mapping[str, object] = {
        "optimizer": "scipy.optimize.minimize:L-BFGS-B",
        "optimizer_success": bool(result.success),
        "optimizer_status": int(result.status),
        "optimizer_message": str(result.message),
        "optimizer_iterations": int(result.nit),
        "optimizer_function_evaluations": int(result.nfev),
        "objective": float(result.fun),
        "training_rows": len(rows),
        "training_effective_matches": float(np.sum(weights)),
        "weighted_home_goal_mean": overall_home,
        "weighted_away_goal_mean": overall_away,
        "team_count": team_count,
        "league_count": league_count,
    }
    return parameters, diagnostics


def _regime_effects(
    rows: Sequence[_TrainingMatch], baseline_goal_rate: float, config: T11ModelConfig
) -> Mapping[str, float]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        if row.regime_id is None:
            continue
        grouped.setdefault(row.regime_id, []).append(
            (float(row.home_goals + row.away_goals) / 2.0, row.weight)
        )
    effects: dict[str, float] = {}
    for regime_id, values in sorted(grouped.items()):
        denominator = sum(weight for _, weight in values)
        if denominator <= 0:
            continue
        rate = sum(goal_rate * weight for goal_rate, weight in values) / denominator
        raw_effect = math.log(max(rate, 0.05) / baseline_goal_rate)
        effects[regime_id] = _bounded(raw_effect / (1.0 + config.regime_prior_scale), -2.0, 2.0)
    return effects


def _uncertainty_metadata(
    rows: Sequence[_TrainingMatch], target: TargetMatch, config: T11ModelConfig
) -> Mapping[str, object]:
    effective_total = sum(row.weight for row in rows)
    teams: dict[str, object] = {}
    multipliers: list[float] = []
    for team_id in target.team_ids:
        direct_rows = tuple(row for row in rows if team_id in (row.home_team_id, row.away_team_id))
        direct_matches = len(direct_rows)
        effective_matches = sum(row.weight for row in direct_rows)
        direct_fraction = min(
            1.0, effective_matches / max(config.minimum_effective_history_matches, 1.0)
        )
        uncertainty_multiplier = 1.0 + 1.25 * (1.0 - direct_fraction)
        if direct_matches == 0:
            pooling = "SHARED_LEAGUE_PRIOR"
        elif direct_matches < config.minimum_history_matches:
            pooling = "HIERARCHICAL_BORROWING"
        else:
            pooling = "DIRECT_AND_POOLED"
        multipliers.append(uncertainty_multiplier)
        teams[team_id] = {
            "direct_matches": direct_matches,
            "effective_matches": effective_matches,
            "shared_training_matches": len(rows),
            "pooling": pooling,
            "borrowed_evidence": direct_matches < config.minimum_history_matches,
            "uncertainty_multiplier": uncertainty_multiplier,
        }
    return {
        "teams": teams,
        "effective_training_matches": effective_total,
        "prediction_uncertainty_multiplier": max(multipliers, default=1.0),
        "uncertainty_method": "sparse_team_support_widens_metadata_v1",
    }


def _fit_input_metadata(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    fixture_ids = tuple(sorted(match.fixture_id for match in history))
    training_ids: set[str] = set(fixture_ids)
    training_digests: set[str] = set()
    for match in history:
        training_ids.update(match.source_assertion_ids)
        training_ids.update(match.metric_ids("full_time_home_goals"))
        training_ids.update(match.metric_ids("full_time_away_goals"))
        training_digests.add(_history_digest(match))
    feature_ids, _feature_digests = _feature_lineage(state, _T11_FEATURE_NAMES)
    return (
        fixture_ids,
        tuple(sorted(training_digests)),
        tuple(sorted(training_ids)),
        feature_ids,
    )


def _runtime_reproducibility(
    config: T11ModelConfig,
    state: FrozenEvidenceState,
    history: Sequence[HistoricalMatch],
) -> Mapping[str, object]:
    np, _, _ = _numeric_modules()
    try:
        import scipy  # type: ignore[import-untyped]

        scipy_version = str(getattr(scipy, "__version__", "unknown"))
    except ImportError:
        scipy_version = "unavailable"
    return {
        "algorithm_version": config.algorithm_version,
        "canonical_json": "RFC-8785-compatible-sorted-JSON",
        "config_digest": config.digest,
        "cutoff_utc": state.cutoff_utc,
        "frozen_evidence_digest": state.digest,
        "history_order": "fixture_id_ascending",
        "input_history_fixture_ids": tuple(sorted(match.fixture_id for match in history)),
        "numpy_version": str(getattr(np, "__version__", "unknown")),
        "platform": platform.platform(),
        "preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
        "preference_catalog_name": DEFAULT_PREFERENCE_CATALOG.name,
        "preference_catalog_version": DEFAULT_PREFERENCE_CATALOG.version,
        "preference_ids": FULL_TIME_GOAL_PREFERENCE_IDS,
        "python_version": platform.python_version(),
        "randomness": "none",
        "scipy_version": scipy_version,
        "software_commit": os.environ.get("MATCHVET_COMMIT", "unknown"),
        "target_fixture_id": state.target_fixture_id,
    }


def _new_unavailable_fit(
    state: FrozenEvidenceState,
    config: T11ModelConfig,
    *,
    reason: str,
    history: Sequence[HistoricalMatch] = (),
    rows: Sequence[_TrainingMatch] = (),
    diagnostics: Mapping[str, object] | None = None,
) -> FullTimeGoalModelFit:
    fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(history, state)
    _, feature_digests = _feature_lineage(state, _T11_FEATURE_NAMES)
    reproducibility: Mapping[str, object]
    try:
        reproducibility = _runtime_reproducibility(config, state, history)
    except _T11FitFailure:
        reproducibility = {
            "algorithm_version": config.algorithm_version,
            "config_digest": config.digest,
            "cutoff_utc": state.cutoff_utc,
            "frozen_evidence_digest": state.digest,
            "history_order": "fixture_id_ascending",
            "input_history_fixture_ids": fixture_ids,
            "preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
            "preference_catalog_name": DEFAULT_PREFERENCE_CATALOG.name,
            "preference_catalog_version": DEFAULT_PREFERENCE_CATALOG.version,
            "preference_ids": FULL_TIME_GOAL_PREFERENCE_IDS,
            "randomness": "none",
            "target_fixture_id": state.target_fixture_id,
        }
    selected_diagnostics = dict(diagnostics or {})
    selected_diagnostics.update(
        {
            "history_rows": len(rows),
            "training_effective_matches": sum(row.weight for row in rows),
            "model_status_reason": reason,
        }
    )
    return FullTimeGoalModelFit(
        status=ModelStatus.MODEL_UNAVAILABLE,
        model_name=config.name,
        model_version=config.version,
        algorithm_version=config.algorithm_version,
        feature_version=config.feature_version,
        target=state.target,
        config=config,
        training_input_fixture_ids=fixture_ids,
        training_input_digests=input_digests,
        training_input_ids=input_ids,
        frozen_evidence_digest=state.digest,
        frozen_artifact_digest=state.artifact_digest,
        frozen_manifest_digest=state.manifest_digest,
        feature_input_ids=feature_ids,
        feature_input_digests=feature_digests,
        diagnostics=selected_diagnostics,
        uncertainty=_uncertainty_metadata(rows, state.target, config),
        reproducibility=reproducibility,
        reason=reason,
    )


def _coerce_state(value: object) -> FrozenEvidenceState:
    if isinstance(value, FrozenEvidenceState):
        return value
    if isinstance(value, Mapping):
        return FrozenEvidenceState.from_dict(value)
    raise T11ValidationError("T11 requires a FrozenEvidenceState from T09.")


def _validate_state_target(state: FrozenEvidenceState) -> None:
    if (
        state.target.fixture_id == state.target.home_team_id
        or state.target.fixture_id == state.target.away_team_id
    ):
        raise T11IntegrityError("T11 target identity overlaps a team identity.")
    if not state.digest:
        raise T11IntegrityError("T11 requires a digest-bearing FrozenEvidenceState.")


def fit_full_time_goal_model(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    *,
    evidence_state: object | None = None,
    config: T11ModelConfig | None = None,
    model_config: T11ModelConfig | None = None,
) -> FullTimeGoalModelFit:
    """Fit the deterministic T11 MAP model from one frozen T09 evidence state.

    The normal call is ``fit_full_time_goal_model(history, state)``.  The
    state-first form is accepted as a convenience for repository services.
    History is deliberately explicit: T09 freezes its feature lineage, while
    T11 consumes the cutoff-valid structured match rows that produced it.
    """
    if evidence_state is not None:
        if frozen_evidence_state is not None:
            raise T11ValidationError("T11 received two FrozenEvidenceState arguments.")
        frozen_evidence_state = evidence_state
    if config is not None and model_config is not None:
        raise T11ValidationError("T11 received two model configurations.")
    selected_config = config or model_config or T11ModelConfig()
    if not isinstance(selected_config, T11ModelConfig):
        raise T11ValidationError("T11 config must be a T11ModelConfig.")

    selected_history: object = history
    if isinstance(history, FrozenEvidenceState):
        if frozen_evidence_state is None:
            raise T11ValidationError("The state-first T11 form also requires history.")
        selected_state = _coerce_state(history)
        selected_history = frozen_evidence_state
    else:
        if frozen_evidence_state is None:
            raise T11ValidationError("T11 fitting requires a FrozenEvidenceState from T09.")
        selected_state = _coerce_state(frozen_evidence_state)
    _validate_state_target(selected_state)
    if selected_history is None or isinstance(selected_history, FrozenEvidenceState):
        raise T11ValidationError("T11 fitting requires structured HistoricalMatch rows.")
    if not isinstance(selected_history, Iterable):
        raise T11ValidationError("T11 history must be iterable.")

    history_records = _coerce_history(
        cast(Iterable[HistoricalMatch | Mapping[str, object]], selected_history)
    )
    rows, ordered_history = _training_rows(history_records, selected_state, selected_config)
    cutoff = _parse_utc(selected_state.target.cutoff_utc)
    expected_history_ids = set(_state_history_ids(selected_state))
    supplied_cutoff_ids = {
        match.fixture_id for match in history_records if _cutoff_valid_history_match(match, cutoff)
    }
    missing_history_ids = tuple(sorted(expected_history_ids - supplied_cutoff_ids))
    unexpected_history_ids = tuple(sorted(supplied_cutoff_ids - expected_history_ids))
    if missing_history_ids:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_INCOMPLETE",
            history=history_records,
            rows=rows,
            diagnostics={"missing_fixture_ids": missing_history_ids},
        )
    if not expected_history_ids and unexpected_history_ids:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics={"unexpected_fixture_ids": unexpected_history_ids},
        )
    mismatched_history_ids = _frozen_history_input_mismatches(history_records, selected_state)
    if mismatched_history_ids:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics={"mismatched_fixture_ids": mismatched_history_ids},
        )
    reason = _minimum_evidence_reason(rows, selected_state.target, selected_config)
    if reason is not None:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason=reason,
            history=ordered_history,
            rows=rows,
        )

    try:
        parameters, diagnostics = _fit_numerical_parameters(
            rows, selected_state.target, selected_config
        )
        baseline_value = _number(parameters.get("baseline_goal_rate"))
        if baseline_value is None:
            raise _T11FitFailure("T11 fit did not retain a finite baseline goal rate.")
        baseline_goal_rate = baseline_value
        effects = _regime_effects(rows, baseline_goal_rate, selected_config)
        offsets = _feature_offsets(
            selected_state,
            selected_state.target,
            selected_config,
            baseline_goal_rate=baseline_goal_rate,
            regime_effects=effects,
        )
        selected_parameters = dict(parameters)
        selected_parameters["regime_effects"] = effects
        selected_parameters["target_feature_offsets"] = offsets
        selected_parameters["target_regime_id"] = _target_regime(selected_state)
        selected_parameters["feature_version"] = selected_config.feature_version
        fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(
            ordered_history, selected_state
        )
        _, feature_digests = _feature_lineage(selected_state, _T11_FEATURE_NAMES)
        fit = FullTimeGoalModelFit(
            status=ModelStatus.AVAILABLE,
            model_name=selected_config.name,
            model_version=selected_config.version,
            algorithm_version=selected_config.algorithm_version,
            feature_version=selected_config.feature_version,
            target=selected_state.target,
            config=selected_config,
            parameters=selected_parameters,
            training_input_fixture_ids=fixture_ids,
            training_input_digests=input_digests,
            training_input_ids=input_ids,
            frozen_evidence_digest=selected_state.digest,
            frozen_artifact_digest=selected_state.artifact_digest,
            frozen_manifest_digest=selected_state.manifest_digest,
            feature_input_ids=feature_ids,
            feature_input_digests=feature_digests,
            diagnostics=diagnostics,
            uncertainty=_uncertainty_metadata(rows, selected_state.target, selected_config),
            reproducibility=_runtime_reproducibility(
                selected_config, selected_state, ordered_history
            ),
        )
        validation_prediction = predict_full_time_goal_distribution(fit, selected_state)
        if not validation_prediction.is_available:
            raise _T11FitFailure(validation_prediction.reason or "INVALID_SCORE_DISTRIBUTION")
        return fit
    except _T11FitFailure as error:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            diagnostics={"fit_error": str(error)},
        )
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            diagnostics={"fit_error": str(error)},
        )


def _parameter_number(parameters: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = _number(parameters.get(key))
    return default if value is None else value


def _parameter_map(parameters: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parameters.get(key)
    return value if isinstance(value, Mapping) else {}


def _prediction_lambdas(
    fit: FullTimeGoalModelFit,
    state: FrozenEvidenceState | None,
) -> tuple[float, float, float, Mapping[str, object]]:
    target = fit.target
    if state is not None:
        _validate_state_target(state)
        if (
            state.target.fixture_id != target.fixture_id
            or state.target.matchweek_id != target.matchweek_id
            or state.target.cutoff_utc != target.cutoff_utc
            or state.target.home_team_id != target.home_team_id
            or state.target.away_team_id != target.away_team_id
        ):
            raise T11IntegrityError(
                "The prediction FrozenEvidenceState does not identify the fitted target."
            )
        if state.digest != fit.frozen_evidence_digest:
            raise T11IntegrityError(
                "The prediction FrozenEvidenceState does not match the fitted evidence digest."
            )
    parameters = fit.parameters
    intercepts = _parameter_map(parameters, "league_season_intercepts")
    target_league_key = _league_season_key(target.competition_key, target.season)
    intercept = _number(intercepts.get(target_league_key))
    if intercept is None:
        intercept = _parameter_number(parameters, "baseline_goal_rate", 0.05)
        intercept = math.log(max(intercept, 0.05))
    attacks = _parameter_map(parameters, "team_attack")
    defenses = _parameter_map(parameters, "team_defense")
    home_attack = _number(attacks.get(target.home_team_id)) or 0.0
    away_attack = _number(attacks.get(target.away_team_id)) or 0.0
    home_defense = _number(defenses.get(target.home_team_id)) or 0.0
    away_defense = _number(defenses.get(target.away_team_id)) or 0.0
    baseline = _parameter_number(parameters, "baseline_goal_rate", math.exp(intercept))
    regime_effects = _parameter_map(parameters, "regime_effects")
    stored_offsets = _parameter_map(parameters, "target_feature_offsets")
    offsets = _feature_offsets(
        state,
        target,
        fit.config,
        baseline_goal_rate=max(baseline, 0.05),
        regime_effects=regime_effects,
        stored=stored_offsets,
    )
    home_offset = _number(offsets.get("home")) or 0.0
    away_offset = _number(offsets.get("away")) or 0.0
    log_max = math.log(max(fit.config.maximum_expected_goals, 0.05))
    log_min = min(-8.0, log_max - 4.0)
    home_eta = _bounded(
        intercept
        + _parameter_number(parameters, "home_advantage")
        + home_attack
        - away_defense
        + home_offset,
        log_min,
        log_max,
    )
    away_eta = _bounded(
        intercept + away_attack - home_defense + away_offset,
        log_min,
        log_max,
    )
    home_lambda = math.exp(home_eta)
    away_lambda = math.exp(away_eta)
    rho = _bounded(
        _parameter_number(parameters, "dixon_coles_rho"),
        -fit.config.dixon_coles_rho_bound,
        fit.config.dixon_coles_rho_bound,
    )
    return home_lambda, away_lambda, rho, offsets


def _poisson_probabilities(rate: float, maximum_goals: int) -> Any:
    np, _, _ = _numeric_modules()
    if not math.isfinite(rate) or rate <= 0:
        raise _T11FitFailure("T11 expected goals must be finite and positive.")
    probabilities = np.empty(maximum_goals + 1, dtype=np.float64)
    probabilities[0] = math.exp(-rate)
    for goal in range(1, maximum_goals + 1):
        probabilities[goal] = probabilities[goal - 1] * rate / goal
    if not np.all(np.isfinite(probabilities)):
        raise _T11FitFailure("T11 Poisson probabilities are not finite.")
    return probabilities


def _score_surface(
    home_lambda: float,
    away_lambda: float,
    rho: float,
    config: T11ModelConfig,
) -> tuple[Any, int, float]:
    np, _, _ = _numeric_modules()
    maximum_goals = max(2, config.maximum_score_goals)
    while True:
        home = _poisson_probabilities(home_lambda, maximum_goals)
        away = _poisson_probabilities(away_lambda, maximum_goals)
        surface = home[:, None] * away[None, :]
        zero_zero = 1.0 - home_lambda * away_lambda * rho
        zero_one = 1.0 + home_lambda * rho
        one_zero = 1.0 + away_lambda * rho
        one_one = 1.0 - rho
        if min(zero_zero, zero_one, one_zero, one_one) <= 0:
            raise _T11FitFailure("T11 Dixon-Coles correction became non-positive.")
        surface[0, 0] *= zero_zero
        surface[0, 1] *= zero_one
        surface[1, 0] *= one_zero
        surface[1, 1] *= one_one
        raw_mass = float(np.sum(surface))
        tail_mass = abs(1.0 - raw_mass)
        if not math.isfinite(raw_mass) or raw_mass <= 0:
            raise _T11FitFailure("T11 score surface has invalid mass.")
        if tail_mass <= config.tail_tolerance:
            surface = surface / raw_mass
            if not np.all(np.isfinite(surface)) or np.any(surface < -1e-12):
                raise _T11FitFailure("T11 score surface is not finite and non-negative.")
            surface = np.maximum(surface, 0.0)
            surface = surface / float(np.sum(surface))
            return surface, maximum_goals, tail_mass
        if maximum_goals >= 128:
            raise _T11FitFailure("T11 score-grid tail mass exceeds the versioned tolerance.")
        maximum_goals = min(128, max(maximum_goals + 1, maximum_goals * 2))


def _settle_score(
    preference: BettingPreference,
    score: Any,
) -> SettlementProbabilities:
    win = 0.0
    loss = 0.0
    push = 0.0
    for home_goals, row in enumerate(score):
        for away_goals, probability_value in enumerate(row):
            probability = float(probability_value)
            if preference.family is PreferenceFamily.MATCH_WINNER:
                selected = (
                    home_goals > away_goals
                    if preference.selection == "Home"
                    else away_goals > home_goals
                    if preference.selection == "Away"
                    else home_goals == away_goals
                )
                if selected:
                    win += probability
                else:
                    loss += probability
            elif preference.family is PreferenceFamily.DOUBLE_CHANCE:
                selected = (
                    home_goals >= away_goals
                    if preference.selection == "1X"
                    else away_goals >= home_goals
                    if preference.selection == "X2"
                    else home_goals != away_goals
                )
                if selected:
                    win += probability
                else:
                    loss += probability
            elif preference.family is PreferenceFamily.MATCH_GOALS_OVER:
                assert preference.line is not None
                if home_goals + away_goals > preference.line:
                    win += probability
                else:
                    loss += probability
            elif preference.family is PreferenceFamily.HOME_TEAM_GOALS_OVER:
                assert preference.line is not None
                if home_goals > preference.line:
                    win += probability
                else:
                    loss += probability
            elif preference.family is PreferenceFamily.AWAY_TEAM_GOALS_OVER:
                assert preference.line is not None
                if away_goals > preference.line:
                    win += probability
                else:
                    loss += probability
            elif preference.family is PreferenceFamily.ASIAN_HANDICAP:
                assert preference.line is not None
                difference = (
                    home_goals - away_goals
                    if preference.selection == "Home"
                    else away_goals - home_goals
                )
                adjusted = 2 * difference + 2 * preference.line
                if adjusted > 0:
                    win += probability
                elif adjusted < 0:
                    loss += probability
                else:
                    push += probability
            else:
                raise T11ValidationError(
                    f"T11 cannot derive unsupported preference family {preference.family}."
                )
    total = win + loss + push
    if not math.isfinite(total) or total <= 0:
        raise T11ValidationError("T11 settlement probabilities have invalid total mass.")
    # Complementing LOSS makes every market sum to one despite summation order.
    win = _bounded(win / total, 0.0, 1.0)
    push = _bounded(push / total, 0.0, 1.0 - win)
    loss = _bounded(1.0 - win - push, 0.0, 1.0)
    return SettlementProbabilities(win, loss, push)


def _settlement_distributions(score: Any) -> Mapping[str, SettlementProbabilities]:
    return {
        preference.preference_id: _settle_score(preference, score)
        for preference in FULL_TIME_GOAL_PREFERENCES
    }


def _unavailable_distribution(fit: FullTimeGoalModelFit, reason: str) -> FullTimeGoalDistribution:
    return FullTimeGoalDistribution(
        status=ModelStatus.MODEL_UNAVAILABLE,
        target_fixture_id=fit.target_fixture_id,
        matchweek_id=fit.matchweek_id,
        model_version=fit.model_version,
        model_digest=fit.digest,
        feature_inputs={
            "frozen_evidence_digest": fit.frozen_evidence_digest,
            "feature_input_ids": fit.feature_input_ids,
            "feature_input_digests": fit.feature_input_digests,
        },
        uncertainty=fit.uncertainty,
        diagnostics=fit.diagnostics,
        reason=reason,
    )


def predict_full_time_goal_distribution(
    fit: FullTimeGoalModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> FullTimeGoalDistribution:
    """Return the score surface and coherent T10-compatible settlement mappings."""
    if not isinstance(fit, FullTimeGoalModelFit):
        raise T11ValidationError("T11 prediction requires a FullTimeGoalModelFit.")
    if not fit.is_available:
        return _unavailable_distribution(fit, fit.reason or "MODEL_UNAVAILABLE")
    selected_state = frozen_evidence_state
    try:
        home_lambda, away_lambda, rho, offsets = _prediction_lambdas(fit, selected_state)
        score, maximum_goals, tail_mass = _score_surface(home_lambda, away_lambda, rho, fit.config)
        settlements = _settlement_distributions(score)
    except _T11FitFailure as error:
        return _unavailable_distribution(fit, str(error))
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        return _unavailable_distribution(fit, f"PREDICTION_FAILED:{error}")
    feature_ids, feature_digests = (
        _feature_lineage(selected_state, _T11_FEATURE_NAMES)
        if selected_state is not None
        else (fit.feature_input_ids, fit.feature_input_digests)
    )
    diagnostics = dict(fit.diagnostics)
    diagnostics.update(
        {
            "dixon_coles_rho": rho,
            "maximum_score_goals": maximum_goals,
            "score_grid_cells": int(score.size),
            "tail_mass": tail_mass,
        }
    )
    feature_inputs = {
        "frozen_evidence_digest": (
            selected_state.digest if selected_state is not None else fit.frozen_evidence_digest
        ),
        "feature_input_ids": feature_ids,
        "feature_input_digests": feature_digests,
        "target_feature_offsets": offsets,
    }
    uncertainty = dict(fit.uncertainty)
    uncertainty["score_grid_tail_tolerance"] = fit.config.tail_tolerance
    return FullTimeGoalDistribution(
        status=ModelStatus.AVAILABLE,
        target_fixture_id=fit.target_fixture_id,
        matchweek_id=fit.matchweek_id,
        model_version=fit.model_version,
        model_digest=fit.digest,
        score_distribution=tuple(tuple(float(cell) for cell in row) for row in score),
        home_expected_goals=home_lambda,
        away_expected_goals=away_lambda,
        maximum_goals=maximum_goals,
        tail_mass=tail_mass,
        settlement_distributions=settlements,
        feature_inputs=feature_inputs,
        uncertainty=uncertainty,
        diagnostics=diagnostics,
    )


def predict_full_time_goals(
    fit: FullTimeGoalModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> FullTimeGoalDistribution:
    """Compatibility alias for the T11 prediction seam."""
    return predict_full_time_goal_distribution(fit, frozen_evidence_state)


fit_t11 = fit_full_time_goal_model


def fit_full_time_goal_model_from_store(
    store: Store,
    frozen_evidence_state: FrozenEvidenceState | Mapping[str, object],
    *,
    config: T11ModelConfig | None = None,
) -> FullTimeGoalModelFit:
    """Fit T11 from the cutoff-valid T06 rows behind a frozen T09 state."""
    if not isinstance(store, Store):
        raise T11ValidationError("T11 store fitting requires a MatchVet Store.")
    state = _coerce_state(frozen_evidence_state)
    from matchvet.t09 import _t06_history_and_facts

    history, _ = _t06_history_and_facts(
        store,
        season=state.target.season,
        cutoff_utc=state.target.cutoff_utc,
        excluded_fixture_ids=(state.target.fixture_id,),
    )
    return fit_full_time_goal_model(history, state, config=config)


class T11ModelService:
    """Small service facade matching the local-first T09/T10 runner shape."""

    def __init__(self, config: T11ModelConfig | None = None) -> None:
        self.config = config or T11ModelConfig()

    def fit(
        self,
        history: Iterable[HistoricalMatch | Mapping[str, object]],
        frozen_evidence_state: FrozenEvidenceState,
    ) -> FullTimeGoalModelFit:
        return fit_full_time_goal_model(history, frozen_evidence_state, config=self.config)

    @staticmethod
    def predict(
        fit: FullTimeGoalModelFit,
        frozen_evidence_state: FrozenEvidenceState | None = None,
    ) -> FullTimeGoalDistribution:
        return predict_full_time_goal_distribution(fit, frozen_evidence_state)


T11Runner = T11ModelService
FullTimeGoalModel = T11ModelService


@dataclass(frozen=True)
class T11Plan:
    """Immutable identity for a T11 fit request."""

    target: TargetMatch
    config: T11ModelConfig = field(default_factory=T11ModelConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetMatch):
            raise T11ValidationError("T11 plans require a TargetMatch.")
        if not isinstance(self.config, T11ModelConfig):
            raise T11ValidationError("T11 plans require a T11ModelConfig.")

    @property
    def run_key(self) -> str:
        return f"t11-full-time-goals:{self.target.matchweek_id}:{self.target.fixture_id}"

    @property
    def plan_digest(self) -> str:
        return _digest(
            {
                "config_digest": self.config.digest,
                "run_key": self.run_key,
                "target": self.target.to_dict(),
            }
        )


@dataclass(frozen=True)
class T11PublishedArtifacts:
    """The content-addressed fit and distribution artifacts published together."""

    fit: FullTimeGoalModelFit
    distribution: FullTimeGoalDistribution
    fit_artifact_digest: str
    distribution_artifact_digest: str


class T11ArtifactRecorder:
    """Publish and reload immutable T11 JSON artifacts through the local store."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T11 artifact publication requires a writable store.")
        self.store = store
        self.artifacts = ArtifactStore(store)

    def publish_fit(self, fit: FullTimeGoalModelFit) -> FullTimeGoalModelFit:
        if not isinstance(fit, FullTimeGoalModelFit):
            raise T11ValidationError("T11 fit artifact publication requires a model fit.")
        record = self.artifacts.publish_artifact(fit.to_bytes(), T11_MEDIA_TYPE)
        return fit.with_artifact(record.digest)

    def publish_distribution(
        self, distribution: FullTimeGoalDistribution
    ) -> FullTimeGoalDistribution:
        if not isinstance(distribution, FullTimeGoalDistribution):
            raise T11ValidationError(
                "T11 distribution artifact publication requires a model distribution."
            )
        record = self.artifacts.publish_artifact(
            distribution.to_bytes(), T11_DISTRIBUTION_MEDIA_TYPE
        )
        return distribution.with_artifact(record.digest)

    def publish(
        self,
        fit: FullTimeGoalModelFit,
        distribution: FullTimeGoalDistribution | None = None,
    ) -> T11PublishedArtifacts:
        published_fit = self.publish_fit(fit)
        selected_distribution = distribution or fit.predict()
        if selected_distribution.model_digest != fit.digest:
            raise T11IntegrityError(
                "A T11 distribution must reference the exact fitted model digest."
            )
        published_distribution = self.publish_distribution(selected_distribution)
        return T11PublishedArtifacts(
            fit=published_fit,
            distribution=published_distribution,
            fit_artifact_digest=cast(str, published_fit.artifact_digest),
            distribution_artifact_digest=cast(str, published_distribution.artifact_digest),
        )

    def load_fit(self, digest: str) -> FullTimeGoalModelFit:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T11_MEDIA_TYPE:
            raise T11IntegrityError("The artifact is not a T11 model fit.")
        fit = FullTimeGoalModelFit.from_dict(
            cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        )
        if fit.artifact_digest != digest:
            fit = fit.with_artifact(digest)
        return fit

    def load_distribution(self, digest: str) -> FullTimeGoalDistribution:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T11_DISTRIBUTION_MEDIA_TYPE:
            raise T11IntegrityError("The artifact is not a T11 settlement distribution.")
        payload = cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        distribution = FullTimeGoalDistribution.from_dict(payload)
        return (
            distribution
            if distribution.artifact_digest == digest
            else distribution.with_artifact(digest)
        )


__all__ = [
    "FULL_TIME_GOAL_MODEL_VERSION",
    "FULL_TIME_GOAL_PREFERENCES",
    "FULL_TIME_GOAL_PREFERENCE_IDS",
    "MODEL_MEDIA_TYPE",
    "MODEL_UNAVAILABLE",
    "T11_DISTRIBUTION_MEDIA_TYPE",
    "T11_MEDIA_TYPE",
    "T11_MODEL_VERSION",
    "FullTimeGoalDistribution",
    "FullTimeGoalModel",
    "FullTimeGoalModelFit",
    "ModelStatus",
    "SettlementProbabilities",
    "T11ArtifactRecorder",
    "T11Error",
    "T11IntegrityError",
    "T11ModelConfig",
    "T11ModelService",
    "T11Plan",
    "T11PublishedArtifacts",
    "T11Runner",
    "T11ValidationError",
    "fit_full_time_goal_model",
    "fit_full_time_goal_model_from_store",
    "fit_t11",
    "predict_full_time_goal_distribution",
    "predict_full_time_goals",
]

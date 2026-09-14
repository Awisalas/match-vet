"""T13 joint corner Settlement Distributions.

T13 fits one hierarchical shared-pace gamma-Poisson model for full-match
Home and Away corners.  The model keeps the two team counts separate while a
shared Gamma pace supplies positive dependence and overdispersion.  Every
corner preference is derived from that one normalized joint surface.

This module consumes cutoff-valid structured history and one frozen T09
Evidence State.  It does not calibrate probabilities, rank preferences, or
make a recommendation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from matchvet.artifacts import ArtifactStore
from matchvet.evidence import EvidenceState
from matchvet.store import Store
from matchvet.t09 import (
    DerivedFeature,
    FrozenEvidenceState,
    HistoricalMatch,
    SourceFact,
    TargetMatch,
)
from matchvet.t10 import (
    CORNER_FACTS,
    DEFAULT_PREFERENCE_CATALOG,
    BettingPreference,
    PreferenceFamily,
)
from matchvet.t11 import ModelStatus, SettlementProbabilities

T13_MODEL_NAME = "matchvet-joint-corner-model"
T13_MODEL_VERSION = "t13-joint-corners-v1"
T13_ALGORITHM_VERSION = "hierarchical-shared-pace-gamma-poisson-map-v1"
T13_FEATURE_VERSION = "t13-frozen-t09-features-v1"
T13_MEDIA_TYPE = "application/vnd.matchvet.t13-joint-corner-model+json"
T13_DISTRIBUTION_MEDIA_TYPE = (
    "application/vnd.matchvet.t13-joint-corner-settlement-distribution+json"
)
MODEL_MEDIA_TYPE = T13_MEDIA_TYPE
JOINT_CORNER_MODEL_VERSION = T13_MODEL_VERSION


class T13Error(Exception):
    """Base class for T13 fitting, prediction, and artifact errors."""


class T13ValidationError(T13Error, ValueError):
    """A T13 input is malformed or violates the frozen-input contract."""


class T13IntegrityError(T13Error):
    """An immutable T13 identity or artifact does not match its content."""


class _T13FitFailure(T13Error):
    """An expected numerical fitting or prediction failure."""


MODEL_UNAVAILABLE = ModelStatus.MODEL_UNAVAILABLE


_CORNER_FAMILIES = frozenset(
    {
        PreferenceFamily.CORNER_WINNER,
        PreferenceFamily.TOTAL_CORNERS_OVER,
        PreferenceFamily.HOME_CORNERS_OVER,
        PreferenceFamily.AWAY_CORNERS_OVER,
    }
)


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
            raise T13ValidationError("T13 JSON values must be finite.")
        return value
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T13ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise T13ValidationError(f"{label} must be a finite number.")
    selected = float(value)
    if not math.isfinite(selected):
        raise T13ValidationError(f"{label} must be a finite number.")
    return selected


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise T13ValidationError(f"{label} must be an object.")
    return cast(Mapping[str, object], value)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


def _strings(values: Iterable[object]) -> tuple[str, ...]:
    selected = tuple(_text(item, "T13 identity") for item in values)
    return tuple(sorted(set(selected)))


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise T13ValidationError("T13 timestamps must be ISO-8601 values.") from error
    if parsed.tzinfo is None:
        raise T13ValidationError("T13 timestamps must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _freeze_map(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): value[key] for key in value})


def _corner_preferences() -> tuple[BettingPreference, ...]:
    return tuple(item for item in DEFAULT_PREFERENCE_CATALOG if item.family in _CORNER_FAMILIES)


CORNER_PREFERENCES = _corner_preferences()
CORNER_PREFERENCE_IDS = tuple(item.preference_id for item in CORNER_PREFERENCES)
JOINT_CORNER_PREFERENCES = CORNER_PREFERENCES
JOINT_CORNER_PREFERENCE_IDS = CORNER_PREFERENCE_IDS


@dataclass(frozen=True)
class CornerHistory:
    """One reliable full-match Home/Away corner observation."""

    fixture_id: str
    home_team_id: str
    away_team_id: str
    kickoff_utc: str
    home_corners: int
    away_corners: int
    competition_key: str | None = None
    regime_id: str | None = None
    source_digest: str | None = None
    source_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        corner_values: tuple[tuple[str, object], ...] = (
            ("corner history fixture ID", self.fixture_id),
            ("corner history home team ID", self.home_team_id),
            ("corner history away team ID", self.away_team_id),
        )
        for label, value in corner_values:
            _text(value, label)
        if self.home_team_id == self.away_team_id:
            raise T13ValidationError("Corner history requires two different teams.")
        object.__setattr__(self, "kickoff_utc", _canonical_utc(self.kickoff_utc))
        for label, value in (
            ("Home corners", self.home_corners),
            ("Away corners", self.away_corners),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise T13ValidationError(f"{label} must be a non-negative integer.")
        if self.competition_key is not None:
            object.__setattr__(
                self, "competition_key", _text(self.competition_key, "competition key")
            )
        if self.regime_id is not None:
            object.__setattr__(self, "regime_id", _text(self.regime_id, "regime ID"))
        if self.source_digest is not None:
            object.__setattr__(self, "source_digest", _text(self.source_digest, "source digest"))
        object.__setattr__(self, "source_input_ids", _strings(self.source_input_ids))

    @property
    def total_corners(self) -> int:
        return self.home_corners + self.away_corners

    @property
    def home_corner_count(self) -> int:
        return self.home_corners

    @property
    def away_corner_count(self) -> int:
        return self.away_corners

    def to_dict(self) -> dict[str, object]:
        return {
            "away_corners": self.away_corners,
            "away_team_id": self.away_team_id,
            "competition_key": self.competition_key,
            "fixture_id": self.fixture_id,
            "home_corners": self.home_corners,
            "home_team_id": self.home_team_id,
            "kickoff_utc": self.kickoff_utc,
            "regime_id": self.regime_id,
            "source_digest": self.source_digest,
            "source_input_ids": self.source_input_ids,
        }


CornerHistoryRow = CornerHistory
JointCornerHistory = CornerHistory


@dataclass(frozen=True)
class T13ModelConfig:
    """Versioned numerical, feature, and pooling controls for T13."""

    name: str = T13_MODEL_NAME
    version: str = T13_MODEL_VERSION
    algorithm_version: str = T13_ALGORITHM_VERSION
    feature_version: str = T13_FEATURE_VERSION
    recency_half_life_days: float = 180.0
    regime_match_weight: float = 1.0
    regime_mismatch_weight: float = 0.35
    unknown_regime_weight: float = 0.75
    minimum_history_matches: int = 3
    minimum_effective_history_matches: float = 3.0
    minimum_shared_team_matches: int = 3
    maximum_expected_corners: float = 20.0
    maximum_corner_count: int = 64
    maximum_corners: int | None = None
    tail_tolerance: float = 1e-10
    minimum_dispersion: float = 1e-4
    maximum_dispersion: float = 5.0
    dispersion_prior_mean: float = 0.15
    dispersion_prior_scale: float = 1.0
    league_dispersion_prior_scale: float = 0.5
    shared_pace_dispersion: float | None = None
    team_prior_scale: float = 0.55
    league_season_prior_scale: float = 0.4
    home_advantage_prior_scale: float = 0.6
    target_feature_scale: float = 0.05
    schedule_feature_scale: float = 0.02
    regime_feature_scale: float = 0.05
    regime_prior_scale: float = 0.3
    optimizer_max_iterations: int = 500
    optimizer_ftol: float = 1e-11

    def __post_init__(self) -> None:
        for label, value in (
            ("model name", self.name),
            ("model version", self.version),
            ("algorithm version", self.algorithm_version),
            ("feature version", self.feature_version),
        ):
            _text(value, f"T13 {label}")
        numeric_values: tuple[tuple[str, float], ...] = (
            ("recency half-life", self.recency_half_life_days),
            ("regime match weight", self.regime_match_weight),
            ("regime mismatch weight", self.regime_mismatch_weight),
            ("unknown regime weight", self.unknown_regime_weight),
            ("minimum effective history", self.minimum_effective_history_matches),
            ("maximum expected corners", self.maximum_expected_corners),
            ("tail tolerance", self.tail_tolerance),
            ("minimum dispersion", self.minimum_dispersion),
            ("maximum dispersion", self.maximum_dispersion),
            ("dispersion prior mean", self.dispersion_prior_mean),
            ("dispersion prior scale", self.dispersion_prior_scale),
            ("league dispersion prior scale", self.league_dispersion_prior_scale),
            ("team prior scale", self.team_prior_scale),
            ("league-season prior scale", self.league_season_prior_scale),
            ("home advantage prior scale", self.home_advantage_prior_scale),
            ("target feature scale", self.target_feature_scale),
            ("schedule feature scale", self.schedule_feature_scale),
            ("regime feature scale", self.regime_feature_scale),
            ("regime prior scale", self.regime_prior_scale),
            ("optimizer ftol", self.optimizer_ftol),
        )
        for numeric_label, numeric_value in numeric_values:
            if not math.isfinite(float(numeric_value)) or float(numeric_value) <= 0:
                raise T13ValidationError(f"T13 {numeric_label} must be positive and finite.")
        if self.regime_match_weight > 1 or self.regime_mismatch_weight > 1:
            raise T13ValidationError("T13 regime weights cannot exceed one.")
        if (
            isinstance(self.minimum_history_matches, bool)
            or not isinstance(self.minimum_history_matches, int)
            or isinstance(self.minimum_shared_team_matches, bool)
            or not isinstance(self.minimum_shared_team_matches, int)
            or self.minimum_history_matches < 1
            or self.minimum_shared_team_matches < 1
        ):
            raise T13ValidationError("T13 history minimums must be positive.")
        if self.maximum_corners is not None:
            if (
                isinstance(self.maximum_corners, bool)
                or not isinstance(self.maximum_corners, int)
                or self.maximum_corners < 2
            ):
                raise T13ValidationError(
                    "T13 maximum corner grids must include at least 0 through 2."
                )
            object.__setattr__(self, "maximum_corner_count", self.maximum_corners)
        if (
            isinstance(self.maximum_corner_count, bool)
            or not isinstance(self.maximum_corner_count, int)
            or self.maximum_corner_count < 2
        ):
            raise T13ValidationError("T13 corner grids must include at least 0 through 2.")
        if self.tail_tolerance >= 1:
            raise T13ValidationError("T13 tail tolerance must be below one.")
        if self.maximum_dispersion <= self.minimum_dispersion:
            raise T13ValidationError("T13 maximum dispersion must exceed its minimum.")
        if not self.minimum_dispersion <= self.dispersion_prior_mean <= self.maximum_dispersion:
            raise T13ValidationError("T13 dispersion prior mean must be inside its bounds.")
        if self.shared_pace_dispersion is not None:
            fixed_dispersion = _finite(self.shared_pace_dispersion, "T13 shared pace dispersion")
            if not self.minimum_dispersion <= fixed_dispersion <= self.maximum_dispersion:
                raise T13ValidationError("T13 shared pace dispersion must be inside its bounds.")
        if (
            isinstance(self.optimizer_max_iterations, bool)
            or not isinstance(self.optimizer_max_iterations, int)
            or self.optimizer_max_iterations < 1
        ):
            raise T13ValidationError("T13 optimizer iterations must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "dispersion_prior_mean": self.dispersion_prior_mean,
            "dispersion_prior_scale": self.dispersion_prior_scale,
            "feature_version": self.feature_version,
            "home_advantage_prior_scale": self.home_advantage_prior_scale,
            "league_season_prior_scale": self.league_season_prior_scale,
            "league_dispersion_prior_scale": self.league_dispersion_prior_scale,
            "maximum_corner_count": self.maximum_corner_count,
            "maximum_corners": self.maximum_corners,
            "maximum_dispersion": self.maximum_dispersion,
            "maximum_expected_corners": self.maximum_expected_corners,
            "minimum_dispersion": self.minimum_dispersion,
            "minimum_effective_history_matches": self.minimum_effective_history_matches,
            "minimum_history_matches": self.minimum_history_matches,
            "minimum_shared_team_matches": self.minimum_shared_team_matches,
            "name": self.name,
            "optimizer_ftol": self.optimizer_ftol,
            "optimizer_max_iterations": self.optimizer_max_iterations,
            "recency_half_life_days": self.recency_half_life_days,
            "regime_feature_scale": self.regime_feature_scale,
            "regime_match_weight": self.regime_match_weight,
            "regime_mismatch_weight": self.regime_mismatch_weight,
            "regime_prior_scale": self.regime_prior_scale,
            "schedule_feature_scale": self.schedule_feature_scale,
            "shared_pace_dispersion": self.shared_pace_dispersion,
            "tail_tolerance": self.tail_tolerance,
            "target_feature_scale": self.target_feature_scale,
            "team_prior_scale": self.team_prior_scale,
            "unknown_regime_weight": self.unknown_regime_weight,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


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
            raise T13ValidationError("T13 history must contain HistoricalMatch records.")
    return tuple(selected)


def _conflicting_history_ids(history: Sequence[HistoricalMatch]) -> tuple[str, ...]:
    by_fixture: dict[str, HistoricalMatch] = {}
    conflicts: set[str] = set()
    for match in history:
        previous = by_fixture.get(match.fixture_id)
        if previous is not None and previous.to_dict() != match.to_dict():
            conflicts.add(match.fixture_id)
        by_fixture.setdefault(match.fixture_id, match)
    return tuple(sorted(conflicts))


def _history_digest(match: HistoricalMatch) -> str:
    return (
        match.source_digest
        if isinstance(match.source_digest, str) and match.source_digest
        else _digest(match.to_dict())
    )


def _history_record_digest(match: HistoricalMatch) -> str:
    """Digest the complete structured row, including model-driving metadata."""
    return _digest(match.to_dict())


def _cutoff_valid_history_match(match: HistoricalMatch, cutoff: datetime) -> bool:
    if match.fixture_status.upper() not in {"COMPLETED", "COMPLETE", "FINAL", "FINISHED", "PLAYED"}:
        return False
    if match.final_state is not EvidenceState.OBSERVED:
        return False
    if _parse_utc(match.kickoff_utc) > cutoff:
        return False
    timestamps = (match.observed_at_utc, match.published_at_utc)
    return not any(value is not None and _parse_utc(value) > cutoff for value in timestamps)


def _corner_pair(match: HistoricalMatch) -> tuple[int, int] | None:
    if match.metric_state(CORNER_FACTS[0]) is not EvidenceState.OBSERVED:
        return None
    if match.metric_state(CORNER_FACTS[1]) is not EvidenceState.OBSERVED:
        return None
    home = match.metrics.get(CORNER_FACTS[0])
    away = match.metrics.get(CORNER_FACTS[1])
    if (
        isinstance(home, bool)
        or not isinstance(home, int)
        or home < 0
        or isinstance(away, bool)
        or not isinstance(away, int)
        or away < 0
    ):
        return None
    return home, away


def _corner_history_row(match: HistoricalMatch) -> CornerHistory | None:
    pair = _corner_pair(match)
    if pair is None:
        return None
    return CornerHistory(
        fixture_id=match.fixture_id,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        kickoff_utc=match.kickoff_utc,
        home_corners=pair[0],
        away_corners=pair[1],
        competition_key=match.competition_key,
        regime_id=match.regime_id,
        source_digest=_history_digest(match),
        source_input_ids=tuple(
            sorted(
                {
                    *match.source_assertion_ids,
                    *match.metric_ids(CORNER_FACTS[0]),
                    *match.metric_ids(CORNER_FACTS[1]),
                }
            )
        ),
    )


def derive_corner_history(
    history: Iterable[HistoricalMatch | Mapping[str, object]],
) -> tuple[CornerHistory, ...]:
    """Return observed corner pairs in fixture-ID order without imputing gaps."""
    by_fixture: dict[str, CornerHistory] = {}
    for match in _coerce_history(history):
        row = _corner_history_row(match)
        if row is None:
            continue
        previous = by_fixture.get(row.fixture_id)
        if previous is not None and previous.to_dict() != row.to_dict():
            raise T13IntegrityError(
                f"Corner history fixture {row.fixture_id} was supplied with conflicting content."
            )
        by_fixture[row.fixture_id] = row
    return tuple(by_fixture[key] for key in sorted(by_fixture))


derive_joint_corner_history = derive_corner_history
derive_corner_history_rows = derive_corner_history


_T13_FEATURE_NAMES = (
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


def _feature_map(state: FrozenEvidenceState) -> Mapping[str, DerivedFeature]:
    return {feature.name: feature for feature in state.derived_features}


def _feature_is_observed(value: object) -> bool:
    selected = getattr(value, "state", None)
    return selected is EvidenceState.OBSERVED or str(selected) == EvidenceState.OBSERVED.value


def _feature_value(state: FrozenEvidenceState, name: str) -> object | None:
    feature = _feature_map(state).get(name)
    if feature is None or not _feature_is_observed(feature):
        return None
    return feature.value


def _feature_lineage(
    state: FrozenEvidenceState, selected_names: Sequence[str] = _T13_FEATURE_NAMES
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ids: set[str] = set()
    digests: set[str] = set()
    selected = set(selected_names)
    for feature in state.derived_features:
        if feature.name not in selected:
            continue
        if not _feature_is_observed(feature):
            continue
        ids.update(feature.input_ids)
        digests.update(feature.input_digests)
        ids.add(feature.feature_id)
        if feature.digest:
            digests.add(feature.digest)
    return tuple(sorted(ids)), tuple(sorted(digests))


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _team_feature_value(value: object, team_id: str) -> Mapping[str, object]:
    selected = _mapping_or_empty(value).get(team_id)
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


def _nested_map(value: object, *keys: str) -> Mapping[str, object]:
    current: object = value
    for key in keys:
        current = _mapping_or_empty(current).get(key)
    return current if isinstance(current, Mapping) else {}


def _regime_token(value: object, depth: int = 0) -> str | None:
    if depth > 4:
        return None
    if isinstance(value, str):
        selected = value.strip()
        if selected and selected.upper() not in {
            "UNKNOWN",
            "NONE",
            "NULL",
            "REGIME_NOT_RECORDED",
        }:
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


def _regime_weight(
    match: HistoricalMatch, target_regime: str | None, config: T13ModelConfig
) -> float:
    if target_regime is None:
        return 1.0
    if match.regime_id is None:
        return config.unknown_regime_weight
    if match.regime_id == target_regime:
        return config.regime_match_weight
    return config.regime_mismatch_weight


@dataclass(frozen=True)
class _CornerTrainingRow:
    fixture_id: str
    home_team_id: str
    away_team_id: str
    league_key: str
    kickoff_utc: str
    home_corners: int
    away_corners: int
    recency_weight: float
    regime_weight: float
    regime_id: str | None

    @property
    def weight(self) -> float:
        return self.recency_weight * self.regime_weight


def _training_rows(
    history: Sequence[HistoricalMatch],
    state: FrozenEvidenceState,
    config: T13ModelConfig,
) -> tuple[tuple[_CornerTrainingRow, ...], tuple[HistoricalMatch, ...], Mapping[str, str]]:
    target = state.target
    cutoff = _parse_utc(target.cutoff_utc)
    expected_ids = set(_state_history_ids(state))
    by_fixture: dict[str, HistoricalMatch] = {}
    invalid: dict[str, str] = {}
    for match in history:
        if match.fixture_id == target.fixture_id:
            invalid.setdefault(match.fixture_id, "TARGET_FIXTURE_EXCLUDED")
            continue
        if match.fixture_id not in expected_ids:
            continue
        if not _cutoff_valid_history_match(match, cutoff):
            invalid.setdefault(match.fixture_id, "NOT_CUTOFF_VALID")
            continue
        if match.competition_type.upper() != "TARGET_LEAGUE":
            invalid.setdefault(match.fixture_id, "NON_TARGET_COMPETITION_EXCLUDED")
            continue
        previous = by_fixture.get(match.fixture_id)
        if previous is not None and previous.to_dict() != match.to_dict():
            raise T13IntegrityError(
                f"Historical Match {match.fixture_id} was supplied with conflicting content."
            )
        by_fixture[match.fixture_id] = match

    ordered = tuple(sorted(by_fixture.values(), key=lambda item: item.fixture_id))
    target_regime = _target_regime(state)
    rows: list[_CornerTrainingRow] = []
    for match in ordered:
        pair = _corner_pair(match)
        if pair is None:
            invalid.setdefault(match.fixture_id, "RELIABLE_HOME_AND_AWAY_CORNERS_REQUIRED")
            continue
        age_days = max(
            0.0,
            (cutoff - _parse_utc(match.kickoff_utc)).total_seconds() / 86_400.0,
        )
        rows.append(
            _CornerTrainingRow(
                fixture_id=match.fixture_id,
                home_team_id=match.home_team_id,
                away_team_id=match.away_team_id,
                league_key=f"{match.competition_key or target.competition_key}:{target.season}",
                kickoff_utc=match.kickoff_utc,
                home_corners=pair[0],
                away_corners=pair[1],
                recency_weight=2.0 ** (-age_days / config.recency_half_life_days),
                regime_weight=_regime_weight(match, target_regime, config),
                regime_id=match.regime_id,
            )
        )
    return tuple(rows), ordered, MappingProxyType(dict(sorted(invalid.items())))


def _minimum_evidence_reason(
    rows: Sequence[_CornerTrainingRow], target: TargetMatch, config: T13ModelConfig
) -> str | None:
    if len(rows) < config.minimum_history_matches:
        return "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"
    effective = sum(row.weight for row in rows)
    if effective < config.minimum_effective_history_matches:
        return "MINIMUM_EFFECTIVE_HISTORY_NOT_SATISFIED"
    if len({team for row in rows for team in (row.home_team_id, row.away_team_id)}) < 2:
        return "MINIMUM_SHARED_TEAM_EVIDENCE_NOT_SATISFIED"
    direct_counts = {
        team_id: sum(team_id in (row.home_team_id, row.away_team_id) for row in rows)
        for team_id in target.team_ids
    }
    if any(
        count < 1 and len(rows) < config.minimum_shared_team_matches
        for count in direct_counts.values()
    ):
        return "MINIMUM_DIRECT_AND_SHARED_HISTORY_NOT_SATISFIED"
    return None


def _unresolved_corner_conflict_ids(state: FrozenEvidenceState) -> tuple[str, ...]:
    expected_ids = set(_state_history_ids(state)) - {state.target.fixture_id}
    return tuple(
        sorted(
            conflict.conflict_id
            for conflict in state.conflicts
            if conflict.material
            and conflict.status == "UNRESOLVED"
            and conflict.evidence_type == "MATCH_STATISTIC"
            and conflict.subject_id in expected_ids
            and conflict.predicate in CORNER_FACTS
        )
    )


def _frozen_history_input_mismatches(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> tuple[str, ...]:
    expected_ids = set(_state_history_ids(state)) - {state.target.fixture_id}
    if not expected_ids:
        return ()
    selected_assertions: dict[tuple[str, str], set[str]] = {}
    for conflict in state.conflicts:
        if (
            not conflict.material
            or conflict.status != "RESOLVED"
            or conflict.evidence_type != "MATCH_STATISTIC"
            or conflict.subject_id not in expected_ids
            or conflict.predicate not in CORNER_FACTS
        ):
            continue
        if conflict.selected_assertion_id is not None:
            selected_assertions.setdefault((conflict.subject_id, conflict.predicate), set()).add(
                conflict.selected_assertion_id
            )

    frozen_values: dict[str, dict[str, object]] = {}
    frozen_digests: dict[str, set[str]] = {}
    for fact in state.source_assertions:
        if (
            fact.evidence_type != "MATCH_STATISTIC"
            or fact.subject_id not in expected_ids
            or fact.predicate not in CORNER_FACTS
        ):
            continue
        selected = selected_assertions.get((fact.subject_id, fact.predicate))
        if selected is not None and fact.fact_id not in selected:
            continue
        frozen_values.setdefault(fact.subject_id, {})[fact.predicate] = fact.value
        if fact.source_digest is not None:
            frozen_digests.setdefault(fact.subject_id, set()).add(fact.source_digest)

    by_fixture = {match.fixture_id: match for match in history}
    mismatches: set[str] = set()
    for (subject_id, predicate), assertion_ids in selected_assertions.items():
        if len(assertion_ids) != 1 or not any(
            fact.subject_id == subject_id
            and fact.predicate == predicate
            and fact.fact_id in assertion_ids
            for fact in state.source_assertions
        ):
            mismatches.add(subject_id)
    for fixture_id, values in frozen_values.items():
        match = by_fixture.get(fixture_id)
        if match is None:
            continue
        if any(match.metrics.get(metric) != values.get(metric) for metric in CORNER_FACTS):
            mismatches.add(fixture_id)
        expected_digests = frozen_digests.get(fixture_id, set())
        if expected_digests and (
            len(expected_digests) != 1 or _history_digest(match) not in expected_digests
        ):
            mismatches.add(fixture_id)
    return tuple(sorted(mismatches))


def _frozen_history_metadata_mismatches(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> tuple[str, ...]:
    """Check model-driving history metadata preserved by the frozen state."""
    expected_ids = set(_state_history_ids(state)) - {state.target.fixture_id}
    if not expected_ids:
        return ()
    by_fixture = {match.fixture_id: match for match in history}
    facts_by_fixture: dict[str, list[SourceFact]] = {}
    mismatches: set[str] = set()
    for fact in state.source_assertions:
        if (
            fact.subject_id in expected_ids
            and fact.evidence_type == "MATCH_STATISTIC"
            and fact.predicate in CORNER_FACTS
        ):
            facts_by_fixture.setdefault(fact.subject_id, []).append(fact)
            if _feature_is_observed(fact) and str(fact.cutoff_eligibility) != "CUTOFF_VALID":
                mismatches.add(fact.subject_id)
    frozen_metadata = state.reproducibility.get("input_history_metadata")
    metadata_by_fixture = frozen_metadata if isinstance(frozen_metadata, Mapping) else {}
    for fixture_id in sorted(expected_ids):
        match = by_fixture.get(fixture_id)
        if match is None:
            continue
        expected_records: list[Mapping[str, object]] = []
        for fact in facts_by_fixture.get(fixture_id, ()):
            provenance = getattr(fact, "provenance", {})
            if isinstance(provenance, Mapping):
                expected_records.append(cast(Mapping[str, object], provenance))
            for key, actual in (
                ("source_key", match.source_key),
                ("origin_id", match.origin_id),
                ("observed_at_utc", match.observed_at_utc),
                ("published_at_utc", match.published_at_utc),
            ):
                expected = getattr(fact, key, None)
                if expected is not None and expected != actual:
                    mismatches.add(fixture_id)
        extra_metadata = metadata_by_fixture.get(fixture_id)
        if isinstance(extra_metadata, Mapping):
            expected_records.append(cast(Mapping[str, object], extra_metadata))
        else:
            expected_records.extend(
                cast(Mapping[str, object], item)
                for item in _as_sequence(extra_metadata)
                if isinstance(item, Mapping)
            )
        for expected in expected_records:
            for key, actual in (
                ("home_team_id", match.home_team_id),
                ("away_team_id", match.away_team_id),
                ("competition_key", match.competition_key),
                ("competition_type", match.competition_type),
                ("fixture_status", match.fixture_status),
                ("final_state", match.final_state),
                ("regime_id", match.regime_id),
                ("kickoff_utc", match.kickoff_utc),
            ):
                frozen = expected.get(key)
                if frozen is None:
                    continue
                if key == "kickoff_utc" and isinstance(frozen, str):
                    try:
                        matches = _canonical_utc(match.kickoff_utc) == _canonical_utc(frozen)
                    except T13ValidationError:
                        matches = False
                else:
                    matches = frozen == actual
                if not matches:
                    mismatches.add(fixture_id)
    return tuple(sorted(mismatches))


def _corner_feature_value(value: object, team_id: str) -> Mapping[str, object]:
    return _nested_map(_team_feature_value(value, team_id), "corners")


def _feature_offsets(
    state: FrozenEvidenceState | None,
    target: TargetMatch,
    config: T13ModelConfig,
    *,
    baseline_corner_rate: float,
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
    covariates: dict[str, dict[str, float]] = {"home": {}, "away": {}}

    for side, team_id in (("home", target.home_team_id), ("away", target.away_team_id)):
        corner_opponent = _corner_feature_value(opponent, team_id)
        opponent_adjusted = _nested_map(corner_opponent, "opponent_adjusted")
        opponent_difference = _number(opponent_adjusted.get("mean_difference"))
        if opponent_difference is not None:
            covariates[side]["opponent"] = _bounded(opponent_difference, -6.0, 6.0)
            components["opponent"][side] = scale * covariates[side]["opponent"]

        corner_venue = _corner_feature_value(venue, team_id)
        venue_effect = _number(corner_venue.get("venue_effect"))
        if venue_effect is not None:
            signed = venue_effect if side == "home" else -venue_effect
            covariates[side]["venue"] = _bounded(signed, -6.0, 6.0)
            components["venue"][side] = scale * covariates[side]["venue"]

        corner_recency = _corner_feature_value(recency, team_id)
        weighted_mean = _number(corner_recency.get("weighted_mean"))
        if weighted_mean is not None:
            covariates[side]["recency"] = _bounded(weighted_mean - baseline_corner_rate, -6.0, 6.0)
            components["recency"][side] = scale * covariates[side]["recency"]

        corner_horizons = _nested_map(_team_feature_value(horizons, team_id), "corners")
        recent = _number(_nested_map(corner_horizons, "recent").get("mean"))
        medium = _number(_nested_map(corner_horizons, "medium").get("mean"))
        if recent is not None and medium is not None:
            covariates[side]["form"] = _bounded(recent - medium, -6.0, 6.0)
            components["form"][side] = 0.5 * scale * covariates[side]["form"]
        else:
            trend = _nested_map(_team_feature_value(trends, team_id), "corners")
            direction = str(trend.get("direction", "")).upper()
            if direction == "INCREASING":
                components["form"][side] = 0.25 * scale
            elif direction == "DECREASING":
                components["form"][side] = -0.25 * scale

        rest_raw = _side_feature_raw(rest, side, team_id)
        rest_map = _mapping_or_empty(rest_raw)
        rest_days = _number(rest_map.get("rest_days") if rest_map else rest_raw)
        congestion_map = _side_feature_value(congestion, side, team_id)
        congestion_count = _number(congestion_map.get("count"))
        if rest_days is not None:
            normalized_rest = _bounded((rest_days - 7.0) / 7.0, -1.0, 1.0)
            covariates[side]["schedule"] = normalized_rest
            components["schedule"][side] += config.schedule_feature_scale * normalized_rest
        if congestion_count is not None:
            congestion_effect = -_bounded(congestion_count / 5.0, 0.0, 1.0)
            covariates[side]["congestion"] = congestion_effect
            components["schedule"][side] += config.schedule_feature_scale * congestion_effect
        cross_raw = _side_feature_raw(cross_competition, side, team_id)
        cross_count: float | None
        if isinstance(cross_raw, (tuple, list)):
            cross_count = float(len(cross_raw))
        elif isinstance(cross_raw, Mapping):
            cross_count = _number(cross_raw.get("count"))
        else:
            cross_count = None
        if cross_count is not None:
            components["schedule"][side] -= (
                config.schedule_feature_scale * 0.25 * _bounded(cross_count / 3.0, 0.0, 1.0)
            )

    effects = regime_effects or {}
    regime_value = _number(effects.get(regime_id)) if regime_id is not None else None
    if regime_value is not None:
        regime_offset = config.regime_feature_scale * _bounded(regime_value, -2.0, 2.0)
        components["regime"]["home"] = regime_offset
        components["regime"]["away"] = regime_offset
        covariates["home"]["regime"] = _bounded(regime_value, -2.0, 2.0)
        covariates["away"]["regime"] = _bounded(regime_value, -2.0, 2.0)

    home_offset = sum(item["home"] for item in components.values())
    away_offset = sum(item["away"] for item in components.values())
    return {
        "away": away_offset,
        "components": components,
        "feature_names": _T13_FEATURE_NAMES,
        "fitted_covariates": covariates,
        "home": home_offset,
        "regime_id": regime_id,
    }


def _numeric_modules() -> tuple[Any, Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    try:
        import numpy as np
        from scipy.optimize import minimize  # type: ignore[import-untyped]
        from scipy.special import digamma, gammaln  # type: ignore[import-untyped]
    except ImportError as error:
        raise _T13FitFailure(
            "T13 requires the native NumPy/SciPy runtime for deterministic MAP fitting."
        ) from error
    return np, minimize, gammaln, digamma


def _fit_numerical_parameters(
    rows: Sequence[_CornerTrainingRow], target: TargetMatch, config: T13ModelConfig
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    np, minimize, gammaln, digamma = _numeric_modules()
    if config.optimizer_max_iterations < 3:
        raise _T13FitFailure("T13 optimizer failed: maximum iterations are too small.")
    if not rows:
        raise _T13FitFailure("T13 has no reliable corner rows to fit.")

    target_league_key = f"{target.competition_key}:{target.season}"
    league_keys = tuple(sorted({row.league_key for row in rows} | {target_league_key}))
    team_ids = tuple(
        sorted(
            {
                *target.team_ids,
                *(team for row in rows for team in (row.home_team_id, row.away_team_id)),
            }
        )
    )
    league_index = {key: index for index, key in enumerate(league_keys)}
    team_index = {team: index for index, team in enumerate(team_ids)}
    league_count = len(league_keys)
    team_count = len(team_ids)
    venue_start = league_count
    for_start = venue_start + league_count
    against_start = for_start + team_count
    dispersion_index = against_start + team_count
    dispersion_group_start = dispersion_index + 1
    parameter_count = dispersion_group_start + league_count

    weights = np.asarray([row.weight for row in rows], dtype=np.float64)
    home_values = np.asarray([row.home_corners for row in rows], dtype=np.float64)
    away_values = np.asarray([row.away_corners for row in rows], dtype=np.float64)
    overall_home = float(np.average(home_values, weights=weights))
    overall_away = float(np.average(away_values, weights=weights))
    baseline = max(0.25, (overall_home + overall_away) / 2.0)
    totals = home_values + away_values
    total_mean = float(np.average(totals, weights=weights))
    total_variance = float(np.average((totals - total_mean) ** 2, weights=weights))
    initial_dispersion = max(
        config.minimum_dispersion,
        min(
            config.maximum_dispersion,
            (total_variance - total_mean) / max(total_mean**2, 1e-6),
        ),
    )
    initial_dispersion = max(config.minimum_dispersion, initial_dispersion)
    if config.shared_pace_dispersion is not None:
        initial_dispersion = config.shared_pace_dispersion
    log_max = math.log(max(config.maximum_expected_corners, 0.05))
    log_min = min(-8.0, log_max - 4.0)
    initial = np.zeros(parameter_count, dtype=np.float64)
    initial[:league_count] = _bounded(math.log(baseline), log_min, log_max)
    initial[dispersion_index] = math.log(initial_dispersion)

    home_indices = np.asarray([team_index[row.home_team_id] for row in rows], dtype=np.int64)
    away_indices = np.asarray([team_index[row.away_team_id] for row in rows], dtype=np.int64)
    league_indices = np.asarray([league_index[row.league_key] for row in rows], dtype=np.int64)
    log_prior_dispersion = math.log(config.dispersion_prior_mean)

    def value_and_gradient(vector: Any) -> tuple[float, Any]:
        league = vector[:league_count]
        venue_effects = vector[venue_start : venue_start + league_count]
        attack = vector[for_start : for_start + team_count]
        defense = vector[against_start : against_start + team_count]
        raw_dispersion = vector[dispersion_index]
        raw_dispersion_groups = vector[dispersion_group_start:]
        dispersion_log_min = math.log(config.minimum_dispersion)
        dispersion_log_max = math.log(config.maximum_dispersion)
        raw_local_dispersion = raw_dispersion + raw_dispersion_groups[league_indices]
        clipped_local_dispersion = np.clip(
            raw_local_dispersion,
            dispersion_log_min,
            dispersion_log_max,
        )
        dispersion_active = (
            (raw_local_dispersion > dispersion_log_min)
            & (raw_local_dispersion < dispersion_log_max)
        ).astype(np.float64)
        shape = np.exp(-clipped_local_dispersion)
        lambda_home = np.exp(
            np.clip(
                league[league_indices]
                + venue_effects[league_indices]
                + attack[home_indices]
                - defense[away_indices],
                log_min,
                log_max,
            )
        )
        lambda_away = np.exp(
            np.clip(
                league[league_indices] + attack[away_indices] - defense[home_indices],
                log_min,
                log_max,
            )
        )
        total_rate = lambda_home + lambda_away
        counts_total = home_values + away_values
        log_likelihood_terms = (
            gammaln(shape + counts_total)
            - gammaln(shape)
            - gammaln(home_values + 1.0)
            - gammaln(away_values + 1.0)
            + shape * np.log(shape)
            - (shape + counts_total) * np.log(shape + total_rate)
            + home_values * np.log(lambda_home)
            + away_values * np.log(lambda_away)
        )
        log_likelihood = float(np.sum(weights * log_likelihood_terms))
        d_home = home_values - (shape + counts_total) * lambda_home / (shape + total_rate)
        d_away = away_values - (shape + counts_total) * lambda_away / (shape + total_rate)
        d_shape = (
            digamma(shape + counts_total)
            - digamma(shape)
            + np.log(shape)
            + 1.0
            - np.log(shape + total_rate)
            - (shape + counts_total) / (shape + total_rate)
        )
        gradient = np.zeros(parameter_count, dtype=np.float64)
        weighted_home = weights * d_home
        weighted_away = weights * d_away
        gradient[:league_count] = np.bincount(
            league_indices, weights=weighted_home + weighted_away, minlength=league_count
        )
        gradient[venue_start : venue_start + league_count] = np.bincount(
            league_indices, weights=weighted_home, minlength=league_count
        )
        gradient[for_start : for_start + team_count] = np.bincount(
            home_indices, weights=weighted_home, minlength=team_count
        ) + np.bincount(away_indices, weights=weighted_away, minlength=team_count)
        gradient[against_start : against_start + team_count] = -np.bincount(
            away_indices, weights=weighted_home, minlength=team_count
        ) - np.bincount(home_indices, weights=weighted_away, minlength=team_count)
        weighted_dispersion = weights * d_shape * -shape * dispersion_active
        gradient[dispersion_index] = float(np.sum(weighted_dispersion))
        gradient[dispersion_group_start:] = np.bincount(
            league_indices,
            weights=weighted_dispersion,
            minlength=league_count,
        )

        prior = 0.0
        prior_gradient = np.zeros(parameter_count, dtype=np.float64)
        league_delta = league - math.log(baseline)
        prior += 0.5 * float(np.sum(league_delta**2)) / config.league_season_prior_scale**2
        prior_gradient[:league_count] += league_delta / config.league_season_prior_scale**2
        prior += 0.5 * float(np.sum(venue_effects**2)) / config.home_advantage_prior_scale**2
        prior_gradient[venue_start : venue_start + league_count] += (
            venue_effects / config.home_advantage_prior_scale**2
        )
        prior += 0.5 * float(np.sum(attack**2)) / config.team_prior_scale**2
        prior_gradient[for_start : for_start + team_count] += attack / config.team_prior_scale**2
        prior += 0.5 * float(np.sum(defense**2)) / config.team_prior_scale**2
        prior_gradient[against_start : against_start + team_count] += (
            defense / config.team_prior_scale**2
        )
        dispersion_delta = raw_dispersion - log_prior_dispersion
        prior += 0.5 * float(dispersion_delta**2) / config.dispersion_prior_scale**2
        prior_gradient[dispersion_index] += dispersion_delta / config.dispersion_prior_scale**2
        prior += (
            0.5 * float(np.sum(raw_dispersion_groups**2)) / config.league_dispersion_prior_scale**2
        )
        prior_gradient[dispersion_group_start:] += (
            raw_dispersion_groups / config.league_dispersion_prior_scale**2
        )
        objective = float(-log_likelihood + prior)
        full_gradient = -gradient + prior_gradient
        if not math.isfinite(objective) or not np.all(np.isfinite(full_gradient)):
            return math.inf, np.full_like(vector, math.nan, dtype=np.float64)
        return objective, full_gradient

    bounds: list[tuple[float, float]] = [(log_min, log_max)] * league_count
    bounds.extend([(-2.5, 2.5)] * league_count)
    bounds.extend([(-4.0, 4.0)] * team_count)
    bounds.extend([(-4.0, 4.0)] * team_count)
    dispersion_log_min = math.log(config.minimum_dispersion)
    dispersion_log_max = math.log(config.maximum_dispersion)
    if config.shared_pace_dispersion is None:
        bounds.append((dispersion_log_min, dispersion_log_max))
        bounds.extend(
            [(dispersion_log_min - dispersion_log_max, dispersion_log_max - dispersion_log_min)]
            * league_count
        )
    else:
        fixed_log_dispersion = math.log(config.shared_pace_dispersion)
        bounds.append((fixed_log_dispersion, fixed_log_dispersion))
        bounds.extend([(0.0, 0.0)] * league_count)
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
        raise _T13FitFailure(f"T13 optimizer failed: {result.message}")

    league = vector[:league_count].copy()
    venue_effects = vector[venue_start : venue_start + league_count].copy()
    attack = vector[for_start : for_start + team_count].copy()
    defense = vector[against_start : against_start + team_count].copy()
    local_dispersion_offsets = vector[dispersion_group_start:].copy()
    attack_mean = float(np.mean(attack))
    defense_mean = float(np.mean(defense))
    attack -= attack_mean
    defense -= defense_mean
    league += attack_mean - defense_mean
    dispersion = float(np.exp(vector[dispersion_index]))
    shape = 1.0 / dispersion
    local_dispersion_logs = np.clip(
        vector[dispersion_index] + local_dispersion_offsets,
        dispersion_log_min,
        dispersion_log_max,
    )
    local_dispersions = np.exp(local_dispersion_logs)
    parameters: Mapping[str, object] = {
        "baseline_corner_rate": baseline,
        "dispersion_log": float(vector[dispersion_index]),
        "league_season_intercepts": {
            key: float(league[index]) for key, index in sorted(league_index.items())
        },
        "shared_pace_dispersion": dispersion,
        "shared_pace_shape": shape,
        "league_season_dispersion_offsets": {
            key: float(local_dispersion_offsets[index])
            for key, index in sorted(league_index.items())
        },
        "league_season_dispersion_logs": {
            key: float(local_dispersion_logs[index]) for key, index in sorted(league_index.items())
        },
        "league_season_dispersions": {
            key: float(local_dispersions[index]) for key, index in sorted(league_index.items())
        },
        "team_corner_against": {
            key: float(defense[index]) for key, index in sorted(team_index.items())
        },
        "team_corner_for": {key: float(attack[index]) for key, index in sorted(team_index.items())},
        "home_venue_effects": {
            key: float(venue_effects[index]) for key, index in sorted(league_index.items())
        },
        "team_ids": team_ids,
        "league_keys": league_keys,
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
        "weighted_home_corner_mean": overall_home,
        "weighted_away_corner_mean": overall_away,
        "weighted_total_corner_mean": total_mean,
        "weighted_total_corner_variance": total_variance,
        "team_count": team_count,
        "league_count": league_count,
        "venue_effect_count": league_count,
        "dispersion_group_count": league_count,
        "league_dispersion_prior_scale": config.league_dispersion_prior_scale,
        "shared_pace_dispersion_fixed": config.shared_pace_dispersion is not None,
    }
    return parameters, diagnostics


def _regime_effects(
    rows: Sequence[_CornerTrainingRow], baseline_corner_rate: float, config: T13ModelConfig
) -> Mapping[str, float]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        if row.regime_id is None:
            continue
        grouped.setdefault(row.regime_id, []).append(
            (float(row.home_corners + row.away_corners), row.weight)
        )
    effects: dict[str, float] = {}
    for regime_id, values in sorted(grouped.items()):
        denominator = sum(weight for _, weight in values)
        if denominator <= 0:
            continue
        rate = sum(total * weight for total, weight in values) / denominator / 2.0
        raw_effect = math.log(max(rate, 0.05) / baseline_corner_rate)
        effects[regime_id] = _bounded(raw_effect / (1.0 + config.regime_prior_scale), -2.0, 2.0)
    return effects


def _uncertainty_metadata(
    rows: Sequence[_CornerTrainingRow], target: TargetMatch, config: T13ModelConfig
) -> Mapping[str, object]:
    effective_total = sum(row.weight for row in rows)
    teams: dict[str, object] = {}
    multipliers: list[float] = []
    for team_id in target.team_ids:
        direct_rows = tuple(row for row in rows if team_id in (row.home_team_id, row.away_team_id))
        direct_matches = len(direct_rows)
        effective_matches = sum(row.weight for row in direct_rows)
        direct_fraction = min(
            1.0,
            effective_matches / max(config.minimum_effective_history_matches, 1.0),
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
        "shared_pace_uncertainty": "MAP_dispersion_with_hierarchical_prior",
    }


def _fit_input_metadata(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    fixture_ids = tuple(sorted(match.fixture_id for match in history))
    training_ids: set[str] = set(fixture_ids)
    training_digests: set[str] = set()
    fixture_id_set = set(fixture_ids)
    for match in history:
        training_ids.update(match.source_assertion_ids)
        training_ids.update(match.metric_ids(CORNER_FACTS[0]))
        training_ids.update(match.metric_ids(CORNER_FACTS[1]))
        training_digests.add(_history_digest(match))
        training_digests.add(_history_record_digest(match))
    for fact in state.source_assertions:
        if (
            fact.subject_id in fixture_id_set
            and fact.evidence_type == "MATCH_STATISTIC"
            and fact.predicate in CORNER_FACTS
        ):
            training_ids.update(fact.source_assertion_ids)
            if fact.source_digest is not None:
                training_digests.add(fact.source_digest)
    feature_ids, _ = _feature_lineage(state)
    return (
        fixture_ids,
        tuple(sorted(training_digests)),
        tuple(sorted(training_ids)),
        feature_ids,
    )


def _training_input_provenance(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState
) -> Mapping[str, object]:
    provenance: dict[str, object] = {}
    for match in sorted(history, key=lambda item: item.fixture_id):
        fixture_provenance: dict[str, object] = {}
        for metric in CORNER_FACTS:
            source_fact_ids: set[str] = set()
            source_digests: set[str] = set()
            for fact in state.source_assertions:
                if fact.subject_id != match.fixture_id or fact.predicate != metric:
                    continue
                source_fact_ids.add(fact.fact_id)
                source_fact_ids.update(fact.source_assertion_ids)
                if fact.source_digest is not None:
                    source_digests.add(fact.source_digest)
            fixture_provenance[metric] = {
                "input_ids": tuple(sorted(match.metric_ids(metric))),
                "record_digest": _history_record_digest(match),
                "source_assertion_ids": tuple(sorted(source_fact_ids)),
                "source_digests": tuple(sorted(source_digests)),
            }
        fixture_provenance["history_metadata"] = {
            "away_team_id": match.away_team_id,
            "competition_key": match.competition_key,
            "competition_type": match.competition_type,
            "final_state": match.final_state,
            "fixture_status": match.fixture_status,
            "home_team_id": match.home_team_id,
            "kickoff_utc": match.kickoff_utc,
            "origin_id": match.origin_id,
            "observed_at_utc": match.observed_at_utc,
            "published_at_utc": match.published_at_utc,
            "regime_id": match.regime_id,
            "source_key": match.source_key,
        }
        provenance[match.fixture_id] = fixture_provenance
    return provenance


def _runtime_reproducibility(
    config: T13ModelConfig, state: FrozenEvidenceState, history: Sequence[HistoricalMatch]
) -> Mapping[str, object]:
    np, _, _, _ = _numeric_modules()
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
        "input_history_record_digests": tuple(
            sorted(_history_record_digest(match) for match in history)
        ),
        "numpy_version": str(getattr(np, "__version__", "unknown")),
        "platform": platform.platform(),
        "preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
        "preference_catalog_name": DEFAULT_PREFERENCE_CATALOG.name,
        "preference_catalog_version": DEFAULT_PREFERENCE_CATALOG.version,
        "preference_ids": CORNER_PREFERENCE_IDS,
        "python_version": platform.python_version(),
        "randomness": "none",
        "scipy_version": scipy_version,
        "shared_pace": "gamma_mean_one_hierarchical_variance_dispersion",
        "software_commit": os.environ.get("MATCHVET_COMMIT", "unknown"),
        "target_fixture_id": state.target_fixture_id,
    }


def _parameter_number(parameters: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = _number(parameters.get(key))
    return default if value is None else value


def _parameter_map(parameters: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parameters.get(key)
    return value if isinstance(value, Mapping) else {}


def _validate_state_target(state: FrozenEvidenceState) -> None:
    if state.target.fixture_id in state.target.team_ids:
        raise T13IntegrityError("T13 target identity overlaps a team identity.")
    if not state.digest:
        raise T13IntegrityError("T13 requires a digest-bearing FrozenEvidenceState.")


def _validate_prediction_state(fit: CornerModelFit, state: FrozenEvidenceState | None) -> None:
    if state is None:
        return
    if state.target.fixture_id != fit.target_fixture_id:
        raise T13IntegrityError(
            "The prediction FrozenEvidenceState does not identify the fitted target."
        )
    if state.digest != fit.frozen_evidence_digest:
        raise T13IntegrityError(
            "The prediction FrozenEvidenceState does not match the fitted evidence digest."
        )


def _joint_gamma_poisson_surface(
    home_rate: float,
    away_rate: float,
    dispersion: float,
    config: T13ModelConfig,
) -> tuple[Any, int, float]:
    np, _, gammaln, _ = _numeric_modules()
    if (
        not math.isfinite(home_rate)
        or not math.isfinite(away_rate)
        or home_rate <= 0
        or away_rate <= 0
    ):
        raise _T13FitFailure("T13 corner intensities must be finite and positive.")
    if not math.isfinite(dispersion) or dispersion <= 0:
        raise _T13FitFailure("T13 shared pace dispersion must be finite and positive.")
    shape = 1.0 / dispersion
    maximum = min(config.maximum_corner_count, max(8, 32))
    while True:
        counts = np.arange(maximum + 1, dtype=np.float64)
        home_counts = counts[:, None]
        away_counts = counts[None, :]
        total_counts = home_counts + away_counts
        total_rate = home_rate + away_rate
        log_surface = (
            gammaln(shape + total_counts)
            - gammaln(shape)
            - gammaln(home_counts + 1.0)
            - gammaln(away_counts + 1.0)
            + shape * math.log(shape)
            - (shape + total_counts) * math.log(shape + total_rate)
            + home_counts * math.log(home_rate)
            + away_counts * math.log(away_rate)
        )
        surface = np.exp(log_surface)
        raw_mass = float(np.sum(surface))
        tail_mass = abs(1.0 - raw_mass)
        if not math.isfinite(raw_mass) or raw_mass <= 0 or not math.isfinite(tail_mass):
            raise _T13FitFailure("T13 joint corner surface has invalid mass.")
        if tail_mass <= config.tail_tolerance:
            surface = np.maximum(surface / raw_mass, 0.0)
            normalized_mass = float(np.sum(surface))
            if not math.isfinite(normalized_mass) or normalized_mass <= 0:
                raise _T13FitFailure("T13 joint corner surface has invalid normalized mass.")
            surface = surface / normalized_mass
            if not np.all(np.isfinite(surface)) or np.any(surface < -1e-12):
                raise _T13FitFailure("T13 joint corner surface is not finite and non-negative.")
            return surface, maximum, tail_mass
        if maximum >= config.maximum_corner_count:
            raise _T13FitFailure(
                "T13 joint corner surface tail mass exceeds the versioned tolerance."
            )
        maximum = min(config.maximum_corner_count, max(maximum + 1, maximum * 2))


def _corner_marginals(
    joint: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    np, _, _, _ = _numeric_modules()
    matrix = np.asarray(joint, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise T13ValidationError("T13 corner marginals require a square joint surface.")
    home = np.sum(matrix, axis=1)
    away = np.sum(matrix, axis=0)
    total = np.zeros(2 * matrix.shape[0] - 1, dtype=np.float64)
    for home_count in range(matrix.shape[0]):
        for away_count in range(matrix.shape[1]):
            total[home_count + away_count] += matrix[home_count, away_count]
    for values in (home, away, total):
        mass = float(np.sum(values))
        if not math.isfinite(mass) or mass <= 0:
            raise T13ValidationError("T13 corner marginal has invalid mass.")
        values /= mass
    return (
        tuple(float(value) for value in home),
        tuple(float(value) for value in away),
        tuple(float(value) for value in total),
    )


def _moments(
    joint: Sequence[Sequence[float]],
) -> tuple[float, float, float, float, float, float]:
    home, away, _ = _corner_marginals(joint)
    expected_home = sum(index * value for index, value in enumerate(home))
    expected_away = sum(index * value for index, value in enumerate(away))
    variance_home = sum((index - expected_home) ** 2 * value for index, value in enumerate(home))
    variance_away = sum((index - expected_away) ** 2 * value for index, value in enumerate(away))
    covariance = sum(
        (home_count - expected_home) * (away_count - expected_away) * float(row[away_count])
        for home_count, row in enumerate(joint)
        for away_count in range(len(row))
    )
    correlation = covariance / math.sqrt(variance_home * variance_away)
    return (
        expected_home,
        expected_away,
        variance_home,
        variance_away,
        covariance,
        correlation,
    )


def _settlement_distributions(
    joint: Sequence[Sequence[float]],
) -> Mapping[str, SettlementProbabilities]:
    settlements: dict[str, SettlementProbabilities] = {}
    for preference in CORNER_PREFERENCES:
        win = 0.0
        if preference.family is PreferenceFamily.CORNER_WINNER:
            for home_count, row in enumerate(joint):
                for away_count, probability in enumerate(row):
                    if (
                        (preference.selection == "Home" and home_count > away_count)
                        or (preference.selection == "Draw" and home_count == away_count)
                        or (preference.selection == "Away" and away_count > home_count)
                    ):
                        win += float(probability)
        else:
            assert preference.line is not None
            for home_count, row in enumerate(joint):
                for away_count, probability in enumerate(row):
                    value = (
                        home_count + away_count
                        if preference.family is PreferenceFamily.TOTAL_CORNERS_OVER
                        else home_count
                        if preference.family is PreferenceFamily.HOME_CORNERS_OVER
                        else away_count
                    )
                    if value > preference.line:
                        win += float(probability)
        win = _bounded(win, 0.0, 1.0)
        settlements[preference.preference_id] = SettlementProbabilities(
            win_probability=win,
            loss_probability=1.0 - win,
            push_probability=0.0,
        )
    return settlements


@dataclass(frozen=True)
class CornerDistribution:
    """One normalized joint corner surface and its twelve derived markets."""

    status: ModelStatus
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    joint_corner_distribution: tuple[tuple[float, ...], ...] = ()
    home_corner_distribution: tuple[float, ...] = ()
    away_corner_distribution: tuple[float, ...] = ()
    total_corner_distribution: tuple[float, ...] = ()
    home_expected_corners: float | None = None
    away_expected_corners: float | None = None
    expected_corners: float | None = None
    home_corner_variance: float | None = None
    away_corner_variance: float | None = None
    corner_covariance: float | None = None
    corner_correlation: float | None = None
    shared_pace_dispersion: float | None = None
    shared_pace_shape: float | None = None
    maximum_corners: int | None = None
    tail_mass: float | None = None
    settlement_distributions: Mapping[str, SettlementProbabilities] = field(default_factory=dict)
    feature_inputs: Mapping[str, object] = field(default_factory=dict)
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    artifact_digest: str | None = None
    distribution_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.target_fixture_id, "T13 target fixture ID")
        _text(self.matchweek_id, "T13 matchweek ID")
        _text(self.model_version, "T13 model version")
        _text(self.model_digest, "T13 model digest")
        if not isinstance(self.status, ModelStatus):
            object.__setattr__(self, "status", ModelStatus(str(self.status)))
        selected = {str(key): value for key, value in self.settlement_distributions.items()}
        if not all(isinstance(value, SettlementProbabilities) for value in selected.values()):
            raise T13ValidationError("T13 settlement distributions require typed probabilities.")
        object.__setattr__(self, "settlement_distributions", MappingProxyType(selected))
        object.__setattr__(self, "feature_inputs", _freeze_map(self.feature_inputs))
        object.__setattr__(self, "uncertainty", _freeze_map(self.uncertainty))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        if self.status is ModelStatus.AVAILABLE:
            if not self.joint_corner_distribution:
                raise T13ValidationError("An available T13 distribution requires a joint surface.")
            rows = tuple(
                tuple(float(cell) for cell in row) for row in self.joint_corner_distribution
            )
            if not rows or any(len(row) != len(rows) for row in rows):
                raise T13ValidationError("T13 joint corner surfaces must be square.")
            if any(not math.isfinite(cell) or cell < -1e-12 for row in rows for cell in row):
                raise T13ValidationError(
                    "T13 joint corner surfaces must be finite and non-negative."
                )
            if abs(sum(sum(row) for row in rows) - 1.0) > 1e-9:
                raise T13ValidationError("T13 joint corner surfaces must be normalized.")
            home, away, total = _corner_marginals(rows)
            for marginal, expected_marginal, label in (
                (self.home_corner_distribution, home, "Home"),
                (self.away_corner_distribution, away, "Away"),
                (self.total_corner_distribution, total, "total"),
            ):
                if marginal and (
                    len(marginal) != len(expected_marginal)
                    or any(
                        abs(float(left) - right) > 1e-9
                        for left, right in zip(marginal, expected_marginal, strict=True)
                    )
                ):
                    raise T13IntegrityError(
                        f"T13 {label} corner marginal does not match the joint surface."
                    )
            moments = _moments(rows)
            numeric_fields = (
                (self.home_expected_corners, moments[0], "Home expected corners"),
                (self.away_expected_corners, moments[1], "Away expected corners"),
                (self.home_corner_variance, moments[2], "Home corner variance"),
                (self.away_corner_variance, moments[3], "Away corner variance"),
                (self.corner_covariance, moments[4], "Corner covariance"),
                (self.corner_correlation, moments[5], "Corner correlation"),
            )
            for observed_value, expected_moment, label in numeric_fields:
                if observed_value is not None and (
                    not math.isfinite(float(observed_value))
                    or abs(float(observed_value) - expected_moment) > 1e-8
                ):
                    raise T13IntegrityError(f"T13 {label} does not match the joint surface.")
            if self.expected_corners is not None and (
                not math.isfinite(float(self.expected_corners))
                or abs(float(self.expected_corners) - moments[0] - moments[1]) > 1e-8
            ):
                raise T13IntegrityError("T13 expected corners do not match the joint surface.")
            if self.tail_mass is not None and (
                not math.isfinite(float(self.tail_mass)) or not 0.0 <= float(self.tail_mass) <= 1.0
            ):
                raise T13ValidationError("T13 corner tail mass must be between zero and one.")
            if self.shared_pace_dispersion is not None and (
                not math.isfinite(float(self.shared_pace_dispersion))
                or float(self.shared_pace_dispersion) <= 0
            ):
                raise T13ValidationError("T13 shared pace dispersion must be positive.")
            if self.shared_pace_shape is not None and (
                not math.isfinite(float(self.shared_pace_shape))
                or float(self.shared_pace_shape) <= 0
            ):
                raise T13ValidationError("T13 shared pace shape must be positive.")
            if set(selected) != set(CORNER_PREFERENCE_IDS):
                raise T13ValidationError(
                    "Available T13 distributions must contain exactly the v1 corner markets."
                )
            actual_settlements = _settlement_distributions(rows)
            for key, expected_settlement in actual_settlements.items():
                actual_settlement = selected[key]
                if any(
                    abs(
                        getattr(actual_settlement, field_name)
                        - getattr(expected_settlement, field_name)
                    )
                    > 1e-9
                    for field_name in ("win", "loss", "push")
                ):
                    raise T13IntegrityError(
                        f"T13 settlement distribution {key} does not match the joint surface."
                    )
            object.__setattr__(self, "joint_corner_distribution", rows)
            object.__setattr__(self, "home_corner_distribution", home)
            object.__setattr__(self, "away_corner_distribution", away)
            object.__setattr__(self, "total_corner_distribution", total)
            if self.home_expected_corners is None:
                object.__setattr__(self, "home_expected_corners", moments[0])
            if self.away_expected_corners is None:
                object.__setattr__(self, "away_expected_corners", moments[1])
            if self.expected_corners is None:
                object.__setattr__(self, "expected_corners", moments[0] + moments[1])
            if self.home_corner_variance is None:
                object.__setattr__(self, "home_corner_variance", moments[2])
            if self.away_corner_variance is None:
                object.__setattr__(self, "away_corner_variance", moments[3])
            if self.corner_covariance is None:
                object.__setattr__(self, "corner_covariance", moments[4])
            if self.corner_correlation is None:
                object.__setattr__(self, "corner_correlation", moments[5])
        elif (
            self.joint_corner_distribution
            or self.home_corner_distribution
            or self.away_corner_distribution
            or self.total_corner_distribution
            or self.settlement_distributions
        ):
            raise T13ValidationError(
                "MODEL_UNAVAILABLE distributions cannot contain probability output."
            )
        expected_digest = _digest(self._core_dict(include_digest=False))
        if self.distribution_digest and self.distribution_digest != expected_digest:
            raise T13IntegrityError("T13 distribution digest does not match its content.")
        object.__setattr__(self, "distribution_digest", expected_digest)

    @property
    def digest(self) -> str:
        return self.distribution_digest

    @property
    def is_available(self) -> bool:
        return self.status is ModelStatus.AVAILABLE

    @property
    def model_unavailable(self) -> bool:
        return self.status is ModelStatus.MODEL_UNAVAILABLE

    @property
    def joint_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.joint_corner_distribution

    @property
    def score_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.joint_corner_distribution

    @property
    def corner_distribution(self) -> tuple[tuple[float, ...], ...]:
        return self.joint_corner_distribution

    @property
    def joint_corner_grid(self) -> tuple[tuple[float, ...], ...]:
        return self.joint_corner_distribution

    @property
    def corner_grid(self) -> tuple[tuple[float, ...], ...]:
        return self.joint_corner_distribution

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
    def settlements(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "away_corner_distribution": self.away_corner_distribution,
            "away_corner_variance": self.away_corner_variance,
            "away_expected_corners": self.away_expected_corners,
            "corner_correlation": self.corner_correlation,
            "corner_covariance": self.corner_covariance,
            "diagnostics": dict(self.diagnostics),
            "expected_corners": self.expected_corners,
            "feature_inputs": dict(self.feature_inputs),
            "home_corner_distribution": self.home_corner_distribution,
            "home_corner_variance": self.home_corner_variance,
            "home_expected_corners": self.home_expected_corners,
            "joint_corner_distribution": self.joint_corner_distribution,
            "matchweek_id": self.matchweek_id,
            "maximum_corners": self.maximum_corners,
            "model_digest": self.model_digest,
            "model_version": self.model_version,
            "reason": self.reason,
            "settlement_distributions": {
                key: value.to_dict() for key, value in sorted(self.settlement_distributions.items())
            },
            "shared_pace_dispersion": self.shared_pace_dispersion,
            "shared_pace_shape": self.shared_pace_shape,
            "status": self.status.value,
            "tail_mass": self.tail_mass,
            "target_fixture_id": self.target_fixture_id,
            "total_corner_distribution": self.total_corner_distribution,
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

    def with_artifact(self, artifact_digest: str) -> CornerDistribution:
        return replace(self, artifact_digest=_text(artifact_digest, "T13 artifact digest"))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CornerDistribution:
        status = ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value)))
        settlements: dict[str, SettlementProbabilities] = {}
        settlement_raw = value.get("settlement_distributions", {})
        if isinstance(settlement_raw, Mapping):
            for key, item in settlement_raw.items():
                mapped = _mapping(item, "T13 settlement distribution")
                settlements[str(key)] = SettlementProbabilities(
                    win_probability=_finite(mapped.get("WIN"), "T13 WIN"),
                    loss_probability=_finite(mapped.get("LOSS"), "T13 LOSS"),
                    push_probability=_finite(mapped.get("PUSH", 0.0), "T13 PUSH"),
                )

        def values(key: str) -> tuple[float, ...]:
            return tuple(_finite(item, f"T13 {key}") for item in _as_sequence(value.get(key, ())))

        joint_raw = value.get(
            "joint_corner_distribution",
            value.get(
                "joint_distribution",
                value.get("corner_distribution", value.get("score_distribution", ())),
            ),
        )
        joint = tuple(
            tuple(_finite(cell, "T13 joint corner distribution value") for cell in row)
            for row in _as_sequence(joint_raw)
            if isinstance(row, (tuple, list))
        )

        def optional(key: str) -> float | None:
            return _number(value.get(key)) if value.get(key) is not None else None

        maximum_raw = value.get("maximum_corners")
        maximum = (
            int(maximum_raw)
            if isinstance(maximum_raw, int) and not isinstance(maximum_raw, bool)
            else None
        )
        reason = value.get("reason")
        return cls(
            status=status,
            target_fixture_id=_text(value.get("target_fixture_id"), "T13 fixture ID"),
            matchweek_id=_text(value.get("matchweek_id"), "T13 matchweek ID"),
            model_version=_text(value.get("model_version"), "T13 model version"),
            model_digest=_text(value.get("model_digest"), "T13 model digest"),
            joint_corner_distribution=joint,
            home_corner_distribution=values("home_corner_distribution"),
            away_corner_distribution=values("away_corner_distribution"),
            total_corner_distribution=values("total_corner_distribution"),
            home_expected_corners=optional("home_expected_corners"),
            away_expected_corners=optional("away_expected_corners"),
            expected_corners=optional("expected_corners"),
            home_corner_variance=optional("home_corner_variance"),
            away_corner_variance=optional("away_corner_variance"),
            corner_covariance=optional("corner_covariance"),
            corner_correlation=optional("corner_correlation"),
            shared_pace_dispersion=optional("shared_pace_dispersion"),
            shared_pace_shape=optional("shared_pace_shape"),
            maximum_corners=maximum,
            tail_mass=optional("tail_mass"),
            settlement_distributions=settlements,
            feature_inputs=_mapping(value.get("feature_inputs", {}), "T13 feature inputs"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T13 uncertainty"),
            diagnostics=_mapping(value.get("diagnostics", {}), "T13 diagnostics"),
            reason=reason if isinstance(reason, str) else None,
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            distribution_digest=str(value.get("distribution_digest", "")),
        )


JointCornerDistribution = CornerDistribution


@dataclass(frozen=True)
class CornerModelFit:
    """A deterministic fitted T13 model with frozen-input identity."""

    status: ModelStatus
    model_name: str
    model_version: str
    algorithm_version: str
    feature_version: str
    target: TargetMatch
    config: T13ModelConfig
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
        for label, value in (
            ("model name", self.model_name),
            ("model version", self.model_version),
            ("algorithm version", self.algorithm_version),
            ("feature version", self.feature_version),
        ):
            _text(value, f"T13 {label}")
        if not isinstance(self.target, TargetMatch):
            raise T13ValidationError("T13 fits require a TargetMatch.")
        if not isinstance(self.config, T13ModelConfig):
            raise T13ValidationError("T13 fits require a T13ModelConfig.")
        for name in ("parameters", "diagnostics", "uncertainty", "reproducibility"):
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
            raise T13ValidationError("Available T13 fits require fitted parameters.")
        expected_digest = _digest(self._core_dict(include_digest=False))
        if self.fit_digest and self.fit_digest != expected_digest:
            raise T13IntegrityError("T13 fit digest does not match its content.")
        object.__setattr__(self, "fit_digest", expected_digest)

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
    def fitted_parameters(self) -> Mapping[str, object]:
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

    def with_artifact(self, artifact_digest: str) -> CornerModelFit:
        return replace(self, artifact_digest=_text(artifact_digest, "T13 artifact digest"))

    def predict(
        self,
        frozen_evidence_state: FrozenEvidenceState | None = None,
    ) -> CornerDistribution:
        return predict_joint_corner_distribution(self, frozen_evidence_state)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CornerModelFit:
        target_value = _mapping(value.get("target"), "T13 fit target")
        config_value = _mapping(value.get("config"), "T13 fit config")
        config_fields = {
            key: config_value[key]
            for key in T13ModelConfig.__dataclass_fields__
            if key in config_value
        }

        def strings(key: str) -> tuple[str, ...]:
            return tuple(item for item in _as_sequence(value.get(key, ())) if isinstance(item, str))

        return cls(
            status=ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value))),
            model_name=_text(value.get("model_name"), "T13 model name"),
            model_version=_text(value.get("model_version"), "T13 model version"),
            algorithm_version=_text(value.get("algorithm_version"), "T13 algorithm version"),
            feature_version=_text(value.get("feature_version"), "T13 feature version"),
            target=TargetMatch(**cast(dict[str, Any], dict(target_value))),
            config=T13ModelConfig(**cast(dict[str, Any], config_fields)),
            parameters=_mapping(value.get("parameters", {}), "T13 parameters"),
            training_input_fixture_ids=strings("training_input_fixture_ids"),
            training_input_digests=strings("training_input_digests"),
            training_input_ids=strings("training_input_ids"),
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
            feature_input_ids=strings("feature_input_ids"),
            feature_input_digests=strings("feature_input_digests"),
            diagnostics=_mapping(value.get("diagnostics", {}), "T13 diagnostics"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T13 uncertainty"),
            reproducibility=_mapping(value.get("reproducibility", {}), "T13 reproducibility"),
            reason=(cast(str, value["reason"]) if isinstance(value.get("reason"), str) else None),
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            fit_digest=str(value.get("fit_digest", "")),
        )


JointCornerModelFit = CornerModelFit
T13CornerModelFit = CornerModelFit


def _unavailable_distribution(fit: CornerModelFit, reason: str) -> CornerDistribution:
    return CornerDistribution(
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


def _prediction_rates(
    fit: CornerModelFit, state: FrozenEvidenceState | None
) -> tuple[float, float, float, Mapping[str, object]]:
    _validate_prediction_state(fit, state)
    target = fit.target
    parameters = fit.parameters
    intercepts = _parameter_map(parameters, "league_season_intercepts")
    league_key = f"{target.competition_key}:{target.season}"
    baseline = max(_parameter_number(parameters, "baseline_corner_rate", 1.0), 0.05)
    intercept = _number(intercepts.get(league_key))
    if intercept is None:
        intercept = math.log(baseline)
    for_effects = _parameter_map(parameters, "team_corner_for")
    against_effects = _parameter_map(parameters, "team_corner_against")
    home_for = _parameter_number(for_effects, target.home_team_id)
    away_for = _parameter_number(for_effects, target.away_team_id)
    home_against = _parameter_number(against_effects, target.home_team_id)
    away_against = _parameter_number(against_effects, target.away_team_id)
    stored_offsets = _parameter_map(parameters, "target_feature_offsets")
    offsets = _feature_offsets(
        state,
        target,
        fit.config,
        baseline_corner_rate=baseline,
        regime_effects=_parameter_map(parameters, "regime_effects"),
        stored=stored_offsets,
    )
    home_offset = _parameter_number(offsets, "home")
    away_offset = _parameter_number(offsets, "away")
    venue_effects = _parameter_map(parameters, "home_venue_effects")
    home_venue = _parameter_number(
        venue_effects,
        league_key,
        _parameter_number(parameters, "home_venue_effect"),
    )
    log_max = math.log(max(fit.config.maximum_expected_corners, 0.05))
    log_min = min(-8.0, log_max - 4.0)
    home_eta = _bounded(
        intercept + home_venue + home_for - away_against + home_offset,
        log_min,
        log_max,
    )
    away_eta = _bounded(intercept + away_for - home_against + away_offset, log_min, log_max)
    population_dispersion = _parameter_number(
        parameters,
        "shared_pace_dispersion",
        fit.config.shared_pace_dispersion or fit.config.dispersion_prior_mean,
    )
    local_dispersions = _parameter_map(parameters, "league_season_dispersions")
    dispersion = _parameter_number(local_dispersions, league_key, population_dispersion)
    dispersion = _bounded(
        dispersion,
        fit.config.minimum_dispersion,
        fit.config.maximum_dispersion,
    )
    return math.exp(home_eta), math.exp(away_eta), dispersion, offsets


def predict_joint_corner_distribution(
    fit: CornerModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> CornerDistribution:
    """Return the normalized T13 joint corner surface and all corner markets."""
    if not isinstance(fit, CornerModelFit):
        raise T13ValidationError("T13 prediction requires a CornerModelFit.")
    if not fit.is_available:
        return _unavailable_distribution(fit, fit.reason or "MODEL_UNAVAILABLE")
    selected_state = frozen_evidence_state
    try:
        home_rate, away_rate, dispersion, offsets = _prediction_rates(fit, selected_state)
        joint, maximum, tail_mass = _joint_gamma_poisson_surface(
            home_rate,
            away_rate,
            dispersion,
            fit.config,
        )
        home_marginal, away_marginal, total_marginal = _corner_marginals(joint)
        settlements = _settlement_distributions(joint)
        moments = _moments(joint)
    except _T13FitFailure as error:
        return _unavailable_distribution(fit, str(error))
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        return _unavailable_distribution(fit, f"PREDICTION_FAILED:{error}")

    feature_ids, feature_digests = (
        _feature_lineage(selected_state)
        if selected_state is not None
        else (fit.feature_input_ids, fit.feature_input_digests)
    )
    diagnostics = dict(fit.diagnostics)
    diagnostics.update(
        {
            "maximum_corner_count": maximum,
            "joint_grid_cells": int(joint.size),
            "tail_mass": tail_mass,
            "shared_pace_covariance": moments[4],
            "shared_pace_correlation": moments[5],
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
    uncertainty["joint_corner_grid_tail_tolerance"] = fit.config.tail_tolerance
    return CornerDistribution(
        status=ModelStatus.AVAILABLE,
        target_fixture_id=fit.target_fixture_id,
        matchweek_id=fit.matchweek_id,
        model_version=fit.model_version,
        model_digest=fit.digest,
        joint_corner_distribution=tuple(tuple(float(cell) for cell in row) for row in joint),
        home_corner_distribution=home_marginal,
        away_corner_distribution=away_marginal,
        total_corner_distribution=total_marginal,
        home_expected_corners=moments[0],
        away_expected_corners=moments[1],
        expected_corners=moments[0] + moments[1],
        home_corner_variance=moments[2],
        away_corner_variance=moments[3],
        corner_covariance=moments[4],
        corner_correlation=moments[5],
        shared_pace_dispersion=dispersion,
        shared_pace_shape=1.0 / dispersion,
        maximum_corners=maximum,
        tail_mass=tail_mass,
        settlement_distributions=settlements,
        feature_inputs=feature_inputs,
        uncertainty=uncertainty,
        diagnostics=diagnostics,
    )


def predict_corner_distribution(
    fit: CornerModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> CornerDistribution:
    return predict_joint_corner_distribution(fit, frozen_evidence_state)


predict_joint_corners = predict_joint_corner_distribution
predict_corners = predict_joint_corner_distribution


def _coerce_state(value: object) -> FrozenEvidenceState:
    if isinstance(value, FrozenEvidenceState):
        return value
    if isinstance(value, Mapping):
        return FrozenEvidenceState.from_dict(value)
    raise T13ValidationError("T13 requires a FrozenEvidenceState from T09.")


def _new_unavailable_fit(
    state: FrozenEvidenceState,
    config: T13ModelConfig,
    *,
    reason: str,
    history: Sequence[HistoricalMatch] = (),
    rows: Sequence[_CornerTrainingRow] = (),
    diagnostics: Mapping[str, object] | None = None,
) -> CornerModelFit:
    fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(history, state)
    _, feature_digests = _feature_lineage(state)
    try:
        reproducibility = _runtime_reproducibility(config, state, history)
    except _T13FitFailure:
        reproducibility = {
            "algorithm_version": config.algorithm_version,
            "config_digest": config.digest,
            "cutoff_utc": state.cutoff_utc,
            "frozen_evidence_digest": state.digest,
            "history_order": "fixture_id_ascending",
            "input_history_fixture_ids": fixture_ids,
            "preference_ids": CORNER_PREFERENCE_IDS,
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
    return CornerModelFit(
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


def fit_joint_corner_model(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    *,
    evidence_state: object | None = None,
    state: object | None = None,
    config: T13ModelConfig | None = None,
    model_config: T13ModelConfig | None = None,
) -> CornerModelFit:
    """Fit the deterministic T13 MAP model from one frozen T09 state."""
    if evidence_state is not None and state is not None:
        raise T13ValidationError("T13 received two FrozenEvidenceState aliases.")
    if state is not None:
        evidence_state = state
    if evidence_state is not None:
        if frozen_evidence_state is not None:
            raise T13ValidationError("T13 received two FrozenEvidenceState arguments.")
        frozen_evidence_state = evidence_state
    if config is not None and model_config is not None:
        raise T13ValidationError("T13 received two model configurations.")
    selected_config = config or model_config or T13ModelConfig()
    if not isinstance(selected_config, T13ModelConfig):
        raise T13ValidationError("T13 config must be a T13ModelConfig.")

    selected_history: object = history
    if isinstance(history, FrozenEvidenceState):
        if frozen_evidence_state is None:
            raise T13ValidationError("The state-first T13 form also requires history.")
        selected_state = _coerce_state(history)
        selected_history = frozen_evidence_state
    else:
        if frozen_evidence_state is None:
            raise T13ValidationError("T13 fitting requires a FrozenEvidenceState from T09.")
        selected_state = _coerce_state(frozen_evidence_state)
    _validate_state_target(selected_state)
    if selected_history is None or isinstance(selected_history, FrozenEvidenceState):
        raise T13ValidationError("T13 fitting requires structured HistoricalMatch rows.")
    if not isinstance(selected_history, Iterable):
        raise T13ValidationError("T13 history must be iterable.")
    history_records = _coerce_history(
        cast(Iterable[HistoricalMatch | Mapping[str, object]], selected_history)
    )
    conflicting_history_ids = _conflicting_history_ids(history_records)
    if conflicting_history_ids:
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="CONFLICTING_CORNER_HISTORY",
            history=history_records,
            diagnostics={
                "conflicting_fixture_ids": conflicting_history_ids,
                "corner_history_metrics": CORNER_FACTS,
            },
        )
    rows, ordered_history, invalid = _training_rows(
        history_records,
        selected_state,
        selected_config,
    )
    cutoff = _parse_utc(selected_state.target.cutoff_utc)
    expected_history_ids = set(_state_history_ids(selected_state)) - {
        selected_state.target.fixture_id
    }
    supplied_cutoff_ids = {
        match.fixture_id for match in history_records if _cutoff_valid_history_match(match, cutoff)
    }
    supplied_cutoff_ids.discard(selected_state.target.fixture_id)
    missing_history_ids = tuple(sorted(expected_history_ids - supplied_cutoff_ids))
    unexpected_history_ids = tuple(sorted(supplied_cutoff_ids - expected_history_ids))
    base_diagnostics: dict[str, object] = {
        "invalid_history_fixture_ids": tuple(sorted(invalid)),
        "invalid_history_reasons": dict(invalid),
        "corner_history_metrics": CORNER_FACTS,
    }
    if missing_history_ids:
        base_diagnostics["missing_fixture_ids"] = missing_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_INCOMPLETE",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    if unexpected_history_ids:
        base_diagnostics["unexpected_fixture_ids"] = unexpected_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    unresolved_conflict_ids = _unresolved_corner_conflict_ids(selected_state)
    if unresolved_conflict_ids:
        base_diagnostics["unresolved_material_conflict_ids"] = unresolved_conflict_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="UNRESOLVED_MATERIAL_CONFLICT",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    mismatched_history_ids = _frozen_history_input_mismatches(history_records, selected_state)
    if mismatched_history_ids:
        base_diagnostics["mismatched_fixture_ids"] = mismatched_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    mismatched_history_metadata_ids = _frozen_history_metadata_mismatches(
        history_records, selected_state
    )
    if mismatched_history_metadata_ids:
        base_diagnostics["mismatched_history_metadata_fixture_ids"] = (
            mismatched_history_metadata_ids
        )
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    minimum_reason = _minimum_evidence_reason(rows, selected_state.target, selected_config)
    if minimum_reason is not None:
        base_diagnostics["minimum_history_reason"] = minimum_reason
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason=minimum_reason,
            history=ordered_history,
            rows=rows,
            diagnostics=base_diagnostics,
        )

    try:
        parameters, numerical_diagnostics = _fit_numerical_parameters(
            rows, selected_state.target, selected_config
        )
        baseline = _number(parameters.get("baseline_corner_rate"))
        if baseline is None or baseline <= 0:
            raise _T13FitFailure("T13 fit did not retain a finite baseline corner rate.")
        effects = _regime_effects(rows, baseline, selected_config)
        offsets = _feature_offsets(
            selected_state,
            selected_state.target,
            selected_config,
            baseline_corner_rate=baseline,
            regime_effects=effects,
        )
        selected_parameters = dict(parameters)
        selected_parameters.update(
            {
                "feature_version": selected_config.feature_version,
                "feature_coefficients": {
                    "opponent": selected_config.target_feature_scale,
                    "recency": selected_config.target_feature_scale,
                    "venue": selected_config.target_feature_scale,
                    "form": selected_config.target_feature_scale * 0.5,
                    "schedule": selected_config.schedule_feature_scale,
                    "regime": selected_config.regime_feature_scale,
                },
                "regime_effects": effects,
                "target_feature_offsets": offsets,
                "target_model_covariates": offsets.get("fitted_covariates", {}),
                "target_regime_id": _target_regime(selected_state),
            }
        )
        fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(
            ordered_history, selected_state
        )
        _, feature_digests = _feature_lineage(selected_state)
        diagnostics = dict(numerical_diagnostics)
        diagnostics.update(base_diagnostics)
        diagnostics.update(
            {
                "recency_half_life_days": selected_config.recency_half_life_days,
                "regime_match_weight": selected_config.regime_match_weight,
                "regime_mismatch_weight": selected_config.regime_mismatch_weight,
                "unknown_regime_weight": selected_config.unknown_regime_weight,
                "regime_effects": effects,
                "training_input_provenance": _training_input_provenance(
                    ordered_history, selected_state
                ),
            }
        )
        fit = CornerModelFit(
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
            uncertainty=_uncertainty_metadata(
                rows,
                selected_state.target,
                selected_config,
            ),
            reproducibility=_runtime_reproducibility(
                selected_config,
                selected_state,
                ordered_history,
            ),
        )
        validation_prediction = predict_joint_corner_distribution(fit, selected_state)
        if not validation_prediction.is_available:
            raise _T13FitFailure(
                validation_prediction.reason or "INVALID_JOINT_CORNER_DISTRIBUTION"
            )
        return fit
    except _T13FitFailure as error:
        base_diagnostics["fit_error"] = str(error)
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        base_diagnostics["fit_error"] = str(error)
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            diagnostics=base_diagnostics,
        )


fit_corner_model = fit_joint_corner_model
fit_joint_corners = fit_joint_corner_model
fit_corners = fit_joint_corner_model
fit_t13 = fit_joint_corner_model


def fit_joint_corner_model_from_store(
    store: Store,
    frozen_evidence_state: FrozenEvidenceState | Mapping[str, object],
    *,
    config: T13ModelConfig | None = None,
) -> CornerModelFit:
    """Fit T13 from the cutoff-valid structured history behind a T09 state."""
    if not isinstance(store, Store):
        raise T13ValidationError("T13 store fitting requires a MatchVet Store.")
    state = _coerce_state(frozen_evidence_state)
    from matchvet.t09 import _t06_history_and_facts

    history, _ = _t06_history_and_facts(
        store,
        season=state.target.season,
        cutoff_utc=state.target.cutoff_utc,
        excluded_fixture_ids=(state.target.fixture_id,),
    )
    return fit_joint_corner_model(history, state, config=config)


class T13ModelService:
    """Small service facade for fitting and predicting one T13 corner model."""

    def __init__(self, config: T13ModelConfig | None = None) -> None:
        self.config = config or T13ModelConfig()

    def fit(
        self,
        history: Iterable[HistoricalMatch | Mapping[str, object]],
        frozen_evidence_state: FrozenEvidenceState,
    ) -> CornerModelFit:
        return fit_joint_corner_model(history, frozen_evidence_state, config=self.config)

    @staticmethod
    def predict(
        fit: CornerModelFit,
        frozen_evidence_state: FrozenEvidenceState | None = None,
    ) -> CornerDistribution:
        return predict_joint_corner_distribution(fit, frozen_evidence_state)


T13Runner = T13ModelService
JointCornerModel = T13ModelService
CornerModel = T13ModelService


@dataclass(frozen=True)
class T13Plan:
    """Immutable identity for a T13 joint corner fit request."""

    target: TargetMatch
    config: T13ModelConfig = field(default_factory=T13ModelConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetMatch):
            raise T13ValidationError("T13 plans require a TargetMatch.")
        if not isinstance(self.config, T13ModelConfig):
            raise T13ValidationError("T13 plans require a T13ModelConfig.")

    @property
    def run_key(self) -> str:
        return f"t13-joint-corners:{self.target.matchweek_id}:{self.target.fixture_id}"

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
class T13PublishedArtifacts:
    """The content-addressed T13 fit and distribution artifacts."""

    fit: CornerModelFit
    distribution: CornerDistribution
    fit_artifact_digest: str
    distribution_artifact_digest: str


class T13ArtifactRecorder:
    """Publish and reload immutable T13 JSON artifacts through the local store."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T13 artifact publication requires a writable store.")
        self.store = store
        self.artifacts = ArtifactStore(store)

    def publish_fit(self, fit: CornerModelFit) -> CornerModelFit:
        if not isinstance(fit, CornerModelFit):
            raise T13ValidationError("T13 fit artifact publication requires a model fit.")
        record = self.artifacts.publish_artifact(fit.to_bytes(), T13_MEDIA_TYPE)
        return fit.with_artifact(record.digest)

    def publish_distribution(self, distribution: CornerDistribution) -> CornerDistribution:
        if not isinstance(distribution, CornerDistribution):
            raise T13ValidationError(
                "T13 distribution artifact publication requires a model distribution."
            )
        record = self.artifacts.publish_artifact(
            distribution.to_bytes(), T13_DISTRIBUTION_MEDIA_TYPE
        )
        return distribution.with_artifact(record.digest)

    def publish(
        self,
        fit: CornerModelFit,
        distribution: CornerDistribution | None = None,
    ) -> T13PublishedArtifacts:
        published_fit = self.publish_fit(fit)
        selected_distribution = distribution or fit.predict()
        if selected_distribution.model_digest != fit.digest:
            raise T13IntegrityError(
                "A T13 distribution must reference the exact fitted model digest."
            )
        published_distribution = self.publish_distribution(selected_distribution)
        return T13PublishedArtifacts(
            fit=published_fit,
            distribution=published_distribution,
            fit_artifact_digest=cast(str, published_fit.artifact_digest),
            distribution_artifact_digest=cast(str, published_distribution.artifact_digest),
        )

    def load_fit(self, digest: str) -> CornerModelFit:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T13_MEDIA_TYPE:
            raise T13IntegrityError("The artifact is not a T13 model fit.")
        fit = CornerModelFit.from_dict(
            cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        )
        return fit if fit.artifact_digest == digest else fit.with_artifact(digest)

    def load_distribution(self, digest: str) -> CornerDistribution:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T13_DISTRIBUTION_MEDIA_TYPE:
            raise T13IntegrityError("The artifact is not a T13 settlement distribution.")
        distribution = CornerDistribution.from_dict(
            cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        )
        return (
            distribution
            if distribution.artifact_digest == digest
            else distribution.with_artifact(digest)
        )


__all__ = [
    "CORNER_PREFERENCES",
    "CORNER_PREFERENCE_IDS",
    "JOINT_CORNER_MODEL_VERSION",
    "JOINT_CORNER_PREFERENCES",
    "JOINT_CORNER_PREFERENCE_IDS",
    "MODEL_MEDIA_TYPE",
    "MODEL_UNAVAILABLE",
    "T13_ALGORITHM_VERSION",
    "T13_DISTRIBUTION_MEDIA_TYPE",
    "T13_MEDIA_TYPE",
    "T13_MODEL_NAME",
    "T13_MODEL_VERSION",
    "CornerDistribution",
    "CornerHistory",
    "CornerHistoryRow",
    "CornerModel",
    "CornerModelFit",
    "JointCornerDistribution",
    "JointCornerHistory",
    "JointCornerModel",
    "JointCornerModelFit",
    "ModelStatus",
    "SettlementProbabilities",
    "T13ArtifactRecorder",
    "T13CornerModelFit",
    "T13Error",
    "T13IntegrityError",
    "T13ModelConfig",
    "T13ModelService",
    "T13Plan",
    "T13PublishedArtifacts",
    "T13Runner",
    "T13ValidationError",
    "derive_corner_history",
    "derive_corner_history_rows",
    "derive_joint_corner_history",
    "fit_corner_model",
    "fit_corners",
    "fit_joint_corner_model",
    "fit_joint_corner_model_from_store",
    "fit_joint_corners",
    "fit_t13",
    "predict_corner_distribution",
    "predict_corners",
    "predict_joint_corner_distribution",
    "predict_joint_corners",
]

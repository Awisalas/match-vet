"""T12 first-half and second-half goal Settlement Distributions.

T12 fits two independent, partially pooled phase models.  The first-half
model consumes reliable half-time goal pairs.  The second-half model consumes
the same reliable half-time pair plus a reliable full-time pair and derives
the second-half goals by subtraction of scores, never by subtracting
probabilities or applying a fixed phase split.

The models are deliberately limited to the T12 probability seam.  They do
not calibrate probabilities, rank preferences, use odds or xG, or produce
recommendations and reports.
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
from matchvet.t09 import FrozenEvidenceState, HistoricalMatch, TargetMatch
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG
from matchvet.t11 import (
    MODEL_UNAVAILABLE,
    FullTimeGoalModelFit,
    ModelStatus,
    SettlementProbabilities,
    fit_full_time_goal_model,
)

T12_MODEL_NAME = "matchvet-half-goal-model"
T12_MODEL_VERSION = "t12-half-goals-v2"
FIRST_HALF_GOAL_MODEL_VERSION = "t12-first-half-goals-v2"
SECOND_HALF_GOAL_MODEL_VERSION = "t12-second-half-goals-v2"
T12_ALGORITHM_VERSION = "hierarchical-phase-poisson-map-v2"
T12_FEATURE_VERSION = "t12-frozen-t09-features-v2"
T12_MEDIA_TYPE = "application/vnd.matchvet.t12-half-goal-model+json"
T12_DISTRIBUTION_MEDIA_TYPE = "application/vnd.matchvet.t12-half-settlement-distribution+json"
MODEL_MEDIA_TYPE = T12_MEDIA_TYPE

FIRST_HALF_OVER_1_5 = "first_half_over_1_5"
SECOND_HALF_OVER_1_5 = "second_half_over_1_5"
HALF_GOAL_PREFERENCE_IDS = (FIRST_HALF_OVER_1_5, SECOND_HALF_OVER_1_5)


class T12Error(Exception):
    """Base class for T12 fitting, prediction, and artifact errors."""


class T12ValidationError(T12Error, ValueError):
    """A T12 input is malformed or outside the frozen-input contract."""


class T12IntegrityError(T12Error):
    """An immutable T12 identity or artifact was reused with different content."""


class HalfPhase(StrEnum):
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"

    @property
    def preference_id(self) -> str:
        return FIRST_HALF_OVER_1_5 if self is HalfPhase.FIRST_HALF else SECOND_HALF_OVER_1_5

    @property
    def model_version(self) -> str:
        return (
            FIRST_HALF_GOAL_MODEL_VERSION
            if self is HalfPhase.FIRST_HALF
            else SECOND_HALF_GOAL_MODEL_VERSION
        )


def _phase(value: HalfPhase | str) -> HalfPhase:
    if isinstance(value, HalfPhase):
        return value
    token = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "FIRST": HalfPhase.FIRST_HALF,
        "FIRST_HALF": HalfPhase.FIRST_HALF,
        "FIRSTHALF": HalfPhase.FIRST_HALF,
        "SECOND": HalfPhase.SECOND_HALF,
        "SECOND_HALF": HalfPhase.SECOND_HALF,
        "SECONDHALF": HalfPhase.SECOND_HALF,
    }
    try:
        return aliases[token]
    except KeyError as error:
        raise T12ValidationError(f"Unknown half phase {value!r}.") from error


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
    if isinstance(value, float) and not math.isfinite(value):
        raise T12ValidationError("T12 JSON values must be finite.")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T12ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise T12ValidationError(f"{label} must be a finite number.")
    selected = float(value)
    if not math.isfinite(selected):
        raise T12ValidationError(f"{label} must be a finite number.")
    return selected


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise T12ValidationError(f"{label} must be an object.")
    return cast(Mapping[str, object], value)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise T12ValidationError("T12 timestamps must be ISO-8601 values.") from error
    if parsed.tzinfo is None:
        raise T12ValidationError("T12 timestamps must include a UTC offset.")
    return parsed.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _strings(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({_text(item, "T12 identity") for item in values}))


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class HalfGoalHistory:
    """One reliable, phase-specific goal observation derived from a match."""

    phase: HalfPhase
    fixture_id: str
    home_team_id: str
    away_team_id: str
    kickoff_utc: str
    home_goals: int
    away_goals: int
    competition_key: str | None = None
    regime_id: str | None = None
    source_digest: str | None = None
    source_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", _phase(self.phase))
        for label, value in (
            ("half history fixture ID", self.fixture_id),
            ("half history home team ID", self.home_team_id),
            ("half history away team ID", self.away_team_id),
        ):
            _text(value, label)
        if self.home_team_id == self.away_team_id:
            raise T12ValidationError("Half history requires two different teams.")
        object.__setattr__(self, "kickoff_utc", _canonical_utc(self.kickoff_utc))
        goal_values: tuple[tuple[str, object], ...] = (
            ("home half goals", self.home_goals),
            ("away half goals", self.away_goals),
        )
        for goal_label, goal_value in goal_values:
            if isinstance(goal_value, bool) or not isinstance(goal_value, int) or goal_value < 0:
                raise T12ValidationError(f"{goal_label} must be a non-negative integer.")
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
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    @property
    def home_half_goals(self) -> int:
        return self.home_goals

    @property
    def away_half_goals(self) -> int:
        return self.away_goals

    def to_dict(self) -> dict[str, object]:
        return {
            "away_goals": self.away_goals,
            "away_team_id": self.away_team_id,
            "competition_key": self.competition_key,
            "fixture_id": self.fixture_id,
            "home_goals": self.home_goals,
            "home_team_id": self.home_team_id,
            "kickoff_utc": self.kickoff_utc,
            "phase": self.phase.value,
            "regime_id": self.regime_id,
            "source_digest": self.source_digest,
            "source_input_ids": self.source_input_ids,
        }


HalfGoalHistoryRow = HalfGoalHistory


def _goal_metric_observed(match: HistoricalMatch, metric: str) -> bool:
    return match.metric_state(metric) is EvidenceState.OBSERVED


def _non_negative_goal_pair(
    match: HistoricalMatch, home_metric: str, away_metric: str
) -> tuple[int, int] | None:
    if not _goal_metric_observed(match, home_metric) or not _goal_metric_observed(
        match, away_metric
    ):
        return None
    home_value = match.metrics.get(home_metric)
    away_value = match.metrics.get(away_metric)
    if (
        isinstance(home_value, bool)
        or not isinstance(home_value, int)
        or home_value < 0
        or isinstance(away_value, bool)
        or not isinstance(away_value, int)
        or away_value < 0
    ):
        return None
    return home_value, away_value


def _reliable_full_time_pair(match: HistoricalMatch) -> tuple[int, int] | None:
    return _non_negative_goal_pair(
        match,
        "full_time_home_goals",
        "full_time_away_goals",
    )


def _reliable_half_time_pair(match: HistoricalMatch) -> tuple[int, int] | None:
    return _non_negative_goal_pair(
        match,
        "half_time_home_goals",
        "half_time_away_goals",
    )


def derive_first_half_goals(match: HistoricalMatch) -> tuple[int, int] | None:
    """Return reliable HT goals, or ``None`` without inventing a value."""
    half_time = _reliable_half_time_pair(match)
    if half_time is None:
        return None
    full_time = _reliable_full_time_pair(match)
    if full_time is not None and (half_time[0] > full_time[0] or half_time[1] > full_time[1]):
        return None
    return half_time


def derive_second_half_goals(match: HistoricalMatch) -> tuple[int, int] | None:
    """Derive SH goals only from an observed and consistent FT/HT score pair."""
    full_time = _reliable_full_time_pair(match)
    half_time = _reliable_half_time_pair(match)
    if full_time is None or half_time is None:
        return None
    if half_time[0] > full_time[0] or half_time[1] > full_time[1]:
        return None
    return full_time[0] - half_time[0], full_time[1] - half_time[1]


def _history_row(
    match: HistoricalMatch,
    phase: HalfPhase,
    goals: tuple[int, int],
) -> HalfGoalHistory:
    return HalfGoalHistory(
        phase=phase,
        fixture_id=match.fixture_id,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        kickoff_utc=match.kickoff_utc,
        home_goals=goals[0],
        away_goals=goals[1],
        competition_key=match.competition_key,
        regime_id=match.regime_id,
        source_digest=(
            match.source_digest
            if isinstance(match.source_digest, str) and match.source_digest
            else _digest(match.to_dict())
        ),
        source_input_ids=tuple(
            sorted(
                {
                    *match.source_assertion_ids,
                    *match.metric_ids("half_time_home_goals"),
                    *match.metric_ids("half_time_away_goals"),
                    *(
                        match.metric_ids("full_time_home_goals")
                        if phase is HalfPhase.SECOND_HALF
                        else ()
                    ),
                    *(
                        match.metric_ids("full_time_away_goals")
                        if phase is HalfPhase.SECOND_HALF
                        else ()
                    ),
                }
            )
        ),
    )


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
            raise T12ValidationError("T12 history must contain HistoricalMatch records.")
    return tuple(selected)


def derive_half_goal_history(
    history: Iterable[HistoricalMatch | Mapping[str, object]],
    phase: HalfPhase | str,
) -> tuple[HalfGoalHistory, ...]:
    """Derive reliable observations for one half in fixture-ID order."""
    selected_phase = _phase(phase)
    records = _coerce_history(history)
    by_fixture: dict[str, HalfGoalHistory] = {}
    for match in records:
        goals = (
            derive_first_half_goals(match)
            if selected_phase is HalfPhase.FIRST_HALF
            else derive_second_half_goals(match)
        )
        if goals is None:
            continue
        row = _history_row(match, selected_phase, goals)
        previous = by_fixture.get(row.fixture_id)
        if previous is not None and previous.to_dict() != row.to_dict():
            raise T12IntegrityError(
                f"Half history fixture {row.fixture_id} was supplied with conflicting content."
            )
        by_fixture[row.fixture_id] = row
    return tuple(by_fixture[key] for key in sorted(by_fixture))


def derive_first_half_history(
    history: Iterable[HistoricalMatch | Mapping[str, object]],
) -> tuple[HalfGoalHistory, ...]:
    return derive_half_goal_history(history, HalfPhase.FIRST_HALF)


def derive_second_half_history(
    history: Iterable[HistoricalMatch | Mapping[str, object]],
) -> tuple[HalfGoalHistory, ...]:
    return derive_half_goal_history(history, HalfPhase.SECOND_HALF)


derive_first_half_goals_history = derive_first_half_history
derive_second_half_goals_history = derive_second_half_history


@dataclass(frozen=True)
class T12ModelConfig:
    """Versioned numerical, feature, and pooling controls for T12."""

    name: str = T12_MODEL_NAME
    version: str = T12_MODEL_VERSION
    algorithm_version: str = T12_ALGORITHM_VERSION
    feature_version: str = T12_FEATURE_VERSION
    recency_half_life_days: float = 180.0
    regime_match_weight: float = 1.0
    regime_mismatch_weight: float = 0.35
    unknown_regime_weight: float = 0.75
    minimum_history_matches: int = 3
    minimum_effective_history_matches: float = 3.0
    minimum_shared_team_matches: int = 3
    maximum_expected_goals: float = 6.0
    maximum_score_goals: int = 32
    tail_tolerance: float = 1e-10
    team_prior_scale: float = 0.55
    league_season_prior_scale: float = 0.4
    home_advantage_prior_scale: float = 0.6
    full_time_strength_scale: float = 0.35
    target_feature_scale: float = 0.05
    schedule_feature_scale: float = 0.02
    regime_feature_scale: float = 0.05
    regime_prior_scale: float = 0.3
    feature_coefficient_prior_scale: float = 1.0
    optimizer_max_iterations: int = 500
    optimizer_ftol: float = 1e-11

    def __post_init__(self) -> None:
        for label, value in (
            ("model name", self.name),
            ("model version", self.version),
            ("algorithm version", self.algorithm_version),
            ("feature version", self.feature_version),
        ):
            _text(value, f"T12 {label}")
        numeric_values: tuple[tuple[str, float], ...] = (
            ("recency half-life", self.recency_half_life_days),
            ("regime match weight", self.regime_match_weight),
            ("regime mismatch weight", self.regime_mismatch_weight),
            ("unknown regime weight", self.unknown_regime_weight),
            ("minimum effective history", self.minimum_effective_history_matches),
            ("maximum expected goals", self.maximum_expected_goals),
            ("tail tolerance", self.tail_tolerance),
            ("team prior scale", self.team_prior_scale),
            ("league-season prior scale", self.league_season_prior_scale),
            ("home advantage prior scale", self.home_advantage_prior_scale),
            ("full-time strength scale", self.full_time_strength_scale),
            ("target feature scale", self.target_feature_scale),
            ("schedule feature scale", self.schedule_feature_scale),
            ("regime feature scale", self.regime_feature_scale),
            ("regime prior scale", self.regime_prior_scale),
            ("feature coefficient prior scale", self.feature_coefficient_prior_scale),
            ("optimizer ftol", self.optimizer_ftol),
        )
        for numeric_label, numeric_value in numeric_values:
            if not math.isfinite(float(numeric_value)) or float(numeric_value) <= 0:
                raise T12ValidationError(f"T12 {numeric_label} must be positive and finite.")
        if self.regime_match_weight > 1 or self.regime_mismatch_weight > 1:
            raise T12ValidationError("T12 regime weights cannot exceed one.")
        if self.minimum_history_matches < 1 or self.minimum_shared_team_matches < 1:
            raise T12ValidationError("T12 history minimums must be positive.")
        if self.maximum_score_goals < 2:
            raise T12ValidationError("T12 score grids must include goals zero through two.")
        if self.tail_tolerance >= 1:
            raise T12ValidationError("T12 tail tolerance must be below one.")
        if self.optimizer_max_iterations < 1:
            raise T12ValidationError("T12 optimizer iterations must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "feature_version": self.feature_version,
            "feature_coefficient_prior_scale": self.feature_coefficient_prior_scale,
            "full_time_strength_scale": self.full_time_strength_scale,
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
            "regime_feature_scale": self.regime_feature_scale,
            "regime_match_weight": self.regime_match_weight,
            "regime_mismatch_weight": self.regime_mismatch_weight,
            "regime_prior_scale": self.regime_prior_scale,
            "schedule_feature_scale": self.schedule_feature_scale,
            "tail_tolerance": self.tail_tolerance,
            "target_feature_scale": self.target_feature_scale,
            "team_prior_scale": self.team_prior_scale,
            "unknown_regime_weight": self.unknown_regime_weight,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class _PhaseTrainingRow:
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
    def weight(self) -> float:
        return self.recency_weight * self.regime_weight


class _T12FitFailure(T12Error):
    """Internal numerical failure converted to MODEL_UNAVAILABLE."""


_T12_FEATURE_NAMES = ("E-TACTICAL-REGIME",)
_PHASE_METRICS = {
    HalfPhase.FIRST_HALF: (
        "half_time_home_goals",
        "half_time_away_goals",
    ),
    HalfPhase.SECOND_HALF: (
        "full_time_home_goals",
        "full_time_away_goals",
        "half_time_home_goals",
        "half_time_away_goals",
    ),
}


def _feature_map(state: FrozenEvidenceState) -> Mapping[str, object]:
    return {feature.name: feature for feature in state.derived_features}


def _feature_value(state: FrozenEvidenceState, name: str) -> object | None:
    feature = _feature_map(state).get(name)
    if feature is None:
        return None
    selected = getattr(feature, "state", None)
    if selected is not EvidenceState.OBSERVED and str(selected) != EvidenceState.OBSERVED.value:
        return None
    return getattr(feature, "value", None)


def _feature_lineage(
    state: FrozenEvidenceState, names: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected_names = set(names)
    input_ids: set[str] = set()
    input_digests: set[str] = set()
    for feature in state.derived_features:
        if feature.name not in selected_names:
            continue
        selected = getattr(feature, "state", None)
        if selected is not EvidenceState.OBSERVED and str(selected) != EvidenceState.OBSERVED.value:
            continue
        input_ids.update(feature.input_ids)
        input_digests.update(feature.input_digests)
        input_ids.add(feature.feature_id)
        input_digests.add(feature.digest)
    return tuple(sorted(input_ids)), tuple(sorted(input_digests))


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


def _cutoff_valid_history_match(match: HistoricalMatch, cutoff: datetime) -> bool:
    if match.fixture_status.upper() not in {"COMPLETED", "FINAL", "FINISHED"}:
        return False
    if match.final_state is not EvidenceState.OBSERVED:
        return False
    timestamps = (match.kickoff_utc, match.observed_at_utc, match.published_at_utc)
    return not any(value is not None and _parse_utc(value) > cutoff for value in timestamps)


def _unresolved_phase_conflict_ids(state: FrozenEvidenceState, phase: HalfPhase) -> tuple[str, ...]:
    expected_ids = set(_state_history_ids(state))
    metric_names = set(_PHASE_METRICS[phase])
    return tuple(
        sorted(
            conflict.conflict_id
            for conflict in state.conflicts
            if conflict.material
            and conflict.status == "UNRESOLVED"
            and conflict.evidence_type == "MATCH_STATISTIC"
            and conflict.subject_id in expected_ids
            and conflict.predicate in metric_names
        )
    )


def _frozen_history_input_mismatches(
    history: Sequence[HistoricalMatch], state: FrozenEvidenceState, phase: HalfPhase
) -> tuple[str, ...]:
    expected_ids = set(_state_history_ids(state))
    if not expected_ids:
        return ()
    metric_names = set(_PHASE_METRICS[phase])
    selected_assertions: dict[tuple[str, str], set[str]] = {}
    for conflict in state.conflicts:
        if (
            not conflict.material
            or conflict.status != "RESOLVED"
            or conflict.evidence_type != "MATCH_STATISTIC"
            or conflict.subject_id not in expected_ids
            or conflict.predicate not in metric_names
        ):
            continue
        if conflict.selected_assertion_id is not None:
            selected_assertions.setdefault((conflict.subject_id, conflict.predicate), set()).add(
                conflict.selected_assertion_id
            )
    frozen: dict[str, dict[str, object]] = {}
    frozen_digests: dict[str, set[str]] = {}
    for fact in state.source_assertions:
        if (
            fact.evidence_type != "MATCH_STATISTIC"
            or fact.subject_id not in expected_ids
            or fact.predicate not in metric_names
        ):
            continue
        selected = selected_assertions.get((fact.subject_id, fact.predicate))
        if selected is not None and fact.fact_id not in selected:
            continue
        entry = frozen.setdefault(fact.subject_id, {})
        entry[fact.predicate] = fact.value
        if fact.source_digest is not None:
            frozen_digests.setdefault(fact.subject_id, set()).add(fact.source_digest)
    by_fixture = {match.fixture_id: match for match in history}
    mismatches: set[str] = set()
    for (subject_id, predicate), assertion_ids in selected_assertions.items():
        if len(assertion_ids) != 1 or not any(
            subject_id == fact.subject_id
            and predicate == fact.predicate
            and fact.fact_id in assertion_ids
            for fact in state.source_assertions
        ):
            mismatches.add(subject_id)
    for fixture_id, inputs in sorted(frozen.items()):
        match = by_fixture.get(fixture_id)
        if match is None:
            continue
        for metric in _PHASE_METRICS[phase]:
            if metric in inputs and match.metrics.get(metric) != inputs[metric]:
                mismatches.add(fixture_id)
                break
        source_digest = match.source_digest
        expected_digests = frozen_digests.get(fixture_id, set())
        if expected_digests and (
            len(expected_digests) != 1 or source_digest not in expected_digests
        ):
            mismatches.add(fixture_id)
    return tuple(sorted(mismatches))


def _league_season_key(competition_key: str, season: str) -> str:
    return f"{competition_key}:{season}"


def _training_rows(
    history: Sequence[HistoricalMatch],
    state: FrozenEvidenceState,
    phase: HalfPhase,
    config: T12ModelConfig,
) -> tuple[tuple[_PhaseTrainingRow, ...], tuple[HistoricalMatch, ...], Mapping[str, str]]:
    target = state.target
    cutoff = _parse_utc(target.cutoff_utc)
    expected_ids = set(_state_history_ids(state))
    by_fixture: dict[str, HistoricalMatch] = {}
    invalid: dict[str, str] = {}
    for match in history:
        if expected_ids and match.fixture_id not in expected_ids:
            continue
        if not _cutoff_valid_history_match(match, cutoff):
            invalid.setdefault(match.fixture_id, "NOT_CUTOFF_VALID")
            continue
        previous = by_fixture.get(match.fixture_id)
        if previous is not None and previous.to_dict() != match.to_dict():
            raise T12IntegrityError(
                f"Historical Match {match.fixture_id} was supplied with conflicting content."
            )
        by_fixture[match.fixture_id] = match
    ordered = tuple(sorted(by_fixture.values(), key=lambda item: item.fixture_id))
    rows: list[_PhaseTrainingRow] = []
    target_regime = _target_regime(state)
    for match in ordered:
        goals = (
            derive_first_half_goals(match)
            if phase is HalfPhase.FIRST_HALF
            else derive_second_half_goals(match)
        )
        if goals is None:
            invalid.setdefault(
                match.fixture_id,
                "RELIABLE_HALF_TIME_AND_FULL_TIME_SCORES_REQUIRED"
                if phase is HalfPhase.SECOND_HALF
                else "RELIABLE_HALF_TIME_SCORE_REQUIRED",
            )
            continue
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
            _PhaseTrainingRow(
                fixture_id=match.fixture_id,
                home_team_id=match.home_team_id,
                away_team_id=match.away_team_id,
                league_key=_league_season_key(
                    match.competition_key or target.competition_key,
                    target.season,
                ),
                kickoff_utc=match.kickoff_utc,
                home_goals=goals[0],
                away_goals=goals[1],
                recency_weight=recency_weight,
                regime_weight=regime_weight,
                regime_id=match.regime_id,
            )
        )
    return tuple(rows), ordered, MappingProxyType(dict(sorted(invalid.items())))


def _minimum_evidence_reason(
    rows: Sequence[_PhaseTrainingRow], target: TargetMatch, config: T12ModelConfig
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


def _full_time_parameter_map(fit: FullTimeGoalModelFit | None, key: str) -> Mapping[str, object]:
    if fit is None or not fit.is_available:
        return {}
    value = fit.parameters.get(key)
    return value if isinstance(value, Mapping) else {}


def _full_time_strength(
    fit: FullTimeGoalModelFit | None, team_ids: Sequence[str], config: T12ModelConfig
) -> tuple[Mapping[str, float], Mapping[str, float], str]:
    attacks = _full_time_parameter_map(fit, "team_attack")
    defenses = _full_time_parameter_map(fit, "team_defense")
    attack_values = {
        team_id: config.full_time_strength_scale * (_number(attacks.get(team_id)) or 0.0)
        for team_id in team_ids
    }
    defense_values = {
        team_id: config.full_time_strength_scale * (_number(defenses.get(team_id)) or 0.0)
        for team_id in team_ids
    }
    source = (
        "T11_FULL_TIME_GOAL_CAPABILITY"
        if fit is not None and fit.is_available
        else "SHARED_LEAGUE_PRIOR"
    )
    return attack_values, defense_values, source


def _feature_offsets(
    state: FrozenEvidenceState | None,
    phase: HalfPhase,
    *,
    feature_coefficients: Mapping[str, object] | None = None,
    model_covariates: Mapping[str, object] | None = None,
    stored: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    if state is None:
        if stored is not None:
            return stored
        return {"home": 0.0, "away": 0.0, "components": {}, "phase": phase.value}

    regime_id = _target_regime(state)
    coefficients = feature_coefficients or {}
    fitted = model_covariates or {}
    fitted_components: dict[str, float] = {"home": 0.0, "away": 0.0}
    for side in ("home", "away"):
        side_covariates = _mapping_or_empty(fitted.get(side))
        for name in ("opponent", "recency", "venue", "schedule", "regime"):
            covariate = _number(side_covariates.get(name))
            coefficient = _number(coefficients.get(name))
            if covariate is not None and coefficient is not None:
                fitted_components[side] += coefficient * covariate

    components = {"fitted": fitted_components}
    return {
        "away": fitted_components["away"],
        "components": components,
        "feature_names": _T12_FEATURE_NAMES,
        "fitted_covariates": fitted,
        "home": fitted_components["home"],
        "phase": phase.value,
        "regime_id": regime_id,
    }


def _numeric_modules() -> tuple[Any, Callable[..., Any], Callable[..., Any]]:
    try:
        import numpy as np
        from scipy.optimize import minimize  # type: ignore[import-untyped]
        from scipy.special import gammaln  # type: ignore[import-untyped]
    except ImportError as error:
        raise _T12FitFailure(
            "T12 requires the native NumPy/SciPy runtime for deterministic MAP fitting."
        ) from error
    return np, minimize, gammaln


def _schedule_covariates(
    rows: Sequence[_PhaseTrainingRow],
    *,
    schedule_history: Sequence[HistoricalMatch] = (),
    target: TargetMatch | None = None,
) -> Mapping[str, tuple[float, float]]:
    """Build cutoff-safe rest and congestion covariates from prior kickoffs.

    Schedule facts are independent of phase-score availability, so every
    cutoff-valid historical fixture contributes a kickoff to this context.
    """
    events: dict[str, tuple[str, str, str]] = {
        match.fixture_id: (match.home_team_id, match.away_team_id, match.kickoff_utc)
        for match in schedule_history
    }
    for row in rows:
        events.setdefault(
            row.fixture_id,
            (row.home_team_id, row.away_team_id, row.kickoff_utc),
        )
    if target is not None:
        events[target.fixture_id] = (
            target.home_team_id,
            target.away_team_id,
            target.kickoff_utc,
        )
    previous_by_team: dict[str, list[datetime]] = {}
    covariates: dict[str, tuple[float, float]] = {}
    chronological = sorted(events.items(), key=lambda item: (item[1][2], item[0]))
    for fixture_id, (home_team_id, away_team_id, kickoff_utc) in chronological:
        kickoff = _parse_utc(kickoff_utc)
        values: list[float] = []
        for team_id in (home_team_id, away_team_id):
            previous = previous_by_team.setdefault(team_id, [])
            rest_days = (kickoff - previous[-1]).total_seconds() / 86_400.0 if previous else 7.0
            congestion = sum(
                1
                for prior_kickoff in previous
                if (kickoff - prior_kickoff).total_seconds() <= 21 * 86_400
            )
            values.append(
                _bounded((rest_days - 7.0) / 7.0, -1.0, 1.0)
                - 0.25 * _bounded(congestion / 5.0, 0.0, 1.0)
            )
            previous.append(kickoff)
        covariates[fixture_id] = (values[0], values[1])
    return covariates


def _fit_numerical_parameters(
    rows: Sequence[_PhaseTrainingRow],
    schedule_history: Sequence[HistoricalMatch],
    target: TargetMatch,
    config: T12ModelConfig,
    full_time_fit: FullTimeGoalModelFit | None,
    target_regime: str | None,
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
    home_index = league_count
    attack_start = league_count + 1
    defense_start = attack_start + team_count
    coefficient_names = ("opponent", "recency", "venue", "schedule", "regime")
    coefficient_start = defense_start + team_count

    home_goals = np.asarray([row.home_goals for row in rows], dtype=np.float64)
    away_goals = np.asarray([row.away_goals for row in rows], dtype=np.float64)
    home_indices = np.asarray([team_index[row.home_team_id] for row in rows], dtype=np.int64)
    away_indices = np.asarray([team_index[row.away_team_id] for row in rows], dtype=np.int64)
    league_indices = np.asarray([league_index[row.league_key] for row in rows], dtype=np.int64)
    weights = np.asarray([row.weight for row in rows], dtype=np.float64)
    if not np.all(np.isfinite(weights)) or float(np.sum(weights)) <= 0:
        raise _T12FitFailure("T12 training weights are not finite and positive.")

    schedule = _schedule_covariates(rows, schedule_history=schedule_history, target=target)
    schedule_home = np.asarray([schedule[row.fixture_id][0] for row in rows], dtype=np.float64)
    schedule_away = np.asarray([schedule[row.fixture_id][1] for row in rows], dtype=np.float64)
    cutoff = _parse_utc(target.cutoff_utc)
    recency = np.asarray(
        [
            -max(
                0.0,
                (cutoff - _parse_utc(row.kickoff_utc)).total_seconds() / 86_400.0,
            )
            / config.recency_half_life_days
            for row in rows
        ],
        dtype=np.float64,
    )
    full_time_defense = _full_time_parameter_map(full_time_fit, "team_defense")
    opponent_home = np.asarray(
        [-(_number(full_time_defense.get(row.away_team_id)) or 0.0) for row in rows],
        dtype=np.float64,
    )
    opponent_away = np.asarray(
        [-(_number(full_time_defense.get(row.home_team_id)) or 0.0) for row in rows],
        dtype=np.float64,
    )
    regime_covariate = np.asarray(
        [
            0.0
            if target_regime is None or row.regime_id is None
            else 1.0
            if row.regime_id == target_regime
            else -1.0
            for row in rows
        ],
        dtype=np.float64,
    )
    target_schedule_home, target_schedule_away = schedule.get(target.fixture_id, (0.0, 0.0))
    target_model_covariates: Mapping[str, Mapping[str, float]] = {
        "home": {
            "opponent": -(_number(full_time_defense.get(target.away_team_id)) or 0.0),
            "recency": 0.0,
            "regime": 1.0 if target_regime is not None else 0.0,
            "schedule": target_schedule_home,
            "venue": 1.0,
        },
        "away": {
            "opponent": -(_number(full_time_defense.get(target.home_team_id)) or 0.0),
            "recency": 0.0,
            "regime": 1.0 if target_regime is not None else 0.0,
            "schedule": target_schedule_away,
            "venue": -1.0,
        },
    }

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
    attack_centers, defense_centers, strength_source = _full_time_strength(
        full_time_fit, team_ids, config
    )
    attack_center_values = np.asarray(
        [attack_centers[team_id] for team_id in team_ids], dtype=np.float64
    )
    defense_center_values = np.asarray(
        [defense_centers[team_id] for team_id in team_ids], dtype=np.float64
    )
    initial = np.concatenate(
        (
            league_initial,
            np.asarray([home_initial], dtype=np.float64),
            attack_center_values,
            defense_center_values,
            np.zeros(len(coefficient_names), dtype=np.float64),
        )
    )

    def unpack(vector: Any) -> tuple[Any, ...]:
        league = vector[:league_count]
        home_advantage = vector[home_index]
        attack = vector[attack_start:defense_start]
        defense = vector[defense_start:coefficient_start]
        coefficients = vector[coefficient_start:]
        attack_centered = attack - np.mean(attack)
        defense_centered = defense - np.mean(defense)
        eta_home_raw = (
            league[league_indices]
            + home_advantage
            + attack_centered[home_indices]
            - defense_centered[away_indices]
            + coefficients[0] * opponent_home
            + coefficients[1] * recency
            + coefficients[2]
            + coefficients[3] * schedule_home
            + coefficients[4] * regime_covariate
        )
        eta_away_raw = (
            league[league_indices]
            + attack_centered[away_indices]
            - defense_centered[home_indices]
            + coefficients[0] * opponent_away
            + coefficients[1] * recency
            - coefficients[2]
            + coefficients[3] * schedule_away
            + coefficients[4] * regime_covariate
        )
        eta_home = np.clip(eta_home_raw, log_min, log_max)
        eta_away = np.clip(eta_away_raw, log_min, log_max)
        lambda_home = np.exp(eta_home)
        lambda_away = np.exp(eta_away)
        return (
            league,
            home_advantage,
            attack,
            defense,
            coefficients,
            eta_home_raw,
            eta_away_raw,
            lambda_home,
            lambda_away,
        )

    def value_and_gradient(vector: Any) -> tuple[float, Any]:
        (
            league,
            home_advantage,
            attack,
            defense,
            coefficients,
            eta_home_raw,
            eta_away_raw,
            lambda_home,
            lambda_away,
        ) = unpack(vector)
        del league, home_advantage, attack, defense, coefficients
        eta_home = np.clip(eta_home_raw, log_min, log_max)
        eta_away = np.clip(eta_away_raw, log_min, log_max)
        g_home_eta = home_goals - lambda_home
        g_away_eta = away_goals - lambda_away
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
        attack_direct = np.bincount(
            home_indices, weights=weighted_home, minlength=team_count
        ) + np.bincount(away_indices, weights=weighted_away, minlength=team_count)
        defense_direct = np.bincount(
            away_indices, weights=-weighted_home, minlength=team_count
        ) + np.bincount(home_indices, weights=-weighted_away, minlength=team_count)
        gradient[attack_start:defense_start] = attack_direct - np.mean(attack_direct)
        gradient[defense_start:coefficient_start] = defense_direct - np.mean(defense_direct)
        gradient[coefficient_start] = float(
            np.sum(weighted_home * opponent_home + weighted_away * opponent_away)
        )
        gradient[coefficient_start + 1] = float(np.sum((weighted_home + weighted_away) * recency))
        gradient[coefficient_start + 2] = float(np.sum(weighted_home - weighted_away))
        gradient[coefficient_start + 3] = float(
            np.sum(weighted_home * schedule_home + weighted_away * schedule_away)
        )
        gradient[coefficient_start + 4] = float(
            np.sum((weighted_home + weighted_away) * regime_covariate)
        )

        prior = 0.0
        prior_gradient = np.zeros_like(vector, dtype=np.float64)
        league_prior = math.log(baseline_goal_rate)
        league_delta = vector[:league_count] - league_prior
        prior += 0.5 * float(np.sum(league_delta**2)) / config.league_season_prior_scale**2
        prior_gradient[:league_count] += league_delta / config.league_season_prior_scale**2
        home_delta = float(vector[home_index] - home_initial)
        prior += 0.5 * home_delta**2 / config.home_advantage_prior_scale**2
        prior_gradient[home_index] += home_delta / config.home_advantage_prior_scale**2
        attack_delta = vector[attack_start:defense_start] - attack_center_values
        defense_delta = vector[defense_start:coefficient_start] - defense_center_values
        prior += 0.5 * float(np.sum(attack_delta**2)) / config.team_prior_scale**2
        prior += 0.5 * float(np.sum(defense_delta**2)) / config.team_prior_scale**2
        prior_gradient[attack_start:defense_start] += attack_delta / config.team_prior_scale**2
        prior_gradient[defense_start:coefficient_start] += (
            defense_delta / config.team_prior_scale**2
        )
        coefficient_delta = vector[coefficient_start:]
        prior += (
            0.5 * float(np.sum(coefficient_delta**2)) / config.feature_coefficient_prior_scale**2
        )
        prior_gradient[coefficient_start:] += (
            coefficient_delta / config.feature_coefficient_prior_scale**2
        )
        objective = float(
            -np.sum(
                weights
                * (
                    home_goals * eta_home
                    - lambda_home
                    - gammaln(home_goals + 1.0)
                    + away_goals * eta_away
                    - lambda_away
                    - gammaln(away_goals + 1.0)
                )
            )
            + prior
        )
        full_gradient = -gradient + prior_gradient
        if not math.isfinite(objective) or not np.all(np.isfinite(full_gradient)):
            return math.inf, np.full_like(vector, math.nan, dtype=np.float64)
        return objective, full_gradient

    bounds: list[tuple[float, float]] = [(log_min, log_max)] * league_count
    bounds.append((-2.5, 2.5))
    bounds.extend([(-4.0, 4.0)] * (team_count * 2))
    bounds.extend([(-2.0, 2.0)] * len(coefficient_names))
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
        raise _T12FitFailure(f"T12 optimizer failed: {result.message}")
    league = vector[:league_count]
    attack = vector[attack_start:defense_start].copy()
    defense = vector[defense_start:coefficient_start].copy()
    attack -= np.mean(attack)
    defense -= np.mean(defense)
    parameters: Mapping[str, object] = {
        "baseline_goal_rate": float(baseline_goal_rate),
        "full_time_strength_source": strength_source,
        "league_season_intercepts": {
            key: float(league[index]) for key, index in sorted(league_index.items())
        },
        "team_attack": {key: float(attack[index]) for key, index in sorted(team_index.items())},
        "team_defense": {key: float(defense[index]) for key, index in sorted(team_index.items())},
        "home_advantage": float(vector[home_index]),
        "feature_coefficients": {
            name: float(vector[coefficient_start + index])
            for index, name in enumerate(coefficient_names)
        },
        "target_model_covariates": target_model_covariates,
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
        "shared_strength_source": strength_source,
        "feature_coefficients": {
            name: float(vector[coefficient_start + index])
            for index, name in enumerate(coefficient_names)
        },
    }
    return parameters, diagnostics


def _regime_effects(
    rows: Sequence[_PhaseTrainingRow], baseline_goal_rate: float, config: T12ModelConfig
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
        effects[regime_id] = _bounded(
            raw_effect / (1.0 + config.regime_prior_scale),
            -2.0,
            2.0,
        )
    return effects


def _uncertainty_metadata(
    rows: Sequence[_PhaseTrainingRow], target: TargetMatch, config: T12ModelConfig, phase: HalfPhase
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
        "phase": phase.value,
        "teams": teams,
        "effective_training_matches": effective_total,
        "prediction_uncertainty_multiplier": max(multipliers, default=1.0),
        "uncertainty_method": "sparse_team_support_widens_metadata_v1",
    }


def _fit_input_metadata(
    history: Sequence[HistoricalMatch],
    state: FrozenEvidenceState,
    phase: HalfPhase,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    fixture_ids = tuple(sorted(match.fixture_id for match in history))
    training_ids: set[str] = set(fixture_ids)
    training_digests: set[str] = set()
    for match in history:
        training_ids.update(match.source_assertion_ids)
        for metric in _PHASE_METRICS[phase]:
            training_ids.update(match.metric_ids(metric))
        training_digests.add(_history_digest(match))
    fixture_ids_set = set(fixture_ids)
    training_digests.update(
        fact.source_digest
        for fact in state.source_assertions
        if fact.subject_id in fixture_ids_set
        and fact.evidence_type == "MATCH_STATISTIC"
        and fact.predicate in _PHASE_METRICS[phase]
        and fact.source_digest is not None
    )
    feature_ids, _ = _feature_lineage(state, _T12_FEATURE_NAMES)
    return (
        fixture_ids,
        tuple(sorted(training_digests)),
        tuple(sorted(training_ids)),
        feature_ids,
    )


def _training_input_provenance(
    history: Sequence[HistoricalMatch],
    state: FrozenEvidenceState,
    phase: HalfPhase,
) -> Mapping[str, object]:
    """Retain phase-metric provenance without flattening multi-source inputs."""
    provenance: dict[str, object] = {}
    for match in sorted(history, key=lambda item: item.fixture_id):
        metrics: dict[str, object] = {}
        for metric in _PHASE_METRICS[phase]:
            source_fact_ids: set[str] = set()
            source_digests: set[str] = set()
            for fact in state.source_assertions:
                if fact.subject_id != match.fixture_id or fact.predicate != metric:
                    continue
                source_fact_ids.add(fact.fact_id)
                source_fact_ids.update(fact.source_assertion_ids)
                if fact.source_digest is not None:
                    source_digests.add(fact.source_digest)
            metrics[metric] = {
                "input_ids": tuple(sorted(match.metric_ids(metric))),
                "source_assertion_ids": tuple(sorted(source_fact_ids)),
                "source_digests": tuple(sorted(source_digests)),
            }
        provenance[match.fixture_id] = metrics
    return provenance


def _runtime_reproducibility(
    config: T12ModelConfig,
    state: FrozenEvidenceState,
    history: Sequence[HistoricalMatch],
    phase: HalfPhase,
    full_time_fit: FullTimeGoalModelFit | None,
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
        "full_time_model_digest": full_time_fit.digest if full_time_fit is not None else None,
        "full_time_model_version": (
            full_time_fit.model_version if full_time_fit is not None else None
        ),
        "history_order": "fixture_id_ascending",
        "input_history_fixture_ids": tuple(sorted(match.fixture_id for match in history)),
        "numpy_version": str(getattr(np, "__version__", "unknown")),
        "phase": phase.value,
        "platform": platform.platform(),
        "preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
        "preference_catalog_name": DEFAULT_PREFERENCE_CATALOG.name,
        "preference_catalog_version": DEFAULT_PREFERENCE_CATALOG.version,
        "preference_ids": (phase.preference_id,),
        "python_version": platform.python_version(),
        "randomness": "none",
        "scipy_version": scipy_version,
        "software_commit": os.environ.get("MATCHVET_COMMIT", "unknown"),
        "target_fixture_id": state.target_fixture_id,
    }


def _freeze_map(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): value[key] for key in value})


@dataclass(frozen=True)
class HalfGoalDistribution:
    """One normalized joint phase score surface and its total-goal marginal."""

    status: ModelStatus
    phase: HalfPhase
    target_fixture_id: str
    matchweek_id: str
    model_version: str
    model_digest: str
    score_distribution: tuple[tuple[float, ...], ...] = ()
    goal_distribution: tuple[float, ...] = ()
    home_expected_goals: float | None = None
    away_expected_goals: float | None = None
    expected_goals: float | None = None
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
        object.__setattr__(self, "phase", _phase(self.phase))
        _text(self.target_fixture_id, "T12 target fixture ID")
        _text(self.matchweek_id, "T12 matchweek ID")
        _text(self.model_version, "T12 model version")
        _text(self.model_digest, "T12 model digest")
        if not isinstance(self.status, ModelStatus):
            object.__setattr__(self, "status", ModelStatus(str(self.status)))
        selected = {str(key): value for key, value in self.settlement_distributions.items()}
        if not all(isinstance(value, SettlementProbabilities) for value in selected.values()):
            raise T12ValidationError("T12 settlement distributions require typed probabilities.")
        object.__setattr__(self, "settlement_distributions", MappingProxyType(selected))
        object.__setattr__(self, "feature_inputs", _freeze_map(self.feature_inputs))
        object.__setattr__(self, "uncertainty", _freeze_map(self.uncertainty))
        object.__setattr__(self, "diagnostics", _freeze_map(self.diagnostics))
        if self.status is ModelStatus.AVAILABLE:
            if not self.score_distribution:
                raise T12ValidationError("An available T12 distribution requires a score grid.")
            rows = tuple(tuple(float(cell) for cell in row) for row in self.score_distribution)
            if not rows or any(len(row) != len(rows) for row in rows):
                raise T12ValidationError("T12 score grids must be square.")
            if any(not math.isfinite(cell) or cell < -1e-12 for row in rows for cell in row):
                raise T12ValidationError("T12 score grids must be finite and non-negative.")
            if abs(sum(sum(row) for row in rows) - 1.0) > 1e-9:
                raise T12ValidationError("T12 score grids must be normalized.")
            goal_values = tuple(float(value) for value in self.goal_distribution)
            if not goal_values:
                goal_values = _total_goal_distribution(rows)
            expected_goal_values = _total_goal_distribution(rows)
            if len(goal_values) != len(expected_goal_values) or any(
                abs(left - right) > 1e-9
                for left, right in zip(goal_values, expected_goal_values, strict=True)
            ):
                raise T12IntegrityError(
                    "T12 total-goal distribution does not match the stored score grid."
                )
            if any(not math.isfinite(value) or value < -1e-12 for value in goal_values):
                raise T12ValidationError(
                    "T12 total-goal distributions must be finite and non-negative."
                )
            if abs(sum(goal_values) - 1.0) > 1e-9:
                raise T12ValidationError("T12 total-goal distributions must be normalized.")
            expected_settlement = _settlement_distribution(goal_values)
            if set(selected) != {self.phase.preference_id}:
                raise T12ValidationError(
                    "Available T12 distributions must contain exactly the phase Over 1.5 market."
                )
            actual = selected[self.phase.preference_id]
            if any(
                abs(getattr(actual, field_name) - getattr(expected_settlement, field_name)) > 1e-9
                for field_name in ("win", "loss", "push")
            ):
                raise T12IntegrityError(
                    "T12 settlement distribution does not match the stored goal distribution."
                )
            if self.home_expected_goals is None or self.away_expected_goals is None:
                raise T12ValidationError("Available T12 distributions require expected goals.")
            for label, value in (
                ("home expected goals", self.home_expected_goals),
                ("away expected goals", self.away_expected_goals),
            ):
                if not math.isfinite(float(value)) or float(value) < 0:
                    raise T12ValidationError(f"T12 {label} must be finite and non-negative.")
            expected_goals = self.expected_goals
            if expected_goals is None:
                expected_goals = sum(i * value for i, value in enumerate(goal_values))
                object.__setattr__(self, "expected_goals", expected_goals)
            if not math.isfinite(float(expected_goals)) or float(expected_goals) < 0:
                raise T12ValidationError("T12 expected goals must be finite and non-negative.")
            if self.tail_mass is not None and (
                not math.isfinite(float(self.tail_mass)) or not 0.0 <= float(self.tail_mass) <= 1.0
            ):
                raise T12ValidationError("T12 score-grid tail mass must be between zero and one.")
            object.__setattr__(self, "score_distribution", rows)
            object.__setattr__(self, "goal_distribution", goal_values)
        else:
            if self.score_distribution or self.goal_distribution or self.settlement_distributions:
                raise T12ValidationError(
                    "MODEL_UNAVAILABLE distributions cannot contain probability output."
                )
        expected = _digest(self._core_dict(include_digest=False))
        if self.distribution_digest and self.distribution_digest != expected:
            raise T12IntegrityError("T12 distribution digest does not match its content.")
        object.__setattr__(self, "distribution_digest", expected)

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
    def total_goal_distribution(self) -> tuple[float, ...]:
        return self.goal_distribution

    @property
    def distribution(self) -> tuple[float, ...]:
        return self.goal_distribution

    @property
    def market_distributions(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def preference_distributions(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    @property
    def settlement_probabilities(self) -> Mapping[str, SettlementProbabilities]:
        return self.settlement_distributions

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "away_expected_goals": self.away_expected_goals,
            "diagnostics": dict(self.diagnostics),
            "expected_goals": self.expected_goals,
            "feature_inputs": dict(self.feature_inputs),
            "goal_distribution": self.goal_distribution,
            "home_expected_goals": self.home_expected_goals,
            "matchweek_id": self.matchweek_id,
            "maximum_goals": self.maximum_goals,
            "model_digest": self.model_digest,
            "model_version": self.model_version,
            "phase": self.phase.value,
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

    def with_artifact(self, artifact_digest: str) -> HalfGoalDistribution:
        return replace(self, artifact_digest=_text(artifact_digest, "T12 artifact digest"))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HalfGoalDistribution:
        status = ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value)))
        selected_phase = _phase(str(value.get("phase", HalfPhase.FIRST_HALF.value)))
        settlements: dict[str, SettlementProbabilities] = {}
        settlement_raw = value.get("settlement_distributions", {})
        if isinstance(settlement_raw, Mapping):
            for key, item in settlement_raw.items():
                mapped = _mapping(item, "T12 settlement distribution")
                settlements[str(key)] = SettlementProbabilities(
                    win_probability=_finite(mapped.get("WIN"), "T12 WIN"),
                    loss_probability=_finite(mapped.get("LOSS"), "T12 LOSS"),
                    push_probability=_finite(mapped.get("PUSH", 0.0), "T12 PUSH"),
                )
        score = tuple(
            tuple(_finite(cell, "T12 score distribution value") for cell in row)
            for row in _as_sequence(value.get("score_distribution", ()))
            if isinstance(row, (tuple, list))
        )
        goals = tuple(
            _finite(item, "T12 goal distribution value")
            for item in _as_sequence(value.get("goal_distribution", ()))
        )
        maximum_goals_value = value.get("maximum_goals")
        maximum_goals = (
            int(maximum_goals_value)
            if isinstance(maximum_goals_value, int) and not isinstance(maximum_goals_value, bool)
            else None
        )
        reason_value = value.get("reason")
        return cls(
            status=status,
            phase=selected_phase,
            target_fixture_id=_text(value.get("target_fixture_id"), "T12 fixture ID"),
            matchweek_id=_text(value.get("matchweek_id"), "T12 matchweek ID"),
            model_version=_text(value.get("model_version"), "T12 model version"),
            model_digest=_text(value.get("model_digest"), "T12 model digest"),
            score_distribution=score,
            goal_distribution=goals,
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
            expected_goals=(
                _number(value.get("expected_goals"))
                if value.get("expected_goals") is not None
                else None
            ),
            maximum_goals=maximum_goals,
            tail_mass=(
                _number(value.get("tail_mass")) if value.get("tail_mass") is not None else None
            ),
            settlement_distributions=settlements,
            feature_inputs=_mapping(value.get("feature_inputs", {}), "T12 feature inputs"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T12 uncertainty"),
            diagnostics=_mapping(value.get("diagnostics", {}), "T12 diagnostics"),
            reason=reason_value if isinstance(reason_value, str) else None,
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            distribution_digest=str(value.get("distribution_digest", "")),
        )


@dataclass(frozen=True)
class HalfGoalModelFit:
    """A deterministic fitted T12 phase model with frozen-input identity."""

    status: ModelStatus
    phase: HalfPhase
    model_name: str
    model_version: str
    algorithm_version: str
    feature_version: str
    target: TargetMatch
    config: T12ModelConfig
    parameters: Mapping[str, object] = field(default_factory=dict)
    training_input_fixture_ids: tuple[str, ...] = ()
    training_input_digests: tuple[str, ...] = ()
    training_input_ids: tuple[str, ...] = ()
    frozen_evidence_digest: str = ""
    frozen_artifact_digest: str | None = None
    frozen_manifest_digest: str | None = None
    feature_input_ids: tuple[str, ...] = ()
    feature_input_digests: tuple[str, ...] = ()
    full_time_model_digest: str | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    reproducibility: Mapping[str, object] = field(default_factory=dict)
    reason: str | None = None
    artifact_digest: str | None = None
    fit_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", _phase(self.phase))
        if not isinstance(self.status, ModelStatus):
            object.__setattr__(self, "status", ModelStatus(str(self.status)))
        for label, value in (
            ("model name", self.model_name),
            ("model version", self.model_version),
            ("algorithm version", self.algorithm_version),
            ("feature version", self.feature_version),
        ):
            _text(value, f"T12 {label}")
        if not isinstance(self.target, TargetMatch):
            raise T12ValidationError("T12 fits require a TargetMatch.")
        if not isinstance(self.config, T12ModelConfig):
            raise T12ValidationError("T12 fits require a T12ModelConfig.")
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
            raise T12ValidationError("Available T12 fits require fitted parameters.")
        expected = _digest(self._core_dict(include_digest=False))
        if self.fit_digest and self.fit_digest != expected:
            raise T12IntegrityError("T12 fit digest does not match its content.")
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
            "full_time_model_digest": self.full_time_model_digest,
            "frozen_artifact_digest": self.frozen_artifact_digest,
            "frozen_evidence_digest": self.frozen_evidence_digest,
            "frozen_manifest_digest": self.frozen_manifest_digest,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "parameters": dict(self.parameters),
            "phase": self.phase.value,
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

    def with_artifact(self, artifact_digest: str) -> HalfGoalModelFit:
        return replace(self, artifact_digest=_text(artifact_digest, "T12 artifact digest"))

    def predict(
        self, frozen_evidence_state: FrozenEvidenceState | None = None
    ) -> HalfGoalDistribution:
        return predict_half_goal_distribution(self, frozen_evidence_state)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HalfGoalModelFit:
        target_value = _mapping(value.get("target"), "T12 fit target")
        config_value = _mapping(value.get("config"), "T12 fit config")
        config_fields = {
            key: config_value[key]
            for key in T12ModelConfig.__dataclass_fields__
            if key in config_value
        }
        reason_value = value.get("reason")
        return cls(
            status=ModelStatus(str(value.get("status", ModelStatus.MODEL_UNAVAILABLE.value))),
            phase=_phase(str(value.get("phase", HalfPhase.FIRST_HALF.value))),
            model_name=_text(value.get("model_name"), "T12 model name"),
            model_version=_text(value.get("model_version"), "T12 model version"),
            algorithm_version=_text(value.get("algorithm_version"), "T12 algorithm version"),
            feature_version=_text(value.get("feature_version"), "T12 feature version"),
            target=TargetMatch(**cast(dict[str, Any], dict(target_value))),
            config=T12ModelConfig(**cast(dict[str, Any], config_fields)),
            parameters=_mapping(value.get("parameters", {}), "T12 parameters"),
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
            full_time_model_digest=(
                str(value["full_time_model_digest"])
                if value.get("full_time_model_digest") is not None
                else None
            ),
            diagnostics=_mapping(value.get("diagnostics", {}), "T12 diagnostics"),
            uncertainty=_mapping(value.get("uncertainty", {}), "T12 uncertainty"),
            reproducibility=_mapping(value.get("reproducibility", {}), "T12 reproducibility"),
            reason=reason_value if isinstance(reason_value, str) else None,
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            fit_digest=str(value.get("fit_digest", "")),
        )


@dataclass(frozen=True)
class HalfGoalModelFits:
    """The separately fitted first-half and second-half T12 models."""

    first_half: HalfGoalModelFit
    second_half: HalfGoalModelFit

    def __post_init__(self) -> None:
        if self.first_half.phase is not HalfPhase.FIRST_HALF:
            raise T12ValidationError("The first_half fit must be a first-half model.")
        if self.second_half.phase is not HalfPhase.SECOND_HALF:
            raise T12ValidationError("The second_half fit must be a second-half model.")

    def __getitem__(self, phase: HalfPhase | str) -> HalfGoalModelFit:
        selected = _phase(phase)
        return self.first_half if selected is HalfPhase.FIRST_HALF else self.second_half

    @property
    def first_half_model(self) -> HalfGoalModelFit:
        return self.first_half

    @property
    def second_half_model(self) -> HalfGoalModelFit:
        return self.second_half


HalfGoalModelBundle = HalfGoalModelFits
HalfGoalModels = HalfGoalModelFits
FirstHalfGoalModelFit = HalfGoalModelFit
SecondHalfGoalModelFit = HalfGoalModelFit
FirstHalfGoalDistribution = HalfGoalDistribution
SecondHalfGoalDistribution = HalfGoalDistribution


def _parameter_number(parameters: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = _number(parameters.get(key))
    return default if value is None else value


def _parameter_map(parameters: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parameters.get(key)
    return value if isinstance(value, Mapping) else {}


def _validate_state_target(state: FrozenEvidenceState) -> None:
    if (
        state.target.fixture_id == state.target.home_team_id
        or state.target.fixture_id == state.target.away_team_id
    ):
        raise T12IntegrityError("T12 target identity overlaps a team identity.")
    if not state.digest:
        raise T12IntegrityError("T12 requires a digest-bearing FrozenEvidenceState.")


def _validate_prediction_state(fit: HalfGoalModelFit, state: FrozenEvidenceState | None) -> None:
    if state is None:
        return
    _validate_state_target(state)
    target = fit.target
    if (
        state.target.fixture_id != target.fixture_id
        or state.target.matchweek_id != target.matchweek_id
        or state.target.cutoff_utc != target.cutoff_utc
        or state.target.home_team_id != target.home_team_id
        or state.target.away_team_id != target.away_team_id
    ):
        raise T12IntegrityError(
            "The prediction FrozenEvidenceState does not identify the fitted target."
        )
    if state.digest != fit.frozen_evidence_digest:
        raise T12IntegrityError(
            "The prediction FrozenEvidenceState does not match the fitted evidence digest."
        )


def _prediction_lambdas(
    fit: HalfGoalModelFit, state: FrozenEvidenceState | None
) -> tuple[float, float, Mapping[str, object]]:
    _validate_prediction_state(fit, state)
    target = fit.target
    parameters = fit.parameters
    intercepts = _parameter_map(parameters, "league_season_intercepts")
    target_league_key = _league_season_key(target.competition_key, target.season)
    intercept = _number(intercepts.get(target_league_key))
    baseline = _parameter_number(parameters, "baseline_goal_rate", 0.05)
    if intercept is None:
        intercept = math.log(max(baseline, 0.05))
    attacks = _parameter_map(parameters, "team_attack")
    defenses = _parameter_map(parameters, "team_defense")
    home_attack = _number(attacks.get(target.home_team_id)) or 0.0
    away_attack = _number(attacks.get(target.away_team_id)) or 0.0
    home_defense = _number(defenses.get(target.home_team_id)) or 0.0
    away_defense = _number(defenses.get(target.away_team_id)) or 0.0
    stored_offsets = _parameter_map(parameters, "target_feature_offsets")
    offsets = _feature_offsets(
        state,
        fit.phase,
        feature_coefficients=_parameter_map(parameters, "feature_coefficients"),
        model_covariates=_parameter_map(parameters, "target_model_covariates"),
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
    return math.exp(home_eta), math.exp(away_eta), offsets


def _poisson_probabilities(rate: float, maximum_goals: int) -> Any:
    np, _, _ = _numeric_modules()
    if not math.isfinite(rate) or rate <= 0:
        raise _T12FitFailure("T12 expected goals must be finite and positive.")
    probabilities = np.empty(maximum_goals + 1, dtype=np.float64)
    probabilities[0] = math.exp(-rate)
    for goal in range(1, maximum_goals + 1):
        probabilities[goal] = probabilities[goal - 1] * rate / goal
    if not np.all(np.isfinite(probabilities)):
        raise _T12FitFailure("T12 Poisson probabilities are not finite.")
    return probabilities


def _score_surface(
    home_lambda: float, away_lambda: float, config: T12ModelConfig
) -> tuple[Any, int, float]:
    np, _, _ = _numeric_modules()
    maximum_goals = max(2, config.maximum_score_goals)
    while True:
        home = _poisson_probabilities(home_lambda, maximum_goals)
        away = _poisson_probabilities(away_lambda, maximum_goals)
        surface = home[:, None] * away[None, :]
        raw_mass = float(np.sum(surface))
        tail_mass = abs(1.0 - raw_mass)
        if not math.isfinite(raw_mass) or raw_mass <= 0:
            raise _T12FitFailure("T12 score surface has invalid mass.")
        if tail_mass <= config.tail_tolerance:
            surface = surface / raw_mass
            if not np.all(np.isfinite(surface)) or np.any(surface < -1e-12):
                raise _T12FitFailure("T12 score surface is not finite and non-negative.")
            surface = np.maximum(surface, 0.0)
            surface = surface / float(np.sum(surface))
            return surface, maximum_goals, tail_mass
        if maximum_goals >= 128:
            raise _T12FitFailure("T12 score-grid tail mass exceeds the versioned tolerance.")
        maximum_goals = min(128, max(maximum_goals + 1, maximum_goals * 2))


def _total_goal_distribution(score: Sequence[Sequence[float]]) -> tuple[float, ...]:
    np, _, _ = _numeric_modules()
    rows = np.asarray(score, dtype=np.float64)
    if rows.ndim != 2 or rows.shape[0] != rows.shape[1]:
        raise T12ValidationError("T12 total-goal conversion requires a square score grid.")
    maximum = rows.shape[0] - 1
    result = np.zeros(2 * maximum + 1, dtype=np.float64)
    for home_goals in range(maximum + 1):
        for away_goals in range(maximum + 1):
            result[home_goals + away_goals] += rows[home_goals, away_goals]
    total = float(np.sum(result))
    if not math.isfinite(total) or total <= 0:
        raise T12ValidationError("T12 total-goal distribution has invalid mass.")
    result = np.maximum(result / total, 0.0)
    result = result / float(np.sum(result))
    return tuple(float(value) for value in result)


def _settlement_distribution(goal_distribution: Sequence[float]) -> SettlementProbabilities:
    win = sum(float(value) for goals, value in enumerate(goal_distribution) if goals > 1.5)
    win = _bounded(win, 0.0, 1.0)
    return SettlementProbabilities(win_probability=win, loss_probability=1.0 - win)


def _unavailable_distribution(fit: HalfGoalModelFit, reason: str) -> HalfGoalDistribution:
    return HalfGoalDistribution(
        status=ModelStatus.MODEL_UNAVAILABLE,
        phase=fit.phase,
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


def predict_half_goal_distribution(
    fit: HalfGoalModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> HalfGoalDistribution:
    """Return one phase's normalized score and total-goal distributions."""
    if not isinstance(fit, HalfGoalModelFit):
        raise T12ValidationError("T12 prediction requires a HalfGoalModelFit.")
    if not fit.is_available:
        return _unavailable_distribution(fit, fit.reason or "MODEL_UNAVAILABLE")
    selected_state = frozen_evidence_state
    try:
        home_lambda, away_lambda, offsets = _prediction_lambdas(fit, selected_state)
        score, maximum_goals, tail_mass = _score_surface(
            home_lambda,
            away_lambda,
            fit.config,
        )
        goal_distribution = _total_goal_distribution(score)
        settlements = {fit.phase.preference_id: _settlement_distribution(goal_distribution)}
    except _T12FitFailure as error:
        return _unavailable_distribution(fit, str(error))
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        return _unavailable_distribution(fit, f"PREDICTION_FAILED:{error}")
    feature_ids, feature_digests = (
        _feature_lineage(selected_state, _T12_FEATURE_NAMES)
        if selected_state is not None
        else (fit.feature_input_ids, fit.feature_input_digests)
    )
    diagnostics = dict(fit.diagnostics)
    diagnostics.update(
        {
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
    return HalfGoalDistribution(
        status=ModelStatus.AVAILABLE,
        phase=fit.phase,
        target_fixture_id=fit.target_fixture_id,
        matchweek_id=fit.matchweek_id,
        model_version=fit.model_version,
        model_digest=fit.digest,
        score_distribution=tuple(tuple(float(cell) for cell in row) for row in score),
        goal_distribution=goal_distribution,
        home_expected_goals=home_lambda,
        away_expected_goals=away_lambda,
        expected_goals=home_lambda + away_lambda,
        maximum_goals=maximum_goals,
        tail_mass=tail_mass,
        settlement_distributions=settlements,
        feature_inputs=feature_inputs,
        uncertainty=uncertainty,
        diagnostics=diagnostics,
    )


def predict_half_goals(
    fit: HalfGoalModelFit,
    frozen_evidence_state: FrozenEvidenceState | None = None,
) -> HalfGoalDistribution:
    return predict_half_goal_distribution(fit, frozen_evidence_state)


def _coerce_state(value: object) -> FrozenEvidenceState:
    if isinstance(value, FrozenEvidenceState):
        return value
    if isinstance(value, Mapping):
        return FrozenEvidenceState.from_dict(value)
    raise T12ValidationError("T12 requires a FrozenEvidenceState from T09.")


def _new_unavailable_fit(
    state: FrozenEvidenceState,
    config: T12ModelConfig,
    phase: HalfPhase,
    *,
    reason: str,
    history: Sequence[HistoricalMatch] = (),
    rows: Sequence[_PhaseTrainingRow] = (),
    full_time_fit: FullTimeGoalModelFit | None = None,
    diagnostics: Mapping[str, object] | None = None,
) -> HalfGoalModelFit:
    fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(history, state, phase)
    _, feature_digests = _feature_lineage(state, _T12_FEATURE_NAMES)
    try:
        reproducibility = _runtime_reproducibility(
            config,
            state,
            history,
            phase,
            full_time_fit,
        )
    except _T12FitFailure:
        reproducibility = {
            "algorithm_version": config.algorithm_version,
            "config_digest": config.digest,
            "cutoff_utc": state.cutoff_utc,
            "frozen_evidence_digest": state.digest,
            "full_time_model_digest": full_time_fit.digest if full_time_fit is not None else None,
            "history_order": "fixture_id_ascending",
            "input_history_fixture_ids": fixture_ids,
            "phase": phase.value,
            "preference_ids": (phase.preference_id,),
            "randomness": "none",
            "target_fixture_id": state.target_fixture_id,
        }
    selected_diagnostics = dict(diagnostics or {})
    selected_diagnostics.update(
        {
            "history_rows": len(rows),
            "training_effective_matches": sum(row.weight for row in rows),
            "training_input_provenance": _training_input_provenance(history, state, phase),
            "model_status_reason": reason,
            "phase": phase.value,
        }
    )
    return HalfGoalModelFit(
        status=ModelStatus.MODEL_UNAVAILABLE,
        phase=phase,
        model_name=f"{T12_MODEL_NAME}:{phase.value.lower()}",
        model_version=phase.model_version,
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
        full_time_model_digest=(full_time_fit.digest if full_time_fit is not None else None),
        diagnostics=selected_diagnostics,
        uncertainty=_uncertainty_metadata(rows, state.target, config, phase),
        reproducibility=reproducibility,
        reason=reason,
    )


def _select_full_time_fit(
    history: Sequence[HistoricalMatch],
    state: FrozenEvidenceState,
    supplied: FullTimeGoalModelFit | None,
) -> FullTimeGoalModelFit:
    if supplied is not None:
        if not isinstance(supplied, FullTimeGoalModelFit):
            raise T12ValidationError("T12 full-time capability must be a FullTimeGoalModelFit.")
        if supplied.target.fixture_id != state.target.fixture_id:
            raise T12IntegrityError("T12 full-time capability targets a different fixture.")
        if supplied.frozen_evidence_digest != state.digest:
            raise T12IntegrityError("T12 full-time capability uses a different Evidence State.")
        return supplied
    return fit_full_time_goal_model(history, state)


def fit_half_goal_model(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    phase: HalfPhase | str = HalfPhase.FIRST_HALF,
    *,
    evidence_state: object | None = None,
    config: T12ModelConfig | None = None,
    model_config: T12ModelConfig | None = None,
    full_time_fit: FullTimeGoalModelFit | None = None,
    full_time_model: FullTimeGoalModelFit | None = None,
) -> HalfGoalModelFit:
    """Fit one deterministic T12 phase model from one frozen T09 state."""
    selected_phase = _phase(phase)
    if evidence_state is not None:
        if frozen_evidence_state is not None:
            raise T12ValidationError("T12 received two FrozenEvidenceState arguments.")
        frozen_evidence_state = evidence_state
    if config is not None and model_config is not None:
        raise T12ValidationError("T12 received two model configurations.")
    if full_time_fit is not None and full_time_model is not None:
        raise T12ValidationError("T12 received two full-time model fits.")
    selected_config = config or model_config or T12ModelConfig()
    if not isinstance(selected_config, T12ModelConfig):
        raise T12ValidationError("T12 config must be a T12ModelConfig.")
    selected_full_time = full_time_fit or full_time_model

    selected_history: object = history
    if isinstance(history, FrozenEvidenceState):
        if frozen_evidence_state is None:
            raise T12ValidationError("The state-first T12 form also requires history.")
        selected_state = _coerce_state(history)
        selected_history = frozen_evidence_state
    else:
        if frozen_evidence_state is None:
            raise T12ValidationError("T12 fitting requires a FrozenEvidenceState from T09.")
        selected_state = _coerce_state(frozen_evidence_state)
    _validate_state_target(selected_state)
    if selected_history is None or isinstance(selected_history, FrozenEvidenceState):
        raise T12ValidationError("T12 fitting requires structured HistoricalMatch rows.")
    if not isinstance(selected_history, Iterable):
        raise T12ValidationError("T12 history must be iterable.")
    history_records = _coerce_history(
        cast(Iterable[HistoricalMatch | Mapping[str, object]], selected_history)
    )
    rows, ordered_history, invalid = _training_rows(
        history_records,
        selected_state,
        selected_phase,
        selected_config,
    )
    cutoff = _parse_utc(selected_state.target.cutoff_utc)
    expected_history_ids = set(_state_history_ids(selected_state))
    supplied_cutoff_ids = {
        match.fixture_id for match in history_records if _cutoff_valid_history_match(match, cutoff)
    }
    missing_history_ids = tuple(sorted(expected_history_ids - supplied_cutoff_ids))
    unexpected_history_ids = tuple(sorted(supplied_cutoff_ids - expected_history_ids))
    base_diagnostics: dict[str, object] = {
        "invalid_history_fixture_ids": tuple(sorted(invalid)),
        "invalid_history_reasons": dict(invalid),
        "phase_history_metrics": _PHASE_METRICS[selected_phase],
        "second_half_derivation": (
            "full_time_minus_half_time_scores"
            if selected_phase is HalfPhase.SECOND_HALF
            else "observed_half_time_scores"
        ),
    }
    if missing_history_ids:
        base_diagnostics["missing_fixture_ids"] = missing_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="FROZEN_HISTORY_INPUTS_INCOMPLETE",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    if not expected_history_ids and unexpected_history_ids:
        base_diagnostics["unexpected_fixture_ids"] = unexpected_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="FROZEN_HISTORY_INPUTS_MISMATCH",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    unresolved_conflict_ids = _unresolved_phase_conflict_ids(selected_state, selected_phase)
    if unresolved_conflict_ids:
        base_diagnostics["unresolved_material_conflict_ids"] = unresolved_conflict_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="UNRESOLVED_MATERIAL_CONFLICT",
            history=history_records,
            rows=rows,
            diagnostics=base_diagnostics,
        )
    mismatched_history_ids = _frozen_history_input_mismatches(
        history_records,
        selected_state,
        selected_phase,
    )
    if mismatched_history_ids:
        base_diagnostics["mismatched_fixture_ids"] = mismatched_history_ids
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
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
            selected_phase,
            reason=(
                f"MINIMUM_{selected_phase.value}_HISTORY_NOT_SATISFIED"
                if minimum_reason == "MINIMUM_HISTORY_MATCHES_NOT_SATISFIED"
                else minimum_reason
            ),
            history=ordered_history,
            rows=rows,
            diagnostics=base_diagnostics,
        )

    selected_full_time_fit = _select_full_time_fit(
        history_records,
        selected_state,
        selected_full_time,
    )
    if not selected_full_time_fit.is_available:
        base_diagnostics["full_time_model_reason"] = selected_full_time_fit.reason
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="FULL_TIME_MODEL_UNAVAILABLE",
            history=ordered_history,
            rows=rows,
            full_time_fit=selected_full_time_fit,
            diagnostics=base_diagnostics,
        )
    try:
        parameters, numerical_diagnostics = _fit_numerical_parameters(
            rows,
            ordered_history,
            selected_state.target,
            selected_config,
            selected_full_time_fit,
            _target_regime(selected_state),
        )
        baseline = _number(parameters.get("baseline_goal_rate"))
        if baseline is None:
            raise _T12FitFailure("T12 fit did not retain a finite baseline goal rate.")
        effects = _regime_effects(rows, baseline, selected_config)
        offsets = _feature_offsets(
            selected_state,
            selected_phase,
            feature_coefficients=_parameter_map(parameters, "feature_coefficients"),
            model_covariates=_parameter_map(parameters, "target_model_covariates"),
        )
        selected_parameters = dict(parameters)
        selected_parameters.update(
            {
                "feature_version": selected_config.feature_version,
                "full_time_model_digest": selected_full_time_fit.digest,
                "full_time_model_version": selected_full_time_fit.model_version,
                "phase": selected_phase.value,
                "regime_effects": effects,
                "target_feature_offsets": offsets,
                "target_regime_id": _target_regime(selected_state),
            }
        )
        fixture_ids, input_digests, input_ids, feature_ids = _fit_input_metadata(
            ordered_history,
            selected_state,
            selected_phase,
        )
        _, feature_digests = _feature_lineage(selected_state, _T12_FEATURE_NAMES)
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
                    ordered_history,
                    selected_state,
                    selected_phase,
                ),
            }
        )
        fit = HalfGoalModelFit(
            status=ModelStatus.AVAILABLE,
            phase=selected_phase,
            model_name=f"{T12_MODEL_NAME}:{selected_phase.value.lower()}",
            model_version=selected_phase.model_version,
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
            full_time_model_digest=selected_full_time_fit.digest,
            diagnostics=diagnostics,
            uncertainty=_uncertainty_metadata(
                rows,
                selected_state.target,
                selected_config,
                selected_phase,
            ),
            reproducibility=_runtime_reproducibility(
                selected_config,
                selected_state,
                ordered_history,
                selected_phase,
                selected_full_time_fit,
            ),
        )
        validation_prediction = predict_half_goal_distribution(fit, selected_state)
        if not validation_prediction.is_available:
            raise _T12FitFailure(validation_prediction.reason or "INVALID_HALF_DISTRIBUTION")
        return fit
    except _T12FitFailure as error:
        base_diagnostics["fit_error"] = str(error)
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            full_time_fit=selected_full_time_fit,
            diagnostics=base_diagnostics,
        )
    except (FloatingPointError, OverflowError, RuntimeError, ValueError) as error:
        base_diagnostics["fit_error"] = str(error)
        return _new_unavailable_fit(
            selected_state,
            selected_config,
            selected_phase,
            reason="FIT_FAILED",
            history=ordered_history,
            rows=rows,
            full_time_fit=selected_full_time_fit,
            diagnostics=base_diagnostics,
        )


def fit_first_half_goal_model(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    *,
    evidence_state: object | None = None,
    config: T12ModelConfig | None = None,
    model_config: T12ModelConfig | None = None,
    full_time_fit: FullTimeGoalModelFit | None = None,
    full_time_model: FullTimeGoalModelFit | None = None,
) -> HalfGoalModelFit:
    return fit_half_goal_model(
        history,
        frozen_evidence_state,
        HalfPhase.FIRST_HALF,
        evidence_state=evidence_state,
        config=config,
        model_config=model_config,
        full_time_fit=full_time_fit,
        full_time_model=full_time_model,
    )


def fit_second_half_goal_model(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    *,
    evidence_state: object | None = None,
    config: T12ModelConfig | None = None,
    model_config: T12ModelConfig | None = None,
    full_time_fit: FullTimeGoalModelFit | None = None,
    full_time_model: FullTimeGoalModelFit | None = None,
) -> HalfGoalModelFit:
    return fit_half_goal_model(
        history,
        frozen_evidence_state,
        HalfPhase.SECOND_HALF,
        evidence_state=evidence_state,
        config=config,
        model_config=model_config,
        full_time_fit=full_time_fit,
        full_time_model=full_time_model,
    )


def fit_half_goal_models(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    *,
    evidence_state: object | None = None,
    config: T12ModelConfig | None = None,
    model_config: T12ModelConfig | None = None,
    full_time_fit: FullTimeGoalModelFit | None = None,
    full_time_model: FullTimeGoalModelFit | None = None,
) -> HalfGoalModelFits:
    """Fit both phase models while sharing one frozen T11 capability fit."""
    if evidence_state is not None:
        if frozen_evidence_state is not None:
            raise T12ValidationError("T12 received two FrozenEvidenceState arguments.")
        frozen_evidence_state = evidence_state
    if history is None or isinstance(history, FrozenEvidenceState):
        if isinstance(history, FrozenEvidenceState):
            if frozen_evidence_state is None:
                raise T12ValidationError("The state-first T12 form also requires history.")
            selected_history: object = frozen_evidence_state
            selected_state = history
        else:
            raise T12ValidationError("T12 fitting requires structured HistoricalMatch rows.")
    else:
        selected_history = history
        if frozen_evidence_state is None:
            raise T12ValidationError("T12 fitting requires a FrozenEvidenceState from T09.")
        selected_state = _coerce_state(frozen_evidence_state)
    if not isinstance(selected_history, Iterable):
        raise T12ValidationError("T12 history must be iterable.")
    history_records = _coerce_history(
        cast(Iterable[HistoricalMatch | Mapping[str, object]], selected_history)
    )
    state = _coerce_state(selected_state)
    selected_config = config or model_config or T12ModelConfig()
    if not isinstance(selected_config, T12ModelConfig):
        raise T12ValidationError("T12 config must be a T12ModelConfig.")
    if full_time_fit is not None and full_time_model is not None:
        raise T12ValidationError("T12 received two full-time model fits.")
    selected_full_time = full_time_fit or full_time_model
    if selected_full_time is None:
        selected_full_time = fit_full_time_goal_model(history_records, state)
    first = fit_first_half_goal_model(
        history_records,
        state,
        config=selected_config,
        full_time_fit=selected_full_time,
    )
    second = fit_second_half_goal_model(
        history_records,
        state,
        config=selected_config,
        full_time_fit=selected_full_time,
    )
    return HalfGoalModelFits(first_half=first, second_half=second)


def fit_first_half_goals(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    **kwargs: object,
) -> HalfGoalModelFit:
    return fit_first_half_goal_model(history, frozen_evidence_state, **kwargs)  # type: ignore[arg-type]


def fit_second_half_goals(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    **kwargs: object,
) -> HalfGoalModelFit:
    return fit_second_half_goal_model(history, frozen_evidence_state, **kwargs)  # type: ignore[arg-type]


def fit_half_goals(
    history: Iterable[HistoricalMatch | Mapping[str, object]] | FrozenEvidenceState | None = None,
    frozen_evidence_state: object | None = None,
    **kwargs: object,
) -> HalfGoalModelFits:
    return fit_half_goal_models(history, frozen_evidence_state, **kwargs)  # type: ignore[arg-type]


def fit_half_goal_model_from_store(
    store: Store,
    frozen_evidence_state: FrozenEvidenceState | Mapping[str, object],
    phase: HalfPhase | str,
    *,
    config: T12ModelConfig | None = None,
) -> HalfGoalModelFit:
    """Fit one T12 phase from the cutoff-valid T06 rows behind a T09 state."""
    if not isinstance(store, Store):
        raise T12ValidationError("T12 store fitting requires a MatchVet Store.")
    state = _coerce_state(frozen_evidence_state)
    from matchvet.t09 import _t06_history_and_facts

    history, _ = _t06_history_and_facts(
        store,
        season=state.target.season,
        cutoff_utc=state.target.cutoff_utc,
        excluded_fixture_ids=(state.target.fixture_id,),
    )
    return fit_half_goal_model(history, state, phase, config=config)


class T12ModelService:
    """Small service facade for separate phase fitting and prediction."""

    def __init__(self, config: T12ModelConfig | None = None) -> None:
        self.config = config or T12ModelConfig()

    def fit(
        self,
        history: Iterable[HistoricalMatch | Mapping[str, object]],
        frozen_evidence_state: FrozenEvidenceState,
        phase: HalfPhase | str = HalfPhase.FIRST_HALF,
        *,
        full_time_fit: FullTimeGoalModelFit | None = None,
    ) -> HalfGoalModelFit:
        return fit_half_goal_model(
            history,
            frozen_evidence_state,
            phase,
            config=self.config,
            full_time_fit=full_time_fit,
        )

    def fit_both(
        self,
        history: Iterable[HistoricalMatch | Mapping[str, object]],
        frozen_evidence_state: FrozenEvidenceState,
        *,
        full_time_fit: FullTimeGoalModelFit | None = None,
    ) -> HalfGoalModelFits:
        return fit_half_goal_models(
            history,
            frozen_evidence_state,
            config=self.config,
            full_time_fit=full_time_fit,
        )

    @staticmethod
    def predict(
        fit: HalfGoalModelFit,
        frozen_evidence_state: FrozenEvidenceState | None = None,
    ) -> HalfGoalDistribution:
        return predict_half_goal_distribution(fit, frozen_evidence_state)


T12Runner = T12ModelService
HalfGoalModel = T12ModelService


@dataclass(frozen=True)
class T12Plan:
    """Immutable identity for a T12 phase fit request."""

    target: TargetMatch
    phase: HalfPhase = HalfPhase.FIRST_HALF
    config: T12ModelConfig = field(default_factory=T12ModelConfig)

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", _phase(self.phase))
        if not isinstance(self.target, TargetMatch):
            raise T12ValidationError("T12 plans require a TargetMatch.")
        if not isinstance(self.config, T12ModelConfig):
            raise T12ValidationError("T12 plans require a T12ModelConfig.")

    @property
    def run_key(self) -> str:
        return f"t12-{self.phase.value.lower()}:{self.target.matchweek_id}:{self.target.fixture_id}"

    @property
    def plan_digest(self) -> str:
        return _digest(
            {
                "config_digest": self.config.digest,
                "phase": self.phase.value,
                "run_key": self.run_key,
                "target": self.target.to_dict(),
            }
        )


@dataclass(frozen=True)
class T12PublishedArtifacts:
    """The content-addressed fit and distribution artifacts published together."""

    fit: HalfGoalModelFit
    distribution: HalfGoalDistribution
    fit_artifact_digest: str
    distribution_artifact_digest: str


class T12ArtifactRecorder:
    """Publish and reload immutable T12 JSON artifacts through the local store."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T12 artifact publication requires a writable store.")
        self.store = store
        self.artifacts = ArtifactStore(store)

    def publish_fit(self, fit: HalfGoalModelFit) -> HalfGoalModelFit:
        if not isinstance(fit, HalfGoalModelFit):
            raise T12ValidationError("T12 fit artifact publication requires a model fit.")
        record = self.artifacts.publish_artifact(fit.to_bytes(), T12_MEDIA_TYPE)
        return fit.with_artifact(record.digest)

    def publish_distribution(self, distribution: HalfGoalDistribution) -> HalfGoalDistribution:
        if not isinstance(distribution, HalfGoalDistribution):
            raise T12ValidationError(
                "T12 distribution artifact publication requires a model distribution."
            )
        record = self.artifacts.publish_artifact(
            distribution.to_bytes(), T12_DISTRIBUTION_MEDIA_TYPE
        )
        return distribution.with_artifact(record.digest)

    def publish(
        self,
        fit: HalfGoalModelFit,
        distribution: HalfGoalDistribution | None = None,
    ) -> T12PublishedArtifacts:
        published_fit = self.publish_fit(fit)
        selected_distribution = distribution or fit.predict()
        if selected_distribution.model_digest != fit.digest:
            raise T12IntegrityError(
                "A T12 distribution must reference the exact fitted model digest."
            )
        published_distribution = self.publish_distribution(selected_distribution)
        return T12PublishedArtifacts(
            fit=published_fit,
            distribution=published_distribution,
            fit_artifact_digest=cast(str, published_fit.artifact_digest),
            distribution_artifact_digest=cast(str, published_distribution.artifact_digest),
        )

    def load_fit(self, digest: str) -> HalfGoalModelFit:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T12_MEDIA_TYPE:
            raise T12IntegrityError("The artifact is not a T12 model fit.")
        fit = HalfGoalModelFit.from_dict(
            cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        )
        return fit if fit.artifact_digest == digest else fit.with_artifact(digest)

    def load_distribution(self, digest: str) -> HalfGoalDistribution:
        record = self.artifacts.verify_artifact(digest)
        if record.media_type != T12_DISTRIBUTION_MEDIA_TYPE:
            raise T12IntegrityError("The artifact is not a T12 settlement distribution.")
        distribution = HalfGoalDistribution.from_dict(
            cast(Mapping[str, object], json.loads(self.artifacts.read_artifact(digest)))
        )
        return (
            distribution
            if distribution.artifact_digest == digest
            else distribution.with_artifact(digest)
        )


__all__ = [
    "FIRST_HALF_GOAL_MODEL_VERSION",
    "FIRST_HALF_OVER_1_5",
    "HALF_GOAL_PREFERENCE_IDS",
    "MODEL_MEDIA_TYPE",
    "MODEL_UNAVAILABLE",
    "SECOND_HALF_GOAL_MODEL_VERSION",
    "SECOND_HALF_OVER_1_5",
    "T12_ALGORITHM_VERSION",
    "T12_DISTRIBUTION_MEDIA_TYPE",
    "T12_MEDIA_TYPE",
    "T12_MODEL_NAME",
    "T12_MODEL_VERSION",
    "FirstHalfGoalDistribution",
    "FirstHalfGoalModelFit",
    "HalfGoalDistribution",
    "HalfGoalHistory",
    "HalfGoalHistoryRow",
    "HalfGoalModel",
    "HalfGoalModelBundle",
    "HalfGoalModelFit",
    "HalfGoalModelFits",
    "HalfGoalModels",
    "HalfPhase",
    "ModelStatus",
    "SecondHalfGoalDistribution",
    "SecondHalfGoalModelFit",
    "SettlementProbabilities",
    "T12ArtifactRecorder",
    "T12Error",
    "T12IntegrityError",
    "T12ModelConfig",
    "T12ModelService",
    "T12Plan",
    "T12PublishedArtifacts",
    "T12Runner",
    "T12ValidationError",
    "derive_first_half_goals",
    "derive_first_half_goals_history",
    "derive_first_half_history",
    "derive_half_goal_history",
    "derive_second_half_goals",
    "derive_second_half_goals_history",
    "derive_second_half_history",
    "fit_first_half_goal_model",
    "fit_first_half_goals",
    "fit_half_goal_model",
    "fit_half_goal_model_from_store",
    "fit_half_goal_models",
    "fit_half_goals",
    "fit_second_half_goal_model",
    "fit_second_half_goals",
    "predict_half_goal_distribution",
    "predict_half_goals",
]

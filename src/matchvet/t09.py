"""T09 frozen Evidence Research.

The T09 seam turns the source-backed facts from T06--T08 into one deterministic
research state for a Target Match.  It deliberately stops at evidence: this
module does not calculate probabilities, settlement results, Selection
Strength, recommendations, or reports.

The public builder is usable without a store so recorded evidence packs can be
tested at the seam.  The store-backed builder and runner are added below the
pure research code; both publish only immutable T03 artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from matchvet.artifacts import (
    ArtifactStore,
    ManifestArtifact,
    ManifestCompleteness,
    ManifestVersion,
    RetentionOmission,
    SnapshotManifest,
)
from matchvet.evidence import (
    CutoffEligibility,
    EvidenceAssertionRecord,
    EvidenceClass,
    EvidenceRecorder,
    EvidenceState,
)
from matchvet.ingestion import deterministic_identifier
from matchvet.matchweek import (
    FrozenMembership,
    MatchweekFreeze,
    MatchweekWindow,
    read_frozen_matchweek,
)
from matchvet.runs import (
    MIB,
    SETTLED_RESOURCE_BUDGET,
    ResourceEstimate,
    ResourceObservation,
    RunCoordinator,
    RunInputContract,
    RunPhase,
    RunStatus,
    WorkContext,
    WorkResult,
)
from matchvet.store import MIGRATIONS, CanonicalIdentifier, Store, VersionIdentity


class T09Error(Exception):
    """Base class for deterministic T09 research failures."""


class T09ValidationError(T09Error, ValueError):
    """An Evidence Research input is malformed or outside the catalog."""


class T09IntegrityError(T09Error):
    """An immutable T09 identity was reused with different content."""


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    POST_CUTOFF = "POST_CUTOFF"


Freshness = FreshnessState


class CoverageState(StrEnum):
    COVERED = "COVERED"
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"
    STALE = "STALE"
    POST_CUTOFF = "POST_CUTOFF"
    CONFLICT = "CONFLICT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNPERFORMED = "UNPERFORMED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResearchStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class AccessState(StrEnum):
    ACCESSIBLE = "ACCESSIBLE"
    INACCESSIBLE = "INACCESSIBLE"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Influence(StrEnum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    CONTEXT = "CONTEXT"


EvidenceInfluence = Influence


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _jsonable(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise T09ValidationError(
            "T09 timestamps must be ISO-8601 values with an explicit UTC offset."
        ) from error
    if parsed.tzinfo is None:
        raise T09ValidationError("T09 timestamps must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(_canonical_utc(value))


def _optional_utc(value: str | None) -> str | None:
    return _canonical_utc(value) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise T09ValidationError("T09 values must contain finite numbers.")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T09ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _state(value: EvidenceState | str) -> EvidenceState:
    try:
        return value if isinstance(value, EvidenceState) else EvidenceState(value.strip().upper())
    except (AttributeError, ValueError) as error:
        raise T09ValidationError("Evidence values must be OBSERVED, ABSENT, or UNKNOWN.") from error


def _access_state(value: AccessState | str) -> AccessState:
    try:
        return value if isinstance(value, AccessState) else AccessState(value.strip().upper())
    except (AttributeError, ValueError) as error:
        raise T09ValidationError("Research attempt accessibility is invalid.") from error


def _freshness_state(value: FreshnessState | str) -> FreshnessState:
    try:
        return value if isinstance(value, FreshnessState) else FreshnessState(value.strip().upper())
    except (AttributeError, ValueError) as error:
        raise T09ValidationError("Evidence freshness state is invalid.") from error


def _eligibility(value: CutoffEligibility | str) -> CutoffEligibility:
    try:
        return (
            value
            if isinstance(value, CutoffEligibility)
            else CutoffEligibility(value.strip().upper())
        )
    except (AttributeError, ValueError) as error:
        raise T09ValidationError(
            "Cutoff eligibility must be CUTOFF_VALID, POST_CUTOFF, or INDETERMINATE."
        ) from error


def _evidence_class(value: EvidenceClass | Influence | str) -> EvidenceClass:
    try:
        text = value.value if isinstance(value, StrEnum) else value
        return EvidenceClass(str(text).strip().upper())
    except (AttributeError, ValueError) as error:
        raise T09ValidationError(
            "Evidence class must be CRITICAL, IMPORTANT, or CONTEXT."
        ) from error


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(item for item in _as_sequence(value) if isinstance(item, str))


def _int_or_string_tuple(value: object) -> tuple[int | str, ...]:
    return tuple(item for item in _as_sequence(value) if isinstance(item, (int, str)))


def _integer(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


_FAMILY_ALIASES = {
    "ASIAN HANDICAP": "Asian Handicaps",
    "ASIAN HANDICAPS": "Asian Handicaps",
    "CORNER MATCH WINNER": "Corner Match Winner",
    "DOUBLE CHANCE": "Double Chance",
    "FULL MATCH TOTAL CORNERS OVER": "Full-Match Total Corners Over",
    "FULL-MATCH TOTAL CORNERS OVER": "Full-Match Total Corners Over",
    "HOME TEAM CORNERS OVER": "Home Team Corners Over",
    "HOME TEAM GOALS OVER": "Home Team Goals Over",
    "AWAY TEAM CORNERS OVER": "Away Team Corners Over",
    "AWAY TEAM GOALS OVER": "Away Team Goals Over",
    "FIRST HALF OVER": "First-Half Over",
    "FIRST-HALF OVER": "First-Half Over",
    "MATCH GOALS OVER": "Match Goals Over",
    "MATCH WINNER": "Match Winner",
    "SECOND HALF OVER": "Second-Half Over",
    "SECOND-HALF OVER": "Second-Half Over",
}


def normalize_family(value: str) -> str:
    text = _text(value, "Preference Family")
    key = " ".join(text.replace("_", " ").split()).upper()
    try:
        return _FAMILY_ALIASES[key]
    except KeyError as error:
        raise T09ValidationError(f"Unsupported Preference Family {value!r}.") from error


PREFERENCE_FAMILIES: tuple[str, ...] = (
    "Match Winner",
    "Double Chance",
    "Asian Handicaps",
    "Match Goals Over",
    "Home Team Goals Over",
    "Away Team Goals Over",
    "First-Half Over",
    "Second-Half Over",
    "Full-Match Total Corners Over",
    "Corner Match Winner",
    "Home Team Corners Over",
    "Away Team Corners Over",
)


class PreferenceFamily(StrEnum):
    MATCH_WINNER = "Match Winner"
    DOUBLE_CHANCE = "Double Chance"
    ASIAN_HANDICAPS = "Asian Handicaps"
    MATCH_GOALS_OVER = "Match Goals Over"
    HOME_TEAM_GOALS_OVER = "Home Team Goals Over"
    AWAY_TEAM_GOALS_OVER = "Away Team Goals Over"
    FIRST_HALF_OVER = "First-Half Over"
    SECOND_HALF_OVER = "Second-Half Over"
    FULL_MATCH_TOTAL_CORNERS_OVER = "Full-Match Total Corners Over"
    CORNER_MATCH_WINNER = "Corner Match Winner"
    HOME_TEAM_CORNERS_OVER = "Home Team Corners Over"
    AWAY_TEAM_CORNERS_OVER = "Away Team Corners Over"


CATALOG_NAME = "Evidence Requirement and Metric Catalog"
CATALOG_VERSION = "1.0.0"
CATALOG_KIND = "evidence_catalog"
RESEARCH_RULES_NAME = "t09-evidence-research-v1"
EVIDENCE_STATE_MEDIA_TYPE = "application/vnd.matchvet.t09-evidence-state+json"


@dataclass(frozen=True)
class EvidenceRequirement:
    requirement_id: str
    label: str
    families: tuple[str, ...]
    mandatory_research: bool
    evidence_class: EvidenceClass
    influence: Influence
    freshness_rule: str
    correlation_group: str
    source_priority: str
    conditional: bool = False

    def __post_init__(self) -> None:
        _text(self.requirement_id, "Evidence requirement ID")
        _text(self.label, "Evidence requirement label")
        normalized = tuple(sorted({normalize_family(item) for item in self.families}))
        if not normalized:
            raise T09ValidationError("Evidence requirements need at least one family.")
        if self.freshness_rule not in {f"FR-{index}" for index in range(1, 10)}:
            raise T09ValidationError("Evidence requirements must name FR-1 through FR-9.")
        object.__setattr__(self, "families", normalized)

    def applies_to(self, family: str) -> bool:
        return normalize_family(family) in self.families

    def to_dict(self) -> dict[str, object]:
        return {
            "conditional": self.conditional,
            "evidence_class": self.evidence_class.value,
            "families": self.families,
            "freshness_rule": self.freshness_rule,
            "influence": self.influence.value,
            "label": self.label,
            "mandatory_research": self.mandatory_research,
            "correlation_group": self.correlation_group,
            "requirement_id": self.requirement_id,
            "source_priority": self.source_priority,
        }


@dataclass(frozen=True)
class EvidenceRequirementCatalog:
    name: str = CATALOG_NAME
    version: str = CATALOG_VERSION
    requirements: tuple[EvidenceRequirement, ...] = ()

    def __post_init__(self) -> None:
        if not self.requirements:
            raise T09ValidationError("An Evidence Requirement catalog cannot be empty.")
        ids = tuple(item.requirement_id for item in self.requirements)
        if len(ids) != len(set(ids)) or ids != tuple(sorted(ids)):
            raise T09ValidationError("Catalog requirement IDs must be sorted and unique.")

    def requirement(self, requirement_id: str) -> EvidenceRequirement:
        for item in self.requirements:
            if item.requirement_id == requirement_id:
                return item
        raise T09ValidationError(f"Unknown Evidence Requirement {requirement_id}.")

    def for_family(self, family: str) -> tuple[EvidenceRequirement, ...]:
        selected = normalize_family(family)
        return tuple(item for item in self.requirements if item.applies_to(selected))

    def critical_for(self, family: str) -> tuple[EvidenceRequirement, ...]:
        return tuple(
            item
            for item in self.for_family(family)
            if item.evidence_class is EvidenceClass.CRITICAL
        )

    def mandatory(self) -> tuple[EvidenceRequirement, ...]:
        return tuple(item for item in self.requirements if item.mandatory_research)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "requirements": [item.to_dict() for item in self.requirements],
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


def _all() -> tuple[str, ...]:
    return PREFERENCE_FAMILIES


def _req(
    requirement_id: str,
    label: str,
    families: Iterable[str],
    *,
    mandatory: bool,
    evidence_class: EvidenceClass,
    influence: Influence,
    freshness_rule: str,
    correlation_group: str,
    source_priority: str,
    conditional: bool = False,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id,
        label,
        tuple(families),
        mandatory,
        evidence_class,
        influence,
        freshness_rule,
        correlation_group,
        source_priority,
        conditional,
    )


_FULL_TIME_OUTCOME = ("Match Winner", "Double Chance", "Asian Handicaps")
_FULL_TIME_GOALS = ("Match Goals Over", "Home Team Goals Over", "Away Team Goals Over")
_HALF_GOALS = ("First-Half Over", "Second-Half Over")
_CORNERS = (
    "Full-Match Total Corners Over",
    "Corner Match Winner",
    "Home Team Corners Over",
    "Away Team Corners Over",
)


def _catalog_requirements() -> tuple[EvidenceRequirement, ...]:
    values = (
        _req(
            "D-HISTORICAL-BASELINE",
            "Exact-line Historical Baseline",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-2",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "D-OPPONENT-STRENGTH",
            "Opponent-adjusted strength",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-3",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "D-RECENCY-STRENGTH",
            "Recency-weighted strength",
            (*_FULL_TIME_OUTCOME, *_FULL_TIME_GOALS, *_HALF_GOALS, *_CORNERS),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-3",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "D-VENUE-EFFECT",
            "Venue effect",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-3",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "M-CORNERS",
            "Regulation and stoppage-time home and away corners",
            _CORNERS,
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-2",
            correlation_group="corners",
            source_priority="SP-CORNER",
        ),
        _req(
            "M-FIXTURE",
            "Target Match identity, scope, kickoff, and venue",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-4",
            correlation_group="schedule/workload",
            source_priority="SP-FIX",
        ),
        _req(
            "M-FT-GOALS",
            "Final full-time goals and result history",
            (*_FULL_TIME_OUTCOME, *_FULL_TIME_GOALS, *_HALF_GOALS),
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-2",
            correlation_group="goals/results",
            source_priority="SP-RESULT",
        ),
        _req(
            "M-HT-GOALS",
            "Final half-time goals history",
            _HALF_GOALS,
            mandatory=True,
            evidence_class=EvidenceClass.CRITICAL,
            influence=Influence.CRITICAL,
            freshness_rule="FR-2",
            correlation_group="goals/results",
            source_priority="SP-RESULT",
        ),
        _req(
            "D-FORM-HORIZONS",
            "Recent, medium, current-season, and older horizons",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-3",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "D-TREND-DIRECTION",
            "Trend direction across compatible horizons",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-3",
            correlation_group="goals/results",
            source_priority="SP-HISTORY",
        ),
        _req(
            "D-REST",
            "Verified rest before the Target Match",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-7",
            correlation_group="schedule/workload",
            source_priority="SP-SCHEDULE",
        ),
        _req(
            "D-CONGESTION",
            "Verified fixture spacing and congestion",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-7",
            correlation_group="schedule/workload",
            source_priority="SP-SCHEDULE",
        ),
        _req(
            "D-CROSS-COMP-WORKLOAD",
            "Cross-competition workload and known rotation context",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-7",
            correlation_group="schedule/workload",
            source_priority="SP-SCHEDULE",
        ),
        _req(
            "D-SCORE-STATE",
            "Score-state and numerical-imbalance distortion",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="discipline/match-state",
            source_priority="SP-STAT",
        ),
        _req(
            "E-AVAILABILITY",
            "Current Target Match availability",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-5",
            correlation_group="personnel/availability",
            source_priority="SP-TEAM",
            conditional=True,
        ),
        _req(
            "E-INJURY",
            "Current injuries and affected roles",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-5",
            correlation_group="personnel/availability",
            source_priority="SP-TEAM",
            conditional=True,
        ),
        _req(
            "E-LINEUP-SCENARIO",
            "Plausible pre-lineup personnel scenarios",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-5",
            correlation_group="personnel/availability",
            source_priority="SP-TEAM",
            conditional=True,
        ),
        _req(
            "E-MANAGER",
            "Current manager identity and appointment state",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-6",
            correlation_group="tactics/regime",
            source_priority="SP-TEAM",
        ),
        _req(
            "E-ROTATION",
            "Likely rotation and role uncertainty",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-5",
            correlation_group="personnel/availability",
            source_priority="SP-TEAM",
            conditional=True,
        ),
        _req(
            "E-SUSPENSION",
            "Formal exact-fixture suspension state",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-4",
            correlation_group="personnel/availability",
            source_priority="SP-SUSPENSION",
            conditional=True,
        ),
        _req(
            "E-TACTICAL-REGIME",
            "Active manager and tactical regime comparability",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-6",
            correlation_group="tactics/regime",
            source_priority="SP-TEAM",
            conditional=True,
        ),
        _req(
            "E-TACTICS",
            "Cutoff-valid tactical observations",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-6",
            correlation_group="tactics/regime",
            source_priority="SP-TEAM",
        ),
        _req(
            "M-REFEREE",
            "Exact-fixture referee appointment",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-4",
            correlation_group="referee",
            source_priority="SP-FIX",
            conditional=True,
        ),
        _req(
            "M-WEATHER",
            "Cutoff-valid exact-venue forecast",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-8",
            correlation_group="weather",
            source_priority="SP-WEATHER",
            conditional=True,
        ),
        _req(
            "E-WEATHER-CONTEXT",
            "Additional sourced weather or pitch context",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-8",
            correlation_group="weather",
            source_priority="SP-WEATHER",
        ),
        _req(
            "E-HEAD-TO-HEAD",
            "Comparable Head-to-Head Evidence",
            _all(),
            mandatory=True,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-9",
            correlation_group="head-to-head",
            source_priority="SP-HISTORY",
        ),
        _req(
            "M-SHOTS",
            "Documented total shots",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="shots/chances",
            source_priority="SP-STAT",
        ),
        _req(
            "M-SOT",
            "Documented shots on target",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="shots/chances",
            source_priority="SP-STAT",
        ),
        _req(
            "M-YELLOW",
            "Documented yellow-card counts",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="discipline/match-state",
            source_priority="SP-STAT",
        ),
        _req(
            "M-RED",
            "Documented dismissals and timing when available",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="discipline/match-state",
            source_priority="SP-STAT",
            conditional=True,
        ),
        _req(
            "M-PENALTY-EVENT",
            "Directly recorded penalty events",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.IMPORTANT,
            influence=Influence.IMPORTANT,
            freshness_rule="FR-2",
            correlation_group="discipline/match-state",
            source_priority="SP-STAT",
            conditional=True,
        ),
        _req(
            "M-PROVIDER-XG",
            "Provider xG retained as research-only context",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-2",
            correlation_group="shots/chances",
            source_priority="SP-STAT",
        ),
        _req(
            "E-REFEREE-CONTEXT",
            "Qualitative referee context",
            _all(),
            mandatory=False,
            evidence_class=EvidenceClass.CONTEXT,
            influence=Influence.CONTEXT,
            freshness_rule="FR-4",
            correlation_group="referee",
            source_priority="SP-FIX",
        ),
    )
    return tuple(sorted(values, key=lambda item: item.requirement_id))


EVIDENCE_REQUIREMENT_CATALOG_V1 = EvidenceRequirementCatalog(requirements=_catalog_requirements())
DEFAULT_CATALOG = EVIDENCE_REQUIREMENT_CATALOG_V1
CATALOG_DIGEST = EVIDENCE_REQUIREMENT_CATALOG_V1.digest


@dataclass(frozen=True)
class FeatureRules:
    """Explicit T09 feature rules; no unversioned recency defaults are hidden."""

    name: str = "t09-feature-rules-v1"
    recency_half_life_days: float = 180.0
    recent_horizon_days: int = 30
    medium_horizon_days: int = 90
    current_season_horizon_days: int = 365
    older_horizon_days: int = 730
    trend_tolerance: float = 0.05
    severe_rest_days: float = 3.0
    severe_wind_kph: float = 50.0
    severe_precipitation_mm: float = 10.0
    severe_temperature_c: float = 35.0
    minimum_history_matches: int = 3
    minimum_effective_history_matches: float = 3.0

    def __post_init__(self) -> None:
        _text(self.name, "Feature rules name")
        if self.recency_half_life_days <= 0:
            raise T09ValidationError("Recency half-life must be positive.")
        horizons = (
            self.recent_horizon_days,
            self.medium_horizon_days,
            self.current_season_horizon_days,
            self.older_horizon_days,
        )
        if any(item <= 0 for item in horizons) or tuple(sorted(horizons)) != horizons:
            raise T09ValidationError("T09 horizons must be positive and increasing.")
        if self.minimum_history_matches < 1 or self.minimum_effective_history_matches <= 0:
            raise T09ValidationError("T09 history sufficiency thresholds must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "current_season_horizon_days": self.current_season_horizon_days,
            "medium_horizon_days": self.medium_horizon_days,
            "name": self.name,
            "older_horizon_days": self.older_horizon_days,
            "recent_horizon_days": self.recent_horizon_days,
            "recency_half_life_days": self.recency_half_life_days,
            "severe_precipitation_mm": self.severe_precipitation_mm,
            "severe_rest_days": self.severe_rest_days,
            "severe_temperature_c": self.severe_temperature_c,
            "severe_wind_kph": self.severe_wind_kph,
            "trend_tolerance": self.trend_tolerance,
            "minimum_history_matches": self.minimum_history_matches,
            "minimum_effective_history_matches": self.minimum_effective_history_matches,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class TargetMatch:
    matchweek_id: str
    cutoff_id: str
    fixture_id: str
    cutoff_utc: str
    kickoff_utc: str
    home_team_id: str
    away_team_id: str
    competition_key: str
    competition_name: str
    season: str
    venue_id: str | None = None
    venue_name: str | None = None
    official_local_timezone: str | None = None
    fixture_status: str = "SCHEDULED"
    source_assertion_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("matchweek ID", self.matchweek_id),
            ("cutoff ID", self.cutoff_id),
            ("fixture ID", self.fixture_id),
            ("home team ID", self.home_team_id),
            ("away team ID", self.away_team_id),
            ("competition key", self.competition_key),
            ("competition name", self.competition_name),
            ("season", self.season),
        ):
            _text(value, label)
        if self.home_team_id == self.away_team_id:
            raise T09ValidationError("A Target Match requires two different teams.")
        cutoff = _canonical_utc(self.cutoff_utc)
        kickoff = _canonical_utc(self.kickoff_utc)
        if kickoff <= cutoff:
            raise T09ValidationError("A Target Match kickoff must be after the Research Cutoff.")
        object.__setattr__(self, "cutoff_utc", cutoff)
        object.__setattr__(self, "kickoff_utc", kickoff)
        object.__setattr__(
            self, "fixture_status", _text(self.fixture_status, "Fixture status").upper()
        )
        object.__setattr__(self, "source_assertion_ids", _sorted_unique(self.source_assertion_ids))

    @property
    def team_ids(self) -> tuple[str, str]:
        return self.home_team_id, self.away_team_id

    def to_dict(self) -> dict[str, object]:
        return {
            "away_team_id": self.away_team_id,
            "competition_key": self.competition_key,
            "competition_name": self.competition_name,
            "cutoff_id": self.cutoff_id,
            "cutoff_utc": self.cutoff_utc,
            "fixture_id": self.fixture_id,
            "fixture_status": self.fixture_status,
            "home_team_id": self.home_team_id,
            "kickoff_utc": self.kickoff_utc,
            "matchweek_id": self.matchweek_id,
            "official_local_timezone": self.official_local_timezone,
            "season": self.season,
            "source_assertion_ids": self.source_assertion_ids,
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
        }


@dataclass(frozen=True)
class HistoricalMatch:
    """Cutoff-replayable structured match facts used by T09 features."""

    fixture_id: str
    home_team_id: str
    away_team_id: str
    kickoff_utc: str
    full_time_home_goals: int | None = None
    full_time_away_goals: int | None = None
    half_time_home_goals: int | None = None
    half_time_away_goals: int | None = None
    corners_home: int | None = None
    corners_away: int | None = None
    shots_home: int | None = None
    shots_away: int | None = None
    shots_on_target_home: int | None = None
    shots_on_target_away: int | None = None
    yellow_cards_home: int | None = None
    yellow_cards_away: int | None = None
    red_cards_home: int | None = None
    red_cards_away: int | None = None
    metric_states: Mapping[str, EvidenceState | str] = field(default_factory=dict)
    metric_input_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    source_assertion_ids: tuple[str, ...] = ()
    source_digest: str | None = None
    source_key: str = "structured-history"
    origin_id: str | None = None
    observed_at_utc: str | None = None
    published_at_utc: str | None = None
    red_card_minutes: tuple[int | str, ...] = ()
    penalty_minutes: tuple[int | str, ...] = ()
    regime_id: str | None = None
    competition_key: str | None = None
    competition_type: str = "TARGET_LEAGUE"
    fixture_status: str = "COMPLETED"
    final_state: EvidenceState | str = EvidenceState.OBSERVED

    def __post_init__(self) -> None:
        for label, value in (
            ("Historical Match fixture ID", self.fixture_id),
            ("Historical Match home team ID", self.home_team_id),
            ("Historical Match away team ID", self.away_team_id),
            ("Historical Match source key", self.source_key),
        ):
            _text(value, label)
        if self.home_team_id == self.away_team_id:
            raise T09ValidationError("Historical Matches require two different teams.")
        object.__setattr__(self, "kickoff_utc", _canonical_utc(self.kickoff_utc))
        object.__setattr__(self, "observed_at_utc", _optional_utc(self.observed_at_utc))
        object.__setattr__(self, "published_at_utc", _optional_utc(self.published_at_utc))
        object.__setattr__(
            self, "fixture_status", _text(self.fixture_status, "Historical Match status").upper()
        )
        object.__setattr__(self, "final_state", _state(self.final_state))
        normalized_states = {str(key): _state(value) for key, value in self.metric_states.items()}
        object.__setattr__(self, "metric_states", MappingProxyType(normalized_states))
        normalized_inputs = {
            str(key): _sorted_unique(values) for key, values in self.metric_input_ids.items()
        }
        object.__setattr__(self, "metric_input_ids", MappingProxyType(normalized_inputs))
        object.__setattr__(self, "source_assertion_ids", _sorted_unique(self.source_assertion_ids))

    @property
    def metrics(self) -> Mapping[str, object | None]:
        return MappingProxyType(
            {
                "full_time_home_goals": self.full_time_home_goals,
                "full_time_away_goals": self.full_time_away_goals,
                "half_time_home_goals": self.half_time_home_goals,
                "half_time_away_goals": self.half_time_away_goals,
                "corners_home": self.corners_home,
                "corners_away": self.corners_away,
                "shots_home": self.shots_home,
                "shots_away": self.shots_away,
                "shots_on_target_home": self.shots_on_target_home,
                "shots_on_target_away": self.shots_on_target_away,
                "yellow_cards_home": self.yellow_cards_home,
                "yellow_cards_away": self.yellow_cards_away,
                "red_cards_home": self.red_cards_home,
                "red_cards_away": self.red_cards_away,
            }
        )

    @property
    def home_goals(self) -> int | None:
        return self.full_time_home_goals

    @property
    def away_goals(self) -> int | None:
        return self.full_time_away_goals

    @property
    def home_corners(self) -> int | None:
        return self.corners_home

    @property
    def away_corners(self) -> int | None:
        return self.corners_away

    def metric_state(self, key: str) -> EvidenceState:
        selected = self.metric_states.get(key)
        has_provenance = bool(
            self.source_assertion_ids
            or self.source_digest
            or self.origin_id
            or self.metric_input_ids.get(key)
        )
        if selected is not None:
            normalized = _state(selected)
            return (
                normalized
                if has_provenance or normalized is not EvidenceState.OBSERVED
                else EvidenceState.UNKNOWN
            )
        if not has_provenance:
            return EvidenceState.UNKNOWN
        return (
            EvidenceState.OBSERVED if self.metrics.get(key) is not None else EvidenceState.UNKNOWN
        )

    def metric_ids(self, key: str) -> tuple[str, ...]:
        return self.metric_input_ids.get(key, self.source_assertion_ids)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> HistoricalMatch:
        def integer(key: str) -> int | None:
            raw = value.get(key)
            if raw is None:
                return None
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise T09ValidationError(f"Historical metric {key} must be an integer or null.")
            return raw

        metrics = value.get("metrics")
        metric_map = metrics if isinstance(metrics, Mapping) else value

        def metric(name: str, *aliases: str) -> int | None:
            for key in (name, *aliases):
                if key in metric_map:
                    raw = metric_map[key]
                    if raw is None:
                        return None
                    if isinstance(raw, bool) or not isinstance(raw, int):
                        raise T09ValidationError(
                            f"Historical metric {key} must be an integer or null."
                        )
                    return raw
            return None

        states_raw = value.get("metric_states", {})
        inputs_raw = value.get("metric_input_ids", {})
        return cls(
            fixture_id=_text(value.get("fixture_id"), "Historical Match fixture ID"),
            home_team_id=_text(value.get("home_team_id"), "Historical Match home team ID"),
            away_team_id=_text(value.get("away_team_id"), "Historical Match away team ID"),
            kickoff_utc=_text(value.get("kickoff_utc"), "Historical Match kickoff"),
            full_time_home_goals=metric("full_time_home_goals", "home_goals"),
            full_time_away_goals=metric("full_time_away_goals", "away_goals"),
            half_time_home_goals=metric("half_time_home_goals"),
            half_time_away_goals=metric("half_time_away_goals"),
            corners_home=metric("corners_home", "home_corners"),
            corners_away=metric("corners_away", "away_corners"),
            shots_home=metric("shots_home"),
            shots_away=metric("shots_away"),
            shots_on_target_home=metric("shots_on_target_home"),
            shots_on_target_away=metric("shots_on_target_away"),
            yellow_cards_home=metric("yellow_cards_home"),
            yellow_cards_away=metric("yellow_cards_away"),
            red_cards_home=metric("red_cards_home"),
            red_cards_away=metric("red_cards_away"),
            metric_states=cast(Mapping[str, EvidenceState | str], states_raw)
            if isinstance(states_raw, Mapping)
            else {},
            metric_input_ids=cast(Mapping[str, tuple[str, ...]], inputs_raw)
            if isinstance(inputs_raw, Mapping)
            else {},
            source_assertion_ids=_string_tuple(value.get("source_assertion_ids", ())),
            source_digest=_optional_text(value.get("source_digest")),
            source_key=str(value.get("source_key", "structured-history")),
            origin_id=_optional_text(value.get("origin_id")),
            observed_at_utc=_optional_text(value.get("observed_at_utc")),
            published_at_utc=_optional_text(value.get("published_at_utc")),
            red_card_minutes=_int_or_string_tuple(value.get("red_card_minutes", ())),
            penalty_minutes=_int_or_string_tuple(value.get("penalty_minutes", ())),
            regime_id=_optional_text(value.get("regime_id")),
            competition_key=_optional_text(value.get("competition_key")),
            competition_type=str(value.get("competition_type", "TARGET_LEAGUE")),
            fixture_status=str(value.get("fixture_status", "COMPLETED")),
            final_state=_state(cast(str, value.get("final_state", "OBSERVED"))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "away_team_id": self.away_team_id,
            "competition_key": self.competition_key,
            "competition_type": self.competition_type,
            "corners_away": self.corners_away,
            "corners_home": self.corners_home,
            "fixture_id": self.fixture_id,
            "full_time_away_goals": self.full_time_away_goals,
            "full_time_home_goals": self.full_time_home_goals,
            "final_state": _enum_value(self.final_state),
            "fixture_status": self.fixture_status,
            "half_time_away_goals": self.half_time_away_goals,
            "half_time_home_goals": self.half_time_home_goals,
            "home_team_id": self.home_team_id,
            "kickoff_utc": self.kickoff_utc,
            "metric_input_ids": self.metric_input_ids,
            "metric_states": self.metric_states,
            "observed_at_utc": self.observed_at_utc,
            "origin_id": self.origin_id,
            "penalty_minutes": self.penalty_minutes,
            "published_at_utc": self.published_at_utc,
            "red_card_minutes": self.red_card_minutes,
            "regime_id": self.regime_id,
            "source_assertion_ids": self.source_assertion_ids,
            "source_digest": self.source_digest,
            "source_key": self.source_key,
            "shots_away": self.shots_away,
            "shots_home": self.shots_home,
            "shots_on_target_away": self.shots_on_target_away,
            "shots_on_target_home": self.shots_on_target_home,
            "yellow_cards_away": self.yellow_cards_away,
            "yellow_cards_home": self.yellow_cards_home,
            "red_cards_away": self.red_cards_away,
            "red_cards_home": self.red_cards_home,
        }


StructuredMatch = HistoricalMatch
HistoricalMatchRecord = HistoricalMatch


@dataclass(frozen=True)
class SourceFact:
    """One source-backed fact, with its cutoff and provenance state."""

    fact_id: str
    subject_id: str
    evidence_type: str
    predicate: str
    state: EvidenceState | str
    value: object | None = None
    evidence_class: EvidenceClass | Influence | str = EvidenceClass.CONTEXT
    source_key: str = "UNKNOWN"
    origin_id: str | None = None
    source_assertion_ids: tuple[str, ...] = ()
    source_digest: str | None = None
    published_at_utc: str | None = None
    observed_at_utc: str | None = None
    retrieved_at_utc: str | None = None
    event_time_utc: str | None = None
    effective_time_utc: str | None = None
    cutoff_eligibility: CutoffEligibility | str = CutoffEligibility.INDETERMINATE
    source_row_key: str | None = None
    correlation_groups: tuple[str, ...] = ()
    unknown_reason: str | None = None
    affirmative_basis: str | None = None
    authority_rank: int = 900
    provenance: Mapping[str, object] = field(default_factory=dict)
    freshness: FreshnessState | str = FreshnessState.UNKNOWN
    age_seconds_at_cutoff: float | None = None
    age_seconds_at_kickoff: float | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("Source Fact ID", self.fact_id),
            ("Source Fact subject ID", self.subject_id),
            ("Source Fact evidence type", self.evidence_type),
            ("Source Fact predicate", self.predicate),
            ("Source Fact source key", self.source_key),
        ):
            _text(value, label)
        selected_state = _state(self.state)
        selected_class = _evidence_class(self.evidence_class)
        if selected_state is EvidenceState.OBSERVED and self.value is None:
            raise T09ValidationError("OBSERVED source facts require a value.")
        if selected_state is EvidenceState.ABSENT and (
            self.value is not None or not self.affirmative_basis
        ):
            raise T09ValidationError("ABSENT source facts require affirmative provenance.")
        if selected_state is EvidenceState.UNKNOWN and (
            self.value is not None or not self.unknown_reason
        ):
            raise T09ValidationError("UNKNOWN source facts require a reason.")
        if not (
            self.source_assertion_ids or self.source_digest or self.origin_id or self.provenance
        ):
            raise T09ValidationError("Source facts require source provenance.")
        _canonical_json(self.value) if selected_state is EvidenceState.OBSERVED else None
        object.__setattr__(self, "state", selected_state)
        object.__setattr__(self, "evidence_class", selected_class)
        object.__setattr__(self, "cutoff_eligibility", _eligibility(self.cutoff_eligibility))
        object.__setattr__(self, "freshness", _freshness_state(self.freshness))
        for name in (
            "published_at_utc",
            "observed_at_utc",
            "retrieved_at_utc",
            "event_time_utc",
            "effective_time_utc",
        ):
            object.__setattr__(self, name, _optional_utc(getattr(self, name)))
        assertion_ids = self.source_assertion_ids or (self.fact_id,)
        object.__setattr__(self, "source_assertion_ids", _sorted_unique(assertion_ids))
        object.__setattr__(self, "correlation_groups", _sorted_unique(self.correlation_groups))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def assertion_ids(self) -> tuple[str, ...]:
        return self.source_assertion_ids

    @property
    def is_cutoff_valid(self) -> bool:
        return self.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID

    def to_dict(self) -> dict[str, object]:
        return {
            "affirmative_basis": self.affirmative_basis,
            "age_seconds_at_cutoff": self.age_seconds_at_cutoff,
            "age_seconds_at_kickoff": self.age_seconds_at_kickoff,
            "authority_rank": self.authority_rank,
            "correlation_groups": self.correlation_groups,
            "cutoff_eligibility": _enum_value(self.cutoff_eligibility),
            "effective_time_utc": self.effective_time_utc,
            "event_time_utc": self.event_time_utc,
            "evidence_class": _enum_value(self.evidence_class),
            "evidence_type": self.evidence_type,
            "fact_id": self.fact_id,
            "freshness": _enum_value(self.freshness),
            "observed_at_utc": self.observed_at_utc,
            "origin_id": self.origin_id,
            "predicate": self.predicate,
            "provenance": dict(self.provenance),
            "published_at_utc": self.published_at_utc,
            "retrieved_at_utc": self.retrieved_at_utc,
            "source_assertion_ids": self.source_assertion_ids,
            "source_digest": self.source_digest,
            "source_key": self.source_key,
            "source_row_key": self.source_row_key,
            "state": _enum_value(self.state),
            "subject_id": self.subject_id,
            "unknown_reason": self.unknown_reason,
            "value": self.value,
        }


SourceAssertion = SourceFact
EvidenceFact = SourceFact


@dataclass(frozen=True)
class ResearchAttempt:
    requirement_id: str
    category: str
    source_key: str
    attempted_at_utc: str
    accessibility: AccessState | str = AccessState.ACCESSIBLE
    outcome: EvidenceState | str = EvidenceState.UNKNOWN
    performed: bool = True
    reason: str = ""
    could_change_decision: bool = False
    source_assertion_ids: tuple[str, ...] = ()
    cutoff_eligibility: CutoffEligibility | str = CutoffEligibility.CUTOFF_VALID

    def __post_init__(self) -> None:
        _text(self.requirement_id, "Research attempt requirement ID")
        _text(self.category, "Research attempt category")
        _text(self.source_key, "Research attempt source key")
        object.__setattr__(self, "attempted_at_utc", _canonical_utc(self.attempted_at_utc))
        object.__setattr__(self, "cutoff_eligibility", _eligibility(self.cutoff_eligibility))
        object.__setattr__(self, "accessibility", _access_state(self.accessibility))
        object.__setattr__(self, "outcome", _state(self.outcome))
        object.__setattr__(self, "source_assertion_ids", _sorted_unique(self.source_assertion_ids))

    @property
    def successful_attempt(self) -> bool:
        return (
            self.performed
            and self.accessibility is AccessState.ACCESSIBLE
            and self.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "accessibility": _enum_value(self.accessibility),
            "attempted_at_utc": self.attempted_at_utc,
            "category": self.category,
            "could_change_decision": self.could_change_decision,
            "cutoff_eligibility": _enum_value(self.cutoff_eligibility),
            "outcome": _enum_value(self.outcome),
            "performed": self.performed,
            "reason": self.reason,
            "requirement_id": self.requirement_id,
            "source_assertion_ids": self.source_assertion_ids,
            "source_key": self.source_key,
        }


@dataclass(frozen=True)
class MaterialScenario:
    scenario_id: str
    family: str
    requirement_id: str
    description: str
    could_change_acceptance: bool = True
    evidence_fact_ids: tuple[str, ...] = ()
    state: EvidenceState | str = EvidenceState.UNKNOWN

    def __post_init__(self) -> None:
        _text(self.scenario_id, "Material scenario ID")
        object.__setattr__(self, "family", normalize_family(self.family))
        _text(self.requirement_id, "Material scenario requirement ID")
        _text(self.description, "Material scenario description")
        object.__setattr__(self, "state", _state(self.state))
        object.__setattr__(self, "evidence_fact_ids", _sorted_unique(self.evidence_fact_ids))

    def to_dict(self) -> dict[str, object]:
        return {
            "could_change_acceptance": self.could_change_acceptance,
            "description": self.description,
            "evidence_fact_ids": self.evidence_fact_ids,
            "family": self.family,
            "requirement_id": self.requirement_id,
            "scenario_id": self.scenario_id,
            "state": _enum_value(self.state),
        }


@dataclass(frozen=True)
class DerivedFeature:
    feature_id: str
    name: str
    state: EvidenceState | str
    value: object | None
    method_version: str
    input_ids: tuple[str, ...]
    input_digests: tuple[str, ...] = ()
    family: str | None = None
    applicability: str = "APPLICABLE"
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    time_scope: Mapping[str, object] = field(default_factory=dict)
    adjustment_state: str = "NONE"
    correlation_groups: tuple[str, ...] = ()
    reason: str | None = None
    digest: str = ""

    def __post_init__(self) -> None:
        _text(self.feature_id, "Derived Feature ID")
        _text(self.name, "Derived Feature name")
        object.__setattr__(self, "state", _state(self.state))
        if self.state is EvidenceState.OBSERVED and self.value is None:
            raise T09ValidationError("Observed Derived Features require a value.")
        if self.state is not EvidenceState.OBSERVED and self.value is not None:
            _canonical_json(self.value)
        object.__setattr__(self, "input_ids", _sorted_unique(self.input_ids))
        object.__setattr__(self, "input_digests", _sorted_unique(self.input_digests))
        object.__setattr__(self, "uncertainty", MappingProxyType(dict(self.uncertainty)))
        object.__setattr__(self, "time_scope", MappingProxyType(dict(self.time_scope)))
        object.__setattr__(self, "correlation_groups", _sorted_unique(self.correlation_groups))
        expected = _digest(self._payload())
        if self.digest and self.digest != expected:
            raise T09IntegrityError(f"Derived Feature {self.feature_id} has a digest mismatch.")
        object.__setattr__(self, "digest", expected)

    @property
    def lineage(self) -> tuple[str, ...]:
        return self.input_ids

    @property
    def input_lineage(self) -> tuple[str, ...]:
        return self.input_ids

    def _payload(self) -> dict[str, object]:
        return {
            "adjustment_state": self.adjustment_state,
            "applicability": self.applicability,
            "correlation_groups": self.correlation_groups,
            "family": self.family,
            "feature_id": self.feature_id,
            "input_digests": self.input_digests,
            "input_ids": self.input_ids,
            "method_version": self.method_version,
            "name": self.name,
            "reason": self.reason,
            "state": _enum_value(self.state),
            "time_scope": dict(self.time_scope),
            "uncertainty": dict(self.uncertainty),
            "value": self.value,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class MaterialConflict:
    conflict_id: str
    subject_id: str
    evidence_type: str
    predicate: str
    assertion_ids: tuple[str, ...]
    values: tuple[object, ...]
    status: str = "UNRESOLVED"
    selected_assertion_id: str | None = None
    resolution_basis: tuple[str, ...] = ()
    rationale: str | None = None
    material: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertion_ids", _sorted_unique(self.assertion_ids))
        object.__setattr__(self, "resolution_basis", _sorted_unique(self.resolution_basis))
        if self.status not in {"UNRESOLVED", "RESOLVED"}:
            raise T09ValidationError("T09 conflict status must be RESOLVED or UNRESOLVED.")

    def to_dict(self) -> dict[str, object]:
        return {
            "assertion_ids": self.assertion_ids,
            "conflict_id": self.conflict_id,
            "evidence_type": self.evidence_type,
            "material": self.material,
            "predicate": self.predicate,
            "rationale": self.rationale,
            "resolution_basis": self.resolution_basis,
            "selected_assertion_id": self.selected_assertion_id,
            "status": self.status,
            "subject_id": self.subject_id,
            "values": self.values,
        }


@dataclass(frozen=True)
class IndependentCorroboration:
    subject_id: str
    evidence_type: str
    predicate: str
    value: object
    origin_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    correlated_assertion_ids: tuple[str, ...] = ()
    correlation_groups: tuple[str, ...] = ()

    @property
    def independent_origin_count(self) -> int:
        return len(self.origin_ids)

    @property
    def count(self) -> int:
        return self.independent_origin_count

    @property
    def effective_confirmation_count(self) -> int:
        return self.independent_origin_count

    def to_dict(self) -> dict[str, object]:
        return {
            "assertion_ids": self.assertion_ids,
            "correlated_assertion_ids": self.correlated_assertion_ids,
            "correlation_groups": self.correlation_groups,
            "evidence_type": self.evidence_type,
            "origin_ids": self.origin_ids,
            "predicate": self.predicate,
            "subject_id": self.subject_id,
            "value": self.value,
        }


@dataclass(frozen=True)
class RequirementEvaluation:
    family: str
    requirement_id: str
    mandatory_research: bool
    catalog_class: EvidenceClass
    influence: Influence
    conditional_critical: bool
    state: EvidenceState
    status: CoverageState
    covered: bool
    blocks_family: bool
    input_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    reason: str = ""
    freshness: FreshnessState = FreshnessState.UNKNOWN
    age_seconds_at_cutoff: float | None = None
    age_seconds_at_kickoff: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", normalize_family(self.family))
        object.__setattr__(self, "input_ids", _sorted_unique(self.input_ids))
        object.__setattr__(self, "gap_ids", _sorted_unique(self.gap_ids))
        if self.status is CoverageState.COVERED and not self.covered:
            raise T09ValidationError("Covered Evidence Requirements must be marked covered.")

    def to_dict(self) -> dict[str, object]:
        return {
            "age_seconds_at_cutoff": self.age_seconds_at_cutoff,
            "age_seconds_at_kickoff": self.age_seconds_at_kickoff,
            "blocks_family": self.blocks_family,
            "catalog_class": self.catalog_class.value,
            "conditional_critical": self.conditional_critical,
            "covered": self.covered,
            "family": self.family,
            "freshness": _enum_value(self.freshness),
            "gap_ids": self.gap_ids,
            "influence": self.influence.value,
            "input_ids": self.input_ids,
            "mandatory_research": self.mandatory_research,
            "reason": self.reason,
            "requirement_id": self.requirement_id,
            "state": _enum_value(self.state),
            "status": self.status.value,
        }


@dataclass(frozen=True)
class EvidenceGap:
    gap_id: str
    family: str
    requirement_id: str
    state: EvidenceState
    reason: str
    materiality: EvidenceClass
    accessibility: AccessState
    attempted_source_keys: tuple[str, ...] = ()
    decision_materiality: bool = False
    conditional_critical: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", normalize_family(self.family))
        object.__setattr__(
            self, "attempted_source_keys", _sorted_unique(self.attempted_source_keys)
        )

    @property
    def blocks_family(self) -> bool:
        return self.materiality is EvidenceClass.CRITICAL or self.conditional_critical

    def to_dict(self) -> dict[str, object]:
        return {
            "accessibility": _enum_value(self.accessibility),
            "attempted_source_keys": self.attempted_source_keys,
            "conditional_critical": self.conditional_critical,
            "decision_materiality": self.decision_materiality,
            "family": self.family,
            "gap_id": self.gap_id,
            "materiality": self.materiality.value,
            "reason": self.reason,
            "requirement_id": self.requirement_id,
            "state": _enum_value(self.state),
        }


@dataclass(frozen=True)
class CriticalEvidenceCoverage:
    family: str
    required_requirement_ids: tuple[str, ...]
    covered_requirement_ids: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...]
    conditional_requirements: tuple[str, ...] = ()
    coverage_ratio: float = 0.0
    complete: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", normalize_family(self.family))
        for name in (
            "required_requirement_ids",
            "covered_requirement_ids",
            "missing_requirement_ids",
            "conditional_requirements",
        ):
            object.__setattr__(self, name, _sorted_unique(getattr(self, name)))
        expected = (
            len(self.covered_requirement_ids) / len(self.required_requirement_ids)
            if self.required_requirement_ids
            else 1.0
        )
        if abs(self.coverage_ratio - expected) > 1e-9:
            raise T09ValidationError("Critical Evidence coverage ratio is inconsistent.")
        if self.complete != (not self.missing_requirement_ids):
            raise T09ValidationError("Critical Evidence coverage completeness is inconsistent.")

    @property
    def covered(self) -> int:
        return len(self.covered_requirement_ids)

    @property
    def required(self) -> int:
        return len(self.required_requirement_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "conditional_requirements": self.conditional_requirements,
            "coverage_ratio": self.coverage_ratio,
            "covered_requirement_ids": self.covered_requirement_ids,
            "family": self.family,
            "missing_requirement_ids": self.missing_requirement_ids,
            "required_requirement_ids": self.required_requirement_ids,
        }


@dataclass(frozen=True)
class ResearchSufficiency:
    family: str
    status: ResearchStatus
    mandatory_research_complete: bool
    critical_evidence_complete: bool
    optional_research_complete: bool
    diminishing_returns_reached: bool
    model_unavailable: bool
    unresolved_material_conflicts: int
    missing_important_requirement_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", normalize_family(self.family))
        object.__setattr__(
            self,
            "missing_important_requirement_ids",
            _sorted_unique(self.missing_important_requirement_ids),
        )
        object.__setattr__(self, "reasons", _sorted_unique(self.reasons))

    @property
    def complete(self) -> bool:
        return self.status is ResearchStatus.SUFFICIENT

    @property
    def sufficient(self) -> bool:
        return self.complete

    def to_dict(self) -> dict[str, object]:
        return {
            "critical_evidence_complete": self.critical_evidence_complete,
            "diminishing_returns_reached": self.diminishing_returns_reached,
            "family": self.family,
            "mandatory_research_complete": self.mandatory_research_complete,
            "missing_important_requirement_ids": self.missing_important_requirement_ids,
            "model_unavailable": self.model_unavailable,
            "optional_research_complete": self.optional_research_complete,
            "reasons": self.reasons,
            "status": self.status.value,
            "unresolved_material_conflicts": self.unresolved_material_conflicts,
        }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


def _enum_value(value: object) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _workload_id(value: object) -> str | None:
    mapped = _as_mapping(value)
    if mapped is not None:
        for key in ("workload_evidence_id", "evidence_id", "id"):
            selected = mapped.get(key)
            if isinstance(selected, str) and selected:
                return selected
    selected = getattr(value, "workload_evidence_id", None)
    return selected if isinstance(selected, str) and selected else None


def _weather_id(value: object) -> str | None:
    mapped = _as_mapping(value)
    if mapped is not None:
        for key in ("weather_evidence_id", "evidence_id", "id"):
            selected = mapped.get(key)
            if isinstance(selected, str) and selected:
                return selected
    selected = getattr(value, "weather_evidence_id", None)
    return selected if isinstance(selected, str) and selected else None


@dataclass(frozen=True)
class EvidenceResearchInput:
    """All facts available to the T09 research seam for one Target Match."""

    target: TargetMatch
    history: tuple[HistoricalMatch, ...] = ()
    source_assertions: tuple[SourceFact | EvidenceAssertionRecord | Mapping[str, object], ...] = ()
    workload: object | None = None
    weather: object | None = None
    mandatory_research: tuple[ResearchAttempt, ...] | None = None
    mandatory_research_performed: bool | None = None
    material_scenarios: tuple[MaterialScenario, ...] = ()
    model_availability: Mapping[str, bool] = field(default_factory=dict)
    baselines: Mapping[str, object] = field(default_factory=dict)
    history_complete: bool = True
    history_gaps: tuple[str, ...] = ()
    h2h_cited: bool = False
    last_material_event_by_team: Mapping[str, str] = field(default_factory=dict)
    conflict_resolutions: Mapping[str, object] = field(default_factory=dict)
    reproducibility: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetMatch):
            raise T09ValidationError("Evidence Research requires a TargetMatch.")
        if not all(isinstance(item, HistoricalMatch) for item in self.history):
            raise T09ValidationError("Structured history must contain HistoricalMatch records.")
        if self.mandatory_research is not None and not all(
            isinstance(item, ResearchAttempt) for item in self.mandatory_research
        ):
            raise T09ValidationError("Mandatory Research must contain ResearchAttempt records.")
        if not all(isinstance(item, MaterialScenario) for item in self.material_scenarios):
            raise T09ValidationError("Material scenarios must contain MaterialScenario records.")
        object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(self, "source_assertions", tuple(self.source_assertions))
        object.__setattr__(self, "material_scenarios", tuple(self.material_scenarios))
        object.__setattr__(
            self, "model_availability", MappingProxyType(dict(self.model_availability))
        )
        object.__setattr__(self, "baselines", MappingProxyType(dict(self.baselines)))
        object.__setattr__(self, "history_gaps", _sorted_unique(self.history_gaps))
        object.__setattr__(
            self,
            "last_material_event_by_team",
            MappingProxyType(dict(self.last_material_event_by_team)),
        )
        object.__setattr__(
            self, "conflict_resolutions", MappingProxyType(dict(self.conflict_resolutions))
        )
        object.__setattr__(self, "reproducibility", MappingProxyType(dict(self.reproducibility)))


EvidenceResearchRequest = EvidenceResearchInput
ResearchInput = EvidenceResearchInput


@dataclass(frozen=True)
class FrozenEvidenceState:
    """Immutable, cutoff-frozen T09 evidence for one Target Match."""

    state_id: str
    target: TargetMatch
    source_assertions: tuple[SourceFact, ...]
    post_cutoff_assertions: tuple[SourceFact, ...]
    research_attempts: tuple[ResearchAttempt, ...]
    requirement_evaluations: tuple[RequirementEvaluation, ...]
    gaps: tuple[EvidenceGap, ...]
    conflicts: tuple[MaterialConflict, ...]
    corroboration: tuple[IndependentCorroboration, ...]
    derived_features: tuple[DerivedFeature, ...]
    critical_evidence_coverage: Mapping[str, CriticalEvidenceCoverage]
    research_sufficiency: Mapping[str, ResearchSufficiency]
    material_scenarios: tuple[MaterialScenario, ...] = ()
    catalog_name: str = CATALOG_NAME
    catalog_version: str = CATALOG_VERSION
    catalog_digest: str = CATALOG_DIGEST
    feature_rules_name: str = "t09-feature-rules-v1"
    feature_rules_digest: str = ""
    research_rules_name: str = RESEARCH_RULES_NAME
    research_rules_digest: str = ""
    reproducibility: Mapping[str, object] = field(default_factory=dict)
    state_digest: str = ""
    artifact_digest: str | None = None
    manifest_digest: str | None = None
    frozen_at_utc: str | None = None

    def __post_init__(self) -> None:
        _text(self.state_id, "Frozen Evidence State ID")
        if not isinstance(self.target, TargetMatch):
            raise T09ValidationError("Frozen Evidence States require a TargetMatch.")
        if self.catalog_version != CATALOG_VERSION or self.catalog_digest != CATALOG_DIGEST:
            raise T09ValidationError("Frozen Evidence States require the immutable catalog v1.")
        if not all(isinstance(item, SourceFact) for item in self.source_assertions):
            raise T09ValidationError("Frozen source assertions must be SourceFact records.")
        if not all(isinstance(item, SourceFact) for item in self.post_cutoff_assertions):
            raise T09ValidationError("Excluded assertions must be SourceFact records.")
        if any(not item.is_cutoff_valid for item in self.source_assertions):
            raise T09ValidationError("Frozen source assertions must be CUTOFF_VALID.")
        if any(item.is_cutoff_valid for item in self.post_cutoff_assertions):
            raise T09ValidationError("Excluded assertions cannot be CUTOFF_VALID.")
        if not all(isinstance(item, MaterialScenario) for item in self.material_scenarios):
            raise T09ValidationError("Frozen scenarios must be MaterialScenario records.")
        for name, values in (
            ("research_attempts", self.research_attempts),
            ("requirement_evaluations", self.requirement_evaluations),
            ("gaps", self.gaps),
            ("conflicts", self.conflicts),
            ("corroboration", self.corroboration),
            ("derived_features", self.derived_features),
        ):
            if not isinstance(values, tuple):
                object.__setattr__(self, name, tuple(values))
        normalized_coverage = {
            normalize_family(str(key)): value
            for key, value in self.critical_evidence_coverage.items()
        }
        normalized_sufficiency = {
            normalize_family(str(key)): value for key, value in self.research_sufficiency.items()
        }
        object.__setattr__(
            self,
            "source_assertions",
            tuple(sorted(self.source_assertions, key=lambda item: item.fact_id)),
        )
        object.__setattr__(
            self,
            "post_cutoff_assertions",
            tuple(sorted(self.post_cutoff_assertions, key=lambda item: item.fact_id)),
        )
        object.__setattr__(
            self,
            "research_attempts",
            tuple(
                sorted(
                    self.research_attempts, key=lambda item: (item.requirement_id, item.source_key)
                )
            ),
        )
        object.__setattr__(
            self,
            "requirement_evaluations",
            tuple(
                sorted(
                    self.requirement_evaluations,
                    key=lambda item: (item.family, item.requirement_id),
                )
            ),
        )
        object.__setattr__(self, "gaps", tuple(sorted(self.gaps, key=lambda item: item.gap_id)))
        object.__setattr__(
            self, "conflicts", tuple(sorted(self.conflicts, key=lambda item: item.conflict_id))
        )
        object.__setattr__(
            self,
            "corroboration",
            tuple(
                sorted(
                    self.corroboration,
                    key=lambda item: (
                        item.subject_id,
                        item.evidence_type,
                        item.predicate,
                        _canonical_json(item.value),
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "derived_features",
            tuple(sorted(self.derived_features, key=lambda item: item.feature_id)),
        )
        object.__setattr__(
            self,
            "material_scenarios",
            tuple(
                sorted(
                    self.material_scenarios,
                    key=lambda item: (item.family, item.requirement_id, item.scenario_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "critical_evidence_coverage",
            MappingProxyType(dict(sorted(normalized_coverage.items()))),
        )
        object.__setattr__(
            self,
            "research_sufficiency",
            MappingProxyType(dict(sorted(normalized_sufficiency.items()))),
        )
        object.__setattr__(self, "reproducibility", MappingProxyType(dict(self.reproducibility)))
        if self.frozen_at_utc is not None:
            object.__setattr__(self, "frozen_at_utc", _canonical_utc(self.frozen_at_utc))
        expected = _digest(self._core_dict(include_digest=False))
        if self.state_digest and self.state_digest != expected:
            raise T09IntegrityError(f"Frozen Evidence State {self.state_id} has a digest mismatch.")
        object.__setattr__(self, "state_digest", expected)

    @property
    def digest(self) -> str:
        return self.state_digest

    @property
    def target_fixture_id(self) -> str:
        return self.target.fixture_id

    @property
    def matchweek_id(self) -> str:
        return self.target.matchweek_id

    @property
    def cutoff_id(self) -> str:
        return self.target.cutoff_id

    @property
    def cutoff_utc(self) -> str:
        return self.target.cutoff_utc

    @property
    def source_facts(self) -> tuple[SourceFact, ...]:
        return self.source_assertions

    @property
    def excluded_source_assertions(self) -> tuple[SourceFact, ...]:
        return self.post_cutoff_assertions

    @property
    def critical_coverage(self) -> Mapping[str, CriticalEvidenceCoverage]:
        return self.critical_evidence_coverage

    @property
    def sufficiency(self) -> Mapping[str, ResearchSufficiency]:
        return self.research_sufficiency

    @property
    def safe_for_decision(self) -> bool:
        return bool(self.research_sufficiency) and all(
            item.status is ResearchStatus.SUFFICIENT for item in self.research_sufficiency.values()
        )

    @property
    def is_frozen(self) -> bool:
        return self.artifact_digest is not None and self.manifest_digest is not None

    def _core_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "catalog_digest": self.catalog_digest,
            "catalog_name": self.catalog_name,
            "catalog_version": self.catalog_version,
            "conflicts": [item.to_dict() for item in self.conflicts],
            "corroboration": [item.to_dict() for item in self.corroboration],
            "critical_evidence_coverage": {
                key: value.to_dict() for key, value in self.critical_evidence_coverage.items()
            },
            "derived_features": [item.to_dict() for item in self.derived_features],
            "feature_rules_digest": self.feature_rules_digest,
            "feature_rules_name": self.feature_rules_name,
            "gaps": [item.to_dict() for item in self.gaps],
            "material_scenarios": [item.to_dict() for item in self.material_scenarios],
            "research_attempts": [item.to_dict() for item in self.research_attempts],
            "research_rules_digest": self.research_rules_digest,
            "research_rules_name": self.research_rules_name,
            "research_sufficiency": {
                key: value.to_dict() for key, value in self.research_sufficiency.items()
            },
            "reproducibility": {
                key: item
                for key, item in self.reproducibility.items()
                if key != "post_cutoff_excluded_fact_ids"
            },
            "requirement_evaluations": [item.to_dict() for item in self.requirement_evaluations],
            "source_assertions": [item.to_dict() for item in self.source_assertions],
            "state_id": self.state_id,
            "target": self.target.to_dict(),
        }
        if include_digest:
            payload["state_digest"] = self.state_digest
        return payload

    def to_dict(self, *, include_publication: bool = True) -> dict[str, object]:
        payload = self._core_dict()
        payload["post_cutoff_assertions"] = [item.to_dict() for item in self.post_cutoff_assertions]
        payload["post_cutoff_excluded_fact_ids"] = tuple(
            item.fact_id for item in self.post_cutoff_assertions
        )
        if include_publication:
            payload.update(
                {
                    "artifact_digest": self.artifact_digest,
                    "frozen_at_utc": self.frozen_at_utc,
                    "manifest_digest": self.manifest_digest,
                }
            )
        return payload

    def to_bytes(self) -> bytes:
        return _canonical_json(self.to_dict(include_publication=False))

    def with_freeze_refs(
        self,
        *,
        artifact_digest: str,
        manifest_digest: str,
        frozen_at_utc: str,
    ) -> FrozenEvidenceState:
        return replace(
            self,
            artifact_digest=artifact_digest,
            manifest_digest=manifest_digest,
            frozen_at_utc=frozen_at_utc,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FrozenEvidenceState:
        target_value = value.get("target")
        if not isinstance(target_value, Mapping):
            raise T09ValidationError("Stored Evidence State target is malformed.")

        def source(item: object) -> SourceFact:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Evidence State source assertion is malformed.")
            return _mapping_source_fact(item)

        def attempt(item: object) -> ResearchAttempt:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Research Attempt is malformed.")
            return ResearchAttempt(
                requirement_id=_text(item.get("requirement_id"), "Research attempt requirement ID"),
                category=_text(item.get("category"), "Research attempt category"),
                source_key=_text(item.get("source_key"), "Research attempt source key"),
                attempted_at_utc=_text(item.get("attempted_at_utc"), "Research attempt timestamp"),
                cutoff_eligibility=str(item.get("cutoff_eligibility", "CUTOFF_VALID")),
                accessibility=str(item.get("accessibility", "ACCESSIBLE")),
                outcome=str(item.get("outcome", "UNKNOWN")),
                performed=bool(item.get("performed", True)),
                reason=str(item.get("reason", "")),
                could_change_decision=bool(item.get("could_change_decision", False)),
                source_assertion_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("source_assertion_ids", ()))
                    if isinstance(item_id, str)
                ),
            )

        def evaluation(item: object) -> RequirementEvaluation:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Requirement Evaluation is malformed.")
            return RequirementEvaluation(
                family=_text(item.get("family"), "Requirement family"),
                requirement_id=_text(item.get("requirement_id"), "Requirement ID"),
                mandatory_research=bool(item.get("mandatory_research", False)),
                catalog_class=EvidenceClass(str(item.get("catalog_class", "CONTEXT"))),
                influence=Influence(str(item.get("influence", "CONTEXT"))),
                conditional_critical=bool(item.get("conditional_critical", False)),
                state=_state(str(item.get("state", "UNKNOWN"))),
                status=CoverageState(str(item.get("status", "UNKNOWN"))),
                covered=bool(item.get("covered", False)),
                blocks_family=bool(item.get("blocks_family", False)),
                input_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("input_ids", ()))
                    if isinstance(item_id, str)
                ),
                gap_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("gap_ids", ()))
                    if isinstance(item_id, str)
                ),
                reason=str(item.get("reason", "")),
                freshness=FreshnessState(str(item.get("freshness", "UNKNOWN"))),
                age_seconds_at_cutoff=_numeric(item.get("age_seconds_at_cutoff")),
                age_seconds_at_kickoff=_numeric(item.get("age_seconds_at_kickoff")),
            )

        def gap(item: object) -> EvidenceGap:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Evidence Gap is malformed.")
            return EvidenceGap(
                gap_id=_text(item.get("gap_id"), "Evidence Gap ID"),
                family=_text(item.get("family"), "Evidence Gap family"),
                requirement_id=_text(item.get("requirement_id"), "Evidence Gap requirement ID"),
                state=_state(str(item.get("state", "UNKNOWN"))),
                reason=_text(item.get("reason"), "Evidence Gap reason"),
                materiality=EvidenceClass(str(item.get("materiality", "CONTEXT"))),
                accessibility=AccessState(str(item.get("accessibility", "NOT_ATTEMPTED"))),
                attempted_source_keys=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("attempted_source_keys", ()))
                    if isinstance(item_id, str)
                ),
                decision_materiality=bool(item.get("decision_materiality", False)),
                conditional_critical=bool(item.get("conditional_critical", False)),
            )

        def scenario(item: object) -> MaterialScenario:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Material Scenario is malformed.")
            return MaterialScenario(
                scenario_id=_text(item.get("scenario_id"), "Material Scenario ID"),
                family=_text(item.get("family"), "Material Scenario family"),
                requirement_id=_text(
                    item.get("requirement_id"), "Material Scenario requirement ID"
                ),
                description=_text(item.get("description"), "Material Scenario description"),
                could_change_acceptance=bool(item.get("could_change_acceptance", True)),
                evidence_fact_ids=_string_tuple(item.get("evidence_fact_ids", ())),
                state=_state(str(item.get("state", "UNKNOWN"))),
            )

        def feature(item: object) -> DerivedFeature:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Derived Feature is malformed.")
            return DerivedFeature(
                feature_id=_text(item.get("feature_id"), "Derived Feature ID"),
                name=_text(item.get("name"), "Derived Feature name"),
                state=_state(str(item.get("state", "UNKNOWN"))),
                value=item.get("value"),
                method_version=_text(item.get("method_version"), "Feature method version"),
                input_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("input_ids", ()))
                    if isinstance(item_id, str)
                ),
                input_digests=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("input_digests", ()))
                    if isinstance(item_id, str)
                ),
                family=item.get("family") if isinstance(item.get("family"), str) else None,
                applicability=str(item.get("applicability", "APPLICABLE")),
                uncertainty=_as_mapping(item.get("uncertainty", {})) or {},
                time_scope=_as_mapping(item.get("time_scope", {})) or {},
                adjustment_state=str(item.get("adjustment_state", "NONE")),
                correlation_groups=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("correlation_groups", ()))
                    if isinstance(item_id, str)
                ),
                reason=item.get("reason") if isinstance(item.get("reason"), str) else None,
                digest=str(item.get("digest", "")),
            )

        def conflict(item: object) -> MaterialConflict:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Material Conflict is malformed.")
            return MaterialConflict(
                conflict_id=_text(item.get("conflict_id"), "Material Conflict ID"),
                subject_id=_text(item.get("subject_id"), "Material Conflict subject ID"),
                evidence_type=_text(item.get("evidence_type"), "Material Conflict evidence type"),
                predicate=_text(item.get("predicate"), "Material Conflict predicate"),
                assertion_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("assertion_ids", ()))
                    if isinstance(item_id, str)
                ),
                values=tuple(_as_sequence(item.get("values", ()))),
                status=str(item.get("status", "UNRESOLVED")),
                selected_assertion_id=item.get("selected_assertion_id")
                if isinstance(item.get("selected_assertion_id"), str)
                else None,
                resolution_basis=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("resolution_basis", ()))
                    if isinstance(item_id, str)
                ),
                rationale=item.get("rationale") if isinstance(item.get("rationale"), str) else None,
                material=bool(item.get("material", True)),
            )

        def corroborated(item: object) -> IndependentCorroboration:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Corroboration is malformed.")
            return IndependentCorroboration(
                subject_id=_text(item.get("subject_id"), "Corroboration subject ID"),
                evidence_type=_text(item.get("evidence_type"), "Corroboration evidence type"),
                predicate=_text(item.get("predicate"), "Corroboration predicate"),
                value=item.get("value"),
                origin_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("origin_ids", ()))
                    if isinstance(item_id, str)
                ),
                assertion_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("assertion_ids", ()))
                    if isinstance(item_id, str)
                ),
                correlated_assertion_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("correlated_assertion_ids", ()))
                    if isinstance(item_id, str)
                ),
                correlation_groups=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("correlation_groups", ()))
                    if isinstance(item_id, str)
                ),
            )

        def coverage_item(item: object) -> CriticalEvidenceCoverage:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Critical Evidence coverage is malformed.")
            required = tuple(
                item_id
                for item_id in _as_sequence(item.get("required_requirement_ids", ()))
                if isinstance(item_id, str)
            )
            covered = tuple(
                item_id
                for item_id in _as_sequence(item.get("covered_requirement_ids", ()))
                if isinstance(item_id, str)
            )
            missing = tuple(
                item_id
                for item_id in _as_sequence(item.get("missing_requirement_ids", ()))
                if isinstance(item_id, str)
            )
            conditional = tuple(
                item_id
                for item_id in _as_sequence(item.get("conditional_requirements", ()))
                if isinstance(item_id, str)
            )
            return CriticalEvidenceCoverage(
                family=_text(item.get("family"), "Coverage family"),
                required_requirement_ids=required,
                covered_requirement_ids=covered,
                missing_requirement_ids=missing,
                conditional_requirements=conditional,
                coverage_ratio=float(item.get("coverage_ratio", 0.0)),
                complete=bool(item.get("complete", False)),
            )

        def sufficiency_item(item: object) -> ResearchSufficiency:
            if not isinstance(item, Mapping):
                raise T09ValidationError("Stored Research Sufficiency is malformed.")
            return ResearchSufficiency(
                family=_text(item.get("family"), "Sufficiency family"),
                status=ResearchStatus(str(item.get("status", "INSUFFICIENT"))),
                mandatory_research_complete=bool(item.get("mandatory_research_complete", False)),
                critical_evidence_complete=bool(item.get("critical_evidence_complete", False)),
                optional_research_complete=bool(item.get("optional_research_complete", False)),
                diminishing_returns_reached=bool(item.get("diminishing_returns_reached", False)),
                model_unavailable=bool(item.get("model_unavailable", False)),
                unresolved_material_conflicts=int(item.get("unresolved_material_conflicts", 0)),
                missing_important_requirement_ids=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("missing_important_requirement_ids", ()))
                    if isinstance(item_id, str)
                ),
                reasons=tuple(
                    item_id
                    for item_id in _as_sequence(item.get("reasons", ()))
                    if isinstance(item_id, str)
                ),
            )

        coverage_raw = value.get("critical_evidence_coverage", {})
        sufficiency_raw = value.get("research_sufficiency", {})
        if not isinstance(coverage_raw, Mapping) or not isinstance(sufficiency_raw, Mapping):
            raise T09ValidationError("Stored Evidence State coverage maps are malformed.")
        return cls(
            state_id=_text(value.get("state_id"), "Frozen Evidence State ID"),
            target=TargetMatch(**cast(dict[str, Any], dict(target_value))),
            source_assertions=tuple(
                source(item) for item in _as_sequence(value.get("source_assertions", ()))
            ),
            post_cutoff_assertions=tuple(
                source(item) for item in _as_sequence(value.get("post_cutoff_assertions", ()))
            ),
            research_attempts=tuple(
                attempt(item) for item in _as_sequence(value.get("research_attempts", ()))
            ),
            requirement_evaluations=tuple(
                evaluation(item) for item in _as_sequence(value.get("requirement_evaluations", ()))
            ),
            gaps=tuple(gap(item) for item in _as_sequence(value.get("gaps", ()))),
            conflicts=tuple(conflict(item) for item in _as_sequence(value.get("conflicts", ()))),
            corroboration=tuple(
                corroborated(item) for item in _as_sequence(value.get("corroboration", ()))
            ),
            derived_features=tuple(
                feature(item) for item in _as_sequence(value.get("derived_features", ()))
            ),
            material_scenarios=tuple(
                scenario(item) for item in _as_sequence(value.get("material_scenarios", ()))
            ),
            critical_evidence_coverage={
                str(key): coverage_item(item) for key, item in coverage_raw.items()
            },
            research_sufficiency={
                str(key): sufficiency_item(item) for key, item in sufficiency_raw.items()
            },
            catalog_name=str(value.get("catalog_name", CATALOG_NAME)),
            catalog_version=str(value.get("catalog_version", CATALOG_VERSION)),
            catalog_digest=str(value.get("catalog_digest", CATALOG_DIGEST)),
            feature_rules_name=str(value.get("feature_rules_name", "t09-feature-rules-v1")),
            feature_rules_digest=str(value.get("feature_rules_digest", "")),
            research_rules_name=str(value.get("research_rules_name", RESEARCH_RULES_NAME)),
            research_rules_digest=str(value.get("research_rules_digest", "")),
            reproducibility=_as_mapping(value.get("reproducibility", {})) or {},
            state_digest=str(value.get("state_digest", "")),
            artifact_digest=_optional_text(value.get("artifact_digest")),
            manifest_digest=_optional_text(value.get("manifest_digest")),
            frozen_at_utc=_optional_text(value.get("frozen_at_utc")),
        )


FrozenState = FrozenEvidenceState
EvidenceStateRecord = FrozenEvidenceState
EvidenceResearchResult = FrozenEvidenceState


def _record_to_source_fact(record: EvidenceAssertionRecord) -> SourceFact:
    provenance = dict(record.provenance)
    source_key = provenance.get("source_key")
    if not isinstance(source_key, str) or not source_key:
        source_key = record.source_class
    source_digest = provenance.get("source_digest")
    return SourceFact(
        fact_id=record.assertion_id,
        subject_id=record.subject_id,
        evidence_type=record.evidence_type,
        predicate=record.predicate,
        state=record.state,
        value=record.value,
        evidence_class=record.evidence_class,
        source_key=source_key,
        origin_id=record.origin_id,
        source_assertion_ids=(record.assertion_id,),
        source_digest=source_digest if isinstance(source_digest, str) else None,
        published_at_utc=_optional_text(record.provenance.get("published_at_utc")),
        observed_at_utc=_optional_text(record.provenance.get("observed_at_utc")),
        retrieved_at_utc=_optional_text(record.provenance.get("retrieved_at_utc")),
        event_time_utc=record.event_time_utc,
        effective_time_utc=record.effective_time_utc,
        cutoff_eligibility=record.cutoff_eligibility,
        source_row_key=record.source_row_key,
        correlation_groups=(
            (str(record.provenance["correlation_group"]),)
            if record.provenance.get("correlation_group") is not None
            else ()
        ),
        unknown_reason=record.unknown_reason,
        affirmative_basis=record.affirmative_basis,
        authority_rank=record.authority_rank,
        provenance=record.provenance,
    )


def _mapping_source_fact(value: Mapping[str, object]) -> SourceFact:
    state = _state(cast(str, value.get("state", "UNKNOWN")))
    raw_assertions = value.get("source_assertion_ids", value.get("assertion_ids", ()))
    assertion_ids = tuple(item for item in _as_sequence(raw_assertions) if isinstance(item, str))
    source_key = value.get("source_key", value.get("source", "UNKNOWN"))
    source_key_text = str(source_key) if source_key is not None else "UNKNOWN"
    origin = value.get("origin_id", value.get("origin"))
    origin_id = str(origin) if isinstance(origin, str) else None
    return SourceFact(
        fact_id=_text(value.get("fact_id", value.get("assertion_id")), "Source Fact ID"),
        subject_id=_text(value.get("subject_id"), "Source Fact subject ID"),
        evidence_type=_text(value.get("evidence_type"), "Source Fact evidence type"),
        predicate=_text(value.get("predicate"), "Source Fact predicate"),
        state=state,
        value=value.get("value"),
        evidence_class=_enum_value(
            value.get("evidence_class", value.get("materiality", "CONTEXT"))
        ),
        source_key=source_key_text,
        origin_id=origin_id,
        source_assertion_ids=assertion_ids,
        source_digest=_optional_text(value.get("source_digest")),
        published_at_utc=_optional_text(value.get("published_at_utc")),
        observed_at_utc=_optional_text(value.get("observed_at_utc")),
        retrieved_at_utc=_optional_text(value.get("retrieved_at_utc")),
        event_time_utc=_optional_text(value.get("event_time_utc")),
        effective_time_utc=_optional_text(value.get("effective_time_utc")),
        cutoff_eligibility=_enum_value(value.get("cutoff_eligibility", "INDETERMINATE")),
        source_row_key=_optional_text(value.get("source_row_key")),
        correlation_groups=_string_tuple(value.get("correlation_groups", ())),
        unknown_reason=_optional_text(value.get("unknown_reason")),
        affirmative_basis=_optional_text(value.get("affirmative_basis")),
        authority_rank=_integer(value.get("authority_rank", 900), 900),
        provenance=_as_mapping(value.get("provenance", {})) or {},
        freshness=str(value.get("freshness", "UNKNOWN")),
        age_seconds_at_cutoff=_numeric(value.get("age_seconds_at_cutoff")),
        age_seconds_at_kickoff=_numeric(value.get("age_seconds_at_kickoff")),
    )


def _source_fact(value: SourceFact | EvidenceAssertionRecord | Mapping[str, object]) -> SourceFact:
    if isinstance(value, SourceFact):
        return value
    if isinstance(value, EvidenceAssertionRecord):
        return _record_to_source_fact(value)
    if isinstance(value, Mapping):
        return _mapping_source_fact(value)
    raise T09ValidationError(
        "Source assertions must be SourceFact or EvidenceAssertionRecord values."
    )


def _history_facts(
    history: Iterable[HistoricalMatch], target: TargetMatch
) -> tuple[SourceFact, ...]:
    facts: list[SourceFact] = []
    metric_classes = {
        "full_time_home_goals": EvidenceClass.CRITICAL,
        "full_time_away_goals": EvidenceClass.CRITICAL,
        "half_time_home_goals": EvidenceClass.CRITICAL,
        "half_time_away_goals": EvidenceClass.CRITICAL,
        "corners_home": EvidenceClass.CRITICAL,
        "corners_away": EvidenceClass.CRITICAL,
        "shots_home": EvidenceClass.IMPORTANT,
        "shots_away": EvidenceClass.IMPORTANT,
        "shots_on_target_home": EvidenceClass.IMPORTANT,
        "shots_on_target_away": EvidenceClass.IMPORTANT,
        "yellow_cards_home": EvidenceClass.IMPORTANT,
        "yellow_cards_away": EvidenceClass.IMPORTANT,
        "red_cards_home": EvidenceClass.IMPORTANT,
        "red_cards_away": EvidenceClass.IMPORTANT,
    }
    for match in history:
        eligibility = CutoffEligibility.CUTOFF_VALID
        timestamp_values = [match.kickoff_utc, match.observed_at_utc, match.published_at_utc]
        if any(
            value is not None and _parse_utc(value) > _parse_utc(target.cutoff_utc)
            for value in timestamp_values
        ):
            eligibility = CutoffEligibility.POST_CUTOFF
        for metric, value in match.metrics.items():
            final = (
                match.fixture_status in {"COMPLETED", "FINAL", "FINISHED"}
                and match.final_state is EvidenceState.OBSERVED
            )
            state = match.metric_state(metric) if final else EvidenceState.UNKNOWN
            source_value = value if state is EvidenceState.OBSERVED else None
            reason = (
                None
                if state is not EvidenceState.UNKNOWN
                else "STRUCTURED_METRIC_NOT_AVAILABLE"
                if final
                else "HISTORICAL_FIXTURE_NOT_FINAL"
            )
            basis = (
                None
                if state is not EvidenceState.ABSENT
                else "STRUCTURED_MATCH_RECORD_AFFIRMATIVELY_HAS_NO_METRIC"
            )
            facts.append(
                SourceFact(
                    fact_id=f"{match.fixture_id}:{metric}",
                    subject_id=match.fixture_id,
                    evidence_type="MATCH_STATISTIC",
                    predicate=metric,
                    state=state,
                    value=source_value,
                    evidence_class=metric_classes[metric],
                    source_key=match.source_key,
                    origin_id=match.origin_id,
                    source_assertion_ids=match.metric_ids(metric),
                    source_digest=match.source_digest or _digest(match.to_dict()),
                    observed_at_utc=match.observed_at_utc,
                    published_at_utc=match.published_at_utc,
                    event_time_utc=match.kickoff_utc,
                    cutoff_eligibility=eligibility,
                    correlation_groups=(
                        "goals/results"
                        if "goals" in metric
                        else "corners"
                        if "corners" in metric
                        else "shots/chances"
                        if "shots" in metric
                        else "discipline/match-state",
                    ),
                    unknown_reason=reason,
                    affirmative_basis=basis,
                    provenance={
                        "fixture_id": match.fixture_id,
                        "competition_key": match.competition_key,
                        "competition_type": match.competition_type,
                        "kickoff_utc": match.kickoff_utc,
                    },
                )
            )
    return tuple(facts)


def _object_dict(value: object | None) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): cast(object, item) for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return {str(key): cast(object, item) for key, item in result.items()}
    return None


def _fact_timestamp(fact: SourceFact) -> str | None:
    for value in (fact.published_at_utc, fact.observed_at_utc, fact.retrieved_at_utc):
        if value is not None:
            return value
    return fact.effective_time_utc or fact.event_time_utc


def _fact_key(fact: SourceFact) -> tuple[str, str, str]:
    return fact.subject_id, fact.evidence_type, fact.predicate


def _fact_value(fact: SourceFact) -> object:
    return {"state": _enum_value(fact.state), "value": fact.value}


def _fact_value_digest(fact: SourceFact) -> str:
    return _digest(_fact_value(fact))


def _value_equal(left: object, right: object) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _canonicalize_embedded_times(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            selected = _canonicalize_embedded_times(item)
            if isinstance(key, str) and key.endswith("_utc") and isinstance(selected, str):
                selected = _canonical_utc(selected)
            result[str(key)] = selected
        return result
    if isinstance(value, (tuple, list)):
        return tuple(_canonicalize_embedded_times(item) for item in value)
    return value


def target_lineage(target: TargetMatch) -> tuple[str, ...]:
    return target.source_assertion_ids or (target.fixture_id,)


def _conflict_relevant_to_ids(conflict: MaterialConflict, input_ids: Iterable[str]) -> bool:
    return bool(set(conflict.assertion_ids).intersection(input_ids))


def _conflict_relevant(conflict: MaterialConflict, evaluation: RequirementEvaluation) -> bool:
    return _conflict_relevant_to_ids(conflict, evaluation.input_ids)


def _fact_is_known(fact: SourceFact) -> bool:
    return fact.state in {EvidenceState.OBSERVED, EvidenceState.ABSENT}


def _workload_payload(
    value: object | None,
) -> tuple[str | None, dict[str, object] | None, str, str | None]:
    mapped = _object_dict(value)
    if mapped is None:
        return None, None, "UNKNOWN", None
    identifier = _workload_id(value) or _workload_id(mapped)
    state = str(mapped.get("state", mapped.get("evidence_state", "UNKNOWN"))).upper()
    digest = mapped.get("evidence_digest", mapped.get("digest"))
    return identifier, mapped, state, digest if isinstance(digest, str) else None


def _weather_payload(value: object | None) -> tuple[str | None, dict[str, object] | None, str, str]:
    mapped = _object_dict(value)
    if mapped is None:
        return None, None, "UNKNOWN", "UNKNOWN"
    identifier = _weather_id(value) or _weather_id(mapped)
    state = str(mapped.get("state", mapped.get("evidence_state", "UNKNOWN"))).upper()
    eligibility = str(mapped.get("cutoff_eligibility", "INDETERMINATE")).upper()
    return identifier, mapped, state, eligibility


def _team_payload(mapped: Mapping[str, object], side: str) -> Mapping[str, object]:
    selected = mapped.get(side)
    return selected if isinstance(selected, Mapping) else {}


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _history_input_ids(
    history: Iterable[HistoricalMatch], metric_names: Iterable[str]
) -> tuple[str, ...]:
    selected = set(metric_names)
    return _sorted_unique(
        assertion_id
        for match in history
        for metric in selected
        for assertion_id in match.metric_ids(metric)
        if match.metric_state(metric) is not EvidenceState.UNKNOWN
    )


def _history_metric_values(
    history: Iterable[HistoricalMatch], team_id: str, metric: str
) -> tuple[tuple[float, str, tuple[str, ...], str], ...]:
    values: list[tuple[float, str, tuple[str, ...], str]] = []
    for match in history:
        if match.home_team_id == team_id:
            selected = metric
            value = match.metrics.get(metric)
        elif match.away_team_id == team_id:
            selected = (
                metric.replace("_home", "_away")
                if metric.endswith("_home")
                else metric.replace("_away", "_home")
            )
            value = match.metrics.get(selected)
        else:
            continue
        if match.metric_state(selected) is not EvidenceState.OBSERVED or _numeric(value) is None:
            continue
        values.append(
            (
                float(cast(int | float, value)),
                match.kickoff_utc,
                match.metric_ids(selected),
                match.fixture_id,
            )
        )
    return tuple(values)


def _make_feature(
    name: str,
    *,
    state: EvidenceState,
    value: object | None,
    input_ids: Iterable[str],
    input_digests: Iterable[str] = (),
    rules: FeatureRules,
    family: str | None = None,
    uncertainty: Mapping[str, object] | None = None,
    time_scope: Mapping[str, object] | None = None,
    adjustment_state: str = "NONE",
    correlation_groups: Iterable[str] = (),
    reason: str | None = None,
) -> DerivedFeature:
    ids = _sorted_unique(input_ids)
    return DerivedFeature(
        feature_id=f"{name}:{family or 'all'}",
        name=name,
        state=state,
        value=value,
        method_version=rules.name,
        input_ids=ids,
        input_digests=tuple(input_digests),
        family=family,
        uncertainty=uncertainty or {},
        time_scope=time_scope or {},
        adjustment_state=adjustment_state,
        correlation_groups=tuple(correlation_groups),
        reason=reason,
    )


class EvidenceResearcher:
    """Build a deterministic Evidence State without performing network research."""

    def __init__(
        self,
        *,
        catalog: EvidenceRequirementCatalog = DEFAULT_CATALOG,
        feature_rules: FeatureRules | None = None,
        research_rules_name: str = RESEARCH_RULES_NAME,
    ) -> None:
        if catalog.version != CATALOG_VERSION:
            raise T09ValidationError(
                f"T09 requires Evidence Requirement catalog version {CATALOG_VERSION}."
            )
        if catalog.digest != CATALOG_DIGEST:
            raise T09ValidationError("T09 requires the immutable Evidence catalog v1 digest.")
        self.catalog = catalog
        self.feature_rules = feature_rules or FeatureRules()
        self.research_rules_name = _text(research_rules_name, "Research rules name")
        self.research_rules_digest = _digest(
            {
                "catalog_digest": catalog.digest,
                "feature_rules_digest": self.feature_rules.digest,
                "name": self.research_rules_name,
                "minimum_history_matches": self.feature_rules.minimum_history_matches,
                "minimum_effective_history_matches": (
                    self.feature_rules.minimum_effective_history_matches
                ),
            }
        )

    def build(self, research_input: EvidenceResearchInput) -> FrozenEvidenceState:
        if not isinstance(research_input, EvidenceResearchInput):
            raise T09ValidationError("Evidence Research build requires EvidenceResearchInput.")
        target = research_input.target
        source_facts = self._source_facts(research_input)
        eligible_history = tuple(
            match
            for match in research_input.history
            if self._history_cutoff_valid(match, target.cutoff_utc)
        )
        normalized, excluded = self._refresh_facts(
            source_facts,
            target,
            research_input.last_material_event_by_team,
        )
        conflicts = self._conflicts(normalized, research_input.conflict_resolutions)
        corroboration = self._corroboration(normalized)
        attempts = self._attempts(research_input, target)
        features = self._features(
            target,
            eligible_history,
            normalized,
            research_input.workload,
            research_input.weather,
            research_input.baselines,
        )
        material_scenarios = self._material_scenarios(
            research_input.material_scenarios,
            facts=normalized,
            features=features,
            attempts=attempts,
        )
        evaluation_input = replace(research_input, material_scenarios=material_scenarios)
        evaluations, gaps, coverage, sufficiency = self._evaluate(
            evaluation_input,
            normalized,
            excluded,
            attempts,
            conflicts,
            features,
            eligible_history,
        )
        state_id = f"evidence-state:{target.matchweek_id}:{target.fixture_id}"
        reproducibility = dict(research_input.reproducibility)
        reproducibility.update(
            {
                "canonical_json": "RFC-8785-compatible-sorted-JSON",
                "cutoff_utc": target.cutoff_utc,
                "input_history_fixture_ids": tuple(
                    sorted(match.fixture_id for match in eligible_history)
                ),
                "input_source_fact_ids": tuple(item.fact_id for item in normalized),
                "post_cutoff_excluded_fact_ids": tuple(item.fact_id for item in excluded),
                "researcher": "matchvet.t09.EvidenceResearcher",
            }
        )
        return FrozenEvidenceState(
            state_id=state_id,
            target=target,
            source_assertions=normalized,
            post_cutoff_assertions=excluded,
            research_attempts=attempts,
            requirement_evaluations=evaluations,
            gaps=gaps,
            conflicts=conflicts,
            corroboration=corroboration,
            derived_features=features,
            critical_evidence_coverage=coverage,
            research_sufficiency=sufficiency,
            material_scenarios=material_scenarios,
            catalog_name=self.catalog.name,
            catalog_version=self.catalog.version,
            catalog_digest=self.catalog.digest,
            feature_rules_name=self.feature_rules.name,
            feature_rules_digest=self.feature_rules.digest,
            research_rules_name=self.research_rules_name,
            research_rules_digest=self.research_rules_digest,
            reproducibility=reproducibility,
        )

    research = build
    produce = build
    build_state = build

    def _source_facts(self, value: EvidenceResearchInput) -> tuple[SourceFact, ...]:
        facts: list[SourceFact] = [_source_fact(item) for item in value.source_assertions]
        facts.extend(_history_facts(value.history, value.target))
        fixture_is_pre_match = value.target.fixture_status in {"SCHEDULED", "CONFIRMED", "INCLUDED"}
        target_fact = SourceFact(
            fact_id=f"{value.target.fixture_id}:M-FIXTURE",
            subject_id=value.target.fixture_id,
            evidence_type="FIXTURE",
            predicate="target_match",
            state=EvidenceState.OBSERVED if fixture_is_pre_match else EvidenceState.UNKNOWN,
            value=value.target.to_dict() if fixture_is_pre_match else None,
            evidence_class=EvidenceClass.CRITICAL,
            source_key="T05-MATCHWEEK-FREEZE",
            origin_id="T05",
            source_assertion_ids=value.target.source_assertion_ids or (value.target.fixture_id,),
            source_digest=_digest(value.target.to_dict()),
            observed_at_utc=value.target.cutoff_utc,
            event_time_utc=value.target.kickoff_utc,
            cutoff_eligibility=CutoffEligibility.CUTOFF_VALID,
            correlation_groups=("schedule/workload",),
            provenance={
                "matchweek_id": value.target.matchweek_id,
                "cutoff_id": value.target.cutoff_id,
            },
            unknown_reason=(None if fixture_is_pre_match else "FIXTURE_STATE_NOT_PRE_MATCH"),
        )
        facts.append(target_fact)
        workload_id, workload_map, workload_state, workload_digest = _workload_payload(
            value.workload
        )
        if workload_map is not None:
            identifier = workload_id or f"workload:{value.target.fixture_id}"
            selected_state = (
                EvidenceState.OBSERVED if workload_state == "OBSERVED" else EvidenceState.UNKNOWN
            )
            facts.append(
                SourceFact(
                    fact_id=identifier,
                    subject_id=value.target.fixture_id,
                    evidence_type="WORKLOAD",
                    predicate="cross_competition_schedule",
                    state=selected_state,
                    value=workload_map if selected_state is EvidenceState.OBSERVED else None,
                    evidence_class=EvidenceClass.IMPORTANT,
                    source_key="T08-WORKLOAD",
                    origin_id="T08",
                    source_assertion_ids=(identifier,),
                    source_digest=workload_digest or _digest(workload_map),
                    observed_at_utc=(
                        str(workload_map["cutoff_utc"])
                        if isinstance(workload_map.get("cutoff_utc"), str)
                        else value.target.cutoff_utc
                    ),
                    cutoff_eligibility=_enum_value(
                        workload_map.get("cutoff_eligibility", "CUTOFF_VALID")
                    ),
                    correlation_groups=("schedule/workload",),
                    unknown_reason=(
                        str(workload_map.get("unknown_reason", "T08_WORKLOAD_UNKNOWN"))
                        if selected_state is EvidenceState.UNKNOWN
                        else None
                    ),
                    provenance={"t08_evidence_digest": workload_digest},
                )
            )
        weather_id, weather_map, weather_state, weather_eligibility = _weather_payload(
            value.weather
        )
        if weather_map is not None:
            identifier = weather_id or f"weather:{value.target.fixture_id}"
            selected_state = (
                EvidenceState.OBSERVED if weather_state == "OBSERVED" else EvidenceState.UNKNOWN
            )
            values = weather_map.get("values", weather_map)
            facts.append(
                SourceFact(
                    fact_id=identifier,
                    subject_id=value.target.fixture_id,
                    evidence_type="WEATHER",
                    predicate="venue_forecast",
                    state=selected_state,
                    value=values if selected_state is EvidenceState.OBSERVED else None,
                    evidence_class=EvidenceClass.CONTEXT,
                    source_key="T08-OPEN-METEO",
                    origin_id="T08",
                    source_assertion_ids=(identifier,),
                    source_digest=(
                        _optional_text(weather_map.get("evidence_digest")) or _digest(weather_map)
                    ),
                    published_at_utc=_optional_text(weather_map.get("forecast_issue_time_utc")),
                    retrieved_at_utc=_optional_text(weather_map.get("retrieved_at_utc")),
                    event_time_utc=value.target.kickoff_utc,
                    cutoff_eligibility=(
                        "CUTOFF_VALID"
                        if weather_eligibility == "CUTOFF_VALID"
                        else weather_eligibility
                    ),
                    correlation_groups=("weather",),
                    unknown_reason=(
                        str(weather_map.get("unknown_reason", "T08_WEATHER_UNKNOWN"))
                        if selected_state is EvidenceState.UNKNOWN
                        else None
                    ),
                    provenance={"t08_weather": True, "values": values},
                )
            )
        by_id: dict[str, SourceFact] = {}
        for fact in facts:
            previous = by_id.get(fact.fact_id)
            if previous is not None and previous.to_dict() != fact.to_dict():
                raise T09IntegrityError(f"Source Fact {fact.fact_id} was reused differently.")
            by_id[fact.fact_id] = fact
        return tuple(sorted(by_id.values(), key=lambda item: item.fact_id))

    def _material_scenarios(
        self,
        explicit: Iterable[MaterialScenario],
        *,
        facts: Sequence[SourceFact],
        features: Sequence[DerivedFeature],
        attempts: Sequence[ResearchAttempt],
    ) -> tuple[MaterialScenario, ...]:
        explicit_scenarios = tuple(explicit)
        for scenario in explicit_scenarios:
            try:
                requirement = self.catalog.requirement(scenario.requirement_id)
            except T09ValidationError:
                raise T09ValidationError(
                    f"Material scenario names unknown requirement {scenario.requirement_id}."
                ) from None
            if scenario.family not in requirement.families:
                raise T09ValidationError(
                    f"Material scenario {scenario.requirement_id} does not apply to "
                    f"{scenario.family}."
                )
        scenarios: dict[str, MaterialScenario] = {
            item.scenario_id: item for item in explicit_scenarios
        }
        feature_map = {item.name: item for item in features}

        weather = feature_map.get("M-WEATHER")
        if weather is not None and weather.state is EvidenceState.OBSERVED:
            weather_values = weather.value
            if isinstance(weather_values, Mapping):
                severe = any(
                    (
                        _numeric(weather_values.get(key)) is not None
                        and (
                            (
                                key in {"temperature_2m", "temperature_2m_max"}
                                and abs(float(_numeric(weather_values.get(key)) or 0.0))
                                >= self.feature_rules.severe_temperature_c
                            )
                            or (
                                key in {"wind_speed_10m", "wind_speed_10m_max"}
                                and float(_numeric(weather_values.get(key)) or 0.0)
                                >= self.feature_rules.severe_wind_kph
                            )
                            or (
                                key in {"precipitation", "precipitation_sum"}
                                and float(_numeric(weather_values.get(key)) or 0.0)
                                >= self.feature_rules.severe_precipitation_mm
                            )
                        )
                    )
                    for key in weather_values
                )
                if severe:
                    for family in PREFERENCE_FAMILIES:
                        scenario_id = f"inferred:weather:{family}"
                        scenarios.setdefault(
                            scenario_id,
                            MaterialScenario(
                                scenario_id=scenario_id,
                                family=family,
                                requirement_id="M-WEATHER",
                                description=(
                                    "Cutoff-valid severe weather indicators could change "
                                    "the acceptance boundary."
                                ),
                                evidence_fact_ids=weather.input_ids,
                            ),
                        )

        rest = feature_map.get("D-REST")
        if rest is not None and rest.state is EvidenceState.OBSERVED:
            rest_values = rest.value
            severe_rest = isinstance(rest_values, Mapping) and any(
                _numeric(rest_values.get(side)) is not None
                and float(_numeric(rest_values.get(side)) or 0.0)
                <= self.feature_rules.severe_rest_days
                for side in ("home", "away")
            )
            if severe_rest:
                for family in PREFERENCE_FAMILIES:
                    scenario_id = f"inferred:rest:{family}"
                    scenarios.setdefault(
                        scenario_id,
                        MaterialScenario(
                            scenario_id=scenario_id,
                            family=family,
                            requirement_id="D-REST",
                            description=(
                                "Short verified rest could change the acceptance boundary."
                            ),
                            evidence_fact_ids=rest.input_ids,
                        ),
                    )

        material_types = {
            "AVAILABILITY": "E-AVAILABILITY",
            "INJURY": "E-INJURY",
            "SUSPENSION": "E-SUSPENSION",
            "EXPECTED_LINEUP": "E-LINEUP-SCENARIO",
            "ROTATION": "E-ROTATION",
            "TACTICAL_CONTEXT": "E-TACTICS",
        }
        for fact in facts:
            requirement_id = material_types.get(fact.evidence_type)
            if requirement_id is None or fact.state is not EvidenceState.OBSERVED:
                continue
            fact_value = fact.value
            is_material = isinstance(fact_value, Mapping) and (
                fact_value.get("material") is True
                or fact_value.get("could_change_acceptance") is True
            )
            if not is_material:
                continue
            for family in PREFERENCE_FAMILIES:
                scenario_id = f"inferred:{fact.fact_id}:{family}"
                scenarios.setdefault(
                    scenario_id,
                    MaterialScenario(
                        scenario_id=scenario_id,
                        family=family,
                        requirement_id=requirement_id,
                        description=(
                            f"Source fact {fact.fact_id} records a material scenario "
                            "that could change the acceptance boundary."
                        ),
                        evidence_fact_ids=(fact.fact_id, *fact.assertion_ids),
                    ),
                )
        for attempt in attempts:
            if (
                not attempt.could_change_decision
                or attempt.cutoff_eligibility is not CutoffEligibility.CUTOFF_VALID
            ):
                continue
            attempt_requirement = next(
                (
                    item
                    for item in self.catalog.requirements
                    if item.requirement_id == attempt.requirement_id
                ),
                None,
            )
            if attempt_requirement is None:
                continue
            for family in attempt_requirement.families:
                scenario_id = (
                    f"inferred:attempt:{attempt.requirement_id}:{attempt.source_key}:{family}"
                )
                scenarios.setdefault(
                    scenario_id,
                    MaterialScenario(
                        scenario_id=scenario_id,
                        family=family,
                        requirement_id=attempt.requirement_id,
                        description=(
                            f"Research attempt {attempt.source_key} marks {attempt.requirement_id} "
                            "as a potentially acceptance-changing gap."
                        ),
                        evidence_fact_ids=attempt.source_assertion_ids,
                    ),
                )
        return tuple(
            sorted(
                scenarios.values(),
                key=lambda item: (item.family, item.requirement_id, item.scenario_id),
            )
        )

    @staticmethod
    def _history_cutoff_valid(match: HistoricalMatch, cutoff_utc: str) -> bool:
        if match.fixture_status not in {"COMPLETED", "FINAL", "FINISHED"}:
            return False
        if match.final_state is not EvidenceState.OBSERVED:
            return False
        cutoff = _parse_utc(cutoff_utc)
        return all(
            value is None or _parse_utc(value) <= cutoff
            for value in (match.kickoff_utc, match.observed_at_utc, match.published_at_utc)
        )

    def _refresh_facts(
        self,
        facts: Iterable[SourceFact],
        target: TargetMatch,
        last_material_event_by_team: Mapping[str, str],
    ) -> tuple[tuple[SourceFact, ...], tuple[SourceFact, ...]]:
        valid: list[SourceFact] = []
        excluded: list[SourceFact] = []
        material_events = {
            team_id: _parse_utc(timestamp)
            for team_id, timestamp in last_material_event_by_team.items()
        }
        cutoff = _parse_utc(target.cutoff_utc)
        kickoff = _parse_utc(target.kickoff_utc)
        for fact in facts:
            eligibility = fact.cutoff_eligibility
            times = [
                fact.published_at_utc,
                fact.observed_at_utc,
                fact.retrieved_at_utc,
            ]
            if any(value is not None and _parse_utc(value) > cutoff for value in times):
                eligibility = CutoffEligibility.POST_CUTOFF
            elif eligibility is CutoffEligibility.INDETERMINATE:
                capture_times = [
                    fact.published_at_utc,
                    fact.observed_at_utc,
                    fact.retrieved_at_utc,
                ]
                if any(value is not None for value in capture_times):
                    eligibility = CutoffEligibility.CUTOFF_VALID
            timestamp = _fact_timestamp(fact)
            age_cutoff = (
                max(0.0, (cutoff - _parse_utc(timestamp)).total_seconds())
                if timestamp is not None
                else None
            )
            age_kickoff = (
                max(0.0, (kickoff - _parse_utc(timestamp)).total_seconds())
                if timestamp is not None
                else None
            )
            if eligibility is CutoffEligibility.POST_CUTOFF:
                freshness = FreshnessState.POST_CUTOFF
            elif eligibility is not CutoffEligibility.CUTOFF_VALID:
                freshness = FreshnessState.UNKNOWN
            elif fact.evidence_type in {"MATCH_STATISTIC", "FIXTURE", "WORKLOAD", "WEATHER"}:
                freshness = FreshnessState.FRESH
            elif timestamp is None:
                freshness = FreshnessState.UNKNOWN
            else:
                relevant_events = [
                    material_events[subject]
                    for subject in (fact.subject_id, *target.team_ids)
                    if subject in material_events
                ]
                freshness = (
                    FreshnessState.STALE
                    if relevant_events and max(relevant_events) > _parse_utc(timestamp)
                    else FreshnessState.FRESH
                )
            refreshed = replace(
                fact,
                cutoff_eligibility=eligibility,
                freshness=freshness,
                age_seconds_at_cutoff=age_cutoff,
                age_seconds_at_kickoff=age_kickoff,
            )
            if eligibility is CutoffEligibility.CUTOFF_VALID:
                valid.append(refreshed)
            else:
                excluded.append(refreshed)
        return tuple(sorted(valid, key=lambda item: item.fact_id)), tuple(
            sorted(excluded, key=lambda item: item.fact_id)
        )

    def _conflicts(
        self,
        facts: Iterable[SourceFact],
        resolutions: Mapping[str, object],
    ) -> tuple[MaterialConflict, ...]:
        groups: dict[tuple[str, str, str], list[SourceFact]] = defaultdict(list)
        for fact in facts:
            if _fact_is_known(fact):
                groups[_fact_key(fact)].append(fact)
        conflicts: list[MaterialConflict] = []
        for key, members in sorted(groups.items()):
            value_groups: dict[str, list[SourceFact]] = defaultdict(list)
            for fact in members:
                value_groups[_fact_value_digest(fact)].append(fact)
            if len(value_groups) < 2:
                continue
            assertion_ids = tuple(sorted(fact.fact_id for fact in members))
            conflict_id = f"conflict:{_digest({'key': key, 'assertion_ids': assertion_ids})}"
            resolution = resolutions.get(conflict_id)
            selected_id, basis, rationale = self._resolution(resolution)
            status = "RESOLVED" if selected_id in assertion_ids else "UNRESOLVED"
            values = tuple(
                sorted(
                    (
                        fact.value
                        if fact.state is EvidenceState.OBSERVED
                        else _enum_value(fact.state)
                        for fact in members
                    ),
                    key=lambda item: _canonical_json(item),
                )
            )
            conflicts.append(
                MaterialConflict(
                    conflict_id=conflict_id,
                    subject_id=key[0],
                    evidence_type=key[1],
                    predicate=key[2],
                    assertion_ids=assertion_ids,
                    values=values,
                    status=status,
                    selected_assertion_id=selected_id,
                    resolution_basis=basis,
                    rationale=rationale,
                    material=True,
                )
            )
        return tuple(conflicts)

    @staticmethod
    def _resolution(value: object | None) -> tuple[str | None, tuple[str, ...], str | None]:
        if value is None:
            return None, (), None
        if isinstance(value, Mapping):
            selected = value.get("selected_assertion_id")
            basis = value.get("basis", value.get("resolution_basis", ()))
            rationale = value.get("rationale")
            return (
                selected if isinstance(selected, str) else None,
                tuple(item for item in _as_sequence(basis) if isinstance(item, str)),
                rationale if isinstance(rationale, str) else None,
            )
        return (
            getattr(value, "selected_assertion_id", None),
            tuple(getattr(value, "basis", ())),
            getattr(value, "rationale", None),
        )

    @staticmethod
    def _corroboration(facts: Iterable[SourceFact]) -> tuple[IndependentCorroboration, ...]:
        groups: dict[tuple[str, str, str, str], list[SourceFact]] = defaultdict(list)
        for fact in facts:
            if _fact_is_known(fact) and fact.freshness is FreshnessState.FRESH:
                groups[(*_fact_key(fact), _fact_value_digest(fact))].append(fact)
        result: list[IndependentCorroboration] = []
        for key, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            clusters: list[list[SourceFact]] = []
            for fact in members:
                matching = [
                    selected
                    for selected in clusters
                    if any(
                        (fact.origin_id is not None and fact.origin_id == prior.origin_id)
                        or (
                            fact.source_row_key is not None
                            and fact.source_row_key == prior.source_row_key
                        )
                        or bool(
                            set(fact.source_assertion_ids).intersection(prior.source_assertion_ids)
                        )
                        for prior in selected
                    )
                ]
                if not matching:
                    clusters.append([fact])
                else:
                    cluster = matching[0]
                    for other in matching[1:]:
                        cluster.extend(other)
                        clusters.remove(other)
                    cluster.append(fact)
            origin_values: list[str] = []
            for cluster in clusters:
                origin = next(
                    (
                        fact.origin_id
                        for fact in sorted(cluster, key=lambda item: item.fact_id)
                        if fact.origin_id is not None
                    ),
                    None,
                )
                if origin is not None:
                    origin_values.append(origin)
            origins = tuple(sorted(origin_values))
            if len(origins) < 2:
                continue
            correlated_ids = tuple(
                sorted(fact.fact_id for cluster in clusters if len(cluster) > 1 for fact in cluster)
            )
            result.append(
                IndependentCorroboration(
                    subject_id=key[0],
                    evidence_type=key[1],
                    predicate=key[2],
                    value=members[0].value
                    if members[0].state is EvidenceState.OBSERVED
                    else _enum_value(members[0].state),
                    origin_ids=origins,
                    assertion_ids=tuple(sorted(fact.fact_id for fact in members)),
                    correlated_assertion_ids=correlated_ids,
                    correlation_groups=_sorted_unique(
                        group for fact in members for group in fact.correlation_groups
                    ),
                )
            )
        return tuple(result)

    def _attempts(
        self, value: EvidenceResearchInput, target: TargetMatch
    ) -> tuple[ResearchAttempt, ...]:
        if value.mandatory_research is not None:
            attempts = list(value.mandatory_research)
        elif value.mandatory_research_performed is True:
            attempts = [
                ResearchAttempt(
                    requirement_id=requirement.requirement_id,
                    category="MANDATORY_RESEARCH",
                    source_key=requirement.source_priority,
                    attempted_at_utc=target.cutoff_utc,
                    accessibility=AccessState.ACCESSIBLE,
                    outcome=EvidenceState.OBSERVED,
                    performed=True,
                    reason="Catalogued cutoff scan performed by deterministic T09 builder.",
                )
                for requirement in self.catalog.mandatory()
            ]
        else:
            attempts = []
        known_requirement_ids = {item.requirement_id for item in self.catalog.requirements}
        unknown_attempts = sorted(
            {
                item.requirement_id
                for item in attempts
                if item.requirement_id not in known_requirement_ids
            }
        )
        if unknown_attempts:
            raise T09ValidationError(
                f"Mandatory Research names unknown requirements: {', '.join(unknown_attempts)}."
            )
        cutoff = _parse_utc(target.cutoff_utc)
        normalized_attempts: list[ResearchAttempt] = []
        for attempt in attempts:
            eligibility = attempt.cutoff_eligibility
            if _parse_utc(attempt.attempted_at_utc) > cutoff:
                eligibility = CutoffEligibility.POST_CUTOFF
            elif eligibility is CutoffEligibility.INDETERMINATE:
                eligibility = CutoffEligibility.CUTOFF_VALID
            normalized_attempts.append(replace(attempt, cutoff_eligibility=eligibility))
        attempts = normalized_attempts
        recorded = {item.requirement_id for item in attempts}
        for requirement in self.catalog.mandatory():
            if requirement.requirement_id in recorded:
                continue
            attempts.append(
                ResearchAttempt(
                    requirement_id=requirement.requirement_id,
                    category="MANDATORY_RESEARCH",
                    source_key=f"NOT_ATTEMPTED:{requirement.source_priority}",
                    attempted_at_utc=target.cutoff_utc,
                    accessibility=AccessState.NOT_ATTEMPTED,
                    outcome=EvidenceState.UNKNOWN,
                    performed=False,
                    reason="No Mandatory Research attempt was supplied before the cutoff.",
                )
            )
        return tuple(sorted(attempts, key=lambda item: (item.requirement_id, item.source_key)))

    def _features(
        self,
        target: TargetMatch,
        history: tuple[HistoricalMatch, ...],
        facts: tuple[SourceFact, ...],
        workload: object | None,
        weather: object | None,
        baselines: Mapping[str, object],
    ) -> tuple[DerivedFeature, ...]:
        workload_fact = next((fact for fact in facts if fact.evidence_type == "WORKLOAD"), None)
        if workload_fact is None or not workload_fact.is_cutoff_valid:
            workload = None
        weather_fact = next((fact for fact in facts if fact.evidence_type == "WEATHER"), None)
        if weather_fact is None or not weather_fact.is_cutoff_valid:
            weather = None
        goal_ids = _history_input_ids(
            history,
            ("full_time_home_goals", "full_time_away_goals"),
        )
        corner_ids = _history_input_ids(history, ("corners_home", "corners_away"))
        feature_values: list[DerivedFeature] = []

        opponent_value: dict[str, object] = {}
        opponent_ids: set[str] = set()
        venue_value: dict[str, object] = {}
        venue_ids: set[str] = set()
        recency_value: dict[str, object] = {}
        recency_ids: set[str] = set()
        horizons_value: dict[str, object] = {}
        horizons_ids: set[str] = set()
        trends_value: dict[str, object] = {}
        trends_ids: set[str] = set()
        goal_history_by_team: dict[str, bool] = {}
        for team_id in target.team_ids:
            records = tuple(
                match for match in history if team_id in (match.home_team_id, match.away_team_id)
            )
            team_goal_records = _history_metric_values(history, team_id, "full_time_home_goals")
            conceded_records = self._history_conceded_values(
                history, team_id, "full_time_home_goals"
            )
            team_corner_records = _history_metric_values(history, team_id, "corners_home")
            conceded_corner_records = self._history_conceded_values(
                history, team_id, "corners_home"
            )
            goal_history_by_team[team_id] = bool(team_goal_records)
            team_goal_ids = _sorted_unique(
                assertion_id for row in team_goal_records for assertion_id in row[2]
            )
            conceded_ids = _sorted_unique(
                assertion_id for row in conceded_records for assertion_id in row[2]
            )
            corner_ids_for_team = _sorted_unique(
                assertion_id
                for row in (*team_corner_records, *conceded_corner_records)
                for assertion_id in row[2]
            )
            opponents = _sorted_unique(
                match.away_team_id if match.home_team_id == team_id else match.home_team_id
                for match in records
            )
            goal_opponent_profiles: dict[str, Mapping[str, object]] = {}
            corner_opponent_profiles: dict[str, Mapping[str, object]] = {}
            profile_ids: set[str] = set()
            for opponent_id in opponents:
                goal_profile, goal_profile_ids = self._team_metric_profile(
                    history, opponent_id, "full_time_home_goals"
                )
                corner_profile, corner_profile_ids = self._team_metric_profile(
                    history, opponent_id, "corners_home"
                )
                goal_opponent_profiles[opponent_id] = goal_profile
                corner_opponent_profiles[opponent_id] = corner_profile
                profile_ids.update((*goal_profile_ids, *corner_profile_ids))
            goal_adjusted = self._opponent_adjusted_difference(
                team_goal_records,
                conceded_records,
                records,
                team_id,
                goal_opponent_profiles,
            )
            corner_adjusted = self._opponent_adjusted_difference(
                team_corner_records,
                conceded_corner_records,
                records,
                team_id,
                corner_opponent_profiles,
            )
            opponent_ids.update((*team_goal_ids, *conceded_ids, *corner_ids_for_team, *profile_ids))
            opponent_value[team_id] = {
                "matches": len(team_goal_records),
                "mean_scored": self._mean(row[0] for row in team_goal_records),
                "mean_conceded": self._mean(row[0] for row in conceded_records),
                "opponents": opponents,
                "opponent_profiles": goal_opponent_profiles,
                "opponent_adjusted": {
                    "mean_difference": self._mean(goal_adjusted),
                    "matches": len(goal_adjusted),
                    "method": "team_goal_difference_minus_opponent_goal_difference",
                },
                "corners": {
                    "matches": len(team_corner_records),
                    "mean_scored": self._mean(row[0] for row in team_corner_records),
                    "mean_conceded": self._mean(row[0] for row in conceded_corner_records),
                    "opponent_profiles": corner_opponent_profiles,
                    "opponent_adjusted": {
                        "mean_difference": self._mean(corner_adjusted),
                        "matches": len(corner_adjusted),
                        "method": "team_corner_difference_minus_opponent_corner_difference",
                    },
                },
            }

            home_records = tuple(
                row
                for row in team_goal_records
                if next((match for match in records if match.fixture_id == row[3]), None)
                is not None
                and next(match for match in records if match.fixture_id == row[3]).home_team_id
                == team_id
            )
            away_records = tuple(row for row in team_goal_records if row not in home_records)
            corner_home_records = tuple(
                row
                for row in team_corner_records
                if next(
                    (
                        match
                        for match in records
                        if match.fixture_id == row[3] and match.home_team_id == team_id
                    ),
                    None,
                )
                is not None
            )
            corner_away_records = tuple(
                row for row in team_corner_records if row not in corner_home_records
            )
            venue_ids.update(
                assertion_id
                for row in (
                    *home_records,
                    *away_records,
                    *corner_home_records,
                    *corner_away_records,
                )
                for assertion_id in row[2]
            )
            home_mean_scored = self._mean(row[0] for row in home_records)
            away_mean_scored = self._mean(row[0] for row in away_records)
            corner_home_mean_scored = self._mean(row[0] for row in corner_home_records)
            corner_away_mean_scored = self._mean(row[0] for row in corner_away_records)
            venue_value[team_id] = {
                "home_mean_scored": home_mean_scored,
                "away_mean_scored": away_mean_scored,
                "venue_effect": (
                    home_mean_scored - away_mean_scored
                    if home_mean_scored is not None and away_mean_scored is not None
                    else None
                ),
                "home_matches": len(home_records),
                "away_matches": len(away_records),
                "corners": {
                    "home_mean_scored": corner_home_mean_scored,
                    "away_mean_scored": corner_away_mean_scored,
                    "venue_effect": (
                        corner_home_mean_scored - corner_away_mean_scored
                        if corner_home_mean_scored is not None
                        and corner_away_mean_scored is not None
                        else None
                    ),
                    "home_matches": len(corner_home_records),
                    "away_matches": len(corner_away_records),
                },
            }

            recency_ids.update((*team_goal_ids, *corner_ids_for_team))
            recency_value[team_id] = {
                **self._recency_summary(team_goal_records, target.cutoff_utc),
                "corners": self._recency_summary(team_corner_records, target.cutoff_utc),
            }
            horizon = self._horizon_summary(team_goal_records, target.cutoff_utc)
            horizons_value[team_id] = {
                **horizon,
                "corners": self._horizon_summary(team_corner_records, target.cutoff_utc),
            }
            horizons_ids.update((*team_goal_ids, *corner_ids_for_team))
            trend, trend_ids_for_team = self._trend(team_goal_records, target.cutoff_utc)
            corner_trend, corner_trend_ids = self._trend(team_corner_records, target.cutoff_utc)
            trends_value[team_id] = {**trend, "corners": corner_trend}
            trends_ids.update((*trend_ids_for_team, *corner_trend_ids))

        both_goal_history = bool(goal_history_by_team) and all(goal_history_by_team.values())
        feature_values.append(
            _make_feature(
                "D-OPPONENT-STRENGTH",
                state=(
                    EvidenceState.OBSERVED
                    if opponent_ids and both_goal_history
                    else EvidenceState.UNKNOWN
                ),
                value=opponent_value if opponent_ids else {"reason": "NO_COMPATIBLE_HISTORY"},
                input_ids=opponent_ids,
                input_digests=self._digests_for_ids(facts, opponent_ids),
                rules=self.feature_rules,
                adjustment_state="OPPONENT_ADJUSTED",
                correlation_groups=("goals/results",),
                reason=(
                    None
                    if opponent_ids and both_goal_history
                    else "INSUFFICIENT_TEAM_HISTORY"
                    if opponent_ids
                    else "NO_COMPATIBLE_HISTORY"
                ),
            )
        )
        feature_values.append(
            _make_feature(
                "D-VENUE-EFFECT",
                state=(
                    EvidenceState.OBSERVED
                    if venue_ids and both_goal_history
                    else EvidenceState.UNKNOWN
                ),
                value=venue_value if venue_ids else {"reason": "NO_VENUE_HISTORY"},
                input_ids=venue_ids,
                input_digests=self._digests_for_ids(facts, venue_ids),
                rules=self.feature_rules,
                adjustment_state="VENUE_ADJUSTED",
                correlation_groups=("goals/results",),
                reason=(
                    None
                    if venue_ids and both_goal_history
                    else "INSUFFICIENT_TEAM_HISTORY"
                    if venue_ids
                    else "NO_VENUE_HISTORY"
                ),
            )
        )
        feature_values.append(
            _make_feature(
                "D-RECENCY-STRENGTH",
                state=(
                    EvidenceState.OBSERVED
                    if recency_ids and both_goal_history
                    else EvidenceState.UNKNOWN
                ),
                value=recency_value if recency_ids else {"reason": "NO_COMPATIBLE_HISTORY"},
                input_ids=recency_ids,
                input_digests=self._digests_for_ids(facts, recency_ids),
                rules=self.feature_rules,
                time_scope={"half_life_days": self.feature_rules.recency_half_life_days},
                correlation_groups=("goals/results",),
                reason=(
                    None
                    if recency_ids and both_goal_history
                    else "INSUFFICIENT_TEAM_HISTORY"
                    if recency_ids
                    else "NO_COMPATIBLE_HISTORY"
                ),
            )
        )
        feature_values.append(
            _make_feature(
                "D-FORM-HORIZONS",
                state=(
                    EvidenceState.OBSERVED
                    if horizons_ids and both_goal_history
                    else EvidenceState.UNKNOWN
                ),
                value=horizons_value if horizons_ids else {"reason": "NO_COMPATIBLE_HISTORY"},
                input_ids=horizons_ids,
                input_digests=self._digests_for_ids(facts, horizons_ids),
                rules=self.feature_rules,
                time_scope={
                    "recent_days": self.feature_rules.recent_horizon_days,
                    "medium_days": self.feature_rules.medium_horizon_days,
                    "current_season_days": self.feature_rules.current_season_horizon_days,
                    "older_days": self.feature_rules.older_horizon_days,
                },
                correlation_groups=("goals/results",),
                reason=(
                    None
                    if horizons_ids and both_goal_history
                    else "INSUFFICIENT_TEAM_HISTORY"
                    if horizons_ids
                    else "NO_COMPATIBLE_HISTORY"
                ),
            )
        )
        feature_values.append(
            _make_feature(
                "D-TREND-DIRECTION",
                state=(
                    EvidenceState.OBSERVED
                    if trends_ids and both_goal_history
                    else EvidenceState.UNKNOWN
                ),
                value=trends_value if trends_ids else {"reason": "NO_COMPATIBLE_HISTORY"},
                input_ids=trends_ids,
                input_digests=self._digests_for_ids(facts, trends_ids),
                rules=self.feature_rules,
                time_scope={"comparison": "recent_vs_medium"},
                correlation_groups=("goals/results",),
                reason=(
                    None
                    if trends_ids and both_goal_history
                    else "INSUFFICIENT_TEAM_HISTORY"
                    if trends_ids
                    else "NO_COMPATIBLE_HISTORY"
                ),
            )
        )

        score_value, score_state, score_ids, score_reason = self._score_state(history, target)
        feature_values.append(
            _make_feature(
                "D-SCORE-STATE",
                state=score_state,
                value=score_value,
                input_ids=score_ids,
                input_digests=self._digests_for_ids(facts, score_ids),
                rules=self.feature_rules,
                correlation_groups=("discipline/match-state",),
                reason=score_reason,
            )
        )

        workload_id, workload_map, workload_state, _ = _workload_payload(workload)
        workload_inputs = (workload_id,) if workload_id is not None else ()
        workload_digests = (
            (workload_fact.source_digest,)
            if workload_fact is not None and workload_fact.source_digest is not None
            else ()
        )
        workload_is_observed = workload_state == "OBSERVED" and workload_map is not None
        rest_value: dict[str, object] = {}
        congestion_value: dict[str, object] = {}
        cross_value: dict[str, object] = {}
        for side in ("home", "away"):
            team = _team_payload(workload_map or {}, side)
            rest_value[side] = team.get("rest_days")
            windows = team.get("congestion_windows", team.get("congestion_periods", ()))
            density = team.get("schedule_density", {})
            cross_value[side] = _string_tuple(team.get("cross_competition_fixture_ids", ()))
            congestion_value[side] = {
                "count": len(windows)
                if isinstance(windows, (list, tuple))
                else _integer(team.get("congestion_count", 0)),
                "schedule_density": density,
            }
        feature_values.append(
            _make_feature(
                "D-REST",
                state=EvidenceState.OBSERVED if workload_is_observed else EvidenceState.UNKNOWN,
                value=rest_value if workload_map is not None else {"reason": "WORKLOAD_UNKNOWN"},
                input_ids=workload_inputs,
                input_digests=workload_digests,
                rules=self.feature_rules,
                correlation_groups=("schedule/workload",),
                reason=None if workload_is_observed else "WORKLOAD_UNKNOWN",
            )
        )
        feature_values.append(
            _make_feature(
                "D-CONGESTION",
                state=EvidenceState.OBSERVED if workload_is_observed else EvidenceState.UNKNOWN,
                value=congestion_value
                if workload_map is not None
                else {"reason": "WORKLOAD_UNKNOWN"},
                input_ids=workload_inputs,
                input_digests=workload_digests,
                rules=self.feature_rules,
                correlation_groups=("schedule/workload",),
                reason=None if workload_is_observed else "WORKLOAD_UNKNOWN",
            )
        )
        feature_values.append(
            _make_feature(
                "D-CROSS-COMP-WORKLOAD",
                state=EvidenceState.OBSERVED if workload_is_observed else EvidenceState.UNKNOWN,
                value=cross_value if workload_map is not None else {"reason": "WORKLOAD_UNKNOWN"},
                input_ids=workload_inputs,
                input_digests=workload_digests,
                rules=self.feature_rules,
                correlation_groups=("schedule/workload",),
                reason=None if workload_is_observed else "WORKLOAD_UNKNOWN",
            )
        )

        baseline_value = dict(baselines)
        baseline_ids = _sorted_unique(
            (*goal_ids, *corner_ids, *tuple(str(key) for key in baseline_value))
        )
        baseline_digests = self._digests_for_ids(facts, baseline_ids) + tuple(
            _digest({"baseline_id": str(key), "value": baseline_value[key]})
            for key in sorted(baseline_value)
        )
        home_goal_rows = _history_metric_values(
            history, target.home_team_id, "full_time_home_goals"
        )
        away_goal_rows = _history_metric_values(
            history, target.away_team_id, "full_time_home_goals"
        )
        total_goal_values = tuple(
            match.full_time_home_goals + match.full_time_away_goals
            for match in history
            if match.full_time_home_goals is not None
            and match.full_time_away_goals is not None
            and match.metric_state("full_time_home_goals") is EvidenceState.OBSERVED
            and match.metric_state("full_time_away_goals") is EvidenceState.OBSERVED
        )
        baseline_value.setdefault(
            "full_time_goals",
            {
                "home_mean": self._mean(row[0] for row in home_goal_rows),
                "away_mean": self._mean(row[0] for row in away_goal_rows),
                "match_total_mean": self._mean(total_goal_values),
            },
        )
        baseline_value.setdefault(
            "full_match_corners",
            {
                "home_mean": self._mean(
                    row[0]
                    for row in _history_metric_values(history, target.home_team_id, "corners_home")
                ),
                "away_mean": self._mean(
                    row[0]
                    for row in _history_metric_values(history, target.away_team_id, "corners_home")
                ),
            },
        )
        feature_values.append(
            _make_feature(
                "D-HISTORICAL-BASELINE",
                state=EvidenceState.OBSERVED if baseline_ids else EvidenceState.UNKNOWN,
                value=baseline_value if baseline_ids else {"reason": "NO_HISTORICAL_BASELINE"},
                input_ids=baseline_ids,
                input_digests=baseline_digests,
                rules=self.feature_rules,
                correlation_groups=("goals/results", "corners"),
                reason=None if baseline_ids else "NO_HISTORICAL_BASELINE",
            )
        )

        weather_id, weather_map, weather_state, _ = _weather_payload(weather)
        weather_inputs = (weather_id,) if weather_id is not None else ()
        weather_digests = (
            (weather_fact.source_digest,)
            if weather_fact is not None and weather_fact.source_digest is not None
            else ()
        )
        weather_values = (
            weather_map.get("values", weather_map)
            if weather_map is not None
            else {"reason": "WEATHER_UNKNOWN"}
        )
        feature_values.append(
            _make_feature(
                "M-WEATHER",
                state=EvidenceState.OBSERVED
                if weather_state == "OBSERVED"
                else EvidenceState.UNKNOWN,
                value=weather_values,
                input_ids=weather_inputs,
                input_digests=weather_digests,
                rules=self.feature_rules,
                correlation_groups=("weather",),
                reason=None if weather_state == "OBSERVED" else "WEATHER_UNKNOWN",
            )
        )

        regime_facts = tuple(
            fact
            for fact in facts
            if fact.evidence_type in {"REGIME_CHANGE", "MANAGER_CHANGE"}
            and fact.predicate in {"active_regime", "manager", "regime"}
            and fact.subject_id in (*target.team_ids, target.fixture_id)
            and fact.state is EvidenceState.OBSERVED
        )
        selected_regime = max(
            regime_facts,
            key=lambda fact: (fact.effective_time_utc or fact.observed_at_utc or "", fact.fact_id),
            default=None,
        )
        feature_values.append(
            _make_feature(
                "E-TACTICAL-REGIME",
                state=EvidenceState.OBSERVED
                if selected_regime is not None
                else EvidenceState.UNKNOWN,
                value=(
                    _canonicalize_embedded_times(selected_regime.value)
                    if selected_regime is not None
                    else {"reason": "REGIME_NOT_RECORDED"}
                ),
                input_ids=selected_regime.assertion_ids if selected_regime is not None else (),
                input_digests=(selected_regime.source_digest,)
                if selected_regime is not None and selected_regime.source_digest is not None
                else (),
                rules=self.feature_rules,
                correlation_groups=("tactics/regime",),
                reason=None if selected_regime is not None else "REGIME_NOT_RECORDED",
            )
        )
        return tuple(sorted(feature_values, key=lambda item: item.feature_id))

    @staticmethod
    def _mean(values: Iterable[float]) -> float | None:
        selected = tuple(values)
        return sum(selected) / len(selected) if selected else None

    @staticmethod
    def _history_conceded_values(
        history: Iterable[HistoricalMatch], team_id: str, metric: str
    ) -> tuple[tuple[float, str, tuple[str, ...], str], ...]:
        values: list[tuple[float, str, tuple[str, ...], str]] = []
        for match in history:
            if match.home_team_id == team_id:
                selected_metric = metric.replace("_home", "_away")
            elif match.away_team_id == team_id:
                selected_metric = metric.replace("_away", "_home")
            else:
                continue
            value = match.metrics.get(selected_metric)
            if match.metric_state(selected_metric) is not EvidenceState.OBSERVED:
                continue
            if _numeric(value) is None:
                continue
            values.append(
                (
                    float(cast(int | float, value)),
                    match.kickoff_utc,
                    match.metric_ids(selected_metric),
                    match.fixture_id,
                )
            )
        return tuple(values)

    def _team_metric_profile(
        self,
        history: Sequence[HistoricalMatch],
        team_id: str,
        metric: str,
    ) -> tuple[Mapping[str, object], tuple[str, ...]]:
        scored = _history_metric_values(history, team_id, metric)
        conceded = self._history_conceded_values(history, team_id, metric)
        conceded_by_fixture = {row[3]: row[0] for row in conceded}
        differences = tuple(
            row[0] - conceded_by_fixture[row[3]] for row in scored if row[3] in conceded_by_fixture
        )
        input_ids = _sorted_unique(
            assertion_id for row in (*scored, *conceded) for assertion_id in row[2]
        )
        return (
            {
                "matches": len(scored),
                "complete_matches": len(differences),
                "mean_scored": self._mean(row[0] for row in scored),
                "mean_conceded": self._mean(row[0] for row in conceded),
                "mean_difference": self._mean(differences),
            },
            input_ids,
        )

    @staticmethod
    def _opponent_adjusted_difference(
        scored: Sequence[tuple[float, str, tuple[str, ...], str]],
        conceded: Sequence[tuple[float, str, tuple[str, ...], str]],
        records: Sequence[HistoricalMatch],
        team_id: str,
        opponent_profiles: Mapping[str, Mapping[str, object]],
    ) -> tuple[float, ...]:
        conceded_by_fixture = {row[3]: row[0] for row in conceded}
        records_by_fixture = {match.fixture_id: match for match in records}
        adjusted: list[float] = []
        for row in scored:
            own_conceded = conceded_by_fixture.get(row[3])
            match = records_by_fixture.get(row[3])
            if own_conceded is None or match is None:
                continue
            opponent_id = (
                match.away_team_id if match.home_team_id == team_id else match.home_team_id
            )
            profile = opponent_profiles.get(opponent_id)
            opponent_difference = (
                _numeric(profile.get("mean_difference")) if profile is not None else None
            )
            if opponent_difference is not None:
                adjusted.append(row[0] - own_conceded - opponent_difference)
        return tuple(adjusted)

    @staticmethod
    def _digests_for_ids(facts: Iterable[SourceFact], input_ids: Iterable[str]) -> tuple[str, ...]:
        ids = set(input_ids)
        return _sorted_unique(
            fact.source_digest
            for fact in facts
            if fact.source_digest is not None
            and (fact.fact_id in ids or ids.intersection(fact.source_assertion_ids))
        )

    def _recency_summary(
        self, rows: Sequence[tuple[float, str, tuple[str, ...], str]], cutoff_utc: str
    ) -> Mapping[str, object]:
        cutoff = _parse_utc(cutoff_utc)
        weighted = []
        for value, timestamp, _, _ in rows:
            age_days = max(0.0, (cutoff - _parse_utc(timestamp)).total_seconds() / 86400.0)
            weight = 2 ** (-age_days / self.feature_rules.recency_half_life_days)
            weighted.append((value, weight))
        denominator = sum(weight for _, weight in weighted)
        return {
            "weighted_mean": sum(value * weight for value, weight in weighted) / denominator
            if denominator
            else None,
            "effective_matches": denominator,
            "matches": len(rows),
        }

    def _horizon_summary(
        self, rows: Sequence[tuple[float, str, tuple[str, ...], str]], cutoff_utc: str
    ) -> Mapping[str, object]:
        cutoff = _parse_utc(cutoff_utc)
        limits = {
            "recent": self.feature_rules.recent_horizon_days,
            "medium": self.feature_rules.medium_horizon_days,
            "current_season": self.feature_rules.current_season_horizon_days,
            "older": self.feature_rules.older_horizon_days,
        }
        result: dict[str, object] = {}
        for name, days in limits.items():
            selected = tuple(
                value
                for value, timestamp, _, _ in rows
                if (cutoff - _parse_utc(timestamp)).total_seconds() <= days * 86400
            )
            result[name] = {"matches": len(selected), "mean": self._mean(selected)}
        return result

    def _trend(
        self, rows: Sequence[tuple[float, str, tuple[str, ...], str]], cutoff_utc: str
    ) -> tuple[Mapping[str, object], tuple[str, ...]]:
        cutoff = _parse_utc(cutoff_utc)
        recent = tuple(
            value
            for value, timestamp, _, _ in rows
            if (cutoff - _parse_utc(timestamp)).total_seconds()
            <= self.feature_rules.recent_horizon_days * 86400
        )
        medium = tuple(
            value
            for value, timestamp, _, _ in rows
            if (cutoff - _parse_utc(timestamp)).total_seconds()
            <= self.feature_rules.medium_horizon_days * 86400
        )
        recent_mean = self._mean(recent)
        medium_mean = self._mean(medium)
        if recent_mean is None or medium_mean is None:
            direction = "INDETERMINATE"
        elif recent_mean - medium_mean > self.feature_rules.trend_tolerance:
            direction = "INCREASING"
        elif medium_mean - recent_mean > self.feature_rules.trend_tolerance:
            direction = "DECREASING"
        else:
            direction = "STABLE"
        return (
            {"direction": direction, "recent_mean": recent_mean, "medium_mean": medium_mean},
            _sorted_unique(assertion_id for row in rows for assertion_id in row[2]),
        )

    @staticmethod
    def _score_state(
        history: Iterable[HistoricalMatch], target: TargetMatch
    ) -> tuple[Mapping[str, object], EvidenceState, tuple[str, ...], str | None]:
        selected = tuple(history)
        values: dict[str, object] = {"timing_known": True, "matches": len(selected)}
        input_ids: set[str] = set()
        timing_known = True
        target_history = False
        goal_history = False
        for side, team_id in (("home", target.home_team_id), ("away", target.away_team_id)):
            red_count = 0
            red_known = True
            red_seen = False
            missing_timing = False
            penalty_count = 0
            goal_margins: list[float] = []
            for match in selected:
                if match.home_team_id == team_id:
                    own_goal_metric = "full_time_home_goals"
                    opponent_goal_metric = "full_time_away_goals"
                    metric = "red_cards_home"
                    red_value = match.red_cards_home
                elif match.away_team_id == team_id:
                    own_goal_metric = "full_time_away_goals"
                    opponent_goal_metric = "full_time_home_goals"
                    metric = "red_cards_away"
                    red_value = match.red_cards_away
                else:
                    continue
                target_history = True
                input_ids.update(match.metric_ids(own_goal_metric))
                input_ids.update(match.metric_ids(opponent_goal_metric))
                own_goals = match.metrics.get(own_goal_metric)
                opponent_goals = match.metrics.get(opponent_goal_metric)
                own_goal_number = _numeric(own_goals)
                opponent_goal_number = _numeric(opponent_goals)
                if (
                    match.metric_state(own_goal_metric) is EvidenceState.OBSERVED
                    and match.metric_state(opponent_goal_metric) is EvidenceState.OBSERVED
                    and own_goal_number is not None
                    and opponent_goal_number is not None
                ):
                    goal_history = True
                    goal_margins.append(own_goal_number - opponent_goal_number)
                input_ids.update(match.metric_ids(metric))
                if match.metric_state(metric) is EvidenceState.UNKNOWN:
                    red_known = False
                    continue
                red_seen = True
                red_count += int(red_value or 0)
                if red_value and len(match.red_card_minutes) < int(red_value):
                    missing_timing = True
                penalty_count += len(match.penalty_minutes)
                if match.penalty_minutes:
                    input_ids.update(match.source_assertion_ids)
            timing_known = timing_known and not missing_timing
            values[side] = {
                "goal_margin_mean": EvidenceResearcher._mean(goal_margins),
                "goal_margin_matches": len(goal_margins),
                "numerical_imbalance": {
                    "red_card_count": red_count if red_known else None,
                    "red_card_state": "OBSERVED" if red_seen and red_known else "UNKNOWN",
                },
                "red_cards": red_count if red_known else None,
                "red_card_state": "OBSERVED" if red_seen and red_known else "UNKNOWN",
                "red_card_timing_known": None if not red_known else not missing_timing,
                "penalty_events": penalty_count,
            }
        values["timing_known"] = timing_known
        if not selected:
            return (
                {"reason": "NO_COMPLETED_MATCH_HISTORY"},
                EvidenceState.UNKNOWN,
                (),
                "NO_COMPLETED_MATCH_HISTORY",
            )
        if not target_history or not goal_history:
            return values, EvidenceState.UNKNOWN, tuple(sorted(input_ids)), "SCORE_STATE_UNKNOWN"
        if not timing_known:
            return (
                values,
                EvidenceState.UNKNOWN,
                tuple(sorted(input_ids)),
                "RED_CARD_TIMING_UNKNOWN",
            )
        return values, EvidenceState.OBSERVED, tuple(sorted(input_ids)), None

    def _evaluate(
        self,
        value: EvidenceResearchInput,
        facts: tuple[SourceFact, ...],
        excluded: tuple[SourceFact, ...],
        attempts: tuple[ResearchAttempt, ...],
        conflicts: tuple[MaterialConflict, ...],
        features: tuple[DerivedFeature, ...],
        history: tuple[HistoricalMatch, ...],
    ) -> tuple[
        tuple[RequirementEvaluation, ...],
        tuple[EvidenceGap, ...],
        Mapping[str, CriticalEvidenceCoverage],
        Mapping[str, ResearchSufficiency],
    ]:
        feature_map = {item.name: item for item in features}
        all_evaluations: list[RequirementEvaluation] = []
        all_gaps: list[EvidenceGap] = []
        coverage: dict[str, CriticalEvidenceCoverage] = {}
        sufficiency: dict[str, ResearchSufficiency] = {}
        for family in PREFERENCE_FAMILIES:
            family_requirements = self.catalog.for_family(family)
            scenarios = tuple(
                scenario
                for scenario in value.material_scenarios
                if scenario.family == family and scenario.could_change_acceptance
            )
            conditional_ids = _sorted_unique(scenario.requirement_id for scenario in scenarios)
            for requirement_id in conditional_ids:
                try:
                    requirement = self.catalog.requirement(requirement_id)
                except T09ValidationError:
                    raise T09ValidationError(
                        f"Material scenario names unknown requirement {requirement_id}."
                    ) from None
                if family not in requirement.families:
                    raise T09ValidationError(
                        f"Material scenario {requirement_id} does not apply to {family}."
                    )
            active_critical_ids = _sorted_unique(
                item.requirement_id
                for item in family_requirements
                if item.evidence_class is EvidenceClass.CRITICAL
            )
            active_critical_ids = _sorted_unique((*active_critical_ids, *conditional_ids))
            family_evaluations: list[RequirementEvaluation] = []
            for requirement in family_requirements:
                is_conditional = requirement.requirement_id in conditional_ids
                evaluation = self._evaluate_requirement(
                    requirement,
                    family,
                    value,
                    facts,
                    excluded,
                    attempts,
                    conflicts,
                    feature_map,
                    history,
                    is_conditional,
                )
                family_evaluations.append(evaluation)
                if not evaluation.covered:
                    gap = self._gap_for(
                        evaluation,
                        attempts,
                        decision_materiality=evaluation.blocks_family,
                    )
                    all_gaps.append(gap)
                    family_evaluations[-1] = replace(evaluation, gap_ids=(gap.gap_id,))
            all_evaluations.extend(family_evaluations)
            by_id = {item.requirement_id: item for item in family_evaluations}
            covered_ids = tuple(
                item_id for item_id in active_critical_ids if by_id[item_id].covered
            )
            missing_ids = tuple(
                item_id for item_id in active_critical_ids if not by_id[item_id].covered
            )
            coverage[family] = CriticalEvidenceCoverage(
                family=family,
                required_requirement_ids=active_critical_ids,
                covered_requirement_ids=covered_ids,
                missing_requirement_ids=missing_ids,
                conditional_requirements=conditional_ids,
                coverage_ratio=(
                    len(covered_ids) / len(active_critical_ids) if active_critical_ids else 1.0
                ),
                complete=not missing_ids,
            )
            mandatory_ids = {
                item.requirement_id for item in family_requirements if item.mandatory_research
            }
            attempted_ids = {
                item.requirement_id
                for item in attempts
                if item.performed and item.successful_attempt
            }
            mandatory_complete = mandatory_ids.issubset(attempted_ids)
            critical_complete = coverage[family].complete
            missing_important = tuple(
                item.requirement_id
                for item in family_evaluations
                if item.catalog_class is EvidenceClass.IMPORTANT and not item.covered
            )
            relevant_conflicts = sum(
                1
                for conflict in conflicts
                if conflict.status == "UNRESOLVED"
                and any(
                    _conflict_relevant(conflict, evaluation)
                    for evaluation in family_evaluations
                    if evaluation.requirement_id in active_critical_ids
                )
            )
            model_unavailable = any(
                by_id[item_id].status is CoverageState.MODEL_UNAVAILABLE
                for item_id in active_critical_ids
            )
            reasons: list[str] = []
            if not mandatory_complete:
                reasons.append("MANDATORY_RESEARCH_UNPERFORMED")
            if not critical_complete:
                reasons.append("CRITICAL_EVIDENCE_INCOMPLETE")
            if relevant_conflicts:
                reasons.append("UNRESOLVED_MATERIAL_CONFLICT")
            if model_unavailable:
                reasons.append("REQUIRED_HISTORY_OR_MODEL_UNAVAILABLE")
            status = (
                ResearchStatus.MODEL_UNAVAILABLE
                if model_unavailable
                else ResearchStatus.INSUFFICIENT
                if not mandatory_complete or not critical_complete or relevant_conflicts
                else ResearchStatus.SUFFICIENT
            )
            optional_complete = not missing_important
            sufficiency[family] = ResearchSufficiency(
                family=family,
                status=status,
                mandatory_research_complete=mandatory_complete,
                critical_evidence_complete=critical_complete,
                optional_research_complete=optional_complete,
                diminishing_returns_reached=optional_complete,
                model_unavailable=model_unavailable,
                unresolved_material_conflicts=relevant_conflicts,
                missing_important_requirement_ids=missing_important,
                reasons=tuple(reasons),
            )
        return (
            tuple(sorted(all_evaluations, key=lambda item: (item.family, item.requirement_id))),
            tuple(sorted(all_gaps, key=lambda item: item.gap_id)),
            MappingProxyType(dict(sorted(coverage.items()))),
            MappingProxyType(dict(sorted(sufficiency.items()))),
        )

    def _evaluate_requirement(
        self,
        requirement: EvidenceRequirement,
        family: str,
        value: EvidenceResearchInput,
        facts: tuple[SourceFact, ...],
        excluded: tuple[SourceFact, ...],
        attempts: tuple[ResearchAttempt, ...],
        conflicts: tuple[MaterialConflict, ...],
        feature_map: Mapping[str, DerivedFeature],
        history: tuple[HistoricalMatch, ...],
        conditional: bool,
    ) -> RequirementEvaluation:
        input_ids, direct_facts, feature, excluded_facts = self._evidence_for_requirement(
            requirement.requirement_id,
            family,
            value,
            facts,
            excluded,
            feature_map,
        )
        relevant_attempts = tuple(
            attempt for attempt in attempts if attempt.requirement_id == requirement.requirement_id
        )
        mandatory_missing = requirement.mandatory_research and not any(
            item.performed and item.successful_attempt for item in relevant_attempts
        )
        status = CoverageState.UNKNOWN
        state = EvidenceState.UNKNOWN
        freshness = FreshnessState.UNKNOWN
        age_cutoff: float | None = None
        age_kickoff: float | None = None
        reason = "EVIDENCE_NOT_FOUND"
        if mandatory_missing:
            status = CoverageState.UNPERFORMED
            reason = "MANDATORY_RESEARCH_NOT_PERFORMED"
        elif self._model_unavailable(
            requirement.requirement_id,
            family,
            value,
            direct_facts,
            feature,
            history,
        ):
            status = CoverageState.MODEL_UNAVAILABLE
            reason = "REQUIRED_HISTORY_OR_MODEL_EVIDENCE_INSUFFICIENT"
        elif feature is not None:
            state = _state(feature.state)
            input_ids = _sorted_unique((*input_ids, *feature.input_ids))
            if feature.state is EvidenceState.OBSERVED:
                status = CoverageState.COVERED
                reason = "DERIVED_FEATURE_AVAILABLE"
            elif excluded_facts:
                status = CoverageState.POST_CUTOFF
                reason = "POST_CUTOFF_EVIDENCE_EXCLUDED"
                state = EvidenceState.UNKNOWN
                freshness = FreshnessState.POST_CUTOFF
            else:
                status = CoverageState.UNKNOWN
                reason = feature.reason or "DERIVED_FEATURE_UNKNOWN"
        elif direct_facts:
            state = self._combined_state(direct_facts)
            input_ids = _sorted_unique(
                (
                    *input_ids,
                    *(assertion_id for fact in direct_facts for assertion_id in fact.assertion_ids),
                )
            )
            freshness = self._combined_freshness(direct_facts)
            ages = [
                item.age_seconds_at_cutoff
                for item in direct_facts
                if item.age_seconds_at_cutoff is not None
            ]
            kickoff_ages = [
                item.age_seconds_at_kickoff
                for item in direct_facts
                if item.age_seconds_at_kickoff is not None
            ]
            age_cutoff = min(ages) if ages else None
            age_kickoff = min(kickoff_ages) if kickoff_ages else None
            if requirement.requirement_id == "E-HEAD-TO-HEAD" and not self._h2h_is_comparable(
                direct_facts
            ):
                status = CoverageState.UNKNOWN
                reason = "H2H_COMPARABILITY_NOT_ESTABLISHED"
            elif state in {EvidenceState.OBSERVED, EvidenceState.ABSENT}:
                if freshness is FreshnessState.STALE:
                    status = CoverageState.STALE
                    reason = "EVIDENCE_STALE_AFTER_MATERIAL_CHANGE"
                elif freshness is FreshnessState.UNKNOWN:
                    status = CoverageState.UNKNOWN
                    reason = "EVIDENCE_FRESHNESS_UNKNOWN"
                else:
                    status = CoverageState.COVERED
                    reason = "CUTOFF_VALID_EVIDENCE_AVAILABLE"
            else:
                status = CoverageState.UNKNOWN
                reason = direct_facts[0].unknown_reason or "EVIDENCE_UNKNOWN"
        elif excluded_facts:
            status = CoverageState.POST_CUTOFF
            reason = "POST_CUTOFF_EVIDENCE_EXCLUDED"
            state = EvidenceState.UNKNOWN
            freshness = FreshnessState.POST_CUTOFF
        conflicting = tuple(
            conflict
            for conflict in conflicts
            if conflict.status == "UNRESOLVED" and _conflict_relevant_to_ids(conflict, input_ids)
        )
        if conflicting and (requirement.evidence_class is EvidenceClass.CRITICAL or conditional):
            status = CoverageState.CONFLICT
            reason = "UNRESOLVED_MATERIAL_CONFLICT"
        covered = status is CoverageState.COVERED
        blocks = (
            requirement.evidence_class is EvidenceClass.CRITICAL or conditional
        ) and not covered
        return RequirementEvaluation(
            family=family,
            requirement_id=requirement.requirement_id,
            mandatory_research=requirement.mandatory_research,
            catalog_class=requirement.evidence_class,
            influence=requirement.influence,
            conditional_critical=conditional,
            state=state,
            status=status,
            covered=covered,
            blocks_family=blocks,
            input_ids=input_ids,
            reason=reason,
            freshness=freshness,
            age_seconds_at_cutoff=age_cutoff,
            age_seconds_at_kickoff=age_kickoff,
        )

    @staticmethod
    def _h2h_is_comparable(facts: Sequence[SourceFact]) -> bool:
        required_checks = ("manager", "personnel", "tactics", "venue", "matchup")
        for fact in facts:
            if fact.state is not EvidenceState.OBSERVED or not isinstance(fact.value, Mapping):
                continue
            comparable = fact.value.get("comparable") is True or fact.value.get(
                "comparability"
            ) in {"COMPARABLE", "PASS"}
            checks = fact.value.get("comparability_checks", fact.value.get("checks"))
            if (
                comparable
                and isinstance(checks, Mapping)
                and all(checks.get(check) is True for check in required_checks)
            ):
                return True
        return False

    def _evidence_for_requirement(
        self,
        requirement_id: str,
        family: str,
        value: EvidenceResearchInput,
        facts: tuple[SourceFact, ...],
        excluded: tuple[SourceFact, ...],
        feature_map: Mapping[str, DerivedFeature],
    ) -> tuple[
        tuple[str, ...], tuple[SourceFact, ...], DerivedFeature | None, tuple[SourceFact, ...]
    ]:
        metric_names = self._required_metrics(requirement_id, family)
        if metric_names:
            matched = tuple(
                fact
                for fact in facts
                if fact.evidence_type == "MATCH_STATISTIC" and fact.predicate in metric_names
            )
            post = tuple(
                fact
                for fact in excluded
                if fact.evidence_type == "MATCH_STATISTIC" and fact.predicate in metric_names
            )
            return (
                _sorted_unique(
                    [fact.fact_id for fact in matched]
                    + [assertion_id for fact in matched for assertion_id in fact.assertion_ids]
                ),
                matched,
                None,
                post,
            )
        feature_name = {
            "D-HISTORICAL-BASELINE": "D-HISTORICAL-BASELINE",
            "D-OPPONENT-STRENGTH": "D-OPPONENT-STRENGTH",
            "D-RECENCY-STRENGTH": "D-RECENCY-STRENGTH",
            "D-VENUE-EFFECT": "D-VENUE-EFFECT",
            "D-FORM-HORIZONS": "D-FORM-HORIZONS",
            "D-TREND-DIRECTION": "D-TREND-DIRECTION",
            "D-SCORE-STATE": "D-SCORE-STATE",
            "D-REST": "D-REST",
            "D-CONGESTION": "D-CONGESTION",
            "D-CROSS-COMP-WORKLOAD": "D-CROSS-COMP-WORKLOAD",
            "M-WEATHER": "M-WEATHER",
            "E-TACTICAL-REGIME": "E-TACTICAL-REGIME",
        }.get(requirement_id)
        if feature_name is not None:
            feature = feature_map.get(feature_name)
            return (feature.input_ids if feature is not None else (), (), feature, ())
        aliases = {
            "M-FIXTURE": {"FIXTURE"},
            "E-MANAGER": {"MANAGER", "MANAGER_CHANGE", "MANAGER_IDENTITY"},
            "E-TACTICS": {"TACTICAL_CONTEXT", "TACTICS"},
            "E-INJURY": {"INJURY", "INJURIES"},
            "E-SUSPENSION": {"SUSPENSION", "SUSPENSIONS"},
            "E-AVAILABILITY": {"AVAILABILITY", "TEAM_AVAILABILITY"},
            "E-LINEUP-SCENARIO": {"EXPECTED_LINEUP", "LINEUP"},
            "E-ROTATION": {"ROTATION", "ROTATION_SCENARIO"},
            "E-TACTICAL-REGIME": {"REGIME_CHANGE", "MANAGER_CHANGE"},
            "M-REFEREE": {"REFEREE_APPOINTMENT"},
            "E-REFEREE-CONTEXT": {"REFEREE_CONTEXT"},
            "E-WEATHER-CONTEXT": {"WEATHER_CONTEXT", "PITCH_CONTEXT"},
            "E-HEAD-TO-HEAD": {"HEAD_TO_HEAD", "H2H"},
            "M-WEATHER": {"WEATHER"},
            "M-PENALTY-EVENT": {"PENALTY_EVENT", "PENALTY"},
            "M-PROVIDER-XG": {"PROVIDER_XG", "XG"},
        }
        types = aliases.get(requirement_id, set())
        matched = tuple(fact for fact in facts if fact.evidence_type in types)
        post = tuple(fact for fact in excluded if fact.evidence_type in types)
        if requirement_id == "E-HEAD-TO-HEAD" and value.h2h_cited:
            return (target_lineage(value.target), (), None, ())
        return (
            _sorted_unique(
                [fact.fact_id for fact in matched]
                + [assertion_id for fact in matched for assertion_id in fact.assertion_ids]
            ),
            matched,
            None,
            post,
        )

    @staticmethod
    def _required_metrics(requirement_id: str, family: str) -> set[str]:
        if requirement_id in {"M-FT-GOALS"}:
            return {"full_time_home_goals", "full_time_away_goals"}
        if requirement_id == "M-HT-GOALS":
            return {"half_time_home_goals", "half_time_away_goals"}
        if requirement_id == "M-CORNERS":
            return {"corners_home", "corners_away"}
        if requirement_id == "M-SHOTS":
            return {"shots_home", "shots_away"}
        if requirement_id == "M-SOT":
            return {"shots_on_target_home", "shots_on_target_away"}
        if requirement_id == "M-YELLOW":
            return {"yellow_cards_home", "yellow_cards_away"}
        if requirement_id == "M-RED":
            return {"red_cards_home", "red_cards_away"}
        del family
        return set()

    def _model_unavailable(
        self,
        requirement_id: str,
        family: str,
        value: EvidenceResearchInput,
        direct_facts: tuple[SourceFact, ...],
        feature: DerivedFeature | None,
        history: tuple[HistoricalMatch, ...],
    ) -> bool:
        forced = value.model_availability.get(family, value.model_availability.get(requirement_id))
        if forced is False:
            return True
        if forced is True:
            return False
        metric_names = self._required_metrics(requirement_id, family)
        if metric_names:
            if self._history_gap_applies(value, requirement_id, family, metric_names):
                return True
            return not all(
                self._metric_history_sufficient(
                    history, metric_names, value.target.cutoff_utc, team_id=team_id
                )
                for team_id in value.target.team_ids
            )
        if requirement_id in {
            "D-HISTORICAL-BASELINE",
            "D-OPPONENT-STRENGTH",
            "D-RECENCY-STRENGTH",
            "D-VENUE-EFFECT",
        }:
            needed = self._family_metric_names(family)
            if self._history_gap_applies(value, requirement_id, family, needed):
                return True
            return not all(
                self._metric_history_sufficient(
                    history, needed, value.target.cutoff_utc, team_id=team_id
                )
                for team_id in value.target.team_ids
            )
        if requirement_id in {"D-FORM-HORIZONS", "D-TREND-DIRECTION"}:
            needed = {"full_time_home_goals", "full_time_away_goals"}
            if self._history_gap_applies(value, requirement_id, family, needed):
                return True
            return not all(
                self._metric_history_sufficient(
                    history, needed, value.target.cutoff_utc, team_id=team_id
                )
                for team_id in value.target.team_ids
            )
        if requirement_id == "D-SCORE-STATE":
            return (
                feature is not None
                and feature.state is EvidenceState.UNKNOWN
                and feature.reason == "SCORE_STATE_UNKNOWN"
                and any(
                    not self._metric_history_sufficient(
                        history,
                        {"full_time_home_goals", "full_time_away_goals"},
                        value.target.cutoff_utc,
                        team_id=team_id,
                    )
                    for team_id in value.target.team_ids
                )
            )
        del direct_facts
        return False

    @staticmethod
    def _history_gap_applies(
        value: EvidenceResearchInput,
        requirement_id: str,
        family: str,
        metric_names: set[str],
    ) -> bool:
        if not value.history_gaps:
            return not value.history_complete
        gap_text = " ".join(value.history_gaps).upper().replace("_", " ")
        if requirement_id.upper() in gap_text:
            return True
        if "CORNER" in gap_text:
            return any("corner" in metric for metric in metric_names)
        if "HALF" in gap_text:
            return any("half" in metric for metric in metric_names)
        if "GOAL" in gap_text:
            return any("goal" in metric for metric in metric_names)
        if any(token in gap_text for token in ("HISTORY", "BASELINE", "FORM", "TREND")):
            return requirement_id.startswith("D-")
        return not value.history_complete

    def _family_metric_names(self, family: str) -> set[str]:
        selected = normalize_family(family)
        if selected in _CORNERS:
            return {"corners_home", "corners_away"}
        if selected in _HALF_GOALS:
            return {
                "full_time_home_goals",
                "full_time_away_goals",
                "half_time_home_goals",
                "half_time_away_goals",
            }
        return {"full_time_home_goals", "full_time_away_goals"}

    def _metric_history_sufficient(
        self,
        history: Sequence[HistoricalMatch],
        metric_names: set[str],
        cutoff_utc: str | None = None,
        team_id: str | None = None,
    ) -> bool:
        complete_rows = 0
        effective_matches = 0.0
        cutoff = _parse_utc(cutoff_utc) if cutoff_utc is not None else None
        for match in history:
            if team_id is not None and team_id not in (match.home_team_id, match.away_team_id):
                continue
            if all(
                match.metric_state(metric) is EvidenceState.OBSERVED
                and match.metrics.get(metric) is not None
                for metric in metric_names
            ):
                complete_rows += 1
                if cutoff is None:
                    effective_matches += 1.0
                else:
                    age_days = max(
                        0.0,
                        (cutoff - _parse_utc(match.kickoff_utc)).total_seconds() / 86400.0,
                    )
                    effective_matches += 2 ** (
                        -age_days / self.feature_rules.recency_half_life_days
                    )
        return (
            complete_rows >= self.feature_rules.minimum_history_matches
            and effective_matches >= self.feature_rules.minimum_effective_history_matches
        )

    @staticmethod
    def _combined_state(facts: Sequence[SourceFact]) -> EvidenceState:
        if any(item.state is EvidenceState.OBSERVED for item in facts):
            return EvidenceState.OBSERVED
        if all(item.state is EvidenceState.ABSENT for item in facts):
            return EvidenceState.ABSENT
        return EvidenceState.UNKNOWN

    @staticmethod
    def _combined_freshness(facts: Sequence[SourceFact]) -> FreshnessState:
        if any(item.freshness is FreshnessState.FRESH for item in facts):
            return FreshnessState.FRESH
        if any(item.freshness is FreshnessState.STALE for item in facts):
            return FreshnessState.STALE
        if any(item.freshness is FreshnessState.POST_CUTOFF for item in facts):
            return FreshnessState.POST_CUTOFF
        return FreshnessState.UNKNOWN

    @staticmethod
    def _gap_for(
        evaluation: RequirementEvaluation,
        attempts: Sequence[ResearchAttempt],
        *,
        decision_materiality: bool,
    ) -> EvidenceGap:
        relevant = tuple(
            item for item in attempts if item.requirement_id == evaluation.requirement_id
        )
        cutoff_relevant = tuple(
            item for item in relevant if item.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
        )
        if not cutoff_relevant or all(
            item.accessibility is AccessState.NOT_ATTEMPTED for item in cutoff_relevant
        ):
            accessibility = AccessState.NOT_ATTEMPTED
        elif all(item.accessibility is AccessState.INACCESSIBLE for item in cutoff_relevant):
            accessibility = AccessState.INACCESSIBLE
        else:
            accessibility = AccessState.ACCESSIBLE
        return EvidenceGap(
            gap_id=f"gap:{evaluation.family}:{evaluation.requirement_id}:{evaluation.status.value}",
            family=evaluation.family,
            requirement_id=evaluation.requirement_id,
            state=evaluation.state,
            reason=evaluation.reason,
            materiality=evaluation.catalog_class,
            accessibility=accessibility,
            attempted_source_keys=tuple(item.source_key for item in relevant),
            decision_materiality=decision_materiality,
            conditional_critical=evaluation.conditional_critical,
        )


@dataclass(frozen=True)
class T09Plan:
    """Immutable run identity for T09 Evidence Research."""

    friday: str
    season: str = "2026-27"
    catalog: EvidenceRequirementCatalog = DEFAULT_CATALOG
    feature_rules: FeatureRules = field(default_factory=FeatureRules)

    def __post_init__(self) -> None:
        MatchweekWindow.for_friday(self.friday)
        _text(self.season, "T09 season")
        if self.catalog.version != CATALOG_VERSION or self.catalog.digest != CATALOG_DIGEST:
            raise T09ValidationError("T09 plans require the immutable Evidence catalog v1 digest.")

    @property
    def run_key(self) -> str:
        friday = MatchweekWindow.for_friday(self.friday).friday_local.isoformat()
        return f"t09-evidence-research:{self.season}:{friday}"

    @property
    def plan_digest(self) -> str:
        friday = MatchweekWindow.for_friday(self.friday).friday_local.isoformat()
        return _digest(
            {
                "catalog_digest": self.catalog.digest,
                "catalog_version": self.catalog.version,
                "feature_rules_digest": self.feature_rules.digest,
                "friday": friday,
                "season": self.season,
            }
        )


@dataclass(frozen=True)
class T09BuildResult:
    """Durable T09 states and their verified T03 Snapshot Manifest."""

    states: tuple[FrozenEvidenceState, ...]
    manifest: SnapshotManifest
    state_artifact_digests: tuple[str, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "states", tuple(sorted(self.states, key=lambda item: item.target_fixture_id))
        )
        object.__setattr__(
            self, "state_artifact_digests", tuple(sorted(self.state_artifact_digests))
        )
        if not self.digest:
            object.__setattr__(
                self,
                "digest",
                _digest(
                    {
                        "manifest_digest": self.manifest.digest,
                        "state_digests": tuple(item.digest for item in self.states),
                        "state_artifact_digests": self.state_artifact_digests,
                    }
                ),
            )

    @property
    def evidence_states(self) -> tuple[FrozenEvidenceState, ...]:
        return self.states

    @property
    def manifest_digest(self) -> str:
        return self.manifest.digest

    @property
    def artifact_digests(self) -> tuple[str, ...]:
        return (*self.state_artifact_digests, self.manifest.digest)


def _state_status(state: FrozenEvidenceState) -> ResearchStatus:
    statuses = tuple(item.status for item in state.research_sufficiency.values())
    if statuses and all(item is ResearchStatus.SUFFICIENT for item in statuses):
        return ResearchStatus.SUFFICIENT
    if any(item is ResearchStatus.MODEL_UNAVAILABLE for item in statuses):
        return ResearchStatus.MODEL_UNAVAILABLE
    return ResearchStatus.INSUFFICIENT


class FrozenEvidenceStateRecorder:
    """Read and publish immutable Evidence State rows in the local store."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Evidence State recording requires a healthy writable store.")
        self.store = store

    @staticmethod
    def _row_id(matchweek_id: str, fixture_id: str) -> str:
        return deterministic_identifier("evidence_state", f"{matchweek_id}:{fixture_id}")

    def record(
        self,
        state: FrozenEvidenceState,
        *,
        artifact_digest: str,
        manifest_digest: str,
        frozen_at_utc: str,
    ) -> FrozenEvidenceState:
        if not state.is_frozen:
            selected = state.with_freeze_refs(
                artifact_digest=artifact_digest,
                manifest_digest=manifest_digest,
                frozen_at_utc=frozen_at_utc,
            )
        else:
            if (
                state.artifact_digest != artifact_digest
                or state.manifest_digest != manifest_digest
                or state.frozen_at_utc != _canonical_utc(frozen_at_utc)
            ):
                raise T09IntegrityError(
                    "A frozen Evidence State cannot be published with different references."
                )
            selected = state
        artifacts = ArtifactStore(self.store)
        artifact = artifacts.verify_artifact(artifact_digest)
        if artifact.media_type != EVIDENCE_STATE_MEDIA_TYPE:
            raise T09IntegrityError("The Evidence State artifact has the wrong media type.")
        if artifacts.read_artifact(artifact_digest) != selected.to_bytes():
            raise T09IntegrityError("The Evidence State artifact content does not match its state.")
        manifest = artifacts.verify_manifest(manifest_digest)
        if (
            manifest.matchweek_id.value != selected.matchweek_id
            or manifest.research_cutoff_id.value != selected.cutoff_id
            or manifest.research_cutoff_utc != selected.cutoff_utc
            or not any(reference.digest == artifact_digest for reference in manifest.artifacts)
        ):
            raise T09IntegrityError("The Evidence State is not an exact member of its manifest.")
        state_id = self._row_id(state.matchweek_id, state.target_fixture_id)
        payload = json.dumps(
            selected.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        status = _state_status(selected).value
        with self.store.transaction() as transaction:
            transaction.add_identifier_if_missing(CanonicalIdentifier("evidence_state", state_id))
            existing = transaction.execute(
                """
                SELECT state_digest, artifact_digest, manifest_digest, payload_json
                FROM evidence_states WHERE evidence_state_id = ?
                """,
                (state_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != selected.digest:
                    raise T09IntegrityError(
                        f"Frozen Evidence State {state_id} was reused with different content."
                    )
                existing_payload = str(existing[3])
                if json.loads(existing_payload) != json.loads(payload):
                    raise T09IntegrityError(
                        f"Frozen Evidence State {state_id} has different publication metadata."
                    )
                return selected
            transaction.execute(
                """
                INSERT INTO evidence_states (
                    evidence_state_id, matchweek_id, cutoff_id, target_fixture_id, state_digest,
                    artifact_digest, manifest_digest, cutoff_utc, frozen_at_utc, catalog_name,
                    catalog_version, catalog_digest, feature_rules_name, feature_rules_digest,
                    research_rules_name, research_rules_digest, research_status, payload_json,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state_id,
                    selected.matchweek_id,
                    selected.cutoff_id,
                    selected.target_fixture_id,
                    selected.digest,
                    artifact_digest,
                    manifest_digest,
                    selected.cutoff_utc,
                    selected.frozen_at_utc,
                    selected.catalog_name,
                    selected.catalog_version,
                    selected.catalog_digest,
                    selected.feature_rules_name,
                    selected.feature_rules_digest,
                    selected.research_rules_name,
                    selected.research_rules_digest,
                    status,
                    payload,
                    selected.frozen_at_utc,
                ),
            )
            for ordinal, fact in enumerate(
                (*selected.source_assertions, *selected.post_cutoff_assertions)
            ):
                transaction.execute(
                    """
                    INSERT INTO evidence_state_sources (
                        evidence_state_id, fact_id, inclusion_state, ordinal
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (state_id, fact.fact_id, _enum_value(fact.cutoff_eligibility), ordinal),
                )
            for evaluation in selected.requirement_evaluations:
                transaction.execute(
                    """
                    INSERT INTO evidence_state_requirements (
                        evidence_state_id, family, requirement_id, status, covered,
                        input_lineage_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state_id,
                        evaluation.family,
                        evaluation.requirement_id,
                        evaluation.status.value,
                        int(evaluation.covered),
                        json.dumps(evaluation.input_ids, separators=(",", ":")),
                    ),
                )
            for feature in selected.derived_features:
                transaction.execute(
                    """
                    INSERT INTO evidence_state_features (
                        evidence_state_id, feature_id, feature_digest
                    ) VALUES (?, ?, ?)
                    """,
                    (state_id, feature.feature_id, feature.digest),
                )
            for gap in selected.gaps:
                transaction.execute(
                    "INSERT INTO evidence_state_gaps (evidence_state_id, gap_id) VALUES (?, ?)",
                    (state_id, gap.gap_id),
                )
            for conflict in selected.conflicts:
                transaction.execute(
                    """
                    INSERT INTO evidence_state_conflicts (evidence_state_id, conflict_id)
                    VALUES (?, ?)
                    """,
                    (state_id, conflict.conflict_id),
                )
            for item in selected.corroboration:
                key = _digest(
                    {
                        "assertion_ids": item.assertion_ids,
                        "predicate": item.predicate,
                        "subject_id": item.subject_id,
                    }
                )
                transaction.execute(
                    """
                    INSERT INTO evidence_state_corroboration (
                        evidence_state_id, corroboration_key
                    ) VALUES (?, ?)
                    """,
                    (state_id, key),
                )
        return selected

    def get(self, matchweek_id: str, fixture_id: str) -> FrozenEvidenceState | None:
        row = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT state_digest, artifact_digest, manifest_digest, payload_json
            FROM evidence_states
            WHERE matchweek_id = ? AND target_fixture_id = ?
            """,
                (matchweek_id, fixture_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        payload = json.loads(str(row[3]))
        if not isinstance(payload, dict):
            raise T09IntegrityError("Stored Evidence State payload is not an object.")
        state = FrozenEvidenceState.from_dict(cast(Mapping[str, object], payload))
        artifacts = ArtifactStore(self.store)
        artifact = artifacts.verify_artifact(str(row[1]))
        if artifact.media_type != EVIDENCE_STATE_MEDIA_TYPE:
            raise T09IntegrityError("The stored Evidence State artifact has the wrong media type.")
        if artifacts.read_artifact(artifact.digest) != state.to_bytes():
            raise T09IntegrityError("The stored Evidence State artifact does not match its state.")
        manifest = artifacts.verify_manifest(str(row[2]))
        if (
            manifest.matchweek_id.value != state.matchweek_id
            or manifest.research_cutoff_id.value != state.cutoff_id
            or manifest.research_cutoff_utc != state.cutoff_utc
            or not any(reference.digest == artifact.digest for reference in manifest.artifacts)
        ):
            raise T09IntegrityError("The stored Evidence State manifest membership is invalid.")
        if state.digest != str(row[0]):
            raise T09IntegrityError("Stored Evidence State digest does not match its payload.")
        if state.artifact_digest != str(row[1]) or state.manifest_digest != str(row[2]):
            raise T09IntegrityError("Stored Evidence State publication references changed.")
        return state

    def records(self, matchweek_id: str) -> tuple[FrozenEvidenceState, ...]:
        rows = (
            self.store._connection_for_repository()
            .execute(
                """
            SELECT target_fixture_id FROM evidence_states
            WHERE matchweek_id = ? ORDER BY target_fixture_id
            """,
                (matchweek_id,),
            )
            .fetchall()
        )
        result = []
        for row in rows:
            state = self.get(matchweek_id, str(row[0]))
            if state is None:
                raise T09IntegrityError("Evidence State row disappeared while reading.")
            result.append(state)
        return tuple(result)

    read = get


def _json_object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise T09IntegrityError(f"{label} must be a JSON object.")
    return cast(Mapping[str, object], value)


def _t06_target(
    store: Store,
    membership: FrozenMembership,
    cutoff_utc: str,
    cutoff_id: str,
    overrides: Mapping[str, TargetMatch],
) -> TargetMatch:
    override = overrides.get(membership.subject_id)
    if override is not None:
        if (
            override.fixture_id != membership.subject_id
            or override.matchweek_id != membership.matchweek_id
            or override.cutoff_id != cutoff_id
            or override.cutoff_utc != _canonical_utc(cutoff_utc)
            or override.kickoff_utc != membership.original_kickoff_utc
        ):
            raise T09IntegrityError("A Target Match override disagrees with frozen T05 membership.")
        if membership.controlling_revision_digest is not None:
            revision = (
                store._connection_for_repository()
                .execute(
                    "SELECT revision_digest FROM fixture_revisions WHERE revision_id = ?",
                    (membership.controlling_revision_id,),
                )
                .fetchone()
            )
            if revision is None or str(revision[0]) != membership.controlling_revision_digest:
                raise T09IntegrityError("The T05 controlling Fixture Revision digest changed.")
        return override
    connection = store._connection_for_repository()
    row = connection.execute(
        """
        SELECT f.fixture_id, f.home_team_id, f.away_team_id, l.league_key,
               l.canonical_name, s.season_label, r.kickoff_utc, r.fixture_status,
               r.observed_at_utc, r.source_assertion_ids_json, r.revision_id,
               r.revision_digest
        FROM fixtures AS f
        JOIN target_leagues AS l ON l.league_id = f.league_id
        JOIN competition_seasons AS s ON s.season_id = f.season_id
        JOIN fixture_revisions AS r ON r.fixture_id = f.fixture_id
        WHERE f.fixture_id = ? AND r.revision_id = ?
        """,
        (membership.subject_id, membership.controlling_revision_id),
    ).fetchone()
    if row is None or membership.controlling_revision_id is None:
        raise T09IntegrityError("The T05 controlling Fixture Revision is unavailable.")
    if str(row[11]) != membership.controlling_revision_digest:
        raise T09IntegrityError("The T05 controlling Fixture Revision digest changed.")
    kickoff = row[6]
    if kickoff is None:
        raise T09IntegrityError("A frozen Target Match has no kickoff timestamp.")
    if _canonical_utc(str(kickoff)) != membership.original_kickoff_utc:
        raise T09IntegrityError("The T05 Target Match kickoff changed.")
    if row[8] is not None and _parse_utc(str(row[8])) > _parse_utc(cutoff_utc):
        raise T09IntegrityError("The controlling Target Match revision was observed after cutoff.")
    try:
        assertion_ids_raw = json.loads(str(row[9]))
    except json.JSONDecodeError as error:
        raise T09IntegrityError("The controlling revision assertion list is malformed.") from error
    assertion_ids = (
        tuple(item for item in assertion_ids_raw if isinstance(item, str))
        if isinstance(assertion_ids_raw, list)
        else ()
    )
    return TargetMatch(
        matchweek_id=membership.matchweek_id,
        cutoff_id=cutoff_id,
        fixture_id=str(row[0]),
        cutoff_utc=cutoff_utc,
        kickoff_utc=str(kickoff),
        home_team_id=str(row[1]),
        away_team_id=str(row[2]),
        competition_key=str(row[3]),
        competition_name=str(row[4]),
        season=str(row[5]),
        fixture_status=str(row[7]),
        source_assertion_ids=assertion_ids or (str(row[10]),),
    )


def _t06_history_and_facts(
    store: Store,
    *,
    season: str,
    cutoff_utc: str,
    excluded_fixture_ids: Iterable[str] = (),
) -> tuple[tuple[HistoricalMatch, ...], tuple[SourceFact, ...]]:
    connection = store._connection_for_repository()
    cutoff = _parse_utc(cutoff_utc)
    excluded = set(excluded_fixture_ids)
    fixture_rows = connection.execute(
        """
        SELECT f.fixture_id, f.home_team_id, f.away_team_id, l.league_key,
               r.revision_id, r.revision_digest, r.kickoff_utc, r.fixture_status,
               r.observed_at_utc, sc.content_sha256, sc.retrieved_at_utc,
               sc.source_published_at_utc, si.source_key
        FROM fixtures AS f
        JOIN target_leagues AS l ON l.league_id = f.league_id
        JOIN competition_seasons AS s ON s.season_id = f.season_id
        JOIN fixture_revisions AS r ON r.fixture_id = f.fixture_id
        JOIN source_captures AS sc ON sc.capture_id = r.source_capture_id
        JOIN source_identities AS si ON si.source_id = sc.source_id
        WHERE s.season_label = ?
        ORDER BY f.fixture_id, r.observed_at_utc, r.revision_id
        """,
        (season,),
    ).fetchall()
    candidates: dict[str, tuple[object, ...]] = {}
    for row in fixture_rows:
        fixture_id = str(row[0])
        if fixture_id in excluded:
            continue
        if row[6] is None or str(row[7]).upper() not in {"COMPLETED", "FINAL", "FINISHED"}:
            continue
        if _parse_utc(str(row[6])) > cutoff:
            continue
        if row[8] is not None and _parse_utc(str(row[8])) > cutoff:
            continue
        if row[10] is not None and _parse_utc(str(row[10])) > cutoff:
            continue
        if row[11] is not None and _parse_utc(str(row[11])) > cutoff:
            continue
        prior = candidates.get(fixture_id)
        if prior is None or (str(row[8]), str(row[4])) > (str(prior[8]), str(prior[4])):
            candidates[fixture_id] = tuple(row)
    histories: list[HistoricalMatch] = []
    raw_facts: list[SourceFact] = []
    for fixture_id, row in sorted(candidates.items()):
        stat_rows = connection.execute(
            """
            SELECT ms.statistic_id, ms.metric_key, ms.team_role, ms.phase,
                   ms.evidence_class, ms.evidence_state, ms.value_integer,
                   ms.value_text, ms.unknown_reason, ms.source_assertion_id,
                   sc.content_sha256, sc.retrieved_at_utc, sc.source_published_at_utc,
                   si.source_key, sa.origin_id, sa.event_time_utc,
                   sa.effective_time_utc, sa.created_at_utc
            FROM match_statistics AS ms
            JOIN source_assertions AS sa ON sa.assertion_id = ms.source_assertion_id
            JOIN source_captures AS sc ON sc.capture_id = sa.capture_id
            JOIN source_identities AS si ON si.source_id = sc.source_id
            WHERE ms.fixture_id = ?
            ORDER BY ms.metric_key, ms.team_role, ms.phase, ms.statistic_id
            """,
            (fixture_id,),
        ).fetchall()
        values: dict[str, int | None] = {}
        states: dict[str, EvidenceState] = {}
        input_ids: dict[str, tuple[str, ...]] = {}
        source_ids: list[str] = []
        source_digest: str | None = None
        selected_stats: dict[str, tuple[tuple[int, str, str], sqlite3.Row, EvidenceState]] = {}
        for stat in stat_rows:
            metric = str(stat[1])
            if metric not in {
                "full_time_home_goals",
                "full_time_away_goals",
                "half_time_home_goals",
                "half_time_away_goals",
                "corners_home",
                "corners_away",
                "shots_home",
                "shots_away",
                "shots_on_target_home",
                "shots_on_target_away",
                "yellow_cards_home",
                "yellow_cards_away",
                "red_cards_home",
                "red_cards_away",
            }:
                continue
            state = EvidenceState(str(stat[5]))
            stat_times = (stat[11], stat[12], stat[15], stat[16], stat[17])
            if stat[11] is None or stat[17] is None:
                stat_eligibility = CutoffEligibility.INDETERMINATE
            elif any(value is not None and _parse_utc(str(value)) > cutoff for value in stat_times):
                stat_eligibility = CutoffEligibility.POST_CUTOFF
            else:
                stat_eligibility = CutoffEligibility.CUTOFF_VALID
            raw_facts.append(
                SourceFact(
                    fact_id=str(stat[0]),
                    subject_id=fixture_id,
                    evidence_type="MATCH_STATISTIC",
                    predicate=metric,
                    state=state,
                    value=int(stat[6])
                    if state is EvidenceState.OBSERVED and stat[6] is not None
                    else None,
                    evidence_class=(
                        EvidenceClass.CRITICAL
                        if str(stat[4]) == "CORE"
                        else EvidenceClass.IMPORTANT
                    ),
                    source_key=str(stat[13]),
                    origin_id=str(stat[14]) if stat[14] is not None else str(stat[13]),
                    source_assertion_ids=(str(stat[0]), str(stat[9])),
                    source_digest=str(stat[10]),
                    published_at_utc=str(stat[12]) if stat[12] is not None else None,
                    observed_at_utc=str(stat[11]) if stat[11] is not None else None,
                    event_time_utc=(str(stat[15]) if stat[15] is not None else str(row[6])),
                    effective_time_utc=str(stat[16]) if stat[16] is not None else None,
                    cutoff_eligibility=stat_eligibility,
                    correlation_groups=(
                        "goals/results"
                        if "goals" in metric
                        else "corners"
                        if "corners" in metric
                        else "shots/chances"
                        if "shots" in metric
                        else "discipline/match-state",
                    ),
                    unknown_reason=(
                        str(stat[8]) if stat[8] is not None else "STRUCTURED_METRIC_NOT_AVAILABLE"
                    )
                    if state is EvidenceState.UNKNOWN
                    else None,
                    affirmative_basis=(
                        "STRUCTURED_STATISTIC_RECORD" if state is EvidenceState.ABSENT else None
                    ),
                    provenance={
                        "fixture_id": fixture_id,
                        "statistic_id": str(stat[0]),
                        "source_assertion_id": str(stat[9]),
                    },
                )
            )
            if stat_eligibility is CutoffEligibility.CUTOFF_VALID:
                rank = (
                    1 if state is EvidenceState.OBSERVED else 0,
                    str(stat[11]),
                    str(stat[0]),
                )
                previous = selected_stats.get(metric)
                if previous is None or rank > previous[0]:
                    selected_stats[metric] = (rank, stat, state)
        for metric, (_, stat, state) in selected_stats.items():
            values[metric] = int(stat[6]) if stat[6] is not None else None
            states[metric] = state
            source_ids.extend((str(stat[0]), str(stat[9])))
            input_ids[metric] = (str(stat[0]), str(stat[9]))
            source_digest = str(stat[10])
        histories.append(
            HistoricalMatch(
                fixture_id=fixture_id,
                home_team_id=str(row[1]),
                away_team_id=str(row[2]),
                kickoff_utc=str(row[6]),
                full_time_home_goals=values.get("full_time_home_goals"),
                full_time_away_goals=values.get("full_time_away_goals"),
                half_time_home_goals=values.get("half_time_home_goals"),
                half_time_away_goals=values.get("half_time_away_goals"),
                corners_home=values.get("corners_home"),
                corners_away=values.get("corners_away"),
                shots_home=values.get("shots_home"),
                shots_away=values.get("shots_away"),
                shots_on_target_home=values.get("shots_on_target_home"),
                shots_on_target_away=values.get("shots_on_target_away"),
                yellow_cards_home=values.get("yellow_cards_home"),
                yellow_cards_away=values.get("yellow_cards_away"),
                red_cards_home=values.get("red_cards_home"),
                red_cards_away=values.get("red_cards_away"),
                metric_states=states,
                metric_input_ids=input_ids,
                source_assertion_ids=tuple(sorted(set(source_ids))) or (str(row[4]),),
                source_digest=source_digest or str(row[5]),
                source_key=str(row[12]),
                origin_id=str(row[12]),
                observed_at_utc=str(row[8]) if row[8] is not None else None,
                published_at_utc=str(row[11]) if row[11] is not None else None,
                competition_key=str(row[3]),
                competition_type="TARGET_LEAGUE",
                fixture_status=str(row[7]),
            )
        )
    return tuple(histories), tuple(raw_facts)


def _version_identity(
    *,
    kind: str,
    name: str,
    content_sha256: str,
    created_at_utc: str,
) -> VersionIdentity:
    return VersionIdentity(
        identifier=CanonicalIdentifier(
            "version",
            deterministic_identifier("version", f"{kind}:{name}:{content_sha256}"),
        ),
        definition_id=CanonicalIdentifier(
            "version_definition",
            deterministic_identifier("version_definition", f"{kind}:{name}"),
        ),
        kind=kind,
        name=name,
        content_sha256=content_sha256,
        canonical_contract_version=1,
        created_at_utc=created_at_utc,
    )


def _ensure_versions(store: Store, versions: Sequence[VersionIdentity]) -> None:
    with store.transaction() as transaction:
        for version in versions:
            stored = store.version(version.identifier)
            if stored is None:
                transaction.add_version(version)
            elif (
                stored.definition_id != version.definition_id
                or stored.kind != version.kind
                or stored.name != version.name
                or stored.content_sha256 != version.content_sha256
                or stored.canonical_contract_version != version.canonical_contract_version
            ):
                raise T09IntegrityError(
                    f"Version {version.identifier.value} was reused differently."
                )


def _contextual_facts_from_store(store: Store, target: TargetMatch) -> tuple[SourceFact, ...]:
    recorder = EvidenceRecorder(store)
    records: list[SourceFact] = []
    subjects = (
        ("FIXTURE", target.fixture_id),
        ("TEAM", target.home_team_id),
        ("TEAM", target.away_team_id),
    )
    for subject_kind, subject_id in subjects:
        try:
            rows = recorder.assertions(
                subject_kind,
                subject_id,
                cutoff_utc=target.cutoff_utc,
                include_unknown=True,
            )
        except ValueError, sqlite3.DatabaseError:
            # T06-only stores do not have T07 assertions for every subject.
            rows = ()
        records.extend(_record_to_source_fact(row) for row in rows)
    return tuple(sorted(records, key=lambda item: item.fact_id))


def _t08_maps(value: object | None) -> tuple[dict[str, object], dict[str, object], str | None]:
    if value is None:
        return {}, {}, None
    selected = getattr(value, "evidence", value)
    if selected is not value and selected is not None:
        value = selected
    if isinstance(value, Mapping):
        workload_raw = value.get("workload", ())
        weather_raw = value.get("weather", ())
        digest = value.get("digest") if isinstance(value.get("digest"), str) else None
    else:
        workload_raw = getattr(value, "workload", ())
        weather_raw = getattr(value, "weather", ())
        digest_value = getattr(value, "digest", None)
        digest = digest_value if isinstance(digest_value, str) else None
    workload: dict[str, object] = {}
    weather: dict[str, object] = {}
    workload_raw_values: Iterable[object]
    if isinstance(workload_raw, Mapping):
        workload_raw_values = workload_raw.values()
    else:
        workload_raw_values = _as_sequence(workload_raw)
    for item in workload_raw_values:
        mapped = _object_dict(item)
        if mapped is None:
            continue
        identifier = _workload_id(item)
        target_fixture_id = mapped.get("target_fixture_id")
        if isinstance(target_fixture_id, str):
            if identifier is not None:
                mapped = {**mapped, "workload_evidence_id": identifier}
            workload[target_fixture_id] = mapped
    weather_raw_values: Iterable[object]
    if isinstance(weather_raw, Mapping):
        weather_raw_values = weather_raw.values()
    else:
        weather_raw_values = _as_sequence(weather_raw)
    for item in weather_raw_values:
        mapped = _object_dict(item)
        if mapped is None:
            continue
        identifier = _weather_id(item)
        target_fixture_id = mapped.get("fixture_id", mapped.get("target_fixture_id"))
        if isinstance(target_fixture_id, str):
            if identifier is not None:
                mapped = {**mapped, "weather_evidence_id": identifier}
            weather[target_fixture_id] = mapped
    return workload, weather, digest


def materialize_context(
    value: Mapping[str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]]
    | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]],
) -> (
    Mapping[str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]]
    | tuple[SourceFact | EvidenceAssertionRecord | Mapping[str, object], ...]
):
    if isinstance(value, Mapping):
        return dict(value)
    return tuple(value)


def _stored_t08_maps(
    store: Store, matchweek_id: str
) -> tuple[dict[str, object], dict[str, object], str | None]:
    from matchvet.weather import WeatherEvidenceRecorder
    from matchvet.workload import WorkloadEvidenceRecorder

    workload: dict[str, object] = {}
    for row in WorkloadEvidenceRecorder(store).records(matchweek_id):
        workload[row.target_fixture_id] = {
            **dict(row.payload),
            "workload_evidence_id": row.workload_evidence_id,
            "state": row.evidence_state.value,
            "evidence_digest": row.evidence_digest,
            "cutoff_eligibility": "CUTOFF_VALID",
        }
    weather: dict[str, object] = {}
    for weather_row in WeatherEvidenceRecorder(store).records(matchweek_id):
        evidence = weather_row.evidence.to_dict()
        evidence["weather_evidence_id"] = weather_row.weather_evidence_id
        evidence["evidence_digest"] = weather_row.evidence_digest
        weather[weather_row.target_fixture_id] = evidence
    digest = _digest(
        {
            "weather": weather,
            "workload": workload,
        }
    )
    return workload, weather, digest


def _manifest_artifacts(store: Store, digests: Iterable[str]) -> tuple[ManifestArtifact, ...]:
    artifacts = ArtifactStore(store)
    result: list[ManifestArtifact] = []
    for digest in sorted(set(digests)):
        metadata = artifacts.verify_artifact(digest)
        result.append(
            ManifestArtifact(
                artifact_id=metadata.artifact_id,
                digest=metadata.digest,
                media_type=metadata.media_type,
                byte_length=metadata.byte_length,
            )
        )
    return tuple(result)


class T09EvidenceBuilder:
    """Combine T06--T08 data and publish immutable T09 states."""

    def __init__(
        self,
        store: Store,
        *,
        catalog: EvidenceRequirementCatalog = DEFAULT_CATALOG,
        feature_rules: FeatureRules | None = None,
        target_matches: Mapping[str, TargetMatch] | Iterable[TargetMatch] = (),
        contextual_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]] = (),
        source_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        | None = None,
        t08_evidence: object | None = None,
        workload_evidence: Mapping[str, object] | None = None,
        weather_evidence: Mapping[str, object] | None = None,
        mandatory_research: tuple[ResearchAttempt, ...] | None = None,
        material_scenarios: Iterable[MaterialScenario] = (),
        model_availability: Mapping[str, bool] | None = None,
        manifest_verified_at_utc: str | None = None,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("Evidence State building requires a healthy writable store.")
        self.store = store
        self.catalog = catalog
        self.feature_rules = feature_rules or FeatureRules()
        selected_context = (
            source_assertions if source_assertions is not None else contextual_assertions
        )
        self.contextual_assertions = selected_context
        self.target_matches = (
            dict(target_matches)
            if isinstance(target_matches, Mapping)
            else {item.fixture_id: item for item in target_matches}
        )
        self.t08_evidence = t08_evidence
        self.workload_evidence = dict(workload_evidence or {})
        self.weather_evidence = dict(weather_evidence or {})
        self.mandatory_research = mandatory_research
        self.material_scenarios = tuple(material_scenarios)
        self.model_availability = dict(model_availability or {})
        self.manifest_verified_at_utc = manifest_verified_at_utc
        self.failure_hook = failure_hook
        self.last_result: T09BuildResult | None = None

    def build(self, freeze: MatchweekFreeze) -> T09BuildResult:
        if not isinstance(freeze, MatchweekFreeze):
            raise T09ValidationError("T09 building requires a frozen T05 Matchweek.")
        target_memberships = tuple(sorted(freeze.target_matches, key=lambda item: item.subject_id))
        history, structured_facts = _t06_history_and_facts(
            self.store,
            season=freeze.season,
            cutoff_utc=freeze.cutoff.cutoff_utc,
            excluded_fixture_ids=(item.subject_id for item in target_memberships),
        )
        stored_workload, stored_weather, stored_t08_digest = _stored_t08_maps(
            self.store, freeze.cutoff.matchweek_id
        )
        supplied_workload, supplied_weather, supplied_t08_digest = _t08_maps(self.t08_evidence)
        stored_workload.update(supplied_workload)
        stored_weather.update(supplied_weather)
        stored_workload.update(self.workload_evidence)
        stored_weather.update(self.weather_evidence)
        t08_digest = supplied_t08_digest or stored_t08_digest
        states: list[FrozenEvidenceState] = []
        artifacts: list[str] = []
        for index, membership in enumerate(target_memberships, start=1):
            if self.failure_hook is not None:
                self.failure_hook(index, membership)
            target = _t06_target(
                self.store,
                membership,
                freeze.cutoff.cutoff_utc,
                freeze.cutoff.cutoff_id,
                self.target_matches,
            )
            context = self._context_for(target.fixture_id)
            if not context:
                context = _contextual_facts_from_store(self.store, target)
            last_events = self._last_material_events(context)
            input_value = EvidenceResearchInput(
                target=target,
                history=history,
                source_assertions=tuple([*context, *structured_facts]),
                workload=stored_workload.get(target.fixture_id),
                weather=stored_weather.get(target.fixture_id),
                mandatory_research=self.mandatory_research,
                material_scenarios=self.material_scenarios,
                model_availability=self.model_availability,
                history_complete=bool(history),
                history_gaps=() if history else ("NO_COMPLETED_HISTORY",),
                last_material_event_by_team=last_events,
                reproducibility={
                    "t05_snapshot_manifest_digest": freeze.snapshot_manifest_digest,
                    "t05_membership_manifest_digest": freeze.membership_manifest_digest,
                    "t05_revision_snapshot_digest": freeze.revision_snapshot_digest,
                    "t08_evidence_digest": t08_digest,
                },
            )
            state = EvidenceResearcher(
                catalog=self.catalog,
                feature_rules=self.feature_rules,
            ).build(input_value)
            publication = ArtifactStore(self.store).publish_artifact(
                state.to_bytes(),
                EVIDENCE_STATE_MEDIA_TYPE,
                expected_digest=hashlib.sha256(state.to_bytes()).hexdigest(),
                retention_class="PROTECTED",
            )
            states.append(state)
            artifacts.append(publication.digest)
        versions = (
            _version_identity(
                kind="evidence_catalog",
                name=self.catalog.name,
                content_sha256=self.catalog.digest,
                created_at_utc=freeze.cutoff.cutoff_utc,
            ),
            _version_identity(
                kind="feature_rules",
                name=self.feature_rules.name,
                content_sha256=self.feature_rules.digest,
                created_at_utc=freeze.cutoff.cutoff_utc,
            ),
            _version_identity(
                kind="research_rules",
                name=RESEARCH_RULES_NAME,
                content_sha256=_digest(
                    {
                        "catalog_digest": self.catalog.digest,
                        "feature_rules_digest": self.feature_rules.digest,
                    }
                ),
                created_at_utc=freeze.cutoff.cutoff_utc,
            ),
        )
        _ensure_versions(self.store, versions)
        all_artifact_digests = (
            freeze.snapshot_manifest_digest,
            freeze.membership_manifest_digest,
            freeze.revision_snapshot_digest,
            *artifacts,
        )
        omissions = tuple(
            RetentionOmission(fact.fact_id, "POST_CUTOFF_OR_INDETERMINATE_EXCLUDED_FROM_INPUTS")
            for state in states
            for fact in state.post_cutoff_assertions
        )
        manifest = SnapshotManifest(
            snapshot_id=CanonicalIdentifier(
                "snapshot_manifest",
                deterministic_identifier("snapshot_manifest", f"t09:{freeze.cutoff.matchweek_id}"),
            ),
            matchweek_id=CanonicalIdentifier("matchweek", freeze.cutoff.matchweek_id),
            research_cutoff_id=CanonicalIdentifier("research_cutoff", freeze.cutoff.cutoff_id),
            version_manifest_id=CanonicalIdentifier(
                "version_manifest",
                deterministic_identifier("version_manifest", f"t09:{freeze.cutoff.matchweek_id}"),
            ),
            research_cutoff_utc=freeze.cutoff.cutoff_utc,
            artifacts=_manifest_artifacts(self.store, all_artifact_digests),
            versions=tuple(
                sorted(
                    (ManifestVersion.from_identity(item) for item in versions),
                    key=lambda item: item.version_id.value,
                )
            ),
            retention_omissions=tuple(
                sorted(set(omissions), key=lambda item: (item.identifier, item.reason))
            ),
            completeness=ManifestCompleteness(
                "COMPLETE" if len(states) == len(target_memberships) else "INCOMPLETE",
                () if len(states) == len(target_memberships) else ("TARGET_EVIDENCE_STATES",),
            ),
            created_at_utc=freeze.cutoff.cutoff_utc,
        )
        manifest_record = ArtifactStore(self.store).publish_manifest(
            manifest,
            verified_at_utc=self.manifest_verified_at_utc,
        )
        verified_manifest = ArtifactStore(self.store).verify_manifest(manifest_record.digest)
        recorder = FrozenEvidenceStateRecorder(self.store)
        frozen_states: list[FrozenEvidenceState] = []
        for state, artifact_digest in zip(states, artifacts, strict=True):
            frozen_states.append(
                recorder.record(
                    state,
                    artifact_digest=artifact_digest,
                    manifest_digest=verified_manifest.digest,
                    frozen_at_utc=freeze.cutoff.cutoff_utc,
                )
            )
        result = T09BuildResult(tuple(frozen_states), verified_manifest, tuple(artifacts))
        self.last_result = result
        return result

    def _context_for(
        self, fixture_id: str
    ) -> tuple[SourceFact | EvidenceAssertionRecord | Mapping[str, object], ...]:
        if isinstance(self.contextual_assertions, Mapping):
            selected = self.contextual_assertions.get(fixture_id, ())
            return tuple(selected)
        return tuple(self.contextual_assertions)

    @staticmethod
    def _last_material_events(
        facts: Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]],
    ) -> Mapping[str, str]:
        result: dict[str, str] = {}
        for raw in facts:
            fact = _source_fact(raw)
            if fact.evidence_type not in {"MANAGER_CHANGE", "REGIME_CHANGE"}:
                continue
            timestamp = fact.effective_time_utc or fact.event_time_utc or fact.observed_at_utc
            if timestamp is not None and timestamp > result.get(fact.subject_id, ""):
                result[fact.subject_id] = timestamp
        return result


def _contract_value(value: object) -> object:
    if isinstance(value, SourceFact):
        return value.to_dict()
    if isinstance(value, EvidenceAssertionRecord):
        return _record_to_source_fact(value).to_dict()
    mapped = _object_dict(value)
    if mapped is not None:
        return mapped
    if isinstance(value, Mapping):
        return {str(key): _contract_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_contract_value(item) for item in value]
    return value


def _store_source_digest(store: Store, matchweek_id: str) -> str:
    connection = store._connection_for_repository()
    payload: dict[str, object] = {}
    for table, order in (
        ("fixture_revisions", "revision_id"),
        ("match_statistics", "statistic_id"),
        ("source_assertions", "assertion_id"),
        ("evidence_assertions", "assertion_id"),
        ("evidence_cutoff_assessments", "assessment_id"),
        ("evidence_conflicts", "conflict_id"),
        ("workload_evidence", "workload_evidence_id"),
        ("weather_evidence", "weather_evidence_id"),
    ):
        rows: Iterable[sqlite3.Row]
        try:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        except sqlite3.DatabaseError:
            rows = ()
        payload[table] = [tuple(row) for row in rows]
    payload["matchweek_id"] = matchweek_id
    return _digest(payload)


def build_t09_input_contract(
    store: Store,
    plan: T09Plan,
    *,
    target_matches: Mapping[str, TargetMatch] | Iterable[TargetMatch] = (),
    contextual_assertions: Mapping[
        str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
    ]
    | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]] = (),
    source_assertions: Mapping[
        str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
    ]
    | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
    | None = None,
    t08_evidence: object | None = None,
    workload_evidence: Mapping[str, object] | None = None,
    weather_evidence: Mapping[str, object] | None = None,
    mandatory_research: tuple[ResearchAttempt, ...] | None = None,
    material_scenarios: Iterable[MaterialScenario] = (),
    model_availability: Mapping[str, bool] | None = None,
    manifest_verified_at_utc: str | None = None,
) -> RunInputContract:
    freeze = read_frozen_matchweek(store, plan.friday, season=plan.season)
    selected_context = materialize_context(
        source_assertions if source_assertions is not None else contextual_assertions
    )
    supplied_workload, supplied_weather, supplied_t08_digest = _t08_maps(t08_evidence)
    source_payload = {
        "contextual_assertions": _contract_value(selected_context),
        "mandatory_research": _contract_value(mandatory_research),
        "manifest_verified_at_utc": manifest_verified_at_utc,
        "store_digest": _store_source_digest(store, freeze.cutoff.matchweek_id),
        "t08": _contract_value(t08_evidence),
        "weather_evidence": _contract_value(weather_evidence or supplied_weather),
        "workload_evidence": _contract_value(workload_evidence or supplied_workload),
    }
    source_digest = _digest(source_payload)
    schema_identity = ":".join(migration.checksum for migration in MIGRATIONS)
    scenarios = tuple(material_scenarios)
    target_payload = _contract_value(
        dict(target_matches) if isinstance(target_matches, Mapping) else tuple(target_matches)
    )
    t08_digest = supplied_t08_digest or _store_source_digest(store, freeze.cutoff.matchweek_id)
    return RunInputContract.from_values(
        {
            "source": f"T06_T07_T08:{source_digest}",
            "cutoff": (
                f"T05:{freeze.cutoff.cutoff_utc}:{freeze.snapshot_manifest_digest}:"
                f"{freeze.membership_manifest_digest}:{freeze.revision_snapshot_digest}"
            ),
            "preference_set": f"T09:FAMILIES:{_digest(target_payload)}",
            "policy": f"T09:CUTOFF_ONLY:CATALOG:{plan.catalog.digest}",
            "model": f"T09:NO_PROBABILITY_MODEL:{_digest(model_availability or {})}",
            "feature": f"{plan.feature_rules.name}:{plan.feature_rules.digest}",
            "research_rule": (
                f"{RESEARCH_RULES_NAME}:{plan.catalog.version}:{plan.catalog.digest}:"
                f"{_digest(scenarios)}:{t08_digest}"
            ),
            "canonical_contract": "MATCHVET_CANONICAL_CONTRACT_V1",
            "schema": schema_identity,
            "environment": "T09:LOCAL_ONLY:CUTOFF_FROZEN_INPUTS",
            "software": "MATCHVET_T09_EVIDENCE_RESEARCH_V1",
        },
        artifact_digests=(
            freeze.snapshot_manifest_digest,
            freeze.membership_manifest_digest,
            freeze.revision_snapshot_digest,
        ),
        predecessor_digests=(
            freeze.snapshot_manifest_digest,
            freeze.membership_manifest_digest,
            freeze.revision_snapshot_digest,
        ),
    )


def _existing_t09_result(store: Store, freeze: MatchweekFreeze) -> T09BuildResult | None:
    snapshot_id = deterministic_identifier("snapshot_manifest", f"t09:{freeze.cutoff.matchweek_id}")
    manifest_digest = store.snapshot_manifest_digest_for_snapshot(snapshot_id)
    if manifest_digest is None:
        return None
    manifest = ArtifactStore(store).verify_manifest(manifest_digest)
    states = FrozenEvidenceStateRecorder(store).records(freeze.cutoff.matchweek_id)
    if not states:
        return None
    artifacts = tuple(
        state.artifact_digest for state in states if state.artifact_digest is not None
    )
    if len(artifacts) != len(states):
        raise T09IntegrityError("A published T09 state is missing its artifact reference.")
    return T09BuildResult(states, manifest, artifacts)


class T09EvidenceRunner:
    """Run T09 through T04 checkpoints and exact-input resume validation."""

    def __init__(self, store: Store) -> None:
        if store.status.mode.value != "READ_WRITE":
            raise PermissionError("T09 run coordination requires a healthy writable store.")
        self.store = store
        self.last_result: T09BuildResult | None = None

    def start(
        self,
        plan: T09Plan,
        *,
        observation: ResourceObservation,
        target_matches: Mapping[str, TargetMatch] | Iterable[TargetMatch] = (),
        contextual_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]] = (),
        source_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        | None = None,
        t08_evidence: object | None = None,
        workload_evidence: Mapping[str, object] | None = None,
        weather_evidence: Mapping[str, object] | None = None,
        mandatory_research: tuple[ResearchAttempt, ...] | None = None,
        material_scenarios: Iterable[MaterialScenario] = (),
        model_availability: Mapping[str, bool] | None = None,
        manifest_verified_at_utc: str | None = None,
        progress: Callable[[RunStatus], None] | None = None,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> RunStatus:
        context = materialize_context(
            source_assertions if source_assertions is not None else contextual_assertions
        )
        scenarios = tuple(material_scenarios)
        targets = (
            dict(target_matches) if isinstance(target_matches, Mapping) else tuple(target_matches)
        )
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        status = coordinator.start(
            matchweek=plan.run_key,
            inputs=build_t09_input_contract(
                self.store,
                plan,
                target_matches=targets,
                contextual_assertions=context,
                t08_evidence=t08_evidence,
                workload_evidence=workload_evidence,
                weather_evidence=weather_evidence,
                mandatory_research=mandatory_research,
                material_scenarios=scenarios,
                model_availability=model_availability,
                manifest_verified_at_utc=manifest_verified_at_utc,
            ),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda work: self._execute(
                plan,
                work,
                target_matches=targets,
                contextual_assertions=context,
                t08_evidence=t08_evidence,
                workload_evidence=workload_evidence,
                weather_evidence=weather_evidence,
                mandatory_research=mandatory_research,
                material_scenarios=scenarios,
                model_availability=model_availability,
                manifest_verified_at_utc=manifest_verified_at_utc,
                failure_hook=failure_hook,
            ),
            progress=progress,
        )
        return status

    def resume(
        self,
        run_id: str,
        plan: T09Plan,
        *,
        observation: ResourceObservation,
        target_matches: Mapping[str, TargetMatch] | Iterable[TargetMatch] = (),
        contextual_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]] = (),
        source_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        | None = None,
        t08_evidence: object | None = None,
        workload_evidence: Mapping[str, object] | None = None,
        weather_evidence: Mapping[str, object] | None = None,
        mandatory_research: tuple[ResearchAttempt, ...] | None = None,
        material_scenarios: Iterable[MaterialScenario] = (),
        model_availability: Mapping[str, bool] | None = None,
        manifest_verified_at_utc: str | None = None,
        progress: Callable[[RunStatus], None] | None = None,
        failure_hook: Callable[[int, FrozenMembership], None] | None = None,
    ) -> RunStatus:
        context = materialize_context(
            source_assertions if source_assertions is not None else contextual_assertions
        )
        scenarios = tuple(material_scenarios)
        targets = (
            dict(target_matches) if isinstance(target_matches, Mapping) else tuple(target_matches)
        )
        coordinator = RunCoordinator(self.store, budget=SETTLED_RESOURCE_BUDGET)
        status = coordinator.resume(
            run_id,
            inputs=build_t09_input_contract(
                self.store,
                plan,
                target_matches=targets,
                contextual_assertions=context,
                t08_evidence=t08_evidence,
                workload_evidence=workload_evidence,
                weather_evidence=weather_evidence,
                mandatory_research=mandatory_research,
                material_scenarios=scenarios,
                model_availability=model_availability,
                manifest_verified_at_utc=manifest_verified_at_utc,
            ),
            estimate=self._estimate(plan),
            observation=observation,
            executor=lambda work: self._execute(
                plan,
                work,
                target_matches=targets,
                contextual_assertions=context,
                t08_evidence=t08_evidence,
                workload_evidence=workload_evidence,
                weather_evidence=weather_evidence,
                mandatory_research=mandatory_research,
                material_scenarios=scenarios,
                model_availability=model_availability,
                manifest_verified_at_utc=manifest_verified_at_utc,
                failure_hook=failure_hook,
            ),
            progress=progress,
        )
        self.last_result = _existing_t09_result(
            self.store, read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        )
        return status

    def _estimate(self, plan: T09Plan) -> ResourceEstimate:
        freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        target_count = max(1, len(freeze.target_matches))
        return ResourceEstimate(
            storage_growth_bytes=target_count * 512 * 1024,
            peak_memory_bytes=384 * MIB,
            duration_seconds=60 + target_count * 20,
            network_bytes=0,
            cpu_heavy_operations=1,
        )

    def _execute(
        self,
        plan: T09Plan,
        context: WorkContext,
        *,
        target_matches: Mapping[str, TargetMatch] | Iterable[TargetMatch],
        contextual_assertions: Mapping[
            str, Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]]
        ]
        | Iterable[SourceFact | EvidenceAssertionRecord | Mapping[str, object]],
        t08_evidence: object | None,
        workload_evidence: Mapping[str, object] | None,
        weather_evidence: Mapping[str, object] | None,
        mandatory_research: tuple[ResearchAttempt, ...] | None,
        material_scenarios: tuple[MaterialScenario, ...],
        model_availability: Mapping[str, bool] | None,
        manifest_verified_at_utc: str | None,
        failure_hook: Callable[[int, FrozenMembership], None] | None,
    ) -> WorkResult:
        if context.phase is not RunPhase.EVIDENCE_ACQUISITION:
            return WorkResult.for_phase(context.phase)
        freeze = read_frozen_matchweek(self.store, plan.friday, season=plan.season)
        result = T09EvidenceBuilder(
            self.store,
            catalog=plan.catalog,
            feature_rules=plan.feature_rules,
            target_matches=target_matches,
            contextual_assertions=contextual_assertions,
            t08_evidence=t08_evidence,
            workload_evidence=workload_evidence,
            weather_evidence=weather_evidence,
            mandatory_research=mandatory_research,
            material_scenarios=material_scenarios,
            model_availability=model_availability,
            manifest_verified_at_utc=manifest_verified_at_utc,
            failure_hook=failure_hook,
        ).build(freeze)
        self.last_result = result
        return WorkResult(result_digest=result.digest, artifact_digests=result.artifact_digests)


EvidenceStateBuilder = T09EvidenceBuilder
EvidenceResearchRunner = T09EvidenceRunner
EvidenceStateRunner = T09EvidenceRunner
build_evidence_states = EvidenceResearcher().build


__all__ = (
    "CATALOG_DIGEST",
    "CATALOG_KIND",
    "CATALOG_NAME",
    "CATALOG_VERSION",
    "DEFAULT_CATALOG",
    "EVIDENCE_REQUIREMENT_CATALOG_V1",
    "EVIDENCE_STATE_MEDIA_TYPE",
    "PREFERENCE_FAMILIES",
    "RESEARCH_RULES_NAME",
    "AccessState",
    "CoverageState",
    "CutoffEligibility",
    "DerivedFeature",
    "EvidenceClass",
    "EvidenceFact",
    "EvidenceGap",
    "EvidenceInfluence",
    "EvidenceRequirement",
    "EvidenceRequirementCatalog",
    "EvidenceResearchInput",
    "EvidenceResearchRequest",
    "EvidenceResearchResult",
    "EvidenceResearchRunner",
    "EvidenceResearcher",
    "EvidenceState",
    "EvidenceStateBuilder",
    "EvidenceStateRecord",
    "EvidenceStateRunner",
    "FeatureRules",
    "Freshness",
    "FreshnessState",
    "FrozenEvidenceState",
    "FrozenState",
    "HistoricalMatch",
    "HistoricalMatchRecord",
    "IndependentCorroboration",
    "Influence",
    "MaterialConflict",
    "MaterialScenario",
    "PreferenceFamily",
    "ResearchAttempt",
    "ResearchInput",
    "ResearchStatus",
    "ResearchSufficiency",
    "SourceAssertion",
    "SourceFact",
    "StructuredMatch",
    "T09BuildResult",
    "T09Error",
    "T09EvidenceBuilder",
    "T09EvidenceRunner",
    "T09IntegrityError",
    "T09Plan",
    "T09ValidationError",
    "TargetMatch",
    "build_evidence_states",
    "normalize_family",
)

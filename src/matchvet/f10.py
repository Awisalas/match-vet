"""Pure V2 research-requirement contract for F10.

This contract names research work and its possible outcomes. It does not perform
research or assert that a source contains evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from matchvet.evidence import EvidenceClass
from matchvet.t09 import PREFERENCE_FAMILIES, PreferenceFamily

V2_REQUIREMENT_CATALOG_NAME = "matchvet-v2-research-requirements"
V2_REQUIREMENT_CATALOG_VERSION = "2.0.0"
V2_REQUIREMENT_CATALOG_KIND = "research_requirement_catalog"
V1_BASELINE_CATALOG = (
    "Evidence Requirement and Metric Catalog",
    "1.0.0",
    "740556efa351db94d3704ec7f30bd8d3708a8c6191432d6cc987f8d60d9fa3fc",
)


class F10ValidationError(ValueError):
    """A V2 requirement catalog is malformed or uses an unsupported version."""


class OutcomeState(StrEnum):
    OBSERVED = "OBSERVED"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    UNPERFORMED = "UNPERFORMED"


_ALL_FAMILIES = tuple(PREFERENCE_FAMILIES)
_ALL_OUTCOMES: tuple[OutcomeState, ...] = tuple(OutcomeState)
_MISSING_PREREQUISITE_OUTCOMES = (
    OutcomeState.OBSERVED,
    OutcomeState.UNKNOWN,
    OutcomeState.CONFLICT,
    OutcomeState.UNPERFORMED,
)


@dataclass(frozen=True)
class ResearchRequirement:
    requirement_id: str
    label: str
    preference_families: tuple[str, ...]
    baseline_requirement_ids: tuple[str, ...]
    evidence_family: str
    evidence_type: str
    mandatory_research: bool
    conditional_when: str | None
    evidence_class: EvidenceClass
    importance: str
    cutoff_relationship: str
    source_prerequisite: tuple[str, str] | None
    source_gap: bool
    health_prerequisite: str | None
    allowed_outcomes: tuple[OutcomeState, ...]
    qualitative: bool = False
    can_create_play: bool = False

    def __post_init__(self) -> None:
        if not self.requirement_id.startswith("V2-") or not self.label:
            raise F10ValidationError("V2 requirements need a stable V2 ID and label.")
        if tuple(sorted(set(self.preference_families))) != self.preference_families:
            raise F10ValidationError("V2 requirement families must be sorted and unique.")
        if tuple(sorted(set(self.baseline_requirement_ids))) != self.baseline_requirement_ids:
            raise F10ValidationError("Baseline requirement IDs must be sorted and unique.")
        if not self.preference_families or not set(self.preference_families).issubset(
            _ALL_FAMILIES
        ):
            raise F10ValidationError("V2 requirement has unsupported Preference Families.")
        if not self.evidence_family or not self.evidence_type or not self.cutoff_relationship:
            raise F10ValidationError("V2 requirements need evidence and cutoff definitions.")
        if not self.allowed_outcomes or len(set(self.allowed_outcomes)) != len(
            self.allowed_outcomes
        ):
            raise F10ValidationError("V2 requirement outcomes must be non-empty and unique.")
        if not set(self.allowed_outcomes).issubset(_ALL_OUTCOMES):
            raise F10ValidationError("V2 requirement contains an unsupported outcome.")
        if self.qualitative and self.can_create_play:
            raise F10ValidationError("Qualitative evidence cannot independently create a PLAY.")
        if self.source_gap and self.source_prerequisite is not None:
            raise F10ValidationError("An unresolved source gap cannot name an approved source.")

    def applies_to(self, family: str | PreferenceFamily) -> bool:
        value = family.value if isinstance(family, PreferenceFamily) else family
        return value in self.preference_families

    def is_research_required(self, condition_met: bool = True) -> bool:
        """Conditional requirements are mandatory whenever their stated condition holds."""
        return self.mandatory_research and (self.conditional_when is None or condition_met)

    def outcomes_without_source(self) -> tuple[OutcomeState, ...]:
        return _MISSING_PREREQUISITE_OUTCOMES

    def outcomes_without_health(self) -> tuple[OutcomeState, ...]:
        return _MISSING_PREREQUISITE_OUTCOMES

    def outcomes_for(
        self, *, research_performed: bool, source_available: bool, health_healthy: bool
    ) -> tuple[OutcomeState, ...]:
        if not research_performed or not source_available or not health_healthy or self.source_gap:
            return _MISSING_PREREQUISITE_OUTCOMES
        return self.allowed_outcomes

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_outcomes": [state.value for state in self.allowed_outcomes],
            "baseline_requirement_ids": list(self.baseline_requirement_ids),
            "can_create_play": self.can_create_play,
            "conditional_when": self.conditional_when,
            "cutoff_relationship": self.cutoff_relationship,
            "evidence_class": self.evidence_class.value,
            "evidence_family": self.evidence_family,
            "evidence_type": self.evidence_type,
            "health_prerequisite": self.health_prerequisite,
            "importance": self.importance,
            "label": self.label,
            "mandatory_research": self.mandatory_research,
            "preference_families": list(self.preference_families),
            "qualitative": self.qualitative,
            "requirement_id": self.requirement_id,
            "source_prerequisite": list(self.source_prerequisite)
            if self.source_prerequisite
            else None,
            "source_gap": self.source_gap,
        }


@dataclass(frozen=True)
class ResearchRequirementCatalog:
    requirements: tuple[ResearchRequirement, ...]
    name: str = V2_REQUIREMENT_CATALOG_NAME
    version: str = V2_REQUIREMENT_CATALOG_VERSION

    def __post_init__(self) -> None:
        if self.version != V2_REQUIREMENT_CATALOG_VERSION:
            raise F10ValidationError(f"Unsupported V2 requirement catalog version: {self.version}.")
        ids = tuple(item.requirement_id for item in self.requirements)
        if not ids or ids != tuple(sorted(set(ids))):
            raise F10ValidationError("V2 requirement IDs must be sorted and unique.")

    def requirement(self, requirement_id: str) -> ResearchRequirement:
        for requirement in self.requirements:
            if requirement.requirement_id == requirement_id:
                return requirement
        raise F10ValidationError(f"Unknown V2 requirement {requirement_id}.")

    def for_family(self, family: str | PreferenceFamily) -> tuple[ResearchRequirement, ...]:
        value = family.value if isinstance(family, PreferenceFamily) else family
        return tuple(item for item in self.requirements if item.applies_to(value))

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_catalog": {
                "name": V1_BASELINE_CATALOG[0],
                "version": V1_BASELINE_CATALOG[1],
                "digest": V1_BASELINE_CATALOG[2],
            },
            "kind": V2_REQUIREMENT_CATALOG_KIND,
            "name": self.name,
            "requirements": [item.to_dict() for item in self.requirements],
            "version": self.version,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, payload: str) -> ResearchRequirementCatalog:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise F10ValidationError("V2 requirement catalog JSON is malformed.") from error
        if not isinstance(value, dict):
            raise F10ValidationError("V2 requirement catalog must be an object.")
        return cls.from_dict(cast(Mapping[str, object], value))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ResearchRequirementCatalog:
        if value.get("version") != V2_REQUIREMENT_CATALOG_VERSION:
            raise F10ValidationError(
                f"Unsupported V2 requirement catalog version: {value.get('version')}."
            )
        if value.get("kind") != V2_REQUIREMENT_CATALOG_KIND:
            raise F10ValidationError("Unsupported V2 requirement catalog kind.")
        baseline_reference = value.get("baseline_catalog")
        expected_baseline_reference = {
            "name": V1_BASELINE_CATALOG[0],
            "version": V1_BASELINE_CATALOG[1],
            "digest": V1_BASELINE_CATALOG[2],
        }
        if baseline_reference != expected_baseline_reference:
            raise F10ValidationError(
                "V2 requirement catalog references an unsupported V1 baseline."
            )
        raw_requirements = value.get("requirements")
        if not isinstance(raw_requirements, list):
            raise F10ValidationError("V2 requirement catalog requirements must be a list.")
        parsed: list[ResearchRequirement] = []
        for raw in raw_requirements:
            if not isinstance(raw, dict):
                raise F10ValidationError("V2 requirement must be an object.")
            try:
                prereq = raw["source_prerequisite"]
                source = tuple(prereq) if isinstance(prereq, list) else None
                outcomes = tuple(
                    OutcomeState(item) for item in cast(list[str], raw["allowed_outcomes"])
                )
                parsed.append(
                    ResearchRequirement(
                        requirement_id=str(raw["requirement_id"]),
                        label=str(raw["label"]),
                        preference_families=tuple(cast(list[str], raw["preference_families"])),
                        baseline_requirement_ids=tuple(
                            cast(list[str], raw["baseline_requirement_ids"])
                        ),
                        evidence_family=str(raw["evidence_family"]),
                        evidence_type=str(raw["evidence_type"]),
                        mandatory_research=bool(raw["mandatory_research"]),
                        conditional_when=cast(str | None, raw["conditional_when"]),
                        evidence_class=EvidenceClass(str(raw["evidence_class"])),
                        importance=str(raw["importance"]),
                        cutoff_relationship=str(raw["cutoff_relationship"]),
                        source_prerequisite=cast(tuple[str, str] | None, source),
                        source_gap=bool(raw["source_gap"]),
                        health_prerequisite=cast(str | None, raw["health_prerequisite"]),
                        allowed_outcomes=outcomes,
                        qualitative=bool(raw["qualitative"]),
                        can_create_play=bool(raw["can_create_play"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise F10ValidationError("V2 requirement record is malformed.") from error
        return cls(tuple(parsed), name=str(value.get("name", V2_REQUIREMENT_CATALOG_NAME)))


def enabled_preference_families() -> tuple[str, ...]:
    """Return the unchanged enabled V1 founder Preference Families in canonical order."""
    return tuple(PREFERENCE_FAMILIES)


def _requirement(
    requirement_id: str,
    label: str,
    evidence_family: str,
    evidence_type: str,
    *,
    families: tuple[str, ...] = _ALL_FAMILIES,
    baseline_ids: tuple[str, ...] = (),
    evidence_class: EvidenceClass = EvidenceClass.IMPORTANT,
    importance: str = "Important contextual evidence",
    conditional_when: str | None = None,
    mandatory: bool = True,
    source: tuple[str, str] | None = None,
    source_gap: bool = False,
    health: str | None = None,
    qualitative: bool = False,
    cutoff_relationship: str = "published_at_or_before_match_evidence_cutoff",
) -> ResearchRequirement:
    return ResearchRequirement(
        requirement_id=requirement_id,
        label=label,
        preference_families=tuple(sorted(families)),
        baseline_requirement_ids=tuple(sorted(baseline_ids)),
        evidence_family=evidence_family,
        evidence_type=evidence_type,
        mandatory_research=mandatory,
        conditional_when=conditional_when,
        evidence_class=evidence_class,
        importance=importance,
        cutoff_relationship=cutoff_relationship,
        source_prerequisite=source,
        source_gap=source_gap,
        health_prerequisite=health,
        allowed_outcomes=_ALL_OUTCOMES,
        qualitative=qualitative,
    )


_RESULT_FAMILIES = (
    PreferenceFamily.MATCH_WINNER.value,
    PreferenceFamily.DOUBLE_CHANCE.value,
    PreferenceFamily.ASIAN_HANDICAPS.value,
)
_GOAL_FAMILIES = (
    PreferenceFamily.MATCH_GOALS_OVER.value,
    PreferenceFamily.HOME_TEAM_GOALS_OVER.value,
    PreferenceFamily.AWAY_TEAM_GOALS_OVER.value,
    PreferenceFamily.FIRST_HALF_OVER.value,
    PreferenceFamily.SECOND_HALF_OVER.value,
)
_CORNER_FAMILIES = (
    PreferenceFamily.FULL_MATCH_TOTAL_CORNERS_OVER.value,
    PreferenceFamily.CORNER_MATCH_WINNER.value,
    PreferenceFamily.HOME_TEAM_CORNERS_OVER.value,
    PreferenceFamily.AWAY_TEAM_CORNERS_OVER.value,
)

_REQUIREMENTS = (
    _requirement(
        "V2-HISTORICAL-BASELINE",
        "Exact-line Historical Baseline",
        "historical_results",
        "preference_outcomes",
        baseline_ids=("D-HISTORICAL-BASELINE",),
        evidence_class=EvidenceClass.CRITICAL,
        importance="Critical predictive baseline",
    ),
    _requirement(
        "V2-RECENT-TEAM-STRENGTH",
        "Recency-weighted team strength",
        "team_performance",
        "team_strength",
        baseline_ids=(
            "D-FORM-HORIZONS",
            "D-OPPONENT-STRENGTH",
            "D-RECENCY-STRENGTH",
            "D-SCORE-STATE",
            "D-TREND-DIRECTION",
            "D-VENUE-EFFECT",
        ),
        evidence_class=EvidenceClass.CRITICAL,
        importance="Critical predictive evidence",
    ),
    _requirement(
        "V2-GOAL-PERFORMANCE",
        "Team and opponent goal performance",
        "goal_performance",
        "goal_counts",
        families=_GOAL_FAMILIES,
        baseline_ids=("M-FT-GOALS", "M-HT-GOALS"),
        evidence_class=EvidenceClass.CRITICAL,
        importance="Critical predictive evidence",
    ),
    _requirement(
        "V2-CORNER-PERFORMANCE",
        "Team and opponent corner performance",
        "corner_performance",
        "corner_counts",
        families=_CORNER_FAMILIES,
        baseline_ids=("M-CORNERS",),
        evidence_class=EvidenceClass.CRITICAL,
        importance="Critical predictive evidence",
    ),
    _requirement(
        "V2-WORKLOAD",
        "Recent and upcoming workload",
        "workload",
        "fixture_workload",
        baseline_ids=("D-CONGESTION", "D-REST"),
        evidence_class=EvidenceClass.IMPORTANT,
        importance="Important fatigue context",
    ),
    _requirement(
        "V2-WEATHER-FORECAST",
        "Match-location weather forecast",
        "weather",
        "forecast",
        baseline_ids=("E-WEATHER-CONTEXT", "M-WEATHER"),
        evidence_class=EvidenceClass.IMPORTANT,
        importance="Important contextual evidence",
        conditional_when="verified venue coordinates and location provenance are available",
        source=("open-meteo", "weather-forecast"),
        health="provider-health-v1:matchvet:research-only:t08-weather:non-commercial",
        cutoff_relationship=(
            "forecast_issue_and_retrieval_at_or_before_cutoff_and_interval_covers_kickoff"
        ),
    ),
    _requirement(
        "V2-UNRESOLVED-WORKLOAD-SOURCE",
        "Additional workload source coverage",
        "workload",
        "cross_competition_fixture_workload",
        baseline_ids=("D-CROSS-COMP-WORKLOAD",),
        conditional_when="cutoff-valid fixture records do not establish complete relevant workload",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-INJURY-AVAILABILITY",
        "Player injury and availability",
        "player_availability",
        "injury_availability",
        baseline_ids=("E-AVAILABILITY", "E-INJURY"),
        conditional_when="relevant player or squad availability can affect this preference",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-SUSPENSIONS",
        "Player suspensions",
        "player_availability",
        "suspension",
        baseline_ids=("E-SUSPENSION",),
        conditional_when="a relevant player suspension may affect this preference",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-EXPECTED-LINEUP",
        "Pre-lineup expected starters",
        "team_selection",
        "expected_lineup",
        baseline_ids=("E-LINEUP-SCENARIO",),
        conditional_when="the Match Evidence Cutoff precedes confirmed starting lineups",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-ROTATION",
        "Expected rotation and tactical selection",
        "team_selection",
        "rotation",
        baseline_ids=("E-ROTATION",),
        conditional_when="fixture congestion or a material team-selection signal exists",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-MANAGER-REGIME",
        "Manager and regime changes",
        "team_context",
        "manager_regime_change",
        baseline_ids=("E-MANAGER", "E-TACTICAL-REGIME"),
        conditional_when="a recent manager or playing-regime change is reported",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-REFEREE-APPOINTMENT",
        "Referee appointment",
        "official_context",
        "referee_appointment",
        baseline_ids=("M-REFEREE",),
        conditional_when="the appointment is published by the cutoff",
        evidence_class=EvidenceClass.CONTEXT,
        importance="Appointment context; unresolved sourcing remains a gap",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-REFEREE-CONTEXT",
        "Referee historical context",
        "official_context",
        "referee_context",
        baseline_ids=("E-REFEREE-CONTEXT",),
        conditional_when="a referee appointment is known and cutoff-valid",
        evidence_class=EvidenceClass.CONTEXT,
        importance="Referee context may inform risk but cannot create a PLAY",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-TACTICAL-CONTEXT",
        "Relevant tactical context",
        "team_context",
        "tactical_context",
        baseline_ids=("E-TACTICS",),
        conditional_when="cutoff-valid reporting identifies a material tactical change",
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-TARGET-FIXTURE",
        "Target Match identity, scope, kickoff, and venue",
        "fixture_identity",
        "target_match_revision",
        evidence_class=EvidenceClass.CRITICAL,
        importance="Critical match context",
        baseline_ids=("M-FIXTURE",),
    ),
    _requirement(
        "V2-OPTIONAL-MATCH-FACTS",
        "Optional sourced match facts",
        "match_statistics",
        "match_event_statistics",
        conditional_when="cutoff-valid sourced records exist for the statistic",
        baseline_ids=(
            "M-PENALTY-EVENT",
            "M-PROVIDER-XG",
            "M-RED",
            "M-SHOTS",
            "M-SOT",
            "M-YELLOW",
        ),
        mandatory=False,
        source=None,
        source_gap=True,
        qualitative=True,
    ),
    _requirement(
        "V2-HEAD-TO-HEAD",
        "Comparable head-to-head history",
        "historical_results",
        "comparable_head_to_head",
        conditional_when="prior meetings have comparable teams and playing regimes",
        baseline_ids=("E-HEAD-TO-HEAD",),
        evidence_class=EvidenceClass.CONTEXT,
        importance="Low-weight context from comparable prior meetings",
    ),
)

V2_REQUIREMENT_CATALOG = ResearchRequirementCatalog(
    tuple(sorted(_REQUIREMENTS, key=lambda item: item.requirement_id))
)

__all__ = [
    "V1_BASELINE_CATALOG",
    "V2_REQUIREMENT_CATALOG",
    "V2_REQUIREMENT_CATALOG_NAME",
    "V2_REQUIREMENT_CATALOG_VERSION",
    "F10ValidationError",
    "OutcomeState",
    "ResearchRequirement",
    "ResearchRequirementCatalog",
    "enabled_preference_families",
]

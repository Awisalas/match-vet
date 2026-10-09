"""Versioned CandidateInput support resolution and joint finalist comparison."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.f13 import F13Error, ModelContractRepository
from matchvet.f14 import (
    CAUSAL_DECISION_INPUT_MEDIA_TYPE,
    CAUSAL_DECISION_MEDIA_TYPE,
    DECISION_INPUT_MEDIA_TYPE,
    DECISION_MEDIA_TYPE,
    DecisionRepository,
    F14Error,
    PreferenceProfileRepository,
)
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.store import Store
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, BettingPreference
from matchvet.t15 import (
    SELECTION_COMPONENTS,
    NormalizationSpec,
    PolicyStatus,
    PolicyVersion,
    SelectionStrengthConfig,
    _threshold_number,
    selection_strength_from_raw_components,
)

F13_SUPPORT_MEDIA_TYPE = "application/vnd.matchvet.f13-candidate-support.v4+json"
T15_COMPARISON_MEDIA_TYPE = "application/vnd.matchvet.t15-joint-comparison.v2+json"
T15_COMPARISON_RESULT_MEDIA_TYPE = "application/vnd.matchvet.t15-comparison-result.v2+json"
F14_SUPPORT_INPUT_MEDIA_TYPE = "application/vnd.matchvet.f14-decision-input.v4+json"
F14_SUPPORT_RESULT_MEDIA_TYPE = "application/vnd.matchvet.f14-decision-result.v4+json"
G6_U1_EVENT_RESULT_MEDIA_TYPE = "application/vnd.matchvet.f13-g6-u1-event-result.v1+json"
G6_U2_VALIDATION_MEDIA_TYPE = "application/vnd.matchvet.f13-g6-u2-validation.v1+json"
G7_REFERENCE_MEDIA_TYPE = "application/vnd.matchvet.f13-g7-reference.v1+json"
G7_EVALUATION_MEDIA_TYPE = "application/vnd.matchvet.f13-g7-evaluation.v1+json"
G8_FAILURE_ASSERTION_MEDIA_TYPE = "application/vnd.matchvet.f13-g8-failure-assertion.v1+json"
G8_MATERIALITY_MEDIA_TYPE = "application/vnd.matchvet.f13-g8-materiality.v1+json"
G8_UNCERTAINTY_REPRESENTATION_MEDIA_TYPE = (
    "application/vnd.matchvet.f13-g8-uncertainty-representation.v1+json"
)
G8_ABSENCE_MEDIA_TYPE = "application/vnd.matchvet.f13-g8-absence.v1+json"
F13_SUPPORT_SCHEMA_VERSION = 4
T15_COMPARISON_SCHEMA_VERSION = 2
F14_SUPPORT_SCHEMA_VERSION = 4
G6_U1_EVENT_SCHEMA_VERSION = 1
GATE_EVIDENCE_SCHEMA_VERSION = 1

GROUP_RESOLVER_RULE = "candidate-input-group-resolver-v2"
COMPARISON_RULE = "t15-joint-maximal-set-v2"
G6_U1_EVENT_ID = "G5_CONSTRAINT_VIOLATION_MASS"
U2_CLAIM_EVIDENCE_BASES = {
    "LATENT_PROBABILITY_INTERVAL_COVERAGE": frozenset({"KNOWN_TRUTH_SIMULATION"}),
    "PREDICTIVE_COVERAGE": frozenset({"LATER_OUTCOME_VALIDATION"}),
    "CALIBRATION": frozenset({"LATER_OUTCOME_VALIDATION"}),
}


class SupportState(StrEnum):
    """Evidence states retained by the successor support contract."""

    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"
    UNPERFORMED = "UNPERFORMED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"
    EVIDENCED_ABSENCE = "EVIDENCED_ABSENCE"
    OBSERVED_EVIDENCE = "OBSERVED_EVIDENCE"


class GateSupportStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PreferenceSupportContext:
    """Exact T10 preference and its supported fallback context."""

    preference: BettingPreference
    league: str
    supported_contexts: tuple[str, ...]
    component_estimands: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.preference, BettingPreference):
            raise ValueError("Support resolution requires an exact T10 preference.")
        if not self.league.strip():
            raise ValueError("Support resolution requires the exact target league.")
        contexts = tuple(self.supported_contexts)
        if any(not isinstance(item, str) or not item.strip() for item in contexts):
            raise ValueError("Supported context ancestry must contain non-empty identities.")
        if len(set(contexts)) != len(contexts):
            raise ValueError("Supported context ancestry cannot contain duplicate identities.")
        estimands = {
            str(component): str(estimand)
            for component, estimand in self.component_estimands.items()
        }
        object.__setattr__(self, "supported_contexts", contexts)
        object.__setattr__(self, "component_estimands", estimands)

    @property
    def settlement_topology(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.preference.possible_results)


@dataclass(frozen=True)
class ComponentSupportReference:
    """One exact normalization reference at a declared preference-group level."""

    component: str
    scope: str
    group_key: str
    estimand_id: str
    settlement_topology: tuple[str, ...]
    normalizer: Mapping[str, object]
    source_artifact_digests: tuple[str, ...]
    state: SupportState = SupportState.SUPPORTED

    def __post_init__(self) -> None:
        if self.component not in SELECTION_COMPONENTS:
            raise ValueError("Component support names an unknown Selection Strength component.")
        if self.scope not in {"EXACT", "FAMILY_LINE", "ROLE", "LEAGUE", "CONTEXT"}:
            raise ValueError("Component support has an unsupported group scope.")
        if not self.group_key.strip() or not self.estimand_id.strip():
            raise ValueError("Component support group and estimand identities are required.")
        if not self.settlement_topology or len(set(self.settlement_topology)) != len(
            self.settlement_topology
        ):
            raise ValueError("Component support requires a complete settlement topology.")
        if not self.source_artifact_digests:
            raise ValueError("Component support requires protected source artifact identities.")
        for digest in self.source_artifact_digests:
            _require_digest(digest, "component support source digest")
        state = SupportState(self.state)
        object.__setattr__(self, "settlement_topology", tuple(self.settlement_topology))
        object.__setattr__(self, "source_artifact_digests", tuple(self.source_artifact_digests))
        object.__setattr__(self, "normalizer", dict(self.normalizer))
        object.__setattr__(self, "state", state)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "estimand_id": self.estimand_id,
            "group_key": self.group_key,
            "normalizer": dict(self.normalizer),
            "scope": self.scope,
            "settlement_topology": self.settlement_topology,
            "source_artifact_digests": self.source_artifact_digests,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ComponentSupportReference:
        _exact_fields(
            value,
            {
                "component",
                "estimand_id",
                "group_key",
                "normalizer",
                "scope",
                "settlement_topology",
                "source_artifact_digests",
                "state",
            },
            "component support reference",
        )
        return cls(
            component=str(value["component"]),
            scope=str(value["scope"]),
            group_key=str(value["group_key"]),
            estimand_id=str(value["estimand_id"]),
            settlement_topology=tuple(cast(Sequence[str], value["settlement_topology"])),
            normalizer=cast(Mapping[str, object], value["normalizer"]),
            source_artifact_digests=tuple(cast(Sequence[str], value["source_artifact_digests"])),
            state=SupportState(str(value["state"])),
        )


@dataclass(frozen=True)
class ResolvedComponentSupport:
    component: str
    state: SupportState
    reference_digest: str | None
    normalizer: NormalizationSpec | None
    ancestors_considered: tuple[str, ...]
    fallback_reason: str


@dataclass(frozen=True)
class CandidatePreferenceSupport:
    """F13 support envelope for one exact enabled T10 preference."""

    preference_id: str
    preference_contract_digest: str
    f13_prediction_digest: str
    component_estimands: Mapping[str, str]
    supported_contexts: tuple[str, ...]
    component_references: tuple[ComponentSupportReference, ...]
    g6: Mapping[str, object] | None = None
    g7: Mapping[str, object] | None = None
    g8: Mapping[str, object] | None = None
    source_artifact_digests: tuple[str, ...] = ()
    state: SupportState = SupportState.SUPPORTED

    def __post_init__(self) -> None:
        if not self.preference_id.strip():
            raise ValueError("Candidate support requires an exact preference identity.")
        _require_digest(self.preference_contract_digest, "T10 preference contract digest")
        _require_digest(self.f13_prediction_digest, "F13 prediction digest")
        for digest in self.source_artifact_digests:
            _require_digest(digest, "candidate support source digest")
        estimands = {str(key): str(value) for key, value in self.component_estimands.items()}
        if any(
            key not in SELECTION_COMPONENTS or not value.strip() for key, value in estimands.items()
        ):
            raise ValueError("Candidate support has an invalid component estimand.")
        contexts = tuple(self.supported_contexts)
        if any(not isinstance(value, str) or not value.strip() for value in contexts):
            raise ValueError("Candidate support context identities cannot be empty.")
        object.__setattr__(self, "component_estimands", estimands)
        object.__setattr__(self, "supported_contexts", contexts)
        object.__setattr__(self, "component_references", tuple(self.component_references))
        object.__setattr__(self, "source_artifact_digests", tuple(self.source_artifact_digests))
        object.__setattr__(self, "g6", _optional_mapping(self.g6))
        object.__setattr__(self, "g7", _optional_mapping(self.g7))
        object.__setattr__(self, "g8", _optional_mapping(self.g8))
        object.__setattr__(self, "state", SupportState(self.state))

    def to_dict(self) -> dict[str, object]:
        return {
            "component_estimands": dict(sorted(self.component_estimands.items())),
            "component_references": [ref.to_dict() for ref in self.component_references],
            "f13_prediction_digest": self.f13_prediction_digest,
            "g6": _plain(self.g6),
            "g7": _plain(self.g7),
            "g8": _plain(self.g8),
            "preference_contract_digest": self.preference_contract_digest,
            "preference_id": self.preference_id,
            "source_artifact_digests": self.source_artifact_digests,
            "state": self.state.value,
            "supported_contexts": self.supported_contexts,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CandidatePreferenceSupport:
        _exact_fields(
            value,
            {
                "component_estimands",
                "component_references",
                "f13_prediction_digest",
                "g6",
                "g7",
                "g8",
                "preference_contract_digest",
                "preference_id",
                "source_artifact_digests",
                "state",
                "supported_contexts",
            },
            "candidate preference support",
        )
        references = value["component_references"]
        if not isinstance(references, list) or any(
            not isinstance(item, Mapping) for item in references
        ):
            raise ValueError("Candidate component references are malformed.")
        return cls(
            preference_id=str(value["preference_id"]),
            preference_contract_digest=str(value["preference_contract_digest"]),
            f13_prediction_digest=str(value["f13_prediction_digest"]),
            component_estimands=cast(Mapping[str, str], value["component_estimands"]),
            supported_contexts=tuple(cast(Sequence[str], value["supported_contexts"])),
            component_references=tuple(
                ComponentSupportReference.from_dict(item) for item in references
            ),
            g6=cast(Mapping[str, object] | None, value["g6"]),
            g7=cast(Mapping[str, object] | None, value["g7"]),
            g8=cast(Mapping[str, object] | None, value["g8"]),
            source_artifact_digests=tuple(cast(Sequence[str], value["source_artifact_digests"])),
            state=SupportState(str(value["state"])),
        )


@dataclass(frozen=True)
class CandidateSupportManifest:
    """Protected F13 support for one exact cutoff, preference set, model, and policy."""

    cutoff_id: str
    cutoff_digest: str
    t10_profile_digest: str
    t10_catalog_digest: str
    f13_result_digest: str
    policy_digest: str
    league: str
    preference_supports: tuple[CandidatePreferenceSupport, ...]
    source_artifact_digests: tuple[str, ...] = ()
    schema_version: int = F13_SUPPORT_SCHEMA_VERSION
    resolver_rule: str = GROUP_RESOLVER_RULE
    resolver_rule_digest: str = ""
    comparison_rule: str = COMPARISON_RULE
    comparison_rule_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != F13_SUPPORT_SCHEMA_VERSION:
            raise ValueError("Unsupported F13 CandidateInput support schema.")
        for name in (
            "t10_profile_digest",
            "t10_catalog_digest",
            "f13_result_digest",
            "policy_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_contract_digest(self.cutoff_digest, "cutoff digest")
        if not self.cutoff_id.strip() or not self.league.strip():
            raise ValueError("F13 support requires exact cutoff and league identities.")
        if self.resolver_rule != GROUP_RESOLVER_RULE or self.comparison_rule != COMPARISON_RULE:
            raise ValueError("F13 support names an unsupported resolver or comparison rule.")
        if self.resolver_rule_digest != group_resolver_rule_digest():
            raise ValueError("F13 support resolver identity does not match this reader.")
        if self.comparison_rule_digest != comparison_rule_digest():
            raise ValueError("F13 support comparison identity does not match this reader.")
        support_rows = tuple(sorted(self.preference_supports, key=lambda row: row.preference_id))
        if len({row.preference_id for row in support_rows}) != len(support_rows):
            raise ValueError("F13 support contains duplicate preference identities.")
        source_digests = tuple(sorted(set(self.source_artifact_digests)))
        for digest in source_digests:
            _require_digest(digest, "F13 support source digest")
        object.__setattr__(self, "preference_supports", support_rows)
        object.__setattr__(self, "source_artifact_digests", source_digests)

    def to_dict(self) -> dict[str, object]:
        return {
            "comparison_rule": self.comparison_rule,
            "comparison_rule_digest": self.comparison_rule_digest,
            "cutoff_digest": self.cutoff_digest,
            "cutoff_id": self.cutoff_id,
            "f13_result_digest": self.f13_result_digest,
            "league": self.league,
            "policy_digest": self.policy_digest,
            "preference_supports": [row.to_dict() for row in self.preference_supports],
            "resolver_rule": self.resolver_rule,
            "resolver_rule_digest": self.resolver_rule_digest,
            "schema_version": self.schema_version,
            "source_artifact_digests": self.source_artifact_digests,
            "t10_catalog_digest": self.t10_catalog_digest,
            "t10_profile_digest": self.t10_profile_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CandidateSupportManifest:
        _exact_fields(
            value,
            {
                "comparison_rule",
                "comparison_rule_digest",
                "cutoff_digest",
                "cutoff_id",
                "f13_result_digest",
                "league",
                "policy_digest",
                "preference_supports",
                "resolver_rule",
                "resolver_rule_digest",
                "schema_version",
                "source_artifact_digests",
                "t10_catalog_digest",
                "t10_profile_digest",
            },
            "F13 CandidateInput support manifest",
        )
        rows = value["preference_supports"]
        if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
            raise ValueError("F13 support preference rows are malformed.")
        if type(value["schema_version"]) is not int:
            raise ValueError("F13 support schema version must be an integer.")
        return cls(
            cutoff_id=str(value["cutoff_id"]),
            cutoff_digest=str(value["cutoff_digest"]),
            t10_profile_digest=str(value["t10_profile_digest"]),
            t10_catalog_digest=str(value["t10_catalog_digest"]),
            f13_result_digest=str(value["f13_result_digest"]),
            policy_digest=str(value["policy_digest"]),
            league=str(value["league"]),
            preference_supports=tuple(CandidatePreferenceSupport.from_dict(item) for item in rows),
            source_artifact_digests=tuple(cast(Sequence[str], value["source_artifact_digests"])),
            schema_version=value["schema_version"],
            resolver_rule=str(value["resolver_rule"]),
            resolver_rule_digest=str(value["resolver_rule_digest"]),
            comparison_rule=str(value["comparison_rule"]),
            comparison_rule_digest=str(value["comparison_rule_digest"]),
        )


@dataclass(frozen=True)
class PairDifferenceSupport:
    """Supported range for one paired difference from one joint rule."""

    left_preference_id: str
    right_preference_id: str
    lower: float | None
    upper: float | None
    state: SupportState
    region_rule_digest: str

    def __post_init__(self) -> None:
        if not self.left_preference_id or not self.right_preference_id:
            raise ValueError("Paired comparison requires two exact finalist identities.")
        if self.left_preference_id >= self.right_preference_id:
            raise ValueError("Paired comparison identities must be in canonical order.")
        _require_digest(self.region_rule_digest, "paired region rule digest")
        state = SupportState(self.state)
        if state is SupportState.SUPPORTED:
            lower = _number(self.lower, "paired difference lower bound")
            upper = _number(self.upper, "paired difference upper bound")
            if lower > upper:
                raise ValueError("Paired difference support range is reversed.")
            object.__setattr__(self, "lower", lower)
            object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "state", state)

    def to_dict(self) -> dict[str, object]:
        return {
            "left_preference_id": self.left_preference_id,
            "lower": self.lower,
            "region_rule_digest": self.region_rule_digest,
            "right_preference_id": self.right_preference_id,
            "state": self.state.value,
            "upper": self.upper,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PairDifferenceSupport:
        _exact_fields(
            value,
            {
                "left_preference_id",
                "lower",
                "region_rule_digest",
                "right_preference_id",
                "state",
                "upper",
            },
            "paired difference support",
        )
        return cls(
            left_preference_id=str(value["left_preference_id"]),
            right_preference_id=str(value["right_preference_id"]),
            lower=cast(float | None, value["lower"]),
            upper=cast(float | None, value["upper"]),
            state=SupportState(str(value["state"])),
            region_rule_digest=str(value["region_rule_digest"]),
        )


@dataclass(frozen=True)
class JointUncertaintySupport:
    """One protected uncertainty object with shared raw component draws."""

    cutoff_id: str
    cutoff_digest: str
    t10_profile_digest: str
    t10_catalog_digest: str
    f13_result_digest: str
    policy_digest: str
    finalist_ids: tuple[str, ...]
    draw_ids: tuple[str, ...]
    raw_component_draws: Mapping[str, Mapping[str, Mapping[str, float]]]
    paired_regions: tuple[PairDifferenceSupport, ...]
    region_rule_digest: str
    source_artifact_digests: tuple[str, ...]
    state: SupportState = SupportState.SUPPORTED
    schema_version: int = T15_COMPARISON_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != T15_COMPARISON_SCHEMA_VERSION:
            raise ValueError("Unsupported T15 joint-comparison schema.")
        for name in (
            "t10_profile_digest",
            "t10_catalog_digest",
            "f13_result_digest",
            "policy_digest",
            "region_rule_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_contract_digest(self.cutoff_digest, "cutoff digest")
        if not self.cutoff_id.strip():
            raise ValueError("Joint comparison requires an exact cutoff identity.")
        finalists = tuple(sorted(set(self.finalist_ids)))
        draws = tuple(sorted(set(self.draw_ids)))
        if len(finalists) != len(self.finalist_ids) or any(not item for item in finalists):
            raise ValueError("Joint comparison finalist identities must be non-empty and unique.")
        if len(draws) != len(self.draw_ids) or any(not item for item in draws):
            raise ValueError("Joint comparison draw identities must be non-empty and unique.")
        normalized_draws: dict[str, dict[str, dict[str, float]]] = {}
        for preference_id, preference_draws in self.raw_component_draws.items():
            normalized_draws[str(preference_id)] = {}
            for draw_id, components in preference_draws.items():
                normalized_draws[str(preference_id)][str(draw_id)] = {
                    str(component): _number(value, "raw Selection Strength component")
                    for component, value in components.items()
                }
        sources = tuple(sorted(set(self.source_artifact_digests)))
        for digest in sources:
            _require_digest(digest, "joint comparison source digest")
        regions = tuple(
            sorted(
                self.paired_regions,
                key=lambda item: (item.left_preference_id, item.right_preference_id),
            )
        )
        if len({(item.left_preference_id, item.right_preference_id) for item in regions}) != len(
            regions
        ):
            raise ValueError("Joint comparison contains duplicate paired regions.")
        object.__setattr__(self, "finalist_ids", finalists)
        object.__setattr__(self, "draw_ids", draws)
        object.__setattr__(self, "raw_component_draws", normalized_draws)
        object.__setattr__(self, "paired_regions", regions)
        object.__setattr__(self, "source_artifact_digests", sources)
        object.__setattr__(self, "state", SupportState(self.state))

    def to_dict(self) -> dict[str, object]:
        return {
            "cutoff_digest": self.cutoff_digest,
            "cutoff_id": self.cutoff_id,
            "draw_ids": self.draw_ids,
            "f13_result_digest": self.f13_result_digest,
            "finalist_ids": self.finalist_ids,
            "paired_regions": [item.to_dict() for item in self.paired_regions],
            "policy_digest": self.policy_digest,
            "raw_component_draws": {
                preference_id: {
                    draw_id: dict(sorted(components.items()))
                    for draw_id, components in sorted(draws.items())
                }
                for preference_id, draws in sorted(self.raw_component_draws.items())
            },
            "region_rule_digest": self.region_rule_digest,
            "schema_version": self.schema_version,
            "source_artifact_digests": self.source_artifact_digests,
            "state": self.state.value,
            "t10_catalog_digest": self.t10_catalog_digest,
            "t10_profile_digest": self.t10_profile_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> JointUncertaintySupport:
        _exact_fields(
            value,
            {
                "cutoff_digest",
                "cutoff_id",
                "draw_ids",
                "f13_result_digest",
                "finalist_ids",
                "paired_regions",
                "policy_digest",
                "raw_component_draws",
                "region_rule_digest",
                "schema_version",
                "source_artifact_digests",
                "state",
                "t10_catalog_digest",
                "t10_profile_digest",
            },
            "T15 joint comparison support",
        )
        regions = value["paired_regions"]
        if not isinstance(regions, list) or any(not isinstance(item, Mapping) for item in regions):
            raise ValueError("T15 paired region rows are malformed.")
        if type(value["schema_version"]) is not int:
            raise ValueError("T15 comparison schema version must be an integer.")
        draws = cast(Mapping[str, Mapping[str, Mapping[str, float]]], value["raw_component_draws"])
        return cls(
            cutoff_id=str(value["cutoff_id"]),
            cutoff_digest=str(value["cutoff_digest"]),
            t10_profile_digest=str(value["t10_profile_digest"]),
            t10_catalog_digest=str(value["t10_catalog_digest"]),
            f13_result_digest=str(value["f13_result_digest"]),
            policy_digest=str(value["policy_digest"]),
            finalist_ids=tuple(cast(Sequence[str], value["finalist_ids"])),
            draw_ids=tuple(cast(Sequence[str], value["draw_ids"])),
            raw_component_draws=draws,
            paired_regions=tuple(PairDifferenceSupport.from_dict(item) for item in regions),
            region_rule_digest=str(value["region_rule_digest"]),
            source_artifact_digests=tuple(cast(Sequence[str], value["source_artifact_digests"])),
            state=SupportState(str(value["state"])),
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True)
class FinalistCandidate:
    """A gate-qualified finalist with exact component normalizers and tie evidence."""

    preference_id: str
    gate_status: GateSupportStatus
    normalizers: Mapping[str, NormalizationSpec]
    normalizer_reference_digests: Mapping[str, str]
    uncertainty_width: float | None
    data_quality: float | None
    failure_risk: float | None
    adversarial_materiality: float | None
    historical_reliability: float | None

    def __post_init__(self) -> None:
        if not self.preference_id:
            raise ValueError("T1 finalist requires a preference identity.")
        normalizers = dict(self.normalizers)
        references = dict(self.normalizer_reference_digests)
        if set(normalizers) != set(SELECTION_COMPONENTS) or set(references) != set(
            SELECTION_COMPONENTS
        ):
            raise ValueError("T1 finalist requires one exact normalizer reference per component.")
        for digest in references.values():
            _require_digest(digest, "component normalizer reference digest")
        for name in (
            "uncertainty_width",
            "data_quality",
            "failure_risk",
            "adversarial_materiality",
            "historical_reliability",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, f"T1 {name}"))
        object.__setattr__(self, "normalizers", normalizers)
        object.__setattr__(self, "normalizer_reference_digests", references)
        object.__setattr__(self, "gate_status", GateSupportStatus(self.gate_status))


class ComparisonState(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


@dataclass(frozen=True)
class PairComparisonResult:
    left_preference_id: str
    right_preference_id: str
    paired_differences: Mapping[str, float]
    supported_region: tuple[float, float] | None
    robustly_outranks: str | None
    state: ComparisonState

    def __post_init__(self) -> None:
        if not self.left_preference_id or not self.right_preference_id:
            raise ValueError("Pair comparison result requires two finalist identities.")
        if self.left_preference_id >= self.right_preference_id:
            raise ValueError("Pair comparison result identities must be in canonical order.")
        differences = {
            str(draw_id): _number(value, "paired Selection Strength difference")
            for draw_id, value in self.paired_differences.items()
        }
        region = self.supported_region
        if region is not None:
            lower = _number(region[0], "paired comparison lower bound")
            upper = _number(region[1], "paired comparison upper bound")
            if lower > upper:
                raise ValueError("Pair comparison result support region is reversed.")
            object.__setattr__(self, "supported_region", (lower, upper))
        object.__setattr__(self, "paired_differences", differences)
        object.__setattr__(self, "state", ComparisonState(self.state))

    def to_dict(self) -> dict[str, object]:
        return {
            "left_preference_id": self.left_preference_id,
            "paired_differences": dict(sorted(self.paired_differences.items())),
            "robustly_outranks": self.robustly_outranks,
            "right_preference_id": self.right_preference_id,
            "state": self.state.value,
            "supported_region": self.supported_region,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PairComparisonResult:
        _exact_fields(
            value,
            {
                "left_preference_id",
                "paired_differences",
                "robustly_outranks",
                "right_preference_id",
                "state",
                "supported_region",
            },
            "T15 pair comparison result",
        )
        region = value["supported_region"]
        if region is not None and (not isinstance(region, (tuple, list)) or len(region) != 2):
            raise ValueError("T15 pair comparison region is malformed.")
        return cls(
            left_preference_id=str(value["left_preference_id"]),
            right_preference_id=str(value["right_preference_id"]),
            paired_differences=cast(Mapping[str, float], value["paired_differences"]),
            supported_region=(
                cast(tuple[float, float], tuple(region)) if region is not None else None
            ),
            robustly_outranks=cast(str | None, value["robustly_outranks"]),
            state=ComparisonState(str(value["state"])),
        )


@dataclass(frozen=True)
class T15ComparisonResult:
    state: ComparisonState
    finalist_ids: tuple[str, ...]
    strength_draws: Mapping[str, Mapping[str, float]]
    pair_results: tuple[PairComparisonResult, ...]
    maximal_set: tuple[str, ...]
    ordered_maximal_set: tuple[str, ...]
    primary_preference_id: str | None
    reason_codes: tuple[str, ...]
    support_manifest_digest: str
    joint_uncertainty_digest: str
    comparison_rule_digest: str
    resolver_rule_digest: str

    def __post_init__(self) -> None:
        for name in (
            "support_manifest_digest",
            "joint_uncertainty_digest",
            "comparison_rule_digest",
            "resolver_rule_digest",
        ):
            _require_digest(getattr(self, name), name)
        finalist_ids = tuple(sorted(set(self.finalist_ids)))
        maximal_set = tuple(sorted(set(self.maximal_set)))
        if finalist_ids != self.finalist_ids or maximal_set != self.maximal_set:
            raise ValueError("T15 comparison finalist sets must be sorted and unique.")
        if not set(maximal_set).issubset(finalist_ids):
            raise ValueError("T15 maximal set contains a non-finalist.")
        state = ComparisonState(self.state)
        if state is ComparisonState.SUPPORTED and (
            set(self.ordered_maximal_set) != set(maximal_set)
            or len(self.ordered_maximal_set) != len(maximal_set)
        ):
            raise ValueError("Supported T15 order must contain every maximal finalist once.")
        if state is ComparisonState.UNKNOWN and self.ordered_maximal_set:
            raise ValueError("Unknown T15 comparison cannot persist a tie-break order.")
        if state is ComparisonState.UNKNOWN and self.primary_preference_id is not None:
            raise ValueError("T15 UNKNOWN comparison cannot select a primary.")
        if state is ComparisonState.SUPPORTED and (
            (maximal_set and self.primary_preference_id != self.ordered_maximal_set[0])
            or (not maximal_set and self.primary_preference_id is not None)
        ):
            raise ValueError("Supported T15 primary must be the first maximal finalist.")
        if self.primary_preference_id is not None and self.primary_preference_id not in maximal_set:
            raise ValueError("T15 primary must belong to the maximal set.")
        draws = {
            str(preference_id): {
                str(draw_id): _number(value, "T15 strength draw")
                for draw_id, value in values.items()
            }
            for preference_id, values in self.strength_draws.items()
        }
        pair_results = tuple(self.pair_results)
        if len(
            {(item.left_preference_id, item.right_preference_id) for item in pair_results}
        ) != len(pair_results):
            raise ValueError("T15 comparison contains duplicate pair results.")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "strength_draws", draws)
        object.__setattr__(self, "pair_results", pair_results)
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self) -> dict[str, object]:
        return {
            "comparison_rule_digest": self.comparison_rule_digest,
            "finalist_ids": self.finalist_ids,
            "joint_uncertainty_digest": self.joint_uncertainty_digest,
            "maximal_set": self.maximal_set,
            "ordered_maximal_set": self.ordered_maximal_set,
            "pair_results": [item.to_dict() for item in self.pair_results],
            "primary_preference_id": self.primary_preference_id,
            "reason_codes": self.reason_codes,
            "resolver_rule_digest": self.resolver_rule_digest,
            "state": self.state.value,
            "strength_draws": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.strength_draws.items())
            },
            "support_manifest_digest": self.support_manifest_digest,
            "schema_version": T15_COMPARISON_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> T15ComparisonResult:
        _exact_fields(
            value,
            {
                "comparison_rule_digest",
                "finalist_ids",
                "joint_uncertainty_digest",
                "maximal_set",
                "ordered_maximal_set",
                "pair_results",
                "primary_preference_id",
                "reason_codes",
                "resolver_rule_digest",
                "schema_version",
                "state",
                "strength_draws",
                "support_manifest_digest",
            },
            "T15 joint comparison result",
        )
        if type(value["schema_version"]) is not int or value["schema_version"] != (
            T15_COMPARISON_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported T15 joint comparison result schema.")
        pairs = value["pair_results"]
        if not isinstance(pairs, list) or any(not isinstance(item, Mapping) for item in pairs):
            raise ValueError("T15 pair comparison result rows are malformed.")
        return cls(
            state=ComparisonState(str(value["state"])),
            finalist_ids=tuple(cast(Sequence[str], value["finalist_ids"])),
            strength_draws=cast(Mapping[str, Mapping[str, float]], value["strength_draws"]),
            pair_results=tuple(PairComparisonResult.from_dict(item) for item in pairs),
            maximal_set=tuple(cast(Sequence[str], value["maximal_set"])),
            ordered_maximal_set=tuple(cast(Sequence[str], value["ordered_maximal_set"])),
            primary_preference_id=cast(str | None, value["primary_preference_id"]),
            reason_codes=tuple(cast(Sequence[str], value["reason_codes"])),
            support_manifest_digest=str(value["support_manifest_digest"]),
            joint_uncertainty_digest=str(value["joint_uncertainty_digest"]),
            comparison_rule_digest=str(value["comparison_rule_digest"]),
            resolver_rule_digest=str(value["resolver_rule_digest"]),
        )


def compare_finalists(
    finalists: Sequence[FinalistCandidate],
    joint: JointUncertaintySupport,
    manifest: CandidateSupportManifest,
    policy: PolicyVersion,
) -> T15ComparisonResult:
    """Compare one fixed finalist set through one coherent joint support object."""

    candidates = tuple(sorted(finalists, key=lambda item: item.preference_id))
    finalist_ids = tuple(item.preference_id for item in candidates)
    unknown = not candidates or len(set(finalist_ids)) != len(finalist_ids)
    identity_matches = (
        joint.cutoff_id == manifest.cutoff_id
        and joint.cutoff_digest == manifest.cutoff_digest
        and joint.t10_profile_digest == manifest.t10_profile_digest
        and joint.t10_catalog_digest == manifest.t10_catalog_digest
        and joint.f13_result_digest == manifest.f13_result_digest
        and joint.policy_digest == manifest.policy_digest == policy.digest
        and manifest.resolver_rule_digest == group_resolver_rule_digest()
        and manifest.comparison_rule_digest == comparison_rule_digest()
    )
    if not identity_matches:
        unknown = True
    if joint.state is not SupportState.SUPPORTED or joint.finalist_ids != finalist_ids:
        unknown = True
    if any(item.gate_status is not GateSupportStatus.PASS for item in candidates):
        unknown = True
    if not joint.draw_ids or set(joint.raw_component_draws) != set(finalist_ids):
        unknown = True
    if policy.selection_strength is None:
        unknown = True
    if unknown:
        return _unknown_comparison(
            finalist_ids, manifest, joint, ("JOINT_COMPARISON_SUPPORT_UNKNOWN",)
        )

    config = cast(SelectionStrengthConfig, policy.selection_strength)
    strength_draws: dict[str, dict[str, float]] = {}
    for finalist in candidates:
        finalist_draws = joint.raw_component_draws.get(finalist.preference_id, {})
        if set(finalist_draws) != set(joint.draw_ids):
            return _unknown_comparison(
                finalist_ids, manifest, joint, ("COMMON_DRAW_SET_INCOMPLETE",)
            )
        strength_draws[finalist.preference_id] = {}
        for draw_id in joint.draw_ids:
            raw_components = finalist_draws[draw_id]
            if set(raw_components) != set(SELECTION_COMPONENTS):
                return _unknown_comparison(
                    finalist_ids, manifest, joint, ("JOINT_COMPONENT_DRAW_INCOMPLETE",)
                )
            try:
                strength, _, reasons = selection_strength_from_raw_components(
                    raw_components, config, normalizers=finalist.normalizers
                )
            except TypeError, ValueError:
                return _unknown_comparison(
                    finalist_ids, manifest, joint, ("JOINT_COMPONENT_DRAW_INVALID",)
                )
            if strength is None or reasons:
                return _unknown_comparison(
                    finalist_ids, manifest, joint, ("SELECTION_STRENGTH_UNKNOWN",)
                )
            strength_draws[finalist.preference_id][draw_id] = strength

    required_pairs = {
        (left, right)
        for index, left in enumerate(finalist_ids)
        for right in finalist_ids[index + 1 :]
    }
    region_map = {
        (item.left_preference_id, item.right_preference_id): item for item in joint.paired_regions
    }
    if set(region_map) != required_pairs:
        return _unknown_comparison(finalist_ids, manifest, joint, ("PAIRED_REGION_SET_INCOMPLETE",))

    pair_results: list[PairComparisonResult] = []
    outranked: set[str] = set()
    for left, right in sorted(required_pairs):
        region = region_map[(left, right)]
        if (
            region.state is not SupportState.SUPPORTED
            or region.region_rule_digest != joint.region_rule_digest
        ):
            return _unknown_comparison(
                finalist_ids, manifest, joint, ("PAIRED_REGION_SUPPORT_UNKNOWN",)
            )
        differences = {
            draw_id: strength_draws[left][draw_id] - strength_draws[right][draw_id]
            for draw_id in joint.draw_ids
        }
        lower = cast(float, region.lower)
        upper = cast(float, region.upper)
        if min(differences.values()) < lower or max(differences.values()) > upper:
            return _unknown_comparison(
                finalist_ids, manifest, joint, ("PAIRED_REGION_DOES_NOT_COVER_COMMON_DRAWS",)
            )
        winner = left if lower > 0.0 else right if upper < 0.0 else None
        if winner is not None:
            outranked.add(right if winner == left else left)
        pair_results.append(
            PairComparisonResult(
                left,
                right,
                differences,
                (lower, upper),
                winner,
                ComparisonState.SUPPORTED,
            )
        )
    maximal_set = tuple(item for item in finalist_ids if item not in outranked)
    if not maximal_set:
        return _unknown_comparison(finalist_ids, manifest, joint, ("ROBUST_COMPARISON_CYCLE",))
    ordered, tie_reason = _order_maximal_set(maximal_set, candidates, policy)
    if tie_reason is not None:
        return T15ComparisonResult(
            ComparisonState.UNKNOWN,
            finalist_ids,
            strength_draws,
            tuple(pair_results),
            maximal_set,
            (),
            None,
            (tie_reason,),
            manifest.digest,
            joint.digest,
            manifest.comparison_rule_digest,
            manifest.resolver_rule_digest,
        )
    return T15ComparisonResult(
        ComparisonState.SUPPORTED,
        finalist_ids,
        strength_draws,
        tuple(pair_results),
        maximal_set,
        ordered,
        ordered[0],
        (),
        manifest.digest,
        joint.digest,
        manifest.comparison_rule_digest,
        manifest.resolver_rule_digest,
    )


def _order_maximal_set(
    maximal_set: tuple[str, ...],
    finalists: tuple[FinalistCandidate, ...],
    policy: PolicyVersion,
) -> tuple[tuple[str, ...], str | None]:
    remaining = list(maximal_set)
    candidate_map = {item.preference_id: item for item in finalists}
    criteria = (
        ("uncertainty_width", False),
        ("data_quality", True),
        ("failure_risk", False),
        ("historical_reliability", True),
    )
    for field, reverse in criteria:
        if len(remaining) < 2:
            break
        values: dict[str, float] = {}
        for preference_id in remaining:
            candidate = candidate_map[preference_id]
            value = getattr(candidate, field)
            if field == "failure_risk" and value is None:
                value = candidate.adversarial_materiality
            if value is None:
                return (), f"TIE_BREAK_SUPPORT_UNKNOWN:{field}"
            values[preference_id] = float(value)
        target = max(values.values()) if reverse else min(values.values())
        remaining = [
            preference_id
            for preference_id in remaining
            if math.isclose(values[preference_id], target, abs_tol=1e-12)
        ]
    order = {
        preference_id: index for index, preference_id in enumerate(policy.user_preference_order)
    }
    remaining.sort(
        key=lambda preference_id: (order.get(preference_id, len(order) + 100000), preference_id)
    )
    primary = remaining[0]
    ordered = (primary, *sorted(set(maximal_set) - {primary}))
    return ordered, None


def _unknown_comparison(
    finalist_ids: tuple[str, ...],
    manifest: CandidateSupportManifest,
    joint: JointUncertaintySupport,
    reasons: tuple[str, ...],
) -> T15ComparisonResult:
    return T15ComparisonResult(
        ComparisonState.UNKNOWN,
        finalist_ids,
        {},
        (),
        (),
        (),
        None,
        reasons,
        manifest.digest,
        joint.digest,
        manifest.comparison_rule_digest,
        manifest.resolver_rule_digest,
    )


@dataclass(frozen=True)
class GateSupportResult:
    gate: str
    status: GateSupportStatus
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class G6U1EventResult:
    """Protected U1 result bound to one exact F13 prediction and G5 event."""

    cutoff_id: str
    cutoff_digest: str
    preference_contract_digest: str
    f13_result_digest: str
    f13_prediction_digest: str
    policy_digest: str
    g5_constraints_digest: str
    uncertainty_law_digest: str
    source_draws_digest: str
    settlement_topology: tuple[str, ...]
    probability_mass: float
    event_id: str = G6_U1_EVENT_ID
    schema_version: int = G6_U1_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != G6_U1_EVENT_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported G6 U1 event result schema.")
        if self.event_id != G6_U1_EVENT_ID or not self.cutoff_id.strip():
            raise ValueError("G6 U1 event result identity is incomplete.")
        for name in (
            "cutoff_digest",
            "preference_contract_digest",
            "f13_result_digest",
            "f13_prediction_digest",
            "policy_digest",
            "g5_constraints_digest",
            "uncertainty_law_digest",
            "source_draws_digest",
        ):
            _require_digest(getattr(self, name), f"G6 U1 {name}")
        topology = tuple(self.settlement_topology)
        if not topology or len(set(topology)) != len(topology):
            raise ValueError("G6 U1 event result requires exact settlement topology.")
        probability_mass = _number(self.probability_mass, "G6 U1 probability mass")
        if not 0.0 <= probability_mass <= 1.0:
            raise ValueError("G6 U1 probability mass must lie between zero and one.")
        object.__setattr__(self, "settlement_topology", topology)
        object.__setattr__(self, "probability_mass", probability_mass)

    def to_dict(self) -> dict[str, object]:
        return {
            "cutoff_digest": self.cutoff_digest,
            "cutoff_id": self.cutoff_id,
            "event_id": self.event_id,
            "f13_prediction_digest": self.f13_prediction_digest,
            "f13_result_digest": self.f13_result_digest,
            "g5_constraints_digest": self.g5_constraints_digest,
            "policy_digest": self.policy_digest,
            "preference_contract_digest": self.preference_contract_digest,
            "probability_mass": self.probability_mass,
            "schema_version": self.schema_version,
            "settlement_topology": self.settlement_topology,
            "source_draws_digest": self.source_draws_digest,
            "uncertainty_law_digest": self.uncertainty_law_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> G6U1EventResult:
        _exact_fields(
            value,
            {
                "cutoff_digest",
                "cutoff_id",
                "event_id",
                "f13_prediction_digest",
                "f13_result_digest",
                "g5_constraints_digest",
                "policy_digest",
                "preference_contract_digest",
                "probability_mass",
                "schema_version",
                "settlement_topology",
                "source_draws_digest",
                "uncertainty_law_digest",
            },
            "G6 U1 event result",
        )
        if type(value["schema_version"]) is not int:
            raise ValueError("G6 U1 event schema version must be an integer.")
        string_fields = (
            "cutoff_digest",
            "cutoff_id",
            "event_id",
            "f13_prediction_digest",
            "f13_result_digest",
            "g5_constraints_digest",
            "policy_digest",
            "preference_contract_digest",
            "source_draws_digest",
            "uncertainty_law_digest",
        )
        if any(not isinstance(value[field], str) for field in string_fields):
            raise ValueError("G6 U1 event result identities must be strings.")
        topology = value["settlement_topology"]
        if not isinstance(topology, (tuple, list)) or any(
            not isinstance(item, str) for item in topology
        ):
            raise ValueError("G6 U1 event topology is malformed.")
        return cls(
            cutoff_id=str(value["cutoff_id"]),
            cutoff_digest=str(value["cutoff_digest"]),
            preference_contract_digest=str(value["preference_contract_digest"]),
            f13_result_digest=str(value["f13_result_digest"]),
            f13_prediction_digest=str(value["f13_prediction_digest"]),
            policy_digest=str(value["policy_digest"]),
            g5_constraints_digest=str(value["g5_constraints_digest"]),
            uncertainty_law_digest=str(value["uncertainty_law_digest"]),
            source_draws_digest=str(value["source_draws_digest"]),
            settlement_topology=tuple(topology),
            probability_mass=cast(float, value["probability_mass"]),
            event_id=str(value["event_id"]),
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True)
class F13UncertaintyIdentity:
    """Exact law and source draws used by one replayed F13 prediction."""

    prediction_digest: str
    uncertainty_law_digest: str
    source_draws_digest: str

    def __post_init__(self) -> None:
        for name in ("prediction_digest", "uncertainty_law_digest", "source_draws_digest"):
            _require_digest(getattr(self, name), f"F13 uncertainty identity {name}")


@dataclass(frozen=True)
class CandidateSupportEvaluation:
    preference_id: str
    component_support: Mapping[str, ResolvedComponentSupport]
    gates: Mapping[str, GateSupportResult]

    @property
    def status(self) -> GateSupportStatus:
        statuses = [item.status for item in self.gates.values()]
        if any(value is GateSupportStatus.FAIL for value in statuses):
            return GateSupportStatus.FAIL
        if any(value is GateSupportStatus.UNKNOWN for value in statuses):
            return GateSupportStatus.UNKNOWN
        return GateSupportStatus.PASS


def group_resolver_rule_digest() -> str:
    return _digest(
        {
            "compatibility": ("component", "estimand_id", "settlement_topology"),
            "fallback_order": ("EXACT", "FAMILY_LINE", "ROLE", "LEAGUE", "CONTEXT"),
            "rule": GROUP_RESOLVER_RULE,
        }
    )


def comparison_rule_digest() -> str:
    return _digest(
        {
            "maximal_set": "no-finalist-robustly-outranked",
            "rule": COMPARISON_RULE,
            "tie_break_order": (
                "uncertainty_ascending",
                "data_quality_descending",
                "failure_risk_ascending",
                "historical_reliability_descending",
                "user_preference_order",
            ),
        }
    )


def evaluate_candidate_support(
    context: PreferenceSupportContext,
    support: CandidatePreferenceSupport | None,
    policy: PolicyVersion,
    *,
    cutoff_id: str,
    cutoff_digest: str,
    f13_result_digest: str,
    f13_uncertainty: F13UncertaintyIdentity | None = None,
) -> CandidateSupportEvaluation:
    """Resolve component references and evaluate G6/G7/G8 without legacy booleans."""

    component_support = {
        component: resolve_component_support(
            context,
            component,
            support.component_references if support is not None else (),
        )
        for component in SELECTION_COMPONENTS
    }
    if support is None or support.state is not SupportState.SUPPORTED:
        unknown = {
            gate: GateSupportResult(gate, GateSupportStatus.UNKNOWN, ("SUPPORT_UNKNOWN",))
            for gate in ("G6", "G7", "G8")
        }
        return CandidateSupportEvaluation(
            context.preference.preference_id, component_support, unknown
        )
    if support.preference_id != context.preference.preference_id:
        raise ValueError("Candidate support preference differs from exact T10 identity.")
    gates = {
        "G6": _evaluate_g6(
            context,
            support,
            policy,
            cutoff_id=cutoff_id,
            cutoff_digest=cutoff_digest,
            f13_result_digest=f13_result_digest,
            f13_uncertainty=f13_uncertainty,
        ),
        "G7": _evaluate_g7(
            context.preference,
            support,
            policy,
            cutoff_id=cutoff_id,
            cutoff_digest=cutoff_digest,
        ),
        "G8": _evaluate_g8(
            context.preference,
            support,
            policy,
            f13_result_digest=f13_result_digest,
        ),
    }
    if any(item.state is not SupportState.SUPPORTED for item in component_support.values()):
        gates["SELECTION_STRENGTH"] = GateSupportResult(
            "SELECTION_STRENGTH", GateSupportStatus.UNKNOWN, ("COMPONENT_SUPPORT_UNKNOWN",)
        )
    else:
        gates["SELECTION_STRENGTH"] = GateSupportResult(
            "SELECTION_STRENGTH", GateSupportStatus.PASS, ()
        )
    return CandidateSupportEvaluation(context.preference.preference_id, component_support, gates)


def _bound_evidence_matches(
    value: object,
    artifact_digest: object,
    *,
    kind: str,
    payload: Mapping[str, object],
) -> bool:
    """Match an exact versioned proof record to the claim and its content digest."""
    if not isinstance(value, Mapping):
        return False
    if set(value) != set(payload) | {"kind", "schema_version"}:
        return False
    if (
        value.get("kind") != kind
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != GATE_EVIDENCE_SCHEMA_VERSION
    ):
        return False
    try:
        digest = _require_digest(artifact_digest, f"{kind} protected artifact digest")
        record_payload = {
            key: item for key, item in value.items() if key not in {"kind", "schema_version"}
        }
        return _bytes(record_payload) == _bytes(dict(payload)) and _digest(value) == digest
    except TypeError, ValueError:
        return False


def _evaluate_g6(
    context: PreferenceSupportContext,
    support: CandidatePreferenceSupport,
    policy: PolicyVersion,
    *,
    cutoff_id: str,
    cutoff_digest: str,
    f13_result_digest: str,
    f13_uncertainty: F13UncertaintyIdentity | None,
) -> GateSupportResult:
    preference = context.preference
    value = support.g6 or {}
    u1 = _mapping(value.get("u1"))
    u2 = _mapping(value.get("u2"))
    required_claim = policy.dependencies.get(f"candidate_input.u2_claim:{preference.preference_id}")
    width_max = _threshold_number(policy, "uncertainty_width_max", preference, lower=0.0, upper=1.0)
    tail_max = _threshold_number(
        policy, "uncertainty_tail_risk_max", preference, lower=0.0, upper=1.0
    )
    if (
        not _supported_record(u1)
        or not _supported_record(u2)
        or required_claim is None
        or required_claim not in U2_CLAIM_EVIDENCE_BASES
        or u2.get("claim") != required_claim
        or u2.get("evidence_basis")
        not in U2_CLAIM_EVIDENCE_BASES.get(str(required_claim), frozenset())
        or u1.get("preference_contract_digest") != _digest(preference.to_dict())
        or u2.get("preference_contract_digest") != _digest(preference.to_dict())
    ):
        return GateSupportResult("G6", GateSupportStatus.UNKNOWN, ("G6_REQUIRED_SUPPORT_UNKNOWN",))
    if (
        f13_uncertainty is None
        or type(u1.get("schema_version")) is not int
        or u1.get("schema_version") != G6_U1_EVENT_SCHEMA_VERSION
        or support.f13_prediction_digest != f13_uncertainty.prediction_digest
        or u1.get("f13_prediction_digest") != f13_uncertainty.prediction_digest
        or u1.get("uncertainty_law_digest") != f13_uncertainty.uncertainty_law_digest
        or u1.get("source_draws_digest") != f13_uncertainty.source_draws_digest
        or u1.get("event_result_digest") != u1.get("artifact_digest")
    ):
        return GateSupportResult("G6", GateSupportStatus.UNKNOWN, ("G6_U1_F13_LINK_UNKNOWN",))
    topology = tuple(item.value for item in preference.possible_results)
    try:
        tail = _number(u1.get("probability_mass"), "G6 U1 probability mass")
        width = _number(value.get("uncertainty_width"), "G6 uncertainty width")
        _require_digest(u1.get("event_result_digest"), "G6 U1 event result digest")
        _require_digest(u1.get("artifact_digest"), "G6 U1 protected artifact digest")
        _require_digest(u1.get("uncertainty_law_digest"), "G6 uncertainty law digest")
        _require_digest(u1.get("g5_constraints_digest"), "G6 G5 constraint digest")
        _require_digest(u1.get("source_draws_digest"), "G6 source draws digest")
        _require_digest(u1.get("f13_result_digest"), "G6 F13 result digest")
        _require_digest(u1.get("f13_prediction_digest"), "G6 F13 prediction digest")
        _require_digest(u1.get("policy_digest"), "G6 PolicyVersion digest")
        _require_digest(u2.get("validation_artifact_digest"), "G6 U2 validation digest")
        _require_digest(u2.get("population_digest"), "G6 U2 population digest")
        _require_digest(u2.get("chronology_digest"), "G6 U2 chronology digest")
        _require_digest(u2.get("groups_digest"), "G6 U2 groups digest")
        _require_digest(u2.get("assumptions_digest"), "G6 U2 assumptions digest")
        _require_digest(u2.get("diagnostics_digest"), "G6 U2 diagnostics digest")
        if not isinstance(u2.get("method"), str) or not str(u2["method"]).strip():
            raise ValueError("G6 U2 method is required.")
        raw_group_keys = u2.get("group_keys")
        if not isinstance(raw_group_keys, (tuple, list)) or any(
            not isinstance(group_key, str) or not group_key.strip() for group_key in raw_group_keys
        ):
            raise ValueError("G6 U2 group manifest is required.")
        u2_group_keys = tuple(raw_group_keys)
        if not u2_group_keys or len(set(u2_group_keys)) != len(u2_group_keys):
            raise ValueError("G6 U2 group manifest must be non-empty and unique.")
        groups_digest = _require_digest(u2.get("groups_digest"), "G6 U2 groups digest")
        if groups_digest != _digest({"group_keys": tuple(sorted(u2_group_keys))}):
            raise ValueError("G6 U2 group manifest differs from its exact digest.")
        u2_topology = tuple(cast(Sequence[str], u2.get("settlement_topology", ())))
        validation_payload = {
            field: u2.get(field)
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
        if not _bound_evidence_matches(
            u2.get("validation_record"),
            u2.get("validation_artifact_digest"),
            kind="G6_U2_VALIDATION",
            payload=validation_payload,
        ):
            raise ValueError("G6 U2 validation claim is not bound to its exact record.")
    except TypeError, ValueError:
        return GateSupportResult("G6", GateSupportStatus.UNKNOWN, ("G6_REQUIRED_SUPPORT_INVALID",))
    required_group_keys = {
        f"LEAGUE:{context.league}",
        f"PREFERENCE:{preference.preference_id}",
    }
    if not required_group_keys.issubset(u2_group_keys):
        return GateSupportResult(
            "G6", GateSupportStatus.UNKNOWN, ("G6_UNSUPPORTED_VALIDATION_GROUP",)
        )
    if (
        u1.get("state") != SupportState.SUPPORTED.value
        or u2.get("state") != SupportState.SUPPORTED.value
        or tuple(cast(Sequence[str], u1.get("settlement_topology", ()))) != topology
        or u2_topology != topology
        or u1.get("cutoff_id") != cutoff_id
        or u1.get("cutoff_digest") != cutoff_digest
        or u1.get("f13_result_digest") != f13_result_digest
        or u1.get("policy_digest") != policy.digest
        or u2.get("cutoff_id") != cutoff_id
        or u2.get("cutoff_digest") != cutoff_digest
        or u2.get("policy_digest") != policy.digest
        or not 0.0 <= tail <= 1.0
        or not 0.0 <= width <= 1.0
    ):
        return GateSupportResult(
            "G6", GateSupportStatus.UNKNOWN, ("G6_IDENTITY_OR_CLAIM_MISMATCH",)
        )
    expected_constraints = _digest(
        {
            "conservative_probability_min": _threshold_number(
                policy, "conservative_probability_min", preference, lower=0.0, upper=1.0
            ),
            "loss_risk_max": _threshold_number(
                policy, "loss_risk_max", preference, lower=0.0, upper=1.0
            ),
            "policy_digest": policy.digest,
            "preference_id": preference.preference_id,
        }
    )
    if (
        width_max is None
        or tail_max is None
        or _threshold_number(
            policy, "conservative_probability_min", preference, lower=0.0, upper=1.0
        )
        is None
        or _threshold_number(policy, "loss_risk_max", preference, lower=0.0, upper=1.0) is None
        or u1.get("g5_constraints_digest") != expected_constraints
    ):
        return GateSupportResult(
            "G6", GateSupportStatus.UNKNOWN, ("G6_PROFILE_LIMIT_OR_G5_BINDING_UNKNOWN",)
        )
    if tail > tail_max or width > width_max:
        return GateSupportResult("G6", GateSupportStatus.FAIL, ("G6_SUPPORTED_LIMIT_EXCEEDED",))
    return GateSupportResult("G6", GateSupportStatus.PASS, ())


def _evaluate_g7(
    preference: BettingPreference,
    support: CandidatePreferenceSupport,
    policy: PolicyVersion,
    *,
    cutoff_id: str,
    cutoff_digest: str,
) -> GateSupportResult:
    value = support.g7 or {}
    required_json = policy.dependencies.get(
        f"candidate_input.g7_references:{preference.preference_id}"
    )
    try:
        parsed_ids = json.loads(required_json) if required_json else []
        if (
            not isinstance(parsed_ids, list)
            or any(not isinstance(item, str) or not item for item in parsed_ids)
            or len(parsed_ids) != len(set(parsed_ids))
        ):
            raise ValueError("G7 reference manifest is malformed or duplicated.")
        required_ids = tuple(sorted(parsed_ids))
    except TypeError, ValueError:
        required_ids = ()
    raw_references = value.get("references", ())
    if not isinstance(raw_references, (tuple, list)) or any(
        not isinstance(item, Mapping) for item in raw_references
    ):
        return GateSupportResult(
            "G7", GateSupportStatus.UNKNOWN, ("G7_REFERENCE_MANIFEST_INVALID",)
        )
    references = tuple(cast(Mapping[str, object], item) for item in raw_references)
    present_ids = tuple(sorted(str(item.get("reference_id", "")) for item in references))
    agreement_min = _threshold_number(
        policy, "model_agreement_min", preference, lower=0.0, upper=1.0
    )
    sensitivity_max = _threshold_number(
        policy, "model_sensitivity_max", preference, lower=0.0, upper=1.0
    )
    candidate_digest = value.get("candidate_prediction_digest")
    evaluation_digest = value.get("evaluation_artifact_digest")
    if (
        not required_ids
        or present_ids != required_ids
        or value.get("state") != SupportState.SUPPORTED.value
        or value.get("preference_contract_digest") != _digest(preference.to_dict())
        or value.get("cutoff_id") != cutoff_id
        or value.get("cutoff_digest") != cutoff_digest
        or agreement_min is None
        or sensitivity_max is None
        or not isinstance(candidate_digest, str)
        or candidate_digest != support.f13_prediction_digest
        or not isinstance(evaluation_digest, str)
    ):
        return GateSupportResult(
            "G7", GateSupportStatus.UNKNOWN, ("G7_EXACT_REFERENCE_MANIFEST_UNKNOWN",)
        )
    topology = tuple(item.value for item in preference.possible_results)
    for reference in references:
        if (
            reference.get("availability_state") != "AVAILABLE"
            or reference.get("eligibility_state") != "ELIGIBLE"
        ):
            return GateSupportResult(
                "G7", GateSupportStatus.UNKNOWN, ("G7_REFERENCE_UNAVAILABLE_OR_INELIGIBLE",)
            )
        if (
            reference.get("cutoff_id") != cutoff_id
            or reference.get("cutoff_digest") != cutoff_digest
        ):
            return GateSupportResult(
                "G7", GateSupportStatus.UNKNOWN, ("G7_REFERENCE_CUTOFF_MISMATCH",)
            )
        distribution = _mapping(reference.get("settlement_distribution"))
        ranges = _mapping(reference.get("settlement_ranges"))
        if set(distribution) != set(topology) or set(ranges) != set(topology):
            return GateSupportResult(
                "G7", GateSupportStatus.UNKNOWN, ("G7_REFERENCE_DISTRIBUTION_INCOMPLETE",)
            )
        try:
            reference_payload = {
                field: reference.get(field)
                for field in (
                    "reference_id",
                    "availability_state",
                    "eligibility_state",
                    "preference_contract_digest",
                    "cutoff_id",
                    "cutoff_digest",
                    "settlement_topology",
                    "settlement_distribution",
                    "settlement_ranges",
                    "dependency_group",
                    "provenance_digest",
                    "model_digest",
                    "calibration_digest",
                    "validation_digest",
                    "assumptions_digest",
                    "information_path_digest",
                    "historical_error_digest",
                    "source_artifact_digests",
                )
            }
            reference_artifact_digest = _require_digest(
                reference.get("reference_artifact_digest"), "G7 exact reference artifact digest"
            )
            if not _bound_evidence_matches(
                reference.get("reference_record"),
                reference_artifact_digest,
                kind="G7_REFERENCE",
                payload=reference_payload,
            ):
                raise ValueError("G7 reference is not bound to its exact protected record.")
            if (
                reference.get("preference_contract_digest") != _digest(preference.to_dict())
                or tuple(cast(Sequence[str], reference.get("settlement_topology", ()))) != topology
            ):
                raise ValueError("G7 reference differs from the exact preference topology.")
            probabilities = [
                _number(distribution[key], "G7 settlement probability") for key in topology
            ]
            if any(value < 0.0 or value > 1.0 for value in probabilities) or not math.isclose(
                sum(probabilities), 1.0, abs_tol=1e-9
            ):
                raise ValueError("Invalid settlement distribution.")
            for key in topology:
                bounds = _mapping(ranges[key])
                lower = _number(bounds.get("lower"), "G7 range lower bound")
                upper = _number(bounds.get("upper"), "G7 range upper bound")
                if lower < 0.0 or upper > 1.0 or lower > upper:
                    raise ValueError("Invalid settlement range.")
            for field in (
                "dependency_group",
                "provenance_digest",
                "model_digest",
                "calibration_digest",
                "validation_digest",
                "assumptions_digest",
                "information_path_digest",
                "historical_error_digest",
                "source_artifact_digests",
            ):
                if not reference.get(field):
                    raise ValueError(f"G7 reference {field} is missing.")
                if field.endswith("_digest"):
                    _require_digest(reference[field], f"G7 reference {field}")
                elif field == "source_artifact_digests":
                    for digest in cast(Sequence[str], reference[field]):
                        _require_digest(digest, "G7 reference source digest")
        except TypeError, ValueError:
            return GateSupportResult(
                "G7", GateSupportStatus.UNKNOWN, ("G7_REFERENCE_SUPPORT_INVALID",)
            )
    try:
        agreement = _number(value.get("model_agreement"), "G7 model agreement")
        sensitivity = _number(value.get("model_sensitivity"), "G7 model sensitivity")
        evaluation_digest = _require_digest(evaluation_digest, "G7 evaluation artifact digest")
        reference_artifact_digests = tuple(
            cast(str, reference.get("reference_artifact_digest"))
            for reference in sorted(references, key=lambda item: str(item.get("reference_id")))
        )
        evaluation_payload = {
            "preference_contract_digest": _digest(preference.to_dict()),
            "cutoff_id": cutoff_id,
            "cutoff_digest": cutoff_digest,
            "policy_digest": policy.digest,
            "candidate_prediction_digest": candidate_digest,
            "reference_artifact_digests": reference_artifact_digests,
            "model_agreement": agreement,
            "model_sensitivity": sensitivity,
        }
        if not _bound_evidence_matches(
            value.get("evaluation_record"),
            evaluation_digest,
            kind="G7_EVALUATION",
            payload=evaluation_payload,
        ):
            raise ValueError("G7 metrics are not bound to the exact reference evaluation.")
    except TypeError, ValueError:
        return GateSupportResult("G7", GateSupportStatus.UNKNOWN, ("G7_EVALUATION_UNKNOWN",))
    if not 0.0 <= agreement <= 1.0 or not 0.0 <= sensitivity <= 1.0:
        return GateSupportResult("G7", GateSupportStatus.UNKNOWN, ("G7_EVALUATION_INVALID",))
    if agreement < agreement_min or sensitivity > sensitivity_max:
        return GateSupportResult("G7", GateSupportStatus.FAIL, ("G7_SUPPORTED_LIMIT_EXCEEDED",))
    return GateSupportResult("G7", GateSupportStatus.PASS, ())


def _evaluate_g8(
    preference: BettingPreference,
    support: CandidatePreferenceSupport,
    policy: PolicyVersion,
    *,
    f13_result_digest: str,
) -> GateSupportResult:
    value = support.g8 or {}
    state = value.get("state")
    if state == SupportState.EVIDENCED_ABSENCE.value:
        try:
            absence_digest = _require_digest(
                value.get("absence_evidence_artifact_digest"),
                "G8 absence evidence artifact digest",
            )
            absence_payload = {
                "state": SupportState.EVIDENCED_ABSENCE.value,
                "preference_contract_digest": _digest(preference.to_dict()),
                "f13_result_digest": f13_result_digest,
                "policy_digest": policy.digest,
            }
            if (
                value.get("preference_contract_digest") != _digest(preference.to_dict())
                or value.get("f13_result_digest") != f13_result_digest
                or value.get("absence_evidence_digest") != absence_digest
                or not _bound_evidence_matches(
                    value.get("absence_evidence_record"),
                    absence_digest,
                    kind="G8_ABSENCE",
                    payload=absence_payload,
                )
            ):
                raise ValueError("G8 absence proof has different exact identities.")
        except ValueError:
            return GateSupportResult("G8", GateSupportStatus.UNKNOWN, ("G8_ABSENCE_NOT_EVIDENCED",))
        return GateSupportResult("G8", GateSupportStatus.PASS, ())
    raw_cases = value.get("failure_cases", ())
    if not isinstance(raw_cases, (tuple, list)) or any(
        not isinstance(item, Mapping) for item in raw_cases
    ):
        return GateSupportResult(
            "G8", GateSupportStatus.UNKNOWN, ("G8_FAILURE_CASE_MANIFEST_INVALID",)
        )
    cases = tuple(cast(Mapping[str, object], item) for item in raw_cases)
    if (
        state != SupportState.SUPPORTED.value
        or not cases
        or value.get("preference_contract_digest") != _digest(preference.to_dict())
        or value.get("f13_result_digest") != f13_result_digest
    ):
        return GateSupportResult(
            "G8", GateSupportStatus.UNKNOWN, ("G8_FAILURE_CASE_MANIFEST_UNKNOWN",)
        )
    unrepresented_max = _threshold_number(
        policy, "adversarial_unrepresented_materiality_max", preference, lower=0.0, upper=1.0
    )
    unknown: list[str] = []
    failed: list[str] = []
    seen_case_ids: set[str] = set()
    seen_assertions: set[str] = set()
    seen_evidence: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_case_ids:
            unknown.append("G8_FAILURE_CASE_ID_INVALID")
            continue
        seen_case_ids.add(case_id)
        evidence = case.get("supporting_evidence_digests")
        assertion_record = case.get("assertion_record")
        materiality = _mapping(case.get("materiality"))
        representation = _mapping(case.get("uncertainty_representation"))
        try:
            assertion_digest = _require_digest(
                case.get("source_assertion_digest"), "G8 source assertion digest"
            )
            if assertion_digest in seen_assertions or assertion_digest in seen_evidence:
                raise ValueError("G8 failure assertions and evidence must be distinct.")
            if not isinstance(evidence, (tuple, list)) or not evidence:
                raise ValueError("G8 requires distinct supporting evidence.")
            evidence_digests = tuple(
                _require_digest(digest, "G8 supporting evidence digest") for digest in evidence
            )
            if (
                len(set(evidence_digests)) != len(evidence_digests)
                or assertion_digest in evidence_digests
                or set(evidence_digests) & seen_assertions
                or set(evidence_digests) & seen_evidence
            ):
                raise ValueError("G8 failure assertions and evidence must be distinct.")
            seen_assertions.add(assertion_digest)
            seen_evidence.update(evidence_digests)
            assertion_payload = {
                "case_id": case_id,
                "preference_contract_digest": _digest(preference.to_dict()),
                "f13_result_digest": f13_result_digest,
                "consequence": case.get("consequence"),
                "supporting_evidence_digests": evidence_digests,
                "policy_digest": policy.digest,
            }
            if not _bound_evidence_matches(
                assertion_record,
                assertion_digest,
                kind="G8_FAILURE_ASSERTION",
                payload=assertion_payload,
            ):
                raise ValueError("G8 assertion is not bound to its exact protected record.")
            if materiality.get("state") != SupportState.SUPPORTED.value:
                raise ValueError("G8 materiality support is unknown.")
            materiality_value = _number(materiality.get("value"), "G8 materiality")
            if not 0.0 <= materiality_value <= 1.0:
                raise ValueError("G8 materiality is invalid.")
            materiality_digest = _require_digest(
                materiality.get("support_artifact_digest"),
                "G8 materiality support artifact digest",
            )
            if materiality.get("support_digest") != materiality_digest:
                raise ValueError("G8 materiality identity differs from its exact artifact.")
            if (
                not isinstance(materiality.get("effect_unit"), str)
                or not materiality["effect_unit"]
            ):
                raise ValueError("G8 effect unit is required.")
            materiality_payload = {
                "case_id": case_id,
                "preference_contract_digest": _digest(preference.to_dict()),
                "f13_result_digest": f13_result_digest,
                "policy_digest": policy.digest,
                "source_assertion_digest": assertion_digest,
                "supporting_evidence_digests": evidence_digests,
                "value": materiality_value,
                "effect_unit": materiality["effect_unit"],
            }
            if not _bound_evidence_matches(
                materiality.get("support_record"),
                materiality_digest,
                kind="G8_MATERIALITY",
                payload=materiality_payload,
            ):
                raise ValueError("G8 materiality is not bound to its exact protected record.")
        except TypeError, ValueError:
            unknown.append("G8_MATERIALITY_OR_EVIDENCE_UNKNOWN")
            continue
        consequence = case.get("consequence")
        if consequence == "VETO":
            failed.append("G8_SUPPORTED_VETO")
        elif consequence not in {"NO_VETO", "DOWNGRADE"}:
            unknown.append("G8_CONSEQUENCE_UNKNOWN")
        representation_state = representation.get("state")
        try:
            u1 = _mapping(_mapping(support.g6).get("u1"))
            uncertainty_law_digest = _require_digest(
                u1.get("uncertainty_law_digest"), "G8 F13 uncertainty law digest"
            )
        except ValueError:
            unknown.append("G8_UNCERTAINTY_REPRESENTATION_UNKNOWN")
            continue
        if representation_state == "REPRESENTED":
            try:
                representation_digest = _require_digest(
                    representation.get("artifact_digest"), "G8 uncertainty representation digest"
                )
                representation_payload = {
                    "state": "REPRESENTED",
                    "case_id": case_id,
                    "preference_contract_digest": _digest(preference.to_dict()),
                    "f13_result_digest": f13_result_digest,
                    "policy_digest": policy.digest,
                    "uncertainty_law_digest": uncertainty_law_digest,
                }
                if (
                    representation.get("f13_result_digest") != f13_result_digest
                    or representation.get("uncertainty_law_digest") != uncertainty_law_digest
                    or not _bound_evidence_matches(
                        representation.get("support_record"),
                        representation_digest,
                        kind="G8_UNCERTAINTY_REPRESENTATION",
                        payload=representation_payload,
                    )
                ):
                    raise ValueError("G8 representation differs from its exact F13 law record.")
            except ValueError:
                unknown.append("G8_UNCERTAINTY_REPRESENTATION_UNKNOWN")
        elif representation_state == "NOT_REPRESENTED":
            try:
                absence_digest = _require_digest(
                    representation.get("absence_evidence_artifact_digest"),
                    "G8 non-representation evidence artifact digest",
                )
                representation_payload = {
                    "state": "NOT_REPRESENTED",
                    "case_id": case_id,
                    "preference_contract_digest": _digest(preference.to_dict()),
                    "f13_result_digest": f13_result_digest,
                    "policy_digest": policy.digest,
                    "uncertainty_law_digest": uncertainty_law_digest,
                }
                if (
                    representation.get("absence_evidence_digest") != absence_digest
                    or representation.get("f13_result_digest") != f13_result_digest
                    or representation.get("uncertainty_law_digest") != uncertainty_law_digest
                    or not _bound_evidence_matches(
                        representation.get("support_record"),
                        absence_digest,
                        kind="G8_UNCERTAINTY_REPRESENTATION",
                        payload=representation_payload,
                    )
                ):
                    raise ValueError(
                        "G8 non-representation proof has a different artifact identity."
                    )
            except ValueError:
                unknown.append("G8_UNCERTAINTY_REPRESENTATION_UNKNOWN")
                continue
            if unrepresented_max is None:
                unknown.append("G8_UNREPRESENTED_MATERIALITY_LIMIT_UNKNOWN")
            elif materiality_value > unrepresented_max:
                failed.append("G8_UNREPRESENTED_MATERIALITY_ABOVE_LIMIT")
        else:
            unknown.append("G8_UNCERTAINTY_REPRESENTATION_UNKNOWN")
    if failed:
        return GateSupportResult("G8", GateSupportStatus.FAIL, tuple(sorted(set(failed))))
    if unknown:
        return GateSupportResult("G8", GateSupportStatus.UNKNOWN, tuple(sorted(set(unknown))))
    return GateSupportResult("G8", GateSupportStatus.PASS, ())


def resolve_component_support(
    context: PreferenceSupportContext,
    component: str,
    references: Sequence[ComponentSupportReference],
) -> ResolvedComponentSupport:
    """Resolve one component by exact preference and compatible ancestors."""

    if component not in SELECTION_COMPONENTS:
        raise ValueError("Support resolution names an unknown Selection Strength component.")
    preference = context.preference
    line = preference.to_dict()["line"]
    line_key = str(line) if line is not None else "NONE"
    groups: list[tuple[str, str]] = [
        ("EXACT", preference.preference_id),
        ("FAMILY_LINE", f"{preference.family.value}|{line_key}"),
        ("ROLE", preference.selection),
        ("LEAGUE", context.league),
        *(("CONTEXT", item) for item in context.supported_contexts),
    ]
    estimand = context.component_estimands.get(component)
    if not estimand:
        return ResolvedComponentSupport(
            component,
            SupportState.UNKNOWN,
            None,
            None,
            (),
            "COMPONENT_ESTIMAND_UNKNOWN",
        )

    considered: list[str] = []
    for scope, group_key in groups:
        identity = f"{scope}:{group_key}"
        matches = tuple(
            reference
            for reference in references
            if reference.component == component
            and reference.scope == scope
            and reference.group_key == group_key
        )
        if len(matches) > 1:
            return ResolvedComponentSupport(
                component,
                SupportState.INVALID,
                None,
                None,
                tuple((*considered, identity)),
                "DUPLICATE_GROUP_REFERENCE",
            )
        considered.append(identity)
        if not matches:
            continue
        reference = matches[0]
        compatible = (
            reference.estimand_id == estimand
            and reference.settlement_topology == context.settlement_topology
        )
        if not compatible or reference.state is not SupportState.SUPPORTED:
            continue
        try:
            normalizer = NormalizationSpec.from_value(reference.normalizer)
        except ValueError:
            return ResolvedComponentSupport(
                component,
                SupportState.INVALID,
                reference.digest,
                None,
                tuple(considered),
                "INVALID_NORMALIZATION_REFERENCE",
            )
        reason = "EXACT" if scope == "EXACT" else f"FALLBACK_{scope}"
        return ResolvedComponentSupport(
            component,
            SupportState.SUPPORTED,
            reference.digest,
            normalizer,
            tuple(considered),
            reason,
        )

    return ResolvedComponentSupport(
        component,
        SupportState.UNKNOWN,
        None,
        None,
        tuple(considered),
        "NO_COMPATIBLE_SUPPORTED_REFERENCE",
    )


def _require_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(_plain(value)).encode("utf-8")).hexdigest()


def _bytes(value: object) -> bytes:
    return canonical_json(_plain(value)).encode("utf-8")


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric.")
    selected = float(value)
    if not math.isfinite(selected):
        raise ValueError(f"{label} must be finite.")
    return selected


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_mapping(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    return dict(value) if value is not None else None


def _supported_record(value: Mapping[str, object]) -> bool:
    return value.get("state") == SupportState.SUPPORTED.value


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class CandidateInputDecisionInput:
    """Exact F14 successor input binding every upstream and comparison identity."""

    base_f14_result_digest: str
    base_f14_input_digest: str
    support_manifest_digest: str
    joint_uncertainty_digest: str
    comparison_result_digest: str
    cutoff_id: str
    cutoff_digest: str
    t10_profile_digest: str
    t10_catalog_digest: str
    t10_preference_contracts: Mapping[str, Mapping[str, object]]
    t10_preference_contract_digests: Mapping[str, str]
    f13_result_digest: str
    policy_version: str
    policy_digest: str
    policy_contract: Mapping[str, object]
    resolver_rule: str
    resolver_rule_digest: str
    comparison_rule: str
    comparison_rule_digest: str
    candidate_contract_digest: str | None
    schema_version: int = F14_SUPPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != F14_SUPPORT_SCHEMA_VERSION:
            raise ValueError("Unsupported F14 CandidateInput successor schema.")
        for name in (
            "base_f14_result_digest",
            "base_f14_input_digest",
            "support_manifest_digest",
            "joint_uncertainty_digest",
            "comparison_result_digest",
            "t10_profile_digest",
            "t10_catalog_digest",
            "f13_result_digest",
            "policy_digest",
            "resolver_rule_digest",
            "comparison_rule_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_contract_digest(self.cutoff_digest, "cutoff digest")
        if self.candidate_contract_digest is not None:
            _require_digest(self.candidate_contract_digest, "candidate contract digest")
        if not self.cutoff_id.strip() or not self.policy_version.strip():
            raise ValueError("F14 successor input requires exact cutoff and policy identities.")
        if self.resolver_rule != GROUP_RESOLVER_RULE or self.comparison_rule != COMPARISON_RULE:
            raise ValueError("F14 successor input names an unsupported consumer rule.")
        contracts = {str(key): dict(value) for key, value in self.t10_preference_contracts.items()}
        digests = {
            str(key): _require_digest(value, "T10 preference contract digest")
            for key, value in self.t10_preference_contract_digests.items()
        }
        if set(contracts) != set(digests) or not contracts:
            raise ValueError("F14 successor input requires the exact enabled T10 contracts.")
        if any(_digest(contract) != digests[key] for key, contract in contracts.items()):
            raise ValueError("F14 successor T10 contract digest differs from its exact contract.")
        policy = dict(self.policy_contract)
        if (
            policy.get("version") != self.policy_version
            or policy.get("policy_digest") != self.policy_digest
        ):
            raise ValueError("F14 successor PolicyVersion differs from its exact policy digest.")
        object.__setattr__(self, "t10_preference_contracts", contracts)
        object.__setattr__(self, "t10_preference_contract_digests", digests)
        object.__setattr__(self, "policy_contract", policy)

    def to_dict(self) -> dict[str, object]:
        return {
            "base_f14_input_digest": self.base_f14_input_digest,
            "base_f14_result_digest": self.base_f14_result_digest,
            "candidate_contract_digest": self.candidate_contract_digest,
            "comparison_result_digest": self.comparison_result_digest,
            "comparison_rule": self.comparison_rule,
            "comparison_rule_digest": self.comparison_rule_digest,
            "cutoff_digest": self.cutoff_digest,
            "cutoff_id": self.cutoff_id,
            "f13_result_digest": self.f13_result_digest,
            "joint_uncertainty_digest": self.joint_uncertainty_digest,
            "policy_contract": dict(self.policy_contract),
            "policy_digest": self.policy_digest,
            "policy_version": self.policy_version,
            "resolver_rule": self.resolver_rule,
            "resolver_rule_digest": self.resolver_rule_digest,
            "schema_version": self.schema_version,
            "support_manifest_digest": self.support_manifest_digest,
            "t10_catalog_digest": self.t10_catalog_digest,
            "t10_preference_contract_digests": dict(
                sorted(self.t10_preference_contract_digests.items())
            ),
            "t10_preference_contracts": {
                key: dict(value) for key, value in sorted(self.t10_preference_contracts.items())
            },
            "t10_profile_digest": self.t10_profile_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CandidateInputDecisionInput:
        _exact_fields(
            value,
            {
                "base_f14_input_digest",
                "base_f14_result_digest",
                "candidate_contract_digest",
                "comparison_result_digest",
                "comparison_rule",
                "comparison_rule_digest",
                "cutoff_digest",
                "cutoff_id",
                "f13_result_digest",
                "joint_uncertainty_digest",
                "policy_contract",
                "policy_digest",
                "policy_version",
                "resolver_rule",
                "resolver_rule_digest",
                "schema_version",
                "support_manifest_digest",
                "t10_catalog_digest",
                "t10_preference_contract_digests",
                "t10_preference_contracts",
                "t10_profile_digest",
            },
            "F14 CandidateInput successor input",
        )
        if type(value["schema_version"]) is not int:
            raise ValueError("F14 successor schema version must be an integer.")
        return cls(
            base_f14_result_digest=str(value["base_f14_result_digest"]),
            base_f14_input_digest=str(value["base_f14_input_digest"]),
            support_manifest_digest=str(value["support_manifest_digest"]),
            joint_uncertainty_digest=str(value["joint_uncertainty_digest"]),
            comparison_result_digest=str(value["comparison_result_digest"]),
            cutoff_id=str(value["cutoff_id"]),
            cutoff_digest=str(value["cutoff_digest"]),
            t10_profile_digest=str(value["t10_profile_digest"]),
            t10_catalog_digest=str(value["t10_catalog_digest"]),
            t10_preference_contracts=cast(
                Mapping[str, Mapping[str, object]], value["t10_preference_contracts"]
            ),
            t10_preference_contract_digests=cast(
                Mapping[str, str], value["t10_preference_contract_digests"]
            ),
            f13_result_digest=str(value["f13_result_digest"]),
            policy_version=str(value["policy_version"]),
            policy_digest=str(value["policy_digest"]),
            policy_contract=cast(Mapping[str, object], value["policy_contract"]),
            resolver_rule=str(value["resolver_rule"]),
            resolver_rule_digest=str(value["resolver_rule_digest"]),
            comparison_rule=str(value["comparison_rule"]),
            comparison_rule_digest=str(value["comparison_rule_digest"]),
            candidate_contract_digest=cast(str | None, value["candidate_contract_digest"]),
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True)
class CandidateInputDecisionResult:
    """Canonical protected F14 successor result."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.canonical_bytes)
        except (TypeError, ValueError) as error:
            raise F14Error("Malformed F14 CandidateInput successor result.") from error
        if not isinstance(value, dict) or _bytes(value) != self.canonical_bytes:
            raise F14Error("F14 CandidateInput successor result must be canonical JSON.")
        if (
            type(value.get("schema_version")) is not int
            or value.get("schema_version") != F14_SUPPORT_SCHEMA_VERSION
            or value.get("status") != "RESEARCH_ONLY"
        ):
            raise F14Error("Unsupported or non-research F14 CandidateInput result.")
        outcome = value.get("outcome")
        primary = value.get("primary_preference_id")
        reason = value.get("decision_reason")
        rows = value.get("preference_results")
        if not isinstance(rows, list) or not rows:
            raise F14Error("F14 CandidateInput result requires one row per enabled preference.")
        row_ids: list[str] = []
        primary_rows: list[str] = []
        terminal_values = {
            "PRIMARY_RECOMMENDATION",
            "SURVIVES_NOT_SELECTED",
            "REJECTED",
            "UNKNOWN",
        }
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("preference_id"), str)
                or row.get("terminal_result") not in terminal_values
            ):
                raise F14Error("F14 CandidateInput result preference row is malformed.")
            row_id = cast(str, row["preference_id"])
            row_ids.append(row_id)
            if row["terminal_result"] == "PRIMARY_RECOMMENDATION":
                primary_rows.append(row_id)
        if len(row_ids) != len(set(row_ids)):
            raise F14Error("F14 CandidateInput result has duplicate preference rows.")
        if outcome == "Primary Recommendation":
            if (
                not isinstance(primary, str)
                or reason is not None
                or primary_rows != [primary]
                or primary not in row_ids
            ):
                raise F14Error("F14 successor recommendation requires one supported primary.")
        elif outcome == "AVOID MATCH":
            if (
                primary is not None
                or primary_rows
                or reason
                not in {
                    "NO_PREFERENCE_PASSED_ABSOLUTE_GATES",
                    "PRIMARY_SELECTION_UNRESOLVED",
                }
            ):
                raise F14Error("F14 successor AVOID requires an exact decision reason.")
            unresolved = value.get("unresolved_preference_ids")
            if reason == "PRIMARY_SELECTION_UNRESOLVED" and not unresolved:
                raise F14Error("Unresolved F14 AVOID requires affected preference identities.")
            if reason == "NO_PREFERENCE_PASSED_ABSOLUTE_GATES" and unresolved:
                raise F14Error("Absolute-gate F14 AVOID cannot retain unresolved candidates.")
        else:
            raise F14Error("Unsupported F14 CandidateInput outcome.")
        if not isinstance(value.get("lineage"), dict) or not isinstance(
            value.get("fixture_id"), str
        ):
            raise F14Error("F14 CandidateInput result lineage or rows are malformed.")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, object]:
        value = json.loads(self.canonical_bytes)
        return cast(dict[str, object], value)


class CandidateInputSupportRepository:
    """Publish and replay exact F13 support, T15 comparison, and F14 v4 artifacts."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)

    def publish_support_manifest(self, manifest: CandidateSupportManifest) -> str:
        return self.artifacts.publish_artifact(
            _bytes(manifest.to_dict()), F13_SUPPORT_MEDIA_TYPE
        ).digest

    def publish_joint_uncertainty(self, joint: JointUncertaintySupport) -> str:
        return self.artifacts.publish_artifact(
            _bytes(joint.to_dict()), T15_COMPARISON_MEDIA_TYPE
        ).digest

    def build_decision(
        self,
        base_f14_result_digest: str,
        support_manifest_digest: str,
        joint_uncertainty_digest: str,
    ) -> CandidateInputDecisionResult:
        prepared = self._prepare(
            base_f14_result_digest, support_manifest_digest, joint_uncertainty_digest
        )
        comparison_bytes = _bytes(prepared[1].to_dict())
        comparison_digest = hashlib.sha256(comparison_bytes).hexdigest()
        self.artifacts.publish_artifact(comparison_bytes, T15_COMPARISON_RESULT_MEDIA_TYPE)
        successor_input = replace(prepared[0], comparison_result_digest=comparison_digest)
        input_bytes = _bytes(successor_input.to_dict())
        input_digest = hashlib.sha256(input_bytes).hexdigest()
        self.artifacts.publish_artifact(input_bytes, F14_SUPPORT_INPUT_MEDIA_TYPE)
        result = CandidateInputDecisionResult(
            _bytes(self._result_payload(successor_input, input_digest, prepared[2], prepared[1]))
        )
        self.artifacts.publish_artifact(result.to_bytes(), F14_SUPPORT_RESULT_MEDIA_TYPE)
        return result

    def replay(self, digest: str) -> CandidateInputDecisionResult:
        content = self._read_exact(digest, F14_SUPPORT_RESULT_MEDIA_TYPE)
        try:
            value = json.loads(content)
            input_digest = value["input_bundle_digest"]
            raw_input = json.loads(self._read_exact(input_digest, F14_SUPPORT_INPUT_MEDIA_TYPE))
            successor_input = CandidateInputDecisionInput.from_dict(raw_input)
            if successor_input.digest != input_digest:
                raise F14Error("F14 successor input digest differs from its exact contents.")
            if value.get("lineage", {}).get("comparison_result_digest") != (
                successor_input.comparison_result_digest
            ):
                raise F14Error("F14 successor result names a different comparison artifact.")
            comparison_bytes = self._read_exact(
                successor_input.comparison_result_digest, T15_COMPARISON_RESULT_MEDIA_TYPE
            )
            comparison_value = json.loads(comparison_bytes)
            if not isinstance(comparison_value, Mapping):
                raise F14Error("T15 comparison result is not a schema object.")
            T15ComparisonResult.from_dict(comparison_value)
            expected_input, expected_comparison, base, _profile, _policy, _manifest, _joint = (
                self._resolve_exact(
                    successor_input.base_f14_result_digest,
                    successor_input.support_manifest_digest,
                    successor_input.joint_uncertainty_digest,
                )
            )
            expected_input = replace(
                expected_input,
                comparison_result_digest=hashlib.sha256(
                    _bytes(expected_comparison.to_dict())
                ).hexdigest(),
            )
            expected_result = CandidateInputDecisionResult(
                _bytes(
                    self._result_payload(
                        expected_input,
                        expected_input.digest,
                        base,
                        expected_comparison,
                    )
                )
            )
            expected_comparison_bytes = _bytes(expected_comparison.to_dict())
            if (
                comparison_bytes != expected_comparison_bytes
                or _bytes(expected_input.to_dict()) != _bytes(successor_input.to_dict())
                or expected_result.to_bytes() != content
                or expected_result.digest != digest
            ):
                raise F14Error(
                    "F14 successor differs from exact replayed predecessor and support artifacts."
                )
            return expected_result
        except F14Error:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise F14Error("Malformed F14 CandidateInput successor lineage.") from error

    def _prepare(
        self,
        base_f14_result_digest: str,
        support_manifest_digest: str,
        joint_uncertainty_digest: str,
    ) -> tuple[
        CandidateInputDecisionInput,
        T15ComparisonResult,
        Mapping[str, object],
        Mapping[str, object],
        PolicyVersion,
        CandidateSupportManifest,
        JointUncertaintySupport,
    ]:
        return self._resolve_exact(
            base_f14_result_digest, support_manifest_digest, joint_uncertainty_digest
        )

    def _resolve_exact(
        self,
        base_f14_result_digest: str,
        support_manifest_digest: str,
        joint_uncertainty_digest: str,
    ) -> tuple[
        CandidateInputDecisionInput,
        T15ComparisonResult,
        Mapping[str, object],
        Mapping[str, object],
        PolicyVersion,
        CandidateSupportManifest,
        JointUncertaintySupport,
    ]:
        base_value = self._read_base_decision(base_f14_result_digest)
        candidate_contract_digest = cast(
            str | None,
            base_value.get("candidate_contract_digest")
            or _mapping(base_value.get("lineage")).get("candidate_contract_digest"),
        )
        base_repository = DecisionRepository(
            self.store, candidate_contract_digest=candidate_contract_digest
        )
        try:
            base_decision = base_repository.replay(base_f14_result_digest).to_dict()
        except (F14Error, KeyError, TypeError, ValueError) as error:
            raise F14Error("Exact predecessor F14 result cannot be replayed.") from error
        if base_decision != base_value:
            raise F14Error("Exact predecessor F14 result changed during replay.")
        lineage = _mapping(base_value.get("lineage"))
        base_input_digest = base_value.get("input_bundle_digest")
        if not isinstance(base_input_digest, str):
            raise F14Error("Exact predecessor F14 input identity is missing.")
        base_input = self._read_base_input(base_input_digest, candidate_contract_digest)
        try:
            cutoff_id = str(base_input["cutoff_id"])
            cutoff = MatchEvidenceCutoffRepository(self.store).replay(cutoff_id)
            profile_digest = str(base_input["profile_digest"])
            profile = PreferenceProfileRepository(self.store).replay(profile_digest)
            policy_value = cast(Mapping[str, object], base_input["policy"])
            policy = PolicyVersion.from_mapping(policy_value)
            if policy.mode is not PolicyStatus.RESEARCH_ONLY:
                raise F14Error("F14 CandidateInput successor must remain RESEARCH_ONLY.")
            if policy_value.get("policy_digest") != policy.digest:
                raise F14Error("Exact predecessor PolicyVersion digest is invalid.")
            f13_digest = str(base_input["model_result_digest"])
            evidence_digest = str(base_input["evidence_digest"])
            f13_model = (
                ModelContractRepository(
                    self.store, candidate_contract_digest=candidate_contract_digest
                )
                .replay(f13_digest, evidence_digest, cutoff_id)
                .to_dict()
            )
        except (F13Error, KeyError, TypeError, ValueError) as error:
            if isinstance(error, F14Error):
                raise
            raise F14Error(
                "Exact cutoff, T10 profile, PolicyVersion, or F13 result is unavailable."
            ) from error

        expected_lineage = {
            "cutoff_id": cutoff_id,
            "evidence_digest": evidence_digest,
            "f13_model_result_digest": f13_digest,
            "profile_digest": profile_digest,
            "t10_preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
            "t15_policy_digest": policy.digest,
            "t15_policy_version": policy.version,
        }
        if any(lineage.get(key) != expected for key, expected in expected_lineage.items()):
            raise F14Error(
                "Exact predecessor F14 lineage differs from its replayed input contracts."
            )
        if (
            candidate_contract_digest is not None
            and lineage.get("candidate_contract_digest") != candidate_contract_digest
        ):
            raise F14Error("Exact predecessor F14 candidate contract lineage differs.")
        target = _mapping(_mapping(f13_model.get("inputs")).get("target"))
        league = target.get("competition_key")
        if not isinstance(league, str) or not league:
            raise F14Error("Exact F13 result has no competition identity for support grouping.")

        manifest = CandidateSupportManifest.from_dict(
            cast(
                Mapping[str, object],
                json.loads(self._read_exact(support_manifest_digest, F13_SUPPORT_MEDIA_TYPE)),
            )
        )
        joint = JointUncertaintySupport.from_dict(
            cast(
                Mapping[str, object],
                json.loads(self._read_exact(joint_uncertainty_digest, T15_COMPARISON_MEDIA_TYPE)),
            )
        )
        f13_lineage_models = _mapping(lineage.get("f13_models"))
        preference_rows = {row.preference_id: row for row in manifest.preference_supports}
        profile_preferences = tuple(profile.enabled_preferences)
        preference_contracts = {
            preference.preference_id: preference.to_dict() for preference in profile_preferences
        }
        preference_contract_digests = {
            preference_id: _digest(contract)
            for preference_id, contract in preference_contracts.items()
        }
        exact_manifest_identity = (
            manifest.cutoff_id == cutoff_id
            and manifest.cutoff_digest == cutoff.digest
            and manifest.t10_profile_digest == profile_digest
            and manifest.t10_catalog_digest == DEFAULT_PREFERENCE_CATALOG.digest
            and manifest.f13_result_digest == f13_digest
            and manifest.policy_digest == policy.digest
            and manifest.league == league
            and set(preference_rows).issubset(preference_contracts)
        )

        support_sources_available = self._protected_sources_available(
            manifest.source_artifact_digests
        )
        joint_sources_available = self._protected_sources_available(joint.source_artifact_digests)
        base_rows = _mapping_rows(base_value.get("preference_results"))
        finalists: list[FinalistCandidate] = []
        unknown_ids: list[str] = []
        output_rows: list[dict[str, object]] = []
        for preference in profile_preferences:
            preference_id = preference.preference_id
            base_row = base_rows.get(preference_id)
            if base_row is None:
                raise F14Error("Exact predecessor F14 result omits an enabled T10 preference.")
            vetting = _mapping(base_row.get("vetting"))
            g05 = _g05_state(vetting)
            support_row = preference_rows.get(preference_id) if exact_manifest_identity else None
            if support_row is not None and (
                support_row.preference_contract_digest != preference_contract_digests[preference_id]
                or support_row.f13_prediction_digest
                != _prediction_digest_for_preference(preference, f13_lineage_models)
            ):
                support_row = None
            f13_uncertainty = _f13_uncertainty_identity(preference, f13_model)
            if (
                f13_uncertainty is not None
                and f13_uncertainty.prediction_digest
                != _prediction_digest_for_preference(preference, f13_lineage_models)
            ):
                f13_uncertainty = None
            safe_support = self._safe_preference_support(
                support_row if support_sources_available else None,
                f13_uncertainty=f13_uncertainty,
                f13_result_digest=f13_digest,
            )
            context = PreferenceSupportContext(
                preference=preference,
                league=league,
                supported_contexts=() if safe_support is None else safe_support.supported_contexts,
                component_estimands={}
                if safe_support is None
                else safe_support.component_estimands,
            )
            if g05 == "FAIL":
                output_rows.append(
                    _successor_preference_row(
                        preference_id,
                        str(base_row.get("terminal_result", "REJECTED")),
                        "REJECTED",
                        {"G0_G5": {"status": "FAIL", "reason_codes": ()}},
                        (),
                        vetting,
                    )
                )
                continue
            if g05 == "UNKNOWN":
                unknown_ids.append(preference_id)
                output_rows.append(
                    _successor_preference_row(
                        preference_id,
                        str(base_row.get("terminal_result", "UNKNOWN")),
                        "UNKNOWN",
                        {"G0_G5": {"status": "UNKNOWN", "reason_codes": ("BASE_G0_G5_UNKNOWN",)}},
                        ("BASE_G0_G5_UNKNOWN",),
                        vetting,
                    )
                )
                continue
            evaluation = evaluate_candidate_support(
                context,
                safe_support,
                policy,
                cutoff_id=cutoff_id,
                cutoff_digest=cutoff.digest,
                f13_result_digest=f13_digest,
                f13_uncertainty=f13_uncertainty,
            )
            gate_rows = {
                name: {
                    "reason_codes": result.reason_codes,
                    "status": result.status.value,
                }
                for name, result in evaluation.gates.items()
            }
            gate_states = tuple(item.status for item in evaluation.gates.values())
            if any(state is GateSupportStatus.FAIL for state in gate_states):
                terminal = "REJECTED"
            elif any(state is GateSupportStatus.UNKNOWN for state in gate_states):
                terminal = "UNKNOWN"
                unknown_ids.append(preference_id)
            else:
                terminal = "SURVIVES_NOT_SELECTED"
                normalizers = {
                    name: value.normalizer
                    for name, value in evaluation.component_support.items()
                    if value.normalizer is not None
                }
                reference_digests = {
                    name: value.reference_digest
                    for name, value in evaluation.component_support.items()
                    if value.reference_digest is not None
                }
                try:
                    finalists.append(
                        FinalistCandidate(
                            preference_id=preference_id,
                            gate_status=GateSupportStatus.PASS,
                            normalizers=cast(Mapping[str, NormalizationSpec], normalizers),
                            normalizer_reference_digests=cast(Mapping[str, str], reference_digests),
                            uncertainty_width=_optional_number(vetting.get("uncertainty_width")),
                            data_quality=_optional_number(vetting.get("data_quality")),
                            failure_risk=_optional_number(vetting.get("failure_risk")),
                            adversarial_materiality=_optional_number(
                                _mapping(vetting.get("adversarial_review")).get("materiality")
                            ),
                            historical_reliability=_optional_number(
                                vetting.get("historical_reliability")
                            ),
                        )
                    )
                except ValueError:
                    terminal = "UNKNOWN"
                    unknown_ids.append(preference_id)
                    gate_rows["SELECTION_STRENGTH"] = {
                        "reason_codes": ("FINALIST_TIE_SUPPORT_UNKNOWN",),
                        "status": GateSupportStatus.UNKNOWN.value,
                    }
            reasons = tuple(
                sorted(
                    {reason for item in evaluation.gates.values() for reason in item.reason_codes}
                )
            )
            output_rows.append(
                _successor_preference_row(
                    preference_id,
                    str(base_row.get("terminal_result", "SURVIVES_NOT_SELECTED")),
                    terminal,
                    gate_rows,
                    reasons,
                    vetting,
                    _resolved_component_rows(evaluation.component_support),
                )
            )

        finalist_ids = tuple(sorted(item.preference_id for item in finalists))
        if unknown_ids:
            comparison = _unknown_comparison(
                finalist_ids,
                manifest,
                joint,
                ("FINALIST_SUPPORT_UNKNOWN",),
            )
        elif not finalists:
            comparison = T15ComparisonResult(
                ComparisonState.SUPPORTED,
                (),
                {},
                (),
                (),
                (),
                None,
                ("NO_FINALISTS",),
                manifest.digest,
                joint.digest,
                manifest.comparison_rule_digest,
                manifest.resolver_rule_digest,
            )
        elif not joint_sources_available:
            comparison = _unknown_comparison(
                finalist_ids, manifest, joint, ("JOINT_SOURCE_ARTIFACT_UNAVAILABLE",)
            )
        else:
            comparison = compare_finalists(finalists, joint, manifest, policy)

        if comparison.state is ComparisonState.UNKNOWN:
            primary_id = None
            outcome = "AVOID MATCH"
            reason = "PRIMARY_SELECTION_UNRESOLVED"
            unresolved_ids = tuple(sorted(set((*unknown_ids, *finalist_ids))))
        elif comparison.primary_preference_id is not None:
            primary_id = comparison.primary_preference_id
            outcome = "Primary Recommendation"
            reason = None
            unresolved_ids = ()
        else:
            primary_id = None
            outcome = "AVOID MATCH"
            reason = "NO_PREFERENCE_PASSED_ABSOLUTE_GATES"
            unresolved_ids = ()
        for row in output_rows:
            if row["preference_id"] == primary_id:
                row["terminal_result"] = "PRIMARY_RECOMMENDATION"
            elif row["preference_id"] in finalist_ids and row["terminal_result"] != "UNKNOWN":
                row["terminal_result"] = "SURVIVES_NOT_SELECTED"

        expected_input = CandidateInputDecisionInput(
            base_f14_result_digest=base_f14_result_digest,
            base_f14_input_digest=base_input_digest,
            support_manifest_digest=support_manifest_digest,
            joint_uncertainty_digest=joint_uncertainty_digest,
            comparison_result_digest="0" * 64,
            cutoff_id=cutoff_id,
            cutoff_digest=cutoff.digest,
            t10_profile_digest=profile_digest,
            t10_catalog_digest=DEFAULT_PREFERENCE_CATALOG.digest,
            t10_preference_contracts=preference_contracts,
            t10_preference_contract_digests=preference_contract_digests,
            f13_result_digest=f13_digest,
            policy_version=policy.version,
            policy_digest=policy.digest,
            policy_contract=policy.to_dict(),
            resolver_rule=GROUP_RESOLVER_RULE,
            resolver_rule_digest=group_resolver_rule_digest(),
            comparison_rule=COMPARISON_RULE,
            comparison_rule_digest=comparison_rule_digest(),
            candidate_contract_digest=candidate_contract_digest,
        )
        base_identity = {
            "candidate_contract_digest": candidate_contract_digest,
            "base_f14_input_digest": base_input_digest,
            "base_f14_result_digest": base_f14_result_digest,
            "cutoff_digest": cutoff.digest,
            "cutoff_id": cutoff_id,
            "evidence_digest": evidence_digest,
            "f13_result_digest": f13_digest,
            "policy_digest": policy.digest,
            "policy_version": policy.version,
            "profile_digest": profile_digest,
            "t10_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
            "t10_preference_contract_digests": preference_contract_digests,
            "t15_comparison_rule": COMPARISON_RULE,
            "t15_comparison_rule_digest": comparison_rule_digest(),
            "t15_policy_digest": policy.digest,
            "t15_policy_version": policy.version,
            "t15_resolver_rule": GROUP_RESOLVER_RULE,
            "t15_resolver_rule_digest": group_resolver_rule_digest(),
        }
        return (
            expected_input,
            comparison,
            {
                "lineage": base_identity,
                "preference_results": output_rows,
                "outcome": outcome,
                "decision_reason": reason,
                "primary_preference_id": primary_id,
                "unresolved_preference_ids": unresolved_ids,
                "fixture_id": base_value.get("fixture_id"),
            },
            base_value,
            policy,
            manifest,
            joint,
        )

    def _result_payload(
        self,
        successor_input: CandidateInputDecisionInput,
        input_digest: str,
        decision: Mapping[str, object],
        comparison: T15ComparisonResult,
    ) -> dict[str, object]:
        lineage = dict(cast(Mapping[str, object], decision["lineage"]))
        lineage.update(
            {
                "comparison_result_digest": successor_input.comparison_result_digest,
                "joint_uncertainty_digest": successor_input.joint_uncertainty_digest,
                "support_manifest_digest": successor_input.support_manifest_digest,
                "t15_comparison_state": comparison.state.value,
                "t15_maximal_set": comparison.maximal_set,
            }
        )
        return {
            "candidate_contract_digest": successor_input.candidate_contract_digest,
            "decision_reason": decision["decision_reason"],
            "fixture_id": decision["fixture_id"],
            "input_bundle_digest": input_digest,
            "lineage": lineage,
            "outcome": decision["outcome"],
            "preference_results": decision["preference_results"],
            "primary_preference_id": decision["primary_preference_id"],
            "schema_version": F14_SUPPORT_SCHEMA_VERSION,
            "status": "RESEARCH_ONLY",
            "unresolved_preference_ids": decision["unresolved_preference_ids"],
        }

    def _safe_preference_support(
        self,
        support: CandidatePreferenceSupport | None,
        *,
        f13_uncertainty: F13UncertaintyIdentity | None,
        f13_result_digest: str,
    ) -> CandidatePreferenceSupport | None:
        if support is None or support.state is not SupportState.SUPPORTED:
            return support
        if not self._protected_sources_available(support.source_artifact_digests):
            return None
        references = tuple(
            reference
            if self._protected_sources_available(reference.source_artifact_digests)
            else replace(reference, state=SupportState.UNKNOWN)
            for reference in support.component_references
        )
        gates: dict[str, Mapping[str, object] | None] = {}
        for gate_name in ("g6", "g7", "g8"):
            gate = getattr(support, gate_name)
            protected_sources_missing = gate is not None and not self._protected_sources_available(
                _artifact_digests(gate)
            )
            invalid_u1 = (
                gate_name == "g6"
                and gate is not None
                and not self._u1_artifact_matches(
                    gate,
                    support,
                    f13_uncertainty=f13_uncertainty,
                    f13_result_digest=f13_result_digest,
                )
            )
            invalid_proof_record = gate is not None and not self._gate_proof_records_match(
                gate_name, gate
            )
            if protected_sources_missing or invalid_u1 or invalid_proof_record:
                gates[gate_name] = {"state": SupportState.UNKNOWN.value}
            else:
                gates[gate_name] = gate
        return replace(
            support,
            component_references=references,
            g6=gates["g6"],
            g7=gates["g7"],
            g8=gates["g8"],
        )

    def _u1_artifact_matches(
        self,
        gate: Mapping[str, object],
        support: CandidatePreferenceSupport,
        *,
        f13_uncertainty: F13UncertaintyIdentity | None,
        f13_result_digest: str,
    ) -> bool:
        if f13_uncertainty is None:
            return False
        u1 = _mapping(gate.get("u1"))
        try:
            artifact_digest = _require_digest(
                u1.get("artifact_digest"), "G6 U1 event artifact digest"
            )
            event_result_digest = _require_digest(
                u1.get("event_result_digest"), "G6 U1 event result digest"
            )
            if (
                type(u1.get("schema_version")) is not int
                or event_result_digest != artifact_digest
                or u1.get("schema_version") != G6_U1_EVENT_SCHEMA_VERSION
            ):
                return False
            content = self._read_exact(artifact_digest, G6_U1_EVENT_RESULT_MEDIA_TYPE)
            record = G6U1EventResult.from_dict(_decode_canonical(content, artifact_digest))
            return (
                record.digest == artifact_digest
                and _bytes(record.to_dict())
                == _bytes({field: u1.get(field) for field in record.to_dict()})
                and record.preference_contract_digest == support.preference_contract_digest
                and record.f13_result_digest == f13_result_digest
                and record.f13_prediction_digest == f13_uncertainty.prediction_digest
                and record.uncertainty_law_digest == f13_uncertainty.uncertainty_law_digest
                and record.source_draws_digest == f13_uncertainty.source_draws_digest
            )
        except F14Error, TypeError, ValueError:
            return False

    def _gate_proof_records_match(self, gate_name: str, gate: Mapping[str, object]) -> bool:
        """Require each accepted G6/G7/G8 claim to name its exact protected proof record."""

        def exact_record(record_value: object, digest_value: object, media_type: str) -> bool:
            if not isinstance(record_value, Mapping):
                return False
            try:
                digest = _require_digest(digest_value, "gate proof artifact digest")
                content = self._read_exact(digest, media_type)
                decoded = _decode_canonical(content, digest)
                return _bytes(record_value) == content and _bytes(decoded) == content
            except F14Error, TypeError, ValueError:
                return False

        if gate_name == "g6":
            u2 = _mapping(gate.get("u2"))
            if u2.get("state") != SupportState.SUPPORTED.value:
                return True
            return exact_record(
                u2.get("validation_record"),
                u2.get("validation_artifact_digest"),
                G6_U2_VALIDATION_MEDIA_TYPE,
            )

        if gate_name == "g7":
            if gate.get("state") != SupportState.SUPPORTED.value:
                return True
            if not exact_record(
                gate.get("evaluation_record"),
                gate.get("evaluation_artifact_digest"),
                G7_EVALUATION_MEDIA_TYPE,
            ):
                return False
            references = gate.get("references")
            if not isinstance(references, (tuple, list)):
                return False
            return all(
                isinstance(reference, Mapping)
                and exact_record(
                    reference.get("reference_record"),
                    reference.get("reference_artifact_digest"),
                    G7_REFERENCE_MEDIA_TYPE,
                )
                for reference in references
            )

        if gate_name != "g8":
            return False
        state = gate.get("state")
        if state == SupportState.EVIDENCED_ABSENCE.value:
            return exact_record(
                gate.get("absence_evidence_record"),
                gate.get("absence_evidence_artifact_digest"),
                G8_ABSENCE_MEDIA_TYPE,
            )
        if state != SupportState.SUPPORTED.value:
            return True
        cases = gate.get("failure_cases")
        if not isinstance(cases, (tuple, list)) or not cases:
            return False
        for case_value in cases:
            if not isinstance(case_value, Mapping):
                return False
            materiality = _mapping(case_value.get("materiality"))
            representation = _mapping(case_value.get("uncertainty_representation"))
            if not exact_record(
                case_value.get("assertion_record"),
                case_value.get("source_assertion_digest"),
                G8_FAILURE_ASSERTION_MEDIA_TYPE,
            ):
                return False
            if not exact_record(
                materiality.get("support_record"),
                materiality.get("support_artifact_digest"),
                G8_MATERIALITY_MEDIA_TYPE,
            ):
                return False
            if representation.get("state") == "REPRESENTED":
                record_digest = representation.get("artifact_digest")
            elif representation.get("state") == "NOT_REPRESENTED":
                record_digest = representation.get("absence_evidence_artifact_digest")
            else:
                return False
            if not exact_record(
                representation.get("support_record"),
                record_digest,
                G8_UNCERTAINTY_REPRESENTATION_MEDIA_TYPE,
            ):
                return False
        return True

    def _protected_sources_available(self, digests: Sequence[str]) -> bool:
        try:
            for digest in digests:
                _require_digest(digest, "protected support source digest")
                metadata = self.store.artifact_metadata(digest)
                if metadata is None or metadata.retention_class != "PROTECTED":
                    return False
                self.artifacts.verify_artifact(digest)
            return True
        except ArtifactError, TypeError, ValueError:
            return False

    def _read_base_decision(self, digest: str) -> dict[str, object]:
        metadata = self.store.artifact_metadata(digest)
        if (
            metadata is None
            or metadata.retention_class != "PROTECTED"
            or metadata.media_type
            not in {
                DECISION_MEDIA_TYPE,
                CAUSAL_DECISION_MEDIA_TYPE,
            }
        ):
            raise F14Error("Missing or wrong protected predecessor F14 result.")
        return _decode_canonical(self.artifacts.read_artifact(digest), digest)

    def _read_base_input(
        self, digest: str, candidate_contract_digest: str | None
    ) -> dict[str, object]:
        metadata = self.store.artifact_metadata(digest)
        expected_media = (
            CAUSAL_DECISION_INPUT_MEDIA_TYPE
            if candidate_contract_digest is not None
            else DECISION_INPUT_MEDIA_TYPE
        )
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            expected_media,
            "PROTECTED",
        ):
            raise F14Error("Missing or wrong protected predecessor F14 input.")
        value = _decode_canonical(self.artifacts.read_artifact(digest), digest)
        if value.get("candidate_contract_digest") != candidate_contract_digest:
            raise F14Error("Predecessor F14 input candidate contract differs from its result.")
        return value

    def _read_exact(self, digest: str, media_type: str) -> bytes:
        _require_digest(digest, "protected artifact digest")
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            media_type,
            "PROTECTED",
        ):
            raise F14Error(f"Missing or wrong protected artifact reference for {media_type}.")
        content = self.artifacts.read_artifact(digest)
        if hashlib.sha256(content).hexdigest() != digest:
            raise F14Error("Protected artifact digest changed during exact replay.")
        return content


def _decode_canonical(content: bytes, digest: str) -> dict[str, object]:
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or _bytes(value) != content:
            raise F14Error("Protected contract is malformed or noncanonical.")
        if hashlib.sha256(content).hexdigest() != digest:
            raise F14Error("Protected contract digest differs from its exact artifact identity.")
        return cast(dict[str, object], value)
    except F14Error:
        raise
    except (TypeError, ValueError) as error:
        raise F14Error("Protected contract is malformed.") from error


def _exact_fields(value: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        raise ValueError(f"{label} fields differ; missing={missing}, extra={extra}.")


def _require_contract_digest(value: object, label: str) -> str:
    if isinstance(value, str) and value.startswith("sha256:"):
        _require_digest(value.removeprefix("sha256:"), label)
        return value
    return _require_digest(value, label)


def _artifact_digests(value: object) -> tuple[str, ...]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name == "artifact_digest" or name.endswith("_artifact_digest"):
                if isinstance(item, str):
                    found.add(item)
            elif name in {
                "source_artifact_digests",
                "support_artifact_digests",
                "supporting_evidence_digests",
            } and isinstance(item, (tuple, list)):
                found.update(str(digest) for digest in item)
            elif name == "source_assertion_digest" and isinstance(item, str):
                found.add(item)
            found.update(_artifact_digests(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(_artifact_digests(item))
    return tuple(sorted(found))


def _mapping_rows(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, list):
        return {}
    rows: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("vetting"), Mapping):
            continue
        preference_id = _mapping(item["vetting"].get("preference")).get("preference_id")
        if isinstance(preference_id, str):
            rows[preference_id] = item
    return rows


def _g05_state(vetting: Mapping[str, object]) -> str:
    gates = vetting.get("gates")
    if not isinstance(gates, list):
        return "UNKNOWN"
    required = {f"G{index}" for index in range(6)}
    observed: dict[str, str] = {}
    for item in gates:
        if not isinstance(item, Mapping):
            continue
        gate_id = item.get("gate_id")
        status = item.get("status")
        if isinstance(gate_id, str) and isinstance(status, str):
            observed[gate_id] = status
    if required - set(observed):
        return "UNKNOWN"
    if any(observed[gate] == "FAIL" for gate in required):
        return "FAIL"
    if all(observed[gate] == "PASS" for gate in required):
        return "PASS"
    return "UNKNOWN"


def _prediction_digest_for_preference(
    preference: BettingPreference, f13_models: Mapping[str, object]
) -> str | None:
    value = _mapping(f13_models.get(_f13_family_key(preference))).get("prediction_digest")
    return value if isinstance(value, str) else None


def _f13_family_key(preference: BettingPreference) -> str:
    family = preference.family.value
    return (
        "FIRST_HALF_GOALS"
        if family == "First-Half Over"
        else "SECOND_HALF_GOALS"
        if family == "Second-Half Over"
        else "CORNERS"
        if family
        in {
            "Corner Match Winner",
            "Full-Match Total Corners Over",
            "Home Team Corners Over",
            "Away Team Corners Over",
        }
        else "FULL_TIME_GOALS"
    )


def _f13_uncertainty_identity(
    preference: BettingPreference, f13_model: Mapping[str, object]
) -> F13UncertaintyIdentity | None:
    results = _mapping(f13_model.get("results"))
    result = _mapping(results.get(_f13_family_key(preference)))
    prediction_digest = result.get("prediction_digest")
    uncertainty = _mapping(result.get("uncertainty"))
    calibrated_uncertainty = _mapping(uncertainty.get("calibrated"))
    parameter = _mapping(_mapping(calibrated_uncertainty.get("components")).get("parameter"))
    source_draws_digest = parameter.get("draws_digest")
    if (
        not isinstance(prediction_digest, str)
        or not calibrated_uncertainty
        or not isinstance(source_draws_digest, str)
    ):
        return None
    try:
        return F13UncertaintyIdentity(
            prediction_digest=prediction_digest,
            uncertainty_law_digest=_digest(calibrated_uncertainty),
            source_draws_digest=source_draws_digest,
        )
    except ValueError:
        return None


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _successor_preference_row(
    preference_id: str,
    base_terminal: str,
    terminal: str,
    gates: Mapping[str, object],
    reasons: Sequence[str],
    vetting: Mapping[str, object],
    component_support: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "base_f14_terminal_result": base_terminal,
        "component_support": dict(component_support or {}),
        "gate_results": dict(gates),
        "preference_id": preference_id,
        "reason_codes": tuple(sorted(set(reasons))),
        "terminal_result": terminal,
        "vetting": dict(vetting),
    }


def _resolved_component_rows(
    values: Mapping[str, ResolvedComponentSupport],
) -> dict[str, object]:
    return {
        component: {
            "ancestors_considered": result.ancestors_considered,
            "fallback_reason": result.fallback_reason,
            "normalizer": result.normalizer.to_dict() if result.normalizer is not None else None,
            "reference_digest": result.reference_digest,
            "state": result.state.value,
        }
        for component, result in sorted(values.items())
    }

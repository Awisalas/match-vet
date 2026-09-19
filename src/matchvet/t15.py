"""T15 frozen-policy preference vetting and ranking.

T15 is the pure Matchweek Vetting seam.  It consumes a frozen T09 Evidence
State, T14 calibrated family predictions, and a caller-supplied frozen policy.
It does not fit models, research evidence, grade matches, read odds, or choose
policy numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fractions import Fraction
from functools import cmp_to_key
from typing import cast

from matchvet.t09 import (
    ResearchStatus,
)
from matchvet.t10 import (
    DEFAULT_PREFERENCE_CATALOG,
    PREFERENCE_CATALOG_DIGEST,
    PREFERENCE_CATALOG_VERSION,
    BettingPreference,
    PreferenceCatalog,
    PreferenceFamily,
)

T15_POLICY_VERSION = "t15-policy-v1"
T15_SCHEMA_VERSION = "t15-vetting-v1"
SELECTION_COMPONENTS: tuple[str, ...] = (
    "conservative_probability",
    "win_lift",
    "loss_risk_improvement",
    "data_quality",
    "uncertainty_quality",
    "model_agreement",
    "adversarial_safety",
    "historical_reliability",
)


class T15Error(Exception):
    """Base class for T15 errors."""


class T15ValidationError(T15Error, ValueError):
    """The T15 input contract is malformed."""


class T15IntegrityError(T15Error):
    """A frozen T15 identity or digest is inconsistent."""


class PolicyValidationError(T15ValidationError):
    """A policy cannot be used for the requested mode."""


class PolicyStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PRODUCTION_PROMOTED = "PRODUCTION_PROMOTED"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"


class CandidateStatus(StrEnum):
    REJECT = "REJECT"
    RESEARCH_CANDIDATE = "RESEARCH CANDIDATE"
    QUALIFIED = "QUALIFIED"
    PRIMARY_RECOMMENDATION = "Primary Recommendation"
    CORRELATED_SECONDARY_FIT = "Correlated Secondary Fit"


class CandidateRole(StrEnum):
    NONE = "NONE"
    RESEARCH_PRIMARY_CANDIDATE = "RESEARCH PRIMARY CANDIDATE"
    RESEARCH_CORRELATED_SECONDARY_CANDIDATE = "RESEARCH CORRELATED SECONDARY CANDIDATE"
    PRIMARY_RECOMMENDATION = "Primary Recommendation"
    CORRELATED_SECONDARY_FIT = "Correlated Secondary Fit"


class MatchDecision(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    RESEARCH_AVOID = "RESEARCH AVOID"
    PLAY = "PLAY"
    AVOID_MATCH = "AVOID MATCH"


class GateId(StrEnum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"


GATE_NAMES: Mapping[GateId, str] = {
    GateId.G0: "supported preference and valid model/distribution",
    GateId.G1: "Research Sufficiency",
    GateId.G2: "Critical Evidence and Data Quality",
    GateId.G3: "historical predictive reliability",
    GateId.G4: "Non-Triviality",
    GateId.G5: "Conservative Probability and LOSS risk",
    GateId.G6: "Probability Uncertainty",
    GateId.G7: "Model Agreement and sensitivity",
    GateId.G8: "evidence-backed adversarial Failure Case",
}


_FORBIDDEN_POLICY_TOKENS = frozenset(
    {
        "bookmaker",
        "bookmaker_odds",
        "odds",
        "implied_probability",
        "price",
        "expected_profit",
        "profit",
        "value",
        "stake",
        "target_volume",
        "volume",
    }
)


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
            raise T15ValidationError("T15 values must be finite.")
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


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _float_mapping(value: object) -> Mapping[str, float]:
    selected = _mapping(value)
    return {
        str(key): float(item)
        for key, item in selected.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def _string_mapping(value: object) -> Mapping[str, str]:
    selected = _mapping(value)
    return {str(key): str(item) for key, item in selected.items()}


def _read(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return cast(object, getattr(value, key, default))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise T15ValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise T15ValidationError(f"{label} must be a finite number.")
    selected = float(value)
    if not math.isfinite(selected):
        raise T15ValidationError(f"{label} must be a finite number.")
    return selected


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _token(value: object) -> str:
    return "_".join(str(value).strip().upper().replace("-", " ").split())


def _value(value: object) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _status_token(value: object) -> str:
    return _token(_value(value))


def _same_family(left: object, right: object) -> bool:
    left_token = _token(left)
    right_token = _token(right)
    if left_token == right_token:
        return True
    return {left_token, right_token} == {"ASIAN_HANDICAP", "ASIAN_HANDICAPS"}


def _tuple_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list, set)):
        return ()
    return tuple(sorted({str(item) for item in value if str(item).strip()}))


def _forbidden_keys(value: object) -> tuple[str, ...]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            token = _token(key)
            if token in _FORBIDDEN_POLICY_TOKENS or any(
                part in token.lower() for part in _FORBIDDEN_POLICY_TOKENS
            ):
                found.add(str(key))
            found.update(_forbidden_keys(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(_forbidden_keys(item))
    return tuple(sorted(found))


def _component_key(value: object) -> str:
    token = _token(value).lower()
    aliases = {
        "c": "conservative_probability",
        "conservative_probability": "conservative_probability",
        "conservative_probability_percentile": "conservative_probability",
        "w": "win_lift",
        "win_lift": "win_lift",
        "conservative_win_lift": "win_lift",
        "l": "loss_risk_improvement",
        "loss_risk": "loss_risk_improvement",
        "loss_risk_improvement": "loss_risk_improvement",
        "q": "data_quality",
        "data_quality": "data_quality",
        "u": "uncertainty_quality",
        "uncertainty": "uncertainty_quality",
        "uncertainty_quality": "uncertainty_quality",
        "m": "model_agreement",
        "model_agreement": "model_agreement",
        "f": "adversarial_safety",
        "failure_safety": "adversarial_safety",
        "adversarial_safety": "adversarial_safety",
        "r": "historical_reliability",
        "historical_reliability": "historical_reliability",
    }
    return aliases.get(token, token)


@dataclass(frozen=True)
class NormalizationSpec:
    """One policy-frozen normalization rule for a strength component."""

    method: str
    reference: tuple[float, ...] = ()
    lower: float | None = None
    upper: float | None = None
    direction: str = "higher"

    def __post_init__(self) -> None:
        method = _token(self.method).lower()
        if method not in {"identity", "percentile", "min_max", "inverse_min_max"}:
            raise T15ValidationError(f"Unsupported T15 normalization method {self.method!r}.")
        if self.direction not in {"higher", "lower"}:
            raise T15ValidationError("T15 normalization direction must be higher or lower.")
        values = tuple(_finite(item, "T15 normalization reference") for item in self.reference)
        if method == "percentile" and not values:
            raise T15ValidationError("Percentile normalization requires reference values.")
        if method in {"min_max", "inverse_min_max"}:
            if self.lower is None or self.upper is None:
                raise T15ValidationError("Min-max normalization requires lower and upper bounds.")
            lower = _finite(self.lower, "T15 normalization lower bound")
            upper = _finite(self.upper, "T15 normalization upper bound")
            if upper <= lower:
                raise T15ValidationError("T15 normalization upper bound must exceed lower bound.")
            object.__setattr__(self, "lower", lower)
            object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "reference", tuple(sorted(values)))

    @classmethod
    def from_value(cls, value: object) -> NormalizationSpec:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(method=value)
        mapped = _mapping(value)
        if not mapped:
            raise T15ValidationError("A normalization rule must be a string or object.")
        reference = mapped.get("reference", mapped.get("reference_values", ()))
        if not isinstance(reference, (tuple, list)):
            reference = ()
        return cls(
            method=str(mapped.get("method", "")),
            reference=tuple(_finite(item, "T15 normalization reference") for item in reference),
            lower=_optional_float(mapped.get("lower")),
            upper=_optional_float(mapped.get("upper")),
            direction=str(mapped.get("direction", "higher")).lower(),
        )

    def apply(self, value: float) -> float:
        selected = _finite(value, "T15 component value")
        if self.method == "identity":
            normalized = selected
        elif self.method == "percentile":
            less = sum(reference < selected for reference in self.reference)
            equal = sum(reference == selected for reference in self.reference)
            normalized = (less + 0.5 * equal) / len(self.reference)
        else:
            assert self.lower is not None and self.upper is not None
            normalized = (selected - self.lower) / (self.upper - self.lower)
            if self.method == "inverse_min_max":
                normalized = 1.0 - normalized
        if self.direction == "lower":
            normalized = 1.0 - normalized
        if not 0.0 <= normalized <= 1.0:
            raise T15ValidationError(
                f"T15 normalization produced {normalized!r}; policy must define "
                "clipping explicitly."
            )
        return normalized

    def to_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction,
            "lower": self.lower,
            "method": self.method,
            "reference": self.reference,
            "upper": self.upper,
        }


@dataclass(frozen=True)
class TransformSpec:
    """One policy-frozen monotonic transform."""

    kind: str
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _token(self.kind).lower()
        if kind not in {"identity", "linear", "power", "clip", "one_minus"}:
            raise T15ValidationError(f"Unsupported T15 transform {self.kind!r}.")
        params = {
            str(key): _finite(item, "T15 transform parameter")
            for key, item in self.parameters.items()
        }
        if kind == "linear" and params.get("slope", 0.0) < 0.0:
            raise T15ValidationError("T15 Selection Strength transforms must be monotonic.")
        if kind == "linear" and not {"slope", "intercept"} <= set(params):
            raise T15ValidationError("Linear T15 transforms require slope and intercept.")
        if kind == "power" and "exponent" not in params:
            raise T15ValidationError("Power T15 transforms require an exponent.")
        if kind == "power" and params.get("exponent", 0.0) <= 0.0:
            raise T15ValidationError("T15 power transform exponent must be positive.")
        if kind == "clip" and not {"lower", "upper"} <= set(params):
            raise T15ValidationError("Clip T15 transforms require lower and upper bounds.")
        if kind == "clip" and params.get("upper", 1.0) < params.get("lower", 0.0):
            raise T15ValidationError("T15 clip transform bounds are invalid.")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "parameters", dict(sorted(params.items())))

    @classmethod
    def from_value(cls, value: object) -> TransformSpec:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(kind=value)
        mapped = _mapping(value)
        if not mapped:
            raise T15ValidationError("A transform must be a string or object.")
        raw_parameters = mapped.get("parameters", {})
        if not isinstance(raw_parameters, Mapping):
            raw_parameters = {
                str(key): item
                for key, item in mapped.items()
                if str(key) not in {"kind", "transform"}
            }
        return cls(
            kind=str(mapped.get("kind", mapped.get("transform", ""))),
            parameters={
                str(key): _finite(item, "T15 transform parameter")
                for key, item in raw_parameters.items()
            },
        )

    def apply(self, value: float) -> float:
        selected = _finite(value, "T15 component value")
        if self.kind == "identity":
            transformed = selected
        elif self.kind == "linear":
            transformed = selected * self.parameters.get("slope", 0.0) + self.parameters.get(
                "intercept", 0.0
            )
        elif self.kind == "power":
            transformed = selected ** self.parameters.get("exponent", 1.0)
        elif self.kind == "clip":
            transformed = max(
                self.parameters.get("lower", 0.0),
                min(self.parameters.get("upper", 1.0), selected),
            )
        else:
            transformed = 1.0 - selected
        if not 0.0 <= transformed <= 1.0:
            raise T15ValidationError(
                f"T15 transform produced {transformed!r}; policy must define a bounded transform."
            )
        return transformed

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class SelectionStrengthConfig:
    """Versioned weights, transforms, and normalization references from #13."""

    weights: Mapping[str, float]
    transforms: Mapping[str, TransformSpec | Mapping[str, object] | str]
    normalizers: Mapping[str, NormalizationSpec | Mapping[str, object] | str]
    version: str = ""

    def __post_init__(self) -> None:
        version = _text(self.version, "Selection Strength version")
        weights = {
            _component_key(key): _finite(value, "Selection Strength weight")
            for key, value in self.weights.items()
        }
        if set(weights) != set(SELECTION_COMPONENTS):
            raise T15ValidationError(
                "Selection Strength weights must name exactly the eight settled components."
            )
        if any(value < 0.0 for value in weights.values()):
            raise T15ValidationError("Selection Strength weights must be non-negative.")
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise T15ValidationError("Selection Strength weights must sum to one.")
        transforms = {
            _component_key(key): TransformSpec.from_value(value)
            for key, value in self.transforms.items()
        }
        normalizers = {
            _component_key(key): NormalizationSpec.from_value(value)
            for key, value in self.normalizers.items()
        }
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "weights", dict(sorted(weights.items())))
        object.__setattr__(self, "transforms", dict(sorted(transforms.items())))
        object.__setattr__(self, "normalizers", dict(sorted(normalizers.items())))

    def to_dict(self) -> dict[str, object]:
        normalizers = cast(Mapping[str, NormalizationSpec], self.normalizers)
        transforms = cast(Mapping[str, TransformSpec], self.transforms)
        return {
            "normalizers": {key: value.to_dict() for key, value in normalizers.items()},
            "transforms": {key: value.to_dict() for key, value in transforms.items()},
            "version": self.version,
            "weights": dict(self.weights),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PolicyVersion:
    """An immutable Selection Policy Version.

    Empty thresholds and no strength configuration are valid for a research
    artifact.  They are unresolved inputs, not defaults.  Production
    validation rejects them.
    """

    version: str
    status: PolicyStatus | str = PolicyStatus.RESEARCH_ONLY
    thresholds: Mapping[str, object] = field(default_factory=dict)
    selection_strength: SelectionStrengthConfig | None = None
    correlation_groups: Mapping[str, str] = field(default_factory=dict)
    user_preference_order: tuple[str, ...] = ()
    dependencies: Mapping[str, str] = field(default_factory=dict)
    promotion_evidence: Mapping[str, object] = field(default_factory=dict)
    catalog_version: str = PREFERENCE_CATALOG_VERSION
    catalog_digest: str = PREFERENCE_CATALOG_DIGEST

    def __post_init__(self) -> None:
        version = _text(self.version, "Policy Version")
        try:
            status = (
                self.status
                if isinstance(self.status, PolicyStatus)
                else PolicyStatus(str(self.status))
            )
        except ValueError as error:
            raise PolicyValidationError(
                f"Unsupported Selection Policy status {self.status!r}."
            ) from error
        forbidden = _forbidden_keys(self.thresholds)
        forbidden += _forbidden_keys(self.dependencies)
        forbidden += _forbidden_keys(self.promotion_evidence)
        if forbidden:
            raise PolicyValidationError(
                "Bookmaker odds, value, profit, stake, and volume cannot be policy inputs: "
                + ", ".join(forbidden)
            )
        if self.catalog_version != PREFERENCE_CATALOG_VERSION:
            raise PolicyValidationError(
                "T15 requires the immutable T10 preference catalog version."
            )
        if self.catalog_digest != PREFERENCE_CATALOG_DIGEST:
            raise PolicyValidationError("T15 requires the immutable T10 preference catalog digest.")
        groups = {
            str(key): _text(value, "Correlation group")
            for key, value in self.correlation_groups.items()
        }
        order = tuple(str(item) for item in self.user_preference_order)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "thresholds", dict(self.thresholds))
        object.__setattr__(self, "correlation_groups", dict(sorted(groups.items())))
        object.__setattr__(self, "user_preference_order", order)
        object.__setattr__(self, "dependencies", dict(sorted(self.dependencies.items())))
        object.__setattr__(self, "promotion_evidence", dict(self.promotion_evidence))

    @property
    def mode(self) -> PolicyStatus:
        return cast(PolicyStatus, self.status)

    @property
    def production_promoted(self) -> bool:
        return self.mode is PolicyStatus.PRODUCTION_PROMOTED

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "catalog_digest": self.catalog_digest,
            "catalog_version": self.catalog_version,
            "correlation_groups": dict(self.correlation_groups),
            "dependencies": dict(self.dependencies),
            "promotion_evidence": dict(self.promotion_evidence),
            "selection_strength": (
                self.selection_strength.to_dict() if self.selection_strength is not None else None
            ),
            "status": self.mode.value,
            "thresholds": dict(self.thresholds),
            "user_preference_order": self.user_preference_order,
            "version": self.version,
        }
        if include_digest:
            payload["policy_digest"] = self.digest
        return payload

    def validate_for_production(
        self, catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG
    ) -> None:
        if self.mode is not PolicyStatus.PRODUCTION_PROMOTED:
            raise PolicyValidationError("A RESEARCH_ONLY policy cannot emit production decisions.")
        if catalog.version != self.catalog_version or catalog.digest != self.catalog_digest:
            raise PolicyValidationError("Policy and Preference Set identities do not match.")
        if self.promotion_evidence.get("explicitly_promoted") is not True:
            raise PolicyValidationError(
                "Production output requires an explicitly Production Promoted Policy Version."
            )
        required = {
            "data_quality_min",
            "historical_reliability_min",
            "non_triviality_baseline_win_max",
            "non_triviality_min_lift",
            "conservative_probability_min",
            "loss_risk_max",
            "uncertainty_width_max",
            "uncertainty_tail_risk_max",
            "model_agreement_min",
            "model_sensitivity_max",
            "statistical_tie_tolerance",
        }
        missing = sorted(
            key
            for key in required
            if not any(
                _threshold_lookup(self.thresholds, key, preference) is not None
                for preference in catalog
            )
        )
        if missing:
            raise PolicyValidationError(
                "Production Policy Version is missing frozen thresholds: " + ", ".join(missing)
            )
        if self.selection_strength is None:
            raise PolicyValidationError(
                "Production Policy Version requires Selection Strength config."
            )
        if set(self.selection_strength.transforms) != set(SELECTION_COMPONENTS):
            raise PolicyValidationError("Production Selection Strength requires every transform.")
        if set(self.selection_strength.normalizers) != set(SELECTION_COMPONENTS):
            raise PolicyValidationError("Production Selection Strength requires every normalizer.")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PolicyVersion:
        raw_strength = value.get("selection_strength")
        strength: SelectionStrengthConfig | None = None
        if isinstance(raw_strength, SelectionStrengthConfig):
            strength = raw_strength
        elif isinstance(raw_strength, Mapping):
            strength = SelectionStrengthConfig(
                weights=_float_mapping(raw_strength.get("weights")),
                transforms=cast(
                    Mapping[str, TransformSpec | Mapping[str, object] | str],
                    _mapping(raw_strength.get("transforms")),
                ),
                normalizers=cast(
                    Mapping[str, NormalizationSpec | Mapping[str, object] | str],
                    _mapping(raw_strength.get("normalizers")),
                ),
                version=str(raw_strength.get("version", "")),
            )
        return cls(
            version=str(value.get("version", "")),
            status=str(value.get("status", PolicyStatus.RESEARCH_ONLY.value)),
            thresholds=_mapping(value.get("thresholds", value.get("gate_thresholds", {}))),
            selection_strength=strength,
            correlation_groups=_string_mapping(value.get("correlation_groups", {})),
            user_preference_order=_tuple_strings(value.get("user_preference_order", ())),
            dependencies=_string_mapping(value.get("dependencies", {})),
            promotion_evidence=_mapping(value.get("promotion_evidence", {})),
            catalog_version=str(value.get("catalog_version", PREFERENCE_CATALOG_VERSION)),
            catalog_digest=str(value.get("catalog_digest", PREFERENCE_CATALOG_DIGEST)),
        )


@dataclass(frozen=True)
class DataQualityMetrics:
    overall: float | None = None
    dimensions: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        selected = None if self.overall is None else _finite(self.overall, "Data Quality")
        if selected is not None and not 0.0 <= selected <= 1.0:
            raise T15ValidationError("Data Quality must be between zero and one.")
        dimensions = {
            str(key): _finite(value, "Data Quality dimension")
            for key, value in self.dimensions.items()
        }
        if any(not 0.0 <= value <= 1.0 for value in dimensions.values()):
            raise T15ValidationError("Data Quality dimensions must be between zero and one.")
        object.__setattr__(self, "overall", selected)
        object.__setattr__(self, "dimensions", dict(sorted(dimensions.items())))

    @classmethod
    def from_value(cls, value: object) -> DataQualityMetrics | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return cls(overall=float(value))
        mapped = _mapping(value)
        if not mapped:
            return None
        dimensions = mapped.get("dimensions", mapped.get("dimension_scores", {}))
        return cls(
            overall=_optional_float(mapped.get("overall", mapped.get("score"))),
            dimensions={
                str(key): float(item)
                for key, item in _mapping(dimensions).items()
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            },
        )


@dataclass(frozen=True)
class HistoricalBaseline:
    win_probability: float
    loss_probability: float
    push_probability: float = 0.0
    hierarchical_key: str = ""
    structural_trivial: bool | None = None
    match_specific_lift: float | None = None
    effective_sample: float | None = None
    uncertainty: float | None = None
    contract: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            _finite(self.win_probability, "Historical Baseline WIN"),
            _finite(self.loss_probability, "Historical Baseline LOSS"),
            _finite(self.push_probability, "Historical Baseline PUSH"),
        )
        if any(value < 0.0 or value > 1.0 for value in values) or not math.isclose(
            sum(values), 1.0, abs_tol=1e-8
        ):
            raise T15ValidationError(
                "Historical Baseline settlement probabilities must sum to one."
            )
        if not _text(self.hierarchical_key, "Historical Baseline hierarchical key"):
            raise T15ValidationError(
                "Historical Baseline must identify its hierarchical reference."
            )
        for name in ("match_specific_lift", "effective_sample", "uncertainty"):
            selected = _optional_float(getattr(self, name))
            if selected is not None and selected < 0.0:
                raise T15ValidationError(f"Historical Baseline {name} cannot be negative.")
            object.__setattr__(self, name, selected)
        object.__setattr__(self, "contract", dict(self.contract))
        object.__setattr__(self, "win_probability", values[0])
        object.__setattr__(self, "loss_probability", values[1])
        object.__setattr__(self, "push_probability", values[2])

    @classmethod
    def from_value(cls, value: object) -> HistoricalBaseline | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        mapped = _mapping(value)
        if not mapped:
            return None
        win = mapped.get("win_probability", mapped.get("win"))
        loss = mapped.get("loss_probability", mapped.get("loss"))
        push = mapped.get("push_probability", mapped.get("push", 0.0))
        if win is None or loss is None:
            return None
        try:
            return cls(
                win_probability=_finite(win, "Historical Baseline WIN"),
                loss_probability=_finite(loss, "Historical Baseline LOSS"),
                push_probability=_finite(push, "Historical Baseline PUSH"),
                hierarchical_key=str(
                    mapped.get("hierarchical_key", mapped.get("reference_key", ""))
                ),
                structural_trivial=_optional_bool(
                    mapped.get("structural_trivial", mapped.get("is_trivial"))
                ),
                match_specific_lift=_optional_float(
                    mapped.get("match_specific_lift", mapped.get("lift"))
                ),
                effective_sample=_optional_float(mapped.get("effective_sample")),
                uncertainty=_optional_float(mapped.get("uncertainty")),
                contract=dict(
                    _mapping(mapped.get("contract", mapped.get("preference_contract", {})))
                ),
            )
        except T15ValidationError:
            return None


@dataclass(frozen=True)
class ReliabilityMetrics:
    overall: float | None = None
    dimensions: Mapping[str, float] = field(default_factory=dict)
    effective_sample: float | None = None

    def __post_init__(self) -> None:
        selected = None if self.overall is None else _finite(self.overall, "Historical reliability")
        if selected is not None and not 0.0 <= selected <= 1.0:
            raise T15ValidationError("Historical reliability must be between zero and one.")
        dimensions = {
            str(key): _finite(value, "Reliability dimension")
            for key, value in self.dimensions.items()
        }
        if any(not 0.0 <= value <= 1.0 for value in dimensions.values()):
            raise T15ValidationError("Reliability dimensions must be between zero and one.")
        sample = _optional_float(self.effective_sample)
        if sample is not None and sample < 0.0:
            raise T15ValidationError("Historical effective sample cannot be negative.")
        object.__setattr__(self, "overall", selected)
        object.__setattr__(self, "dimensions", dict(sorted(dimensions.items())))
        object.__setattr__(self, "effective_sample", sample)

    @classmethod
    def from_value(cls, value: object) -> ReliabilityMetrics | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return cls(overall=float(value))
        mapped = _mapping(value)
        if not mapped:
            return None
        dims = mapped.get("dimensions", mapped.get("dimension_scores", {}))
        return cls(
            overall=_optional_float(mapped.get("overall", mapped.get("score"))),
            dimensions={
                str(key): float(item)
                for key, item in _mapping(dims).items()
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            },
            effective_sample=_optional_float(mapped.get("effective_sample")),
        )


@dataclass(frozen=True)
class AdversarialReview:
    failure_case: str
    supporting_evidence_ids: tuple[str, ...]
    materiality: float
    represented_in_uncertainty: bool
    veto: bool = False
    complete: bool = True
    downgrade: bool = False

    def __post_init__(self) -> None:
        _text(self.failure_case, "Adversarial Failure Case")
        materiality = _finite(self.materiality, "Failure Case materiality")
        if not 0.0 <= materiality <= 1.0:
            raise T15ValidationError("Failure Case materiality must be between zero and one.")
        object.__setattr__(
            self, "supporting_evidence_ids", _tuple_strings(self.supporting_evidence_ids)
        )
        object.__setattr__(self, "materiality", materiality)

    @classmethod
    def from_value(cls, value: object) -> AdversarialReview | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        mapped = _mapping(value)
        if not mapped:
            return None
        evidence = mapped.get(
            "supporting_evidence_ids",
            mapped.get("evidence_ids", mapped.get("supporting_evidence", ())),
        )
        try:
            return cls(
                failure_case=str(mapped.get("failure_case", mapped.get("description", ""))),
                supporting_evidence_ids=_tuple_strings(evidence),
                materiality=_finite(mapped.get("materiality", 0.0), "Failure Case materiality"),
                represented_in_uncertainty=bool(
                    mapped.get("represented_in_uncertainty", mapped.get("represented", False))
                ),
                veto=bool(mapped.get("veto", mapped.get("downgrade_to_reject", False))),
                complete=bool(mapped.get("complete", True)),
                downgrade=bool(mapped.get("downgrade", False)),
            )
        except TypeError, T15ValidationError:
            return None

    @property
    def evidence_backed(self) -> bool:
        return bool(self.supporting_evidence_ids)

    @property
    def safety(self) -> float:
        return max(0.0, min(1.0, 1.0 - self.materiality))

    @property
    def outcome(self) -> str:
        if self.veto:
            return "VETO"
        if self.downgrade:
            return "DOWNGRADE"
        return "PASS"


@dataclass(frozen=True)
class CandidateInput:
    """Per-preference material not stored inside T09/T14."""

    data_quality: DataQualityMetrics | Mapping[str, object] | float | None = None
    baseline: HistoricalBaseline | Mapping[str, object] | None = None
    historical_reliability: ReliabilityMetrics | Mapping[str, object] | float | None = None
    adversarial_review: AdversarialReview | Mapping[str, object] | None = None
    selection_components: Mapping[str, float] = field(default_factory=dict)
    correlation_group: str | None = None
    uncertainty_width: float | None = None
    uncertainty_tail_risk: float | None = None
    uncertainty_reliable: bool | None = None
    uncertainty_quality: float | None = None
    model_agreement: float | None = None
    model_sensitivity: float | None = None
    adversarial_safety: float | None = None
    failure_risk: float | None = None
    non_trivial: bool | None = None
    supporting_case: str | None = None
    explanatory: bool = True
    paired_strength_uncertainty: float | None = None
    selection_strength_interval: tuple[float, float] | None = None
    user_order: int | None = None

    def normalized(self) -> CandidateInput:
        quality = DataQualityMetrics.from_value(self.data_quality)
        baseline = HistoricalBaseline.from_value(self.baseline)
        reliability = ReliabilityMetrics.from_value(self.historical_reliability)
        review = AdversarialReview.from_value(self.adversarial_review)
        components = {
            _component_key(key): _finite(value, "Selection Strength component")
            for key, value in self.selection_components.items()
        }
        for value in components.values():
            if not 0.0 <= value <= 1.0:
                raise T15ValidationError(
                    "Selection Strength component overrides must be normalized."
                )
        bounded_fields = (
            "uncertainty_tail_risk",
            "uncertainty_quality",
            "model_agreement",
            "model_sensitivity",
            "adversarial_safety",
            "failure_risk",
        )
        for name in bounded_fields:
            selected = _optional_float(getattr(self, name))
            if selected is not None and not 0.0 <= selected <= 1.0:
                raise T15ValidationError(f"{name} must be between zero and one.")
        width = _optional_float(self.uncertainty_width)
        if width is not None and not 0.0 <= width <= 1.0:
            raise T15ValidationError("uncertainty_width must be between zero and one.")
        paired_uncertainty = _optional_float(self.paired_strength_uncertainty)
        if paired_uncertainty is not None and not 0.0 <= paired_uncertainty <= 1.0:
            raise T15ValidationError("paired_strength_uncertainty must be between zero and one.")
        interval = self.selection_strength_interval
        if interval is not None:
            if len(interval) != 2:
                raise T15ValidationError("Selection Strength intervals require two bounds.")
            lower = _finite(interval[0], "Selection Strength interval")
            upper = _finite(interval[1], "Selection Strength interval")
            if lower < 0.0 or upper > 1.0 or upper < lower:
                raise T15ValidationError("Selection Strength interval bounds are reversed.")
            interval = (lower, upper)
        return replace(
            self,
            data_quality=quality,
            baseline=baseline,
            historical_reliability=reliability,
            adversarial_review=review,
            selection_components=components,
            correlation_group=(self.correlation_group.strip() if self.correlation_group else None),
            uncertainty_width=_optional_float(self.uncertainty_width),
            uncertainty_tail_risk=_optional_float(self.uncertainty_tail_risk),
            uncertainty_quality=_optional_float(self.uncertainty_quality),
            model_agreement=_optional_float(self.model_agreement),
            model_sensitivity=_optional_float(self.model_sensitivity),
            adversarial_safety=_optional_float(self.adversarial_safety),
            failure_risk=_optional_float(self.failure_risk),
            selection_strength_interval=interval,
        )

    @classmethod
    def from_value(cls, value: object) -> CandidateInput:
        if isinstance(value, cls):
            return value.normalized()
        mapped = _mapping(value)
        if not mapped:
            return cls().normalized()
        components = mapped.get("selection_components", mapped.get("components", {}))
        interval_value = mapped.get("selection_strength_interval", mapped.get("strength_interval"))
        interval: tuple[float, float] | None = None
        if isinstance(interval_value, (tuple, list)) and len(interval_value) == 2:
            interval = (float(interval_value[0]), float(interval_value[1]))
        return cls(
            data_quality=cast(
                DataQualityMetrics | Mapping[str, object] | float | None,
                mapped.get("data_quality", mapped.get("overall_data_quality")),
            ),
            baseline=cast(
                HistoricalBaseline | Mapping[str, object] | None,
                mapped.get("baseline", mapped.get("historical_baseline")),
            ),
            historical_reliability=cast(
                ReliabilityMetrics | Mapping[str, object] | float | None,
                mapped.get("historical_reliability", mapped.get("reliability")),
            ),
            adversarial_review=cast(
                AdversarialReview | Mapping[str, object] | None,
                mapped.get("adversarial_review", mapped.get("failure_case")),
            ),
            selection_components=_float_mapping(components),
            correlation_group=(
                str(mapped.get("correlation_group", mapped.get("correlation_key")))
                if mapped.get("correlation_group", mapped.get("correlation_key")) is not None
                else None
            ),
            uncertainty_width=_optional_float(mapped.get("uncertainty_width")),
            uncertainty_tail_risk=_optional_float(
                mapped.get("uncertainty_tail_risk", mapped.get("tail_risk"))
            ),
            uncertainty_reliable=_optional_bool(
                mapped.get("uncertainty_reliable", mapped.get("uncertainty_validated"))
            ),
            uncertainty_quality=_optional_float(mapped.get("uncertainty_quality")),
            model_agreement=_optional_float(mapped.get("model_agreement")),
            model_sensitivity=_optional_float(mapped.get("model_sensitivity")),
            adversarial_safety=_optional_float(mapped.get("adversarial_safety")),
            failure_risk=_optional_float(mapped.get("failure_risk")),
            non_trivial=_optional_bool(mapped.get("non_trivial", mapped.get("non_triviality"))),
            supporting_case=(
                str(mapped.get("supporting_case"))
                if mapped.get("supporting_case") is not None
                else None
            ),
            explanatory=bool(mapped.get("explanatory", True)),
            paired_strength_uncertainty=_optional_float(
                mapped.get("paired_strength_uncertainty", mapped.get("strength_uncertainty"))
            ),
            selection_strength_interval=interval,
            user_order=(
                int(cast(int, mapped["user_order"]))
                if isinstance(mapped.get("user_order"), int)
                and not isinstance(mapped.get("user_order"), bool)
                else None
            ),
        ).normalized()


@dataclass(frozen=True)
class GateResult:
    gate_id: GateId
    name: str
    status: GateStatus
    reason_codes: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status is GateStatus.FAIL

    def to_dict(self) -> dict[str, object]:
        return {
            "details": dict(self.details),
            "gate_id": self.gate_id.value,
            "name": self.name,
            "passed": self.passed,
            "reason_codes": self.reason_codes,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class _PredictionView:
    raw: object
    status: str
    family: str | None
    target_fixture_id: str | None
    matchweek_id: str | None
    model_version: str | None
    model_digest: str | None
    calibration_version: str | None
    prediction_digest: str | None
    settlements: Mapping[str, object]
    estimated: Mapping[str, object]
    conservative: Mapping[str, object]
    loss_upper: Mapping[str, object]
    intervals: Mapping[str, object]
    uncertainty: Mapping[str, object]
    model_agreement: float | None
    reference_sensitivity: Mapping[str, object]


def _map_field(value: object, key: str) -> Mapping[str, object]:
    selected = _read(value, key, {})
    mapped = _mapping(selected)
    if mapped:
        return mapped
    to_dict = getattr(selected, "to_dict", None)
    if callable(to_dict):
        return _mapping(to_dict())
    return {}


def _prediction_view(value: object, *, preference_id: str | None = None) -> _PredictionView:
    if isinstance(value, _PredictionView):
        return value
    if (
        preference_id is not None
        and isinstance(value, Mapping)
        and not any(
            key in value
            for key in (
                "settlement_distributions",
                "status",
                "model_version",
                "model_digest",
            )
        )
    ):
        value = {
            "status": "AVAILABLE",
            "settlement_distributions": {preference_id: value},
        }
    reference_sensitivity = _map_field(value, "reference_sensitivity")
    model_agreement = _optional_float(_read(value, "model_agreement"))
    if model_agreement is None:
        model_agreement = _optional_float(reference_sensitivity.get("agreement"))
    return _PredictionView(
        raw=value,
        status=_status_token(_read(value, "status", "UNKNOWN")),
        family=(str(_read(value, "family")) if _read(value, "family") is not None else None),
        target_fixture_id=(
            str(_read(value, "target_fixture_id"))
            if _read(value, "target_fixture_id") is not None
            else None
        ),
        matchweek_id=(
            str(_read(value, "matchweek_id")) if _read(value, "matchweek_id") is not None else None
        ),
        model_version=(
            str(_read(value, "model_version"))
            if _read(value, "model_version") is not None
            else None
        ),
        model_digest=(
            str(_read(value, "model_digest")) if _read(value, "model_digest") is not None else None
        ),
        calibration_version=(
            str(_read(value, "calibration_version"))
            if _read(value, "calibration_version") is not None
            else None
        ),
        prediction_digest=(
            str(_read(value, "prediction_digest", _read(value, "digest")))
            if _read(value, "prediction_digest", _read(value, "digest")) is not None
            else None
        ),
        settlements=_map_field(value, "settlement_distributions"),
        estimated=_map_field(value, "estimated_probabilities"),
        conservative=_map_field(value, "conservative_probabilities"),
        loss_upper=_map_field(value, "loss_probability_upper"),
        intervals=_map_field(value, "probability_intervals"),
        uncertainty=_map_field(value, "uncertainty"),
        model_agreement=model_agreement,
        reference_sensitivity=reference_sensitivity,
    )


def _family_model_key(preference: BettingPreference) -> str:
    family = preference.family
    if family in {
        PreferenceFamily.FIRST_HALF_OVER,
    }:
        return "FIRST_HALF_GOALS"
    if family in {PreferenceFamily.SECOND_HALF_OVER}:
        return "SECOND_HALF_GOALS"
    if family in {
        PreferenceFamily.CORNER_WINNER,
        PreferenceFamily.TOTAL_CORNERS_OVER,
        PreferenceFamily.HOME_CORNERS_OVER,
        PreferenceFamily.AWAY_CORNERS_OVER,
    }:
        return "CORNERS"
    return "FULL_TIME_GOALS"


def _prediction_for(predictions: object, preference: BettingPreference) -> _PredictionView | None:
    if predictions is None:
        return None
    if not isinstance(predictions, Mapping):
        return _prediction_view(predictions)
    direct = predictions.get(preference.preference_id)
    if direct is not None:
        return _prediction_view(direct, preference_id=preference.preference_id)
    family_key = _family_model_key(preference)
    aliases = {
        family_key,
        family_key.lower(),
        family_key.replace("_", "-"),
        family_key.replace("_", " "),
    }
    for key, value in predictions.items():
        if _token(key) in {_token(alias) for alias in aliases}:
            return _prediction_view(value)
    if "settlement_distributions" in predictions or "status" in predictions:
        return _prediction_view(predictions)
    return None


def _probability(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        names = {
            "WIN": ("WIN", "win", "win_probability"),
            "LOSS": ("LOSS", "loss", "loss_probability"),
            "PUSH": ("PUSH", "push", "push_probability"),
        }
        for key in names[field_name]:
            if key in value:
                selected = _optional_float(value[key])
                return selected
        return None
    aliases = {
        "WIN": ("win", "win_probability"),
        "LOSS": ("loss", "loss_probability"),
        "PUSH": ("push", "push_probability"),
    }
    for key in aliases[field_name]:
        selected = _optional_float(getattr(value, key, None))
        if selected is not None:
            return selected
    return None


def _probability_map_value(
    values: Mapping[str, object], preference_id: str, field: str
) -> float | None:
    selected = values.get(preference_id)
    if selected is None:
        return None
    if isinstance(selected, (int, float)) and not isinstance(selected, bool):
        return _optional_float(selected)
    return _probability(selected, field)


def _interval_width(view: _PredictionView, preference_id: str) -> float | None:
    raw = view.intervals.get(preference_id)
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        selected = raw.get("WIN", raw.get("win"))
    else:
        selected = getattr(raw, "WIN", getattr(raw, "win", None))
    lower = _optional_float(_read(selected, "lower"))
    upper = _optional_float(_read(selected, "upper"))
    if lower is None or upper is None:
        return None
    return upper - lower


def _family_lookup(values: object, family: object) -> object | None:
    selected = _mapping(values)
    for key, value in selected.items():
        if _same_family(key, family):
            return value
    return None


def _state_target(state: object) -> object | None:
    return _read(state, "target")


def _state_integrity(state: object, target: object) -> tuple[bool, tuple[str, ...]]:
    state_digest = _read(state, "state_digest", _read(state, "digest"))
    reasons: list[str] = []
    if not isinstance(state_digest, str) or not state_digest.strip():
        reasons.append("EVIDENCE_STATE_DIGEST_MISSING")
    reported_digest = _read(state, "digest")
    if (
        isinstance(reported_digest, str)
        and isinstance(state_digest, str)
        and reported_digest != state_digest
    ):
        reasons.append("EVIDENCE_STATE_DIGEST_MISMATCH")
    state_id = _read(state, "state_id")
    if state_id is not None and (not isinstance(state_id, str) or not state_id.strip()):
        reasons.append("EVIDENCE_STATE_ID_INVALID")
    if not str(_read(target, "fixture_id", "")).strip():
        reasons.append("EVIDENCE_TARGET_ID_MISSING")
    if not str(_read(target, "matchweek_id", "")).strip():
        reasons.append("EVIDENCE_MATCHWEEK_ID_MISSING")
    return not reasons, tuple(sorted(set(reasons)))


def _state_collection(state: object, *keys: str) -> object:
    for key in keys:
        selected = _read(state, key)
        if selected is not None:
            return selected
    return {}


def _threshold_lookup(
    thresholds: Mapping[str, object], key: str, preference: BettingPreference | None = None
) -> object | None:
    aliases = {
        "data_quality_min": ("data_quality_min", "g2_data_quality_min"),
        "historical_reliability_min": ("historical_reliability_min", "reliability_min"),
        "non_triviality_baseline_win_max": (
            "non_triviality_baseline_win_max",
            "trivial_baseline_win_max",
        ),
        "non_triviality_min_lift": ("non_triviality_min_lift", "match_specific_lift_min"),
        "conservative_probability_min": (
            "conservative_probability_min",
            "conservative_win_probability_min",
        ),
        "loss_risk_max": ("loss_risk_max", "loss_probability_upper_max"),
        "uncertainty_width_max": ("uncertainty_width_max", "probability_uncertainty_width_max"),
        "uncertainty_tail_risk_max": ("uncertainty_tail_risk_max", "tail_risk_max"),
        "model_agreement_min": ("model_agreement_min", "agreement_min"),
        "model_sensitivity_max": ("model_sensitivity_max", "sensitivity_max"),
        "statistical_tie_tolerance": ("statistical_tie_tolerance", "tie_tolerance"),
    }
    value: object | None = None
    for alias in aliases.get(key, (key,)):
        if alias in thresholds:
            value = thresholds[alias]
            break
    if isinstance(value, Mapping) and preference is not None:
        for candidate in (
            preference.preference_id,
            preference.family.value,
            str(preference.family),
            "default",
        ):
            if candidate in value:
                return cast(object, value[candidate])
        return None
    return value


def _threshold_number(
    policy: PolicyVersion,
    key: str,
    preference: BettingPreference,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> float | None:
    raw = _threshold_lookup(policy.thresholds, key, preference)
    selected = _optional_float(raw)
    if selected is None:
        return None
    if lower is not None and selected < lower:
        raise PolicyValidationError(f"Policy threshold {key} is below its allowed range.")
    if upper is not None and selected > upper:
        raise PolicyValidationError(f"Policy threshold {key} is above its allowed range.")
    return selected


def _gate(
    gate_id: GateId,
    passed: bool | None,
    reason_codes: Iterable[str] = (),
    details: Mapping[str, object] | None = None,
) -> GateResult:
    status = (
        GateStatus.UNRESOLVED if passed is None else GateStatus.PASS if passed else GateStatus.FAIL
    )
    return GateResult(
        gate_id=gate_id,
        name=GATE_NAMES[gate_id],
        status=status,
        reason_codes=tuple(sorted(set(reason_codes))),
        details=dict(details or {}),
    )


def _supported_preference(
    preference: BettingPreference, catalog: PreferenceCatalog
) -> tuple[bool, tuple[str, ...]]:
    if preference.preference_id not in {item.preference_id for item in catalog}:
        return False, ("DISABLED_PREFERENCE",)
    label = preference.label.upper()
    if "UNDER" in label or preference.selection.upper() == "UNDER":
        return False, ("BANNED_UNDER_MARKET",)
    if (
        preference.selection.upper() == "OVER"
        and preference.line is not None
        and preference.line == Fraction(1, 2)
    ):
        return False, ("BANNED_OVER_0_5",)
    try:
        canonical = DEFAULT_PREFERENCE_CATALOG.get(preference.preference_id)
    except ValueError:
        return False, ("UNSUPPORTED_PREFERENCE",)
    if preference.to_dict() != canonical.to_dict():
        return False, ("UNSUPPORTED_PREFERENCE_CONTRACT",)
    return True, ()


def _prediction_integrity(
    view: _PredictionView | None,
    preference: BettingPreference,
    target: object,
) -> tuple[bool, tuple[str, ...], dict[str, object]]:
    if view is None:
        return False, ("MODEL_UNAVAILABLE", "MODEL_DISTRIBUTION_MISSING"), {}
    reasons: list[str] = []
    details: dict[str, object] = {
        "status": view.status,
        "family": view.family,
        "model_version": view.model_version,
        "model_digest": view.model_digest,
        "calibration_version": view.calibration_version,
        "prediction_digest": view.prediction_digest,
    }
    if view.status != "AVAILABLE":
        reasons.append("MODEL_UNAVAILABLE")
    if view.family is None:
        reasons.append("MISSING_MODEL_FAMILY")
    expected_family = _family_model_key(preference)
    if view.family is not None and _token(view.family) != _token(expected_family):
        reasons.append("MODEL_FAMILY_MISMATCH")
    target_fixture_id = str(_read(target, "fixture_id", ""))
    matchweek_id = str(_read(target, "matchweek_id", ""))
    if view.target_fixture_id is None:
        reasons.append("MISSING_PREDICTION_TARGET")
    elif view.target_fixture_id != target_fixture_id:
        reasons.append("PREDICTION_TARGET_MISMATCH")
    if view.matchweek_id is None:
        reasons.append("MISSING_PREDICTION_MATCHWEEK")
    elif view.matchweek_id != matchweek_id:
        reasons.append("PREDICTION_MATCHWEEK_MISMATCH")
    for label, value in (
        ("model_version", view.model_version),
        ("model_digest", view.model_digest),
        ("calibration_version", view.calibration_version),
        ("prediction_digest", view.prediction_digest),
    ):
        if value is None or not value.strip():
            reasons.append(f"MISSING_{label.upper()}")
    raw_digest = _read(view.raw, "digest")
    if (
        isinstance(raw_digest, str)
        and view.prediction_digest is not None
        and raw_digest != view.prediction_digest
    ):
        reasons.append("PREDICTION_DIGEST_MISMATCH")
    settlement = view.settlements.get(preference.preference_id)
    win = _probability(settlement, "WIN")
    loss = _probability(settlement, "LOSS")
    push = _probability(settlement, "PUSH")
    if win is None or loss is None or push is None:
        reasons.append("INVALID_SETTLEMENT_DISTRIBUTION")
    else:
        details.update({"win": win, "loss": loss, "push": push})
        if any(value < -1e-9 or value > 1.0 + 1e-9 for value in (win, loss, push)):
            reasons.append("INVALID_SETTLEMENT_DISTRIBUTION")
        if not math.isclose(win + loss + push, 1.0, abs_tol=1e-8):
            reasons.append("SETTLEMENT_DISTRIBUTION_NOT_NORMALIZED")
        expects_push = "PUSH" in {
            str(item.value if isinstance(item, StrEnum) else item)
            for item in preference.possible_results
        }
        if not expects_push and push > 1e-8:
            reasons.append("UNEXPECTED_PUSH_MASS")
        if expects_push and push < -1e-8:
            reasons.append("MISSING_PUSH_TOPOLOGY")
    estimated = _probability_map_value(view.estimated, preference.preference_id, "WIN")
    conservative = _probability_map_value(view.conservative, preference.preference_id, "WIN")
    if estimated is None:
        reasons.append("ESTIMATED_PROBABILITY_MISSING")
    elif not 0.0 <= estimated <= 1.0:
        reasons.append("ESTIMATED_PROBABILITY_INVALID")
    if estimated is not None and win is not None and not math.isclose(estimated, win, abs_tol=1e-7):
        reasons.append("ESTIMATED_PROBABILITY_MISMATCH")
    if conservative is not None:
        if not 0.0 <= conservative <= 1.0:
            reasons.append("CONSERVATIVE_PROBABILITY_INVALID")
        elif win is not None and conservative > win + 1e-8:
            reasons.append("CONSERVATIVE_PROBABILITY_EXCEEDS_ESTIMATE")
    return not reasons, tuple(sorted(set(reasons))), details


def _review_for_gates(candidate: CandidateInput) -> AdversarialReview | None:
    selected = candidate.adversarial_review
    return (
        selected
        if isinstance(selected, AdversarialReview)
        else AdversarialReview.from_value(selected)
    )


def _sufficiency_gate(
    state: object, preference: BettingPreference, review: AdversarialReview | None
) -> GateResult:
    family = preference.family.value
    sufficiency = _family_lookup(
        _state_collection(state, "research_sufficiency", "sufficiency"), family
    )
    if sufficiency is None:
        return _gate(GateId.G1, False, ("RESEARCH_SUFFICIENCY_MISSING",))
    reasons: list[str] = []
    status = _status_token(_read(sufficiency, "status", "UNKNOWN"))
    if status != ResearchStatus.SUFFICIENT.value:
        reasons.append("RESEARCH_SUFFICIENCY_INSUFFICIENT")
    if _read(sufficiency, "mandatory_research_complete") is not True:
        reasons.append("MANDATORY_RESEARCH_INCOMPLETE")
    if _read(sufficiency, "critical_evidence_complete") is not True:
        reasons.append("CRITICAL_EVIDENCE_INCOMPLETE")
    if _read(sufficiency, "diminishing_returns_reached") is not True:
        reasons.append("RESEARCH_DIMINISHING_RETURNS_NOT_REACHED")
    if bool(_read(sufficiency, "model_unavailable", False)):
        reasons.append("MODEL_UNAVAILABLE")
    unresolved_conflicts = _read(sufficiency, "unresolved_material_conflicts", 0)
    if isinstance(unresolved_conflicts, (int, float)) and unresolved_conflicts > 0:
        reasons.append("UNRESOLVED_MATERIAL_CONFLICT")
    if review is None or not review.complete:
        reasons.append("ADVERSARIAL_REVIEW_INCOMPLETE")
    return _gate(
        GateId.G1,
        not reasons,
        reasons,
        {
            "family": family,
            "research_status": status,
            "unresolved_material_conflicts": unresolved_conflicts,
        },
    )


def _data_quality_thresholds(policy: PolicyVersion) -> Mapping[str, object]:
    for key in (
        "data_quality_dimension_min",
        "data_quality_dimensions",
        "g2_data_quality_dimensions",
    ):
        selected = policy.thresholds.get(key)
        if isinstance(selected, Mapping):
            return selected
    return {}


def _g2_gate(
    state: object,
    preference: BettingPreference,
    candidate: CandidateInput,
    policy: PolicyVersion,
) -> GateResult:
    family = preference.family.value
    coverage = _family_lookup(
        _state_collection(state, "critical_evidence_coverage", "critical_coverage"), family
    )
    quality = candidate.data_quality
    reasons: list[str] = []
    if coverage is None:
        reasons.append("CRITICAL_EVIDENCE_COVERAGE_MISSING")
    else:
        if _read(coverage, "complete") is not True:
            reasons.append("CRITICAL_EVIDENCE_MISSING")
        missing = _read(coverage, "missing_requirement_ids", ())
        if missing:
            reasons.append("CRITICAL_EVIDENCE_MISSING")
    unresolved = []
    gaps = _state_collection(state, "gaps", "evidence_gaps")
    if isinstance(gaps, (tuple, list)):
        for gap in gaps:
            if _same_family(_read(gap, "family", ""), family) and bool(
                _read(gap, "blocks_family", False)
            ):
                unresolved.append(str(_read(gap, "gap_id", "")))
    if unresolved:
        reasons.append("CRITICAL_EVIDENCE_GAP")
    conflicts = _state_collection(state, "conflicts", "material_conflicts")
    unresolved_conflicts = (
        tuple(
            str(_read(conflict, "conflict_id", ""))
            for conflict in conflicts
            if bool(_read(conflict, "material", True))
            and _status_token(_read(conflict, "status", "UNRESOLVED")) == "UNRESOLVED"
            and (not _read(conflict, "family") or _same_family(_read(conflict, "family"), family))
        )
        if isinstance(conflicts, (tuple, list))
        else ()
    )
    if unresolved_conflicts:
        reasons.append("UNRESOLVED_MATERIAL_CONFLICT")
    minimum = _threshold_number(policy, "data_quality_min", preference, lower=0.0, upper=1.0)
    if minimum is None:
        reasons.append("POLICY_THRESHOLD_UNRESOLVED")
    elif quality is None or not isinstance(quality, DataQualityMetrics) or quality.overall is None:
        reasons.append("DATA_QUALITY_MISSING")
    elif quality.overall < minimum:
        reasons.append("DATA_QUALITY_BELOW_THRESHOLD")
    dimension_thresholds = _data_quality_thresholds(policy)
    dimensions: dict[str, object] = {}
    for name, raw_threshold in dimension_thresholds.items():
        threshold = _optional_float(raw_threshold)
        selected = (
            quality.dimensions.get(str(name)) if isinstance(quality, DataQualityMetrics) else None
        )
        dimensions[str(name)] = {"observed": selected, "threshold": threshold}
        if threshold is None:
            reasons.append("POLICY_DATA_QUALITY_DIMENSION_UNRESOLVED")
        elif selected is None:
            reasons.append(f"DATA_QUALITY_DIMENSION_MISSING:{name}")
        elif selected < threshold:
            reasons.append(f"DATA_QUALITY_DIMENSION_BELOW_THRESHOLD:{name}")
    return _gate(
        GateId.G2,
        not reasons,
        reasons,
        {
            "coverage_complete": bool(_read(coverage, "complete", False)),
            "data_quality": quality.overall if isinstance(quality, DataQualityMetrics) else None,
            "dimensions": dimensions,
            "unresolved_gap_ids": unresolved,
            "unresolved_conflict_ids": unresolved_conflicts,
        },
    )


def _reliability_dimension_thresholds(policy: PolicyVersion) -> Mapping[str, object]:
    for key in (
        "historical_reliability_dimensions",
        "reliability_dimensions",
        "g3_reliability_dimensions",
    ):
        selected = policy.thresholds.get(key)
        if isinstance(selected, Mapping):
            return selected
    return {}


def _g3_gate(
    preference: BettingPreference,
    candidate: CandidateInput,
    policy: PolicyVersion,
) -> GateResult:
    reliability = candidate.historical_reliability
    minimum = _threshold_number(
        policy, "historical_reliability_min", preference, lower=0.0, upper=1.0
    )
    reasons: list[str] = []
    if minimum is None:
        reasons.append("POLICY_THRESHOLD_UNRESOLVED")
    elif not isinstance(reliability, ReliabilityMetrics) or reliability.overall is None:
        reasons.append("HISTORICAL_RELIABILITY_MISSING")
    elif reliability.overall < minimum:
        reasons.append("HISTORICAL_RELIABILITY_BELOW_THRESHOLD")
    dimension_details: dict[str, object] = {}
    if isinstance(reliability, ReliabilityMetrics):
        for name, raw_threshold in _reliability_dimension_thresholds(policy).items():
            threshold = _optional_float(raw_threshold)
            observed = reliability.dimensions.get(str(name))
            dimension_details[str(name)] = {"observed": observed, "threshold": threshold}
            if threshold is None:
                reasons.append("POLICY_RELIABILITY_DIMENSION_UNRESOLVED")
            elif observed is None:
                reasons.append(f"RELIABILITY_DIMENSION_MISSING:{name}")
            elif observed < threshold:
                reasons.append(f"RELIABILITY_DIMENSION_BELOW_THRESHOLD:{name}")
    effective_sample_threshold = _optional_float(
        _threshold_lookup(policy.thresholds, "minimum_effective_sample", preference)
    )
    if effective_sample_threshold is not None:
        observed_sample = (
            reliability.effective_sample if isinstance(reliability, ReliabilityMetrics) else None
        )
        if observed_sample is None:
            reasons.append("HISTORICAL_EFFECTIVE_SAMPLE_MISSING")
        elif observed_sample < effective_sample_threshold:
            reasons.append("HISTORICAL_EFFECTIVE_SAMPLE_BELOW_THRESHOLD")
    return _gate(
        GateId.G3,
        not reasons,
        reasons,
        {
            "reliability": reliability.overall
            if isinstance(reliability, ReliabilityMetrics)
            else None,
            "dimensions": dimension_details,
            "effective_sample": reliability.effective_sample
            if isinstance(reliability, ReliabilityMetrics)
            else None,
        },
    )


def _g4_gate(
    preference: BettingPreference,
    candidate: CandidateInput,
    policy: PolicyVersion,
) -> GateResult:
    baseline = candidate.baseline
    reasons: list[str] = []
    if not isinstance(baseline, HistoricalBaseline):
        return _gate(GateId.G4, False, ("HISTORICAL_BASELINE_MISSING",))
    expected_contract = preference.to_dict()
    if not baseline.contract:
        reasons.append("HISTORICAL_BASELINE_CONTRACT_MISSING")
    elif _canonical_json(baseline.contract) != _canonical_json(expected_contract):
        reasons.append("HISTORICAL_BASELINE_CONTRACT_MISMATCH")
    explicit = candidate.non_trivial
    if baseline.structural_trivial is True or explicit is False:
        reasons.append("NON_TRIVIALITY_REJECTED")
    baseline_max = _threshold_number(
        policy, "non_triviality_baseline_win_max", preference, lower=0.0, upper=1.0
    )
    lift_min = _threshold_number(
        policy, "non_triviality_min_lift", preference, lower=0.0, upper=1.0
    )
    if explicit is None and baseline.structural_trivial is None:
        if baseline_max is None or lift_min is None:
            reasons.append("POLICY_THRESHOLD_UNRESOLVED")
        else:
            if baseline.win_probability >= baseline_max:
                if baseline.match_specific_lift is None:
                    reasons.append("MATCH_SPECIFIC_LIFT_MISSING")
                elif baseline.match_specific_lift < lift_min:
                    reasons.append("NON_TRIVIALITY_REJECTED")
            elif (
                baseline.match_specific_lift is not None and baseline.match_specific_lift < lift_min
            ):
                reasons.append("MATCH_SPECIFIC_LIFT_BELOW_THRESHOLD")
    elif (
        (explicit is True or baseline.structural_trivial is False)
        and baseline_max is not None
        and baseline.win_probability >= baseline_max
        and baseline.match_specific_lift is not None
        and lift_min is not None
        and baseline.match_specific_lift < lift_min
    ):
        reasons.append("NON_TRIVIALITY_REJECTED")
    return _gate(
        GateId.G4,
        not reasons,
        reasons,
        {
            "hierarchical_baseline": baseline.hierarchical_key,
            "baseline_win": baseline.win_probability,
            "baseline_loss": baseline.loss_probability,
            "baseline_push": baseline.push_probability,
            "structural_trivial": baseline.structural_trivial,
            "match_specific_lift": baseline.match_specific_lift,
        },
    )


def _g5_gate(
    view: _PredictionView | None,
    preference: BettingPreference,
    policy: PolicyVersion,
) -> GateResult:
    minimum = _threshold_number(
        policy, "conservative_probability_min", preference, lower=0.0, upper=1.0
    )
    loss_max = _threshold_number(policy, "loss_risk_max", preference, lower=0.0, upper=1.0)
    reasons: list[str] = []
    details: dict[str, object] = {}
    if minimum is None or loss_max is None:
        reasons.append("POLICY_THRESHOLD_UNRESOLVED")
    if view is None:
        reasons.append("CONSERVATIVE_PROBABILITY_MISSING")
        reasons.append("LOSS_RISK_MISSING")
    else:
        conservative = _probability_map_value(view.conservative, preference.preference_id, "WIN")
        loss_risk = _probability_map_value(view.loss_upper, preference.preference_id, "LOSS")
        details.update({"conservative_probability": conservative, "loss_risk_upper": loss_risk})
        if conservative is None:
            reasons.append("CONSERVATIVE_PROBABILITY_MISSING")
        elif not 0.0 <= conservative <= 1.0:
            reasons.append("CONSERVATIVE_PROBABILITY_INVALID")
        elif minimum is not None and conservative < minimum:
            reasons.append("CONSERVATIVE_PROBABILITY_BELOW_THRESHOLD")
        if loss_risk is None:
            reasons.append("LOSS_RISK_MISSING")
        if loss_risk is not None:
            if not 0.0 <= loss_risk <= 1.0:
                reasons.append("LOSS_RISK_INVALID")
            elif loss_max is not None and loss_risk > loss_max:
                reasons.append("LOSS_RISK_ABOVE_THRESHOLD")
    return _gate(GateId.G5, not reasons, reasons, details)


def _g6_gate(
    view: _PredictionView | None,
    candidate: CandidateInput,
    preference: BettingPreference,
    policy: PolicyVersion,
) -> GateResult:
    width_max = _threshold_number(policy, "uncertainty_width_max", preference, lower=0.0, upper=1.0)
    tail_max = _threshold_number(
        policy, "uncertainty_tail_risk_max", preference, lower=0.0, upper=1.0
    )
    reasons: list[str] = []
    if width_max is None or tail_max is None:
        reasons.append("POLICY_THRESHOLD_UNRESOLVED")
    width = candidate.uncertainty_width
    if width is None and view is not None:
        width = _interval_width(view, preference.preference_id)
    tail = candidate.uncertainty_tail_risk
    if tail is None and view is not None:
        tail = _optional_float(view.uncertainty.get("tail_risk"))
    reliable = candidate.uncertainty_reliable
    if reliable is None and view is not None:
        reliable = _optional_bool(
            view.uncertainty.get(
                "empirical_coverage_validated",
                view.uncertainty.get("uncertainty_reliability_validated"),
            )
        )
    if width is None:
        reasons.append("PROBABILITY_UNCERTAINTY_MISSING")
    elif width < 0.0 or width > 1.0 or (width_max is not None and width > width_max):
        reasons.append("PROBABILITY_UNCERTAINTY_ABOVE_THRESHOLD")
    if tail is None:
        reasons.append("UNCERTAINTY_TAIL_RISK_MISSING")
    elif tail < 0.0 or tail > 1.0 or (tail_max is not None and tail > tail_max):
        reasons.append("UNCERTAINTY_TAIL_RISK_ABOVE_THRESHOLD")
    if reliable is not True:
        reasons.append("UNCERTAINTY_METHOD_NOT_EMPIRICALLY_RELIABLE")
    return _gate(
        GateId.G6,
        not reasons,
        reasons,
        {"width": width, "tail_risk": tail, "empirically_reliable": reliable},
    )


def _sensitivity_value(view: _PredictionView | None, preference_id: str) -> float | None:
    if view is None:
        return None
    selected = view.reference_sensitivity.get("sensitivity_by_preference")
    if isinstance(selected, Mapping):
        direct = _optional_float(selected.get(preference_id))
        if direct is not None:
            return direct
    selected_group = view.reference_sensitivity.get("group_sensitivity")
    if isinstance(selected_group, Mapping):
        values = [
            float(item)
            for item in selected_group.values()
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        if values:
            return max(values)
    return _optional_float(view.reference_sensitivity.get("sensitivity"))


def _g7_gate(
    view: _PredictionView | None,
    candidate: CandidateInput,
    preference: BettingPreference,
    policy: PolicyVersion,
) -> GateResult:
    agreement_min = _threshold_number(
        policy, "model_agreement_min", preference, lower=0.0, upper=1.0
    )
    sensitivity_max = _threshold_number(
        policy, "model_sensitivity_max", preference, lower=0.0, upper=1.0
    )
    reasons: list[str] = []
    if agreement_min is None or sensitivity_max is None:
        reasons.append("POLICY_THRESHOLD_UNRESOLVED")
    agreement = candidate.model_agreement
    if agreement is None and view is not None:
        agreement = view.model_agreement
    sensitivity = candidate.model_sensitivity
    if sensitivity is None:
        sensitivity = _sensitivity_value(view, preference.preference_id)
    if agreement is None:
        reasons.append("MODEL_AGREEMENT_MISSING")
    elif not 0.0 <= agreement <= 1.0:
        reasons.append("MODEL_AGREEMENT_INVALID")
    elif agreement_min is not None and agreement < agreement_min:
        reasons.append("MODEL_AGREEMENT_BELOW_THRESHOLD")
    if sensitivity is None:
        reasons.append("MODEL_SENSITIVITY_MISSING")
    elif not 0.0 <= sensitivity <= 1.0:
        reasons.append("MODEL_SENSITIVITY_INVALID")
    elif sensitivity_max is not None and sensitivity > sensitivity_max:
        reasons.append("MODEL_SENSITIVITY_ABOVE_THRESHOLD")
    return _gate(
        GateId.G7,
        not reasons,
        reasons,
        {"model_agreement": agreement, "model_sensitivity": sensitivity},
    )


def _g8_gate(
    candidate: CandidateInput, policy: PolicyVersion, preference: BettingPreference
) -> GateResult:
    review = _review_for_gates(candidate)
    if review is None:
        return _gate(GateId.G8, False, ("ADVERSARIAL_FAILURE_CASE_MISSING",))
    reasons: list[str] = []
    if not review.complete:
        reasons.append("ADVERSARIAL_REVIEW_INCOMPLETE")
    if not review.evidence_backed:
        reasons.append("ADVERSARIAL_FAILURE_CASE_NOT_EVIDENCE_BACKED")
    if review.veto:
        reasons.append("ADVERSARIAL_VETO")
    unrepresented_max = _threshold_number(
        policy,
        "adversarial_unrepresented_materiality_max",
        preference,
        lower=0.0,
        upper=1.0,
    )
    if (
        unrepresented_max is not None
        and not review.represented_in_uncertainty
        and review.materiality > unrepresented_max
    ):
        reasons.append("ADVERSARIAL_RISK_NOT represented_in_uncertainty".replace(" ", "_"))
    return _gate(
        GateId.G8,
        not reasons,
        reasons,
        {
            "failure_case": review.failure_case,
            "supporting_evidence_ids": review.supporting_evidence_ids,
            "materiality": review.materiality,
            "represented_in_uncertainty": review.represented_in_uncertainty,
            "veto": review.veto,
            "downgrade": review.downgrade,
            "outcome": review.outcome,
        },
    )


@dataclass(frozen=True)
class PreferenceVettingResult:
    target_fixture_id: str
    preference: BettingPreference
    status: CandidateStatus
    role: CandidateRole
    gates: tuple[GateResult, ...]
    rejection_reasons: tuple[str, ...] = ()
    selection_strength_reasons: tuple[str, ...] = ()
    estimated_probability: float | None = None
    conservative_probability: float | None = None
    loss_risk_upper: float | None = None
    push_probability: float | None = None
    uncertainty_width: float | None = None
    data_quality: float | None = None
    model_agreement: float | None = None
    model_sensitivity: float | None = None
    historical_reliability: float | None = None
    failure_risk: float | None = None
    baseline: HistoricalBaseline | None = None
    adversarial_review: AdversarialReview | None = None
    selection_components: Mapping[str, float] = field(default_factory=dict)
    selection_strength: float | None = None
    selection_strength_interval: tuple[float, float] | None = None
    rank: int | None = None
    correlation_group: str | None = None
    supporting_case: str | None = None
    explanatory: bool = True

    @property
    def is_rejected(self) -> bool:
        return self.status is CandidateStatus.REJECT

    @property
    def is_gate_survivor(self) -> bool:
        return all(gate.status is GateStatus.PASS for gate in self.gates)

    @property
    def is_production_output(self) -> bool:
        return self.status in {
            CandidateStatus.PRIMARY_RECOMMENDATION,
            CandidateStatus.CORRELATED_SECONDARY_FIT,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "adversarial_review": (
                {
                    "complete": self.adversarial_review.complete,
                    "failure_case": self.adversarial_review.failure_case,
                    "materiality": self.adversarial_review.materiality,
                    "represented_in_uncertainty": (
                        self.adversarial_review.represented_in_uncertainty
                    ),
                    "supporting_evidence_ids": self.adversarial_review.supporting_evidence_ids,
                    "veto": self.adversarial_review.veto,
                    "downgrade": self.adversarial_review.downgrade,
                    "outcome": self.adversarial_review.outcome,
                }
                if self.adversarial_review is not None
                else None
            ),
            "baseline": (
                {
                    "hierarchical_key": self.baseline.hierarchical_key,
                    "contract": dict(self.baseline.contract),
                    "loss_probability": self.baseline.loss_probability,
                    "match_specific_lift": self.baseline.match_specific_lift,
                    "push_probability": self.baseline.push_probability,
                    "structural_trivial": self.baseline.structural_trivial,
                    "win_probability": self.baseline.win_probability,
                }
                if self.baseline is not None
                else None
            ),
            "conservative_probability": self.conservative_probability,
            "correlation_group": self.correlation_group,
            "data_quality": self.data_quality,
            "estimated_probability": self.estimated_probability,
            "failure_risk": self.failure_risk,
            "gates": [gate.to_dict() for gate in self.gates],
            "historical_reliability": self.historical_reliability,
            "loss_risk_upper": self.loss_risk_upper,
            "model_agreement": self.model_agreement,
            "model_sensitivity": self.model_sensitivity,
            "preference": self.preference.to_dict(),
            "push_probability": self.push_probability,
            "rank": self.rank,
            "rejection_reasons": self.rejection_reasons,
            "role": self.role.value,
            "selection_components": dict(self.selection_components),
            "selection_strength_reasons": self.selection_strength_reasons,
            "selection_strength": self.selection_strength,
            "selection_strength_interval": self.selection_strength_interval,
            "status": self.status.value,
            "supporting_case": self.supporting_case,
            "target_fixture_id": self.target_fixture_id,
            "uncertainty_width": self.uncertainty_width,
            "explanatory": self.explanatory,
        }


@dataclass(frozen=True)
class MatchVettingResult:
    target: object
    policy_version: str
    policy_status: PolicyStatus
    decision: MatchDecision
    preference_results: tuple[PreferenceVettingResult, ...]
    policy_digest: str = ""
    evidence_state_digest: str = ""
    research_primary_candidate: PreferenceVettingResult | None = None
    research_secondary_candidates: tuple[PreferenceVettingResult, ...] = ()
    primary_recommendation: PreferenceVettingResult | None = None
    secondary_fits: tuple[PreferenceVettingResult, ...] = ()
    avoid_reason: str | None = None
    audit_digest: str = ""

    def __post_init__(self) -> None:
        ordered = tuple(self.preference_results)
        if len({item.preference.preference_id for item in ordered}) != len(ordered):
            raise T15IntegrityError("T15 audit contains duplicate preference results.")
        if self.policy_status is PolicyStatus.RESEARCH_ONLY:
            if self.primary_recommendation is not None or self.secondary_fits:
                raise T15IntegrityError(
                    "Research-only audits cannot carry production recommendations."
                )
            if any(item.is_production_output for item in ordered):
                raise T15IntegrityError(
                    "Research-only audits cannot label a preference as production output."
                )
            if self.decision not in {MatchDecision.RESEARCH_ONLY, MatchDecision.RESEARCH_AVOID}:
                raise T15IntegrityError("Research-only audits cannot carry production decisions.")
        else:
            if self.decision is MatchDecision.PLAY and self.primary_recommendation is None:
                raise T15IntegrityError(
                    "Production PLAY requires exactly one Primary Recommendation."
                )
            primary_count = sum(
                item.role is CandidateRole.PRIMARY_RECOMMENDATION for item in ordered
            )
            if self.decision is MatchDecision.PLAY and primary_count != 1:
                raise T15IntegrityError(
                    "Production PLAY requires exactly one Primary Recommendation role."
                )
            if self.decision is not MatchDecision.PLAY and (
                self.primary_recommendation is not None or self.secondary_fits or primary_count
            ):
                raise T15IntegrityError(
                    "Only production PLAY may carry production recommendations."
                )
        expected = _digest(self._payload(include_digest=False))
        if self.audit_digest and self.audit_digest != expected:
            raise T15IntegrityError("T15 match audit digest does not match its content.")
        object.__setattr__(self, "audit_digest", expected)

    @property
    def audit_complete(self) -> bool:
        return len(self.preference_results) == 37

    @property
    def is_research_only(self) -> bool:
        return self.policy_status is PolicyStatus.RESEARCH_ONLY

    @property
    def production_play(self) -> bool:
        return (
            self.decision is MatchDecision.PLAY
            and self.policy_status is PolicyStatus.PRODUCTION_PROMOTED
        )

    @property
    def all_rejected(self) -> bool:
        return not any(item.is_gate_survivor for item in self.preference_results)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "decision": self.decision.value,
            "policy_status": self.policy_status.value,
            "policy_digest": self.policy_digest,
            "policy_version": self.policy_version,
            "preference_results": [item.to_dict() for item in self.preference_results],
            "research_primary_candidate": (
                self.research_primary_candidate.preference.preference_id
                if self.research_primary_candidate is not None
                else None
            ),
            "research_secondary_candidates": tuple(
                item.preference.preference_id for item in self.research_secondary_candidates
            ),
            "primary_recommendation": (
                self.primary_recommendation.preference.preference_id
                if self.primary_recommendation is not None
                else None
            ),
            "secondary_fits": tuple(item.preference.preference_id for item in self.secondary_fits),
            "target": _jsonable(self.target),
            "evidence_state_digest": self.evidence_state_digest,
            "avoid_reason": self.avoid_reason,
        }
        if include_digest:
            payload["audit_digest"] = self.audit_digest
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._payload()


@dataclass(frozen=True)
class MatchweekVettingAudit:
    matches: tuple[MatchVettingResult, ...]
    policy_version: str
    policy_status: PolicyStatus
    policy_digest: str = ""
    audit_digest: str = ""

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(self.matches, key=lambda item: str(_read(item.target, "fixture_id", "")))
        )
        fixture_ids = tuple(str(_read(item.target, "fixture_id", "")) for item in ordered)
        if len(set(fixture_ids)) != len(fixture_ids):
            raise T15IntegrityError("T15 Matchweek audit contains duplicate fixtures.")
        if any(
            item.policy_version != self.policy_version
            or item.policy_status is not self.policy_status
            for item in ordered
        ):
            raise T15IntegrityError("T15 Matchweek audit contains mixed policy identities.")
        object.__setattr__(self, "matches", ordered)
        expected = _digest(self._payload(include_digest=False))
        if self.audit_digest and self.audit_digest != expected:
            raise T15IntegrityError("T15 Matchweek audit digest does not match its content.")
        object.__setattr__(self, "audit_digest", expected)

    def _payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "matches": [item.to_dict() for item in self.matches],
            "policy_digest": self.policy_digest,
            "policy_status": self.policy_status.value,
            "policy_version": self.policy_version,
        }
        if include_digest:
            payload["audit_digest"] = self.audit_digest
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._payload()


def _prediction_metrics(
    view: _PredictionView | None,
    preference: BettingPreference,
) -> dict[str, float | None]:
    if view is None:
        return {
            "estimated": None,
            "conservative": None,
            "loss_upper": None,
            "push": None,
            "uncertainty_width": None,
            "model_agreement": None,
            "model_sensitivity": None,
        }
    settlement = view.settlements.get(preference.preference_id)
    estimated = _probability_map_value(view.estimated, preference.preference_id, "WIN")
    return {
        "estimated": (estimated if estimated is not None else _probability(settlement, "WIN")),
        "conservative": _probability_map_value(view.conservative, preference.preference_id, "WIN"),
        "loss_upper": _probability_map_value(view.loss_upper, preference.preference_id, "LOSS"),
        "push": _probability(settlement, "PUSH"),
        "uncertainty_width": _interval_width(view, preference.preference_id),
        "model_agreement": view.model_agreement,
        "model_sensitivity": _sensitivity_value(view, preference.preference_id),
    }


def _policy_group(
    policy: PolicyVersion, preference_id: str, candidate: CandidateInput
) -> str | None:
    if candidate.correlation_group:
        return candidate.correlation_group
    direct = policy.correlation_groups.get(preference_id)
    if direct:
        return direct
    for key, value in policy.correlation_groups.items():
        if value == preference_id:
            return key
    return None


def _raw_component(
    component: str,
    candidate: CandidateInput,
    metrics: Mapping[str, float | None],
) -> float | None:
    if component in candidate.selection_components:
        return candidate.selection_components[component]
    baseline = candidate.baseline if isinstance(candidate.baseline, HistoricalBaseline) else None
    quality = (
        candidate.data_quality if isinstance(candidate.data_quality, DataQualityMetrics) else None
    )
    reliability = (
        candidate.historical_reliability
        if isinstance(candidate.historical_reliability, ReliabilityMetrics)
        else None
    )
    review = _review_for_gates(candidate)
    if component == "conservative_probability":
        return metrics.get("conservative")
    if component == "win_lift":
        cp = metrics.get("conservative")
        return (
            max(0.0, cp - baseline.win_probability)
            if cp is not None and baseline is not None
            else None
        )
    if component == "loss_risk_improvement":
        risk = metrics.get("loss_upper")
        return (
            max(0.0, baseline.loss_probability - risk)
            if risk is not None and baseline is not None
            else None
        )
    if component == "data_quality":
        return quality.overall if quality is not None else None
    if component == "uncertainty_quality":
        if candidate.uncertainty_quality is not None:
            return candidate.uncertainty_quality
        width = metrics.get("uncertainty_width")
        return width
    if component == "model_agreement":
        return (
            candidate.model_agreement
            if candidate.model_agreement is not None
            else metrics.get("model_agreement")
        )
    if component == "adversarial_safety":
        if candidate.adversarial_safety is not None:
            return candidate.adversarial_safety
        if candidate.failure_risk is not None:
            return 1.0 - candidate.failure_risk
        return review.safety if review is not None else None
    if component == "historical_reliability":
        return reliability.overall if reliability is not None else None
    return None


def _selection_strength(
    candidate: CandidateInput,
    metrics: Mapping[str, float | None],
    config: SelectionStrengthConfig | None,
) -> tuple[float | None, Mapping[str, float], tuple[str, ...]]:
    if config is None:
        return None, {}, ("SELECTION_STRENGTH_CONFIGURATION_MISSING",)
    components: dict[str, float] = {}
    reasons: list[str] = []
    normalizers = cast(Mapping[str, NormalizationSpec], config.normalizers)
    transforms = cast(Mapping[str, TransformSpec], config.transforms)
    for component in SELECTION_COMPONENTS:
        raw = _raw_component(component, candidate, metrics)
        normalizer = normalizers.get(component)
        transform = transforms.get(component)
        if raw is None or normalizer is None or transform is None:
            reasons.append(f"SELECTION_COMPONENT_UNRESOLVED:{component}")
            continue
        try:
            normalized = normalizer.apply(raw)
            components[component] = transform.apply(normalized)
        except T15ValidationError:
            reasons.append(f"SELECTION_COMPONENT_INVALID:{component}")
    if reasons:
        return None, components, tuple(sorted(set(reasons)))
    score = sum(
        config.weights[component] * components[component] for component in SELECTION_COMPONENTS
    )
    return score, components, ()


def _candidate_interval(
    score: float | None,
    candidate: CandidateInput,
) -> tuple[float, float] | None:
    if candidate.selection_strength_interval is not None:
        return candidate.selection_strength_interval
    if score is not None and candidate.paired_strength_uncertainty is not None:
        spread = candidate.paired_strength_uncertainty
        return (max(0.0, score - spread), min(1.0, score + spread))
    return None


def _comparison_value(item: PreferenceVettingResult, key: str) -> float:
    if key == "uncertainty":
        return item.uncertainty_width if item.uncertainty_width is not None else math.inf
    if key == "quality":
        return item.data_quality if item.data_quality is not None else -math.inf
    if key == "failure":
        if item.failure_risk is not None:
            return item.failure_risk
        if item.adversarial_review is None:
            return math.inf
        return item.adversarial_review.materiality
    if key == "reliability":
        return item.historical_reliability if item.historical_reliability is not None else -math.inf
    return 0.0


def _user_order(policy: PolicyVersion, preference_id: str) -> int:
    try:
        return policy.user_preference_order.index(preference_id)
    except ValueError:
        return len(policy.user_preference_order) + 100000


def _is_tie(
    left: PreferenceVettingResult, right: PreferenceVettingResult, policy: PolicyVersion
) -> bool:
    if left.selection_strength is None or right.selection_strength is None:
        return True
    left_interval = left.selection_strength_interval
    right_interval = right.selection_strength_interval
    if (
        left_interval is not None
        and right_interval is not None
        and left_interval[0] <= right_interval[1]
        and right_interval[0] <= left_interval[1]
    ):
        return True
    tolerance = _optional_float(_threshold_lookup(policy.thresholds, "statistical_tie_tolerance"))
    return (
        tolerance is not None
        and abs(left.selection_strength - right.selection_strength) <= tolerance
    )


def _compare_results(
    left: PreferenceVettingResult, right: PreferenceVettingResult, policy: PolicyVersion
) -> int:
    if (
        left.selection_strength is not None
        and right.selection_strength is not None
        and not _is_tie(left, right, policy)
    ):
        return -1 if left.selection_strength > right.selection_strength else 1
    for key, reverse in (
        ("uncertainty", False),
        ("quality", True),
        ("failure", False),
        ("reliability", True),
    ):
        left_value = _comparison_value(left, key)
        right_value = _comparison_value(right, key)
        if not math.isclose(left_value, right_value, abs_tol=1e-12):
            if reverse:
                return -1 if left_value > right_value else 1
            return -1 if left_value < right_value else 1
    left_order = _user_order(policy, left.preference.preference_id)
    right_order = _user_order(policy, right.preference.preference_id)
    if left_order != right_order:
        return -1 if left_order < right_order else 1
    return -1 if left.preference.preference_id < right.preference.preference_id else 1


def _rank_survivors(
    survivors: Sequence[PreferenceVettingResult], policy: PolicyVersion
) -> tuple[PreferenceVettingResult, ...]:
    def comparator(left: PreferenceVettingResult, right: PreferenceVettingResult) -> int:
        return _compare_results(left, right, policy)

    ordered = sorted(
        tuple(survivors),
        key=cmp_to_key(comparator),
    )
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))


def _result_for_preference(
    state: object,
    preference: BettingPreference,
    policy: PolicyVersion,
    candidate: CandidateInput,
    predictions: object,
    catalog: PreferenceCatalog,
) -> PreferenceVettingResult:
    target = _state_target(state)
    target_fixture_id = str(_read(target, "fixture_id", ""))
    view = _prediction_for(predictions, preference)
    normalized_candidate = candidate.normalized()
    supported, support_reasons = _supported_preference(preference, catalog)
    state_ok, state_reasons = _state_integrity(state, target)
    prediction_ok, prediction_reasons, prediction_details = _prediction_integrity(
        view, preference, target
    )
    gates = (
        _gate(
            GateId.G0,
            state_ok and supported and prediction_ok,
            (*state_reasons, *support_reasons, *prediction_reasons),
            {
                "evidence_state": {"ok": state_ok, "reason_codes": state_reasons},
                "supported_preference": supported,
                "prediction": prediction_details,
            },
        ),
        _sufficiency_gate(state, preference, _review_for_gates(normalized_candidate)),
        _g2_gate(state, preference, normalized_candidate, policy),
        _g3_gate(preference, normalized_candidate, policy),
        _g4_gate(preference, normalized_candidate, policy),
        _g5_gate(view, preference, policy),
        _g6_gate(view, normalized_candidate, preference, policy),
        _g7_gate(view, normalized_candidate, preference, policy),
        _g8_gate(normalized_candidate, policy, preference),
    )
    metrics = _prediction_metrics(view, preference)
    metrics["uncertainty_width"] = (
        normalized_candidate.uncertainty_width
        if normalized_candidate.uncertainty_width is not None
        else metrics["uncertainty_width"]
    )
    metrics["model_agreement"] = (
        normalized_candidate.model_agreement
        if normalized_candidate.model_agreement is not None
        else metrics["model_agreement"]
    )
    metrics["model_sensitivity"] = (
        normalized_candidate.model_sensitivity
        if normalized_candidate.model_sensitivity is not None
        else metrics["model_sensitivity"]
    )
    score, components, score_reasons = _selection_strength(
        normalized_candidate, metrics, policy.selection_strength
    )
    gate_reasons = tuple(
        sorted(
            {
                reason
                for gate in gates
                if gate.status is not GateStatus.PASS
                for reason in gate.reason_codes
            }
        )
    )
    survivor = all(gate.status is GateStatus.PASS for gate in gates)
    rejection_reasons = tuple(
        sorted(set((*gate_reasons, *(score_reasons if not survivor else ()))))
    )
    if not survivor:
        status = CandidateStatus.REJECT
    elif policy.mode is PolicyStatus.RESEARCH_ONLY:
        status = CandidateStatus.RESEARCH_CANDIDATE
    else:
        status = CandidateStatus.QUALIFIED
    interval = _candidate_interval(score, normalized_candidate)
    baseline = normalized_candidate.baseline
    quality = normalized_candidate.data_quality
    reliability = normalized_candidate.historical_reliability
    review = _review_for_gates(normalized_candidate)
    return PreferenceVettingResult(
        target_fixture_id=target_fixture_id,
        preference=preference,
        status=status,
        role=CandidateRole.NONE,
        gates=gates,
        rejection_reasons=rejection_reasons,
        selection_strength_reasons=score_reasons,
        estimated_probability=metrics["estimated"],
        conservative_probability=metrics["conservative"],
        loss_risk_upper=metrics["loss_upper"],
        push_probability=metrics["push"],
        uncertainty_width=metrics["uncertainty_width"],
        data_quality=quality.overall if isinstance(quality, DataQualityMetrics) else None,
        model_agreement=metrics["model_agreement"],
        model_sensitivity=metrics["model_sensitivity"],
        historical_reliability=reliability.overall
        if isinstance(reliability, ReliabilityMetrics)
        else None,
        failure_risk=normalized_candidate.failure_risk,
        baseline=baseline if isinstance(baseline, HistoricalBaseline) else None,
        adversarial_review=review,
        selection_components=components if survivor else {},
        selection_strength=score if survivor else None,
        selection_strength_interval=interval if survivor else None,
        correlation_group=_policy_group(policy, preference.preference_id, normalized_candidate),
        supporting_case=normalized_candidate.supporting_case,
        explanatory=normalized_candidate.explanatory,
    )


def _research_roles(
    ranked: Sequence[PreferenceVettingResult],
    policy: PolicyVersion,
) -> tuple[
    tuple[PreferenceVettingResult, ...],
    PreferenceVettingResult | None,
    tuple[PreferenceVettingResult, ...],
]:
    if not ranked:
        return (), None, ()
    primary = ranked[0]
    primary_group = primary.correlation_group
    with_roles: list[PreferenceVettingResult] = []
    secondary: list[PreferenceVettingResult] = []
    for item in ranked:
        if item.preference.preference_id == primary.preference.preference_id:
            updated = replace(item, role=CandidateRole.RESEARCH_PRIMARY_CANDIDATE)
        elif primary_group and item.correlation_group == primary_group and item.explanatory:
            updated = replace(
                item,
                role=CandidateRole.RESEARCH_CORRELATED_SECONDARY_CANDIDATE,
            )
            secondary.append(updated)
        else:
            updated = item
        with_roles.append(updated)
    selected_primary = next(
        item
        for item in with_roles
        if item.preference.preference_id == primary.preference.preference_id
    )
    selected_secondary = tuple(secondary)
    return tuple(with_roles), selected_primary, selected_secondary


def _production_roles(
    ranked: Sequence[PreferenceVettingResult],
) -> tuple[
    tuple[PreferenceVettingResult, ...],
    PreferenceVettingResult | None,
    tuple[PreferenceVettingResult, ...],
]:
    if not ranked:
        return (), None, ()
    primary = replace(
        ranked[0],
        status=CandidateStatus.PRIMARY_RECOMMENDATION,
        role=CandidateRole.PRIMARY_RECOMMENDATION,
    )
    primary_group = primary.correlation_group
    selected: list[PreferenceVettingResult] = [primary]
    secondary: list[PreferenceVettingResult] = []
    for item in ranked[1:]:
        if primary_group and item.correlation_group == primary_group and item.explanatory:
            updated = replace(
                item,
                status=CandidateStatus.CORRELATED_SECONDARY_FIT,
                role=CandidateRole.CORRELATED_SECONDARY_FIT,
            )
            secondary.append(updated)
        else:
            updated = item
        selected.append(updated)
    return tuple(selected), primary, tuple(secondary)


def _replace_ranked_results(
    all_results: Sequence[PreferenceVettingResult],
    ranked: Sequence[PreferenceVettingResult],
) -> tuple[PreferenceVettingResult, ...]:
    by_id = {item.preference.preference_id: item for item in ranked}
    return tuple(by_id.get(item.preference.preference_id, item) for item in all_results)


def vet_target_match(
    frozen_evidence_state: object,
    predictions: Mapping[str, object] | object | None,
    policy: PolicyVersion,
    *,
    candidate_inputs: Mapping[str, CandidateInput | Mapping[str, object]] | None = None,
    catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG,
) -> MatchVettingResult:
    """Vet every enabled preference for one frozen Target Match.

    The function retains a row for every catalog item.  Production is a
    property of the supplied policy, never of this function's caller.
    """

    target = _state_target(frozen_evidence_state)
    if target is None:
        raise T15ValidationError("T15 vetting requires a T09 frozen Evidence State target.")
    if not isinstance(policy, PolicyVersion):
        raise T15ValidationError("T15 vetting requires a PolicyVersion.")
    if policy.production_promoted and (
        catalog.version != policy.catalog_version or catalog.digest != policy.catalog_digest
    ):
        raise PolicyValidationError("The active Preference Set does not match the Policy Version.")
    if policy.production_promoted:
        policy.validate_for_production(catalog)
    evidence_state_digest = str(
        _read(frozen_evidence_state, "state_digest", _read(frozen_evidence_state, "digest", ""))
    )
    inputs = candidate_inputs or {}
    results = tuple(
        _result_for_preference(
            frozen_evidence_state,
            preference,
            policy,
            CandidateInput.from_value(inputs.get(preference.preference_id)),
            predictions,
            catalog,
        )
        for preference in catalog
    )
    survivors = tuple(item for item in results if item.is_gate_survivor)
    rankable = tuple(item for item in survivors if item.selection_strength is not None)
    ranked = _rank_survivors(rankable, policy) if policy.selection_strength is not None else ()
    if policy.mode is PolicyStatus.RESEARCH_ONLY:
        if ranked:
            ranked_results, research_primary, research_secondary = _research_roles(ranked, policy)
            updated_results = _replace_ranked_results(results, ranked_results)
            return MatchVettingResult(
                target=target,
                policy_version=policy.version,
                policy_status=policy.mode,
                decision=MatchDecision.RESEARCH_ONLY,
                preference_results=updated_results,
                policy_digest=policy.digest,
                evidence_state_digest=evidence_state_digest,
                research_primary_candidate=research_primary,
                research_secondary_candidates=research_secondary,
                avoid_reason=None,
            )
        if survivors:
            return MatchVettingResult(
                target=target,
                policy_version=policy.version,
                policy_status=policy.mode,
                decision=MatchDecision.RESEARCH_ONLY,
                preference_results=results,
                policy_digest=policy.digest,
                evidence_state_digest=evidence_state_digest,
                avoid_reason="RESEARCH_SELECTION_STRENGTH_UNAVAILABLE",
            )
        return MatchVettingResult(
            target=target,
            policy_version=policy.version,
            policy_status=policy.mode,
            decision=MatchDecision.RESEARCH_AVOID,
            preference_results=results,
            policy_digest=policy.digest,
            evidence_state_digest=evidence_state_digest,
            avoid_reason="RESEARCH_NO_PREFERENCE_PASSED_ABSOLUTE_GATES",
        )
    if not ranked:
        return MatchVettingResult(
            target=target,
            policy_version=policy.version,
            policy_status=policy.mode,
            decision=MatchDecision.AVOID_MATCH,
            preference_results=results,
            policy_digest=policy.digest,
            evidence_state_digest=evidence_state_digest,
            avoid_reason=(
                "NO_PREFERENCE_PASSED_ABSOLUTE_GATES"
                if not survivors
                else "SELECTION_STRENGTH_UNAVAILABLE"
            ),
        )
    ranked_results, primary, secondary = _production_roles(ranked)
    return MatchVettingResult(
        target=target,
        policy_version=policy.version,
        policy_status=policy.mode,
        decision=MatchDecision.PLAY,
        preference_results=_replace_ranked_results(results, ranked_results),
        policy_digest=policy.digest,
        evidence_state_digest=evidence_state_digest,
        primary_recommendation=primary,
        secondary_fits=secondary,
        avoid_reason=None,
    )


def vet_matchweek(
    frozen_evidence_states: Mapping[str, object] | Iterable[object],
    predictions: Mapping[str, object] | object | None,
    policy: PolicyVersion,
    *,
    candidate_inputs: Mapping[str, Mapping[str, CandidateInput | Mapping[str, object]]]
    | None = None,
    catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG,
) -> MatchweekVettingAudit:
    """Vet all supplied frozen Target Matches in deterministic fixture order."""

    if isinstance(frozen_evidence_states, Mapping):
        states = tuple(frozen_evidence_states.items())
    else:
        states = tuple(
            (str(_read(_state_target(state), "fixture_id", "")), state)
            for state in frozen_evidence_states
        )
    results: list[MatchVettingResult] = []
    for fixture_id, state in sorted(states, key=lambda item: item[0]):
        per_match_predictions: object = predictions
        if isinstance(predictions, Mapping) and fixture_id in predictions:
            per_match_predictions = predictions[fixture_id]
        per_match_inputs = (candidate_inputs or {}).get(fixture_id)
        results.append(
            vet_target_match(
                state,
                per_match_predictions,
                policy,
                candidate_inputs=per_match_inputs,
                catalog=catalog,
            )
        )
    return MatchweekVettingAudit(
        matches=tuple(results),
        policy_version=policy.version,
        policy_status=policy.mode,
        policy_digest=policy.digest,
    )


def vet_match(
    frozen_evidence_state: object,
    predictions: Mapping[str, object] | object | None,
    policy: PolicyVersion,
    *,
    candidate_inputs: Mapping[str, CandidateInput | Mapping[str, object]] | None = None,
    catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG,
) -> MatchVettingResult:
    """Alias for the public single-match vetting seam."""

    return vet_target_match(
        frozen_evidence_state,
        predictions,
        policy,
        candidate_inputs=candidate_inputs,
        catalog=catalog,
    )


def validate_policy_for_production(
    policy: PolicyVersion,
    catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG,
) -> None:
    """Validate the explicit production contract without running a match."""

    policy.validate_for_production(catalog)


__all__ = [
    "SELECTION_COMPONENTS",
    "AdversarialReview",
    "CandidateInput",
    "CandidateRole",
    "CandidateStatus",
    "DataQualityMetrics",
    "GateId",
    "GateResult",
    "GateStatus",
    "HistoricalBaseline",
    "MatchDecision",
    "MatchVettingResult",
    "MatchweekVettingAudit",
    "NormalizationSpec",
    "PolicyStatus",
    "PolicyValidationError",
    "PolicyVersion",
    "PreferenceVettingResult",
    "ReliabilityMetrics",
    "SelectionStrengthConfig",
    "T15Error",
    "T15IntegrityError",
    "T15ValidationError",
    "TransformSpec",
    "validate_policy_for_production",
    "vet_match",
    "vet_matchweek",
    "vet_target_match",
]

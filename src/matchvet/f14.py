"""Immutable V2 founder Preference Profile and single-match decision contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from matchvet.artifacts import ArtifactStore
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f12 import ContextualAttemptRepository
from matchvet.f13 import INPUT_MEDIA_TYPE, F13Error, ModelContractRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.store import Store
from matchvet.t09 import (
    EvidenceResearcher,
    EvidenceResearchInput,
    HistoricalMatch,
    ResearchAttempt,
    TargetMatch,
)
from matchvet.t10 import (
    DEFAULT_PREFERENCE_CATALOG,
    PREFERENCE_CATALOG_VERSION,
    BettingPreference,
    PreferenceCatalog,
)
from matchvet.t15 import (
    CandidateInput,
    PolicyStatus,
    PolicyVersion,
    vet_target_match,
)

PROFILE_MEDIA_TYPE = "application/vnd.matchvet.f14-preference-profile.v2+json"
DECISION_INPUT_MEDIA_TYPE = "application/vnd.matchvet.f14-decision-input.v2+json"
DECISION_MEDIA_TYPE = "application/vnd.matchvet.f14-decision-result.v2+json"
SCHEMA_VERSION = 2
PROFILE_VERSION = "matchvet-founder-preference-profile-v1"


class F14Error(ValueError):
    """An F14 profile, decision, or exact predecessor is invalid."""


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


@dataclass(frozen=True)
class PreferenceProfile:
    """Immutable enabled preferences, distinct from the engine's capability catalog."""

    profile_version: str
    enabled_preferences: tuple[BettingPreference, ...]
    capability_catalog_version: str = PREFERENCE_CATALOG_VERSION
    capability_catalog_digest: str = DEFAULT_PREFERENCE_CATALOG.digest
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise F14Error("Unsupported Preference Profile schema.")
        if not isinstance(self.profile_version, str) or not self.profile_version.strip():
            raise F14Error("Preference Profile version is required.")
        if (
            self.capability_catalog_version != PREFERENCE_CATALOG_VERSION
            or self.capability_catalog_digest != DEFAULT_PREFERENCE_CATALOG.digest
        ):
            raise F14Error("Preference Profile names unsupported engine market capability.")
        preferences = tuple(self.enabled_preferences)
        if any(not isinstance(item, BettingPreference) for item in preferences):
            raise F14Error("Preference Profile entries must be canonical Betting Preferences.")
        ids = tuple(item.preference_id for item in preferences)
        if not ids or ids != tuple(sorted(set(ids))):
            raise F14Error("Enabled preferences must be non-empty, sorted and unique.")
        approved = {item.preference_id: item for item in DEFAULT_PREFERENCE_CATALOG}
        if any(approved.get(item.preference_id) != item for item in preferences):
            raise F14Error("Preference Profile contains a banned, trivial, or unapproved contract.")
        object.__setattr__(self, "enabled_preferences", preferences)

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_catalog_digest": self.capability_catalog_digest,
            "capability_catalog_version": self.capability_catalog_version,
            "enabled_preferences": [item.to_dict() for item in self.enabled_preferences],
            "profile_version": self.profile_version,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


class PreferenceProfileRepository:
    """Build and replay exact protected Preference Profile artifacts."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)

    def build_profile(
        self,
        enabled_preference_ids: Iterable[str],
        *,
        profile_version: str = PROFILE_VERSION,
    ) -> PreferenceProfile:
        ids = tuple(enabled_preference_ids)
        if any(not isinstance(item, str) or not item.strip() for item in ids):
            raise F14Error("Preference Profile IDs must be non-empty strings.")
        if len(set(ids)) != len(ids):
            raise F14Error("Preference Profile cannot enable a preference more than once.")
        try:
            catalog_by_id = {item.preference_id: item for item in DEFAULT_PREFERENCE_CATALOG}
            selected = tuple(catalog_by_id[item] for item in sorted(ids))
        except (KeyError, TypeError) as error:
            raise F14Error(
                "Preference Profile contains a banned or unapproved preference."
            ) from error
        profile = PreferenceProfile(profile_version, selected)
        self.artifacts.publish_artifact(_bytes(profile.to_dict()), PROFILE_MEDIA_TYPE)
        return profile

    def replay(self, digest: str) -> PreferenceProfile:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            PROFILE_MEDIA_TYPE,
            "PROTECTED",
        ):
            raise F14Error("Missing or wrong protected Preference Profile artifact.")
        content = self.artifacts.read_artifact(digest)
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or _bytes(value) != content:
                raise F14Error("Preference Profile artifact is malformed or noncanonical.")
            if (
                type(value.get("schema_version")) is not int
                or value["schema_version"] != SCHEMA_VERSION
            ):
                raise F14Error("Unsupported Preference Profile schema.")
            raw_preferences = value["enabled_preferences"]
            if not isinstance(raw_preferences, list):
                raise F14Error("Malformed Preference Profile preference list.")
            catalog = {item.preference_id: item for item in DEFAULT_PREFERENCE_CATALOG}
            preferences = tuple(catalog[row["preference_id"]] for row in raw_preferences)
            if _bytes([item.to_dict() for item in preferences]) != _bytes(raw_preferences):
                raise F14Error("Preference Profile preference contracts differ from T10.")
            profile = PreferenceProfile(
                profile_version=value["profile_version"],
                enabled_preferences=preferences,
                capability_catalog_version=value["capability_catalog_version"],
                capability_catalog_digest=value["capability_catalog_digest"],
                schema_version=value["schema_version"],
            )
            if profile.digest != digest or _bytes(profile.to_dict()) != _bytes(value):
                raise F14Error("Preference Profile digest does not match its contents.")
            return profile
        except F14Error:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise F14Error("Malformed Preference Profile artifact.") from error


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class DecisionInputBundle:
    """Exact immutable references and per-preference evidence for one F14 decision."""

    profile_digest: str
    evidence_digest: str
    cutoff_id: str
    model_result_digest: str
    policy: Mapping[str, object]
    candidate_inputs: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        for name in ("profile_digest", "evidence_digest", "cutoff_id", "model_result_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise F14Error(f"Decision input {name} is required.")
        policy = _freeze(self.policy)
        candidates = _freeze(self.candidate_inputs)
        if not isinstance(policy, Mapping) or not isinstance(candidates, Mapping):
            raise F14Error("Decision policy and candidate inputs must be mappings.")
        if _contains_odds(candidates):
            raise F14Error("Odds are not accepted by F14 decision inputs.")
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "candidate_inputs", candidates)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_inputs": _plain(self.candidate_inputs),
            "cutoff_id": self.cutoff_id,
            "evidence_digest": self.evidence_digest,
            "model_result_digest": self.model_result_digest,
            "policy": _plain(self.policy),
            "profile_digest": self.profile_digest,
            "schema_version": SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class DecisionResult:
    """Canonical, protected F14 output for exactly one Target Match."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.canonical_bytes)
            if not isinstance(value, dict) or _bytes(value) != self.canonical_bytes:
                raise F14Error("F14 decision result must be canonical JSON.")
            if (
                value.get("schema_version") != SCHEMA_VERSION
                or value.get("status") != "RESEARCH_ONLY"
            ):
                raise F14Error("Unsupported or non-research F14 decision result.")
            rows = value.get("preference_results")
            if not isinstance(rows, list) or not rows:
                raise F14Error("F14 decision requires terminal results for enabled preferences.")
            preference_ids = []
            primary_rows = []
            terminal_values = {
                "PRIMARY_RECOMMENDATION",
                "SURVIVES_NOT_SELECTED",
                "REJECTED",
            }
            for row in rows:
                if not isinstance(row, dict) or row.get("terminal_result") not in terminal_values:
                    raise F14Error("Every enabled preference needs one terminal F14 result.")
                vetting = row.get("vetting")
                if not isinstance(vetting, dict) or not isinstance(vetting.get("preference"), dict):
                    raise F14Error("F14 preference vetting lineage is malformed.")
                preference_id = vetting["preference"].get("preference_id")
                if not isinstance(preference_id, str) or not preference_id:
                    raise F14Error("F14 preference result is missing its identity.")
                preference_ids.append(preference_id)
                if row["terminal_result"] == "PRIMARY_RECOMMENDATION":
                    primary_rows.append(preference_id)
            if len(preference_ids) != len(set(preference_ids)):
                raise F14Error("F14 decision has duplicate preference results.")
            if value.get("outcome") == "Primary Recommendation":
                if len(primary_rows) != 1 or value.get("primary_preference_id") != primary_rows[0]:
                    raise F14Error(
                        "F14 recommendation requires exactly one Primary Recommendation."
                    )
            elif value.get("outcome") == "AVOID MATCH":
                if value.get("primary_preference_id") is not None or primary_rows:
                    raise F14Error("AVOID MATCH cannot include a recommendation.")
            else:
                raise F14Error("Unsupported F14 decision outcome.")
        except F14Error:
            raise
        except (TypeError, ValueError) as error:
            raise F14Error("Malformed F14 decision result.") from error

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.canonical_bytes)
        return value

    @property
    def fixture_id(self) -> str:
        return str(self.to_dict()["fixture_id"])

    @property
    def status(self) -> str:
        return str(self.to_dict()["status"])

    @property
    def outcome(self) -> str:
        return str(self.to_dict()["outcome"])

    @property
    def primary_preference_id(self) -> str | None:
        value = self.to_dict()["primary_preference_id"]
        return str(value) if value is not None else None

    @property
    def preference_results(self) -> tuple[Mapping[str, object], ...]:
        rows = self.to_dict()["preference_results"]
        if not isinstance(rows, list):
            raise F14Error("F14 preference results are malformed.")
        return cast(tuple[Mapping[str, object], ...], tuple(_freeze(row) for row in rows))

    @property
    def confidence(self) -> Mapping[str, object] | None:
        value = self.to_dict()["confidence"]
        if not isinstance(value, Mapping):
            return None
        return cast(Mapping[str, object], _freeze(value))

    @property
    def data_quality(self) -> float | None:
        value = self.to_dict()["data_quality"]
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def risk(self) -> Mapping[str, object] | None:
        value = self.to_dict()["risk"]
        if not isinstance(value, Mapping):
            return None
        return cast(Mapping[str, object], _freeze(value))

    @property
    def lineage(self) -> Mapping[str, object]:
        value = self.to_dict()["lineage"]
        if not isinstance(value, Mapping):
            raise F14Error("Decision lineage is malformed.")
        return cast(Mapping[str, object], _freeze(value))


class DecisionRepository:
    """Build, protect, and exactly replay one-match F14 decisions."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)
        self.profiles = PreferenceProfileRepository(store)

    def build_decision(self, bundle: DecisionInputBundle) -> DecisionResult:
        if not isinstance(bundle, DecisionInputBundle):
            raise F14Error("F14 requires an exact DecisionInputBundle.")
        input_bytes = _bytes(bundle.to_dict())
        input_record = self.artifacts.publish_artifact(input_bytes, DECISION_INPUT_MEDIA_TYPE)
        result = self._evaluate(bundle, input_record.digest)
        self.artifacts.publish_artifact(result.to_bytes(), DECISION_MEDIA_TYPE)
        return result

    def replay(self, digest: str) -> DecisionResult:
        value = self._read(digest, DECISION_MEDIA_TYPE)
        try:
            if value.get("schema_version") != SCHEMA_VERSION:
                raise F14Error("Unsupported F14 decision schema.")
            input_digest = value["input_bundle_digest"]
            raw_inputs = self._read(input_digest, DECISION_INPUT_MEDIA_TYPE)
            bundle = DecisionInputBundle(
                profile_digest=raw_inputs["profile_digest"],
                evidence_digest=raw_inputs["evidence_digest"],
                cutoff_id=raw_inputs["cutoff_id"],
                model_result_digest=raw_inputs["model_result_digest"],
                policy=raw_inputs["policy"],
                candidate_inputs=raw_inputs["candidate_inputs"],
            )
            if bundle.to_dict() != raw_inputs:
                raise F14Error("Decision input bundle is noncanonical.")
            expected = self._evaluate(bundle, input_digest)
            if expected.to_bytes() != _bytes(value) or expected.digest != digest:
                raise F14Error("F14 decision result differs from exact retained inputs.")
            return expected
        except F14Error:
            raise
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise F14Error("Malformed F14 decision or lineage.") from error

    def _read(self, digest: str, media_type: str) -> dict[str, Any]:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            media_type,
            "PROTECTED",
        ):
            raise F14Error(f"Missing or wrong protected F14 artifact for {media_type}.")
        content = self.artifacts.read_artifact(digest)
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or _bytes(value) != content:
                raise F14Error("Malformed or noncanonical F14 artifact.")
            return value
        except (TypeError, ValueError) as error:
            raise F14Error("Malformed F14 artifact.") from error

    def _evidence_state(self, model: Mapping[str, Any]) -> object:
        inputs = model["inputs"]
        metadata = self.store.artifact_metadata(inputs["history_snapshot_digest"])
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            INPUT_MEDIA_TYPE,
            "PROTECTED",
        ):
            raise F14Error("F13 historical model inputs are missing or unprotected.")
        snapshot_bytes = self.artifacts.read_artifact(inputs["history_snapshot_digest"])
        snapshot = json.loads(snapshot_bytes)
        if _bytes(snapshot) != snapshot_bytes or snapshot.get("schema_version") != SCHEMA_VERSION:
            raise F14Error("F13 historical model inputs are corrupt.")
        history = tuple(HistoricalMatch.from_mapping(row) for row in snapshot["history"])
        target = TargetMatch(**inputs["target"])
        context = inputs["context"]
        attempts: tuple[ResearchAttempt, ...] = ()
        attempt_ref = context.get("contextual_attempt")
        if attempt_ref is not None:
            attempt = ContextualAttemptRepository(self.store).get(attempt_ref["attempt_id"])
            attempts = (
                ResearchAttempt(
                    requirement_id="M-WEATHER",
                    category="MANDATORY_RESEARCH",
                    source_key=attempt.provider_id,
                    attempted_at_utc=attempt.acquired_at_utc,
                    outcome=context["weather"]["state"],
                    accessibility=(
                        "ACCESSIBLE" if attempt.response_status == 200 else "INACCESSIBLE"
                    ),
                    source_assertion_ids=(attempt.attempt_id, attempt.digest),
                    reason="Exact F11/F12 weather acquisition attempt.",
                ),
            )
        state = EvidenceResearcher().build(
            EvidenceResearchInput(
                target=target,
                history=history,
                workload=context["workload"],
                weather=context["weather"],
                mandatory_research=attempts,
            )
        )
        if state.digest != model["research_state_digest"]:
            raise F14Error("Rebuilt F13 evidence state differs from exact model lineage.")
        return state

    def _evaluate(self, bundle: DecisionInputBundle, input_digest: str) -> DecisionResult:
        profile = self.profiles.replay(bundle.profile_digest)
        policy = PolicyVersion.from_mapping(bundle.policy)
        if policy.mode is not PolicyStatus.RESEARCH_ONLY:
            raise F14Error("F14 decisions must remain RESEARCH_ONLY.")
        supplied_policy_digest = bundle.policy.get("policy_digest")
        if supplied_policy_digest != policy.digest:
            raise F14Error("Decision policy digest does not match its exact policy contract.")
        try:
            model = (
                ModelContractRepository(self.store)
                .replay(bundle.model_result_digest, bundle.evidence_digest, bundle.cutoff_id)
                .to_dict()
            )
        except (F13Error, KeyError, TypeError, ValueError) as error:
            raise F14Error("Exact F13 model result cannot be replayed.") from error
        inputs = model["inputs"]
        if inputs["requirement_catalog_digest"] != V2_REQUIREMENT_CATALOG.digest:
            raise F14Error("F13 model result does not reference the exact F10 catalog.")
        if inputs["evidence_set_digest"] != bundle.evidence_digest:
            raise F14Error("F13 evidence reference differs from the decision input.")
        fixture_id = inputs["fixture_id"]
        if model["results"] == {} or any(
            row.get("fixture_id") != fixture_id for row in model["results"].values()
        ):
            raise F14Error("F13 model outputs have a missing or cross-match reference.")
        candidate_ids = set(bundle.candidate_inputs)
        enabled_ids = {item.preference_id for item in profile.enabled_preferences}
        unexpected_candidates = candidate_ids - enabled_ids
        if unexpected_candidates:
            raise F14Error("Candidate inputs name disabled or unsupported preferences.")
        candidates_plain = _plain(bundle.candidate_inputs)
        if not isinstance(candidates_plain, Mapping):
            raise F14Error("Decision candidate inputs are malformed.")
        if _contains_odds(candidates_plain):
            raise F14Error("Odds are not accepted by F14 decision inputs.")
        typed_candidates = {
            key: CandidateInput.from_value(value) for key, value in candidates_plain.items()
        }
        predictions: dict[str, object] = {}
        for preference in profile.enabled_preferences:
            family = _model_family_key(preference)
            output = model["results"][family]
            calibrated = output["calibrated"]
            if not isinstance(calibrated, dict):
                raise F14Error("F13 calibrated model output is malformed.")
            adapted = dict(calibrated)
            settlements = calibrated.get("settlement_distributions")
            estimated = calibrated.get("estimated_probabilities")
            conservative = calibrated.get("conservative_probabilities")
            quantitative_support = (
                output.get("model_availability") == "AVAILABLE"
                and calibrated.get("status") == "AVAILABLE"
                and isinstance(settlements, Mapping)
                and preference.preference_id in settlements
                and isinstance(estimated, Mapping)
                and preference.preference_id in estimated
                and isinstance(conservative, Mapping)
                and preference.preference_id in conservative
            )
            if not quantitative_support:
                # T15's G0 hard gate sees this before survivor ranking.
                adapted["status"] = "MODEL_UNAVAILABLE"
            predictions[preference.preference_id] = adapted
        subset = PreferenceCatalog(
            profile.enabled_preferences,
            version=DEFAULT_PREFERENCE_CATALOG.version,
            name=DEFAULT_PREFERENCE_CATALOG.name,
        )
        state = self._evidence_state(model)
        t15_result = vet_target_match(
            state,
            predictions,
            policy,
            candidate_inputs=typed_candidates,
            catalog=subset,
        )
        if tuple(item.preference.preference_id for item in t15_result.preference_results) != tuple(
            item.preference_id for item in profile.enabled_preferences
        ):
            raise F14Error("T15 did not return exactly one result per enabled preference.")
        selected = t15_result.research_primary_candidate
        primary_id: str | None = None
        if selected is not None and selected.is_gate_survivor:
            model_ref = model["results"][_model_family_key(selected.preference)]
            calibrated = model_ref["calibrated"]
            if (
                model_ref["model_availability"] == "AVAILABLE"
                and calibrated.get("status") == "AVAILABLE"
                and selected.selection_strength is not None
                and selected.estimated_probability is not None
                and selected.conservative_probability is not None
            ):
                primary_id = selected.preference.preference_id
        output_results = []
        for item in t15_result.preference_results:
            status = (
                "PRIMARY_RECOMMENDATION"
                if item.preference.preference_id == primary_id
                else "SURVIVES_NOT_SELECTED"
                if item.is_gate_survivor and item.selection_strength is not None
                else "REJECTED"
            )
            output_results.append({"terminal_result": status, "vetting": item.to_dict()})
        primary = next(
            (
                item
                for item in t15_result.preference_results
                if item.preference.preference_id == primary_id
            ),
            None,
        )
        lineage = {
            "capability_catalog_digest": profile.capability_catalog_digest,
            "capability_catalog_version": profile.capability_catalog_version,
            "cutoff_id": bundle.cutoff_id,
            "evidence_digest": bundle.evidence_digest,
            "f10_catalog_digest": inputs["requirement_catalog_digest"],
            "f13_input_digest": model["input_digest"],
            "f13_model_result_digest": bundle.model_result_digest,
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
                for family, row in model["results"].items()
            },
            "f13_research_state_digest": model["research_state_digest"],
            "profile_digest": profile.digest,
            "t10_preference_catalog_digest": DEFAULT_PREFERENCE_CATALOG.digest,
            "t15_policy_digest": policy.digest,
            "t15_policy_version": policy.version,
        }
        result_payload: dict[str, object] = {
            "confidence": None
            if primary is None
            else {
                "conservative_probability": primary.conservative_probability,
                "estimated_probability": primary.estimated_probability,
                "selection_strength": primary.selection_strength,
                "uncertainty_width": primary.uncertainty_width,
            },
            "data_quality": None if primary is None else primary.data_quality,
            "fixture_id": fixture_id,
            "input_bundle_digest": input_digest,
            "lineage": lineage,
            "outcome": "Primary Recommendation" if primary_id else "AVOID MATCH",
            "primary_preference_id": primary_id,
            "preference_results": output_results,
            "risk": None
            if primary is None
            else {
                "adversarial_review": primary.to_dict()["adversarial_review"],
                "failure_risk": primary.failure_risk,
                "loss_probability_upper": primary.loss_risk_upper,
            },
            "schema_version": SCHEMA_VERSION,
            "status": "RESEARCH_ONLY",
        }
        return DecisionResult(_bytes(result_payload))


def _model_family_key(preference: BettingPreference) -> str:
    family = preference.family.value
    if family == "First-Half Over":
        return "FIRST_HALF_GOALS"
    if family == "Second-Half Over":
        return "SECOND_HALF_GOALS"
    if family in {
        "Corner Match Winner",
        "Full-Match Total Corners Over",
        "Home Team Corners Over",
        "Away Team Corners Over",
    }:
        return "CORNERS"
    return "FULL_TIME_GOALS"


def _contains_odds(value: object) -> bool:
    if isinstance(value, Mapping):
        forbidden = ("odds", "price", "bookmaker", "stake", "profit", "volume")
        return any(
            any(
                token in "".join(char.lower() for char in str(key) if char.isalnum())
                for token in forbidden
            )
            or _contains_odds(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_odds(item) for item in value)
    return False

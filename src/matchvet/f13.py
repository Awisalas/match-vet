"""Separate immutable V2 model contracts using the unchanged T11-T14 engines."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

from matchvet import t11, t12, t13, t14
from matchvet.artifacts import ArtifactStore
from matchvet.evidence import EvidenceState
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f11 import HISTORY_MEDIA_TYPE, F11EvidenceRepository
from matchvet.f12 import ContextualAttemptRepository
from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import canonical_json
from matchvet.store import Store
from matchvet.t09 import (
    EvidenceResearcher,
    EvidenceResearchInput,
    HistoricalMatch,
    ResearchAttempt,
    TargetMatch,
)
from matchvet.t11 import FullTimeGoalModelFit, fit_full_time_goal_model
from matchvet.t12 import (
    HalfGoalModelFit,
    derive_first_half_goals,
    derive_second_half_goals,
    fit_first_half_goal_model,
    fit_second_half_goal_model,
)
from matchvet.t13 import CornerModelFit, fit_joint_corner_model
from matchvet.t14 import (
    CalibrationObservation,
    DistributionInput,
    ModelFamily,
    calibrate_distribution,
    fit_calibration,
)

INPUT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-input.v2+json"
RESULT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-result.v2+json"
MODEL_MEDIA_TYPE = "application/vnd.matchvet.f13-model-fit.v2+json"
PREDICTION_MEDIA_TYPE = "application/vnd.matchvet.f13-distribution.v2+json"
CALIBRATION_MEDIA_TYPE = "application/vnd.matchvet.f13-calibration.v2+json"
SOURCE_MEDIA_TYPE = "application/vnd.matchvet.f13-history-source.v2+json"
SCHEMA_VERSION = 2
RESEARCH_ADAPTER_VERSION = "f13-t09-history-context-v2"


class F13Error(ValueError):
    """The exact model contract or one of its predecessors is invalid."""


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _bytes(value: object) -> bytes:
    return canonical_json(_plain(value)).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _engine_contract() -> dict[str, object]:
    researcher = EvidenceResearcher()
    return {
        "RESEARCH_ADAPTER": {
            "version": RESEARCH_ADAPTER_VERSION,
            "feature_rules_digest": researcher.feature_rules.digest,
            "research_rules_digest": researcher.research_rules_digest,
        },
        "FULL_TIME_GOALS": {
            "model_version": t11.T11_MODEL_VERSION,
            "algorithm_version": t11.T11_ALGORITHM_VERSION,
            "feature_version": t11.T11_FEATURE_VERSION,
            "config_digest": t11.T11ModelConfig().digest,
        },
        "FIRST_HALF_GOALS": {
            "model_version": t12.FIRST_HALF_GOAL_MODEL_VERSION,
            "algorithm_version": t12.T12_ALGORITHM_VERSION,
            "feature_version": t12.T12_FEATURE_VERSION,
            "config_digest": t12.T12ModelConfig().digest,
        },
        "SECOND_HALF_GOALS": {
            "model_version": t12.SECOND_HALF_GOAL_MODEL_VERSION,
            "algorithm_version": t12.T12_ALGORITHM_VERSION,
            "feature_version": t12.T12_FEATURE_VERSION,
            "config_digest": t12.T12ModelConfig().digest,
        },
        "CORNERS": {
            "model_version": t13.T13_MODEL_VERSION,
            "algorithm_version": t13.T13_ALGORITHM_VERSION,
            "feature_version": t13.T13_FEATURE_VERSION,
            "config_digest": t13.T13ModelConfig().digest,
        },
        "CALIBRATION_UNCERTAINTY": {
            "model_version": t14.T14_MODEL_VERSION,
            "algorithm_version": t14.T14_ALGORITHM_VERSION,
            "feature_version": t14.T14_FEATURE_VERSION,
            "calibration_version": t14.T14_CALIBRATION_VERSION,
            "config_digest": t14.T14Config().digest,
        },
    }


def engine_version_identity() -> str:
    """Return the deterministic identity of the configured T11-T14 engine contract."""
    return _digest(_engine_contract())


@dataclass(frozen=True)
class ModelContract:
    canonical_bytes: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.canonical_bytes)
        return value


@dataclass(frozen=True)
class CalibrationCase:
    """Observed counts joined to one exact retained V2 prediction."""

    prediction_contract_digest: str
    fixture_id: str
    family: ModelFamily

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", ModelFamily(self.family))
        if not self.fixture_id or not self.prediction_contract_digest:
            raise F13Error("Calibration requires exact prior prediction lineage.")


class ModelContractRepository:
    """Build and replay exact contracts; no latest lookups or caller model facts."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.artifacts = ArtifactStore(store)

    def _read(self, digest: str, media_type: str) -> dict[str, Any]:
        metadata = self.store.artifact_metadata(digest)
        if metadata is None or (metadata.media_type, metadata.retention_class) != (
            media_type,
            "PROTECTED",
        ):
            raise F13Error(f"Missing or wrong protected artifact reference for {media_type}.")
        content = self.artifacts.read_artifact(digest)
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or _bytes(value) != content:
                raise F13Error("Noncanonical model contract.")
            return value
        except (ValueError, TypeError) as error:
            raise F13Error("Malformed model contract.") from error

    def _binding(self, evidence_digest: str, cutoff_id: str) -> dict[str, Any]:
        cutoff = MatchEvidenceCutoffRepository(self.store).get_by_id(cutoff_id)
        if cutoff is None:
            raise F13Error("Exact F07 cutoff is missing.")
        evidence = (
            F11EvidenceRepository(self.store)
            .replay(evidence_digest, freeze_id=cutoff.freeze_id, policy_digest=cutoff.policy_digest)
            .to_dict()
        )
        matches = [m for m in evidence["matches"] if m["cutoff"]["cutoff_id"] == cutoff_id]
        if len(matches) != 1 or matches[0]["cutoff"]["digest"] != cutoff.digest:
            raise F13Error("Evidence does not name this exact cutoff.")
        history_meta = self.store.artifact_metadata(evidence["history_artifact_digest"])
        if history_meta is None or history_meta.media_type != HISTORY_MEDIA_TYPE:
            raise F13Error("Missing F11 history.")
        fixtures = json.loads(self.artifacts.read_artifact(history_meta.digest))
        target_rows = [
            f
            for f in fixtures
            if (f["fixture_id"], f["revision_id"], f["revision_digest"])
            == (cutoff.fixture_id, cutoff.fixture_revision_ref, cutoff.fixture_revision_digest)
        ]
        if len(target_rows) != 1:
            raise F13Error("Missing exact target revision.")
        fixture = target_rows[0]
        target = TargetMatch(
            matchweek_id=cutoff.freeze_id,
            cutoff_id=cutoff.cutoff_id,
            fixture_id=cutoff.fixture_id,
            cutoff_utc=cutoff.cutoff_at_utc,
            kickoff_utc=fixture["kickoff_utc"],
            home_team_id=fixture["home_team_id"],
            away_team_id=fixture["away_team_id"],
            competition_key=fixture["competition_key"],
            competition_name=fixture["competition_name"],
            season=fixture["season"],
            source_assertion_ids=(cutoff.fixture_revision_ref,),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "fixture_id": cutoff.fixture_id,
            "freeze_id": cutoff.freeze_id,
            "freeze_digest": cutoff.freeze_digest,
            "membership_id": cutoff.membership_id,
            "membership_digest": cutoff.membership_digest,
            "cutoff_id": cutoff_id,
            "cutoff_digest": cutoff.digest,
            "evidence_set_digest": evidence_digest,
            "requirement_catalog_digest": V2_REQUIREMENT_CATALOG.digest,
            "engine_contract": _engine_contract(),
            "research_adapter_version": RESEARCH_ADAPTER_VERSION,
            "target": target.to_dict(),
            "context": matches[0],
        }

    def retain_history(self, history: Iterable[HistoricalMatch]) -> tuple[HistoricalMatch, ...]:
        """Retain explicitly supplied upstream rows and bind them to exact source bytes.

        This records upstream assertions; it does not certify provider authenticity.
        No mutable history lookup is performed during build or replay.
        """
        rows = tuple(history)
        if any(type(m) is not HistoricalMatch for m in rows):
            raise F13Error("History sources require typed HistoricalMatch records.")
        if len({m.fixture_id for m in rows}) != len(rows):
            raise F13Error("Conflicting historical source fixture IDs.")
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "history": sorted((m.to_dict() for m in rows), key=_bytes),
            "kind": "STRUCTURED_HISTORY_SOURCE",
        }
        digest = self.artifacts.publish_artifact(_bytes(snapshot), SOURCE_MEDIA_TYPE).digest
        return tuple(replace(m, source_digest=digest) for m in rows)

    def _verify_history_source(
        self, match: HistoricalMatch, sources: dict[str, dict[str, Any]]
    ) -> None:
        if match.source_digest is None:
            raise F13Error("Historical source digest is missing.")
        if match.source_digest not in sources:
            source = self._read(match.source_digest, SOURCE_MEDIA_TYPE)
            if type(source.get("schema_version")) is not int or (
                source["schema_version"] != SCHEMA_VERSION
                or set(source) != {"schema_version", "history", "kind"}
                or source.get("kind") != "STRUCTURED_HISTORY_SOURCE"
            ):
                raise F13Error("Unsupported historical source schema.")
            rows = source["history"]
            if not isinstance(rows, list) or len({r["fixture_id"] for r in rows}) != len(rows):
                raise F13Error("Malformed or conflicting historical source rows.")
            sources[match.source_digest] = {r["fixture_id"]: r for r in rows}
        row = sources[match.source_digest].get(match.fixture_id)
        if row is None:
            raise F13Error("Missing exact historical source row.")
        retained = HistoricalMatch.from_mapping(row)
        if _bytes(retained.to_dict()) != _bytes(row):
            raise F13Error("Unsupported historical source row fields.")
        resolved = replace(retained, source_digest=match.source_digest)
        if _bytes(resolved.to_dict()) != _bytes(match.to_dict()):
            raise F13Error("Historical input differs from exact retained source row.")

    @staticmethod
    def _eligible_history(match: HistoricalMatch, fixture_id: str, boundary: datetime) -> bool:
        return (
            match.observed_at_utc is not None
            and match.source_digest is not None
            and bool(match.source_assertion_ids)
            and match.fixture_id != fixture_id
            and all(
                datetime.fromisoformat(t) <= boundary
                for t in (match.kickoff_utc, match.observed_at_utc, match.published_at_utc)
                if t is not None
            )
        )

    def build(
        self,
        evidence_digest: str,
        cutoff_id: str,
        *,
        history: Iterable[HistoricalMatch],
        calibration_cases: Iterable[CalibrationCase] = (),
    ) -> ModelContract:
        inputs = self._binding(evidence_digest, cutoff_id)
        boundary = datetime.fromisoformat(inputs["target"]["cutoff_utc"])
        retained = []
        excluded = []
        for match in history:
            if type(match) is not HistoricalMatch:
                raise F13Error("Model history requires typed HistoricalMatch inputs.")
            valid = self._eligible_history(match, inputs["fixture_id"], boundary)
            if valid:
                retained.append(match.to_dict())
            else:
                excluded.append(
                    {
                        "fixture_id": match.fixture_id,
                        "digest": _digest(match.to_dict()),
                        "reason": "POST_CUTOFF_OR_INDETERMINATE_LINEAGE",
                    }
                )
        retained.sort(key=_bytes)
        if len({m["fixture_id"] for m in retained}) != len(retained):
            raise F13Error("Conflicting or duplicate historical fixture inputs.")
        snapshot = {"schema_version": SCHEMA_VERSION, "history": retained}
        inputs["history_snapshot_digest"] = self.artifacts.publish_artifact(
            _bytes(snapshot), INPUT_MEDIA_TYPE
        ).digest
        inputs["excluded_history"] = sorted(excluded, key=_bytes)
        inputs["calibration_cases"] = sorted((asdict(c) for c in calibration_cases), key=_bytes)
        result = self._evaluate(inputs, snapshot, publish=True)
        self.artifacts.publish_artifact(result.to_bytes(), RESULT_MEDIA_TYPE)
        return result

    def _calibration_observations(
        self,
        inputs: dict[str, Any],
        history: tuple[HistoricalMatch, ...],
        family: ModelFamily,
        model_version: str,
        predecessors: dict[str, dict[str, Any]],
    ) -> tuple[CalibrationObservation, ...]:
        records = []
        seen = set()
        boundary = datetime.fromisoformat(inputs["target"]["cutoff_utc"])
        for raw in inputs["calibration_cases"]:
            case = CalibrationCase(**raw)
            if case.family != family:
                continue
            if case.fixture_id in seen:
                raise F13Error("Duplicate calibration fixture.")
            seen.add(case.fixture_id)
            outcomes = [m for m in history if m.fixture_id == case.fixture_id]
            if len(outcomes) != 1:
                raise F13Error("Calibration outcome is missing from exact history snapshot.")
            outcome_match = outcomes[0]
            outcome_text = max(
                t
                for t in (outcome_match.observed_at_utc, outcome_match.published_at_utc)
                if t is not None
            )
            outcome = datetime.fromisoformat(outcome_text)
            if outcome > boundary:
                raise F13Error("Calibration outcome is post-cutoff.")
            previous = self._read(case.prediction_contract_digest, RESULT_MEDIA_TYPE)
            predecessor = previous["inputs"]
            expected_target = predecessor["target"]
            if outcome_match.competition_key is not None and (
                outcome_match.competition_key != expected_target["competition_key"]
            ):
                raise F13Error("Calibration outcome differs from exact prediction competition.")
            if (
                outcome_match.home_team_id,
                outcome_match.away_team_id,
                outcome_match.kickoff_utc,
            ) != (
                expected_target["home_team_id"],
                expected_target["away_team_id"],
                expected_target["kickoff_utc"],
            ):
                raise F13Error(
                    "Calibration outcome differs from exact prediction fixture identity."
                )
            kickoff = datetime.fromisoformat(predecessor["target"]["kickoff_utc"])
            if (
                case.fixture_id != predecessor["fixture_id"]
                or case.fixture_id == inputs["fixture_id"]
                or kickoff > outcome
                or datetime.fromisoformat(predecessor["target"]["cutoff_utc"]) >= boundary
            ):
                raise F13Error("Wrong or future calibration prediction reference.")
            if case.prediction_contract_digest not in predecessors:
                predecessors[case.prediction_contract_digest] = self.replay(
                    case.prediction_contract_digest,
                    predecessor["evidence_set_digest"],
                    predecessor["cutoff_id"],
                ).to_dict()
            previous = predecessors[case.prediction_contract_digest]
            model = previous["results"][family.value]
            if (
                model["model_version"] != model_version
                or model["model_availability"] != "AVAILABLE"
            ):
                raise F13Error("Wrong or unavailable calibration model reference.")
            distribution = DistributionInput.from_model_output(model["prediction"], family=family)
            counts = self._outcome_counts(outcome_match, family)
            if counts is None:
                continue
            records.append(
                CalibrationObservation(
                    fixture_id=case.fixture_id,
                    family=family,
                    kickoff_utc=predecessor["target"]["kickoff_utc"],
                    distribution=distribution,
                    observed_home_count=counts[0],
                    observed_away_count=counts[1],
                    observed_total_count=sum(counts),
                    prediction_cutoff_utc=predecessor["target"]["cutoff_utc"],
                    outcome_utc=outcome_text,
                    model_training_fixture_ids=tuple(model["fit"]["training_input_fixture_ids"]),
                    model_training_input_ids=tuple(model["training_input_ids"]),
                    model_version=model_version,
                    model_digest=model["model_fit_digest"],
                    evidence_state_digest=previous["research_state_digest"],
                    source_input_ids=outcome_match.source_assertion_ids,
                    source_input_digests=(
                        outcome_match.source_digest or "",
                        _digest(outcome_match.to_dict()),
                        case.prediction_contract_digest,
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _outcome_counts(match: HistoricalMatch, family: ModelFamily) -> tuple[int, int] | None:
        if match.final_state is not EvidenceState.OBSERVED or match.fixture_status not in {
            "COMPLETED",
            "FINAL",
            "FINISHED",
        }:
            return None
        if family is ModelFamily.FIRST_HALF_GOALS:
            return derive_first_half_goals(match)
        if family is ModelFamily.SECOND_HALF_GOALS:
            return derive_second_half_goals(match)
        metrics = (
            ("corners_home", "corners_away")
            if family is ModelFamily.CORNERS
            else ("full_time_home_goals", "full_time_away_goals")
        )
        values = tuple(match.metrics[k] for k in metrics)
        if any(match.metric_state(k) is not EvidenceState.OBSERVED for k in metrics):
            return None
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
            return None
        home, away = values
        assert isinstance(home, int) and isinstance(away, int)
        return home, away

    def _retain(
        self,
        payload: object,
        media_type: str,
        inputs: dict[str, Any],
        family: ModelFamily,
        *,
        publish: bool,
    ) -> str:
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "input_digest": _digest(inputs),
            "model_family": family.value,
            "payload": payload,
        }
        digest = _digest(envelope)
        if publish:
            self.artifacts.publish_artifact(_bytes(envelope), media_type)
        elif self._read(digest, media_type) != json.loads(_bytes(envelope)):
            raise F13Error("Wrong model artifact lineage.")
        return digest

    def _evaluate(
        self, inputs: dict[str, Any], snapshot: dict[str, Any], *, publish: bool = False
    ) -> ModelContract:
        expected_keys = {
            "schema_version",
            "fixture_id",
            "freeze_id",
            "freeze_digest",
            "membership_id",
            "membership_digest",
            "cutoff_id",
            "cutoff_digest",
            "evidence_set_digest",
            "requirement_catalog_digest",
            "target",
            "context",
            "history_snapshot_digest",
            "excluded_history",
            "calibration_cases",
            "engine_contract",
            "research_adapter_version",
        }
        if (
            set(inputs) != expected_keys
            or type(inputs["schema_version"]) is not int
            or (inputs["schema_version"] != SCHEMA_VERSION)
        ):
            raise F13Error("Unsupported model input schema.")
        if not isinstance(inputs["calibration_cases"], list) or not isinstance(
            inputs["excluded_history"], list
        ):
            raise F13Error("Malformed model input collections.")
        if (
            type(snapshot.get("schema_version")) is not int
            or snapshot["schema_version"] != SCHEMA_VERSION
            or set(snapshot)
            != {
                "schema_version",
                "history",
            }
        ):
            raise F13Error("Unsupported historical input schema.")
        if not isinstance(snapshot["history"], list) or any(
            not isinstance(row, dict) for row in snapshot["history"]
        ):
            raise F13Error("Malformed historical input collection.")
        for excluded in inputs["excluded_history"]:
            if not isinstance(excluded, dict) or set(excluded) != {
                "fixture_id",
                "digest",
                "reason",
            }:
                raise F13Error("Malformed excluded historical input.")
            if (
                not isinstance(excluded["fixture_id"], str)
                or not excluded["fixture_id"]
                or not isinstance(excluded["digest"], str)
                or len(excluded["digest"]) != 64
                or any(c not in "0123456789abcdef" for c in excluded["digest"])
                or excluded["reason"] != "POST_CUTOFF_OR_INDETERMINATE_LINEAGE"
            ):
                raise F13Error("Malformed excluded historical input lineage.")
        history = tuple(HistoricalMatch.from_mapping(m) for m in snapshot["history"])
        if any(
            _bytes(m.to_dict()) != _bytes(raw)
            for m, raw in zip(history, snapshot["history"], strict=True)
        ):
            raise F13Error("Unsupported historical input row fields.")
        target = TargetMatch(**inputs["target"])
        boundary = datetime.fromisoformat(target.cutoff_utc)
        if len({m.fixture_id for m in history}) != len(history):
            raise F13Error("Duplicate historical input identity.")
        sources: dict[str, dict[str, Any]] = {}
        for match in history:
            self._verify_history_source(match, sources)
            if not self._eligible_history(match, inputs["fixture_id"], boundary):
                raise F13Error("Historical input is post-cutoff or has indeterminate lineage.")
        attempts: tuple[ResearchAttempt, ...] = ()
        attempt_ref = inputs["context"]["contextual_attempt"]
        if attempt_ref is not None:
            attempt = ContextualAttemptRepository(self.store).get(attempt_ref["attempt_id"])
            attempts = (
                ResearchAttempt(
                    requirement_id="M-WEATHER",
                    category="MANDATORY_RESEARCH",
                    source_key=attempt.provider_id,
                    attempted_at_utc=attempt.acquired_at_utc,
                    outcome=inputs["context"]["weather"]["state"],
                    accessibility="ACCESSIBLE"
                    if attempt.response_status == 200
                    else "INACCESSIBLE",
                    source_assertion_ids=(attempt.attempt_id, attempt.digest),
                    reason="Exact F11/F12 weather acquisition attempt.",
                ),
            )
        state = EvidenceResearcher().build(
            EvidenceResearchInput(
                target=target,
                history=history,
                workload=inputs["context"]["workload"],
                weather=inputs["context"]["weather"],
                mandatory_research=attempts,
            )
        )
        full = fit_full_time_goal_model(history, state)
        fits: dict[ModelFamily, FullTimeGoalModelFit | HalfGoalModelFit | CornerModelFit] = {
            ModelFamily.FULL_TIME_GOALS: full,
            ModelFamily.FIRST_HALF_GOALS: fit_first_half_goal_model(
                history, state, full_time_fit=full
            ),
            ModelFamily.SECOND_HALF_GOALS: fit_second_half_goal_model(
                history, state, full_time_fit=full
            ),
            ModelFamily.CORNERS: fit_joint_corner_model(history, state),
        }
        results = {}
        predecessors: dict[str, dict[str, Any]] = {}
        for family, fit in fits.items():
            prediction = fit.predict(state)
            calibration = fit_calibration(
                self._calibration_observations(
                    inputs, history, family, fit.model_version, predecessors
                ),
                family=family,
                calibration_end_utc=target.cutoff_utc,
                expected_model_version=fit.model_version,
            )
            calibrated = calibrate_distribution(
                prediction, calibration, model_fit=fit, frozen_evidence_state=state
            )
            fit_value = fit.to_dict()
            prediction_value = prediction.to_dict()
            results[family.value] = {
                "schema_version": SCHEMA_VERSION,
                "fixture_id": target.fixture_id,
                "input_digest": _digest(inputs),
                "input_lineage": {
                    k: inputs[k]
                    for k in (
                        "freeze_id",
                        "freeze_digest",
                        "membership_id",
                        "membership_digest",
                        "cutoff_id",
                        "cutoff_digest",
                        "evidence_set_digest",
                        "history_snapshot_digest",
                        "requirement_catalog_digest",
                        "engine_contract",
                        "research_adapter_version",
                    )
                },
                "model_family": family.value,
                "model_version": fit.model_version,
                "model_fit_digest": fit.digest,
                "model_artifact_digest": self._retain(
                    fit_value, MODEL_MEDIA_TYPE, inputs, family, publish=publish
                ),
                "prediction_artifact_digest": self._retain(
                    prediction_value, PREDICTION_MEDIA_TYPE, inputs, family, publish=publish
                ),
                "calibration_artifact_digest": self._retain(
                    calibration.to_dict(), CALIBRATION_MEDIA_TYPE, inputs, family, publish=publish
                ),
                "fit": fit_value,
                "prediction_digest": prediction.digest,
                "prediction": prediction_value,
                "estimated_distribution": {
                    k: v.to_dict() for k, v in prediction.settlement_distributions.items()
                },
                "model_availability": fit.status.value,
                "feature_input_ids": fit_value["feature_input_ids"],
                "feature_input_digests": fit_value["feature_input_digests"],
                "training_input_ids": fit_value["training_input_ids"],
                "training_input_digests": fit_value["training_input_digests"],
                "calibration_version": calibration.calibration_version,
                "uncertainty_engine": inputs["engine_contract"]["CALIBRATION_UNCERTAINTY"],
                "calibration_digest": calibration.digest,
                "calibration": calibration.to_dict(),
                "calibrated": calibrated.to_dict(),
                "uncertainty": {
                    "model": fit_value["uncertainty"],
                    "prediction": prediction_value["uncertainty"],
                    "calibrated": calibrated.to_dict()["uncertainty"],
                    "research_gaps": [g.to_dict() for g in state.gaps],
                    "research_conflicts": [c.to_dict() for c in state.conflicts],
                },
            }
        return ModelContract(
            _bytes(
                {
                    "schema_version": SCHEMA_VERSION,
                    "inputs": inputs,
                    "input_digest": _digest(inputs),
                    "features": [f.to_dict() for f in state.derived_features],
                    "research_state_digest": state.digest,
                    "research_adapter_version": inputs["research_adapter_version"],
                    "research_attempts": [a.to_dict() for a in state.research_attempts],
                    "research_requirements": {
                        r.requirement_id: {
                            "state": inputs["context"]["workload"]["state"]
                            if r.requirement_id == "V2-WORKLOAD"
                            else inputs["context"]["weather"]["state"]
                            if r.requirement_id == "V2-WEATHER-FORECAST"
                            else "OBSERVED"
                            if r.requirement_id == "V2-TARGET-FIXTURE"
                            else "UNKNOWN",
                            "basis": "EXACT_F11_CONTEXT"
                            if r.requirement_id
                            in {"V2-WORKLOAD", "V2-WEATHER-FORECAST", "V2-TARGET-FIXTURE"}
                            else "NO_V2_REQUIREMENT_ASSESSMENT",
                        }
                        for r in V2_REQUIREMENT_CATALOG.requirements
                    },
                    "results": results,
                }
            )
        )

    def replay(self, digest: str, evidence_digest: str, cutoff_id: str) -> ModelContract:
        value = self._read(digest, RESULT_MEDIA_TYPE)
        try:
            if (
                type(value["schema_version"]) is not int
                or value["schema_version"] != SCHEMA_VERSION
            ):
                raise F13Error("Unsupported model result schema.")
            binding = self._binding(evidence_digest, cutoff_id)
            inputs = value["inputs"]
            if any(_bytes(inputs.get(k)) != _bytes(v) for k, v in binding.items()):
                raise F13Error("Wrong membership, cutoff or evidence reference.")
            snapshot = self._read(inputs["history_snapshot_digest"], INPUT_MEDIA_TYPE)
            expected = self._evaluate(inputs, snapshot)
            if expected.to_bytes() != _bytes(value):
                raise F13Error("Model result or lineage differs from exact inputs.")
            return expected
        except (KeyError, TypeError, AttributeError) as error:
            raise F13Error("Malformed model result or input lineage.") from error

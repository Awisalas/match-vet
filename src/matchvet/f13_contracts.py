"""Exact historical and causal F13 schema, engine and numerical context dispatch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast

from matchvet import t11, t12, t13, t14
from matchvet.matchweek_membership import canonical_json
from matchvet.t09 import EvidenceResearcher

INPUT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-input.v2+json"
RESULT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-result.v2+json"
MODEL_MEDIA_TYPE = "application/vnd.matchvet.f13-model-fit.v2+json"
PREDICTION_MEDIA_TYPE = "application/vnd.matchvet.f13-distribution.v2+json"
CALIBRATION_MEDIA_TYPE = "application/vnd.matchvet.f13-calibration.v2+json"
SOURCE_MEDIA_TYPE = "application/vnd.matchvet.f13-history-source.v2+json"
SCHEMA_VERSION = 2
CAUSAL_INPUT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-input.v3+json"
CAUSAL_RESULT_MEDIA_TYPE = "application/vnd.matchvet.f13-model-result.v3+json"
CAUSAL_MODEL_MEDIA_TYPE = "application/vnd.matchvet.f13-model-fit.v3+json"
CAUSAL_PREDICTION_MEDIA_TYPE = "application/vnd.matchvet.f13-distribution.v3+json"
CAUSAL_CALIBRATION_MEDIA_TYPE = "application/vnd.matchvet.f13-calibration.v3+json"
CAUSAL_BINDING_MEDIA_TYPE = "application/vnd.matchvet.f13-input-binding.v1+json"
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


def causal_engine_contract() -> dict[str, object]:
    """Explicit successor adapter over the unchanged historical numerical engines."""
    contract = _engine_contract()
    adapter = dict(cast(dict[str, object], contract["RESEARCH_ADAPTER"]))
    adapter["version"] = "f13-t09-causal-context-v3"
    contract["RESEARCH_ADAPTER"] = adapter
    return contract


def causal_engine_version_identity() -> str:
    return _digest(causal_engine_contract())


def engine_contract_for_schema(schema: int) -> dict[str, object]:
    if type(schema) is not int or schema not in {2, 3}:
        raise F13Error("Unsupported explicit engine/adapter schema.")
    return causal_engine_contract() if schema == 3 else _engine_contract()


def media_for_schema(media: str, schema: int) -> str:
    return (
        {
            INPUT_MEDIA_TYPE: CAUSAL_INPUT_MEDIA_TYPE,
            RESULT_MEDIA_TYPE: CAUSAL_RESULT_MEDIA_TYPE,
            MODEL_MEDIA_TYPE: CAUSAL_MODEL_MEDIA_TYPE,
            PREDICTION_MEDIA_TYPE: CAUSAL_PREDICTION_MEDIA_TYPE,
            CALIBRATION_MEDIA_TYPE: CAUSAL_CALIBRATION_MEDIA_TYPE,
        }.get(media, media)
        if schema == 3
        else media
    )


def research_context(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Historical numerical engines consume chronology, never qualify a candidate.

    Successor storage stays UNQUALIFIED. This explicitly versioned adapter permits
    contextual numerical computation under the legacy engines' input vocabulary.
    Only the selection owner can qualify the resulting complete graph.
    """
    context = json.loads(_bytes(inputs["context"]))
    if inputs["schema_version"] == 3:
        for key in ("weather", "workload"):
            if context[key]["cutoff_eligibility"] != "UNQUALIFIED":
                raise F13Error("Causal context cannot carry local cutoff qualification.")
            context[key]["cutoff_eligibility"] = "CUTOFF_VALID"
        if context["weather"]["state"] == "OBSERVED":
            context["weather"]["freshness"] = "CUTOFF_VALID"
    return cast(dict[str, Any], context)

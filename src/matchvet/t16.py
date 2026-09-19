"""T16 publication of complete Matchweek Audits and concise Reports.

T15 owns preference-level vetting and ranking.  T16 owns the immutable boundary
around that result: coverage validation, reproducibility metadata, safe
production/research presentation, deterministic Markdown, and the local
artifact publication marker used by the read-only CLI commands.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import cast

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.matchweek import AppendixDisposition, MembershipState
from matchvet.store import Store, StoreMode
from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, PreferenceCatalog
from matchvet.t15 import (
    CandidateRole,
    CandidateStatus,
    MatchDecision,
    PolicyStatus,
)

T16_SCHEMA_VERSION = 1
T16_AUDIT_SCHEMA = "matchvet.matchweek.audit"
T16_REPORT_SCHEMA = "matchvet.matchweek.report"
T16_PUBLICATION_SCHEMA = "matchvet.matchweek.publication"
T16_AUDIT_MEDIA_TYPE = "application/vnd.matchvet.t16-audit+json"
T16_REPORT_MEDIA_TYPE = "text/markdown"
T16_PUBLICATION_MEDIA_TYPE = "application/vnd.matchvet.t16-publication+json"
AFRICA_LAGOS = "Africa/Lagos"
T16_EXPECTED_PREFERENCE_COUNT = 37
DEFAULT_TARGET_LEAGUE_SET = (
    "Premier League",
    "Serie A",
    "La Liga",
    "Bundesliga",
    "Ligue 1",
    "Liga Portugal",
    "Belgian Pro League",
)


class T16Error(Exception):
    """Base class for T16 publication and reading failures."""


class T16ValidationError(T16Error, ValueError):
    """The T16 input or persisted contract is malformed."""


class T16IncompleteError(T16Error):
    """An incomplete run or audit cannot be published as a completed report."""


class T16NotFoundError(T16Error, LookupError):
    """The requested complete publication or match does not exist."""


class T16IntegrityError(T16Error):
    """A persisted T16 artifact or digest failed verification."""


class PublicationState(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class AuditMode(StrEnum):
    PRODUCTION = "PRODUCTION"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class RejectionCategory(StrEnum):
    INSUFFICIENT_PROBABILITY = "INSUFFICIENT_PROBABILITY"
    EXCESSIVE_UNCERTAINTY = "EXCESSIVE_UNCERTAINTY"
    INSUFFICIENT_DATA_QUALITY = "INSUFFICIENT_DATA_QUALITY"
    INCOMPLETE_RESEARCH = "INCOMPLETE_RESEARCH"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    ADVERSARIAL_VETO = "ADVERSARIAL_VETO"
    NON_TRIVIALITY_GATE_FAILURE = "NON_TRIVIALITY_GATE_FAILURE"
    MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
    NO_PREFERENCE_PASSED_ABSOLUTE_GATES = "NO_PREFERENCE_PASSED_ABSOLUTE_GATES"
    SELECTION_STRENGTH_UNAVAILABLE = "SELECTION_STRENGTH_UNAVAILABLE"


def _read(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _enum_value(value: object) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _token(value: object) -> str:
    return "_".join(_enum_value(value).strip().upper().replace("-", " ").split())


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except TypeError:
            return _jsonable(to_dict(include_publication=True))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise T16ValidationError("T16 JSON values must be finite.")
        return value
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
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


def _object_dict(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except TypeError:
            result = to_dict(include_publication=True)
        if isinstance(result, Mapping):
            return {str(key): item for key, item in result.items()}
    values = getattr(value, "__dict__", None)
    if isinstance(values, Mapping):
        return {str(key): item for key, item in values.items()}
    return {}


def _sequence(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError:
        return ()


def _text(value: object, label: str, default: str = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if default:
        return default
    raise T16ValidationError(f"{label} must be a non-empty string.")


def _to_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], _jsonable(_object_dict(value)))


def _membership_id(membership: object) -> str:
    return str(
        _read(
            membership,
            "subject_id",
            _read(membership, "fixture_id", _read(membership, "membership_id", "")),
        )
    )


def _membership_state(membership: object) -> str:
    return _token(_read(membership, "membership_state", "INCLUDED"))


def _is_target_membership(membership: object) -> bool:
    target = _read(membership, "target_match", None)
    if isinstance(target, bool):
        return target
    return _membership_state(membership) == MembershipState.INCLUDED.value


def _target_from(
    result: object | None, state: object | None, membership: object | None = None
) -> object:
    target = _read(result, "target") if result is not None else None
    if target is not None:
        return target
    target = _read(state, "target") if state is not None else None
    if target is None:
        if membership is not None:
            fixture_id = _membership_id(membership)
            if fixture_id:
                return {"fixture_id": fixture_id}
        raise T16ValidationError("A Target Match is required for each included membership.")
    return target


def _fixture_id(result: object | None, state: object | None, membership: object) -> str:
    value = _read(result, "target") if result is not None else None
    if value is not None:
        selected = _read(value, "fixture_id", "")
        if selected:
            return str(selected)
    value = _read(state, "target") if state is not None else None
    if value is not None:
        selected = _read(value, "fixture_id", "")
        if selected:
            return str(selected)
    return _membership_id(membership)


def _target_payload(target: object) -> dict[str, object]:
    payload = _object_dict(target)
    if payload:
        return cast(dict[str, object], _jsonable(payload))
    return {"fixture_id": str(_read(target, "fixture_id", ""))}


def _policy_status(policy: object | None, result: object | None) -> str:
    selected = _read(policy, "mode", _read(policy, "status", None)) if policy else None
    if selected is None and result is not None:
        selected = _read(result, "policy_status", PolicyStatus.RESEARCH_ONLY)
    return _enum_value(selected or PolicyStatus.RESEARCH_ONLY)


def _policy_info(policy: object | None, result: object | None) -> dict[str, object]:
    status = _policy_status(policy, result)
    version = str(_read(policy, "version", _read(result, "policy_version", "UNSPECIFIED")))
    digest = str(_read(policy, "digest", _read(result, "policy_digest", "UNSPECIFIED")))
    detail = _object_dict(policy) if policy is not None else {}
    return {
        "version": version,
        "digest": digest,
        "status": status,
        "thresholds": _jsonable(detail.get("thresholds", {})),
    }


def _result_decision(result: object) -> str:
    return _enum_value(_read(result, "decision", MatchDecision.RESEARCH_ONLY))


def _prediction_groups(predictions: object, fixture_id: str) -> tuple[Mapping[str, object], ...]:
    selected = predictions
    if isinstance(selected, Mapping) and fixture_id in selected:
        selected = selected[fixture_id]
    groups: list[Mapping[str, object]] = []
    visited: set[int] = set()

    def collect(value: object) -> None:
        selected_dict = _object_dict(value)
        if not selected_dict or id(selected_dict) in visited:
            return
        visited.add(id(selected_dict))
        groups.append(selected_dict)
        for child in selected_dict.values():
            if isinstance(child, Mapping) or callable(getattr(child, "to_dict", None)):
                collect(child)

    collect(selected)
    return tuple(groups)


def _distribution_for(
    predictions: object, fixture_id: str, preference_id: str, candidate: object
) -> dict[str, object]:
    for group in _prediction_groups(predictions, fixture_id):
        distributions = group.get("settlement_distributions")
        if isinstance(distributions, Mapping) and preference_id in distributions:
            selected = distributions[preference_id]
            if isinstance(selected, Mapping):
                return cast(dict[str, object], _jsonable(selected))
    estimated = _read(candidate, "estimated_probability")
    loss = _read(candidate, "loss_risk_upper")
    push = _read(candidate, "push_probability", 0.0)
    if all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in (estimated, loss, push)
    ):
        return {
            "LOSS": float(cast(float, loss)),
            "PUSH": float(cast(float, push)),
            "WIN": float(cast(float, estimated)),
        }
    return {}


def _prediction_metadata(
    predictions: object, fixture_id: str, preference_id: str
) -> dict[str, object]:
    for group in _prediction_groups(predictions, fixture_id):
        distributions = group.get("probability_intervals")
        interval = distributions.get(preference_id) if isinstance(distributions, Mapping) else None
        if interval is not None or any(
            key in group
            for key in ("model_version", "model_digest", "calibration_version", "prediction_digest")
        ):
            return {
                "calibration_version": group.get("calibration_version"),
                "model_digest": group.get("model_digest"),
                "model_version": group.get("model_version"),
                "probability_interval": _jsonable(interval),
                "prediction_digest": group.get("prediction_digest"),
                "uncertainty": _jsonable(group.get("uncertainty", {})),
            }
    return {}


def _evidence_payload(
    state: object | None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    if state is None:
        return {}, {}, (), ()
    payload = _to_dict(state)
    identities: set[str] = set()
    identity_fields: dict[str, object] = {}
    for key in ("state_id", "state_digest", "artifact_digest", "manifest_digest"):
        value = payload.get(key, _read(state, key))
        if value not in (None, ""):
            identity_fields[key] = _jsonable(value)
            identities.add(str(value))
    for key in ("source_assertions", "post_cutoff_assertions"):
        items = payload.get(key, ())
        if isinstance(items, (tuple, list)):
            for item in items:
                row = _object_dict(item)
                for item_key in (
                    "fact_id",
                    "evidence_id",
                    "source_assertion_id",
                    "capture_id",
                    "origin_id",
                ):
                    value = row.get(item_key)
                    if value not in (None, ""):
                        identities.add(str(value))
    identity_fields["evidence_ids"] = tuple(sorted(identities))
    gaps = tuple(
        cast(dict[str, object], _jsonable(_object_dict(item)))
        for item in _sequence(payload.get("gaps", ()))
    )
    conflicts = tuple(
        cast(dict[str, object], _jsonable(_object_dict(item)))
        for item in _sequence(payload.get("conflicts", ()))
    )
    return payload, identity_fields, gaps, conflicts


def _reason_category(reason: object) -> RejectionCategory:
    token = _token(reason)
    if "SELECTION_STRENGTH" in token or "SELECTION_COMPONENT" in token:
        return RejectionCategory.SELECTION_STRENGTH_UNAVAILABLE
    if "UNCERTAINTY" in token or "TAIL_RISK" in token:
        return RejectionCategory.EXCESSIVE_UNCERTAINTY
    if any(
        marker in token
        for marker in (
            "DATA_QUALITY",
            "CRITICAL_EVIDENCE",
            "EVIDENCE_STATE",
            "HISTORICAL_",
        )
    ):
        return RejectionCategory.INSUFFICIENT_DATA_QUALITY
    if (
        "RESEARCH" in token
        or "MANDATORY_RESEARCH" in token
        or "MODEL_UNAVAILABLE" in token
        or "MISSING_MODEL" in token
        or "PREDICTION_" in token
        or "SETTLEMENT_DISTRIBUTION" in token
        or "POLICY_THRESHOLD" in token
    ):
        return RejectionCategory.INCOMPLETE_RESEARCH
    if "CONFLICT" in token:
        return RejectionCategory.MATERIAL_CONFLICT
    if "ADVERSARIAL" in token or "VETO" in token:
        return RejectionCategory.ADVERSARIAL_VETO
    if "TRIVIAL" in token or "LIFT" in token:
        return RejectionCategory.NON_TRIVIALITY_GATE_FAILURE
    if "MODEL_" in token or "SENSITIVITY" in token:
        return RejectionCategory.MODEL_DISAGREEMENT
    if "PROBABILITY" in token or "LOSS_RISK" in token or "SELECTION_STRENGTH" in token:
        return RejectionCategory.INSUFFICIENT_PROBABILITY
    return RejectionCategory.NO_PREFERENCE_PASSED_ABSOLUTE_GATES


_CATEGORY_PRIORITY = {
    RejectionCategory.INCOMPLETE_RESEARCH: 0,
    RejectionCategory.MATERIAL_CONFLICT: 1,
    RejectionCategory.INSUFFICIENT_DATA_QUALITY: 2,
    RejectionCategory.EXCESSIVE_UNCERTAINTY: 3,
    RejectionCategory.MODEL_DISAGREEMENT: 4,
    RejectionCategory.ADVERSARIAL_VETO: 5,
    RejectionCategory.NON_TRIVIALITY_GATE_FAILURE: 6,
    RejectionCategory.INSUFFICIENT_PROBABILITY: 7,
    RejectionCategory.SELECTION_STRENGTH_UNAVAILABLE: 8,
    RejectionCategory.NO_PREFERENCE_PASSED_ABSOLUTE_GATES: 9,
}


def _candidate_payload(
    candidate: object,
    *,
    predictions: object,
    fixture_id: str,
    evidence_gaps: Sequence[Mapping[str, object]],
    evidence_conflicts: Sequence[Mapping[str, object]],
    research: bool = False,
    incomplete: bool = False,
    rankable_count: int = 0,
) -> dict[str, object]:
    payload = _to_dict(candidate)
    preference = _read(candidate, "preference")
    preference_payload = _to_dict(preference)
    preference_id = str(
        preference_payload.get("preference_id", _read(candidate, "preference_id", ""))
    )
    review = _object_dict(_read(candidate, "adversarial_review"))
    if not review:
        review = _object_dict(payload.get("adversarial_review"))
    status = _enum_value(_read(candidate, "status", payload.get("status", "REJECT")))
    role = _enum_value(_read(candidate, "role", payload.get("role", "NONE")))
    if incomplete:
        status = "UNPUBLISHED"
        role = "UNPUBLISHED"
    elif research:
        if status not in {CandidateStatus.REJECT.value, "REJECT"}:
            status = "RESEARCH CANDIDATE"
        if role not in {CandidateRole.NONE.value, "NONE"}:
            role = role.replace("Primary Recommendation", "Research Primary Candidate").replace(
                "Correlated Secondary Fit", "Research Correlated Secondary Candidate"
            )
    raw_reasons = _read(candidate, "rejection_reasons", payload.get("rejection_reasons", ()))
    rejection_reasons = tuple(sorted(str(item) for item in _sequence(raw_reasons)))
    categories = tuple(sorted({_reason_category(item).value for item in rejection_reasons}))
    baseline = _jsonable(_read(candidate, "baseline", payload.get("baseline")))
    uncertainty = {
        "width": _read(candidate, "uncertainty_width", payload.get("uncertainty_width")),
        "tail_risk": _read(candidate, "uncertainty_tail_risk"),
        "prediction": _prediction_metadata(predictions, fixture_id, preference_id),
    }
    failure_case = review.get("failure_case") or "No evidence-backed failure case was retained."
    support_case = _read(candidate, "supporting_case", payload.get("supporting_case"))
    rank = _read(candidate, "rank", payload.get("rank"))
    if rank is None:
        rank = 1 if role not in {"NONE", "UNPUBLISHED"} else None
    if rank == 1:
        ranking_reason = (
            f"Highest Selection Strength among {rankable_count or 1} qualifying candidate(s); "
            "tie-breakers use uncertainty, Data Quality, failure risk, and reliability."
        )
    else:
        ranking_reason = "Retained as an independently qualifying correlated alternative."
    return {
        "candidate_status": status,
        "role": role,
        "target_fixture_id": _read(
            candidate, "target_fixture_id", payload.get("target_fixture_id")
        ),
        "preference": preference_payload,
        "preference_id": preference_id,
        "preference_line": preference_payload.get("line"),
        "exact_preference": preference_payload.get("label", preference_id),
        "gates": _jsonable(_read(candidate, "gates", payload.get("gates", ()))),
        "settlement_distribution": _distribution_for(
            predictions, fixture_id, preference_id, candidate
        ),
        "estimated_probability": _read(
            candidate, "estimated_probability", payload.get("estimated_probability")
        ),
        "conservative_probability": _read(
            candidate, "conservative_probability", payload.get("conservative_probability")
        ),
        "uncertainty": uncertainty,
        "data_quality": _read(candidate, "data_quality", payload.get("data_quality")),
        "model_agreement": _read(candidate, "model_agreement", payload.get("model_agreement")),
        "model_sensitivity": _read(
            candidate, "model_sensitivity", payload.get("model_sensitivity")
        ),
        "loss_risk_upper": _read(candidate, "loss_risk_upper", payload.get("loss_risk_upper")),
        "push_probability": _read(candidate, "push_probability", payload.get("push_probability")),
        "historical_reliability": _read(
            candidate, "historical_reliability", payload.get("historical_reliability")
        ),
        "failure_risk": _read(candidate, "failure_risk", payload.get("failure_risk")),
        "adversarial_review": _jsonable(review) if review else None,
        "risk_assessment": {
            "failure_risk": _read(candidate, "failure_risk", payload.get("failure_risk")),
            "failure_case": failure_case,
            "materiality": review.get("materiality"),
            "represented_in_uncertainty": review.get("represented_in_uncertainty"),
            "veto": review.get("veto", False),
            "downgrade": review.get("downgrade", False),
        },
        "strongest_supporting_case": support_case,
        "strongest_credible_failure_case": failure_case,
        "material_evidence_gaps": tuple(
            gap
            for gap in evidence_gaps
            if bool(gap.get("decision_materiality", gap.get("blocks_family", True)))
        ),
        "material_evidence_conflicts": tuple(
            conflict for conflict in evidence_conflicts if bool(conflict.get("material", True))
        ),
        "historical_baseline": baseline,
        "selection_strength": _read(
            candidate, "selection_strength", payload.get("selection_strength")
        ),
        "selection_strength_interval": _jsonable(
            _read(
                candidate, "selection_strength_interval", payload.get("selection_strength_interval")
            )
        ),
        "selection_strength_components": _jsonable(
            _read(candidate, "selection_components", payload.get("selection_components", {}))
        ),
        "selection_strength_reasons": _jsonable(
            _read(
                candidate,
                "selection_strength_reasons",
                payload.get("selection_strength_reasons", ()),
            )
        ),
        "rejection_reasons": rejection_reasons,
        "rejection_categories": categories,
        "rank": rank,
        "why_ranked_above_alternatives": ranking_reason,
        "explanatory": bool(_read(candidate, "explanatory", payload.get("explanatory", True))),
        "correlation_group": _read(
            candidate, "correlation_group", payload.get("correlation_group")
        ),
        "t15_vetting_result": payload,
    }


def _avoid_payload(
    result: object, candidates: Sequence[Mapping[str, object]], *, research: bool
) -> dict[str, object] | None:
    decision = _result_decision(result)
    expected = {MatchDecision.AVOID_MATCH.value, MatchDecision.RESEARCH_AVOID.value}
    if decision not in expected:
        return None
    raw_reason = _read(result, "avoid_reason")
    reason = (
        raw_reason.strip()
        if isinstance(raw_reason, str) and raw_reason.strip()
        else "NO_PREFERENCE_PASSED_ABSOLUTE_GATES"
    )
    reason_category = _reason_category(reason)
    reasons = sorted(
        {
            str(item)
            for candidate in candidates
            for item in cast(Sequence[object], candidate.get("rejection_reasons", ()))
        }
    )
    categories = sorted({_reason_category(item).value for item in reasons})
    if reason.startswith("RESEARCH_SELECTION_STRENGTH"):
        reason_category = RejectionCategory.SELECTION_STRENGTH_UNAVAILABLE
    elif reason.startswith("RESEARCH_"):
        reason_category = RejectionCategory.NO_PREFERENCE_PASSED_ABSOLUTE_GATES
    elif (
        reason
        in {
            "NO_PREFERENCE_PASSED_ABSOLUTE_GATES",
            "RESEARCH_NO_PREFERENCE_PASSED_ABSOLUTE_GATES",
        }
        and categories
    ):
        reason_category = min(
            (RejectionCategory(item) for item in categories),
            key=lambda item: _CATEGORY_PRIORITY[item],
        )
    return {
        "label": "RESEARCH AVOID" if research else "AVOID MATCH",
        "category": reason_category.value,
        "reason_code": reason,
        "supporting_rejection_reasons": tuple(reasons),
        "supporting_categories": tuple(categories),
    }


def _appendix_withdrawn(appendix: Sequence[object]) -> set[str]:
    withdrawn: set[str] = set()
    for entry in appendix:
        disposition = _token(_read(entry, "disposition", ""))
        if disposition != _token(AppendixDisposition.WITHDRAWN):
            continue
        selected = _read(entry, "fixture_id", _read(entry, "subject_id", ""))
        if selected:
            withdrawn.add(str(selected))
    return withdrawn


def _research_candidate(result: object) -> object | None:
    return _read(result, "research_primary_candidate")


def _research_secondaries(result: object) -> tuple[object, ...]:
    return _sequence(_read(result, "research_secondary_candidates", ()))


def _production_primary(result: object) -> object | None:
    return _read(result, "primary_recommendation")


def _production_secondaries(result: object) -> tuple[object, ...]:
    return _sequence(_read(result, "secondary_fits", ()))


def _match_payload(
    membership: object,
    result: object | None,
    state: object | None,
    predictions: object,
    *,
    research: bool,
    incomplete: bool,
    withdrawn: bool,
    catalog: PreferenceCatalog,
) -> dict[str, object]:
    fixture_id = _fixture_id(result, state, membership)
    evidence, identities, gaps, conflicts = _evidence_payload(state)
    raw_candidates = _sequence(_read(result, "preference_results", ())) if result else ()
    catalog_order = {item.preference_id: index for index, item in enumerate(catalog)}
    raw_candidates = tuple(
        sorted(
            raw_candidates,
            key=lambda item: (
                catalog_order.get(
                    str(_read(_read(item, "preference"), "preference_id", "")),
                    len(catalog),
                ),
                str(_read(_read(item, "preference"), "preference_id", "")),
            ),
        )
    )
    candidate_rows = tuple(
        _candidate_payload(
            candidate,
            predictions=predictions,
            fixture_id=fixture_id,
            evidence_gaps=gaps,
            evidence_conflicts=conflicts,
            research=research,
            incomplete=incomplete,
            rankable_count=sum(
                1
                for item in raw_candidates
                if _read(item, "selection_strength") is not None
                and not bool(_read(item, "is_rejected", False))
            ),
        )
        for candidate in raw_candidates
    )
    target = _target_from(result, state, membership)
    original_decision = _result_decision(result) if result is not None else "NO DECISION"
    if incomplete:
        outcome = "INCOMPLETE"
        decision = "NO DECISION"
        primary = None
        secondaries: tuple[dict[str, object], ...] = ()
        avoid = None
    elif withdrawn:
        outcome = "WITHDRAWN"
        decision = "WITHDRAWN"
        primary = None
        secondaries = ()
        avoid = None
    elif research:
        decision = original_decision
        outcome = decision
        primary = (
            _candidate_payload(
                candidate,
                predictions=predictions,
                fixture_id=fixture_id,
                evidence_gaps=gaps,
                evidence_conflicts=conflicts,
                research=True,
                rankable_count=len(candidate_rows),
            )
            if (candidate := _research_candidate(result)) is not None
            else None
        )
        secondaries = tuple(
            _candidate_payload(
                candidate,
                predictions=predictions,
                fixture_id=fixture_id,
                evidence_gaps=gaps,
                evidence_conflicts=conflicts,
                research=True,
                rankable_count=len(candidate_rows),
            )
            for candidate in _research_secondaries(result)
        )
        avoid = _avoid_payload(result, candidate_rows, research=True)
    else:
        decision = original_decision
        outcome = decision
        primary = (
            _candidate_payload(
                candidate,
                predictions=predictions,
                fixture_id=fixture_id,
                evidence_gaps=gaps,
                evidence_conflicts=conflicts,
                rankable_count=len(candidate_rows),
            )
            if (candidate := _production_primary(result)) is not None
            else None
        )
        secondaries = tuple(
            _candidate_payload(
                candidate,
                predictions=predictions,
                fixture_id=fixture_id,
                evidence_gaps=gaps,
                evidence_conflicts=conflicts,
                rankable_count=len(candidate_rows),
            )
            for candidate in _production_secondaries(result)
        )
        avoid = _avoid_payload(result, candidate_rows, research=False)
    settlement_result = "VOID" if withdrawn else None
    payload: dict[str, object] = {
        "fixture_id": fixture_id,
        "target": _target_payload(target),
        "membership": _to_dict(membership),
        "membership_state": _membership_state(membership),
        "outcome": outcome,
        "decision": decision,
        "original_decision": original_decision if withdrawn else None,
        "settlement_result": settlement_result,
        "primary_recommendation": primary if not research and not withdrawn else None,
        "primary_candidate": primary if research and not withdrawn else None,
        "correlated_secondary_fits": secondaries if not research and not withdrawn else (),
        "correlated_secondary_candidates": secondaries if research and not withdrawn else (),
        "avoid": avoid,
        "preference_results": candidate_rows,
        "evidence": evidence,
        "evidence_identities": identities,
        "material_evidence_gaps": tuple(
            gap
            for gap in gaps
            if bool(gap.get("decision_materiality", gap.get("blocks_family", True)))
        ),
        "material_evidence_conflicts": tuple(
            conflict for conflict in conflicts if bool(conflict.get("material", True))
        ),
        "evidence_state_digest": str(
            _read(result, "evidence_state_digest", identities.get("state_digest", ""))
        ),
        "vetting_audit_digest": str(_read(result, "audit_digest", ""))
        if result is not None
        else "",
        "policy_version": str(_read(result, "policy_version", "UNSPECIFIED"))
        if result is not None
        else "UNSPECIFIED",
        "policy_digest": str(_read(result, "policy_digest", "UNSPECIFIED"))
        if result is not None
        else "UNSPECIFIED",
    }
    return cast(dict[str, object], _jsonable(payload))


def _run_is_complete(run_status: object | None) -> tuple[bool, tuple[str, ...]]:
    if run_status is None:
        return True, ()
    state = _token(_read(run_status, "state", "INCOMPLETE"))
    completed = _read(run_status, "completed_work_units", None)
    total = _read(run_status, "total_work_units", None)
    reasons: list[str] = []
    if state != PublicationState.COMPLETE.value:
        reasons.append("RUN_NOT_COMPLETE")
    if isinstance(completed, int) and isinstance(total, int) and completed != total:
        reasons.append("RUN_WORK_UNITS_INCOMPLETE")
    if reasons:
        checkpoint = _read(run_status, "last_checkpoint", "none")
        reasons.append(f"LAST_CHECKPOINT:{checkpoint}")
    return not reasons, tuple(reasons)


def _normalise_memberships(memberships: object) -> tuple[object, ...]:
    nested = _read(memberships, "memberships", None)
    return _sequence(nested if nested is not None else memberships)


def _normalise_vetting(vetting: Mapping[str, object] | Iterable[object]) -> dict[str, object]:
    nested = _read(vetting, "matches", None)
    if nested is not None:
        vetting = cast(Iterable[object], nested)
    if isinstance(vetting, Mapping):
        return {str(key): value for key, value in vetting.items()}
    selected: dict[str, object] = {}
    for result in vetting:
        target = _read(result, "target")
        fixture_id = str(_read(target, "fixture_id", _read(result, "fixture_id", "")))
        if fixture_id:
            selected[fixture_id] = result
    return selected


def _freeze_reproducibility(value: object, matchweek_id: str) -> dict[str, object]:
    """Project T05 freeze identities into the T16 reproducibility record."""

    metadata: dict[str, object] = {"matchweek_id": matchweek_id}
    window = _read(value, "window")
    if window is not None:
        metadata.update(
            {
                "window_start_local": _read(window, "start_local", "UNSPECIFIED"),
                "window_end_local": _read(window, "end_local", "UNSPECIFIED"),
                "display_timezone": str(_read(window, "timezone", AFRICA_LAGOS)),
            }
        )
    cutoff = _read(value, "cutoff")
    if cutoff is not None:
        metadata.update(
            {
                "retrieval_cutoff_id": _read(cutoff, "cutoff_id", "UNSPECIFIED"),
                "retrieval_cutoff": _read(cutoff, "cutoff_utc", "UNSPECIFIED"),
                "matchweek_research_cutoff_utc": _read(cutoff, "cutoff_utc", "UNSPECIFIED"),
                "research_cutoff_digest": _read(cutoff, "digest", "UNSPECIFIED"),
            }
        )
    for source_key, target_key in (
        ("snapshot_manifest_digest", "matchweek_snapshot_digest"),
        ("membership_manifest_digest", "matchweek_membership_manifest_digest"),
        ("revision_snapshot_digest", "revision_snapshot_digest"),
    ):
        selected = _read(value, source_key)
        if selected not in (None, ""):
            metadata[target_key] = selected
    season = _read(value, "season")
    if season not in (None, ""):
        metadata["season"] = season
    return metadata


def _evidence_version_metadata(states: Mapping[str, object]) -> dict[str, object]:
    versions: dict[str, object] = {}
    for fixture_id, state in sorted(states.items()):
        values: dict[str, object] = {}
        for key in (
            "catalog_name",
            "catalog_version",
            "catalog_digest",
            "feature_rules_name",
            "feature_rules_digest",
            "research_rules_name",
            "research_rules_digest",
            "artifact_digest",
            "manifest_digest",
            "state_digest",
        ):
            value = _read(state, key)
            if value not in (None, ""):
                values[key] = _jsonable(value)
        if values:
            versions[fixture_id] = values
    return versions


def _prediction_version_metadata(predictions: Mapping[str, object]) -> dict[str, object]:
    versions: dict[str, object] = {}
    for fixture_id, value in sorted(predictions.items()):
        groups = _prediction_groups(value, fixture_id)
        rows: list[dict[str, object]] = []
        for group in groups:
            row = {
                key: group.get(key)
                for key in (
                    "model_version",
                    "model_digest",
                    "calibration_version",
                    "prediction_digest",
                )
                if group.get(key) not in (None, "")
            }
            if row and row not in rows:
                rows.append(row)
        if rows:
            versions[fixture_id] = tuple(rows)
    return versions


def _prediction_identity_digests(predictions: Mapping[str, object]) -> tuple[str, ...]:
    digests: set[str] = set()
    for fixture_id, value in sorted(predictions.items()):
        for group in _prediction_groups(value, fixture_id):
            for key in ("prediction_digest", "model_digest"):
                selected = group.get(key)
                if selected not in (None, ""):
                    digests.add(str(selected))
    return tuple(sorted(digests))


def _default_reproducibility(
    matchweek_id: str, policy: object | None, metadata: Mapping[str, object]
) -> dict[str, object]:
    supplied_policy = metadata.get("selection_policy")
    policy_details = (
        cast(dict[str, object], _jsonable(supplied_policy))
        if isinstance(supplied_policy, Mapping)
        else _policy_info(policy, None)
    )
    window = {
        "start_local": metadata.get("window_start_local", "UNSPECIFIED"),
        "end_local": metadata.get("window_end_local", "UNSPECIFIED"),
        "display_timezone": metadata.get("display_timezone", AFRICA_LAGOS),
    }
    software_commit = metadata.get("software_commit", "UNSPECIFIED")
    result = {
        "matchweek_id": matchweek_id,
        "window": window,
        "matchweek_date_window": window,
        "target_league_set": metadata.get("target_league_set", DEFAULT_TARGET_LEAGUE_SET),
        "target_league_set_version": metadata.get(
            "target_league_set_version", "2026-27-target-leagues-v1"
        ),
        "preference_set": {
            "version": DEFAULT_PREFERENCE_CATALOG.version,
            "digest": DEFAULT_PREFERENCE_CATALOG.digest,
        },
        "selection_policy": policy_details,
        "model_version": metadata.get("model_version", "UNSPECIFIED"),
        "model_ensemble_version": metadata.get(
            "model_ensemble_version", metadata.get("model_version", "UNSPECIFIED")
        ),
        "feature_version": metadata.get("feature_version", "UNSPECIFIED"),
        "research_rules_version": metadata.get("research_rules_version", "UNSPECIFIED"),
        "data_snapshot_digest": metadata.get("data_snapshot_digest", "UNSPECIFIED"),
        "data_snapshot_id": metadata.get(
            "data_snapshot_id", metadata.get("data_snapshot_digest", "UNSPECIFIED")
        ),
        "retrieval_cutoff": metadata.get(
            "retrieval_cutoff", metadata.get("matchweek_research_cutoff_utc", "UNSPECIFIED")
        ),
        "retrieval_cutoff_id": metadata.get(
            "retrieval_cutoff_id",
            metadata.get(
                "retrieval_cutoff", metadata.get("matchweek_research_cutoff_utc", "UNSPECIFIED")
            ),
        ),
        "matchweek_research_cutoff_utc": metadata.get(
            "matchweek_research_cutoff_utc", "UNSPECIFIED"
        ),
        "canonical_timestamps": "UTC",
        "canonical_timestamp_rule": metadata.get(
            "canonical_timestamp_rule", "UTC event timestamps; deterministic sort by fixture_id"
        ),
        "display_timezone": metadata.get("display_timezone", AFRICA_LAGOS),
        "software_commit": software_commit,
        "software": {"commit": software_commit},
        "matchweek_membership_manifest_digest": metadata.get(
            "matchweek_membership_manifest_digest",
            metadata.get("membership_manifest_digest", "UNSPECIFIED"),
        ),
        "matchweek_snapshot_digest": metadata.get(
            "matchweek_snapshot_digest",
            metadata.get("data_snapshot_digest", "UNSPECIFIED"),
        ),
    }
    for key, value in metadata.items():
        if key not in result and key != "window_start_local" and key != "window_end_local":
            result[str(key)] = _jsonable(value)
    return cast(dict[str, object], _jsonable(result))


@dataclass(frozen=True)
class MatchweekAudit:
    """A canonical, schema-versioned T16 audit payload."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        normalized = cast(dict[str, object], _jsonable(self.payload))
        if (
            normalized.get("schema_version") != T16_SCHEMA_VERSION
            or normalized.get("schema") != T16_AUDIT_SCHEMA
        ):
            raise T16ValidationError("Unsupported Matchweek Audit schema.")
        supplied = normalized.get("audit_digest")
        without = {key: value for key, value in normalized.items() if key != "audit_digest"}
        expected = _digest(without)
        if supplied != expected:
            raise T16IntegrityError("Matchweek Audit digest does not match its content.")
        expected_audit_id = f"audit-{_digest({**without, 'audit_id': ''})[:16]}"
        if normalized.get("audit_id") != expected_audit_id:
            raise T16IntegrityError("Matchweek Audit ID does not match its content.")
        try:
            PublicationState(str(normalized.get("publication_state")))
            AuditMode(str(normalized.get("mode")))
        except ValueError as error:
            raise T16ValidationError(
                "Matchweek Audit publication state or mode is invalid."
            ) from error
        preference_set = normalized.get("preference_set")
        if not isinstance(preference_set, Mapping):
            raise T16ValidationError("Matchweek Audit preference set is malformed.")
        preferences = preference_set.get("preferences")
        if not isinstance(preferences, list) or preference_set.get("count") != len(preferences):
            raise T16ValidationError("Matchweek Audit preference set count is invalid.")
        if preference_set.get("count") != T16_EXPECTED_PREFERENCE_COUNT:
            raise T16ValidationError("Matchweek Audit must use all 37 preferences.")
        preference_ids = tuple(
            str(item.get("preference_id"))
            for item in preferences
            if isinstance(item, Mapping) and item.get("preference_id") not in (None, "")
        )
        if len(preference_ids) != len(preferences) or len(set(preference_ids)) != len(
            preference_ids
        ):
            raise T16ValidationError("Matchweek Audit preference identities are invalid.")
        if normalized.get("publication_state") == PublicationState.COMPLETE.value:
            expected_count = preference_set.get("count")
            matches = normalized.get("matches")
            if not isinstance(expected_count, int) or not isinstance(matches, list):
                raise T16ValidationError("Complete Matchweek Audit coverage is malformed.")
            if any(
                not isinstance(match, Mapping)
                or not isinstance(match.get("preference_results"), list)
                or len(match["preference_results"]) != expected_count
                for match in matches
            ):
                raise T16ValidationError(
                    "Complete Matchweek Audit must retain every preference result per match."
                )
            fixture_ids: list[str] = []
            for match in matches:
                if not isinstance(match, Mapping):
                    continue
                fixture_id = match.get("fixture_id")
                if fixture_id in (None, ""):
                    raise T16ValidationError("Complete Matchweek Audit match IDs are invalid.")
                fixture_ids.append(str(fixture_id))
                rows = match.get("preference_results")
                if not isinstance(rows, list):
                    continue
                row_ids = tuple(
                    str(row.get("preference", {}).get("preference_id"))
                    for row in rows
                    if isinstance(row, Mapping)
                    and isinstance(row.get("preference"), Mapping)
                    and row["preference"].get("preference_id") not in (None, "")
                )
                if row_ids != preference_ids:
                    raise T16ValidationError(
                        "Complete Matchweek Audit preference matrices do not match the catalog."
                    )
            if len(set(fixture_ids)) != len(fixture_ids):
                raise T16ValidationError("Complete Matchweek Audit contains duplicate matches.")
            matrix = normalized.get("preference_matrix")
            if not isinstance(matrix, Mapping):
                raise T16ValidationError("Complete Matchweek Audit preference matrix is missing.")
            for match in matches:
                assert isinstance(match, Mapping)
                fixture_id = str(match["fixture_id"])
                if _canonical_json(matrix.get(fixture_id)) != _canonical_json(
                    match.get("preference_results")
                ):
                    raise T16ValidationError(
                        "Complete Matchweek Audit preference matrix is inconsistent."
                    )
            mode = AuditMode(str(normalized["mode"]))
            for match in matches:
                assert isinstance(match, Mapping)
                outcome = str(match.get("outcome"))
                if mode is AuditMode.PRODUCTION:
                    if match.get("primary_candidate") is not None:
                        raise T16ValidationError(
                            "Production Matchweek Audits cannot carry research candidates."
                        )
                    if outcome == MatchDecision.PLAY.value and (
                        match.get("primary_recommendation") is None
                        or match.get("decision") != MatchDecision.PLAY.value
                    ):
                        raise T16ValidationError(
                            "Production PLAY must carry one Primary Recommendation."
                        )
                else:
                    if match.get("primary_recommendation") is not None or match.get(
                        "correlated_secondary_fits"
                    ):
                        raise T16ValidationError(
                            "Research-only Matchweek Audits cannot carry production fits."
                        )
                    if outcome in {
                        MatchDecision.PLAY.value,
                        MatchDecision.AVOID_MATCH.value,
                    }:
                        raise T16ValidationError(
                            "Research-only Matchweek Audits cannot carry production decisions."
                        )
        object.__setattr__(self, "payload", normalized)

    @property
    def audit_id(self) -> str:
        return str(self.payload["audit_id"])

    @property
    def audit_digest(self) -> str:
        return str(self.payload["audit_digest"])

    @property
    def publication_state(self) -> PublicationState:
        return PublicationState(str(self.payload["publication_state"]))

    @property
    def mode(self) -> AuditMode:
        return AuditMode(str(self.payload["mode"]))

    @property
    def matches(self) -> tuple[dict[str, object], ...]:
        return tuple(
            cast(dict[str, object], item)
            for item in cast(Sequence[object], self.payload["matches"])
        )

    @property
    def coverage(self) -> dict[str, object]:
        return cast(dict[str, object], self.payload["coverage"])

    @property
    def reproducibility(self) -> dict[str, object]:
        return cast(dict[str, object], self.payload["reproducibility"])

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(self.payload))

    def to_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MatchweekAudit:
        return cls(value)


def build_matchweek_audit(
    matchweek_id: str,
    memberships: Iterable[object] | object,
    vetting: Mapping[str, object] | Iterable[object],
    *,
    evidence_states: Mapping[str, object] | None = None,
    predictions: Mapping[str, object] | None = None,
    policy: object | None = None,
    appendix: Iterable[object] = (),
    withdrawn_fixture_ids: Iterable[str] = (),
    void_fixture_ids: Iterable[str] = (),
    reproducibility: Mapping[str, object] | None = None,
    run_status: object | None = None,
    catalog: PreferenceCatalog = DEFAULT_PREFERENCE_CATALOG,
) -> MatchweekAudit:
    """Build a complete or explicitly incomplete audit without publishing it."""

    selected_matchweek = _text(matchweek_id, "Matchweek ID")
    if len(catalog) != T16_EXPECTED_PREFERENCE_COUNT:
        raise T16ValidationError("T16 requires the complete 37-preference active Preference Set.")
    membership_rows = _normalise_memberships(memberships)
    vetting_by_fixture = _normalise_vetting(vetting)
    state_by_fixture = {str(key): value for key, value in (evidence_states or {}).items()}
    prediction_by_fixture = {str(key): value for key, value in (predictions or {}).items()}
    appendix_rows = tuple(appendix)
    if not appendix_rows:
        appendix_rows = _sequence(_read(memberships, "appendix", ()))
    withdrawn_ids = _appendix_withdrawn(appendix_rows)
    withdrawn_ids.update(str(item) for item in withdrawn_fixture_ids)
    withdrawn_ids.update(str(item) for item in void_fixture_ids)
    complete_run, run_reasons = _run_is_complete(run_status)
    included = tuple(
        sorted(
            (item for item in membership_rows if _is_target_membership(item)), key=_membership_id
        )
    )
    included_ids = tuple(_membership_id(item) for item in included)
    indeterminate = tuple(
        sorted(
            (
                item
                for item in membership_rows
                if _membership_state(item) == MembershipState.INDETERMINATE.value
            ),
            key=_membership_id,
        )
    )
    excluded = tuple(
        sorted(
            (
                item
                for item in membership_rows
                if not _is_target_membership(item)
                and _membership_state(item) != MembershipState.INDETERMINATE.value
            ),
            key=_membership_id,
        )
    )
    result_values = tuple(vetting_by_fixture.values())
    statuses = {_policy_status(None, item) for item in result_values if item is not None}
    if PolicyStatus.RESEARCH_ONLY.value in statuses:
        selected_status = PolicyStatus.RESEARCH_ONLY.value
    elif PolicyStatus.PRODUCTION_PROMOTED.value in statuses:
        selected_status = PolicyStatus.PRODUCTION_PROMOTED.value
    else:
        selected_status = _policy_status(policy, None)
    incomplete_reasons = list(run_reasons)
    if len(set(included_ids)) != len(included_ids):
        incomplete_reasons.append("DUPLICATE_TARGET_MATCH_IDS")
    if len(statuses) > 1:
        incomplete_reasons.append("MIXED_POLICY_MODES")
    if selected_status not in {
        PolicyStatus.RESEARCH_ONLY.value,
        PolicyStatus.PRODUCTION_PROMOTED.value,
    }:
        incomplete_reasons.append(f"INVALID_POLICY_MODE:{selected_status}")
        selected_status = PolicyStatus.RESEARCH_ONLY.value
    if policy is not None:
        expected_status = _policy_status(policy, None)
        if statuses and any(status != expected_status for status in statuses):
            incomplete_reasons.append("POLICY_MODE_MISMATCH")
        expected_version = _read(policy, "version")
        if expected_version not in (None, "") and any(
            _read(item, "policy_version") != expected_version
            for item in result_values
            if item is not None
        ):
            incomplete_reasons.append("POLICY_VERSION_MISMATCH")
    for result in result_values:
        if result is None:
            continue
        result_status = _policy_status(None, result)
        result_decision = _result_decision(result)
        allowed_decisions = (
            {MatchDecision.RESEARCH_ONLY.value, MatchDecision.RESEARCH_AVOID.value}
            if result_status == PolicyStatus.RESEARCH_ONLY.value
            else {MatchDecision.PLAY.value, MatchDecision.AVOID_MATCH.value}
        )
        if (
            result_status
            not in {
                PolicyStatus.RESEARCH_ONLY.value,
                PolicyStatus.PRODUCTION_PROMOTED.value,
            }
            or result_decision not in allowed_decisions
        ):
            incomplete_reasons.append(f"DECISION_MODE_MISMATCH:{result_status}:{result_decision}")
    match_payloads: list[dict[str, object]] = []
    for membership in included:
        fixture_id = _membership_id(membership)
        result = vetting_by_fixture.get(fixture_id)
        state = state_by_fixture.get(fixture_id)
        actual_fixture_id = _fixture_id(result, state, membership)
        if actual_fixture_id != fixture_id:
            incomplete_reasons.append(f"FIXTURE_ID_MISMATCH:{fixture_id}")
        rows = _sequence(_read(result, "preference_results", ())) if result is not None else ()
        preference_ids = tuple(
            str(_read(_read(row, "preference"), "preference_id", "")) for row in rows
        )
        if result is None:
            incomplete_reasons.append(f"MISSING_VETTING:{fixture_id}")
        if state is None:
            incomplete_reasons.append(f"MISSING_EVIDENCE_STATE:{fixture_id}")
        if len(rows) != len(catalog):
            incomplete_reasons.append(f"PREFERENCE_COUNT:{fixture_id}:{len(rows)}:{len(catalog)}")
        if set(preference_ids) != {item.preference_id for item in catalog}:
            incomplete_reasons.append(f"PREFERENCE_MATRIX:{fixture_id}")
        match_payloads.append(
            _match_payload(
                membership,
                result,
                state,
                prediction_by_fixture.get(fixture_id, {}),
                research=selected_status != PolicyStatus.PRODUCTION_PROMOTED.value,
                incomplete=not complete_run,
                withdrawn=fixture_id in withdrawn_ids,
                catalog=catalog,
            )
        )
    complete = not incomplete_reasons
    if not complete:
        match_payloads = [
            {
                **match,
                "outcome": "INCOMPLETE",
                "decision": "NO DECISION",
                "original_decision": None,
                "primary_recommendation": None,
                "primary_candidate": None,
                "correlated_secondary_fits": (),
                "correlated_secondary_candidates": (),
                "avoid": None,
            }
            for match in match_payloads
        ]
    metadata = _freeze_reproducibility(memberships, selected_matchweek)
    evidence_reproducibility = {
        fixture_id: _read(state, "reproducibility", {})
        for fixture_id, state in sorted(state_by_fixture.items())
        if _read(state, "reproducibility", {})
    }
    if evidence_reproducibility:
        metadata["evidence_reproducibility"] = evidence_reproducibility
    evidence_versions = _evidence_version_metadata(state_by_fixture)
    if evidence_versions:
        metadata["evidence_state_versions"] = evidence_versions
    prediction_versions = _prediction_version_metadata(prediction_by_fixture)
    if prediction_versions:
        metadata["prediction_versions"] = prediction_versions
    policy_payload = _policy_info(policy, result_values[0] if result_values else None)
    metadata.update(reproducibility or {})
    metadata.setdefault("selection_policy", policy_payload)
    reproducibility_payload = _default_reproducibility(selected_matchweek, policy, metadata)
    if selected_status == PolicyStatus.PRODUCTION_PROMOTED.value:
        mode = AuditMode.PRODUCTION.value
    else:
        mode = AuditMode.RESEARCH_ONLY.value
    core: dict[str, object] = {
        "schema": T16_AUDIT_SCHEMA,
        "schema_version": T16_SCHEMA_VERSION,
        "publication_state": PublicationState.COMPLETE.value
        if complete
        else PublicationState.INCOMPLETE.value,
        "mode": mode,
        "matchweek_id": selected_matchweek,
        "coverage": {
            "complete": complete,
            "included_target_matches": len(included),
            "evaluated_target_matches": sum(
                len(cast(Sequence[object], item["preference_results"])) == len(catalog)
                for item in match_payloads
            ),
            "expected_preference_results_per_match": len(catalog),
            "retained_preference_results": sum(
                len(cast(Sequence[object], item["preference_results"])) for item in match_payloads
            ),
            "indeterminate_memberships": tuple(_membership_id(item) for item in indeterminate),
            "excluded_memberships": tuple(_membership_id(item) for item in excluded),
            "withdrawn_fixture_ids": tuple(sorted(withdrawn_ids)),
            "incomplete_reasons": tuple(sorted(set(incomplete_reasons))),
        },
        "preference_set": {
            "name": catalog.name,
            "version": catalog.version,
            "digest": catalog.digest,
            "count": len(catalog),
            "preferences": tuple(item.to_dict() for item in catalog),
        },
        "selection_policy": policy_payload,
        "reproducibility": reproducibility_payload,
        "memberships": tuple(
            _to_dict(item) for item in sorted(membership_rows, key=_membership_id)
        ),
        "appendix": tuple(
            _to_dict(item)
            for item in sorted(
                appendix_rows,
                key=lambda item: str(_read(item, "event_key", _read(item, "appendix_id", ""))),
            )
        ),
        "matches": tuple(match_payloads),
        "preference_matrix": {
            str(match["fixture_id"]): match["preference_results"] for match in match_payloads
        },
        "audit_references": {
            "evidence_state_digests": tuple(
                sorted(
                    str(match.get("evidence_state_digest", ""))
                    for match in match_payloads
                    if match.get("evidence_state_digest")
                )
            ),
            "evidence_artifact_digests": tuple(
                sorted(
                    str(_read(state, "artifact_digest"))
                    for state in state_by_fixture.values()
                    if _read(state, "artifact_digest")
                )
            ),
            "evidence_manifest_digests": tuple(
                sorted(
                    str(_read(state, "manifest_digest"))
                    for state in state_by_fixture.values()
                    if _read(state, "manifest_digest")
                )
            ),
            "prediction_digests": _prediction_identity_digests(prediction_by_fixture),
            "membership_digests": tuple(
                sorted(
                    str(_read(item, "digest", ""))
                    for item in membership_rows
                    if _read(item, "digest", "")
                )
            ),
            "fixture_revision_digests": tuple(
                sorted(
                    str(_read(item, "controlling_revision_digest", ""))
                    for item in membership_rows
                    if _read(item, "controlling_revision_digest", "")
                )
            ),
        },
        "run": {
            "run_id": _read(run_status, "run_id") if run_status is not None else None,
            "state": _read(run_status, "state")
            if run_status is not None
            else ("COMPLETE" if complete else "INCOMPLETE"),
            "last_checkpoint": _read(run_status, "last_checkpoint", "none")
            if run_status is not None
            else "none",
        },
    }
    pre_digest = _digest({**core, "audit_id": ""})
    core["audit_id"] = f"audit-{pre_digest[:16]}"
    audit_digest = _digest(core)
    core["audit_digest"] = audit_digest
    return MatchweekAudit(core)


def _coerce_audit(value: MatchweekAudit | Mapping[str, object]) -> MatchweekAudit:
    return value if isinstance(value, MatchweekAudit) else MatchweekAudit.from_dict(value)


def build_report_payload(audit: MatchweekAudit | Mapping[str, object]) -> dict[str, object]:
    """Return the concise report projection; the Vetting Matrix stays in the audit."""

    selected = _coerce_audit(audit)
    if selected.publication_state is PublicationState.INCOMPLETE:
        return {
            "schema": T16_REPORT_SCHEMA,
            "schema_version": T16_SCHEMA_VERSION,
            "publication_state": PublicationState.INCOMPLETE.value,
            "status": "INCOMPLETE",
            "decision_state": "NO DECISION",
            "mode": AuditMode.RESEARCH_ONLY.value,
            "matchweek_id": selected.payload["matchweek_id"],
            "completion": selected.coverage,
            "matches": (),
            "audit_reference": {
                "audit_id": selected.audit_id,
                "audit_digest": selected.audit_digest,
            },
        }
    matches: list[dict[str, object]] = []
    for match in selected.matches:
        summary: dict[str, object] = {
            "fixture_id": match["fixture_id"],
            "target": match["target"],
            "outcome": match["outcome"],
            "settlement_result": match.get("settlement_result"),
        }
        if selected.mode is AuditMode.PRODUCTION:
            summary.update(
                {
                    "primary_recommendation": match.get("primary_recommendation"),
                    "correlated_secondary_fits": match.get("correlated_secondary_fits", ()),
                    "avoid": match.get("avoid"),
                }
            )
        else:
            summary.update(
                {
                    "research_candidate": match.get("primary_candidate"),
                    "correlated_secondary_candidates": match.get(
                        "correlated_secondary_candidates", ()
                    ),
                    "research_avoid": match.get("avoid"),
                }
            )
        matches.append(cast(dict[str, object], _jsonable(summary)))
    return {
        "schema": T16_REPORT_SCHEMA,
        "schema_version": T16_SCHEMA_VERSION,
        "publication_state": PublicationState.COMPLETE.value,
        "status": "COMPLETE",
        "mode": selected.mode.value,
        "matchweek_id": selected.payload["matchweek_id"],
        "completion": selected.coverage,
        "selection_policy": selected.payload["selection_policy"],
        "matches": tuple(matches),
        "audit_reference": {"audit_id": selected.audit_id, "audit_digest": selected.audit_digest},
    }


def _number(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _detail(value: object) -> str:
    if isinstance(value, (Mapping, tuple, list)):
        return _canonical_json(value).decode("utf-8")
    return str(value)


def _match_title(match: Mapping[str, object]) -> str:
    target = match.get("target")
    row = target if isinstance(target, Mapping) else {}
    home = row.get("home_team_id", "UNKNOWN")
    away = row.get("away_team_id", "UNKNOWN")
    return f"{home} v {away} ({match.get('fixture_id', 'UNKNOWN')})"


def _render_card(card: Mapping[str, object], heading: str, *, indent: str = "") -> list[str]:
    risk = card.get("risk_assessment")
    risk_row = risk if isinstance(risk, Mapping) else {}
    uncertainty = card.get("uncertainty")
    uncertainty_row = uncertainty if isinstance(uncertainty, Mapping) else {}
    gap_count = len(_sequence(card.get("material_evidence_gaps", ())))
    conflict_count = len(_sequence(card.get("material_evidence_conflicts", ())))
    lines = [
        f"{indent}### {heading}: {card.get('exact_preference', 'UNKNOWN')}",
        f"{indent}- Exact preference/line: {card.get('exact_preference', 'UNKNOWN')}",
        f"{indent}- Estimated Probability: {_number(card.get('estimated_probability'))}",
        f"{indent}- Conservative Probability: {_number(card.get('conservative_probability'))}",
        f"{indent}- uncertainty: {_number(uncertainty_row.get('width'))}",
        f"{indent}- Data Quality: {_number(card.get('data_quality'))}",
        f"{indent}- Model Agreement: {_number(card.get('model_agreement'))}",
        f"{indent}- risk/failure assessment: {_number(risk_row.get('failure_risk'))}; "
        f"{risk_row.get('failure_case', 'UNKNOWN')}",
        f"{indent}- strongest supporting case: "
        f"{card.get('strongest_supporting_case') or 'UNKNOWN'}",
        f"{indent}- strongest credible failure case: "
        f"{card.get('strongest_credible_failure_case') or 'UNKNOWN'}",
        f"{indent}- material evidence gaps/conflicts: {gap_count}/{conflict_count}",
        f"{indent}- historical baseline: {_detail(card.get('historical_baseline') or 'UNKNOWN')}",
        f"{indent}- Selection Strength: {_number(card.get('selection_strength'))}",
        f"{indent}- why it ranked above alternatives: "
        f"{card.get('why_ranked_above_alternatives', 'UNKNOWN')}",
    ]
    return lines


def render_markdown_report(audit: MatchweekAudit | Mapping[str, object]) -> str:
    """Render deterministic UTF-8 Markdown with strict mode-specific language."""

    selected = _coerce_audit(audit)
    lines = ["# matchvet report", ""]
    if selected.publication_state is PublicationState.INCOMPLETE:
        lines.extend(
            (
                "## INCOMPLETE — NO DECISION",
                "",
                "This run is incomplete. No production decision is published.",
                "",
                f"- Matchweek: {selected.payload['matchweek_id']}",
                f"- Last checkpoint: "
                f"{cast(Mapping[str, object], selected.payload['run'])['last_checkpoint']}",
                f"- Audit: {selected.audit_id} ({selected.audit_digest})",
                "",
            )
        )
        return "\n".join(lines)
    if selected.mode is AuditMode.RESEARCH_ONLY:
        lines.extend(
            (
                "## RESEARCH ONLY — NOT A RECOMMENDATION",
                "",
                f"Matchweek: {selected.payload['matchweek_id']}",
                "",
            )
        )
        for match in selected.matches:
            lines.append(f"### {_match_title(match)}")
            if match["outcome"] == "WITHDRAWN":
                lines.append("- Withdrawn / VOID — no production or research settlement.")
            elif match["outcome"] == MatchDecision.RESEARCH_AVOID.value:
                avoid_value = match.get("avoid")
                avoid = avoid_value if isinstance(avoid_value, Mapping) else {}
                lines.append(
                    f"- RESEARCH AVOID: {avoid.get('category', 'UNKNOWN')} — "
                    f"{avoid.get('reason_code', 'UNKNOWN')}"
                )
            elif match.get("primary_candidate") is not None:
                lines.extend(
                    _render_card(
                        cast(Mapping[str, object], match["primary_candidate"]),
                        "Primary Candidate (RESEARCH ONLY)",
                    )
                )
                candidates = match.get("correlated_secondary_candidates", ())
                if candidates:
                    lines.append("- Correlated Secondary Candidates:")
                    for candidate in cast(Sequence[Mapping[str, object]], candidates):
                        lines.append(f"  - {candidate.get('exact_preference', 'UNKNOWN')}")
            else:
                lines.append("- RESEARCH ONLY: no ranked candidate")
            lines.append("")
        lines.extend(("## Withdrawn / VOID", ""))
        for match in selected.matches:
            if match["outcome"] == "WITHDRAWN":
                lines.append(f"- Withdrawn / VOID — {_match_title(match)}")
        indeterminate = _sequence(selected.coverage.get("indeterminate_memberships", ()))
        if indeterminate:
            lines.extend(("", "## INDETERMINATE", ""))
            for membership_id in indeterminate:
                lines.append(f"- INDETERMINATE — {membership_id} — NO DECISION")
        lines.extend(
            (
                "## Audit Reference",
                "",
                f"- Audit: {selected.audit_id}",
                f"- Digest: {selected.audit_digest}",
                "",
            )
        )
        return "\n".join(lines)
    lines.extend(
        (
            "## COMPLETE",
            "",
            f"Matchweek: {selected.payload['matchweek_id']}",
            f"Policy: "
            f"{cast(Mapping[str, object], selected.payload['selection_policy'])['version']}",
            "",
            "## PLAY",
            "",
        )
    )
    for match in selected.matches:
        if match["outcome"] != MatchDecision.PLAY.value:
            continue
        lines.append(f"### {_match_title(match)}")
        primary = match.get("primary_recommendation")
        if primary is not None:
            lines.extend(
                _render_card(cast(Mapping[str, object], primary), "Primary Recommendation")
            )
        secondaries = match.get("correlated_secondary_fits", ())
        if secondaries:
            lines.append("- Correlated Secondary Fits:")
            for candidate in cast(Sequence[Mapping[str, object]], secondaries):
                lines.append(f"  - {candidate.get('exact_preference', 'UNKNOWN')}")
        lines.append("")
    lines.extend(("## AVOID", ""))
    for match in selected.matches:
        if match["outcome"] == MatchDecision.AVOID_MATCH.value:
            avoid_value = match.get("avoid")
            avoid = avoid_value if isinstance(avoid_value, Mapping) else {}
            lines.append(
                f"- AVOID MATCH — {_match_title(match)} — {avoid.get('category', 'UNKNOWN')} — "
                f"{avoid.get('reason_code', 'UNKNOWN')}"
            )
    lines.append("")
    lines.extend(("## Withdrawn / VOID", ""))
    for match in selected.matches:
        if match["outcome"] == "WITHDRAWN":
            lines.append(f"- Withdrawn / VOID — {_match_title(match)}")
    indeterminate = _sequence(selected.coverage.get("indeterminate_memberships", ()))
    if indeterminate:
        lines.extend(("", "## INDETERMINATE", ""))
        for membership_id in indeterminate:
            lines.append(f"- INDETERMINATE — {membership_id} — NO DECISION")
    lines.extend(
        (
            "",
            "## Audit Reference",
            "",
            f"- Audit: {selected.audit_id}",
            f"- Digest: {selected.audit_digest}",
            "",
        )
    )
    return "\n".join(lines)


render_report = render_markdown_report


@dataclass(frozen=True)
class T16Publication:
    publication_state: PublicationState
    matchweek_id: str
    audit_id: str
    audit_digest: str
    audit_artifact_digest: str
    report_artifact_digest: str
    publication_artifact_digest: str
    mode: AuditMode
    run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(self.__dict__))


def _run_is_persisted_incomplete(store: Store, run_id: str | None) -> bool:
    if not run_id:
        return False
    connection = cast(sqlite3.Connection, store._connection)
    row = connection.execute(
        "SELECT state FROM research_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    return row is not None and str(row[0]) != PublicationState.COMPLETE.value


def publish_matchweek_audit(
    audit: MatchweekAudit | Mapping[str, object],
    *,
    store: Store | None,
    run_id: str | None = None,
) -> T16Publication:
    """Publish audit, report, and a final visibility marker atomically by contract."""

    selected = _coerce_audit(audit)
    if selected.publication_state is not PublicationState.COMPLETE:
        raise T16IncompleteError("INCOMPLETE audit cannot publish a completed Matchweek Report.")
    if store is None:
        raise T16ValidationError("A writable private Store is required for publication.")
    if store.status.mode is not StoreMode.READ_WRITE:
        raise T16ValidationError("T16 publication requires a healthy writable Store.")
    if _run_is_persisted_incomplete(store, run_id):
        raise T16IncompleteError("The associated run is incomplete and cannot publish T16 output.")
    artifacts = ArtifactStore(store)
    try:
        audit_record = artifacts.publish_artifact(selected.to_bytes(), T16_AUDIT_MEDIA_TYPE)
        report_bytes = render_markdown_report(selected).encode("utf-8")
        report_record = artifacts.publish_artifact(report_bytes, T16_REPORT_MEDIA_TYPE)
        marker = {
            "schema": T16_PUBLICATION_SCHEMA,
            "schema_version": T16_SCHEMA_VERSION,
            "publication_state": PublicationState.COMPLETE.value,
            "matchweek_id": selected.payload["matchweek_id"],
            "audit_id": selected.audit_id,
            "audit_digest": selected.audit_digest,
            "audit_artifact_digest": audit_record.digest,
            "report_artifact_digest": report_record.digest,
            "mode": selected.mode.value,
            "run_id": run_id,
        }
        marker_record = artifacts.publish_artifact(
            _canonical_json(marker), T16_PUBLICATION_MEDIA_TYPE
        )
    except (ArtifactError, OSError, sqlite3.DatabaseError) as error:
        raise T16Error(f"Atomic T16 publication failed: {error}") from error
    return T16Publication(
        publication_state=PublicationState.COMPLETE,
        matchweek_id=str(selected.payload["matchweek_id"]),
        audit_id=selected.audit_id,
        audit_digest=selected.audit_digest,
        audit_artifact_digest=audit_record.digest,
        report_artifact_digest=report_record.digest,
        publication_artifact_digest=marker_record.digest,
        mode=selected.mode,
        run_id=run_id,
    )


publish_audit = publish_matchweek_audit


def _read_catalog(database_path: Path, private_root: Path | None) -> tuple[dict[str, object], ...]:
    del private_root
    path = database_path.resolve()
    if not path.exists():
        raise T16NotFoundError("The authoritative MatchVet Store is not configured.")
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.DatabaseError as error:
        raise T16IntegrityError("The authoritative Store is not readable.") from error
    try:
        rows = connection.execute(
            "SELECT digest, media_type, relative_path, created_at_utc "
            "FROM artifacts WHERE media_type = ? ORDER BY created_at_utc, digest",
            (T16_PUBLICATION_MEDIA_TYPE,),
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise T16IntegrityError("The artifact catalog is not readable.") from error
    finally:
        connection.close()
    publications: list[dict[str, object]] = []
    required_marker_keys = {
        "schema",
        "schema_version",
        "publication_state",
        "matchweek_id",
        "audit_id",
        "audit_digest",
        "audit_artifact_digest",
        "report_artifact_digest",
        "mode",
        "run_id",
    }
    for digest, media_type, relative_path, created_at in rows:
        if media_type != T16_PUBLICATION_MEDIA_TYPE:
            raise T16IntegrityError("A T16 publication artifact has an invalid media type.")
        object_path = (path.parent / str(relative_path)).resolve()
        if not object_path.is_relative_to(path.parent.resolve()) or not object_path.is_file():
            raise T16IntegrityError(f"T16 publication artifact {digest} is missing.")
        content = object_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != str(digest):
            raise T16IntegrityError(
                f"T16 publication artifact {digest} failed digest verification."
            )
        try:
            marker = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T16IntegrityError("A T16 publication marker is malformed.") from error
        if (
            not isinstance(marker, dict)
            or marker.get("schema") != T16_PUBLICATION_SCHEMA
            or marker.get("schema_version") != T16_SCHEMA_VERSION
            or marker.get("publication_state") != PublicationState.COMPLETE.value
            or set(marker) != required_marker_keys
        ):
            raise T16IntegrityError("A T16 publication marker has an invalid schema or state.")
        if _canonical_json(marker) != content:
            raise T16IntegrityError("A T16 publication marker is not canonical JSON.")
        try:
            AuditMode(str(marker["mode"]))
        except ValueError as error:
            raise T16IntegrityError("A T16 publication marker has an invalid mode.") from error
        for key in (
            "matchweek_id",
            "audit_id",
            "audit_digest",
            "audit_artifact_digest",
            "report_artifact_digest",
        ):
            value = marker[key]
            if not isinstance(value, str) or not value.strip():
                raise T16IntegrityError(f"A T16 publication marker has an invalid {key}.")
        selected = {str(key): value for key, value in marker.items()}
        selected["publication_artifact_digest"] = str(digest)
        selected["published_at_utc"] = str(created_at)
        publications.append(selected)
    return tuple(publications)


def _read_artifact(
    database_path: Path, digest: str, *, expected_media_type: str | None = None
) -> bytes:
    path = database_path.resolve()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT media_type, relative_path FROM artifacts WHERE digest = ?", (digest,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise T16IntegrityError(f"Referenced T16 artifact {digest} is not catalogued.")
    if expected_media_type is not None and str(row[0]) != expected_media_type:
        raise T16IntegrityError(f"Referenced T16 artifact {digest} has an invalid media type.")
    object_path = (path.parent / str(row[1])).resolve()
    if not object_path.is_relative_to(path.parent.resolve()) or not object_path.is_file():
        raise T16IntegrityError(f"Referenced T16 artifact {digest} is missing.")
    content = object_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise T16IntegrityError(f"Referenced T16 artifact {digest} failed verification.")
    return content


def _latest_publication(
    database_path: Path, private_root: Path | None, matchweek_id: str | None = None
) -> dict[str, object]:
    publications = _read_catalog(database_path, private_root)
    if matchweek_id is not None:
        publications = tuple(
            item for item in publications if str(item.get("matchweek_id")) == matchweek_id
        )
    if not publications:
        raise T16NotFoundError("No complete Matchweek Audit has been published.")
    return max(
        publications,
        key=lambda item: (
            str(item.get("published_at_utc", "")),
            str(item["publication_artifact_digest"]),
        ),
    )


def read_audit(
    database_path: Path, *, private_root: Path | None = None, matchweek_id: str | None = None
) -> MatchweekAudit:
    marker = _latest_publication(database_path, private_root, matchweek_id)
    content = _read_artifact(
        database_path,
        str(marker["audit_artifact_digest"]),
        expected_media_type=T16_AUDIT_MEDIA_TYPE,
    )
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise T16IntegrityError("The published T16 audit JSON is malformed.") from error
    if not isinstance(value, Mapping):
        raise T16IntegrityError("The published T16 audit JSON root is not an object.")
    audit = MatchweekAudit.from_dict(value)
    if (
        audit.audit_digest != str(marker["audit_digest"])
        or audit.audit_id != str(marker["audit_id"])
        or str(audit.payload["matchweek_id"]) != str(marker["matchweek_id"])
        or audit.mode.value != str(marker["mode"])
    ):
        raise T16IntegrityError("The publication marker does not match the audit digest.")
    return audit


def read_report(
    database_path: Path, *, private_root: Path | None = None, matchweek_id: str | None = None
) -> dict[str, object]:
    audit = read_audit(database_path, private_root=private_root, matchweek_id=matchweek_id)
    marker = _latest_publication(database_path, private_root, matchweek_id)
    expected = render_markdown_report(audit).encode("utf-8")
    stored = _read_artifact(
        database_path,
        str(marker["report_artifact_digest"]),
        expected_media_type=T16_REPORT_MEDIA_TYPE,
    )
    if stored != expected:
        raise T16IntegrityError(
            "The published deterministic Markdown report does not match the audit."
        )
    return build_report_payload(audit)


def inspect_match(
    database_path: Path,
    match: str,
    *,
    private_root: Path | None = None,
    matchweek_id: str | None = None,
) -> dict[str, object]:
    audit = read_audit(database_path, private_root=private_root, matchweek_id=matchweek_id)
    for row in audit.matches:
        membership = row.get("membership")
        membership_row = membership if isinstance(membership, Mapping) else {}
        if (
            str(row.get("fixture_id")) == match
            or str(membership_row.get("membership_id")) == match
            or str(membership_row.get("subject_id")) == match
        ):
            return row
    raise T16NotFoundError(f"Match {match} is not present in the complete Matchweek Audit.")


def _grading_state(database_path: Path, matchweek_id: str) -> str:
    path = database_path.resolve()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT grading_state FROM settlement_grades WHERE matchweek_id = ?",
            (matchweek_id,),
        ).fetchall()
    except sqlite3.DatabaseError:
        return "NOT_STARTED"
    finally:
        if connection is not None:
            connection.close()
    states = {str(row[0]) for row in rows}
    if not states:
        return "NOT_STARTED"
    if "PENDING" in states:
        return "PENDING"
    return "FINAL"


def history(database_path: Path, *, private_root: Path | None = None) -> list[dict[str, object]]:
    """List lifecycle, audit, grading, export, backup, mode, and policy state."""

    publications = _read_catalog(database_path, private_root) if database_path.exists() else ()
    by_run = {str(item.get("run_id")): item for item in publications if item.get("run_id")}
    by_matchweek = {str(item.get("matchweek_id")): item for item in publications}
    path = database_path.resolve()
    run_rows: list[tuple[object, ...]] = []
    if path.exists():
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            run_rows = [
                tuple(row)
                for row in connection.execute(
                    "SELECT run_id, matchweek, state, mode, current_phase, "
                    "last_checkpoint, input_digest, started_at_utc, completed_at_utc "
                    "FROM research_runs ORDER BY started_at_utc DESC, run_id DESC"
                ).fetchall()
            ]
        except sqlite3.DatabaseError:
            run_rows = []
        finally:
            connection.close()
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in run_rows:
        run_id, matchweek_id, state, mode, phase, checkpoint, input_digest, started, completed = row
        marker = by_run.get(str(run_id), by_matchweek.get(str(matchweek_id)))
        key = (str(run_id), str(matchweek_id))
        seen.add(key)
        output.append(
            {
                "run_id": str(run_id),
                "matchweek_id": str(matchweek_id),
                "run_state": str(state),
                "phase": str(phase),
                "last_checkpoint": str(checkpoint or "none"),
                "input_digest": str(input_digest),
                "started_at_utc": str(started),
                "completed_at_utc": completed,
                "audit_state": "COMPLETE"
                if marker
                else ("INCOMPLETE" if str(state) == "INCOMPLETE" else "NONE"),
                "audit_id": marker.get("audit_id") if marker else None,
                "audit_digest": marker.get("audit_digest") if marker else None,
                "grading_state": _grading_state(database_path, str(matchweek_id)),
                "export_state": "OUT_OF_SCOPE",
                "backup_state": "OUT_OF_SCOPE",
                "mode": marker.get("mode", str(mode)) if marker else str(mode),
                "policy_state": "PRODUCTION_PROMOTED"
                if marker and marker.get("mode") == AuditMode.PRODUCTION.value
                else "RESEARCH_ONLY",
            }
        )
    for marker in publications:
        key = (str(marker.get("run_id") or ""), str(marker.get("matchweek_id")))
        if key in seen:
            continue
        output.append(
            {
                "run_id": marker.get("run_id"),
                "matchweek_id": marker.get("matchweek_id"),
                "run_state": "COMPLETE",
                "phase": "atomic_report_and_audit_publication",
                "last_checkpoint": "atomic_report_and_audit_publication",
                "input_digest": None,
                "started_at_utc": None,
                "completed_at_utc": marker.get("published_at_utc"),
                "audit_state": "COMPLETE",
                "audit_id": marker.get("audit_id"),
                "audit_digest": marker.get("audit_digest"),
                "grading_state": _grading_state(database_path, str(marker.get("matchweek_id"))),
                "export_state": "OUT_OF_SCOPE",
                "backup_state": "OUT_OF_SCOPE",
                "mode": marker.get("mode"),
                "policy_state": "PRODUCTION_PROMOTED"
                if marker.get("mode") == AuditMode.PRODUCTION.value
                else "RESEARCH_ONLY",
            }
        )
    output.sort(
        key=lambda item: (
            str(item.get("started_at_utc") or item.get("completed_at_utc") or ""),
            str(item.get("run_id") or ""),
        ),
        reverse=True,
    )
    return output


__all__ = [
    "AFRICA_LAGOS",
    "DEFAULT_TARGET_LEAGUE_SET",
    "T16_AUDIT_MEDIA_TYPE",
    "T16_AUDIT_SCHEMA",
    "T16_EXPECTED_PREFERENCE_COUNT",
    "T16_PUBLICATION_MEDIA_TYPE",
    "T16_PUBLICATION_SCHEMA",
    "T16_REPORT_MEDIA_TYPE",
    "T16_REPORT_SCHEMA",
    "T16_SCHEMA_VERSION",
    "AuditMode",
    "MatchweekAudit",
    "PublicationState",
    "RejectionCategory",
    "T16Error",
    "T16IncompleteError",
    "T16IntegrityError",
    "T16NotFoundError",
    "T16Publication",
    "T16ValidationError",
    "build_matchweek_audit",
    "build_report_payload",
    "history",
    "inspect_match",
    "publish_audit",
    "publish_matchweek_audit",
    "read_audit",
    "read_report",
    "render_markdown_report",
    "render_report",
]

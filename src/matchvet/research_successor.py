"""Closed identity for prospective six-scope RESEARCH_ONLY research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from matchvet.active_fixture_coverage import active_fixture_scopes_for_matchweek
from matchvet.active_scope import SUCCESSOR_SIX_SCOPE
from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.matchweek_membership import canonical_json
from matchvet.store import Store

SIX_SCOPE_COHORT_ID = "matchvet:prospective-six-scope"
SIX_SCOPE_COHORT_CONTRACT = "matchvet-prospective-six-scope-cohort-v1"
SIX_SCOPE_COHORT_MEDIA_TYPE = "application/vnd.matchvet.prospective-cohort.v1+json"
SIX_SCOPE_CAPTURE_CONTRACT = "research-capture-index-v3"
SIX_SCOPE_EVALUATION_COHORT = "PROSPECTIVE_SIX_SCOPE_RESEARCH_ONLY"


class SuccessorIdentityError(ValueError):
    """The retained six-scope prospective identity is absent or inconsistent."""


def six_scope_binding() -> dict[str, str]:
    """Return the exact scope contract identity used by downstream artifacts."""
    return {
        "active_scope_contract_id": SUCCESSOR_SIX_SCOPE.contract_id,
        "active_scope_contract_version": str(SUCCESSOR_SIX_SCOPE.version),
        "active_scope_digest": SUCCESSOR_SIX_SCOPE.digest.removeprefix("sha256:"),
    }


def six_scope_cohort_value() -> dict[str, Any]:
    """Return the immutable prospective cohort descriptor body."""
    scope_value = asdict(SUCCESSOR_SIX_SCOPE)
    scope_value["league_keys"] = list(SUCCESSOR_SIX_SCOPE.league_keys)
    return {
        "active_scope": scope_value,
        "audit_denominator": "all_f06_memberships_x_enabled_preferences",
        "cohort_id": SIX_SCOPE_COHORT_ID,
        "contract": SIX_SCOPE_COHORT_CONTRACT,
        "correlation_groups": ["logical_matchweek_id", "fixture_id"],
        "chronology_version": "0.2.0",
        "schema_version": 1,
        "statistical_denominator": "included_f06_memberships_x_enabled_preferences",
        "subgroup_key": "scope_id",
        "role": "prospective_RESEARCH_ONLY",
    }


def six_scope_cohort_bytes() -> bytes:
    return canonical_json(six_scope_cohort_value()).encode("utf-8")


def six_scope_cohort_digest() -> str:
    return hashlib.sha256(six_scope_cohort_bytes()).hexdigest()


def publish_six_scope_cohort(store: Store) -> str:
    """Publish the fixed descriptor by exact bytes; no current/latest lookup exists."""
    return (
        ArtifactStore(store)
        .publish_artifact(six_scope_cohort_bytes(), SIX_SCOPE_COHORT_MEDIA_TYPE)
        .digest
    )


def resolve_six_scope_cohort(store: Store, digest: str) -> dict[str, Any]:
    """Resolve only the exact fixed, protected cohort descriptor."""
    if digest != six_scope_cohort_digest():
        raise SuccessorIdentityError("Prospective six-scope cohort digest is not canonical.")
    record = store.artifact_metadata(digest)
    if record is None or (record.media_type, record.retention_class) != (
        SIX_SCOPE_COHORT_MEDIA_TYPE,
        "PROTECTED",
    ):
        raise SuccessorIdentityError("Exact protected six-scope cohort descriptor is unavailable.")
    try:
        content = ArtifactStore(store).read_artifact(digest)
        value = json.loads(content)
        if (
            not isinstance(value, dict)
            or canonical_json(value).encode("utf-8") != content
            or value != six_scope_cohort_value()
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise SuccessorIdentityError("Six-scope cohort descriptor differs from its contract.")
        return value
    except SuccessorIdentityError:
        raise
    except (ArtifactError, TypeError, ValueError) as error:
        raise SuccessorIdentityError("Malformed six-scope cohort descriptor.") from error


def validate_six_scope_freeze(freeze: Any) -> None:
    """Require the exact policy3 six-league F06 membership identity."""
    scopes = active_fixture_scopes_for_matchweek(
        freeze.matchweek_friday, active_scope=SUCCESSOR_SIX_SCOPE
    )
    if (
        freeze.season != SUCCESSOR_SIX_SCOPE.season
        or freeze.policy.policy_version != "3"
        or tuple(scope.scope_id for scope in freeze.scopes)
        != tuple(scope.scope_id for scope in scopes)
    ):
        raise SuccessorIdentityError("F06 freeze is not the exact policy3 six-scope population.")

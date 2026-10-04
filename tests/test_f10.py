from __future__ import annotations

import json

import pytest

from matchvet.f10 import (
    V1_BASELINE_CATALOG,
    V2_REQUIREMENT_CATALOG,
    V2_REQUIREMENT_CATALOG_VERSION,
    F10ValidationError,
    OutcomeState,
    ResearchRequirementCatalog,
    enabled_preference_families,
)
from matchvet.t09 import CATALOG_DIGEST, DEFAULT_CATALOG, PREFERENCE_FAMILIES


def test_each_enabled_family_has_stable_v2_requirements() -> None:
    catalog = V2_REQUIREMENT_CATALOG

    assert enabled_preference_families() == PREFERENCE_FAMILIES
    for family in enabled_preference_families():
        requirements = catalog.for_family(family)
        assert requirements
        assert requirements == catalog.for_family(family)
        assert tuple(sorted(item.requirement_id for item in requirements)) == tuple(
            item.requirement_id for item in requirements
        )


def test_v2_contract_preserves_all_research_outcomes() -> None:
    assert {state.value for state in OutcomeState} == {
        "OBSERVED",
        "ABSENT",
        "UNKNOWN",
        "CONFLICT",
        "UNPERFORMED",
    }
    assert all(
        OutcomeState.ABSENT in req.allowed_outcomes for req in V2_REQUIREMENT_CATALOG.requirements
    )
    assert all(
        {OutcomeState.UNKNOWN, OutcomeState.UNPERFORMED}.issubset(req.allowed_outcomes)
        for req in V2_REQUIREMENT_CATALOG.requirements
    )


def test_missing_source_or_health_cannot_mean_absent() -> None:
    for req in V2_REQUIREMENT_CATALOG.requirements:
        assert OutcomeState.ABSENT not in req.outcomes_for(
            research_performed=True, source_available=False, health_healthy=True
        )
        assert OutcomeState.ABSENT not in req.outcomes_for(
            research_performed=True, source_available=True, health_healthy=False
        )
        assert OutcomeState.ABSENT not in req.outcomes_for(
            research_performed=False, source_available=True, health_healthy=True
        )
        assert OutcomeState.UNKNOWN in req.outcomes_for(
            research_performed=True, source_available=False, health_healthy=True
        )
        assert OutcomeState.UNPERFORMED in req.outcomes_for(
            research_performed=False, source_available=True, health_healthy=True
        )
        if req.source_gap:
            assert OutcomeState.ABSENT not in req.outcomes_for(
                research_performed=True, source_available=True, health_healthy=True
            )
        else:
            assert OutcomeState.ABSENT in req.outcomes_for(
                research_performed=True, source_available=True, health_healthy=True
            )


def test_conditional_requirements_expose_condition() -> None:
    conditional = [item for item in V2_REQUIREMENT_CATALOG.requirements if item.conditional_when]

    assert conditional
    assert all(
        item.conditional_when is not None and item.conditional_when.strip() for item in conditional
    )
    assert all(item.is_research_required(False) is False for item in conditional)
    conditional_mandatory = [item for item in conditional if item.mandatory_research]
    assert conditional_mandatory
    assert all(item.is_research_required(True) for item in conditional_mandatory)


def test_weather_uses_approved_open_meteo_capability_and_health() -> None:
    weather = V2_REQUIREMENT_CATALOG.requirement("V2-WEATHER-FORECAST")

    assert weather.source_prerequisite == ("open-meteo", "weather-forecast")
    assert weather.health_prerequisite == (
        "provider-health-v1:matchvet:research-only:t08-weather:non-commercial"
    )
    assert weather.mandatory_research


def test_f08_source_gaps_are_explicit_without_fabricated_providers() -> None:
    gap_ids = {
        "V2-INJURY-AVAILABILITY",
        "V2-SUSPENSIONS",
        "V2-EXPECTED-LINEUP",
        "V2-ROTATION",
        "V2-MANAGER-REGIME",
        "V2-REFEREE-APPOINTMENT",
        "V2-REFEREE-CONTEXT",
        "V2-UNRESOLVED-WORKLOAD-SOURCE",
    }

    for requirement_id in gap_ids:
        requirement = V2_REQUIREMENT_CATALOG.requirement(requirement_id)
        assert requirement.source_gap
        assert requirement.source_prerequisite is None
        assert {OutcomeState.UNKNOWN, OutcomeState.UNPERFORMED}.issubset(
            requirement.allowed_outcomes
        )


def test_qualitative_evidence_cannot_independently_create_play() -> None:
    qualitative = [item for item in V2_REQUIREMENT_CATALOG.requirements if item.qualitative]

    assert qualitative
    assert all(not item.can_create_play for item in qualitative)


def test_v1_catalog_digest_is_unchanged() -> None:
    assert CATALOG_DIGEST == "740556efa351db94d3704ec7f30bd8d3708a8c6191432d6cc987f8d60d9fa3fc"
    assert V1_BASELINE_CATALOG[2] == CATALOG_DIGEST


def test_v2_crosswalk_accounts_for_every_historical_v1_requirement() -> None:
    baseline_ids = {
        baseline_id
        for requirement in V2_REQUIREMENT_CATALOG.requirements
        for baseline_id in requirement.baseline_requirement_ids
    }

    assert baseline_ids == {item.requirement_id for item in DEFAULT_CATALOG.requirements}


def test_v2_catalog_serialization_digest_and_replay_are_deterministic() -> None:
    catalog = V2_REQUIREMENT_CATALOG
    encoded = catalog.canonical_json()

    assert json.loads(encoded) == catalog.to_dict()
    assert catalog.digest == "250288cc0f189dd5818b570a08fcb5a3023ac8b05fa8e1665b24fea60673412e"
    assert catalog.digest == ResearchRequirementCatalog.from_json(encoded).digest
    assert ResearchRequirementCatalog.from_json(encoded).canonical_json() == encoded
    assert catalog.version == V2_REQUIREMENT_CATALOG_VERSION


def test_unknown_v2_catalog_version_fails_closed() -> None:
    payload = V2_REQUIREMENT_CATALOG.to_dict()
    payload["version"] = "99.0.0"

    with pytest.raises(F10ValidationError, match="Unsupported"):
        ResearchRequirementCatalog.from_dict(payload)

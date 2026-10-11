"""Exact automatic F01 v4 successor; legacy codecs remain version-specific."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from matchvet.active_scope import SUCCESSOR_SIX_SCOPE, ActiveScopeContract
from matchvet.fixture_coverage import (
    CoverageFreshnessResult,
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    FixtureIdentityResolution,
    FixtureRevisionReference,
    FixtureScope,
    MatchweekScheduleState,
    ProviderAttempt,
    ProviderCoverageEvidence,
    _assess_fixture_coverage,
    _coverage_evidence_from_json,
    _freshness_result_from_json,
    _identity_resolution_from_json,
    _json_value,
    _payload_int,
    _payload_list,
    _payload_object,
    _payload_optional_string,
    _payload_string,
    _payload_string_tuple,
    _provider_attempt_from_json,
    _revision_reference_from_json,
    _scope_assessment_from_json,
)
from matchvet.matchweek import MatchweekWindow

FIXTURE_COVERAGE_V4_CONTRACT_VERSION = "fixture-coverage-v4-v4"
FIXTURE_COVERAGE_V4_SCHEMA_VERSION = 4


def active_fixture_scopes_for_matchweek(
    friday: str, *, active_scope: ActiveScopeContract
) -> tuple[FixtureScope, ...]:
    if type(active_scope) is not ActiveScopeContract or active_scope != SUCCESSOR_SIX_SCOPE:
        raise ValueError("Automatic successor coverage requires the fixed six active contract.")
    canonical_friday = MatchweekWindow.for_friday(friday).friday_local.isoformat()
    return tuple(
        FixtureScope(key, active_scope.season, canonical_friday) for key in active_scope.league_keys
    )


@dataclass(frozen=True, kw_only=True)
class ActiveFixtureCoverageAssessment(FixtureCoverageAssessment):
    active_scope: ActiveScopeContract

    def __post_init__(self) -> None:
        if (
            self.contract_version != FIXTURE_COVERAGE_V4_CONTRACT_VERSION
            or type(self.schema_version) is not int
            or self.schema_version != FIXTURE_COVERAGE_V4_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported successor F01 contract or schema.")
        scopes = tuple(item.scope for item in self.scope_assessments)
        if not scopes or scopes != active_fixture_scopes_for_matchweek(
            scopes[0].matchweek_friday, active_scope=self.active_scope
        ):
            raise ValueError("Successor F01 requires exactly six ordered canonical scopes.")
        scope_ids = {scope.scope_id for scope in scopes}
        references: tuple[
            ProviderAttempt
            | ProviderCoverageEvidence
            | FixtureRevisionReference
            | FixtureIdentityResolution,
            ...,
        ] = (
            *self.provider_attempts,
            *self.coverage_evidence,
            *self.fixture_revisions,
            *self.identity_resolutions,
        )
        if any(item.scope_id not in scope_ids for item in references):
            raise ValueError("Successor F01 cannot reference evidence outside its six scopes.")
        super().__post_init__()


def assess_active_fixture_coverage(
    *,
    active_scope: ActiveScopeContract,
    scopes: tuple[FixtureScope, ...],
    provider_attempts: tuple[ProviderAttempt, ...],
    coverage_evidence: tuple[ProviderCoverageEvidence, ...],
    fixture_revisions: tuple[FixtureRevisionReference, ...],
    identity_resolutions: tuple[FixtureIdentityResolution, ...],
    freshness_results: tuple[CoverageFreshnessResult, ...],
) -> ActiveFixtureCoverageAssessment:
    return cast(
        ActiveFixtureCoverageAssessment,
        _assess_fixture_coverage(
            active_scope=active_scope,
            scopes=scopes,
            provider_attempts=provider_attempts,
            coverage_evidence=coverage_evidence,
            fixture_revisions=fixture_revisions,
            identity_resolutions=identity_resolutions,
            freshness_results=freshness_results,
        ),
    )


def encode_active_f01(assessment: ActiveFixtureCoverageAssessment) -> str:
    return json.dumps(
        _json_value(assessment),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def decode_active_f01(encoded: str) -> ActiveFixtureCoverageAssessment:
    try:
        root = _payload_object(
            json.loads(encoded),
            (
                "contract_version",
                "schema_version",
                "active_scope",
                "freshness_policy_id",
                "scope_assessments",
                "provider_attempts",
                "coverage_evidence",
                "fixture_revisions",
                "identity_resolutions",
                "freshness_results",
                "schedule_state",
                "digest",
            ),
            "Active Fixture Coverage Assessment",
        )
        reference = _payload_object(
            root["active_scope"],
            ("contract_id", "version", "season", "league_keys", "digest"),
            "Active Scope Contract",
        )
        active_scope = ActiveScopeContract(
            contract_id=_payload_string(reference["contract_id"], "contract_id"),
            version=_payload_int(reference["version"], "version"),
            season=_payload_string(reference["season"], "season"),
            league_keys=_payload_string_tuple(reference["league_keys"], "league_keys"),
            digest=_payload_string(reference["digest"], "digest"),
        )
        assessment = ActiveFixtureCoverageAssessment(
            contract_version=_payload_string(root["contract_version"], "contract_version"),
            schema_version=_payload_int(root["schema_version"], "schema_version"),
            active_scope=active_scope,
            freshness_policy_id=_payload_optional_string(
                root["freshness_policy_id"], "freshness_policy_id"
            ),
            scope_assessments=tuple(
                _scope_assessment_from_json(v)
                for v in _payload_list(root["scope_assessments"], "scope_assessments")
            ),
            provider_attempts=tuple(
                _provider_attempt_from_json(v)
                for v in _payload_list(root["provider_attempts"], "provider_attempts")
            ),
            coverage_evidence=tuple(
                _coverage_evidence_from_json(v)
                for v in _payload_list(root["coverage_evidence"], "coverage_evidence")
            ),
            fixture_revisions=tuple(
                _revision_reference_from_json(v)
                for v in _payload_list(root["fixture_revisions"], "fixture_revisions")
            ),
            identity_resolutions=tuple(
                _identity_resolution_from_json(v)
                for v in _payload_list(root["identity_resolutions"], "identity_resolutions")
            ),
            freshness_results=tuple(
                _freshness_result_from_json(v)
                for v in _payload_list(root["freshness_results"], "freshness_results")
            ),
            schedule_state=MatchweekScheduleState(
                _payload_string(root["schedule_state"], "schedule_state")
            ),
            digest=_payload_string(root["digest"], "digest"),
        )
        if encode_active_f01(assessment) != encoded:
            raise FixtureCoveragePayloadError("Successor F01 payload is not canonical.")
        return assessment
    except (KeyError, TypeError, ValueError) as error:
        raise FixtureCoveragePayloadError("Successor F01 payload is invalid.") from error

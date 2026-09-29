"""Closed, version-aware F01 assessment serialization."""

from __future__ import annotations

import json
from typing import TypeGuard, cast

from matchvet.fixture_coverage import (
    FIXTURE_COVERAGE_CONTRACT_VERSION,
    FIXTURE_COVERAGE_SCHEMA_VERSION,
    FixtureCoverageAssessment,
    FixtureCoveragePayloadError,
    SupportedFixtureCoverageAssessment,
    fixture_coverage_assessment_from_canonical_json,
    fixture_coverage_assessment_to_canonical_json,
)

FIXTURE_COVERAGE_V3_CONTRACT_VERSION = "fixture-coverage-v3-v3"
FIXTURE_COVERAGE_V3_SCHEMA_VERSION = 3


def is_supported_f01_assessment(
    value: object,
) -> TypeGuard[SupportedFixtureCoverageAssessment]:
    """Accept only the two concrete F01 assessment classes and exact version pairs."""
    if type(value) is FixtureCoverageAssessment:
        return (
            value.contract_version == FIXTURE_COVERAGE_CONTRACT_VERSION
            and type(value.schema_version) is int
            and value.schema_version == FIXTURE_COVERAGE_SCHEMA_VERSION
        )
    from matchvet.operator_fixture_attestation import AttestedFixtureCoverageAssessment

    return (
        type(value) is AttestedFixtureCoverageAssessment
        and value.contract_version == FIXTURE_COVERAGE_V3_CONTRACT_VERSION
        and type(value.schema_version) is int
        and value.schema_version == FIXTURE_COVERAGE_V3_SCHEMA_VERSION
    )


def encode_f01(assessment: SupportedFixtureCoverageAssessment) -> str:
    """Encode one exact supported F01 value without changing legacy v2 bytes."""
    if not is_supported_f01_assessment(assessment):
        raise FixtureCoveragePayloadError("Fixture Coverage assessment version is unsupported.")
    if assessment.contract_version == FIXTURE_COVERAGE_CONTRACT_VERSION:
        return fixture_coverage_assessment_to_canonical_json(
            cast(FixtureCoverageAssessment, assessment)
        )
    from matchvet.operator_fixture_attestation import (
        AttestedFixtureCoverageAssessment,
        attested_fixture_coverage_assessment_to_canonical_json,
    )

    return attested_fixture_coverage_assessment_to_canonical_json(
        cast(AttestedFixtureCoverageAssessment, assessment)
    )


def decode_f01(encoded: str) -> SupportedFixtureCoverageAssessment:
    """Dispatch only exact version/schema pairs and require canonical JSON."""
    try:
        raw = json.loads(encoded)
        if not isinstance(raw, dict):
            raise FixtureCoveragePayloadError("Fixture Coverage payload root must be an object.")
        canonical = json.dumps(
            raw,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        if canonical != encoded:
            raise FixtureCoveragePayloadError("Fixture Coverage payload is not canonical JSON.")
        contract_version = raw.get("contract_version")
        schema_version = raw.get("schema_version")
        if (
            contract_version == FIXTURE_COVERAGE_CONTRACT_VERSION
            and type(schema_version) is int
            and schema_version == FIXTURE_COVERAGE_SCHEMA_VERSION
        ):
            return fixture_coverage_assessment_from_canonical_json(encoded)
        if (
            contract_version == FIXTURE_COVERAGE_V3_CONTRACT_VERSION
            and type(schema_version) is int
            and schema_version == FIXTURE_COVERAGE_V3_SCHEMA_VERSION
        ):
            from matchvet.operator_fixture_attestation import (
                attested_fixture_coverage_assessment_from_canonical_json,
            )

            return attested_fixture_coverage_assessment_from_canonical_json(encoded)
        raise FixtureCoveragePayloadError("Fixture Coverage payload uses unsupported F01 versions.")
    except FixtureCoveragePayloadError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise FixtureCoveragePayloadError("Fixture Coverage payload is invalid.") from error

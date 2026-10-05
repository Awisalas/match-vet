"""Canonical, exact-key codecs for the frozen CB01 v1 artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

CONTRACT_VERSION = "cb01-v1"
SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")


class CB01SchemaError(ValueError):
    """A CB01 artifact is malformed, noncanonical, or outside its v1 schema."""


MEDIA_TYPES = {
    "PreEnrollment": "application/vnd.matchvet.cb01-pre-enrollment.v1+json",
    "FixtureEnrollmentBatch": "application/vnd.matchvet.cb01-fixture-enrollment-batch.v1+json",
    "TimestampAttempt": "application/vnd.matchvet.cb01-timestamp-attempt.v1+json",
    "TimestampAttemptResult": "application/vnd.matchvet.cb01-timestamp-attempt-result.v1+json",
    "TimestampVerification": "application/vnd.matchvet.cb01-timestamp-verification.v1+json",
    "EnrollmentRecord": "application/vnd.matchvet.cb01-enrollment-record.v1+json",
    "FixtureEnrollmentPublication": (
        "application/vnd.matchvet.cb01-fixture-enrollment-publication.v1+json"
    ),
    "TimestampFailure": "application/vnd.matchvet.cb01-timestamp-failure.v1+json",
    "OutcomeAttachment": "application/vnd.matchvet.cb01-outcome-attachment.v1+json",
    "OutcomeFactAttachment": "application/vnd.matchvet.cb01-outcome-fact-attachment.v1+json",
    "TrustPolicy": "application/vnd.matchvet.cb01-trust-policy.v1+json",
    "TrustMaterial": "application/vnd.matchvet.cb01-trust-material.v1+json",
}

BODY_KEYS: dict[str, frozenset[str]] = {
    "PreEnrollment": frozenset(
        {
            "anchor",
            "lineage",
            "preference",
            "forecast",
            "support",
            "eligibility",
            "disposition",
            "reasons",
            "software_identity",
        }
    ),
    "FixtureEnrollmentBatch": frozenset(
        {
            "anchor",
            "lineage",
            "expected_preference_ids",
            "entries",
        }
    ),
    "TimestampAttempt": frozenset(
        {
            "batch_digest",
            "request_digest",
            "nonce_hex",
            "trust_policy_digest",
            "attempt_number",
            "predecessor_attempt_digest",
        }
    ),
    "TimestampAttemptResult": frozenset(
        {
            "attempt_digest",
            "response_digest",
            "transport_state",
            "reasons",
        }
    ),
    "TimestampVerification": frozenset(
        {
            "attempt_digest",
            "attempt_result_digest",
            "response_digest",
            "trust_policy_digest",
            "trust_material_digest",
            "tsa",
            "chain_fingerprints",
            "trust_state",
            "checks",
            "verifier",
            "state",
            "reasons",
        }
    ),
    "EnrollmentRecord": frozenset(
        {
            "pre_enrollment_digest",
            "batch_digest",
            "attempt_digest",
            "request_digest",
            "response_digest",
            "verification_digest",
            "trust_policy_digest",
            "trust_material_digest",
            "disposition",
            "reasons",
        }
    ),
    "FixtureEnrollmentPublication": frozenset(
        {
            "batch_digest",
            "verification_digest",
            "records",
        }
    ),
    "TimestampFailure": frozenset(
        {
            "batch_digest",
            "attempt_digest",
            "attempt_result_digest",
            "verification_digest",
            "expected_preference_ids",
            "reasons",
        }
    ),
    "OutcomeAttachment": frozenset(
        {
            "enrollment_digest",
            "settlement_digest",
            "settlement_identity",
            "state",
            "result",
            "correction_sequence",
            "predecessor_digest",
            "fact_attachment_digest",
        }
    ),
    "OutcomeFactAttachment": frozenset(
        {
            "enrollment_digest",
            "settlement_digest",
            "anchor",
            "evidence_snapshot_digests",
            "resolution_rule",
            "facts",
            "family_states",
            "correction_sequence",
            "predecessor_digest",
        }
    ),
    "TrustPolicy": frozenset(
        {
            "policy_id",
            "policy_version",
            "material_digest",
            "endpoint",
            "imprint_algorithm",
            "cms_digest_algorithm",
            "cms_signature_oid",
            "allowed_token_policy_oids",
            "signer_fingerprints",
            "anchor_fingerprints",
            "certificate_time_basis",
            "trust_update_policy",
            "transport_limits",
            "request_budget",
            "usage_policy_evidence_digests",
        }
    ),
    "TrustMaterial": frozenset(
        {
            "material_id",
            "material_version",
            "certificates",
            "primary_source_evidence_digests",
        }
    ),
}

REFERENCE_KEYS = frozenset({"id", "version", "digest", "state", "reasons"})
ANCHOR_KEYS = frozenset(
    {
        "freeze",
        "membership",
        "fixture_revision",
        "cutoff",
        "profile",
        "fixture_id",
        "home_team_id",
        "away_team_id",
        "competition_id",
        "season_id",
        "matchweek_id",
        "kickoff_utc",
        "cutoff_utc",
    }
)
LINEAGE_KEYS = frozenset(
    {
        "f06",
        "f07",
        "f10_catalog",
        "f10_requirements",
        "f11_evidence",
        "f13_input",
        "f13_result",
        "f13_history",
        "f14_profile",
        "f14_decision",
        "f14_policy",
        "f16_manifest",
        "f16_match_result",
    }
)
PREFERENCE_KEYS = frozenset(
    {
        "id",
        "catalog",
        "family",
        "side",
        "line",
        "phase",
        "settlement_topology",
    }
)
SUPPORT_KEYS = frozenset(
    {
        "candidate_input",
        "research",
        "adversarial_review",
        "calibration",
        "baseline",
        "uncertainty_validation",
        "independent_reference",
        "g6",
        "g7",
        "paired_strength",
    }
)
ELIGIBILITY_KEYS = frozenset(
    {
        "calibration",
        "data_quality",
        "reliability",
        "baseline",
        "adversarial_risk",
        "g6",
        "g7_reference",
        "paired_strength",
        "policy_validation",
    }
)
FAMILY_IDS = ("CORNERS", "FIRST_HALF_GOALS", "FULL_TIME_GOALS", "SECOND_HALF_GOALS")
FACT_KEYS = (
    "full_time_home_goals",
    "full_time_away_goals",
    "half_time_home_goals",
    "half_time_away_goals",
    "corners_home",
    "corners_away",
)


def canonical_bytes(value: object) -> bytes:
    """Encode finite JSON using the repository's exact canonical JSON convention."""
    try:
        return json.dumps(
            _jsonable(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise CB01SchemaError("CB01 values must be finite canonical JSON data.") from error


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encode_artifact(kind: str, body: dict[str, Any]) -> bytes:
    if kind not in BODY_KEYS:
        raise CB01SchemaError(f"Unsupported CB01 artifact kind {kind!r}.")
    envelope = {
        "body": body,
        "contract_version": CONTRACT_VERSION,
        "kind": kind,
        "schema_version": SCHEMA_VERSION,
    }
    _validate_body(kind, body)
    return canonical_bytes(envelope)


def decode_artifact(
    content: bytes, *, expected_kind: str | None = None
) -> tuple[str, dict[str, Any]]:
    if not isinstance(content, bytes):
        raise CB01SchemaError("CB01 artifact content must be bytes.")
    try:
        parsed = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except CB01SchemaError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise CB01SchemaError("CB01 artifact is not valid UTF-8 JSON.") from error
    if not isinstance(parsed, dict) or set(parsed) != {
        "body",
        "contract_version",
        "kind",
        "schema_version",
    }:
        raise CB01SchemaError("CB01 envelope has an unknown or missing key.")
    kind = parsed["kind"]
    if not isinstance(kind, str) or kind not in BODY_KEYS:
        raise CB01SchemaError("CB01 artifact kind is unsupported.")
    if expected_kind is not None and kind != expected_kind:
        raise CB01SchemaError("CB01 artifact kind differs from the requested kind.")
    if type(parsed["schema_version"]) is not int or parsed["schema_version"] != SCHEMA_VERSION:
        raise CB01SchemaError("CB01 schema version is unsupported.")
    if parsed["contract_version"] != CONTRACT_VERSION:
        raise CB01SchemaError("CB01 contract version is unsupported.")
    body = parsed["body"]
    if not isinstance(body, dict):
        raise CB01SchemaError("CB01 artifact body must be an object.")
    _validate_body(kind, body)
    if canonical_bytes(parsed) != content:
        raise CB01SchemaError("CB01 artifact bytes are not canonical.")
    return kind, cast(dict[str, Any], body)


def exact_utc(value: str) -> str:
    """Validate exact UTC Z spelling while retaining all fractional digits."""
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        raise CB01SchemaError("CB01 instants must use an exact UTC Z timestamp.")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CB01SchemaError("CB01 UTC instant is malformed.") from error
    return value


def normalize_utc(value: str) -> str:
    """Normalize an offset-aware ISO instant to UTC without changing its fraction."""
    if not isinstance(value, str):
        raise CB01SchemaError("CB01 source timestamps must be strings.")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})",
        value,
    )
    if match is None:
        raise CB01SchemaError("CB01 source timestamps must have an explicit UTC offset.")
    date_part, time_part, fraction, offset = match.groups()
    local = datetime.fromisoformat(f"{date_part}T{time_part}")
    if offset == "Z":
        selected_offset = UTC
    else:
        normalized_offset = offset.replace(":", "")
        sign = 1 if normalized_offset[0] == "+" else -1
        hours = int(normalized_offset[1:3])
        minutes = int(normalized_offset[3:5])
        if hours > 23 or minutes > 59:
            raise CB01SchemaError("CB01 source timestamp offset is malformed.")
        selected_offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
    utc = local.replace(tzinfo=selected_offset).astimezone(UTC)
    result = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if fraction:
        result += f".{fraction}"
    return result + "Z"


def compare_utc(left: str, right: str) -> int:
    """Compare exact UTC instants without truncating fractional precision."""
    left_dt = datetime.fromisoformat(exact_utc(left)[:-1] + "+00:00")
    right_dt = datetime.fromisoformat(exact_utc(right)[:-1] + "+00:00")
    # datetime truncates fractions beyond microseconds; compare the decimal fraction exactly.
    left_frac = _utc_parts(left)[1]
    right_frac = _utc_parts(right)[1]
    if left_dt.replace(microsecond=0) < right_dt.replace(microsecond=0):
        return -1
    if left_dt.replace(microsecond=0) > right_dt.replace(microsecond=0):
        return 1
    width = max(len(left_frac), len(right_frac))
    left_num = int(left_frac.ljust(width, "0") or "0")
    right_num = int(right_frac.ljust(width, "0") or "0")
    return (left_num > right_num) - (left_num < right_num)


def _utc_parts(value: str) -> tuple[str, str]:
    body = exact_utc(value)[:-1]
    whole, dot, fraction = body.partition(".")
    return whole, fraction if dot else ""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CB01SchemaError(f"Duplicate CB01 JSON key {key!r}.")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise CB01SchemaError(f"Non-finite JSON number {value!r} is forbidden.")


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise CB01SchemaError("CB01 JSON object keys must be strings.")
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise CB01SchemaError("CB01 JSON numbers must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise CB01SchemaError(f"Unsupported CB01 JSON value {type(value).__name__}.")


def _keys(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CB01SchemaError(f"{label} has unknown or missing keys.")
    return cast(dict[str, Any], value)


def _strings(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or (nonempty and not item) for item in value
    ):
        raise CB01SchemaError(f"{label} must be an array of strings.")
    return cast(list[str], value)


def _reasons(value: object, label: str) -> list[str]:
    reasons = _strings(value, label)
    if reasons != sorted(set(reasons)):
        raise CB01SchemaError(f"{label} must be sorted and unique.")
    return reasons


def _digest(value: object, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise CB01SchemaError(f"{label} must be a lowercase SHA-256 digest.")


def _validate_body(kind: str, value: dict[str, Any]) -> None:
    body = _keys(value, BODY_KEYS[kind], kind)
    if kind == "TimestampAttempt":
        for key in ("batch_digest", "request_digest", "trust_policy_digest"):
            _digest(body[key], key)
        if type(body["attempt_number"]) is not int or body["attempt_number"] not in (1, 2):
            raise CB01SchemaError("TimestampAttempt number must be one or two.")
        _digest(body["predecessor_attempt_digest"], "predecessor attempt digest", nullable=True)
        if body["attempt_number"] == 1 and body["predecessor_attempt_digest"] is not None:
            raise CB01SchemaError("The normal TimestampAttempt cannot have a predecessor.")
        if body["attempt_number"] == 2:
            _digest(body["predecessor_attempt_digest"], "retry predecessor digest")
        if (
            not isinstance(body["nonce_hex"], str)
            or re.fullmatch(r"[0-9a-f]+", body["nonce_hex"]) is None
            or int(body["nonce_hex"], 16) <= 0
        ):
            raise CB01SchemaError("TimestampAttempt nonce must be lowercase hexadecimal.")
    elif kind == "TimestampAttemptResult":
        _digest(body["attempt_digest"], "attempt digest")
        _digest(body["response_digest"], "response digest", nullable=True)
        if body["transport_state"] not in {"RECEIVED", "UNAVAILABLE", "REJECTED", "MALFORMED"}:
            raise CB01SchemaError("TimestampAttemptResult transport state is invalid.")
        _reasons(body["reasons"], "attempt result reasons")
    elif kind == "TimestampFailure":
        for key in (
            "batch_digest",
            "attempt_digest",
            "attempt_result_digest",
            "verification_digest",
        ):
            _digest(body[key], key, nullable=key != "batch_digest")
        failure_preference_ids = _strings(
            body["expected_preference_ids"], "expected preference IDs"
        )
        if failure_preference_ids != sorted(set(failure_preference_ids)):
            raise CB01SchemaError("Expected preference IDs must be sorted and unique.")
        _reasons(body["reasons"], "failure reasons")
    elif kind == "FixtureEnrollmentBatch":
        _validate_anchor(body["anchor"])
        _validate_lineage(body["lineage"])
        batch_preference_ids = _strings(body["expected_preference_ids"], "expected preference IDs")
        if batch_preference_ids != sorted(set(batch_preference_ids)):
            raise CB01SchemaError("Expected preference IDs must be sorted and unique.")
        entries = body["entries"]
        if not isinstance(entries, list):
            raise CB01SchemaError("Batch entries must be an array.")
        seen: list[str] = []
        for entry in entries:
            row = _keys(
                entry,
                frozenset({"preference_id", "pre_enrollment_digest", "disposition", "reasons"}),
                "BatchEntry",
            )
            if not isinstance(row["preference_id"], str) or not row["preference_id"]:
                raise CB01SchemaError("BatchEntry preference ID is malformed.")
            seen.append(row["preference_id"])
            _digest(row["pre_enrollment_digest"], "pre-enrollment digest")
            if row["disposition"] not in {"READY_FOR_WITNESS", "INCOMPLETE", "EXCLUDED"}:
                raise CB01SchemaError("BatchEntry disposition is invalid.")
            _reasons(row["reasons"], "BatchEntry reasons")
        if seen != batch_preference_ids:
            raise CB01SchemaError("Batch entries must match the complete sorted denominator.")
    elif kind == "PreEnrollment":
        _validate_anchor(body["anchor"])
        _validate_lineage(body["lineage"])
        _validate_preference(body["preference"])
        _validate_forecast(body["forecast"])
        _validate_references(body["support"], SUPPORT_KEYS, "Support")
        _validate_eligibility(body["eligibility"])
        _validate_reference(body["software_identity"])
        if body["disposition"] not in {"READY_FOR_WITNESS", "INCOMPLETE", "EXCLUDED"}:
            raise CB01SchemaError("PreEnrollment disposition is invalid.")
        _reasons(body["reasons"], "PreEnrollment reasons")
    elif kind == "TimestampVerification":
        for key in (
            "attempt_digest",
            "attempt_result_digest",
            "response_digest",
            "trust_policy_digest",
            "trust_material_digest",
        ):
            _digest(body[key], key)
        _validate_tsa(body["tsa"])
        _strings(body["chain_fingerprints"], "certificate fingerprints")
        _validate_trust_state(body["trust_state"])
        _validate_checks(body["checks"])
        verifier = _keys(
            body["verifier"],
            frozenset({"name", "version", "options", "software_digest"}),
            "VerifierIdentity",
        )
        for key in ("name", "version"):
            _nonempty_string(verifier[key], key)
        _strings(verifier["options"], "verifier options", nonempty=False)
        _digest(verifier["software_digest"], "verifier software digest")
        if body["state"] not in {"VERIFIED", "FAILED"}:
            raise CB01SchemaError("TimestampVerification state is invalid.")
        _reasons(body["reasons"], "verification reasons")
        if body["state"] == "VERIFIED":
            if any(item["state"] != "PASSED" for item in body["checks"].values()):
                raise CB01SchemaError("A VERIFIED timestamp must pass every verification check.")
            required_tsa = (
                "status",
                "imprint_algorithm",
                "imprint_hex",
                "nonce_hex",
                "policy_oid",
                "serial_hex",
                "gen_time_utc",
                "signer_fingerprint",
                "issuer",
                "certificate_serial_hex",
                "ess_binding",
            )
            if any(body["tsa"][key] is None for key in required_tsa):
                raise CB01SchemaError("A VERIFIED timestamp requires its complete TSA identity.")
    elif kind == "EnrollmentRecord":
        for key in BODY_KEYS[kind] - {"disposition", "reasons"}:
            _digest(body[key], key)
        if body["disposition"] not in {"ENROLLED_LIVE", "INCOMPLETE", "EXCLUDED"}:
            raise CB01SchemaError("EnrollmentRecord disposition is invalid.")
        _reasons(body["reasons"], "EnrollmentRecord reasons")
    elif kind == "FixtureEnrollmentPublication":
        _digest(body["batch_digest"], "batch digest")
        _digest(body["verification_digest"], "verification digest")
        rows = body["records"]
        if not isinstance(rows, list):
            raise CB01SchemaError("Publication records must be an array.")
        publication_preference_ids: list[str] = []
        for row in rows:
            item = _keys(row, frozenset({"preference_id", "enrollment_digest"}), "PublicationEntry")
            publication_preference_ids.append(
                _nonempty_string(item["preference_id"], "preference ID")
            )
            _digest(item["enrollment_digest"], "enrollment digest")
        if publication_preference_ids != sorted(set(publication_preference_ids)):
            raise CB01SchemaError("Publication records must be sorted and unique.")
    elif kind == "OutcomeAttachment":
        _digest(body["enrollment_digest"], "enrollment digest")
        _digest(body["settlement_digest"], "settlement digest")
        _validate_settlement_identity(body["settlement_identity"])
        if body["state"] not in {"PENDING", "CONFLICTING", "WIN", "LOSS", "PUSH", "VOID"}:
            raise CB01SchemaError("OutcomeAttachment state is invalid.")
        if body["result"] not in {None, "WIN", "LOSS", "PUSH", "VOID"}:
            raise CB01SchemaError("OutcomeAttachment result is invalid.")
        _counter(body["correction_sequence"], "correction sequence")
        _digest(body["predecessor_digest"], "predecessor digest", nullable=True)
        _digest(body["fact_attachment_digest"], "fact attachment digest", nullable=True)
    elif kind == "OutcomeFactAttachment":
        _digest(body["enrollment_digest"], "enrollment digest")
        _digest(body["settlement_digest"], "settlement digest")
        _validate_anchor(body["anchor"])
        digests = _strings(body["evidence_snapshot_digests"], "evidence snapshot digests")
        if digests != sorted(set(digests)):
            raise CB01SchemaError("Evidence snapshot digests must be sorted and unique.")
        for evidence_snapshot_digest in digests:
            _digest(evidence_snapshot_digest, "evidence snapshot digest")
        _validate_reference(body["resolution_rule"])
        _validate_facts(body["facts"])
        _validate_family_states(body["family_states"])
        _counter(body["correction_sequence"], "correction sequence")
        _digest(body["predecessor_digest"], "predecessor digest", nullable=True)
    elif kind == "TrustPolicy":
        _validate_trust_policy(body)
    elif kind == "TrustMaterial":
        _validate_trust_material(body)


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CB01SchemaError(f"{label} must be a non-empty string.")
    return value


def _counter(value: object, label: str) -> None:
    if type(value) is not int or value < 0:
        raise CB01SchemaError(f"{label} must be a non-negative integer.")


def _validate_reference(value: object) -> None:
    ref = _keys(value, REFERENCE_KEYS, "Reference")
    if ref["state"] not in {"PRESENT", "ABSENT", "UNKNOWN", "UNPERFORMED"}:
        raise CB01SchemaError("Reference state is invalid.")
    _reasons(ref["reasons"], "Reference reasons")
    for key in ("id", "version"):
        if ref[key] is not None and not isinstance(ref[key], str):
            raise CB01SchemaError(f"Reference {key} must be a string or null.")
    _digest(ref["digest"], "Reference digest", nullable=True)
    if ref["state"] == "PRESENT" and ref["digest"] is None:
        raise CB01SchemaError("A PRESENT Reference requires its digest.")
    if ref["state"] == "PRESENT" and (not ref["id"] or not ref["version"]):
        raise CB01SchemaError("A PRESENT Reference requires its exact identity and version.")
    if ref["state"] != "PRESENT" and (not ref["reasons"] or ref["digest"] is not None):
        raise CB01SchemaError("An unavailable Reference requires reasons and a null digest.")


def _validate_references(value: object, keys: frozenset[str], label: str) -> None:
    refs = _keys(value, keys, label)
    for reference in refs.values():
        _validate_reference(reference)


def _validate_anchor(value: object) -> None:
    anchor = _keys(value, ANCHOR_KEYS, "Anchor")
    for key in ("freeze", "membership", "fixture_revision", "cutoff", "profile"):
        _validate_reference(anchor[key])
        if anchor[key]["state"] != "PRESENT":
            raise CB01SchemaError(f"Anchor {key} must be PRESENT for an enrollment batch.")
    for key in (
        "fixture_id",
        "home_team_id",
        "away_team_id",
        "competition_id",
        "season_id",
        "matchweek_id",
    ):
        _nonempty_string(anchor[key], key)
    exact_utc(anchor["kickoff_utc"])
    exact_utc(anchor["cutoff_utc"])


def _validate_lineage(value: object) -> None:
    refs = _keys(value, LINEAGE_KEYS, "Lineage")
    for reference in refs.values():
        _validate_reference(reference)


def _validate_preference(value: object) -> None:
    row = _keys(value, PREFERENCE_KEYS, "Preference")
    for key in ("id", "family", "side", "phase", "settlement_topology"):
        _nonempty_string(row[key], key)
    if not isinstance(row["catalog"], dict):
        raise CB01SchemaError("Preference catalog value must preserve its catalog object.")
    if row["line"] is not None and not isinstance(row["line"], (str, int, float)):
        raise CB01SchemaError("Preference line must preserve its catalog scalar or null.")


def _validate_forecast(value: object) -> None:
    forecast = _keys(value, frozenset({"result_reference", "families"}), "Forecast")
    _validate_reference(forecast["result_reference"])
    families = forecast["families"]
    if not isinstance(families, list):
        raise CB01SchemaError("Forecast families must be an array.")
    ids: list[str] = []
    family_keys = frozenset(
        {
            "family_id",
            "input_reference",
            "fit_reference",
            "prediction_reference",
            "calibration_reference",
            "retained_family_payload",
        }
    )
    for item in families:
        family = _keys(item, family_keys, "ForecastFamily")
        ids.append(_nonempty_string(family["family_id"], "family ID"))
        for key in (
            "input_reference",
            "fit_reference",
            "prediction_reference",
            "calibration_reference",
        ):
            _validate_reference(family[key])
        if not isinstance(family["retained_family_payload"], dict):
            raise CB01SchemaError("Retained F13 family payload must be an object.")
    if tuple(ids) != FAMILY_IDS:
        raise CB01SchemaError("Forecast must preserve all four F13 families in exact order.")


def _validate_eligibility(value: object) -> None:
    dimensions = _keys(value, ELIGIBILITY_KEYS, "Eligibility")
    expected = frozenset({"state", "reasons", "supporting_digests"})
    for dimension in dimensions.values():
        item = _keys(dimension, expected, "EligibilityDimension")
        if item["state"] != "NOT_ASSESSED":
            raise CB01SchemaError("CB01 eligibility dimensions must remain NOT_ASSESSED.")
        _reasons(item["reasons"], "Eligibility reasons")
        digests = _strings(item["supporting_digests"], "Eligibility supporting digests")
        if digests != sorted(set(digests)):
            raise CB01SchemaError("Eligibility supporting digests must be sorted and unique.")
        for digest in digests:
            _digest(digest, "Eligibility supporting digest")


def _validate_tsa(value: object) -> None:
    tsa = _keys(
        value,
        frozenset(
            {
                "status",
                "imprint_algorithm",
                "imprint_hex",
                "nonce_hex",
                "policy_oid",
                "serial_hex",
                "gen_time_utc",
                "accuracy",
                "signer_fingerprint",
                "issuer",
                "certificate_serial_hex",
                "ess_binding",
            }
        ),
        "TsaIdentity",
    )
    for key in (
        "status",
        "imprint_algorithm",
        "imprint_hex",
        "nonce_hex",
        "policy_oid",
        "serial_hex",
        "signer_fingerprint",
        "issuer",
        "certificate_serial_hex",
        "ess_binding",
    ):
        if tsa[key] is not None:
            _nonempty_string(tsa[key], key)
    if tsa["gen_time_utc"] is not None:
        exact_utc(tsa["gen_time_utc"])
    accuracy = _keys(
        tsa["accuracy"], frozenset({"seconds", "millis", "micros"}), "Timestamp accuracy"
    )
    for value in accuracy.values():
        if value is not None and (type(value) is not int or value < 0):
            raise CB01SchemaError(
                "Timestamp accuracy fields must be non-negative integers or null."
            )


def _validate_trust_state(value: object) -> None:
    keys = frozenset(
        {
            "bootstrap_root_version",
            "bootstrap_root_digest",
            "root_version",
            "root_digest",
            "timestamp_version",
            "timestamp_digest",
            "snapshot_version",
            "snapshot_digest",
            "targets_version",
            "targets_digest",
            "trusted_root_target_digest",
            "trusted_root_length",
            "tsa_entry_uri",
            "tsa_entry_subject",
            "valid_for_start",
            "valid_for_end",
            "chain_fingerprints",
            "verification_client",
            "verification_client_version",
        }
    )
    state = _keys(value, keys, "TrustStateIdentity")
    for key in (
        "bootstrap_root_digest",
        "root_digest",
        "timestamp_digest",
        "snapshot_digest",
        "targets_digest",
        "trusted_root_target_digest",
    ):
        _digest(state[key], key)
    for key in (
        "bootstrap_root_version",
        "root_version",
        "timestamp_version",
        "snapshot_version",
        "targets_version",
        "trusted_root_length",
    ):
        if type(state[key]) is not int or state[key] < 1:
            raise CB01SchemaError(f"Trust state {key} must be a positive integer.")
    for key in (
        "tsa_entry_uri",
        "tsa_entry_subject",
        "valid_for_start",
        "verification_client",
        "verification_client_version",
    ):
        _nonempty_string(state[key], key)
    if state["valid_for_end"] is not None:
        _nonempty_string(state["valid_for_end"], "valid_for_end")
    fingerprints = _strings(state["chain_fingerprints"], "trust-state chain fingerprints")
    for fingerprint in fingerprints:
        _digest(fingerprint, "trust-state certificate fingerprint")


def _validate_checks(value: object) -> None:
    names = frozenset(
        {
            "status",
            "imprint",
            "nonce",
            "signature",
            "signer",
            "eku",
            "policy",
            "chain",
            "trusted_root",
            "certificate_validity_at_gen_time",
            "time_window",
            "denominator",
            "lineage",
        }
    )
    checks = _keys(value, names, "VerificationChecks")
    for check in checks.values():
        item = _keys(check, frozenset({"state", "reasons"}), "VerificationCheck")
        if item["state"] not in {"PASSED", "FAILED", "UNPERFORMED"}:
            raise CB01SchemaError("VerificationCheck state is invalid.")
        _reasons(item["reasons"], "VerificationCheck reasons")
        if item["state"] == "PASSED" and item["reasons"]:
            raise CB01SchemaError("A passed verification check cannot contain failure reasons.")
        if item["state"] == "FAILED" and not item["reasons"]:
            raise CB01SchemaError("A failed verification check must retain its reason.")


def _validate_settlement_identity(value: object) -> None:
    keys = frozenset(
        {
            "manifest_digest",
            "match_result_digest",
            "decision_digest",
            "fixture_id",
            "preference_id",
            "evidence_digest",
            "f19_correction_sequence",
            "f19_predecessor_digest",
        }
    )
    identity = _keys(value, keys, "SettlementIdentity")
    for key in ("manifest_digest", "match_result_digest", "decision_digest", "evidence_digest"):
        _digest(identity[key], key)
    for key in ("fixture_id", "preference_id"):
        _nonempty_string(identity[key], key)
    _counter(identity["f19_correction_sequence"], "F19 correction sequence")
    _digest(identity["f19_predecessor_digest"], "F19 predecessor digest", nullable=True)


def _validate_facts(value: object) -> None:
    facts = _keys(value, frozenset(FACT_KEYS), "OutcomeFacts")
    keys = frozenset(
        {
            "value",
            "state",
            "reasons",
            "selected_evidence_digest",
            "source_record_id",
            "source_assertion_ids",
            "source_revision_id",
            "published_at_utc",
            "observed_at_utc",
            "retrieved_at_utc",
        }
    )
    for raw in facts.values():
        fact = _keys(raw, keys, "OutcomeFact")
        if fact["value"] is not None:
            _counter(fact["value"], "outcome fact value")
        if fact["state"] not in {"AVAILABLE", "MISSING", "CONFLICTING", "NOT_APPLICABLE"}:
            raise CB01SchemaError("Outcome fact state is invalid.")
        _reasons(fact["reasons"], "outcome fact reasons")
        _digest(fact["selected_evidence_digest"], "selected evidence digest", nullable=True)
        for key in ("source_record_id", "source_revision_id"):
            if fact[key] is not None and not isinstance(fact[key], str):
                raise CB01SchemaError(f"{key} must be a string or null.")
        assertions = _strings(fact["source_assertion_ids"], "source assertion IDs")
        if assertions != sorted(set(assertions)):
            raise CB01SchemaError("Source assertion IDs must be sorted and unique.")
        for key in ("published_at_utc", "observed_at_utc", "retrieved_at_utc"):
            if fact[key] is not None:
                exact_utc(fact[key])
        if fact["state"] == "AVAILABLE" and (
            fact["value"] is None or fact["selected_evidence_digest"] is None
        ):
            raise CB01SchemaError(
                "AVAILABLE facts require an exact selected evidence digest and value."
            )
        if fact["state"] != "AVAILABLE" and not fact["reasons"]:
            raise CB01SchemaError("Unavailable outcome facts require an explicit reason.")


def _validate_family_states(value: object) -> None:
    states = _keys(value, frozenset(FAMILY_IDS), "FamilyStates")
    keys = frozenset(
        {"state", "required_fact_keys", "selected_evidence_digests", "derivation_rule", "reasons"}
    )
    for family in states.values():
        item = _keys(family, keys, "FamilyState")
        if item["state"] not in {
            "AVAILABLE",
            "MISSING",
            "CONFLICTING",
            "NOT_APPLICABLE",
            "UNPERFORMED",
        }:
            raise CB01SchemaError("Family state is invalid.")
        _strings(item["required_fact_keys"], "family required fact keys")
        digests = _strings(item["selected_evidence_digests"], "family selected evidence digests")
        if digests != sorted(set(digests)):
            raise CB01SchemaError("Family evidence digests must be sorted and unique.")
        for digest in digests:
            _digest(digest, "family evidence digest")
        if item["derivation_rule"] is not None:
            _validate_reference(item["derivation_rule"])
        _reasons(item["reasons"], "family reasons")


def _validate_trust_policy(value: object) -> None:
    policy = _keys(value, BODY_KEYS["TrustPolicy"], "TrustPolicy")
    for key in (
        "policy_id",
        "policy_version",
        "endpoint",
        "imprint_algorithm",
        "cms_digest_algorithm",
        "cms_signature_oid",
        "certificate_time_basis",
    ):
        _nonempty_string(policy[key], key)
    _digest(policy["material_digest"], "TrustPolicy material digest")
    for key in (
        "allowed_token_policy_oids",
        "signer_fingerprints",
        "anchor_fingerprints",
        "usage_policy_evidence_digests",
    ):
        values = _strings(policy[key], key)
        if values != sorted(set(values)):
            raise CB01SchemaError(f"TrustPolicy {key} must be sorted and unique.")
    for key in ("signer_fingerprints", "anchor_fingerprints", "usage_policy_evidence_digests"):
        for item in policy[key]:
            _digest(item, key)
    update = _keys(
        policy["trust_update_policy"],
        frozenset(
            {
                "mode",
                "bootstrap_root_version",
                "current_root_version",
                "trusted_root_target_digest",
                "metadata_digests",
                "refresh_before_each_batch",
                "post_issuance_reassessment",
            }
        ),
        "TrustUpdatePolicy",
    )
    if (
        update["mode"] != "SIGSTORE_TUF_TRUSTED_ROOT"
        or update["refresh_before_each_batch"] is not True
        or update["post_issuance_reassessment"] != "EXPLICIT_IMMUTABLE"
    ):
        raise CB01SchemaError("TrustPolicy update mode is invalid.")
    for key in ("bootstrap_root_version", "current_root_version"):
        if type(update[key]) is not int or update[key] < 1:
            raise CB01SchemaError("TrustPolicy TUF versions must be positive integers.")
    _digest(update["trusted_root_target_digest"], "trusted root target digest")
    metadata_digests = _keys(
        update["metadata_digests"],
        frozenset({"root", "timestamp", "snapshot", "targets"}),
        "TrustPolicy metadata digests",
    )
    for digest in metadata_digests.values():
        _digest(digest, "metadata digest")
    limits = _keys(
        policy["transport_limits"],
        frozenset(
            {
                "connect_timeout_seconds",
                "total_timeout_seconds",
                "max_response_bytes",
                "max_trusted_root_bytes",
            }
        ),
        "TransportLimits",
    )
    for value in limits.values():
        if type(value) is not int or value < 1:
            raise CB01SchemaError("Transport limits must be positive integers.")
    budget = _keys(
        policy["request_budget"],
        frozenset(
            {
                "max_attempts_per_fixture",
                "concurrency",
                "automatic_retries",
                "scope",
                "state",
                "reasons",
            }
        ),
        "RequestBudget",
    )
    if (
        budget["max_attempts_per_fixture"] != 2
        or budget["concurrency"] != 1
        or budget["automatic_retries"] != 0
    ):
        raise CB01SchemaError("TrustPolicy request budget differs from CB01 v1.")
    _nonempty_string(budget["scope"], "request scope")
    _nonempty_string(budget["state"], "request budget state")
    _reasons(budget["reasons"], "request budget reasons")


def _validate_trust_material(value: object) -> None:
    material = _keys(value, BODY_KEYS["TrustMaterial"], "TrustMaterial")
    for key in ("material_id", "material_version"):
        _nonempty_string(material[key], key)
    sources = _strings(material["primary_source_evidence_digests"], "TrustMaterial sources")
    if sources != sorted(set(sources)):
        raise CB01SchemaError("TrustMaterial source evidence digests must be sorted and unique.")
    for digest in sources:
        _digest(digest, "TrustMaterial source evidence digest")
    rows = material["certificates"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise CB01SchemaError("TrustMaterial v1 must retain the two pinned TSA certificates.")
    roles: list[str] = []
    cert_keys = frozenset(
        {
            "role",
            "der_digest",
            "der_fingerprint",
            "subject",
            "issuer",
            "serial_hex",
            "source_url",
            "anchor_decision",
        }
    )
    for row in rows:
        cert = _keys(row, cert_keys, "TrustMaterial certificate")
        roles.append(_nonempty_string(cert["role"], "certificate role"))
        _digest(cert["der_digest"], "certificate DER digest")
        _digest(cert["der_fingerprint"], "certificate DER fingerprint")
        if cert["der_digest"] != cert["der_fingerprint"]:
            raise CB01SchemaError("Certificate DER digest and fingerprint must match.")
        for key in ("subject", "issuer", "serial_hex", "source_url", "anchor_decision"):
            _nonempty_string(cert[key], key)
    if roles != ["SIGNER", "ANCHOR"]:
        raise CB01SchemaError("TrustMaterial certificates must be signer then anchor.")

"""Exact offline source-use projections. These bytes never grant current authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast

from matchvet.artifacts import ArtifactStore
from matchvet.causal_candidate import resolve as resolve_candidate
from matchvet.causal_trust import _parse_json_object
from matchvet.causal_witness import _canonical
from matchvet.f19 import SettlementRepository
from matchvet.matchweek_research import MatchweekResearchRepository
from matchvet.store import Store

MANIFEST_CONTRACT = "research-source-use-manifest-v1"
MANIFEST_MEDIA_TYPE = "application/vnd.matchvet.research-source-use-manifest.v1+json"
DECISION_CONTRACT = "research-real-source-use-decision-v2"
DECISION_MEDIA_TYPE = "application/vnd.matchvet.research-source-use-decision.v2+json"
RISK_BASIS = "PRODUCT_OWNER_AUTOMATION_RISK_ACCEPTED"
OPERATIONS = (
    "ATTRIBUTION",
    "AUTOMATED_ACCESS",
    "DERIVED_STATISTICAL_USE",
    "NORMALIZED_RETENTION",
    "PRIVATE_BACKUP_RESTORE_REPLAY",
    "RAW_RETENTION",
    "REDISTRIBUTION",
)
POLICY = {
    "contract": "research-source-risk-policy-v1",
    "revision": "ADR-0006-2026-10-10",
    "adr_digest": "b9d8650549f29e1483e95a091ff5f2a6eb59cbd0aeaded19239041e5ddde1ff5",
    "internal_basis": RISK_BASIS,
    "purpose": "RESEARCH_ONLY",
    "issue": 70,
    "private_retention": True,
    "redistributable": False,
    "external_permission_inferred": False,
    "access_control_bypass": False,
}
POLICY_BYTES = _canonical(POLICY)
POLICY_DIGEST = hashlib.sha256(POLICY_BYTES).hexdigest()
POLICY_MEDIA_TYPE = "application/vnd.matchvet.research-source-risk-policy.v1+json"

# Only exact primary-key references found in the selected artifacts are followed.
# No latest source, history, terms, health or outcome lookup is allowed.
_SOURCE_TABLES = {
    "source_identities": "source_id",
    "independent_origins": "origin_id",
    "source_captures": "capture_id",
    "evidence_captures": "capture_id",
    "source_assertions": "assertion_id",
    "evidence_assertions": "assertion_id",
    "fixture_revisions": "revision_id",
    "source_team_mappings": "mapping_id",
    "team_aliases": "alias_id",
}
_ENTRY_FIELDS = {
    "dependency_id",
    "provider",
    "publisher",
    "upstream_lineage",
    "source_type",
    "access_type",
    "endpoint",
    "raw_identity",
    "normalized_identity",
    "parser_version",
    "retrieved_at",
    "published_at",
    "observed_at",
    "competition",
    "season",
    "capability",
    "requested_operations",
    "external_permission",
    "operation_permissions",
    "terms_review",
    "internal_basis",
    "retention",
    "attribution",
    "technical_limits",
}


class SourceAuthorizationError(ValueError):
    """Exact source evidence or independently current authority is unavailable."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return _canonical(value)


def object_bytes(raw: bytes) -> dict[str, Any]:
    try:
        value = _parse_json_object(raw, "source-use")
    except ValueError as error:
        raise SourceAuthorizationError("Malformed source-use JSON evidence.") from error
    if canonical(value) != raw:
        raise SourceAuthorizationError("Source-use evidence is not canonical.")
    return value


def read(store: Store, identity: str, media_type: str) -> dict[str, Any]:
    metadata = store.artifact_metadata(identity)
    if metadata is None or (metadata.media_type, metadata.retention_class) != (
        media_type,
        "PROTECTED",
    ):
        raise SourceAuthorizationError("Missing exact protected source-use evidence.")
    return object_bytes(ArtifactStore(store).read_artifact(identity))


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise SourceAuthorizationError("Missing source authority timestamp.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise SourceAuthorizationError("Source timestamp lacks an explicit UTC offset.")
    return parsed.astimezone(UTC)


def _strings(value: object) -> set[str]:
    if isinstance(value, str):
        # JSON columns in selected SQLite rows contain further exact references.
        try:
            nested = json.loads(value)
        except ValueError:
            return {value}
        return {value} | (_strings(nested) if not isinstance(nested, str) else {nested})
    if isinstance(value, Mapping):
        return set().union(*(_strings(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(_strings(v) for v in value))
    return set()


def _closure(store: Store, roots: tuple[str, ...]) -> list[dict[str, Any]]:
    artifacts = ArtifactStore(store)
    dependencies: dict[str, dict[str, Any]] = {}
    strings: set[str] = set()
    pending_artifacts = set(roots)
    examined: set[str] = set()
    connection = store._connection_for_repository()
    while pending_artifacts or strings - examined:
        for identity in sorted(pending_artifacts):
            record = artifacts.verify_artifact(identity)
            raw = artifacts.read_artifact(identity)
            dependencies["artifact:" + identity] = {
                "id": "artifact:" + identity,
                "digest": identity,
                "media_type": record.media_type,
                "byte_length": record.byte_length,
                "retention_class": record.retention_class,
            }
            # Exact binary/raw bytes are already bound by their digest.
            with suppress(ValueError, UnicodeDecodeError):
                strings.update(_strings(json.loads(raw)))
        pending_artifacts = set()
        candidates = sorted(strings - examined)
        examined.update(candidates)
        for table, primary in _SOURCE_TABLES.items():
            for offset in range(0, len(candidates), 200):
                values = candidates[offset : offset + 200]
                marks = ",".join("?" for _ in values)
                cursor = connection.execute(
                    f"SELECT * FROM {table} WHERE {primary} IN ({marks})", values
                )
                columns = tuple(item[0] for item in cursor.description)
                for row in cursor:
                    facts = dict(zip(columns, row, strict=True))
                    identity = table + ":" + str(facts[primary])
                    dependencies[identity] = {
                        "id": identity,
                        "digest": digest(canonical(facts)),
                        "facts": facts,
                    }
                    strings.update(_strings(facts))
                    raw_identity = facts.get("artifact_digest")
                    if isinstance(raw_identity, str):
                        if "artifact:" + raw_identity not in dependencies:
                            pending_artifacts.add(raw_identity)
                        if facts.get("content_sha256") != raw_identity:
                            raise SourceAuthorizationError("Source raw identity/digest mismatch.")
    return [dependencies[key] for key in sorted(dependencies)]


def selected_projection(store: Store, selection_digest: str) -> dict[str, Any]:
    selected = MatchweekResearchRepository(store).inspect_causal(selection_digest)
    artifacts = ArtifactStore(store)
    selection = artifacts.verify_manifest(selection_digest)
    dependencies = _closure(store, tuple(ref.digest for ref in selection.artifacts))
    f16 = object_bytes(artifacts.read_artifact(selected.f16_manifest_digest))
    candidate = resolve_candidate(store, f16["candidate_contract_digest"])
    return {
        "selection_digest": selection_digest,
        "graph_digest": selection.aggregate_sha256,
        "selection": json.loads(selection.to_bytes()),
        "completion_receipt_digest": selected.completion_receipt_digest,
        "f16_manifest_digest": selected.f16_manifest_digest,
        "candidate_digest": candidate.digest,
        "freeze_digest": candidate.freeze_digest,
        "profile_digest": candidate.profile_digest,
        "decision_policy_digest": candidate.decision_policy_digest,
        "logical_matchweek_id": candidate.logical_matchweek_id,
        "freeze_id": selected.freeze_id,
        "cutoff_policy_digest": selected.policy_digest,
        "common_T": selected.cutoff_at_utc,
        "season": selected.season,
        "friday": selected.matchweek_friday,
        "dependencies": dependencies,
    }


def outcome_projection(
    store: Store, selection_digest: str, settlement_digest: str
) -> dict[str, Any]:
    selected = selected_projection(store, selection_digest)
    settlement = SettlementRepository(store).replay(settlement_digest).to_dict()
    if (
        settlement.get("selection_digest") != selection_digest
        or settlement.get("manifest_digest") != selected["f16_manifest_digest"]
    ):
        raise SourceAuthorizationError("Outcome source manifest differs from original selection.")
    # Outcomes have their own closure. They never join or replace the pre-T graph.
    return {
        "selection_digest": selection_digest,
        "graph_digest": selected["graph_digest"],
        "f16_manifest_digest": selected["f16_manifest_digest"],
        "settlement_digest": settlement_digest,
        "settlement": settlement,
        "dependencies": _closure(store, (settlement_digest,)),
    }


def _nonempty(value: object) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SourceAuthorizationError("Missing source-use classification identity.")


def _sorted_strings(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise SourceAuthorizationError("Malformed source-use identities.")
    if value != sorted(set(value)):
        raise SourceAuthorizationError("Duplicate or unordered source-use identities.")
    return cast(list[str], value)


def _validate_entry(store: Store, entry: dict[str, Any]) -> None:
    if set(entry) != _ENTRY_FIELDS or entry["internal_basis"] != RISK_BASIS:
        raise SourceAuthorizationError("Unsupported source-use classification/basis.")
    for key in (
        "dependency_id",
        "provider",
        "publisher",
        "endpoint",
        "parser_version",
        "competition",
        "season",
        "capability",
        "attribution",
    ):
        _nonempty(entry[key])
    if entry["source_type"] not in {
        "AUTOMATED_API",
        "AUTOMATED_DATASET",
        "AUTOMATED_PUBLIC_PAGE",
        "RETAINED_DATASET_REUSE",
        "MANUAL_CITATION",
        "OPERATOR_ATTESTATION",
        "DERIVED",
        "SELF_AUTHORED",
    } or entry["access_type"] not in {"PUBLIC", "MANUAL", "RETAINED", "NONE"}:
        raise SourceAuthorizationError("Source access class is outside ADR 0006.")
    lineage = entry["upstream_lineage"]
    if not isinstance(lineage, dict) or set(lineage) != {"state", "identities", "reason"}:
        raise SourceAuthorizationError("Missing explicit upstream lineage.")
    ids = _sorted_strings(lineage["identities"])
    if lineage["state"] not in {"KNOWN", "UNKNOWN"} or ((lineage["state"] == "KNOWN") != bool(ids)):
        raise SourceAuthorizationError("Unknown upstream lineage cannot invent ancestry.")
    _nonempty(lineage["reason"])
    for key in ("raw_identity", "normalized_identity"):
        identity = entry[key]
        if not isinstance(identity, dict) or set(identity) != {"id", "digest"}:
            raise SourceAuthorizationError("Missing raw/normalized identity.")
        _nonempty(identity["id"])
        _nonempty(identity["digest"])
    for key in ("retrieved_at", "published_at", "observed_at"):
        if entry[key] != "UNKNOWN":
            timestamp(entry[key])
    requested = _sorted_strings(entry["requested_operations"])
    if not requested or not set(requested).issubset(OPERATIONS) or "REDISTRIBUTION" in requested:
        raise SourceAuthorizationError("Risk acceptance permits private operations only.")
    permission = entry["external_permission"]
    if not isinstance(permission, dict) or set(permission) != {"state", "evidence", "reason"}:
        raise SourceAuthorizationError("Missing separate external permission truth.")
    evidence = _sorted_strings(permission["evidence"])
    _nonempty(permission["reason"])
    if permission["state"] not in {"UNKNOWN", "REFUSED", "GRANTED"} or (
        permission["state"] == "GRANTED" and not evidence
    ):
        raise SourceAuthorizationError("External grants require exact retained evidence.")
    dimensions = entry["operation_permissions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(OPERATIONS):
        raise SourceAuthorizationError("Source operations must be classified separately.")
    for result in dimensions.values():
        if (
            not isinstance(result, dict)
            or set(result) != {"state", "reason"}
            or result["state"] not in {"PERMITTED", "PROHIBITED", "UNKNOWN", "NOT_APPLICABLE"}
        ):
            raise SourceAuthorizationError("Malformed external operation classification.")
        _nonempty(result["reason"])
        if result["state"] == "PERMITTED" and permission["state"] != "GRANTED":
            raise SourceAuthorizationError(
                "Internal risk acceptance cannot imply external permission."
            )
    terms = entry["terms_review"]
    if not isinstance(terms, dict) or set(terms) != {
        "identity",
        "url",
        "digest",
        "reviewed_at",
        "effective_at",
        "valid_until",
        "classification",
        "evidence",
        "manual_policy_digest",
    }:
        raise SourceAuthorizationError("Missing exact terms/policy review.")
    for key in ("identity", "url", "digest", "classification"):
        _nonempty(terms[key])
    timestamp(terms["reviewed_at"])
    for key in ("effective_at", "valid_until"):
        if terms[key] != "UNKNOWN":
            timestamp(terms[key])
    terms_evidence = _sorted_strings(terms["evidence"])
    if not terms_evidence or terms["digest"] not in terms_evidence:
        raise SourceAuthorizationError("Terms review must retain its exact evidence.")
    for identity in sorted(set(evidence + terms_evidence)):
        metadata = store.artifact_metadata(identity)
        if metadata is None or metadata.retention_class != "PROTECTED":
            raise SourceAuthorizationError("Missing protected review/grant evidence.")
        ArtifactStore(store).verify_artifact(identity)
    manual_policy = terms["manual_policy_digest"]
    if (
        entry["source_type"] in {"MANUAL_CITATION", "OPERATOR_ATTESTATION"}
        and manual_policy == "UNKNOWN"
    ):
        raise SourceAuthorizationError("Selected manual evidence needs its exact manual policy.")
    if manual_policy != "UNKNOWN":
        ArtifactStore(store).verify_artifact(manual_policy)
    retention = entry["retention"]
    if (
        not isinstance(retention, dict)
        or set(retention)
        != {"class", "redistributable", "duration", "termination", "backup_location", "recipients"}
        or retention["class"] != "PROTECTED"
        or retention["redistributable"] is not False
    ):
        raise SourceAuthorizationError("Risk captures require private protected retention.")
    for key in ("duration", "termination", "backup_location", "recipients"):
        _nonempty(retention[key])
    limits = entry["technical_limits"]
    if (
        not isinstance(limits, dict)
        or set(limits)
        != {"requests", "bytes", "timeout_seconds", "rate_limit_review", "bypass_access_controls"}
        or limits["bypass_access_controls"] is not False
    ):
        raise SourceAuthorizationError("Missing bounded noncircumventing access plan.")
    for key in ("requests", "bytes", "timeout_seconds"):
        if type(limits[key]) is not int or limits[key] <= 0:
            raise SourceAuthorizationError("Source access limits must be positive integers.")
    _nonempty(limits["rate_limit_review"])


def _bind_dependency(entry: dict[str, Any], dependency: dict[str, Any]) -> None:
    expected = {"id": dependency["id"], "digest": dependency["digest"]}
    if entry["normalized_identity"] != expected:
        raise SourceAuthorizationError(
            "Classification normalized identity differs from exact dependency."
        )
    facts = dependency.get("facts", {})
    raw_digest = facts.get("artifact_digest")
    if "media_type" in dependency:
        raw_digest = dependency["digest"]
    if raw_digest is not None and entry["raw_identity"] != {
        "id": "artifact:" + raw_digest,
        "digest": raw_digest,
    }:
        raise SourceAuthorizationError("Classification raw identity differs from retained bytes.")
    if facts.get("locator") is not None and entry["endpoint"] != facts["locator"]:
        raise SourceAuthorizationError("Classification endpoint differs from source provenance.")
    for field, column in (
        ("retrieved_at", "retrieved_at_utc"),
        ("published_at", "source_published_at_utc"),
        ("observed_at", "observed_at_utc"),
    ):
        if column in facts:
            actual = facts[column]
            if (actual is None and entry[field] != "UNKNOWN") or (
                actual is not None
                and (entry[field] == "UNKNOWN" or timestamp(entry[field]) != timestamp(actual))
            ):
                raise SourceAuthorizationError("Classification changes known/UNKNOWN source times.")
    if "collector_version" in facts and entry["parser_version"] != facts["collector_version"]:
        raise SourceAuthorizationError("Classification changes retained collector version.")
    if "source_key" in facts and entry["provider"] != facts["source_key"]:
        raise SourceAuthorizationError("Classification changes retained provider identity.")
    if "owner" in facts and entry["publisher"] != facts["owner"]:
        raise SourceAuthorizationError("Classification changes retained publisher identity.")
    if facts.get("access_method") == "MANUAL_CITATION" and (
        entry["source_type"] not in {"MANUAL_CITATION", "OPERATOR_ATTESTATION"}
        or entry["access_type"] != "MANUAL"
    ):
        raise SourceAuthorizationError("Classification changes retained manual access provenance.")


def verify_manifest(store: Store, manifest_digest: str) -> dict[str, Any]:
    value = read(store, manifest_digest, MANIFEST_MEDIA_TYPE)
    if (
        set(value)
        != {
            "contract",
            "schema_version",
            "purpose",
            "issue",
            "stage",
            "selection_digest",
            "projection",
            "entries",
            "policy_digest",
        }
        or value["contract"] != MANIFEST_CONTRACT
        or type(value["schema_version"]) is not int
        or (
            value["schema_version"] != 1
            or value["purpose"] != "RESEARCH_ONLY"
            or type(value["issue"]) is not int
            or value["issue"] != 70
            or value["policy_digest"] != POLICY_DIGEST
        )
    ):
        raise SourceAuthorizationError("Unsupported source-use manifest/policy/purpose.")
    if read(store, POLICY_DIGEST, POLICY_MEDIA_TYPE) != POLICY:
        raise SourceAuthorizationError("Exact source risk policy is unavailable.")
    stage = value["stage"]
    projection = value["projection"]
    if stage == "SELECTED_GRAPH":
        expected = selected_projection(store, value["selection_digest"])
    elif stage == "OUTCOME":
        expected = outcome_projection(
            store, value["selection_digest"], projection["settlement_digest"]
        )
    elif stage == "ACQUISITION":
        if (
            value["selection_digest"] is not None
            or not isinstance(projection, dict)
            or set(projection) != {"request", "dependencies"}
            or projection["dependencies"] != []
        ):
            raise SourceAuthorizationError("Acquisition intent cannot claim a future graph.")
        request = projection["request"]
        if not isinstance(request, dict) or set(request) != {"identity", "entry"}:
            raise SourceAuthorizationError("Missing exact source acquisition request.")
        _nonempty(request["identity"])
        expected = projection
    else:
        raise SourceAuthorizationError("Unsupported source-use manifest stage.")
    if projection != expected:
        raise SourceAuthorizationError(
            "Source manifest differs from exact selected dependency closure."
        )
    entries = value["entries"]
    if (
        not isinstance(entries, list)
        or not entries
        or any(not isinstance(v, dict) for v in entries)
    ):
        raise SourceAuthorizationError("Source manifest lacks exact dependency classifications.")
    identities = [v.get("dependency_id") for v in entries]
    if any(not isinstance(v, str) for v in identities) or identities != sorted(set(identities)):
        raise SourceAuthorizationError("Duplicate/conflicting source dependency classification.")
    expected_ids = (
        [projection["request"]["identity"]]
        if stage == "ACQUISITION"
        else [dependency["id"] for dependency in projection["dependencies"]]
    )
    if identities != expected_ids or (
        stage == "ACQUISITION" and entries != [projection["request"]["entry"]]
    ):
        raise SourceAuthorizationError("Source manifest omits or adds selected dependencies.")
    for entry in entries:
        _validate_entry(store, entry)
    if stage != "ACQUISITION":
        for entry, dependency in zip(entries, projection["dependencies"], strict=True):
            _bind_dependency(entry, dependency)
    return value


def retain_manifest(
    store: Store,
    *,
    stage: str,
    selection_digest: str | None,
    projection: dict[str, Any],
    entries: tuple[dict[str, Any], ...],
) -> str:
    """Retain reviewable classifications; only independent signatures can authorize them."""
    artifacts = ArtifactStore(store)
    artifacts.publish_artifact(POLICY_BYTES, POLICY_MEDIA_TYPE)
    value = {
        "contract": MANIFEST_CONTRACT,
        "schema_version": 1,
        "purpose": "RESEARCH_ONLY",
        "issue": 70,
        "stage": stage,
        "selection_digest": selection_digest,
        "projection": projection,
        "entries": sorted(entries, key=lambda v: v["dependency_id"]),
        "policy_digest": POLICY_DIGEST,
    }
    identity = artifacts.publish_artifact(canonical(value), MANIFEST_MEDIA_TYPE).digest
    verify_manifest(store, identity)
    return identity

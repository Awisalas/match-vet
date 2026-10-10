"""Independent current source authority, separate from causal owner activation.

The owner installs configuration outside Store recovery. A fresh authenticated
checkpoint is required for every dispatch and admission. Retained keys are only
historical evidence. See docs/design/research-source-authorization.md.
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.causal_activation import _checkpoint, _hex
from matchvet.causal_trust import _openssl
from matchvet.source_manifest import (
    DECISION_CONTRACT,
    DECISION_MEDIA_TYPE,
    MANIFEST_MEDIA_TYPE,
    POLICY_DIGEST,
    RISK_BASIS,
    SourceAuthorizationError,
    canonical,
    digest,
    object_bytes,
    read,
    timestamp,
    verify_manifest,
)
from matchvet.store import Store

_SOURCE_CONFIG = Path(sys.base_prefix) / "etc/matchvet/source-authorizer-v1.json"
_DOMAIN = "matchvet-source-authority-v1"
_IDENTITY = ("owner", "deployment", "catalog", "history")
_FIELDS = {
    "domain",
    "schema_version",
    "algorithm",
    "action",
    *_IDENTITY,
    "sequence",
    "predecessor",
    "purpose",
    "issue",
    "manifest_digest",
    "policy_digest",
    "issued_at",
    "not_before",
    "not_after",
    "state",
    "reason_codes",
    "adverse",
    "replacement_manifest_digest",
}
_STATES = {"APPROVED", "REFUSED", "UNKNOWN", "WITHDRAWN", "SUPERSEDED"}
ELIGIBILITY_MEDIA_TYPE = "application/vnd.matchvet.research-source-eligibility.v1+json"
# Logical raw/normalized roles live in the eligibility record. Identical bytes
# share one content-addressed object, including when normalization is lossless.
RAW_MEDIA_TYPE = "application/vnd.matchvet.private-research-source.bytes"
NORMALIZED_MEDIA_TYPE = RAW_MEDIA_TYPE
_RETAINED_OPERATIONS = {
    "RAW_RETENTION",
    "NORMALIZED_RETENTION",
    "PRIVATE_BACKUP_RESTORE_REPLAY",
    "DERIVED_STATISTICAL_USE",
}


def _verify(raw: bytes, key: bytes) -> dict[str, Any]:
    if len(raw) > 16 * 1024 * 1024:
        raise SourceAuthorizationError("Source authority evidence exceeds its bound.")
    if len(key) != 44 or key[:12] != bytes.fromhex("302a300506032b6570032100"):
        raise SourceAuthorizationError("Source authority requires Ed25519 SPKI DER.")
    envelope = object_bytes(raw)
    if set(envelope) != {"signed", "signature"} or not isinstance(envelope["signed"], dict):
        raise SourceAuthorizationError("Unsupported source authority envelope.")
    signed = envelope["signed"]
    signature = _hex(envelope["signature"])
    if (
        len(signature) != 64
        or signed.get("domain") != _DOMAIN
        or type(signed.get("schema_version")) is not int
        or signed["schema_version"] != 1
        or signed.get("algorithm") != "Ed25519"
        or (signed.get("owner") != digest(key))
    ):
        raise SourceAuthorizationError("Source authority domain/schema/key mismatch.")
    with tempfile.TemporaryDirectory(prefix="matchvet-source-verify-") as directory:
        work = Path(directory)
        for name, content in (
            ("key.der", key),
            ("message", _DOMAIN.encode() + b"\0" + canonical(signed)),
            ("signature", signature),
        ):
            (work / name).write_bytes(content)
        _openssl(
            [
                "pkeyutl",
                "-verify",
                "-pubin",
                "-keyform",
                "DER",
                "-inkey",
                str(work / "key.der"),
                "-rawin",
                "-in",
                str(work / "message"),
                "-sigfile",
                str(work / "signature"),
            ]
        )
    return signed


def _history(records: tuple[bytes, ...], key: bytes) -> dict[str, tuple[dict[str, Any], bytes]]:
    if not records or len(records) > 1024:
        raise SourceAuthorizationError("Missing bounded source authority history.")
    state: dict[str, tuple[dict[str, Any], bytes]] = {}
    first: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    for sequence, raw in enumerate(records, 1):
        value = _verify(raw, key)
        if (
            set(value) != _FIELDS
            or type(value["sequence"]) is not int
            or (
                value["sequence"] != sequence
                or value["predecessor"]
                != (None if sequence == 1 else digest(records[sequence - 2]))
                or value["purpose"] != "RESEARCH_ONLY"
                or type(value["issue"]) is not int
                or value["issue"] != 70
                or value["policy_digest"] != POLICY_DIGEST
                or value["state"] not in _STATES
                or any(not isinstance(value[k], str) or not value[k] for k in _IDENTITY)
                or timestamp(value["not_before"]) >= timestamp(value["not_after"])
            )
        ):
            raise SourceAuthorizationError("Source authority identity/policy/sequence mismatch.")
        timestamp(value["issued_at"])
        if first is not None and any(value[k] != first[k] for k in _IDENTITY):
            raise SourceAuthorizationError("Source authority history changes issuer/deployment.")
        if previous is not None and timestamp(value["issued_at"]) < timestamp(
            previous["issued_at"]
        ):
            raise SourceAuthorizationError("Source authority publication chronology rolled back.")
        reasons = value["reason_codes"]
        if (
            not isinstance(reasons, list)
            or any(not isinstance(v, str) or not v for v in reasons)
            or (reasons != sorted(set(reasons)) or (value["state"] == "APPROVED") != (not reasons))
        ):
            raise SourceAuthorizationError("Source authority state/reasons disagree.")
        target = value["manifest_digest"]
        if not isinstance(target, str) or len(_hex(target)) != 32:
            raise SourceAuthorizationError("Missing exact authorized manifest identity.")
        prior = state.get(target)
        action = value["action"]
        if action == "authorize":
            if (
                prior is not None
                or value["state"] not in {"APPROVED", "REFUSED", "UNKNOWN"}
                or (
                    value["adverse"] is not None or value["replacement_manifest_digest"] is not None
                )
            ):
                raise SourceAuthorizationError(
                    "Authorization cannot rewrite a prior classification."
                )
        elif action in {"withdraw", "supersede", "reconcile"}:
            if prior is None:
                raise SourceAuthorizationError("Source change has no exact authorized predecessor.")
            original = prior[0]
            if any(
                value[k] != original[k]
                for k in ("not_before", "not_after", "manifest_digest", "policy_digest")
            ):
                raise SourceAuthorizationError("Source change broadens an immutable authorization.")
            if action == "reconcile":
                if any(
                    value[k] != original[k]
                    for k in ("state", "reason_codes", "adverse", "replacement_manifest_digest")
                ):
                    raise SourceAuthorizationError(
                        "Reconciliation cannot restore withdrawn capability."
                    )
            else:
                expected = "WITHDRAWN" if action == "withdraw" else "SUPERSEDED"
                if (
                    original["state"]
                    not in (
                        {"APPROVED", "UNKNOWN", "REFUSED", "WITHDRAWN"}
                        if action == "supersede"
                        else {"APPROVED", "UNKNOWN", "REFUSED"}
                    )
                    or value["state"] != expected
                ):
                    raise SourceAuthorizationError("Conflicting source withdrawal/supersession.")
                adverse = value["adverse"]
                if (
                    not isinstance(adverse, dict)
                    or set(adverse) != {"effective_from", "published_at", "observed_at", "reason"}
                    or not isinstance(adverse["reason"], str)
                    or not adverse["reason"]
                ):
                    raise SourceAuthorizationError("Missing exact source adverse evidence.")
                for field in ("published_at", "observed_at"):
                    timestamp(adverse[field])
                if adverse["effective_from"] != "UNKNOWN":
                    timestamp(adverse["effective_from"])
                replacement = value["replacement_manifest_digest"]
                if (action == "withdraw" and replacement is not None) or (
                    action == "supersede"
                    and (
                        not isinstance(replacement, str)
                        or len(_hex(replacement)) != 32
                        or replacement == target
                    )
                ):
                    raise SourceAuthorizationError(
                        "Supersession needs a different reviewed manifest."
                    )
        else:
            raise SourceAuthorizationError("Unsupported source authority action.")
        state[target] = (value, raw)
        first = first or value
        previous = value
    return state


def _check_head(
    raw: bytes,
    key: bytes,
    records: tuple[bytes, ...],
    nonce: str | None,
    *,
    expected_head: tuple[dict[str, Any], str] | None = None,
) -> dict[str, Any]:
    if expected_head is None:
        expected_head = object_bytes(records[-1])["signed"], digest(records[-1])
    last, last_digest = expected_head
    head = _verify(raw, key)
    if (
        set(head)
        != {
            "domain",
            "schema_version",
            "algorithm",
            "action",
            *_IDENTITY,
            "nonce",
            "sequence",
            "head",
            "continuity",
            "current_time",
        }
        or head["action"] != "checkpoint"
        or head["continuity"] != "RECONCILED"
        or (nonce is not None and head["nonce"] != nonce)
        or len(_hex(head["nonce"])) != 32
        or type(head["sequence"]) is not int
        or (
            head["sequence"] != len(records)
            or head["head"] != last_digest
            or any(head[k] != last[k] for k in _IDENTITY)
            or timestamp(head["current_time"]) < timestamp(last["issued_at"])
        )
    ):
        raise SourceAuthorizationError(
            "Stale, rolled-back, conflicting or uncertain source checkpoint."
        )
    return head


def _installation(
    store: Store,
) -> tuple[dict[str, Any], tuple[bytes, ...], bytes, dict[str, tuple[dict[str, Any], bytes]]]:
    status = _SOURCE_CONFIG.stat()
    if status.st_uid != os.getuid() or status.st_mode & 0o022 or _SOURCE_CONFIG.is_symlink():
        raise SourceAuthorizationError(
            "Source authority installation is not independently protected."
        )
    config = object_bytes(_SOURCE_CONFIG.read_bytes())
    if set(config) != {
        "verification_key",
        "deployment",
        "catalog",
        "history",
        "records",
        "checkpoint_socket",
    } or any(not isinstance(v, str) or not v for v in config.values()):
        raise SourceAuthorizationError(
            "Missing independently installed source authorizer configuration."
        )
    if config["catalog"] != str(store.path.resolve()) or any(
        not Path(config[k]).is_absolute() for k in ("records", "checkpoint_socket")
    ):
        raise SourceAuthorizationError("Source authority catalog/installation mismatch.")
    paths = sorted(Path(config["records"]).iterdir())
    if (
        not paths
        or len(paths) > 1024
        or [p.name for p in paths] != [f"{n:020d}.json" for n in range(1, len(paths) + 1)]
        or any(p.is_symlink() or not p.is_file() for p in paths)
    ):
        raise SourceAuthorizationError("Missing or forked append-only source authority history.")
    records = tuple(p.read_bytes() for p in paths)
    key = _hex(config["verification_key"])
    state = _history(records, key)
    last = object_bytes(records[-1])["signed"]
    if any(last[k] != config[k] for k in ("deployment", "catalog", "history")):
        raise SourceAuthorizationError("Source authority installation and history conflict.")
    return config, records, key, state


def _current_checkpoint(
    config: dict[str, Any], records: tuple[bytes, ...], key: bytes
) -> tuple[bytes, dict[str, Any]]:
    expected_head = object_bytes(records[-1])["signed"], digest(records[-1])
    nonce = secrets.token_bytes(32).hex()
    checkpoint = _checkpoint(config, nonce)
    head = _check_head(checkpoint, key, records, nonce, expected_head=expected_head)
    return checkpoint, head


def _load(store: Store) -> dict[str, Any]:
    config, records, key, _state = _installation(store)
    checkpoint, _head = _current_checkpoint(config, records, key)
    return {
        "records": [v.hex() for v in records],
        "checkpoint": checkpoint.hex(),
        "verification_key": key.hex(),
    }


def _evidence(
    value: dict[str, Any],
) -> tuple[dict[str, tuple[dict[str, Any], bytes]], dict[str, Any]]:
    if set(value) != {"records", "checkpoint", "verification_key"} or not isinstance(
        value["records"], list
    ):
        raise SourceAuthorizationError("Malformed retained source authority evidence.")
    records = tuple(_hex(v) for v in value["records"])
    key = _hex(value["verification_key"])
    state = _history(records, key)
    head = _check_head(_hex(value["checkpoint"]), key, records, None)
    return state, head


def _decision(
    manifest_digest: str, manifest: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    state, head = _evidence(evidence)
    if manifest_digest not in state:
        raise SourceAuthorizationError("No independently current exact manifest authorization.")
    record, raw = state[manifest_digest]
    return {
        "contract": DECISION_CONTRACT,
        "schema_version": 2,
        "purpose": "RESEARCH_ONLY",
        "issue": 70,
        "manifest_digest": manifest_digest,
        "policy_digest": POLICY_DIGEST,
        "binding": {
            "stage": manifest["stage"],
            "selection_digest": manifest["selection_digest"],
            "projection_digest": digest(canonical(manifest["projection"])),
        },
        "state": record["state"],
        "reason_codes": record["reason_codes"],
        "authority": record["owner"],
        "authority_record_digest": digest(raw),
        "issued_at": head["current_time"],
        "not_before": record["not_before"],
        "not_after": record["not_after"],
        "evidence": evidence,
    }


def replay_decision(store: Store, decision_digest: str) -> dict[str, Any]:
    """Historical inspection only. No runtime configuration, checkpoint call or network."""
    try:
        value = read(store, decision_digest, DECISION_MEDIA_TYPE)
        manifest = verify_manifest(store, value["manifest_digest"], historical_inspection=True)
        if value != _decision(value["manifest_digest"], manifest, value["evidence"]):
            raise SourceAuthorizationError(
                "Source-use decision differs from exact signed evidence."
            )
        return value
    except (OSError, ValueError, TypeError, KeyError, ArtifactError) as error:
        raise SourceAuthorizationError(
            "Exact V2 source decision failed historical replay."
        ) from error


def _applicability_window(
    manifest: dict[str, Any], decision: dict[str, Any]
) -> tuple[datetime, datetime]:
    if decision["state"] != "APPROVED":
        raise SourceAuthorizationError(
            "Source authority is missing, expired, refused or withdrawn."
        )
    lower, upper = timestamp(decision["not_before"]), timestamp(decision["not_after"])
    required = _RETAINED_OPERATIONS | (
        {"AUTOMATED_ACCESS"} if manifest["stage"] == "ACQUISITION" else set()
    )
    for entry in manifest["entries"]:
        if not required.issubset(entry["requested_operations"]):
            raise SourceAuthorizationError(
                "Source manifest lacks required retention/replay/derived operation authority."
            )
        terms = entry["terms_review"]
        lower = max(lower, timestamp(terms["reviewed_at"]))
        if terms["valid_until"] != "UNKNOWN":
            upper = min(upper, timestamp(terms["valid_until"]))
    return lower, upper


def _require_applicable(manifest: dict[str, Any], decision: dict[str, Any]) -> None:
    lower, upper = _applicability_window(manifest, decision)
    if not lower <= timestamp(decision["issued_at"]) < upper:
        raise SourceAuthorizationError(
            "Source authority or terms classification is expired or not yet applicable."
        )


def _scope(manifest: dict[str, Any]) -> tuple[object, ...]:
    stage = manifest["stage"]
    if stage == "ACQUISITION":
        entry = manifest["entries"][0]
        return (
            stage,
            *(entry[k] for k in ("provider", "endpoint", "competition", "season", "capability")),
        )
    return (stage, manifest["selection_digest"], manifest["projection"].get("settlement_digest"))


def _classification_scopes(
    store: Store, manifest_digest: str, state: dict[str, tuple[dict[str, Any], bytes]]
) -> dict[str, tuple[object, ...]]:
    return {
        identity: _scope(read(store, identity, MANIFEST_MEDIA_TYPE))
        for identity, (record, _raw) in state.items()
        if identity != manifest_digest and record["state"] != "SUPERSEDED"
    }


def _require_unambiguous(
    manifest_digest: str,
    manifest: dict[str, Any],
    state: dict[str, tuple[dict[str, Any], bytes]],
    head: dict[str, Any],
    scopes: dict[str, tuple[object, ...]],
) -> None:
    now = timestamp(head["current_time"])
    for identity, (record, _raw) in state.items():
        if (
            identity == manifest_digest
            or record["state"] == "SUPERSEDED"
            or (
                record["state"] == "APPROVED"
                and not (timestamp(record["not_before"]) <= now < timestamp(record["not_after"]))
            )
        ):
            continue
        if scopes[identity] == _scope(manifest):
            raise SourceAuthorizationError(
                "Conflicting current source classifications need explicit supersession."
            )


@dataclass(frozen=True)
class PrivateSourceCapture:
    raw_digest: str
    normalized_digest: str
    eligibility_digest: str
    decision_digest: str


class SourceAuthorizationRepository:
    """Authorize exact retained manifests through independently installed current state."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def authorize(self, manifest_digest: str) -> str:
        """Retain V2 status. A retained status alone cannot dispatch or admit anything."""
        try:
            evidence = _load(self.store)
            manifest = verify_manifest(self.store, manifest_digest)
            decision = _decision(manifest_digest, manifest, evidence)
            if decision["state"] == "APPROVED":
                _require_applicable(manifest, decision)
                state, head = _evidence(evidence)
                _require_unambiguous(
                    manifest_digest,
                    manifest,
                    state,
                    head,
                    _classification_scopes(self.store, manifest_digest, state),
                )
            return (
                ArtifactStore(self.store)
                .publish_artifact(canonical(decision), DECISION_MEDIA_TYPE)
                .digest
            )
        except (OSError, ValueError, TypeError, KeyError, ArtifactError) as error:
            raise SourceAuthorizationError(
                "Current source authorization is unavailable; use refused."
            ) from error

    def require_current(self, decision_digest: str) -> dict[str, Any]:
        """Recheck independent continuity and original lineage immediately before a side effect."""
        try:
            original = replay_decision(self.store, decision_digest)
            manifest = verify_manifest(self.store, original["manifest_digest"])
            _require_applicable(manifest, original)
            config, records, key, state = _installation(self.store)
            old = original["evidence"]
            if key.hex() != old["verification_key"] or (
                [v.hex() for v in records[: len(old["records"])]] != old["records"]
            ):
                raise SourceAuthorizationError(
                    "Retained source authorization is outside current lineage."
                )
            scopes = _classification_scopes(self.store, original["manifest_digest"], state)
            record = state.get(original["manifest_digest"])
            if record is None:
                raise SourceAuthorizationError("No independently current exact authorization.")
            lower, upper = _applicability_window(manifest, record[0])
            conflicts = [
                (timestamp(other["not_before"]), timestamp(other["not_after"]))
                if other["state"] == "APPROVED"
                else None
                for identity, (other, _raw) in state.items()
                if identity != original["manifest_digest"]
                and other["state"] != "SUPERSEDED"
                and scopes[identity] == _scope(manifest)
            ]
            original_time = timestamp(original["issued_at"])
            # All retained reads, manifest checks, history verification and time
            # parsing precede this fresh checkpoint. A completed change during
            # validation appears in state or makes the checkpoint disagree.
            _checkpoint_bytes, head = _current_checkpoint(config, records, key)
            now = timestamp(head["current_time"])
            if now < original_time:
                raise SourceAuthorizationError("Current source checkpoint time rolled back.")
            if not lower <= now < upper:
                raise SourceAuthorizationError("Current source authority or terms review expired.")
            if any(window is None or window[0] <= now < window[1] for window in conflicts):
                raise SourceAuthorizationError(
                    "Conflicting current source classifications need explicit supersession."
                )
            return manifest
        except (OSError, ValueError, TypeError, KeyError, ArtifactError) as error:
            raise SourceAuthorizationError(
                "Current source authorization changed or is uncertain; use refused."
            ) from error

    def acquire(
        self,
        manifest_digest: str,
        acquire_bytes: Callable[[], bytes],
        normalize: Callable[[bytes], bytes],
    ) -> PrivateSourceCapture:
        """Bounded byte acquisition seam for future adapters, with private protected admission.

        Adapters must enforce the exact endpoint, access plan and provider limits.
        This seam installs no adapter and performs no source access on its own.
        """
        decision_digest = self.authorize(manifest_digest)
        manifest = self.require_current(decision_digest)
        if manifest["stage"] != "ACQUISITION":
            raise SourceAuthorizationError(
                "Acquisition requires a separate prospective source intent."
            )
        entry = manifest["entries"][0]
        if entry["access_type"] != "PUBLIC" or entry["source_type"] not in {
            "AUTOMATED_API",
            "AUTOMATED_DATASET",
            "AUTOMATED_PUBLIC_PAGE",
        }:
            raise SourceAuthorizationError(
                "Acquisition requires an automated public-source intent."
            )

        def guard() -> object:
            return self.require_current(decision_digest)

        guard()  # dispatch, with no cached authorizer capability
        raw = acquire_bytes()
        if not isinstance(raw, bytes) or len(raw) > entry["technical_limits"]["bytes"]:
            raise SourceAuthorizationError("Source capture exceeded its exact byte plan.")
        guard()
        normalized = normalize(raw)
        if (
            not isinstance(normalized, bytes)
            or len(normalized) > entry["technical_limits"]["bytes"]
        ):
            raise SourceAuthorizationError("Normalized capture exceeded its byte plan.")
        artifacts = ArtifactStore(self.store, write_guard=guard)
        raw_digest = artifacts.publish_artifact(raw, RAW_MEDIA_TYPE).digest
        normalized_digest = artifacts.publish_artifact(normalized, NORMALIZED_MEDIA_TYPE).digest
        eligibility = {
            "contract": "research-source-internal-eligibility-v1",
            "schema_version": 1,
            "internal_basis": RISK_BASIS,
            "purpose": "RESEARCH_ONLY",
            "manifest_digest": manifest_digest,
            "decision_digest": decision_digest,
            "provider": entry["provider"],
            "competition": entry["competition"],
            "season": entry["season"],
            "capability": entry["capability"],
            "raw_digest": raw_digest,
            "normalized_digest": normalized_digest,
            "external_permission": entry["external_permission"],
            "retention": entry["retention"],
        }
        eligibility_digest = artifacts.publish_artifact(
            canonical(eligibility), ELIGIBILITY_MEDIA_TYPE
        ).digest
        return PrivateSourceCapture(
            raw_digest, normalized_digest, eligibility_digest, decision_digest
        )

    def coverage_eligibility(
        self,
        eligibility_digest: str,
        *,
        provider: str,
        competition: str,
        season: str,
        capability: str,
        raw_digest: str,
    ) -> str:
        """Return an exact F01 internal policy reference; supply no coverage/freshness claim.

        F05 keeps its released external/policy permission assessment. This sidecar
        is a separate internal risk eligibility reference for prospective use.
        """
        value = read(self.store, eligibility_digest, ELIGIBILITY_MEDIA_TYPE)
        manifest = self.require_current(value["decision_digest"])
        entry = manifest["entries"][0]
        expected = {
            "contract": "research-source-internal-eligibility-v1",
            "schema_version": 1,
            "internal_basis": RISK_BASIS,
            "purpose": "RESEARCH_ONLY",
            "manifest_digest": digest(canonical(manifest)),
            "decision_digest": value["decision_digest"],
            "provider": provider,
            "competition": competition,
            "season": season,
            "capability": capability,
            "raw_digest": raw_digest,
            "normalized_digest": value["normalized_digest"],
            "external_permission": entry["external_permission"],
            "retention": entry["retention"],
        }
        if value != expected or any(
            entry[k] != expected[k] for k in ("provider", "competition", "season", "capability")
        ):
            raise SourceAuthorizationError(
                "Internal source eligibility differs from exact capture/scope."
            )
        for identity, media_type in (
            (value["raw_digest"], RAW_MEDIA_TYPE),
            (value["normalized_digest"], NORMALIZED_MEDIA_TYPE),
        ):
            metadata = self.store.artifact_metadata(identity)
            if metadata is None or (metadata.media_type, metadata.retention_class) != (
                media_type,
                "PROTECTED",
            ):
                raise SourceAuthorizationError("Risk capture is not private/protected.")
            ArtifactStore(self.store).verify_artifact(identity)
        return eligibility_digest

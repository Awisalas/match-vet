"""Bounded Sigstore TUF refresh and RFC 3161 verification for CB01."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from matchvet.cb01_schema import (
    CB01SchemaError,
    compare_utc,
    digest_bytes,
    encode_artifact,
)

TSA_ENDPOINT = "https://timestamp.sigstore.dev/api/v1/timestamp"
TUF_BASE_URL = "https://tuf-repo-cdn.sigstore.dev/"
TUF_ROOT_HISTORY_BASE_URL = (
    "https://raw.githubusercontent.com/sigstore/root-signing/main/metadata/root_history/"
)
TUF_TARGET_MIRROR_URL = (
    "https://raw.githubusercontent.com/sigstore/root-signing/main/targets/trusted_root.json"
)
BOOTSTRAP_ROOT_VERSION = 10
BOOTSTRAP_ROOT_SHA256 = "836bff947925edfc23eb9ce17af66fb1e43bb5e2bdd240520985ae52b585eae9"
TRUSTED_ROOT_SHA256 = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66"
TSA_SIGNER_SHA256 = "85f927bc07ab62cac3b44356c10efc81b2c6883fda7ab9e6d870d9d13acd05b7"
TSA_ANCHOR_SHA256 = "2aca8fea5d3ce48b01cc77076293c280e6c23ffe44034757ee7833ca9f45d633"
TSA_POLICY_OID = "1.3.6.1.4.1.57264.2"
TSA_SUBJECT = "O=sigstore.dev, CN=sigstore-tsa"
TSA_ISSUER = "O=sigstore.dev, CN=sigstore-tsa-selfsigned"
TSA_VALID_FROM = "2025-04-08T06:59:43Z"
TSA_VALID_UNTIL = "2035-04-06T06:59:43Z"
TRUSTED_ROOT_VALID_FROM = "2025-07-04T00:00:00Z"
CMS_DIGEST_OID = "2.16.840.1.101.3.4.2.1"
CMS_SIGNATURE_OID = "1.2.840.10045.4.3.2"
SHA256_OID = "2.16.840.1.101.3.4.2.1"
TST_INFO_OID = "1.2.840.113549.1.9.16.1.4"
ESS_SIGNING_CERT_V2_OID = "1.2.840.113549.1.9.16.2.47"
MAX_TUF_ROOT_UPDATES = 64
MAX_TUF_ROLE_SIGNATURES = 64
MAX_TUF_ROLE_KEYIDS = 16
MAX_REFRESH_SECONDS = 120
OPENSSL_STEP_TIMEOUT_SECONDS = 8

# These are the exact authenticated metadata versions reviewed into CB01 v1.
TUF_METADATA_VERSION_FLOORS = {"timestamp": 799, "snapshot": 165, "targets": 14}

ROOT_MEDIA_TYPE = "application/vnd.matchvet.sigstore-tuf-root.v1+json"
TIMESTAMP_MEDIA_TYPE = "application/vnd.matchvet.sigstore-tuf-timestamp.v1+json"
SNAPSHOT_MEDIA_TYPE = "application/vnd.matchvet.sigstore-tuf-snapshot.v1+json"
TARGETS_MEDIA_TYPE = "application/vnd.matchvet.sigstore-tuf-targets.v1+json"
TRUSTED_ROOT_MEDIA_TYPE = "application/vnd.matchvet.sigstore-trusted-root.v1+json"
REQUEST_MEDIA_TYPE = "application/vnd.matchvet.cb01-rfc3161-query+der"
RESPONSE_MEDIA_TYPE = "application/vnd.matchvet.cb01-rfc3161-response+der"


class CB01TrustError(ValueError):
    """Sigstore TUF or RFC 3161 material failed the frozen CB01 policy."""


def _utc_now() -> datetime:
    """Return current UTC for TUF refresh validation, independently of chronology proof."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class TrustRefresh:
    root_history: tuple[bytes, ...]
    timestamp: bytes
    snapshot: bytes
    targets: bytes
    trusted_root: bytes
    target_source_url: str
    state: dict[str, Any]
    tsa_entry: dict[str, Any]
    signer_der: bytes
    anchor_der: bytes

    def retained_artifacts(self) -> tuple[tuple[str, bytes], ...]:
        return (
            *((ROOT_MEDIA_TYPE, _bootstrap_root_bytes()),),
            *((ROOT_MEDIA_TYPE, raw) for raw in self.root_history),
            (TIMESTAMP_MEDIA_TYPE, self.timestamp),
            (SNAPSHOT_MEDIA_TYPE, self.snapshot),
            (TARGETS_MEDIA_TYPE, self.targets),
            (TRUSTED_ROOT_MEDIA_TYPE, self.trusted_root),
        )


@dataclass(frozen=True)
class TimestampRequest:
    der: bytes
    nonce_hex: str


@dataclass(frozen=True)
class TimestampTransport:
    state: str
    response: bytes | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TimestampVerificationResult:
    state: str
    tsa: dict[str, Any]
    chain_fingerprints: tuple[str, ...]
    checks: dict[str, dict[str, Any]]
    reasons: tuple[str, ...]


class WitnessBackend(Protocol):
    """Private seam for deterministic TUF/TSA fixtures in the normal test suite."""

    def refresh_trust(self, policy_body: dict[str, Any]) -> TrustRefresh: ...

    def replay_trust(
        self,
        root_history: tuple[bytes, ...],
        timestamp: bytes,
        snapshot: bytes,
        targets: bytes,
        trusted_root: bytes,
        policy_body: dict[str, Any],
    ) -> TrustRefresh: ...

    def create_request(self, batch_bytes: bytes) -> TimestampRequest: ...

    def submit_request(
        self, request_der: bytes, policy_body: dict[str, Any]
    ) -> TimestampTransport: ...

    def verify_response(
        self,
        request_der: bytes,
        nonce_hex: str,
        response_der: bytes,
        trust: TrustRefresh,
        policy_body: dict[str, Any],
        *,
        batch_digest: str,
        cutoff_utc: str,
        kickoff_utc: str,
    ) -> TimestampVerificationResult: ...


def trust_material_body() -> dict[str, Any]:
    signer_der = _certificate_bytes("sigstore-tsa-leaf.der")
    anchor_der = _certificate_bytes("sigstore-tsa-root.der")
    return {
        "material_id": "cb01-sigstore-tsa-trust-material",
        "material_version": "1",
        "certificates": [
            {
                "role": "SIGNER",
                "der_digest": digest_bytes(signer_der),
                "der_fingerprint": digest_bytes(signer_der),
                "subject": TSA_SUBJECT,
                "issuer": TSA_ISSUER,
                "serial_hex": "3a13542f0c9061eebcc1432fcb8a8e8b2a238b0c",
                "source_url": TUF_TARGET_MIRROR_URL,
                "anchor_decision": "PINNED_SIGSTORE_TUF_TIMESTAMP_AUTHORITY",
            },
            {
                "role": "ANCHOR",
                "der_digest": digest_bytes(anchor_der),
                "der_fingerprint": digest_bytes(anchor_der),
                "subject": TSA_ISSUER,
                "issuer": TSA_ISSUER,
                "serial_hex": "57b7f418b0cea04cc887c2d7496f34389894a75e",
                "source_url": TUF_TARGET_MIRROR_URL,
                "anchor_decision": "PINNED_SIGSTORE_TUF_TIMESTAMP_AUTHORITY",
            },
        ],
        "primary_source_evidence_digests": sorted((BOOTSTRAP_ROOT_SHA256, TRUSTED_ROOT_SHA256)),
    }


def trust_material_artifact() -> bytes:
    return encode_artifact("TrustMaterial", trust_material_body())


def trust_policy_body() -> dict[str, Any]:
    material_digest = digest_bytes(trust_material_artifact())
    return {
        "policy_id": "cb01-sigstore-tuf-rfc3161-v1",
        "policy_version": "1",
        "material_digest": material_digest,
        "endpoint": TSA_ENDPOINT,
        "imprint_algorithm": "sha256",
        "cms_digest_algorithm": "sha256",
        "cms_signature_oid": CMS_SIGNATURE_OID,
        "allowed_token_policy_oids": [TSA_POLICY_OID],
        "signer_fingerprints": [TSA_SIGNER_SHA256],
        "anchor_fingerprints": [TSA_ANCHOR_SHA256],
        "certificate_time_basis": "SIGNED_GEN_TIME",
        "trust_update_policy": {
            "mode": "SIGSTORE_TUF_TRUSTED_ROOT",
            "bootstrap_root_version": BOOTSTRAP_ROOT_VERSION,
            "current_root_version": 15,
            "trusted_root_target_digest": TRUSTED_ROOT_SHA256,
            "metadata_digests": {
                "root": "73747011d0857ada15479a16c4cae0f3ed03aac698b523b97e1de314ac9d9ca8",
                "timestamp": "b8cd928494ed0736a71f93bf0bcb0e1d5bcfc4b871bc564b235306dac513b783",
                "snapshot": "8f784ab614ec62bfdd5f568eb2a2e3011668449ba235ed4eb7befa99f8469933",
                "targets": "6a697f7f8908c8ab26c11786ecb490b54acec97fa8c802e399f065f8a0cc1acd",
            },
            "refresh_before_each_batch": True,
            "post_issuance_reassessment": "EXPLICIT_IMMUTABLE",
        },
        "transport_limits": {
            "connect_timeout_seconds": 10,
            "total_timeout_seconds": 30,
            "max_response_bytes": 1_048_576,
            "max_trusted_root_bytes": 10_485_760,
        },
        "request_budget": {
            "max_attempts_per_fixture": 2,
            "concurrency": 1,
            "automatic_retries": 0,
            "scope": "ONE_NORMAL_REQUEST_AND_AT_MOST_ONE_EXPLICIT_RETRY_PER_FIXTURE_BATCH",
            "state": "NO_PUBLISHED_NUMERIC_SERVICE_QUOTA",
            "reasons": ["Sigstore publishes no numeric per-client quota in reviewed evidence."],
        },
        "usage_policy_evidence_digests": sorted((BOOTSTRAP_ROOT_SHA256, TRUSTED_ROOT_SHA256)),
    }


def trust_policy_artifact() -> bytes:
    return encode_artifact("TrustPolicy", trust_policy_body())


def bootstrap_root_artifact() -> bytes:
    return _bootstrap_root_bytes()


def bootstrap_root_digest() -> str:
    return digest_bytes(_bootstrap_root_bytes())


def trust_state_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Return only the exact contract identity fields from a verified refresh."""
    expected = {
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
    if set(value) != expected:
        raise CB01TrustError("Trusted TUF state does not match the CB01 identity schema.")
    return value


class SigstoreWitnessBackend:
    """Use the pinned Sigstore TUF root plus OpenSSL and curl for RFC 3161."""

    def refresh_trust(self, policy_body: dict[str, Any]) -> TrustRefresh:
        deadline = time.monotonic() + MAX_REFRESH_SECONDS
        update_started_at = _utc_now()
        bootstrap = _bootstrap_root_bytes()
        if digest_bytes(bootstrap) != BOOTSTRAP_ROOT_SHA256:
            raise CB01TrustError("Pinned Sigstore bootstrap root digest does not match v1.")
        root_doc = _parse_json(bootstrap, "bootstrap root")
        if _root_version(root_doc) != BOOTSTRAP_ROOT_VERSION:
            raise CB01TrustError("Pinned Sigstore bootstrap root is not version 10.")
        prior = root_doc
        updates: list[bytes] = []
        for version in range(
            BOOTSTRAP_ROOT_VERSION + 1, BOOTSTRAP_ROOT_VERSION + MAX_TUF_ROOT_UPDATES + 1
        ):
            content = _fetch_curl(
                f"{TUF_BASE_URL}{version}.root.json",
                max_bytes=policy_body["transport_limits"]["max_response_bytes"],
                connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
                total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
                deadline=deadline,
                not_found_is_none=True,
            )
            if content is None:
                break
            candidate = _parse_json(content, f"root version {version}")
            if _root_version(candidate) != version:
                raise CB01TrustError("Sigstore TUF root update skipped or repeated a version.")
            _verify_role(candidate, prior, "root", deadline=deadline)
            _verify_role(candidate, candidate, "root", deadline=deadline)
            updates.append(content)
            prior = candidate
        else:
            raise CB01TrustError("Sigstore TUF root rotation exceeded the v1 update bound.")
        # TUF verifies every sequential root rotation, then checks the resulting root's
        # expiry. An expired intermediate is still needed to authenticate its successor.
        _check_expiry(prior, update_started_at)
        if _root_version(prior) < int(policy_body["trust_update_policy"]["current_root_version"]):
            raise CB01TrustError("Sigstore TUF root chain is older than the reviewed v1 root.")

        timestamp = _fetch_curl(
            f"{TUF_BASE_URL}timestamp.json",
            max_bytes=policy_body["transport_limits"]["max_response_bytes"],
            connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
            total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
            deadline=deadline,
        )
        assert timestamp is not None
        timestamp_doc = _parse_json(timestamp, "timestamp metadata")
        _verify_role(timestamp_doc, prior, "timestamp", deadline=deadline)
        _check_expiry(timestamp_doc, update_started_at)
        timestamp_version = _metadata_version(timestamp_doc, "timestamp")
        snapshot_version = _referenced_version(timestamp_doc, "snapshot.json")

        snapshot = _fetch_curl(
            f"{TUF_BASE_URL}{snapshot_version}.snapshot.json",
            max_bytes=policy_body["transport_limits"]["max_response_bytes"],
            connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
            total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
            deadline=deadline,
        )
        assert snapshot is not None
        snapshot_doc = _parse_json(snapshot, "snapshot metadata")
        _verify_role(snapshot_doc, prior, "snapshot", deadline=deadline)
        _check_expiry(snapshot_doc, update_started_at)
        if _metadata_version(snapshot_doc, "snapshot") != snapshot_version:
            raise CB01TrustError("Sigstore snapshot version differs from timestamp metadata.")
        _verify_metadata_reference(timestamp_doc, "snapshot.json", snapshot)
        targets_version = _referenced_version(snapshot_doc, "targets.json")
        targets = _fetch_curl(
            f"{TUF_BASE_URL}{targets_version}.targets.json",
            max_bytes=policy_body["transport_limits"]["max_response_bytes"],
            connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
            total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
            deadline=deadline,
        )
        assert targets is not None
        targets_doc = _parse_json(targets, "targets metadata")
        _verify_role(targets_doc, prior, "targets", deadline=deadline)
        _check_expiry(targets_doc, update_started_at)
        if _metadata_version(targets_doc, "targets") != targets_version:
            raise CB01TrustError("Sigstore targets version differs from snapshot metadata.")
        _verify_metadata_reference(snapshot_doc, "targets.json", targets)

        target_entry = _trusted_root_target_entry(targets_doc)
        target_length = _positive_int(target_entry.get("length"), "trusted_root target length")
        target_digest = _target_sha256(target_entry)
        if target_digest != policy_body["trust_update_policy"]["trusted_root_target_digest"]:
            raise CB01TrustError(
                "Authenticated Sigstore TrustedRoot target differs from pinned v1."
            )
        target = _fetch_curl(
            f"{TUF_BASE_URL}trusted_root.json",
            max_bytes=policy_body["transport_limits"]["max_trusted_root_bytes"],
            connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
            total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
            deadline=deadline,
            not_found_is_none=True,
        )
        target_url = f"{TUF_BASE_URL}trusted_root.json"
        if target is None:
            target = _fetch_curl(
                TUF_TARGET_MIRROR_URL,
                max_bytes=policy_body["transport_limits"]["max_trusted_root_bytes"],
                connect_timeout=policy_body["transport_limits"]["connect_timeout_seconds"],
                total_timeout=policy_body["transport_limits"]["total_timeout_seconds"],
                deadline=deadline,
            )
            target_url = TUF_TARGET_MIRROR_URL
        assert target is not None
        if len(target) != target_length or digest_bytes(target) != target_digest:
            raise CB01TrustError(
                "Sigstore TrustedRoot target failed authenticated hash/length checks."
            )
        target_doc = _parse_json_object(target, "TrustedRoot target")
        tsa_entry, signer_der, anchor_der = _select_tsa_entry(target_doc, policy_body)
        root_version = _root_version(prior)
        state = {
            "bootstrap_root_version": BOOTSTRAP_ROOT_VERSION,
            "bootstrap_root_digest": BOOTSTRAP_ROOT_SHA256,
            "root_version": root_version,
            "root_digest": digest_bytes(updates[-1]) if updates else BOOTSTRAP_ROOT_SHA256,
            "timestamp_version": timestamp_version,
            "timestamp_digest": digest_bytes(timestamp),
            "snapshot_version": snapshot_version,
            "snapshot_digest": digest_bytes(snapshot),
            "targets_version": targets_version,
            "targets_digest": digest_bytes(targets),
            "trusted_root_target_digest": digest_bytes(target),
            "trusted_root_length": len(target),
            "tsa_entry_uri": tsa_entry["uri"],
            "tsa_entry_subject": _display_subject(tsa_entry["subject"]),
            "valid_for_start": tsa_entry["validFor"]["start"],
            "valid_for_end": tsa_entry["validFor"].get("end"),
            "chain_fingerprints": [digest_bytes(signer_der), digest_bytes(anchor_der)],
            "verification_client": "OpenSSL",
            "verification_client_version": _openssl_version(),
        }
        trust = TrustRefresh(
            root_history=tuple(updates),
            timestamp=timestamp,
            snapshot=snapshot,
            targets=targets,
            trusted_root=target,
            target_source_url=target_url,
            state=state,
            tsa_entry=tsa_entry,
            signer_der=signer_der,
            anchor_der=anchor_der,
        )
        _validate_trust_identity(trust, policy_body)
        return trust

    def replay_trust(
        self,
        root_history: tuple[bytes, ...],
        timestamp: bytes,
        snapshot: bytes,
        targets: bytes,
        trusted_root: bytes,
        policy_body: dict[str, Any],
    ) -> TrustRefresh:
        return replay_trust_state(
            root_history, timestamp, snapshot, targets, trusted_root, policy_body
        )

    def create_request(self, batch_bytes: bytes) -> TimestampRequest:
        if not batch_bytes:
            raise CB01TrustError("Cannot timestamp an empty batch artifact.")
        with tempfile.TemporaryDirectory(prefix="matchvet-cb01-request-") as directory:
            work = Path(directory)
            batch_file = work / "batch.json"
            request_file = work / "request.tsq"
            batch_file.write_bytes(batch_bytes)
            _openssl(
                [
                    "ts",
                    "-query",
                    "-data",
                    str(batch_file),
                    "-sha256",
                    "-cert",
                    "-out",
                    str(request_file),
                ]
            )
            request_der = request_file.read_bytes()
        query = _parse_ts_query(request_der)
        expected_imprint = hashlib.sha256(batch_bytes).digest()
        if query["algorithm_oid"] != SHA256_OID or query["imprint"] != expected_imprint:
            raise CB01TrustError("OpenSSL produced a request with the wrong SHA-256 imprint.")
        if query["cert_req"] is not True:
            raise CB01TrustError("OpenSSL request does not request the TSA certificate.")
        nonce = query["nonce"]
        if nonce <= 0:
            raise CB01TrustError("OpenSSL request did not produce a positive nonce.")
        return TimestampRequest(request_der, f"{nonce:x}")

    def submit_request(self, request_der: bytes, policy_body: dict[str, Any]) -> TimestampTransport:
        limits = policy_body["transport_limits"]
        with tempfile.TemporaryDirectory(prefix="matchvet-cb01-tsa-") as directory:
            work = Path(directory)
            request_file = work / "request.tsq"
            response_file = work / "response.tsr"
            request_file.write_bytes(request_der)
            command = [
                "curl",
                "--silent",
                "--show-error",
                "--connect-timeout",
                str(limits["connect_timeout_seconds"]),
                "--max-time",
                str(limits["total_timeout_seconds"]),
                "--max-filesize",
                str(limits["max_response_bytes"]),
                "--header",
                "Content-Type: application/timestamp-query",
                "--header",
                "Accept: application/timestamp-reply",
                "--data-binary",
                f"@{request_file}",
                "--output",
                str(response_file),
                "--write-out",
                "%{http_code}",
                policy_body["endpoint"],
            ]
            try:
                completed = subprocess.run(command, capture_output=True, timeout=35, check=False)
            except OSError, subprocess.TimeoutExpired:
                return TimestampTransport("UNAVAILABLE", None, ("TSA_TRANSPORT_UNAVAILABLE",))
            status = completed.stdout.decode("ascii", errors="ignore")[-3:]
            if completed.returncode != 0:
                reason = (
                    "TSA_RESPONSE_TOO_LARGE"
                    if "Maximum file size" in completed.stderr.decode(errors="ignore")
                    else "TSA_TRANSPORT_UNAVAILABLE"
                )
                response = _bounded_file(response_file, limits["max_response_bytes"])
                return TimestampTransport("UNAVAILABLE", response, (reason,))
            response = _bounded_file(response_file, limits["max_response_bytes"])
            if status != "200":
                return TimestampTransport(
                    "REJECTED", response, (f"TSA_HTTP_STATUS_{status or 'UNKNOWN'}",)
                )
            if not response:
                return TimestampTransport("MALFORMED", b"", ("TSA_EMPTY_RESPONSE",))
            return TimestampTransport("RECEIVED", response, ())

    def verify_response(
        self,
        request_der: bytes,
        nonce_hex: str,
        response_der: bytes,
        trust: TrustRefresh,
        policy_body: dict[str, Any],
        *,
        batch_digest: str,
        cutoff_utc: str,
        kickoff_utc: str,
    ) -> TimestampVerificationResult:
        return _verify_timestamp(
            request_der,
            nonce_hex,
            response_der,
            trust,
            policy_body,
            batch_digest=batch_digest,
            cutoff_utc=cutoff_utc,
            kickoff_utc=kickoff_utc,
        )


def replay_trust_state(
    root_history: tuple[bytes, ...],
    timestamp: bytes,
    snapshot: bytes,
    targets: bytes,
    trusted_root: bytes,
    policy_body: dict[str, Any],
) -> TrustRefresh:
    """Reverify exact retained TUF bytes during offline recovery."""
    if len(root_history) > MAX_TUF_ROOT_UPDATES:
        raise CB01TrustError("Retained Sigstore TUF root history exceeds the v1 replay bound.")
    deadline = time.monotonic() + MAX_REFRESH_SECONDS
    bootstrap = _bootstrap_root_bytes()
    if digest_bytes(bootstrap) != BOOTSTRAP_ROOT_SHA256:
        raise CB01TrustError("Pinned Sigstore bootstrap root digest does not match v1.")
    prior = _parse_json(bootstrap, "bootstrap root")
    for index, content in enumerate(root_history, start=BOOTSTRAP_ROOT_VERSION + 1):
        candidate = _parse_json(content, f"retained root {index}")
        if _root_version(candidate) != index:
            raise CB01TrustError("Retained TUF root history is not sequential.")
        _verify_role(candidate, prior, "root", deadline=deadline)
        _verify_role(candidate, candidate, "root", deadline=deadline)
        prior = candidate
    if _root_version(prior) < int(policy_body["trust_update_policy"]["current_root_version"]):
        raise CB01TrustError("Retained TUF root is older than the reviewed v1 root.")
    timestamp_doc = _parse_json(timestamp, "retained timestamp metadata")
    snapshot_doc = _parse_json(snapshot, "retained snapshot metadata")
    targets_doc = _parse_json(targets, "retained targets metadata")
    _verify_role(timestamp_doc, prior, "timestamp", deadline=deadline)
    _verify_role(snapshot_doc, prior, "snapshot", deadline=deadline)
    _verify_role(targets_doc, prior, "targets", deadline=deadline)
    if _referenced_version(timestamp_doc, "snapshot.json") != _metadata_version(
        snapshot_doc, "snapshot"
    ):
        raise CB01TrustError("Retained timestamp and snapshot versions disagree.")
    if _referenced_version(snapshot_doc, "targets.json") != _metadata_version(
        targets_doc, "targets"
    ):
        raise CB01TrustError("Retained snapshot and targets versions disagree.")
    _verify_metadata_reference(timestamp_doc, "snapshot.json", snapshot)
    _verify_metadata_reference(snapshot_doc, "targets.json", targets)
    target_entry = _trusted_root_target_entry(targets_doc)
    if len(trusted_root) != _positive_int(target_entry.get("length"), "trusted_root target length"):
        raise CB01TrustError("Retained TrustedRoot length differs from authenticated metadata.")
    if digest_bytes(trusted_root) != _target_sha256(target_entry):
        raise CB01TrustError("Retained TrustedRoot digest differs from authenticated metadata.")
    if (
        digest_bytes(trusted_root)
        != policy_body["trust_update_policy"]["trusted_root_target_digest"]
    ):
        raise CB01TrustError("Retained TrustedRoot digest differs from pinned v1.")
    target_doc = _parse_json_object(trusted_root, "retained TrustedRoot target")
    tsa_entry, signer_der, anchor_der = _select_tsa_entry(target_doc, policy_body)
    state = {
        "bootstrap_root_version": BOOTSTRAP_ROOT_VERSION,
        "bootstrap_root_digest": BOOTSTRAP_ROOT_SHA256,
        "root_version": _root_version(prior),
        "root_digest": digest_bytes(root_history[-1]) if root_history else BOOTSTRAP_ROOT_SHA256,
        "timestamp_version": _metadata_version(timestamp_doc, "timestamp"),
        "timestamp_digest": digest_bytes(timestamp),
        "snapshot_version": _metadata_version(snapshot_doc, "snapshot"),
        "snapshot_digest": digest_bytes(snapshot),
        "targets_version": _metadata_version(targets_doc, "targets"),
        "targets_digest": digest_bytes(targets),
        "trusted_root_target_digest": digest_bytes(trusted_root),
        "trusted_root_length": len(trusted_root),
        "tsa_entry_uri": tsa_entry["uri"],
        "tsa_entry_subject": _display_subject(tsa_entry["subject"]),
        "valid_for_start": tsa_entry["validFor"]["start"],
        "valid_for_end": tsa_entry["validFor"].get("end"),
        "chain_fingerprints": [digest_bytes(signer_der), digest_bytes(anchor_der)],
        "verification_client": "OpenSSL",
        "verification_client_version": _openssl_version(),
    }
    result = TrustRefresh(
        root_history=root_history,
        timestamp=timestamp,
        snapshot=snapshot,
        targets=targets,
        trusted_root=trusted_root,
        target_source_url=TUF_TARGET_MIRROR_URL,
        state=state,
        tsa_entry=tsa_entry,
        signer_der=signer_der,
        anchor_der=anchor_der,
    )
    _validate_trust_identity(result, policy_body)
    return result


def _validate_trust_identity(trust: TrustRefresh, policy_body: dict[str, Any]) -> None:
    state = trust_state_schema(trust.state)
    _validate_tuf_metadata_floor(state, policy_body)
    if state["tsa_entry_uri"] != TSA_ENDPOINT:
        raise CB01TrustError("Authenticated TUF timestamp authority URI differs from v1.")
    if state["tsa_entry_subject"] != "O=sigstore.dev, CN=sigstore-tsa-selfsigned":
        raise CB01TrustError("Authenticated TUF timestamp authority subject differs from v1.")
    if (
        state["chain_fingerprints"]
        != policy_body["signer_fingerprints"] + policy_body["anchor_fingerprints"]
    ):
        raise CB01TrustError(
            "Authenticated TUF timestamp authority certificate chain differs from v1."
        )


def _validate_tuf_metadata_floor(state: dict[str, Any], policy_body: dict[str, Any]) -> None:
    """Reject TUF state older than or conflicting with the reviewed v1 baseline."""
    update = policy_body["trust_update_policy"]
    digests = update["metadata_digests"]
    floors = {
        "root": (int(update["current_root_version"]), "root_version", "root_digest"),
        **{
            role: (version, f"{role}_version", f"{role}_digest")
            for role, version in TUF_METADATA_VERSION_FLOORS.items()
        },
    }
    for role, (minimum, version_key, digest_key) in floors.items():
        version = state[version_key]
        digest = state[digest_key]
        if version < minimum:
            raise CB01TrustError(f"Sigstore TUF {role} metadata is below the frozen v1 floor.")
        if version == minimum and digest != digests[role]:
            raise CB01TrustError(
                f"Sigstore TUF {role} metadata conflicts with the frozen v1 floor."
            )


def _verify_timestamp(
    request_der: bytes,
    nonce_hex: str,
    response_der: bytes,
    trust: TrustRefresh,
    policy_body: dict[str, Any],
    *,
    batch_digest: str,
    cutoff_utc: str,
    kickoff_utc: str,
) -> TimestampVerificationResult:
    check_names = (
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
    )
    checks = {name: {"state": "UNPERFORMED", "reasons": []} for name in check_names}
    reasons: list[str] = []
    identity = _empty_tsa_identity()
    chain: tuple[str, ...] = ()

    def passed(name: str) -> None:
        checks[name] = {"state": "PASSED", "reasons": []}

    def failed(name: str, reason: str) -> None:
        checks[name] = {"state": "FAILED", "reasons": [reason]}
        reasons.append(reason)

    try:
        _validate_trust_identity(trust, policy_body)
        passed("trusted_root")
    except CB01TrustError, CB01SchemaError:
        failed("trusted_root", "AUTHENTICATED_TRUST_STATE_MISMATCH")
        return TimestampVerificationResult("FAILED", identity, chain, checks, tuple(reasons))

    try:
        response = _parse_ts_response(response_der)
        if response["status"] != 0:
            failed("status", "RFC3161_STATUS_NOT_GRANTED")
            return TimestampVerificationResult("FAILED", identity, chain, checks, tuple(reasons))
        token_der = response["token"]
        token = _parse_timestamp_token(token_der)
        passed("status")
    except CB01TrustError, IndexError, ValueError, TypeError:
        failed("status", "RFC3161_RESPONSE_MALFORMED_OR_REJECTED")
        return TimestampVerificationResult("FAILED", identity, chain, checks, tuple(reasons))

    try:
        request = _parse_ts_query(request_der)
        if request["algorithm_oid"] != SHA256_OID or token["algorithm_oid"] != SHA256_OID:
            raise CB01TrustError("RFC3161 imprint algorithm is not SHA-256.")
        if token["imprint"] != bytes.fromhex(batch_digest):
            raise CB01TrustError("RFC3161 SHA-256 imprint differs from the exact batch digest.")
        if request["imprint"] != token["imprint"]:
            raise CB01TrustError("RFC3161 token imprint differs from its exact request.")
        passed("imprint")
    except CB01TrustError, ValueError, KeyError:
        failed("imprint", "RFC3161_SHA256_IMPRINT_MISMATCH")

    try:
        attempt_nonce = int(nonce_hex, 16)
        if (
            request["nonce"] != attempt_nonce
            or token["nonce"] != attempt_nonce
            or attempt_nonce <= 0
        ):
            raise CB01TrustError("RFC3161 nonce differs from its exact retained request.")
        passed("nonce")
    except CB01TrustError, ValueError, KeyError:
        failed("nonce", "RFC3161_NONCE_MISMATCH")

    if token.get("policy_oid") in policy_body["allowed_token_policy_oids"]:
        passed("policy")
    else:
        failed("policy", "RFC3161_TOKEN_POLICY_REJECTED")

    try:
        cms = _cms_identity(token_der)
        if (
            cms["digest_oid"] != CMS_DIGEST_OID
            or cms["signature_oid"] != policy_body["cms_signature_oid"]
        ):
            raise CB01TrustError("CMS digest or signature algorithm differs from pinned policy.")
        if not cms["has_ess_cert_id_v2"]:
            raise CB01TrustError("CMS token has no ESSCertIDv2 signer binding.")
        cms_valid = True
    except CB01TrustError, ValueError, IndexError:
        failed("signature", "CMS_ALGORITHM_OR_ESS_BINDING_REJECTED")
        cms = None
        cms_valid = False

    try:
        signer_pem, signer_fingerprint, signer_subject, signer_issuer, signer_serial = (
            _embedded_signer(token_der, trust.signer_der)
        )
        identity["signer_fingerprint"] = signer_fingerprint
        identity["issuer"] = signer_issuer
        identity["certificate_serial_hex"] = signer_serial.lower()
        if (
            signer_fingerprint != TSA_SIGNER_SHA256
            or signer_subject != TSA_SUBJECT
            or signer_issuer != TSA_ISSUER
        ):
            raise CB01TrustError(
                "CMS signer identity differs from pinned Sigstore TSA certificate."
            )
        if signer_fingerprint not in policy_body["signer_fingerprints"]:
            raise CB01TrustError("CMS signer fingerprint is not in the immutable trust policy.")
        passed("signer")
    except CB01TrustError, OSError, ValueError, subprocess.SubprocessError:
        failed("signer", "SIGSTORE_TSA_SIGNER_IDENTITY_MISMATCH")
        signer_pem = b""

    try:
        _verify_eku(signer_pem)
        passed("eku")
    except CB01TrustError, OSError, subprocess.SubprocessError:
        failed("eku", "TSA_SIGNER_TIMESTAMPING_EKU_INVALID")

    gen_time = token.get("gen_time_utc")
    if isinstance(gen_time, str):
        identity.update(
            {
                "status": "GRANTED",
                "imprint_algorithm": "sha256",
                "imprint_hex": token["imprint"].hex(),
                "nonce_hex": f"{token['nonce']:x}",
                "policy_oid": token["policy_oid"],
                "serial_hex": f"{token['serial']:x}",
                "gen_time_utc": gen_time,
                "accuracy": token["accuracy"],
                "ess_binding": "ESSCertIDv2_SHA256_VERIFIED",
            }
        )
    else:
        failed("status", "RFC3161_GEN_TIME_MISSING")

    try:
        if gen_time is None or not _valid_for_contains(trust.tsa_entry, gen_time):
            raise CB01TrustError("Signed genTime is outside the TUF TrustedRoot validFor period.")
        _verify_certificate_chain(request_der, response_der, trust, gen_time, policy_body)
        if cms_valid:
            passed("signature")
        passed("chain")
        passed("certificate_validity_at_gen_time")
    except CB01TrustError, OSError, subprocess.SubprocessError, ValueError:
        if checks["signature"]["state"] == "UNPERFORMED":
            failed("signature", "RFC3161_CMS_SIGNATURE_INVALID")
        failed("chain", "TSA_CERTIFICATE_CHAIN_INVALID_AT_SIGNED_GEN_TIME")
        failed(
            "certificate_validity_at_gen_time", "TSA_CERTIFICATE_TIME_INVALID_AT_SIGNED_GEN_TIME"
        )

    try:
        if (
            compare_utc(cutoff_utc, gen_time or "") >= 0
            or compare_utc(gen_time or "", kickoff_utc) >= 0
        ):
            raise CB01TrustError("Signed genTime is not strictly between F07 cutoff and kickoff.")
        passed("time_window")
    except CB01TrustError, CB01SchemaError, ValueError:
        failed("time_window", "SIGNED_GEN_TIME_OUTSIDE_STRICT_CUTOFF_KICKOFF_WINDOW")

    chain = tuple(trust.state["chain_fingerprints"])
    verified = all(check["state"] == "PASSED" for check in checks.values())
    if verified:
        return TimestampVerificationResult("VERIFIED", identity, chain, checks, ())
    return TimestampVerificationResult(
        "FAILED", identity, chain, checks, tuple(sorted(set(reasons)))
    )


def _empty_tsa_identity() -> dict[str, Any]:
    return {
        "status": None,
        "imprint_algorithm": None,
        "imprint_hex": None,
        "nonce_hex": None,
        "policy_oid": None,
        "serial_hex": None,
        "gen_time_utc": None,
        "accuracy": {"seconds": None, "millis": None, "micros": None},
        "signer_fingerprint": None,
        "issuer": None,
        "certificate_serial_hex": None,
        "ess_binding": None,
    }


def _verify_certificate_chain(
    request_der: bytes,
    response_der: bytes,
    trust: TrustRefresh,
    gen_time: str,
    policy_body: dict[str, Any],
) -> None:
    _ = request_der
    _ = response_der
    _ = policy_body
    _check_signer_cert_exact_validity(trust.signer_der, gen_time)
    _check_signer_cert_exact_validity(trust.anchor_der, gen_time)
    token_command = _openssl_version()
    _ = token_command
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-verify-") as directory:
        work = Path(directory)
        response_path = work / "response.tsr"
        anchor_path = work / "anchor.der"
        signer_path = work / "signer.der"
        ca_path = work / "anchor.pem"
        untrusted_path = work / "signer.pem"
        query_path = work / "request.tsq"
        chain_path = work / "untrusted.pem"
        empty_ca_dir = work / "empty-ca"
        empty_ca_dir.mkdir()
        response_path.write_bytes(response_der)
        anchor_path.write_bytes(trust.anchor_der)
        signer_path.write_bytes(trust.signer_der)
        _convert_cert(anchor_path, ca_path)
        _convert_cert(signer_path, untrusted_path)
        chain_path.write_bytes(untrusted_path.read_bytes())
        query_path.write_bytes(request_der)
        second = _openssl(
            [
                "ts",
                "-verify",
                "-queryfile",
                str(query_path),
                "-in",
                str(response_path),
                "-CAfile",
                str(ca_path),
                "-CApath",
                str(empty_ca_dir),
                "-untrusted",
                str(chain_path),
                "-policy",
                TSA_POLICY_OID,
                "-attime",
                str(_whole_epoch(gen_time)),
            ]
        )
        if b"Verification: OK" not in second.stdout:
            raise CB01TrustError("OpenSSL did not verify the RFC3161 CMS signature and chain.")


def _convert_cert(der_path: Path, pem_path: Path) -> None:
    _openssl(["x509", "-inform", "DER", "-in", str(der_path), "-out", str(pem_path)])


def _check_signer_cert_exact_validity(der: bytes, gen_time: str) -> None:
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-cert-time-") as directory:
        cert_path = Path(directory) / "cert.der"
        cert_path.write_bytes(der)
        completed = _openssl(
            [
                "x509",
                "-inform",
                "DER",
                "-in",
                str(cert_path),
                "-noout",
                "-startdate",
                "-enddate",
            ]
        )
    values = dict(
        line.split("=", 1)
        for line in completed.stdout.decode("ascii", errors="strict").splitlines()
        if "=" in line
    )
    if not {"notBefore", "notAfter"}.issubset(values):
        raise CB01TrustError("OpenSSL did not report certificate validity bounds.")
    before = _openssl_time_to_utc(values["notBefore"])
    after = _openssl_time_to_utc(values["notAfter"])
    if compare_utc(before, gen_time) > 0 or compare_utc(gen_time, after) > 0:
        raise CB01TrustError("TSA certificate is not valid at exact signed genTime.")


def _verify_eku(signer_pem: bytes) -> None:
    if not signer_pem:
        raise CB01TrustError("Signer certificate is unavailable.")
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-eku-") as directory:
        path = Path(directory) / "signer.pem"
        path.write_bytes(signer_pem)
        output = _openssl(["x509", "-in", str(path), "-text", "-noout"]).stdout.decode(
            "utf-8", errors="replace"
        )
    match = re.search(r"X509v3 Extended Key Usage: (critical)?\s*\n\s*([^\n]+)", output)
    if match is None or match.group(1) != "critical" or match.group(2).strip() != "Time Stamping":
        raise CB01TrustError("TSA signer EKU must be critical and exclusively timeStamping.")


def _embedded_signer(token_der: bytes, expected_der: bytes) -> tuple[bytes, str, str, str, str]:
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-certs-") as directory:
        token_path = Path(directory) / "token.der"
        certs_path = Path(directory) / "certs.pem"
        token_path.write_bytes(token_der)
        _openssl(
            [
                "pkcs7",
                "-inform",
                "DER",
                "-in",
                str(token_path),
                "-print_certs",
                "-out",
                str(certs_path),
            ]
        )
        pem_bytes = certs_path.read_bytes()
        blocks = re.findall(
            rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\s*",
            pem_bytes,
            flags=re.S,
        )
        for index, block in enumerate(blocks):
            pem_path = Path(directory) / f"cert-{index}.pem"
            der_path = Path(directory) / f"cert-{index}.der"
            pem_path.write_bytes(block)
            _openssl(["x509", "-in", str(pem_path), "-outform", "DER", "-out", str(der_path)])
            cert_der = der_path.read_bytes()
            if cert_der != expected_der:
                continue
            details = _openssl(
                [
                    "x509",
                    "-inform",
                    "DER",
                    "-in",
                    str(der_path),
                    "-noout",
                    "-subject",
                    "-issuer",
                    "-serial",
                ]
            ).stdout.decode("utf-8", errors="strict")
            values = {
                key: value.strip()
                for key, value in (
                    line.split("=", 1) for line in details.splitlines() if "=" in line
                )
            }
            return (
                block,
                digest_bytes(cert_der),
                values.get("subject", ""),
                values.get("issuer", ""),
                values.get("serial", ""),
            )
    raise CB01TrustError("RFC3161 CMS does not embed the exact TUF-pinned signer certificate.")


def _parse_ts_query(content: bytes) -> dict[str, Any]:
    root = _tlv(content)
    if root["tag"] != 0x30 or root["end"] != len(content):
        raise CB01TrustError("Malformed RFC3161 TimeStampReq DER.")
    fields = _children(root)
    if len(fields) not in (3, 4) or _integer(fields[0]) != 1 or fields[1]["tag"] != 0x30:
        raise CB01TrustError("Malformed RFC3161 TimeStampReq fields.")
    imprint_fields = _children(fields[1])
    if (
        len(imprint_fields) != 2
        or imprint_fields[0]["tag"] != 0x30
        or imprint_fields[1]["tag"] != 0x04
    ):
        raise CB01TrustError("Malformed RFC3161 message imprint.")
    algorithm = _children(imprint_fields[0])
    nonce = next((item for item in fields[2:] if item["tag"] == 0x02), None)
    cert_req = next((item for item in fields[2:] if item["tag"] == 0x01), None)
    if nonce is None:
        raise CB01TrustError("RFC3161 TimeStampReq nonce is missing.")
    return {
        "algorithm_oid": _oid(algorithm[0]),
        "imprint": imprint_fields[1]["content"],
        "nonce": _integer(nonce),
        "cert_req": cert_req is not None and cert_req["content"] == b"\xff",
    }


def _parse_ts_response(content: bytes) -> dict[str, Any]:
    root = _tlv(content)
    if root["tag"] != 0x30 or root["end"] != len(content):
        raise CB01TrustError("Malformed RFC3161 TimeStampResp DER.")
    fields = _children(root)
    if not fields or fields[0]["tag"] != 0x30:
        raise CB01TrustError("RFC3161 response status is missing.")
    status_fields = _children(fields[0])
    if not status_fields:
        raise CB01TrustError("RFC3161 response status is malformed.")
    return {
        "status": _integer(status_fields[0]),
        "token": _raw(fields[1]) if len(fields) > 1 else None,
    }


def _parse_timestamp_token(token_der: bytes) -> dict[str, Any]:
    content_info = _tlv(token_der)
    content_fields = _children(content_info)
    if content_info["tag"] != 0x30 or len(content_fields) != 2 or content_fields[0]["tag"] != 0x06:
        raise CB01TrustError("Malformed CMS ContentInfo in RFC3161 token.")
    if _oid(content_fields[0]) != "1.2.840.113549.1.7.2" or content_fields[1]["tag"] != 0xA0:
        raise CB01TrustError("RFC3161 token is not CMS SignedData.")
    signed_data = _children(_tlv(content_fields[1]["content"]))
    encap = next(
        (item for item in signed_data if item["tag"] == 0x30 and item is not signed_data[0]), None
    )
    if encap is None:
        raise CB01TrustError("CMS token has no encapsulated TSTInfo.")
    encap_fields = _children(encap)
    if (
        len(encap_fields) != 2
        or _oid(encap_fields[0]) != TST_INFO_OID
        or encap_fields[1]["tag"] != 0xA0
    ):
        raise CB01TrustError("CMS token content is not RFC3161 TSTInfo.")
    octet = _tlv(encap_fields[1]["content"])
    if octet["tag"] != 0x04:
        raise CB01TrustError("CMS token TSTInfo OCTET STRING is malformed.")
    tst = _children(_tlv(octet["content"]))
    if len(tst) < 5 or _integer(tst[0]) != 1:
        raise CB01TrustError("RFC3161 TSTInfo is malformed.")
    imprint = _children(tst[2])
    if len(imprint) != 2:
        raise CB01TrustError("RFC3161 TSTInfo message imprint is malformed.")
    imprint_alg = _children(imprint[0])
    serial = _integer(tst[3])
    if tst[4]["tag"] != 0x18:
        raise CB01TrustError("RFC3161 TSTInfo genTime is missing.")
    gen_time = _generalized_time(tst[4]["content"].decode("ascii", errors="strict"))
    accuracy: dict[str, int | None] = {"seconds": None, "millis": None, "micros": None}
    nonce = None
    index = 5
    while index < len(tst):
        item = tst[index]
        if item["tag"] == 0x30:
            for field in _children(item):
                key = {0x02: "seconds", 0x80: "millis", 0x81: "micros"}.get(field["tag"])
                if key is not None:
                    value = int.from_bytes(field["content"], "big", signed=field["tag"] == 0x02)
                    if value < 0:
                        raise CB01TrustError("Timestamp accuracy cannot be negative.")
                    accuracy[key] = value
        elif item["tag"] == 0x02:
            nonce = _integer(item)
        index += 1
    return {
        "policy_oid": _oid(tst[1]),
        "algorithm_oid": _oid(imprint_alg[0]),
        "imprint": imprint[1]["content"],
        "serial": serial,
        "gen_time_utc": gen_time,
        "accuracy": accuracy,
        "nonce": nonce,
    }


def _cms_identity(token_der: bytes) -> dict[str, Any]:
    content_info = _children(_tlv(token_der))
    signed_data = _children(_tlv(content_info[1]["content"]))
    signer_set = next(item for item in reversed(signed_data) if item["tag"] == 0x31)
    signers = _children(signer_set)
    if len(signers) != 1:
        raise CB01TrustError("RFC3161 token must have exactly one CMS signer.")
    signer_fields = _children(signers[0])
    if len(signer_fields) < 5:
        raise CB01TrustError("RFC3161 CMS SignerInfo is malformed.")
    digest_alg = _children(signer_fields[2])
    attrs = signer_fields[3]
    signature_alg = _children(signer_fields[4])
    has_ess = False
    if attrs["tag"] == 0xA0:
        for attr in _children(attrs):
            attr_fields = _children(attr)
            if attr_fields and _oid(attr_fields[0]) == ESS_SIGNING_CERT_V2_OID:
                has_ess = True
    return {
        "digest_oid": _oid(digest_alg[0]),
        "signature_oid": _oid(signature_alg[0]),
        "has_ess_cert_id_v2": has_ess,
    }


def _tlv(content: bytes, offset: int = 0) -> dict[str, Any]:
    if offset >= len(content):
        raise CB01TrustError("Unexpected end of DER data.")
    tag = content[offset]
    cursor = offset + 1
    if cursor >= len(content):
        raise CB01TrustError("Truncated DER length.")
    first = content[cursor]
    cursor += 1
    if first < 0x80:
        size = first
    else:
        width = first & 0x7F
        if width == 0 or width > 4 or cursor + width > len(content):
            raise CB01TrustError("Indefinite or excessive DER length is forbidden.")
        size = int.from_bytes(content[cursor : cursor + width], "big")
        if size < 0x80:
            raise CB01TrustError("Nonminimal DER length is malformed.")
        cursor += width
    end = cursor + size
    if end > len(content):
        raise CB01TrustError("DER field exceeds its containing object.")
    return {
        "tag": tag,
        "content": content[cursor:end],
        "start": offset,
        "content_start": cursor,
        "end": end,
        "raw": content[offset:end],
    }


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    content = cast(bytes, node["content"])
    items: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(content):
        item = _tlv(content, cursor)
        item["raw"] = content[cursor : item["end"]]
        item["start"] = cursor
        cursor = item["end"]
        items.append(item)
    if cursor != len(content):
        raise CB01TrustError("Malformed DER child boundary.")
    return items


def _raw(node: dict[str, Any]) -> bytes:
    return cast(bytes, node["raw"])


def _integer(node: dict[str, Any]) -> int:
    if node["tag"] != 0x02 or not node["content"]:
        raise CB01TrustError("DER INTEGER is malformed.")
    value = cast(bytes, node["content"])
    return int.from_bytes(value, "big", signed=True)


def _oid(node: dict[str, Any]) -> str:
    if node["tag"] != 0x06 or not node["content"]:
        raise CB01TrustError("DER object identifier is malformed.")
    values: list[int] = []
    current = 0
    for byte in cast(bytes, node["content"]):
        current = (current << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            values.append(current)
            current = 0
    if current:
        raise CB01TrustError("DER object identifier is truncated.")
    first = values.pop(0)
    arc1 = min(first // 40, 2)
    arc2 = first - 40 * arc1
    return ".".join(str(value) for value in (arc1, arc2, *values))


def _generalized_time(value: str) -> str:
    match = re.fullmatch(
        r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:[.,](\d+))?(Z|[+-]\d{4})", value
    )
    if match is None:
        raise CB01TrustError("RFC3161 genTime must be full precision GeneralizedTime.")
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    local = datetime(
        int(year), int(month), int(day), int(hour), int(minute), int(second), tzinfo=UTC
    )
    if zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        offset = sign * (int(zone[1:3]) * 60 + int(zone[3:5]))
        from datetime import timedelta

        local = local - timedelta(minutes=offset)
    base = local.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{fraction}Z" if fraction else f"{base}Z"


def _whole_epoch(value: str) -> int:
    normalized = value[:-1] if value.endswith("Z") else value
    second_part = normalized.split(".", 1)[0]
    return int(datetime.fromisoformat(second_part + "+00:00").timestamp())


def _openssl_time_to_utc(value: str) -> str:
    parsed = datetime.strptime(value, "%b %d %H:%M:%S %Y GMT").replace(tzinfo=UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _openssl(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["openssl", *arguments],
            capture_output=True,
            timeout=OPENSSL_STEP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CB01TrustError("Bounded OpenSSL verification failed to complete.") from error
    if completed.returncode != 0:
        # Details can contain ASN.1 and certificate dumps; persist stable reason codes instead.
        raise CB01TrustError("Bounded OpenSSL verification rejected the input.")
    return completed


def _fetch_curl(
    url: str,
    *,
    max_bytes: int,
    connect_timeout: int,
    total_timeout: int,
    deadline: float,
    not_found_is_none: bool = False,
) -> bytes | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CB01TrustError("Sigstore TUF refresh exceeded its total time bound.")
    timeout = min(total_timeout, max(1, int(remaining)))
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-curl-") as directory:
        destination = Path(directory) / "response.bin"
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "2",
            "--connect-timeout",
            str(min(connect_timeout, timeout)),
            "--max-time",
            str(timeout),
            "--max-filesize",
            str(max_bytes),
            "--output",
            str(destination),
            "--write-out",
            "%{http_code}",
            url,
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=timeout + 2, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CB01TrustError("Bounded Sigstore TUF network request failed.") from error
        status = completed.stdout.decode("ascii", errors="ignore")[-3:]
        if completed.returncode != 0:
            raise CB01TrustError(
                "Bounded Sigstore TUF network request was unavailable or too large."
            )
        if status == "404" and not_found_is_none:
            return None
        if status != "200":
            raise CB01TrustError(f"Sigstore TUF request returned HTTP {status or 'UNKNOWN'}.")
        try:
            size = destination.stat().st_size
            if size > max_bytes:
                raise CB01TrustError("Sigstore TUF response exceeded its byte bound.")
            return destination.read_bytes()
        except OSError as error:
            raise CB01TrustError("Sigstore TUF response could not be retained.") from error


def _bounded_file(path: Path, limit: int) -> bytes | None:
    if not path.exists():
        return None
    try:
        if path.stat().st_size > limit:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _parse_json(content: bytes, label: str) -> dict[str, Any]:
    value = _parse_json_object(content, label)
    if not isinstance(value.get("signed"), dict):
        raise CB01TrustError(f"Sigstore {label} is not signed TUF JSON.")
    return value


def _parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_bad_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, CB01TrustError) as error:
        raise CB01TrustError(f"Sigstore {label} is malformed JSON.") from error
    if not isinstance(value, dict):
        raise CB01TrustError(f"Sigstore {label} is not a JSON object.")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CB01TrustError("Duplicate JSON key in Sigstore TUF metadata.")
        value[key] = item
    return value


def _bad_constant(value: str) -> None:
    raise CB01TrustError(f"Invalid non-finite TUF JSON number {value}.")


def _root_version(document: dict[str, Any]) -> int:
    signed = document["signed"]
    if signed.get("_type") != "root" or type(signed.get("version")) is not int:
        raise CB01TrustError("Sigstore root metadata type or version is invalid.")
    return cast(int, signed["version"])


def _metadata_version(document: dict[str, Any], role: str) -> int:
    signed = document["signed"]
    if (
        signed.get("_type") != role
        or type(signed.get("version")) is not int
        or signed["version"] < 1
    ):
        raise CB01TrustError(f"Sigstore {role} metadata type or version is invalid.")
    return cast(int, signed["version"])


def _referenced_version(document: dict[str, Any], filename: str) -> int:
    try:
        version = document["signed"]["meta"][filename]["version"]
    except (KeyError, TypeError) as error:
        raise CB01TrustError(f"Sigstore TUF metadata has no reference to {filename}.") from error
    if type(version) is not int or version < 1:
        raise CB01TrustError(f"Sigstore TUF reference to {filename} has an invalid version.")
    return version


def _verify_metadata_reference(document: dict[str, Any], filename: str, content: bytes) -> None:
    reference = document["signed"]["meta"][filename]
    if "length" in reference and _positive_int(reference["length"], "TUF metadata length") != len(
        content
    ):
        raise CB01TrustError(f"Sigstore TUF {filename} length does not match its parent metadata.")
    hashes = reference.get("hashes")
    if hashes is not None:
        if not isinstance(hashes, dict) or not isinstance(hashes.get("sha256"), str):
            raise CB01TrustError(f"Sigstore TUF {filename} hash reference is malformed.")
        if hashlib.sha256(content).hexdigest() != hashes["sha256"]:
            raise CB01TrustError(
                f"Sigstore TUF {filename} hash does not match its parent metadata."
            )


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise CB01TrustError(f"{label} must be a positive integer.")
    return value


def _target_sha256(entry: dict[str, Any]) -> str:
    hashes = entry.get("hashes")
    if not isinstance(hashes, dict):
        raise CB01TrustError("Sigstore TrustedRoot target has no SHA-256 digest.")
    digest_value = hashes.get("sha256")
    if not isinstance(digest_value, str):
        raise CB01TrustError("Sigstore TrustedRoot target has no SHA-256 digest.")
    digest = digest_value
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise CB01TrustError("Sigstore TrustedRoot target SHA-256 digest is malformed.")
    return digest


def _trusted_root_target_entry(document: dict[str, Any]) -> dict[str, Any]:
    try:
        entry = document["signed"]["targets"]["trusted_root.json"]
    except (KeyError, TypeError) as error:
        raise CB01TrustError(
            "Authenticated Sigstore TUF metadata has no trusted_root.json target."
        ) from error
    if not isinstance(entry, dict):
        raise CB01TrustError("Sigstore TrustedRoot target metadata is malformed.")
    return cast(dict[str, Any], entry)


def _verify_role(
    document: dict[str, Any],
    root: dict[str, Any],
    role: str,
    *,
    deadline: float | None = None,
) -> None:
    signed = document.get("signed")
    signatures = document.get("signatures")
    if not isinstance(signed, dict) or not isinstance(signatures, list):
        raise CB01TrustError("Sigstore TUF metadata signature structure is malformed.")
    policy = root["signed"]["roles"].get(role)
    if not isinstance(policy, dict):
        raise CB01TrustError(f"Sigstore TUF root has no {role} role.")
    keyids = policy.get("keyids")
    threshold = policy.get("threshold")
    if (
        not isinstance(keyids, list)
        or not keyids
        or len(keyids) > MAX_TUF_ROLE_KEYIDS
        or any(not isinstance(keyid, str) or not keyid for keyid in keyids)
        or len(keyids) != len(set(keyids))
        or type(threshold) is not int
        or threshold < 1
        or threshold > len(keyids)
    ):
        raise CB01TrustError(f"Sigstore TUF {role} threshold is malformed.")
    if len(signatures) > MAX_TUF_ROLE_SIGNATURES:
        raise CB01TrustError(f"Sigstore TUF {role} has too many signature records.")
    signed_bytes = _tuf_canonical_bytes(signed)
    valid_keyids: set[str] = set()
    signature_keyids: set[str] = set()
    keys = root["signed"]["keys"]
    for signature in signatures:
        if not isinstance(signature, dict):
            raise CB01TrustError("Sigstore TUF signature record is malformed.")
        keyid = signature.get("keyid")
        sig = signature.get("sig")
        if not isinstance(keyid, str) or not isinstance(sig, str):
            raise CB01TrustError("Sigstore TUF signature identity is malformed.")
        if keyid in signature_keyids:
            raise CB01TrustError("Sigstore TUF metadata has duplicate signatures for one key.")
        signature_keyids.add(keyid)
        if keyid not in keyids:
            continue
        key = keys.get(keyid)
        if (
            not isinstance(key, dict)
            or key.get("keytype") != "ecdsa"
            or key.get("scheme") != "ecdsa-sha2-nistp256"
        ):
            raise CB01TrustError("Sigstore TUF signature uses an unsupported key type or scheme.")
        public_pem = key["keyval"].get("public")
        if not isinstance(public_pem, str):
            raise CB01TrustError("Sigstore TUF ECDSA public key is missing.")
        try:
            signature_der = bytes.fromhex(sig)
        except ValueError as error:
            raise CB01TrustError("Sigstore TUF ECDSA signature is malformed.") from error
        if deadline is not None:
            _check_crypto_deadline(deadline)
        if _verify_ecdsa(public_pem.encode(), signed_bytes, signature_der):
            valid_keyids.add(keyid)
        if deadline is not None:
            _check_crypto_deadline(deadline)
    if len(valid_keyids) < threshold:
        raise CB01TrustError(f"Sigstore TUF {role} signature threshold was not met.")


def _check_crypto_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise CB01TrustError("Sigstore TUF cryptographic work exceeded its v1 time bound.")


def _verify_ecdsa(public_pem: bytes, message: bytes, signature: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="matchvet-cb01-tuf-sig-") as directory:
        work = Path(directory)
        key_path, message_path, signature_path = (
            work / "key.pem",
            work / "signed.json",
            work / "signature.der",
        )
        key_path.write_bytes(public_pem)
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        try:
            completed = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(key_path),
                    "-signature",
                    str(signature_path),
                    str(message_path),
                ],
                capture_output=True,
                timeout=OPENSSL_STEP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CB01TrustError(
                "Bounded TUF signature verification failed to complete."
            ) from error
        return completed.returncode == 0 and b"Verified OK" in completed.stdout


def _check_expiry(document: dict[str, Any], now: datetime) -> None:
    expires = document["signed"].get("expires")
    if not isinstance(expires, str):
        raise CB01TrustError("Sigstore TUF metadata expiry is missing.")
    try:
        expiration = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError as error:
        raise CB01TrustError("Sigstore TUF metadata expiry is malformed.") from error
    if expiration.tzinfo is None or expiration.astimezone(UTC) <= now.astimezone(UTC):
        raise CB01TrustError("Sigstore TUF metadata is expired at refresh time.")


def _select_tsa_entry(
    target: dict[str, Any], policy_body: dict[str, Any]
) -> tuple[dict[str, Any], bytes, bytes]:
    if target.get("mediaType") != "application/vnd.dev.sigstore.trustedroot+json;version=0.1":
        raise CB01TrustError("Sigstore TrustedRoot target media type is unsupported.")
    authorities = target.get("timestampAuthorities")
    if not isinstance(authorities, list):
        raise CB01TrustError("Sigstore TrustedRoot timestampAuthorities is malformed.")
    matches = [
        row
        for row in authorities
        if isinstance(row, dict) and row.get("uri") == policy_body["endpoint"]
    ]
    if len(matches) != 1:
        raise CB01TrustError("Sigstore TrustedRoot must contain exactly one expected TSA entry.")
    entry = matches[0]
    subject = entry.get("subject")
    chain = (
        entry.get("certChain", {}).get("certificates")
        if isinstance(entry.get("certChain"), dict)
        else None
    )
    valid_for = entry.get("validFor")
    if not isinstance(subject, dict) or _display_subject(subject) != TSA_ISSUER:
        raise CB01TrustError("Sigstore TrustedRoot TSA subject differs from pinned v1.")
    if not isinstance(valid_for, dict) or not isinstance(valid_for.get("start"), str):
        raise CB01TrustError("Sigstore TrustedRoot TSA validFor start is missing.")
    if valid_for["start"] != TRUSTED_ROOT_VALID_FROM or valid_for.get("end") is not None:
        raise CB01TrustError("Sigstore TrustedRoot TSA validFor period differs from pinned v1.")
    if not isinstance(chain, list) or len(chain) != 2:
        raise CB01TrustError(
            "Sigstore TrustedRoot TSA chain must contain exactly two certificates."
        )
    try:
        signer_der = base64.b64decode(chain[0]["rawBytes"], validate=True)
        anchor_der = base64.b64decode(chain[1]["rawBytes"], validate=True)
    except (TypeError, ValueError, KeyError) as error:
        raise CB01TrustError("Sigstore TrustedRoot TSA certificate bytes are malformed.") from error
    if (
        digest_bytes(signer_der) != TSA_SIGNER_SHA256
        or digest_bytes(anchor_der) != TSA_ANCHOR_SHA256
    ):
        raise CB01TrustError("Sigstore TrustedRoot TSA certificate bytes differ from pinned v1.")
    if signer_der != _certificate_bytes(
        "sigstore-tsa-leaf.der"
    ) or anchor_der != _certificate_bytes("sigstore-tsa-root.der"):
        raise CB01TrustError(
            "Sigstore TrustedRoot TSA certificates do not match package trust material."
        )
    return cast(dict[str, Any], entry), signer_der, anchor_der


def _display_subject(value: dict[str, Any]) -> str:
    organization = value.get("organization")
    common_name = value.get("commonName")
    if not isinstance(organization, str) or not isinstance(common_name, str):
        raise CB01TrustError("Sigstore TrustedRoot subject is malformed.")
    return f"O={organization}, CN={common_name}"


def _valid_for_contains(entry: dict[str, Any], gen_time: str) -> bool:
    valid_for = entry["validFor"]
    start = valid_for["start"]
    end = valid_for.get("end")
    if compare_utc(start, gen_time) > 0:
        return False
    return end is None or compare_utc(gen_time, end) <= 0


def _tuf_canonical_bytes(value: object) -> bytes:
    def encode(item: object) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if type(item) is int:
            return str(item)
        if isinstance(item, str):
            return '"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(item, list):
            return "[" + ",".join(encode(value) for value in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise CB01TrustError("TUF canonical metadata object keys must be strings.")
            fields = (encode(key) + ":" + encode(item[key]) for key in sorted(item))
            return "{" + ",".join(fields) + "}"
        raise CB01TrustError("TUF canonical JSON forbids floating-point and unsupported values.")

    return encode(value).encode("utf-8")


def _bootstrap_root_bytes() -> bytes:
    return _asset_bytes("sigstore-root10.json")


def _certificate_bytes(name: str) -> bytes:
    return _asset_bytes(name)


def _asset_bytes(name: str) -> bytes:
    path = Path(__file__).resolve().parent / "data" / "cb01" / name
    try:
        return path.read_bytes()
    except OSError as error:
        raise CB01TrustError(f"Pinned Sigstore trust asset {name} is unavailable.") from error


def _openssl_version() -> str:
    try:
        result = subprocess.run(["openssl", "version"], capture_output=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise CB01TrustError(
            "OpenSSL is required for the frozen Sigstore verification policy."
        ) from error
    text = result.stdout.decode("ascii", errors="replace").strip()
    if not text.startswith("OpenSSL "):
        raise CB01TrustError("Unsupported OpenSSL implementation.")
    return text.split()[1]


def _der_length(size: int) -> bytes:
    if size < 0x80:
        return bytes([size])
    encoded = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _der(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(content)) + content


def _oid_der(value: str) -> bytes:
    arcs = [int(item) for item in value.split(".")]
    if len(arcs) < 2 or arcs[0] > 2 or (arcs[1] >= 40 and arcs[0] < 2):
        raise CB01TrustError("Malformed TUF elliptic curve OID.")
    encoded = bytearray([40 * arcs[0] + arcs[1]])
    for arc in arcs[2:]:
        parts = [arc & 0x7F]
        arc >>= 7
        while arc:
            parts.append(0x80 | (arc & 0x7F))
            arc >>= 7
        encoded.extend(reversed(parts))
    return _der(0x06, bytes(encoded))


def _public_pem_from_tuf_key(value: dict[str, Any]) -> bytes:
    pem = value["keyval"]["public"]
    if not isinstance(pem, str):
        raise CB01TrustError("TUF public key PEM is malformed.")
    return pem.encode("ascii")

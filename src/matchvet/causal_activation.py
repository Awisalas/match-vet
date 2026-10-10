"""Private owner authentication. See docs/design/causal-owner-activation.md.

A fresh independent checkpoint is mandatory. No local record, retained key or
caller-built Approval grants authority. This module never fetches TUF metadata.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from matchvet.causal_trust import (
    _PROFILE,
    _PROFILE_DIGEST,
    _TARGET,
    _Approval,
    _authenticate,
    _openssl,
    _parse_json_object,
    _TrustBundle,
    _utc,
)
from matchvet.causal_witness import WitnessError, _canonical, _digest
from matchvet.store import Store

_OWNER_CONFIG = Path(sys.base_prefix) / "etc/matchvet/causal-owner-v1.json"
_DOMAIN = "matchvet-causal-owner-v1"
_PREMISES = {
    "operator_policy_compliance": True,
    "uncompromised_authority": True,
    "unsmeared_utc": True,
}
_LIMIT = 16 * 1024 * 1024
_FIELDS = {
    "domain",
    "schema_version",
    "algorithm",
    "action",
    "owner",
    "deployment",
    "catalog",
    "history",
    "sequence",
    "predecessor",
    "purpose",
    "issue",
    "profile_digest",
    "profile",
    "accepted_premises",
    "not_before",
    "not_after",
    "bundle",
    "floors",
    "adverse",
}
_IDENTITY = ("owner", "deployment", "catalog", "history")


def _hex(value: object) -> bytes:
    if not isinstance(value, str):
        raise WitnessError("Owner evidence requires exact hexadecimal bytes.")
    raw = bytes.fromhex(value)
    if raw.hex() != value:
        raise WitnessError("Noncanonical owner hexadecimal bytes.")
    return raw


def _json(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > _LIMIT:
        raise WitnessError("Owner evidence exceeds its bound.")
    value = _parse_json_object(raw, "owner")
    if _canonical(value) != raw:
        raise WitnessError("Noncanonical owner envelope.")
    return value


def _verify(raw: bytes, key: bytes) -> dict[str, Any]:
    # RFC 8410 Ed25519 SPKI with no parameters; record bytes cannot nominate keys.
    if len(key) != 44 or key[:12] != bytes.fromhex("302a300506032b6570032100"):
        raise WitnessError("Owner key must be Ed25519 SubjectPublicKeyInfo DER.")
    envelope = _json(raw)
    if set(envelope) != {"signed", "signature"} or not isinstance(envelope["signed"], dict):
        raise WitnessError("Unsupported owner envelope.")
    signature = _hex(envelope["signature"])
    signed = envelope["signed"]
    if (
        len(signature) != 64
        or signed.get("domain") != _DOMAIN
        or type(signed.get("schema_version")) is not int
        or signed["schema_version"] != 1
        or signed.get("algorithm") != "Ed25519"
        or signed.get("owner") != _digest(key)
    ):
        raise WitnessError("Owner envelope domain/schema/key mismatch.")
    with tempfile.TemporaryDirectory(prefix="matchvet-owner-verify-") as directory:
        work = Path(directory)
        for name, content in (
            ("key.der", key),
            ("message", _DOMAIN.encode() + b"\0" + _canonical(signed)),
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


def _bundle(value: object) -> _TrustBundle:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "roots",
            "timestamp",
            "snapshot",
            "targets",
            "trusted_root",
        }
        or not isinstance(value["roots"], list)
    ):
        raise WitnessError("Missing exact admitted owner trust bundle.")
    return _TrustBundle(
        tuple(_hex(v) for v in value["roots"]),
        *(_hex(value[v]) for v in ("timestamp", "snapshot", "targets", "trusted_root")),
    )


def _history(records: tuple[bytes, ...], key: bytes) -> tuple[_Approval, _TrustBundle]:
    if not records or len(records) > 1024:
        raise WitnessError("Missing or excessive owner history.")
    prior: dict[str, Any] | None = None
    prior_raw: bytes | None = None
    bundle: _TrustBundle | None = None
    for sequence, raw in enumerate(records, 1):
        value = _verify(raw, key)
        if (
            set(value) != _FIELDS
            or type(value["sequence"]) is not int
            or value["sequence"] != sequence
            or value["predecessor"] != (None if prior_raw is None else _digest(prior_raw))
            or any(not isinstance(value[k], str) or not value[k] for k in _IDENTITY)
            or value["purpose"] != "RESEARCH_ONLY"
            or type(value["issue"]) is not int
            or value["issue"] != 70
            or value["profile_digest"] != _PROFILE_DIGEST
            or _canonical(value["profile"]) != _PROFILE
            or _canonical(value["accepted_premises"]) != _canonical(_PREMISES)
            or _utc(value["not_before"]) >= _utc(value["not_after"])
        ):
            raise WitnessError("Owner record identity/profile/sequence mismatch.")
        action = value["action"]
        if prior is None:
            if action != "activate" or value["adverse"] is not None:
                raise WitnessError("Owner history must begin with activation.")
        else:
            fixed = _FIELDS - {"sequence", "predecessor", "action", "bundle", "floors", "adverse"}
            if any(value[k] != prior[k] for k in fixed):
                raise WitnessError("Owner history changes immutable approval identities.")
            if action == "admit":
                if prior["adverse"] is not None or value["adverse"] is not None:
                    raise WitnessError("Withdrawn owner history cannot admit new metadata.")
            elif action == "withdraw":
                if value["adverse"] is None or prior["adverse"] is not None:
                    raise WitnessError("Withdrawal must append exact adverse evidence once.")
                if any(value[k] != prior[k] for k in ("bundle", "floors")):
                    raise WitnessError("Withdrawal cannot change admitted metadata.")
            elif action == "reconcile":
                if any(value[k] != prior[k] for k in ("bundle", "floors", "adverse")):
                    raise WitnessError("Reconciliation cannot erase or change owner state.")
            else:
                raise WitnessError("Unsupported owner action.")
        adverse = value["adverse"]
        if adverse is not None:
            if not isinstance(adverse, dict) or set(adverse) != {
                "effective_from",
                "published_at",
                "observed_at",
            }:
                raise WitnessError("Malformed authenticated adverse evidence.")
            for field in ("published_at", "observed_at"):
                _utc(adverse[field])
            if adverse["effective_from"] is not None:
                _utc(adverse["effective_from"])
        candidate = _bundle(value["bundle"])
        if bundle is not None and candidate.roots[: len(bundle.roots)] != bundle.roots:
            raise WitnessError("Owner admission rewrites an admitted root rotation identity.")
        if candidate != bundle:
            authenticated = _authenticate(candidate)
            if _digest(candidate.trusted_root) != _TARGET:
                raise WitnessError("Owner admission changes the immutable TrustedRoot pin.")
            if value["floors"] != [list(v) for v in authenticated.versions]:
                raise WitnessError("Owner floors do not name the exact authenticated closure.")
        elif prior is not None and value["floors"] != prior["floors"]:
            raise WitnessError("Owner floors changed without exact metadata admission.")
        if prior is not None:
            for old, new in zip(prior["floors"], value["floors"], strict=True):
                if old[0] != new[0] or new[1] < old[1] or (new[1] == old[1] and new[2] != old[2]):
                    raise WitnessError("Owner floor rollback or equal-version hash conflict.")
        bundle, prior, prior_raw = candidate, value, raw
    assert prior is not None and bundle is not None
    adverse = prior["adverse"]
    return _Approval(
        prior["not_before"],
        prior["not_after"],
        tuple(tuple(v) for v in prior["floors"]),
        _TARGET,
        prior["history"],
        None if adverse is None else (adverse["effective_from"] or prior["not_before"]),
        owner_record=records[-1],
    ), bundle


def _checkpoint(config: dict[str, Any], nonce: str) -> bytes:
    request = {k: config[k] for k in ("deployment", "catalog", "history")}
    request["nonce"] = nonce
    deadline = time.monotonic() + 5
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(config["checkpoint_socket"])
        connection.sendall(_canonical(request) + b"\n")
        content = bytearray()
        while len(content) <= _LIMIT:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WitnessError("Independent checkpoint deadline expired.")
            connection.settimeout(remaining)
            chunk = connection.recv(min(65536, _LIMIT + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if b"\n" in chunk:
                break
    if not content.endswith(b"\n") or len(content) > _LIMIT:
        raise WitnessError("Missing bounded independent checkpoint response.")
    return bytes(content[:-1])


def _check_head(
    raw: bytes,
    key: bytes,
    last: dict[str, Any],
    records: tuple[bytes, ...],
    *,
    nonce: str | None = None,
) -> None:
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
            "floors",
            "continuity",
        }
        or head["action"] != "checkpoint"
        or head["continuity"] != "RECONCILED"
        or (nonce is not None and head["nonce"] != nonce)
        or len(_hex(head["nonce"])) != 32
        or any(head[k] != last[k] for k in _IDENTITY)
        or type(head["sequence"]) is not int
        or head["sequence"] != len(records)
        or head["head"] != _digest(records[-1])
        or head["floors"] != last["floors"]
    ):
        raise WitnessError("Missing, old, forked or uncertain independent owner checkpoint.")


def _load_owner(store: Store) -> tuple[_Approval, _TrustBundle]:
    config = _json(_OWNER_CONFIG.read_bytes())
    status = _OWNER_CONFIG.stat()
    if status.st_uid != os.getuid() or status.st_mode & 0o022:
        raise WitnessError("Owner installation is not independently protected.")
    if set(config) != {
        "verification_key",
        "deployment",
        "catalog",
        "history",
        "records",
        "checkpoint_socket",
    } or any(not isinstance(v, str) or not v for v in config.values()):
        raise WitnessError("Missing independently installed owner configuration.")
    if config["catalog"] != str(store.path.resolve()) or any(
        not Path(config[k]).is_absolute() for k in ("records", "checkpoint_socket")
    ):
        raise WitnessError("Owner deployment/catalog installation mismatch.")
    key = _hex(config["verification_key"])
    directory = Path(config["records"])
    paths = sorted(directory.iterdir())
    if (
        not paths
        or len(paths) > 1024
        or [p.name for p in paths] != [f"{n:020d}.json" for n in range(1, len(paths) + 1)]
    ):
        raise WitnessError("Missing or forked append-only owner history.")
    records = tuple(path.read_bytes() for path in paths)
    approval, bundle = _history(records, key)
    last = _json(records[-1])["signed"]
    if any(last[k] != config[k] for k in ("deployment", "catalog", "history")):
        raise WitnessError("Owner configuration and history identities conflict.")
    nonce = secrets.token_bytes(32).hex()
    checkpoint = _checkpoint(config, nonce)
    _check_head(checkpoint, key, last, records, nonce=nonce)
    from dataclasses import replace

    return replace(
        approval,
        owner_evidence=_canonical(
            {
                "schema_version": 2,
                "approval_digest": _digest(records[-1]),
                "records": [v.hex() for v in records],
                "checkpoint": checkpoint.hex(),
                "verification_key": key.hex(),
            }
        ),
    ), bundle


def _retained_approval(raw: bytes) -> tuple[_Approval, _TrustBundle]:
    """Historical inspection only; independently trusted current history grants use."""
    value = _json(raw)
    if set(value) != {
        "schema_version",
        "approval_digest",
        "records",
        "checkpoint",
        "verification_key",
    } or (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 2
        or not isinstance(value["records"], list)
    ):
        raise WitnessError("Unsupported signed approval evidence schema.")
    records = tuple(_hex(v) for v in value["records"])
    if not records or value["approval_digest"] != _digest(records[-1]):
        raise WitnessError("Retained approval identity differs from its signed record bytes.")
    key = _hex(value["verification_key"])
    approval, bundle = _history(records, key)
    _check_head(_hex(value["checkpoint"]), key, _json(records[-1])["signed"], records)
    from dataclasses import replace

    return replace(approval, owner_evidence=raw), bundle


def _require_lineage(original: _Approval, current: _Approval) -> None:
    if original.owner_evidence is None or current.owner_evidence is None:
        raise WitnessError("Retained approval has no independently authenticated lineage.")
    prior, now = (_json(v) for v in (original.owner_evidence, current.owner_evidence))
    if prior["verification_key"] != now["verification_key"] or (
        now["records"][: len(prior["records"])] != prior["records"]
    ):
        raise WitnessError("Original approval is not in the current authenticated owner history.")

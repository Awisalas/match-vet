"""Synthetic owner service and offline retained closures. No installed authority."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from causal_selection_support import trust

from matchvet.causal_trust import _PROFILE, _PROFILE_DIGEST, _authenticate, _openssl, _TrustBundle
from matchvet.causal_witness import _canonical, _digest
from matchvet.store import Store

FRESH = Path(__file__).resolve().parents[1] / ".audit/issue-87-implementation"


def fresh_bundle() -> _TrustBundle:
    return replace(
        trust(),
        timestamp=(FRESH / "timestamp.json").read_bytes(),
        snapshot=(FRESH / "snapshot.json").read_bytes(),
    )


def bundle_fields(bundle: _TrustBundle) -> dict[str, object]:
    return {
        "roots": [v.hex() for v in bundle.roots],
        **{
            k: getattr(bundle, k).hex()
            for k in ("timestamp", "snapshot", "targets", "trusted_root")
        },
    }


class Owner:
    def __init__(self, root: Path, store: Store) -> None:
        self.root = root
        root.mkdir()
        self.records = root / "history"
        self.records.mkdir()
        self.config_path = root / "installed.json"
        self.private = root / "synthetic-private.der"
        # RFC 8410 PKCS#8 with a fixed synthetic seed, never production provisioning.
        self.private.write_bytes(
            bytes.fromhex("302e020100300506032b657004220420") + bytes(range(32))
        )
        self.key = _openssl(
            [
                "pkey",
                "-inform",
                "DER",
                "-in",
                str(self.private),
                "-pubout",
                "-outform",
                "DER",
            ]
        ).stdout
        self.config: dict[str, str] = {
            "verification_key": self.key.hex(),
            "deployment": "offline-synthetic-deployment",
            "catalog": str(store.path.resolve()),
            "history": "offline-synthetic-history",
            "records": str(self.records),
            "checkpoint_socket": str(root / "checkpoint.sock"),
        }
        self.install()
        self.raws: list[bytes] = []
        self.head_changes: dict[str, object] = {}
        self.append("activate")

    def install(self) -> None:
        self.config_path.write_bytes(_canonical(self.config))
        self.config_path.chmod(0o600)

    def sign(self, value: dict[str, Any]) -> bytes:
        message = self.root / "message"
        message.write_bytes(b"matchvet-causal-owner-v1\0" + _canonical(value))
        signature = _openssl(
            [
                "pkeyutl",
                "-sign",
                "-keyform",
                "DER",
                "-inkey",
                str(self.private),
                "-rawin",
                "-in",
                str(message),
            ]
        ).stdout
        return _canonical({"signed": value, "signature": signature.hex()})

    def append(self, action: str, **changes: Any) -> bytes:
        if self.raws:
            value = json.loads(self.raws[-1])["signed"]
        else:
            bundle = trust()
            value = {
                "domain": "matchvet-causal-owner-v1",
                "schema_version": 1,
                "algorithm": "Ed25519",
                "owner": _digest(self.key),
                **{k: self.config[k] for k in ("deployment", "catalog", "history")},
                "purpose": "RESEARCH_ONLY",
                "issue": 70,
                "profile_digest": _PROFILE_DIGEST,
                "profile": json.loads(_PROFILE),
                "accepted_premises": {
                    "operator_policy_compliance": True,
                    "uncompromised_authority": True,
                    "unsmeared_utc": True,
                },
                "not_before": "2025-07-04T00:00:00Z",
                "not_after": "2026-11-01T00:00:00Z",
                "adverse": None,
                "bundle": bundle_fields(bundle),
                "floors": [list(v) for v in _authenticate(bundle).versions],
            }
        value.update(
            action=action,
            sequence=len(self.raws) + 1,
            predecessor=_digest(self.raws[-1]) if self.raws else None,
        )
        value.update(changes)
        raw = self.sign(value)
        self.raws.append(raw)
        (self.records / f"{len(self.raws):020d}.json").write_bytes(raw)
        return raw

    def admit(self, bundle: _TrustBundle) -> bytes:
        return self.append(
            "admit",
            bundle=bundle_fields(bundle),
            floors=[list(v) for v in _authenticate(bundle).versions],
        )

    def withdraw(self, effective: str | None = "2026-10-05T04:50:20Z") -> bytes:
        return self.append(
            "withdraw",
            adverse={
                "effective_from": effective,
                "published_at": "2026-10-10T01:00:00Z",
                "observed_at": "2026-10-10T02:00:00Z",
            },
        )

    def checkpoint(self, config: dict[str, Any], nonce: str) -> bytes:
        last = json.loads(self.raws[-1])["signed"]
        value = {
            "domain": "matchvet-causal-owner-v1",
            "schema_version": 1,
            "algorithm": "Ed25519",
            "action": "checkpoint",
            "owner": _digest(self.key),
            **{k: self.config[k] for k in ("deployment", "catalog", "history")},
            "nonce": nonce,
            "sequence": len(self.raws),
            "head": _digest(self.raws[-1]),
            "floors": last["floors"],
            "continuity": "RECONCILED",
        }
        value.update(self.head_changes)
        return self.sign(value)

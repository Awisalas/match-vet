"""Synthetic Ed25519 source owner and retained classifications, never provisioning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from issue84_support import SuccessorWeek

from matchvet.artifacts import ArtifactStore
from matchvet.causal_trust import _openssl
from matchvet.source_manifest import (
    OPERATIONS,
    POLICY_DIGEST,
    RISK_BASIS,
    canonical,
    digest,
    outcome_projection,
    retain_manifest,
    selected_projection,
)
from matchvet.store import Store


def reopen_capture_week(root: Path) -> SuccessorWeek:
    """Reuse a completed isolated #86 graph without generating another F15 run."""
    from issue84_support import CausalGraphIdentity, HistoricalV1

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import CANDIDATE_MEDIA_TYPE, resolve
    from matchvet.f10 import V2_REQUIREMENT_CATALOG
    from matchvet.f13 import causal_engine_version_identity
    from matchvet.f15 import AnalyzeMatchweekRequest
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion

    with open_store(root / "store.sqlite3", private_root=root) as store:
        candidates = [
            v.digest for v in store.artifact_catalog() if v.media_type == CANDIDATE_MEDIA_TYPE
        ]
        manifests = [
            v.digest for v in store.artifact_catalog() if v.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(candidates) == len(manifests) == 1
        candidate = resolve(store, candidates[0])
        freeze = MatchweekMembershipRepository(store).get_by_id(candidate.freeze_id)
        assert freeze is not None
        value = json.loads(ArtifactStore(store).read_artifact(manifests[0]))
        cutoffs = MatchEvidenceCutoffRepository(store).replay_for_freeze(
            candidate.freeze_id, candidate.cutoff_policy_digest
        )
        request = AnalyzeMatchweekRequest(
            freeze.matchweek_friday,
            candidate.freeze_id,
            candidate.cutoff_policy_digest,
            tuple(sorted(v.cutoff_id for v in cutoffs)),
            V2_REQUIREMENT_CATALOG.digest,
            causal_engine_version_identity(),
            candidate.profile_digest,
            PolicyVersion.from_mapping(value["policy"]),
            candidate.digest,
        )
        return SuccessorWeek(
            root,
            request,
            manifests[0],
            CausalGraphIdentity(candidate.logical_matchweek_id, candidate.cutoff_at_utc),
            freeze.freeze_digest,
            tuple(
                sorted(
                    v.membership_id for v in freeze.memberships if v.decision.value == "INCLUDED"
                )
            ),
            HistoricalV1("", "", "", ()),
            (),
        )


def entry(store: Store, dependency_id: str = "synthetic-public-request") -> dict[str, Any]:
    evidence = (
        ArtifactStore(store)
        .publish_artifact(
            b"Synthetic restrictive terms reviewed for private research risk; no external grant.",
            "text/plain",
        )
        .digest
    )
    return {
        "dependency_id": dependency_id,
        "provider": "synthetic-provider",
        "publisher": "synthetic-publisher",
        "upstream_lineage": {
            "state": "UNKNOWN",
            "identities": [],
            "reason": "No upstream evidence.",
        },
        "source_type": "AUTOMATED_API",
        "access_type": "PUBLIC",
        "endpoint": "https://offline.invalid/feed",
        "raw_identity": {"id": "UNKNOWN", "digest": "UNKNOWN"},
        "normalized_identity": {"id": "UNKNOWN", "digest": "UNKNOWN"},
        "parser_version": "synthetic-parser-v1",
        "retrieved_at": "UNKNOWN",
        "published_at": "UNKNOWN",
        "observed_at": "UNKNOWN",
        "competition": "synthetic-competition",
        "season": "2026-27",
        "capability": "scheduled-fixtures",
        "requested_operations": list(OPERATIONS[:-1]),
        "external_permission": {
            "state": "UNKNOWN",
            "evidence": [],
            "reason": "No publisher grant.",
        },
        "operation_permissions": {
            operation: {"state": "UNKNOWN", "reason": "No publisher grant."}
            for operation in OPERATIONS
        },
        "terms_review": {
            "identity": "synthetic-terms-v1",
            "url": "https://offline.invalid/terms",
            "digest": evidence,
            "reviewed_at": "2026-10-10T08:00:00Z",
            "effective_at": "UNKNOWN",
            "valid_until": "2026-11-01T00:00:00Z",
            "classification": "Restrictive external terms; internal private risk accepted.",
            "evidence": [evidence],
            "manual_policy_digest": "UNKNOWN",
        },
        "internal_basis": RISK_BASIS,
        "retention": {
            "class": "PROTECTED",
            "redistributable": False,
            "duration": "Research evidence lifecycle",
            "termination": "UNKNOWN",
            "backup_location": "Private recovery storage",
            "recipients": "Private operator",
        },
        "attribution": "Retain exact synthetic source identity.",
        "technical_limits": {
            "requests": 1,
            "bytes": 1024,
            "timeout_seconds": 5,
            "rate_limit_review": "Synthetic provider permits one request.",
            "bypass_access_controls": False,
        },
    }


def acquisition_manifest(store: Store, classification: dict[str, Any] | None = None) -> str:
    classification = classification or entry(store)
    return retain_manifest(
        store,
        stage="ACQUISITION",
        selection_digest=None,
        projection={
            "request": {"identity": classification["dependency_id"], "entry": classification},
            "dependencies": [],
        },
        entries=(classification,),
    )


def projection_entries(store: Store, projection: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    entries = []
    for dependency in projection["dependencies"]:
        classification = entry(store, dependency["id"])
        classification["normalized_identity"] = {
            "id": dependency["id"],
            "digest": dependency["digest"],
        }
        facts = dependency.get("facts", {})
        raw_digest = facts.get("artifact_digest")
        if "media_type" in dependency:
            raw_digest = dependency["digest"]
        if raw_digest:
            classification["raw_identity"] = {"id": "artifact:" + raw_digest, "digest": raw_digest}
        if "locator" in facts:
            classification["endpoint"] = facts["locator"]
        if "source_key" in facts:
            classification["provider"] = facts["source_key"]
        if "owner" in facts:
            classification["publisher"] = facts["owner"]
        if facts.get("access_method") == "MANUAL_CITATION":
            classification["source_type"] = "MANUAL_CITATION"
            classification["access_type"] = "MANUAL"
            classification["terms_review"]["manual_policy_digest"] = classification["terms_review"][
                "digest"
            ]
        if "collector_version" in facts:
            classification["parser_version"] = facts["collector_version"]
        for field, column in (
            ("retrieved_at", "retrieved_at_utc"),
            ("published_at", "source_published_at_utc"),
            ("observed_at", "observed_at_utc"),
        ):
            if column in facts:
                classification[field] = facts[column] or "UNKNOWN"
        entries.append(classification)
    return tuple(entries)


def graph_manifest(store: Store, selection_digest: str) -> str:
    projection = selected_projection(store, selection_digest)
    return retain_manifest(
        store,
        stage="SELECTED_GRAPH",
        selection_digest=selection_digest,
        projection=projection,
        entries=projection_entries(store, projection),
    )


def outcome_manifest(store: Store, selection_digest: str, settlement_digest: str) -> str:
    projection = outcome_projection(store, selection_digest, settlement_digest)
    return retain_manifest(
        store,
        stage="OUTCOME",
        selection_digest=selection_digest,
        projection=projection,
        entries=projection_entries(store, projection),
    )


class SourceOwner:
    def __init__(self, root: Path, store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
        root.mkdir()
        self.root = root
        self.records = root / "history"
        self.records.mkdir()
        self.private = root / "synthetic-private.der"
        self.private.write_bytes(
            bytes.fromhex("302e020100300506032b657004220420") + bytes(range(32, 64))
        )
        self.key = _openssl(
            ["pkey", "-inform", "DER", "-in", str(self.private), "-pubout", "-outform", "DER"]
        ).stdout
        self.config_path = root / "installed.json"
        self.config = {
            "verification_key": self.key.hex(),
            "deployment": "synthetic-source-deployment",
            "catalog": str(store.path.resolve()),
            "history": "synthetic-source-history",
            "records": str(self.records),
            "checkpoint_socket": str(root / "checkpoint.sock"),
        }
        self.config_path.write_bytes(canonical(self.config))
        self.config_path.chmod(0o600)
        self.raws: list[bytes] = []
        self.head_changes: dict[str, Any] = {}
        self.now = "2026-10-10T09:00:00Z"
        self.calls = 0
        monkeypatch.setattr("matchvet.source_authorization._SOURCE_CONFIG", self.config_path)
        monkeypatch.setattr("matchvet.source_authorization._checkpoint", self.checkpoint)

    def sign(self, signed: dict[str, Any]) -> bytes:
        message = self.root / "message"
        message.write_bytes(b"matchvet-source-authority-v1\0" + canonical(signed))
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
        return canonical({"signed": signed, "signature": signature.hex()})

    def append(self, manifest_digest: str, action: str = "authorize", **changes: Any) -> bytes:
        previous = next(
            (
                json.loads(v)["signed"]
                for v in reversed(self.raws)
                if json.loads(v)["signed"]["manifest_digest"] == manifest_digest
            ),
            None,
        )
        value = (
            dict(previous)
            if previous
            else {
                "domain": "matchvet-source-authority-v1",
                "schema_version": 1,
                "algorithm": "Ed25519",
                "owner": digest(self.key),
                **{key: self.config[key] for key in ("deployment", "catalog", "history")},
                "purpose": "RESEARCH_ONLY",
                "issue": 70,
                "manifest_digest": manifest_digest,
                "policy_digest": POLICY_DIGEST,
                "not_before": "2026-10-10T00:00:00Z",
                "not_after": "2026-11-01T00:00:00Z",
                "state": "APPROVED",
                "reason_codes": [],
                "adverse": None,
                "replacement_manifest_digest": None,
            }
        )
        value.update(
            action=action,
            sequence=len(self.raws) + 1,
            predecessor=digest(self.raws[-1]) if self.raws else None,
            issued_at=self.now,
        )
        value.update(changes)
        raw = self.sign(value)
        self.raws.append(raw)
        (self.records / f"{len(self.raws):020d}.json").write_bytes(raw)
        return raw

    def withdraw(self, manifest_digest: str) -> None:
        self.append(
            manifest_digest,
            "withdraw",
            state="WITHDRAWN",
            reason_codes=["OWNER_WITHDRAWN"],
            adverse={
                "effective_from": "UNKNOWN",
                "observed_at": self.now,
                "published_at": self.now,
                "reason": "Synthetic owner withdrawal.",
            },
        )

    def checkpoint(self, _config: dict[str, Any], nonce: str) -> bytes:
        self.calls += 1
        value = {
            "domain": "matchvet-source-authority-v1",
            "schema_version": 1,
            "algorithm": "Ed25519",
            "action": "checkpoint",
            "owner": digest(self.key),
            **{key: self.config[key] for key in ("deployment", "catalog", "history")},
            "nonce": nonce,
            "sequence": len(self.raws),
            "head": digest(self.raws[-1]),
            "continuity": "RECONCILED",
            "current_time": self.now,
        }
        value.update(self.head_changes)
        return self.sign(value)

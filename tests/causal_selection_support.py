"""Synthetic successor admission only; no stage schema or production activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from matchvet.artifacts import ArtifactStore, ManifestArtifact
from matchvet.causal_selection import _CausalGraph
from matchvet.causal_trust import _Approval, _TrustBundle
from matchvet.causal_witness import _canonical, _digest, _ParsedEvent
from matchvet.matchweek_research import MatchweekResearchRepository, _reference
from matchvet.store import Store

WIRE = Path(__file__).resolve().parents[1] / "docs/research/cb01-sigstore-witness-2026-10-05"


def approval() -> _Approval:
    return _Approval(
        "2025-07-04T00:00:00Z",
        "2026-10-06T00:00:00Z",
        (
            ("root", 15, _digest((WIRE / "15.root.json").read_bytes())),
            ("timestamp", 799, _digest((WIRE / "timestamp.json").read_bytes())),
            ("snapshot", 165, _digest((WIRE / "snapshot.json").read_bytes())),
            ("targets", 14, _digest((WIRE / "targets.json").read_bytes())),
        ),
        _digest((WIRE / "trusted_root.json").read_bytes()),
        "isolated-approved-history",
    )


def trust() -> _TrustBundle:
    return _TrustBundle(
        tuple((WIRE / f"{v}.root.json").read_bytes() for v in range(11, 16)),
        (WIRE / "timestamp.json").read_bytes(),
        (WIRE / "snapshot.json").read_bytes(),
        (WIRE / "targets.json").read_bytes(),
        (WIRE / "trusted_root.json").read_bytes(),
    )


def synthetic_graph(store: Store, *, salt: str = "") -> _CausalGraph:
    artifacts = ArtifactStore(store)
    refs: list[ManifestArtifact] = []

    def put(role: str, deps: tuple[str, ...] = (), **fields: object) -> str:
        record = artifacts.publish_artifact(
            _canonical(
                {"role": role, "successor": True, "dependencies": deps, "salt": salt, **fields}
            ),
            "application/vnd.matchvet.test-successor+json",
            retention_class="PROTECTED",
        )
        refs.append(_reference(artifacts, record.digest))
        return record.digest

    scopes = ("ENG", "ITA", "ESP", "GER", "FRA", "POR", "BEL")
    members = ("Friday", "Monday")
    captures = tuple(put("source-" + scope) for scope in scopes)
    f06 = put("F06-seven-scopes-Friday-Monday", captures, scopes=scopes, included=members)
    policy = put(
        "F07-21600", (f06,), lead_seconds=21600, common_T="2026-10-05T05:00:00.000000+00:00"
    )
    candidate = put("candidate")
    profile = put("profile")
    engine = put("engine")
    decision = put("decision-policy")
    f11 = put("F11", (f06, policy, candidate, *captures), scopes=scopes, included=members)
    model = put("F13", (f11, engine, candidate), included=members)
    f14 = put("F14", (f11, model, decision, profile, candidate), included=members)
    f16 = put("F16", (f06, policy, candidate, f11, model, f14), included=members, f11=f11)
    return _CausalGraph(
        "2026-27",
        "2026-10-02",
        "synthetic-freeze",
        policy,
        "2026-10-05T05:00:00.000000+00:00",
        f16,
        tuple(sorted(refs, key=lambda r: r.digest)),
        candidate,
        f06,
        profile,
        model,
        engine,
        decision,
    )


def install_admission(monkeypatch: Any, graph: _CausalGraph) -> None:
    def admit(
        self: MatchweekResearchRepository,
        digest: str,
        *,
        references: tuple[ManifestArtifact, ...] | None = None,
    ) -> _CausalGraph:
        assert digest == graph.f16_digest
        if references is not None and references != graph.references:
            raise ValueError("Synthetic graph closure mismatch")
        from matchvet.matchweek_research import MatchweekResearchError

        visited: set[str] = set()
        nodes: dict[str, dict[str, Any]] = {}

        def visit(current: str) -> None:
            if current in visited:
                return
            visited.add(current)
            value = json.loads(self._artifacts.read_artifact(current))
            if value.get("successor") is not True:
                raise MatchweekResearchError("Synthetic successor semantics required")
            nodes[value["role"]] = value
            for child in value["dependencies"]:
                visit(child)

        visit(digest)
        if visited != {r.digest for r in graph.references}:
            raise MatchweekResearchError("Synthetic complete transitive graph differs")
        expected_members = ["Friday", "Monday"]
        expected_scopes = ["ENG", "ITA", "ESP", "GER", "FRA", "POR", "BEL"]
        for role in ("F06-seven-scopes-Friday-Monday", "F11", "F13", "F14", "F16"):
            if nodes[role]["included"] != expected_members:
                raise MatchweekResearchError("Synthetic INCLUDED member omission")
        if (
            any(
                nodes[role]["scopes"] != expected_scopes
                for role in ("F06-seven-scopes-Friday-Monday", "F11")
            )
            or nodes["F07-21600"]["lead_seconds"] != 21600
            or nodes["F07-21600"]["common_T"] != graph.cutoff
        ):
            raise MatchweekResearchError("Synthetic seven-scope/common-T mismatch")
        return graph

    monkeypatch.setattr(MatchweekResearchRepository, "_admit_v2", admit)


def synthetic_verify(
    request: bytes,
    response: bytes,
    imprint: bytes,
    nonce: int,
    bundle: _TrustBundle,
    state: _Approval,
    *,
    qualify: bool = True,
) -> _ParsedEvent:
    # Wire cryptography is independently exercised using retained signed fixtures.
    assert response == b"isolated-signed-response"
    return _ParsedEvent(
        response,
        imprint,
        nonce,
        "2026-10-05T04:50:20.000000+00:00",
        "2026-10-05T04:50:22.000000+00:00",
        "20261005045021Z",
    )


def crash_worker(root: str, graph: _CausalGraph, mode: str) -> None:
    import os
    import sqlite3
    from typing import cast
    from unittest.mock import patch

    from matchvet.research_identity import completion_slot
    from matchvet.store import open_store

    path = Path(root)
    with open_store(path / "store.sqlite3", private_root=path) as store:
        connection = store._connection_for_repository()

        class Boundary:
            def __getattr__(self, name: str) -> Any:
                return getattr(connection, name)

            def commit(self) -> None:
                receipt = connection.execute(
                    "SELECT 1 FROM snapshot_manifests WHERE snapshot_id = ?",
                    (completion_slot(graph.logical_id),),
                ).fetchone()
                if receipt and mode == "receipt-before-commit":
                    os._exit(37)
                connection.commit()
                if receipt and mode == "receipt-after-commit":
                    os._exit(37)

        store._connection = cast(sqlite3.Connection, Boundary())

        def post(attempt: Any) -> bytes:
            if mode == "before-request":
                os._exit(37)
            attempt._start_transport()
            with (path / "request-count").open("ab") as log:
                log.write(b"1")
            return b"isolated-signed-response"

        def verify(*args: Any, **kwargs: Any) -> _ParsedEvent:
            event = synthetic_verify(*args, **kwargs)
            if mode == "after-signing":
                os._exit(37)
            return event

        with (
            patch("matchvet.causal_selection._load_approval", lambda s: (approval(), trust())),
            patch("matchvet.causal_witness._post", post),
            patch("matchvet.causal_witness._verify_event", verify),
        ):
            MatchweekResearchRepository(store).seal_completed_v2(graph.f16_digest)
    raise AssertionError("Crash boundary not reached")

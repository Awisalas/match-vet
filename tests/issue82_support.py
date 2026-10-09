"""Offline real successor fixtures shared by focused #82 tests."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from test_issue76 import Case

from matchvet.causal_selection import _CausalGraph
from matchvet.causal_trust import _Approval, _TrustBundle
from matchvet.causal_witness import _ParsedEvent
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import causal_engine_version_identity
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE, F16MatchweekProcessor
from matchvet.matchweek_research import MatchweekResearchError, MatchweekResearchRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import Store, open_store


@dataclass(frozen=True)
class Successor:
    root: Path
    request: AnalyzeMatchweekRequest
    candidate: str
    run_id: str
    input_digest: str
    manifest: str
    graph: _CausalGraph


def copy_store(source: Path, destination: Path) -> None:
    shutil.copytree(source / "objects", destination / "objects")
    shutil.copyfile(source / "store.sqlite3", destination / "store.sqlite3")


def context(
    request: AnalyzeMatchweekRequest, phase: RunPhase, input_digest: str = "0" * 64
) -> WorkContext:
    return WorkContext(
        "direct", "direct", request.matchweek, phase, 1, "RESEARCH_ONLY", input_digest, "0" * 64, 1
    )


def phase_arguments(request: AnalyzeMatchweekRequest) -> dict[str, object]:
    return {
        "freeze_id": request.freeze_id,
        "cutoff_policy_digest": request.cutoff_policy_digest,
        "cutoff_ids": request.cutoff_ids,
        "profile_digest": request.preference_profile_digest,
        "policy": request.policy,
    }


@pytest.fixture(scope="module")
def successor(
    weather_candidate: tuple[Case, str, str], tmp_path_factory: pytest.TempPathFactory
) -> Successor:
    candidate, digest, _ = weather_candidate

    root = tmp_path_factory.mktemp("issue82-real-successor")
    copy_store(candidate.root, root)
    with open_store(root / "store.sqlite3", private_root=root) as store:
        request = replace(
            candidate.request,
            candidate_contract_digest=digest,
            model_version_identity=causal_engine_version_identity(),
        )
        progress = AnalyzeMatchweek(store, candidate_contract_digest=digest).start(request)
        assert progress.analysis_state == "F16_COMPLETE_AWAITING_F17"
        roots = [
            m.digest for m in store.artifact_catalog() if m.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(roots) == 1
        manifest = F16MatchweekProcessor(store).replay_manifest(roots[0])
        assert manifest.to_dict()["candidate_contract_digest"] == digest
        graph = MatchweekResearchRepository(store)._admit_v2(roots[0])
        return Successor(
            root,
            request,
            digest,
            progress.run_id,
            progress.t04_status.input_digest,
            roots[0],
            graph,
        )


@pytest.fixture
def successor_store(successor: Successor, tmp_path: Path) -> Iterator[Store]:
    copy_store(successor.root, tmp_path)
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


@pytest.fixture(scope="module")
def weather_candidate(
    candidate: Case, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Case, str, str]:
    from matchweek_research_support import BEFORE
    from test_issue82 import descriptor

    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.store import open_store
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    root = tmp_path_factory.mktemp("issue82-weather")
    copy_store(candidate.root, root)
    with open_store(root / "store.sqlite3", private_root=root) as store:
        digest = descriptor(store, candidate)
        cutoff = MatchEvidenceCutoffRepository(store).replay(candidate.request.cutoff_ids[0])
        venue = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", BEFORE.isoformat()
        )
        request = WeatherRequest(
            cutoff.fixture_id, "2026-09-25T19:00:00Z", cutoff.cutoff_at_utc, venue
        )
        client = StaticWeatherClient(
            {
                request.url: {
                    "latitude": 6.5,
                    "longitude": 3.4,
                    "forecast_issue_time": "2026-09-25T11:00:00Z",
                    "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
                }
            },
            retrieved_at_utc="2026-10-01T12:00:00Z",
        )
        evidence = F11EvidenceRepository(store, candidate_contract_digest=digest).build(
            candidate.request.freeze_id,
            candidate.request.cutoff_policy_digest,
            weather_client=client,
            locations={cutoff.fixture_id: venue},
        )
        assert len(client.calls) == 1
        row = evidence.to_dict()["matches"][0]
        assert row["weather"]["state"] == "OBSERVED"
        assert row["weather"]["cutoff_eligibility"] == "UNQUALIFIED"
        assert row["weather"]["freshness"] == "UNKNOWN"
        assert row["contextual_attempt"] is not None
    return Case(root, candidate.request), digest, evidence.digest


@pytest.fixture
def weather_store(weather_candidate: tuple[Case, str, str], tmp_path: Path) -> Iterator[Store]:

    from matchvet.store import open_store

    case, _, _ = weather_candidate
    copy_store(case.root, tmp_path)
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


@pytest.fixture(scope="module", params=["qualified", "terminal"])
def selected_candidate(
    successor: Successor, request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Successor, str, bool]:
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from causal_selection_support import approval, trust

    from matchvet.causal_selection import _WitnessAttempt
    from matchvet.causal_witness import WitnessError, _ParsedEvent
    from matchvet.research_identity import selection_slot
    from matchvet.store import open_store

    root = tmp_path_factory.mktemp("issue82-" + str(request.param))
    copy_store(successor.root, root)
    calls = []
    cutoff = datetime.fromisoformat(successor.graph.cutoff)

    def post(attempt: _WitnessAttempt) -> bytes:
        calls.append(attempt._start_transport())
        if request.param == "terminal":
            raise WitnessError("isolated terminal transport failure")
        return b"isolated-signed-response"

    def verify(
        request_bytes: bytes,
        response: bytes,
        imprint: bytes,
        nonce: int,
        bundle: _TrustBundle,
        state: _Approval,
        *,
        qualify: bool = True,
    ) -> _ParsedEvent:
        assert response == b"isolated-signed-response"
        return _ParsedEvent(
            response,
            imprint,
            nonce,
            (cutoff - timedelta(seconds=3)).isoformat(timespec="microseconds"),
            (cutoff - timedelta(seconds=1)).isoformat(timespec="microseconds"),
            (cutoff - timedelta(seconds=2)).strftime("%Y%m%d%H%M%SZ"),
        )

    with open_store(root / "store.sqlite3", private_root=root) as store:
        owner = MatchweekResearchRepository(store)
        with (
            patch("matchvet.causal_selection._load_approval", lambda s: (approval(), trust())),
            patch("matchvet.causal_witness._post", post),
            patch("matchvet.causal_witness._verify_event", verify),
        ):
            if request.param == "terminal":
                with pytest.raises(MatchweekResearchError):
                    owner.seal_completed_v2(successor.manifest)
            else:
                chosen = owner.seal_completed_v2(successor.manifest)
                assert chosen.completion_receipt_digest
            selection = store.snapshot_manifest_digest_for_snapshot(
                selection_slot(successor.graph.logical_id)
            )
            assert selection is not None
            inspected = owner.inspect_causal(selection)
            assert inspected.f16_manifest_digest == successor.manifest
            assert bool(inspected.completion_receipt_digest) == (request.param == "qualified")
        assert len(calls) == 1
    return replace(successor, root=root), selection, request.param == "qualified"


@pytest.fixture
def selected_candidate_store(
    selected_candidate: tuple[Successor, str, bool], tmp_path: Path
) -> Iterator[Store]:

    from matchvet.store import open_store

    successor, _, _ = selected_candidate
    copy_store(successor.root, tmp_path)
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store

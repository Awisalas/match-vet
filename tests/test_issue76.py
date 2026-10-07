import shutil
from collections.abc import Generator
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest
from matchweek_research_support import BEFORE, CUTOFF, Clock
from test_matchweek_membership import _persistable_schedule_assessment
from test_matchweek_research import Graph, Qualified
from test_matchweek_research import graph as graph
from test_matchweek_research import qualified as qualified
from test_matchweek_research import selected_store as selected_store

from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import engine_version_identity
from matchvet.f14 import DecisionInputBundle, PreferenceProfileRepository
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
from matchvet.f16 import F16MatchweekProcessor
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    CORRECTED_RULE,
    MatchweekResearchError,
    MatchweekResearchRepository,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.store import Store, open_store
from matchvet.t15 import PolicyVersion


def _selected_bundle(store: Store, digest: str) -> DecisionInputBundle:
    import json

    from matchvet.artifacts import ArtifactStore
    from matchvet.f14 import DecisionInputBundle, DecisionRepository

    decision = DecisionRepository(store).replay(digest)
    raw = json.loads(ArtifactStore(store).read_artifact(decision.to_dict()["input_bundle_digest"]))
    raw.pop("schema_version")
    return DecisionInputBundle(**raw)


def test_selected_f11_f13_f14_f16_replay_and_alternate_writers_refuse(
    selected_store: Store, graph: Graph, qualified: Qualified
) -> None:
    from matchvet.f11 import F11Error
    from matchvet.f13 import ModelContractRepository
    from matchvet.f14 import DecisionRepository
    from matchvet.f16 import F16Error
    from matchvet.runs import RunPhase, WorkContext
    from matchvet.workload import WorkloadRules

    manifest = F16MatchweekProcessor(selected_store).replay_manifest(graph.f16)
    row = manifest.match_results[0]
    bundle = _selected_bundle(selected_store, row.decision_digest)
    alternate_profile = PreferenceProfileRepository(selected_store).build_profile(
        ("match_winner_away",)
    )
    before = selected_store.artifact_catalog()
    evidence = F11EvidenceRepository(
        selected_store, clock=Clock(CUTOFF)
    ).build_or_replay_for_freeze(graph.freeze, graph.policy)
    assert evidence.digest == row.evidence_digest
    with pytest.raises(F11Error, match="request"):
        F11EvidenceRepository(selected_store).build(
            graph.freeze, graph.policy, weather_client=None, rules=WorkloadRules(name="alternate")
        )
    from matchvet.weather import VenueLocation

    fixture = MatchEvidenceCutoffRepository(selected_store).replay(row.cutoff_id).fixture_id
    with pytest.raises(F11Error, match="request"):
        F11EvidenceRepository(selected_store).build(
            graph.freeze,
            graph.policy,
            weather_client=None,
            locations={
                fixture: VenueLocation(
                    "alternate",
                    "Alternate",
                    1.0,
                    2.0,
                    "venue",
                    "https://venue.test",
                    BEFORE.isoformat(),
                )
            },
        )
    model = ModelContractRepository(
        selected_store, clock=Clock(CUTOFF)
    ).build_from_retained_history(row.evidence_digest, row.cutoff_id)
    assert model.digest == row.model_digest
    with pytest.raises(MatchweekResearchError, match="occupied"):
        ModelContractRepository(selected_store).build(
            row.evidence_digest, row.cutoff_id, history=()
        )
    assert (
        DecisionRepository(selected_store, clock=Clock(CUTOFF))
        .build_or_replay_decision(bundle)
        .digest
        == row.decision_digest
    )
    with pytest.raises(MatchweekResearchError, match="occupied"):
        DecisionRepository(selected_store).build_decision(bundle)
    context = WorkContext(
        "synthetic",
        "synthetic",
        "2026-09-25",
        RunPhase.PREFERENCE_VETTING,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    from matchvet.runs import WorkResult

    def invoke(policy: PolicyVersion, profile: str | None = None) -> WorkResult:
        return F16MatchweekProcessor(selected_store, clock=Clock(CUTOFF)).process_phase(
            context,
            freeze_id=graph.freeze,
            cutoff_policy_digest=graph.policy,
            cutoff_ids=(row.cutoff_id,),
            profile_digest=profile or manifest.to_dict()["profile_digest"],
            policy=policy,
        )

    assert (
        invoke(PolicyVersion.from_mapping(manifest.to_dict()["policy"])).result_digest == graph.f16
    )
    with pytest.raises(F16Error, match="policy"):
        invoke(PolicyVersion(version="changed"))
    with pytest.raises(F16Error, match=r"[Pp]rofile"):
        invoke(PolicyVersion.from_mapping(manifest.to_dict()["policy"]), alternate_profile.digest)
    assert selected_store.artifact_catalog() == before
    assert (
        MatchweekResearchRepository(selected_store).replay(qualified.selection).f16_manifest_digest
        == graph.f16
    )


def test_selected_inputs_do_not_discover_later_catalog_history(
    selected_store: Store, graph: Graph
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import SOURCE_MEDIA_TYPE, ModelContractRepository

    row = F16MatchweekProcessor(selected_store).replay_manifest(graph.f16).match_results[0]
    expected = ModelContractRepository(selected_store).replay(
        row.model_digest, row.evidence_digest, row.cutoff_id
    )
    # An unsupported new source would fail loudly if replay enumerated the mutable source catalog.
    ArtifactStore(selected_store).publish_artifact(b"later corrupt source", SOURCE_MEDIA_TYPE)
    assert (
        ModelContractRepository(selected_store)
        .build_from_retained_history(row.evidence_digest, row.cutoff_id)
        .to_bytes()
        == expected.to_bytes()
    )


def test_restart_selected_replay_needs_no_trusted_production_clock(
    selected_store: Store, qualified: Qualified
) -> None:
    path = selected_store.path
    expected = MatchweekResearchRepository(selected_store).replay(qualified.selection)
    selected_store.close()
    with open_store(path, private_root=path.parent) as reopened:
        assert MatchweekResearchRepository(reopened).replay(qualified.selection) == expected


def test_f11_sync_crossing_t_cannot_retain_new_evidence(
    candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    clock = Clock()
    sync = os.fsync

    def crossing_sync(descriptor: int) -> None:
        sync(descriptor)
        clock.value = CUTOFF

    monkeypatch.setattr(os, "fsync", crossing_sync)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        F11EvidenceRepository(candidate_store, clock=clock).build(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest, weather_client=None
        )
    assert candidate_store.artifact_catalog() == before


def test_commit_return_at_t_is_refused_and_late_candidate_cannot_be_adopted(
    candidate: Case, candidate_store: Store
) -> None:
    import sqlite3
    from typing import Any, cast

    from matchvet.f11 import EVIDENCE_MEDIA_TYPE

    clock = Clock()
    connection = candidate_store._connection_for_repository()

    class DelayedCommit:
        def __getattr__(self, name: str) -> Any:
            return getattr(connection, name)

        def commit(self) -> None:
            connection.commit()
            clock.value = CUTOFF

    candidate_store._connection = cast(sqlite3.Connection, DelayedCommit())
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        F11EvidenceRepository(candidate_store, clock=clock).build(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest, weather_client=None
        )
    assert not any(
        row.media_type == EVIDENCE_MEDIA_TYPE for row in candidate_store.artifact_catalog()
    )
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        F11EvidenceRepository(candidate_store, clock=clock).build_or_replay_for_freeze(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
    with pytest.raises(MatchweekResearchError, match="No indexed"):
        MatchweekResearchRepository(candidate_store).replay_for_matchweek(
            season="2026-27", matchweek_friday="2026-09-25"
        )


def test_default_untrusted_time_cannot_authorize_prospective_f15(
    candidate: Case, candidate_store: Store
) -> None:
    with pytest.raises(MatchweekResearchError, match="unavailable"):
        AnalyzeMatchweek(candidate_store).start(candidate.request)


def test_default_f15_and_f16_refuse_new_legacy_candidate_work(
    candidate: Case, candidate_store: Store
) -> None:
    from matchvet.f15 import AnalyzeMatchweekError
    from matchvet.f16 import F16Error
    from matchvet.runs import RunPhase, WorkContext

    cutoffs = MatchEvidenceCutoffRepository(candidate_store)
    legacy = cutoffs.persist_policy(CutoffPolicy("legacy", "issue76", 21600))
    boundaries = cutoffs.persist_for_freeze(candidate.request.freeze_id, legacy)
    request = replace(
        candidate.request,
        cutoff_policy_digest=legacy,
        cutoff_ids=tuple(sorted(row.cutoff_id for row in boundaries)),
    )
    before = candidate_store.artifact_catalog()
    with pytest.raises(AnalyzeMatchweekError, match="corrected"):
        AnalyzeMatchweek(candidate_store, clock=Clock()).start(request)
    context = WorkContext(
        "synthetic",
        "synthetic",
        "2026-09-25",
        RunPhase.PREFERENCE_VETTING,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    with pytest.raises(F16Error, match="corrected"):
        F16MatchweekProcessor(candidate_store, clock=Clock()).process_phase(
            context,
            freeze_id=request.freeze_id,
            cutoff_policy_digest=legacy,
            cutoff_ids=request.cutoff_ids,
            profile_digest=request.preference_profile_digest,
            policy=request.policy,
        )
    assert candidate_store.artifact_catalog() == before


def test_late_unknown_attempt_cannot_replace_selected_weather_or_decision(
    candidate: Case, candidate_store: Store
) -> None:
    from matchvet.f12 import ContextualAttemptRepository, ContextualResearchAttempt, F12Error
    from matchvet.f14 import DecisionRepository
    from matchvet.runs import RunPhase, WorkContext
    from matchvet.weather import (
        StaticWeatherClient,
        VenueLocation,
        WeatherHTTPResponse,
        WeatherRequest,
        WeatherUnavailable,
        build_weather_evidence,
    )
    from matchvet.weather_provider_health import OpenMeteoHealthRecorder

    request = candidate.request
    cutoff = MatchEvidenceCutoffRepository(candidate_store).replay(request.cutoff_ids[0])
    location = VenueLocation(
        "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", BEFORE.isoformat()
    )
    weather_request = WeatherRequest(
        cutoff.fixture_id, "2026-09-25T19:00:00Z", cutoff.cutoff_at_utc, location
    )
    client = StaticWeatherClient(
        {
            weather_request.url: {
                "latitude": 6.5,
                "longitude": 3.4,
                "forecast_issue_time": "2026-09-25T11:00:00Z",
                "hourly": {"time": [weather_request.interval_start_utc], "temperature_2m": [27]},
            }
        },
        retrieved_at_utc=BEFORE.isoformat(),
    )
    evidence = F11EvidenceRepository(candidate_store, clock=Clock()).build(
        request.freeze_id,
        request.cutoff_policy_digest,
        weather_client=client,
        locations={cutoff.fixture_id: location},
    )
    ref = evidence.to_dict()["matches"][0]["contextual_attempt"]
    attempt = ContextualAttemptRepository(candidate_store).get(ref["attempt_id"])
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        ContextualAttemptRepository(candidate_store, clock=Clock(CUTOFF)).publish(attempt)
    assert candidate_store.artifact_catalog() == before
    context = WorkContext(
        "synthetic",
        "synthetic",
        "2026-09-25",
        RunPhase.PREFERENCE_VETTING,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    result = F16MatchweekProcessor(candidate_store, clock=Clock()).process_phase(
        context,
        freeze_id=request.freeze_id,
        cutoff_policy_digest=request.cutoff_policy_digest,
        cutoff_ids=request.cutoff_ids,
        profile_digest=request.preference_profile_digest,
        policy=request.policy,
    )
    selected = MatchweekResearchRepository(candidate_store, clock=Clock()).seal_completed(
        result.result_digest
    )
    row = (
        F16MatchweekProcessor(candidate_store)
        .replay_manifest(selected.f16_manifest_digest)
        .match_results[0]
    )
    decision = DecisionRepository(candidate_store).replay(row.decision_digest)
    assert (
        ContextualAttemptRepository(candidate_store).publish(attempt).to_bytes()
        == attempt.to_bytes()
    )

    class UnavailableClient:
        def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
            raise WeatherUnavailable("separate later audit failure")

    # Standalone F09 auditing has no recommendation authority.
    recorder = OpenMeteoHealthRecorder(
        ProviderHealthRepository(candidate_store),
        clock=lambda: CUTOFF.isoformat(timespec="microseconds"),
    )
    unknown = build_weather_evidence(
        fixture_id=cutoff.fixture_id,
        target_time_utc=weather_request.target_time_utc,
        cutoff_utc=cutoff.cutoff_at_utc,
        location=location,
        client=UnavailableClient(),
        health_recorder=recorder,
    )
    late = ContextualResearchAttempt.create(
        cutoff=cutoff,
        request=weather_request,
        weather=unknown,
        health=recorder.records[0],
        response_artifact_digest=None,
        error_type="WeatherUnavailable",
    )
    with pytest.raises(F12Error, match="selected"):
        ContextualAttemptRepository(candidate_store).publish(late)
    from matchvet.artifacts import ArtifactStore
    from matchvet.f12 import F12_ATTEMPT_MEDIA_TYPE

    # Retain through the generic audit path; it has no selection authority.
    ArtifactStore(candidate_store).publish_artifact(late.to_bytes(), F12_ATTEMPT_MEDIA_TYPE)
    assert (
        ContextualAttemptRepository(candidate_store).publish(attempt).to_bytes()
        == attempt.to_bytes()
    )
    assert MatchweekResearchRepository(candidate_store).replay(selected.digest) == selected
    assert (
        MatchweekResearchRepository(candidate_store).seal_completed(selected.f16_manifest_digest)
        == selected
    )
    assert (
        DecisionRepository(candidate_store).replay(row.decision_digest).to_bytes()
        == decision.to_bytes()
    )
    assert (
        F11EvidenceRepository(candidate_store)
        .build_or_replay_for_freeze(request.freeze_id, request.cutoff_policy_digest)
        .to_bytes()
        == evidence.to_bytes()
    )


@dataclass(frozen=True)
class Case:
    root: Path
    request: AnalyzeMatchweekRequest


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory) -> Case:
    root = tmp_path_factory.mktemp("issue76-candidate")
    with open_store(root / "store.sqlite3", private_root=root) as store:
        freeze = _freeze(store, root)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        boundaries = cutoffs.persist_for_freeze(freeze, policy)
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        request = AnalyzeMatchweekRequest(
            "2026-09-25",
            freeze,
            policy,
            tuple(sorted(row.cutoff_id for row in boundaries)),
            V2_REQUIREMENT_CATALOG.digest,
            engine_version_identity(),
            profile.digest,
            PolicyVersion(version="issue76"),
        )
    return Case(root, request)


@pytest.fixture
def candidate_store(candidate: Case, tmp_path: Path) -> Generator[Store]:
    shutil.copytree(candidate.root / "objects", tmp_path / "objects")
    shutil.copyfile(candidate.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


def test_prospective_corrected_f15_chain_and_selected_resume_after_t(
    candidate: Case, candidate_store: Store
) -> None:
    request = candidate.request
    service = AnalyzeMatchweek(candidate_store, clock=Clock())
    progress = service.start(request)
    identities = F16MatchweekProcessor(candidate_store).completed_artifact_identities(
        freeze_id=request.freeze_id,
        cutoff_policy_digest=request.cutoff_policy_digest,
        profile_digest=request.preference_profile_digest,
        policy=request.policy,
    )
    assert identities, progress.t04_status
    digest = next(
        value.rsplit(":", 1)[1] for value in identities if value.startswith("F16_MANIFEST:")
    )
    selected = MatchweekResearchRepository(candidate_store, clock=Clock()).seal_completed(digest)
    before = candidate_store.artifact_catalog()
    assert (
        AnalyzeMatchweek(candidate_store).resume(progress.run_id, request).durable_result_identities
        == progress.durable_result_identities
    )
    assert MatchweekResearchRepository(candidate_store).replay(selected.digest) == selected
    assert candidate_store.artifact_catalog() == before


@pytest.mark.parametrize("same_repository", [False, True])
def test_model_writer_reentry_cannot_create_an_alternate_frozen_result(
    candidate: Case, candidate_store: Store, same_repository: bool
) -> None:
    from collections.abc import Iterator

    from matchvet.f13 import F13Error, ModelContractRepository
    from matchvet.t09 import HistoricalMatch

    request = candidate.request
    evidence = F11EvidenceRepository(candidate_store, clock=Clock()).build(
        request.freeze_id, request.cutoff_policy_digest, weather_client=None
    )
    repository = ModelContractRepository(candidate_store, clock=Clock())
    results: list[str] = []

    def reenter() -> Iterator[HistoricalMatch]:
        results.append(
            (
                repository
                if same_repository
                else ModelContractRepository(candidate_store, clock=Clock())
            )
            .build(evidence.digest, request.cutoff_ids[0], history=())
            .digest
        )
        yield from ()

    with pytest.raises(F13Error, match="frozen model"):
        repository.build(evidence.digest, request.cutoff_ids[0], history=reenter())
    assert repository.retained_result_digest(evidence.digest, request.cutoff_ids[0]) == results[0]


def test_f15_partial_resume_cannot_execute_a_missing_writer_after_t(
    candidate: Case, candidate_store: Store
) -> None:
    from matchvet.matchweek_research import TrustedUTCUpperBound
    from matchvet.runs import RunPhase

    class InterruptingClock(Clock):
        def observe(self) -> TrustedUTCUpperBound:
            if (
                candidate_store._connection_for_repository()
                .execute("SELECT run_id FROM research_runs")
                .fetchone()
                is not None
            ):
                raise KeyboardInterrupt
            return super().observe()

    progress = AnalyzeMatchweek(candidate_store, clock=InterruptingClock()).start(candidate.request)
    assert progress.phase is RunPhase.PREFLIGHT
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="cutoff"):
        AnalyzeMatchweek(candidate_store, clock=Clock(CUTOFF)).resume(
            progress.run_id, candidate.request
        )
    assert candidate_store.artifact_catalog() == before


def _freeze(store: Store, root: Path) -> str:
    assessment = _persistable_schedule_assessment(
        store, root, (("2026-09-25", "20:00", "Friday United", "Friday City"),)
    )
    FixtureCoverageRepository(store).persist(assessment)
    ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
    return (
        MatchweekMembershipRepository(store, clock=lambda: BEFORE)
        .freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        .freeze_id
    )


def test_direct_f11_acquisition_refuses_cutoff_equality(tmp_path: Path) -> None:
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        cutoffs.persist_for_freeze(freeze, policy)
        before = store.artifact_catalog()
        with pytest.raises(MatchweekResearchError, match="cutoff"):
            F11EvidenceRepository(store, clock=Clock(CUTOFF)).build(
                freeze, policy, weather_client=None
            )
        assert store.artifact_catalog() == before


@pytest.mark.parametrize(
    "phase", ["EVIDENCE_ACQUISITION", "FROZEN_EVIDENCE_STATE", "PREFERENCE_VETTING"]
)
def test_direct_f16_missing_phase_refuses_after_cutoff(tmp_path: Path, phase: str) -> None:
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.f16 import F16MatchweekProcessor
    from matchvet.runs import RunPhase, WorkContext
    from matchvet.t15 import PolicyVersion

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        boundaries = cutoffs.persist_for_freeze(freeze, policy)
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        context = WorkContext(
            "synthetic",
            "synthetic",
            "2026-09-25",
            RunPhase[phase],
            1,
            "RESEARCH_ONLY",
            "0" * 64,
            "0" * 64,
            1,
        )
        before = store.artifact_catalog()
        with pytest.raises(MatchweekResearchError, match="cutoff"):
            F16MatchweekProcessor(store, clock=Clock(CUTOFF)).process_phase(
                context,
                freeze_id=freeze,
                cutoff_policy_digest=policy,
                cutoff_ids=tuple(sorted(row.cutoff_id for row in boundaries)),
                profile_digest=profile.digest,
                policy=PolicyVersion(version="issue76"),
            )
        assert store.artifact_catalog() == before


def test_corrected_f11_request_cannot_change_its_first_frozen_state(tmp_path: Path) -> None:
    from matchvet.f11 import F11Error
    from matchvet.workload import WorkloadRules

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        cutoffs.persist_for_freeze(freeze, policy)
        repository = F11EvidenceRepository(store, clock=Clock())
        first = repository.build(freeze, policy, weather_client=None)
        assert repository.build(freeze, policy, weather_client=None) == first
        with pytest.raises(F11Error, match="request"):
            repository.build(
                freeze, policy, weather_client=None, rules=WorkloadRules(name="changed")
            )


def test_direct_f13_discovery_and_f14_creation_refuse_closed_boundary(tmp_path: Path) -> None:
    from matchvet.f13 import ModelContractRepository
    from matchvet.f14 import DecisionInputBundle, DecisionRepository, PreferenceProfileRepository
    from matchvet.t15 import PolicyVersion

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        evidence = F11EvidenceRepository(store, clock=Clock()).build(
            freeze, policy, weather_client=None
        )
        before = store.artifact_catalog()
        with pytest.raises(MatchweekResearchError, match="cutoff"):
            ModelContractRepository(store, clock=Clock(CUTOFF)).build_from_retained_history(
                evidence.digest, cutoff.cutoff_id
            )
        assert store.artifact_catalog() == before

        model = ModelContractRepository(store, clock=Clock()).build(
            evidence.digest, cutoff.cutoff_id, history=()
        )
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        selection_policy = PolicyVersion(version="issue76")
        bundle = DecisionInputBundle(
            profile.digest,
            evidence.digest,
            cutoff.cutoff_id,
            model.digest,
            {**selection_policy.to_dict(), "policy_digest": selection_policy.digest},
            {},
        )
        before = store.artifact_catalog()
        with pytest.raises(MatchweekResearchError, match="cutoff"):
            DecisionRepository(store, clock=Clock(CUTOFF)).build_decision(bundle)
        assert store.artifact_catalog() == before


@pytest.mark.parametrize("retrieved", [CUTOFF + timedelta(seconds=1), BEFORE - timedelta(hours=2)])
def test_f11_early_publication_never_authorizes_invalid_retrieval(
    tmp_path: Path, retrieved: object
) -> None:
    from datetime import datetime

    from matchvet.f11 import F11Error
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    assert isinstance(retrieved, datetime)
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        freeze = _freeze(store, tmp_path)
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        cutoff = cutoffs.persist_for_freeze(freeze, policy)[0]
        location = VenueLocation(
            "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", BEFORE.isoformat()
        )
        request = WeatherRequest(
            cutoff.fixture_id, "2026-09-25T19:00:00Z", cutoff.cutoff_at_utc, location
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
            retrieved_at_utc=retrieved.isoformat(),
        )
        with pytest.raises(F11Error, match="retriev"):
            F11EvidenceRepository(store, clock=Clock()).build(
                freeze, policy, weather_client=client, locations={cutoff.fixture_id: location}
            )


def test_multimatch_boundary_and_partial_decisions_pin_one_profile_and_policy(
    tmp_path: Path,
) -> None:
    from matchvet.f13 import ModelContractRepository
    from matchvet.f14 import DecisionRepository, F14Error
    from matchvet.f15 import AnalyzeMatchweekError

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (
                ("2026-09-25", "20:00", "Friday United", "Friday City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store, clock=lambda: BEFORE).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue76", "1", 21600, rule=CORRECTED_RULE))
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, policy)
        assert len(boundaries) == 2
        assert len({row.cutoff_at_utc for row in boundaries}) == 1
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        alternate = PreferenceProfileRepository(store).build_profile(("match_winner_away",))
        selection_policy = PolicyVersion(version="issue76")
        request = AnalyzeMatchweekRequest(
            "2026-09-25",
            freeze.freeze_id,
            policy,
            tuple(sorted(row.cutoff_id for row in boundaries)),
            V2_REQUIREMENT_CATALOG.digest,
            engine_version_identity(),
            profile.digest,
            selection_policy,
        )
        # Equal common T does not make distinct policy identities interchangeable.
        other_policy = cutoffs.persist_policy(
            CutoffPolicy("other", "1", 21600, rule=CORRECTED_RULE)
        )
        other = cutoffs.persist_for_freeze(freeze.freeze_id, other_policy)
        mixed = replace(
            request, cutoff_ids=tuple(sorted((boundaries[0].cutoff_id, other[1].cutoff_id)))
        )
        with pytest.raises(AnalyzeMatchweekError, match="policy"):
            AnalyzeMatchweek(store, clock=Clock()).start(mixed)
        incomplete = replace(request, cutoff_ids=(boundaries[0].cutoff_id,))
        with pytest.raises(AnalyzeMatchweekError, match="every INCLUDED"):
            AnalyzeMatchweek(store, clock=Clock()).start(incomplete)
        MatchweekResearchRepository(store, clock=Clock()).require_preselection_open(
            freeze.freeze_id, policy
        )
        evidence = F11EvidenceRepository(store, clock=Clock()).build(
            freeze.freeze_id, policy, weather_client=None
        )
        models = tuple(
            ModelContractRepository(store, clock=Clock()).build(
                evidence.digest, row.cutoff_id, history=()
            )
            for row in boundaries
        )
        bundle = DecisionInputBundle(
            profile.digest,
            evidence.digest,
            boundaries[0].cutoff_id,
            models[0].digest,
            {**selection_policy.to_dict(), "policy_digest": selection_policy.digest},
            {},
        )
        DecisionRepository(store, clock=Clock()).build_decision(bundle)
        second = replace(
            bundle, cutoff_id=boundaries[1].cutoff_id, model_result_digest=models[1].digest
        )
        before = store.artifact_catalog()
        with pytest.raises((F14Error, MatchweekResearchError), match=r"profile|policy"):
            DecisionRepository(store, clock=Clock()).build_decision(
                replace(second, profile_digest=alternate.digest)
            )
        changed = PolicyVersion(version="alternate")
        with pytest.raises((F14Error, MatchweekResearchError), match=r"profile|policy"):
            DecisionRepository(store, clock=Clock()).build_decision(
                replace(second, policy={**changed.to_dict(), "policy_digest": changed.digest})
            )
        assert store.artifact_catalog() == before
        DecisionRepository(store, clock=Clock()).build_decision(second)


def test_partial_weather_attempt_pins_boundary_before_final_f11(
    candidate: Case,
    candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE
    from matchvet.f12 import F12_ATTEMPT_MEDIA_TYPE
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    request = candidate.request
    cutoffs = MatchEvidenceCutoffRepository(candidate_store)
    cutoff = cutoffs.replay(request.cutoff_ids[0])
    location = VenueLocation(
        "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", BEFORE.isoformat()
    )
    weather_request = WeatherRequest(
        cutoff.fixture_id, "2026-09-25T19:00:00Z", cutoff.cutoff_at_utc, location
    )
    client = StaticWeatherClient(
        {
            weather_request.url: {
                "latitude": 6.5,
                "longitude": 3.4,
                "forecast_issue_time": "2026-09-25T11:00:00Z",
                "hourly": {"time": [weather_request.interval_start_utc], "temperature_2m": [27]},
            }
        },
        retrieved_at_utc=BEFORE.isoformat(),
    )
    original = ArtifactStore.publish_artifact

    def fail_final(
        self: ArtifactStore, content: bytes, media_type: str = "application/octet-stream"
    ) -> object:
        if media_type == EVIDENCE_MEDIA_TYPE:
            raise RuntimeError("interrupt before final evidence retention")
        return original(self, content, media_type)

    with monkeypatch.context() as patch:
        patch.setattr(ArtifactStore, "publish_artifact", fail_final)
        with pytest.raises(RuntimeError, match="interrupt"):
            F11EvidenceRepository(candidate_store, clock=Clock()).build(
                request.freeze_id,
                request.cutoff_policy_digest,
                weather_client=client,
                locations={cutoff.fixture_id: location},
            )
    assert any(
        row.media_type == F12_ATTEMPT_MEDIA_TYPE for row in candidate_store.artifact_catalog()
    )
    assert not any(
        row.media_type == EVIDENCE_MEDIA_TYPE for row in candidate_store.artifact_catalog()
    )
    alternate_policy = cutoffs.persist_policy(
        CutoffPolicy("alternate", "1", 21600, rule=CORRECTED_RULE)
    )
    alternate = cutoffs.persist_for_freeze(request.freeze_id, alternate_policy)
    assert alternate[0].cutoff_at_utc == cutoff.cutoff_at_utc
    with pytest.raises(MatchweekResearchError, match="candidate boundary"):
        F11EvidenceRepository(candidate_store, clock=Clock()).build(
            request.freeze_id, alternate_policy, weather_client=None
        )
    freeze = MatchweekMembershipRepository(candidate_store).get_by_id(request.freeze_id)
    assert freeze is not None
    other = MatchweekMembershipRepository(candidate_store, clock=lambda: BEFORE).freeze_exact(
        freeze.season,
        freeze.matchweek_friday,
        freeze.assessment_digest,
        "matchvet:matchweek-membership",
        "2",
    )
    cutoffs.persist_for_freeze(other.freeze_id, request.cutoff_policy_digest)
    with pytest.raises(MatchweekResearchError, match="candidate boundary"):
        F11EvidenceRepository(candidate_store, clock=Clock()).build(
            other.freeze_id, request.cutoff_policy_digest, weather_client=None
        )


def test_later_outcomes_are_excluded_and_closed_discovery_never_consumes_history(
    candidate: Case,
    candidate_store: Store,
) -> None:
    import json
    from collections.abc import Iterator

    from test_t11 import _history

    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import ModelContractRepository
    from matchvet.t09 import HistoricalMatch

    request = candidate.request
    evidence = F11EvidenceRepository(candidate_store, clock=Clock()).build(
        request.freeze_id, request.cutoff_policy_digest, weather_client=None
    )
    repository = ModelContractRepository(candidate_store, clock=Clock())
    future = replace(
        _history()[0],
        fixture_id="later-matchweek-outcome",
        observed_at_utc=(CUTOFF + timedelta(days=2)).isoformat(),
    )
    source = repository.retain_history((future,))
    model = repository.build(evidence.digest, request.cutoff_ids[0], history=source)
    value = model.to_dict()
    snapshot = json.loads(
        ArtifactStore(candidate_store).read_artifact(value["inputs"]["history_snapshot_digest"])
    )
    assert snapshot["history"] == []
    assert value["inputs"]["excluded_history"][0]["fixture_id"] == future.fixture_id
    repository.retain_history((replace(future, fixture_id="even-later-outcome"),))
    assert (
        repository.build_from_retained_history(evidence.digest, request.cutoff_ids[0]).digest
        == model.digest
    )
    consumed = False

    def mutable_history() -> Iterator[HistoricalMatch]:
        nonlocal consumed
        consumed = True
        yield from source

    with pytest.raises(MatchweekResearchError, match="cutoff"):
        ModelContractRepository(candidate_store, clock=Clock(CUTOFF)).build(
            evidence.digest, request.cutoff_ids[0], history=mutable_history()
        )
    assert not consumed


def test_legacy_f15_inspection_survives_corrected_selection_same_matchweek(
    graph: Graph,
    tmp_path: Path,
) -> None:
    shutil.copytree(graph.root / "objects", tmp_path / "objects")
    shutil.copyfile(graph.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        manifest = F16MatchweekProcessor(store).replay_manifest(graph.f16)
        cutoffs = MatchEvidenceCutoffRepository(store)
        legacy_policy = cutoffs.persist_policy(CutoffPolicy("legacy", "1", 21600))
        boundaries = cutoffs.persist_for_freeze(graph.freeze, legacy_policy)
        request = AnalyzeMatchweekRequest(
            "2026-09-25",
            graph.freeze,
            legacy_policy,
            tuple(sorted(row.cutoff_id for row in boundaries)),
            V2_REQUIREMENT_CATALOG.digest,
            engine_version_identity(),
            manifest.to_dict()["profile_digest"],
            PolicyVersion.from_mapping(manifest.to_dict()["policy"]),
        )
        previous = AnalyzeMatchweek(store, legacy_research=True).start(request)
        legacy_identity = next(
            item for item in previous.durable_result_identities if item.startswith("F16_MANIFEST:")
        )
        legacy_manifest = legacy_identity.rsplit(":sha256:", 1)[1]
        retained = F16MatchweekProcessor(store).replay_manifest(legacy_manifest).to_bytes()
        MatchweekResearchRepository(store, clock=Clock()).seal_completed(graph.f16)
        before = store.artifact_catalog()
        inspected = AnalyzeMatchweek(store).inspect(previous.run_id, request)
        assert legacy_identity in inspected.durable_result_identities
        assert inspected.durable_result_identities == previous.durable_result_identities
        assert F16MatchweekProcessor(store).replay_manifest(legacy_manifest).to_bytes() == retained
        assert store.artifact_catalog() == before


def test_partial_f15_run_pins_profile_policy_and_boundary_before_any_writer(
    candidate: Case,
    candidate_store: Store,
) -> None:
    from matchvet.matchweek_research import TrustedUTCUpperBound
    from matchvet.runs import RunPhase, WorkContext

    request = candidate.request
    alternate_profile = PreferenceProfileRepository(candidate_store).build_profile(
        ("match_winner_away",)
    )
    cutoffs = MatchEvidenceCutoffRepository(candidate_store)
    alternate_policy = cutoffs.persist_policy(
        CutoffPolicy("alternate", "1", 21600, rule=CORRECTED_RULE)
    )
    alternate_boundaries = cutoffs.persist_for_freeze(request.freeze_id, alternate_policy)

    class InterruptingClock(Clock):
        def observe(self) -> TrustedUTCUpperBound:
            if (
                candidate_store._connection_for_repository()
                .execute("SELECT run_id FROM research_runs")
                .fetchone()
                is not None
            ):
                raise KeyboardInterrupt
            return super().observe()

    progress = AnalyzeMatchweek(candidate_store, clock=InterruptingClock()).start(request)
    assert progress.phase is RunPhase.PREFLIGHT
    before = candidate_store.artifact_catalog()
    for changed in (
        replace(request, preference_profile_digest=alternate_profile.digest),
        replace(request, policy=PolicyVersion(version="alternate")),
        replace(
            request,
            cutoff_policy_digest=alternate_policy,
            cutoff_ids=tuple(sorted(row.cutoff_id for row in alternate_boundaries)),
        ),
    ):
        with pytest.raises(MatchweekResearchError, match=r"profile|policy|candidate boundary"):
            AnalyzeMatchweek(candidate_store, clock=Clock()).start(changed)
    context = WorkContext(
        "direct",
        "direct",
        request.matchweek,
        RunPhase.FROZEN_EVIDENCE_STATE,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    with pytest.raises(MatchweekResearchError, match="profile"):
        F16MatchweekProcessor(candidate_store, clock=Clock()).process_phase(
            context,
            freeze_id=request.freeze_id,
            cutoff_policy_digest=request.cutoff_policy_digest,
            cutoff_ids=request.cutoff_ids,
            profile_digest=alternate_profile.digest,
            policy=request.policy,
        )
    assert candidate_store.artifact_catalog() == before
    assert (
        AnalyzeMatchweek(candidate_store)
        .inspect(progress.run_id, request)
        .durable_result_identities
        == progress.durable_result_identities
    )

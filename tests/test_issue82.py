from __future__ import annotations

from dataclasses import replace
from typing import Any, Never

import pytest
from issue82_support import Successor
from issue82_support import selected_candidate as selected_candidate
from issue82_support import selected_candidate_store as selected_candidate_store
from issue82_support import successor as successor
from issue82_support import successor_store as successor_store
from issue82_support import weather_candidate as weather_candidate
from issue82_support import weather_store as weather_store
from test_issue76 import Case
from test_issue76 import candidate as candidate
from test_issue76 import candidate_store as candidate_store

from matchvet.artifacts import ArtifactRecord, ArtifactStore
from matchvet.causal_trust import _PROFILE_DIGEST, _Approval, _TrustBundle
from matchvet.causal_witness import _ParsedEvent
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import ModelContractRepository, causal_engine_version_identity
from matchvet.f14 import DecisionInputBundle, DecisionRepository
from matchvet.f15 import AnalyzeMatchweek
from matchvet.f16 import F16MatchweekProcessor
from matchvet.matchweek_research import MatchweekResearchError, MatchweekResearchRepository
from matchvet.runs import RunPhase
from matchvet.store import Store


def descriptor(store: Store, case: Case) -> str:
    return MatchweekResearchRepository(store).publish_candidate(
        freeze_id=case.request.freeze_id,
        policy_digest=case.request.cutoff_policy_digest,
        profile_digest=case.request.preference_profile_digest,
        decision_policy=case.request.policy,
        engine_version=causal_engine_version_identity(),
        witness_profile_digest=_PROFILE_DIGEST,
    )


def test_descriptor_is_immutable_identity_and_does_not_occupy(
    candidate: Case, candidate_store: Store
) -> None:
    owner = MatchweekResearchRepository(candidate_store)
    first = descriptor(candidate_store, candidate)
    request = replace(candidate.request, policy=replace(candidate.request.policy, version="other"))
    second = descriptor(candidate_store, replace(candidate, request=request))
    assert first != second
    for digest in (first, second):
        value = owner.resolve_candidate(digest)
        assert value.contract_version == "matchvet-causal-selection-v2"
        assert value.freeze_id == candidate.request.freeze_id
        assert value.digest == digest
        owner.require_causal_write(digest)
    with pytest.raises(MatchweekResearchError):
        owner.resolve_candidate("0" * 64)


def test_direct_f11_pins_candidate_and_competing_descriptor_refuses(
    candidate: Case, candidate_store: Store
) -> None:
    first = descriptor(candidate_store, candidate)
    second = descriptor(
        candidate_store,
        replace(
            candidate,
            request=replace(
                candidate.request, policy=replace(candidate.request.policy, version="other")
            ),
        ),
    )
    evidence = F11EvidenceRepository(
        candidate_store, candidate_contract_digest=first
    ).build_or_replay_for_freeze(
        candidate.request.freeze_id, candidate.request.cutoff_policy_digest
    )
    assert evidence.to_dict()["candidate_contract_digest"] == first
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="candidate"):
        F11EvidenceRepository(
            candidate_store, candidate_contract_digest=second
        ).build_or_replay_for_freeze(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
    assert candidate_store.artifact_catalog() == before


def test_direct_decision_binds_candidate_and_refuses_missing_constructor_context(
    successor: Successor,
    successor_store: Store,
) -> None:
    import json

    from matchvet.artifacts import ArtifactStore

    manifest = F16MatchweekProcessor(successor_store).replay_manifest(successor.manifest)
    row = manifest.match_results[0]
    result = DecisionRepository(successor_store).replay(row.decision_digest)
    raw = json.loads(
        ArtifactStore(successor_store).read_artifact(result.to_dict()["input_bundle_digest"])
    )
    raw.pop("schema_version")
    bundle = DecisionInputBundle(**raw)
    before = successor_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError):
        DecisionRepository(successor_store).build_decision(bundle)
    assert successor_store.artifact_catalog() == before
    assert result.to_dict()["candidate_contract_digest"] == successor.candidate
    assert result.to_dict()["lineage"]["candidate_contract_digest"] == successor.candidate
    assert (
        DecisionRepository(successor_store, candidate_contract_digest=successor.candidate)
        .build_decision(bundle)
        .to_bytes()
        == result.to_bytes()
    )
    assert successor_store.artifact_catalog() == before


def test_f15_identity_and_real_f16_complete_successor_admission(successor: Successor) -> None:
    graph = successor.graph
    assert graph.candidate_digest == successor.candidate
    references = {ref.digest for ref in graph.references}
    assert {
        successor.manifest,
        graph.freeze_digest,
        graph.profile_digest,
        graph.engine_digest,
        graph.policy_digest,
    } <= references
    assert successor.input_digest
    from matchvet.candidate_primitives import HEALTH_MEDIA_TYPE
    from matchvet.f12 import CAUSAL_F12_ATTEMPT_MEDIA_TYPE

    assert any(ref.media_type == CAUSAL_F12_ATTEMPT_MEDIA_TYPE for ref in graph.references)
    assert any(ref.media_type == HEALTH_MEDIA_TYPE for ref in graph.references)


def test_direct_model_binds_successor_input_result_and_reader_has_no_writer_authority(
    successor: Successor,
    successor_store: Store,
) -> None:
    manifest = F16MatchweekProcessor(successor_store).replay_manifest(successor.manifest)
    row = manifest.match_results[0]
    reader = ModelContractRepository(successor_store)
    model = reader.replay(row.model_digest, row.evidence_digest, row.cutoff_id)
    value = model.to_dict()
    assert value["schema_version"] == 3
    assert value["candidate_contract_digest"] == successor.candidate
    assert value["inputs"]["candidate_contract_digest"] == successor.candidate
    before = successor_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError):
        reader.build_from_retained_history(row.evidence_digest, row.cutoff_id)
    assert successor_store.artifact_catalog() == before


def test_successor_weather_ignores_advisory_retrieval_cutoff() -> None:
    from matchvet.weather import VenueLocation, WeatherRequest, parse_open_meteo_response

    request = WeatherRequest(
        "fixture",
        "2026-09-25T19:00:00Z",
        "2026-09-25T13:00:00Z",
        VenueLocation(
            "venue", "Venue", 6.5, 3.4, "venue", "https://venue.test", "2026-09-20T10:00:00Z"
        ),
    )
    payload = {
        "latitude": 6.5,
        "longitude": 3.4,
        "forecast_issue_time": "2026-09-25T11:00:00Z",
        "hourly": {"time": ["2026-09-25T19:00"], "temperature_2m": [27]},
    }
    for retrieval in ("2026-09-25T12:00:00Z", "2026-10-25T12:00:00Z"):
        weather = parse_open_meteo_response(
            payload,
            request,
            retrieved_at_utc=retrieval,
            selection_contract="matchvet-causal-selection-v2",
        )
        assert weather.state.value == "OBSERVED"
        assert weather.cutoff_eligibility.value == "INDETERMINATE"
        assert weather.freshness.value == "UNKNOWN"
    unknown = parse_open_meteo_response(
        {k: v for k, v in payload.items() if k != "forecast_issue_time"},
        request,
        retrieved_at_utc="2026-09-25T12:00:00Z",
        selection_contract="matchvet-causal-selection-v2",
    )
    assert unknown.state.value == "UNKNOWN"


@pytest.mark.parametrize(
    "stage", ["owner", "f11", "f12", "f13", "f14", "f15", "f16", "weather", "health"]
)
def test_missing_causal_context_refuses_before_side_effects(
    stage: str, candidate_store: Store
) -> None:
    from matchvet.f12 import ContextualAttemptRepository
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import WeatherEvidenceBuilder
    from matchvet.weather_provider_health import OpenMeteoHealthRecorder

    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="explicit"):
        if stage == "weather":
            WeatherEvidenceBuilder(None, selection_contract="matchvet-causal-selection-v2")
        elif stage == "health":
            OpenMeteoHealthRecorder(
                ProviderHealthRepository(candidate_store),
                selection_contract="matchvet-causal-selection-v2",
            )
        else:
            factory = {
                "owner": MatchweekResearchRepository,
                "f11": F11EvidenceRepository,
                "f12": ContextualAttemptRepository,
                "f13": ModelContractRepository,
                "f14": DecisionRepository,
                "f15": AnalyzeMatchweek,
                "f16": F16MatchweekProcessor,
            }[stage]
            factory(candidate_store, selection_contract="matchvet-causal-selection-v2")
    assert candidate_store.artifact_catalog() == before


@pytest.mark.parametrize("phase", list(RunPhase))
def test_each_f16_phase_rejects_changed_descriptor_context_before_publication(
    phase: RunPhase,
    candidate: Case,
    candidate_store: Store,
) -> None:
    from issue82_support import context

    digest = descriptor(candidate_store, candidate)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="context"):
        F16MatchweekProcessor(candidate_store, candidate_contract_digest=digest).process_phase(
            context(candidate.request, phase),
            freeze_id=candidate.request.freeze_id,
            cutoff_policy_digest=candidate.request.cutoff_policy_digest,
            cutoff_ids=candidate.request.cutoff_ids,
            profile_digest="0" * 64,
            policy=candidate.request.policy,
        )
    assert candidate_store.artifact_catalog() == before


def test_direct_f11_validates_before_replay_discovery(
    candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = descriptor(candidate_store, candidate)

    def discovery() -> object:
        raise AssertionError("mutable catalog discovery preceded candidate validation")

    monkeypatch.setattr(candidate_store, "artifact_catalog", discovery)
    with pytest.raises(MatchweekResearchError, match="context"):
        F11EvidenceRepository(
            candidate_store, candidate_contract_digest=digest
        ).build_or_replay_for_freeze("missing-freeze", candidate.request.cutoff_policy_digest)


@pytest.mark.parametrize("kind", ["f11", "f12", "f14"])
def test_old_partial_timing_association_blocks_causal_even_with_vacant_selection(
    kind: str,
    candidate: Case,
    candidate_store: Store,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import canonical
    from matchvet.f11 import EVIDENCE_MEDIA_TYPE
    from matchvet.f12 import F12_ATTEMPT_MEDIA_TYPE
    from matchvet.f14 import DECISION_INPUT_MEDIA_TYPE

    first = descriptor(candidate_store, candidate)
    media, payload = {
        "f11": (
            EVIDENCE_MEDIA_TYPE,
            {
                "schema_version": 3,
                "freeze_id": candidate.request.freeze_id,
                "policy_digest": candidate.request.cutoff_policy_digest,
            },
        ),
        "f12": (
            F12_ATTEMPT_MEDIA_TYPE,
            {"schema_version": 1, "cutoff_id": candidate.request.cutoff_ids[0]},
        ),
        "f14": (
            DECISION_INPUT_MEDIA_TYPE,
            {"schema_version": 2, "cutoff_id": candidate.request.cutoff_ids[0]},
        ),
    }[kind]
    ArtifactStore(candidate_store).publish_artifact(canonical(payload), media)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="cross-version"):
        F11EvidenceRepository(
            candidate_store, candidate_contract_digest=first
        ).build_or_replay_for_freeze(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
    assert candidate_store.artifact_catalog() == before


@pytest.mark.parametrize("association", ["missing", "ambiguous", "unsupported"])
def test_malformed_or_ambiguous_old_association_refuses(
    association: str,
    candidate: Case,
    candidate_store: Store,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import canonical
    from matchvet.f14 import DECISION_INPUT_MEDIA_TYPE

    digest = descriptor(candidate_store, candidate)
    value = {
        "schema_version": 2,
        "cutoff_id": "unknown" if association == "missing" else candidate.request.cutoff_ids[0],
    }
    if association == "ambiguous":
        value["freeze_id"] = "another-freeze"
    media = (
        DECISION_INPUT_MEDIA_TYPE
        if association != "unsupported"
        else DECISION_INPUT_MEDIA_TYPE.replace(".v2", ".v99")
    )
    ArtifactStore(candidate_store).publish_artifact(canonical(value), media)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError):
        MatchweekResearchRepository(candidate_store).require_causal_write(digest)
    assert candidate_store.artifact_catalog() == before


def test_raw_sources_and_descriptors_do_not_occupy(candidate: Case, candidate_store: Store) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import SOURCE_MEDIA_TYPE

    first = descriptor(candidate_store, candidate)
    ArtifactStore(candidate_store).publish_artifact(
        b"reusable raw source primitive", SOURCE_MEDIA_TYPE
    )
    owner = MatchweekResearchRepository(candidate_store)
    owner.require_causal_write(first)
    second = descriptor(
        candidate_store,
        replace(
            candidate,
            request=replace(
                candidate.request, policy=replace(candidate.request.policy, version="second")
            ),
        ),
    )
    owner.require_causal_write(second)


def test_guarded_publication_rechecks_competing_descriptors_and_dormant_historical_writer(
    candidate: Case, candidate_store: Store
) -> None:
    from matchweek_research_support import Clock

    from matchvet.causal_candidate import canonical
    from matchvet.f11 import CAUSAL_HISTORY_MEDIA_TYPE

    first = descriptor(candidate_store, candidate)
    second = descriptor(
        candidate_store,
        replace(
            candidate,
            request=replace(
                candidate.request, policy=replace(candidate.request.policy, version="second")
            ),
        ),
    )
    old = MatchweekResearchRepository(candidate_store, clock=Clock()).candidate_artifacts(
        candidate.request.freeze_id, candidate.request.cutoff_policy_digest
    )

    def guarded(digest: str) -> ArtifactStore:
        return MatchweekResearchRepository(
            candidate_store, candidate_contract_digest=digest
        ).candidate_artifacts(candidate.request.freeze_id, candidate.request.cutoff_policy_digest)

    waiting = guarded(second)
    winner = guarded(first)
    payload = {
        "schema_version": 1,
        "candidate_contract_digest": first,
        "freeze_id": candidate.request.freeze_id,
        "policy_digest": candidate.request.cutoff_policy_digest,
        "history": [],
    }
    winner.publish_artifact(canonical(payload), CAUSAL_HISTORY_MEDIA_TYPE)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="cross-version"):
        waiting.publish_artifact(
            canonical({**payload, "candidate_contract_digest": second}), CAUSAL_HISTORY_MEDIA_TYPE
        )
    with pytest.raises(MatchweekResearchError, match="cross-version"):
        old.publish_artifact(
            b"old publication after causal pin", "application/vnd.matchvet.test-input+json"
        )
    assert candidate_store.artifact_catalog() == before


def test_stored_catalog_reader_context_has_no_writer_authority(
    candidate: Case, candidate_store: Store
) -> None:
    digest = descriptor(candidate_store, candidate)
    with (
        candidate_store._scope_artifact_catalog(frozenset()),
        pytest.raises(MatchweekResearchError, match="reader context"),
    ):
        MatchweekResearchRepository(candidate_store).require_causal_write(digest)


def test_local_clock_never_qualifies_and_advisory_clock_only_vetoes(
    candidate: Case, candidate_store: Store
) -> None:
    from datetime import timedelta

    from matchweek_research_support import CUTOFF, Clock

    digest = descriptor(candidate_store, candidate)
    owner = MatchweekResearchRepository(
        candidate_store, candidate_contract_digest=digest, clock=Clock(CUTOFF + timedelta(days=365))
    )
    assert (
        owner.require_candidate_write(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
        is None
    )
    with pytest.raises(MatchweekResearchError, match="never returns"):
        owner.require_preselection_open(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
    for local in (
        CUTOFF - timedelta(days=365),
        CUTOFF + timedelta(days=365),
        CUTOFF - timedelta(days=1),
    ):
        from functools import partial

        advisory = MatchweekResearchRepository(
            candidate_store, advisory_clock=partial(lambda x: x, local)
        )
        if local >= CUTOFF:
            with pytest.raises(MatchweekResearchError, match="wasted"):
                advisory.require_causal_write(digest)
        else:
            advisory.require_causal_write(digest)
    assert (
        candidate_store._connection_for_repository()
        .execute("SELECT count(*) FROM snapshot_manifests")
        .fetchone()[0]
        == 0
    )


def test_cli_missing_candidate_refuses_before_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from matchvet.cli import main

    def opening(*args: object, **kwargs: object) -> None:
        raise AssertionError("missing context opened a store")

    monkeypatch.setattr("matchvet.causal_candidate_cli.open_store", opening)
    assert (
        main(
            ["run", "2026-09-25", "--selection-contract", "matchvet-causal-selection-v2", "--json"]
        )
        == 1
    )
    assert "MV-CAUSAL-CANDIDATE-REFUSED" in capsys.readouterr().out


def test_direct_f12_binds_constructor_and_reentrant_first_attempt(
    weather_candidate: tuple[Case, str, str], weather_store: Store
) -> None:
    from matchvet.f12 import ContextualAttemptRepository, F12Error

    case, digest, evidence_digest = weather_candidate
    evidence = F11EvidenceRepository(weather_store).replay(
        evidence_digest,
        freeze_id=case.request.freeze_id,
        policy_digest=case.request.cutoff_policy_digest,
    )
    reference = evidence.to_dict()["matches"][0]["contextual_attempt"]
    attempt = ContextualAttemptRepository(weather_store).get(
        reference["attempt_id"], cutoff_id=case.request.cutoff_ids[0]
    )
    assert attempt.candidate_contract_digest == digest
    assert attempt.outcome.value == "SUCCEEDED"
    before = weather_store.artifact_catalog()
    with pytest.raises(F12Error, match="constructor"):
        ContextualAttemptRepository(weather_store).publish(attempt)
    writer = ContextualAttemptRepository(weather_store, candidate_contract_digest=digest)
    assert writer.publish(attempt).to_bytes() == attempt.to_bytes()
    with pytest.raises(ValueError):
        writer.publish(replace(attempt, acquired_at_utc="2026-10-02T12:00:00Z"))
    assert weather_store.artifact_catalog() == before


def test_weather_direct_context_checked_before_acquisition_or_health(
    candidate: Case, candidate_store: Store
) -> None:
    from matchweek_research_support import BEFORE

    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.weather import (
        StaticWeatherClient,
        VenueLocation,
        WeatherEvidenceBuilder,
        WeatherTarget,
    )

    digest = descriptor(candidate_store, candidate)
    client = StaticWeatherClient({})
    location = VenueLocation(
        "stadium", "Stadium", 6.5, 3.4, "venue", "https://venue.test", BEFORE.isoformat()
    )
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="context"):
        WeatherEvidenceBuilder(
            client,
            provider_health_repository=ProviderHealthRepository(candidate_store),
            candidate_contract_digest=digest,
        ).build(
            (
                WeatherTarget(
                    "another-fixture", "2026-09-25T19:00:00Z", "2026-09-25T13:00:00Z", location
                ),
            )
        )
    assert client.calls == []
    assert candidate_store.artifact_catalog() == before
    assert (
        candidate_store._connection_for_repository()
        .execute("SELECT count(*) FROM contextual_provider_health_records")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("old", [False, True])
def test_partial_f15_changed_resume_and_cross_version_refusal(
    old: bool, candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchweek_research_support import Clock

    from matchvet.f15 import _AnalyzeExecutor
    from matchvet.runs import WorkContext, WorkInterrupted, WorkResult

    digest = descriptor(candidate_store, candidate)
    request = (
        candidate.request
        if old
        else replace(
            candidate.request,
            candidate_contract_digest=digest,
            model_version_identity=causal_engine_version_identity(),
        )
    )

    def interrupt(self: _AnalyzeExecutor, context: WorkContext) -> WorkResult:
        raise WorkInterrupted("isolated partial run before any stage")

    with monkeypatch.context() as patch:
        patch.setattr(_AnalyzeExecutor, "__call__", interrupt)
        progress = AnalyzeMatchweek(
            candidate_store,
            clock=Clock() if old else None,
            candidate_contract_digest=None if old else digest,
        ).start(request)
    assert progress.phase is RunPhase.PREFLIGHT
    second = descriptor(
        candidate_store,
        replace(
            candidate,
            request=replace(
                candidate.request, policy=replace(candidate.request.policy, version="other")
            ),
        ),
    )
    changed = replace(
        candidate.request,
        candidate_contract_digest=second,
        model_version_identity=causal_engine_version_identity(),
        policy=replace(candidate.request.policy, version="other"),
    )
    before = candidate_store.artifact_catalog()
    attempts = (
        candidate_store._connection_for_repository()
        .execute("SELECT count(*) FROM run_attempts")
        .fetchone()[0]
    )
    with pytest.raises(ValueError):
        AnalyzeMatchweek(candidate_store, candidate_contract_digest=second).resume(
            progress.run_id, changed
        )
    assert (
        candidate_store._connection_for_repository()
        .execute("SELECT count(*) FROM run_attempts")
        .fetchone()[0]
        == attempts
    )
    with pytest.raises(MatchweekResearchError, match="cross-version"):
        MatchweekResearchRepository(candidate_store).require_causal_write(digest if old else second)
    assert candidate_store.artifact_catalog() == before


def test_exact_f13_partial_input_retry_and_changed_binding_refusal(
    candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.f13 import CAUSAL_BINDING_MEDIA_TYPE

    digest = descriptor(candidate_store, candidate)
    evidence = F11EvidenceRepository(candidate_store, candidate_contract_digest=digest).build(
        candidate.request.freeze_id, candidate.request.cutoff_policy_digest, weather_client=None
    )
    writer = ModelContractRepository(candidate_store, candidate_contract_digest=digest)
    original = ArtifactStore.publish_artifact

    def after_binding(
        self: ArtifactStore,
        content: bytes,
        media_type: str = "application/octet-stream",
        **kwargs: Any,
    ) -> ArtifactRecord:
        result = original(self, content, media_type, **kwargs)
        if media_type == CAUSAL_BINDING_MEDIA_TYPE:
            raise RuntimeError("interrupted after exact input retention")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ArtifactStore, "publish_artifact", after_binding)
        with pytest.raises(RuntimeError, match="interrupted"):
            writer.build(evidence.digest, candidate.request.cutoff_ids[0], history=())
    result = writer.build(evidence.digest, candidate.request.cutoff_ids[0], history=())
    assert result.to_dict()["candidate_contract_digest"] == digest
    before = candidate_store.artifact_catalog()
    with pytest.raises(ValueError, match="frozen"):
        writer.build(evidence.digest, candidate.request.cutoff_ids[0], history=())
    assert candidate_store.artifact_catalog() == before


def test_incomplete_and_mixed_real_successor_graph_refuses(
    successor: Successor, successor_store: Store
) -> None:
    import json

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import canonical
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE

    owner = MatchweekResearchRepository(successor_store)
    raw = json.loads(ArtifactStore(successor_store).read_artifact(successor.manifest))
    for altered in ({**raw, "matches": []}, {**raw, "candidate_contract_digest": "0" * 64}):
        bad = ArtifactStore(successor_store).publish_artifact(
            canonical(altered), CAUSAL_MANIFEST_MEDIA_TYPE
        )
        with pytest.raises(MatchweekResearchError):
            owner._admit_v2(bad.digest)
    with pytest.raises(MatchweekResearchError, match=r"references|graph"):
        owner._admit_v2(successor.manifest, references=successor.graph.references[:-1])


def test_f11_exact_media_schema_pair_and_history_pair_refuses(
    successor: Successor, successor_store: Store
) -> None:
    import json

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import canonical
    from matchvet.f11 import (
        CAUSAL_EVIDENCE_MEDIA_TYPE,
        EVIDENCE_MEDIA_TYPE,
        HISTORY_MEDIA_TYPE,
        F11Error,
    )

    evidence_digest = next(
        r.digest for r in successor.graph.references if r.media_type == CAUSAL_EVIDENCE_MEDIA_TYPE
    )
    artifacts = ArtifactStore(successor_store)
    raw = artifacts.read_artifact(evidence_digest)
    envelope = json.loads(raw)
    # Publish incompatible versions without bypassing the store's immutable metadata.
    for media, schema in ((EVIDENCE_MEDIA_TYPE, 4), (CAUSAL_EVIDENCE_MEDIA_TYPE, 3)):
        altered = {**envelope, "schema_version": schema, "test_mismatch": True}
        bad = artifacts.publish_artifact(canonical(altered), media)
        with pytest.raises(F11Error, match="media/schema"):
            F11EvidenceRepository(successor_store).replay(
                bad.digest,
                freeze_id=successor.request.freeze_id,
                policy_digest=successor.request.cutoff_policy_digest,
            )
    history = json.loads(artifacts.read_artifact(envelope["history_artifact_digest"]))
    bad_history = artifacts.publish_artifact(
        canonical({**history, "test_mismatch": True}), HISTORY_MEDIA_TYPE
    )
    altered = {**envelope, "history_artifact_digest": bad_history.digest}
    bad = artifacts.publish_artifact(canonical(altered), CAUSAL_EVIDENCE_MEDIA_TYPE)
    with pytest.raises(F11Error, match="wrong"):
        F11EvidenceRepository(successor_store).replay(
            bad.digest,
            freeze_id=successor.request.freeze_id,
            policy_digest=successor.request.cutoff_policy_digest,
        )


def test_causal_weather_without_owner_refuses_before_fetch() -> None:
    from matchvet.weather import (
        StaticWeatherClient,
        VenueLocation,
        WeatherEvidenceBuilder,
        WeatherTarget,
    )

    client = StaticWeatherClient({})
    target = WeatherTarget(
        "fixture",
        "2026-09-25T19:00:00Z",
        "2026-09-25T13:00:00Z",
        VenueLocation(
            "venue", "Venue", 6.5, 3.4, "venue", "https://venue.test", "2026-09-20T10:00:00Z"
        ),
    )
    with pytest.raises(MatchweekResearchError):
        WeatherEvidenceBuilder(client, candidate_contract_digest="0" * 64).build((target,))
    assert client.calls == []


def test_exact_history_query_accepts_large_immutable_history() -> None:
    import sqlite3

    from matchvet.workload import _exact_revision_query

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE revisions(fixture TEXT, revision TEXT, digest TEXT)")
        rows = [(f"fixture-{i}", f"revision-{i}", f"digest-{i}") for i in range(1500)]
        connection.executemany("INSERT INTO revisions VALUES (?, ?, ?)", rows)
        predicate, parameters = _exact_revision_query(
            frozenset(rows), ("fixture", "revision", "digest")
        )
        assert connection.execute(
            "SELECT count(*) FROM revisions WHERE 1" + predicate, parameters
        ).fetchone()[0] == len(rows)
    finally:
        connection.close()


def test_causal_decision_missing_dependencies_does_not_pin_input(
    candidate: Case, candidate_store: Store
) -> None:
    digest = descriptor(candidate_store, candidate)
    bundle = DecisionInputBundle(
        candidate.request.preference_profile_digest,
        "0" * 64,
        candidate.request.cutoff_ids[0],
        "1" * 64,
        {**candidate.request.policy.to_dict(), "policy_digest": candidate.request.policy.digest},
        {},
        candidate_contract_digest=digest,
    )
    before = candidate_store.artifact_catalog()
    with pytest.raises(ValueError):
        DecisionRepository(candidate_store, candidate_contract_digest=digest).build_decision(bundle)
    assert candidate_store.artifact_catalog() == before


def test_selected_or_terminal_slot_allows_exact_replay_and_refuses_new_graph(
    selected_candidate: tuple[Successor, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from datetime import datetime, timedelta

    from causal_selection_support import approval, trust
    from issue82_support import context

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_witness import _ParsedEvent
    from matchvet.f11 import CAUSAL_EVIDENCE_MEDIA_TYPE
    from matchvet.f13 import SOURCE_MEDIA_TYPE
    from matchvet.runs import WorkInterrupted

    case, selection, qualified = selected_candidate
    cutoff = datetime.fromisoformat(case.graph.cutoff)

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
        return _ParsedEvent(
            response,
            imprint,
            nonce,
            (cutoff - timedelta(seconds=3)).isoformat(timespec="microseconds"),
            (cutoff - timedelta(seconds=1)).isoformat(timespec="microseconds"),
            (cutoff - timedelta(seconds=2)).strftime("%Y%m%d%H%M%SZ"),
        )

    monkeypatch.setattr("matchvet.causal_witness._verify_event", verify)
    monkeypatch.setattr("matchvet.causal_selection._load_approval", lambda s: (approval(), trust()))

    def transport(*args: object) -> Never:
        raise AssertionError("selected inspection/replay requested another witness")

    monkeypatch.setattr("matchvet.causal_witness._post", transport)
    artifacts = ArtifactStore(selected_candidate_store)
    # A later unassociated source must not affect exact selected discovery.
    artifacts.publish_artifact(b"later malformed raw history", SOURCE_MEDIA_TYPE)
    row = (
        F16MatchweekProcessor(selected_candidate_store)
        .replay_manifest(case.manifest)
        .match_results[0]
    )
    raw = json.loads(artifacts.read_artifact(row.decision_digest))
    bundle_raw = json.loads(artifacts.read_artifact(raw["input_bundle_digest"]))
    bundle_raw.pop("schema_version")
    bundle = DecisionInputBundle(**bundle_raw)
    before = selected_candidate_store.artifact_catalog()
    owner = MatchweekResearchRepository(selected_candidate_store)
    with pytest.raises(MatchweekResearchError, match="explicit candidate context"):
        owner.selected_for_boundary(case.request.freeze_id, case.request.cutoff_policy_digest)
    assert owner.inspect_causal(selection).f16_manifest_digest == case.manifest
    f11 = F11EvidenceRepository(selected_candidate_store, candidate_contract_digest=case.candidate)
    assert (
        f11.build_or_replay_for_freeze(
            case.request.freeze_id, case.request.cutoff_policy_digest
        ).digest
        == row.evidence_digest
    )
    assert (
        ModelContractRepository(selected_candidate_store, candidate_contract_digest=case.candidate)
        .build_from_retained_history(row.evidence_digest, row.cutoff_id)
        .digest
        == row.model_digest
    )
    assert (
        DecisionRepository(selected_candidate_store, candidate_contract_digest=case.candidate)
        .build_or_replay_decision(bundle)
        .digest
        == row.decision_digest
    )
    processor = F16MatchweekProcessor(
        selected_candidate_store, candidate_contract_digest=case.candidate
    )
    assert (
        processor.process_phase(
            context(case.request, RunPhase.PREFERENCE_VETTING),
            freeze_id=case.request.freeze_id,
            cutoff_policy_digest=case.request.cutoff_policy_digest,
            cutoff_ids=case.request.cutoff_ids,
            profile_digest=case.request.preference_profile_digest,
            policy=case.request.policy,
        ).result_digest
        == case.manifest
    )
    with pytest.raises(WorkInterrupted):
        processor.process_phase(
            context(case.request, RunPhase.AUDIT_VERIFICATION),
            freeze_id=case.request.freeze_id,
            cutoff_policy_digest=case.request.cutoff_policy_digest,
            cutoff_ids=case.request.cutoff_ids,
            profile_digest=case.request.preference_profile_digest,
            policy=case.request.policy,
        )
    from matchvet.f11 import F11Error
    from matchvet.workload import WorkloadRules

    with pytest.raises(F11Error, match="request"):
        f11.build(
            case.request.freeze_id,
            case.request.cutoff_policy_digest,
            weather_client=None,
            rules=WorkloadRules(name="alternate"),
        )
    for action in (
        lambda: ModelContractRepository(
            selected_candidate_store, candidate_contract_digest=case.candidate
        ).build(row.evidence_digest, row.cutoff_id, history=()),
        lambda: DecisionRepository(
            selected_candidate_store, candidate_contract_digest=case.candidate
        ).build_decision(bundle),
    ):
        with pytest.raises(MatchweekResearchError, match="occupied"):
            action()
    progress = AnalyzeMatchweek(
        selected_candidate_store, candidate_contract_digest=case.candidate
    ).resume(case.run_id, case.request)
    assert progress.run_id == case.run_id
    assert selected_candidate_store.artifact_catalog() == before
    assert row.evidence_digest in {
        r.digest for r in case.graph.references if r.media_type == CAUSAL_EVIDENCE_MEDIA_TYPE
    }
    assert qualified == bool(owner.inspect_causal(selection).completion_receipt_digest)


def test_public_weather_causal_entry_requires_owner_before_fetch() -> None:
    from matchvet.weather import StaticWeatherClient, VenueLocation, build_weather_evidence

    client = StaticWeatherClient({})
    with pytest.raises(MatchweekResearchError, match="owner"):
        build_weather_evidence(
            fixture_id="fixture",
            target_time_utc="2026-09-25T19:00:00Z",
            cutoff_utc="2026-09-25T13:00:00Z",
            location=VenueLocation(
                "venue", "Venue", 6.5, 3.4, "venue", "https://venue.test", "2026-09-20T10:00:00Z"
            ),
            client=client,
            selection_contract="matchvet-causal-selection-v2",
        )
    assert client.calls == []


def test_inside_transaction_candidate_mismatch_rolls_back_pin(
    candidate: Case, candidate_store: Store
) -> None:
    from matchvet.artifacts import ArtifactError
    from matchvet.causal_candidate import canonical
    from matchvet.f11 import CAUSAL_HISTORY_MEDIA_TYPE

    first = descriptor(candidate_store, candidate)
    second = descriptor(
        candidate_store,
        replace(
            candidate,
            request=replace(
                candidate.request, policy=replace(candidate.request.policy, version="other")
            ),
        ),
    )
    owner = MatchweekResearchRepository(candidate_store, candidate_contract_digest=first)
    artifacts = owner.candidate_artifacts(
        candidate.request.freeze_id, candidate.request.cutoff_policy_digest
    )
    calls: list[bool] = []
    original = artifacts._write_guard
    assert original is not None

    def guard() -> object:
        calls.append(candidate_store._connection_for_repository().in_transaction)
        return original()

    artifacts._write_guard = guard
    before = candidate_store.artifact_catalog()
    wrong = {
        "schema_version": 1,
        "candidate_contract_digest": second,
        "freeze_id": candidate.request.freeze_id,
        "policy_digest": candidate.request.cutoff_policy_digest,
        "history": [],
    }
    with pytest.raises(ArtifactError, match="catalog publication"):
        artifacts.publish_artifact(canonical(wrong), CAUSAL_HISTORY_MEDIA_TYPE)
    assert calls == [False, False, True]
    assert candidate_store.artifact_catalog() == before
    owner.require_causal_write(first)
    owner.require_causal_write(second)


def test_legacy_f11_publication_cannot_cross_a_causal_pin(
    candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.causal_candidate import canonical
    from matchvet.f11 import CAUSAL_HISTORY_MEDIA_TYPE, EVIDENCE_MEDIA_TYPE
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository

    digest = descriptor(candidate_store, candidate)
    cutoffs = MatchEvidenceCutoffRepository(candidate_store)
    old_policy = cutoffs.persist_policy(CutoffPolicy("legacy", "1", 21600))
    cutoffs.persist_for_freeze(candidate.request.freeze_id, old_policy)
    winner = MatchweekResearchRepository(
        candidate_store, candidate_contract_digest=digest
    ).candidate_artifacts(candidate.request.freeze_id, candidate.request.cutoff_policy_digest)
    payload = {
        "schema_version": 1,
        "candidate_contract_digest": digest,
        "freeze_id": candidate.request.freeze_id,
        "policy_digest": candidate.request.cutoff_policy_digest,
        "history": [],
    }
    original = ArtifactStore._publish_object
    switched = False

    def during_publication(self: ArtifactStore, content: bytes, record: ArtifactRecord) -> None:
        nonlocal switched
        original(self, content, record)
        if record.media_type == EVIDENCE_MEDIA_TYPE and not switched:
            switched = True
            winner.publish_artifact(canonical(payload), CAUSAL_HISTORY_MEDIA_TYPE)

    monkeypatch.setattr(ArtifactStore, "_publish_object", during_publication)
    with pytest.raises(MatchweekResearchError, match="cross-version"):
        F11EvidenceRepository(candidate_store).build(
            candidate.request.freeze_id, old_policy, weather_client=None
        )
    assert switched
    assert not any(r.media_type == EVIDENCE_MEDIA_TYPE for r in candidate_store.artifact_catalog())
    assert (
        sum(r.media_type == CAUSAL_HISTORY_MEDIA_TYPE for r in candidate_store.artifact_catalog())
        == 1
    )


def test_causal_graph_replay_through_read_only_connection(
    successor: Successor, successor_store: Store
) -> None:
    from matchvet.store import StoreMode

    connection = successor_store._connection_for_repository()
    connection.execute("PRAGMA query_only = ON")
    successor_store.status = replace(successor_store.status, mode=StoreMode.READ_ONLY_RECOVERY)
    manifest = F16MatchweekProcessor(successor_store).replay_manifest(successor.manifest)
    assert manifest.digest == successor.manifest
    assert (
        MatchweekResearchRepository(successor_store)._admit_v2(successor.manifest).references
        == successor.graph.references
    )


def test_causal_selected_lookup_requires_caller_context_before_replay(
    candidate: Case, candidate_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from matchvet.artifacts import ManifestVersion
    from matchvet.causal_selection import _version_v2

    owner = MatchweekResearchRepository(candidate_store)
    # Only the indexed version is needed for this rejection; no graph may be replayed.
    monkeypatch.setattr(
        candidate_store, "snapshot_manifest_digest_for_snapshot", lambda slot: "0" * 64
    )
    monkeypatch.setattr(
        owner._artifacts,
        "verify_manifest",
        lambda digest: SimpleNamespace(
            versions=(ManifestVersion.from_identity(_version_v2("selection")),)
        ),
    )

    def replay(digest: str) -> Never:
        raise AssertionError("stored selection reached replay without caller candidate context")

    monkeypatch.setattr(owner, "replay", replay)
    before = candidate_store.artifact_catalog()
    with pytest.raises(MatchweekResearchError, match="explicit candidate context"):
        owner.selected_for_boundary(
            candidate.request.freeze_id, candidate.request.cutoff_policy_digest
        )
    assert candidate_store.artifact_catalog() == before


def test_retained_history_reads_without_schedule_writer_authority(
    candidate: Case, candidate_store: Store
) -> None:
    from matchvet.store import StoreMode
    from matchvet.workload import WorkloadScheduleRecorder, load_canonical_fixture_history

    history = load_canonical_fixture_history(candidate_store)
    assert history
    schedule = replace(
        history[0],
        fixture_id="offline-cup-context",
        competition_key="offline-cup",
        competition_name="Offline cup",
        competition_type="DOMESTIC_CUP",
    )
    WorkloadScheduleRecorder(candidate_store).record(schedule)
    history = load_canonical_fixture_history(candidate_store)
    recorded = tuple(f for f in history if f.fixture_id == "offline-cup-context")
    assert len(recorded) == 1
    assert recorded[0].competition_key == "offline-cup"
    assert recorded[0].competition_type == "DOMESTIC_CUP"
    assert recorded[0].provenance == schedule.provenance
    retained = frozenset((f.fixture_id, f.revision_id, f.revision_digest) for f in history)
    before = candidate_store.artifact_catalog()
    candidate_store._connection_for_repository().execute("PRAGMA query_only = ON")
    candidate_store.status = replace(candidate_store.status, mode=StoreMode.READ_ONLY_RECOVERY)
    with pytest.raises(PermissionError, match="writable store"):
        WorkloadScheduleRecorder(candidate_store)
    assert load_canonical_fixture_history(candidate_store, exact_revisions=retained) == history
    assert candidate_store.artifact_catalog() == before

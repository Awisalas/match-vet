from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from issue84_support import (
    _next_friday_with_future_cutoff,
    _synthetic_rows,
    install_synthetic_authority,
    synthetic_authority,
    synthetic_timestamp_response,
)
from matchweek_research_support import Clock
from membership_policy3_support import _six_scope_assessment
from source_authorization_support import SourceOwner, graph_manifest, outcome_manifest
from test_matchweek_membership import _persistable_schedule_assessment
from test_research_capture import authority as authority
from test_research_capture import selected_case as selected_case
from test_research_capture import selected_source as selected_source
from test_research_capture import successor_week as successor_week

from matchvet.artifacts import ArtifactStore
from matchvet.candidate_support import SupportState
from matchvet.causal_candidate import CANDIDATE_V2_MEDIA_TYPE
from matchvet.causal_selection import _WitnessAttempt
from matchvet.causal_trust import _PROFILE_DIGEST
from matchvet.f10 import V2_REQUIREMENT_CATALOG
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import causal_engine_version_identity
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE, F16MatchweekProcessor
from matchvet.f19 import SUCCESSOR_SETTLEMENT_MEDIA_TYPE, F19Error, SettlementRepository
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership import MatchweekMembershipFreeze, canonical_json
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    CORRECTED_RULE,
    MatchweekResearchError,
    MatchweekResearchRepository,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.research_capture import (
    CAPTURE_V3_MEDIA_TYPE,
    CaptureError,
    CaptureState,
    ResearchCaptureRepository,
)
from matchvet.research_successor import (
    SIX_SCOPE_COHORT_MEDIA_TYPE,
    publish_six_scope_cohort,
    six_scope_binding,
    six_scope_cohort_digest,
)
from matchvet.store import open_store
from matchvet.t10 import SettlementEvidence
from matchvet.t15 import PolicyVersion
from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

_ORIGINAL_WITNESS_EVIDENCE = _WitnessAttempt._evidence
_ORIGINAL_INSPECT_CAUSAL = MatchweekResearchRepository.inspect_causal
_ORIGINAL_CAPTURE_BASE_VALUE = ResearchCaptureRepository._base_value


@dataclass(frozen=True)
class SixScopeGraph:
    root: Path
    friday: str
    freeze_id: str
    freeze_digest: str
    profile_digest: str
    cutoff_policy_digest: str
    f16_manifest_digest: str
    candidate_digest: str
    cohort_digest: str
    common_cutoff_utc: str
    included_membership_ids: tuple[str, ...]
    excluded_membership_ids: tuple[str, ...]
    freeze: MatchweekMembershipFreeze


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Issue #100 tests forbid network access.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="module")
def six_scope_graph(tmp_path_factory: pytest.TempPathFactory) -> SixScopeGraph:
    reused_root = os.environ.get("MATCHVET_ISSUE100_REUSE_ROOT")
    if reused_root is not None:
        root = Path(reused_root)
        with open_store(root / "store.sqlite3", private_root=root) as store:
            candidates = [
                item.digest
                for item in store.artifact_catalog()
                if item.media_type == CANDIDATE_V2_MEDIA_TYPE
            ]
            manifests = [
                item.digest
                for item in store.artifact_catalog()
                if item.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
            ]
            assert len(candidates) == len(manifests) == 1
            candidate = MatchweekResearchRepository(store).resolve_candidate(candidates[0])
            freeze = MatchweekMembershipRepository(store).get_by_id(candidate.freeze_id)
            assert freeze is not None
            included_ids = tuple(
                sorted(
                    item.membership_id
                    for item in freeze.memberships
                    if item.decision.value == "INCLUDED"
                )
            )
            excluded_ids = tuple(
                sorted(
                    item.membership_id
                    for item in freeze.memberships
                    if item.decision.value != "INCLUDED"
                )
            )
            assert candidate.cohort_descriptor_digest is not None
            return SixScopeGraph(
                root,
                freeze.matchweek_friday,
                freeze.freeze_id,
                freeze.freeze_digest,
                candidate.profile_digest,
                candidate.cutoff_policy_digest,
                manifests[0],
                candidates[0],
                candidate.cohort_descriptor_digest,
                candidate.cutoff_at_utc,
                included_ids,
                excluded_ids,
                freeze,
            )

    root = tmp_path_factory.mktemp("issue100-six-scope")
    now = datetime.now(UTC)
    friday = _next_friday_with_future_cutoff(now) + timedelta(days=7)
    friday_text = friday.isoformat()
    rows_by_league = _synthetic_rows(friday)
    rows_by_league["serie_a"] = (
        rows_by_league["serie_a"][0],
        (
            (friday + timedelta(days=4)).isoformat(),
            "12:00",
            "Issue100 outside home",
            "Issue100 outside away",
        ),
    )
    rows_by_league["premier_league"] = ()

    with open_store(root / "store.sqlite3", private_root=root) as store:
        legacy_assessment = _persistable_schedule_assessment(
            store,
            root,
            (),
            matchweek_friday=friday_text,
            rows_by_league=rows_by_league,
        )
        assessment = _six_scope_assessment(legacy_assessment)
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store, clock=lambda: now).freeze_exact(
            "2026-27",
            friday_text,
            assessment.digest,
            "matchvet:matchweek-membership",
            "3",
        )
        assert freeze.policy.policy_version == "3"
        assert len(freeze.scopes) == 6
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy_digest = cutoffs.persist_policy(
            CutoffPolicy("issue100-six-scope", "1", 21600, rule=CORRECTED_RULE)
        )
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, cutoff_policy_digest)
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        policy = PolicyVersion(version="issue100-six-scope")
        cohort_digest = publish_six_scope_cohort(store)
        owner = MatchweekResearchRepository(store)
        candidate_digest = owner.publish_successor_six_scope_candidate(
            freeze_id=freeze.freeze_id,
            policy_digest=cutoff_policy_digest,
            profile_digest=profile.digest,
            decision_policy=policy,
            engine_version=causal_engine_version_identity(),
            witness_profile_digest=_PROFILE_DIGEST,
            cohort_descriptor_digest=cohort_digest,
        )
        freeze = MatchweekMembershipRepository(store).get_by_id(freeze.freeze_id)
        assert freeze is not None
        members = {item.membership_id: item for item in freeze.memberships}
        locations: dict[str, VenueLocation] = {}
        responses: dict[str, dict[str, object]] = {}
        for boundary in boundaries:
            member = members[boundary.membership_id]
            kickoff = member.controlling_revision.kickoff_utc
            assert kickoff is not None
            venue = VenueLocation(
                "issue100-" + member.fixture_id,
                "Issue100 synthetic stadium",
                6.5,
                3.4,
                "synthetic-fixture",
                "https://venue.test/issue100",
                "2026-09-16T12:00:00Z",
            )
            weather_request = WeatherRequest(
                member.fixture_id, kickoff, boundary.cutoff_at_utc, venue
            )
            locations[member.fixture_id] = venue
            issue_time = datetime.fromisoformat(boundary.cutoff_at_utc) - timedelta(hours=1)
            responses[weather_request.url] = {
                "latitude": venue.latitude,
                "longitude": venue.longitude,
                "forecast_issue_time": issue_time.isoformat().replace("+00:00", "Z"),
                "hourly": {
                    "time": [weather_request.interval_start_utc],
                    "temperature_2m": [26],
                },
            }
        weather_client = StaticWeatherClient(responses, retrieved_at_utc="2026-09-16T12:00:00Z")
        F11EvidenceRepository(store, candidate_contract_digest=candidate_digest).build(
            freeze.freeze_id,
            cutoff_policy_digest,
            weather_client=weather_client,
            locations=locations,
        )
        request = AnalyzeMatchweekRequest(
            friday_text,
            freeze.freeze_id,
            cutoff_policy_digest,
            tuple(sorted(item.cutoff_id for item in boundaries)),
            V2_REQUIREMENT_CATALOG.digest,
            causal_engine_version_identity(),
            profile.digest,
            policy,
            candidate_digest,
        )
        progress = AnalyzeMatchweek(store, candidate_contract_digest=candidate_digest).start(
            request
        )
        assert progress.analysis_state == "F16_COMPLETE_AWAITING_F17"
        manifests = [
            item.digest
            for item in store.artifact_catalog()
            if item.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(manifests) == 1
        included_ids = tuple(
            sorted(
                item.membership_id
                for item in freeze.memberships
                if item.decision.value == "INCLUDED"
            )
        )
        excluded_ids = tuple(
            sorted(
                item.membership_id
                for item in freeze.memberships
                if item.decision.value != "INCLUDED"
            )
        )
        assert included_ids and excluded_ids
        snapshot_root = os.environ.get("MATCHVET_ISSUE100_SNAPSHOT_ROOT")
        if snapshot_root is not None:
            from issue84_support import copy_store

            destination = Path(snapshot_root)
            if destination.exists():
                raise AssertionError("Issue #100 snapshot destination must be new.")
            store._connection_for_repository().execute("PRAGMA wal_checkpoint(TRUNCATE)")
            copy_store(root, destination)
            root = destination
        return SixScopeGraph(
            root,
            friday_text,
            freeze.freeze_id,
            freeze.freeze_digest,
            profile.digest,
            cutoff_policy_digest,
            manifests[0],
            candidate_digest,
            cohort_digest,
            boundaries[0].cutoff_at_utc,
            included_ids,
            excluded_ids,
            freeze,
        )


def test_six_scope_integrated_path_and_exact_offline_replay(
    six_scope_graph: SixScopeGraph,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.cb01 import BootstrapRepository
    from matchvet.cb01_evaluation import CB01EvaluationError, MatchweekEvaluationRepository

    destination = tmp_path / "mixed-six-store"
    from issue84_support import copy_store

    copy_store(six_scope_graph.root, destination)
    authority = synthetic_authority(tmp_path / "issue100-authority")
    install_synthetic_authority(monkeypatch, authority)
    cutoff = datetime.fromisoformat(six_scope_graph.common_cutoff_utc)

    with open_store(destination / "store.sqlite3", private_root=destination) as store:
        # The fixture loaded this immutable F06 payload from the byte-identical
        # source Store. Reuse it for the repeated downstream joins in this test.
        validated_freeze = six_scope_graph.freeze
        assert validated_freeze.freeze_digest == six_scope_graph.freeze_digest
        original_get_by_id = MatchweekMembershipRepository.get_by_id

        def get_validated_freeze(
            repository: MatchweekMembershipRepository, requested_freeze_id: str
        ) -> MatchweekMembershipFreeze | None:
            if requested_freeze_id == validated_freeze.freeze_id:
                return validated_freeze
            return original_get_by_id(repository, requested_freeze_id)

        monkeypatch.setattr(MatchweekMembershipRepository, "get_by_id", get_validated_freeze)
        from matchvet.provider_health import ProviderHealthRecord
        from matchvet.provider_health import (
            provider_health_record_from_canonical_json as decode_provider_health,
        )

        validated_health: dict[str, ProviderHealthRecord] = {}

        def decode_validated_health(encoded: str) -> ProviderHealthRecord:
            record = validated_health.get(encoded)
            if record is None:
                record = decode_provider_health(encoded)
                validated_health[encoded] = record
            return record

        # The F05 decoder is pure and its records are frozen. Reuse only exact
        # canonical payload decodes across repeated F06/F16 joins in this Store.
        monkeypatch.setattr(
            "matchvet.provider_health_repository.provider_health_record_from_canonical_json",
            decode_validated_health,
        )

        def deliver(attempt: Any) -> bytes:
            request = attempt._start_transport()
            return synthetic_timestamp_response(request, authority, cutoff - timedelta(minutes=10))

        monkeypatch.setattr("matchvet.causal_witness._post", deliver)
        owner = MatchweekResearchRepository(
            store,
            clock=Clock(cutoff - timedelta(seconds=1)),
            candidate_contract_digest=six_scope_graph.candidate_digest,
        )
        selected = owner.seal_completed_v2(six_scope_graph.f16_manifest_digest)
        candidate = owner.resolve_candidate(six_scope_graph.candidate_digest)
        assert candidate.is_successor_six_scope
        assert candidate.scope_identity_value() == six_scope_binding() | {
            "cohort_descriptor_digest": six_scope_graph.cohort_digest
        }
        f16_value = json.loads(
            ArtifactStore(store).read_artifact(six_scope_graph.f16_manifest_digest)
        )
        assert all(
            f16_value[key] == expected for key, expected in candidate.scope_identity_value().items()
        )
        selection = ArtifactStore(store).verify_manifest(selected.digest)
        assert six_scope_graph.cohort_digest in {item.digest for item in selection.artifacts}
        receipt = ArtifactStore(store).verify_manifest(selected.completion_receipt_digest)
        provenance_ref = next(
            item
            for item in receipt.artifacts
            if item.media_type == "application/vnd.matchvet.causal-selection-witness.v1+json"
        )
        provenance = json.loads(ArtifactStore(store).read_artifact(provenance_ref.digest))
        binding = json.loads(ArtifactStore(store).read_artifact(provenance["evidence"]["binding"]))
        assert all(
            binding[key] == expected for key, expected in candidate.scope_identity_value().items()
        )

        capture = ResearchCaptureRepository(store)
        with pytest.raises(CaptureError, match="candidate scope contract"):
            capture.capture_week(selected.digest)
        initial = capture.capture_successor_week(selected.digest)
        initial_value = initial.to_dict()
        assert initial_value["schema_version"] == 3
        assert initial_value["contract"] == "research-capture-index-v3"
        assert initial_value["denominator"]["row_count"] == (
            len(six_scope_graph.included_membership_ids)
            + len(six_scope_graph.excluded_membership_ids)
        )
        assert initial_value["denominator"]["statistical_row_count"] == len(
            six_scope_graph.included_membership_ids
        )
        assert {
            row["capture_state"]
            for row in initial_value["denominator_rows"]
            if row["membership_state"] == "INCLUDED"
        } == {CaptureState.UNATTEMPTED.value}
        assert {
            row["capture_state"]
            for row in initial_value["denominator_rows"]
            if row["membership_state"] == "EXCLUDED"
        } == {CaptureState.EXCLUDED.value}
        assert all(
            row["candidate_input"]["state"] == SupportState.UNKNOWN.value
            for row in initial_value["denominator_rows"]
        )
        assert initial_value["population"]["correlation_groups"] == [
            "logical_matchweek_id",
            "fixture_id",
        ]
        assert initial_value["population"]["scope_subgroups"]
        tampered_index = json.loads(initial.to_bytes())
        tampered_index["active_scope_identity"]["active_scope_digest"] = "0" * 64
        forged_index = ArtifactStore(store).publish_artifact(
            canonical_json(tampered_index).encode(),
            CAPTURE_V3_MEDIA_TYPE,
            retention_class="PROTECTED",
        )
        with pytest.raises(CaptureError):
            capture.replay(forged_index.digest)

        evaluation = MatchweekEvaluationRepository(store).inspect_successor_cohort(
            six_scope_graph.freeze_digest,
            six_scope_graph.profile_digest,
            six_scope_graph.cutoff_policy_digest,
            selection_digest=selected.digest,
        )
        expected_full = len(six_scope_graph.included_membership_ids) + len(
            six_scope_graph.excluded_membership_ids
        )
        assert evaluation.cohort == "PROSPECTIVE_SIX_SCOPE_RESEARCH_ONLY"
        assert len(evaluation.denominator.rows) == expected_full
        assert evaluation.included_count == len(six_scope_graph.included_membership_ids)
        assert evaluation.population_metadata is not None
        assert evaluation.population_metadata["audit_pair_count"] == expected_full
        assert evaluation.population_metadata["statistical_pair_count"] == len(
            six_scope_graph.included_membership_ids
        )
        with pytest.raises(CB01EvaluationError, match="candidate contract"):
            MatchweekEvaluationRepository(store).inspect_cohort(
                six_scope_graph.freeze_digest,
                six_scope_graph.profile_digest,
                six_scope_graph.cutoff_policy_digest,
                selection_digest=selected.digest,
            )

        monkeypatch.setattr(
            "matchvet.causal_witness._post",
            lambda *_args, **_kwargs: pytest.fail("Offline replay requested a new witness."),
        )
        missing_authority_backend = DeterministicWitnessBackend(
            transport_states=("UNAVAILABLE", "RECEIVED"),
            gen_time_utc=(cutoff + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        )
        bootstrap = BootstrapRepository(store, witness_backend=missing_authority_backend)
        source_manifest = graph_manifest(store, selected.digest)
        source_owner = SourceOwner(tmp_path / "issue100-source-owner", store, monkeypatch)
        with pytest.raises(CaptureError, match="manifest is required"):
            capture.capture_successor_week(
                selected.digest,
                prior_index_digest=initial.digest,
                enroll=True,
            )
        with pytest.raises(CaptureError, match="Current exact source authorization"):
            capture.capture_successor_week(
                selected.digest,
                prior_index_digest=initial.digest,
                enroll=True,
                source_manifest_digest=source_manifest,
            )
        source_owner.append(source_manifest)
        enrolled = ResearchCaptureRepository(store, bootstrap=bootstrap).capture_successor_week(
            selected.digest,
            prior_index_digest=initial.digest,
            enroll=True,
            source_manifest_digest=source_manifest,
        )
        enrolled_value = enrolled.to_dict()
        enrolled_example = next(
            row
            for row in enrolled_value["denominator_rows"]
            if row["membership_state"] == "INCLUDED" and row["cb01"]["batch_digest"] is not None
        )
        batch_value = capture._cb01_body(
            enrolled_example["cb01"]["batch_digest"], "FixtureEnrollmentBatch"
        )
        forged_batch = json.loads(canonical_json(batch_value))
        forged_batch["lineage"]["causal_selection"]["active_scope_digest"] = "0" * 64
        with pytest.raises(CaptureError, match="exact selected freeze or graph"):
            capture._verify_batch_binding(
                enrolled_value, enrolled_example["membership_id"], forged_batch
            )
        assert len(enrolled_value["denominator_rows"]) == expected_full
        assert all(
            row["capture_state"] == CaptureState.EXCLUDED.value
            for row in enrolled_value["denominator_rows"]
            if row["membership_state"] == "EXCLUDED"
        )
        included_states = {
            row["capture_state"]
            for row in enrolled_value["denominator_rows"]
            if row["membership_state"] == "INCLUDED"
        }
        assert included_states == {CaptureState.FAILED.value, CaptureState.ENROLLED.value}
        assert any(
            row["cb01"]["failure_digests"]
            for row in enrolled_value["denominator_rows"]
            if row["capture_state"] == CaptureState.FAILED.value
        )
        assert missing_authority_backend.request_count == len(
            six_scope_graph.included_membership_ids
        )
        prior_attempt_count = missing_authority_backend.request_count
        missing_current_owner = SourceOwner(
            tmp_path / "issue100-owner-without-current-checkpoint", store, monkeypatch
        )
        with pytest.raises(CaptureError, match="Current exact source authorization"):
            capture.capture_successor_week(
                selected.digest,
                prior_index_digest=enrolled.digest,
                enroll=True,
                source_manifest_digest=source_manifest,
            )
        assert missing_current_owner.calls == 0
        assert missing_authority_backend.request_count == prior_attempt_count
        monkeypatch.setattr(
            "matchvet.source_authorization._SOURCE_CONFIG", source_owner.config_path
        )
        monkeypatch.setattr("matchvet.source_authorization._checkpoint", source_owner.checkpoint)

        freeze = MatchweekMembershipRepository(store).get_by_id(six_scope_graph.freeze_id)
        assert freeze is not None
        members = {item.membership_id: item for item in freeze.memberships}
        enrolled_rows = [
            row
            for row in enrolled_value["denominator_rows"]
            if row["membership_state"] == "INCLUDED"
        ]
        target_row = next(
            row for row in enrolled_rows if row["capture_state"] == CaptureState.ENROLLED.value
        )
        target_member = members[target_row["membership_id"]]
        match_result = next(
            item
            for item in F16MatchweekProcessor(store)
            .replay_manifest(six_scope_graph.f16_manifest_digest)
            .match_results
            if item.membership_id == target_member.membership_id
        )
        kickoff = datetime.fromisoformat(target_member.controlling_revision.kickoff_utc or "")
        preference_id = target_row["preference_id"]
        settlement_repository = SettlementRepository(store)
        first_evidence = SettlementEvidence(
            fixture_id=target_member.fixture_id,
            source_level="COMPETITION",
            source_key="issue100-synthetic-league",
            record_id="issue100-final-score-v1",
            fixture_status="FINISHED",
            full_time_home_goals=2,
            full_time_away_goals=0,
            published_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
            observed_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
            retrieved_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
        )
        first_settlement = settlement_repository.build(
            six_scope_graph.f16_manifest_digest,
            match_result.match_result_digest,
            preference_id,
            (first_evidence,),
        )
        assert first_settlement.to_dict()["schema_version"] == 3
        assert (
            first_settlement.to_dict()["active_scope_digest"]
            == six_scope_binding()["active_scope_digest"]
        )
        settlement_metadata = store.artifact_metadata(first_settlement.digest)
        assert settlement_metadata is not None
        assert settlement_metadata.media_type == SUCCESSOR_SETTLEMENT_MEDIA_TYPE
        altered_settlement = first_settlement.to_dict()
        altered_settlement["active_scope_digest"] = "0" * 64
        forged_settlement = ArtifactStore(store).publish_artifact(
            canonical_json(altered_settlement).encode(),
            SUCCESSOR_SETTLEMENT_MEDIA_TYPE,
            retention_class="PROTECTED",
        )
        with pytest.raises(F19Error):
            settlement_repository.replay(forged_settlement.digest)
        first_outcome_manifest = outcome_manifest(store, selected.digest, first_settlement.digest)
        source_owner.append(first_outcome_manifest)
        outcome_capture = ResearchCaptureRepository(
            store, bootstrap=bootstrap
        ).attach_successor_outcome(
            enrolled.digest,
            membership_id=target_member.membership_id,
            preference_id=preference_id,
            settlement_digest=first_settlement.digest,
            source_manifest_digest=first_outcome_manifest,
        )
        first_attachment = outcome_capture.to_dict()["denominator_rows"]
        target_history = next(
            row["outcome_history"]
            for row in first_attachment
            if row["membership_id"] == target_member.membership_id
        )
        assert len(target_history) == 1
        assert target_history[0]["active_scope_identity"] == six_scope_binding() | {
            "cohort_descriptor_digest": six_scope_graph.cohort_digest
        }

        corrected_evidence = replace(
            first_evidence,
            record_id="issue100-final-score-v2",
            full_time_home_goals=1,
            published_at_utc=(kickoff + timedelta(hours=3)).isoformat(),
            observed_at_utc=(kickoff + timedelta(hours=3)).isoformat(),
            retrieved_at_utc=(kickoff + timedelta(hours=3)).isoformat(),
        )
        corrected_settlement = settlement_repository.correct(
            first_settlement.digest, (corrected_evidence,)
        )
        assert corrected_settlement.predecessor_digest == first_settlement.digest
        assert corrected_settlement.correction_sequence == 1
        corrected_manifest = outcome_manifest(store, selected.digest, corrected_settlement.digest)
        source_owner.append(corrected_manifest)
        corrected_capture = ResearchCaptureRepository(
            store, bootstrap=bootstrap
        ).attach_successor_outcome(
            outcome_capture.digest,
            membership_id=target_member.membership_id,
            preference_id=preference_id,
            settlement_digest=corrected_settlement.digest,
            predecessor_attachment_digest=target_history[-1]["outcome_attachment_digest"],
            source_manifest_digest=corrected_manifest,
        )
        history = next(
            row["outcome_history"]
            for row in corrected_capture.to_dict()["denominator_rows"]
            if row["membership_id"] == target_member.membership_id
        )
        assert [item["correction_sequence"] for item in history] == [0, 1]
        assert (
            history[1]["predecessor_attachment_digest"] == history[0]["outcome_attachment_digest"]
        )
        with pytest.raises(F19Error):
            settlement_repository.correct(corrected_settlement.digest, (first_evidence,))

        source_owner.withdraw(source_manifest)
        before = missing_authority_backend.request_count
        with pytest.raises(CaptureError, match="withdrawn"):
            ResearchCaptureRepository(store, bootstrap=bootstrap).capture_successor_week(
                selected.digest,
                prior_index_digest=corrected_capture.digest,
                enroll=True,
                source_manifest_digest=source_manifest,
            )
        assert missing_authority_backend.request_count == before

        monkeypatch.setattr(
            "matchvet.causal_selection._load_approval",
            lambda *_args, **_kwargs: pytest.fail("Historical replay requested current authority."),
        )
        assert capture.replay(initial.digest).to_bytes() == initial.to_bytes()
        assert (
            ResearchCaptureRepository(store, bootstrap=bootstrap)
            .replay(corrected_capture.digest)
            .to_bytes()
            == corrected_capture.to_bytes()
        )
        replayed = MatchweekEvaluationRepository(store).inspect_historical_successor_cohort(
            six_scope_graph.freeze_digest,
            six_scope_graph.profile_digest,
            six_scope_graph.cutoff_policy_digest,
            selection_digest=selected.digest,
            exact_publication_digests=tuple(
                row["cb01"]["publication_digest"]
                for row in enrolled_value["denominator_rows"]
                if row["cb01"]["publication_digest"] is not None
            ),
        )
        assert replayed.qualification_status == "HISTORICAL_INSPECTION_ONLY"


def test_successor_candidate_and_index_identity_mismatches_fail_closed(
    six_scope_graph: SixScopeGraph, tmp_path: Path
) -> None:
    from matchvet.causal_candidate import resolve
    from matchvet.source_manifest import canonical

    destination = tmp_path / "identity-mismatch"
    from issue84_support import copy_store

    copy_store(six_scope_graph.root, destination)
    with open_store(destination / "store.sqlite3", private_root=destination) as store:
        artifacts = ArtifactStore(store)
        candidate = json.loads(artifacts.read_artifact(six_scope_graph.candidate_digest))
        candidate["active_scope_digest"] = "0" * 64
        forged_candidate = artifacts.publish_artifact(
            canonical(candidate), CANDIDATE_V2_MEDIA_TYPE
        ).digest
        with pytest.raises(MatchweekResearchError):
            resolve(store, forged_candidate)
        candidate_with_mismatched_cohort = json.loads(
            artifacts.read_artifact(six_scope_graph.candidate_digest)
        )
        candidate_with_mismatched_cohort["cohort_descriptor_digest"] = "0" * 64
        forged_cohort_candidate = artifacts.publish_artifact(
            canonical(candidate_with_mismatched_cohort), CANDIDATE_V2_MEDIA_TYPE
        ).digest
        with pytest.raises(MatchweekResearchError):
            resolve(store, forged_cohort_candidate)

        # A descriptor cannot silently select another cohort, even with a successful artifact write.
        cohort_metadata = store.artifact_metadata(six_scope_graph.cohort_digest)
        assert cohort_metadata is not None
        assert cohort_metadata.media_type == SIX_SCOPE_COHORT_MEDIA_TYPE
        with pytest.raises(MatchweekResearchError):
            MatchweekResearchRepository(store).publish_successor_six_scope_candidate(
                freeze_id=six_scope_graph.freeze_id,
                policy_digest=six_scope_graph.cutoff_policy_digest,
                profile_digest=six_scope_graph.profile_digest,
                decision_policy=PolicyVersion(version="issue100-six-scope"),
                engine_version=causal_engine_version_identity(),
                witness_profile_digest=_PROFILE_DIGEST,
                cohort_descriptor_digest="1" * 64,
            )

        # The fixed scope descriptor digest is not derived from mutable active defaults.
        assert six_scope_cohort_digest() == six_scope_graph.cohort_digest


def test_successor_cb01_batch_binds_exact_scope_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cb01-successor-identity"
    with open_store(root / "store.sqlite3", private_root=root) as store:
        repository = ResearchCaptureRepository(store)
        freeze_id = "freeze-100"
        membership_id = "membership-100"
        preference_id = "match_winner_home"
        profile_digest = "1" * 64
        membership_digest = "2" * 64
        cutoff_id = "cutoff-100"
        cutoff_digest = "3" * 64
        f11_digest = "4" * 64
        f13_digest = "5" * 64
        f14_digest = "6" * 64
        f16_digest = "7" * 64
        match_result_digest = "8" * 64
        active_scope_identity = {
            "active_scope_contract_id": "matchvet-active-scope-v2",
            "active_scope_contract_version": "2",
            "active_scope_digest": "9" * 64,
            "cohort_descriptor_digest": "a" * 64,
        }
        value: dict[str, Any] = {
            "schema_version": 3,
            "freeze": {"freeze_id": freeze_id, "digest": "b" * 64},
            "profile": {"digest": profile_digest, "enabled_preference_ids": [preference_id]},
            "selection": {"digest": "c" * 64, "completion_receipt_digest": "d" * 64},
            "graph": {"candidate_digest": "e" * 64, "f16_manifest_digest": f16_digest},
            "chronology": {"common_T_utc": "2026-10-10T12:00:00+00:00"},
            "active_scope_identity": active_scope_identity,
            "denominator_rows": [
                {
                    "membership_id": membership_id,
                    "preference_id": preference_id,
                    "f06": {"membership_digest": membership_digest},
                    "lineage": {
                        "f07_cutoff_id": cutoff_id,
                        "f07_cutoff_digest": cutoff_digest,
                        "f11_evidence_digest": f11_digest,
                        "f13_result_digest": f13_digest,
                        "f14_decision_digest": f14_digest,
                        "f16_match_result_digest": match_result_digest,
                    },
                }
            ],
        }

        def reference(identity: str, digest: str) -> dict[str, str]:
            return {"state": "PRESENT", "id": identity, "digest": digest}

        batch: dict[str, Any] = {
            "expected_preference_ids": [preference_id],
            "anchor": {
                "freeze": reference(freeze_id, "b" * 64),
                "membership": reference(membership_id, membership_digest),
                "cutoff": reference(cutoff_id, cutoff_digest),
                "profile": reference(profile_digest, profile_digest),
                "cutoff_utc": "2026-10-10T12:00:00+00:00",
                "kickoff_utc": "2026-10-10T18:00:00+00:00",
            },
            "lineage": {
                "f06": reference(freeze_id, "b" * 64),
                "f07": reference(cutoff_id, cutoff_digest),
                "f11_evidence": reference(f11_digest, f11_digest),
                "f13_result": reference(f13_digest, f13_digest),
                "f14_decision": reference(f14_digest, f14_digest),
                "f14_profile": reference(profile_digest, profile_digest),
                "f16_manifest": reference(f16_digest, f16_digest),
                "f16_match_result": reference(match_result_digest, match_result_digest),
                "causal_selection": {
                    "selection_digest": "c" * 64,
                    "completion_receipt_digest": "d" * 64,
                    "candidate_contract_digest": "e" * 64,
                    **active_scope_identity,
                },
            },
        }
        monkeypatch.setattr(
            repository,
            "_membership_kickoff",
            lambda _value, _membership_id: "2026-10-10T18:00:00+00:00",
        )
        repository._verify_batch_binding(value, membership_id, batch)

        forged_batch = json.loads(canonical_json(batch))
        forged_batch["lineage"]["causal_selection"]["cohort_descriptor_digest"] = "f" * 64
        with pytest.raises(CaptureError, match="exact selected freeze or graph"):
            repository._verify_batch_binding(value, membership_id, forged_batch)


def test_historical_seven_selection_occupies_the_shared_logical_week(
    selected_case: Any,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "occupied-seven-week"
    from issue84_support import copy_store

    copy_store(selected_case.root, destination)
    with open_store(destination / "store.sqlite3", private_root=destination) as store:
        historical_freeze = MatchweekMembershipRepository(store).get_by_id(
            selected_case.week.request.freeze_id
        )
        assert historical_freeze is not None
        historical_assessment = FixtureCoverageRepository(store).get(
            historical_freeze.assessment_digest
        )
        assert historical_assessment is not None
        six_assessment = _six_scope_assessment(historical_assessment)
        FixtureCoverageRepository(store).persist(six_assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(six_assessment))
        six_freeze = MatchweekMembershipRepository(store).freeze_exact(
            historical_freeze.season,
            historical_freeze.matchweek_friday,
            six_assessment.digest,
            "matchvet:matchweek-membership",
            "3",
        )
        assert len(six_freeze.scopes) == 6
        candidate = MatchweekResearchRepository(store).resolve_candidate(
            selected_case.week.request.candidate_contract_digest or ""
        )
        cohort_digest = publish_six_scope_cohort(store)
        with pytest.raises(MatchweekResearchError, match="cross-version candidate"):
            MatchweekResearchRepository(store).publish_successor_six_scope_candidate(
                freeze_id=six_freeze.freeze_id,
                policy_digest=candidate.cutoff_policy_digest,
                profile_digest=candidate.profile_digest,
                decision_policy=PolicyVersion(version="issue100-six-scope"),
                engine_version=causal_engine_version_identity(),
                witness_profile_digest=_PROFILE_DIGEST,
                cohort_descriptor_digest=cohort_digest,
            )


def _merge_sqlite_store(source_root: Path, destination_root: Path) -> None:
    shutil.copytree(
        source_root / "objects",
        destination_root / "objects",
        dirs_exist_ok=True,
    )
    source = source_root / "store.sqlite3"
    destination = destination_root / "store.sqlite3"
    connection = sqlite3.connect(destination, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ATTACH DATABASE ? AS historical", (str(source),))
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM main.sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        source_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM historical.sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if set(tables) != source_tables:
            raise AssertionError("Historical and successor stores have different schemas.")
        for table in tables:
            connection.execute(
                f'INSERT OR IGNORE INTO main."{table}" SELECT * FROM historical."{table}"'
            )
        violations = connection.execute("PRAGMA main.foreign_key_check").fetchall()
        if violations:
            raise AssertionError(
                f"Merged historical store has foreign-key violations: {violations}"
            )
        connection.execute("DETACH DATABASE historical")
    finally:
        connection.close()


def test_mixed_store_replays_historical_seven_bytes_unchanged(
    six_scope_graph: SixScopeGraph,
    selected_case: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor_root = tmp_path / "six-scope-store"
    from issue84_support import (
        copy_store,
        install_synthetic_authority,
        synthetic_authority,
        synthetic_timestamp_response,
    )

    copy_store(six_scope_graph.root, successor_root)
    authority = synthetic_authority(tmp_path / "issue100-mixed-authority")
    monkeypatch.setattr(_WitnessAttempt, "_evidence", _ORIGINAL_WITNESS_EVIDENCE)
    monkeypatch.setattr(MatchweekResearchRepository, "inspect_causal", _ORIGINAL_INSPECT_CAUSAL)
    monkeypatch.setattr(ResearchCaptureRepository, "_base_value", _ORIGINAL_CAPTURE_BASE_VALUE)
    install_synthetic_authority(monkeypatch, authority)
    cutoff = datetime.fromisoformat(six_scope_graph.common_cutoff_utc)
    with open_store(successor_root / "store.sqlite3", private_root=successor_root) as store:

        def deliver(attempt: Any) -> bytes:
            request = attempt._start_transport()
            return synthetic_timestamp_response(request, authority, cutoff - timedelta(minutes=10))

        monkeypatch.setattr("matchvet.causal_witness._post", deliver)
        selected = MatchweekResearchRepository(
            store,
            clock=Clock(cutoff - timedelta(seconds=1)),
            candidate_contract_digest=six_scope_graph.candidate_digest,
        ).seal_completed_v2(six_scope_graph.f16_manifest_digest)
        selected_graphs = {
            selected_case.selection_digest: selected_case.graph_snapshot,
            selected.digest: selected,
        }

        def inspect_retained_selection(
            repository: MatchweekResearchRepository, selection_digest: str
        ) -> Any:
            retained = selected_graphs.get(selection_digest)
            if retained is not None:
                return retained
            return _ORIGINAL_INSPECT_CAUSAL(repository, selection_digest)

        monkeypatch.setattr(
            MatchweekResearchRepository, "inspect_causal", inspect_retained_selection
        )
        successor_capture = ResearchCaptureRepository(store).capture_successor_week(selected.digest)
        successor_bytes = successor_capture.to_bytes()

    legacy_root = selected_case.root
    with open_store(legacy_root / "store.sqlite3", private_root=legacy_root) as legacy_store:
        legacy_selection_digest = selected_case.selection_digest
        legacy_receipt_digest = selected_case.graph_snapshot.completion_receipt_digest
        legacy_repository = ResearchCaptureRepository(legacy_store)
        legacy_initial = legacy_repository.capture_week(legacy_selection_digest)
        legacy_manifest = graph_manifest(legacy_store, legacy_selection_digest)
        source_owner = SourceOwner(
            tmp_path / "issue100-mixed-source-owner", legacy_store, monkeypatch
        )
        source_owner.append(legacy_manifest)
        source_owner.withdraw(legacy_manifest)
        legacy_v2 = legacy_repository.capture_week(
            legacy_selection_digest,
            prior_index_digest=legacy_initial.digest,
            enroll=True,
            source_manifest_digest=legacy_manifest,
        )
        legacy_initial_bytes = legacy_initial.to_bytes()
        legacy_v2_bytes = legacy_v2.to_bytes()
        legacy_selection_bytes = legacy_repository.artifacts.verify_manifest(
            legacy_selection_digest
        ).to_bytes()
        legacy_receipt_bytes = legacy_repository.artifacts.verify_manifest(
            legacy_receipt_digest
        ).to_bytes()

    mixed_root = tmp_path / "mixed-lineage-store"
    copy_store(legacy_root, mixed_root)
    _merge_sqlite_store(successor_root, mixed_root)
    with open_store(mixed_root / "store.sqlite3", private_root=mixed_root) as mixed_store:
        historical = ResearchCaptureRepository(mixed_store)
        assert historical.replay(legacy_initial.digest).to_bytes() == legacy_initial_bytes
        assert historical.replay(legacy_v2.digest).to_bytes() == legacy_v2_bytes
        assert (
            historical.artifacts.verify_manifest(legacy_selection_digest).to_bytes()
            == legacy_selection_bytes
        )
        assert (
            historical.artifacts.verify_manifest(legacy_receipt_digest).to_bytes()
            == legacy_receipt_bytes
        )
        assert historical.replay(successor_capture.digest).to_bytes() == successor_bytes

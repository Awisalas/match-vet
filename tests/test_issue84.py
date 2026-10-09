from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from issue84_support import (
    SuccessorWeek,
    SyntheticAuthority,
    build_successor_week,
    copy_store,
    install_synthetic_authority,
    reopen_successor_week,
    synthetic_authority,
    synthetic_timestamp_response,
)

pytest_plugins = ("test_matchweek_research",)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Issue #84 tests forbid network access.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="module")
def successor_week(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> SuccessorWeek:
    retained_root = os.environ.get("MATCHVET_ISSUE84_REUSE_ROOT")
    if retained_root is not None:
        return reopen_successor_week(Path(retained_root))
    from test_matchweek_research import Graph as HistoricalGraph

    graph = request.getfixturevalue("graph")
    assert isinstance(graph, HistoricalGraph)
    return build_successor_week(tmp_path_factory.mktemp("issue84-integrated-week"), graph)


@pytest.fixture(scope="module")
def authority(tmp_path_factory: pytest.TempPathFactory) -> SyntheticAuthority:
    return synthetic_authority(tmp_path_factory.mktemp("issue84-authority"))


def test_synthetic_rfc3161_signature_uses_real_profile_verifier(
    authority: SyntheticAuthority, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet.causal_witness import _request, _verify_event

    install_synthetic_authority(monkeypatch, authority)
    binding = b"synthetic exact graph binding for issue 84"
    nonce = (1 << 256) + 19
    request = _request(binding, nonce)
    gen_time = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=2)
    response = synthetic_timestamp_response(request, authority, gen_time)

    event = _verify_event(
        request,
        response,
        hashlib.sha256(binding).digest(),
        nonce,
        authority.bundle,
        authority.approval,
    )

    assert event.gen_time == gen_time.strftime("%Y%m%d%H%M%SZ")
    assert event.imprint == hashlib.sha256(binding).digest()
    assert event.nonce == nonce
    assert datetime.fromisoformat(event.lower) == gen_time - timedelta(milliseconds=1)
    assert datetime.fromisoformat(event.upper) == gen_time + timedelta(milliseconds=1)


def test_causal_retention_keeps_cb01_wire_tuf_identity(
    authority: SyntheticAuthority, tmp_path: Path
) -> None:
    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_selection import _evidence_media
    from matchvet.cb01 import BootstrapRepository
    from matchvet.store import open_store

    root = tmp_path / "tuf-identity"
    with open_store(root / "store.sqlite3", private_root=root) as store:
        artifacts = ArtifactStore(store)
        for name, content in authority.bundle.evidence():
            artifacts.publish_artifact(content, _evidence_media(name), retention_class="PROTECTED")
        backend = DeterministicWitnessBackend()
        BootstrapRepository(store, witness_backend=backend)._retain_trust(backend.trust)


def test_complete_successor_path_reopens_and_reaches_cb01_evaluation_and_f19(
    successor_week: SuccessorWeek,
    authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_dispatch import resolve_qualified_causal_selection
    from matchvet.causal_witness import _parse_response, _query
    from matchvet.cb01 import BootstrapRepository
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository
    from matchvet.cb01_sources import FixtureEnrollmentInput
    from matchvet.f14 import DecisionRepository, PreferenceProfileRepository
    from matchvet.f16 import F16MatchweekProcessor
    from matchvet.f19 import SettlementRepository, SettlementState
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import MatchweekResearchRepository
    from matchvet.research_identity import completion_slot, selection_slot
    from matchvet.store import open_store
    from matchvet.t10 import SettlementEvidence

    week = successor_week
    destination = tmp_path / "integrated-week"
    copy_store(week.root, destination)
    install_synthetic_authority(monkeypatch, authority)
    cutoff = datetime.fromisoformat(week.graph.cutoff)
    delivery_clock = {"current": cutoff - timedelta(microseconds=1)}
    transport_calls: list[bytes] = []
    delivery: dict[str, str] = {}
    selection_id = selection_slot(week.graph.logical_id)
    receipt_id = completion_slot(week.graph.logical_id)

    with open_store(destination / "store.sqlite3", private_root=destination) as store:
        owner = MatchweekResearchRepository(
            store, candidate_contract_digest=week.request.candidate_contract_digest
        )
        assert store.snapshot_manifest_digest_for_snapshot(selection_id) is None
        assert store.snapshot_manifest_digest_for_snapshot(receipt_id) is None

        def deliver_after_t(attempt: Any) -> bytes:
            request = attempt._start_transport()
            transport_calls.append(request)
            selected = store.snapshot_manifest_digest_for_snapshot(selection_id)
            assert selected is not None
            assert store.snapshot_manifest_digest_for_snapshot(receipt_id) is None
            binding = json.loads(attempt._binding)
            assert binding["selection_digest"] == selected
            assert binding["f16_digest"] == week.manifest_digest
            assert binding["logical_matchweek_id"] == week.graph.logical_id
            request_imprint, request_nonce = _query(request)
            assert request_imprint == hashlib.sha256(attempt._binding).digest()
            assert request_nonce == attempt._nonce
            signed_time = cutoff - timedelta(minutes=10)
            response = synthetic_timestamp_response(request, authority, signed_time)
            event = _parse_response(response, authority.signer_der, authority.anchor_der)
            assert datetime.fromisoformat(event.upper) < cutoff
            delivery_clock["current"] = cutoff + timedelta(microseconds=1)
            delivery["at"] = delivery_clock["current"].isoformat()
            delivery["signed_upper"] = event.upper
            return response

        monkeypatch.setattr("matchvet.causal_witness._post", deliver_after_t)
        selected = owner.seal_completed_v2(week.manifest_digest)
        assert len(transport_calls) == 1
        assert datetime.fromisoformat(delivery["at"]) > cutoff
        assert datetime.fromisoformat(delivery["signed_upper"]) < cutoff
        receipt_digest = store.snapshot_manifest_digest_for_snapshot(receipt_id)
        assert receipt_digest == selected.completion_receipt_digest
        assert delivery_clock["current"] > cutoff

    with open_store(destination / "store.sqlite3", private_root=destination) as store:
        # Reopening replays exact indexed evidence offline and never asks the TSA again.
        monkeypatch.setattr(
            "matchvet.causal_witness._post",
            lambda *_args, **_kwargs: pytest.fail("Offline replay requested a new witness."),
        )
        qualified = resolve_qualified_causal_selection(store, selected.digest)
        assert qualified.f16_manifest_digest == week.manifest_digest
        assert qualified.completion_receipt_digest == receipt_digest
        assert qualified.candidate_contract_digest == week.request.candidate_contract_digest
        assert qualified.selection.cutoff_at_utc == week.graph.cutoff

        # The retained v1 selection and every canonical graph object still replay in this store.
        old = MatchweekResearchRepository(store).replay(week.historical_v1.selection_digest)
        assert old.f16_manifest_digest == week.historical_v1.f16_digest
        assert old.completion_receipt_digest == week.historical_v1.completion_digest
        artifacts = ArtifactStore(store)
        for digest, original in week.historical_v1.frozen_artifacts:
            assert artifacts.read_artifact(digest) == original
        old_manifest = F16MatchweekProcessor(store).replay_manifest(week.historical_v1.f16_digest)
        assert old_manifest.to_bytes() == artifacts.read_artifact(week.historical_v1.f16_digest)

        freeze = MatchweekMembershipRepository(store).get_by_id(week.request.freeze_id)
        assert freeze is not None
        profile = PreferenceProfileRepository(store).replay(week.request.preference_profile_digest)
        cutoffs = MatchEvidenceCutoffRepository(store).replay_for_freeze(
            week.request.freeze_id, week.request.cutoff_policy_digest
        )
        assert len(cutoffs) == len(week.included_membership_ids)
        assert len({item.cutoff_at_utc for item in cutoffs}) == 1
        assert all(item.cutoff_at_utc == week.graph.cutoff for item in cutoffs)
        cutoff_by_membership = {item.membership_id: item for item in cutoffs}
        first_membership, second_membership = week.included_membership_ids[:2]

        def enrollment_input(membership_id: str) -> FixtureEnrollmentInput:
            return FixtureEnrollmentInput(
                week.request.freeze_id,
                membership_id,
                cutoff_by_membership[membership_id].cutoff_id,
                week.request.preference_profile_digest,
                week.manifest_digest,
                selected.digest,
            )

        unavailable = BootstrapRepository(
            store,
            witness_backend=DeterministicWitnessBackend(transport_states=("UNAVAILABLE",)),
        ).enroll_fixture(enrollment_input(first_membership))
        assert unavailable.publication_digest is None
        assert unavailable.failure_digests

        cb01_gen_time = datetime.fromisoformat(week.graph.cutoff) + timedelta(minutes=1)
        cb01_backend = DeterministicWitnessBackend(
            gen_time_utc=cb01_gen_time.isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        bootstrap = BootstrapRepository(store, witness_backend=cb01_backend)
        enrolled = bootstrap.enroll_fixture(enrollment_input(second_membership))
        assert enrolled.publication_digest is not None
        assert enrolled.verification_digest is not None
        verification = bootstrap._read_kind(enrolled.verification_digest, "TimestampVerification")
        gen_time = datetime.fromisoformat(
            verification["tsa"]["gen_time_utc"].replace("Z", "+00:00")
        )
        member_by_id = {member.membership_id: member for member in freeze.memberships}
        kickoff = datetime.fromisoformat(
            member_by_id[second_membership].controlling_revision.kickoff_utc or ""
        )
        assert cutoff < gen_time < kickoff
        assert verification["checks"]["time_window"]["state"] == "PASSED"

        evaluation = MatchweekEvaluationRepository(
            store, witness_backend=cb01_backend
        ).inspect_cohort(
            freeze.freeze_digest,
            profile.digest,
            week.request.cutoff_policy_digest,
            selection_digest=selected.digest,
            exact_publication_digests=(enrolled.publication_digest,),
        )
        assert evaluation.cohort == "CAUSAL_SELECTION_V2"
        assert evaluation.selection_contract == "matchvet-causal-selection-v2"
        assert evaluation.qualification_status == "PRESENTLY_QUALIFIED"
        expected_denominator = len(freeze.memberships) * len(profile.enabled_preferences)
        assert len(evaluation.denominator.rows) == expected_denominator == 3
        assert evaluation.included_count == expected_denominator
        rows_by_member = {
            membership_id: tuple(
                row for row in evaluation.denominator.rows if row.membership_id == membership_id
            )
            for membership_id in week.included_membership_ids
        }
        assert rows_by_member[first_membership][0].failure_digests
        assert (
            rows_by_member[second_membership][0].publication_digest == enrolled.publication_digest
        )
        unattempted = set(week.included_membership_ids) - {first_membership, second_membership}
        assert all(
            row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED"
            for membership_id in unattempted
            for row in rows_by_member[membership_id]
        )

        manifest = F16MatchweekProcessor(store).replay_manifest(week.manifest_digest)
        match_result = next(
            item for item in manifest.match_results if item.membership_id == second_membership
        )
        decision = DecisionRepository(store).replay(match_result.decision_digest)
        decision_bytes_before = artifacts.read_artifact(decision.to_dict()["input_bundle_digest"])
        graph_bytes_before = dict(week.frozen_artifacts)
        settlement = SettlementRepository(store)
        preference_id = profile.enabled_preferences[0].preference_id
        pending = settlement.build(
            week.manifest_digest,
            match_result.match_result_digest,
            preference_id,
            (),
        )
        assert pending.state is SettlementState.PENDING
        pending_value = pending.to_dict()
        assert pending_value["selection_digest"] == selected.digest
        assert pending_value["completion_receipt_digest"] == receipt_digest
        assert pending_value["manifest_digest"] == week.manifest_digest
        assert pending_value["decision_digest"] == match_result.decision_digest
        assert pending_value["candidate_contract_digest"] == week.request.candidate_contract_digest

        evidence = SettlementEvidence(
            fixture_id=member_by_id[second_membership].fixture_id,
            source_level="COMPETITION",
            source_key="issue84-synthetic-league",
            record_id="issue84-final-score",
            fixture_status="FINISHED",
            full_time_home_goals=2,
            full_time_away_goals=0,
            published_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
            observed_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
            retrieved_at_utc=(kickoff + timedelta(hours=2)).isoformat(),
        )
        corrected = settlement.correct(pending.digest, (evidence,))
        assert corrected.predecessor_digest == pending.digest
        assert corrected.correction_sequence == 1
        assert corrected.state in {SettlementState.WIN, SettlementState.LOSS}
        assert settlement.replay(corrected.digest).to_bytes() == corrected.to_bytes()
        assert (
            artifacts.read_artifact(decision.to_dict()["input_bundle_digest"])
            == decision_bytes_before
        )
        assert {
            digest: artifacts.read_artifact(digest) for digest in graph_bytes_before
        } == graph_bytes_before


def test_production_causal_activation_still_refuses(
    tmp_path: Path,
) -> None:
    from matchvet.causal_selection import _load_approval
    from matchvet.matchweek_research import MatchweekResearchError
    from matchvet.store import open_store

    root = tmp_path / "production-refusal"
    with (
        open_store(root / "store.sqlite3", private_root=root) as store,
        pytest.raises(MatchweekResearchError, match="activation is unavailable"),
    ):
        _load_approval(store)

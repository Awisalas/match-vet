from __future__ import annotations

import json
import os
import socket
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from issue84_support import (
    CausalGraphIdentity,
    HistoricalV1,
    SuccessorWeek,
    SyntheticAuthority,
    copy_store,
    install_synthetic_authority,
    reopen_successor_week,
    synthetic_authority,
    synthetic_timestamp_response,
)

from matchvet.matchweek_research import FrozenMatchweekResearch, MatchweekResearchRepository
from matchvet.research_capture import (
    CaptureError,
    CaptureState,
    ResearchCaptureRepository,
    SourceUseDecision,
    SourceUseState,
    require_cb01_window,
    require_pre_t_witness,
)
from matchvet.store import open_store


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Issue #86 capture tests forbid network access.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="module")
def successor_week(
    tmp_path_factory: pytest.TempPathFactory,
) -> SuccessorWeek:
    reuse_root = os.environ.get("MATCHVET_ISSUE86_REUSE_ROOT") or os.environ.get(
        "MATCHVET_ISSUE84_REUSE_ROOT"
    )
    if reuse_root is not None:
        return reopen_successor_week(Path(reuse_root))
    root = tmp_path_factory.mktemp("issue86-week")
    from matchweek_research_support import Clock
    from test_matchweek_membership import _persistable_schedule_assessment

    from matchvet.candidate_primitives import HEALTH_MEDIA_TYPE
    from matchvet.causal_trust import _PROFILE_DIGEST
    from matchvet.f10 import V2_REQUIREMENT_CATALOG
    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f13 import causal_engine_version_identity
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE
    from matchvet.fixture_coverage_repository import FixtureCoverageRepository
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import CORRECTED_RULE, MatchweekResearchRepository
    from matchvet.provider_health_acquisition import build_provider_health_records
    from matchvet.provider_health_repository import ProviderHealthRepository
    from matchvet.store import open_store
    from matchvet.t15 import PolicyVersion

    now = datetime.now(UTC)
    friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
    if datetime.combine(friday, datetime.min.time(), tzinfo=UTC) <= now + timedelta(hours=24):
        friday += timedelta(days=7)
    friday_text = friday.isoformat()
    with open_store(root / "store.sqlite3", private_root=root) as store:
        rows_by_league = {
            "serie_a": (
                (friday_text, "20:00", "Issue86 placeholder home", "Issue86 placeholder away"),
            ),
        }
        assessment = _persistable_schedule_assessment(
            store,
            root,
            rows_by_league["serie_a"],
            matchweek_friday=friday_text,
            rows_by_league=rows_by_league,
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store, clock=lambda: now).freeze_exact(
            "2026-27",
            friday_text,
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy_digest = cutoffs.persist_policy(
            CutoffPolicy("issue86-seven-scope", "1", 21600, rule=CORRECTED_RULE)
        )
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, cutoff_policy_digest)
        profile = PreferenceProfileRepository(store).build_profile(("match_winner_home",))
        policy = PolicyVersion(version="issue86-diagnostic")
        owner = MatchweekResearchRepository(store, clock=Clock())
        candidate_digest = owner.publish_candidate(
            freeze_id=freeze.freeze_id,
            policy_digest=cutoff_policy_digest,
            profile_digest=profile.digest,
            decision_policy=policy,
            engine_version=causal_engine_version_identity(),
            witness_profile_digest=_PROFILE_DIGEST,
        )
        candidate = owner.resolve_candidate(candidate_digest)
        F11EvidenceRepository(store, candidate_contract_digest=candidate_digest).build(
            freeze.freeze_id, cutoff_policy_digest, weather_client=None
        )
        request_value = AnalyzeMatchweekRequest(
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
        progress = AnalyzeMatchweek(
            store, clock=Clock(), candidate_contract_digest=candidate_digest
        ).start(request_value)
        assert progress.analysis_state == "F16_COMPLETE_AWAITING_F17"
        manifests = [
            item.digest
            for item in store.artifact_catalog()
            if item.media_type == CAUSAL_MANIFEST_MEDIA_TYPE
        ]
        assert len(manifests) == 1
        freeze_value = MatchweekMembershipRepository(store).get_by_id(freeze.freeze_id)
        assert freeze_value is not None
        included = tuple(
            sorted(
                member.membership_id
                for member in freeze_value.memberships
                if member.decision.value == "INCLUDED"
            )
        )
        assert len(freeze_value.scopes) == 7 and included
        assert HEALTH_MEDIA_TYPE in {item.media_type for item in store.artifact_catalog()}
        return SuccessorWeek(
            root,
            request_value,
            manifests[0],
            CausalGraphIdentity(candidate.logical_matchweek_id, candidate.cutoff_at_utc),
            freeze.freeze_digest,
            included,
            HistoricalV1("", "", "", ()),
            (),
        )


@pytest.fixture(scope="module")
def authority(tmp_path_factory: pytest.TempPathFactory) -> SyntheticAuthority:
    return synthetic_authority(tmp_path_factory.mktemp("issue86-authority"))


@dataclass(frozen=True)
class SelectedCase:
    root: Path
    week: SuccessorWeek
    selection_digest: str
    graph_snapshot: FrozenMatchweekResearch
    base_value: dict[str, Any] = field(default_factory=dict)


@pytest.fixture(scope="module")
def selected_source(
    successor_week: SuccessorWeek,
    authority: SyntheticAuthority,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[SelectedCase]:
    from matchvet.matchweek_research import MatchweekResearchRepository

    root = tmp_path_factory.mktemp("issue86-selected")
    copy_store(successor_week.root, root)
    patcher = pytest.MonkeyPatch()
    with open_store(root / "store.sqlite3", private_root=root) as store:
        from matchvet.artifacts import ArtifactStore
        from matchvet.causal_trust import (
            _PROFILE_DIGEST,
            _Approval,
            _AuthenticatedTrust,
            _TrustBundle,
        )
        from matchvet.research_identity import completion_slot, selection_slot

        selected_digest = store.snapshot_manifest_digest_for_snapshot(
            selection_slot(successor_week.graph.logical_id)
        )
        if selected_digest is not None:
            artifacts = ArtifactStore(store)
            selection = artifacts.verify_manifest(selected_digest)
            receipt_digest = store.snapshot_manifest_digest_for_snapshot(
                completion_slot(successor_week.graph.logical_id)
            )
            assert receipt_digest is not None
            receipt = artifacts.verify_manifest(receipt_digest)
            provenance_ref = next(
                ref
                for ref in receipt.artifacts
                if ref.media_type == "application/vnd.matchvet.causal-selection-witness.v1+json"
            )
            provenance = json.loads(artifacts.read_artifact(provenance_ref.digest))
            evidence = {
                name: artifacts.read_artifact(digest)
                for name, digest in provenance["evidence"].items()
            }
            approval_raw = json.loads(evidence["approval"])
            approval = _Approval(
                not_before=approval_raw["not_before"],
                not_after=approval_raw["not_after"],
                floors=tuple(tuple(item) for item in approval_raw["floors"]),
                target_digest=approval_raw["target_digest"],
                history_identity=approval_raw["history_identity"],
                withdrawn_from=approval_raw["withdrawn_from"],
                timescale=approval_raw["timescale"],
                operator_compliance=approval_raw["operator_compliance"],
                profile_digest=approval_raw["profile_digest"],
            )
            roots = tuple(
                evidence[name]
                for name in sorted(
                    (item for item in evidence if item.startswith("root-")),
                    key=lambda item: int(item.removeprefix("root-")),
                )
            )
            bundle = _TrustBundle(
                roots,
                evidence["timestamp"],
                evidence["snapshot"],
                evidence["targets"],
                evidence["trusted-root"],
            )
            retained_authority = replace(
                authority,
                bundle=bundle,
                approval=approval,
                authenticated=_AuthenticatedTrust(
                    evidence["signer"],
                    evidence["anchor"],
                    approval.not_before,
                    approval.not_after,
                    (),
                    approval.floors,
                ),
                signer_der=evidence["signer"],
                anchor_der=evidence["anchor"],
            )
            assert selection.digest == selected_digest
            assert approval.profile_digest == _PROFILE_DIGEST
            install_synthetic_authority(patcher, retained_authority)
            from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

            freeze = MatchweekMembershipRepository(store).get_by_id(
                successor_week.request.freeze_id
            )
            assert freeze is not None
            graph_snapshot = FrozenMatchweekResearch(
                selected_digest,
                freeze.season,
                successor_week.request.matchweek,
                successor_week.request.freeze_id,
                successor_week.request.cutoff_policy_digest,
                successor_week.graph.cutoff,
                successor_week.manifest_digest,
                receipt_digest,
            )
            selected_case_value = SelectedCase(
                root, successor_week, selected_digest, graph_snapshot
            )
        else:
            install_synthetic_authority(patcher, authority)
            cutoff = datetime.fromisoformat(successor_week.graph.cutoff)

            def deliver(attempt: Any) -> bytes:
                request_der = attempt._start_transport()
                binding = json.loads(attempt._binding)
                assert binding["f16_digest"] == successor_week.manifest_digest
                signed_time = cutoff - timedelta(minutes=10)
                return synthetic_timestamp_response(request_der, authority, signed_time)

            patcher.setattr("matchvet.causal_witness._post", deliver)
            selected = MatchweekResearchRepository(
                store, candidate_contract_digest=successor_week.request.candidate_contract_digest
            ).seal_completed_v2(successor_week.manifest_digest)
            selected_case_value = SelectedCase(root, successor_week, selected.digest, selected)

        def inspect_causal(
            _repository: MatchweekResearchRepository, selection_digest: str
        ) -> FrozenMatchweekResearch:
            if selection_digest != selected_case_value.selection_digest:
                raise AssertionError("Issue #86 fixture requested another causal selection.")
            return selected_case_value.graph_snapshot

        patcher.setattr(MatchweekResearchRepository, "inspect_causal", inspect_causal)
        base_value = ResearchCaptureRepository(store)._base_value(
            selected_case_value.selection_digest
        )
        selected_case_value = replace(selected_case_value, base_value=base_value)
    try:
        yield selected_case_value
    finally:
        patcher.undo()


@pytest.fixture
def selected_case(
    selected_source: SelectedCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SelectedCase:
    root = tmp_path / "selected-store"
    copy_store(selected_source.root, root)
    case = SelectedCase(
        root,
        selected_source.week,
        selected_source.selection_digest,
        selected_source.graph_snapshot,
        selected_source.base_value,
    )

    def inspect_causal(
        _repository: MatchweekResearchRepository, selection_digest: str
    ) -> FrozenMatchweekResearch:
        if selection_digest != case.selection_digest:
            raise AssertionError("Issue #86 tests requested another causal selection.")
        return case.graph_snapshot

    monkeypatch.setattr(MatchweekResearchRepository, "inspect_causal", inspect_causal)

    qualified_selection = SimpleNamespace(
        candidate=SimpleNamespace(
            witness_profile_digest=case.base_value["chronology"]["witness_profile_digest"]
        ),
        candidate_contract_digest=case.base_value["graph"]["candidate_digest"],
        f16_manifest_digest=case.base_value["graph"]["f16_manifest_digest"],
    )

    def resolve_qualified(_store: Any, selection_digest: str) -> Any:
        if selection_digest != case.selection_digest:
            raise AssertionError("Issue #86 tests requested another causal selection.")
        return qualified_selection

    monkeypatch.setattr(
        "matchvet.research_capture.resolve_qualified_causal_selection", resolve_qualified
    )

    def build_base(_repository: ResearchCaptureRepository, selection_digest: str) -> dict[str, Any]:
        if selection_digest != case.selection_digest:
            raise AssertionError("Issue #86 tests requested another causal selection.")
        from matchvet.matchweek_membership import canonical_json

        return json.loads(canonical_json(case.base_value))

    monkeypatch.setattr(ResearchCaptureRepository, "_base_value", build_base)
    return case


class StaticSourceAuthorizer:
    def __init__(self, decision: SourceUseDecision) -> None:
        self.decision = decision
        self.calls: list[dict[str, object]] = []

    def authorize_real_source_use(
        self,
        *,
        freeze_digest: str,
        selection_digest: str,
        profile_digest: str,
        scope_ids: tuple[str, ...],
    ) -> SourceUseDecision:
        self.calls.append(
            {
                "freeze_digest": freeze_digest,
                "profile_digest": profile_digest,
                "scope_ids": scope_ids,
                "selection_digest": selection_digest,
            }
        )
        return self.decision


def _source_authorizer(
    store: Any,
    index_value: dict[str, Any],
    *,
    withdrawn: bool = False,
) -> StaticSourceAuthorizer:
    from matchvet.artifacts import ArtifactStore
    from matchvet.matchweek_membership import canonical_json

    state = SourceUseState.WITHDRAWN if withdrawn else SourceUseState.APPROVED
    reasons = ["TEST_SOURCE_USE_WITHDRAWN"] if withdrawn else []
    content = canonical_json(
        {
            "contract": "research-real-source-use-decision-v1",
            "freeze_digest": index_value["freeze"]["digest"],
            "profile_digest": index_value["profile"]["digest"],
            "reason_codes": reasons,
            "scope_ids": index_value["freeze"]["scope_ids"],
            "selection_digest": index_value["selection"]["digest"],
            "state": state.value,
        }
    ).encode("utf-8")
    artifact = ArtifactStore(store).publish_artifact(
        content,
        "application/vnd.matchvet.research-source-use-decision.v1+json",
        retention_class="PROTECTED",
    )
    return StaticSourceAuthorizer(
        SourceUseDecision(
            state,
            artifact.digest,
            tuple(reasons),
        )
    )


def _exact_test_batch_body(
    value: dict[str, Any], membership_id: str, repository: ResearchCaptureRepository
) -> dict[str, Any]:
    rows = [row for row in value["denominator_rows"] if row["membership_id"] == membership_id]
    first = rows[0]

    def reference(identity: str, digest: str) -> dict[str, str]:
        return {"digest": digest.removeprefix("sha256:"), "id": identity, "state": "PRESENT"}

    freeze_digest = value["freeze"]["digest"].removeprefix("sha256:")
    cutoff_digest = first["lineage"]["f07_cutoff_digest"].removeprefix("sha256:")
    return {
        "anchor": {
            "freeze": reference(value["freeze"]["freeze_id"], freeze_digest),
            "membership": reference(membership_id, first["f06"]["membership_digest"]),
            "cutoff": reference(first["lineage"]["f07_cutoff_id"], cutoff_digest),
            "profile": reference(value["profile"]["digest"], value["profile"]["digest"]),
            "cutoff_utc": value["chronology"]["common_T_utc"],
            "kickoff_utc": repository._membership_kickoff(value, membership_id),
        },
        "lineage": {
            "f06": reference(value["freeze"]["freeze_id"], freeze_digest),
            "f07": reference(first["lineage"]["f07_cutoff_id"], cutoff_digest),
            "f11_evidence": reference(
                first["lineage"]["f11_evidence_digest"],
                first["lineage"]["f11_evidence_digest"],
            ),
            "f13_result": reference(
                first["lineage"]["f13_result_digest"],
                first["lineage"]["f13_result_digest"],
            ),
            "f14_decision": reference(
                first["lineage"]["f14_decision_digest"],
                first["lineage"]["f14_decision_digest"],
            ),
            "f14_profile": reference(value["profile"]["digest"], value["profile"]["digest"]),
            "f16_manifest": reference(
                value["graph"]["f16_manifest_digest"],
                value["graph"]["f16_manifest_digest"],
            ),
            "f16_match_result": reference(
                first["lineage"]["f16_match_result_digest"],
                first["lineage"]["f16_match_result_digest"],
            ),
            "causal_selection": {
                "candidate_contract_digest": value["graph"]["candidate_digest"],
                "completion_receipt_digest": value["selection"]["completion_receipt_digest"],
                "selection_digest": value["selection"]["digest"],
            },
        },
        "expected_preference_ids": value["profile"]["enabled_preference_ids"],
        "entries": [
            {
                "disposition": "READY_FOR_WITNESS",
                "pre_enrollment_digest": f"{ordinal:064x}",
                "preference_id": row["preference_id"],
                "reasons": [],
            }
            for ordinal, row in enumerate(rows, start=1)
        ],
    }


def test_capture_chronology_boundaries_are_strict() -> None:
    common_t = datetime(2026, 10, 9, 12, tzinfo=UTC)
    kickoff = common_t + timedelta(hours=6)

    require_pre_t_witness(common_t - timedelta(microseconds=1), common_t)
    require_cb01_window(common_t + timedelta(microseconds=1), common_t, kickoff)

    with pytest.raises(CaptureError, match="strictly before common T"):
        require_pre_t_witness(common_t, common_t)
    with pytest.raises(CaptureError, match="strictly after common T"):
        require_cb01_window(common_t, common_t, kickoff)
    with pytest.raises(CaptureError, match="strictly before kickoff"):
        require_cb01_window(kickoff, common_t, kickoff)


def test_capture_states_keep_unavailable_reasons() -> None:
    assert CaptureState.UNATTEMPTED.value == "UNATTEMPTED"
    assert CaptureState.FAILED.value == "FAILED"
    assert CaptureState.WITHDRAWN.value == "WITHDRAWN"
    assert CaptureState.MISSING.value == "MISSING"


def test_exact_offline_capture_index_replays_the_complete_denominator(
    selected_case: SelectedCase,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.matchweek_membership import canonical_json
    from matchvet.research_capture import CAPTURE_INDEX_MEDIA_TYPE

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        index = repository.capture_week(selected_case.selection_digest)
        value = index.to_dict()
        assert len(value["freeze"]["scope_ids"]) == 7
        assert value["denominator"]["included_membership_count"] == len(
            selected_case.week.included_membership_ids
        )
        assert value["denominator"]["membership_count"] == len(
            selected_case.week.included_membership_ids
        )
        assert value["denominator"]["row_count"] == (
            value["denominator"]["membership_count"] * value["denominator"]["preference_count"]
        )
        assert value["freeze"]["membership_count"] >= value["denominator"]["membership_count"]
        assert len(value["excluded_memberships"]) == (
            value["freeze"]["membership_count"] - value["denominator"]["membership_count"]
        )
        assert all(row["capture_state"] == "UNATTEMPTED" for row in value["denominator_rows"])
        assert all(row["outcome_state"] == "MISSING" for row in value["denominator_rows"])
        assert all(
            row["candidate_input"]["state"] == "UNKNOWN" for row in value["denominator_rows"]
        )
        assert all(
            row["f14"]["preference_result"]["terminal_result"]
            in {"PRIMARY_RECOMMENDATION", "SURVIVES_NOT_SELECTED", "REJECTED"}
            and isinstance(row["f14"]["preference_result"]["vetting"], dict)
            for row in value["denominator_rows"]
        )
        assert value["roles"] == {
            "final_evaluation": None,
            "fitting": None,
            "validation": None,
        }
        assert (
            value["chronology"]["selection_witness"]["upper_bound_utc"]
            < value["chronology"]["common_T_utc"]
        )
        raw_families = value["denominator_rows"][0]["f13"]["families"]
        assert raw_families
        assert all("raw_prediction_artifact_digest" in item for item in raw_families)
        assert all("calibration_availability_state" in item for item in raw_families)
        assert all(item["calibrated_prediction_is_validation"] is False for item in raw_families)
        replay = repository.replay(index.digest)
        assert replay.to_bytes() == index.to_bytes()
        assert repository.capture_week(selected_case.selection_digest).digest == index.digest
        tampered = index.to_dict()
        tampered["denominator_rows"][0]["candidate_input"]["state"] = "SUPPORTED"
        tampered_artifact = ArtifactStore(store).publish_artifact(
            canonical_json(tampered).encode("utf-8"),
            CAPTURE_INDEX_MEDIA_TYPE,
            retention_class="PROTECTED",
        )
        with pytest.raises(CaptureError, match="upstream denominator row"):
            repository.replay(tampered_artifact.digest)
        metadata = store.artifact_metadata(index.digest)
        assert metadata is not None
        assert (metadata.media_type, metadata.retention_class) == (
            CAPTURE_INDEX_MEDIA_TYPE,
            "PROTECTED",
        )
        assert ArtifactStore(store).read_artifact(index.digest) == index.to_bytes()


def test_source_authorization_absence_refuses_before_cb01(
    selected_case: SelectedCase,
) -> None:
    from matchvet.cb01_schema import MEDIA_TYPES

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        index = repository.capture_week(selected_case.selection_digest)
        before = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }
        with pytest.raises(CaptureError, match="authorization is absent"):
            repository.capture_week(
                selected_case.selection_digest,
                prior_index_digest=index.digest,
                enroll=True,
            )
        after = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }
        assert after == before


def test_withdrawn_source_use_is_retained_without_attempting_cb01(
    selected_case: SelectedCase,
) -> None:
    from matchvet.cb01_schema import MEDIA_TYPES

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        index = repository.capture_week(selected_case.selection_digest)
        authorizer = _source_authorizer(store, index.to_dict(), withdrawn=True)
        before = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }
        repository.source_authorizer = authorizer
        withdrawn = repository.capture_week(
            selected_case.selection_digest,
            prior_index_digest=index.digest,
            enroll=True,
        )
        value = repository.replay(withdrawn.digest).to_dict()
        assert value["predecessor_digest"] == index.digest
        assert value["source_use"]["state"] == "WITHDRAWN"
        assert all(row["capture_state"] == "WITHDRAWN" for row in value["denominator_rows"])
        assert all(
            row["capture_reasons"] == ["TEST_SOURCE_USE_WITHDRAWN"]
            for row in value["denominator_rows"]
        )
        after = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }
        assert after == before
        assert authorizer.calls[0]["scope_ids"] == tuple(value["freeze"]["scope_ids"])


def test_causal_profile_absence_refuses_before_cb01(
    selected_case: SelectedCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.cb01_schema import MEDIA_TYPES
    from matchvet.matchweek_research import MatchweekResearchError

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        index = repository.capture_week(selected_case.selection_digest)
        repository.source_authorizer = _source_authorizer(store, index.to_dict())
        before = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }

        def unavailable(*_args: Any, **_kwargs: Any) -> Any:
            raise MatchweekResearchError("Authenticated causal profile activation is unavailable.")

        monkeypatch.setattr(
            "matchvet.research_capture.resolve_qualified_causal_selection", unavailable
        )
        with pytest.raises(CaptureError):
            repository.capture_week(
                selected_case.selection_digest,
                prior_index_digest=index.digest,
                enroll=True,
            )
        after = {
            row.digest
            for row in store.artifact_catalog()
            if row.media_type == MEDIA_TYPES["TimestampAttempt"]
        }
        assert after == before


def test_failed_cb01_attempt_keeps_exact_failure_rows(
    selected_case: SelectedCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.cb01 import BatchResult

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        value = repository.capture_week(selected_case.selection_digest).to_dict()
        batch_bodies: dict[str, dict[str, Any]] = {}
        failure_bodies: dict[str, dict[str, Any]] = {}

        def read_cb01_body(digest: str, kind: str) -> dict[str, Any]:
            if kind == "FixtureEnrollmentBatch":
                return batch_bodies[digest]
            if kind == "TimestampFailure":
                return failure_bodies[digest]
            raise AssertionError(f"Unexpected CB01 fixture kind: {kind}")

        monkeypatch.setattr(repository, "_cb01_body", read_cb01_body)
        monkeypatch.setattr(
            "matchvet.research_capture.replay_fixture_sources",
            lambda _store, _batch: object(),
        )
        monkeypatch.setattr(
            repository.bootstrap,
            "_assert_prepared_batch",
            lambda _prepared, _digest, _batch: None,
        )
        memberships = sorted({row["membership_id"] for row in value["denominator_rows"]})
        for ordinal, membership_id in enumerate(memberships, start=1):
            rows = [
                row for row in value["denominator_rows"] if row["membership_id"] == membership_id
            ]
            batch_digest = f"{ordinal:064x}"
            failure_digest = f"{ordinal + 100:064x}"
            batch_bodies[batch_digest] = _exact_test_batch_body(value, membership_id, repository)
            failure_bodies[failure_digest] = {
                "attempt_digest": None,
                "batch_digest": batch_digest,
                "attempt_result_digest": None,
                "expected_preference_ids": value["profile"]["enabled_preference_ids"],
                "reasons": ["TEST_TSA_UNAVAILABLE"],
                "verification_digest": None,
            }
            repository._apply_batch_result(
                value,
                rows,
                BatchResult(
                    batch_digest,
                    None,
                    None,
                    None,
                    (failure_digest,),
                    "INCOMPLETE",
                    (),
                ),
            )

        value["capture_state"] = "FAILED"
        assert all(row["capture_state"] == "FAILED" for row in value["denominator_rows"])
        assert all(
            row["cb01"]["failure_digests"] and row["cb01"]["batch_digest"]
            for row in value["denominator_rows"]
        )
        assert all(
            row["capture_reasons"] == ["TEST_TSA_UNAVAILABLE"] for row in value["denominator_rows"]
        )
        failed_index_artifact = repository._publish(value)
        failed_index = repository.replay(failed_index_artifact.digest).to_dict()
        assert all(row["capture_state"] == "FAILED" for row in failed_index["denominator_rows"])
        first_batch = batch_bodies[f"{1:064x}"]
        exact_selection_digest = first_batch["lineage"]["causal_selection"]["selection_digest"]
        first_batch["lineage"]["causal_selection"]["selection_digest"] = "f" * 64
        with pytest.raises(CaptureError, match="exact selected freeze or graph"):
            repository.replay(failed_index_artifact.digest)
        first_batch["lineage"]["causal_selection"]["selection_digest"] = exact_selection_digest
        repository.source_authorizer = _source_authorizer(store, failed_index, withdrawn=True)
        withdrawn_failed = repository.capture_week(
            selected_case.selection_digest,
            prior_index_digest=failed_index_artifact.digest,
            enroll=True,
        )
        withdrawn_failed_value = repository.replay(withdrawn_failed.digest).to_dict()
        assert withdrawn_failed_value["capture_state"] == "WITHDRAWN"
        assert all(
            row["capture_state"] == "FAILED"
            and row["cb01"]["failure_digests"]
            and row["capture_reasons"] == ["TEST_TSA_UNAVAILABLE"]
            for row in withdrawn_failed_value["denominator_rows"]
        )
        missing_value = repository.capture_week(selected_case.selection_digest).to_dict()
        missing_membership = memberships[0]
        missing_rows = [
            row
            for row in missing_value["denominator_rows"]
            if row["membership_id"] == missing_membership
        ]
        missing_batch_digest = "f" * 64
        batch_bodies[missing_batch_digest] = _exact_test_batch_body(
            missing_value, missing_membership, repository
        )
        repository._apply_batch_result(
            missing_value,
            missing_rows,
            BatchResult(missing_batch_digest, None, None, None, (), "INCOMPLETE", ()),
        )
        assert all(row["capture_state"] == "MISSING" for row in missing_rows)
        assert all(row["capture_reasons"] == ["CB01_RESULT_MISSING"] for row in missing_rows)
        missing_index = repository.replay(repository._publish(missing_value).digest).to_dict()
        replayed_missing_rows = [
            row
            for row in missing_index["denominator_rows"]
            if row["membership_id"] == missing_membership
        ]
        assert all(row["capture_state"] == "MISSING" for row in replayed_missing_rows)


def test_f19_outcome_versions_append_to_exact_row_and_preserve_times(
    selected_case: SelectedCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from matchvet.f19 import SettlementRepository

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        initial = repository.capture_week(selected_case.selection_digest)
        value = initial.to_dict()
        row = value["denominator_rows"][0]
        enrollment_digest = "1" * 64
        row["capture_state"] = "ENROLLED"
        row["capture_reasons"] = []
        row["cb01"].update(
            {
                "batch_digest": "2" * 64,
                "enrollment_digest": enrollment_digest,
                "gen_time_utc": "2026-10-09T18:30:00Z",
                "publication_digest": "3" * 64,
                "verification_digest": "4" * 64,
            }
        )
        value["capture_state"] = "ENROLLED"
        current = [repository._publish(value)]
        first_digest = "a" * 64
        corrected_digest = "b" * 64
        evidence_snapshots = {
            first_digest: {
                "evidence_digest": "c" * 64,
                "fixture_status": "FINISHED",
                "observed_at_utc": "2026-11-01T10:02:00+00:00",
                "published_at_utc": "2026-11-01T10:00:00+00:00",
                "record_id": "issue86-unknown-v1",
                "retrieved_at_utc": "2026-11-01T10:04:00+00:00",
                "source_digest": "d" * 64,
                "source_key": "issue86-offline-test-source",
                "source_level": "COMPETITION",
            },
            corrected_digest: {
                "evidence_digest": "e" * 64,
                "fixture_status": "FINISHED",
                "observed_at_utc": "2026-11-01T11:02:00+00:00",
                "published_at_utc": "2026-11-01T11:00:00+00:00",
                "record_id": "issue86-final-v2",
                "retrieved_at_utc": "2026-11-01T11:04:00+00:00",
                "source_digest": "f" * 64,
                "source_key": "issue86-offline-test-source",
                "source_level": "COMPETITION",
            },
        }
        settlements = {
            first_digest: {
                "correction_sequence": 0,
                "evidence": [evidence_snapshots[first_digest]],
                "manifest_digest": row["lineage"]["f16_manifest_digest"],
                "match_result_digest": row["lineage"]["f16_match_result_digest"],
                "preference_id": row["preference_id"],
                "predecessor_digest": None,
                "selection_digest": selected_case.selection_digest,
                "state": "WIN",
            },
            corrected_digest: {
                "correction_sequence": 1,
                "evidence": [evidence_snapshots[corrected_digest]],
                "manifest_digest": row["lineage"]["f16_manifest_digest"],
                "match_result_digest": row["lineage"]["f16_match_result_digest"],
                "preference_id": row["preference_id"],
                "predecessor_digest": first_digest,
                "selection_digest": selected_case.selection_digest,
                "state": "WIN",
            },
        }
        monkeypatch.setattr(
            repository,
            "replay",
            lambda digest: (
                current[0]
                if digest == current[0].digest
                else pytest.fail("Capture attachment requested a different index.")
            ),
        )
        monkeypatch.setattr(
            SettlementRepository,
            "replay",
            lambda _self, digest: SimpleNamespace(to_dict=lambda: settlements[digest]),
        )
        attachment_calls: list[tuple[str, str, str | None]] = []
        attachment_values = {
            first_digest: ("5" * 64, "6" * 64),
            corrected_digest: ("7" * 64, "8" * 64),
        }

        def attach_cb01(
            exact_enrollment: str,
            exact_settlement: str,
            exact_fact_evidence: tuple[str, ...] | None,
            predecessor: str | None,
        ) -> tuple[str, str]:
            assert exact_enrollment == enrollment_digest
            assert exact_fact_evidence is None
            attachment_calls.append((exact_settlement, exact_enrollment, predecessor))
            return attachment_values[exact_settlement]

        monkeypatch.setattr(repository.bootstrap, "attach_outcome", attach_cb01)

        settlements[first_digest]["state"] = "PENDING"
        with pytest.raises(CaptureError, match="post-play outcome"):
            repository.attach_outcome(
                current[0].digest,
                membership_id=row["membership_id"],
                preference_id=row["preference_id"],
                settlement_digest=first_digest,
            )
        settlements[first_digest]["state"] = "WIN"
        settlements[first_digest]["evidence"] = []
        with pytest.raises(CaptureError, match="source-backed evidence"):
            repository.attach_outcome(
                current[0].digest,
                membership_id=row["membership_id"],
                preference_id=row["preference_id"],
                settlement_digest=first_digest,
            )
        settlements[first_digest]["evidence"] = [evidence_snapshots[first_digest]]
        kickoff = datetime.fromisoformat(
            repository._membership_kickoff(value, row["membership_id"]).replace("Z", "+00:00")
        )
        pre_kickoff = dict(evidence_snapshots[first_digest])
        pre_kickoff_time = (kickoff - timedelta(seconds=1)).isoformat()
        for key in ("published_at_utc", "observed_at_utc", "retrieved_at_utc"):
            pre_kickoff[key] = pre_kickoff_time
        settlements[first_digest]["evidence"] = [pre_kickoff]
        with pytest.raises(CaptureError, match="strictly after the controlling kickoff"):
            repository.attach_outcome(
                current[0].digest,
                membership_id=row["membership_id"],
                preference_id=row["preference_id"],
                settlement_digest=first_digest,
            )
        settlements[first_digest]["evidence"] = [evidence_snapshots[first_digest]]

        first = repository.attach_outcome(
            current[0].digest,
            membership_id=row["membership_id"],
            preference_id=row["preference_id"],
            settlement_digest=first_digest,
        )
        original_first = first.to_bytes()
        first_history = first.to_dict()["denominator_rows"][0]["outcome_history"]
        assert first_history[0]["correction_sequence"] == 0
        assert first_history[0]["source_provenance"] == [evidence_snapshots[first_digest]]
        current[0] = first

        second = repository.attach_outcome(
            current[0].digest,
            membership_id=row["membership_id"],
            preference_id=row["preference_id"],
            settlement_digest=corrected_digest,
            predecessor_attachment_digest=first_history[0]["outcome_attachment_digest"],
        )
        second_value = second.to_dict()
        history = second_value["denominator_rows"][0]["outcome_history"]
        assert first.to_bytes() == original_first
        assert [item["correction_sequence"] for item in history] == [0, 1]
        assert (
            history[1]["predecessor_attachment_digest"] == history[0]["outcome_attachment_digest"]
        )
        assert history[1]["source_provenance"] == [evidence_snapshots[corrected_digest]]
        assert second_value["denominator_rows"][0]["outcome_state"] == "PRESENT"
        assert attachment_calls == [
            (first_digest, enrollment_digest, None),
            (corrected_digest, enrollment_digest, history[0]["outcome_attachment_digest"]),
        ]
        with pytest.raises(CaptureError, match="never latest"):
            repository.attach_outcome(
                second.digest,
                membership_id=row["membership_id"],
                preference_id=row["preference_id"],
                settlement_digest="latest",
            )

        def cb01_body(digest: str, kind: str) -> dict[str, Any]:
            if kind == "OutcomeAttachment":
                sequence = 0 if digest == history[0]["outcome_attachment_digest"] else 1
                return {
                    "correction_sequence": sequence,
                    "enrollment_digest": enrollment_digest,
                    "fact_attachment_digest": history[sequence]["fact_attachment_digest"],
                    "predecessor_digest": (
                        history[sequence - 1]["outcome_attachment_digest"] if sequence else None
                    ),
                    "settlement_digest": history[sequence]["settlement_digest"],
                }
            if kind == "OutcomeFactAttachment":
                sequence = 0 if digest == history[0]["fact_attachment_digest"] else 1
                return {
                    "correction_sequence": sequence,
                    "enrollment_digest": enrollment_digest,
                    "predecessor_digest": (
                        history[sequence - 1]["fact_attachment_digest"] if sequence else None
                    ),
                    "settlement_digest": history[sequence]["settlement_digest"],
                }
            raise AssertionError(f"Unexpected CB01 fixture kind: {kind}")

        monkeypatch.setattr(repository, "_cb01_body", cb01_body)
        repository._verify_outcomes(
            second_value,
            second_value["denominator_rows"][0],
            ((row["preference_id"], enrollment_digest, {}),),
        )
        settlements[corrected_digest]["state"] = "PENDING"
        with pytest.raises(CaptureError, match="post-play outcome"):
            repository._verify_outcomes(
                second_value,
                second_value["denominator_rows"][0],
                ((row["preference_id"], enrollment_digest, {}),),
            )
        settlements[corrected_digest]["state"] = "WIN"
        settlements[corrected_digest]["evidence"] = [pre_kickoff]
        with pytest.raises(CaptureError, match="strictly after the controlling kickoff"):
            repository._verify_outcomes(
                second_value,
                second_value["denominator_rows"][0],
                ((row["preference_id"], enrollment_digest, {}),),
            )

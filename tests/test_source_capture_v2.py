"""Exact selected-graph source authorization over retained #86 fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from source_authorization_support import SourceOwner, graph_manifest, projection_entries
from test_research_capture import (
    SelectedCase,
)
from test_research_capture import (
    authority as authority,
)
from test_research_capture import (
    forbid_network as forbid_network,
)
from test_research_capture import (
    selected_case as selected_case,
)
from test_research_capture import (
    selected_source as selected_source,
)
from test_research_capture import (
    successor_week as successor_week,
)

from matchvet.artifacts import ArtifactError, ArtifactStore
from matchvet.research_capture import CaptureError, ResearchCaptureRepository
from matchvet.source_authorization import SourceAuthorizationRepository, replay_decision
from matchvet.source_manifest import (
    MANIFEST_MEDIA_TYPE,
    SourceAuthorizationError,
    canonical,
    read,
    retain_manifest,
    selected_projection,
    verify_manifest,
)
from matchvet.store import Store, open_store


def test_selected_graph_attribution_only_approval_refuses_continuation(
    selected_case: SelectedCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        projection = selected_projection(store, selected_case.selection_digest)
        entries = projection_entries(store, projection)
        for classification in entries:
            classification["requested_operations"] = ["ATTRIBUTION"]
        manifest = retain_manifest(
            store,
            stage="SELECTED_GRAPH",
            selection_digest=selected_case.selection_digest,
            projection=projection,
            entries=entries,
        )
        owner = SourceOwner(tmp_path / "owner", store, monkeypatch)
        owner.append(manifest)
        repository = ResearchCaptureRepository(store)
        initial = repository.capture_week(selected_case.selection_digest)
        with pytest.raises(CaptureError, match="authorization"):
            repository.capture_week(
                selected_case.selection_digest,
                prior_index_digest=initial.digest,
                enroll=True,
                source_manifest_digest=manifest,
            )
        from matchvet.cb01_schema import MEDIA_TYPES

        assert all(
            item.media_type != MEDIA_TYPES["TimestampAttempt"] for item in store.artifact_catalog()
        )


def test_exact_selected_manifest_replay_and_new_v2_withdrawal(
    selected_case: SelectedCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        manifest_digest = graph_manifest(store, selected_case.selection_digest)
        manifest = verify_manifest(store, manifest_digest)
        dependency_ids = {row["id"] for row in manifest["projection"]["dependencies"]}
        assert any(identity.startswith("source_captures:") for identity in dependency_ids)
        assert any(identity.startswith("source_assertions:") for identity in dependency_ids)
        assert any(identity.startswith("fixture_revisions:") for identity in dependency_ids)
        assert [row["dependency_id"] for row in manifest["entries"]] == sorted(dependency_ids)
        retained = ArtifactStore(store).read_artifact(manifest_digest)
        owner = SourceOwner(tmp_path / "source-owner", store, monkeypatch)
        owner.append(manifest_digest)
        authority = SourceAuthorizationRepository(store)
        decision_digest = authority.authorize(manifest_digest)
        repository = ResearchCaptureRepository(store)
        initial = repository.capture_week(selected_case.selection_digest)
        owner.withdraw(manifest_digest)
        withdrawn = repository.capture_week(
            selected_case.selection_digest,
            prior_index_digest=initial.digest,
            enroll=True,
            source_manifest_digest=manifest_digest,
        )
        assert withdrawn.to_dict()["contract"] == "research-capture-index-v2"
        assert withdrawn.to_dict()["source_use"]["manifest_digest"] == manifest_digest
        assert all(
            row["capture_state"] == "WITHDRAWN" for row in withdrawn.to_dict()["denominator_rows"]
        )
        assert ArtifactStore(store).read_artifact(manifest_digest) == retained
        monkeypatch.setattr(
            "matchvet.source_authorization._checkpoint",
            lambda *_a: pytest.fail("Historical replay contacted current service"),
        )
        assert repository.replay(withdrawn.digest).to_bytes() == withdrawn.to_bytes()
        assert repository.replay(initial.digest).to_bytes() == initial.to_bytes()
        assert replay_decision(store, decision_digest)["state"] == "APPROVED"


@pytest.mark.parametrize(
    "mutation", ["graph", "dependency", "omission", "extra", "raw", "normalized", "time"]
)
def test_selected_manifest_mismatch_refuses(
    mutation: str,
    selected_case: SelectedCase,
) -> None:
    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        original = graph_manifest(store, selected_case.selection_digest)
        value = read(store, original, MANIFEST_MEDIA_TYPE)
        if mutation == "graph":
            value["projection"]["f16_manifest_digest"] = "0" * 64
        if mutation == "dependency":
            value["projection"]["dependencies"][0]["digest"] = "0" * 64
        if mutation == "omission":
            value["entries"].pop()
        if mutation == "extra":
            value["entries"].append(
                dict(value["entries"][-1], dependency_id="unselected-store-source")
            )
        if mutation in {"raw", "normalized"}:
            value["entries"][0][mutation + "_identity"]["digest"] = "UNKNOWN"
        if mutation == "time":
            capture = next(
                item
                for item in value["entries"]
                if item["dependency_id"].startswith("source_captures:")
            )
            capture["retrieved_at"] = "UNKNOWN"
        altered = (
            ArtifactStore(store).publish_artifact(canonical(value), MANIFEST_MEDIA_TYPE).digest
        )
        with pytest.raises(SourceAuthorizationError):
            verify_manifest(store, altered)


def test_caller_v1_authorizer_cannot_continue_without_v2_authority(
    selected_case: SelectedCase,
) -> None:
    from test_research_capture import _source_authorizer

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        initial = repository.capture_week(selected_case.selection_digest)
        caller = _source_authorizer(store, initial.to_dict())
        repository.source_authorizer = caller
        with pytest.raises(CaptureError):
            repository.capture_week(
                selected_case.selection_digest, prior_index_digest=initial.digest, enroll=True
            )
        assert caller.calls == []
        manifest_digest = graph_manifest(store, selected_case.selection_digest)
        with pytest.raises(CaptureError):
            repository.capture_week(
                selected_case.selection_digest,
                prior_index_digest=initial.digest,
                enroll=True,
                source_manifest_digest=manifest_digest,
            )


def test_v1_decision_reader_preserves_exact_historical_bytes(selected_case: SelectedCase) -> None:
    from test_research_capture import _source_authorizer

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        repository = ResearchCaptureRepository(store)
        initial = repository.capture_week(selected_case.selection_digest)
        value = initial.to_dict()
        legacy = _source_authorizer(store, value, withdrawn=True)
        raw = ArtifactStore(store).read_artifact(legacy.decision.decision_digest)
        assert set(json.loads(raw)) == {
            "contract",
            "freeze_digest",
            "profile_digest",
            "reason_codes",
            "scope_ids",
            "selection_digest",
            "state",
        }
        value["source_use"] = {
            "decision_digest": legacy.decision.decision_digest,
            "reason_codes": list(legacy.decision.reason_codes),
            "state": "WITHDRAWN",
        }
        value["capture_state"] = "WITHDRAWN"
        for row in value["denominator_rows"]:
            row["capture_state"] = "WITHDRAWN"
            row["capture_reasons"] = list(legacy.decision.reason_codes)
        historical = repository._publish(value)
        assert repository.replay(historical.digest).to_bytes() == historical.to_bytes()
        assert ArtifactStore(store).read_artifact(legacy.decision.decision_digest) == raw


@pytest.mark.parametrize(
    "withdrawal", ["NONE", "REFRESH", "SUBMIT", "DISPATCH_VALIDATION", "ADMISSION_VALIDATION"]
)
def test_v2_continuation_checks_dispatch_and_protected_cb01_admission(
    withdrawal: str,
    selected_case: SelectedCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.cb01 import BootstrapRepository
    from matchvet.cb01_schema import MEDIA_TYPES
    from matchvet.cb01_sources import (
        FixtureEnrollmentInput,
        PreparedSources,
        prepare_fixture_sources,
    )
    from matchvet.cb01_trust import TimestampTransport, TrustRefresh

    with open_store(selected_case.root / "store.sqlite3", private_root=selected_case.root) as store:
        manifest_digest = graph_manifest(store, selected_case.selection_digest)
        owner = SourceOwner(tmp_path / "source-owner", store, monkeypatch)
        owner.append(manifest_digest)

        # Exact graph replay is exercised above. This test targets fresh authority
        # at real CB01 boundaries; its retained input graph is immutable throughout.
        projection = verify_manifest(store, manifest_digest)["projection"]

        def retained_projection(retained_store: Store, selection_digest: str) -> dict[str, Any]:
            assert retained_store.path == store.path
            assert selection_digest == selected_case.selection_digest
            return dict(projection)

        monkeypatch.setattr("matchvet.source_manifest.selected_projection", retained_projection)

        prepared_cache: dict[FixtureEnrollmentInput, PreparedSources] = {}

        def retained_preparation(
            retained_store: Store,
            request: FixtureEnrollmentInput,
            *,
            historical_inspection: bool = False,
        ) -> PreparedSources:
            assert retained_store.path == store.path
            if request not in prepared_cache:
                prepared_cache[request] = prepare_fixture_sources(
                    retained_store, request, historical_inspection=historical_inspection
                )
            return prepared_cache[request]

        monkeypatch.setattr("matchvet.cb01.prepare_fixture_sources", retained_preparation)
        monkeypatch.setattr("matchvet.cb01_sources.prepare_fixture_sources", retained_preparation)

        class WithdrawalWitness(DeterministicWitnessBackend):
            def refresh_trust(self, policy_body: dict[str, Any]) -> TrustRefresh:
                result = super().refresh_trust(policy_body)
                if withdrawal == "REFRESH":
                    owner.withdraw(manifest_digest)
                return result

            def submit_request(
                self, request_der: bytes, policy_body: dict[str, Any]
            ) -> TimestampTransport:
                result = super().submit_request(request_der, policy_body)
                if withdrawal == "SUBMIT":
                    owner.withdraw(manifest_digest)
                return result

        witness = WithdrawalWitness(transport_states=("UNAVAILABLE",))
        bootstrap = BootstrapRepository(store, witness_backend=witness)
        if withdrawal in {"DISPATCH_VALIDATION", "ADMISSION_VALIDATION"}:
            pending_validation: list[int] = []

            def withdraw_during_validation(
                retained_store: Store, identity: str, *, historical_inspection: bool = False
            ) -> dict[str, Any]:
                result = verify_manifest(
                    retained_store, identity, historical_inspection=historical_inspection
                )
                if pending_validation and owner.calls == pending_validation[0]:
                    pending_validation.clear()
                    owner.withdraw(manifest_digest)
                return result

            monkeypatch.setattr(
                "matchvet.source_authorization.verify_manifest", withdraw_during_validation
            )
            if withdrawal == "DISPATCH_VALIDATION":
                original_trust = bootstrap._load_attempt_trust

                def dispatch_ready(*args: Any, **kwargs: Any) -> Any:
                    result = original_trust(*args, **kwargs)
                    pending_validation.append(owner.calls)
                    return result

                monkeypatch.setattr(bootstrap, "_load_attempt_trust", dispatch_ready)
            else:
                from matchvet.artifacts import ArtifactRecord

                original_publish = ArtifactStore._publish_object

                def staged_result(
                    artifacts: ArtifactStore, content: bytes, record: ArtifactRecord
                ) -> None:
                    original_publish(artifacts, content, record)
                    if record.media_type == MEDIA_TYPES["TimestampAttemptResult"]:
                        # One guard after staging, then the guard inside catalog
                        # insertion. Withdraw during validation of the latter.
                        pending_validation.append(owner.calls + 1)

                monkeypatch.setattr(ArtifactStore, "_publish_object", staged_result)
        repository = ResearchCaptureRepository(store, bootstrap=bootstrap)
        initial = repository.capture_week(selected_case.selection_digest)
        if withdrawal == "NONE":
            result = repository.capture_week(
                selected_case.selection_digest,
                prior_index_digest=initial.digest,
                enroll=True,
                source_manifest_digest=manifest_digest,
            )
            value = result.to_dict()
            assert value["source_use"]["state"] == "APPROVED"
            assert value["contract"] == "research-capture-index-v2"
            assert value["denominator"] == initial.to_dict()["denominator"]
            assert all(row["capture_state"] == "FAILED" for row in value["denominator_rows"])
            assert repository.replay(result.digest).to_bytes() == result.to_bytes()
        else:
            with pytest.raises((SourceAuthorizationError, CaptureError, ValueError, ArtifactError)):
                repository.capture_week(
                    selected_case.selection_digest,
                    prior_index_digest=initial.digest,
                    enroll=True,
                    source_manifest_digest=manifest_digest,
                )
            assert all(
                item.media_type != MEDIA_TYPES["TimestampAttemptResult"]
                for item in store.artifact_catalog()
            )
        expected_requests = (
            len(initial.to_dict()["denominator_rows"])
            if withdrawal == "NONE"
            else 0
            if withdrawal in {"REFRESH", "DISPATCH_VALIDATION"}
            else 1
        )
        assert witness.request_count == expected_requests

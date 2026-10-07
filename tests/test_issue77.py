from __future__ import annotations

import json
import shutil
import socket
from collections.abc import Generator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from issue77_support import RetainedWitness
from matchweek_research_support import Clock
from test_matchweek_membership import _persistable_schedule_assessment
from test_matchweek_research import Graph, Qualified
from test_matchweek_research import graph as graph
from test_matchweek_research import qualified as qualified
from test_matchweek_research import research_store as research_store
from test_matchweek_research import selected_store as selected_store

from matchvet.artifacts import ArtifactStore
from matchvet.cb01 import BootstrapRepository
from matchvet.cb01_evaluation import CB01EvaluationError, MatchweekEvaluationRepository
from matchvet.cb01_schema import MEDIA_TYPES, decode_artifact, encode_artifact
from matchvet.cb01_sources import (
    CB01SourceError,
    FixtureEnrollmentInput,
    prepare_fixture_sources,
)
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import F16MatchweekProcessor
from matchvet.f19 import F19Error, SettlementRepository, SettlementState
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import CORRECTED_RULE, MatchweekResearchRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import Store, StoreBusyError, open_store
from matchvet.t10 import SettlementEvidence
from matchvet.t15 import PolicyVersion


def _request(store: Store, graph: Graph) -> FixtureEnrollmentInput:
    manifest = F16MatchweekProcessor(store).replay_manifest(graph.f16)
    row = manifest.match_results[0]
    return FixtureEnrollmentInput(
        graph.freeze,
        row.membership_id,
        row.cutoff_id,
        manifest.to_dict()["profile_digest"],
        graph.f16,
    )


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Issue 77 tests forbid network access.")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@dataclass(frozen=True)
class Slate:
    root: Path
    freeze_digest: str
    policy: str
    profile: str
    selection: str
    requests: tuple[FixtureEnrollmentInput, ...]


@pytest.fixture(scope="module")
def slate(tmp_path_factory: pytest.TempPathFactory) -> Slate:
    root = tmp_path_factory.mktemp("issue77-slate")
    with open_store(root / "store.sqlite3", private_root=root) as store:
        assessment = _persistable_schedule_assessment(
            store,
            root,
            (
                ("2026-09-25", "20:00", "Friday United", "Friday City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 14, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        cutoffs = MatchEvidenceCutoffRepository(store)
        policy = cutoffs.persist_policy(CutoffPolicy("issue77", "1", 21600, rule=CORRECTED_RULE))
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, policy)
        profile = PreferenceProfileRepository(store).build_profile(
            ("match_winner_home", "asian_handicap_home_0_0")
        )
        result = F16MatchweekProcessor(store, clock=Clock()).process_phase(
            WorkContext(
                "issue77",
                "issue77",
                "2026-09-25",
                RunPhase.PREFERENCE_VETTING,
                1,
                "RESEARCH_ONLY",
                "0" * 64,
                "0" * 64,
                1,
            ),
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=policy,
            cutoff_ids=tuple(sorted(item.cutoff_id for item in boundaries)),
            profile_digest=profile.digest,
            policy=PolicyVersion(version="research-policy-v1"),
        )
        selected = MatchweekResearchRepository(store, clock=Clock()).seal_completed(
            result.result_digest
        )
        kickoffs = {
            item.membership_id: item.controlling_revision.kickoff_utc for item in freeze.memberships
        }
        requests = tuple(
            FixtureEnrollmentInput(
                freeze.freeze_id,
                item.membership_id,
                item.cutoff_id,
                profile.digest,
                result.result_digest,
            )
            for item in sorted(boundaries, key=lambda row: kickoffs[row.membership_id] or "")
        )
    return Slate(root, freeze.freeze_digest, policy, profile.digest, selected.digest, requests)


@pytest.fixture
def slate_store(slate: Slate, tmp_path: Path) -> Generator[Store]:
    shutil.copytree(slate.root / "objects", tmp_path / "objects")
    shutil.copyfile(slate.root / "store.sqlite3", tmp_path / "store.sqlite3")
    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        yield store


def test_corrected_cb01_preparation_requires_qualified_selection(
    research_store: Store, graph: Graph
) -> None:
    before = research_store.artifact_catalog()
    with pytest.raises(CB01SourceError, match="selected"):
        prepare_fixture_sources(research_store, _request(research_store, graph))
    assert research_store.artifact_catalog() == before


def test_corrected_f19_cannot_settle_an_unselected_candidate(
    research_store: Store, graph: Graph
) -> None:
    manifest = F16MatchweekProcessor(research_store).replay_manifest(graph.f16)
    with pytest.raises(F19Error, match="selected"):
        SettlementRepository(research_store).build(
            graph.f16, manifest.match_results[0].match_result_digest, "match_winner_home", ()
        )


def test_corrected_denominator_exists_without_f16_selection_or_attempts(tmp_path: Path) -> None:
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository

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
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 14, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        profile = PreferenceProfileRepository(store).build_profile(
            ("match_winner_home", "asian_handicap_home_0_0")
        )
        policy = MatchEvidenceCutoffRepository(store).persist_policy(
            CutoffPolicy("issue77", "1", 21600, rule=CORRECTED_RULE)
        )
        view = MatchweekEvaluationRepository(store).inspect_cohort(
            freeze.freeze_digest, profile.digest, policy
        )
        assert len(view.denominator.rows) == 4
        assert view.included_count == 4
        assert view.cases == ()
        assert view.selection is None
        assert {row.state for row in view.denominator.rows} == {"INCOMPLETE_FOR_NOT_ATTEMPTED"}
        assert all(
            "MATCHWEEK_SELECTION_UNAVAILABLE" in row.reasons for row in view.denominator.rows
        )
        assert all("EXACT_F07_BOUNDARY_UNAVAILABLE" in row.reasons for row in view.denominator.rows)


def test_corrected_evaluation_binds_one_exact_selected_origin(
    selected_store: Store, graph: Graph, qualified: Qualified
) -> None:
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository

    request = _request(selected_store, graph)
    prepared = prepare_fixture_sources(selected_store, request)
    view = MatchweekEvaluationRepository(selected_store).inspect_cohort(
        prepared.freeze.freeze_digest,
        request.profile_digest,
        graph.policy,
        selection_digest=qualified.selection,
    )
    assert view.selection is not None and view.selection.digest == qualified.selection
    assert view.selection.f16_manifest_digest == graph.f16
    assert view.common_cutoff_utc == "2026-09-25T13:00:00.000000+00:00"
    assert view.cohort == "CORRECTED_MATCHWEEK"
    assert view.chronology_version == "0.2.0"
    assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in view.denominator.rows)


def test_corrected_receipt_qualifies_without_hiding_unattempted_preferences(
    slate_store: Store, slate: Slate
) -> None:
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository

    backend = RetainedWitness()
    result = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    assert result.publication_digest is not None
    view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_publication_digests=(result.publication_digest,),
    )
    assert view.included_count == len(view.denominator.rows) == 4
    assert len(view.cases) == 1
    assert sum(row.state == "ENROLLED_LIVE" for row in view.denominator.rows) == 2
    assert sum(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in view.denominator.rows) == 2
    assert backend.request_count == 1


def test_corrected_chronology_has_one_shared_origin_across_fixture_kickoffs(
    slate_store: Store, slate: Slate
) -> None:
    boundaries = MatchEvidenceCutoffRepository(slate_store).replay_for_freeze(
        slate.requests[0].freeze_id, slate.policy
    )
    assert len(boundaries) == 2
    assert {row.cutoff_at_utc for row in boundaries} == {"2026-09-25T13:00:00.000000+00:00"}
    freeze = MatchweekMembershipRepository(slate_store).get_by_id(slate.requests[0].freeze_id)
    assert freeze is not None
    assert len({row.controlling_revision.kickoff_utc for row in freeze.memberships}) == 2
    view = MatchweekEvaluationRepository(slate_store).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
    )
    assert view.common_cutoff_utc == boundaries[0].cutoff_at_utc
    assert view.chronology_version == "0.2.0" and view.cohort == "CORRECTED_MATCHWEEK"


def test_evaluation_is_read_only_and_never_repairs_missing_enrollment(
    slate_store: Store, slate: Slate, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = RetainedWitness()
    enrolled = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    assert enrolled.publication_digest is not None
    before = slate_store.artifact_catalog()

    def forbid(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Evaluation must never publish artifacts.")

    monkeypatch.setattr(ArtifactStore, "publish_artifact", forbid)
    monkeypatch.setattr(slate_store, "transaction", forbid)
    repository = MatchweekEvaluationRepository(slate_store, witness_backend=backend)
    view = repository.inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_publication_digests=(enrolled.publication_digest,),
    )
    assert view.included_count == 4 and len(view.cases) == 1
    digest = enrolled.rows[0].enrollment_digest
    assert digest is not None
    metadata = slate_store.artifact_metadata(digest)
    assert metadata is not None
    path = slate_store.path.parent / metadata.relative_path
    path.unlink()
    with pytest.raises(CB01EvaluationError) as refused:
        repository.inspect_cohort(
            slate.freeze_digest,
            slate.profile,
            slate.policy,
            selection_digest=slate.selection,
            exact_publication_digests=(enrolled.publication_digest,),
        )
    assert refused.value.denominator is not None and len(refused.value.denominator.rows) == 4
    assert not path.exists() and slate_store.artifact_catalog() == before


def test_successful_retry_keeps_exact_failed_attempt_history(
    slate_store: Store, slate: Slate
) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE", "RECEIVED"))
    repository = BootstrapRepository(slate_store, witness_backend=backend)
    failed = repository.enroll_fixture(slate.requests[0])
    assert failed.attempt_digest is not None
    enrolled = repository.resume(failed.batch_digest, failed.attempt_digest, retry_failed=True)
    assert enrolled.publication_digest is not None and enrolled.attempt_digest is not None
    first = json.loads(ArtifactStore(slate_store).read_artifact(failed.attempt_digest))["body"]
    second = json.loads(ArtifactStore(slate_store).read_artifact(enrolled.attempt_digest))["body"]
    assert first["nonce_hex"] != second["nonce_hex"]
    view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_publication_digests=(enrolled.publication_digest,),
    )
    assert view.included_count == 4
    assert all(
        row.failure_digests == failed.failure_digests
        for row in view.denominator.rows
        if row.membership_id == slate.requests[0].membership_id
    )


def test_f19_supported_writers_cannot_fork_concurrently(slate_store: Store) -> None:
    with pytest.raises(StoreBusyError):
        open_store(slate_store.path, private_root=slate_store.path.parent)


def test_failed_witness_keeps_the_complete_denominator(slate_store: Store, slate: Slate) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE",))
    result = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    assert result.publication_digest is None and result.failure_digests
    view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
    )
    assert view.included_count == 4
    assert sum(row.state == "INCOMPLETE" for row in view.denominator.rows) == 2
    assert sum(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in view.denominator.rows) == 2
    assert all(
        row.failure_digests == result.failure_digests
        for row in view.denominator.rows
        if row.membership_id == slate.requests[0].membership_id
    )
    assert view.cases == ()


@pytest.mark.parametrize(
    "tamper",
    ["membership", "manifest", "batch_preferences", "failure_preferences", "verified", "entry"],
)
def test_failure_requires_exact_selected_batch_replay(
    slate_store: Store, slate: Slate, tamper: str
) -> None:
    backend = RetainedWitness(transport_states=() if tamper == "verified" else ("UNAVAILABLE",))
    failed = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    artifacts = ArtifactStore(slate_store)
    batch = decode_artifact(artifacts.read_artifact(failed.batch_digest))[1]
    if tamper == "membership":
        batch["anchor"]["membership"]["id"] = slate.requests[1].membership_id
    elif tamper == "manifest":
        batch["lineage"]["f16_manifest"]["digest"] = "f" * 64
    elif tamper == "batch_preferences":
        batch["expected_preference_ids"] = batch["expected_preference_ids"][:1]
        batch["entries"] = batch["entries"][:1]
    elif tamper == "entry":
        batch["entries"][0]["disposition"] = "INCOMPLETE"
    forged_batch = artifacts.publish_artifact(
        encode_artifact("FixtureEnrollmentBatch", batch), MEDIA_TYPES["FixtureEnrollmentBatch"]
    ).digest
    if tamper == "verified":
        assert failed.verification_digest is not None
        verification = decode_artifact(artifacts.read_artifact(failed.verification_digest))[1]
        failure = {
            "batch_digest": failed.batch_digest,
            "attempt_digest": failed.attempt_digest,
            "attempt_result_digest": verification["attempt_result_digest"],
            "verification_digest": failed.verification_digest,
            "expected_preference_ids": batch["expected_preference_ids"],
            "reasons": ["RFC3161_SIGNATURE_INVALID"],
        }
    else:
        failure = decode_artifact(artifacts.read_artifact(failed.failure_digests[0]))[1]
    failure["batch_digest"] = forged_batch
    if tamper == "batch_preferences":
        failure["expected_preference_ids"] = batch["expected_preference_ids"]
    elif tamper == "failure_preferences":
        failure["expected_preference_ids"] = failure["expected_preference_ids"][:1]
    forged_failure = artifacts.publish_artifact(
        encode_artifact("TimestampFailure", failure), MEDIA_TYPES["TimestampFailure"]
    ).digest
    view = MatchweekEvaluationRepository(slate_store).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
    )
    assert view.included_count == 4
    assert forged_failure in view.unavailable_failure_digests
    assert all(forged_failure not in row.failure_digests for row in view.denominator.rows)
    assert all(
        row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED"
        for row in view.denominator.rows
        if row.membership_id == slate.requests[1].membership_id
    )


def test_legacy_failure_cannot_mark_a_corrected_case_as_attempted(
    slate_store: Store, slate: Slate
) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE",))
    cutoffs = MatchEvidenceCutoffRepository(slate_store)
    legacy = cutoffs.persist_policy(CutoffPolicy("legacy-per-match", "1", 21600))
    boundary = next(
        row
        for row in cutoffs.persist_for_freeze(slate.requests[0].freeze_id, legacy)
        if row.membership_id == slate.requests[0].membership_id
    )
    request = replace(slate.requests[0], cutoff_id=boundary.cutoff_id, f16_manifest_digest=None)
    result = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(request)
    assert result.failure_digests
    view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
    )
    assert view.included_count == 4
    assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in view.denominator.rows)
    assert all(row.failure_digests == () for row in view.denominator.rows)


def test_missing_legacy_cutoff_cannot_import_failure_into_corrected_cohort(
    slate_store: Store, slate: Slate
) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE",))
    cutoffs = MatchEvidenceCutoffRepository(slate_store)
    legacy = cutoffs.persist_policy(CutoffPolicy("legacy-per-match", "1", 21600))
    boundary = next(
        row
        for row in cutoffs.persist_for_freeze(slate.requests[0].freeze_id, legacy)
        if row.membership_id == slate.requests[0].membership_id
    )
    failed = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        replace(slate.requests[0], cutoff_id=boundary.cutoff_id, f16_manifest_digest=None)
    )
    metadata = slate_store.artifact_metadata(boundary.digest.removeprefix("sha256:"))
    assert metadata is not None
    (slate_store.path.parent / metadata.relative_path).unlink()
    view = MatchweekEvaluationRepository(slate_store).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
    )
    assert view.included_count == 4
    assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in view.denominator.rows)
    assert all(not row.failure_digests for row in view.denominator.rows)
    assert set(failed.failure_digests) <= set(view.unavailable_failure_digests)


def test_denominator_survives_missing_selected_f16(slate_store: Store, slate: Slate) -> None:
    manifest = slate.requests[0].f16_manifest_digest
    assert manifest is not None
    metadata = slate_store.artifact_metadata(manifest)
    assert metadata is not None
    path = slate_store.path.parent / metadata.relative_path
    path.unlink()
    repository = MatchweekEvaluationRepository(slate_store)
    unavailable = repository.inspect_cohort(slate.freeze_digest, slate.profile, slate.policy)
    assert unavailable.included_count == 4 and len(unavailable.denominator.rows) == 4
    assert unavailable.cases == ()
    assert all(row.enrollment_digest is None for row in unavailable.denominator.rows)
    with pytest.raises(CB01EvaluationError, match="selected") as refused:
        repository.inspect_cohort(
            slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
        )
    assert refused.value.denominator == repository.inspect_denominator(
        slate.freeze_digest, slate.profile
    )
    assert refused.value.denominator is not None and len(refused.value.denominator.rows) == 4
    assert not path.exists()


def test_failed_witness_denominator_survives_missing_cutoff_lineage(
    slate_store: Store, slate: Slate
) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE",))
    failed = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    cutoff_digest = slate.requests[0].cutoff_id.removeprefix("f07:")
    metadata = slate_store.artifact_metadata(cutoff_digest)
    assert metadata is not None
    (slate_store.path.parent / metadata.relative_path).unlink()
    view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy
    )
    assert view.included_count == 4
    assert view.selection is None and view.cases == ()
    assert all(row.enrollment_digest is None for row in view.denominator.rows)
    assert set(failed.failure_digests) <= set(view.unavailable_failure_digests)
    assert all(not row.failure_digests for row in view.denominator.rows)


@pytest.mark.parametrize("missing", ["failure", "batch"])
def test_unreadable_failure_cannot_prevent_denominator(
    slate_store: Store, slate: Slate, missing: str
) -> None:
    backend = RetainedWitness(transport_states=("UNAVAILABLE",))
    failed = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[0]
    )
    digest = failed.failure_digests[0] if missing == "failure" else failed.batch_digest
    metadata = slate_store.artifact_metadata(digest)
    assert metadata is not None
    (slate_store.path.parent / metadata.relative_path).unlink()
    view = MatchweekEvaluationRepository(slate_store).inspect_cohort(
        slate.freeze_digest, slate.profile, slate.policy
    )
    assert view.included_count == len(view.denominator.rows) == 4
    assert view.cases == ()
    assert failed.failure_digests[0] in view.catalog_unavailable_failure_digests
    assert all(not row.failure_digests for row in view.denominator.rows)


@pytest.mark.parametrize(
    "fixture,gen_time,qualifies",
    [
        (0, "2026-09-25T12:59:59.9999999Z", False),
        (0, "2026-09-25T13:00:00Z", False),
        (0, "2026-09-25T13:00:00.0000001Z", True),
        (0, "2026-09-25T18:59:59.9999999Z", True),
        (0, "2026-09-25T19:00:00Z", False),
        (1, "2026-09-25T19:00:00.0000001Z", True),
        (1, "2026-09-28T19:00:00Z", False),
        (1, "2026-09-28T19:00:00.0000001Z", False),
    ],
)
def test_corrected_witness_uses_strict_common_t_and_own_kickoff(
    slate_store: Store, slate: Slate, fixture: int, gen_time: str, qualifies: bool
) -> None:
    backend = RetainedWitness(gen_time_utc=gen_time)
    result = BootstrapRepository(slate_store, witness_backend=backend).enroll_fixture(
        slate.requests[fixture]
    )
    assert (result.publication_digest is not None) is qualifies
    if qualifies:
        assert len(result.rows) == 2
    if not qualifies:
        assert result.rows == ()  # Historical BatchResult; denominator is independent.
        view = MatchweekEvaluationRepository(slate_store, witness_backend=backend).inspect_cohort(
            slate.freeze_digest, slate.profile, slate.policy, selection_digest=slate.selection
        )
        assert view.included_count == 4
        assert {row.state for row in view.denominator.rows} <= {
            "INCOMPLETE",
            "INCOMPLETE_FOR_NOT_ATTEMPTED",
        }


@pytest.mark.parametrize(
    "variant", ["missing_f16", "other_f16", "profile", "policy", "T", "freeze"]
)
def test_corrected_cb01_refuses_mixed_exact_identities(
    selected_store: Store, graph: Graph, variant: str
) -> None:
    request = _request(selected_store, graph)
    if variant == "missing_f16":
        request = replace(request, f16_manifest_digest=None)
    elif variant == "other_f16":
        request = replace(request, f16_manifest_digest="0" * 64)
    elif variant == "profile":
        profile = PreferenceProfileRepository(selected_store).build_profile(
            ("match_winner_home",), profile_version="different-exact-profile"
        )
        request = replace(request, profile_digest=profile.digest)
    elif variant == "freeze":
        request = replace(request, freeze_id="sha256:" + "0" * 64)
    else:
        repository = MatchEvidenceCutoffRepository(selected_store)
        policy = repository.persist_policy(
            CutoffPolicy(
                "alternate-exact-policy",
                variant,
                21600 if variant == "policy" else 21601,
                rule=CORRECTED_RULE,
            )
        )
        boundary = repository.persist_for_freeze(request.freeze_id, policy)[0]
        request = replace(request, cutoff_id=boundary.cutoff_id)
    with pytest.raises(CB01SourceError):
        prepare_fixture_sources(selected_store, request)


def test_corrected_evaluation_refuses_legacy_policy_even_with_equal_t(
    slate_store: Store, slate: Slate
) -> None:
    legacy = MatchEvidenceCutoffRepository(slate_store).persist_policy(
        CutoffPolicy("legacy-per-match", "1", 21600)
    )
    boundaries = MatchEvidenceCutoffRepository(slate_store).persist_for_freeze(
        slate.requests[0].freeze_id, legacy
    )
    assert "2026-09-25T13:00:00.000000+00:00" in {row.cutoff_at_utc for row in boundaries}
    with pytest.raises(CB01EvaluationError, match="Legacy"):
        MatchweekEvaluationRepository(slate_store).inspect_cohort(
            slate.freeze_digest, slate.profile, legacy, selection_digest=slate.selection
        )


def test_corrected_evaluation_refuses_a_receipt_digest_as_selection(
    selected_store: Store, graph: Graph, qualified: Qualified
) -> None:
    request = _request(selected_store, graph)
    freeze = MatchweekMembershipRepository(selected_store).get_by_id(graph.freeze)
    assert freeze is not None
    with pytest.raises(CB01EvaluationError, match="selected"):
        MatchweekEvaluationRepository(selected_store).inspect_cohort(
            freeze.freeze_digest,
            request.profile_digest,
            graph.policy,
            selection_digest=qualified.receipt,
        )


def test_valid_alternate_f16_cannot_qualify_cb01_or_f19(
    research_store: Store, graph: Graph, tmp_path: Path
) -> None:
    root = tmp_path / "alternate"
    root.mkdir()
    shutil.copytree(graph.inputs_root / "objects", root / "objects")
    shutil.copyfile(graph.inputs_root / "store.sqlite3", root / "store.sqlite3")
    with open_store(root / "store.sqlite3", private_root=root) as alternative:
        profile = PreferenceProfileRepository(alternative).build_profile(
            ("match_winner_home",), profile_version="alternate-exact-profile"
        )
        boundaries = MatchEvidenceCutoffRepository(alternative).replay_for_freeze(
            graph.freeze, graph.policy
        )
        result = F16MatchweekProcessor(alternative, clock=Clock()).process_phase(
            WorkContext(
                "alternative",
                "alternative",
                "2026-09-25",
                RunPhase.PREFERENCE_VETTING,
                1,
                "RESEARCH_ONLY",
                "0" * 64,
                "0" * 64,
                1,
            ),
            freeze_id=graph.freeze,
            cutoff_policy_digest=graph.policy,
            cutoff_ids=tuple(row.cutoff_id for row in boundaries),
            profile_digest=profile.digest,
            policy=PolicyVersion(version="research-policy-v1"),
        )
        alternative_manifest = F16MatchweekProcessor(alternative).replay_manifest(
            result.result_digest
        )
        for metadata in alternative.artifact_catalog():
            ArtifactStore(research_store).publish_artifact(
                ArtifactStore(alternative).read_artifact(metadata.digest),
                metadata.media_type,
                retention_class=metadata.retention_class,
            )
    assert (
        F16MatchweekProcessor(research_store).replay_manifest(alternative_manifest.digest)
        == alternative_manifest
    )
    selected = MatchweekResearchRepository(research_store, clock=Clock()).seal_completed(graph.f16)
    original = _request(research_store, graph)
    changed = replace(
        original, profile_digest=profile.digest, f16_manifest_digest=alternative_manifest.digest
    )
    with pytest.raises(CB01SourceError, match="selected"):
        prepare_fixture_sources(research_store, changed)
    with pytest.raises(F19Error, match="selected"):
        SettlementRepository(research_store).build(
            alternative_manifest.digest,
            alternative_manifest.match_results[0].match_result_digest,
            "match_winner_home",
            (),
        )
    freeze = MatchweekMembershipRepository(research_store).get_by_id(graph.freeze)
    assert freeze is not None
    with pytest.raises(CB01EvaluationError, match="Profile"):
        MatchweekEvaluationRepository(research_store).inspect_cohort(
            freeze.freeze_digest,
            profile.digest,
            graph.policy,
            selection_digest=selected.digest,
        )


def test_f19_cache_cannot_bypass_missing_selection_receipt(
    selected_store: Store, graph: Graph, qualified: Qualified
) -> None:
    manifest = F16MatchweekProcessor(selected_store).replay_manifest(graph.f16)
    row = manifest.match_results[0]
    repository = SettlementRepository(selected_store)
    pending = repository.build(graph.f16, row.match_result_digest, "match_winner_home", ())
    metadata = selected_store.artifact_metadata(qualified.receipt)
    assert metadata is not None
    (selected_store.path.parent / metadata.relative_path).unlink()
    with pytest.raises(F19Error, match="selected"):
        repository.build(graph.f16, row.match_result_digest, "match_winner_home", ())
    with pytest.raises(F19Error, match="selected"):
        repository.replay(pending.digest)


def test_f19_outcomes_append_without_changing_frozen_inputs(
    slate_store: Store, slate: Slate
) -> None:
    from matchvet.f11 import F11EvidenceRepository
    from matchvet.f13 import SOURCE_MEDIA_TYPE, ModelContractRepository

    artifacts = ArtifactStore(slate_store)
    backend = RetainedWitness()
    evaluation = MatchweekEvaluationRepository(slate_store, witness_backend=backend)
    empty = evaluation.inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_attachment_digests=(),
    )
    assert empty.included_count == 4 and not empty.cases
    manifest = json.loads(artifacts.read_artifact(slate.requests[0].f16_manifest_digest or ""))
    matched = next(
        row
        for row in manifest["matches"]
        if row["membership_id"] == slate.requests[0].membership_id
    )
    frozen_bytes = {
        digest: artifacts.read_artifact(digest)
        for row in manifest["matches"]
        for digest in (row["evidence_digest"], row["model_digest"], row["decision_digest"])
    }
    monday_before = prepare_fixture_sources(slate_store, slate.requests[1]).pre_enrollments
    fixture = prepare_fixture_sources(slate_store, slate.requests[0]).membership.fixture_id
    settlements = SettlementRepository(slate_store)
    pending = settlements.build(
        manifest_digest=slate.requests[0].f16_manifest_digest or "",
        match_result_digest=matched["match_result_digest"],
        preference_id="match_winner_home",
        evidence=(),
    )
    win_evidence = SettlementEvidence(
        fixture_id=fixture,
        source_level="COMPETITION",
        source_key="league",
        record_id="final-v1",
        fixture_status="FINISHED",
        full_time_home_goals=2,
        full_time_away_goals=0,
        published_at_utc="2026-09-25T22:00:00Z",
        observed_at_utc="2026-09-25T22:01:00Z",
        retrieved_at_utc="2026-09-25T22:01:00Z",
    )
    win = settlements.correct(pending.digest, (win_evidence,))
    loss_evidence = replace(
        win_evidence,
        evidence_digest="",
        record_id="official-correction-v2",
        full_time_home_goals=0,
        full_time_away_goals=2,
        published_at_utc="2026-09-26T10:00:00Z",
        observed_at_utc="2026-09-26T10:01:00Z",
        retrieved_at_utc="2026-09-26T10:01:00Z",
    )
    loss = settlements.correct(win.digest, (loss_evidence,))
    assert (pending.state, win.state, loss.state) == (
        SettlementState.PENDING,
        SettlementState.WIN,
        SettlementState.LOSS,
    )
    assert loss.correction_sequence == 2 and loss.predecessor_digest == win.digest
    assert win.predecessor_digest == pending.digest
    assert settlements.replay(pending.digest).to_bytes() == pending.to_bytes()
    with pytest.raises(F19Error, match="successor"):
        settlements.correct(pending.digest, (loss_evidence,))
    with pytest.raises(F19Error, match="lineage"):
        settlements.build(
            slate.requests[0].f16_manifest_digest or "",
            matched["match_result_digest"],
            "asian_handicap_home_0_0",
            (),
            predecessor_digest=pending.digest,
        )
    bootstrap = BootstrapRepository(slate_store, witness_backend=backend)
    enrolled = bootstrap.enroll_fixture(slate.requests[0])
    enrollment = next(
        row.enrollment_digest for row in enrolled.rows if row.preference_id == "match_winner_home"
    )
    assert enrolled.publication_digest is not None and enrollment is not None
    first, _ = bootstrap.attach_outcome(enrollment, pending.digest)
    second, _ = bootstrap.attach_outcome(enrollment, win.digest, predecessor_digest=first)
    third, _ = bootstrap.attach_outcome(enrollment, loss.digest, predecessor_digest=second)
    view = evaluation.inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_publication_digests=(enrolled.publication_digest,),
        exact_attachment_digests=(third,),
    )
    assert view.included_count == 4
    assert len(view.cases[0].attachments) == 1
    assert view.cases[0].attachments[0][1]["settlement_digest"] == loss.digest
    no_latest = evaluation.inspect_cohort(
        slate.freeze_digest,
        slate.profile,
        slate.policy,
        selection_digest=slate.selection,
        exact_publication_digests=(enrolled.publication_digest,),
    )
    assert no_latest.cases[0].attachments == ()
    artifacts.publish_artifact(
        b"post-cutoff outcome source must not be enumerated", SOURCE_MEDIA_TYPE
    )
    for row in manifest["matches"]:
        assert (
            ModelContractRepository(slate_store)
            .build_from_retained_history(row["evidence_digest"], row["cutoff_id"])
            .to_bytes()
            == frozen_bytes[row["model_digest"]]
        )
    assert (
        F11EvidenceRepository(slate_store)
        .build_or_replay_for_freeze(slate.requests[0].freeze_id, slate.policy)
        .to_bytes()
        == frozen_bytes[matched["evidence_digest"]]
    )
    monday_after = prepare_fixture_sources(slate_store, slate.requests[1]).pre_enrollments
    assert monday_after == monday_before
    later_backend = RetainedWitness(gen_time_utc="2026-09-26T12:00:00Z")
    later = BootstrapRepository(slate_store, witness_backend=later_backend).enroll_fixture(
        slate.requests[1]
    )
    assert later.publication_digest is not None
    assert all(
        artifacts.read_artifact(digest) == content for digest, content in frozen_bytes.items()
    )

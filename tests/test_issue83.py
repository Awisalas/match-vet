from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from causal_selection_support import approval, trust
from issue82_support import selected_candidate as selected_candidate
from issue82_support import selected_candidate_store as selected_candidate_store
from issue82_support import successor as successor
from issue82_support import successor_store as successor_store
from issue82_support import weather_candidate as weather_candidate
from issue82_support import weather_store as weather_store
from test_issue76 import candidate as candidate
from test_issue76 import candidate_store as candidate_store
from test_issue77 import slate as issue77_slate  # noqa: F401

from matchvet.causal_witness import _ParsedEvent
from matchvet.cb01_evaluation import (
    CAUSAL_COHORT,
    LEGACY_COHORT,
    MatchweekEvaluationRepository,
)
from matchvet.cb01_sources import (
    CB01SourceError,
    FixtureEnrollmentInput,
    prepare_fixture_sources,
)
from matchvet.f16 import F16MatchweekProcessor
from matchvet.matchweek_research import MatchweekResearchRepository
from matchvet.store import Store


@pytest.fixture
def historical_v1_selection(issue77_slate: Any) -> Any:  # noqa: F811
    return issue77_slate


def _allow_causal_replay(monkeypatch: pytest.MonkeyPatch, case: Any) -> None:
    cutoff = datetime.fromisoformat(case.graph.cutoff)

    def verify(
        request: bytes,
        response: bytes,
        imprint: bytes,
        nonce: int,
        bundle: Any,
        state: Any,
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

    monkeypatch.setattr(
        "matchvet.causal_selection._load_approval", lambda store: (approval(), trust())
    )
    monkeypatch.setattr("matchvet.causal_witness._verify_event", verify)


def test_qualified_v2_selection_resolves_exact_owner_context(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.causal_dispatch import resolve_qualified_causal_selection

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises the refusal case")
    _allow_causal_replay(monkeypatch, case)

    result = resolve_qualified_causal_selection(selected_candidate_store, selection_digest)

    assert result.selection_digest == selection_digest
    assert result.completion_receipt_digest
    assert result.candidate_contract_digest == case.candidate
    assert result.f16_manifest_digest == case.manifest
    assert result.engine_version
    assert result.engine_contract_digest
    assert result.selection_reader.name.endswith("matchvet-causal-selection-v2")


def test_unselected_candidate_and_terminal_selection_cannot_supply_recommendations(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.causal_dispatch import resolve_qualified_causal_selection

    with pytest.raises(ValueError, match=r"qualification|manifest|selection|version"):
        resolve_qualified_causal_selection(
            selected_candidate_store, selected_candidate[0].candidate
        )

    case, selection_digest, qualified = selected_candidate
    if qualified:
        pytest.skip("qualified fixture exercises the success case")
    _allow_causal_replay(monkeypatch, case)
    with pytest.raises(ValueError, match=r"receipt|qualified|unqualified"):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)


def test_historical_complete_selection_cannot_be_represented_as_qualified_v2(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from matchvet.artifacts import ArtifactStore, ManifestVersion
    from matchvet.causal_dispatch import resolve_qualified_causal_selection
    from matchvet.matchweek_research import MatchweekResearchError, _version

    _, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises the receipt refusal")
    original_verify = ArtifactStore.verify_manifest

    def historical_version(self: ArtifactStore, digest: str) -> Any:
        manifest = original_verify(self, digest)
        if digest != selection_digest:
            return manifest
        return replace(manifest, versions=(ManifestVersion.from_identity(_version("selection")),))

    monkeypatch.setattr(ArtifactStore, "verify_manifest", historical_version)

    with pytest.raises(MatchweekResearchError, match="Unsupported causal selection version"):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)


def test_alternate_indexed_selection_and_unsupported_version_fail_before_time_check(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_dispatch import resolve_qualified_causal_selection
    from matchvet.matchweek_research import MatchweekResearchError
    from matchvet.research_identity import selection_slot

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises the receipt refusal")
    logical = case.graph.logical_id
    original_lookup = selected_candidate_store.snapshot_manifest_digest_for_snapshot
    monkeypatch.setattr(
        selected_candidate_store,
        "snapshot_manifest_digest_for_snapshot",
        lambda slot: case.candidate if slot == selection_slot(logical) else original_lookup(slot),
    )
    with pytest.raises(MatchweekResearchError, match="indexed"):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)
    monkeypatch.setattr(
        selected_candidate_store, "snapshot_manifest_digest_for_snapshot", original_lookup
    )

    original_verify = ArtifactStore.verify_manifest

    def unsupported(self: ArtifactStore, digest: str) -> Any:
        manifest = original_verify(self, digest)
        if digest != selection_digest:
            return manifest
        return replace(
            manifest,
            versions=(replace(manifest.versions[0], canonical_contract_version=3),),
        )

    monkeypatch.setattr(ArtifactStore, "verify_manifest", unsupported)
    monkeypatch.setattr(
        "matchvet.causal_witness._verify_event",
        lambda *args, **kwargs: pytest.fail("unsupported version reached timestamp comparison"),
    )
    with pytest.raises(MatchweekResearchError, match="Unsupported causal selection version"):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)

    monkeypatch.setattr(ArtifactStore, "verify_manifest", original_verify)
    import matchvet.causal_dispatch as causal_dispatch

    original_resolve = causal_dispatch.resolve

    def unsupported_candidate(store: Store, digest: str) -> Any:
        return replace(original_resolve(store, digest), contract_version="unsupported-candidate")

    monkeypatch.setattr(causal_dispatch, "resolve", unsupported_candidate)
    with pytest.raises(MatchweekResearchError, match="Unsupported selected candidate contract"):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)


def test_withdrawn_qualification_refuses_but_selection_remains_inspectable(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from matchvet.causal_dispatch import resolve_qualified_causal_selection
    from matchvet.matchweek_research import MatchweekResearchError

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture does not carry a qualified receipt")
    _allow_causal_replay(monkeypatch, case)
    withdrawn = replace(approval(), withdrawn_from="2026-09-25T00:00:00Z")
    monkeypatch.setattr(
        "matchvet.causal_selection._load_approval", lambda store: (withdrawn, trust())
    )

    owner = MatchweekResearchRepository(selected_candidate_store)
    assert owner.inspect_causal(selection_digest).f16_manifest_digest == case.manifest
    with pytest.raises(MatchweekResearchError):
        resolve_qualified_causal_selection(selected_candidate_store, selection_digest)
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    freeze = MatchweekMembershipRepository(selected_candidate_store).get_by_id(
        case.request.freeze_id
    )
    assert freeze is not None
    historical = MatchweekEvaluationRepository(selected_candidate_store).inspect_historical_cohort(
        freeze.freeze_digest,
        case.request.preference_profile_digest,
        case.request.cutoff_policy_digest,
        selection_digest=selection_digest,
    )
    assert historical.cohort == "CAUSAL_SELECTION_V2"
    assert historical.qualification_status == "HISTORICAL_INSPECTION_ONLY"


def test_cb01_causal_adapter_requires_and_retains_exact_selection_origin(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises the refusal case")
    _allow_causal_replay(monkeypatch, case)
    manifest = F16MatchweekProcessor(selected_candidate_store).replay_manifest(case.manifest)
    row = manifest.match_results[0]
    request = FixtureEnrollmentInput(
        case.request.freeze_id,
        row.membership_id,
        row.cutoff_id,
        case.request.preference_profile_digest,
        case.manifest,
        selection_digest,
    )

    prepared = prepare_fixture_sources(selected_candidate_store, request)

    assert prepared.qualification_status == "PRESENTLY_QUALIFIED_CAUSAL_SELECTION_V2"
    assert prepared.lineage["causal_selection"]["selection_digest"] == selection_digest
    assert prepared.lineage["causal_selection"]["completion_receipt_digest"]
    assert prepared.lineage["causal_selection"]["candidate_contract_digest"] == case.candidate
    assert prepared.expected_preference_ids == tuple(
        sorted(item.preference_id for item in prepared.profile.enabled_preferences)
    )
    assert len(prepared.pre_enrollments) == len(prepared.profile.enabled_preferences)
    from matchvet.cb01_schema import LINEAGE_KEYS, CB01SchemaError, _keys

    with pytest.raises(CB01SchemaError):
        _keys(prepared.lineage, LINEAGE_KEYS, "Lineage")


def test_cb01_refuses_candidate_only_causal_f16(
    successor: Any,
    successor_store: Store,
) -> None:
    from matchvet.f16 import F16MatchweekProcessor

    manifest = F16MatchweekProcessor(successor_store).replay_manifest(successor.manifest)
    row = manifest.match_results[0]
    request = FixtureEnrollmentInput(
        successor.request.freeze_id,
        row.membership_id,
        row.cutoff_id,
        successor.request.preference_profile_digest,
        successor.manifest,
    )
    with pytest.raises(CB01SourceError, match="explicit exact qualified selection"):
        prepare_fixture_sources(successor_store, request)


def test_denominator_remains_complete_without_f16_and_with_unattempted_preferences(
    candidate: Any,
    candidate_store: Store,
) -> None:
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    freeze = MatchweekMembershipRepository(candidate_store).get_by_id(candidate.request.freeze_id)
    assert freeze is not None
    membership = next(row for row in freeze.memberships if row.decision.value == "INCLUDED")
    cutoffs = MatchEvidenceCutoffRepository(candidate_store)
    cutoff = next(
        row
        for cutoff_id in candidate.request.cutoff_ids
        if (row := cutoffs.replay(cutoff_id)).fixture_id == membership.fixture_id
    )
    request = FixtureEnrollmentInput(
        candidate.request.freeze_id,
        membership.membership_id,
        cutoff.cutoff_id,
        candidate.request.preference_profile_digest,
    )
    prepared = prepare_fixture_sources(candidate_store, request)
    denominator = MatchweekEvaluationRepository(candidate_store).inspect_denominator(
        freeze.freeze_digest, candidate.request.preference_profile_digest
    )

    included_memberships = sum(m.decision.value == "INCLUDED" for m in freeze.memberships)
    expected_denominator = included_memberships * len(prepared.profile.enabled_preferences)
    assert len(denominator.rows) == len(freeze.memberships) * len(
        prepared.profile.enabled_preferences
    )
    assert sum(row.membership_state == "INCLUDED" for row in denominator.rows) == (
        expected_denominator
    )
    assert prepared.expected_preference_ids == tuple(
        sorted(item.preference_id for item in prepared.profile.enabled_preferences)
    )
    assert prepared.f16_manifest_digest is None
    assert all(row["disposition"] == "INCOMPLETE" for row in prepared.pre_enrollments)
    assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in denominator.rows)


def test_missing_causal_receipt_preserves_full_denominator_on_refusal(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
) -> None:
    from matchvet.cb01_evaluation import CB01EvaluationError
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    case, selection_digest, qualified = selected_candidate
    if qualified:
        pytest.skip("terminal fixture has no completion receipt")
    freeze = MatchweekMembershipRepository(selected_candidate_store).get_by_id(
        case.request.freeze_id
    )
    assert freeze is not None
    evaluation = MatchweekEvaluationRepository(selected_candidate_store)
    with pytest.raises(CB01EvaluationError) as refused:
        evaluation.inspect_cohort(
            freeze.freeze_digest,
            case.request.preference_profile_digest,
            case.request.cutoff_policy_digest,
            selection_digest=selection_digest,
        )
    assert refused.value.denominator == evaluation.inspect_denominator(
        freeze.freeze_digest, case.request.preference_profile_digest
    )


def test_causal_and_legacy_cohorts_are_separate_and_unattempted_rows_remain(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises qualification refusal")
    _allow_causal_replay(monkeypatch, case)
    freeze = MatchweekMembershipRepository(selected_candidate_store).get_by_id(
        case.request.freeze_id
    )
    assert freeze is not None
    evaluation = MatchweekEvaluationRepository(selected_candidate_store)
    causal = evaluation.inspect_cohort(
        freeze.freeze_digest,
        case.request.preference_profile_digest,
        case.request.cutoff_policy_digest,
        selection_digest=selection_digest,
    )
    assert causal.cohort == CAUSAL_COHORT
    assert causal.chronology_version == "0.2.0"
    assert causal.selection_contract == "matchvet-causal-selection-v2"
    assert causal.qualification_status == "PRESENTLY_QUALIFIED"
    assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in causal.denominator.rows)

    cutoffs = MatchEvidenceCutoffRepository(selected_candidate_store)
    legacy_policy = cutoffs.persist_policy(CutoffPolicy("issue83-legacy", "1", 21600))
    legacy = evaluation.inspect_legacy_cohort(
        freeze.freeze_digest,
        case.request.preference_profile_digest,
        legacy_policy,
    )
    assert legacy.cohort == LEGACY_COHORT
    assert legacy.chronology_version == "PER_MATCH_LEGACY"
    assert legacy.selection is None
    assert legacy.qualification_status == "HISTORICAL_INSPECTION_ONLY"
    assert len(legacy.denominator.rows) == len(causal.denominator.rows)
    with pytest.raises(ValueError, match="Corrected selection"):
        evaluation.inspect_legacy_cohort(
            freeze.freeze_digest,
            case.request.preference_profile_digest,
            case.request.cutoff_policy_digest,
        )


def test_corrected_v1_cohort_is_historical_only(historical_v1_selection: Any) -> None:
    from matchvet.cb01_evaluation import MatchweekEvaluationRepository
    from matchvet.store import open_store

    with open_store(
        historical_v1_selection.root / "store.sqlite3",
        private_root=historical_v1_selection.root,
    ) as store:
        view = MatchweekEvaluationRepository(store).inspect_cohort(
            historical_v1_selection.freeze_digest,
            historical_v1_selection.profile,
            historical_v1_selection.policy,
            selection_digest=historical_v1_selection.selection,
        )
    assert view.cohort == "CORRECTED_MATCHWEEK"
    assert view.chronology_version == "0.2.0"
    assert view.selection_contract == "postcommit-upper-bound-v1"
    assert view.qualification_status == "HISTORICAL_INSPECTION_ONLY"


def test_cb01_failed_witness_keeps_the_complete_causal_denominator(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.cb01 import BootstrapRepository
    from matchvet.f14 import PreferenceProfileRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture exercises qualification refusal")
    _allow_causal_replay(monkeypatch, case)
    manifest = F16MatchweekProcessor(selected_candidate_store).replay_manifest(case.manifest)
    row = manifest.match_results[0]
    request = FixtureEnrollmentInput(
        case.request.freeze_id,
        row.membership_id,
        row.cutoff_id,
        case.request.preference_profile_digest,
        case.manifest,
        selection_digest,
    )
    result = BootstrapRepository(
        selected_candidate_store,
        witness_backend=DeterministicWitnessBackend(transport_states=("UNAVAILABLE",)),
    ).enroll_fixture(request)
    freeze = MatchweekMembershipRepository(selected_candidate_store).get_by_id(
        case.request.freeze_id
    )
    assert freeze is not None
    view = MatchweekEvaluationRepository(selected_candidate_store).inspect_cohort(
        freeze.freeze_digest,
        case.request.preference_profile_digest,
        case.request.cutoff_policy_digest,
        selection_digest=selection_digest,
    )
    included_membership_ids = {
        m.membership_id for m in freeze.memberships if m.decision.value == "INCLUDED"
    }
    failed_memberships = {row.membership_id for row in view.denominator.rows if row.failure_digests}
    profile = PreferenceProfileRepository(selected_candidate_store).replay(
        case.request.preference_profile_digest
    )
    assert result.publication_digest is None and result.failure_digests
    included_count = sum(m.decision.value == "INCLUDED" for m in freeze.memberships)
    assert len(view.denominator.rows) == len(freeze.memberships) * len(profile.enabled_preferences)
    assert view.included_count == included_count * len(profile.enabled_preferences)
    assert failed_memberships == {row.membership_id}
    assert all(item.state == "INCOMPLETE" for item in view.denominator.rows if item.failure_digests)
    assert included_membership_ids.issuperset(failed_memberships)


def test_cb01_and_causal_witnesses_cannot_substitute_roles(
    selected_candidate: tuple[Any, str, bool],
    selected_candidate_store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import json

    from test_cb01_repository import DeterministicWitnessBackend

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_dispatch import resolve_qualified_causal_selection
    from matchvet.causal_selection import _PROVENANCE
    from matchvet.cb01 import BootstrapRepository
    from matchvet.cb01_schema import normalize_utc
    from matchvet.match_evidence_cutoff import MatchEvidenceCutoffRepository
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import MatchweekResearchError
    from matchvet.research_identity import completion_slot

    case, selection_digest, qualified = selected_candidate
    if not qualified:
        pytest.skip("terminal fixture has no causal witness token")
    _allow_causal_replay(monkeypatch, case)
    manifest = F16MatchweekProcessor(selected_candidate_store).replay_manifest(case.manifest)
    row = manifest.match_results[0]
    request = FixtureEnrollmentInput(
        case.request.freeze_id,
        row.membership_id,
        row.cutoff_id,
        case.request.preference_profile_digest,
        case.manifest,
        selection_digest,
    )
    backend = DeterministicWitnessBackend()
    result = BootstrapRepository(selected_candidate_store, witness_backend=backend).enroll_fixture(
        request
    )
    assert result.publication_digest is not None
    assert result.verification_digest is not None
    verification = BootstrapRepository(selected_candidate_store)._read_kind(
        result.verification_digest, "TimestampVerification"
    )
    assert isinstance(verification["response_digest"], str)
    with pytest.raises(MatchweekResearchError):
        resolve_qualified_causal_selection(
            selected_candidate_store, verification["response_digest"]
        )

    logical = case.graph.logical_id
    receipt_digest = selected_candidate_store.snapshot_manifest_digest_for_snapshot(
        completion_slot(logical)
    )
    assert receipt_digest is not None
    receipt = ArtifactStore(selected_candidate_store).verify_manifest(receipt_digest)
    provenance_ref = next(ref for ref in receipt.artifacts if ref.media_type == _PROVENANCE)
    provenance = json.loads(
        ArtifactStore(selected_candidate_store).read_artifact(provenance_ref.digest)
    )
    response = ArtifactStore(selected_candidate_store).read_artifact(
        provenance["evidence"]["response"]
    )
    batch_bytes = ArtifactStore(selected_candidate_store).read_artifact(result.batch_digest)
    cb01_request = backend.create_request(batch_bytes)
    cutoff = MatchEvidenceCutoffRepository(selected_candidate_store).replay(row.cutoff_id)
    freeze = MatchweekMembershipRepository(selected_candidate_store).get_by_id(
        case.request.freeze_id
    )
    assert freeze is not None
    membership = next(
        item for item in freeze.memberships if item.membership_id == row.membership_id
    )
    verification = backend.verify_response(
        cb01_request.der,
        cb01_request.nonce_hex,
        response,
        backend.trust,
        backend.policy,
        batch_digest=hashlib.sha256(batch_bytes).hexdigest(),
        cutoff_utc=normalize_utc(cutoff.cutoff_at_utc),
        kickoff_utc=normalize_utc(membership.controlling_revision.kickoff_utc or ""),
    )
    assert verification.state == "FAILED"


def test_f19_binds_exact_causal_origin_and_appends_corrections_only(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from matchvet.artifacts import ArtifactStore
    from matchvet.causal_candidate import CAUSAL_CONTRACT
    from matchvet.f16 import CAUSAL_MANIFEST_MEDIA_TYPE, F16MatchweekProcessor
    from matchvet.f19 import CAUSAL_SETTLEMENT_MEDIA_TYPE, F19Error, SettlementRepository
    from matchvet.matchweek_membership import canonical_json
    from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
    from matchvet.matchweek_research import MatchweekResearchRepository
    from matchvet.research_identity import completion_slot, logical_matchweek_id, selection_slot
    from matchvet.store import open_store
    from matchvet.t10 import DEFAULT_PREFERENCE_CATALOG, SettlementEvidence

    freeze_id = "f" * 64
    policy_digest = "a" * 64
    candidate_digest = "c" * 64
    engine_digest = "d" * 64
    selection_digest = "1" * 64
    receipt_digest = "2" * 64
    alternate_selection_digest = "3" * 64
    season = "2026"
    friday = "2026-09-25"
    logical = logical_matchweek_id(season, friday)
    selected_slot = selection_slot(logical)
    receipt_slot = completion_slot(logical)
    fixture_id = "fixture-home-away"
    preference = DEFAULT_PREFERENCE_CATALOG.get("match_winner_home")
    preference_id = preference.preference_id
    cutoff = "2026-09-25T00:00:00Z"
    freeze = SimpleNamespace(season=season, matchweek_friday=friday)

    def origin(selection: str, manifest: str, receipt: str) -> Any:
        selection_state = SimpleNamespace(
            digest=selection,
            completion_receipt_digest=receipt,
            f16_manifest_digest=manifest,
            freeze_id=freeze_id,
            policy_digest=policy_digest,
            cutoff_at_utc=cutoff,
        )
        reader = SimpleNamespace(
            version_id=SimpleNamespace(value="selection-v2-reader"),
            definition_id=SimpleNamespace(value="selection-v2-definition"),
            name="matchvet-causal-selection-v2",
            content_sha256="6" * 64,
            canonical_contract_version=2,
        )
        return SimpleNamespace(
            selection=selection_state,
            selection_digest=selection,
            completion_receipt_digest=receipt,
            f16_manifest_digest=manifest,
            candidate_contract_digest=candidate_digest,
            candidate=SimpleNamespace(contract_version=CAUSAL_CONTRACT),
            engine_contract_digest=engine_digest,
            engine_version="causal-engine-v1",
            selection_reader=reader,
        )

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        artifacts = ArtifactStore(store)
        input_artifacts = {
            artifacts.publish_artifact(
                content, "application/vnd.matchvet.issue83-frozen-input+json"
            ).digest: content
            for content in (
                b"frozen F11 recommendation evidence",
                b"frozen F13 prediction input",
                b"frozen F14 decision input",
            )
        }
        decision_body = {
            "fixture_id": fixture_id,
            "preference_results": [{"vetting": {"preference": preference.to_dict()}}],
        }
        decision_ref = artifacts.publish_artifact(
            canonical_json(decision_body).encode("utf-8"),
            "application/vnd.matchvet.issue83-f14+json",
        )
        decision_digest = decision_ref.digest
        match_result_body = {
            "decision_digest": decision_digest,
            "fixture_id": fixture_id,
            "outcome": "HOME_WIN",
        }
        match_result_ref = artifacts.publish_artifact(
            canonical_json(match_result_body).encode("utf-8"),
            "application/vnd.matchvet.issue83-f16-match+json",
        )
        match_result_digest = match_result_ref.digest
        evidence_digest, model_digest, _ = input_artifacts
        manifest_value = {
            "freeze_id": freeze_id,
            "cutoff_policy_digest": policy_digest,
            "matches": [
                {
                    "match_result_digest": match_result_digest,
                    "decision_digest": decision_digest,
                    "evidence_digest": evidence_digest,
                    "model_digest": model_digest,
                }
            ],
        }
        manifest_ref = artifacts.publish_artifact(
            canonical_json(manifest_value).encode("utf-8"), CAUSAL_MANIFEST_MEDIA_TYPE
        )
        alternate_match_result_ref = artifacts.publish_artifact(
            canonical_json({**match_result_body, "outcome": "HOME_LOSS"}).encode("utf-8"),
            "application/vnd.matchvet.issue83-f16-match+json",
        )
        alternate_manifest_value = {
            **manifest_value,
            "matches": [
                {
                    **manifest_value["matches"][0],
                    "match_result_digest": alternate_match_result_ref.digest,
                }
            ],
        }
        alternate_manifest_ref = artifacts.publish_artifact(
            canonical_json(alternate_manifest_value).encode("utf-8"),
            CAUSAL_MANIFEST_MEDIA_TYPE,
        )

        class FakeManifest:
            def __init__(self, digest: str, value: dict[str, Any]) -> None:
                self.digest = digest
                self.match_results = (
                    SimpleNamespace(
                        match_result_digest=value["matches"][0]["match_result_digest"],
                        decision_digest=value["matches"][0]["decision_digest"],
                    ),
                )
                self.value = value

            def to_dict(self) -> dict[str, Any]:
                return self.value

        manifests = {
            manifest_ref.digest: FakeManifest(manifest_ref.digest, manifest_value),
            alternate_manifest_ref.digest: FakeManifest(
                alternate_manifest_ref.digest, alternate_manifest_value
            ),
        }
        slot_values = {selected_slot: selection_digest, receipt_slot: receipt_digest}
        origins = {
            selection_digest: origin(selection_digest, manifest_ref.digest, receipt_digest),
            alternate_selection_digest: origin(
                alternate_selection_digest, alternate_manifest_ref.digest, receipt_digest
            ),
        }
        decision = SimpleNamespace(to_dict=lambda: decision_body)

        monkeypatch.setattr(
            F16MatchweekProcessor,
            "replay_manifest",
            lambda self, digest: manifests[digest],
        )
        monkeypatch.setattr(
            "matchvet.f14.DecisionRepository.replay",
            lambda self, digest: decision if digest == decision_digest else None,
        )
        monkeypatch.setattr(
            MatchweekMembershipRepository,
            "get_by_id",
            lambda self, value: freeze if value == freeze_id else None,
        )
        monkeypatch.setattr(
            MatchweekResearchRepository,
            "is_corrected",
            lambda self, value: value == policy_digest,
        )
        monkeypatch.setattr(
            store,
            "snapshot_manifest_digest_for_snapshot",
            lambda slot: slot_values.get(slot),
        )

        def resolve_origin(_store: Store, digest: str) -> Any:
            return origins[digest]

        monkeypatch.setattr(
            "matchvet.causal_dispatch.resolve_qualified_causal_selection", resolve_origin
        )
        monkeypatch.setattr("matchvet.causal_dispatch.inspect_causal_selection", resolve_origin)

        settlement = SettlementRepository(store)
        pending = settlement.build(manifest_ref.digest, match_result_digest, preference_id, ())
        metadata = store.artifact_metadata(pending.digest)
        assert metadata is not None and metadata.media_type == CAUSAL_SETTLEMENT_MEDIA_TYPE
        pending_value = pending.to_dict()
        assert pending_value["selection_digest"] == selection_digest
        assert pending_value["completion_receipt_digest"] == receipt_digest
        assert pending_value["candidate_contract_digest"] == candidate_digest
        assert pending_value["engine_contract_digest"] == engine_digest
        assert pending_value["selection_reader_name"] == "matchvet-causal-selection-v2"
        assert pending_value["decision_digest"] == decision_digest

        final_evidence = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="league",
            record_id="official-final",
            fixture_status="FINISHED",
            full_time_home_goals=2,
            full_time_away_goals=0,
            published_at_utc="2026-09-25T22:00:00Z",
            observed_at_utc="2026-09-25T22:00:00Z",
            retrieved_at_utc="2026-09-25T22:00:00Z",
        )
        corrected = settlement.correct(pending.digest, (final_evidence,))
        assert corrected.predecessor_digest == pending.digest
        assert corrected.correction_sequence == 1
        assert settlement.replay(corrected.digest).to_bytes() == corrected.to_bytes()
        assert settlement.replay(pending.digest).to_bytes() == pending.to_bytes()
        monkeypatch.setattr(
            "matchvet.causal_dispatch.resolve_qualified_causal_selection",
            lambda _store, _digest: (_ for _ in ()).throw(ValueError("trust withdrawn")),
        )
        assert settlement.replay(pending.digest).to_bytes() == pending.to_bytes()
        monkeypatch.setattr(
            "matchvet.causal_dispatch.resolve_qualified_causal_selection", resolve_origin
        )
        assert all(
            artifacts.read_artifact(digest) == content
            for digest, content in input_artifacts.items()
        )

        # An already cached F19 lineage cannot keep settling against a prior
        # selection when a different valid graph occupies the logical slot.
        slot_values[selected_slot] = alternate_selection_digest
        with pytest.raises(F19Error, match="exact selected F16 manifest"):
            settlement.build(manifest_ref.digest, match_result_digest, preference_id, ())

        # A retained causal F19 record without its exact completion receipt is
        # inspectable only while the original receipt remains indexed.
        slot_values[selected_slot] = selection_digest
        slot_values[receipt_slot] = None
        origins[selection_digest] = origin(selection_digest, manifest_ref.digest, "")
        with pytest.raises(F19Error, match="completion receipt"):
            settlement.replay(pending.digest)

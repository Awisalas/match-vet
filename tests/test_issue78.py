from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from issue77_support import RetainedWitness
from matchweek_research_support import Clock
from test_matchweek_membership import _persistable_schedule_assessment

from matchvet.artifacts import ArtifactStore
from matchvet.cb01 import BootstrapRepository
from matchvet.cb01_evaluation import MatchweekEvaluationRepository
from matchvet.cb01_sources import FixtureEnrollmentInput
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import ModelContractRepository
from matchvet.f14 import DecisionRepository, PreferenceProfileRepository
from matchvet.f16 import F16MatchweekProcessor
from matchvet.f19 import SettlementRepository, SettlementState
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.matchweek_research import (
    CORRECTED_RULE,
    MatchweekResearchRepository,
)
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import open_store
from matchvet.t10 import SettlementEvidence
from matchvet.t15 import PolicyVersion

EXPECTED_T = "2026-09-25T12:00:00.000000+00:00"


def _forbid_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Issue 78 uses synthetic data and retained offline witnesses only.")


def test_one_selected_matchweek_state_replays_through_cb01_and_f19(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _forbid_network)
    database = tmp_path / "store.sqlite3"
    expected_cutoff = datetime(2026, 9, 25, 12, tzinfo=UTC)
    qualification_clock = Clock(expected_cutoff - timedelta(minutes=1))

    with open_store(database, private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (
                ("2026-09-25", "20:00", "Friday Serie A", "Friday City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
            ),
            rows_by_league={
                "premier_league": (("2026-09-28", "20:00", "Monday United", "Monday City"),),
                "serie_a": (("2026-09-25", "20:00", "Friday Serie A", "Friday City"),),
            },
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC)
        ).freeze_exact(
            "2026-27", "2026-09-25", assessment.digest, "matchvet:matchweek-membership", "1"
        )
        included = tuple(row for row in freeze.memberships if row.decision.value == "INCLUDED")
        assert len(freeze.scopes) == 7
        assert len(included) == 2
        earliest = min(included, key=lambda row: row.controlling_revision.kickoff_utc or "")
        later = next(row for row in included if row.scope_id.startswith("premier_league:"))
        assert earliest.scope_id.startswith("serie_a:")
        assert earliest.controlling_revision.kickoff_utc == "2026-09-25T18:00:00+00:00"
        assert later.controlling_revision.kickoff_utc == "2026-09-28T19:00:00+00:00"

        cutoffs = MatchEvidenceCutoffRepository(store)
        legacy_policy = cutoffs.persist_policy(CutoffPolicy("issue78-legacy", "1", 21600))
        legacy_boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, legacy_policy)
        assert len(legacy_boundaries) == 2
        assert len({row.cutoff_at_utc for row in legacy_boundaries}) == 2
        profile = PreferenceProfileRepository(store).build_profile(
            ("match_winner_home", "asian_handicap_home_0_0")
        )
        decision_policy = PolicyVersion(version="issue78")
        context = WorkContext(
            "issue78",
            "issue78",
            "2026-09-25",
            RunPhase.PREFERENCE_VETTING,
            1,
            "RESEARCH_ONLY",
            "0" * 64,
            "0" * 64,
            1,
        )

        legacy_f07_bytes = {
            row.cutoff_id: cutoffs.replay(row.cutoff_id).to_bytes() for row in legacy_boundaries
        }
        legacy_result = F16MatchweekProcessor(
            store, clock=qualification_clock, legacy_research=True
        ).process_phase(
            context,
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=legacy_policy,
            cutoff_ids=tuple(sorted(row.cutoff_id for row in legacy_boundaries)),
            profile_digest=profile.digest,
            policy=decision_policy,
        )
        legacy_f16_digest = legacy_result.result_digest
        legacy_manifest = F16MatchweekProcessor(store, legacy_research=True).replay_manifest(
            legacy_f16_digest
        )
        legacy_f16_bytes = legacy_manifest.to_bytes()
        legacy_children: dict[tuple[str, str], bytes] = {}
        for row in legacy_manifest.match_results:
            evidence = F11EvidenceRepository(store).replay(
                row.evidence_digest, freeze_id=freeze.freeze_id, policy_digest=legacy_policy
            )
            model = ModelContractRepository(store).replay(
                row.model_digest, row.evidence_digest, row.cutoff_id
            )
            decision = DecisionRepository(store).replay(row.decision_digest)
            legacy_children[("F11", evidence.digest)] = evidence.to_bytes()
            legacy_children[("F13", model.digest)] = model.to_bytes()
            legacy_children[("F14", decision.digest)] = decision.to_bytes()

        corrected_policy = cutoffs.persist_policy(
            CutoffPolicy("issue78-corrected", "0.2.0", 21600, rule=CORRECTED_RULE)
        )
        boundaries = cutoffs.persist_for_freeze(freeze.freeze_id, corrected_policy)
        assert len(boundaries) == len(included)
        assert {row.membership_id for row in boundaries} == {row.membership_id for row in included}
        assert {row.cutoff_at_utc for row in boundaries} == {EXPECTED_T}
        assert {row.cutoff_at_utc for row in boundaries} == {
            (
                datetime.fromisoformat(earliest.controlling_revision.kickoff_utc or "")
                - timedelta(seconds=21600)
            ).isoformat(timespec="microseconds")
        }
        assert earliest.controlling_revision.kickoff_utc == (
            expected_cutoff + timedelta(seconds=21600)
        ).isoformat(timespec="seconds")
        corrected_result = F16MatchweekProcessor(store, clock=qualification_clock).process_phase(
            context,
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=corrected_policy,
            cutoff_ids=tuple(sorted(row.cutoff_id for row in boundaries)),
            profile_digest=profile.digest,
            policy=decision_policy,
        )
        corrected_f16_digest = corrected_result.result_digest
        corrected_manifest = F16MatchweekProcessor(store).replay_manifest(corrected_f16_digest)
        assert {row.membership_id for row in corrected_manifest.match_results} == {
            row.membership_id for row in included
        }
        assert all(
            row.evidence_digest and row.model_digest and row.decision_digest
            for row in corrected_manifest.match_results
        )

        selected = MatchweekResearchRepository(store, clock=qualification_clock).seal_completed(
            corrected_f16_digest
        )
        assert selected.f16_manifest_digest == corrected_f16_digest
        assert selected.cutoff_at_utc == EXPECTED_T
        receipt = ArtifactStore(store).verify_manifest(selected.completion_receipt_digest)
        assert receipt.created_at_utc < EXPECTED_T

        corrected_dependencies = {
            digest: ArtifactStore(store).read_artifact(digest)
            for row in corrected_manifest.match_results
            for digest in (row.evidence_digest, row.model_digest, row.decision_digest)
        }
        corrected_manifest_bytes = corrected_manifest.to_bytes()
        freeze_digest = freeze.freeze_digest
        profile_digest = profile.digest
        f16_by_membership = {row.membership_id: row for row in corrected_manifest.match_results}

    with open_store(database, private_root=tmp_path) as store:
        research = MatchweekResearchRepository(store)
        replayed = research.replay_for_matchweek(season="2026-27", matchweek_friday="2026-09-25")
        assert replayed == selected
        assert research.replay(selected.digest) == selected
        replayed_manifest = F16MatchweekProcessor(store).replay_manifest(corrected_f16_digest)
        assert replayed_manifest.to_bytes() == corrected_manifest_bytes
        replayed_later = next(
            row
            for row in replayed_manifest.match_results
            if row.membership_id == later.membership_id
        )
        assert replayed_later == f16_by_membership[later.membership_id]
        assert MatchweekResearchRepository(store).seal_completed(corrected_f16_digest) == selected

        catalog_before_recommendation_replay = store.artifact_catalog()
        later_context = WorkContext(
            "issue78-later-replay",
            later.membership_id,
            context.matchweek,
            context.phase,
            context.attempt,
            context.mode,
            context.input_digest,
            context.predecessor_digest,
            context.cpu_concurrency,
        )
        later_replay = F16MatchweekProcessor(
            store, clock=Clock(expected_cutoff + timedelta(minutes=1))
        ).process_phase(
            later_context,
            freeze_id=freeze.freeze_id,
            cutoff_policy_digest=corrected_policy,
            cutoff_ids=tuple(sorted(row.cutoff_id for row in boundaries)),
            profile_digest=profile_digest,
            policy=decision_policy,
        )
        assert later_replay.result_digest == corrected_f16_digest
        assert f16_by_membership[later.membership_id].match_result_digest in (
            later_replay.artifact_digests
        )
        assert f16_by_membership[later.membership_id].decision_digest in (
            later_replay.artifact_digests
        )
        assert store.artifact_catalog() == catalog_before_recommendation_replay

        legacy_manifest_after_restart = F16MatchweekProcessor(
            store, legacy_research=True
        ).replay_manifest(legacy_f16_digest)
        assert legacy_manifest_after_restart.to_bytes() == legacy_f16_bytes
        for row in legacy_manifest_after_restart.match_results:
            evidence = F11EvidenceRepository(store).replay(
                row.evidence_digest, freeze_id=freeze.freeze_id, policy_digest=legacy_policy
            )
            model = ModelContractRepository(store).replay(
                row.model_digest, row.evidence_digest, row.cutoff_id
            )
            decision = DecisionRepository(store).replay(row.decision_digest)
            assert evidence.to_bytes() == legacy_children[("F11", evidence.digest)]
            assert model.to_bytes() == legacy_children[("F13", model.digest)]
            assert decision.to_bytes() == legacy_children[("F14", decision.digest)]

        evaluation = MatchweekEvaluationRepository(store)
        denominator = evaluation.inspect_denominator(freeze_digest, profile_digest)
        assert len(denominator.rows) == len(included) * 2 == 4
        assert all(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in denominator.rows)
        later_result = f16_by_membership[later.membership_id]
        enrollment = BootstrapRepository(store, witness_backend=RetainedWitness()).enroll_fixture(
            FixtureEnrollmentInput(
                freeze.freeze_id,
                later.membership_id,
                later_result.cutoff_id,
                profile_digest,
                corrected_f16_digest,
            )
        )
        assert enrollment.publication_digest is not None
        cohort = MatchweekEvaluationRepository(
            store, witness_backend=RetainedWitness()
        ).inspect_cohort(
            freeze_digest,
            profile_digest,
            corrected_policy,
            selection_digest=selected.digest,
            exact_publication_digests=(enrollment.publication_digest,),
        )
        assert cohort.chronology_version == "0.2.0"
        assert cohort.cohort == "CORRECTED_MATCHWEEK"
        assert cohort.included_count == len(cohort.denominator.rows) == 4
        assert sum(row.state == "ENROLLED_LIVE" for row in cohort.denominator.rows) == 2
        assert (
            sum(row.state == "INCOMPLETE_FOR_NOT_ATTEMPTED" for row in cohort.denominator.rows) == 2
        )

        frozen_bytes = dict(corrected_dependencies)
        frozen_bytes[corrected_f16_digest] = corrected_manifest_bytes
        settlement = SettlementRepository(store)
        pending = settlement.build(
            corrected_f16_digest,
            later_result.match_result_digest,
            "match_winner_home",
            (),
        )
        settled = settlement.correct(
            pending.digest,
            (
                SettlementEvidence(
                    fixture_id=later.fixture_id,
                    source_level="COMPETITION",
                    source_key="synthetic-league",
                    record_id="synthetic-final-v1",
                    fixture_status="FINISHED",
                    full_time_home_goals=2,
                    full_time_away_goals=0,
                    published_at_utc="2026-09-28T22:00:00Z",
                    observed_at_utc="2026-09-28T22:01:00Z",
                    retrieved_at_utc="2026-09-28T22:01:00Z",
                ),
            ),
        )
        assert settled.state == SettlementState.WIN
        assert {
            digest: ArtifactStore(store).read_artifact(digest) for digest in frozen_bytes
        } == frozen_bytes
        assert settlement.replay(pending.digest).to_bytes() == pending.to_bytes()

        for cutoff_id, encoded in legacy_f07_bytes.items():
            assert MatchEvidenceCutoffRepository(store).replay(cutoff_id).to_bytes() == encoded

        historical_root = Path(__file__).resolve().parents[1]
        historical_identities = {
            "src/matchvet/cb01.py": (
                "7de7f617d652329146a3fa3c4f2b9638134dfb3c8d4c931bb35b6a90ac200092"
            ),
            "src/matchvet/cb01_trust.py": (
                "4f75585163f353bc6dfcac1e566ee1502562d9a03b7c6e2b1fefc2800974c9be"
            ),
            "docs/product-v2/CANDIDATE-INPUT-METHODOLOGY.md": (
                "1ebeb80f33190f18440d2dcfa5b2526d3907223471f4b2711b7445b0ece8e200"
            ),
        }
        for filename, expected_digest in historical_identities.items():
            assert sha256((historical_root / filename).read_bytes()).hexdigest() == expected_digest

        from test_cb01_trust import _captured_trust

        from matchvet.cb01_trust import SigstoreWitnessBackend, _parse_ts_query, trust_policy_body

        retained = historical_root / "docs/research/cb01-sigstore-witness-2026-10-05"
        request = (retained / "request.tsq").read_bytes()
        query = _parse_ts_query(request)
        historical_witness = SigstoreWitnessBackend().verify_response(
            request,
            f"{query['nonce']:x}",
            (retained / "response.tsr").read_bytes(),
            _captured_trust(),
            trust_policy_body(),
            batch_digest=query["imprint"].hex(),
            cutoff_utc="2026-10-05T04:00:00Z",
            kickoff_utc="2026-10-08T19:00:00Z",
        )
        assert historical_witness.checks["signature"]["state"] == "PASSED"
        assert historical_witness.tsa["gen_time_utc"] == "2026-10-05T04:50:21Z"

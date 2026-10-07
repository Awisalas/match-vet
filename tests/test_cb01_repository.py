from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from test_match_evidence_cutoff import _freeze
from test_matchweek_membership import _persistable_schedule_assessment

from matchvet.artifacts import ArtifactStore
from matchvet.cb01 import BootstrapRepository, CB01Error
from matchvet.cb01_schema import MEDIA_TYPES, decode_artifact
from matchvet.cb01_sources import FixtureEnrollmentInput
from matchvet.cb01_trust import (
    REQUEST_MEDIA_TYPE,
    TSA_ISSUER,
    TSA_POLICY_OID,
    TSA_SIGNER_SHA256,
    TimestampRequest,
    TimestampTransport,
    TimestampVerificationResult,
    TrustRefresh,
    replay_trust_state,
    trust_policy_body,
)
from matchvet.f11 import F11EvidenceRepository
from matchvet.f13 import ModelContractRepository
from matchvet.f14 import PreferenceProfileRepository
from matchvet.f16 import MANIFEST_MEDIA_TYPE, F16MatchweekProcessor
from matchvet.f19 import SettlementRepository, SettlementState
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.match_evidence_cutoff import CutoffPolicy, MatchEvidenceCutoffRepository
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import Store, open_store
from matchvet.t10 import SettlementEvidence, SettlementResult, T10GradingService
from matchvet.t15 import PolicyVersion

_ROOT = Path(__file__).resolve().parents[1]
_TUF_FIXTURE = _ROOT / "docs/research/cb01-sigstore-witness-2026-10-05"


@dataclass(frozen=True)
class EnrollmentCase:
    root: Path
    database: Path
    request: FixtureEnrollmentInput
    freeze_digest: str
    profile_digest: str


def _read_cb01(store: Store, digest: str, kind: str) -> dict[str, Any]:
    return decode_artifact(ArtifactStore(store).read_artifact(digest), expected_kind=kind)[1]


def _cb01_artifacts(store: Store, kind: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (item.digest, _read_cb01(store, item.digest, kind))
        for item in store.artifact_catalog()
        if item.media_type == MEDIA_TYPES[kind]
    ]


@pytest.fixture(scope="module")
def enrollment_case(tmp_path_factory: pytest.TempPathFactory) -> Generator[EnrollmentCase]:
    root = tmp_path_factory.mktemp("cb01-source-case")
    database = root / "matchvet.sqlite3"
    with open_store(database, private_root=root) as store:
        freeze_id = _freeze(store, root)
        cutoffs = MatchEvidenceCutoffRepository(store)
        cutoff_policy_digest = cutoffs.persist_policy(CutoffPolicy("cb01-test", "1", 3600))
        cutoff = cutoffs.persist_for_freeze(freeze_id, cutoff_policy_digest)[0]
        evidence = F11EvidenceRepository(store).build_or_replay_for_freeze(
            freeze_id, cutoff_policy_digest
        )
        ModelContractRepository(store).build(evidence.digest, cutoff.cutoff_id, history=())
        profiles = PreferenceProfileRepository(store)
        profile = profiles.build_profile(("asian_handicap_home_0_0", "match_winner_home"))
        context = WorkContext(
            run_id="cb01-test",
            stable_key="cb01-test",
            matchweek="2026-09-25",
            phase=RunPhase.PREFERENCE_VETTING,
            attempt=1,
            mode="TEST",
            input_digest="0" * 64,
            predecessor_digest="0" * 64,
            cpu_concurrency=1,
        )
        F16MatchweekProcessor(store, legacy_research=True).process_phase(
            context,
            freeze_id=freeze_id,
            cutoff_policy_digest=cutoff_policy_digest,
            cutoff_ids=(cutoff.cutoff_id,),
            profile_digest=profile.digest,
            policy=PolicyVersion(version="research-policy-v1"),
        )
        manifest_digest = next(
            item.digest
            for item in store.artifact_catalog()
            if item.media_type == MANIFEST_MEDIA_TYPE
        )
        freeze = (
            __import__(
                "matchvet.matchweek_membership_repository",
                fromlist=["MatchweekMembershipRepository"],
            )
            .MatchweekMembershipRepository(store)
            .get_by_id(freeze_id)
        )
        assert freeze is not None and len(freeze.memberships) == 1
        request = FixtureEnrollmentInput(
            freeze_id,
            freeze.memberships[0].membership_id,
            cutoff.cutoff_id,
            profile.digest,
            manifest_digest,
        )
    yield EnrollmentCase(root, database, request, freeze.freeze_digest, profile.digest)


@pytest.fixture
def cloned_case(enrollment_case: EnrollmentCase, tmp_path: Path) -> EnrollmentCase:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(enrollment_case.root / "objects", root / "objects")
    database = root / "matchvet.sqlite3"
    shutil.copyfile(enrollment_case.database, database)
    return EnrollmentCase(
        root,
        database,
        enrollment_case.request,
        enrollment_case.freeze_digest,
        enrollment_case.profile_digest,
    )


class DeterministicWitnessBackend:
    """Offline TSA fixture boundary over the retained, authenticated Sigstore TUF snapshot."""

    def __init__(
        self,
        *,
        transport_states: tuple[str, ...] = (),
        failure: str | None = None,
        gen_time_utc: str | None = None,
    ) -> None:
        root_history = tuple(
            (_TUF_FIXTURE / f"{version}.root.json").read_bytes() for version in range(11, 16)
        )
        timestamp = (_TUF_FIXTURE / "timestamp.json").read_bytes()
        snapshot = (_TUF_FIXTURE / "snapshot.json").read_bytes()
        targets = (_TUF_FIXTURE / "targets.json").read_bytes()
        trusted_root = (_TUF_FIXTURE / "trusted_root.json").read_bytes()
        self.policy = trust_policy_body()
        self.trust = replay_trust_state(
            root_history,
            timestamp,
            snapshot,
            targets,
            trusted_root,
            self.policy,
        )
        self.transport_states = list(transport_states)
        self.failure = failure
        self.gen_time_utc = gen_time_utc
        self.refresh_count = 0
        self.request_count = 0
        self.verify_count = 0
        from matchvet.cb01_trust import SigstoreWitnessBackend

        self.request_builder = SigstoreWitnessBackend()

    def refresh_trust(self, policy_body: dict[str, Any]) -> TrustRefresh:
        assert policy_body == self.policy
        self.refresh_count += 1
        return self.trust

    def replay_trust(
        self,
        root_history: tuple[bytes, ...],
        timestamp: bytes,
        snapshot: bytes,
        targets: bytes,
        trusted_root: bytes,
        policy_body: dict[str, Any],
    ) -> TrustRefresh:
        assert root_history == self.trust.root_history
        assert (timestamp, snapshot, targets, trusted_root) == (
            self.trust.timestamp,
            self.trust.snapshot,
            self.trust.targets,
            self.trust.trusted_root,
        )
        assert policy_body == self.policy
        return self.trust

    def create_request(self, batch_bytes: bytes) -> TimestampRequest:
        return self.request_builder.create_request(batch_bytes)

    def submit_request(self, request_der: bytes, policy_body: dict[str, Any]) -> TimestampTransport:
        self.request_count += 1
        assert policy_body == self.policy
        state = self.transport_states.pop(0) if self.transport_states else "RECEIVED"
        if state == "UNAVAILABLE":
            return TimestampTransport(state, None, ("FIXTURE_TSA_UNAVAILABLE",))
        response = b"CB01-FAKE-SIGSTORE-TSA-v1:" + hashlib.sha256(request_der).hexdigest().encode()
        reasons = ("FIXTURE_TSA_REJECTED",) if state == "REJECTED" else ()
        return TimestampTransport(state, response, reasons)

    def verify_response(
        self,
        request_der: bytes,
        nonce_hex: str,
        response_der: bytes,
        trust: TrustRefresh,
        policy_body: dict[str, Any],
        *,
        batch_digest: str,
        cutoff_utc: str,
        kickoff_utc: str,
    ) -> TimestampVerificationResult:
        from matchvet.cb01_trust import _parse_ts_query

        self.verify_count += 1
        request = _parse_ts_query(request_der)
        failure = self.failure
        expected = b"CB01-FAKE-SIGSTORE-TSA-v1:" + hashlib.sha256(request_der).hexdigest().encode()
        valid = response_der == expected and request["imprint"].hex() == batch_digest
        valid = valid and request["nonce"] == int(nonce_hex, 16) and nonce_hex != "0"
        valid = valid and trust.state == self.trust.state and policy_body == self.policy
        gen_time = self.gen_time_utc or (
            "2026-09-25T19:00:00.0000001Z" if failure == "time" else "2026-09-25T18:30:00Z"
        )
        from matchvet.cb01_schema import compare_utc

        valid_time = (
            compare_utc(cutoff_utc, gen_time) < 0 and compare_utc(gen_time, kickoff_utc) < 0
        )
        status = failure != "status" and valid
        checks = {
            name: {"state": "PASSED", "reasons": []}
            for name in (
                "status",
                "imprint",
                "nonce",
                "signature",
                "signer",
                "eku",
                "policy",
                "chain",
                "trusted_root",
                "certificate_validity_at_gen_time",
                "time_window",
                "denominator",
                "lineage",
            )
        }
        failures = {
            "status": not status,
            "imprint": not valid or failure == "digest",
            "nonce": not valid or failure == "nonce",
            "signature": failure == "signature",
            "signer": failure == "signer",
            "eku": failure == "eku",
            "policy": failure == "policy",
            "chain": failure == "chain",
            "trusted_root": failure == "trust",
            "certificate_validity_at_gen_time": failure == "chain",
            "time_window": not valid_time,
        }
        reasons: list[str] = []
        for name, failed in failures.items():
            if failed:
                reason = f"FIXTURE_{name.upper()}_FAILED"
                checks[name] = {"state": "FAILED", "reasons": [reason]}
                reasons.append(reason)
        identity = {
            "status": "GRANTED",
            "imprint_algorithm": "sha256",
            "imprint_hex": request["imprint"].hex(),
            "nonce_hex": nonce_hex if failure != "nonce" else "1",
            "policy_oid": TSA_POLICY_OID,
            "serial_hex": "1",
            "gen_time_utc": gen_time,
            "accuracy": {"seconds": 1, "millis": None, "micros": None},
            "signer_fingerprint": TSA_SIGNER_SHA256 if failure != "signer" else "0" * 64,
            "issuer": TSA_ISSUER,
            "certificate_serial_hex": "3a13542f0c9061eebcc1432fcb8a8e8b2a238b0c",
            "ess_binding": "ESSCertIDv2_SHA256_VERIFIED",
        }
        if failure == "trust":
            trust_checks = checks["trusted_root"]
            trust_checks.update({"state": "FAILED", "reasons": ["FIXTURE_TRUST_FAILED"]})
        return TimestampVerificationResult(
            "VERIFIED" if not reasons else "FAILED",
            identity,
            tuple(trust.state["chain_fingerprints"]),
            checks,
            tuple(sorted(reasons)),
        )


def test_exact_batch_is_witnessed_once_and_replays_after_store_reopen(
    cloned_case: EnrollmentCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_rebuild(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("CB01 must replay retained upstream work, never rebuild it.")

    monkeypatch.setattr(F11EvidenceRepository, "build_or_replay_for_freeze", refuse_rebuild)
    monkeypatch.setattr(ModelContractRepository, "build", refuse_rebuild)
    monkeypatch.setattr(F16MatchweekProcessor, "process_phase", refuse_rebuild)
    backend = DeterministicWitnessBackend()
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        first = repository.enroll_fixture(cloned_case.request)
        assert first.state == "PUBLISHED"
        assert first.publication_digest is not None
        assert [row.preference_id for row in first.rows] == [
            "asian_handicap_home_0_0",
            "match_winner_home",
        ]
        assert {row.disposition for row in first.rows} == {"ENROLLED_LIVE"}
        assert backend.request_count == 1
        assert backend.refresh_count == 1
        batch_bytes = ArtifactStore(store).read_artifact(first.batch_digest)
        batch = _read_cb01(store, first.batch_digest, "FixtureEnrollmentBatch")
        assert batch["expected_preference_ids"] == [
            "asian_handicap_home_0_0",
            "match_winner_home",
        ]
        assert [row["preference_id"] for row in batch["entries"]] == batch[
            "expected_preference_ids"
        ]
        from matchvet.cb01_trust import _parse_ts_query

        attempt = _read_cb01(store, first.attempt_digest or "", "TimestampAttempt")
        request = ArtifactStore(store).read_artifact(attempt["request_digest"])
        parsed_request = _parse_ts_query(request)
        assert parsed_request["cert_req"] is True
        assert parsed_request["algorithm_oid"] == "2.16.840.1.101.3.4.2.1"
        assert parsed_request["imprint"] == hashlib.sha256(batch_bytes).digest()
        assert f"{parsed_request['nonce']:x}" == attempt["nonce_hex"]
        for entry in batch["entries"]:
            pre = _read_cb01(store, entry["pre_enrollment_digest"], "PreEnrollment")
            assert all(
                pre["lineage"][key]["state"] == "PRESENT"
                for key in (
                    "f11_evidence",
                    "f13_input",
                    "f13_result",
                    "f13_history",
                    "f14_decision",
                    "f14_policy",
                    "f16_manifest",
                    "f16_match_result",
                )
            )
            assert all(value["state"] == "NOT_ASSESSED" for value in pre["eligibility"].values())
            pre_keys = _all_object_keys(pre)
            assert not {"outcome", "settlement", "f19"} & pre_keys
            model_digest = pre["lineage"]["f13_result"]["digest"]
            model_value = json.loads(ArtifactStore(store).read_artifact(model_digest))
            for family in pre["forecast"]["families"]:
                assert (
                    family["retained_family_payload"] == model_value["results"][family["family_id"]]
                )
        publication = repository.replay(first.publication_digest)
        assert publication.batch_digest == first.batch_digest

    with open_store(cloned_case.database, private_root=cloned_case.root) as reopened:
        repository = BootstrapRepository(reopened, witness_backend=backend)
        replayed = repository.enroll_fixture(cloned_case.request)
        assert replayed.publication_digest == first.publication_digest
        resumed = repository.resume(first.batch_digest, first.attempt_digest or "")
        assert resumed.publication_digest == first.publication_digest
        assert backend.request_count == 1
        assert (
            repository.inspect_denominator(
                cloned_case.freeze_digest,
                cloned_case.profile_digest,
                (first.publication_digest,),
            )
            .rows[0]
            .state
            == "ENROLLED_LIVE"
        )


def _all_object_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_object_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_object_keys(item) for item in value))
    return set()


def test_verified_batch_keeps_missing_f16_rows_incomplete_and_visible(
    cloned_case: EnrollmentCase,
) -> None:
    backend = DeterministicWitnessBackend()
    request = replace(cloned_case.request, f16_manifest_digest=None)
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        result = repository.enroll_fixture(request)

        assert result.state == "PUBLISHED"
        assert result.publication_digest is not None
        assert result.verification_digest is not None
        assert {row.disposition for row in result.rows} == {"INCOMPLETE"}
        verification = _read_cb01(store, result.verification_digest, "TimestampVerification")
        assert verification["state"] == "VERIFIED"
        batch = _read_cb01(store, result.batch_digest, "FixtureEnrollmentBatch")
        assert [row["preference_id"] for row in batch["entries"]] == batch[
            "expected_preference_ids"
        ]
        assert batch["lineage"]["f16_manifest"]["state"] == "ABSENT"
        assert batch["lineage"]["f11_evidence"]["state"] == "UNPERFORMED"
        view = repository.inspect_denominator(
            cloned_case.freeze_digest,
            cloned_case.profile_digest,
            (result.publication_digest,),
        )
        assert len(view.rows) == len(batch["expected_preference_ids"])
        assert {row.state for row in view.rows} == {"INCOMPLETE"}


def test_denominator_inspection_keeps_every_f06_exclusion(tmp_path: Path) -> None:
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        assessment = _persistable_schedule_assessment(
            store,
            tmp_path,
            (
                ("2026-09-25", "20:00", "Friday United", "Friday City"),
                ("2026-09-28", "20:00", "Monday United", "Monday City"),
                ("2026-09-29", "20:00", "Excluded United", "Excluded City"),
            ),
        )
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        freeze = MatchweekMembershipRepository(store).freeze_exact(
            "2026-27",
            "2026-09-25",
            assessment.digest,
            "matchvet:matchweek-membership",
            "1",
        )
        profile = PreferenceProfileRepository(store).build_profile(
            ("asian_handicap_home_0_0", "match_winner_home")
        )

        view = BootstrapRepository(store).inspect_denominator(freeze.freeze_digest, profile.digest)

        assert len(view.rows) == len(freeze.memberships) * len(profile.enabled_preferences)
        excluded = [row for row in view.rows if row.membership_state != "INCLUDED"]
        assert excluded
        assert {row.state for row in excluded} == {"EXCLUDED"}


def test_recovery_reuses_request_response_and_partial_records(
    cloned_case: EnrollmentCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = DeterministicWitnessBackend()
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        original_publish = repository._publish_kind

        def stop_before_attempt(kind: str, content: bytes) -> str:
            if kind == "TimestampAttempt":
                raise SystemExit("interrupted after retained RFC3161 request")
            return original_publish(kind, content)

        with monkeypatch.context() as patcher:
            patcher.setattr(repository, "_publish_kind", stop_before_attempt)
            with pytest.raises(SystemExit, match="retained RFC3161 request"):
                repository.enroll_fixture(cloned_case.request)

        batches = _cb01_artifacts(store, "FixtureEnrollmentBatch")
        requests = [
            item
            for item in store.artifact_catalog()
            if item.media_type.startswith(REQUEST_MEDIA_TYPE)
        ]
        assert len(batches) == 1
        assert len(requests) == 1
        assert not _cb01_artifacts(store, "TimestampAttempt")
        batch_digest = batches[0][0]
        request_digest = requests[0].digest

    with open_store(cloned_case.database, private_root=cloned_case.root) as reopened:
        repository = BootstrapRepository(reopened, witness_backend=backend)
        original_publish = repository._publish_kind

        def stop_before_result(kind: str, content: bytes) -> str:
            if kind == "TimestampAttemptResult":
                raise SystemExit("interrupted after retained TSA response")
            return original_publish(kind, content)

        with monkeypatch.context() as patcher:
            patcher.setattr(repository, "_publish_kind", stop_before_result)
            with pytest.raises(SystemExit, match="retained TSA response"):
                repository.enroll_fixture(cloned_case.request)

        attempts = _cb01_artifacts(reopened, "TimestampAttempt")
        assert len(attempts) == 1
        attempt_digest, attempt = attempts[0]
        assert attempt["request_digest"] == request_digest
        assert backend.request_count == 1

    with open_store(cloned_case.database, private_root=cloned_case.root) as reopened:
        repository = BootstrapRepository(reopened, witness_backend=backend)
        original_publish = repository._publish_kind

        def stop_after_first_record(kind: str, content: bytes) -> str:
            digest = original_publish(kind, content)
            if kind == "EnrollmentRecord":
                raise SystemExit("interrupted after the first enrollment record")
            return digest

        with monkeypatch.context() as patcher:
            patcher.setattr(repository, "_publish_kind", stop_after_first_record)
            with pytest.raises(SystemExit, match="first enrollment record"):
                repository.resume(batch_digest, attempt_digest)

        records = _cb01_artifacts(reopened, "EnrollmentRecord")
        assert len(records) == 1
        assert len(_cb01_artifacts(reopened, "TimestampVerification")) == 1
        assert not _cb01_artifacts(reopened, "FixtureEnrollmentPublication")

    with open_store(cloned_case.database, private_root=cloned_case.root) as reopened:
        repository = BootstrapRepository(reopened, witness_backend=backend)
        recovered = repository.resume(batch_digest, attempt_digest)
        assert recovered.state == "PUBLISHED"
        assert recovered.publication_digest is not None
        assert backend.request_count == 1


def test_outcome_attachments_preserve_f19_states_and_correction_facts(
    cloned_case: EnrollmentCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = DeterministicWitnessBackend()
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        result = repository.enroll_fixture(cloned_case.request)
        assert result.publication_digest is not None
        batch = _read_cb01(store, result.batch_digest, "FixtureEnrollmentBatch")
        manifest_digest = batch["lineage"]["f16_manifest"]["id"]
        match_digest = batch["lineage"]["f16_match_result"]["id"]
        fixture_id = batch["anchor"]["fixture_id"]
        enrollment_by_preference = {row.preference_id: row.enrollment_digest for row in result.rows}
        settlements = SettlementRepository(store)

        pending = settlements.build(
            manifest_digest,
            match_digest,
            "match_winner_home",
            (
                SettlementEvidence(
                    fixture_id=fixture_id,
                    source_key="competition-feed",
                    record_id="pending-score",
                    fixture_status="UNKNOWN",
                    full_time_home_goals=1,
                    full_time_away_goals=0,
                ),
            ),
        )
        assert pending.state is SettlementState.PENDING
        publish_kind = repository._publish_kind

        def interrupt_before_outcome(kind: str, content: bytes) -> str:
            if kind == "OutcomeAttachment":
                raise RuntimeError("simulated interruption after fact publication")
            return publish_kind(kind, content)

        monkeypatch.setattr(repository, "_publish_kind", interrupt_before_outcome)
        with pytest.raises(RuntimeError, match="simulated interruption"):
            repository.attach_outcome(
                enrollment_by_preference["match_winner_home"] or "", pending.digest
            )
        orphan_fact_digests = {
            digest for digest, _ in _cb01_artifacts(store, "OutcomeFactAttachment")
        }
        assert len(orphan_fact_digests) == 1
        orphan_fact_digest = next(iter(orphan_fact_digests))
        with pytest.raises(CB01Error, match="selected exact OutcomeAttachment"):
            repository.replay(result.publication_digest, (orphan_fact_digest,))
        monkeypatch.setattr(repository, "_publish_kind", publish_kind)
        first_attachment, first_fact = repository.attach_outcome(
            enrollment_by_preference["match_winner_home"] or "", pending.digest
        )
        assert first_fact == orphan_fact_digest
        pending_fact = _read_cb01(store, first_fact, "OutcomeFactAttachment")
        assert pending_fact["facts"]["full_time_home_goals"]["state"] == "MISSING"
        assert pending_fact["facts"]["full_time_home_goals"]["value"] is None
        with pytest.raises(CB01Error, match="selected exact OutcomeAttachment"):
            repository.replay(result.publication_digest, (first_fact,))

        finished_evidence = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="competition-feed",
            record_id="final-score",
            fixture_status="FINISHED",
            regulation_completed=True,
            full_time_home_goals=2,
            full_time_away_goals=0,
            half_time_home_goals=1,
            half_time_away_goals=0,
            corners_home=4,
            corners_away=2,
            source_assertion_ids=("assertion:final-score",),
            published_at_utc="2026-09-25T18:00:00Z",
            observed_at_utc="2026-09-25T18:01:00Z",
            retrieved_at_utc="2026-09-25T18:02:00Z",
            provenance={"source_revision_id": "score-revision-1"},
        )
        supplemental_evidence = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="FEDERATION",
            source_key="federation-feed",
            record_id="federation-corners",
            fixture_status="FINISHED",
            regulation_completed=True,
            corners_home=4,
            corners_away=2,
            source_assertion_ids=("assertion:federation-corners",),
        )
        T10GradingService(store).grade_fixture((supplemental_evidence,), fixture_id=fixture_id)
        win = settlements.correct(pending.digest, (finished_evidence,))
        assert win.settlement_result is SettlementResult.WIN
        win_attachment, win_fact = repository.attach_outcome(
            enrollment_by_preference["match_winner_home"] or "",
            win.digest,
            exact_fact_evidence=(supplemental_evidence.evidence_digest,),
            predecessor_digest=first_attachment,
        )
        win_body = _read_cb01(store, win_attachment, "OutcomeAttachment")
        assert win_body["state"] == "WIN"
        assert win_body["result"] == "WIN"
        win_facts = _read_cb01(store, win_fact, "OutcomeFactAttachment")
        for fact_key, expected in (
            ("full_time_home_goals", 2),
            ("full_time_away_goals", 0),
            ("half_time_home_goals", 1),
            ("half_time_away_goals", 0),
            ("corners_home", 4),
            ("corners_away", 2),
        ):
            assert win_facts["facts"][fact_key]["state"] == "AVAILABLE"
            assert win_facts["facts"][fact_key]["value"] == expected
        assert finished_evidence.evidence_digest in win_facts["evidence_snapshot_digests"]
        assert supplemental_evidence.evidence_digest in win_facts["evidence_snapshot_digests"]

        conflict_a = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="official-league-feed",
            record_id="official-score-a",
            fixture_status="FINISHED",
            full_time_home_goals=2,
            full_time_away_goals=0,
        )
        conflict_b = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="official-league-feed",
            record_id="official-score-b",
            fixture_status="FINISHED",
            full_time_home_goals=0,
            full_time_away_goals=2,
        )
        conflicting = settlements.correct(win.digest, (conflict_a, conflict_b))
        assert conflicting.state is SettlementState.CONFLICTING
        fact_digests_before = {
            digest for digest, _ in _cb01_artifacts(store, "OutcomeFactAttachment")
        }
        with pytest.raises(CB01Error, match="complete exact F19 evidence snapshot"):
            repository.attach_outcome(
                enrollment_by_preference["match_winner_home"] or "",
                conflicting.digest,
                exact_fact_evidence=(conflict_a.evidence_digest,),
                predecessor_digest=win_attachment,
            )
        assert fact_digests_before == {
            digest for digest, _ in _cb01_artifacts(store, "OutcomeFactAttachment")
        }
        conflict_attachment, conflict_fact = repository.attach_outcome(
            enrollment_by_preference["match_winner_home"] or "",
            conflicting.digest,
            predecessor_digest=win_attachment,
        )
        conflict_body = _read_cb01(store, conflict_attachment, "OutcomeAttachment")
        assert conflict_body["state"] == "CONFLICTING"
        assert conflict_body["result"] is None
        conflict_facts = _read_cb01(store, conflict_fact, "OutcomeFactAttachment")
        assert conflict_facts["facts"]["full_time_home_goals"]["state"] == "CONFLICTING"
        assert conflict_facts["family_states"]["FULL_TIME_GOALS"]["state"] == "CONFLICTING"

        loss_evidence = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="official-league-feed",
            record_id="corrected-loss-score",
            fixture_status="FINISHED",
            full_time_home_goals=0,
            full_time_away_goals=1,
            half_time_home_goals=0,
            half_time_away_goals=1,
        )
        loss = settlements.correct(conflicting.digest, (loss_evidence,))
        assert loss.settlement_result is SettlementResult.LOSS
        loss_attachment, loss_fact = repository.attach_outcome(
            enrollment_by_preference["match_winner_home"] or "",
            loss.digest,
            predecessor_digest=conflict_attachment,
        )
        loss_body = _read_cb01(store, loss_attachment, "OutcomeAttachment")
        assert loss_body["state"] == "LOSS"
        assert loss_body["result"] == "LOSS"

        void_evidence = SettlementEvidence(
            fixture_id=fixture_id,
            source_level="COMPETITION",
            source_key="official-league-feed",
            record_id="cancelled-fixture",
            fixture_status="CANCELLED",
        )
        void = settlements.correct(loss.digest, (void_evidence,))
        assert void.settlement_result is SettlementResult.VOID
        void_attachment, void_fact = repository.attach_outcome(
            enrollment_by_preference["match_winner_home"] or "",
            void.digest,
            predecessor_digest=loss_attachment,
        )
        void_body = _read_cb01(store, void_attachment, "OutcomeAttachment")
        assert void_body["state"] == "VOID"
        assert void_body["result"] == "VOID"
        void_facts = _read_cb01(store, void_fact, "OutcomeFactAttachment")
        assert void_facts["facts"]["full_time_home_goals"]["state"] == "NOT_APPLICABLE"

        push = settlements.build(
            manifest_digest,
            match_digest,
            "asian_handicap_home_0_0",
            (
                SettlementEvidence(
                    fixture_id=fixture_id,
                    source_level="COMPETITION",
                    source_key="competition-feed",
                    record_id="draw-score",
                    fixture_status="FINISHED",
                    regulation_completed=True,
                    full_time_home_goals=1,
                    full_time_away_goals=1,
                ),
            ),
        )
        assert push.settlement_result is SettlementResult.PUSH
        push_attachment, push_fact = repository.attach_outcome(
            enrollment_by_preference["asian_handicap_home_0_0"] or "", push.digest
        )
        push_body = _read_cb01(store, push_attachment, "OutcomeAttachment")
        assert push_body["state"] == "PUSH"
        assert push_body["result"] == "PUSH"

        replayed = repository.replay(
            result.publication_digest,
            (
                first_attachment,
                first_fact,
                win_attachment,
                win_fact,
                conflict_attachment,
                conflict_fact,
                loss_attachment,
                loss_fact,
                void_attachment,
                void_fact,
                push_attachment,
                push_fact,
            ),
        )
        assert len(replayed.attachments) == 12


@pytest.mark.parametrize(
    ("failure", "expected_check"),
    [
        ("digest", "imprint"),
        ("nonce", "nonce"),
        ("signer", "signer"),
        ("signature", "signature"),
        ("chain", "chain"),
        ("trust", "trusted_root"),
        ("time", "time_window"),
    ],
)
def test_invalid_sigstore_witness_is_durable_and_never_live(
    cloned_case: EnrollmentCase, failure: str, expected_check: str
) -> None:
    backend = DeterministicWitnessBackend(failure=failure)
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        result = repository.enroll_fixture(cloned_case.request)
        assert result.publication_digest is None
        assert result.failure_digests
        assert result.verification_digest is not None
        verification = repository._read_kind(result.verification_digest, "TimestampVerification")
        assert verification["state"] == "FAILED"
        assert verification["checks"][expected_check]["state"] == "FAILED"
        assert not result.rows
        failure_body = repository._read_kind(result.failure_digests[0], "TimestampFailure")
        assert failure_body["expected_preference_ids"] == [
            "asian_handicap_home_0_0",
            "match_winner_home",
        ]


def test_tsa_unavailable_is_durable_and_retry_requires_explicit_request(
    cloned_case: EnrollmentCase,
) -> None:
    backend = DeterministicWitnessBackend(transport_states=("UNAVAILABLE", "RECEIVED"))
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        repository = BootstrapRepository(store, witness_backend=backend)
        first = repository.enroll_fixture(cloned_case.request)
        assert first.state == "INCOMPLETE"
        assert first.publication_digest is None
        assert backend.request_count == 1
        repeated = repository.enroll_fixture(cloned_case.request)
        assert repeated.publication_digest is None
        assert backend.request_count == 1
        recovered = repository.resume(
            first.batch_digest,
            first.attempt_digest or "",
            retry_failed=True,
        )
        assert recovered.publication_digest is not None
        assert backend.request_count == 2
        attempts = repository._attempts_for_batch(first.batch_digest)
        assert [item[1]["attempt_number"] for item in attempts] == [1, 2]
        assert attempts[1][1]["predecessor_attempt_digest"] == attempts[0][0]


@pytest.mark.parametrize("transport_state", ["REJECTED", "MALFORMED"])
def test_rejected_or_malformed_tsa_response_stays_incomplete(
    cloned_case: EnrollmentCase, transport_state: str
) -> None:
    backend = DeterministicWitnessBackend(transport_states=(transport_state,))
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        result = BootstrapRepository(store, witness_backend=backend).enroll_fixture(
            cloned_case.request
        )
        assert result.state == "INCOMPLETE"
        assert result.publication_digest is None
        assert result.failure_digests
        if transport_state == "MALFORMED":
            assert result.verification_digest is not None
            verification = _read_cb01(store, result.verification_digest, "TimestampVerification")
            assert verification["state"] == "FAILED"


@pytest.mark.parametrize(
    "gen_time_utc",
    (
        "2026-09-25T17:59:59.9999999Z",
        "2026-09-25T18:00:00Z",
        "2026-09-25T19:00:00Z",
        "2026-09-25T19:00:00.0000001Z",
    ),
)
def test_signed_gen_time_must_be_strictly_inside_cutoff_and_kickoff(
    cloned_case: EnrollmentCase, gen_time_utc: str
) -> None:
    backend = DeterministicWitnessBackend(gen_time_utc=gen_time_utc)
    with open_store(cloned_case.database, private_root=cloned_case.root) as store:
        result = BootstrapRepository(store, witness_backend=backend).enroll_fixture(
            cloned_case.request
        )
        assert result.publication_digest is None
        assert result.verification_digest is not None
        verification = BootstrapRepository(store, witness_backend=backend)._read_kind(
            result.verification_digest, "TimestampVerification"
        )
        assert verification["checks"]["time_window"]["state"] == "FAILED"

from __future__ import annotations

import json
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import matchvet.t19 as t19
from matchvet.runs import RunLifecycleError, observe_resources
from matchvet.t19 import (
    REQUIRED_QUALIFICATION_GATES,
    GateEvidence,
    GateStatus,
    QualificationEvidence,
    QualificationStatus,
    RecordedCorpus,
    RecordedReplayResult,
    ResourceMeasurement,
    T19Error,
    T19ValidationError,
    _offline_network_guard,
    qualify_research_only,
    run_recorded_replay,
)

CORPUS_PATH = Path(__file__).parent / "recorded" / "t19-seven-league.json"


def _replay() -> RecordedReplayResult:
    corpus = RecordedCorpus.read(CORPUS_PATH)
    return RecordedReplayResult(
        corpus_digest=corpus.digest,
        league_keys=corpus.league_keys,
        target_match_count=7,
        preference_result_count=7 * 37,
        grade_count=7 * 37,
        research_only=True,
        production_language=(),
        replay_digest="a" * 64,
        report_digest="b" * 64,
        audit_digest="c" * 64,
        export_digest="d" * 64,
        backup_digest="e" * 64,
        restored_audit_digest="c" * 64,
        evaluation_digest="f" * 64,
        evaluation_lifecycle="EVALUATED_RESEARCH_ONLY",
        evaluation_status="INCONCLUSIVE",
        details=MappingProxyType(
            {
                "calibration_bundle_statuses": {
                    "AVAILABLE": 0,
                    "MODEL_UNAVAILABLE": 7,
                    "REJECT": 0,
                },
                "contextual_conflict_count": 1,
                "chronological_evaluated_target_count": 0,
                "chronological_framework_observation_count": 1,
                "chronological_model_unavailable_exclusion_count": 7,
                "fallback_imports": 1,
                "grade_identity_digest": "9" * 64,
                "missing_corner_void_count": 12,
                "missing_data_inference_count": 0,
                "model_statuses": {"AVAILABLE": 1, "MODEL_UNAVAILABLE": 1},
                "post_cutoff_withdrawal_count": 1,
                "prohibited_market_key_count": 0,
                "rejected_preference_count": 7 * 37,
                "restored_grade_count": 7 * 37,
                "restored_grade_identity_digest": "9" * 64,
                "unspecified_identity_count": 0,
                "unknown_weather_count": 2,
                "withdrawn_fixture_count": 1,
            }
        ),
    )


def _resources() -> ResourceMeasurement:
    return ResourceMeasurement(
        runtime_seconds=10.0,
        peak_memory_bytes=256 * 1024**2,
        temporary_storage_growth_bytes=8 * 1024**2,
        final_managed_storage_bytes=16 * 1024**2,
        free_space_floor_bytes=4 * 1024**3,
        cpu_heavy_concurrency=1,
        network_bytes=0,
    )


def _gates() -> tuple[GateEvidence, ...]:
    return tuple(
        GateEvidence(
            name=name,
            status=GateStatus.PASS,
            command=f"check {name}",
            exit_code=0,
            output_digest=str(index + 1).zfill(64),
        )
        for index, name in enumerate(REQUIRED_QUALIFICATION_GATES)
    )


def test_recorded_corpus_is_rights_safe_and_covers_the_exact_target_league_set() -> None:
    corpus = RecordedCorpus.read(CORPUS_PATH)

    assert corpus.league_keys == (
        "premier_league",
        "serie_a",
        "la_liga",
        "bundesliga",
        "ligue_1",
        "liga_portugal",
        "belgian_pro_league",
    )
    assert corpus.rights.redistributable is True
    assert corpus.rights.contains_third_party_raw_data is False
    assert corpus.digest == RecordedCorpus.from_bytes(corpus.to_bytes()).digest


def test_recorded_replay_network_guard_blocks_socket_connections() -> None:
    with (
        _offline_network_guard(),
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection,
        pytest.raises(T19Error, match="network operation"),
    ):
        connection.connect(("127.0.0.1", 9))


def test_recorded_replay_honors_device_free_space_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = RecordedCorpus.read(CORPUS_PATH)
    observed = observe_resources(tmp_path / "matchvet.sqlite3")
    monkeypatch.setattr(
        t19,
        "observe_resources",
        lambda _path: replace(observed, free_space_bytes=0),
    )

    with pytest.raises(RunLifecycleError) as failure:
        run_recorded_replay(corpus, tmp_path / "replay")

    assert failure.value.error.code == "MV-PREFLIGHT-FREE_SPACE"


def test_replay_comparison_preserves_operational_backup_identity(tmp_path: Path) -> None:
    first = _replay().to_dict()
    second = dict(first)
    second["backup_digest"] = "0" * 64
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps({"replay": first}), encoding="utf-8")
    second_path.write_text(json.dumps({"replay": second}), encoding="utf-8")
    comparator = Path(__file__).resolve().parents[1] / "scripts/compare-t19-replays.py"

    matched = subprocess.run(
        (sys.executable, str(comparator), str(first_path), str(second_path)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert matched.returncode == 0

    second["audit_digest"] = "0" * 64
    second_path.write_text(json.dumps({"replay": second}), encoding="utf-8")
    mismatched = subprocess.run(
        (sys.executable, str(comparator), str(first_path), str(second_path)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatched.returncode == 1
    assert "audit_digest" in mismatched.stderr


def test_recorded_corpus_rejects_missing_league_and_unsafe_rights(tmp_path: Path) -> None:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["leagues"] = payload["leagues"][:-1]
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(T19ValidationError, match="exact seven-league"):
        RecordedCorpus.read(missing)

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["rights"]["redistributable"] = False
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(T19ValidationError, match="redistributable"):
        RecordedCorpus.read(unsafe)

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["rights"]["license"] = "custom"
    with pytest.raises(T19ValidationError, match=r"CC0-1\.0"):
        RecordedCorpus.from_bytes(json.dumps(payload).encode())

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["schema"] = "matchvet.recorded-qualification-corpus.v999"
    with pytest.raises(T19ValidationError, match="schema"):
        RecordedCorpus.from_bytes(json.dumps(payload).encode())

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["captured_at_utc"] = "2026-09-17T13:00:00+01:00"
    with pytest.raises(T19ValidationError, match="UTC"):
        RecordedCorpus.from_bytes(json.dumps(payload).encode())

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["undeclared_raw"] = {"source": "not covered by the corpus digest"}
    with pytest.raises(T19ValidationError, match=r"extra=\['undeclared_raw'\]"):
        RecordedCorpus.from_bytes(json.dumps(payload).encode())

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["leagues"][0]["history_results"] = payload["leagues"][0]["history_results"][:-1]
    with pytest.raises(T19ValidationError, match="exactly six"):
        RecordedCorpus.from_bytes(json.dumps(payload).encode())


@pytest.mark.recorded_e2e
def test_all_seven_league_replay_is_research_only_and_deterministic(tmp_path: Path) -> None:
    corpus = RecordedCorpus.read(CORPUS_PATH)

    first = run_recorded_replay(corpus, tmp_path / "first")
    second = run_recorded_replay(corpus, tmp_path / "second")

    assert first.failures() == ()
    assert first.replay_digest == second.replay_digest
    assert first.report_digest == second.report_digest
    assert first.audit_digest == second.audit_digest
    assert first.export_digest == second.export_digest
    # Each verified backup preserves its own run IDs, times, and device observations.
    # Reproducibility is the restored authoritative state, not identical SQLite bytes.
    assert first.restored_audit_digest == second.restored_audit_digest
    assert first.evaluation_digest == second.evaluation_digest
    assert first.details["grade_identity_digest"] == second.details["grade_identity_digest"]
    assert (
        first.details["restored_grade_identity_digest"]
        == second.details["restored_grade_identity_digest"]
    )
    assert first.target_match_count == 7
    assert first.preference_result_count == 7 * 37
    assert first.grade_count == 7 * 37
    assert first.research_only is True
    assert first.production_language == ()
    assert first.details["fallback_imports"] == 1
    assert first.details["contextual_conflict_count"] == 1
    model_statuses = first.details["model_statuses"]
    assert isinstance(model_statuses, dict)
    assert model_statuses["AVAILABLE"] > 0
    assert model_statuses["MODEL_UNAVAILABLE"] > 0
    assert sum(model_statuses.values()) == 7 * 4
    assert first.details["calibration_bundle_statuses"] == {
        "AVAILABLE": 0,
        "MODEL_UNAVAILABLE": 7,
        "REJECT": 0,
    }
    assert first.details["unknown_weather_count"] == 2
    assert first.details["withdrawn_fixture_count"] == 1
    assert first.details["missing_data_inference_count"] == 0
    assert first.details["missing_corner_void_count"] == 12
    assert first.details["rejected_preference_count"] == 7 * 37
    assert first.details["unspecified_identity_count"] == 0


def test_qualification_is_fail_closed_and_can_only_qualify_research_only() -> None:
    evidence = QualificationEvidence(
        software_commit="1" * 40,
        environment_digest="2" * 64,
        gates=_gates(),
        replay=_replay(),
        deterministic_replay_digest="a" * 64,
        resources=_resources(),
        known_limitations=("The corpus is structural and does not prove predictive reliability.",),
    )

    result = qualify_research_only(evidence)

    assert result.status is QualificationStatus.QUALIFIED_RESEARCH_ONLY
    assert result.mode == "RESEARCH_ONLY"
    assert result.production_promotion is False
    assert "PLAY" not in result.to_bytes().decode("utf-8")
    assert result.digest == qualify_research_only(evidence).digest

    failed = qualify_research_only(
        QualificationEvidence(
            software_commit=evidence.software_commit,
            environment_digest=evidence.environment_digest,
            gates=evidence.gates[:-1],
            replay=evidence.replay,
            deterministic_replay_digest=evidence.deterministic_replay_digest,
            resources=evidence.resources,
            known_limitations=evidence.known_limitations,
        )
    )
    assert failed.status is QualificationStatus.NOT_QUALIFIED
    assert failed.failure_reasons == ("MISSING_GATE:failure_injection",)


def test_qualification_rejects_replay_or_resource_contract_failure() -> None:
    replay = _replay()
    mismatched = QualificationEvidence(
        software_commit="1" * 40,
        environment_digest="2" * 64,
        gates=_gates(),
        replay=replay,
        deterministic_replay_digest="0" * 64,
        resources=_resources(),
        known_limitations=("Statistical promotion remains out of scope.",),
    )
    result = qualify_research_only(mismatched)
    assert result.status is QualificationStatus.NOT_QUALIFIED
    assert "REPLAY_NOT_DETERMINISTIC" in result.failure_reasons

    over_memory = QualificationEvidence(
        software_commit="1" * 40,
        environment_digest="2" * 64,
        gates=_gates(),
        replay=replay,
        deterministic_replay_digest=replay.replay_digest,
        resources=ResourceMeasurement(
            runtime_seconds=10.0,
            peak_memory_bytes=2 * 1024**3,
            temporary_storage_growth_bytes=0,
            final_managed_storage_bytes=0,
            free_space_floor_bytes=4 * 1024**3,
            cpu_heavy_concurrency=1,
            network_bytes=0,
        ),
        known_limitations=("Statistical promotion remains out of scope.",),
    )
    result = qualify_research_only(over_memory)
    assert result.status is QualificationStatus.NOT_QUALIFIED
    assert "RESOURCE_BUDGET:peak_memory_bytes" in result.failure_reasons

    over_runtime_target = QualificationEvidence(
        software_commit="1" * 40,
        environment_digest="2" * 64,
        gates=_gates(),
        replay=replay,
        deterministic_replay_digest=replay.replay_digest,
        resources=ResourceMeasurement(
            runtime_seconds=7_201.0,
            peak_memory_bytes=256 * 1024**2,
            temporary_storage_growth_bytes=0,
            final_managed_storage_bytes=0,
            free_space_floor_bytes=4 * 1024**3,
            cpu_heavy_concurrency=1,
            network_bytes=0,
        ),
        known_limitations=("Statistical promotion remains out of scope.",),
    )
    result = qualify_research_only(over_runtime_target)
    assert result.status is QualificationStatus.NOT_QUALIFIED
    assert "RESOURCE_BUDGET:runtime_seconds" in result.failure_reasons

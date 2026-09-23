#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import MappingProxyType

from matchvet.t19 import (
    GateEvidence,
    GateStatus,
    QualificationEvidence,
    QualificationStatus,
    RecordedReplayResult,
    ResourceMeasurement,
    T19ValidationError,
    qualify_research_only,
)


def _failed_replay(reason: str) -> tuple[RecordedReplayResult, ResourceMeasurement]:
    replay = RecordedReplayResult(
        corpus_digest="0" * 64,
        league_keys=(),
        target_match_count=0,
        preference_result_count=0,
        grade_count=0,
        research_only=False,
        production_language=(reason,),
        replay_digest="0" * 64,
        report_digest="0" * 64,
        audit_digest="0" * 64,
        export_digest="0" * 64,
        backup_digest="0" * 64,
        restored_audit_digest="1" * 64,
        evaluation_digest="0" * 64,
        evaluation_lifecycle="NOT_RUN",
        evaluation_status="NOT_RUN",
        details=MappingProxyType(
            {
                "grade_identity_digest": "0" * 64,
                "missing_data_inference_count": -1,
                "rejected_preference_count": -1,
                "replay_failure": reason,
                "restored_grade_count": -1,
                "restored_grade_identity_digest": "1" * 64,
                "unspecified_identity_count": -1,
            }
        ),
    )
    resources = ResourceMeasurement(
        runtime_seconds=0.0,
        peak_memory_bytes=None,
        temporary_storage_growth_bytes=0,
        final_managed_storage_bytes=0,
        free_space_floor_bytes=0,
        cpu_heavy_concurrency=0,
        network_bytes=0,
    )
    return replay, resources


def main() -> int:
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: build-t19-manifest.py GATES REPLAY DETERMINISTIC_REPLAY "
            "ENVIRONMENT COMMIT OUTPUT"
        )
    (
        gates_path,
        replay_path,
        deterministic_path,
        environment_path,
        commit_path,
        output_path,
    ) = map(Path, sys.argv[1:])
    gate_lines = gates_path.read_text(encoding="utf-8").splitlines()
    gates: list[GateEvidence] = []
    for line in gate_lines[1:]:
        name, status, exit_code, elapsed, digest, command, _log = line.split("\t", 6)
        log_path = Path(_log)
        details: tuple[str, ...] = ()
        if status == GateStatus.FAIL.value:
            try:
                details = tuple(log_path.read_text(encoding="utf-8").splitlines()[-20:])
            except OSError as error:
                details = (f"qualification log unavailable: {error}",)
        gates.append(
            GateEvidence(
                name=name,
                status=GateStatus(status),
                command=command,
                exit_code=int(exit_code),
                output_digest=digest,
                elapsed_seconds=float(elapsed),
                details=details,
            )
        )
    try:
        measured = json.loads(replay_path.read_text(encoding="utf-8"))
        replay_raw = measured["replay"]
        replay = RecordedReplayResult(
            corpus_digest=replay_raw["corpus_digest"],
            league_keys=tuple(replay_raw["league_keys"]),
            target_match_count=replay_raw["target_match_count"],
            preference_result_count=replay_raw["preference_result_count"],
            grade_count=replay_raw["grade_count"],
            research_only=replay_raw["research_only"],
            production_language=tuple(replay_raw["production_language"]),
            replay_digest=replay_raw["replay_digest"],
            report_digest=replay_raw["report_digest"],
            audit_digest=replay_raw["audit_digest"],
            export_digest=replay_raw["export_digest"],
            backup_digest=replay_raw["backup_digest"],
            restored_audit_digest=replay_raw["restored_audit_digest"],
            evaluation_digest=replay_raw["evaluation_digest"],
            evaluation_lifecycle=replay_raw["evaluation_lifecycle"],
            evaluation_status=replay_raw["evaluation_status"],
            details=MappingProxyType(dict(replay_raw["details"])),
        )
        resources = ResourceMeasurement(**measured["resources"])
    except (OSError, KeyError, TypeError, ValueError, T19ValidationError) as error:
        replay, resources = _failed_replay(f"REPLAY_ARTIFACT_UNAVAILABLE:{error}")
    try:
        deterministic_replay_digest = json.loads(deterministic_path.read_text(encoding="utf-8"))[
            "replay"
        ]["replay_digest"]
    except OSError, KeyError, TypeError, json.JSONDecodeError:
        deterministic_replay_digest = "f" * 64
    evidence = QualificationEvidence(
        software_commit=commit_path.read_text(encoding="utf-8").strip(),
        environment_digest=hashlib.sha256(environment_path.read_bytes()).hexdigest(),
        gates=tuple(gates),
        replay=replay,
        deterministic_replay_digest=deterministic_replay_digest,
        resources=resources,
        known_limitations=(
            "The self-authored structural corpus does not establish real-world "
            "predictive reliability.",
            "No statistical Production Promotion thresholds or acceptance criteria exist in T19.",
            "The replay is offline and does not establish current availability of "
            "live data sources.",
            "Rights-restricted raw third-party source material is deliberately excluded "
            "from export.",
            "Recorded sparse packs exercise missing half-time and corner data as "
            "unavailable evidence.",
        ),
    )
    manifest = qualify_research_only(evidence)
    output_path.write_bytes(manifest.to_bytes() + b"\n")
    print(manifest.status.value)
    for reason in manifest.failure_reasons:
        print(reason)
    return 0 if manifest.status is QualificationStatus.QUALIFIED_RESEARCH_ONLY else 1


if __name__ == "__main__":
    raise SystemExit(main())

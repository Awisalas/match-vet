from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from matchvet.doctor import apply_runtime_limits, build_report, render_human_report
from matchvet.runs import (
    RunCoordinator,
    RunLifecycleError,
    RunStatus,
    build_local_input_contract,
    default_resource_estimate,
    observe_resources,
    read_resume_candidate,
    read_run_status,
)
from matchvet.store import (
    InspectionStatus,
    StoreBusyError,
    StoreMode,
    default_database_path,
    inspect_store,
    open_store,
    termux_private_root,
)
from matchvet.t16 import (
    T16Error,
    T16IntegrityError,
    T16NotFoundError,
    inspect_match,
    read_audit,
    read_report,
    render_markdown_report,
)
from matchvet.t16 import (
    history as read_history,
)
from matchvet.t17 import (
    T17Error,
    backup_store,
    export_matchweek,
    restore_backup,
    verify_backup,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matchvet",
        description="Local-first football research and preference vetting.",
    )
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser("doctor", help="check the pinned Termux environment")
    doctor.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the complete schema-versioned environment report",
    )
    doctor.add_argument(
        "--store",
        type=Path,
        help="inspect this authoritative private-storage database",
    )
    run = commands.add_parser("run", help="start a bounded Matchweek lifecycle")
    run.add_argument("date", nargs="?", help="Matchweek date in Africa/Lagos (YYYY-MM-DD)")
    _add_run_options(run)
    status = commands.add_parser("status", help="show a run's durable lifecycle state")
    status.add_argument("run_id", nargs="?", help="run ID; defaults to the latest run")
    _add_run_options(status)
    resume = commands.add_parser("resume", help="resume a digest-compatible unfinished run")
    resume.add_argument("run_id", nargs="?", help="run ID; defaults to the latest run")
    _add_run_options(resume)
    ingest = commands.add_parser("ingest", help="acquire T06 fixtures and structured history")
    ingest.add_argument("--season", default="2026-27", help="current season in YYYY-YY form")
    ingest.add_argument(
        "--history-season",
        action="append",
        default=[],
        dest="history_seasons",
        help="historical season in YYYY-YY form; repeat for more seasons",
    )
    ingest.add_argument("--resume", dest="resume_run_id", help="resume a T06 run by ID")
    ingest.add_argument(
        "--refresh-current",
        action="store_true",
        help="refresh the current-season cache instead of reusing it",
    )
    _add_run_options(ingest)
    freeze = commands.add_parser(
        "freeze", help="freeze T05 Matchweek membership from acquired Fixture Revisions"
    )
    freeze.add_argument("date", help="Matchweek Friday in Africa/Lagos (YYYY-MM-DD)")
    freeze.add_argument("--season", default="2026-27", help="Target season in YYYY-YY form")
    freeze.add_argument(
        "--as-of-utc",
        help="observation time for deterministic replay (canonical UTC ISO-8601)",
    )
    freeze.add_argument("--resume", dest="resume_run_id", help="resume a T05 run by ID")
    _add_run_options(freeze)
    grade = commands.add_parser(
        "grade", help="grade all 37 T10 preferences from recorded fixture evidence"
    )
    grade.add_argument(
        "--input",
        type=Path,
        required=True,
        dest="input_path",
        help="local JSON evidence pack recorded from an approved fixture source",
    )
    grade.add_argument(
        "--finalize",
        action="store_true",
        help="close unresolved evidence as VOID instead of leaving it pending",
    )
    _add_run_options(grade)
    report = commands.add_parser("report", help="show the latest complete Matchweek Report")
    report.add_argument("matchweek", nargs="?", help="Matchweek ID; defaults to the latest")
    report.add_argument(
        "--audit",
        action="store_true",
        help="show the complete schema-versioned audit instead of the concise report",
    )
    _add_run_options(report)
    inspect_command = commands.add_parser(
        "inspect", help="show the complete audit detail for one Target Match"
    )
    inspect_command.add_argument("match", help="fixture or Target Match ID")
    inspect_command.add_argument(
        "--matchweek", help="Matchweek ID; defaults to the latest complete publication"
    )
    _add_run_options(inspect_command)
    history_command = commands.add_parser(
        "history", help="list run, audit, grading, export, backup, and policy state"
    )
    _add_run_options(history_command)
    export = commands.add_parser(
        "export", help="publish a complete Matchweek copy to shared storage"
    )
    export.add_argument("--destination", type=Path, required=True, help="shared export directory")
    export.add_argument(
        "--matchweek", help="Matchweek ID; defaults to the latest complete publication"
    )
    export.add_argument(
        "--include-raw-evidence",
        "--raw-evidence",
        action="store_true",
        dest="include_raw_evidence",
        help="copy only rights-safe reusable raw evidence",
    )
    _add_run_options(export)
    backup = commands.add_parser("backup", help="create or verify a private recovery copy")
    backup.add_argument("--destination", type=Path, help="shared backup directory")
    backup.add_argument("--verify", type=Path, metavar="BUNDLE", help="verify an existing backup")
    _add_run_options(backup)
    restore = commands.add_parser(
        "restore", help="restore a verified backup into a new private target"
    )
    restore.add_argument(
        "--source", type=Path, required=True, help="verified shared backup directory"
    )
    restore.add_argument("--target", type=Path, required=True, help="new private database path")
    restore.add_argument("--json", action="store_true", dest="as_json", help="print JSON")
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", type=Path, help="authoritative private-storage database")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON")


def _show_bootstrap_state() -> None:
    database_path = default_database_path()
    private_root = termux_private_root()
    store = inspect_store(database_path, private_root=private_root)
    print("MatchVet")
    if store.status is InspectionStatus.HEALTHY:
        print("State: READY")
        print("Mode: RESEARCH_ONLY")
        print(f"Store: healthy; schema {store.schema_version}")
        try:
            incomplete = read_resume_candidate(database_path, private_root)
        except LookupError as selection_error:
            try:
                latest = read_run_status(database_path, private_root)
            except LookupError:
                print("Active run: none")
                print("Next action: matchvet run")
            else:
                print(f"Active run: {latest.run_id}; {latest.state}; {latest.last_checkpoint}")
                next_action = (
                    "matchvet status"
                    if "Multiple compatible" in str(selection_error)
                    else "matchvet run"
                )
                print(f"Next action: {next_action}")
        else:
            print(
                f"Active run: {incomplete.run_id}; {incomplete.state}; {incomplete.last_checkpoint}"
            )
            print(f"Next action: matchvet resume {incomplete.run_id}")
    elif store.status is InspectionStatus.RECOVERY_REQUIRED:
        print("State: RECOVERY_REQUIRED")
        print("Mode: RESEARCH_ONLY")
        print(f"Store: read-only recovery required; {store.issues[0].code}")
        print("Active run: unavailable")
        print("Next action: matchvet doctor")
    else:
        print("State: BOOTSTRAP")
        print("Mode: RESEARCH_ONLY")
        print("Store: not configured")
        print("Active run: none")
        print("Next action: matchvet doctor")


def main(arguments: Sequence[str] | None = None) -> int:
    apply_runtime_limits()
    parsed = _parser().parse_args(arguments)
    if parsed.command is None:
        _show_bootstrap_state()
        return 0

    if parsed.command == "doctor":
        report = build_report(parsed.store)
        if parsed.as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(render_human_report(report), end="")
        return 0 if report["status"] == "PASS" else 1
    if parsed.command == "run":
        return _run_command(parsed.date, parsed.store, parsed.as_json)
    if parsed.command == "ingest":
        return _ingest_command(
            parsed.season,
            tuple(parsed.history_seasons),
            parsed.store,
            parsed.as_json,
            parsed.resume_run_id,
            parsed.refresh_current,
        )
    if parsed.command == "freeze":
        return _freeze_command(
            parsed.date,
            parsed.season,
            parsed.as_of_utc,
            parsed.store,
            parsed.as_json,
            parsed.resume_run_id,
        )
    if parsed.command == "grade":
        return _grade_command(parsed.input_path, parsed.store, parsed.as_json, parsed.finalize)
    if parsed.command == "status":
        return _status_command(parsed.run_id, parsed.store, parsed.as_json)
    if parsed.command == "report":
        return _report_command(parsed.matchweek, parsed.store, parsed.as_json, parsed.audit)
    if parsed.command == "inspect":
        return _inspect_command(
            parsed.match,
            parsed.matchweek,
            parsed.store,
            parsed.as_json,
        )
    if parsed.command == "history":
        return _history_command(parsed.store, parsed.as_json)
    if parsed.command == "export":
        return _export_command(
            parsed.matchweek,
            parsed.store,
            parsed.destination,
            parsed.include_raw_evidence,
            parsed.as_json,
        )
    if parsed.command == "backup":
        return _backup_command(
            parsed.store,
            parsed.destination,
            parsed.verify,
            parsed.as_json,
        )
    if parsed.command == "restore":
        return _restore_command(parsed.source, parsed.target, parsed.as_json)
    return _resume_command(parsed.run_id, parsed.store, parsed.as_json)


def _export_command(
    matchweek_id: str | None,
    store_path: Path | None,
    destination: Path,
    include_raw_evidence: bool,
    as_json: bool,
) -> int:
    database_path = store_path or default_database_path()
    try:
        result = export_matchweek(
            database_path,
            destination,
            private_root=termux_private_root(),
            matchweek_id=matchweek_id,
            include_raw_evidence=include_raw_evidence,
        )
    except T17Error as error:
        return _t17_error(error, as_json, "export")
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T17-EXPORT-CLI_FAILED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": (
                    f"matchvet export --store {database_path} --destination {destination}"
                ),
            },
            as_json,
        )
    return _print_t17_result(result.to_dict(), as_json, "MatchVet export")


def _backup_command(
    store_path: Path | None,
    destination: Path | None,
    verify_path: Path | None,
    as_json: bool,
) -> int:
    if verify_path is not None and destination is not None:
        return _t17_option_error(
            "MV-T17-BACKUP-OPTIONS_INVALID",
            "Use either --destination or --verify, not both.",
            as_json,
        )
    if verify_path is not None:
        try:
            verification = verify_backup(verify_path)
        except T17Error as error:
            return _t17_error(
                T17Error(
                    error.code,
                    error.message,
                    status=error.status,
                    recovery_command=error.recovery_command,
                    source=verify_path,
                    destination=error.destination or verify_path,
                    manifest_digest=error.manifest_digest,
                ),
                as_json,
                "backup",
            )
        except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
            return _print_error(
                {
                    "status": "REFUSED",
                    "code": "MV-T17-BACKUP-CLI_FAILED",
                    "explanation": str(error),
                    "last_checkpoint": "none",
                    "reuse_state": "NONE",
                    "recovery_command": f"matchvet backup --verify {verify_path}",
                },
                as_json,
            )
        payload: dict[str, object] = {
            "operation": "backup_verify",
            "status": "VERIFIED",
            "source": str(verify_path),
            "destination": str(verification.destination),
            "manifest_digest": verification.manifest_digest,
            "completion_digest": verification.completion_digest,
            "verification": verification.to_dict(),
        }
        return _print_t17_result(payload, as_json, "MatchVet backup verify")
    if destination is None:
        return _t17_option_error(
            "MV-T17-BACKUP-DESTINATION_REQUIRED",
            "Backup creation requires --destination; use --verify BUNDLE to verify a copy.",
            as_json,
        )
    database_path = store_path or default_database_path()
    try:
        result = backup_store(
            database_path,
            destination,
            private_root=termux_private_root(),
        )
    except T17Error as error:
        return _t17_error(error, as_json, "backup")
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T17-BACKUP-CLI_FAILED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": (
                    f"matchvet backup --store {database_path} --destination {destination}"
                ),
            },
            as_json,
        )
    return _print_t17_result(result.to_dict(), as_json, "MatchVet backup")


def _restore_command(source: Path, target: Path, as_json: bool) -> int:
    try:
        result = restore_backup(
            source,
            target,
            private_root=termux_private_root(),
        )
    except T17Error as error:
        return _t17_error(error, as_json, "restore")
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T17-RESTORE-CLI_FAILED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet restore --source {source} --target {target}.new",
            },
            as_json,
        )
    return _print_t17_result(result.to_dict(), as_json, "MatchVet restore")


def _t17_error(error: T17Error, as_json: bool, command: str) -> int:
    payload = error.to_dict()
    payload["last_checkpoint"] = "none"
    payload["reuse_state"] = "BLOCKED" if "INTEGRITY" in error.code else "NONE"
    if payload["recovery_command"] is None:
        payload["recovery_command"] = f"matchvet {command}"
    return _print_error(payload, as_json)


def _t17_option_error(code: str, explanation: str, as_json: bool) -> int:
    return _print_error(
        {
            "status": "REFUSED",
            "code": code,
            "explanation": explanation,
            "last_checkpoint": "none",
            "reuse_state": "NONE",
            "recovery_command": "matchvet doctor",
        },
        as_json,
    )


def _print_t17_result(payload: dict[str, object], as_json: bool, heading: str) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(heading)
    print(f"Status: {payload.get('status', 'VERIFIED')}")
    if payload.get("source") is not None:
        print(f"Source: {payload['source']}")
    if payload.get("destination") is not None:
        print(f"Destination: {payload['destination']}")
    if payload.get("manifest_digest") is not None:
        print(f"Manifest: {payload['manifest_digest']}")
    for label, key in (
        ("Completion", "completion_digest"),
        ("Audit", "audit_digest"),
        ("Report", "report_digest"),
        ("Database", "database_digest"),
        ("Backup", "backup_id"),
    ):
        if payload.get(key) is not None:
            print(f"{label}: {payload[key]}")
    print("Verification: PASS")
    return 0


def _t16_error(error: Exception, database_path: Path, command: str, as_json: bool) -> int:
    if isinstance(error, T16NotFoundError):
        return _print_error(
            {
                "status": "INCOMPLETE",
                "code": "MV-T16-AUDIT_UNAVAILABLE",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet status --store {database_path}",
                "decision_state": "NO DECISION",
            },
            as_json,
        )
    code = (
        "MV-T16-INTEGRITY_FAILED" if isinstance(error, T16IntegrityError) else "MV-T16-READ_FAILED"
    )
    return _print_error(
        {
            "status": "REFUSED",
            "code": code,
            "explanation": str(error),
            "last_checkpoint": "none",
            "reuse_state": "BLOCKED" if isinstance(error, T16IntegrityError) else "NONE",
            "recovery_command": f"matchvet doctor --store {database_path}"
            if isinstance(error, T16IntegrityError)
            else f"matchvet {command} --store {database_path}",
        },
        as_json,
    )


def _report_command(
    matchweek_id: str | None,
    store_path: Path | None,
    as_json: bool,
    audit: bool,
) -> int:
    database_path = store_path or default_database_path()
    try:
        if audit:
            payload = read_audit(
                database_path,
                private_root=termux_private_root(),
                matchweek_id=matchweek_id,
            ).to_dict()
        else:
            payload = read_report(
                database_path,
                private_root=termux_private_root(),
                matchweek_id=matchweek_id,
            )
    except (T16Error, OSError, sqlite3.DatabaseError) as error:
        return _t16_error(error, database_path, "report", as_json)
    if as_json or audit:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        selected_audit = read_audit(
            database_path,
            private_root=termux_private_root(),
            matchweek_id=matchweek_id,
        )
        print(render_markdown_report(selected_audit), end="")
    return 0


def _inspect_command(
    match: str,
    matchweek_id: str | None,
    store_path: Path | None,
    as_json: bool,
) -> int:
    database_path = store_path or default_database_path()
    try:
        payload = inspect_match(
            database_path,
            match,
            private_root=termux_private_root(),
            matchweek_id=matchweek_id,
        )
    except (T16Error, OSError, sqlite3.DatabaseError) as error:
        return _t16_error(error, database_path, "inspect", as_json)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"MatchVet inspect {match}")
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _history_command(store_path: Path | None, as_json: bool) -> int:
    database_path = store_path or default_database_path()
    try:
        payload = read_history(database_path, private_root=termux_private_root())
    except (T16Error, OSError, sqlite3.DatabaseError) as error:
        return _t16_error(error, database_path, "history", as_json)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("MatchVet history")
        if not payload:
            print("No runs or audits")
        for item in payload:
            print(
                f"{item['matchweek_id']} run_id={item.get('run_id') or 'none'} "
                f"state={item['run_state']} audit={item['audit_state']} "
                f"grading={item['grading_state']} mode={item['mode']} "
                f"policy={item['policy_state']}"
            )
    return 0


def _grade_command(input_path: Path, store_path: Path | None, as_json: bool, finalize: bool) -> int:
    from matchvet.t10 import SettlementGradeRecorder, T10Error

    database_path = store_path or default_database_path()
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("T10 grading input must be a JSON object.")
        raw_evidence = raw.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ValueError("T10 grading input must contain a non-empty evidence list.")
        if not all(isinstance(item, Mapping) for item in raw_evidence):
            raise ValueError("Every T10 evidence entry must be a JSON object.")

        def string_map(key: str) -> dict[str, str]:
            selected = raw.get(key, {})
            if not isinstance(selected, Mapping):
                raise ValueError(f"T10 grading input field {key} must be an object.")
            if not all(
                isinstance(name, str) and isinstance(value, str) for name, value in selected.items()
            ):
                raise ValueError(f"T10 grading input field {key} must map strings to strings.")
            return {str(name): str(value) for name, value in selected.items()}

        fixture_id = raw.get("fixture_id")
        if fixture_id is not None and not isinstance(fixture_id, str):
            raise ValueError("T10 grading input field fixture_id must be a string or null.")
        frozen_evidence_digest = raw.get("frozen_evidence_digest")
        if frozen_evidence_digest is not None and not isinstance(frozen_evidence_digest, str):
            raise ValueError(
                "T10 grading input field frozen_evidence_digest must be a string or null."
            )
        matchweek_id = raw.get("matchweek_id", "")
        if not isinstance(matchweek_id, str):
            raise ValueError("T10 grading input field matchweek_id must be a string.")
        withdrawn = raw.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise ValueError("T10 grading input field withdrawn must be boolean.")
        input_finalize = raw.get("finalize", False)
        if not isinstance(input_finalize, bool):
            raise ValueError("T10 grading input field finalize must be boolean.")

        with open_store(database_path, private_root=termux_private_root()) as store:
            if store.status.mode is not StoreMode.READ_WRITE:
                issue = store.status.issues[0]
                return _print_error(
                    {
                        "status": "REFUSED",
                        "code": issue.code,
                        "explanation": issue.message,
                        "last_checkpoint": "none",
                        "reuse_state": "NONE",
                        "recovery_command": f"matchvet doctor --store {database_path}",
                    },
                    as_json,
                )
            grades = SettlementGradeRecorder(store).grade_fixture_and_record(
                tuple(raw_evidence),
                fixture_id=fixture_id,
                finalize=finalize or input_finalize,
                withdrawn=withdrawn,
                matchweek_id=matchweek_id,
                recommendation_ids=string_map("recommendation_ids"),
                prediction_digests=string_map("prediction_digests"),
                frozen_evidence_digest=frozen_evidence_digest,
            )
    except StoreBusyError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T10-COORDINATOR_BUSY",
                "explanation": "Another foreground MatchVet coordinator owns the store.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet grade --input {input_path}",
            },
            as_json,
        )
    except (OSError, T10Error, TypeError, ValueError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T10-GRADING_FAILED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet grade --input {input_path}",
            },
            as_json,
        )
    payload = {
        "catalog_count": len(grades),
        "fixture_id": grades[0].fixture_id if grades else fixture_id,
        "grades": [grade.to_dict() for grade in grades],
        "grading_state_counts": {
            "FINAL": sum(grade.grading_state.value == "FINAL" for grade in grades),
            "PENDING": sum(grade.grading_state.value == "PENDING" for grade in grades),
        },
        "settlement_counts": {
            result: sum(
                grade.settlement_result is not None and grade.settlement_result.value == result
                for grade in grades
            )
            for result in ("WIN", "LOSS", "PUSH", "VOID")
        },
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("MatchVet T10 grading")
        print(f"Fixture: {payload['fixture_id']}")
        print(f"Preferences: {payload['catalog_count']}")
        print(f"States: {payload['grading_state_counts']}")
        print(f"Results: {payload['settlement_counts']}")
    return 0


def _run_command(date_text: str | None, store_path: Path | None, as_json: bool) -> int:
    try:
        matchweek = _matchweek_key(date_text)
    except ValueError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-USAGE-DATE_INVALID",
                "explanation": "DATE must be the Matchweek Friday in YYYY-MM-DD.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet run YYYY-MM-DD",
            },
            as_json,
        )
    database_path = store_path or default_database_path()
    try:
        with open_store(database_path, private_root=termux_private_root()) as store:
            if store.status.mode is not StoreMode.READ_WRITE:
                issue = store.status.issues[0]
                return _print_error(
                    {
                        "status": "REFUSED",
                        "code": issue.code,
                        "explanation": issue.message,
                        "last_checkpoint": "none",
                        "reuse_state": "NONE",
                        "recovery_command": f"matchvet doctor --store {database_path}",
                    },
                    as_json,
                )
            status = RunCoordinator(store).start(
                matchweek=matchweek,
                inputs=build_local_input_contract(matchweek),
                estimate=default_resource_estimate(),
                observation=observe_resources(database_path),
                progress=None if as_json else _print_progress,
            )
    except RunLifecycleError as error:
        return _print_error(asdict(error.error), as_json)
    except StoreBusyError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-RUN-COORDINATOR_BUSY",
                "explanation": "Another foreground MatchVet coordinator owns the store.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet status",
            },
            as_json,
        )
    _print_status(status, as_json, heading="MatchVet run")
    return 0


def _status_command(run_id: str | None, store_path: Path | None, as_json: bool) -> int:
    database_path = store_path or default_database_path()
    try:
        status = read_run_status(database_path, termux_private_root(), run_id)
    except (LookupError, RuntimeError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-RUN-STATUS_UNAVAILABLE",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet doctor --store {database_path}",
            },
            as_json,
        )
    _print_status(status, as_json, heading="MatchVet status")
    return 0


def _resume_command(run_id: str | None, store_path: Path | None, as_json: bool) -> int:
    database_path = store_path or default_database_path()
    try:
        prior = (
            read_run_status(database_path, termux_private_root(), run_id)
            if run_id is not None
            else read_resume_candidate(database_path, termux_private_root())
        )
        with open_store(database_path, private_root=termux_private_root()) as store:
            if store.status.mode is not StoreMode.READ_WRITE:
                issue = store.status.issues[0]
                raise RuntimeError(f"{issue.code}: {issue.message}")
            status = RunCoordinator(store).resume(
                prior.run_id,
                inputs=build_local_input_contract(prior.matchweek),
                estimate=default_resource_estimate(),
                observation=observe_resources(database_path),
                progress=None if as_json else _print_progress,
            )
    except RunLifecycleError as error:
        return _print_error(asdict(error.error), as_json)
    except StoreBusyError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-RESUME-COORDINATOR_BUSY",
                "explanation": "Another foreground MatchVet coordinator owns the store.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet status",
            },
            as_json,
        )
    except (LookupError, RuntimeError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-RESUME-STATUS_UNAVAILABLE",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet doctor --store {database_path}",
            },
            as_json,
        )
    _print_status(status, as_json, heading="MatchVet resume")
    return 0


def _print_status(status: RunStatus, as_json: bool, *, heading: str) -> None:
    if as_json:
        print(json.dumps(asdict(status), indent=2, sort_keys=True))
        return
    estimate = status.resource_preflight["estimate"]
    preflight = estimate if isinstance(estimate, dict) else {}
    lines = [
        heading,
        f"Run: {status.run_id}",
        f"Matchweek: {status.matchweek}",
        f"State: {status.state}",
        f"Phase: {status.phase}",
        f"Attempt: {status.current_attempt}",
        f"Work units: {status.completed_work_units}/{status.total_work_units}",
        f"Last checkpoint: {status.last_checkpoint}",
        f"Checkpoint time: {status.checkpoint_at_utc or 'none'}",
        f"Elapsed: {status.elapsed_seconds}s",
        f"Mode: {status.mode}",
        f"Input digest: {status.input_digest}",
        "Preflight: "
        f"time={preflight.get('duration_seconds', 'UNKNOWN')}s; "
        f"storage={preflight.get('storage_growth_bytes', 'UNKNOWN')}B; "
        f"memory={preflight.get('peak_memory_bytes', 'UNKNOWN')}B; "
        f"CPU={status.resource_preflight['cpu_concurrency']}; "
        f"network={preflight.get('network_bytes', 'UNKNOWN')}B",
        f"Reuse: {status.reuse_state}",
        f"Decision: {status.decision_state}",
    ]
    if status.stale:
        lines.append("Lifecycle warning: stale RUNNING attempt")
    lines.extend(f"Warning: {warning}" for warning in status.warnings)
    if status.error_code is not None:
        lines.extend(
            (
                f"Error: {status.error_code}",
                f"Explanation: {status.error_explanation}",
                f"Recovery: {status.recovery_command}",
            )
        )
    print("\n".join(lines))


def _print_progress(status: RunStatus) -> None:
    estimate = status.resource_preflight["estimate"]
    preflight = estimate if isinstance(estimate, dict) else {}
    print(
        "Progress: "
        f"phase={status.phase}; work={status.completed_work_units}/{status.total_work_units}; "
        f"checkpoint={status.last_checkpoint}; elapsed={status.elapsed_seconds}s; "
        f"mode={status.mode}"
    )
    if status.completed_work_units == 0:
        print(
            "Preflight: "
            f"matchweek={status.matchweek}; input={status.input_digest}; "
            f"time={preflight.get('duration_seconds', 'UNKNOWN')}s; "
            f"storage={preflight.get('storage_growth_bytes', 'UNKNOWN')}B; "
            f"memory={preflight.get('peak_memory_bytes', 'UNKNOWN')}B; "
            f"CPU={status.resource_preflight['cpu_concurrency']}; "
            f"network={preflight.get('network_bytes', 'UNKNOWN')}B"
        )


def _print_error(error: dict[str, object], as_json: bool) -> int:
    if as_json:
        print(json.dumps(error, indent=2, sort_keys=True))
    else:
        lines = [
            str(error["status"]),
            f"Code: {error['code']}",
            f"Explanation: {error['explanation']}",
            f"Last checkpoint: {error['last_checkpoint']}",
            f"Checkpoint time: {error.get('checkpoint_at_utc') or 'none'}",
            f"Reuse: {error['reuse_state']}",
        ]
        if error.get("source") is not None:
            lines.append(f"Source: {error['source']}")
        if error.get("destination") is not None:
            lines.append(f"Destination: {error['destination']}")
        if error.get("manifest_digest") is not None:
            lines.append(f"Manifest: {error['manifest_digest']}")
        if error.get("verification") is not None:
            lines.append(f"Verification: {error['verification']}")
        lines.append(f"Recovery: {error['recovery_command']}")
        print("\n".join(lines))
    return 1


def _matchweek_key(date_text: str | None) -> str:
    if date_text is not None:
        selected = datetime.strptime(date_text, "%Y-%m-%d").date()
        if selected.weekday() != 4:
            raise ValueError("Matchweeks start on Friday")
        return selected.isoformat()
    from matchvet.matchweek import AFRICA_LAGOS

    today = datetime.now(AFRICA_LAGOS).date()
    days_until_friday = (4 - today.weekday()) % 7
    return (today + timedelta(days=days_until_friday)).isoformat()


def _ingest_command(
    season: str,
    historical_seasons: tuple[str, ...],
    store_path: Path | None,
    as_json: bool,
    resume_run_id: str | None,
    refresh_current: bool,
) -> int:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionError,
        IngestionPlan,
        ResumableSourceDownloader,
        T06AcquisitionRunner,
    )

    database_path = store_path or default_database_path()
    try:
        plan = IngestionPlan(
            current_season=season,
            historical_seasons=historical_seasons,
            refresh_current=refresh_current,
        )
        private_root = termux_private_root()
        with open_store(database_path, private_root=private_root) as store:
            if store.status.mode is not StoreMode.READ_WRITE:
                issue = store.status.issues[0]
                return _print_error(
                    {
                        "status": "REFUSED",
                        "code": issue.code,
                        "explanation": issue.message,
                        "last_checkpoint": "none",
                        "reuse_state": "NONE",
                        "recovery_command": f"matchvet doctor --store {database_path}",
                    },
                    as_json,
                )
            downloader = ResumableSourceDownloader(private_root)
            importer = FixtureHistoryImporter(store, private_root=private_root)
            acquirer = FixtureHistoryAcquirer(importer, downloader)
            runner = T06AcquisitionRunner(store, acquirer)
            observation = observe_resources(database_path)
            status = (
                runner.resume(
                    resume_run_id,
                    plan,
                    observation=observation,
                    progress=None if as_json else _print_progress,
                )
                if resume_run_id is not None
                else runner.start(
                    plan,
                    observation=observation,
                    progress=None if as_json else _print_progress,
                )
            )
            report = runner.last_report
    except RunLifecycleError as error:
        return _print_error(asdict(error.error), as_json)
    except StoreBusyError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T06-COORDINATOR_BUSY",
                "explanation": "Another foreground MatchVet coordinator owns the store.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet status",
            },
            as_json,
        )
    except (IngestionError, OSError, RuntimeError, ValueError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T06-INGESTION_FAILED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet doctor --store {database_path}",
            },
            as_json,
        )

    report_json = None
    if report is not None:
        report_json = {
            "bytes_downloaded": report.bytes_downloaded,
            "cache_hits": report.cache_hits,
            "digest": report.digest,
            "fallback_imports": report.fallback_imports,
            "imports": [asdict(item) for item in report.imports],
            "issues": [asdict(item) for item in report.issues],
            "plan_digest": report.plan_digest,
        }
    if as_json:
        print(
            json.dumps(
                {"acquisition": report_json, "run": asdict(status)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_status(status, False, heading="MatchVet T06 ingestion")
        if report is not None:
            print(
                "Acquisition: "
                f"imports={len(report.imports)}; fallback={report.fallback_imports}; "
                f"cache_hits={report.cache_hits}; bytes={report.bytes_downloaded}; "
                f"issues={len(report.issues)}"
            )
    return 0


def _freeze_command(
    date_text: str,
    season: str,
    as_of_utc: str | None,
    store_path: Path | None,
    as_json: bool,
    resume_run_id: str | None,
) -> int:
    from matchvet.matchweek import MatchweekError, MatchweekFreezePlan, MatchweekFreezeRunner

    database_path = store_path or default_database_path()
    try:
        plan = MatchweekFreezePlan(date_text, season=season, as_of_utc=as_of_utc)
        with open_store(database_path, private_root=termux_private_root()) as store:
            if store.status.mode is not StoreMode.READ_WRITE:
                issue = store.status.issues[0]
                return _print_error(
                    {
                        "status": "REFUSED",
                        "code": issue.code,
                        "explanation": issue.message,
                        "last_checkpoint": "none",
                        "reuse_state": "NONE",
                        "recovery_command": f"matchvet doctor --store {database_path}",
                    },
                    as_json,
                )
            runner = MatchweekFreezeRunner(store)
            observation = observe_resources(database_path)
            if resume_run_id is None:
                status = runner.start(
                    plan,
                    observation=observation,
                    progress=None if as_json else _print_progress,
                )
            else:
                status = runner.resume(
                    resume_run_id,
                    plan,
                    observation=observation,
                    progress=None if as_json else _print_progress,
                )
            frozen = runner.last_freeze
            if frozen is None:
                raise MatchweekError(
                    "MV-T05-FREEZE_NOT_PUBLISHED", "T05 completed without a frozen Matchweek."
                )
            summary = _freeze_summary(frozen)
    except MatchweekError as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": error.code,
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet freeze {date_text} --store {database_path}",
            },
            as_json,
        )
    except RunLifecycleError as error:
        return _print_error(asdict(error.error), as_json)
    except StoreBusyError:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T05-COORDINATOR_BUSY",
                "explanation": "Another foreground MatchVet coordinator owns the store.",
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet status",
            },
            as_json,
        )
    except (ValueError, LookupError, RuntimeError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-T05-FREEZE_UNAVAILABLE",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": f"matchvet doctor --store {database_path}",
            },
            as_json,
        )
    if as_json:
        payload = asdict(status)
        payload["freeze"] = summary
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        _print_status(status, False, heading="MatchVet freeze")
        print(
            "Freeze: "
            f"cutoff={summary['cutoff_utc']}; targets={summary['target_matches']}; "
            f"indeterminate={summary['indeterminate_memberships']}; "
            f"manifest={summary['snapshot_manifest_digest']}"
        )
    return 0


def _freeze_summary(frozen: object) -> dict[str, object]:
    from matchvet.matchweek import MatchweekFreeze

    if not isinstance(frozen, MatchweekFreeze):
        raise TypeError("A MatchweekFreeze summary requires a frozen Matchweek.")
    return {
        "cutoff_utc": frozen.cutoff.cutoff_utc,
        "excluded_memberships": len(frozen.excluded_memberships),
        "indeterminate_memberships": len(frozen.indeterminate_memberships),
        "matchweek": frozen.window.friday_local.isoformat(),
        "membership_manifest_digest": frozen.membership_manifest_digest,
        "season": frozen.season,
        "snapshot_manifest_digest": frozen.snapshot_manifest_digest,
        "target_matches": len(frozen.target_matches),
    }

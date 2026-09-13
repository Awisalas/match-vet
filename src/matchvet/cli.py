from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    if parsed.command == "status":
        return _status_command(parsed.run_id, parsed.store, parsed.as_json)
    return _resume_command(parsed.run_id, parsed.store, parsed.as_json)


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
        print(
            "\n".join(
                (
                    str(error["status"]),
                    f"Code: {error['code']}",
                    f"Explanation: {error['explanation']}",
                    f"Last checkpoint: {error['last_checkpoint']}",
                    f"Checkpoint time: {error.get('checkpoint_at_utc') or 'none'}",
                    f"Reuse: {error['reuse_state']}",
                    f"Recovery: {error['recovery_command']}",
                )
            )
        )
    return 1


def _matchweek_key(date_text: str | None) -> str:
    if date_text is not None:
        selected = datetime.strptime(date_text, "%Y-%m-%d").date()
        if selected.weekday() != 4:
            raise ValueError("Matchweeks start on Friday")
        return selected.isoformat()
    today = datetime.now(ZoneInfo("Africa/Lagos")).date()
    days_until_friday = (4 - today.weekday()) % 7
    return (today + timedelta(days=days_until_friday)).isoformat()

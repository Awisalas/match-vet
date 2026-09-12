from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from matchvet.doctor import apply_runtime_limits, build_report, render_human_report
from matchvet.store import (
    InspectionStatus,
    default_database_path,
    inspect_store,
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
    return parser


def _show_bootstrap_state() -> None:
    store = inspect_store(default_database_path(), private_root=termux_private_root())
    print("MatchVet")
    if store.status is InspectionStatus.HEALTHY:
        print("State: READY")
        print("Mode: RESEARCH_ONLY")
        print(f"Store: healthy; schema {store.schema_version}")
    elif store.status is InspectionStatus.RECOVERY_REQUIRED:
        print("State: RECOVERY_REQUIRED")
        print("Mode: RESEARCH_ONLY")
        print(f"Store: read-only recovery required; {store.issues[0].code}")
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

    report = build_report(parsed.store)
    if parsed.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_human_report(report), end="")
    return 0 if report["status"] == "PASS" else 1

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from matchvet.doctor import apply_runtime_limits, build_report, render_human_report


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
    return parser


def _show_bootstrap_state() -> None:
    print("MatchVet")
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

    report = build_report()
    if parsed.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_human_report(report), end="")
    return 0 if report["status"] == "PASS" else 1

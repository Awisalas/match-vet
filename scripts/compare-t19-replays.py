#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare-t19-replays.py FIRST SECOND")
    first_path, second_path = map(Path, sys.argv[1:])
    first = json.loads(first_path.read_text(encoding="utf-8"))["replay"]
    second = json.loads(second_path.read_text(encoding="utf-8"))["replay"]
    fields = (
        "replay_digest",
        "report_digest",
        "audit_digest",
        "restored_audit_digest",
        "export_digest",
        "evaluation_digest",
    )
    mismatches = [field for field in fields if first.get(field) != second.get(field)]
    for field in ("grade_identity_digest", "restored_grade_identity_digest"):
        if first.get("details", {}).get(field) != second.get("details", {}).get(field):
            mismatches.append(field)
    if mismatches:
        print("deterministic replay mismatch: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    for field in fields:
        print(f"{field}={first[field]}")
    print("backup digests are per-run integrity identities, not cross-run semantic identities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

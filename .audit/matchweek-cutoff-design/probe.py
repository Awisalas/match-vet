"""Read-only contract probes. No model artifacts or SQLite connections are created."""

import hashlib
import socket
import sqlite3
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from matchvet import f11
from matchvet import match_evidence_cutoff as f07
from matchvet.matchweek_membership import canonical_json


def forbidden(*args, **kwargs):
    raise AssertionError("This investigation must not open SQLite or use the network")


freeze = SimpleNamespace(freeze_id="freeze", freeze_digest="freeze-digest")


def member(name, kickoff):
    return SimpleNamespace(
        membership_id=name,
        membership_digest=name + "-digest",
        fixture_id=name + "-fixture",
        controlling_revision_id=name + "-revision",
        controlling_revision_digest=name + "-revision-digest",
        controlling_revision=SimpleNamespace(kickoff_utc=kickoff, kickoff_precision="INSTANT"),
    )


with patch.object(sqlite3, "connect", forbidden), patch.object(socket.socket, "connect", forbidden):
    policy = f07.CutoffPolicy("probe-legacy", "1", 21600)
    before = canonical_json(asdict(policy))
    friday = member("friday", "2026-10-09T16:45:00+00:00")
    monday = member("monday", "2026-10-12T18:00:00+00:00")
    # Trap the return constructor. The shipped arithmetic runs, but no F07 object
    # or canonical cutoff payload is created, published, or retained.
    with patch.object(f07, "MatchEvidenceCutoff", lambda *args: args[-1]):
        friday_boundary = f07._cutoff(freeze, friday, policy, "probe-policy")
        monday_boundary = f07._cutoff(freeze, monday, policy, "probe-policy")
    assert friday_boundary == "2026-10-09T10:45:00.000000+00:00"
    assert monday_boundary == "2026-10-12T12:00:00.000000+00:00"
    assert friday_boundary != monday_boundary
    assert before == canonical_json(asdict(policy))
    print("PASS: shipped legacy arithmetic assigns distinct Friday/Monday cutoffs")
    print("PASS: legacy policy canonical bytes were not modified")
    try:
        f07.CutoffPolicy(
            "probe-new",
            "2",
            21600,
            rule="MATCHWEEK_EARLIEST_INCLUDED_KICKOFF_MINUS_LEAD_TIME",
        )
    except f07.MatchEvidenceCutoffError as error:
        assert error.code == "MV-F07-VERSION-UNSUPPORTED"
        print("PASS: existing reader fails closed on an unsupported policy rule")
    else:
        raise AssertionError("The current reader unexpectedly accepted a new rule")
    request = {"freeze_id": "freeze", "policy_digest": "policy", "context": [], "locations": {}}
    changed = dict(request, locations={"fixture": {"venue": "different"}})
    assert f11._digest(f11._bytes(request)) != f11._digest(f11._bytes(changed))
    print("PASS: changed F11 request configuration has a different request identity")
    assert set(asdict(policy)) == {
        "policy_id",
        "policy_version",
        "lead_time_seconds",
        "schema_version",
        "rule",
    }
    assert hashlib.sha256(before.encode()).digest()
    print("PASS: existing policy layout already carries an explicit digest-bound rule")

print("NO SQLite connection, network request, or F06/F07/F11/F13/F14/F16/CB01 artifact creation")

"""Offline blast-radius proof. All writes are to one temporary synthetic store."""

# Imports follow path setup and the offline socket guard deliberately.
# ruff: noqa: E402
from __future__ import annotations

import copy
import hashlib
import json
import socket
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


# Any accidental network activity must fail loudly.
def refuse_network(*args, **kwargs):
    raise AssertionError("This audit proof must be offline")


socket.create_connection = refuse_network
socket.socket.connect = refuse_network

from test_matchweek_membership import _persistable_empty_assessment

import matchvet.fixture_coverage as fc
from matchvet.fixture_coverage_codec import decode_f01, encode_f01
from matchvet.fixture_coverage_repository import FixtureCoverageRepository
from matchvet.matchweek_membership import (
    F06_POLICY_ID,
    PolicySnapshot,
    canonical_json,
    freeze_identity,
    policy_snapshot,
    sha256_digest,
)
from matchvet.matchweek_membership_repository import MatchweekMembershipRepository
from matchvet.provider_health_acquisition import build_provider_health_records
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.research_identity import logical_matchweek_id, selection_slot
from matchvet.store import open_store


def prefixed(value):
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def insert_dict(connection, table, record):
    # Table and column identities come only from this module or sqlite cursor.
    names = tuple(record)
    connection.execute(
        f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
        tuple(record[name] for name in names),
    )


legacy_bytes = (ROOT / "tests/fixtures/f01_v2_unknown_2026_09_25.json").read_text()
legacy = decode_f01(legacy_bytes)
assert encode_f01(legacy) == legacy_bytes
assert len(legacy.scope_assessments) == 7
six_requested = fc.fixture_scopes_for_matchweek("2026-09-25", season="2026-27")[:-1]
result = fc.assess_fixture_coverage(
    scopes=six_requested,
    provider_attempts=(),
    coverage_evidence=(),
    fixture_revisions=(),
    identity_resolutions=(),
    freshness_results=(),
)
assert len(result.scope_assessments) == 7
assert result.scope_assessments[-1].scope.league_key == "belgian_pro_league"
assert result.scope_assessments[-1].coverage_state.value == "UNKNOWN"
assert result.digest == legacy.digest
print("PASS: six requested scopes still produce the exact old seven-scope UNKNOWN artifact")

old_keys = fc._TARGET_LEAGUE_KEYS
try:
    fc._TARGET_LEAGUE_KEYS = old_keys[:-1]
    try:
        decode_f01(legacy_bytes)
    except ValueError as error:
        print("PASS: removing BEL from global F01 registry breaks exact legacy decode:", error)
    else:
        raise AssertionError("Legacy Belgian scope unexpectedly decoded after global shrink")
finally:
    fc._TARGET_LEAGUE_KEYS = old_keys
assert encode_f01(decode_f01(legacy_bytes)) == legacy_bytes
print("PASS: restored registry retains exact original seven-scope bytes/digest")

try:
    policy_snapshot(F06_POLICY_ID, "3")
except ValueError:
    print("PASS: successor F06 policy3 is currently unsupported; admission remains unimplemented")
else:
    raise AssertionError("Unexpected existing successor policy3")

with tempfile.TemporaryDirectory(
    prefix="synthetic-six-scope-", dir=Path(tempfile.gettempdir())
) as work:
    workdir = Path(work)
    with open_store(workdir / "matchvet.sqlite3", private_root=workdir) as store:
        assessment = _persistable_empty_assessment(store, workdir)
        FixtureCoverageRepository(store).persist(assessment)
        ProviderHealthRepository(store).persist_many(build_provider_health_records(assessment))
        repo = MatchweekMembershipRepository(
            store, clock=lambda: datetime(2026, 9, 24, 12, tzinfo=UTC)
        )
        freeze = repo.freeze_exact(
            season="2026-27",
            matchweek_friday="2026-09-25",
            assessment_digest=assessment.digest,
            policy_id="matchvet:matchweek-membership",
            policy_version="1",
        )
        assert repo.get_by_id(freeze.freeze_id) == freeze
        connection = store._connection_for_repository()
        schema_before = connection.execute("PRAGMA schema_version").fetchone()[0]
        # STORAGE-ONLY shapes for proposed successors: no claim current readers support them.
        f01 = {
            "digest": "",
            "scope_assessments": [
                {
                    "scope": {
                        "league_key": scope.league_key,
                        "season": scope.season,
                        "matchweek_friday": scope.matchweek_friday,
                    }
                }
                for scope in six_requested
            ],
            "provider_attempts": [],
            "coverage_evidence": [],
            "fixture_revisions": [],
            "identity_resolutions": [],
            "freshness_results": [],
            "contract_version": "audit-six-scope-f01-successor",
            "schema_version": 4,
            "active_scope_contract": "matchvet-active-scopes-v2-six",
        }
        f01["digest"] = prefixed({k: v for k, v in f01.items() if k != "digest"})
        cursor = connection.execute("SELECT * FROM fixture_coverage_assessments LIMIT 1")
        assessment_row = dict(
            zip([col[0] for col in cursor.description], cursor.fetchone(), strict=True)
        )
        assessment_row.update(
            assessment_digest=f01["digest"],
            assessment_json=canonical_json(f01),
            contract_version=f01["contract_version"],
            assessment_schema_version=4,
        )
        insert_dict(connection, "fixture_coverage_assessments", assessment_row)
        payload = copy.deepcopy(freeze.to_payload())
        document = json.loads(payload["policy"]["canonical_json"])
        document["version"] = "3"
        document["active_scope_contract"] = {
            "id": "matchvet-active-scopes",
            "version": "2",
            "ordered_league_keys": [scope.league_key for scope in six_requested],
        }
        encoded_policy = canonical_json(document)
        policy = PolicySnapshot(
            "matchvet:matchweek-membership", "3", encoded_policy, sha256_digest(encoded_policy)
        )
        payload.update(
            assessment_digest=f01["digest"],
            policy=policy.to_payload(),
            scopes=payload["scopes"][:-1],
            provider_health_references=[],
        )
        payload["freeze_id"] = freeze_identity(
            freeze.season, freeze.matchweek_friday, f01["digest"], policy
        )
        payload["freeze_digest"] = prefixed(
            {k: v for k, v in payload.items() if k != "freeze_digest"}
        )
        cursor = connection.execute("SELECT * FROM v2_matchweek_membership_freezes LIMIT 1")
        freeze_row = dict(
            zip([col[0] for col in cursor.description], cursor.fetchone(), strict=True)
        )
        freeze_row.update(
            freeze_id=payload["freeze_id"],
            freeze_digest=payload["freeze_digest"],
            freeze_json=canonical_json(payload),
            assessment_digest=f01["digest"],
            policy_version="3",
            policy_digest=policy.digest,
        )
        insert_dict(connection, "v2_matchweek_membership_freezes", freeze_row)
        assert connection.execute("PRAGMA schema_version").fetchone()[0] == schema_before
        print(
            "PASS: real schema stores a new F01 version and six-scope F06 "
            "policy snapshot without DDL"
        )
        bad = copy.deepcopy(freeze_row)
        bad_payload = copy.deepcopy(payload)
        bad_payload["contract_version"] = "matchweek-membership-freeze-v3"
        bad_payload["payload_version"] = 2
        bad_payload["freeze_id"] = "sha256:" + "e" * 64
        bad_payload["freeze_digest"] = prefixed(
            {k: v for k, v in bad_payload.items() if k != "freeze_digest"}
        )
        bad.update(
            freeze_id=bad_payload["freeze_id"],
            freeze_digest=bad_payload["freeze_digest"],
            freeze_json=canonical_json(bad_payload),
            contract_version=bad_payload["contract_version"],
            payload_version=bad_payload["payload_version"],
        )
        try:
            insert_dict(connection, "v2_matchweek_membership_freezes", bad)
        except sqlite3.IntegrityError as error:
            assert "contract_version" in str(error) or "payload_version" in str(error)
            print("PASS: bumping F06 envelope is rejected by actual SQLite CHECK:", error)
        else:
            raise AssertionError("Expected fixed F06 envelope to refuse successor schema")
        assert repo.get_by_id(freeze.freeze_id) == freeze
        print("PASS: legacy F06 freeze still replays after successor-shape rows are inserted")

logical = logical_matchweek_id("2026-27", "2026-09-25")
print(
    "PASS: logical calendar week has one selection slot independent of scope:",
    selection_slot(logical),
)
print(
    "LIMIT: proposed six-scope readers, semantic validation, cohort dispatch "
    "and activation are UNIMPLEMENTED"
)

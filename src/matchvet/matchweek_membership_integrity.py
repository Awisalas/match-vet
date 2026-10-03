"""Assessment-specific integrity facts for F06 membership policy 2."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from itertools import combinations
from typing import cast

from matchvet.fixture_coverage import FixtureRevisionReference
from matchvet.ingestion import (
    _parse_date,
    _source_timezone,
    canonical_key,
    deterministic_identifier,
    league_by_key,
)
from matchvet.matchweek_membership import (
    AssertionIntegritySnapshot,
    ConflictSnapshot,
    FixtureRevisionSnapshot,
    RevisionIntegritySnapshot,
    canonical_json,
    membership_policy_document,
)
from matchvet.operator_fixture_attestation import _candidate_date, _candidate_instant
from matchvet.store import Store


class MembershipReferenceError(ValueError):
    """Exact immutable membership evidence is incomplete or internally inconsistent."""


def status_class(value: str) -> str:
    """Use the policy's membership classes, preserving unfamiliar statuses as distinct facts."""
    normalized = value.strip().upper()
    mapping = cast(dict[str, list[str]], membership_policy_document("2")["status_mapping"])
    for category, values in mapping.items():
        if normalized in values:
            return category.upper()
    return normalized


def semantic_values_conflict(predicate: str, values: Iterable[str], league_key: str) -> bool:
    """Apply LF07's typed local-date compatibility and the membership status classes."""
    distinct = set(values)
    if predicate != "kickoff":
        return len(distinct) > 1
    instants: set[datetime] = set()
    dates = set()
    for encoded in distinct:
        fact = json.loads(encoded)
        if not isinstance(fact, dict):
            raise MembershipReferenceError("A semantic kickoff must carry its precision.")
        if fact.get("precision") == "INSTANT":
            instant = _candidate_instant(fact.get("value"))
            if instant is None:
                raise MembershipReferenceError("An observed kickoff instant is malformed.")
            instants.add(instant)
        elif fact.get("precision") == "DATE":
            local_date = _candidate_date(fact.get("value"))
            if local_date is None:
                raise MembershipReferenceError("An observed kickoff date is malformed.")
            dates.add(local_date)
        else:
            raise MembershipReferenceError("An observed kickoff has unsupported precision.")
    if len(instants) > 1 or len(dates) > 1:
        return True
    timezone = league_by_key(league_key).timezone
    return any(
        instant.astimezone(_source_timezone(timezone, local_date)).date() != local_date
        for instant in instants
        for local_date in dates
    )


def _revision_kickoff(snapshot: FixtureRevisionSnapshot) -> str | None:
    if snapshot.kickoff_state != "OBSERVED":
        return None
    if snapshot.kickoff_precision == "DATE":
        local_date = _parse_date(snapshot.kickoff_local_text or "")
        if local_date is not None:
            return canonical_json({"precision": "DATE", "value": local_date.isoformat()})
    elif snapshot.kickoff_precision == "INSTANT":
        instant = _candidate_instant(snapshot.kickoff_utc)
        if instant is not None:
            return canonical_json({"precision": "INSTANT", "value": instant.isoformat()})
    return None


def has_revision_conflict(snapshots: tuple[FixtureRevisionSnapshot, ...]) -> bool:
    best_rank = max(item.authority_rank for item in snapshots)
    best_time = max(
        item.latest_support_retrieved_at_utc
        for item in snapshots
        if item.authority_rank == best_rank
    )
    tier = [
        item
        for item in snapshots
        if (item.authority_rank, item.latest_support_retrieved_at_utc) == (best_rank, best_time)
    ]
    for left, right in combinations(tier, 2):
        if left.integrity is None or right.integrity is None:
            raise MembershipReferenceError("Semantic revision integrity is missing.")
        if (left.integrity.home_team_id, left.integrity.away_team_id) != (
            right.integrity.home_team_id,
            right.integrity.away_team_id,
        ) or status_class(left.fixture_status) != status_class(right.fixture_status):
            return True
        if status_class(left.fixture_status) == "SCHEDULED":
            values = (_revision_kickoff(left), _revision_kickoff(right))
            if None in values:
                if values[0] != values[1]:
                    return True
            elif semantic_values_conflict(
                "kickoff", cast(tuple[str, str], values), left.scope_id.split(":")[0]
            ):
                return True
    return False


def controller_key(snapshot: FixtureRevisionSnapshot) -> tuple[int, datetime, bool, str, str]:
    return (
        snapshot.authority_rank,
        datetime.fromisoformat(snapshot.latest_support_retrieved_at_utc),
        snapshot.integrity is not None and snapshot.kickoff_precision == "INSTANT",
        snapshot.revision_id,
        snapshot.revision_digest,
    )


def load_revision_integrity(
    store: Store, reference: FixtureRevisionReference
) -> RevisionIntegritySnapshot:
    """Freeze exact assertion bytes and canonical identities from persisted mapping evidence."""
    connection = store._connection_for_repository()
    fixture = connection.execute(
        """SELECT f.home_team_id, f.away_team_id, f.league_id, l.league_key,
                  s.season_label, r.source_round, r.kickoff_precision, r.kickoff_utc,
                  r.kickoff_state, r.kickoff_local_text, r.fixture_status
           FROM fixture_revisions r JOIN fixtures f ON f.fixture_id = r.fixture_id
           JOIN target_leagues l ON l.league_id = f.league_id
           JOIN competition_seasons s ON s.season_id = f.season_id
           WHERE r.revision_id = ? AND f.fixture_id = ?""",
        (reference.revision_id, reference.fixture_id),
    ).fetchone()
    if fixture is None or reference.fixture_id != deterministic_identifier(
        "fixture", f"{fixture[3]}:{fixture[4]}:{fixture[0]}:{fixture[1]}"
    ):
        raise MembershipReferenceError(
            f"Revision {reference.revision_id} has invalid canonical teams."
        )
    payload = dict(
        zip(
            (
                "source_round",
                "kickoff_precision",
                "kickoff_utc",
                "kickoff_state",
                "kickoff_local_text",
                "fixture_status",
            ),
            fixture[5:],
            strict=True,
        )
    )
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if reference.revision_digest != digest or reference.revision_id != deterministic_identifier(
        "fixture_revision", f"{reference.fixture_id}:{digest}"
    ):
        raise MembershipReferenceError(
            f"Revision {reference.revision_id} has invalid content digest."
        )
    assertions: list[AssertionIntegritySnapshot] = []
    predicates: dict[tuple[str, str], set[str]] = defaultdict(set)
    for assertion_id in sorted(reference.source_assertion_ids):
        cursor = connection.execute(
            "SELECT * FROM source_assertions WHERE assertion_id = ?", (assertion_id,)
        )
        row = cursor.fetchone()
        if row is None:
            raise MembershipReferenceError(f"Missing assertion {assertion_id}.")
        fact = dict(zip((column[0] for column in cursor.description), row, strict=True))
        if (fact["subject_kind"], fact["subject_key"]) != ("FIXTURE", reference.fixture_id):
            raise MembershipReferenceError(f"Assertion {assertion_id} has an invalid subject.")
        predicates[(str(fact["capture_id"]), str(fact["source_row_key"]))].add(
            str(fact["predicate"])
        )
        semantic_value = fact["normalized_value_json"]
        mapping_id = mapping_digest = None
        if fact["predicate"] in ("home_team", "away_team"):
            if fact["evidence_state"] != "OBSERVED" or not isinstance(semantic_value, str):
                raise MembershipReferenceError(f"Team assertion {assertion_id} is not observed.")
            name = json.loads(semantic_value)
            if not isinstance(name, str):
                raise MembershipReferenceError(
                    f"Team assertion {assertion_id} has an invalid name."
                )
            mappings = connection.execute(
                """SELECT m.* FROM source_team_mappings m JOIN source_captures c
                     ON c.source_id = m.source_id
                   WHERE c.capture_id = ? AND m.league_id = ? AND m.source_team_key = ?""",
                (fact["capture_id"], fixture[2], canonical_key(name)),
            ).fetchall()
            expected = str(fixture[0 if fact["predicate"] == "home_team" else 1])
            if len(mappings) != 1 or mappings[0][5] != "CONFIRMED" or mappings[0][6] != expected:
                raise MembershipReferenceError(
                    f"Team assertion {assertion_id} disagrees with canonical fixture identity."
                )
            mapping_id = str(mappings[0][0])
            mapping_digest = hashlib.sha256(canonical_json(tuple(mappings[0])).encode()).hexdigest()
            semantic_value = canonical_json(expected)
        elif fact["predicate"] in ("status", "fixture_status"):
            if fact["evidence_state"] != "OBSERVED" or not isinstance(semantic_value, str):
                raise MembershipReferenceError(f"Status assertion {assertion_id} is not observed.")
            value = json.loads(semantic_value)
            if not isinstance(value, str):
                raise MembershipReferenceError(f"Status assertion {assertion_id} is malformed.")
            semantic_value = canonical_json(status_class(value))
            if status_class(value) != status_class(str(fixture[10])):
                raise MembershipReferenceError(
                    f"Status assertion {assertion_id} disagrees with revision."
                )
        elif fact["predicate"] == "kickoff" and semantic_value is not None:
            value = json.loads(semantic_value)
            if not isinstance(value, str):
                raise MembershipReferenceError(f"Kickoff assertion {assertion_id} is malformed.")
            if fixture[6] == "DATE":
                local_date = _candidate_date(value)
                if local_date is None:
                    raise MembershipReferenceError(f"DATE assertion {assertion_id} is malformed.")
                semantic_value = canonical_json(
                    {"precision": "DATE", "value": local_date.isoformat()}
                )
                if local_date != _parse_date(str(fixture[9])) or fixture[7] is not None:
                    raise MembershipReferenceError(
                        f"DATE assertion {assertion_id} disagrees with revision."
                    )
            else:
                instant = _candidate_instant(value)
                if instant is None:
                    raise MembershipReferenceError(
                        f"INSTANT assertion {assertion_id} is malformed."
                    )
                semantic_value = canonical_json(
                    {"precision": "INSTANT", "value": instant.isoformat()}
                )
                if instant != _candidate_instant(fixture[7]):
                    raise MembershipReferenceError(
                        f"INSTANT assertion {assertion_id} disagrees with revision."
                    )
            if fixture[8] != fact["evidence_state"]:
                raise MembershipReferenceError(
                    f"Kickoff assertion {assertion_id} has inconsistent state."
                )
        elif fact["predicate"] == "kickoff" and fixture[8] == "OBSERVED":
            raise MembershipReferenceError(
                f"Observed revision has unknown kickoff assertion {assertion_id}."
            )
        assertions.append(
            AssertionIntegritySnapshot(
                assertion_id=assertion_id,
                content_digest=hashlib.sha256(canonical_json(fact).encode()).hexdigest(),
                semantic_value=semantic_value,
                mapping_id=mapping_id,
                mapping_digest=mapping_digest,
            )
        )
    critical = {"home_team", "away_team", "kickoff", "status", "fixture_status"}
    membership_rows = {key: values for key, values in predicates.items() if values & critical}
    if not membership_rows or any(
        not {"home_team", "away_team", "kickoff"}.issubset(values)
        for values in membership_rows.values()
    ):
        raise MembershipReferenceError("Selected source rows omit membership assertions.")
    if {key[0] for key in membership_rows} != set(reference.source_capture_ids):
        raise MembershipReferenceError("Selected captures lack complete membership source rows.")
    for (capture_id, row_key), row_predicates in membership_rows.items():
        required = connection.execute(
            "SELECT assertion_id FROM source_assertions "
            "WHERE capture_id=? AND source_row_key=? AND subject_key=? "
            "AND predicate IN ('home_team','away_team','kickoff','status','fixture_status')",
            (capture_id, row_key, reference.fixture_id),
        ).fetchall()
        if not {str(item[0]) for item in required}.issubset(reference.source_assertion_ids):
            raise MembershipReferenceError(
                "Selected source row omits a membership-critical assertion."
            )
        if row_predicates & {"status", "fixture_status"}:
            continue
        goals = connection.execute(
            "SELECT predicate, evidence_state FROM source_assertions "
            "WHERE capture_id=? AND source_row_key=? AND subject_key=? "
            "AND predicate IN ('full_time_home_goals', 'full_time_away_goals')",
            (capture_id, row_key, reference.fixture_id),
        ).fetchall()
        completed = {str(item[0]) for item in goals if item[1] == "OBSERVED"} == {
            "full_time_home_goals",
            "full_time_away_goals",
        }
        inferred = (
            "COMPLETED" if completed else "SCHEDULED" if fixture[8] == "OBSERVED" else "UNKNOWN"
        )
        if status_class(str(fixture[10])) != status_class(inferred):
            raise MembershipReferenceError(
                "Revision status disagrees with inferred source row status."
            )
    return RevisionIntegritySnapshot(
        str(fixture[0]), str(fixture[1]), fixture[5], tuple(assertions)
    )


def _value_digest(values: Iterable[str]) -> str:
    return hashlib.sha256(canonical_json(sorted(set(values))).encode()).hexdigest()


def _selected_values(
    store: Store, fixture_id: str, assertion_ids: tuple[str, ...]
) -> dict[str, dict[str, str]]:
    rows = (
        store._connection_for_repository()
        .execute(
            """
        SELECT assertion_id, predicate, normalized_value_json
        FROM source_assertions
        WHERE subject_kind = 'FIXTURE' AND subject_key = ?
          AND evidence_state = 'OBSERVED' AND normalized_value_json IS NOT NULL
          AND assertion_id IN (SELECT value FROM json_each(?))
        ORDER BY predicate, assertion_id
        """,
            (fixture_id, canonical_json(assertion_ids)),
        )
        .fetchall()
    )
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for assertion_id, predicate, value in rows:
        result[str(predicate)][str(assertion_id)] = str(value)
    return result


def _history_members(
    store: Store, fixture_id: str, predicate: str, conflict_id: str, value_digest: str
) -> dict[str, str]:
    rows = (
        store._connection_for_repository()
        .execute(
            """
        SELECT a.assertion_id, a.subject_kind, a.subject_key, a.predicate,
               a.evidence_state, a.normalized_value_json
        FROM conflict_assertions AS link
        JOIN source_assertions AS a ON a.assertion_id = link.assertion_id
        WHERE link.conflict_id = ? ORDER BY a.assertion_id
        """,
            (conflict_id,),
        )
        .fetchall()
    )
    members: dict[str, str] = {}
    for assertion_id, kind, subject, actual_predicate, state, value in rows:
        if (kind, subject, actual_predicate, state) != (
            "FIXTURE",
            fixture_id,
            predicate,
            "OBSERVED",
        ) or value is None:
            raise MembershipReferenceError(f"Conflict {conflict_id} has an invalid member context.")
        members[str(assertion_id)] = str(value)
    if len(set(members.values())) < 2 or _value_digest(members.values()) != value_digest:
        raise MembershipReferenceError(f"Conflict {conflict_id} has inconsistent history values.")
    return members


def project_conflicts(
    store: Store,
    fixture_id: str,
    assertion_ids: tuple[str, ...],
    semantic_values: dict[str, str | None] | None = None,
) -> tuple[ConflictSnapshot, ...]:
    """Project all exact assertion members from a validated covering history record."""
    connection = store._connection_for_repository()
    projections: list[ConflictSnapshot] = []
    for predicate, exact in sorted(
        material_conflict_values(store, fixture_id, assertion_ids, semantic_values).items()
    ):
        values = tuple(sorted(set(exact.values())))
        candidates = connection.execute(
            """
            SELECT conflict_id, value_digest FROM conflict_sets
            WHERE subject_kind = 'FIXTURE' AND subject_key = ? AND predicate = ?
              AND status = 'UNRESOLVED' ORDER BY value_digest, conflict_id
            """,
            (fixture_id, predicate),
        ).fetchall()
        covering: list[tuple[int, str, str]] = []
        for conflict_id, history_digest in candidates:
            members = _history_members(
                store, fixture_id, predicate, str(conflict_id), str(history_digest)
            )
            if set(exact).issubset(members):
                covering.append((len(set(members.values())), str(history_digest), str(conflict_id)))
        if not covering:
            raise MembershipReferenceError(
                f"Fixture {fixture_id} predicate {predicate} "
                "lacks complete selected conflict members."
            )
        _, history_digest, conflict_id = min(covering)
        projections.append(
            ConflictSnapshot(
                conflict_id=conflict_id,
                predicate=predicate,
                value_digest=_value_digest(values),
                assertion_ids=tuple(sorted(exact)),
                values=values,
                history_value_digest=history_digest,
            )
        )
    return tuple(projections)


def material_conflict_values(
    store: Store,
    fixture_id: str,
    assertion_ids: tuple[str, ...],
    semantic_values: dict[str, str | None] | None,
) -> dict[str, dict[str, str]]:
    """Derive complete material predicates independently of conflict snapshot presence."""
    league = (
        store._connection_for_repository()
        .execute(
            "SELECT l.league_key FROM fixtures f JOIN target_leagues l ON l.league_id=f.league_id "
            "WHERE f.fixture_id=?",
            (fixture_id,),
        )
        .fetchone()
    )
    if league is None:
        raise MembershipReferenceError("Conflict projection has no canonical fixture.")
    result = {}
    for predicate, exact in _selected_values(store, fixture_id, assertion_ids).items():
        if len(set(exact.values())) < 2:
            continue
        if semantic_values is not None:
            compared = [semantic_values[key] for key in exact]
            if any(value is None for value in compared):
                raise MembershipReferenceError("Observed conflict assertion has no semantic value.")
            if not semantic_values_conflict(predicate, cast(list[str], compared), str(league[0])):
                continue
        result[predicate] = exact
    return result


def validate_conflict_projection(
    store: Store,
    fixture_id: str,
    projection: ConflictSnapshot,
    selected_assertion_ids: tuple[str, ...],
) -> dict[str, str]:
    """Validate the recorded basis and every selected member, without choosing later history."""
    row = (
        store._connection_for_repository()
        .execute(
            "SELECT subject_kind, subject_key, predicate, value_digest, status "
            "FROM conflict_sets WHERE conflict_id = ?",
            (projection.conflict_id,),
        )
        .fetchone()
    )
    if row is None or tuple(row) != (
        "FIXTURE",
        fixture_id,
        projection.predicate,
        projection.history_value_digest,
        "UNRESOLVED",
    ):
        raise MembershipReferenceError(
            f"Conflict {projection.conflict_id} changed its history basis."
        )
    assert projection.history_value_digest is not None
    members = _history_members(
        store,
        fixture_id,
        projection.predicate,
        projection.conflict_id,
        projection.history_value_digest,
    )
    exact = _selected_values(store, fixture_id, selected_assertion_ids).get(
        projection.predicate, {}
    )
    if tuple(sorted(exact)) != projection.assertion_ids or not set(exact).issubset(members):
        raise MembershipReferenceError(
            f"Conflict {projection.conflict_id} omits selected assertions."
        )
    if (
        tuple(sorted(set(exact.values()))) != projection.values
        or _value_digest(exact.values()) != projection.value_digest
        or any(members[key] != value for key, value in exact.items())
    ):
        raise MembershipReferenceError(
            f"Conflict {projection.conflict_id} changed selected values."
        )
    return exact

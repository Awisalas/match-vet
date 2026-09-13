from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from matchvet.ingestion import FixtureHistoryImporter
    from matchvet.matchweek import PostCutoffValidityReview
    from matchvet.store import Store


def _schedule_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    lines = ["Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC"]
    lines.extend(
        f"E0,{date_text},{time_text},{home},{away},,,,,,,"
        for date_text, time_text, home, away in rows
    )
    return ("\n".join(lines) + "\n").encode()


def _import_schedule(
    tmp_path: Path, rows: list[tuple[str, str, str, str]], retrieved: str
) -> tuple[Store, FixtureHistoryImporter]:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.store import open_store

    content = _schedule_csv(rows)
    store = open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path)
    importer = FixtureHistoryImporter(store, private_root=tmp_path)
    importer.import_dataset(
        FootballDataCSVParser().parse(
            content,
            league=league_by_key("premier_league"),
            season="2026-27",
        ),
        content,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc=retrieved,
            observed_terms="restricted private test capture",
        ),
    )
    return store, importer


def test_matchweek_window_is_friday_to_tuesday_in_africa_lagos() -> None:
    from matchvet.matchweek import MatchweekWindow

    window = MatchweekWindow.for_friday("2026-09-18")

    assert window.friday_local.isoformat() == "2026-09-18"
    assert window.start_local.isoformat() == "2026-09-18T00:00:00+01:00"
    assert window.end_local.isoformat() == "2026-09-22T00:00:00+01:00"
    assert window.start_utc == "2026-09-17T23:00:00.000000+00:00"
    assert window.end_utc == "2026-09-21T23:00:00.000000+00:00"
    assert window.contains(datetime(2026, 9, 17, 23, tzinfo=UTC))
    assert window.contains(datetime(2026, 9, 21, 22, 59, 59, tzinfo=UTC))
    assert not window.contains(datetime(2026, 9, 21, 23, tzinfo=UTC))

    with pytest.raises(ValueError, match="Friday"):
        MatchweekWindow.for_friday("2026-09-20")


def test_revision_observed_at_exact_cutoff_is_cutoff_valid(tmp_path: Path) -> None:
    from matchvet.matchweek import freeze_matchweek

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-18T13:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-18T13:00:00+00:00",
        created_at_utc="2026-09-18T13:00:00+00:00",
    )

    assert len(frozen.target_matches) == 1
    assert frozen.cutoff.cutoff_utc == "2026-09-18T13:00:00.000000+00:00"
    store.close()


def test_freeze_creates_normal_friday_to_monday_membership_and_one_cutoff(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek import MembershipState, freeze_matchweek

    store, importer = _import_schedule(
        tmp_path,
        [
            ("18/09/2026", "20:00", "Arsenal", "Coventry"),
            ("19/09/2026", "15:00", "Leeds", "West Ham"),
            ("21/09/2026", "20:00", "Newcastle", "Brighton"),
            ("22/09/2026", "20:00", "Chelsea", "Everton"),
        ],
        "2026-09-17T12:00:00+00:00",
    )
    assert len(importer.fixtures()) == 4
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    store.close()

    assert len(frozen.target_matches) == 3
    assert {item.membership_state for item in frozen.memberships} == {
        MembershipState.INCLUDED,
        MembershipState.EXCLUDED,
    }
    assert frozen.cutoff.cutoff_utc == "2026-09-18T13:00:00.000000+00:00"
    assert frozen.cutoff.earliest_included_kickoff_utc == "2026-09-18T19:00:00.000000+00:00"
    assert len({item.controlling_revision_id for item in frozen.memberships}) == 4
    assert all(item.controlling_revision_digest for item in frozen.memberships)


def test_freeze_is_immutable_and_replay_uses_the_stored_revision_digest(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek import freeze_matchweek, replay_matchweek

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    fixture_id = frozen.target_matches[0].subject_id
    original_ids = tuple(item.controlling_revision_id for item in frozen.memberships)
    replay = replay_matchweek(store, "2026-09-18")

    assert replay.freeze.memberships == frozen.memberships
    assert tuple(item.revision_id for item in replay.controlling_revisions) == original_ids

    # A later current revision is not replay input and cannot alter the frozen result.
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )

    revised = _schedule_csv([("19/09/2026", "20:00", "Arsenal", "Coventry")])
    FixtureHistoryImporter(store, private_root=tmp_path).import_dataset(
        FootballDataCSVParser().parse(
            revised, league=league_by_key("premier_league"), season="2026-27"
        ),
        revised,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    again = replay_matchweek(store, "2026-09-18")
    assert again.freeze.memberships == frozen.memberships
    assert again.controlling_revisions[0].fixture_id == fixture_id
    store.close()


def _full_validity_review() -> PostCutoffValidityReview:
    from matchvet.matchweek import PostCutoffValidityReview

    return PostCutoffValidityReview(
        identity_unchanged=True,
        scope_unchanged=True,
        kickoff_after_cutoff=True,
        no_postponement_or_cancellation=True,
        pre_match_valid=True,
        critical_evidence_valid=True,
        research_sufficiency_valid=True,
        information_boundary_valid=True,
    )


def _insert_fixture_status_revision(
    store: Store,
    fixture_id: str,
    *,
    status: str,
    observed_at: str,
    kickoff_utc: str | None,
) -> str:
    from matchvet.ingestion import deterministic_identifier
    from matchvet.store import CanonicalIdentifier

    connection = store._connection_for_repository()
    predecessor_row = connection.execute(
        """
        SELECT revision_id FROM fixture_revisions
        WHERE fixture_id = ? ORDER BY observed_at_utc DESC, revision_id DESC LIMIT 1
        """,
        (fixture_id,),
    ).fetchone()
    capture_row = connection.execute(
        """
        SELECT capture_id FROM source_captures
        ORDER BY retrieved_at_utc DESC, capture_id DESC LIMIT 1
        """
    ).fetchone()
    assert predecessor_row is not None
    assert capture_row is not None
    payload = {
        "fixture_status": status,
        "kickoff_local_text": None,
        "kickoff_precision": "INSTANT" if kickoff_utc is not None else "UNKNOWN",
        "kickoff_state": "OBSERVED" if kickoff_utc is not None else "UNKNOWN",
        "kickoff_utc": kickoff_utc,
        "source_round": None,
    }
    revision_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    revision_id = deterministic_identifier("fixture_revision", f"{fixture_id}:{revision_digest}")
    with store.transaction() as transaction:
        transaction.add_identifier_if_missing(CanonicalIdentifier("fixture_revision", revision_id))
        transaction.execute(
            """
            INSERT INTO fixture_revisions (
                revision_id, fixture_id, predecessor_revision_id, revision_digest,
                kickoff_state, kickoff_utc, kickoff_local_text, kickoff_precision,
                fixture_status, source_round, observed_at_utc, source_capture_id,
                source_assertion_ids_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                fixture_id,
                str(predecessor_row[0]),
                revision_digest,
                payload["kickoff_state"],
                kickoff_utc,
                None,
                payload["kickoff_precision"],
                status,
                None,
                observed_at,
                str(capture_row[0]),
                "[]",
                observed_at,
            ),
        )
    return revision_id


def test_post_cutoff_addition_is_appendix_only_and_same_window_move_can_preserve(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        append_post_cutoff_changes,
        append_post_cutoff_revision,
        freeze_matchweek,
        read_frozen_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    added = _schedule_csv([("19/09/2026", "15:00", "Leeds", "West Ham")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            added, league=league_by_key("premier_league"), season="2026-27"
        ),
        added,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    added_event = append_post_cutoff_changes(
        store,
        "2026-09-18",
        as_of_utc="2026-09-18T14:00:00+00:00",
    )[0]
    assert added_event.event_kind is AppendixEventKind.FIXTURE_ADDED_AFTER_CUTOFF
    assert added_event.disposition is AppendixDisposition.APPENDIX_ONLY
    assert not any(item.subject_id == added_event.fixture_id for item in frozen.target_matches)

    fixture_id = frozen.target_matches[0].subject_id
    moved = _schedule_csv([("19/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            moved, league=league_by_key("premier_league"), season="2026-27"
        ),
        moved,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T15:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    moved_revision = importer.revisions(fixture_id)[-1]
    preserved = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=moved_revision.revision_id,
        as_of_utc="2026-09-18T15:00:00+00:00",
        validity_review=_full_validity_review(),
    )
    assert preserved.event_kind is AppendixEventKind.SAME_WINDOW_KICKOFF_CHANGE
    assert preserved.disposition is AppendixDisposition.PRESERVED
    assert preserved.settlement_result is None
    assert read_frozen_matchweek(store, "2026-09-18").target_matches == frozen.target_matches
    store.close()


@pytest.mark.parametrize(
    ("new_date", "expected_kind"),
    [
        ("22/09/2026", "MOVED_OUTSIDE_WINDOW"),
        ("18/09/2026", "INVALID_PREMATCH_TIMING"),
    ],
)
def test_invalid_post_cutoff_kickoff_withdraws_and_grades_void(
    tmp_path: Path, new_date: str, expected_kind: str
) -> None:
    from matchvet.ingestion import (
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import (
        AppendixDisposition,
        append_post_cutoff_revision,
        freeze_matchweek,
        read_frozen_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    fixture_id = frozen.target_matches[0].subject_id
    revised = _schedule_csv([(new_date, "12:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            revised, league=league_by_key("premier_league"), season="2026-27"
        ),
        revised,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    revision = importer.revisions(fixture_id)[-1]
    event = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=revision.revision_id,
        as_of_utc="2026-09-18T14:00:00+00:00",
    )

    assert event.event_kind.value == expected_kind
    assert event.disposition is AppendixDisposition.WITHDRAWN
    assert event.settlement_result == "VOID"
    assert read_frozen_matchweek(store, "2026-09-18").target_matches == frozen.target_matches
    store.close()


def test_post_cutoff_move_into_window_is_appendix_only(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import FootballDataCSVParser, SourceCaptureInput, league_by_key
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        append_post_cutoff_revision,
        freeze_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [
            ("18/09/2026", "20:00", "Arsenal", "Coventry"),
            ("25/09/2026", "20:00", "Leeds", "West Ham"),
        ],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    moved_fixture_id = next(
        item.subject_id for item in frozen.excluded_memberships if item.subject_kind == "FIXTURE"
    )
    moved = _schedule_csv([("19/09/2026", "15:00", "Leeds", "West Ham")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            moved, league=league_by_key("premier_league"), season="2026-27"
        ),
        moved,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    revision = importer.revisions(moved_fixture_id)[-1]
    event = append_post_cutoff_revision(
        store,
        "2026-09-18",
        moved_fixture_id,
        revision_id=revision.revision_id,
        as_of_utc="2026-09-18T14:00:00+00:00",
    )

    assert event.event_kind is AppendixEventKind.MOVED_IN_AFTER_CUTOFF
    assert event.disposition is AppendixDisposition.APPENDIX_ONLY
    assert moved_fixture_id not in {item.subject_id for item in frozen.target_matches}
    store.close()


def test_inside_window_change_with_failed_validity_review_withdraws(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import FootballDataCSVParser, SourceCaptureInput, league_by_key
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        PostCutoffValidityReview,
        append_post_cutoff_revision,
        freeze_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    fixture_id = frozen.target_matches[0].subject_id
    moved = _schedule_csv([("19/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            moved, league=league_by_key("premier_league"), season="2026-27"
        ),
        moved,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T15:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    revision = importer.revisions(fixture_id)[-1]
    invalid_review = PostCutoffValidityReview(
        identity_unchanged=True,
        scope_unchanged=True,
        kickoff_after_cutoff=True,
        no_postponement_or_cancellation=True,
        pre_match_valid=True,
        critical_evidence_valid=False,
        research_sufficiency_valid=True,
        information_boundary_valid=True,
    )
    event = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=revision.revision_id,
        as_of_utc="2026-09-18T15:00:00+00:00",
        validity_review=invalid_review,
    )

    assert event.event_kind is AppendixEventKind.SAME_WINDOW_KICKOFF_CHANGE
    assert event.disposition is AppendixDisposition.WITHDRAWN
    assert event.settlement_result == "VOID"
    store.close()


@pytest.mark.parametrize("status", ["POSTPONED", "CANCELLED"])
def test_postponement_and_cancellation_withdraw_and_later_reschedule_stays_void(
    tmp_path: Path, status: str
) -> None:
    from matchvet.ingestion import (
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        append_post_cutoff_revision,
        freeze_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    fixture_id = frozen.target_matches[0].subject_id
    unchanged = _schedule_csv([("18/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            unchanged, league=league_by_key("premier_league"), season="2026-27"
        ),
        unchanged,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    status_revision_id = _insert_fixture_status_revision(
        store,
        fixture_id,
        status=status,
        observed_at="2026-09-18T14:00:00.000000+00:00",
        kickoff_utc=None,
    )
    withdrawn = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=status_revision_id,
        as_of_utc="2026-09-18T14:00:00+00:00",
    )
    assert withdrawn.event_kind.value == status
    assert withdrawn.disposition is AppendixDisposition.WITHDRAWN
    assert withdrawn.settlement_result == "VOID"

    rescheduled = _schedule_csv([("19/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            rescheduled, league=league_by_key("premier_league"), season="2026-27"
        ),
        rescheduled,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T15:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    rescheduled_revision = importer.revisions(fixture_id)[-1]
    later = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=rescheduled_revision.revision_id,
        as_of_utc="2026-09-18T15:00:00+00:00",
        validity_review=_full_validity_review(),
    )

    assert later.event_kind is AppendixEventKind.SAME_WINDOW_KICKOFF_CHANGE
    assert later.disposition is AppendixDisposition.WITHDRAWN
    assert later.settlement_result == "VOID"
    store.close()


def test_freeze_uses_the_pre_cutoff_schedule_when_current_state_is_postponed(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import FootballDataCSVParser, SourceCaptureInput, league_by_key
    from matchvet.matchweek import freeze_matchweek

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    fixture_id = importer.fixtures()[0].fixture_id
    unchanged = _schedule_csv([("18/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            unchanged, league=league_by_key("premier_league"), season="2026-27"
        ),
        unchanged,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    _insert_fixture_status_revision(
        store,
        fixture_id,
        status="POSTPONED",
        observed_at="2026-09-18T14:00:00.000000+00:00",
        kickoff_utc=None,
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-18T14:00:00+00:00",
        created_at_utc="2026-09-18T14:00:00+00:00",
    )

    assert tuple(item.subject_id for item in frozen.target_matches) == (fixture_id,)
    assert frozen.cutoff.cutoff_utc == "2026-09-18T13:00:00.000000+00:00"
    store.close()


def test_confirmed_identity_with_material_kickoff_conflict_is_included_but_blocked(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        OpenFootballJSONParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import MembershipState, freeze_matchweek

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    conflicting = (
        b'{"matches":[{"date":"2026-09-19","time":"20:00",'
        b'"team1":"Arsenal FC","team2":"Coventry City FC","score":{}}]}'
    )
    importer.import_dataset(
        OpenFootballJSONParser().parse(
            conflicting, league=league_by_key("premier_league"), season="2026-27"
        ),
        conflicting,
        SourceCaptureInput(
            source_url="https://example.test/en.1.json",
            retrieved_at_utc="2026-09-17T13:00:00+00:00",
            observed_terms="OpenFootball CC0",
        ),
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T13:00:00+00:00",
        created_at_utc="2026-09-17T13:00:00+00:00",
    )
    included = frozen.target_matches[0]

    assert included.membership_state is MembershipState.INCLUDED
    assert included.material_conflict is True
    assert included.conflict_predicates == ("kickoff",)
    assert included.decision_state == "MATERIAL_CONFLICT_BLOCKED"
    assert frozen.normal_coverage_denominator == 1
    store.close()


def test_unresolved_identity_is_indeterminate_and_excluded_from_coverage(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        TeamCanonicalizer,
        league_by_key,
    )
    from matchvet.matchweek import MembershipState, freeze_matchweek

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    league = league_by_key("premier_league")
    mapping = TeamCanonicalizer()
    first = mapping.register_team(league, "United One")
    second = mapping.register_team(league, "United Two")
    mapping.register_alias(league, "United", first)
    mapping.register_alias(league, "United", second)
    content = _schedule_csv([("19/09/2026", "15:00", "United", "Leeds")])
    FixtureHistoryImporter(store, private_root=tmp_path, team_canonicalizer=mapping).import_dataset(
        FootballDataCSVParser().parse(content, league=league, season="2026-27"),
        content,
        SourceCaptureInput(
            source_url="https://example.test/E0-ambiguous.csv",
            retrieved_at_utc="2026-09-17T12:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )

    indeterminate = tuple(
        item
        for item in frozen.memberships
        if item.membership_state is MembershipState.INDETERMINATE
    )
    assert len(indeterminate) == 1
    assert indeterminate[0].target_match is False
    assert indeterminate[0].decision_state == "NO_DECISION_INDETERMINATE"
    assert frozen.normal_coverage_denominator == 1
    store.close()


def test_post_cutoff_unresolved_identity_is_appendix_only(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        TeamCanonicalizer,
        league_by_key,
    )
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        append_post_cutoff_changes,
        freeze_matchweek,
    )

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    league = league_by_key("premier_league")
    mapping = TeamCanonicalizer()
    first = mapping.register_team(league, "United One")
    second = mapping.register_team(league, "United Two")
    mapping.register_alias(league, "United", first)
    mapping.register_alias(league, "United", second)
    content = _schedule_csv([("19/09/2026", "15:00", "United", "Leeds")])
    FixtureHistoryImporter(store, private_root=tmp_path, team_canonicalizer=mapping).import_dataset(
        FootballDataCSVParser().parse(content, league=league, season="2026-27"),
        content,
        SourceCaptureInput(
            source_url="https://example.test/E0-ambiguous.csv",
            retrieved_at_utc="2026-09-18T14:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )

    events = append_post_cutoff_changes(
        store,
        "2026-09-18",
        as_of_utc="2026-09-18T14:00:00+00:00",
    )

    assert len(events) == 1
    assert events[0].event_kind is AppendixEventKind.IDENTITY_CONFLICT
    assert events[0].disposition is AppendixDisposition.APPENDIX_ONLY
    assert events[0].subject_kind == "UNRESOLVED_FIXTURE_ROW"
    assert frozen.target_matches
    store.close()


def test_revision_authority_precedes_recency_and_duplicate_providers_do_not_duplicate_membership(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        OpenFootballJSONParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import freeze_matchweek

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-18T12:00:00+00:00",
    )
    # Add a lower-authority provider assertion for the same canonical fixture at a
    # different kickoff.  The source is still before the eventual cutoff.
    openfootball = (
        b'{"matches":[{"date":"2026-09-19","time":"20:00",'
        b'"team1":"Arsenal FC","team2":"Coventry City FC","score":{}}]}'
    )
    importer.import_dataset(
        OpenFootballJSONParser().parse(
            openfootball, league=league_by_key("premier_league"), season="2026-27"
        ),
        openfootball,
        SourceCaptureInput(
            source_url="https://example.test/en.1.json",
            retrieved_at_utc="2026-09-18T12:30:00+00:00",
            observed_terms="OpenFootball CC0",
        ),
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-19T00:00:00+00:00",
        created_at_utc="2026-09-19T00:00:00+00:00",
    )

    assert len(frozen.target_matches) == 1
    selected = frozen.target_matches[0]
    assert selected.source_authority_rank == 300
    assert selected.source_authority.startswith("STRUCTURED_PROVIDER:")
    assert selected.original_kickoff_utc == "2026-09-18T19:00:00.000000+00:00"
    assert len(frozen.memberships) == 1
    store.close()


def test_membership_and_revision_manifests_have_deterministic_digests(
    tmp_path: Path,
) -> None:
    from matchvet.artifacts import ArtifactStore
    from matchvet.matchweek import freeze_matchweek

    frozen_values = []
    manifest_bytes = []
    for name in ("first", "second"):
        store_root = tmp_path / name
        store_root.mkdir()
        store, _ = _import_schedule(
            store_root,
            [
                ("18/09/2026", "20:00", "Arsenal", "Coventry"),
                ("21/09/2026", "20:00", "Leeds", "West Ham"),
            ],
            "2026-09-17T12:00:00+00:00",
        )
        frozen = freeze_matchweek(
            store,
            "2026-09-18",
            as_of_utc="2026-09-17T12:00:00+00:00",
            created_at_utc="2026-09-17T12:00:00+00:00",
        )
        artifacts = ArtifactStore(store)
        frozen_values.append(
            (
                frozen.cutoff.digest,
                frozen.membership_manifest_digest,
                frozen.revision_snapshot_digest,
                frozen.memberships,
            )
        )
        manifest_bytes.append(artifacts.read_artifact(frozen.membership_manifest_digest))
        store.close()

    assert frozen_values[0] == frozen_values[1]
    assert manifest_bytes[0] == manifest_bytes[1]


def test_post_cutoff_identity_conflict_withdraws_without_changing_membership(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import FootballDataCSVParser, SourceCaptureInput, league_by_key
    from matchvet.matchweek import (
        AppendixDisposition,
        AppendixEventKind,
        append_post_cutoff_revision,
        freeze_matchweek,
    )

    store, importer = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    fixture_id = frozen.target_matches[0].subject_id
    moved = _schedule_csv([("19/09/2026", "20:00", "Arsenal", "Coventry")])
    importer.import_dataset(
        FootballDataCSVParser().parse(
            moved, league=league_by_key("premier_league"), season="2026-27"
        ),
        moved,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-18T15:00:00+00:00",
            observed_terms="restricted private test capture",
        ),
    )
    revision = importer.revisions(fixture_id)[-1]
    event = append_post_cutoff_revision(
        store,
        "2026-09-18",
        fixture_id,
        revision_id=revision.revision_id,
        as_of_utc="2026-09-18T15:00:00+00:00",
        identity_unchanged=False,
        validity_review=_full_validity_review(),
    )

    assert event.event_kind is AppendixEventKind.IDENTITY_CONFLICT
    assert event.disposition is AppendixDisposition.WITHDRAWN
    assert event.settlement_result == "VOID"
    store.close()


def test_replay_rejects_changed_or_missing_controlling_revision(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek import MatchweekError, freeze_matchweek, replay_matchweek

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    frozen = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    revision_id = frozen.target_matches[0].controlling_revision_id
    assert revision_id is not None
    connection = store._connection_for_repository()
    connection.execute("DROP TRIGGER fixture_revisions_no_update")
    connection.execute(
        "UPDATE fixture_revisions SET revision_digest = ? WHERE revision_id = ?",
        ("f" * 64, revision_id),
    )
    with pytest.raises(MatchweekError, match="changed"):
        replay_matchweek(store, "2026-09-18")

    connection.execute("DROP TRIGGER fixture_revisions_no_delete")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DELETE FROM fixture_revisions WHERE revision_id = ?", (revision_id,))
    with pytest.raises(MatchweekError, match="missing"):
        replay_matchweek(store, "2026-09-18")
    store.close()


def test_t05_runner_resumes_from_t04_checkpoint_without_recomputing_membership(
    tmp_path: Path,
) -> None:
    from matchvet.matchweek import (
        MatchweekFreezePlan,
        MatchweekFreezeRunner,
        freeze_matchweek,
    )
    from matchvet.runs import (
        GIB,
        ResourceObservation,
        RunLifecycleError,
        RunPhase,
        WorkContext,
        WorkInterrupted,
        WorkResult,
    )

    store, _ = _import_schedule(
        tmp_path,
        [("18/09/2026", "20:00", "Arsenal", "Coventry")],
        "2026-09-17T12:00:00+00:00",
    )
    plan = MatchweekFreezePlan(
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00.000000+00:00",
    )
    observation = ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0)

    class InterruptingRunner(MatchweekFreezeRunner):
        def __init__(self, store: Store) -> None:
            super().__init__(store)
            self.interrupted = False

        def _execute(self, plan: MatchweekFreezePlan, context: WorkContext) -> WorkResult:
            if context.phase is RunPhase.EVIDENCE_ACQUISITION and not self.interrupted:
                self.interrupted = True
                raise WorkInterrupted("synthetic T05 interruption")
            return super()._execute(plan, context)

    runner = InterruptingRunner(store)
    with pytest.raises(RunLifecycleError) as failed:
        runner.start(plan, observation=observation)
    resumed = runner.resume(failed.value.run_id, plan, observation=observation)

    assert resumed.state.value == "COMPLETE"
    assert resumed.work_units[1].attempt == 2
    assert runner.last_freeze is not None
    assert runner.last_freeze.membership_manifest_digest
    assert (
        freeze_matchweek(
            store,
            "2026-09-18",
            as_of_utc="2026-09-19T00:00:00+00:00",
        ).membership_manifest_digest
        == runner.last_freeze.membership_manifest_digest
    )
    store.close()

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from matchvet.ingestion import (
    ABSENT,
    OBSERVED,
    TARGET_LEAGUES,
    UNKNOWN,
    FootballDataCSVParser,
    SourceParseError,
    football_data_url,
    league_by_key,
)

FOOTBALL_DATA_SAMPLE = """\
Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,HxG,AxG,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,B365H
E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,2,0,H,T Bramall,1.88,0.2,20,4,6,1,10,13,8,2,1,1,0,0,1.2
E0,22/08/2026,15:00,Leeds,West Ham,,,,,,,,,,,,,,,,,,,,,
E0,23/08/2026,15:00,Arsenal,Newcastle,,,,,,,,,,,,,,,,,bad,2,,,,,,
"""


def test_target_league_set_and_primary_url_cover_exactly_seven_leagues() -> None:
    assert tuple(league.key for league in TARGET_LEAGUES) == (
        "premier_league",
        "serie_a",
        "la_liga",
        "bundesliga",
        "ligue_1",
        "liga_portugal",
        "belgian_pro_league",
    )
    assert len(TARGET_LEAGUES) == 7
    assert football_data_url(league_by_key("premier_league"), "2026-27") == (
        "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
    )
    assert football_data_url(league_by_key("belgian_pro_league"), "2025-26") == (
        "https://www.football-data.co.uk/mmz4281/2526/B1.csv"
    )


def test_refresh_policy_changes_the_t06_resume_identity() -> None:
    from matchvet.ingestion import IngestionPlan, build_t06_input_contract

    cached = IngestionPlan(current_season="2026-27", refresh_current=False)
    refreshed = IngestionPlan(current_season="2026-27", refresh_current=True)

    assert cached.plan_digest != refreshed.plan_digest
    assert (
        build_t06_input_contract(cached).aggregate_digest
        != build_t06_input_contract(refreshed).aggregate_digest
    )


def test_football_data_parser_keeps_only_approved_fields_and_epistemic_states() -> None:
    dataset = FootballDataCSVParser().parse(
        FOOTBALL_DATA_SAMPLE.encode("latin-1"),
        league=league_by_key("premier_league"),
        season="2026-27",
    )

    first, second, third = dataset.rows
    assert first.home_team == "Arsenal"
    assert first.kickoff_utc == datetime(2026, 8, 21, 19, tzinfo=UTC)
    assert first.fields["full_time_home_goals"].state == OBSERVED
    assert first.fields["full_time_home_goals"].value == 3
    assert first.fields["corners_home"].value == 8
    assert first.fields["home_xg"].state == OBSERVED
    assert first.fields["home_xg"].evidence_class == "OPTIONAL_EVIDENCE"
    assert "B365H" not in first.raw_fields
    assert "Referee" not in first.raw_fields

    assert second.fields["full_time_home_goals"].state == UNKNOWN
    assert second.fields["full_time_home_goals"].unknown_reason == "SOURCE_MISSING_FIELD"
    assert second.fields["corners_home"].state == UNKNOWN

    assert third.fields["corners_away"].state == UNKNOWN
    assert third.fields["corners_away"].unknown_reason == "MALFORMED_VALUE"
    assert third.fields["full_time_home_goals"].state == UNKNOWN


def test_parser_ignores_unapproved_odds_headers_with_colliding_normalized_names() -> None:
    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,B365>2.5,B365<2.5,B365C>2.5,B365C<2.5\n"
        b"E0,21/08/2026,20:00,Arsenal,Coventry,2.1,1.8,2.0,1.7\n"
    )

    dataset = FootballDataCSVParser().parse(
        content,
        league=league_by_key("premier_league"),
        season="2026-27",
    )

    assert len(dataset.rows) == 1
    assert dataset.rows[0].raw_fields == {
        "Div": "E0",
        "Date": "21/08/2026",
        "Time": "20:00",
        "HomeTeam": "Arsenal",
        "AwayTeam": "Coventry",
    }


def test_parser_rejects_structurally_malformed_input() -> None:
    with pytest.raises(SourceParseError, match="required HomeTeam and AwayTeam columns"):
        FootballDataCSVParser().parse(
            b"Date,HomeTeam\n21/08/2026,Arsenal\n",
            league=league_by_key("premier_league"),
            season="2026-27",
        )


def test_epistemic_constants_do_not_confuse_absent_with_unknown() -> None:
    assert OBSERVED != UNKNOWN
    assert UNKNOWN != ABSENT


OPENFOOTBALL_SAMPLE = b"""{
  "name": "England Premier League 2026/27",
  "matches": [
    {"round": "Matchday 1", "date": "2026-08-21", "time": "20:00",
     "team1": "Arsenal FC", "team2": "Coventry City FC",
     "score": {"ht": [2, 0], "ft": [3, 0]}},
    {"round": "Matchday 2", "date": "2026-08-28",
     "team1": "Leeds United AFC", "team2": "West Ham United", "score": {}}
  ]
}"""


def test_openfootball_parser_is_a_six_league_fixture_and_goal_fallback() -> None:
    from matchvet.ingestion import OpenFootballJSONParser, openfootball_url

    league = league_by_key("premier_league")
    dataset = OpenFootballJSONParser().parse(OPENFOOTBALL_SAMPLE, league=league, season="2026-27")

    assert openfootball_url(league, "2026-27").endswith("/2026-27/en.1.json")
    assert len(dataset.rows) == 2
    assert dataset.rows[0].home_team == "Arsenal FC"
    assert dataset.rows[0].fields["full_time_home_goals"].value == 3
    assert dataset.rows[0].fields["half_time_home_goals"].value == 2
    assert dataset.rows[1].fields["half_time_home_goals"].unknown_reason == "SOURCE_MISSING_FIELD"
    assert dataset.rows[0].fields["shots_home"].unknown_reason == "SOURCE_OUTSIDE_COVERAGE"

    with pytest.raises(SourceParseError, match="matches array"):
        OpenFootballJSONParser().parse(b'{"name": "wrong"}', league=league, season="2026-27")


def test_openfootball_fallback_is_not_claimed_for_belgian_pro_league() -> None:
    from matchvet.ingestion import openfootball_url

    with pytest.raises(Exception, match="no permitted fallback"):
        openfootball_url(league_by_key("belgian_pro_league"), "2026-27")


def test_team_canonicalizer_accepts_aliases_and_leaves_ambiguity_unresolved() -> None:
    from matchvet.ingestion import MappingState, TeamCanonicalizer

    league = league_by_key("premier_league")
    mapping = TeamCanonicalizer()
    united = mapping.register_team(league, "Manchester United", "Man United")
    mapping.register_team(league, "Manchester City", "Man City")
    mapping.register_alias(league, "United", united)
    mapping.register_alias(
        league,
        "United",
        mapping.resolve_or_register(league, "Manchester City").canonical_team_id or "",
    )

    assert mapping.resolve(league, "Man United").state is MappingState.CONFIRMED
    assert mapping.resolve(league, "Man United").canonical_team_id == united
    assert mapping.resolve(league, "United").state is MappingState.AMBIGUOUS
    assert mapping.resolve(league, "Unknown Athletic").state is MappingState.UNKNOWN


def _minimal_csv(
    home: str = "Arsenal", away: str = "Coventry", date_text: str = "21/08/2026"
) -> bytes:
    return (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC,HS,AS,HY,AY,HR,AR\n"
        f"E0,{date_text},20:00,{home},{away},3,0,H,2,0,8,2,20,4,1,1,0,0\n"
    ).encode()


def test_importer_supports_all_seven_leagues_and_preserves_restricted_rights(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        results = []
        for league in TARGET_LEAGUES:
            dataset = FootballDataCSVParser().parse(_minimal_csv(), league=league, season="2026-27")
            results.append(
                importer.import_dataset(
                    dataset,
                    _minimal_csv(),
                    SourceCaptureInput(
                        source_url=f"https://example.test/{league.key}.csv",
                        retrieved_at_utc="2026-09-13T12:00:00+00:00",
                        observed_terms="restricted private test capture",
                    ),
                )
            )

        assert {result.league_key for result in results} == {
            league.key for league in TARGET_LEAGUES
        }
        assert len(importer.fixtures()) == 7
        assert all(
            capture.allowed_use == "RESTRICTED_PRIVATE"
            and capture.retention_status == "RETAIN_PRIVATE"
            and capture.redistributable is False
            for capture in importer.source_captures()
        )


def test_importer_is_idempotent_and_fixture_revisions_are_append_only(tmp_path: Path) -> None:
    from matchvet.ingestion import FixtureHistoryImporter, FootballDataCSVParser, SourceCaptureInput
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    first_content = _minimal_csv(date_text="21/08/2026")
    second_content = _minimal_csv(date_text="22/08/2026")
    league = league_by_key("premier_league")
    first_dataset = FootballDataCSVParser().parse(first_content, league=league, season="2026-27")
    second_dataset = FootballDataCSVParser().parse(second_content, league=league, season="2026-27")

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        capture = SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-13T12:00:00+00:00",
            observed_terms="restricted private test capture",
        )
        first = importer.import_dataset(first_dataset, first_content, capture)
        duplicate = importer.import_dataset(first_dataset, first_content, capture)
        revised = importer.import_dataset(
            second_dataset,
            second_content,
            SourceCaptureInput(
                source_url="https://example.test/E0.csv",
                retrieved_at_utc="2026-09-13T13:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )
        fixture_id = importer.fixtures()[0].fixture_id
        revisions = importer.revisions(fixture_id)

        assert first.fixtures_imported == 1
        assert duplicate.fixtures_imported == 0
        assert duplicate.source_capture_id == first.source_capture_id
        assert revised.revisions_appended == 1
        assert len(revisions) == 2
        assert revisions[0].kickoff_utc != revisions[1].kickoff_utc


def test_importer_retains_conflicting_source_assertions_and_unknown_fields(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        OpenFootballJSONParser,
        SourceCaptureInput,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    football_data = _minimal_csv(date_text="21/08/2026")
    openfootball = (
        b'{"matches":[{"date":"2026-08-22","time":"20:00",'
        b'"team1":"Arsenal FC","team2":"Coventry City FC","score":{}}]}'
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        importer.import_dataset(
            FootballDataCSVParser().parse(football_data, league=league, season="2026-27"),
            football_data,
            SourceCaptureInput(
                source_url="https://example.test/E0.csv",
                retrieved_at_utc="2026-09-13T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )
        importer.import_dataset(
            OpenFootballJSONParser().parse(openfootball, league=league, season="2026-27"),
            openfootball,
            SourceCaptureInput(
                source_url="https://example.test/en.1.json",
                retrieved_at_utc="2026-09-13T13:00:00+00:00",
                observed_terms="CC0",
            ),
        )
        fixture = importer.fixtures()[0]
        statistics = importer.statistics(fixture.fixture_id)
        conflicts = importer.conflicts(fixture.fixture_id)

        assert any(
            stat.metric_key == "corners_home" and stat.state is UNKNOWN for stat in statistics
        )
        assert any(
            stat.metric_key == "full_time_home_goals" and stat.state is OBSERVED
            for stat in statistics
        )
        assert any(conflict.predicate == "kickoff" for conflict in conflicts)
        assert (
            sum(1 for assertion in importer.source_assertions() if assertion.predicate == "kickoff")
            == 2
        )


def test_ambiguous_team_aliases_remain_unresolved(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        TeamCanonicalizer,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    mapping = TeamCanonicalizer()
    first = mapping.register_team(league, "United One")
    second = mapping.register_team(league, "United Two")
    mapping.register_alias(league, "United", first)
    mapping.register_alias(league, "United", second)
    content = _minimal_csv(home="United", away="Arsenal")

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(
            store, private_root=private_root, team_canonicalizer=mapping
        )
        result = importer.import_dataset(
            FootballDataCSVParser().parse(content, league=league, season="2026-27"),
            content,
            SourceCaptureInput(
                source_url="https://example.test/E0.csv",
                retrieved_at_utc="2026-09-13T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )

        assert result.unresolved_rows == 1
        assert importer.fixtures() == ()


def test_import_transaction_rolls_back_all_normalized_rows_on_failure(tmp_path: Path) -> None:
    from matchvet.ingestion import FixtureHistoryImporter, FootballDataCSVParser, SourceCaptureInput
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    content = _minimal_csv()
    dataset = FootballDataCSVParser().parse(
        content, league=league_by_key("premier_league"), season="2026-27"
    )
    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        with pytest.raises(RuntimeError, match="injected import failure"):
            importer.import_dataset(
                dataset,
                content,
                SourceCaptureInput(
                    source_url="https://example.test/E0.csv",
                    retrieved_at_utc="2026-09-13T12:00:00+00:00",
                    observed_terms="restricted private test capture",
                ),
                failure_hook=lambda row_number: (
                    (_ for _ in ()).throw(RuntimeError("injected import failure"))
                    if row_number == 1
                    else None
                ),
            )
        assert importer.fixtures() == ()
        assert importer.source_captures() == ()


def test_acquirer_imports_all_seven_leagues_offline(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    sources = {
        football_data_url(league, "2026-27"): _minimal_csv(
            home=f"Home {index}", away=f"Away {index}"
        )
        for index, league in enumerate(TARGET_LEAGUES)
    }
    plan = IngestionPlan(current_season="2026-27", use_openfootball_fallback=False)
    fetcher = StaticSourceFetcher(sources)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, fetcher).acquire(plan)

        assert len(report.imports) == 7
        assert report.issues == ()
        assert report.fallback_imports == 0
        assert {item.league_key for item in report.imports} == {
            league.key for league in TARGET_LEAGUES
        }
        assert fetcher.calls == [football_data_url(league, "2026-27") for league in TARGET_LEAGUES]
        assert len(importer.source_captures()) == 7


def test_successful_results_acquisition_does_not_suppress_schedule_acquisition(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import (
        MatchweekScheduleState,
        ProviderAttemptState,
        ScopeCoverageState,
    )
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    schedule = b"""{"matches":[
      {"date":"2026-09-25","time":"20:00","team1":"Arsenal",
       "team2":"Coventry","score":{}}
    ]}"""
    fetcher = StaticSourceFetcher(
        {
            football_data_url(league, "2026-27"): _minimal_csv(),
            openfootball_url(league, "2026-27"): schedule,
        }
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, fetcher).acquire(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        scheduled = report.scheduled_fixtures
        assert scheduled is not None
        assert fetcher.calls == [
            football_data_url(league, "2026-27"),
            openfootball_url(league, "2026-27"),
            openfootball_text_url(league, "2026-27"),
        ]
        assert len(report.imports) == 1
        assert len(scheduled.imports) == 1
        json_attempt = next(
            item
            for item in scheduled.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        assert json_attempt.state is ProviderAttemptState.CAPTURED
        assert len(scheduled.assessment.scope_assessments) == 7
        assert (
            scheduled.assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
        )
        assert scheduled.assessment.schedule_state is MatchweekScheduleState.UNKNOWN


def test_acquirer_requests_all_six_schedule_feeds_and_keeps_belgium_unknown(
    tmp_path: Path,
) -> None:
    from matchvet.fixture_coverage import (
        MatchweekScheduleState,
        ProviderAttemptState,
        ScopeCoverageState,
    )
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    schedule_payloads = {
        openfootball_url(league, "2026-27"): (
            b'{"matches":[{"date":"2026-09-25","time":"20:00",'
            b'"team1":"Arsenal","team2":"Coventry","score":{}}]}'
        )
        for league in TARGET_LEAGUES
        if league.openfootball_supported
    }
    sources = {football_data_url(league, "2026-27"): _minimal_csv() for league in TARGET_LEAGUES}
    sources.update(schedule_payloads)
    text_payload = b"= OpenFootball schedule\n\nMatchday 1\n"
    sources.update(
        {
            openfootball_text_url(league, "2026-27"): text_payload
            for league in TARGET_LEAGUES
            if league.openfootball_supported
        }
    )
    fetcher = StaticSourceFetcher(sources)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, fetcher).acquire(
            IngestionPlan(current_season="2026-27", matchweek_friday="2026-09-25")
        )

        scheduled = report.scheduled_fixtures
        assert scheduled is not None
        supported = tuple(league for league in TARGET_LEAGUES if league.openfootball_supported)
        expected_schedule_urls = [
            url
            for league in supported
            for url in (
                openfootball_url(league, "2026-27"),
                openfootball_text_url(league, "2026-27"),
            )
        ]
        assert fetcher.calls[-12:] == expected_schedule_urls
        assert len(scheduled.assessment.provider_attempts) == 12
        assert all(
            item.state is ProviderAttemptState.CAPTURED
            for item in scheduled.assessment.provider_attempts
        )
        assert len(scheduled.imports) == 12
        assert len(scheduled.assessment.fixture_revisions) == 6
        assert scheduled.assessment.coverage_evidence == ()
        assert scheduled.assessment.schedule_state is MatchweekScheduleState.UNKNOWN
        assert all(
            item.coverage_state is ScopeCoverageState.UNKNOWN
            for item in scheduled.assessment.scope_assessments
        )
        belgium = next(
            item
            for item in scheduled.assessment.scope_assessments
            if item.scope.league_key == "belgian_pro_league"
        )
        assert belgium.coverage_state is ScopeCoverageState.UNKNOWN
        assert belgium.provider_attempt_ids == ()
        assert any("belgian_pro_league" in item for item in scheduled.diagnostics)


@pytest.mark.parametrize(
    ("primary_content", "primary_state"),
    (
        (None, "UNAVAILABLE"),
        (b"not-json", "MALFORMED"),
        (b'{"matches":[]}', "CAPTURED"),
        (
            b'{"matches":[{"date":"2026-09-25","team1":"Arsenal","team2":"Coventry","score":{}}]}',
            "CAPTURED",
        ),
    ),
    ids=("unavailable", "malformed", "empty", "partial"),
)
def test_schedule_acquisition_retains_openfootball_text_fallback_attempt(
    tmp_path: Path,
    primary_content: bytes | None,
    primary_state: str,
) -> None:
    from matchvet.fixture_coverage import ProviderAttemptState
    from matchvet.ingestion import (
        DownloadedSource,
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        SourceUnavailable,
        StaticSourceFetcher,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    primary_url = openfootball_url(league, "2026-27")
    fallback_url = openfootball_text_url(league, "2026-27")
    fallback_content = (
        b"= English Premier League 2026/27\n\n"
        b"Matchday 6\n\nFri Sep 25 2026\n\n"
        b"20:00 Arsenal FC v Coventry City FC\n"
    )

    class PrimaryUnavailableFetcher(StaticSourceFetcher):
        def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> DownloadedSource:
            if url == primary_url and primary_content is None:
                self.calls.append(url)
                raise SourceUnavailable("HTTP 503 from schedule feed", http_status=503)
            return super().fetch(url, cache_key=cache_key, refresh=refresh)

    fetcher = PrimaryUnavailableFetcher({fallback_url: fallback_content})
    if primary_content is not None:
        fetcher.sources[primary_url] = primary_content

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        scheduled = FixtureHistoryAcquirer(
            importer,
            fetcher,
            attempted_at=lambda: "2026-09-25T10:01:00+00:00",
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27", leagues=(league,), matchweek_friday="2026-09-25"
            )
        )

        attempts = scheduled.assessment.provider_attempts
        assert fetcher.calls == [primary_url, fallback_url]
        assert len(attempts) == 2
        assert attempts[0].state is ProviderAttemptState(primary_state)
        assert attempts[0].provider_id == "openfootball-json"
        assert attempts[0].http_status == (503 if primary_state == "UNAVAILABLE" else 200)
        assert attempts[1].state is ProviderAttemptState.CAPTURED
        assert attempts[1].provider_id == "openfootball-footballtxt"
        assert attempts[1].capture_id is not None
        assert attempts[1].capture_digest is not None
        assert len(scheduled.imports) == (1 if primary_state in {"UNAVAILABLE", "MALFORMED"} else 2)
        assert any(result.fixtures_seen == 1 for result in scheduled.imports)


@pytest.mark.parametrize(
    ("fallback_content", "fallback_state"),
    ((None, "UNAVAILABLE"), (b"malformed text", "MALFORMED"), (b"= Empty schedule\n", "CAPTURED")),
    ids=("unavailable", "malformed", "empty"),
)
def test_schedule_text_fallback_outcomes_are_retained(
    tmp_path: Path,
    fallback_content: bytes | None,
    fallback_state: str,
) -> None:
    from matchvet.fixture_coverage import MatchweekScheduleState, ProviderAttemptState
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    primary_url = openfootball_url(league, "2026-27")
    fallback_url = openfootball_text_url(league, "2026-27")
    sources = {primary_url: b'{"matches":[]}'}
    if fallback_content is not None:
        sources[fallback_url] = fallback_content

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        scheduled = FixtureHistoryAcquirer(
            importer,
            StaticSourceFetcher(sources),
            attempted_at=lambda: "2026-09-25T10:01:00+00:00",
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27", leagues=(league,), matchweek_friday="2026-09-25"
            )
        )

        attempts = {item.provider_id: item for item in scheduled.assessment.provider_attempts}
        primary_attempt = attempts["openfootball-json"]
        fallback_attempt = attempts["openfootball-footballtxt"]
        assert primary_attempt.state is ProviderAttemptState.CAPTURED
        assert fallback_attempt.state is ProviderAttemptState(fallback_state)
        assert scheduled.assessment.schedule_state is MatchweekScheduleState.UNKNOWN
        assert scheduled.assessment.coverage_evidence == ()
        if fallback_state == "UNAVAILABLE":
            assert fallback_attempt.http_status is None
            assert fallback_attempt.capture_id is None
        else:
            assert fallback_attempt.capture_id is not None
            assert fallback_attempt.capture_digest is not None
            assert any(
                capture.capture_id == fallback_attempt.capture_id
                for capture in importer.source_captures()
            )


def test_date_only_text_fixture_is_included_by_f01_matchweek_scope(tmp_path: Path) -> None:
    from matchvet.fixture_coverage import FixtureIdentityState
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        TeamCanonicalizer,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    canonicalizer = TeamCanonicalizer()
    canonicalizer.register_team(league, "Northside")
    canonicalizer.register_team(league, "Harbor United")
    text_source = openfootball_text_url(league, "2026-27")
    text_content = (
        b"= English Premier League 2026/27\n\n"
        b"Matchday 1\n\nFri Sep 25 2026\n\n"
        b"Northside v Harbor United\n"
        b"Mystery United v Unlisted Athletic\n"
    )
    fetcher = StaticSourceFetcher(
        {
            openfootball_url(league, "2026-27"): b'{"matches":[]}',
            text_source: text_content,
        },
        retrieved_at_utc="2026-09-25T10:00:00+00:00",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(
            store,
            private_root=private_root,
            team_canonicalizer=canonicalizer,
        )
        scheduled = FixtureHistoryAcquirer(importer, fetcher).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        text_attempt = next(
            item
            for item in scheduled.assessment.provider_attempts
            if item.provider_id == "openfootball-footballtxt"
        )
        assert len(scheduled.assessment.fixture_revisions) == 1
        revision = scheduled.assessment.fixture_revisions[0]
        assert revision.source_capture_ids == (text_attempt.capture_id,)
        assert len(scheduled.assessment.identity_resolutions) == 2
        assert scheduled.imports[-1].unresolved_rows == 1
        resolved_identity = next(
            item
            for item in scheduled.assessment.identity_resolutions
            if item.state is FixtureIdentityState.RESOLVED
        )
        assert resolved_identity.source_capture_ids == (text_attempt.capture_id,)
        unresolved_identity = next(
            item
            for item in scheduled.assessment.identity_resolutions
            if item.state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
        )
        assert unresolved_identity.source_capture_ids == (text_attempt.capture_id,)
        stored = importer.revisions(importer.fixtures()[0].fixture_id)[0]
        assert stored.kickoff_utc is None
        assert stored.kickoff_precision == "DATE"


def test_date_only_text_fixture_crossing_f01_boundary_is_not_assigned_to_scope(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        TeamCanonicalizer,
        openfootball_text_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("serie_a")
    canonicalizer = TeamCanonicalizer()
    canonicalizer.register_team(league, "Northside")
    canonicalizer.register_team(league, "Harbor United")
    text_source = openfootball_text_url(league, "2026-27")
    text_content = (
        b"= Italy Serie A 2026/27\n\nMatchday 1\n\nFri Sep 25 2026\n\nNorthside v Harbor United\n"
    )
    fetcher = StaticSourceFetcher(
        {
            openfootball_url(league, "2026-27"): b'{"matches":[]}',
            text_source: text_content,
        },
        retrieved_at_utc="2026-09-25T10:00:00+00:00",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(
            store,
            private_root=private_root,
            team_canonicalizer=canonicalizer,
        )
        scheduled = FixtureHistoryAcquirer(importer, fetcher).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        text_attempt = next(
            item
            for item in scheduled.assessment.provider_attempts
            if item.provider_id == "openfootball-footballtxt"
        )
        fixtures = importer.fixtures()
        assert len(fixtures) == 1
        stored_revisions = importer.revisions(fixtures[0].fixture_id)
        assert len(stored_revisions) == 1
        assert scheduled.imports[-1].fixtures_seen == 1
        assert scheduled.assessment.fixture_revisions == ()
        assert scheduled.assessment.identity_resolutions == ()
        assert text_attempt.capture_id is not None


@pytest.mark.parametrize(
    ("schedule_payload", "expected_state"),
    [
        (None, "UNAVAILABLE"),
        (b"not-json", "MALFORMED"),
        (b'{"matches":[]}', "CAPTURED"),
    ],
    ids=("unavailable", "malformed", "valid-empty"),
)
def test_schedule_attempt_states_do_not_infer_coverage_from_transport_or_rows(
    tmp_path: Path,
    schedule_payload: bytes | None,
    expected_state: str,
) -> None:
    from matchvet.fixture_coverage import MatchweekScheduleState, ScopeCoverageState
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    sources = {football_data_url(league, "2026-27"): _minimal_csv()}
    if schedule_payload is not None:
        sources[openfootball_url(league, "2026-27")] = schedule_payload
    fetcher = StaticSourceFetcher(
        sources,
        retrieved_at_utc="2026-09-25T10:00:00+00:00",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(
            importer,
            fetcher,
            attempted_at=lambda: "2026-09-25T10:01:00+00:00",
        ).acquire(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        scheduled = report.scheduled_fixtures
        assert scheduled is not None
        attempt = next(
            item
            for item in scheduled.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        assert attempt.state.value == expected_state
        assert scheduled.assessment.schedule_state is MatchweekScheduleState.UNKNOWN
        assert all(
            item.coverage_state is ScopeCoverageState.UNKNOWN
            for item in scheduled.assessment.scope_assessments
        )
        assert scheduled.assessment.coverage_evidence == ()
        if expected_state == "UNAVAILABLE":
            assert attempt.capture_id is None
            assert len(importer.source_captures()) == 1
            assert scheduled.imports == ()
        elif expected_state == "MALFORMED":
            assert attempt.capture_id is not None
            assert attempt.capture_digest is not None
            assert any(item.capture_id == attempt.capture_id for item in importer.source_captures())
            assert scheduled.imports == ()
        else:
            assert attempt.capture_id is not None
            assert len(scheduled.imports) == 1
            assert scheduled.imports[0].fixtures_seen == 0


def test_partial_schedule_preserves_unresolved_teams_without_guessing(tmp_path: Path) -> None:
    from matchvet.fixture_coverage import (
        FixtureIdentityState,
        MatchweekScheduleState,
        ScopeCoverageState,
    )
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    source_url = openfootball_url(league, "2026-27")
    schedule = b"""{"matches":[
      {"date":"2026-09-26","time":"15:00","team1":"Mystery United",
       "team2":"Unlisted Athletic","score":{}}
    ]}"""
    fetcher = StaticSourceFetcher(
        {
            football_data_url(league, "2026-27"): _minimal_csv(),
            source_url: schedule,
        }
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, fetcher).acquire(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        scheduled = report.scheduled_fixtures
        assert scheduled is not None
        assert scheduled.imports[0].unresolved_rows == 1
        assert all(
            fixture.home_team_name != "Mystery United"
            and fixture.away_team_name != "Unlisted Athletic"
            for fixture in importer.fixtures()
        )
        unresolved = scheduled.assessment.identity_resolutions
        assert len(unresolved) == 1
        assert unresolved[0].state is FixtureIdentityState.UNRESOLVED_FIXTURE_IDENTITY
        json_attempt = next(
            item
            for item in scheduled.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        assert unresolved[0].source_capture_ids == (json_attempt.capture_id,)
        assert unresolved[0].source_assertion_ids
        assert scheduled.assessment.scope_assessments[0].identity_blocker_candidate_ids == (
            unresolved[0].candidate_id,
        )
        assert (
            scheduled.assessment.scope_assessments[0].coverage_state is ScopeCoverageState.UNKNOWN
        )
        assert scheduled.assessment.schedule_state is MatchweekScheduleState.UNKNOWN


def test_schedule_import_is_idempotent_and_reschedules_append_revisions(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        TeamCanonicalizer,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    source_url = openfootball_url(league, "2026-27")
    canonicalizer = TeamCanonicalizer()
    canonicalizer.register_team(league, "Northside")
    canonicalizer.register_team(league, "Harbor FC")

    def schedule(time_text: str) -> bytes:
        return (
            '{"matches":[{"date":"2026-09-25","time":"'
            + time_text
            + '","team1":"Northside","team2":"Harbor FC","score":{}}]}'
        ).encode()

    fetcher = StaticSourceFetcher(
        {source_url: schedule("20:00")},
        retrieved_at_utc="2026-09-25T10:00:00+00:00",
    )
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(
            store,
            private_root=private_root,
            team_canonicalizer=canonicalizer,
        )
        acquirer = FixtureHistoryAcquirer(importer, fetcher)

        first = acquirer.acquire_scheduled_fixtures(plan)
        first_revision = first.assessment.fixture_revisions[0]
        fixture = importer.fixtures()[0]
        first_history = importer.revisions(fixture.fixture_id)
        assert len(first_history) == 1
        assert first.imports[0].revisions_appended == 1
        assert first_revision.revision_id == first_history[0].revision_id
        json_attempt = next(
            item
            for item in first.assessment.provider_attempts
            if item.provider_id == "openfootball-json"
        )
        assert first_revision.source_capture_ids == (json_attempt.capture_id,)
        assert first_revision.source_assertion_ids

        duplicate = acquirer.acquire_scheduled_fixtures(plan)
        assert duplicate.imports[0].from_existing_capture is True
        assert duplicate.imports[0].revisions_appended == 0
        assert len(importer.revisions(fixture.fixture_id)) == 1

        fetcher.sources[source_url] = schedule("21:00")
        fetcher.retrieved_at_utc = "2026-09-25T11:00:00+00:00"
        rescheduled = acquirer.acquire_scheduled_fixtures(plan)
        revisions = importer.revisions(fixture.fixture_id)
        assert rescheduled.imports[0].revisions_appended == 1
        assert len(revisions) == 2
        assert revisions[1].predecessor_revision_id == revisions[0].revision_id
        assert revisions[1].kickoff_utc != revisions[0].kickoff_utc

        replay = acquirer.acquire_scheduled_fixtures(plan)
        assert replay.imports[0].from_existing_capture is True
        assert len(importer.revisions(fixture.fixture_id)) == 2


def test_schedule_import_reuses_persisted_team_aliases(tmp_path: Path) -> None:
    from matchvet.fixture_coverage import FixtureIdentityState
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        FootballDataCSVParser,
        IngestionPlan,
        SourceCaptureInput,
        StaticSourceFetcher,
        TeamCanonicalizer,
        football_data_url,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    canonicalizer = TeamCanonicalizer()
    canonicalizer.register_team(league, "Canonical Home", "Home Alias")
    canonicalizer.register_team(league, "Canonical Away", "Away Alias")
    results_content = _minimal_csv(home="Home Alias", away="Away Alias")
    schedule_content = b"""{"matches":[
      {"date":"2026-09-26","time":"15:00","team1":"Home Alias",
       "team2":"Away Alias","score":{}}
    ]}"""

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        results_importer = FixtureHistoryImporter(
            store,
            private_root=private_root,
            team_canonicalizer=canonicalizer,
        )
        results_importer.import_dataset(
            FootballDataCSVParser().parse(results_content, league=league, season="2026-27"),
            results_content,
            SourceCaptureInput(
                source_url=football_data_url(league, "2026-27"),
                retrieved_at_utc="2026-09-13T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )
        expected_fixture_id = results_importer.fixtures()[0].fixture_id

        schedule_importer = FixtureHistoryImporter(store, private_root=private_root)
        scheduled = FixtureHistoryAcquirer(
            schedule_importer,
            StaticSourceFetcher(
                {openfootball_url(league, "2026-27"): schedule_content},
                retrieved_at_utc="2026-09-25T10:00:00+00:00",
            ),
        ).acquire_scheduled_fixtures(
            IngestionPlan(
                current_season="2026-27",
                leagues=(league,),
                matchweek_friday="2026-09-25",
            )
        )

        assert scheduled.imports[0].unresolved_rows == 0
        assert len(scheduled.assessment.identity_resolutions) == 1
        identity = scheduled.assessment.identity_resolutions[0]
        assert identity.state is FixtureIdentityState.RESOLVED
        assert identity.canonical_fixture_id == expected_fixture_id
        assert schedule_importer.revisions(expected_fixture_id)[-1].fixture_status == "SCHEDULED"


def test_acquirer_imports_an_explicit_historical_season(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    sources = {
        football_data_url(league, season): _minimal_csv(date_text=date_text)
        for season, date_text in (("2026-27", "21/08/2026"), ("2025-26", "21/08/2025"))
    }
    plan = IngestionPlan(
        current_season="2026-27",
        historical_seasons=("2025-26",),
        leagues=(league,),
        use_openfootball_fallback=False,
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, StaticSourceFetcher(sources)).acquire(plan)

        assert {(item.season, item.league_key) for item in report.imports} == {
            ("2026-27", "premier_league"),
            ("2025-26", "premier_league"),
        }
        assert len(importer.fixtures()) == 2


def test_acquirer_uses_only_the_permitted_six_league_fallback(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        SourceKind,
        StaticSourceFetcher,
        openfootball_url,
    )
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    premier = league_by_key("premier_league")
    belgian = league_by_key("belgian_pro_league")
    sources = {
        openfootball_url(premier, "2026-27"): OPENFOOTBALL_SAMPLE,
        football_data_url(belgian, "2026-27"): _minimal_csv(),
    }
    fetcher = StaticSourceFetcher(sources)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        report = FixtureHistoryAcquirer(importer, fetcher).acquire(
            IngestionPlan(current_season="2026-27", leagues=(premier, belgian))
        )

        assert len(report.imports) == 2
        assert report.fallback_imports == 1
        assert report.issues == ()
        assert fetcher.calls == [
            football_data_url(premier, "2026-27"),
            openfootball_url(premier, "2026-27"),
            football_data_url(belgian, "2026-27"),
        ]
        assert {capture.allowed_use for capture in importer.source_captures()} == {
            "RESTRICTED_PRIVATE",
            "CC0",
        }

        missing_belgian = FixtureHistoryAcquirer(importer, StaticSourceFetcher({})).acquire(
            IngestionPlan(current_season="2026-27", leagues=(belgian,))
        )
        assert len(missing_belgian.issues) == 1
        assert missing_belgian.issues[0].source_kind is SourceKind.FOOTBALL_DATA
        assert missing_belgian.issues[0].fallback_attempted is False


def test_duplicate_rows_are_counted_without_duplicate_assertions(tmp_path: Path) -> None:
    from matchvet.ingestion import FixtureHistoryImporter, FootballDataCSVParser, SourceCaptureInput
    from matchvet.store import open_store

    lines = _minimal_csv().decode().strip().splitlines()
    content = (lines[0] + "\n" + lines[1] + "\n" + lines[1] + "\n").encode()
    league = league_by_key("premier_league")

    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        result = importer.import_dataset(
            FootballDataCSVParser().parse(content, league=league, season="2026-27"),
            content,
            SourceCaptureInput(
                source_url="https://example.test/E0.csv",
                retrieved_at_utc="2026-09-13T12:00:00+00:00",
                observed_terms="restricted private test capture",
            ),
        )

        assert result.fixtures_imported == 1
        assert result.duplicate_rows == 1
        assert len(importer.fixtures()) == 1


def test_downloader_resumes_private_partial_cache_and_never_calls_unapproved_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.request import Request

    from matchvet import ingestion
    from matchvet.ingestion import ResumableSourceDownloader, SourcePolicyError

    class FakeResponse:
        status = 206

        def __init__(self) -> None:
            self.headers = {"Content-Type": "text/csv; charset=utf-8"}
            self._content = b"def"
            self._offset = 0
            self.closed = False

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            del size
            if self._offset:
                return b""
            self._offset = len(self._content)
            return self._content

        def close(self) -> None:
            self.closed = True

    calls: list[str | None] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        assert isinstance(request, Request)
        assert timeout == 1.0
        calls.append(request.get_header("Range"))
        return FakeResponse()

    monkeypatch.setattr(ingestion, "urlopen", fake_urlopen)
    downloader = ResumableSourceDownloader(
        tmp_path, max_source_bytes=16, network_cap_bytes=16, timeout_seconds=1.0
    )
    cache_key = "resume-key"
    stem = hashlib.sha256(cache_key.encode()).hexdigest()
    part_path = tmp_path / "cache" / "t06" / f"{stem}.part"
    part_path.write_bytes(b"abc")

    downloaded = downloader.fetch(
        "https://www.football-data.co.uk/mmz4281/2627/E0.csv", cache_key=cache_key
    )
    cached = downloader.fetch(
        "https://www.football-data.co.uk/mmz4281/2627/E0.csv", cache_key=cache_key
    )

    assert downloaded.content == b"abcdef"
    assert downloaded.bytes_downloaded == 3
    assert downloaded.content_type == "text/csv"
    assert cached.from_cache is True
    assert calls == ["bytes=3-"]
    assert downloader.network_bytes == 3
    with pytest.raises(SourcePolicyError):
        downloader.fetch("https://example.test/private.csv", cache_key="blocked")


def test_downloader_preserves_http_error_status_for_provider_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from http.client import HTTPMessage
    from urllib.error import HTTPError
    from urllib.request import Request

    from matchvet import ingestion
    from matchvet.ingestion import ResumableSourceDownloader, SourceUnavailable

    url = "https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/en.1.json"

    def fail_with_http_status(request: object, timeout: float) -> None:
        assert isinstance(request, Request)
        assert timeout == 1.0
        raise HTTPError(request.full_url, 503, "Service unavailable", HTTPMessage(), None)

    monkeypatch.setattr(ingestion, "urlopen", fail_with_http_status)
    downloader = ResumableSourceDownloader(tmp_path, timeout_seconds=1.0)

    with pytest.raises(SourceUnavailable) as unavailable:
        downloader.fetch(url, cache_key="schedule")

    assert unavailable.value.http_status == 503


def test_downloader_preserves_response_status_when_body_exceeds_source_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet import ingestion
    from matchvet.ingestion import ResumableSourceDownloader, SourceUnavailable

    class OversizedResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = {"Content-Type": "text/plain"}

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            del size
            return b"too large"

        def close(self) -> None:
            return

    monkeypatch.setattr(ingestion, "urlopen", lambda request, timeout: OversizedResponse())
    downloader = ResumableSourceDownloader(
        tmp_path,
        max_source_bytes=4,
        network_cap_bytes=100,
        timeout_seconds=1.0,
    )

    with pytest.raises(SourceUnavailable) as unavailable:
        downloader.fetch(
            "https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/en.1.json",
            cache_key="oversized",
        )

    assert unavailable.value.http_status == 200


def test_downloader_rejects_a_redirect_to_an_unapproved_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matchvet import ingestion
    from matchvet.ingestion import ResumableSourceDownloader, SourcePolicyError

    class RedirectedResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = {"Content-Type": "text/csv"}

        def getcode(self) -> int:
            return self.status

        def geturl(self) -> str:
            return "https://example.test/rejected.csv"

        def close(self) -> None:
            return None

    monkeypatch.setattr(ingestion, "urlopen", lambda request, timeout: RedirectedResponse())
    downloader = ResumableSourceDownloader(tmp_path)

    with pytest.raises(SourcePolicyError):
        downloader.fetch(
            "https://www.football-data.co.uk/mmz4281/2627/E0.csv", cache_key="redirect"
        )


def test_downloader_selects_routine_or_explicit_historical_network_budget(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import ResumableSourceDownloader
    from matchvet.runs import SETTLED_RESOURCE_BUDGET

    downloader = ResumableSourceDownloader(tmp_path)
    assert downloader.network_cap_bytes == SETTLED_RESOURCE_BUDGET.routine_network_bytes

    downloader.configure_for_plan(historical=True)
    assert downloader.network_cap_bytes == SETTLED_RESOURCE_BUDGET.historical_network_bytes

    downloader.configure_for_plan(historical=False)
    assert downloader.network_cap_bytes == SETTLED_RESOURCE_BUDGET.routine_network_bytes


def test_t06_runner_resumes_from_t04_checkpoint(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        AcquisitionReport,
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        T06AcquisitionRunner,
    )
    from matchvet.runs import GIB, ResourceObservation, RunLifecycleError, WorkInterrupted
    from matchvet.store import open_store

    class InterruptingAcquirer(FixtureHistoryAcquirer):
        def __init__(self, importer: FixtureHistoryImporter, fetcher: StaticSourceFetcher) -> None:
            super().__init__(importer, fetcher)
            self._interrupted = False

        def acquire(self, plan: IngestionPlan) -> AcquisitionReport:
            if not self._interrupted:
                self._interrupted = True
                raise WorkInterrupted("synthetic terminal interruption")
            return super().acquire(plan)

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        use_openfootball_fallback=False,
    )
    fetcher = StaticSourceFetcher({football_data_url(league, "2026-27"): _minimal_csv()})
    observation = ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0)

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        acquirer = InterruptingAcquirer(importer, fetcher)
        runner = T06AcquisitionRunner(store, acquirer)
        with pytest.raises(RunLifecycleError) as interrupted:
            runner.start(plan, observation=observation)

        status = runner.resume(interrupted.value.run_id, plan, observation=observation)

        assert status.state.value == "COMPLETE"
        assert status.completed_work_units == status.total_work_units == 7
        assert status.work_units[1].attempt == 2
        assert runner.last_report is not None
        assert len(importer.source_captures()) == 1


def test_t06_keeps_fixture_coverage_assessment_out_of_durable_artifact(tmp_path: Path) -> None:
    import json

    from matchvet.artifacts import ArtifactStore
    from matchvet.ingestion import (
        FixtureHistoryAcquirer,
        FixtureHistoryImporter,
        IngestionPlan,
        StaticSourceFetcher,
        T06AcquisitionRunner,
        openfootball_url,
    )
    from matchvet.runs import GIB, ResourceObservation
    from matchvet.store import open_store

    private_root = tmp_path / "private"
    private_root.mkdir()
    league = league_by_key("premier_league")
    schedule = b"""{"matches":[
      {"date":"2026-09-25","time":"20:00","team1":"Arsenal",
       "team2":"Coventry","score":{}}
    ]}"""
    fetcher = StaticSourceFetcher(
        {
            football_data_url(league, "2026-27"): _minimal_csv(),
            openfootball_url(league, "2026-27"): schedule,
        }
    )
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(league,),
        matchweek_friday="2026-09-25",
    )

    with open_store(private_root / "matchvet.sqlite3", private_root=private_root) as store:
        importer = FixtureHistoryImporter(store, private_root=private_root)
        runner = T06AcquisitionRunner(store, FixtureHistoryAcquirer(importer, fetcher))
        status = runner.start(
            plan,
            observation=ResourceObservation(0, 5 * GIB, 2 * GIB, 3, False, False, 0),
        )

        assert status.state.value == "COMPLETE"
        assert runner.last_report is not None
        assert runner.last_report.scheduled_fixtures is not None
        artifact = next(
            item
            for item in store.artifact_catalog()
            if item.media_type == "application/vnd.matchvet.t06-acquisition+json"
        )
        payload = json.loads(ArtifactStore(store).read_artifact(artifact.digest))
        assert payload["schema_version"] == 1
        assert "scheduled_fixtures" not in payload
        assert "assessment_digest" not in payload
        assert payload["report_digest"] == runner.last_report.digest

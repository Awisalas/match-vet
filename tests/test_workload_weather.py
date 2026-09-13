from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from matchvet.matchweek import MatchweekFreeze
    from matchvet.store import Store
    from matchvet.workload import CanonicalFixture, FixtureProvenance


def _provenance(
    key: str,
    observed: str,
    *,
    eligibility: str = "CUTOFF_VALID",
) -> FixtureProvenance:
    from matchvet.workload import FixtureProvenance

    return FixtureProvenance(
        source_key=key,
        locator=f"https://{key}.example/fixture",
        observed_at_utc=observed,
        cutoff_eligibility=eligibility,
    )


def _fixture(
    fixture_id: str,
    home: str,
    away: str,
    kickoff: str | None,
    *,
    competition: str = "premier_league",
    competition_type: str = "TARGET_LEAGUE",
    status: str = "COMPLETED",
    observed: str = "2026-09-12T12:00:00+00:00",
    revision_id: str = "r1",
) -> CanonicalFixture:
    from matchvet.workload import CanonicalFixture

    return CanonicalFixture(
        fixture_id=fixture_id,
        home_team_id=home,
        away_team_id=away,
        kickoff_utc=kickoff,
        competition_key=competition,
        competition_name=competition.replace("_", " ").title(),
        competition_type=competition_type,
        season="2026-27",
        status=status,
        revision_id=revision_id,
        provenance=(_provenance(competition, observed),),
    )


def test_workload_uses_canonical_revision_once_and_includes_cross_competition_context() -> None:
    from matchvet.workload import WorkloadCalculator

    cutoff = "2026-09-13T12:00:00+00:00"
    target = _fixture(
        "target",
        "home",
        "away",
        "2026-09-13T20:00:00+00:00",
        status="SCHEDULED",
        revision_id="target-r1",
    )
    fixtures = (
        _fixture("league-1", "home", "other", "2026-09-01T20:00:00+00:00"),
        _fixture(
            "cup-1",
            "home",
            "cup-opponent",
            "2026-09-10T20:00:00+00:00",
            competition="domestic_cup",
            competition_type="DOMESTIC_CUP",
            revision_id="cup-r2",
        ),
        # The same canonical cup fixture is repeated by a second source.
        _fixture(
            "cup-1",
            "home",
            "cup-opponent",
            "2026-09-10T20:00:00+00:00",
            competition="domestic_cup",
            competition_type="DOMESTIC_CUP",
            observed="2026-09-12T13:00:00+00:00",
            revision_id="cup-r2",
        ),
        _fixture(
            "continental-1",
            "away",
            "continental-opponent",
            "2026-09-12T20:00:00+00:00",
            competition="uefa_champions_league",
            competition_type="CONTINENTAL",
        ),
        target,
    )

    result = WorkloadCalculator(fixtures, cutoff_utc=cutoff).calculate(target)

    assert result.state.value == "OBSERVED"
    assert result.home.rest_days == pytest.approx(3.0)
    assert result.away.rest_days == pytest.approx(1.0)
    assert result.home.cross_competition_fixture_ids == ("cup-1",)
    assert result.away.cross_competition_fixture_ids == ("continental-1",)
    assert result.home.schedule_density[7] == 1
    assert result.home.schedule_density[14] == 2
    assert len(result.home.turnaround_periods) == 2
    assert len(result.home.congestion_windows) == 1
    assert result.home.unique_fixture_count_before_target == 2


def test_rescheduled_fixture_is_counted_once_before_cutoff() -> None:
    from matchvet.workload import WorkloadCalculator

    cutoff = "2026-09-13T12:00:00+00:00"
    target = _fixture(
        "target",
        "home",
        "away",
        "2026-09-13T20:00:00+00:00",
        status="SCHEDULED",
        revision_id="target-r1",
    )
    fixtures = (
        _fixture(
            "moved",
            "home",
            "opponent",
            None,
            status="POSTPONED",
            observed="2026-09-08T10:00:00+00:00",
            revision_id="moved-r1",
        ),
        _fixture(
            "moved",
            "home",
            "opponent",
            "2026-09-10T20:00:00+00:00",
            status="COMPLETED",
            observed="2026-09-11T10:00:00+00:00",
            revision_id="moved-r2",
        ),
        _fixture(
            "moved",
            "home",
            "opponent",
            "2026-09-12T20:00:00+00:00",
            status="COMPLETED",
            observed="2026-09-13T13:00:00+00:00",
            revision_id="moved-r3-post-cutoff",
        ),
        target,
    )

    result = WorkloadCalculator(fixtures, cutoff_utc=cutoff).calculate(target)

    assert result.home.latest_completed_fixture_id == "moved"
    assert result.home.rest_days == pytest.approx(3.0)
    assert result.home.unique_fixture_count_before_target == 1
    assert result.home.schedule_density[7] == 1


def test_unknown_schedule_conflict_does_not_become_zero_rest() -> None:
    from matchvet.workload import WorkloadCalculator

    target = _fixture(
        "target",
        "home",
        "away",
        "2026-09-13T20:00:00+00:00",
        status="SCHEDULED",
        revision_id="target-r1",
    )
    conflicting = _fixture(
        "conflict",
        "home",
        "opponent",
        "2026-09-12T20:00:00+00:00",
        status="COMPLETED",
        revision_id="same-revision",
    )
    conflicting_other = _fixture(
        "conflict",
        "other-home",
        "opponent",
        "2026-09-12T20:00:00+00:00",
        status="COMPLETED",
        revision_id="same-revision",
    )

    result = WorkloadCalculator(
        (target, conflicting, conflicting_other), cutoff_utc="2026-09-13T12:00:00+00:00"
    ).calculate(target)

    assert result.home.rest_days is None
    assert result.home.state.value == "UNKNOWN"
    assert "FIXTURE_CONFLICT" in result.home.unknown_reasons


def test_weather_parser_records_attribution_units_and_cutoff_validity() -> None:
    from matchvet.evidence import CutoffEligibility
    from matchvet.weather import (
        VenueLocation,
        WeatherRequest,
        parse_open_meteo_response,
    )

    location = VenueLocation(
        venue_id="venue-1",
        venue_name="Example Stadium",
        latitude=6.5244,
        longitude=3.3792,
        source_key="official-venue",
        locator="https://official.example/venue",
        observed_at_utc="2026-09-01T10:00:00+00:00",
    )
    request = WeatherRequest(
        fixture_id="target",
        target_time_utc="2026-09-13T20:00:00+00:00",
        cutoff_utc="2026-09-13T12:00:00+00:00",
        location=location,
    )
    payload = {
        "latitude": 6.52440,
        "longitude": 3.37920,
        "timezone": "UTC",
        "model": "best_match",
        "forecast_issue_time": "2026-09-13T10:00:00Z",
        "hourly": {
            "time": ["2026-09-13T20:00"],
            "temperature_2m": [27.5],
            "precipitation": [0.2],
            "weather_code": [61],
        },
        "hourly_units": {
            "temperature_2m": "°C",
            "precipitation": "mm",
            "weather_code": "wmo code",
        },
    }

    evidence = parse_open_meteo_response(
        payload,
        request,
        retrieved_at_utc="2026-09-13T10:01:00+00:00",
    )

    assert evidence.state.value == "OBSERVED"
    assert evidence.cutoff_eligibility is CutoffEligibility.CUTOFF_VALID
    assert evidence.forecast_model == "best_match"
    assert evidence.forecast_target_time_utc == "2026-09-13T20:00:00.000000+00:00"
    assert evidence.values["temperature_2m"] == 27.5
    assert evidence.units["precipitation"] == "mm"
    assert "Open-Meteo" in evidence.attribution
    assert evidence.location_provenance["source_key"] == "official-venue"


def test_weather_post_cutoff_wrong_location_outside_interval_and_missing_location_are_unknown() -> (
    None
):
    from matchvet.weather import (
        UNKNOWN,
        VenueLocation,
        WeatherRequest,
        build_weather_evidence,
        parse_open_meteo_response,
    )

    location = VenueLocation(
        venue_id="venue-1",
        venue_name="Example Stadium",
        latitude=6.5244,
        longitude=3.3792,
        source_key="official-venue",
        locator="https://official.example/venue",
        observed_at_utc="2026-09-01T10:00:00+00:00",
    )
    request = WeatherRequest(
        fixture_id="target",
        target_time_utc="2026-09-13T20:00:00+00:00",
        cutoff_utc="2026-09-13T12:00:00+00:00",
        location=location,
    )
    base = {
        "latitude": 6.5244,
        "longitude": 3.3792,
        "model": "best_match",
        "hourly": {"time": ["2026-09-13T20:00"], "temperature_2m": [27.5]},
        "hourly_units": {"temperature_2m": "°C"},
    }
    post = dict(base, forecast_issue_time="2026-09-13T13:00:00Z")
    post_evidence = parse_open_meteo_response(
        post, request, retrieved_at_utc="2026-09-13T13:01:00+00:00"
    )
    assert post_evidence.state is UNKNOWN
    assert post_evidence.unknown_reason == "FORECAST_POST_CUTOFF"

    with pytest.raises(ValueError, match="coordinates"):
        parse_open_meteo_response(
            dict(base, latitude=9.0),
            request,
            retrieved_at_utc="2026-09-13T10:00:00+00:00",
        )

    with pytest.raises(ValueError, match="target interval"):
        parse_open_meteo_response(
            dict(base, hourly={"time": ["2026-09-14T20:00"], "temperature_2m": [27.5]}),
            request,
            retrieved_at_utc="2026-09-13T10:00:00+00:00",
        )

    unknown = build_weather_evidence(
        fixture_id="target",
        target_time_utc="2026-09-13T20:00:00+00:00",
        cutoff_utc="2026-09-13T12:00:00+00:00",
        location=None,
        client=None,
    )
    assert unknown.state is UNKNOWN
    assert unknown.unknown_reason == "VENUE_LOCATION_UNKNOWN"


def _frozen_store(tmp_path: Path) -> tuple[Store, MatchweekFreeze]:
    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.matchweek import freeze_matchweek
    from matchvet.store import open_store

    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HC,AC\n"
        b"E0,18/09/2026,20:00,Arsenal,Coventry,,,,,,,,\n"
        b"E0,19/09/2026,20:00,Leeds,West Ham,,,,,,,,\n"
    )
    store = open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path)
    FixtureHistoryImporter(store, private_root=tmp_path).import_dataset(
        FootballDataCSVParser().parse(
            content,
            league=league_by_key("premier_league"),
            season="2026-27",
        ),
        content,
        SourceCaptureInput(
            source_url="https://example.test/E0.csv",
            retrieved_at_utc="2026-09-17T12:00:00+00:00",
            observed_terms="test fixture history",
        ),
    )
    freeze = freeze_matchweek(
        store,
        "2026-09-18",
        as_of_utc="2026-09-17T12:00:00+00:00",
        created_at_utc="2026-09-17T12:00:00+00:00",
    )
    return store, freeze


def test_workload_schedule_context_is_idempotent_and_transactional(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.workload import WorkloadScheduleRecorder

    store = open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path)
    first = _fixture(
        "cup-1",
        "home",
        "cup-opponent",
        "2026-09-10T20:00:00+00:00",
        competition="domestic_cup",
        competition_type="DOMESTIC_CUP",
        revision_id="cup-r1",
    )
    second = _fixture(
        "continental-1",
        "away",
        "continental-opponent",
        "2026-09-12T20:00:00+00:00",
        competition="uefa_champions_league",
        competition_type="CONTINENTAL",
        revision_id="continental-r1",
    )
    recorder = WorkloadScheduleRecorder(store)
    assert recorder.record(first).from_existing is False
    assert recorder.record(first).from_existing is True

    def fail(index: int) -> None:
        if index == 2:
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        recorder.record_many(
            (second, _fixture("third", "home", "other", "2026-09-11T20:00:00+00:00")),
            failure_hook=fail,
        )
    assert len(recorder.fixtures()) == 1
    store.close()


def test_open_meteo_cache_is_bounded_and_idempotent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from matchvet.weather import OpenMeteoClient, VenueLocation, WeatherRequest

    location = VenueLocation(
        "venue-1",
        "Example Stadium",
        6.5244,
        3.3792,
        "official-venue",
        "https://official.example/venue",
        "2026-09-01T10:00:00+00:00",
    )
    request = WeatherRequest(
        "target",
        "2026-09-13T20:00:00+00:00",
        "2026-09-13T12:00:00+00:00",
        location,
    )
    body = b'{"latitude":6.5244,"longitude":3.3792}'

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}

        def __init__(self) -> None:
            self.reads = 0

        def getcode(self) -> int:
            return 200

        def read(self, _size: int) -> bytes:
            if self.reads:
                return b""
            self.reads += 1
            return body

        def close(self) -> None:
            return None

    responses: list[Response] = []

    def fake_urlopen(*_args: object, **_kwargs: object) -> Response:
        response = Response()
        responses.append(response)
        return response

    monkeypatch.setattr("matchvet.weather.urlopen", fake_urlopen)
    client = OpenMeteoClient(tmp_path, cache_ttl_seconds=3600)
    first = client.fetch(request)
    second = client.fetch(request)
    assert first.from_cache is False
    assert second.from_cache is True
    assert len(responses) == 1
    assert client.network_bytes == len(body)


def test_t08_runner_resumes_after_interruption_and_keeps_weather_observed(
    tmp_path: Path,
) -> None:
    from matchvet.runs import ResourceObservation, RunLifecycleError
    from matchvet.t08 import T08EvidenceRunner, T08Plan
    from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

    store, freeze = _frozen_store(tmp_path)
    locations = {
        item.subject_id: VenueLocation(
            item.subject_id,
            "Verified Stadium",
            6.5244,
            3.3792,
            "official-venue",
            "https://official.example/venue",
            "2026-09-01T10:00:00+00:00",
        )
        for item in freeze.target_matches
    }
    responses: dict[str, dict[str, object]] = {}
    for item in freeze.target_matches:
        request = WeatherRequest(
            item.subject_id,
            item.original_kickoff_utc or "",
            freeze.cutoff.cutoff_utc,
            locations[item.subject_id],
        )
        responses[request.url] = {
            "latitude": 6.5244,
            "longitude": 3.3792,
            "model": "best_match",
            "forecast_issue_time": "2026-09-18T10:00:00Z",
            "hourly": {
                "time": [request.interval_start_utc],
                "temperature_2m": [27],
            },
            "hourly_units": {"temperature_2m": "°C"},
        }
    client = StaticWeatherClient(
        responses,
        retrieved_at_utc="2026-09-18T12:00:00+00:00",
    )
    observation = ResourceObservation(
        managed_storage_bytes=0,
        free_space_bytes=4 * 1024**3,
        available_memory_bytes=2 * 1024**3,
        available_cpus=4,
        memory_pressure=False,
        thermal_pressure=False,
        active_coordinators=0,
    )
    calls = 0

    def interrupt_on_second(index: int, _membership: object) -> None:
        nonlocal calls
        calls += 1
        if index == 2:
            raise KeyboardInterrupt

    runner = T08EvidenceRunner(store)
    with pytest.raises(RunLifecycleError) as error:
        runner.start(
            T08Plan("2026-09-18"),
            observation=observation,
            weather_client=client,
            locations=locations,
            failure_hook=interrupt_on_second,
        )
    assert error.value.run_id
    assert calls == 2
    status = runner.resume(
        error.value.run_id,
        T08Plan("2026-09-18"),
        observation=observation,
        weather_client=client,
        locations=locations,
    )
    assert status.state.value == "COMPLETE"
    connection = store._connection_for_repository()
    assert connection.execute("SELECT count(*) FROM workload_evidence").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM weather_evidence").fetchone()[0] == 2
    assert all(
        row[0] == "OBSERVED"
        for row in connection.execute("SELECT evidence_state FROM weather_evidence")
    )
    store.close()

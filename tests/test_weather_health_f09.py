from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import pytest
from test_workload_weather import _frozen_store

from matchvet.provider_health import (
    CapabilityAvailabilityState,
    CapabilityCoverageEvidenceReference,
    CoverageState,
    FailureState,
    FreshnessState,
    StructuralValidityState,
    UsePermissionState,
)
from matchvet.provider_health_repository import ProviderHealthRepository
from matchvet.t08 import T08EvidenceBuilder
from matchvet.weather import StaticWeatherClient, VenueLocation, WeatherRequest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from matchvet.weather import WeatherEvidence, WeatherHTTPResponse


def test_t08_records_only_actual_open_meteo_weather_health_before_publication(
    tmp_path: Path,
) -> None:
    store, freeze = _frozen_store(tmp_path)
    try:
        target = freeze.target_matches[0]
        location = VenueLocation(
            "verified-venue",
            "Verified Stadium",
            6.5244,
            3.3792,
            "official-venue",
            "https://official.example/venue",
            "2026-09-01T10:00:00+00:00",
        )
        request = WeatherRequest(
            target.subject_id,
            target.original_kickoff_utc or "",
            freeze.cutoff.cutoff_utc,
            location,
        )
        payload: dict[str, object] = {
            "latitude": 6.5244,
            "longitude": 3.3792,
            "forecast_issue_time": "2026-09-18T10:00:00Z",
            "hourly": {
                "time": [request.interval_start_utc],
                **{variable: [27] for variable in request.variables},
            },
        }
        client = StaticWeatherClient(
            {request.url: payload}, retrieved_at_utc="2026-09-18T12:00:00+00:00"
        )
        result = T08EvidenceBuilder(
            store,
            weather_client=client,
            locations={target.subject_id: location},
        ).build(freeze)
        (record,) = result.provider_health_records
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert record.provider.provider_id == "open-meteo"
        assert record.capability.capability_id == "weather-forecast"
        assert record.requested_scope.fixture_scope is None
        assert record.use_permission.state is UsePermissionState.PERMITTED
        assert record.capability_availability.state is CapabilityAvailabilityState.AVAILABLE
        assert record.structural_validity.state is StructuralValidityState.VALID
        assert record.coverage.state is CoverageState.COMPLETE
        # T08 cutoff eligibility does not establish an age-based freshness policy.
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert record.failure.state is FailureState.NO_FAILURE_OBSERVED
        weather = next(
            item for item in result.evidence.weather if item.fixture_id == target.subject_id
        )
        assert weather.state.value == "OBSERVED"
        assert len(result.provider_health_records) == 1
    finally:
        store.close()


def test_weather_fetch_permission_failure_remains_distinct_from_unavailability(
    tmp_path: Path,
) -> None:
    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import (
        WeatherEvidenceBuilder,
        WeatherPolicyError,
        WeatherTarget,
    )

    class DeniedClient:
        def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
            del request, refresh
            raise WeatherPolicyError("Non-commercial forecast access denied")

    request = _request()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            DeniedClient(),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is UsePermissionState.NOT_PERMITTED
        assert record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
        assert record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert record.coverage.state is CoverageState.UNKNOWN
        assert record.failure.state is FailureState.FAILED
        assert tuple(code.value for code in record.failure.reason_codes) == ("PERMISSION_FAILED",)
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert result.evidence[0].state.value == "UNKNOWN"


def test_unavailable_weather_keeps_unobserved_dimensions_unknown(tmp_path: Path) -> None:
    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import WeatherEvidenceBuilder, WeatherTarget

    request = _request()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient({}),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is UsePermissionState.PERMITTED
        assert record.reachability.state.value == "UNKNOWN"
        assert record.capability_availability.state is CapabilityAvailabilityState.UNAVAILABLE
        assert record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert record.coverage.state is CoverageState.UNKNOWN
        assert record.failure.state is FailureState.FAILED
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert result.evidence[0].state.value == "UNKNOWN"


def test_malformed_response_does_not_claim_weather_capability_or_coverage(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import DEFAULT_WEATHER_VARIABLES, WeatherEvidenceBuilder, WeatherTarget

    request = replace(_request(), variables=DEFAULT_WEATHER_VARIABLES)
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient({request.url: b"{"}),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is UsePermissionState.PERMITTED
        assert record.reachability.state.value == "REACHABLE"
        assert record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
        assert record.structural_validity.state is StructuralValidityState.INVALID
        assert record.coverage.state is CoverageState.UNKNOWN
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert record.failure.state is FailureState.FAILED
        assert tuple(code.value for code in record.failure.reason_codes) == ("MALFORMED_RESPONSE",)
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert result.evidence[0].unknown_reason == "MALFORMED_RESPONSE"


def test_valid_partial_weather_does_not_claim_complete_requested_variable_coverage(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import DEFAULT_WEATHER_VARIABLES, WeatherEvidenceBuilder, WeatherTarget

    request = replace(_request(), variables=DEFAULT_WEATHER_VARIABLES)
    payload: dict[str, object] = {
        "latitude": request.location.latitude,
        "longitude": request.location.longitude,
        "forecast_issue_time": "2026-09-18T10:00:00Z",
        "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
    }
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient(
                {request.url: payload}, retrieved_at_utc="2026-09-18T12:00:00+00:00"
            ),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.capability_availability.state is CapabilityAvailabilityState.AVAILABLE
        assert record.structural_validity.state is StructuralValidityState.VALID
        assert record.coverage.state is CoverageState.PARTIAL
        assert record.coverage.witness is not None
        coverage = record.coverage.witness.evidence[0]
        assert isinstance(coverage, CapabilityCoverageEvidenceReference)
        assert coverage.covered_extent_ids == ("temperature_2m",)
        assert coverage.known_gap_ids == (
            "precipitation",
            "relative_humidity_2m",
            "weather_code",
            "wind_speed_10m",
        )
        assert ProviderHealthRepository(store).get(record.digest) == record


@pytest.mark.parametrize(
    ("status", "permission", "availability"),
    [
        (429, UsePermissionState.PERMITTED, CapabilityAvailabilityState.UNAVAILABLE),
        (503, UsePermissionState.PERMITTED, CapabilityAvailabilityState.UNAVAILABLE),
        (401, UsePermissionState.NOT_PERMITTED, CapabilityAvailabilityState.UNKNOWN),
        (403, UsePermissionState.NOT_PERMITTED, CapabilityAvailabilityState.UNKNOWN),
    ],
)
def test_http_denial_and_service_unavailability_remain_distinct(
    tmp_path: Path,
    status: int,
    permission: UsePermissionState,
    availability: CapabilityAvailabilityState,
) -> None:
    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import WeatherEvidenceBuilder, WeatherHTTPResponse, WeatherTarget

    class ResponseClient:
        def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
            del refresh
            return WeatherHTTPResponse(
                b"{}", "2026-09-18T12:00:00+00:00", response_status=status, url=request.url
            )

    request = _request()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            ResponseClient(),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is permission
        assert record.reachability.state.value == "REACHABLE"
        assert record.capability_availability.state is availability
        assert record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert record.coverage.state is CoverageState.UNKNOWN
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert record.failure.state is FailureState.FAILED
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert result.evidence[0].state.value == "UNKNOWN"


def test_real_open_meteo_client_keeps_http_permission_denial(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from email.message import Message
    from urllib.error import HTTPError
    from urllib.request import Request

    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import OpenMeteoClient, WeatherEvidenceBuilder, WeatherTarget

    def denied_urlopen(request: Request, *, timeout: float) -> NoReturn:
        del timeout
        raise HTTPError(request.full_url, 403, "Access denied", Message(), None)

    monkeypatch.setattr("matchvet.weather.urlopen", denied_urlopen)
    request = _request()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            OpenMeteoClient(tmp_path),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is UsePermissionState.NOT_PERMITTED
        assert tuple(code.value for code in record.failure.reason_codes) == ("PERMISSION_FAILED",)
        assert ProviderHealthRepository(store).get(record.digest) == record


def test_post_cutoff_forecast_is_an_explicit_health_failure(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import DEFAULT_WEATHER_VARIABLES, WeatherEvidenceBuilder, WeatherTarget

    request = replace(_request(), variables=DEFAULT_WEATHER_VARIABLES)
    payload: dict[str, object] = {
        "latitude": request.location.latitude,
        "longitude": request.location.longitude,
        "forecast_issue_time": "2026-09-18T14:00:00Z",
        "hourly": {
            "time": [request.interval_start_utc],
            **{variable: [27] for variable in request.variables},
        },
    }
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient(
                {request.url: payload}, retrieved_at_utc="2026-09-18T14:00:00+00:00"
            ),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert result.evidence[0].unknown_reason == "FORECAST_POST_CUTOFF"
        assert record.failure.state is FailureState.FAILED
        assert tuple(code.value for code in record.failure.reason_codes) == (
            "FORECAST_POST_CUTOFF",
        )
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert ProviderHealthRepository(store).get(record.digest) == record


def _parsed_weather() -> tuple[WeatherRequest, WeatherHTTPResponse, WeatherEvidence]:
    import json

    from test_provider_health_f09 import _request

    from matchvet.weather import WeatherHTTPResponse, parse_open_meteo_response

    request = _request()
    content = json.dumps(
        {
            "latitude": request.location.latitude,
            "longitude": request.location.longitude,
            "forecast_issue_time": "2026-09-18T10:00:00Z",
            "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
        }
    ).encode()
    response = WeatherHTTPResponse(content, "2026-09-18T12:00:00+00:00", url=request.url)
    forecast = parse_open_meteo_response(
        content, request, retrieved_at_utc=response.retrieved_at_utc
    )
    return request, response, forecast


@pytest.mark.parametrize("mismatch", ["query_url", "fixture", "response_bytes"])
def test_health_observation_refuses_forecast_or_response_from_another_query(
    tmp_path: Path,
    mismatch: str,
) -> None:
    from dataclasses import replace

    from matchvet.store import open_store
    from matchvet.weather_provider_health import OpenMeteoHealthRecorder

    request, response, forecast = _parsed_weather()
    if mismatch == "query_url":
        response = replace(response, url=request.url + "&models=other-model")
    elif mismatch == "fixture":
        forecast = replace(forecast, fixture_id="other-match")
    else:
        response = replace(response, content=b"{}")
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = OpenMeteoHealthRecorder(ProviderHealthRepository(store))
        with pytest.raises(ValueError, match=r"scope|response"):
            recorder.record(request, response, forecast)
        assert recorder.records == ()


def test_health_persistence_does_not_publish_weather_evidence(tmp_path: Path) -> None:
    from matchvet.store import open_store
    from matchvet.weather import WeatherEvidenceRecorder
    from matchvet.weather_provider_health import OpenMeteoHealthRecorder

    request, response, forecast = _parsed_weather()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        recorder = OpenMeteoHealthRecorder(ProviderHealthRepository(store))
        record = recorder.record(request, response, forecast)
        assert ProviderHealthRepository(store).get(record.digest) == record
        assert WeatherEvidenceRecorder(store).records("health-only-observation") == ()


def test_health_persistence_failure_prevents_t08_weather_publication(tmp_path: Path) -> None:
    from matchvet.provider_health_repository import ProviderHealthIntegrityError
    from matchvet.weather import WeatherEvidenceRecorder

    store, freeze = _frozen_store(tmp_path)
    try:
        target = sorted(freeze.target_matches, key=lambda item: item.subject_id)[0]
        location = VenueLocation(
            "test-venue",
            "Test Venue",
            6.5244,
            3.3792,
            "official-venue",
            "https://official.example/venue",
            "2026-09-01T10:00:00+00:00",
        )
        request = WeatherRequest(
            target.subject_id, target.original_kickoff_utc or "", freeze.cutoff.cutoff_utc, location
        )
        payload: dict[str, object] = {
            "latitude": 6.5244,
            "longitude": 3.3792,
            "forecast_issue_time": "2026-09-18T10:00:00Z",
            "hourly": {"time": [request.interval_start_utc], "temperature_2m": [27]},
        }
        client = StaticWeatherClient(
            {request.url: payload}, retrieved_at_utc="2026-09-18T12:00:00+00:00"
        )
        # Corrupt the health write boundary so every real insert fails.
        with store.transaction() as transaction:
            transaction.execute("""
                CREATE TRIGGER injected_contextual_health_failure
                BEFORE INSERT ON contextual_provider_health_records
                BEGIN SELECT RAISE(ABORT, 'injected F09 write failure'); END
            """)
        with pytest.raises(ProviderHealthIntegrityError):
            T08EvidenceBuilder(
                store, weather_client=client, locations={target.subject_id: location}
            ).build(freeze)
        assert WeatherEvidenceRecorder(store).records(freeze.cutoff.matchweek_id) == ()
    finally:
        store.close()


def test_raw_http_permission_error_at_weather_client_seam_is_retained(tmp_path: Path) -> None:
    from email.message import Message
    from urllib.error import HTTPError

    from test_provider_health_f09 import _request

    from matchvet.store import open_store
    from matchvet.weather import WeatherEvidenceBuilder, WeatherTarget

    class DeniedClient:
        def fetch(self, request: WeatherRequest, *, refresh: bool = False) -> WeatherHTTPResponse:
            del refresh
            raise HTTPError(request.url, 403, "Access denied", Message(), None)

    request = _request()
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            DeniedClient(),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert record.use_permission.state is UsePermissionState.NOT_PERMITTED
        assert record.reachability.state.value == "REACHABLE"
        assert record.capability_availability.state is CapabilityAvailabilityState.UNKNOWN
        assert tuple(code.value for code in record.failure.reason_codes) == ("PERMISSION_FAILED",)
        assert ProviderHealthRepository(store).get(record.digest) == record


def test_uncovered_forecast_interval_is_distinct_from_malformed_response(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_provider_health_f09 import _request

    from matchvet.provider_health import CapabilityCoverageEvidenceReference
    from matchvet.store import open_store
    from matchvet.weather import DEFAULT_WEATHER_VARIABLES, WeatherEvidenceBuilder, WeatherTarget

    request = replace(_request(), variables=DEFAULT_WEATHER_VARIABLES)
    payload: dict[str, object] = {
        "latitude": request.location.latitude,
        "longitude": request.location.longitude,
        "forecast_issue_time": "2026-09-18T10:00:00Z",
        "hourly": {
            "time": ["2026-09-17T19:00:00Z"],
            **{variable: [27] for variable in request.variables},
        },
    }
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient(
                {request.url: payload}, retrieved_at_utc="2026-09-18T12:00:00+00:00"
            ),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert result.evidence[0].unknown_reason == "FORECAST_OUTSIDE_TARGET_INTERVAL"
        assert record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert record.coverage.state is CoverageState.PARTIAL
        assert record.coverage.witness is not None
        coverage = record.coverage.witness.evidence[0]
        assert isinstance(coverage, CapabilityCoverageEvidenceReference)
        assert coverage.covered_extent_ids == ()
        assert coverage.known_gap_ids == ("target_interval",)
        assert tuple(code.value for code in record.failure.reason_codes) == (
            "FORECAST_OUTSIDE_TARGET_INTERVAL",
        )
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert ProviderHealthRepository(store).get(record.digest) == record


def test_absent_requested_variables_are_distinct_from_malformed_response(tmp_path: Path) -> None:
    from dataclasses import replace

    from test_provider_health_f09 import _request

    from matchvet.provider_health import CapabilityCoverageEvidenceReference
    from matchvet.store import open_store
    from matchvet.weather import DEFAULT_WEATHER_VARIABLES, WeatherEvidenceBuilder, WeatherTarget

    request = replace(_request(), variables=DEFAULT_WEATHER_VARIABLES)
    payload: dict[str, object] = {
        "latitude": request.location.latitude,
        "longitude": request.location.longitude,
        "forecast_issue_time": "2026-09-18T10:00:00Z",
        "hourly": {
            "time": [request.target_time_utc],
            "unrequested_variable": [27],
        },
    }
    with open_store(tmp_path / "matchvet.sqlite3", private_root=tmp_path) as store:
        result = WeatherEvidenceBuilder(
            StaticWeatherClient(
                {request.url: payload}, retrieved_at_utc="2026-09-18T12:00:00+00:00"
            ),
            provider_health_repository=ProviderHealthRepository(store),
        ).build(
            (
                WeatherTarget(
                    request.fixture_id,
                    request.target_time_utc,
                    request.cutoff_utc,
                    request.location,
                ),
            )
        )
        (record,) = result.provider_health_records
        assert result.evidence[0].unknown_reason == "MALFORMED_RESPONSE"
        assert record.structural_validity.state is StructuralValidityState.UNKNOWN
        assert record.coverage.state is CoverageState.PARTIAL
        assert record.coverage.witness is not None
        coverage = record.coverage.witness.evidence[0]
        assert isinstance(coverage, CapabilityCoverageEvidenceReference)
        assert coverage.covered_extent_ids == ()
        assert coverage.known_gap_ids == tuple(sorted(request.variables))
        assert tuple(code.value for code in record.failure.reason_codes) == (
            "FORECAST_VARIABLES_UNAVAILABLE",
        )
        assert record.freshness.state is FreshnessState.UNKNOWN
        assert ProviderHealthRepository(store).get(record.digest) == record
